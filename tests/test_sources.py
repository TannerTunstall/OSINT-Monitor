"""Tests for RSS and Twitter sources.

Why these tests matter:
- Silent source failures = no data flowing, users won't know
- RSS content filter bugs = wrong messages delivered or missed
- Twitter failover bugs = one bad Nitter instance kills all Twitter monitoring
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from src.sources.twitter import TwitterSource, MAX_CONSECUTIVE_FAILURES
from src.config import TwitterSourceConfig, RSSFeedsConfig, RSSFeed


# ── RSS Source ────────────────────────────────────────────

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>AWS us-east-1 degraded</title>
      <link>https://example.com/1</link>
      <guid>entry-1</guid>
      <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Scheduled maintenance in eu-west-1</title>
      <link>https://example.com/2</link>
      <guid>entry-2</guid>
    </item>
    <item>
      <title>All systems operational</title>
      <link>https://example.com/3</link>
      <guid>entry-3</guid>
    </item>
  </channel>
</rss>"""


class TestRSSSource:
    async def test_parses_valid_feed(self):
        from src.sources.rss import RSSSource
        config = RSSFeedsConfig(feeds=[RSSFeed(url="https://example.com/feed", label="Test")])
        source = RSSSource(config)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=SAMPLE_RSS_XML)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        source._session = mock_session

        messages = await source.poll()
        assert len(messages) == 3
        assert messages[0].source == "rss"
        assert messages[0].author == "Test"
        assert "us-east-1" in messages[0].content

    async def test_content_filter_works(self):
        from src.sources.rss import RSSSource
        config = RSSFeedsConfig(feeds=[
            RSSFeed(url="https://example.com/feed", label="Test", content_filter=["us-east-1"])
        ])
        source = RSSSource(config)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=SAMPLE_RSS_XML)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        source._session = mock_session

        messages = await source.poll()
        assert len(messages) == 1
        assert "us-east-1" in messages[0].content

    async def test_http_error_doesnt_crash(self):
        from src.sources.rss import RSSSource
        config = RSSFeedsConfig(feeds=[
            RSSFeed(url="https://broken.com/feed", label="Broken"),
            RSSFeed(url="https://working.com/feed", label="Working"),
        ])
        source = RSSSource(config)

        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = AsyncMock()
            if "broken" in url:
                resp.status = 404
            else:
                resp.status = 200
                resp.text = AsyncMock(return_value=SAMPLE_RSS_XML)
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        mock_session = MagicMock()
        mock_session.get = mock_get
        source._session = mock_session

        messages = await source.poll()
        assert call_count == 2  # both feeds attempted
        assert len(messages) == 3  # only working feed's messages


# ── Twitter Source ────────────────────────────────────────

class TestTwitterAccountCleaning:
    def test_strips_at_sign(self):
        config = TwitterSourceConfig(method="nitter_rss", nitter_instances=["https://n.example.com"], accounts=["@user1", "  @user2  "])
        source = TwitterSource(config)
        assert source.config.accounts == ["user1", "user2"]

    def test_strips_slashes(self):
        config = TwitterSourceConfig(method="nitter_rss", nitter_instances=["https://n.example.com"], accounts=["/user1/"])
        source = TwitterSource(config)
        assert source.config.accounts == ["user1"]


class TestTwitterFailover:
    def test_deprioritizes_after_consecutive_failures(self):
        config = TwitterSourceConfig(method="nitter_rss", nitter_instances=["https://a.com", "https://b.com"], accounts=["user"])
        source = TwitterSource(config)
        source._instance_health = {
            "https://a.com": {"failures": 0, "deprioritized_until": 0},
            "https://b.com": {"failures": 0, "deprioritized_until": 0},
        }

        for _ in range(MAX_CONSECUTIVE_FAILURES):
            source._record_instance_failure("https://a.com")

        health = source._instance_health["https://a.com"]
        assert health["failures"] == MAX_CONSECUTIVE_FAILURES
        assert health["deprioritized_until"] > time.monotonic()

    def test_success_resets_failure_count(self):
        config = TwitterSourceConfig(method="nitter_rss", nitter_instances=["https://a.com"], accounts=["user"])
        source = TwitterSource(config)
        source._instance_health = {"https://a.com": {"failures": 2, "deprioritized_until": 0}}

        source._record_instance_success("https://a.com")

        assert source._instance_health["https://a.com"]["failures"] == 0
        assert source._healthy_instance == "https://a.com"

    def test_sorted_instances_healthy_first(self):
        config = TwitterSourceConfig(method="nitter_rss", nitter_instances=["https://a.com", "https://b.com"], accounts=["user"])
        source = TwitterSource(config)
        source._instance_health = {
            "https://a.com": {"failures": 0, "deprioritized_until": time.monotonic() + 3600},  # deprioritized
            "https://b.com": {"failures": 0, "deprioritized_until": 0},  # healthy
        }

        sorted_instances = source._get_sorted_instances()
        assert sorted_instances[0] == "https://b.com"  # healthy first
        assert sorted_instances[1] == "https://a.com"  # deprioritized last
