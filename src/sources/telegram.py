import logging
from datetime import datetime, timezone

from telethon import TelegramClient

from src.config import TelegramSourceConfig
from src.sources.base import Message, Source

logger = logging.getLogger(__name__)


class TelegramSource(Source):
    def __init__(self, config: TelegramSourceConfig):
        self.config = config
        self._client: TelegramClient | None = None
        self._channel_entities = []

    async def start(self):
        self._client = TelegramClient(
            f"session/{self.config.session_name}",
            self.config.api_id,
            self.config.api_hash,
        )
        await self._client.start()

        for ch in self.config.channels:
            try:
                entity = await self._client.get_entity(ch)
                self._channel_entities.append(entity)
                logger.info("Monitoring Telegram channel: %s (id=%s)", getattr(entity, 'title', ch), entity.id)
            except Exception:
                logger.exception("Failed to resolve Telegram channel: %s", ch)

        if not self._channel_entities:
            logger.warning("No Telegram channels resolved successfully")

        logger.info("Telegram source started (polling mode), monitoring %d channel(s)", len(self._channel_entities))

    @staticmethod
    def _describe_content(tg_msg) -> str:
        text = tg_msg.text or ""
        media_label = ""
        if tg_msg.photo:
            media_label = "[Photo]"
        elif tg_msg.video:
            media_label = "[Video]"
        elif tg_msg.document:
            media_label = "[Document]"
        elif tg_msg.sticker:
            media_label = "[Sticker]"
        elif tg_msg.gif:
            media_label = "[GIF]"
        elif tg_msg.voice:
            media_label = "[Voice message]"
        elif tg_msg.audio:
            media_label = "[Audio]"
        elif tg_msg.poll:
            media_label = "[Poll]"
        elif tg_msg.contact:
            media_label = "[Contact]"
        elif tg_msg.geo:
            media_label = "[Location]"
        elif not text:
            media_label = "[Media]"

        if text and media_label:
            return f"{media_label} {text}"
        return text or media_label

    @staticmethod
    def _make_link(chat, msg_id: int) -> str:
        username = getattr(chat, 'username', None)
        if username:
            return f"https://t.me/{username}/{msg_id}"
        chat_id = getattr(chat, 'id', 0)
        return f"https://t.me/c/{abs(chat_id)}/{msg_id}"

    async def poll(self) -> list[Message]:
        logger.debug("[TELEGRAM] Polling %d channel(s)...", len(self._channel_entities))
        messages = []
        for entity in self._channel_entities:
            ch_name = getattr(entity, 'title', str(entity.id))
            try:
                count = 0
                async for tg_msg in self._client.iter_messages(entity, limit=10):
                    chat_title = ch_name
                    sender = await tg_msg.get_sender() if tg_msg.sender_id else None
                    author = None
                    if sender:
                        author = getattr(sender, 'username', None) or getattr(sender, 'first_name', None)

                    msg = Message(
                        source="telegram",
                        source_id=str(tg_msg.id),
                        author=f"{chat_title}" + (f" / {author}" if author else ""),
                        content=self._describe_content(tg_msg),
                        url=self._make_link(entity, tg_msg.id),
                        timestamp=tg_msg.date.replace(tzinfo=timezone.utc) if tg_msg.date else None,
                    )
                    messages.append(msg)
                    count += 1
                logger.debug("[TELEGRAM] Fetched %d messages from %s", count, ch_name)
            except Exception:
                logger.exception("[TELEGRAM] Error polling channel: %s", ch_name)

        logger.info("[TELEGRAM] Poll complete: %d messages from %d channels", len(messages), len(self._channel_entities))
        messages.sort(key=lambda m: m.timestamp or datetime.min)
        return messages

    async def stop(self):
        if self._client:
            await self._client.disconnect()
            logger.info("Telegram source stopped")
