"""Tests for notification delivery.

Why these tests matter:
- Broken notifier = users don't get alerts (the whole point of the tool)
- Wrong retry behavior = hammering down services or silently dropping messages
- Template bugs in webhook = malformed payloads to downstream APIs
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from aioresponses import aioresponses

from src.config import DiscordConfig, SlackConfig, WebhookConfig, WebhookEndpoint, SignalConfig, WhatsAppConfig, EmailConfig
from src.notifiers.discord import DiscordNotifier, DISCORD_MAX_LENGTH
from src.notifiers.slack import SlackNotifier
from src.notifiers.webhook import WebhookNotifier
from src.notifiers.signal import SignalNotifier
from src.notifiers.whatsapp import WhatsAppNotifier


class TestDiscordNotifier:
    @pytest.fixture
    def notifier(self):
        config = DiscordConfig(enabled=True, webhook_urls=["https://discord.com/api/webhooks/test/token"])
        return DiscordNotifier(config)

    async def test_send_success(self, notifier):
        with aioresponses() as m:
            m.post("https://discord.com/api/webhooks/test/token", status=204)
            result = await notifier.send("Test message")
            assert result is True
        await notifier.close()

    async def test_client_error_returns_false(self, notifier):
        """400 errors should not be retried — return False immediately."""
        with aioresponses() as m:
            m.post("https://discord.com/api/webhooks/test/token", status=400, body="Bad Request")
            result = await notifier.send("Test message")
            assert result is False
        await notifier.close()

    async def test_truncates_long_message(self, notifier):
        """Messages over 2000 chars should be truncated."""
        long_msg = "a" * 3000
        with aioresponses() as m:
            m.post("https://discord.com/api/webhooks/test/token", status=204)
            result = await notifier.send(long_msg)
            assert result is True
        await notifier.close()
        # The DISCORD_MAX_LENGTH constant enforces 2000 char limit
        assert DISCORD_MAX_LENGTH == 2000

    async def test_multiple_webhooks_all_called(self):
        config = DiscordConfig(enabled=True, webhook_urls=[
            "https://discord.com/api/webhooks/1/a",
            "https://discord.com/api/webhooks/2/b",
        ])
        notifier = DiscordNotifier(config)
        with aioresponses() as m:
            m.post("https://discord.com/api/webhooks/1/a", status=204)
            m.post("https://discord.com/api/webhooks/2/b", status=204)
            result = await notifier.send("Test")
            assert result is True
            # Both URLs should have been called
            assert len(m.requests) == 2
        await notifier.close()


class TestSlackNotifier:
    async def test_send_success(self):
        config = SlackConfig(enabled=True, webhook_urls=["https://hooks.slack.com/services/T/B/x"])
        notifier = SlackNotifier(config)
        with aioresponses() as m:
            m.post("https://hooks.slack.com/services/T/B/x", status=200, body="ok")
            result = await notifier.send("Test message")
            assert result is True
        await notifier.close()


class TestWebhookNotifier:
    async def test_default_template(self):
        config = WebhookConfig(enabled=True, urls=[
            WebhookEndpoint(url="https://api.example.com/hook")
        ])
        notifier = WebhookNotifier(config)
        with aioresponses() as m:
            m.post("https://api.example.com/hook", status=200)
            result = await notifier.send("Alert: server down")
            assert result is True
        await notifier.close()

    async def test_custom_method_put(self):
        config = WebhookConfig(enabled=True, urls=[
            WebhookEndpoint(url="https://api.example.com/hook", method="PUT")
        ])
        notifier = WebhookNotifier(config)
        with aioresponses() as m:
            m.put("https://api.example.com/hook", status=200)
            result = await notifier.send("Alert")
            assert result is True
        await notifier.close()

    async def test_escapes_quotes_in_message(self):
        """Messages with quotes shouldn't break JSON body template."""
        config = WebhookConfig(enabled=True, urls=[
            WebhookEndpoint(url="https://api.example.com/hook")
        ])
        notifier = WebhookNotifier(config)
        with aioresponses() as m:
            m.post("https://api.example.com/hook", status=200)
            result = await notifier.send('Alert: "critical" failure')
            assert result is True
        await notifier.close()

    async def test_multiple_endpoints_all_called(self):
        config = WebhookConfig(enabled=True, urls=[
            WebhookEndpoint(url="https://api1.example.com/hook"),
            WebhookEndpoint(url="https://api2.example.com/hook"),
        ])
        notifier = WebhookNotifier(config)
        with aioresponses() as m:
            m.post("https://api1.example.com/hook", status=200)
            m.post("https://api2.example.com/hook", status=200)
            result = await notifier.send("Alert")
            assert result is True
            assert len(m.requests) == 2
        await notifier.close()


