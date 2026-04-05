import logging

import aiohttp

from src.config import WhatsAppConfig
from src.notifiers.base import Notifier
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)


class WhatsAppNotifier(Notifier):
    def __init__(self, config: WhatsAppConfig):
        self.config = config
        self._session: aiohttp.ClientSession | None = None

    async def ensure_session(self):
        """Wait for WAHA to be available, then ensure session is WORKING."""
        import asyncio
        api_url = self.config.api_url.rstrip("/")
        session_name = self.config.session_name

        # Wait for WAHA container to be reachable
        for attempt in range(30):
            try:
                session = self._get_session()
                async with session.get(f"{api_url}/api/sessions", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                pass
            if attempt < 29:
                logger.info("Waiting for WAHA to start... (attempt %d/30)", attempt + 1)
                await asyncio.sleep(2)
        else:
            logger.warning("WAHA not reachable after 60s — WhatsApp notifications may fail")
            return

        # Check session status
        try:
            session = self._get_session()
            async with session.get(f"{api_url}/api/sessions/{session_name}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get("status", "UNKNOWN")
                    logger.info("WAHA session '%s' status: %s", session_name, status)
                    if status == "WORKING":
                        return
                else:
                    status = "NOT_FOUND"

            # Session needs starting
            logger.info("WAHA session not active (%s), starting...", status)
            await session.post(f"{api_url}/api/sessions/stop", json={"name": session_name})
            await asyncio.sleep(1)
            async with session.post(f"{api_url}/api/sessions/start", json={"name": session_name}) as resp:
                body = await resp.text()
                logger.info("WAHA start response %d: %s", resp.status, body[:200])

            # Wait for session to reach WORKING
            for _ in range(15):
                await asyncio.sleep(2)
                async with session.get(f"{api_url}/api/sessions/{session_name}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        status = data.get("status", "UNKNOWN")
                        logger.info("WAHA session status: %s", status)
                        if status == "WORKING":
                            return
                        if status == "SCAN_QR_CODE":
                            logger.warning("WAHA needs QR pairing — pair via dashboard")
                            return

            logger.warning("WAHA session did not reach WORKING state")
        except Exception:
            logger.warning("Failed to check/start WAHA session — will retry on first send")

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @with_retry(max_retries=3, base_delay=2.0)
    async def _send_to_chat(self, chat_id: str, text: str) -> bool:
        session = self._get_session()
        url = f"{self.config.api_url.rstrip('/')}/api/sendText"
        payload = {
            "chatId": chat_id,
            "text": text,
            "session": self.config.session_name,
        }
        headers = {}
        if self.config.api_key:
            headers["X-Api-Key"] = self.config.api_key

        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status in (200, 201):
                return True
            body = await resp.text()
            logger.error("WhatsApp API error %d for %s: %s", resp.status, chat_id, body)
            if resp.status >= 500:
                raise RuntimeError(f"WhatsApp API server error: {resp.status}")
            return False

    async def send(self, text: str) -> bool:
        all_ok = True
        for chat_id in self.config.chat_ids:
            try:
                ok = await self._send_to_chat(chat_id, text)
                if not ok:
                    all_ok = False
            except Exception as exc:
                logger.error("Failed to send WhatsApp message to %s after retries: %s", chat_id, exc)
                all_ok = False
        return all_ok

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
