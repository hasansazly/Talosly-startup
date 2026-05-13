import pytest
from openai.resources.chat.completions import AsyncCompletions

from backend.config import settings
from backend.models import RiskScoreResponse
from backend.services.blacklist import BLACKLIST
from backend.services.scorer import TransactionScorer


class ChoiceMessage:
    def __init__(self, content):
        self.content = content


class Choice:
    def __init__(self, text):
        self.message = ChoiceMessage(text)


class Message:
    def __init__(self, text):
        self.choices = [Choice(text)]


@pytest.mark.asyncio
async def test_json_response_parses_into_risk_score_response(monkeypatch):
    async def fake_create(self, **kwargs):
        assert kwargs["model"] == "gpt-4o-mini"
        return Message('{"risk_score": 87, "risk_summary": "Large suspicious call", "risk_factors": ["high value"]}')

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    monkeypatch.setattr(AsyncCompletions, "create", fake_create)
    scorer = TransactionScorer()
    result = await scorer.score_transaction({"tx_hash": "0xabc", "input_data": "0x"}, {"name": "Talosly Test"})
    assert result.risk_score == 87
    assert result.risk_summary == "Large suspicious call"


@pytest.mark.asyncio
async def test_new_security_prompt_response_parses_into_existing_api_shape(monkeypatch):
    async def fake_create(self, **kwargs):
        assert "Return ONLY this JSON" in kwargs["messages"][0]["content"]
        return Message('{"score": 72, "reason": "Approval exceeds safe threshold", "pattern": "APPROVAL", "action": "ALERT"}')

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(AsyncCompletions, "create", fake_create)
    scorer = TransactionScorer()
    result = await scorer.score_transaction({"tx_hash": "0xabc", "input_data": "0x"}, {"name": "Talosly Test"})
    assert result.risk_score == 72
    assert result.risk_summary == "Approval exceeds safe threshold"
    assert result.risk_factors == ["APPROVAL", "ALERT"]


@pytest.mark.asyncio
async def test_malformed_json_falls_back_to_score_50(monkeypatch):
    async def fake_create(self, **_kwargs):
        return Message("not json")

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(AsyncCompletions, "create", fake_create)
    scorer = TransactionScorer()
    result = await scorer.score_transaction({"tx_hash": "0xabc", "input_data": "0x"}, {"name": "Talosly Test"})
    assert result.risk_score == 50
    assert result.risk_summary == "Scoring unavailable"


def test_out_of_range_score_raises_validation_error():
    scorer = TransactionScorer()
    with pytest.raises(ValueError):
        scorer._parse_response('{"risk_score": 150, "risk_summary": "Bad", "risk_factors": []}')


@pytest.mark.asyncio
async def test_wallet_reputation_returns_neutral_without_web3_provider():
    scorer = TransactionScorer()

    assert await scorer._get_wallet_reputation("0x1111111111111111111111111111111111111111") == {
        "is_new": False,
        "has_no_ens": False,
    }


@pytest.mark.asyncio
async def test_wallet_reputation_uses_attached_async_web3_provider():
    class FakeEth:
        async def get_transaction_count(self, _address):
            return 3

    class FakeEns:
        async def name(self, _address):
            return None

    class FakeW3:
        eth = FakeEth()
        ens = FakeEns()

    scorer = TransactionScorer()
    scorer.w3 = FakeW3()

    assert await scorer._get_wallet_reputation("0x1111111111111111111111111111111111111111") == {
        "is_new": True,
        "has_no_ens": True,
    }


def test_pre_screen_flags_blacklisted_address():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x0000000000000000000000000000000000000000",
            "to_address": next(iter(BLACKLIST)).upper(),
            "input_data": "0x",
            "value_eth": 0,
        }
    )
    assert result is not None
    assert result.risk_score == 98
    assert result.risk_factors == ["BLACKLISTED_ADDRESS"]


def test_pre_screen_flags_expanded_blacklist_with_mixed_case_input():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x098B716B8AAF21512996DC57EB0615E2383E2F96",
            "to_address": "0x0000000000000000000000000000000000000000",
            "input_data": "0x",
            "value_eth": 0,
        }
    )

    assert result is not None
    assert result.risk_score == 98
    assert result.risk_factors == ["BLACKLISTED_ADDRESS"]


