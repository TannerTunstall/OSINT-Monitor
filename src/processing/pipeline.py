import html
import logging
import re
from collections import deque

import aiohttp

from src.config import FilterConfig, SourceFilter, TranslationConfig
from src.db import MessageDB
from src.health import HealthRegistry
from src.notifiers.base import Notifier
from src.sources.base import Message

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 2000

HTML_TAG_RE = re.compile(r"<[^>]+>")
# Matches non-Latin scripts: Arabic, Persian, CJK, Cyrillic, Devanagari, Thai, etc.
NON_LATIN_RE = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF"  # Arabic/Persian
    r"\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF"                  # CJK/Japanese
    r"\u0400-\u04FF"                                              # Cyrillic
    r"\u0900-\u097F"                                              # Devanagari
    r"\u0E00-\u0E7F"                                              # Thai
    r"\uAC00-\uD7AF]"                                             # Korean
)


def _clean_html(text: str) -> str:
    text = HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _needs_translation(text: str) -> bool:
    """Check if text contains significant non-Latin characters that may need translation."""
    if not text:
        return False
    non_latin_chars = len(NON_LATIN_RE.findall(text))
    non_space = len(text.replace(" ", "").replace("\n", ""))
    if non_space == 0:
        return False
    return (non_latin_chars / non_space) > 0.2


