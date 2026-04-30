import asyncio
import logging
import signal

from backend import database as db
from backend.config import settings
from backend.services.rpc import EthereumRPCClient
from backend.services.scorer import TransactionScorer
from backend.services.telegram import TelegramService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class TaloslyWorker:
    def __init__(self) -> None:
        self.rpc = EthereumRPCClient()
        self.scorer = TransactionScorer()
        self.telegram = TelegramService()
        self.running = True
        self.last_seen_blocks: dict[str, int] = {}

    def stop(self, *_args) -> None:
        self.running = False

    async def run(self) -> None:
        await db.init_db()
        logger.info("Talosly worker starting...")
        while self.running:
            protocols = await db.get_all_protocols(active_only=True)
            for protocol in protocols:
                try:
                    await self._poll_protocol(protocol)
                except Exception as exc:
                    logger.exception("Talosly worker error for %s: %s", protocol.get("name"), exc)
            await asyncio.sleep(max(settings.poll_interval_seconds, 10))
        logger.info("Talosly worker stopped.")

    async def _poll_protocol(self, protocol: dict) -> None:
        address = protocol["address"]
        latest_block = await self.rpc.get_latest_block_number()
        last_seen = self.last_seen_blocks.get(address) or protocol.get("last_seen_block") or latest_block - 10
        from_block = int(last_seen) + 1
        to_block = min(latest_block, from_block + 4)
        if from_block > to_block:
            return
        raw_txs = await self.rpc.get_transactions_for_address(address, from_block, to_block)
        for raw_tx in raw_txs:
            parsed = self.rpc.parse_transaction(raw_tx)
            tx_id, is_new = await db.upsert_transaction(protocol["id"], parsed)
            if not is_new:
                continue
            logger.info("Talosly: New tx %s... for %s", parsed["tx_hash"][:10], protocol["name"])
            score_result = await self.scorer.score_transaction(parsed, protocol)
            await db.update_transaction_score(tx_id, score_result.risk_score, score_result.risk_summary)
            if score_result.risk_score >= settings.risk_alert_threshold:
                alert_id = await db.insert_alert(tx_id, score_result.risk_score, score_result.risk_summary)
                sent = await self.telegram.send_alert(protocol, parsed, score_result)
                if sent:
                    await db.mark_telegram_sent(alert_id)
                logger.info("Talosly: ALERT fired — score %s for %s...", score_result.risk_score, parsed["tx_hash"][:10])
        self.last_seen_blocks[address] = to_block
        await db.update_protocol_last_seen(protocol["id"], to_block)


async def main() -> None:
    worker = TaloslyWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop)
    await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Talosly worker stopped.")
