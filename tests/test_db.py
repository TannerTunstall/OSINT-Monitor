"""Tests for MessageDB — dedup, export, stats, cleanup.

Why these tests matter:
- Broken dedup = duplicate alert spam
- Broken cleanup = disk fills up
- Broken stats = dashboard shows wrong data
- Broken export = users can't generate reports
"""

import pytest
from datetime import datetime, timezone, timedelta


class TestInsertDedup:
    async def test_first_insert_returns_true(self, db):
        result = await db.insert_if_new(source="telegram", source_id="123", content="hello")
        assert result is True

    async def test_duplicate_returns_false(self, db):
        await db.insert_if_new(source="telegram", source_id="123", content="hello")
        result = await db.insert_if_new(source="telegram", source_id="123", content="hello again")
        assert result is False

    async def test_different_sources_same_id_not_deduped(self, db):
        """telegram:123 and twitter:123 are different messages."""
        r1 = await db.insert_if_new(source="telegram", source_id="123", content="from telegram")
        r2 = await db.insert_if_new(source="twitter", source_id="123", content="from twitter")
        assert r1 is True
        assert r2 is True


class TestGetRecent:
    async def test_returns_messages_ordered(self, db):
        await db.insert_if_new(source="telegram", source_id="1", content="first")
        await db.insert_if_new(source="telegram", source_id="2", content="second")
        results = await db.get_recent(limit=10)
        assert len(results) == 2
        # Most recent first
        assert results[0]["source_id"] == "2"

    async def test_filters_by_source(self, db):
        await db.insert_if_new(source="telegram", source_id="1", content="tg msg")
        await db.insert_if_new(source="twitter", source_id="2", content="tw msg")
        results = await db.get_recent(limit=10, source="telegram")
        assert len(results) == 1
        assert results[0]["source"] == "telegram"


class TestExport:
    async def test_export_with_date_range(self, db):
        await db.insert_if_new(source="rss", source_id="1", content="old")
        await db.insert_if_new(source="rss", source_id="2", content="new")
        # Export everything (no date filter)
        results = await db.export()
        assert len(results) == 2
        # Export with future start date — should get nothing
        results = await db.export(start="2099-01-01")
        assert len(results) == 0


class TestStats:
    async def test_counts_match(self, db):
        await db.insert_if_new(source="telegram", source_id="1", content="msg1")
        await db.insert_if_new(source="telegram", source_id="2", content="msg2")
        await db.insert_if_new(source="twitter", source_id="3", content="msg3")
        stats = await db.stats()
        assert stats["total"] == 3
        assert stats["by_source"]["telegram"] == 2
        assert stats["by_source"]["twitter"] == 1
        assert stats["today"] == 3


class TestCleanup:
    async def test_removes_old_keeps_recent(self, db):
        # Insert a message and manually backdate it
        await db.insert_if_new(source="rss", source_id="old", content="old message")
        await db._db.execute(
            "UPDATE messages SET created_at = ? WHERE source_id = ?",
            ((datetime.now(timezone.utc) - timedelta(days=100)).isoformat(), "old"),
        )
        await db._db.commit()
        await db.insert_if_new(source="rss", source_id="new", content="new message")

        await db.cleanup(retention_days=90)

        results = await db.get_recent(limit=10)
        assert len(results) == 1
        assert results[0]["source_id"] == "new"