def test_pre_screen_flags_known_exploit_target_contract():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x0000000000000000000000000000000000000000",
            "to_address": "0x27182842E098f60e3D576794A5bFFb0777E025d3",
            "input_data": "0x",
            "value_eth": 0,
        }
    )

    assert result is not None
    assert result.risk_score == 82
    assert result.risk_factors == ["KNOWN_EXPLOIT_TARGET"]


@pytest.mark.asyncio
async def test_score_transaction_runs_pre_screen_without_openai_key(monkeypatch):
    async def fake_address_label(_address):
        return {
            "label": None,
            "is_dangerous": False,
            "is_new_wallet": False,
            "funded_by_tornado": False,
            "tx_count": -1,
        }

    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr("backend.services.scorer.get_address_label", fake_address_label)
    scorer = TransactionScorer()
    result = await scorer.score_transaction(
        {
            "tx_hash": "0xabc",
            "from_address": next(iter(BLACKLIST)).upper(),
            "to_address": "0x0000000000000000000000000000000000000000",
            "input_data": "0x",
            "value_eth": 0,
        },
        {"name": "Backtest"},
    )

    assert result.risk_score >= 98
    assert "BLACKLISTED_ADDRESS" in result.risk_factors


def test_pre_screen_flags_self_transfer():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x1111111111111111111111111111111111111111",
            "input_data": "0x",
            "value_eth": 0,
        }
    )
    assert result is not None
    assert result.risk_score == 78
    assert result.risk_summary == "Self-transfer detected"
    assert result.risk_factors == ["SELF_TRANSFER"]


def test_pre_screen_flags_zero_value_payload_probe_with_rpc_field_names():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from": "0x1111111111111111111111111111111111111111",
            "to": "0x2222222222222222222222222222222222222222",
            "input": "0x" + ("a" * 198),
            "value": "0x0",
        }
    )
    assert result is not None
    assert result.risk_score == 55
    assert result.risk_summary == "Exploit behavior detected: zero value contract call, large payload probe"
    assert result.risk_factors == ["ZERO_VALUE_CONTRACT_CALL", "LARGE_PAYLOAD_PROBE"]


def test_pre_screen_flags_euler_style_behavior_without_blacklist():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d",
            "from_address": "0x0000000000000000000000000000000000000001",
            "to_address": "0xebc29199c817dc47ba12e3f86102564d640cbf99",
            "value_eth": 0,
            "gas_used": 6_211_412,
            "input_data": "0x863df8af",
        }
    )

    assert result is not None
    assert result.risk_score >= 85
    assert result.risk_factors == ["DONATION_PATTERN", "ZERO_VALUE_CONTRACT_CALL", "HIGH_VALUE_VAULT"]


def test_pre_screen_uses_contextual_price_impact_for_oracle_manipulation():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x2222222222222222222222222222222222222222",
            "value_eth": 0,
            "gas_used": 800_000,
            "input_data": "0x5cffe9de",
            "price_impact_pct": 7.5,
        }
    )

    assert result is not None
    assert result.risk_score >= 92
    assert result.risk_factors == ["FLASH_LOAN", "HIGH_GAS_EXECUTION", "PRICE_IMPACT"]


def test_pre_screen_flags_reentrancy_pattern_with_distinct_score():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x2222222222222222222222222222222222222222",
            "value_eth": 0,
            "gas_used": 120_000,
            "input_data": "0x12345678",
            "same_contract_call_count": 4,
        }
    )

    assert result is not None
    assert result.risk_score == 88
    assert result.risk_factors == ["ZERO_VALUE_CONTRACT_CALL", "REENTRANCY_PATTERN"]


def test_pre_screen_flags_unauthorized_mint_and_balance_jump():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x2222222222222222222222222222222222222222",
            "value_eth": 0,
            "gas_used": 200_000,
            "input_data": "0x40c10f19",
            "attacker_balance_before_usd": 0,
            "attacker_balance_after_usd": 1_250_000,
        }
    )

    assert result is not None
    assert result.risk_score == 100
    assert result.risk_factors == ["ZERO_VALUE_CONTRACT_CALL", "UNAUTHORIZED_MINT_SIGNAL", "BALANCE_JUMP"]