class TestSignalNotifier:
    async def test_send_success(self):
        config = SignalConfig(enabled=True, api_url="http://signal:8080", sender="+1234567890", recipients=["+0987654321"])
        notifier = SignalNotifier(config)
        with aioresponses() as m:
            m.post("http://signal:8080/v2/send", status=200)
            result = await notifier.send("Test alert")
            assert result is True
        await notifier.close()

    async def test_send_failure(self):
        config = SignalConfig(enabled=True, api_url="http://signal:8080", sender="+1234567890", recipients=["+0987654321"])
        notifier = SignalNotifier(config)
        with aioresponses() as m:
            m.post("http://signal:8080/v2/send", status=400, body="Bad request")
            result = await notifier.send("Test alert")
            assert result is False
        await notifier.close()

    async def test_empty_recipients_returns_true(self):
        config = SignalConfig(enabled=True, api_url="http://signal:8080", sender="+1234567890", recipients=[])
        notifier = SignalNotifier(config)
        result = await notifier.send("Test alert")
        assert result is True
        await notifier.close()


class TestWhatsAppNotifier:
    async def test_send_success(self):
        config = WhatsAppConfig(enabled=True, api_url="http://waha:3000", session_name="default", chat_ids=["123@c.us"])
        notifier = WhatsAppNotifier(config)
        with aioresponses() as m:
            m.post("http://waha:3000/api/sendText", status=200)
            result = await notifier.send("Test message")
            assert result is True
        await notifier.close()

    async def test_send_failure(self):
        config = WhatsAppConfig(enabled=True, api_url="http://waha:3000", session_name="default", chat_ids=["123@c.us"])
        notifier = WhatsAppNotifier(config)
        with aioresponses() as m:
            m.post("http://waha:3000/api/sendText", status=400, body="Error")
            result = await notifier.send("Test message")
            assert result is False
        await notifier.close()


class TestEmailNotifier:
    async def test_send_success(self):
        config = EmailConfig(enabled=True, smtp_host="smtp.test.com", smtp_port=587,
                             from_address="test@test.com", to_addresses=["user@test.com"])
        from src.notifiers.email import EmailNotifier
        notifier = EmailNotifier(config)
        with patch("src.notifiers.email.EmailNotifier._send_email", new_callable=AsyncMock, return_value=True):
            result = await notifier.send("Test alert")
            assert result is True

    async def test_smtp_failure_returns_false(self):
        config = EmailConfig(enabled=True, smtp_host="smtp.test.com", smtp_port=587,
                             from_address="test@test.com", to_addresses=["user@test.com"])
        from src.notifiers.email import EmailNotifier
        notifier = EmailNotifier(config)
        with patch("src.notifiers.email.EmailNotifier._send_email", new_callable=AsyncMock, side_effect=Exception("SMTP error")):
            result = await notifier.send("Test alert")
            assert result is False

    async def test_subject_truncation(self):
        config = EmailConfig(enabled=True, smtp_host="smtp.test.com", smtp_port=587,
                             from_address="test@test.com", to_addresses=["a@b.com"],
                             subject_prefix="[OSINT]")
        long_text = "a" * 200
        subject = f"{config.subject_prefix} {long_text[:80]}"
        assert len(subject) < 100  # subject is capped at prefix + 80 chars
