import asyncio
import logging
from pathlib import Path

from aiohttp import web
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

logger = logging.getLogger(__name__)

SESSION_DIR = "session"


class TelegramAuthManager:
    """Manages Telegram authentication via web API instead of interactive terminal."""

    def __init__(self):
        self._client: TelegramClient | None = None
        self._phone: str | None = None
        self._phone_code_hash: str | None = None
        self._state: str = "idle"  # idle, awaiting_code, awaiting_2fa, authenticated

    @property
    def state(self) -> str:
        return self._state

    def _session_exists(self) -> bool:
        return any(Path(SESSION_DIR).glob("*.session"))

    async def check_status(self) -> dict:
        """Check if we already have a valid Telegram session."""
        if self._state == "authenticated":
            return {"status": "authenticated"}

        if self._session_exists():
            return {"status": "session_exists", "message": "Telegram session file found."}

        return {"status": "not_configured"}

    async def start_auth(self, api_id: int, api_hash: str, phone: str) -> dict:
        """Step 1: Send phone number, Telegram sends verification code."""
        try:
            Path(SESSION_DIR).mkdir(parents=True, exist_ok=True)
            self._client = TelegramClient(
                f"{SESSION_DIR}/osint_monitor", api_id, api_hash
            )
            await self._client.connect()

            result = await self._client.send_code_request(phone)
            self._phone = phone
            self._phone_code_hash = result.phone_code_hash
            self._state = "awaiting_code"

            return {
                "status": "awaiting_code",
                "message": "Verification code sent to your Telegram app.",
            }
        except FloodWaitError as e:
            return {
                "status": "error",
                "message": f"Rate limited. Wait {e.seconds} seconds and try again.",
            }
        except Exception as e:
            logger.exception("Telegram auth start failed")
            return {"status": "error", "message": str(e)}

    async def submit_code(self, code: str) -> dict:
        """Step 2: Submit the verification code."""
        if self._state != "awaiting_code" or not self._client:
            return {"status": "error", "message": "No pending auth. Start again."}

        try:
            await self._client.sign_in(
                phone=self._phone,
                code=code,
                phone_code_hash=self._phone_code_hash,
            )
            self._state = "authenticated"
            await self._client.disconnect()
            return {"status": "authenticated", "message": "Telegram authenticated successfully!"}

        except SessionPasswordNeededError:
            self._state = "awaiting_2fa"
            return {
                "status": "awaiting_2fa",
                "message": "Two-factor authentication is enabled. Enter your 2FA password.",
            }
        except PhoneCodeInvalidError:
            return {"status": "error", "message": "Invalid code. Try again."}
        except PhoneCodeExpiredError:
            self._state = "idle"
            return {"status": "error", "message": "Code expired. Start auth again."}
        except Exception as e:
            logger.exception("Telegram code submission failed")
            return {"status": "error", "message": str(e)}

    async def submit_2fa(self, password: str) -> dict:
        """Step 3: Submit 2FA password if required."""
        if self._state != "awaiting_2fa" or not self._client:
            return {"status": "error", "message": "No pending 2FA. Start again."}

        try:
            await self._client.sign_in(password=password)
            self._state = "authenticated"
            await self._client.disconnect()
            return {"status": "authenticated", "message": "Telegram authenticated successfully!"}
        except Exception as e:
            logger.exception("Telegram 2FA submission failed")
            return {"status": "error", "message": str(e)}

    async def cleanup(self):
        if self._client and self._client.is_connected():
            await self._client.disconnect()


def add_telegram_auth_routes(app: web.Application, auth_manager: TelegramAuthManager):
    """Register Telegram auth API routes."""

    async def status(request):
        result = await auth_manager.check_status()
        return web.json_response(result)

    async def start(request):
        data = await request.json()
        api_id = int(data.get("api_id", 0))
        api_hash = data.get("api_hash", "")
        phone = data.get("phone", "")
        if not all([api_id, api_hash, phone]):
            return web.json_response(
                {"status": "error", "message": "api_id, api_hash, and phone are required."},
                status=400,
            )
        result = await auth_manager.start_auth(api_id, api_hash, phone)
        return web.json_response(result)

    async def code(request):
        data = await request.json()
        result = await auth_manager.submit_code(data.get("code", ""))
        return web.json_response(result)

    async def twofa(request):
        data = await request.json()
        result = await auth_manager.submit_2fa(data.get("password", ""))
        return web.json_response(result)

    app.router.add_get("/api/telegram-auth/status", status)
    app.router.add_post("/api/telegram-auth/start", start)
    app.router.add_post("/api/telegram-auth/code", code)
    app.router.add_post("/api/telegram-auth/2fa", twofa)
