import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class TelegramSourceConfig:
    api_id: int
    api_hash: str
    session_name: str
    channels: list[str | int]


@dataclass
class TwitterSourceConfig:
    method: str
    nitter_instances: list[str]
    accounts: list[str]


@dataclass
class RSSFeed:
    url: str
    label: str
    content_filter: list[str] = field(default_factory=list)


# Backward-compatible alias
AWSFeed = RSSFeed


@dataclass
class RSSFeedsConfig:
    feeds: list[RSSFeed]


# Backward-compatible alias
AWSHealthConfig = RSSFeedsConfig


@dataclass
class RadarConfig:
    enabled: bool = False
    api_token: str = ""
    countries: dict[str, str] = field(default_factory=dict)


@dataclass
class SourcesConfig:
    telegram: TelegramSourceConfig | None = None
    twitter: TwitterSourceConfig | None = None
    rss_feeds: RSSFeedsConfig | None = None
    radar: RadarConfig | None = None


@dataclass
class SignalConfig:
    enabled: bool
    api_url: str
    sender: str
    recipients: list[str]


@dataclass
class WhatsAppConfig:
    enabled: bool
    api_url: str
    session_name: str
    chat_ids: list[str]
    api_key: str | None = None


@dataclass
class DiscordConfig:
    enabled: bool
    webhook_urls: list[str]


@dataclass
class SlackConfig:
    enabled: bool
    webhook_urls: list[str]


@dataclass
class EmailConfig:
    enabled: bool
    smtp_host: str
    smtp_port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    from_address: str = ""
    to_addresses: list[str] = field(default_factory=list)
    subject_prefix: str = "[OSINT Monitor]"


@dataclass
class WebhookEndpoint:
    url: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    body_template: str = '{"message": "{message}"}'


@dataclass
class WebhookConfig:
    enabled: bool
    urls: list[WebhookEndpoint] = field(default_factory=list)


@dataclass
class NotifiersConfig:
    signal: SignalConfig | None = None
    whatsapp: WhatsAppConfig | None = None
    discord: DiscordConfig | None = None
    slack: SlackConfig | None = None
    email: EmailConfig | None = None
    webhook: WebhookConfig | None = None


@dataclass
class PollingConfig:
    telegram_interval_seconds: int = 30
    twitter_interval_seconds: int = 300
    rss_feeds_interval_seconds: int = 120
    radar_interval_seconds: int = 300


@dataclass
class DatabaseConfig:
    path: str = "data/messages.db"
    retention_days: int = 90


@dataclass
class SourceFilter:
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)


@dataclass
class FilterConfig:
    default: SourceFilter = field(default_factory=SourceFilter)
    per_source: dict[str, SourceFilter] = field(default_factory=dict)


@dataclass
class TranslationConfig:
    enabled: bool = False
    api_url: str = "http://translate:5000"
    target_language: str = "en"


