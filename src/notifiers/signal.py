import logging

import aiohttp

from src.config import SignalConfig
from src.notifiers.base import Notifier
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)


class SignalNotifier(Notifier):
    def __init__(self, config: SignalConfig):
        self.config = config
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @with_retry(max_retries=3, base_delay=2.0)
    async def _send_to_recipient(self, recipient: str, text: str) -> bool:
        session = self._get_session()
        url = f"{self.config.api_url.rstrip('/')}/v2/send"
        payload = {
            "message": text,
            "number": self.config.sender,
            "recipients": [recipient],
        }
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status in (200, 201):
                return True
            body = await resp.text()
            logger.error("Signal API error %d for %s: %s", resp.status, recipient, body)
            if resp.status >= 500:
                raise RuntimeError(f"Signal API server error: {resp.status}")
            return False

    async def send(self, text: str) -> bool:
        all_ok = True
        for recipient in self.config.recipients:
            try:
                ok = await self._send_to_recipient(recipient, text)
                if not ok:
                    all_ok = False
            except Exception:
                logger.exception("Failed to send Signal message to %s", recipient)
                all_ok = False
        return all_ok

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
