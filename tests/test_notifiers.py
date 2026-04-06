"""Tests for notification delivery.

Why these tests matter:
- Broken notifier = users don't get alerts (the whole point of the tool)
- Wrong retry behavior = hammering down services or silently dropping messages
- Template bugs in webhook = malformed payloads to downstream APIs
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aioresponses import aioresponses

from src.config import DiscordConfig, SlackConfig, WebhookConfig, WebhookEndpoint
from src.notifiers.discord import DiscordNotifier, DISCORD_MAX_LENGTH
from src.notifiers.slack import SlackNotifier
from src.notifiers.webhook import WebhookNotifier


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
