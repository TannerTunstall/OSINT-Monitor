import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    author TEXT,
    content TEXT,
    url TEXT,
    timestamp DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    translation TEXT,
    matched_keywords TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_source ON messages(source);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
"""

MIGRATE_COLUMNS = [
    ("translation", "TEXT"),
    ("matched_keywords", "TEXT"),
]


class MessageDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(SCHEMA)
        # Migrate existing databases: add new columns if missing
        cursor = await self._db.execute("PRAGMA table_info(messages)")
        existing = {row[1] for row in await cursor.fetchall()}
        for col_name, col_type in MIGRATE_COLUMNS:
            if col_name not in existing:
                await self._db.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def insert_if_new(
        self,
        source: str,
        source_id: str,
        author: str | None = None,
        content: str | None = None,
        url: str | None = None,
        timestamp: datetime | None = None,
        translation: str | None = None,
        matched_keywords: str | None = None,
    ) -> bool:
        """Insert a message if it doesn't already exist. Returns True if inserted (new)."""
        msg_id = f"{source}:{source_id}"
        try:
            await self._db.execute(
                "INSERT INTO messages (id, source, source_id, author, content, url, timestamp, translation, matched_keywords) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (msg_id, source, source_id, author, content, url, timestamp, translation, matched_keywords),
            )
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def update_enrichment(self, source: str, source_id: str, translation: str | None, matched_keywords: str | None):
        """Update translation and matched_keywords after processing."""
        msg_id = f"{source}:{source_id}"
        await self._db.execute(
            "UPDATE messages SET translation = ?, matched_keywords = ? WHERE id = ?",
            (translation, matched_keywords, msg_id),
        )
        await self._db.commit()

    async def get_recent(self, limit: int = 100, source: str | None = None) -> list[dict]:
        """Get recent messages from the cache, optionally filtered by source."""
        if source:
            cursor = await self._db.execute(
                "SELECT source, source_id, author, content, url, timestamp, created_at, translation, matched_keywords "
                "FROM messages WHERE source = ? ORDER BY created_at DESC LIMIT ?",
                (source, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT source, source_id, author, content, url, timestamp, created_at, translation, matched_keywords "
                "FROM messages ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [
            {
                "source": r[0], "source_id": r[1], "author": r[2],
                "content": r[3], "url": r[4], "timestamp": r[5], "created_at": r[6],
                "translation": r[7], "matched_keywords": r[8],
            }
            for r in rows
        ]

    async def search(
        self,
        query: str | None = None,
        source: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Search messages with optional text query and source filter. Returns (messages, total_count)."""
        conditions = []
        params = []

        if source:
            conditions.append("source = ?")
            params.append(source)
        if query:
            like = f"%{query}%"
            conditions.append("(content LIKE ? OR author LIKE ? OR translation LIKE ? OR matched_keywords LIKE ?)")
            params.extend([like, like, like, like])

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        # Get total count
        count_cursor = await self._db.execute(f"SELECT COUNT(*) FROM messages{where}", params)
        total = (await count_cursor.fetchone())[0]

        # Get paginated results
        params.extend([limit, offset])
        cursor = await self._db.execute(
            f"SELECT source, source_id, author, content, url, timestamp, created_at, translation, matched_keywords "
            f"FROM messages{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cursor.fetchall()
        messages = [
            {
                "source": r[0], "source_id": r[1], "author": r[2],
                "content": r[3], "url": r[4], "timestamp": r[5], "created_at": r[6],
                "translation": r[7], "matched_keywords": r[8],
            }
            for r in rows
        ]
        return messages, total

    async def export(
        self,
        source: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 10000,
    ) -> list[dict]:
        """Export messages with optional source and date range filters."""
        conditions = []
        params = []
        if source:
            conditions.append("source = ?")
            params.append(source)
        if start:
            conditions.append("created_at >= ?")
            params.append(start)
        if end:
            conditions.append("created_at <= ?")
            params.append(end)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        cursor = await self._db.execute(
            f"SELECT source, source_id, author, content, url, timestamp, created_at, translation, matched_keywords "
            f"FROM messages{where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [
            {
                "source": r[0], "source_id": r[1], "author": r[2],
                "content": r[3], "url": r[4], "timestamp": r[5], "created_at": r[6],
                "translation": r[7], "matched_keywords": r[8],
            }
            for r in rows
        ]

    async def stats(self) -> dict:
        """Get analytics data: message counts, volume by hour, source breakdown."""
        result = {}

        # Total count
        cursor = await self._db.execute("SELECT COUNT(*) FROM messages")
        result["total"] = (await cursor.fetchone())[0]

        # Today count
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM messages WHERE created_at >= date('now')"
        )
        result["today"] = (await cursor.fetchone())[0]

        # This week count
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM messages WHERE created_at >= date('now', '-7 days')"
        )
        result["this_week"] = (await cursor.fetchone())[0]

        # Per-source counts
        cursor = await self._db.execute(
            "SELECT source, COUNT(*) FROM messages GROUP BY source ORDER BY COUNT(*) DESC"
        )
        result["by_source"] = {r[0]: r[1] for r in await cursor.fetchall()}

        # Most recent message timestamp
        cursor = await self._db.execute(
            "SELECT created_at FROM messages ORDER BY created_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        result["last_message_at"] = row[0] if row else None

        # Volume per hour for last 7 days (for area chart)
        cursor = await self._db.execute(
            "SELECT strftime('%Y-%m-%d %H:00', created_at) as hour, source, COUNT(*) "
            "FROM messages WHERE created_at >= datetime('now', '-7 days') "
            "GROUP BY hour, source ORDER BY hour"
        )
        hourly = {}
        for hour, source, count in await cursor.fetchall():
            if hour not in hourly:
                hourly[hour] = {}
            hourly[hour][source] = count
        result["hourly"] = hourly

        # Volume per hour for last 24h (for detailed view)
        cursor = await self._db.execute(
            "SELECT strftime('%Y-%m-%d %H:00', created_at) as hour, source, COUNT(*) "
            "FROM messages WHERE created_at >= datetime('now', '-1 day') "
            "GROUP BY hour, source ORDER BY hour"
        )
        hourly_24h = {}
        for hour, source, count in await cursor.fetchall():
            if hour not in hourly_24h:
                hourly_24h[hour] = {}
            hourly_24h[hour][source] = count
        result["hourly_24h"] = hourly_24h

        # Volume per day for last 30 days (for bar chart)
        cursor = await self._db.execute(
            "SELECT date(created_at) as day, source, COUNT(*) "
            "FROM messages WHERE created_at >= datetime('now', '-30 days') "
            "GROUP BY day, source ORDER BY day"
        )
        daily = {}
        for day, source, count in await cursor.fetchall():
            if day not in daily:
                daily[day] = {}
            daily[day][source] = count
        result["daily"] = daily

        # Top authors
        cursor = await self._db.execute(
            "SELECT author, source, COUNT(*) FROM messages "
            "WHERE author IS NOT NULL GROUP BY author ORDER BY COUNT(*) DESC LIMIT 15"
        )
        result["top_authors"] = [
            {"author": r[0], "source": r[1], "count": r[2]} for r in await cursor.fetchall()
        ]

        return result

    async def cleanup(self, retention_days: int):
        """Delete messages older than retention_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        await self._db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff.isoformat(),))
        await self._db.commit()
