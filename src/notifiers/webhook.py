import logging

import aiohttp

from src.config import WebhookConfig, WebhookEndpoint
from src.notifiers.base import Notifier
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)


class WebhookNotifier(Notifier):
    def __init__(self, config: WebhookConfig):
        self.config = config
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @with_retry(max_retries=3, base_delay=2.0)
    async def _send_to_endpoint(self, endpoint: WebhookEndpoint, text: str) -> bool:
        session = self._get_session()
        url = endpoint.url
        method = endpoint.method.upper()
        headers = endpoint.headers
        body_template = endpoint.body_template
        body = body_template.replace("{message}", text.replace('"', '\\"').replace("\n", "\\n"))

        async with session.request(
            method, url,
            data=body,
            headers={"Content-Type": "application/json", **headers},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if 200 <= resp.status < 300:
                return True
            resp_body = await resp.text()
            logger.error("Webhook error %d for %s: %s", resp.status, url, resp_body[:200])
            if resp.status == 429 or resp.status >= 500:
                raise RuntimeError(f"Webhook error: {resp.status}")
            return False

    async def send(self, text: str) -> bool:
        all_ok = True
        for endpoint in self.config.urls:
            try:
                ok = await self._send_to_endpoint(endpoint, text)
                if not ok:
                    all_ok = False
            except Exception:
                logger.exception("Failed to send webhook to %s", endpoint.url)
                all_ok = False
        return all_ok

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
