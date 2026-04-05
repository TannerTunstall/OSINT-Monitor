# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

OSINT Monitor — an async Python application that monitors Telegram channels, X/Twitter accounts (via Nitter RSS), RSS/Atom feeds, and Cloudflare Radar traffic anomalies, then pushes alerts to WhatsApp, Signal, Discord, Slack, Email, or webhooks. All configuration is done via a web dashboard on port 8550.

## Commands

```bash
# Run locally (outside Docker)
pip install .
osint-monitor                         # uses config.yaml by default
python -m src.main path/to/config.yaml

# Docker (production)
docker compose up -d --build          # build and start (no WhatsApp)
docker compose --profile whatsapp up -d --build  # with WhatsApp
docker compose logs -f osint-monitor  # live logs
docker compose down                   # stop everything

# First-time deploy
bash setup.sh       # Linux/macOS
# or: powershell -ExecutionPolicy Bypass -File setup.ps1  # Windows

# Tests
pip install ".[dev]"
pytest
```

## Architecture

**Entrypoint:** `src/main.py` — async event loop. If config is empty, starts dashboard only; otherwise boots sources + pipeline + notifiers + dashboard. No separate "setup mode" — it always runs the dashboard.

**Data flow:**
```
Sources (poll) → Pipeline (dedup via SQLite, translate, keyword filter, format) → Notifiers (send)
```

On startup, all sources are **seeded** first (existing messages inserted into DB without triggering notifications), then polling loops begin so only genuinely new messages fire alerts.

**Key abstractions:**
- `src/sources/base.py` — `Source` ABC (`start`, `poll`, `stop`) and `Message` dataclass
- `src/notifiers/base.py` — `Notifier` ABC (`send`, `close`)
- `src/processing/pipeline.py` — `Pipeline` orchestrates: DB dedup → translation (LibreTranslate, auto language detection) → keyword filtering → content similarity dedup → format → send
- `src/config.py` — YAML config with `${ENV_VAR}` substitution; `validate_config()` returns all errors at once; `ConfigError` exception
- `src/db.py` — `MessageDB` wraps aiosqlite; primary key is `{source}:{source_id}`; has retention cleanup, export, and analytics queries
- `src/health.py` — `HealthRegistry` / `ConnectorStatus` tracks per-connector health state
- `src/dashboard/server.py` — aiohttp web app with REST API for config CRUD, validation, WhatsApp QR pairing (with Docker container management), Telegram auth, LibreTranslate status, logs, test notifications, analytics, export

**Sources:**
- `TelegramSource` — Telethon client, polls last 10 messages per channel
- `TwitterSource` — Nitter RSS with instance health tracking and deprioritization after consecutive failures
- `RSSSource` — Generic RSS/Atom feeds via feedparser (formerly AWSHealthSource, backward-compatible aliases exist)
- `RadarSource` — Cloudflare Radar API for configurable country traffic anomalies and global cloud outages

**Notifiers:**
- `WhatsAppNotifier` — WAHA API, retry with exponential backoff. Container starts on-demand.
- `SignalNotifier` — signal-cli REST API
- `DiscordNotifier` — Discord webhooks
- `SlackNotifier` — Slack webhooks
- `EmailNotifier` — SMTP via aiosmtplib (optional dependency)
- `WebhookNotifier` — Generic HTTP with configurable templates

**Dashboard UI:**
- Modular: `index.html` (structure), `style.css` (design), `js/api.js` (client/helpers), `js/app.js` (logic)
- Tabs: Sources, Analytics, Feed, Delivery, Filters, Credentials, Logs
- Chart.js for analytics visualizations
- Welcome banner on first run (not a forced wizard)
- Inline Telegram auth in Credentials tab, WhatsApp QR pairing in Delivery tab

**Docker services:** `osint-monitor` (the app), `whatsapp-api` (WAHA, profile: whatsapp — starts on demand), `translate` (LibreTranslate). Signal API commented out by default.

## Config

- `config.yaml` — main config (gitignored); copy from `config.example.yaml`
- `.env` — secrets (gitignored); referenced in config via `${VAR}` syntax
- Config changes via dashboard trigger a restart (process exits with code 0, Docker `unless-stopped` restarts it)
- Legacy config keys (`aws_health`, `region_filter`, `aws_health_interval_seconds`) are accepted for backward compatibility

## Key Patterns

- Everything is async (`asyncio` + `aiohttp`). Sources and notifiers manage their own `aiohttp.ClientSession` lifecycles.
- Graceful shutdown: SIGINT/SIGTERM cancels all polling tasks, then sources/notifiers/pipeline are cleaned up in order. Windows-safe (skips signal handlers on win32).
- The dashboard writes directly to `config.yaml` and `.env` files on disk, then triggers a restart.
- Telegram session files live in `session/` directory (mounted as Docker volume).
- WhatsApp (WAHA) container managed via Docker socket — started on-demand when user enables WhatsApp or clicks "Pair WhatsApp".
- Config validation: `validate_config()` in `src/config.py` returns all errors at once; also available via `/api/config/validate` endpoint.
- Query params are bounds-checked (limit, lines) and date formats validated on export.