class Pipeline:
    def __init__(
        self,
        db: MessageDB,
        notifiers: list[Notifier],
        filters: FilterConfig | None = None,
        health: HealthRegistry | None = None,
        translation: TranslationConfig | None = None,
    ):
        self.db = db
        self.notifiers = notifiers
        self.filters = filters
        self.health = health
        self.translation = translation
        self._translate_session: aiohttp.ClientSession | None = None
        self._recent_texts: deque = deque(maxlen=50)

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """Jaccard similarity on word sets."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)

    def _is_duplicate_content(self, text: str, source_id: str, author: str) -> bool:
        """Check if text is too similar to any recently sent message."""
        for prev_text, prev_author in self._recent_texts:
            sim = self._similarity(text, prev_text)
            if sim > 0.6:
                logger.info("[DEDUP] Suppressed %s — %.0f%% similar to recent message from %s", source_id, sim * 100, prev_author)
                return True
        return False

    def _get_filter_for_source(self, source: str) -> SourceFilter:
        """Get the keyword filter for a specific source, falling back to default."""
        if not self.filters:
            return SourceFilter()
        if source in self.filters.per_source:
            return self.filters.per_source[source]
        return self.filters.default

    @staticmethod
    def _word_match(keyword: str, text: str) -> bool:
        """Whole-word match. Multi-word keywords use substring match (e.g. 'data center')."""
        pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
        return bool(re.search(pattern, text))

    def _check_keywords(self, source: str, text: str, source_id: str) -> tuple[bool, list[str]]:
        """Check text against source-specific keywords using whole-word matching.
        Returns (passes, matched_keywords)."""
        sf = self._get_filter_for_source(source)
        text_lower = text.lower()

        # Check excludes first
        if sf.exclude_keywords:
            for kw in sf.exclude_keywords:
                if self._word_match(kw, text_lower):
                    logger.info("Excluded: keyword '%s' matched in %s message %s", kw, source, source_id)
                    return False, []

        # Check includes
        if sf.include_keywords:
            matched = [kw for kw in sf.include_keywords if self._word_match(kw, text_lower)]
            if matched:
                logger.info("Keyword match: %s found in %s message %s", matched, source, source_id)
                return True, matched
            else:
                logger.info("Filtered out: no keyword match for %s message %s", source, source_id)
                return False, []

        # No include filter = forward everything
        logger.debug("No keyword filter for %s — forwarding", source)
        return True, []

    async def _detect_language(self, text: str) -> str | None:
        """Use LibreTranslate /detect to identify the language of text."""
        try:
            if self._translate_session is None or self._translate_session.closed:
                self._translate_session = aiohttp.ClientSession()

            url = f"{self.translation.api_url.rstrip('/')}/detect"
            payload = {"q": text[:500]}  # Short sample is enough for detection

            async with self._translate_session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and isinstance(data, list) and len(data) > 0:
                        lang = data[0].get("language")
                        confidence = data[0].get("confidence", 0)
                        logger.debug("Language detection: %s (confidence: %.2f)", lang, confidence)
                        return lang
                else:
                    logger.debug("Language detection failed: HTTP %d", resp.status)
        except Exception as exc:
            logger.debug("Language detection error: %s", exc)
        return None

    async def _translate(self, text: str) -> str | None:
        if not self.translation or not self.translation.enabled:
            return None
        if not text or not text.strip():
            return None

        # Use LibreTranslate's /detect to check if text is already in target language
        detected = await self._detect_language(text)
        if detected and detected == self.translation.target_language:
            logger.debug("Text already in target language (%s), skipping translation", detected)
            return None

        # Fallback: if detection fails, use character-based heuristic
        if detected is None and not _needs_translation(text):
            return None

        logger.info("Translation: detected %s text, translating to %s...",
                     detected or "non-target-language", self.translation.target_language)
        try:
            if self._translate_session is None or self._translate_session.closed:
                self._translate_session = aiohttp.ClientSession()

            url = f"{self.translation.api_url.rstrip('/')}/translate"
            payload = {
                "q": text[:2000],
                "source": "auto",
                "target": self.translation.target_language,
                "format": "text",
            }
            logger.info("Translation: POST %s", url)

            async with self._translate_session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    translated = data.get("translatedText", "")
                    if translated and translated != text:
                        logger.info("Translation: success (%d chars → %d chars)", len(text), len(translated))
                        return translated
                    else:
                        logger.warning("Translation: API returned same text or empty result")
                else:
                    body = await resp.text()
                    logger.warning("Translation: API returned %d: %s", resp.status, body[:300])
        except aiohttp.ClientError as exc:
            logger.warning("Translation: cannot reach LibreTranslate at %s: %s", self.translation.api_url, exc)
        except Exception:
            logger.exception("Translation: unexpected error")

        return None

    def _format_message(self, msg: Message, translation: str | None, matched_keywords: list[str]) -> str:
        content = _clean_html(msg.content) if msg.content else ""

        parts = [f"[{msg.source.upper()}]"]
        if msg.author:
            parts.append(f" {msg.author}")

        if matched_keywords:
            kw_str = ", ".join(f'"{kw}"' for kw in matched_keywords)
            parts.append(f"\nFlagged: {kw_str}")

        if translation:
            parts.append(f"\n\n{_truncate(translation, 1200)}")
            parts.append(f"\n\n[Original]\n{_truncate(content, 600)}")
        else:
            parts.append(f"\n{_truncate(content)}")

        if msg.url:
            parts.append(f"\n{msg.url}")
        if msg.timestamp:
            parts.append(f"\n{msg.timestamp.strftime('%Y-%m-%d %H:%M UTC')}")

        return _truncate("".join(parts))

    async def seed(self, msg: Message):
        await self.db.insert_if_new(
            source=msg.source,
            source_id=msg.source_id,
            author=msg.author,
            content=msg.content,
            url=msg.url,
            timestamp=msg.timestamp,
        )

    async def process(self, msg: Message):
        is_new = await self.db.insert_if_new(
            source=msg.source,
            source_id=msg.source_id,
            author=msg.author,
            content=msg.content,
            url=msg.url,
            timestamp=msg.timestamp,
        )
        if not is_new:
            return

        # Log the new message
        preview = (msg.content or "")[:80].replace("\n", " ")
        logger.info("New %s message from %s: %s", msg.source, msg.author or "unknown", preview)

        # Step 1: Translate (if non-target-language)
        content = _clean_html(msg.content) if msg.content else ""
        translation = await self._translate(content)

        # Store translation immediately — always available in exports for data collection
        if translation:
            await self.db.update_enrichment(msg.source, msg.source_id, translation, None)

        # Step 2: Filter against ENGLISH text (translated or original)
        filter_text = translation or content
        passes, matched_keywords = self._check_keywords(msg.source, filter_text, msg.source_id)
        if not passes:
            return

        # Step 3: Content similarity dedup (skip for test messages)
        if not msg.source_id.startswith("test-") and self._is_duplicate_content(filter_text, msg.source_id, msg.author or "unknown"):
            return

        # Store matched keywords alongside translation
        if matched_keywords:
            kw_str = ", ".join(matched_keywords)
            await self.db.update_enrichment(msg.source, msg.source_id, translation, kw_str)

        # Step 4: Format and send
        self._recent_texts.append((filter_text, msg.author or "unknown"))
        text = self._format_message(msg, translation, matched_keywords)

        for notifier in self.notifiers:
            name = notifier.__class__.__name__
            try:
                success = await notifier.send(text)
                if success:
                    if self.health:
                        h = self.health.get(name.replace("Notifier", ""))
                        if h:
                            h.record_success(1)
                else:
                    logger.warning("Notifier %s failed to send", name)
                    if self.health:
                        h = self.health.get(name.replace("Notifier", ""))
                        if h:
                            h.record_error("Send failed")
            except Exception as exc:
                logger.exception("Error sending via %s", name)
                if self.health:
                    h = self.health.get(name.replace("Notifier", ""))
                    if h:
                        h.record_error(str(exc))

    async def close(self):
        if self._translate_session and not self._translate_session.closed:
            await self._translate_session.close()