def test_pre_screen_flags_bridge_message_invariant_risk_without_hash_exception():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x5d94309e5a0090b165fa4181519701637b6daeba",
            "value_eth": 0,
            "gas_used": 170_000,
            "input_data": "0x928bc4b2" + ("0" * 240),
        }
    )

    assert result is not None
    assert result.risk_score == 100
    assert result.risk_factors == ["CROSS_CHAIN_MESSAGE_PROCESS", "KNOWN_BRIDGE_CONTRACT", "BRIDGE_INVARIANT_RISK"]


def test_pre_screen_flags_cross_chain_relay_privilege_payload_without_hash_exception():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x2222222222222222222222222222222222222222",
            "value_eth": 0,
            "gas_used": 140_000,
            "input_data": "0xd450e04c" + ("0" * 2200),
        }
    )

    assert result is not None
    assert result.risk_score == 100
    assert result.risk_factors == ["CROSS_CHAIN_RELAY_EXECUTION", "PRIVILEGED_RELAY_PAYLOAD", "CALLDATA_COMPLEXITY"]


def test_pre_screen_flags_amm_state_mismatch_with_oracle_context():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x2222222222222222222222222222222222222222",
            "value_eth": 0,
            "gas_used": 650_000,
            "input_data": "0xabcdef01",
            "liquidity_delta_mismatch": True,
            "oracle_deviation_pct": 6.2,
        }
    )

    assert result is not None
    assert result.risk_score == 100
    assert result.risk_factors == ["ZERO_VALUE_CONTRACT_CALL", "HIGH_GAS_EXECUTION", "PRICE_IMPACT"]


def test_pre_screen_damps_reverted_flash_loan_attempts():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x2222222222222222222222222222222222222222",
            "value_eth": 0,
            "gas_used": 420_000,
            "input_data": "0xab9c4b5d" + ("0" * 2400),
            "status": "0x0",
        }
    )

    assert result is not None
    assert 40 <= result.risk_score <= 65
    assert "FLASH_LOAN" in result.risk_factors


def test_pre_screen_caps_plain_flash_loan_flow_below_critical():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x2222222222222222222222222222222222222222",
            "value_eth": 0,
            "gas_used": 420_000,
            "input_data": "0x5cffe9de" + ("0" * 2400),
            "status": "0x1",
        }
    )

    assert result is not None
    assert 40 <= result.risk_score <= 65
    assert "FLASH_LOAN" in result.risk_factors


def test_pre_screen_caps_plain_liquidation_flow_below_critical():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x2222222222222222222222222222222222222222",
            "value_eth": 0,
            "gas_used": 750_000,
            "input_data": "0x42d96952" + ("0" * 500),
            "status": "0x1",
        }
    )

    assert result is not None
    assert result.risk_score == 65
    assert result.risk_factors == ["ZERO_VALUE_CONTRACT_CALL", "HIGH_GAS_EXECUTION", "LARGE_PAYLOAD_PROBE"]


def test_pre_screen_ignores_known_safe_router_for_behavioral_rules():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x0000000000000000000000000000000000000001",
            "to_address": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
            "value_eth": 0,
            "gas_used": 900_000,
            "input_data": "0x863df8af",
        }
    )

    assert result is None


@pytest.mark.asyncio
async def test_score_transaction_boosts_probe_pattern_to_alert_threshold(monkeypatch):
    async def fake_address_label(_address):
        return {
            "label": None,
            "is_dangerous": False,
            "is_new_wallet": False,
            "funded_by_tornado": False,
            "tx_count": -1,
        }

    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr("backend.services.scorer.get_address_label", fake_address_label)
    scorer = TransactionScorer()
    result = await scorer.score_transaction(
        {
            "tx_hash": "0xabc",
            "from": "0x1111111111111111111111111111111111111111",
            "to": "0x2222222222222222222222222222222222222222",
            "input": "0x" + ("a" * 198),
            "value": "0x0",
        },
        {"name": "Probe Test"},
    )

    assert result.risk_score == 55
    assert result.risk_factors == ["ZERO_VALUE_CONTRACT_CALL", "LARGE_PAYLOAD_PROBE"]


