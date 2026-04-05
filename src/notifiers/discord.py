import logging

import aiohttp

from src.config import DiscordConfig
from src.notifiers.base import Notifier
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

DISCORD_MAX_LENGTH = 2000


class DiscordNotifier(Notifier):
    def __init__(self, config: DiscordConfig):
        self.config = config
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @with_retry(max_retries=3, base_delay=2.0)
    async def _send_to_webhook(self, url: str, text: str) -> bool:
        session = self._get_session()
        payload = {"content": text[:DISCORD_MAX_LENGTH]}
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status in (200, 204):
                return True
            body = await resp.text()
            logger.error("Discord webhook error %d: %s", resp.status, body[:200])
            if resp.status == 429 or resp.status >= 500:
                raise RuntimeError(f"Discord webhook error: {resp.status}")
            return False

    async def send(self, text: str) -> bool:
        all_ok = True
        for url in self.config.webhook_urls:
            try:
                ok = await self._send_to_webhook(url, text)
                if not ok:
                    all_ok = False
            except Exception:
                logger.exception("Failed to send Discord webhook")
                all_ok = False
        return all_ok

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
