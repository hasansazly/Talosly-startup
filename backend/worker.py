import asyncio
import signal
import time

from backend import database as db
from backend.config import settings
from backend.services.logger import logger
from backend.services.rpc import EthereumRPCClient
from backend.services.scorer import TransactionScorer
from backend.services.telegram import TelegramService


class TaloslyWorker:
    def __init__(self) -> None:
        self.rpc = EthereumRPCClient()
        self.scorer = TransactionScorer()
        self.telegram = TelegramService()
        self.running = True
        self.last_seen_blocks: dict[str, int] = {}
        self.rpc_backoff_seconds = 0

    def stop(self, *_args) -> None:
        self.running = False

    async def run(self) -> None:
        await db.init_db()
        logger.info(
            "worker.start",
            version="0.2.0",
            environment=settings.app_env,
            poll_interval=settings.poll_interval_seconds,
            risk_threshold=settings.risk_alert_threshold,
            database="PostgreSQL",
        )
        while self.running:
            started = time.perf_counter()
            protocols_checked = 0
            transactions_found = 0
            alerts_fired = 0
            logger.info("worker.poll.start")
            protocols = await db.get_all_protocols(active_only=True)
            for protocol in protocols:
                protocols_checked += 1
                try:
                    found, alerts = await self._poll_protocol(protocol)
                    transactions_found += found
                    alerts_fired += alerts
                    self.rpc_backoff_seconds = 0
                except Exception as exc:
                    self.rpc_backoff_seconds = 30 if self.rpc_backoff_seconds == 0 else min(self.rpc_backoff_seconds * 2, 120)
                    logger.error("worker.protocol.error", protocol=protocol.get("name"), error=str(exc), backoff_seconds=self.rpc_backoff_seconds)
                    await asyncio.sleep(self.rpc_backoff_seconds)
            logger.info(
                "worker.poll.complete",
                protocols_checked=protocols_checked,
                transactions_found=transactions_found,
                alerts_fired=alerts_fired,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            await asyncio.sleep(max(settings.poll_interval_seconds, 10))
        await self.shutdown("stop requested")

    async def shutdown(self, reason: str) -> None:
        logger.info("worker.shutdown", reason=reason)
        await db.close_db()
        logger.info("worker.stopped")

    async def _poll_protocol(self, protocol: dict) -> tuple[int, int]:
        address = protocol["address"]
        latest_block = await self.rpc.get_latest_block_number()
        last_seen = self.last_seen_blocks.get(address) or protocol.get("last_seen_block") or latest_block - 10
        from_block = int(last_seen) + 1
        to_block = min(latest_block, from_block + 4)
        if from_block > to_block:
            return 0, 0
        raw_txs = await self.rpc.get_transactions_for_address(address, from_block, to_block)
        transactions_found = 0
        alerts_fired = 0
        for raw_tx in raw_txs:
            parsed = self.rpc.parse_transaction(raw_tx)
            tx_id, is_new = await db.upsert_transaction(protocol["id"], parsed)
            if not is_new:
                continue
            transactions_found += 1
            logger.info("transaction.fetched", protocol=protocol["name"], tx_hash=parsed["tx_hash"][:18], block_number=parsed.get("block_number"))
            score_result = await self.scorer.score_transaction(parsed, protocol)
            await db.update_transaction_score(tx_id, score_result.risk_score, score_result.risk_summary)
            logger.info("transaction.scored", protocol=protocol["name"], tx_hash=parsed["tx_hash"][:18], risk_score=score_result.risk_score)
            if score_result.risk_score >= settings.risk_alert_threshold:
                alert_id = await db.insert_alert(tx_id, score_result.risk_score, score_result.risk_summary)
                alerts_fired += 1
                logger.info("alert.created", alert_id=alert_id, risk_score=score_result.risk_score, tx_hash=parsed["tx_hash"][:18])
                sent = await self.telegram.send_alert(protocol, parsed, score_result)
                if sent:
                    await db.mark_telegram_sent(alert_id)
                    logger.info("alert.telegram.sent", alert_id=alert_id)
                else:
                    logger.warning("alert.telegram.failed", alert_id=alert_id)
        self.last_seen_blocks[address] = to_block
        await db.update_protocol_last_seen(protocol["id"], to_block)
        return transactions_found, alerts_fired


async def main() -> None:
    worker = TaloslyWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
