import pytest
import aiosqlite

from src.db import MessageDB, SCHEMA, MIGRATE_COLUMNS
from src.sources.base import Message
from datetime import datetime, timezone


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


@pytest.fixture
async def db():
    """In-memory SQLite database for testing."""
    database = MessageDB(":memory:")
    # Manually connect with in-memory path
    database._db = await aiosqlite.connect(":memory:")
    await database._db.executescript(SCHEMA)
    # Run migrations (same as connect())
    cursor = await database._db.execute("PRAGMA table_info(messages)")
    existing = {row[1] for row in await cursor.fetchall()}
    for col_name, col_type in MIGRATE_COLUMNS:
        if col_name not in existing:
            await database._db.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
    await database._db.commit()
    yield database
    await database.close()


@pytest.fixture
def make_message():
    """Factory for creating Message objects."""
    def _make(source="telegram", source_id="msg-1", author="Test", content="Test content", url=None, timestamp=None):
        return Message(
            source=source,
            source_id=source_id,
            author=author,
            content=content,
            url=url,
            timestamp=timestamp or datetime.now(timezone.utc),
        )
    return _make


class MockNotifier:
    """Mock notifier that records all sent messages."""
    def __init__(self, succeed=True):
        self.sent = []
        self.succeed = succeed

    async def send(self, text: str) -> bool:
        self.sent.append(text)
        return self.succeed

    async def close(self):
        pass
