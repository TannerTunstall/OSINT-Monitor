import asyncio
import logging
import time
from datetime import datetime

import aiohttp
import feedparser

from src.config import TwitterSourceConfig
from src.sources.base import Message, Source

logger = logging.getLogger(__name__)

# Deprioritize an instance after this many consecutive failures
MAX_CONSECUTIVE_FAILURES = 3
# How long to deprioritize a failed instance (seconds)
DEPRIORITIZE_DURATION = 3600  # 1 hour


class TwitterSource(Source):
    def __init__(self, config: TwitterSourceConfig):
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._healthy_instance: str | None = None
        # Track instance health: {url: {"failures": int, "deprioritized_until": float}}
        self._instance_health: dict[str, dict] = {}
        # Clean account names: strip @, whitespace, leading slashes
        self.config.accounts = [
            a.strip().lstrip("@").strip("/")
            for a in self.config.accounts if a.strip()
        ]

    async def start(self):
        self._session = aiohttp.ClientSession(headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        })
        for instance in self.config.nitter_instances:
            self._instance_health[instance] = {"failures": 0, "deprioritized_until": 0}
        logger.info(
            "Twitter source started: %d account(s) %s, %d Nitter instance(s)",
            len(self.config.accounts),
            self.config.accounts,
            len(self.config.nitter_instances),
        )

    def _get_sorted_instances(self) -> list[str]:
        """Return instances sorted by health: healthy first, deprioritized last."""
        now = time.monotonic()
        available = []
        deprioritized = []

        for instance in self.config.nitter_instances:
            health = self._instance_health.get(instance, {"failures": 0, "deprioritized_until": 0})
            if health["deprioritized_until"] > now:
                deprioritized.append(instance)
            else:
                available.append(instance)

        # Put the last known healthy instance first
        if self._healthy_instance and self._healthy_instance in available:
            available = [self._healthy_instance] + [i for i in available if i != self._healthy_instance]

        return available + deprioritized

    def _record_instance_failure(self, instance: str):
        health = self._instance_health.setdefault(instance, {"failures": 0, "deprioritized_until": 0})
        health["failures"] += 1
        if health["failures"] >= MAX_CONSECUTIVE_FAILURES:
            health["deprioritized_until"] = time.monotonic() + DEPRIORITIZE_DURATION
            logger.warning("[TWITTER] Deprioritizing %s for %d seconds after %d consecutive failures",
                           instance, DEPRIORITIZE_DURATION, health["failures"])

    def _record_instance_success(self, instance: str):
        self._instance_health[instance] = {"failures": 0, "deprioritized_until": 0}
        self._healthy_instance = instance

    async def _fetch_nitter_rss(self, account: str) -> list[Message]:
        """Try each Nitter instance until one works."""
        instances = self._get_sorted_instances()

        for instance in instances:
            base = instance.rstrip("/")
            url = f"{base}/{account}/rss"
            try:
                req_headers = {"Accept": "application/rss+xml, application/xml, text/xml"}
                async with self._session.get(url, headers=req_headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.warning("[TWITTER] Nitter %s returned %d for @%s", base, resp.status, account)
                        self._record_instance_failure(instance)
                        continue
                    text = await resp.text()

                parsed = feedparser.parse(text)
                if not parsed.entries:
                    logger.warning("[TWITTER] Nitter %s empty feed for @%s. Starts: %s", base, account, text[:200])
                    self._record_instance_failure(instance)
                    continue

                self._record_instance_success(instance)
                messages = []
                for entry in parsed.entries:
                    entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
                    published = entry.get("published_parsed")
                    ts = datetime(*published[:6]) if published else None

                    content = entry.get("title", "") or entry.get("summary", "")

                    # Convert nitter link to x.com link for the notification
                    link = entry.get("link", "")
                    if link and "nitter" in link:
                        link = link.split("#")[0]  # remove #m fragment
                        # Extract /username/status/id from nitter URL
                        parts = link.replace(base, "").strip("/")
                        link = f"https://x.com/{parts}"

                    msg = Message(
                        source="twitter",
                        source_id=entry_id,
                        author=f"@{account}",
                        content=content,
                        url=link or None,
                        timestamp=ts,
                    )
                    messages.append(msg)

                logger.debug("[TWITTER] Fetched %d tweets for @%s from %s", len(messages), account, base)
                return messages

            except asyncio.TimeoutError:
                logger.warning("[TWITTER] Nitter %s timed out for @%s", base, account)
                self._record_instance_failure(instance)
            except Exception:
                logger.exception("Nitter %s error for @%s", base, account)
                self._record_instance_failure(instance)

        logger.warning("[TWITTER] All Nitter instances failed for @%s", account)
        return []

    async def poll(self) -> list[Message]:
        logger.debug("[TWITTER] Polling %d account(s)...", len(self.config.accounts))
        all_messages = []
        for account in self.config.accounts:
            messages = await self._fetch_nitter_rss(account)
            all_messages.extend(messages)
        all_messages.sort(key=lambda m: m.timestamp or datetime.min)
        logger.info("[TWITTER] Poll complete: %d tweets from %d accounts", len(all_messages), len(self.config.accounts))
        return all_messages

    async def stop(self):
        if self._session:
            await self._session.close()
