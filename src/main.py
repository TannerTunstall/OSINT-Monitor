import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from aiohttp import web

from src.config import is_config_empty, load_config, load_raw_config
from src.dashboard.server import create_dashboard
from src.db import MessageDB
from src.health import ConnectorStatus, HealthRegistry
from src.processing.pipeline import Pipeline
from src.sources.base import Source
from src.utils.logging import setup_logging

logger = logging.getLogger(__name__)

DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8550"))


async def seed_source(source: Source, pipeline: Pipeline):
    """First poll: seed the DB with existing messages WITHOUT sending notifications.
    This prevents flooding the notification channel on every restart."""
    try:
        messages = await source.poll()
        for msg in messages:
            await pipeline.seed(msg)
        logger.info("Seeded %d existing messages from %s", len(messages), source.__class__.__name__)
    except Exception:
        logger.exception("Error seeding %s", source.__class__.__name__)


async def run_polling_source(
    source: Source, pipeline: Pipeline, interval: int, health: ConnectorStatus,
):
    """Poll a source on a fixed interval and process new messages."""
    while True:
        try:
            messages = await source.poll()
            for msg in messages:
                await pipeline.process(msg)
            health.record_success(len(messages))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Error polling %s", source.__class__.__name__)
            health.record_error(str(exc))
        await asyncio.sleep(interval)



async def run_db_cleanup(db: MessageDB, retention_days: int):
    """Clean up old messages on startup, then every 24 hours."""
    while True:
        try:
            await db.cleanup(retention_days)
            logger.info("DB cleanup completed (retention: %d days)", retention_days)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error during DB cleanup")
        await asyncio.sleep(86400)


