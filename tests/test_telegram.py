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
