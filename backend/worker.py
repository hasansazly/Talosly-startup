import asyncio
import contextlib
import datetime
import signal
import time

from backend import database as db
from backend.config import settings
from backend.mempool import MempoolSubscriber
from backend.services.logger import logger
from backend.services.rpc import EthereumRPCClient, EthereumRPCRateLimitError
from backend.services.scorer import TransactionScorer
from backend.services.telegram import TelegramService
from scoring.features import Layer2FeatureEngineering
from scoring.filters import PreFilterManager
from scoring.layer3 import Layer3MLEnsemble
from scoring.layer4 import get_oracle


class TaloslyWorker:
    def __init__(self) -> None:
        self.rpc = EthereumRPCClient()
        self.scorer = TransactionScorer()
        self.telegram = TelegramService()
        self.pre_filter = PreFilterManager()
        self.layer2 = Layer2FeatureEngineering()
        self.layer3 = Layer3MLEnsemble()
        self.layer4 = get_oracle()
        self.running = True
        self.last_seen_blocks: dict[str, int] = {}
        self.rpc_backoff_seconds = 0
        self.mempool_subscriber: MempoolSubscriber | None = None
        self.mempool_task: asyncio.Task | None = None
        self.mempool_protocols: dict[str, dict] = {}

    def stop(self, *_args) -> None:
        self.running = False
        if self.mempool_subscriber:
            self.mempool_subscriber.stop()

    async def run(self) -> None:
        await db.init_db()
        logger.info(
            "worker.start",
            version="0.2.0",
            environment=settings.app_env,
            poll_interval=settings.poll_interval_seconds,
            rpc_polling=settings.enable_rpc_polling,
            risk_threshold=await self._risk_threshold(),
            database="PostgreSQL",
        )
        try:
            if settings.enable_mempool_subscriber and settings.ethereum_ws_url:
                await asyncio.gather(
                    self._poll_loop(),
                    self._run_mempool_subscriber(),
                    return_exceptions=True,
                )
            else:
                if settings.enable_mempool_subscriber:
                    logger.warning("mempool.disabled", reason="missing websocket url")
                await self._poll_loop()
        finally:
            await self.shutdown("stop requested")

    async def _poll_loop(self) -> None:
        while self.running:
            if not settings.enable_rpc_polling:
                logger.info("worker.poll.disabled", reason="rpc polling disabled")
                await asyncio.sleep(max(settings.poll_interval_seconds, 60))
                continue

            started = time.perf_counter()
            protocols_checked = 0
            transactions_found = 0
            alerts_fired = 0
            logger.info("worker.poll.start")
            protocols = await db.get_all_protocols(active_only=True)
            try:
                latest_block = await self.rpc.get_latest_block_number()
            except EthereumRPCRateLimitError as exc:
                retry_after_seconds = getattr(exc, "retry_after_seconds", None) or 0
                self.rpc_backoff_seconds = int(
                    max(settings.ethereum_rpc_rate_limit_backoff_seconds, retry_after_seconds)
                )
                logger.error("worker.rpc.rate_limited", error=str(exc), backoff_seconds=self.rpc_backoff_seconds)
                await asyncio.sleep(self.rpc_backoff_seconds)
                continue
            except Exception as exc:
                self.rpc_backoff_seconds = (
                    30
                    if self.rpc_backoff_seconds == 0
                    else min(self.rpc_backoff_seconds * 2, settings.ethereum_rpc_rate_limit_backoff_seconds)
                )
                logger.error("worker.rpc.error", error=str(exc), backoff_seconds=self.rpc_backoff_seconds)
                await asyncio.sleep(self.rpc_backoff_seconds)
                continue
            block_transactions_cache: dict[int, list[dict]] = {}
            for protocol in protocols:
                protocols_checked += 1
                try:
                    found, alerts = await self._poll_protocol(protocol, latest_block, block_transactions_cache)
                    transactions_found += found
                    alerts_fired += alerts
                    self.rpc_backoff_seconds = 0
                except Exception as exc:
                    self.rpc_backoff_seconds = (
                        30
                        if self.rpc_backoff_seconds == 0
                        else min(self.rpc_backoff_seconds * 2, settings.ethereum_rpc_rate_limit_backoff_seconds)
                    )
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

    async def shutdown(self, reason: str) -> None:
        logger.info("worker.shutdown", reason=reason)
        if self.mempool_subscriber:
            self.mempool_subscriber.stop()
        if self.mempool_task:
            self.mempool_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.mempool_task
        await db.close_db()
        logger.info("worker.stopped")

    async def _run_mempool_subscriber(self) -> None:
        protocols = await db.get_all_protocols(active_only=True)
        self.mempool_protocols = {
            protocol["address"].lower(): protocol
            for protocol in protocols
            if protocol.get("address")
        }
        if not self.mempool_protocols:
            logger.warning("mempool.disabled", reason="no active protocol addresses")
            return
        self.mempool_subscriber = MempoolSubscriber(
            settings.ethereum_ws_url,
            tx_handler_callback=self._process_mempool_transaction,
            to_addresses=list(self.mempool_protocols),
        )
        self.mempool_task = asyncio.current_task()
        logger.info("mempool.started", watched_protocols=len(self.mempool_protocols))
        await self.mempool_subscriber.start()

    async def _process_mempool_transaction(self, tx: dict) -> None:
        tx_hash = tx.get("hash")
        to_address = (tx.get("to") or "").lower()
        protocol = self.mempool_protocols.get(to_address)
        if not tx_hash or not protocol:
            return

        tx_data = {
            "to": tx.get("to"),
            "from": tx.get("from"),
            "input": tx.get("input", "0x"),
            "value": tx.get("value", 0),
        }
        should_escalate, filter_reason = self.pre_filter.should_evaluate(tx_data)
        if not should_escalate:
            logger.info(
                "mempool.transaction.prefilter.pass",
                tx_hash=tx_hash[:18],
                reason=filter_reason,
            )
            return
        layer2_features = self.layer2.process(tx).to_dict()
        layer3_result = self.layer3.score(tx_hash, layer2_features).to_dict()
        if not layer3_result["escalate_to_llm"]:
            logger.info(
                "mempool.transaction.layer3.skip",
                protocol=protocol.get("name"),
                tx_hash=tx_hash[:18],
                layer3_result=layer3_result,
            )
            return

        layer4_result = await self.layer4.analyze(tx_hash, layer2_features, layer3_result)
        if not layer4_result.should_alert:
            logger.info(
                "mempool.transaction.layer4.skip",
                protocol=protocol.get("name"),
                tx_hash=tx_hash[:18],
                layer4_result=layer4_result.to_dict(),
            )
            return

        logger.info(
            "mempool.transaction.matched",
            protocol=protocol.get("name"),
            tx_hash=tx_hash[:18],
            to_address=to_address,
            layer2_features=layer2_features,
            layer3_result=layer3_result,
            layer4_result=layer4_result.to_dict(),
        )

    async def _risk_threshold(self) -> int:
        return int(await db.get_app_setting("risk_alert_threshold", settings.risk_alert_threshold))

    async def _poll_protocol(self, protocol: dict, latest_block: int, block_transactions_cache: dict[int, list[dict]]) -> tuple[int, int]:
        address = protocol["address"]
        initial_lookback = max(settings.ethereum_initial_lookback_blocks, 0)
        last_seen = self.last_seen_blocks.get(address) or protocol.get("last_seen_block") or latest_block - initial_lookback
        from_block = int(last_seen) + 1
        blocks_per_poll = max(settings.ethereum_blocks_per_poll, 1)
        to_block = min(latest_block, from_block + blocks_per_poll - 1)
        if from_block > to_block:
            return 0, 0
        raw_txs = await self.rpc.get_transactions_for_address(address, from_block, to_block, block_transactions_cache)
        transactions_found = 0
        alerts_fired = 0
        pre_screened_this_loop = 0
        openai_scored_this_loop = 0
        for raw_tx in raw_txs:
            parsed = self.rpc.parse_transaction(raw_tx)
            parsed["input_data"] = raw_tx.get("input") or parsed.get("input_data") or ""
            tx_id, is_new = await db.upsert_transaction(protocol["id"], parsed)
            if not is_new:
                continue
            transactions_found += 1

            tx_data = {
                "to": parsed.get("to_address"),
                "from": parsed.get("from_address"),
                "input": parsed.get("input_data", "0x"),
                "value": parsed.get("value_eth", 0),
            }
            should_escalate, filter_reason = self.pre_filter.should_evaluate(tx_data)
            if not should_escalate:
                logger.info(
                    "transaction.prefilter.pass",
                    protocol=protocol["name"],
                    tx_hash=parsed["tx_hash"][:18],
                    reason=filter_reason,
                )
                continue
            parsed["layer2_features"] = self.layer2.process(parsed).to_dict()
            parsed["layer3_result"] = self.layer3.score(parsed["tx_hash"], parsed["layer2_features"]).to_dict()
            if not parsed["layer3_result"]["escalate_to_llm"]:
                logger.info(
                    "transaction.layer3.skip",
                    protocol=protocol["name"],
                    tx_hash=parsed["tx_hash"][:18],
                    layer3_result=parsed["layer3_result"],
                )
                continue

            layer4_result = await self.layer4.analyze(
                parsed["tx_hash"],
                parsed["layer2_features"],
                parsed["layer3_result"],
            )
            parsed["layer4_result"] = layer4_result.to_dict()
            logger.info(
                "transaction.layer4.result",
                protocol=protocol["name"],
                tx_hash=parsed["tx_hash"][:18],
                verdict=layer4_result.verdict,
                probability=layer4_result.exploit_probability,
                confidence=layer4_result.confidence,
                action=layer4_result.recommended_action,
                attack_type=layer4_result.attack_type,
                cost_usd=layer4_result.cost_usd,
                fallback=layer4_result.fallback_used,
                layer3_score=layer4_result.layer3_score,
            )
            if not layer4_result.should_alert:
                logger.info(
                    "transaction.layer4.skip",
                    protocol=protocol["name"],
                    tx_hash=parsed["tx_hash"][:18],
                    verdict=layer4_result.verdict,
                    probability=layer4_result.exploit_probability,
                )
                continue

            logger.info("transaction.fetched", protocol=protocol["name"], tx_hash=parsed["tx_hash"][:18], block_number=parsed.get("block_number"))
            score_result = await self.scorer.score_transaction(parsed, protocol)
            if score_result.risk_factors:
                pre_screened_this_loop += 1
            else:
                openai_scored_this_loop += 1
            await db.update_transaction_score(tx_id, score_result.risk_score, score_result.risk_summary, score_result.risk_factors)
            logger.info("transaction.scored", protocol=protocol["name"], tx_hash=parsed["tx_hash"][:18], risk_score=score_result.risk_score)
            if score_result.risk_score >= await self._risk_threshold():
                alert_id = await db.insert_alert(tx_id, score_result.risk_score, score_result.risk_summary)
                alerts_fired += 1
                logger.info("alert.created", alert_id=alert_id, risk_score=score_result.risk_score, tx_hash=parsed["tx_hash"][:18])
                sent = await self.telegram.send_alert(protocol, parsed, score_result)
                if sent:
                    await db.mark_telegram_sent(alert_id)
                    logger.info("alert.telegram.sent", alert_id=alert_id)
                elif getattr(self.telegram, "last_send_suppressed", False):
                    logger.info("alert.telegram.suppressed", alert_id=alert_id)
                else:
                    logger.warning("alert.telegram.failed", alert_id=alert_id)
        self.last_seen_blocks[address] = to_block
        await db.update_protocol_last_seen(protocol["id"], to_block)

        # Track scoring metrics
        if transactions_found > 0:
            avg_score = await db.get_avg_score_today(protocol["id"])
            await db.upsert_scoring_metrics(
                date=datetime.date.today(),
                total_scored=transactions_found,
                pre_screened=pre_screened_this_loop,
                openai_scored=openai_scored_this_loop,
                alerts_fired=alerts_fired,
                avg_score=avg_score or 0.0,
            )

        return transactions_found, alerts_fired


async def main() -> None:
    worker = TaloslyWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