async def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"

    # Ensure config and .env files exist (first run / pip install mode).
    # Skip if they already exist — in Docker they are bind-mounted and may
    # be owned by root, so touching them would fail as non-root user.
    if not Path(config_path).exists():
        Path(config_path).touch()
    if not Path(".env").exists():
        Path(".env").touch()

    # Try to load config — if empty or invalid, run with defaults (dashboard only)
    config = None
    raw = load_raw_config(config_path)
    if raw and not is_config_empty(raw):
        try:
            config = load_config(config_path)
        except Exception as exc:
            logger.error("Config load error: %s — starting with dashboard only", exc)

    setup_logging(config.log_level if config else "INFO")
    logger.info("Starting OSINT Monitor")

    health = HealthRegistry()
    db = MessageDB(config.database.path if config else "data/messages.db")
    await db.connect()

    # Build notifiers
    notifiers = []
    if config and config.notifiers.whatsapp and config.notifiers.whatsapp.enabled:
        from src.notifiers.whatsapp import WhatsAppNotifier
        n = WhatsAppNotifier(config.notifiers.whatsapp)
        notifiers.append(n)
        health.register("WhatsApp", "notifier")

        async def _start_waha_and_session():
            """Try to start WAHA container via Docker, then ensure session."""
            try:
                import aiohttp as _aiohttp
                async with _aiohttp.ClientSession(connector=_aiohttp.UnixConnector(path="/var/run/docker.sock")) as docker:
                    async with docker.get("http://localhost/containers/whatsapp-api/json") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("State", {}).get("Status") != "running":
                                logger.info("Starting WAHA container...")
                                await docker.post("http://localhost/containers/whatsapp-api/start")
                        else:
                            logger.info("WAHA container not found — WhatsApp will be unavailable until started")
                            return
            except Exception:
                logger.debug("Docker socket not available — assuming WAHA is managed externally")
            await n.ensure_session()

        asyncio.create_task(_start_waha_and_session())

    if config and config.notifiers.signal and config.notifiers.signal.enabled:
        from src.notifiers.signal import SignalNotifier
        n = SignalNotifier(config.notifiers.signal)
        notifiers.append(n)
        health.register("Signal", "notifier")

        async def _start_signal_container():
            """Start signal-api container via Docker if not running."""
            try:
                import aiohttp as _aiohttp
                async with _aiohttp.ClientSession(connector=_aiohttp.UnixConnector(path="/var/run/docker.sock")) as docker:
                    async with docker.get("http://localhost/containers/signal-api/json") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("State", {}).get("Status") != "running":
                                logger.info("Starting Signal container...")
                                await docker.post("http://localhost/containers/signal-api/start")
                        else:
                            logger.info("Signal container not found — Signal notifications may be unavailable")
            except Exception:
                logger.debug("Docker socket not available — assuming Signal container is managed externally")

        asyncio.create_task(_start_signal_container())

    if config and config.notifiers.discord and config.notifiers.discord.enabled:
        from src.notifiers.discord import DiscordNotifier
        n = DiscordNotifier(config.notifiers.discord)
        notifiers.append(n)
        health.register("Discord", "notifier")

    if config and config.notifiers.slack and config.notifiers.slack.enabled:
        from src.notifiers.slack import SlackNotifier
        n = SlackNotifier(config.notifiers.slack)
        notifiers.append(n)
        health.register("Slack", "notifier")

    if config and config.notifiers.email and config.notifiers.email.enabled:
        from src.notifiers.email import EmailNotifier
        n = EmailNotifier(config.notifiers.email)
        notifiers.append(n)
        health.register("Email", "notifier")

    if config and config.notifiers.webhook and config.notifiers.webhook.enabled:
        from src.notifiers.webhook import WebhookNotifier
        n = WebhookNotifier(config.notifiers.webhook)
        notifiers.append(n)
        health.register("Webhook", "notifier")

    if not notifiers:
        logger.warning("No notifiers configured — dashboard-only mode.")

    pipeline = Pipeline(
        db=db, notifiers=notifiers,
        filters=config.filters if config else None,
        health=health,
        translation=config.translation if config else None,
    )

    # Build sources — all are polling-based
    sources: list[Source] = []
    source_configs = []  # (name, source, interval)

    if config and config.sources.telegram:
        from src.sources.telegram import TelegramSource
        tg_source = TelegramSource(config.sources.telegram)
        await tg_source.start()
        sources.append(tg_source)
        source_configs.append(("Telegram", tg_source, config.polling.telegram_interval_seconds))

    if config and config.sources.twitter:
        from src.sources.twitter import TwitterSource
        twitter_source = TwitterSource(config.sources.twitter)
        await twitter_source.start()
        sources.append(twitter_source)
        source_configs.append(("Twitter/X", twitter_source, config.polling.twitter_interval_seconds))

    if config and config.sources.rss_feeds:
        from src.sources.rss import RSSSource
        rss_source = RSSSource(config.sources.rss_feeds)
        await rss_source.start()
        sources.append(rss_source)
        source_configs.append(("RSS Feeds", rss_source, config.polling.rss_feeds_interval_seconds))

    if config and config.sources.radar and config.sources.radar.enabled and config.sources.radar.api_token:
        from src.sources.radar import RadarSource
        radar_source = RadarSource(config.sources.radar.api_token, config.sources.radar.countries)
        await radar_source.start()
        sources.append(radar_source)
        source_configs.append(("Radar", radar_source, config.polling.radar_interval_seconds))

    # Seed: record existing messages in DB WITHOUT sending notifications
    logger.info("Seeding existing messages from %d source(s)...", len(sources))
    for name, source, _ in source_configs:
        await seed_source(source, pipeline)

    # Start poll loops — only genuinely NEW messages trigger notifications
    tasks = []
    for name, source, interval in source_configs:
        h = health.register(name, "source")
        tasks.append(
            asyncio.create_task(
                run_polling_source(source, pipeline, interval, h),
                name=f"{name.lower().replace('/', '_')}_poller",
            )
        )

    # DB cleanup task
    tasks.append(
        asyncio.create_task(
            run_db_cleanup(db, config.database.retention_days if config else 90),
            name="db_cleanup",
        )
    )

    # Restart callback
    restart_requested = False

    def request_restart():
        nonlocal restart_requested
        restart_requested = True
        logger.info("Restart requested via dashboard")
        for t in tasks:
            t.cancel()

    # Start dashboard
    dashboard_app = create_dashboard(health, notifiers, restart_callback=request_restart, pipeline=pipeline, db=db)
    runner = web.AppRunner(dashboard_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", DASHBOARD_PORT)
    await site.start()
    logger.info("Dashboard running at http://0.0.0.0:%d", DASHBOARD_PORT)

    logger.info(
        "OSINT Monitor running with %d source(s), %d notifier(s)",
        len(sources), len(notifiers),
    )

    # Graceful shutdown
    def handle_signal():
        logger.info("Shutdown signal received")
        for t in tasks:
            t.cancel()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down sources and notifiers")
        for source in sources:
            try:
                await source.stop()
            except Exception:
                logger.exception("Error stopping %s", source.__class__.__name__)
        for notifier in notifiers:
            try:
                await notifier.close()
            except Exception:
                logger.exception("Error closing %s", notifier.__class__.__name__)
        await pipeline.close()
        await runner.cleanup()
        await db.close()

        if restart_requested:
            logger.info("Restarting OSINT Monitor...")
            sys.exit(0)  # Docker restart: unless-stopped handles the restart
        else:
            logger.info("OSINT Monitor stopped")


def cli_entry():
    """Entry point for `osint-monitor` CLI command (via pyproject.toml)."""
    asyncio.run(main())


if __name__ == "__main__":
    cli_entry()
