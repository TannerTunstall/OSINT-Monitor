import asyncio
import logging
from pathlib import Path

import aiohttp
import yaml
from aiohttp import web

from src.dashboard.telegram_auth import TelegramAuthManager, add_telegram_auth_routes
from src.health import HealthRegistry

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"
ENV_PATH = ".env"
SESSION_DIR = "session"


def _read_config() -> dict:
    p = Path(CONFIG_PATH)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            raw = yaml.safe_load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _write_config(data: dict):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _read_env() -> dict[str, str]:
    env = {}
    p = Path(ENV_PATH)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _write_env(env: dict[str, str]):
    lines = []
    for k, v in env.items():
        lines.append(f"{k}={v}")
    Path(ENV_PATH).write_text("\n".join(lines) + "\n")


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    return "*" * min(len(value), 12)


def _is_setup_complete() -> bool:
    """Check if minimum setup has been done."""
    env = _read_env()
    has_creds = bool(env.get("TELEGRAM_API_ID")) and bool(env.get("TELEGRAM_API_HASH"))
    has_session = any(Path(SESSION_DIR).glob("*.session")) if Path(SESSION_DIR).exists() else False
    cfg = _read_config()
    has_notifier = bool(cfg.get("notifiers", {}).get("whatsapp", {}).get("chat_ids")) or \
                   bool(cfg.get("notifiers", {}).get("signal", {}).get("recipients"))
    return has_creds and has_session and has_notifier


