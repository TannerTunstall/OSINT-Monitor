# Contributing to OSINT Monitor

## Development Setup

```bash
# Clone the repo
git clone https://github.com/TannerTunstall/OSINT-Monitor.git
cd osint-monitor

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install in development mode
pip install -e ".[dev]"

# Run locally
python -m src.main config.yaml
```

The dashboard will be available at `http://localhost:8550`.

## Project Structure

```
src/
  main.py                  # Async entrypoint — boots sources, pipeline, notifiers, dashboard
  config.py                # YAML config parsing + validation
  db.py                    # SQLite message store with retention and analytics
  health.py                # Connector health tracking
  sources/
    base.py                # Source ABC + Message dataclass
    telegram.py            # Telegram via Telethon
    twitter.py             # Twitter/X via Nitter RSS with instance failover
    rss.py                 # Generic RSS/Atom feeds with content filtering
    radar.py               # Cloudflare Radar API
  notifiers/
    base.py                # Notifier ABC
    whatsapp.py            # WhatsApp via WAHA
    signal.py              # Signal via REST API
    discord.py             # Discord webhooks
    slack.py               # Slack webhooks
    email.py               # SMTP email
    webhook.py             # Generic webhooks
  processing/
    pipeline.py            # Dedup, translate, filter, format, send
  dashboard/
    server.py              # aiohttp REST API + security middleware
    telegram_auth.py       # Telegram phone authentication flow
    static/
      index.html           # Dashboard SPA shell
      style.css            # Full design system (dark theme)
      js/
        app.js             # Tab logic, analytics, config management
        api.js             # API helpers, escaping, feed presets
  utils/
    logging.py             # Log setup with rotation
    retry.py               # Exponential backoff with jitter
tests/
  conftest.py              # Shared fixtures (async DB, message factory, mock notifier)
  test_config.py           # Config parsing, backward compat, validation
  test_db.py               # SQLite dedup, export, stats, cleanup
  test_notifiers.py        # Discord, Slack, Webhook delivery
  test_pipeline.py         # Process flow, dedup, keywords, similarity, translation
  test_retry.py            # Retry logic, backoff timing, exhaustion
  test_sources.py          # RSS parsing, content filters, Twitter failover
```

## Adding a New Source

1. Create `src/sources/your_source.py`
2. Inherit from `Source` (in `src/sources/base.py`)
3. Implement `start()`, `poll()`, and `stop()`
4. `poll()` returns a list of `Message` objects
5. Add a config dataclass in `src/config.py`
6. Register it in `src/main.py` (follow the existing pattern)

```python
from src.sources.base import Message, Source

class MySource(Source):
    async def start(self):
        # Initialize connections, sessions, etc.
        pass

    async def poll(self) -> list[Message]:
        # Fetch new data and return normalized Messages
        return [
            Message(
                source="my_source",
                source_id="unique-id-123",
                author="Source Name",
                content="The message content",
                url="https://example.com/link",
                timestamp=datetime.now(timezone.utc),
            )
        ]

    async def stop(self):
        # Clean up resources
        pass
```

## Adding a New Notifier

1. Create `src/notifiers/your_notifier.py`
2. Inherit from `Notifier` (in `src/notifiers/base.py`)
3. Implement `send(text) -> bool` and `close()`
4. Use `@with_retry` decorator for network calls
5. Add a config dataclass in `src/config.py`
6. Register it in `src/main.py`

```python
from src.notifiers.base import Notifier
from src.utils.retry import with_retry

class MyNotifier(Notifier):
    @with_retry(max_retries=3, base_delay=2.0)
    async def send(self, text: str) -> bool:
        # Send the notification, return True on success
        return True

    async def close(self):
        # Clean up resources
        pass
```

## Code Style

- Python 3.11+, fully async (asyncio + aiohttp)
- Type hints on function signatures
- Use `logging` module (not print)
- Follow existing patterns for error handling and session management

## Running Tests

```bash
# Install dev dependencies (includes pytest + aioresponses)
pip install -e ".[dev]"

# Run all tests
pytest -v

# Run a specific test file
pytest tests/test_pipeline.py -v
```

## CI/CD

GitHub Actions runs automatically on pushes to `main` and on pull requests:

- **Lint** — Syntax check all Python files (`py_compile`)
- **Test** — `pytest` on Python 3.11 and 3.12
- **Docker Build** — Validates the Docker image builds successfully

## Pull Requests

1. Fork the repo and create a feature branch
2. Make your changes
3. Run tests locally: `pytest -v`
4. Submit a PR with a clear description of what and why
5. CI must pass before merge
