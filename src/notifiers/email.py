import logging
from email.message import EmailMessage

from src.config import EmailConfig
from src.notifiers.base import Notifier
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    def __init__(self, config: EmailConfig):
        self.config = config

    @with_retry(max_retries=3, base_delay=5.0)
    async def _send_email(self, text: str) -> bool:
        try:
            import aiosmtplib
        except ImportError:
            logger.error("aiosmtplib not installed. Install with: pip install osint-monitor[email]")
            return False

        msg = EmailMessage()
        msg["From"] = self.config.from_address
        msg["To"] = ", ".join(self.config.to_addresses)
        msg["Subject"] = f"{self.config.subject_prefix} {text[:80]}"
        msg.set_content(text)

        await aiosmtplib.send(
            msg,
            hostname=self.config.smtp_host,
            port=self.config.smtp_port,
            start_tls=self.config.use_tls,
            username=self.config.username or None,
            password=self.config.password or None,
            timeout=30,
        )
        return True

    async def send(self, text: str) -> bool:
        try:
            return await self._send_email(text)
        except Exception:
            logger.exception("Failed to send email notification")
            return False

    async def close(self):
        pass
