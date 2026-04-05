from src.processing.pipeline import Pipeline, _clean_html, _needs_translation, _truncate
from src.config import FilterConfig, SourceFilter


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
        # Mostly English with a few Arabic chars
        assert _needs_translation("Hello world مرحبا end") is False

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
