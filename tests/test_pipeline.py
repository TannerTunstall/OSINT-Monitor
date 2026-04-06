import pytest
from unittest.mock import AsyncMock
from collections import deque

from src.processing.pipeline import Pipeline, _clean_html, _needs_translation, _truncate
from src.config import FilterConfig, SourceFilter
from src.sources.base import Message
from datetime import datetime, timezone
from tests.conftest import MockNotifier


class TestCleanHtml:
    def test_strips_tags(self):
        assert _clean_html("<b>bold</b> text") == "bold text"

    def test_unescapes_entities(self):
        assert _clean_html("&amp; &lt; &gt;") == "& < >"

    def test_collapses_newlines(self):
        assert _clean_html("a\n\n\n\nb") == "a\n\nb"

    def test_strips_whitespace(self):
        assert _clean_html("  hello  ") == "hello"


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("short", 100) == "short"

    def test_long_text_truncated(self):
        result = _truncate("a" * 200, 50)
        assert len(result) == 50
        assert result.endswith("...")


class TestNeedsTranslation:
    def test_empty_text(self):
        assert _needs_translation("") is False

    def test_english_text(self):
        assert _needs_translation("This is an English sentence") is False

    def test_arabic_text(self):
        assert _needs_translation("هذا نص باللغة العربية ويجب ترجمته") is True

    def test_mixed_text_below_threshold(self):
        # Mostly English with very few non-Latin chars (below 20% threshold)
        assert _needs_translation("Hello world and some more English text here مر") is False

    def test_cyrillic_text(self):
        assert _needs_translation("Это текст на русском языке для перевода") is True

    def test_cjk_text(self):
        assert _needs_translation("这是一段中文测试文本需要翻译") is True


class TestKeywordFiltering:
    def test_no_filter_passes_all(self):
        p = Pipeline.__new__(Pipeline)
        p.filters = None
        sf = p._get_filter_for_source("telegram")
        assert sf.include_keywords == []
        assert sf.exclude_keywords == []

    def test_word_match_whole_word(self):
        assert Pipeline._word_match("war", "the war began") is True
        assert Pipeline._word_match("war", "warning issued") is False

    def test_word_match_multi_word(self):
        assert Pipeline._word_match("data center", "the data center failed") is True

    def test_exclude_keyword_blocks(self):
        p = Pipeline.__new__(Pipeline)
        p.filters = FilterConfig(
            default=SourceFilter(exclude_keywords=["maintenance"]),
        )
        passes, _ = p._check_keywords("telegram", "scheduled maintenance tonight", "test-1")
        assert passes is False

    def test_include_keyword_passes(self):
        p = Pipeline.__new__(Pipeline)
        p.filters = FilterConfig(
            default=SourceFilter(include_keywords=["outage"]),
        )
        passes, matched = p._check_keywords("telegram", "major outage reported", "test-1")
        assert passes is True
        assert "outage" in matched

    def test_include_keyword_filters(self):
        p = Pipeline.__new__(Pipeline)
        p.filters = FilterConfig(
            default=SourceFilter(include_keywords=["outage"]),
        )
        passes, _ = p._check_keywords("telegram", "nothing interesting here", "test-1")
        assert passes is False


class TestSimilarity:
    def test_identical_texts(self):
        assert Pipeline._similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert Pipeline._similarity("alpha beta", "gamma delta") == 0.0

    def test_partial_overlap(self):
        sim = Pipeline._similarity("the cat sat", "the dog sat")
        assert 0.3 < sim < 0.8


class TestPipelineProcess:
    """Tests for the full message processing pipeline.
    Why: Bugs here = missed alerts or alert floods.
    """

    def _make_pipeline(self, notifier, db, filters=None):
        p = Pipeline(db=db, notifiers=[notifier], filters=filters, health=None, translation=None)
        return p

    async def test_new_message_sent_to_notifier(self, db, make_message):
        notifier = MockNotifier()
        p = self._make_pipeline(notifier, db)
        msg = make_message(source_id="new-1", content="Breaking: server down")
        await p.process(msg)
        assert len(notifier.sent) == 1
        assert "server down" in notifier.sent[0]

    async def test_duplicate_not_sent(self, db, make_message):
        notifier = MockNotifier()
        p = self._make_pipeline(notifier, db)
        msg = make_message(source_id="dup-1", content="Some event")
        await p.process(msg)
        await p.process(msg)  # same source_id
        assert len(notifier.sent) == 1  # only first one sent

    async def test_excluded_keyword_blocks(self, db, make_message):
        notifier = MockNotifier()
        filters = FilterConfig(default=SourceFilter(exclude_keywords=["maintenance"]))
        p = self._make_pipeline(notifier, db, filters=filters)
        msg = make_message(source_id="exc-1", content="Scheduled maintenance window tonight")
        await p.process(msg)
        assert len(notifier.sent) == 0

    async def test_include_keyword_passes_with_flag(self, db, make_message):
        notifier = MockNotifier()
        filters = FilterConfig(default=SourceFilter(include_keywords=["outage"]))
        p = self._make_pipeline(notifier, db, filters=filters)
        msg = make_message(source_id="inc-1", content="Major outage affecting all users")
        await p.process(msg)
        assert len(notifier.sent) == 1
        assert 'Flagged: "outage"' in notifier.sent[0]

    async def test_test_message_skips_similarity_dedup(self, db, make_message):
        """source_id starting with 'test-' should bypass Jaccard similarity check."""
        notifier = MockNotifier()
        p = self._make_pipeline(notifier, db)
        msg1 = make_message(source_id="test-1", content="TEST of delivery method working correctly")
        msg2 = make_message(source_id="test-2", content="TEST of delivery method working correctly")
        await p.process(msg1)
        await p.process(msg2)
        assert len(notifier.sent) == 2  # both sent despite identical content

    async def test_similarity_dedup_blocks_near_duplicate(self, db, make_message):
        notifier = MockNotifier()
        p = self._make_pipeline(notifier, db)
        msg1 = make_message(source_id="sim-1", content="AWS us-east-1 experiencing elevated error rates for EC2 instances")
        msg2 = make_message(source_id="sim-2", content="AWS us-east-1 experiencing elevated error rates for EC2 instances and Lambda")
        await p.process(msg1)
        await p.process(msg2)
        assert len(notifier.sent) == 1  # second suppressed as near-duplicate

    async def test_seed_does_not_notify(self, db, make_message):
        notifier = MockNotifier()
        p = self._make_pipeline(notifier, db)
        msg = make_message(source_id="seed-1", content="Existing message from before restart")
        await p.seed(msg)
        assert len(notifier.sent) == 0
        # But it should be in the DB
        results = await db.get_recent(limit=10)
        assert len(results) == 1