def create_dashboard(health: HealthRegistry, notifiers: list, restart_callback=None, pipeline=None, db=None) -> web.Application:
    @web.middleware
    async def security_headers(request, handler):
        response = await handler(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @web.middleware
    async def error_middleware(request, handler):
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except (ValueError, KeyError) as e:
            return web.json_response({"status": "error", "message": f"Invalid request: {e}"}, status=400)
        except Exception as e:
            logger.exception("Unhandled error in %s %s", request.method, request.path)
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    app = web.Application(middlewares=[security_headers, error_middleware])
    app["health"] = health
    app["notifiers"] = notifiers
    app["restart_callback"] = restart_callback
    app["pipeline"] = pipeline
    app["db"] = db

    telegram_auth = TelegramAuthManager()

    static_dir = Path(__file__).parent / "static"

    async def index(request):
        return web.FileResponse(static_dir / "index.html")

    # ── Setup status ─────────────────────────────────────────

    async def api_setup_status(request):
        env = _read_env()
        cfg = _read_config()

        has_telegram_creds = bool(env.get("TELEGRAM_API_ID")) and bool(env.get("TELEGRAM_API_HASH"))
        has_telegram_session = any(Path(SESSION_DIR).glob("*.session")) if Path(SESSION_DIR).exists() else False

        # Any source configured (not just Telegram)
        sources = cfg.get("sources") or {}
        has_sources = bool(sources)

        # Any notifier configured (not just WhatsApp)
        notifiers = cfg.get("notifiers") or {}
        has_notifier = any(
            isinstance(v, dict) and v.get("enabled", True) and (
                v.get("chat_ids") or v.get("recipients") or v.get("webhook_urls") or v.get("to_addresses") or v.get("urls")
            )
            for v in notifiers.values()
        )

        # Setup is complete if there is at least one source AND one notifier
        setup_complete = has_sources and has_notifier

        return web.json_response({
            "setup_complete": setup_complete,
            "has_sources": has_sources,
            "has_notifier": has_notifier,
            "telegram_creds": has_telegram_creds,
            "telegram_authed": has_telegram_session,
        })

    # ── Health / Status ──────────────────────────────────────

    async def api_health(request):
        return web.json_response(health.summary())

    # ── Config: full read/write ──────────────────────────────

    async def api_config_get(request):
        return web.json_response(_read_config())

    async def api_config_put(request):
        data = await request.json()
        from src.config import validate_config
        errors = validate_config(data)
        if errors:
            return web.json_response({"status": "error", "errors": errors}, status=400)
        _write_config(data)
        logger.info("Config updated via dashboard")
        return web.json_response({"status": "ok", "message": "Config saved. Restart to apply."})

    async def api_config_validate(request):
        data = await request.json()
        from src.config import validate_config
        errors = validate_config(data)
        if errors:
            return web.json_response({"valid": False, "errors": errors})
        return web.json_response({"valid": True, "errors": []})

    # ── Sources CRUD ─────────────────────────────────────────

    async def api_sources_get(request):
        return web.json_response(_read_config().get("sources", {}))

    async def api_sources_put(request):
        data = await request.json()
        cfg = _read_config()
        cfg["sources"] = data
        _write_config(cfg)
        return web.json_response({"status": "ok", "message": "Sources updated. Restart to apply."})

    # ── Notifiers CRUD ───────────────────────────────────────

    async def api_notifiers_get(request):
        return web.json_response(_read_config().get("notifiers", {}))

    async def api_notifiers_put(request):
        data = await request.json()
        cfg = _read_config()
        cfg["notifiers"] = data
        _write_config(cfg)
        return web.json_response({"status": "ok", "message": "Notifiers updated. Restart to apply."})

    # ── Filters ──────────────────────────────────────────────

    async def api_filters_get(request):
        return web.json_response(_read_config().get("filters", {}))

    async def api_filters_put(request):
        data = await request.json()
        cfg = _read_config()
        cfg["filters"] = data
        _write_config(cfg)
        return web.json_response({"status": "ok", "message": "Filters updated. Restart to apply."})

    # ── Polling intervals ────────────────────────────────────

    async def api_polling_get(request):
        return web.json_response(_read_config().get("polling", {}))

    async def api_polling_put(request):
        data = await request.json()
        cfg = _read_config()
        cfg["polling"] = data
        _write_config(cfg)
        return web.json_response({"status": "ok", "message": "Polling config updated. Restart to apply."})

    # ── Credentials (.env) ───────────────────────────────────

    async def api_credentials_get(request):
        env = _read_env()
        masked = {k: _mask_secret(v) for k, v in env.items()}
        return web.json_response(masked)

    ALLOWED_CREDENTIAL_KEYS = {
        "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
        "CLOUDFLARE_RADAR_API_TOKEN",
        "SMTP_USER", "SMTP_PASSWORD",
        "WEBHOOK_TOKEN",
        "WAHA_TAG",
    }

    async def api_credentials_put(request):
        data = await request.json()
        current = _read_env()
        for k, v in data.items():
            if k not in ALLOWED_CREDENTIAL_KEYS:
                continue
            if v and not v.endswith("****"):
                current[k] = v
        _write_env(current)
        logger.info("Credentials updated via dashboard")
        return web.json_response({"status": "ok", "message": "Credentials saved. Restart to apply."})

    # ── WhatsApp QR / status proxy (from WAHA) ───────────────

    async def _get_waha_url(self=None):
        cfg = _read_config()
        wa_cfg = cfg.get("notifiers", {}).get("whatsapp", {})
        return wa_cfg.get("api_url", "http://whatsapp-api:3000"), wa_cfg.get("session_name", "default")

    async def _ensure_waha_container():
        """Start the WAHA Docker container if it's not running.
        Creates and pulls the image if the container doesn't exist.
        Returns True if WAHA becomes reachable."""
        import asyncio as _asyncio
        import json as _json
        api_url, _ = await _get_waha_url()

        # First check if WAHA is already reachable
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{api_url}/api/sessions", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        return True
        except Exception:
            pass

        logger.info("WAHA not reachable — managing container via Docker socket...")
        try:
            async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path="/var/run/docker.sock")) as docker:
                # Check if container exists
                async with docker.get("http://localhost/containers/whatsapp-api/json") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        state = data.get("State", {}).get("Status", "")
                        if state != "running":
                            logger.info("Starting stopped WAHA container (state: %s)...", state)
                            await docker.post("http://localhost/containers/whatsapp-api/start")

                    elif resp.status == 404:
                        # Container doesn't exist — pull image and create it
                        import re as _re_tag
                        env = _read_env()
                        waha_tag = env.get("WAHA_TAG", "latest")
                        if not _re_tag.match(r"^[a-zA-Z0-9._-]+$", waha_tag):
                            logger.warning("Invalid WAHA_TAG value: %s — using 'latest'", waha_tag)
                            waha_tag = "latest"
                        image = f"devlikeapro/waha:{waha_tag}"

                        # Pull image
                        logger.info("Pulling WAHA image: %s (this may take a minute)...", image)
                        async with docker.post(
                            f"http://localhost/images/create?fromImage=devlikeapro/waha&tag={waha_tag}",
                            timeout=aiohttp.ClientTimeout(total=300),
                        ) as pull_resp:
                            if pull_resp.status not in (200, 201):
                                body = await pull_resp.text()
                                logger.error("Failed to pull WAHA image: %d %s", pull_resp.status, body[:200])
                                return False
                            # Read stream to completion
                            async for _ in pull_resp.content:
                                pass
                        logger.info("WAHA image pulled successfully.")

                        # Create container
                        import os
                        app_dir = os.path.dirname(os.path.abspath("config.yaml"))
                        container_config = {
                            "Image": image,
                            "Env": [
                                "WAHA_DEFAULT_SESSION=default",
                                "WAHA_NO_API_KEY=True",
                                "WAHA_DASHBOARD_NO_PASSWORD=True",
                                "WHATSAPP_RESTART_ALL_SESSIONS=True",
                            ],
                            "HostConfig": {
                                "Binds": [f"{app_dir}/whatsapp-data:/app/.sessions"],
                                "PortBindings": {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3000"}]},
                                "RestartPolicy": {"Name": "no"},
                            },
                            "ExposedPorts": {"3000/tcp": {}},
                        }
                        logger.info("Creating WAHA container...")
                        async with docker.post(
                            "http://localhost/containers/create?name=whatsapp-api",
                            json=container_config,
                        ) as create_resp:
                            if create_resp.status not in (200, 201):
                                body = await create_resp.text()
                                logger.error("Failed to create WAHA container: %d %s", create_resp.status, body[:200])
                                return False

                        # Start container
                        await docker.post("http://localhost/containers/whatsapp-api/start")
                        logger.info("WAHA container created and started.")

        except Exception as e:
            logger.warning("Cannot manage WAHA via Docker: %s", e)
            return False

        # Wait for WAHA to become reachable
        for attempt in range(30):
            await _asyncio.sleep(2)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{api_url}/api/sessions", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                        if resp.status == 200:
                            logger.info("WAHA is now reachable.")
                            return True
            except Exception:
                pass
            logger.info("Waiting for WAHA... (attempt %d/30)", attempt + 1)

        logger.warning("WAHA did not become reachable after 60 seconds.")
        return False

    async def api_whatsapp_start(request):
        """Start a WAHA session so it enters SCAN_QR_CODE state.
        Ensures the WAHA container is running first."""
        import asyncio as _asyncio

        # Ensure WAHA container is running
        waha_ok = await _ensure_waha_container()
        if not waha_ok:
            return web.json_response(
                {"status": "error", "message": "Could not start WhatsApp service. Check Docker is running and try again."},
                status=502,
            )

        api_url, session_name = await _get_waha_url()
        try:
            async with aiohttp.ClientSession() as session:
                # Stop session first (clears FAILED/STOPPED state)
                stop_url = f"{api_url}/api/sessions/stop"
                async with session.post(stop_url, json={"name": session_name}) as resp:
                    stop_body = await resp.text()
                    logger.info("WAHA stop response %d: %s", resp.status, stop_body[:200])

                await _asyncio.sleep(1)

                # Now start fresh
                start_url = f"{api_url}/api/sessions/start"
                async with session.post(start_url, json={"name": session_name}) as resp:
                    start_body = await resp.text()
                    logger.info("WAHA start response %d: %s", resp.status, start_body[:200])

                # Wait for session to initialize
                await _asyncio.sleep(3)

                # Check status
                status_url = f"{api_url}/api/sessions/{session_name}"
                async with session.get(status_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return web.json_response(data)
                    else:
                        body = await resp.text()
                        return web.json_response(
                            {"status": "unknown", "message": f"Status check returned {resp.status}: {body}"}
                        )
        except aiohttp.ClientError as e:
            return web.json_response(
                {"status": "error", "message": f"Cannot reach WhatsApp API: {e}"},
                status=502,
            )

    async def api_whatsapp_qr(request):
        api_url, session_name = await _get_waha_url()
        try:
            async with aiohttp.ClientSession() as session:
                # Get QR code as base64 JSON (more reliable than image proxy)
                qr_url = f"{api_url}/api/{session_name}/auth/qr"
                headers = {"Accept": "application/json"}
                async with session.get(qr_url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return web.json_response(data)
                    elif resp.status == 404:
                        return web.json_response(
                            {"status": "not_ready", "message": "Session not started. Click 'Start Session' first."},
                            status=404,
                        )
                    else:
                        body = await resp.text()
                        return web.json_response(
                            {"status": "error", "message": f"WAHA returned {resp.status}: {body}"},
                            status=resp.status,
                        )
        except aiohttp.ClientError as e:
            return web.json_response(
                {"status": "error", "message": f"Cannot reach WhatsApp API: {e}"},
                status=502,
            )

    async def api_whatsapp_status(request):
        api_url, session_name = await _get_waha_url()
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{api_url}/api/sessions/{session_name}"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return web.json_response(data)
                    elif resp.status == 404:
                        return web.json_response({"status": "STOPPED", "message": "Session not found."})
                    else:
                        body = await resp.text()
                        return web.json_response({"status": "error", "message": body}, status=resp.status)
        except aiohttp.ClientError as e:
            return web.json_response(
                {"status": "error", "message": f"Cannot reach WhatsApp API: {e}"},
                status=502,
            )

    # ── Test notification ────────────────────────────────────

    async def api_test_notification(request):
        test_msg = "[OSINT MONITOR] Test notification — if you see this, delivery is working."
        results = []
        for notifier in app["notifiers"]:
            name = notifier.__class__.__name__
            try:
                ok = await notifier.send(test_msg)
                results.append({"notifier": name, "success": ok})
            except Exception as e:
                results.append({"notifier": name, "success": False, "error": str(e)})
        return web.json_response({"results": results})

    # ── LibreTranslate status ────────────────────────────────

    async def api_translate_status(request):
        """Check LibreTranslate availability, loaded languages, and configured languages."""
        cfg = _read_config()
        api_url = (cfg.get("translation") or {}).get("api_url", "http://translate:5000")

        # Read LT_LOAD_ONLY from docker-compose.yml
        configured_langs = ""
        try:
            compose_path = Path(CONFIG_PATH).parent / "docker-compose.yml"
            if compose_path.exists():
                import re
                text = compose_path.read_text()
                m = re.search(r"LT_LOAD_ONLY=([^\s#]+)", text)
                if m:
                    configured_langs = m.group(1)
        except Exception:
            pass

        try:
            import aiohttp as _aiohttp
            async with _aiohttp.ClientSession() as session:
                async with session.get(f"{api_url.rstrip('/')}/languages", timeout=_aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        langs = await resp.json()
                        return web.json_response({
                            "ok": True,
                            "languages": langs,
                            "configured": configured_langs,
                        })
                    return web.json_response({"ok": False, "error": f"HTTP {resp.status}", "configured": configured_langs})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e), "configured": configured_langs})

    async def api_translate_configure(request):
        """Update LT_LOAD_ONLY in docker-compose.yml."""
        data = await request.json()
        langs = data.get("languages", "").strip()
        if not langs:
            return web.json_response({"status": "error", "message": "languages is required"}, status=400)
        # Validate: must be comma-separated 2-3 letter language codes only
        import re as _re
        if not _re.match(r'^[a-z]{2,3}(,[a-z]{2,3})*$', langs):
            return web.json_response({"status": "error", "message": "Invalid format. Use comma-separated language codes (e.g. en,ar,fa)"}, status=400)

        compose_path = Path(CONFIG_PATH).parent / "docker-compose.yml"
        if not compose_path.exists():
            return web.json_response({"status": "error", "message": "docker-compose.yml not found"}, status=404)

        import re
        text = compose_path.read_text()
        new_text = re.sub(
            r"(LT_LOAD_ONLY=)[^\s#]+",
            f"\\g<1>{langs}",
            text,
        )
        if new_text == text:
            # Same languages already configured — still proceed with container rebuild
            logger.info("LT_LOAD_ONLY already set to %s — rebuilding container anyway", langs)
        else:
            compose_path.write_text(new_text)
            logger.info("Updated LT_LOAD_ONLY to: %s", langs)

        # Recreate the translate container with the new env var
        try:
            async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path="/var/run/docker.sock")) as docker:
                # Get current container config for volumes/ports
                async with docker.get("http://localhost/containers/translate/json") as resp:
                    if resp.status != 200:
                        return web.json_response({"status": "ok", "message": f"Languages saved to: {langs}. Could not auto-restart translate container — restart it manually."})
                    old = await resp.json()

                # Stop and remove old container
                await docker.post("http://localhost/containers/translate/stop", timeout=aiohttp.ClientTimeout(total=30))
                await docker.delete("http://localhost/containers/translate")
                logger.info("Stopped and removed old translate container.")

                # Recreate with updated env
                old_env = old.get("Config", {}).get("Env", [])
                new_env = [e for e in old_env if not e.startswith("LT_LOAD_ONLY=") and not e.startswith("LT_UPDATE_MODELS=")]
                new_env.append(f"LT_LOAD_ONLY={langs}")
                new_env.append("LT_UPDATE_MODELS=true")

                container_config = {
                    "Image": old.get("Config", {}).get("Image", "libretranslate/libretranslate:latest"),
                    "Env": new_env,
                    "ExposedPorts": old.get("Config", {}).get("ExposedPorts", {}),
                    "HostConfig": {
                        "Binds": old.get("HostConfig", {}).get("Binds", []),
                        "PortBindings": old.get("HostConfig", {}).get("PortBindings", {}),
                        "RestartPolicy": old.get("HostConfig", {}).get("RestartPolicy", {"Name": "unless-stopped"}),
                    },
                }
                async with docker.post("http://localhost/containers/create?name=translate", json=container_config) as create_resp:
                    if create_resp.status not in (200, 201):
                        body = await create_resp.text()
                        logger.error("Failed to recreate translate container: %s", body[:200])
                        return web.json_response({"status": "ok", "message": f"Languages saved. Failed to auto-restart — restart translate container manually."})

                await docker.post("http://localhost/containers/translate/start")
                logger.info("Translate container recreated with LT_LOAD_ONLY=%s", langs)

        except Exception as e:
            logger.warning("Could not auto-restart translate container: %s", e)
            return web.json_response({"status": "ok", "message": f"Languages saved to: {langs}. Could not auto-restart — restart translate container manually."})

        return web.json_response({"status": "ok", "message": f"Languages updated to: {langs}. Translate container is restarting — language models will download shortly."})

    # ── Test source messages ───────────────────────────────

    async def api_test_source(request):
        """Send a test message through the full pipeline (translate → filter → format → send)."""
        import time
        import random
        data = await request.json()
        msg_type = data.get("type", "telegram")

        # Each test needs a unique source_id to avoid SQLite dedup
        uid = f"test-{int(time.time())}-{random.randint(1000,9999)}"

        test_messages = {
            "telegram": {
                "source": "telegram", "source_id": uid,
                "author": "Test Channel", "url": "https://t.me/test/1",
                "content": "TEST of Telegram delivery method. If you see this message, Telegram source processing and notification delivery are working correctly.",
            },
            "telegram_translation": {
                "source": "telegram", "source_id": uid,
                "author": "Test Channel", "url": "https://t.me/test/2",
                "content": "TEST de la methode de livraison Telegram avec traduction. Ce message teste le pipeline de traduction automatique.",
            },
            "twitter": {
                "source": "twitter", "source_id": uid,
                "author": "@testaccount", "url": "https://x.com/testaccount/status/123",
                "content": "TEST of Twitter/X delivery method. If you see this message, Twitter source processing and notification delivery are working correctly.",
            },
            "rss": {
                "source": "rss", "source_id": uid,
                "author": "Test RSS Feed", "url": "https://example.com/feed",
                "content": "TEST of RSS feed delivery method. If you see this message, RSS source processing and notification delivery are working correctly.",
            },
            "radar_anomaly": {
                "source": "radar", "source_id": uid,
                "author": "Traffic Anomaly — Test",
                "url": "https://radar.cloudflare.com/outage-center",
                "content": "TEST of Radar anomaly delivery method. If you see this message, Cloudflare Radar source processing and notification delivery are working correctly.",
            },
            "radar_outage": {
                "source": "radar", "source_id": uid,
                "author": "Cloud Outage — Test",
                "url": "https://radar.cloudflare.com/outage-center",
                "content": "TEST of Radar outage delivery method. If you see this message, Cloudflare Radar outage monitoring and notification delivery are working correctly.",
            },
        }

        msg_data = test_messages.get(msg_type, test_messages["telegram"])

        from src.sources.base import Message
        from datetime import datetime, timezone
        msg = Message(
            source=msg_data["source"],
            source_id=msg_data["source_id"],
            author=msg_data["author"],
            content=msg_data["content"],
            url=msg_data["url"],
            timestamp=datetime.now(timezone.utc),
        )

        pipeline = app.get("pipeline")
        if not pipeline:
            return web.json_response({"status": "error", "message": "Pipeline not available"}, status=500)

        try:
            await pipeline.process(msg)
            return web.json_response({"status": "ok", "message": f"Test {msg_type} message sent through pipeline"})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    # ── Restart trigger ──────────────────────────────────────

    async def api_restart(request):
        cb = app["restart_callback"]
        if cb:
            cb()
            return web.json_response({"status": "ok", "message": "Restart triggered."})
        return web.json_response({"status": "error", "message": "Restart not available."}, status=501)

    # ── Analytics ────────────────────────────────────────────

    async def api_analytics(request):
        db = app.get("db")
        if not db:
            return web.json_response({"error": "Database not available"}, status=500)
        stats = await db.stats()
        # Add health data
        stats["health"] = health.summary()
        return web.json_response(stats)

    # ── Logs (last N lines) ──────────────────────────────────

    async def api_messages_recent(request):
        try:
            limit = min(int(request.query.get("limit", "100")), 1000)
        except (ValueError, TypeError):
            limit = 100
        try:
            offset = max(int(request.query.get("offset", "0")), 0)
        except (ValueError, TypeError):
            offset = 0
        source = request.query.get("source", None)
        if source == "all":
            source = None
        query = request.query.get("q", "").strip() or None
        db = app.get("db")
        if not db:
            return web.json_response({"messages": [], "total": 0})
        messages, total = await db.search(query=query, source=source, limit=limit, offset=offset)
        return web.json_response({"messages": messages, "total": total})

    async def api_export(request):
        """Export messages as JSON or CSV."""
        import re as _re
        fmt = request.query.get("format", "json")
        if fmt not in ("json", "csv"):
            fmt = "json"
        source = request.query.get("source")
        if source == "all":
            source = None
        start = request.query.get("start")
        end = request.query.get("end")
        try:
            limit = min(int(request.query.get("limit", "10000")), 50000)
        except (ValueError, TypeError):
            limit = 10000

        # Validate date formats if provided
        date_re = _re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")
        if start and not date_re.match(start):
            return web.json_response({"error": "Invalid start date format. Use YYYY-MM-DD."}, status=400)
        if end and not date_re.match(end):
            return web.json_response({"error": "Invalid end date format. Use YYYY-MM-DD."}, status=400)

        db = app.get("db")
        if not db:
            return web.json_response({"error": "Database not available"}, status=500)

        messages = await db.export(source=source, start=start, end=end, limit=limit)

        if fmt == "csv":
            import csv
            import io
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["source", "source_id", "author", "content", "translation", "matched_keywords", "url", "timestamp", "created_at"])
            writer.writeheader()
            writer.writerows(messages)
            return web.Response(
                body=output.getvalue(),
                content_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=osint_export.csv"},
            )

        return web.json_response({"messages": messages, "count": len(messages)})

    async def api_logs(request):
        try:
            n = min(int(request.query.get("lines", "100")), 1000)
        except (ValueError, TypeError):
            n = 100
        log_file = Path("logs/osint_monitor.log")
        if not log_file.exists():
            return web.json_response({"lines": []})
        if log_file.stat().st_size > 50 * 1024 * 1024:  # 50MB safety cap
            return web.json_response({"lines": ["[Log file too large to display. Clear logs or check the file directly.]"]})
        all_lines = log_file.read_text().splitlines()
        return web.json_response({"lines": all_lines[-n:]})

    # ── Update Check & Apply ──────────────────────────────────

    GITHUB_REPO = "TannerTunstall/OSINT-Monitor"
    _update_state = {"in_progress": False}

    async def api_update_check(request):
        """Check if a newer version is available on GitHub."""
        version_file = Path("VERSION")
        local_commit = version_file.read_text().strip() if version_file.exists() else "unknown"

        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"
                async with session.get(url, headers={"Accept": "application/vnd.github.v3+json"},
                                       timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return web.json_response({"error": "Cannot reach GitHub API"}, status=502)
                    data = await resp.json()
                    remote_commit = data.get("sha", "")
                    remote_message = data.get("commit", {}).get("message", "").split("\n")[0]
                    remote_date = data.get("commit", {}).get("committer", {}).get("date", "")

                    up_to_date = local_commit != "unknown" and remote_commit == local_commit
                    return web.json_response({
                        "local_commit": local_commit[:12] if local_commit != "unknown" else "unknown",
                        "remote_commit": remote_commit[:12],
                        "remote_message": remote_message,
                        "remote_date": remote_date,
                        "up_to_date": up_to_date,
                    })
        except Exception as exc:
            logger.warning("Update check failed: %s", exc)
            return web.json_response({"error": str(exc)}, status=502)

    def _get_host_project_path(container_data: dict) -> str | None:
        """Extract host project path from container bind mounts."""
        for mount in container_data.get("Mounts", []):
            if mount.get("Destination") == "/app/config.yaml":
                host_path = mount["Source"]
                # macOS Docker Desktop may prefix with /host_mnt
                if host_path.startswith("/host_mnt/"):
                    host_path = host_path[len("/host_mnt"):]
                return str(Path(host_path).parent)
        return None

    async def _ensure_image(docker, image: str):
        """Pull an image if it doesn't exist locally."""
        async with docker.get(f"http://localhost/images/{image}/json") as resp:
            if resp.status == 200:
                return  # Already exists
        logger.info("Pulling image %s...", image)
        async with docker.post(
            f"http://localhost/images/create?fromImage={image.split(':')[0]}&tag={image.split(':')[-1] if ':' in image else 'latest'}",
            timeout=aiohttp.ClientTimeout(total=300),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Cannot pull {image}: {body}")
            # Consume the stream to completion
            async for _ in resp.content:
                pass

    async def _create_and_run_container(docker, name: str, config: dict, timeout: int = 120) -> tuple[int, str]:
        """Create, start, wait for a container. Returns (exit_code, logs)."""
        # Ensure image exists
        await _ensure_image(docker, config["Image"])

        # Clean up any existing container with this name
        await docker.delete(f"http://localhost/containers/{name}?force=true")
        await asyncio.sleep(0.5)

        # Create
        async with docker.post(f"http://localhost/containers/create?name={name}", json=config) as resp:
            if resp.status != 201:
                body = await resp.text()
                raise RuntimeError(f"Cannot create {name}: {body}")

        # Start
        async with docker.post(f"http://localhost/containers/{name}/start") as resp:
            if resp.status not in (204, 304):
                raise RuntimeError(f"Cannot start {name}")

        # Wait
        async with docker.post(f"http://localhost/containers/{name}/wait",
                               timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            result = await resp.json()
            exit_code = result.get("StatusCode", -1)

        # Get logs (strip Docker stream headers by requesting raw)
        async with docker.get(f"http://localhost/containers/{name}/logs?stdout=true&stderr=true") as resp:
            raw = await resp.read()
            # Docker multiplexed stream: each frame has 8-byte header, strip them
            logs = ""
            i = 0
            while i < len(raw):
                if i + 8 <= len(raw):
                    size = int.from_bytes(raw[i+4:i+8], "big")
                    if i + 8 + size <= len(raw):
                        logs += raw[i+8:i+8+size].decode("utf-8", errors="replace")
                    i += 8 + size
                else:
                    break

        # Cleanup
        await docker.delete(f"http://localhost/containers/{name}?force=true")

        return exit_code, logs

    async def api_update_apply(request):
        """Safely update: backup config, clone fresh into /tmp, copy source files, verify, rebuild.

        Safety: git never runs in the project directory. Config and data are never touched.
        """
        if _update_state["in_progress"]:
            return web.json_response({"error": "Update already in progress"}, status=409)
        _update_state["in_progress"] = True

        try:
            import re as _re_update
            async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path="/var/run/docker.sock")) as docker:
                # Find host project path
                async with docker.get("http://localhost/containers/osint-monitor/json") as resp:
                    if resp.status != 200:
                        _update_state["in_progress"] = False
                        return web.json_response({"error": "Cannot inspect container"}, status=500)
                    host_path = _get_host_project_path(await resp.json())

                if not host_path:
                    _update_state["in_progress"] = False
                    return web.json_response({"error": "Cannot determine host project path"}, status=500)

                logger.info("Update: host path = %s", host_path)

                # ── Step 1: Pre-flight backup ──────────────────
                logger.info("Update: backing up config files...")
                preflight_cmd = (
                    'set -e; '
                    'if [ ! -f /repo/config.yaml ]; then echo "ABORT: config.yaml missing or is a directory" >&2; exit 1; fi; '
                    'if [ ! -f /repo/.env ]; then echo "ABORT: .env missing or is a directory" >&2; exit 1; fi; '
                    'TIMESTAMP=$(date +%Y%m%d_%H%M%S); '
                    'BACKUP_DIR="/repo/backups/${TIMESTAMP}"; '
                    'mkdir -p "$BACKUP_DIR"; '
                    'cp -p /repo/config.yaml "$BACKUP_DIR/config.yaml"; '
                    'cp -p /repo/.env "$BACKUP_DIR/.env"; '
                    'echo "$BACKUP_DIR" > /repo/backups/.latest; '
                    'cd /repo/backups && ls -dt */ 2>/dev/null | tail -n +6 | xargs rm -rf 2>/dev/null; '
                    'echo "PREFLIGHT_OK"'
                )
                exit_code, logs = await _create_and_run_container(docker, "osint-preflight", {
                    "Image": "alpine:latest",
                    "Cmd": ["sh", "-c", preflight_cmd],
                    "HostConfig": {"Binds": [f"{host_path}:/repo"]},
                })
                if exit_code != 0 or "PREFLIGHT_OK" not in logs:
                    _update_state["in_progress"] = False
                    return web.json_response({
                        "error": f"Pre-flight check failed — update aborted. Your files are untouched.\n{logs[-500:]}"
                    }, status=500)

                logger.info("Update: backup complete")

                # ── Step 2: Fresh clone into /tmp ──────────────
                logger.info("Update: cloning latest code from GitHub...")
                clone_cmd = (
                    'set -e; '
                    'TMPDIR="/hostmnt/tmp/osint-update-$$"; '
                    'mkdir -p "$TMPDIR"; '
                    f'git clone --depth 1 --branch main https://github.com/{GITHUB_REPO}.git "$TMPDIR/repo"; '
                    'git -C "$TMPDIR/repo" rev-parse HEAD; '
                    'echo "CLONE_DIR=$TMPDIR"'
                )
                exit_code, logs = await _create_and_run_container(docker, "osint-cloner", {
                    "Image": "alpine/git",
                    "Entrypoint": ["sh"],
                    "Cmd": ["-c", clone_cmd],
                    "HostConfig": {"Binds": ["/tmp:/hostmnt/tmp"]},
                }, timeout=120)
                if exit_code != 0:
                    _update_state["in_progress"] = False
                    return web.json_response({"error": f"Git clone failed:\n{logs[-500:]}"}, status=500)

                commit_match = _re_update.search(r'\b([0-9a-f]{40})\b', logs)
                new_commit = commit_match.group(1) if commit_match else "unknown"
                dir_match = _re_update.search(r'CLONE_DIR=(.+)', logs)
                clone_dir = dir_match.group(1).strip() if dir_match else None

                if not clone_dir:
                    _update_state["in_progress"] = False
                    return web.json_response({"error": "Could not determine clone directory"}, status=500)

                # Container path /hostmnt/tmp/... → host path /tmp/...
                host_clone_dir = clone_dir.replace("/hostmnt/tmp", "/tmp")
                logger.info("Update: cloned commit %s to %s", new_commit[:12], host_clone_dir)

                # ── Step 3: Copy source files only ─────────────
                logger.info("Update: copying source files (config/data untouched)...")
                overlay_cmd = (
                    'set -e; '
                    'CLONE="/clone/repo"; '
                    'DEST="/repo"; '
                    'rm -rf "$DEST/src" && cp -r "$CLONE/src" "$DEST/src"; '
                    'rm -rf "$DEST/tests" && cp -r "$CLONE/tests" "$DEST/tests" 2>/dev/null || true; '
                    'cp "$CLONE/Dockerfile" "$DEST/Dockerfile"; '
                    'cp "$CLONE/docker-compose.yml" "$DEST/docker-compose.yml"; '
                    'cp "$CLONE/docker-entrypoint.sh" "$DEST/docker-entrypoint.sh"; '
                    'cp "$CLONE/requirements.txt" "$DEST/requirements.txt"; '
                    'cp "$CLONE/setup.sh" "$DEST/setup.sh" 2>/dev/null || true; '
                    'cp "$CLONE/pyproject.toml" "$DEST/pyproject.toml" 2>/dev/null || true; '
                    'cp "$CLONE/.gitignore" "$DEST/.gitignore" 2>/dev/null || true; '
                    'cp "$CLONE/README.md" "$DEST/README.md" 2>/dev/null || true; '
                    'cp "$CLONE/CONTRIBUTING.md" "$DEST/CONTRIBUTING.md" 2>/dev/null || true; '
                    'cp "$CLONE/LICENSE" "$DEST/LICENSE" 2>/dev/null || true; '
                    'if [ -d "$CLONE/docs" ]; then rm -rf "$DEST/docs" && cp -r "$CLONE/docs" "$DEST/docs"; fi; '
                    'if [ -d "$CLONE/.github" ]; then rm -rf "$DEST/.github" && cp -r "$CLONE/.github" "$DEST/.github"; fi; '
                    'OWNER=$(stat -c "%u:%g" /repo 2>/dev/null || stat -f "%u:%g" /repo); '
                    'chown -R $OWNER "$DEST/src" "$DEST/Dockerfile" "$DEST/docker-compose.yml" '
                    '  "$DEST/docker-entrypoint.sh" "$DEST/requirements.txt" 2>/dev/null || true; '
                    'echo "OVERLAY_OK"'
                )
                exit_code, logs = await _create_and_run_container(docker, "osint-overlay", {
                    "Image": "alpine:latest",
                    "Cmd": ["sh", "-c", overlay_cmd],
                    "HostConfig": {
                        "Binds": [
                            f"{host_clone_dir}:/clone:ro",
                            f"{host_path}:/repo",
                        ],
                    },
                })
                if exit_code != 0 or "OVERLAY_OK" not in logs:
                    _update_state["in_progress"] = False
                    return web.json_response({"error": f"File copy failed:\n{logs[-500:]}"}, status=500)

                # ── Step 4: Post-flight verification ───────────
                logger.info("Update: verifying config files...")
                verify_cmd = (
                    'set -e; '
                    'BACKUP_DIR=$(cat /repo/backups/.latest 2>/dev/null); '
                    'if [ ! -f /repo/config.yaml ]; then '
                    '  echo "CRITICAL: config.yaml missing — restoring from backup"; '
                    '  if [ -n "$BACKUP_DIR" ] && [ -f "$BACKUP_DIR/config.yaml" ]; then '
                    '    rm -rf /repo/config.yaml 2>/dev/null || true; '
                    '    cp -p "$BACKUP_DIR/config.yaml" /repo/config.yaml; '
                    '  else echo "FATAL: no backup available" >&2; exit 1; fi; '
                    'fi; '
                    'if [ ! -f /repo/.env ]; then '
                    '  echo "CRITICAL: .env missing — restoring from backup"; '
                    '  if [ -n "$BACKUP_DIR" ] && [ -f "$BACKUP_DIR/.env" ]; then '
                    '    rm -rf /repo/.env 2>/dev/null || true; '
                    '    cp -p "$BACKUP_DIR/.env" /repo/.env; '
                    '  else echo "FATAL: no backup available" >&2; exit 1; fi; '
                    'fi; '
                    'if [ ! -s /repo/config.yaml ] && [ -n "$BACKUP_DIR" ] && [ -s "$BACKUP_DIR/config.yaml" ]; then '
                    '  cp -p "$BACKUP_DIR/config.yaml" /repo/config.yaml; '
                    '  echo "Restored empty config.yaml from backup"; '
                    'fi; '
                    'echo "VERIFY_OK"'
                )
                exit_code, logs = await _create_and_run_container(docker, "osint-verify", {
                    "Image": "alpine:latest",
                    "Cmd": ["sh", "-c", verify_cmd],
                    "HostConfig": {"Binds": [f"{host_path}:/repo"]},
                })
                if exit_code != 0 or "VERIFY_OK" not in logs:
                    _update_state["in_progress"] = False
                    return web.json_response({
                        "error": f"Post-update verification failed. Config restored from backup.\n{logs[-500:]}"
                    }, status=500)

                logger.info("Update: verification passed")

                # ── Step 5: Cleanup temp clone ─────────────────
                await _create_and_run_container(docker, "osint-cleanup", {
                    "Image": "alpine:latest",
                    "Cmd": ["sh", "-c", "rm -rf /hostmnt/tmp/osint-update-*"],
                    "HostConfig": {"Binds": ["/tmp:/hostmnt/tmp"]},
                })

                # ── Step 6: Rebuild container ──────────────────
                project_name = Path(host_path).name
                logger.info("Update: rebuilding container (project: %s)...", project_name)
                rebuild_config = {
                    "Image": "docker:cli",
                    "Cmd": ["sh", "-c",
                            f"docker compose -p {project_name} -f /repo/docker-compose.yml up -d --build osint-monitor"],
                    "WorkingDir": "/repo",
                    "Env": [f"GIT_COMMIT={new_commit}"],
                    "HostConfig": {
                        "Binds": [
                            f"{host_path}:/repo",
                            "/var/run/docker.sock:/var/run/docker.sock",
                        ],
                    },
                }

                await _ensure_image(docker, "docker:cli")
                await docker.delete("http://localhost/containers/osint-rebuilder?force=true")
                await asyncio.sleep(0.5)
                async with docker.post("http://localhost/containers/create?name=osint-rebuilder",
                                       json=rebuild_config) as resp:
                    if resp.status != 201:
                        body = await resp.text()
                        _update_state["in_progress"] = False
                        return web.json_response({"error": f"Cannot create rebuilder: {body}"}, status=500)

                # Schedule rebuilder start AFTER response is sent
                async def _start_rebuilder():
                    await asyncio.sleep(1)
                    try:
                        async with aiohttp.ClientSession(
                            connector=aiohttp.UnixConnector(path="/var/run/docker.sock")
                        ) as d:
                            await d.post("http://localhost/containers/osint-rebuilder/start")
                            logger.info("Update: rebuilder started — this container will be replaced")
                    except Exception:
                        logger.exception("Update: failed to start rebuilder")

                asyncio.create_task(_start_rebuilder())

                return web.json_response({
                    "status": "updating",
                    "message": "Code updated safely. Rebuilding container...",
                    "new_commit": new_commit[:12],
                })

        except Exception as exc:
            logger.exception("Update failed")
            _update_state["in_progress"] = False
            return web.json_response({"error": str(exc)}, status=500)

    async def api_logs_clear(request):
        log_file = Path("logs/osint_monitor.log")
        if log_file.exists():
            log_file.write_text("")
            logger.info("Logs cleared via dashboard")
        return web.json_response({"status": "ok", "message": "Logs cleared"})

    # ── Routes ───────────────────────────────────────────────

    app.router.add_get("/", index)
    app.router.add_get("/api/setup-status", api_setup_status)
    app.router.add_get("/api/health", api_health)
    app.router.add_get("/api/config", api_config_get)
    app.router.add_put("/api/config", api_config_put)
    app.router.add_post("/api/config/validate", api_config_validate)
    app.router.add_get("/api/sources", api_sources_get)
    app.router.add_put("/api/sources", api_sources_put)
    app.router.add_get("/api/notifiers", api_notifiers_get)
    app.router.add_put("/api/notifiers", api_notifiers_put)
    app.router.add_get("/api/filters", api_filters_get)
    app.router.add_put("/api/filters", api_filters_put)
    app.router.add_get("/api/polling", api_polling_get)
    app.router.add_put("/api/polling", api_polling_put)
    app.router.add_get("/api/credentials", api_credentials_get)
    app.router.add_put("/api/credentials", api_credentials_put)
    app.router.add_post("/api/whatsapp/start", api_whatsapp_start)
    app.router.add_get("/api/whatsapp/qr", api_whatsapp_qr)
    app.router.add_get("/api/whatsapp/status", api_whatsapp_status)
    app.router.add_post("/api/test-notification", api_test_notification)
    app.router.add_get("/api/translate/status", api_translate_status)
    app.router.add_post("/api/translate/configure", api_translate_configure)
    app.router.add_post("/api/test-source", api_test_source)
    app.router.add_post("/api/restart", api_restart)
    app.router.add_get("/api/analytics", api_analytics)
    app.router.add_get("/api/messages/recent", api_messages_recent)
    app.router.add_get("/api/export", api_export)
    app.router.add_get("/api/logs", api_logs)
    app.router.add_post("/api/logs/clear", api_logs_clear)
    app.router.add_get("/api/update/check", api_update_check)
    app.router.add_post("/api/update/apply", api_update_apply)
    app.router.add_static("/static/", static_dir)

    # Telegram auth routes
    add_telegram_auth_routes(app, telegram_auth)

    return app
