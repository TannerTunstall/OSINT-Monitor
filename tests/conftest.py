import pytest


@pytest.fixture
def sample_config_dict():
    """A minimal valid config dict for testing."""
    return {
        "sources": {
            "rss_feeds": {
                "feeds": [
                    {"url": "https://example.com/feed.xml", "label": "Test Feed"}
                ]
            }
        },
        "notifiers": {
            "discord": {
                "enabled": True,
                "webhook_urls": ["https://discord.com/api/webhooks/test/test"],
            }
        },
    }


@pytest.fixture
def sample_messages():
    """Sample message dicts for pipeline testing."""
    return [
        {
            "source": "telegram",
            "source_id": "test-1",
            "author": "Test Channel",
            "content": "This is a test message about a network outage",
            "url": "https://t.me/test/1",
        },
        {
            "source": "twitter",
            "source_id": "test-2",
            "author": "@testaccount",
            "content": "Breaking news about infrastructure",
            "url": "https://x.com/test/status/123",
        },
    ]
