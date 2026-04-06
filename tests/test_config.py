import os
import tempfile

import pytest
import yaml

from src.config import (
    ConfigError, load_config, validate_config, is_config_empty,
    _substitute_env_vars, _parse_rss_feeds, _parse_webhook,
)


class TestValidateConfig:
    def test_valid_minimal_config(self, sample_config_dict):
        errors = validate_config(sample_config_dict)
        assert errors == []

    def test_empty_config(self):
        errors = validate_config({})
        assert errors == []  # empty config is valid (no sources = setup mode)

    def test_invalid_type(self):
        errors = validate_config("not a dict")
        assert len(errors) == 1
        assert "must be a YAML mapping" in errors[0]

    def test_telegram_missing_required_fields(self):
        cfg = {"sources": {"telegram": {}}}
        errors = validate_config(cfg)
        assert any("api_id" in e for e in errors)
        assert any("api_hash" in e for e in errors)
        assert any("channels" in e for e in errors)

    def test_telegram_valid(self):
        cfg = {
            "sources": {
                "telegram": {
                    "api_id": "12345",
                    "api_hash": "abc123",
                    "channels": ["@test"],
                }
            }
        }
        errors = validate_config(cfg)
        assert errors == []

    def test_twitter_missing_fields(self):
        cfg = {"sources": {"twitter": {}}}
        errors = validate_config(cfg)
        assert any("nitter_instances" in e for e in errors)
        assert any("accounts" in e for e in errors)

    def test_rss_feeds_missing_url(self):
        cfg = {"sources": {"rss_feeds": {"feeds": [{"label": "no url"}]}}}
        errors = validate_config(cfg)
        assert any("url" in e for e in errors)

    def test_aws_health_backward_compat(self):
        """Legacy aws_health key should be accepted."""
        cfg = {
            "sources": {
                "aws_health": {
                    "feeds": [{"url": "https://example.com/rss", "label": "Test"}]
                }
            }
        }
        errors = validate_config(cfg)
        assert errors == []

    def test_whatsapp_missing_fields(self):
        cfg = {"notifiers": {"whatsapp": {"enabled": True}}}
        errors = validate_config(cfg)
        assert any("api_url" in e for e in errors)
        assert any("chat_ids" in e for e in errors)

    def test_discord_missing_webhook_urls(self):
        cfg = {"notifiers": {"discord": {"enabled": True}}}
        errors = validate_config(cfg)
        assert any("webhook_urls" in e for e in errors)

    def test_email_missing_fields(self):
        cfg = {"notifiers": {"email": {"enabled": True}}}
        errors = validate_config(cfg)
        assert any("smtp_host" in e for e in errors)
        assert any("from_address" in e for e in errors)
        assert any("to_addresses" in e for e in errors)


class TestLoadConfig:
    def test_load_valid_config(self, sample_config_dict):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(sample_config_dict, f)
            f.flush()
            config = load_config(f.name)
            assert config.sources.rss_feeds is not None
            assert len(config.sources.rss_feeds.feeds) == 1
            assert config.notifiers.discord is not None
            assert config.notifiers.discord.enabled is True

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_env_var_substitution(self):
        os.environ["TEST_OSINT_VAR"] = "substituted_value"
        try:
            cfg = {
                "sources": {
                    "telegram": {
                        "api_id": "12345",
                        "api_hash": "${TEST_OSINT_VAR}",
                        "channels": ["@test"],
                    }
                },
                "notifiers": {},
            }
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                yaml.dump(cfg, f)
                f.flush()
                config = load_config(f.name)
                assert config.sources.telegram.api_hash == "substituted_value"
        finally:
            del os.environ["TEST_OSINT_VAR"]


class TestBackwardCompat:
    """Existing users with old config keys shouldn't break on upgrade."""

    def test_aws_health_key_parsed_as_rss_feeds(self):
        cfg = {
            "sources": {
                "aws_health": {
                    "feeds": [{"url": "https://status.aws.amazon.com/rss/all.rss", "label": "AWS"}]
                }
            },
            "notifiers": {},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(cfg, f)
            f.flush()
            config = load_config(f.name)
            assert config.sources.rss_feeds is not None
            assert config.sources.rss_feeds.feeds[0].label == "AWS"

    def test_region_filter_accepted_as_content_filter(self):
        raw = {"feeds": [{"url": "https://example.com/rss", "label": "Test", "region_filter": ["us-east-1"]}]}
        result = _parse_rss_feeds(raw)
        assert result.feeds[0].content_filter == ["us-east-1"]


class TestWebhookParsing:
    def test_string_urls_become_endpoints(self):
        raw = {"enabled": True, "urls": [
            "https://api.example.com/hook1",
            "https://api.example.com/hook2",
        ]}
        result = _parse_webhook(raw)
        assert len(result.urls) == 2
        assert result.urls[0].url == "https://api.example.com/hook1"
        assert result.urls[0].method == "POST"  # default

    def test_dict_urls_with_method_and_headers(self):
        raw = {"enabled": True, "urls": [
            {"url": "https://api.example.com/hook", "method": "PUT", "headers": {"X-Token": "abc"}}
        ]}
        result = _parse_webhook(raw)
        assert result.urls[0].method == "PUT"
        assert result.urls[0].headers == {"X-Token": "abc"}

    def test_mixed_string_and_dict(self):
        raw = {"enabled": True, "urls": [
            "https://simple.com/hook",
            {"url": "https://complex.com/hook", "method": "PUT"},
        ]}
        result = _parse_webhook(raw)
        assert len(result.urls) == 2
        assert result.urls[0].method == "POST"
        assert result.urls[1].method == "PUT"


class TestEnvVarSubstitution:
    def test_missing_var_stays_as_is(self):
        result = _substitute_env_vars("${DEFINITELY_NOT_SET_VAR}")
        assert result == "${DEFINITELY_NOT_SET_VAR}"

    def test_multiple_vars_in_one_string(self):
        os.environ["TEST_A"] = "hello"
        os.environ["TEST_B"] = "world"
        try:
            result = _substitute_env_vars("${TEST_A} ${TEST_B}")
            assert result == "hello world"
        finally:
            del os.environ["TEST_A"]
            del os.environ["TEST_B"]


class TestConfigErrorCollectsAll:
    def test_multiple_errors_reported_at_once(self):
        """Config with multiple problems should report all of them, not just the first."""
        cfg = {
            "sources": {"telegram": {}},  # missing api_id, api_hash, channels
            "notifiers": {"discord": {"enabled": True}},  # missing webhook_urls
        }
        errors = validate_config(cfg)
        assert len(errors) >= 4  # at least api_id, api_hash, channels, webhook_urls


class TestIsConfigEmpty:
    def test_empty_when_no_sources_or_notifiers(self):
        assert is_config_empty({}) is True
        assert is_config_empty({"sources": {}, "notifiers": {}}) is True

    def test_not_empty_with_sources(self):
        assert is_config_empty({"sources": {"rss_feeds": {"feeds": []}}}) is False
