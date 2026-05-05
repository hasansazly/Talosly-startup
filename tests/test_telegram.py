from backend.services.telegram import TelegramService


def test_telegram_message_escapes_dynamic_values_before_html_formatting():
    service = TelegramService()
    message = service._format_message(
        {"name": 'Bad <Protocol> "Alpha"'},
        {"tx_hash": "0xabc<bad>&hash"},
        {"risk_score": 98},
    )

    assert "Bad &lt;Protocol&gt; &quot;Alpha&quot;" in message
    assert "0xabc&lt;bad&gt;&amp;hash" in message
    assert "Bad <Protocol>" not in message
    assert "0xabc<bad>&hash" not in message


def test_telegram_message_uses_safe_fallbacks_for_empty_values():
    service = TelegramService()
    message = service._format_message({"name": ""}, {"tx_hash": ""}, {"risk_score": None})

    assert "<b>Protocol:</b> Unknown Protocol" in message
    assert "<b>Score:</b> <code>0</code>" in message
    assert "<b>TX:</b> <code>No Hash Available</code>" in message
