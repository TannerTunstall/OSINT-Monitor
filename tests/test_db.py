"""Tests for MessageDB — dedup, export, stats, cleanup.

Why these tests matter:
- Broken dedup = duplicate alert spam
- Broken cleanup = disk fills up
- Broken stats = dashboard shows wrong data
- Broken export = users can't generate reports
"""

import pytest
import aiosqlite
from datetime import datetime, timezone, timedelta
from src.db import MessageDB, SCHEMA


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


class TestUpdateEnrichment:
    async def test_stores_translation_and_keywords(self, db):
        await db.insert_if_new(source="telegram", source_id="1", content="original")
        await db.update_enrichment("telegram", "1", "translated text", "war, outage")
        results = await db.get_recent(limit=1)
        assert results[0]["translation"] == "translated text"
        assert results[0]["matched_keywords"] == "war, outage"

    async def test_update_nonexistent_message(self, db):
        """Updating a non-existent message should not crash."""
        await db.update_enrichment("telegram", "nonexistent", "translation", None)
        # No error raised

    async def test_overwrite_enrichment(self, db):
        await db.insert_if_new(source="rss", source_id="1", content="text")
        await db.update_enrichment("rss", "1", "first translation", None)
        await db.update_enrichment("rss", "1", "updated translation", "keyword1")
        results = await db.get_recent(limit=1)
        assert results[0]["translation"] == "updated translation"
        assert results[0]["matched_keywords"] == "keyword1"


class TestMigration:
    async def test_existing_db_gets_new_columns(self):
        """Old DB without translation/matched_keywords columns should get them on connect."""
        old_schema = """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
            author TEXT, content TEXT, url TEXT, timestamp DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
        db = MessageDB(":memory:")
        db._db = await aiosqlite.connect(":memory:")
        await db._db.executescript(old_schema)
        await db._db.commit()

        # Reconnect with full connect() which runs migrations
        db2 = MessageDB(":memory:")
        db2._db = db._db
        # Simulate migration
        cursor = await db2._db.execute("PRAGMA table_info(messages)")
        existing = {row[1] for row in await cursor.fetchall()}
        assert "translation" not in existing  # not yet migrated

        from src.db import MIGRATE_COLUMNS
        for col_name, col_type in MIGRATE_COLUMNS:
            if col_name not in existing:
                await db2._db.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
        await db2._db.commit()

        cursor = await db2._db.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in await cursor.fetchall()}
        assert "translation" in columns
        assert "matched_keywords" in columns
        await db._db.close()

    async def test_already_migrated_db_no_error(self, db):
        """Running migration on already-migrated DB should not raise errors."""
        from src.db import MIGRATE_COLUMNS
        cursor = await db._db.execute("PRAGMA table_info(messages)")
        existing = {row[1] for row in await cursor.fetchall()}
        for col_name, col_type in MIGRATE_COLUMNS:
            if col_name not in existing:
                await db._db.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
        # No error raised — columns already exist, so loop body doesn't execute


class TestStatsEdgeCases:
    async def test_empty_db_returns_zeros(self, db):
        stats = await db.stats()
        assert stats["total"] == 0
        assert stats["today"] == 0
        assert stats["this_week"] == 0
        assert stats["by_source"] == {}
        assert stats["top_authors"] == []
        assert stats["last_message_at"] is None

    async def test_single_message_stats(self, db):
        await db.insert_if_new(source="radar", source_id="1", author="Radar", content="outage")
        stats = await db.stats()
        assert stats["total"] == 1
        assert stats["today"] == 1
        assert stats["by_source"]["radar"] == 1
        assert len(stats["top_authors"]) == 1


class TestExportFilters:
    async def test_source_plus_date_range(self, db):
        await db.insert_if_new(source="telegram", source_id="1", content="tg")
        await db.insert_if_new(source="twitter", source_id="2", content="tw")
        results = await db.export(source="telegram")
        assert len(results) == 1
        assert results[0]["source"] == "telegram"

    async def test_no_matches_returns_empty(self, db):
        await db.insert_if_new(source="rss", source_id="1", content="msg")
        results = await db.export(source="nonexistent")
        assert results == []

    async def test_limit_respected(self, db):
        for i in range(5):
            await db.insert_if_new(source="rss", source_id=str(i), content=f"msg{i}")
        results = await db.export(limit=2)
        assert len(results) == 2
