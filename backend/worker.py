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
from kya.alerts import send_agent_score_alert
from kya.baselines import get_baseline, update_baseline
from kya.config import kya_settings
from kya.features import build_feature_vector
from kya.ingest import ingest_wallet
from kya.score import score_agent_event
from scoring.features import Layer2FeatureEngineering
from scoring.filters import PreFilterManager
from scoring.layer3 import Layer3MLEnsemble
from scoring.layer4 import get_oracle
from scoring.layer5 import AlertOrchestrator


class TaloslyWorker:
    def __init__(self) -> None:
        self.rpc = EthereumRPCClient()
        self.scorer = TransactionScorer()
        self.telegram = TelegramService()
        self.pre_filter = PreFilterManager()
        self.layer2 = Layer2FeatureEngineering()
        self.layer3 = Layer3MLEnsemble()
        self.layer4 = get_oracle()
        self.layer5 = AlertOrchestrator(db, self.telegram)
        self.running = True
        self.last_seen_blocks: dict[str, int] = {}
        self.rpc_backoff_seconds = 0
        self.mempool_subscriber: MempoolSubscriber | None = None
        self.mempool_task: asyncio.Task | None = None
        self.mempool_protocols: dict[str, dict] = {}
        self.kya_seen_tx_hashes: dict[int, set[str]] = {}

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
            rpc_endpoint=self.rpc.sanitized_rpc_url(),
            risk_threshold=await self._risk_threshold(),
            database="PostgreSQL",
        )
        try:
            worker_tasks = []
            if settings.enable_mempool_subscriber and settings.ethereum_ws_url:
                worker_tasks.extend([self._poll_loop(), self._run_mempool_subscriber()])
            else:
                if settings.enable_mempool_subscriber:
                    logger.warning("mempool.disabled", reason="missing websocket url")
                worker_tasks.append(self._poll_loop())
            if kya_settings.enable_kya:
                worker_tasks.append(self._run_kya_loop())
            if len(worker_tasks) == 1:
                await worker_tasks[0]
            else:
                await asyncio.gather(*worker_tasks, return_exceptions=True)
        finally:
            await self.shutdown("stop requested")

    async def _run_kya_loop(self) -> None:
        logger.info("worker.kya.start", interval_seconds=kya_settings.kya_poll_interval_seconds)
        while self.running:
            try:
                wallets = await self._get_agent_wallets()
                for wallet in wallets:
                    await self._process_agent_wallet(wallet)
            except EthereumRPCRateLimitError as exc:
                retry_after_seconds = getattr(exc, "retry_after_seconds", None) or 0
                backoff_seconds = int(max(settings.ethereum_rpc_rate_limit_backoff_seconds, retry_after_seconds))
                logger.error("worker.kya.rpc.rate_limited", error=str(exc), backoff_seconds=backoff_seconds)
                await asyncio.sleep(backoff_seconds)
                continue
            except Exception as exc:
                logger.error("worker.kya.error", error=str(exc))
            await asyncio.sleep(max(kya_settings.kya_poll_interval_seconds, 10))

    async def _get_agent_wallets(self) -> list[dict]:
        pool = await db.get_pool()
        rows = await pool.fetch(
            """
            SELECT
                agents.id AS agent_id,
                agents.name,
                agents.principal_ref,
                agent_wallets.id AS wallet_id,
                agent_wallets.chain,
                agent_wallets.address
            FROM agent_wallets
            JOIN agents ON agents.id = agent_wallets.agent_id
            WHERE agents.status = 'active'
            ORDER BY agent_wallets.added_at ASC
            """
        )
        return [dict(row) for row in rows]

    async def _process_agent_wallet(self, wallet: dict) -> int:
        agent_id = int(wallet["agent_id"])
        address = str(wallet["address"])
        lookback = max(settings.ethereum_blocks_per_poll, 1)
        events = await ingest_wallet(agent_id, address, lookback, rpc_client=self.rpc)
        seen = self.kya_seen_tx_hashes.setdefault(int(wallet["wallet_id"]), set())
        processed = 0
        for event in events:
            if event.tx_hash in seen:
                continue
            seen.add(event.tx_hash)
            baseline = await get_baseline(agent_id)
            build_feature_vector(event, baseline)
            updated_baseline = await update_baseline(agent_id, event)
            score = await score_agent_event(agent_id, event, updated_baseline)
            await send_agent_score_alert(
                {
                    "name": wallet.get("name"),
                    "principal_ref": wallet.get("principal_ref"),
                    "address": address,
                },
                event.tx_hash,
                score,
                telegram=self.telegram,
            )
            processed += 1
        return processed

    # Layer 0 — raw data ingestion
    #
    # Pull confirmed on-chain transactions through the configured Ethereum RPC
    # source before later filtering, feature extraction, and scoring layers run.
    async def _poll_loop(self) -> None:
        logger.info("worker.layer0.rpc.start")
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

    # Layer 0 — raw data ingestion
    #
    # Subscribe to pending transactions from the configured Alchemy websocket
    # source before later filtering, feature extraction, and scoring layers run.
    async def _run_mempool_subscriber(self) -> None:
        logger.info("worker.layer0.mempool.start")
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

        parsed = self._parse_mempool_transaction(tx)
        tx_data = {
            "to": parsed.get("to_address"),
            "from": parsed.get("from_address"),
            "input": parsed.get("input_data", "0x"),
            "value": parsed.get("value_eth", 0),
        }
        should_escalate, filter_reason = self.pre_filter.should_evaluate(tx_data)
        if not should_escalate:
            logger.info(
                "mempool.transaction.prefilter.pass",
                tx_hash=tx_hash[:18],
                reason=filter_reason,
            )
            return
        layer2_features = self.layer2.process(parsed).to_dict()
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

        tx_id, is_new = await db.upsert_transaction(protocol["id"], parsed)
        if not is_new:
            logger.info(
                "mempool.transaction.duplicate",
                protocol=protocol.get("name"),
                tx_hash=tx_hash[:18],
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
        score_result = await self.scorer.score_transaction(parsed, protocol)
        layer5_result = await self.layer5.process(
            tx_id=tx_id,
            protocol=protocol,
            transaction=parsed,
            score_result=score_result,
            layer3=layer3_result,
            layer4=layer4_result,
            threshold=await self._risk_threshold(),
        )
        logger.info(
            "mempool.transaction.scored",
            protocol=protocol.get("name"),
            tx_hash=tx_hash[:18],
            risk_score=layer5_result.decision.enriched_score,
            layer5_reason=layer5_result.decision.reason,
        )
        if layer5_result.alert_created:
            logger.info(
                "mempool.alert.created",
                alert_id=layer5_result.alert_id,
                risk_score=layer5_result.decision.enriched_score,
                tx_hash=tx_hash[:18],
            )
            if layer5_result.telegram_sent:
                logger.info("mempool.alert.telegram.sent", alert_id=layer5_result.alert_id)
            elif getattr(self.telegram, "last_send_suppressed", False):
                logger.info("mempool.alert.telegram.suppressed", alert_id=layer5_result.alert_id)
            else:
                logger.warning("mempool.alert.telegram.failed", alert_id=layer5_result.alert_id)

    def _parse_mempool_transaction(self, tx: dict) -> dict:
        value_wei = self._parse_hex_int(tx.get("value"))
        gas_value = tx.get("gas") or tx.get("gasLimit")
        gas_price_wei = self._parse_hex_int(tx.get("gasPrice") or tx.get("maxFeePerGas"))
        return {
            "tx_hash": tx.get("hash"),
            "block_number": None,
            "from_address": tx.get("from"),
            "to_address": tx.get("to"),
            "value_eth": value_wei / 10**18,
            "gas_used": self._parse_hex_int(gas_value),
            "gas_price_gwei": gas_price_wei / 10**9 if gas_price_wei else 0,
            "input_data": (tx.get("input") or "")[:500],
            "status": None,
            "logs": [],
        }

    @staticmethod
    def _parse_hex_int(value: object) -> int:
        if value is None or isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value, 16) if value.startswith("0x") else int(value)
            except ValueError:
                return 0
        return 0

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
            layer5_result = await self.layer5.process(
                tx_id=tx_id,
                protocol=protocol,
                transaction=parsed,
                score_result=score_result,
                layer3=parsed.get("layer3_result"),
                layer4=layer4_result,
                threshold=await self._risk_threshold(),
            )
            logger.info(
                "transaction.scored",
                protocol=protocol["name"],
                tx_hash=parsed["tx_hash"][:18],
                risk_score=layer5_result.decision.enriched_score,
                layer5_reason=layer5_result.decision.reason,
            )
            if layer5_result.alert_created:
                alerts_fired += 1
                logger.info(
                    "alert.created",
                    alert_id=layer5_result.alert_id,
                    risk_score=layer5_result.decision.enriched_score,
                    tx_hash=parsed["tx_hash"][:18],
                )
                if layer5_result.telegram_sent:
                    logger.info("alert.telegram.sent", alert_id=layer5_result.alert_id)
                elif getattr(self.telegram, "last_send_suppressed", False):
                    logger.info("alert.telegram.suppressed", alert_id=layer5_result.alert_id)
                else:
                    logger.warning("alert.telegram.failed", alert_id=layer5_result.alert_id)
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
