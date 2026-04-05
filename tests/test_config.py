import os
import tempfile

import pytest
import yaml

from src.config import ConfigError, load_config, validate_config


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
