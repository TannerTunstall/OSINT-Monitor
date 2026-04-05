import logging
from datetime import datetime

import aiohttp
import feedparser

from src.config import RSSFeedsConfig
from src.sources.base import Message, Source

logger = logging.getLogger(__name__)


class RSSSource(Source):
    """Polls RSS/Atom feeds and emits normalized messages."""

    def __init__(self, config: RSSFeedsConfig):
        self.config = config
        self._session: aiohttp.ClientSession | None = None

    async def start(self):
        self._session = aiohttp.ClientSession()
        logger.info("[RSS] Source started with %d feed(s)", len(self.config.feeds))

    async def poll(self) -> list[Message]:
        logger.debug("[RSS] Polling %d feed(s)...", len(self.config.feeds))
        messages = []
        for feed_cfg in self.config.feeds:
            try:
                async with self._session.get(feed_cfg.url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        logger.warning("[RSS] %s returned HTTP %d", feed_cfg.label, resp.status)
                        continue
                    text = await resp.text()

                parsed = feedparser.parse(text)
                total = len(parsed.entries)
                matched = 0

                for entry in parsed.entries:
                    if feed_cfg.content_filter:
                        entry_text = (
                            entry.get("title", "") + " " + entry.get("summary", "")
                        ).lower()
                        if not any(rf.lower() in entry_text for rf in feed_cfg.content_filter):
                            continue

                    matched += 1
                    entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
                    published = entry.get("published_parsed")
                    ts = datetime(*published[:6]) if published else None

                    msg = Message(
                        source="rss",
                        source_id=entry_id,
                        author=feed_cfg.label,
                        content=entry.get("title", ""),
                        url=entry.get("link"),
                        timestamp=ts,
                    )
                    messages.append(msg)

                if feed_cfg.content_filter:
                    logger.debug("[RSS] %s: %d entries, %d matched content filter", feed_cfg.label, total, matched)
                else:
                    logger.debug("[RSS] %s: %d entries", feed_cfg.label, total)

            except Exception:
                logger.exception("[RSS] Error fetching feed: %s", feed_cfg.label)

        logger.info("[RSS] Poll complete: %d entries from %d feeds", len(messages), len(self.config.feeds))

        return messages

    async def stop(self):
        if self._session:
            await self._session.close()


# Backward-compatible alias
AWSHealthSource = RSSSource