@pytest.mark.asyncio
async def test_score_transaction_applies_wallet_reputation_multiplier(monkeypatch):
    async def fake_reputation(_address):
        return {"is_new": True, "has_no_ens": True}

    async def fake_address_label(_address):
        return {
            "label": None,
            "is_dangerous": False,
            "is_new_wallet": False,
            "funded_by_tornado": False,
            "tx_count": -1,
        }

    monkeypatch.setattr(settings, "openai_api_key", "")
    scorer = TransactionScorer()
    monkeypatch.setattr(scorer, "_get_wallet_reputation", fake_reputation)
    monkeypatch.setattr("backend.services.scorer.get_address_label", fake_address_label)

    result = await scorer.score_transaction(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x2222222222222222222222222222222222222222",
            "input_data": "0x" + ("a" * 198),
            "value_eth": 0,
        },
        {"name": "Probe Test"},
    )

    assert result.risk_score == 70
    assert result.risk_factors == ["ZERO_VALUE_CONTRACT_CALL", "LARGE_PAYLOAD_PROBE", "NEW_WALLET"]


@pytest.mark.asyncio
async def test_behavioral_multiplier_caps_score_at_100(monkeypatch):
    async def fake_reputation(_address):
        return {"is_new": True, "has_no_ens": True}

    async def fake_address_label(_address):
        return {
            "label": None,
            "is_dangerous": False,
            "is_new_wallet": False,
            "funded_by_tornado": False,
            "tx_count": -1,
        }

    scorer = TransactionScorer()
    monkeypatch.setattr(scorer, "_get_wallet_reputation", fake_reputation)
    monkeypatch.setattr("backend.services.scorer.get_address_label", fake_address_label)

    result = await scorer._apply_behavioral_multiplier(
        RiskScoreResponse(
            tx_hash="0xabc",
            risk_score=98,
            risk_summary="High-risk: Known malicious entity.",
            risk_factors=["BLACKLISTED_ADDRESS"],
        ),
        "0x1111111111111111111111111111111111111111",
    )

    assert result.risk_score == 100
    assert result.risk_factors == ["BLACKLISTED_ADDRESS", "NEW_WALLET", "NO_ENS_IDENTITY"]


@pytest.mark.asyncio
async def test_behavioral_multiplier_adds_etherscan_danger_label(monkeypatch):
    async def fake_reputation(_address):
        return {"is_new": False, "has_no_ens": False}

    async def fake_address_label(_address):
        return {
            "label": "unverified contract",
            "is_dangerous": True,
            "is_new_wallet": False,
            "funded_by_tornado": False,
            "tx_count": 4,
        }

    scorer = TransactionScorer()
    monkeypatch.setattr(scorer, "_get_wallet_reputation", fake_reputation)
    monkeypatch.setattr("backend.services.scorer.get_address_label", fake_address_label)

    result = await scorer._apply_behavioral_multiplier(
        RiskScoreResponse(
            tx_hash="0xabc",
            risk_score=72,
            risk_summary="Zero value with large payload",
            risk_factors=["PROBE_PATTERN"],
        ),
        "0x1111111111111111111111111111111111111111",
    )

    assert result.risk_score == 92
    assert result.risk_factors == ["PROBE_PATTERN", "ETHERSCAN_DANGER_LABEL"]


@pytest.mark.asyncio
async def test_behavioral_multiplier_adds_etherscan_new_wallet_and_tornado(monkeypatch):
    async def fake_reputation(_address):
        return {"is_new": False, "has_no_ens": False}

    async def fake_address_label(_address):
        return {
            "label": "Tornado Cash funded, new wallet (2 txs)",
            "is_dangerous": True,
            "is_new_wallet": True,
            "funded_by_tornado": True,
            "tx_count": 2,
        }

    scorer = TransactionScorer()
    monkeypatch.setattr(scorer, "_get_wallet_reputation", fake_reputation)
    monkeypatch.setattr("backend.services.scorer.get_address_label", fake_address_label)

    result = await scorer._apply_behavioral_multiplier(
        RiskScoreResponse(
            tx_hash="0xabc",
            risk_score=40,
            risk_summary="Low base score",
            risk_factors=["NORMAL"],
        ),
        "0x1111111111111111111111111111111111111111",
    )

    assert result.risk_score == 90
    assert result.risk_factors == ["NORMAL", "NEW_WALLET", "TORNADO_FUNDED"]
