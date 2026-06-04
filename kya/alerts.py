"""KYA alerts delivered through Talosly's existing Telegram service."""

from __future__ import annotations

import json
from typing import Any

from backend import database as db
from backend.services.telegram import TelegramService
from kya.baselines import get_baseline
from kya.config import kya_settings
from kya.score import AgentTrustScore
from kya.signals.conformal import ConformalSignal, compute_conformal_signal


async def send_agent_score_alert(
    agent: dict[str, Any],
    action: str,
    score: AgentTrustScore,
    telegram: TelegramService | None = None,
) -> bool:
    """Send a KYA alert when derived agent risk exceeds the configured threshold."""
    risk_score = 100 - int(score.trust_score)
    conformal = None
    if kya_settings.kya_enable_conformal:
        baseline = await get_baseline(score.agent_id)
        conformal = compute_conformal_signal(
            float(score.layer3.get("isolation_score") or 0.0),
            baseline.get("conformal_calib"),
        )
        await _persist_conformal_calibration(score.agent_id, conformal.calibration)
        if not conformal.provisional and not conformal.anomalous:
            return False
    if (conformal is None or conformal.provisional) and risk_score < int(kya_settings.kya_alert_threshold):
        return False

    service = telegram or TelegramService()
    agent_name = str(agent.get("name") or f"agent-{score.agent_id}")
    dedupe_ref = str(agent.get("principal_ref") or agent.get("address") or score.agent_id)
    reason = _format_reason(agent_name, action, risk_score, score, conformal)
    return await service.send_smart_alert(
        {"name": f"KYA Agent: {agent_name}", "address": dedupe_ref},
        risk_score,
        action,
        reason,
    )


def _format_reason(
    agent_name: str,
    action: str,
    risk_score: int,
    score: AgentTrustScore,
    conformal: ConformalSignal | None = None,
) -> str:
    reasons = _human_readable_reasons(score)
    reason = (
        f"Agent {agent_name} action {action} scored {risk_score}/100 risk. "
        f"Reasons: {'; '.join(reasons) if reasons else 'no dominant anomaly reason'}."
    )
    if conformal is None:
        return reason
    if conformal.provisional:
        return f"{reason} Conformal confidence: provisional."
    return f"{reason} Conformal confidence: {conformal.confidence:.1%}."


async def _persist_conformal_calibration(agent_id: int, calibration: dict[str, Any]) -> None:
    pool = await db.get_pool()
    await pool.execute(
        """
        UPDATE agent_profiles
        SET baseline = jsonb_set(baseline, '{conformal_calib}', $2::jsonb, true),
            updated_at = NOW()
        WHERE agent_id = $1
        """,
        agent_id,
        json.dumps(calibration, sort_keys=True),
    )


def _human_readable_reasons(score: AgentTrustScore) -> list[str]:
    phrases = []
    factor_phrases = {
        "new_counterparty": "funds to never-seen counterparty",
        "unseen_selector": "never-seen action selector",
        "off_hours": "activity outside usual active hours",
        "cadence_break": "cadence break versus baseline",
        "value_outlier": "value far above baseline",
    }
    for factor in score.risk_factors:
        phrase = factor_phrases.get(factor)
        if phrase and phrase not in phrases:
            phrases.append(phrase)

    for item in score.shap_top:
        feature = str(item.get("feature") or "")
        if not feature:
            continue
        phrase = _humanize_feature(feature, item)
        if phrase not in phrases:
            phrases.append(phrase)
    return phrases[:6]


def _humanize_feature(feature: str, item: dict[str, Any]) -> str:
    labels = {
        "graph_centrality": "unusual counterparty graph",
        "velocity": "unusual action velocity",
        "pool_drain_ratio": "large value movement versus baseline",
        "flash_loan_fingerprint": "unusual action fingerprint",
        "wallet_age_days": "new or low-history wallet pattern",
        "tornado_tagged": "mixer-associated wallet signal",
        "calldata_entropy": "unusual calldata entropy",
        "gas_anomaly_zscore": "gas or cadence anomaly",
    }
    impact = item.get("shap")
    if impact is None:
        return labels.get(feature, feature.replace("_", " "))
    return f"{labels.get(feature, feature.replace('_', ' '))} (impact {float(impact):.2f})"


__all__ = ["TelegramService", "send_agent_score_alert"]
