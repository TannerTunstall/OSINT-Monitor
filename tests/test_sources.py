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
from src.sources.radar import RadarSource
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


# ── Radar Source ─────────────────────────────────────────

SAMPLE_ANOMALY_RESPONSE = {
    "result": {
        "trafficAnomalies": [
            {
                "uuid": "abc-123",
                "asnDetails": {"asn": "48159", "name": "TIC-AS"},
                "locationDetails": {"code": "IR", "name": "Iran"},
                "status": "VERIFIED",
                "type": "LOCATION",
                "startDate": "2026-04-06T17:30:00Z",
            }
        ]
    }
}

SAMPLE_OUTAGE_RESPONSE = {
    "result": {
        "annotations": [
            {
                "id": "outage-001",
                "dataSource": "ORIGIN",
                "description": "AWS us-east-1 elevated errors",
                "eventType": "OUTAGE",
                "startDate": "2026-04-06T10:00:00Z",
                "endDate": None,
                "locationsDetails": [{"code": "US", "name": "United States"}],
                "asnsDetails": [{"asn": "16509", "name": "AMAZON-02"}],
            },
            {
                "id": "outage-002",
                "dataSource": "BGP",
                "description": "BGP route leak in Iran",
                "eventType": "OUTAGE",
                "startDate": "2026-04-05T08:00:00Z",
                "endDate": "2026-04-05T12:00:00Z",
                "locationsDetails": [{"code": "IR", "name": "Iran"}],
                "asnsDetails": [],
            },
            {
                "id": "outage-003",
                "dataSource": "BGP",
                "description": "Unrelated outage in Brazil",
                "eventType": "OUTAGE",
                "startDate": "2026-04-05T06:00:00Z",
                "endDate": None,
                "locationsDetails": [{"code": "BR", "name": "Brazil"}],
                "asnsDetails": [],
            },
        ]
    }
}


class TestRadarTrafficAnomalies:
    async def test_parses_valid_anomaly(self):
        source = RadarSource(api_token="test-token", countries={"IR": "Iran"})
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=SAMPLE_ANOMALY_RESPONSE)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        source._session = mock_session

        messages = await source._fetch_traffic_anomalies()
        assert len(messages) == 1
        assert messages[0].source == "radar"
        assert "anomaly-abc-123" == messages[0].source_id
        assert "TIC-AS" in messages[0].content
        assert "Iran" in messages[0].author

    async def test_non_200_skips_country(self):
        source = RadarSource(api_token="test-token", countries={"IR": "Iran"})
        mock_resp = AsyncMock()
        mock_resp.status = 401
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        source._session = mock_session

        messages = await source._fetch_traffic_anomalies()
        assert len(messages) == 0

    async def test_empty_countries_returns_empty(self):
        source = RadarSource(api_token="test-token", countries={})
        messages = await source._fetch_traffic_anomalies()
        assert messages == []

    async def test_malformed_timestamp_handled(self):
        response = {"result": {"trafficAnomalies": [{
            "uuid": "x", "asnDetails": {}, "status": "VERIFIED",
            "type": "LOCATION", "startDate": "not-a-date",
        }]}}
        source = RadarSource(api_token="test", countries={"US": "United States"})
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        source._session = mock_session

        messages = await source._fetch_traffic_anomalies()
        assert len(messages) == 1
        assert messages[0].timestamp is None

    async def test_missing_uuid_uses_fallback_id(self):
        response = {"result": {"trafficAnomalies": [{
            "asnDetails": {}, "status": "VERIFIED",
            "type": "LOCATION", "startDate": "2026-04-06T10:00:00Z",
        }]}}
        source = RadarSource(api_token="test", countries={"US": "United States"})
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        source._session = mock_session

        messages = await source._fetch_traffic_anomalies()
        assert "US-2026-04-06T10:00:00Z" in messages[0].source_id


class TestRadarOutages:
    async def test_origin_outage_included_without_countries(self):
        """ORIGIN outages should be included even with no countries configured."""
        source = RadarSource(api_token="test", countries={})
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=SAMPLE_OUTAGE_RESPONSE)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        source._session = mock_session

        messages = await source._fetch_origin_outages()
        # Only ORIGIN outage (outage-001) should pass — others filtered
        assert len(messages) == 1
        assert "Cloud Outage" in messages[0].author

    async def test_monitored_country_outage_included(self):
        """Outages for configured countries should be included."""
        source = RadarSource(api_token="test", countries={"IR": "Iran"})
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=SAMPLE_OUTAGE_RESPONSE)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        source._session = mock_session

        messages = await source._fetch_origin_outages()
        # ORIGIN (001) + IR match (002) = 2, Brazil (003) filtered out
        assert len(messages) == 2
        sources = [m.source_id for m in messages]
        assert "outage-outage-001" in sources
        assert "outage-outage-002" in sources

    async def test_unmonitored_non_origin_filtered_out(self):
        """Non-ORIGIN outages for unconfigured countries should be skipped."""
        source = RadarSource(api_token="test", countries={"DE": "Germany"})
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=SAMPLE_OUTAGE_RESPONSE)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        source._session = mock_session

        messages = await source._fetch_origin_outages()
        # Only ORIGIN passes — IR and BR not in {DE}
        assert len(messages) == 1

    async def test_empty_locations_and_asns(self):
        response = {"result": {"annotations": [{
            "id": "empty-1", "dataSource": "ORIGIN", "description": "Unknown outage",
            "eventType": "OUTAGE", "startDate": "2026-04-06T00:00:00Z",
            "endDate": None, "locationsDetails": [], "asnsDetails": [],
        }]}}
        source = RadarSource(api_token="test", countries={})
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        source._session = mock_session

        messages = await source._fetch_origin_outages()
        assert len(messages) == 1
        assert "Unknown outage" in messages[0].content