@dataclass
class AppConfig:
    sources: SourcesConfig
    notifiers: NotifiersConfig
    polling: PollingConfig = field(default_factory=PollingConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    log_level: str = "INFO"


ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


class ConfigError(Exception):
    """Raised when config validation fails. Contains a list of human-readable error messages."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Config validation failed: {'; '.join(errors)}")


def validate_config(raw: dict) -> list[str]:
    """Validate raw config dict and return a list of human-readable error messages.
    Returns an empty list if config is valid."""
    errors = []

    if not isinstance(raw, dict):
        return ["Config must be a YAML mapping (dict)"]

    sources = raw.get("sources", {}) or {}

    # Telegram validation
    if "telegram" in sources:
        tg = sources["telegram"]
        if not isinstance(tg, dict):
            errors.append("sources.telegram must be a mapping")
        else:
            if not tg.get("api_id"):
                errors.append("sources.telegram.api_id is required")
            if not tg.get("api_hash"):
                errors.append("sources.telegram.api_hash is required")
            channels = tg.get("channels")
            if not channels or not isinstance(channels, list):
                errors.append("sources.telegram.channels must be a non-empty list")

    # Twitter validation
    if "twitter" in sources:
        tw = sources["twitter"]
        if not isinstance(tw, dict):
            errors.append("sources.twitter must be a mapping")
        else:
            instances = tw.get("nitter_instances")
            if not instances or not isinstance(instances, list):
                errors.append("sources.twitter.nitter_instances must be a non-empty list")
            accounts = tw.get("accounts")
            if not accounts or not isinstance(accounts, list):
                errors.append("sources.twitter.accounts must be a non-empty list")

    # RSS feeds validation
    rss_key = "rss_feeds" if "rss_feeds" in sources else "aws_health" if "aws_health" in sources else None
    if rss_key:
        rss = sources[rss_key]
        if not isinstance(rss, dict):
            errors.append(f"sources.{rss_key} must be a mapping")
        else:
            feeds = rss.get("feeds")
            if not feeds or not isinstance(feeds, list):
                errors.append(f"sources.{rss_key}.feeds must be a non-empty list")
            else:
                for i, f in enumerate(feeds):
                    if not isinstance(f, dict) or not f.get("url"):
                        errors.append(f"sources.{rss_key}.feeds[{i}].url is required")

    # Radar validation
    if "radar" in sources:
        radar = sources["radar"]
        if isinstance(radar, dict) and radar.get("enabled"):
            if not radar.get("api_token") and not os.environ.get("CLOUDFLARE_RADAR_TOKEN"):
                errors.append("sources.radar.api_token is required when radar is enabled (or set CLOUDFLARE_RADAR_TOKEN env var)")

    # Notifiers validation
    notifiers = raw.get("notifiers", {}) or {}

    if "whatsapp" in notifiers:
        wa = notifiers["whatsapp"]
        if isinstance(wa, dict) and wa.get("enabled", True):
            if not wa.get("api_url"):
                errors.append("notifiers.whatsapp.api_url is required")
            chat_ids = wa.get("chat_ids")
            if not chat_ids or not isinstance(chat_ids, list):
                errors.append("notifiers.whatsapp.chat_ids must be a non-empty list")

    if "signal" in notifiers:
        sig = notifiers["signal"]
        if isinstance(sig, dict) and sig.get("enabled", True):
            if not sig.get("api_url"):
                errors.append("notifiers.signal.api_url is required")
            if not sig.get("sender"):
                errors.append("notifiers.signal.sender is required")
            recipients = sig.get("recipients")
            if not recipients or not isinstance(recipients, list):
                errors.append("notifiers.signal.recipients must be a non-empty list")

    if "discord" in notifiers:
        dc = notifiers["discord"]
        if isinstance(dc, dict) and dc.get("enabled", True):
            urls = dc.get("webhook_urls")
            if not urls or not isinstance(urls, list):
                errors.append("notifiers.discord.webhook_urls must be a non-empty list")

    if "slack" in notifiers:
        sl = notifiers["slack"]
        if isinstance(sl, dict) and sl.get("enabled", True):
            urls = sl.get("webhook_urls")
            if not urls or not isinstance(urls, list):
                errors.append("notifiers.slack.webhook_urls must be a non-empty list")

    if "email" in notifiers:
        em = notifiers["email"]
        if isinstance(em, dict) and em.get("enabled", True):
            if not em.get("smtp_host"):
                errors.append("notifiers.email.smtp_host is required")
            if not em.get("from_address"):
                errors.append("notifiers.email.from_address is required")
            to = em.get("to_addresses")
            if not to or not isinstance(to, list):
                errors.append("notifiers.email.to_addresses must be a non-empty list")

    return errors


def _substitute_env_vars(value: str) -> str:
    """Replace ${VAR} placeholders with environment variable values.
    Leaves ${VAR} unchanged if the env var is not set (lenient)."""

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            return match.group(0)  # leave ${VAR} as-is
        return env_val

    return ENV_VAR_PATTERN.sub(replacer, value)


def _walk_and_substitute(obj):
    """Recursively substitute env vars in all string values."""
    if isinstance(obj, str):
        return _substitute_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _walk_and_substitute(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_and_substitute(item) for item in obj]
    return obj


def _parse_telegram(raw: dict) -> TelegramSourceConfig:
    return TelegramSourceConfig(
        api_id=int(raw["api_id"]),
        api_hash=raw["api_hash"],
        session_name=raw.get("session_name", "osint_monitor"),
        channels=raw["channels"],
    )


def _parse_twitter(raw: dict) -> TwitterSourceConfig:
    return TwitterSourceConfig(
        method=raw.get("method", "nitter_rss"),
        nitter_instances=raw.get("nitter_instances", ["https://nitter.net/"]),
        accounts=raw.get("accounts", []),
    )


def _parse_rss_feeds(raw: dict) -> RSSFeedsConfig:
    feeds = [
        RSSFeed(
            url=f["url"],
            label=f.get("label", ""),
            content_filter=f.get("content_filter", []) or f.get("region_filter", []) or [],
        )
        for f in raw.get("feeds", [])
    ]
    return RSSFeedsConfig(feeds=feeds)


def _parse_radar(raw: dict) -> RadarConfig:
    countries = raw.get("countries", {}) or {}
    return RadarConfig(
        enabled=raw.get("enabled", False),
        api_token=raw.get("api_token", "") or os.environ.get("CLOUDFLARE_RADAR_TOKEN", ""),
        countries=countries,
    )


def _parse_signal(raw: dict) -> SignalConfig:
    return SignalConfig(
        enabled=raw.get("enabled", True),
        api_url=raw["api_url"],
        sender=raw["sender"],
        recipients=raw["recipients"],
    )


def _parse_whatsapp(raw: dict) -> WhatsAppConfig:
    return WhatsAppConfig(
        enabled=raw.get("enabled", True),
        api_url=raw["api_url"],
        session_name=raw.get("session_name", "default"),
        chat_ids=raw["chat_ids"],
        api_key=raw.get("api_key"),
    )


def _parse_discord(raw: dict) -> DiscordConfig:
    return DiscordConfig(
        enabled=raw.get("enabled", True),
        webhook_urls=raw.get("webhook_urls", []),
    )


def _parse_slack(raw: dict) -> SlackConfig:
    return SlackConfig(
        enabled=raw.get("enabled", True),
        webhook_urls=raw.get("webhook_urls", []),
    )


def _parse_email(raw: dict) -> EmailConfig:
    return EmailConfig(
        enabled=raw.get("enabled", True),
        smtp_host=raw.get("smtp_host", ""),
        smtp_port=raw.get("smtp_port", 587),
        use_tls=raw.get("use_tls", True),
        username=raw.get("username", ""),
        password=raw.get("password", ""),
        from_address=raw.get("from_address", ""),
        to_addresses=raw.get("to_addresses", []),
        subject_prefix=raw.get("subject_prefix", "[OSINT Monitor]"),
    )


def _parse_webhook(raw: dict) -> WebhookConfig:
    urls = []
    for u in raw.get("urls", []):
        if isinstance(u, str):
            urls.append(WebhookEndpoint(url=u))
        elif isinstance(u, dict):
            urls.append(WebhookEndpoint(
                url=u["url"],
                method=u.get("method", "POST"),
                headers=u.get("headers", {}),
                body_template=u.get("body_template", '{"message": "{message}"}'),
            ))
    return WebhookConfig(enabled=raw.get("enabled", True), urls=urls)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load and validate configuration from YAML file."""
    load_dotenv()

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        raise ValueError("Config file is empty or invalid")

    raw = _walk_and_substitute(raw)

    # Validate before parsing
    errors = validate_config(raw)
    if errors:
        raise ConfigError(errors)

    sources_raw = raw.get("sources", {}) or {}

    # RSS feeds: accept both "rss_feeds" and legacy "aws_health" key
    rss_raw = sources_raw.get("rss_feeds") or sources_raw.get("aws_health")

    # Radar: parse via helper
    radar_raw = sources_raw.get("radar", {}) or {}
    radar = _parse_radar(radar_raw) if radar_raw.get("enabled") or os.environ.get("CLOUDFLARE_RADAR_TOKEN") else None

    sources = SourcesConfig(
        telegram=_parse_telegram(sources_raw["telegram"]) if "telegram" in sources_raw else None,
        twitter=_parse_twitter(sources_raw["twitter"]) if "twitter" in sources_raw else None,
        rss_feeds=_parse_rss_feeds(rss_raw) if rss_raw else None,
        radar=radar,
    )

    notifiers_raw = raw.get("notifiers", {}) or {}
    notifiers = NotifiersConfig(
        signal=_parse_signal(notifiers_raw["signal"]) if "signal" in notifiers_raw else None,
        whatsapp=_parse_whatsapp(notifiers_raw["whatsapp"]) if "whatsapp" in notifiers_raw else None,
        discord=_parse_discord(notifiers_raw["discord"]) if "discord" in notifiers_raw else None,
        slack=_parse_slack(notifiers_raw["slack"]) if "slack" in notifiers_raw else None,
        email=_parse_email(notifiers_raw["email"]) if "email" in notifiers_raw else None,
        webhook=_parse_webhook(notifiers_raw["webhook"]) if "webhook" in notifiers_raw else None,
    )

    polling_raw = raw.get("polling", {})
    polling = PollingConfig(
        telegram_interval_seconds=polling_raw.get("telegram_interval_seconds", 30),
        twitter_interval_seconds=polling_raw.get("twitter_interval_seconds", 300),
        rss_feeds_interval_seconds=polling_raw.get("rss_feeds_interval_seconds") or polling_raw.get("aws_health_interval_seconds", 120),
        radar_interval_seconds=polling_raw.get("radar_interval_seconds", 300),
    )

    db_raw = raw.get("database", {})
    database = DatabaseConfig(
        path=db_raw.get("path", "data/messages.db"),
        retention_days=db_raw.get("retention_days", 90),
    )

    log_level = raw.get("logging", {}).get("level", "INFO")

    filters_raw = raw.get("filters", {}) or {}
    default_filter = SourceFilter(
        include_keywords=filters_raw.get("include_keywords", []) or [],
        exclude_keywords=filters_raw.get("exclude_keywords", []) or [],
    )
    per_source = {}
    for source_name in ("telegram", "twitter", "rss", "rss_feeds", "aws_health", "status", "radar"):
        if source_name in filters_raw and isinstance(filters_raw[source_name], dict):
            sf = filters_raw[source_name]
            per_source[source_name] = SourceFilter(
                include_keywords=sf.get("include_keywords", []) or [],
                exclude_keywords=sf.get("exclude_keywords", []) or [],
            )
    filters = FilterConfig(default=default_filter, per_source=per_source)

    trans_raw = raw.get("translation", {}) or {}
    translation = TranslationConfig(
        enabled=trans_raw.get("enabled", False),
        api_url=trans_raw.get("api_url", "http://translate:5000"),
        target_language=trans_raw.get("target_language", "en"),
    )

    return AppConfig(
        sources=sources,
        notifiers=notifiers,
        polling=polling,
        database=database,
        filters=filters,
        translation=translation,
        log_level=log_level,
    )


def load_raw_config(config_path: str = "config.yaml") -> dict | None:
    """Read YAML without env var substitution. Returns None if missing or empty."""
    path = Path(config_path)
    if not path.exists():
        return None
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not raw or not isinstance(raw, dict):
        return None
    return raw


def is_config_empty(raw: dict) -> bool:
    """True if config has no sources and no notifiers configured."""
    sources = raw.get("sources") or {}
    notifiers = raw.get("notifiers") or {}
    return not sources and not notifiers
