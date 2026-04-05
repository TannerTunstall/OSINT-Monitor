# Troubleshooting

## WhatsApp

**WhatsApp disconnected / not receiving messages:**
Dashboard > Delivery > click "Re-pair WhatsApp" and scan the QR code again with your phone.

**WAHA container not starting:**
Check logs: `docker compose logs whatsapp-api`. Ensure port 3000 is not in use by another service.

## Telegram

**Telegram auth expired:**
The dashboard will detect this and prompt you to re-authenticate (phone + verification code).

**Session file issues:**
Telegram session files are stored in `session/` (or `telegram_session/` in Docker). If you get persistent auth errors, delete the `.session` file and re-authenticate via the dashboard.

## Twitter/X (Nitter)

**No tweets coming through:**
Nitter instances go down frequently. Update your instance list in Dashboard > Sources > Twitter. Check instance availability at community-maintained Nitter instance lists.

**yt-dlp fallback:**
If all Nitter instances fail, the Docker image includes yt-dlp as a fallback. This is automatic but slower.

## RSS Feeds

**Feed not updating:**
Check that the feed URL is accessible. Some feeds require specific User-Agent headers. Check logs for HTTP error codes.

## Translation

**Translation not working:**
- Ensure the LibreTranslate container is running: `docker compose logs translate`
- First startup can take several minutes while language models download
- If running without Docker, set `translation.api_url` to your LibreTranslate instance

**Wrong language detected:**
LibreTranslate uses automatic language detection. If it's misdetecting, ensure your `target_language` is set correctly in config.

## Docker / LXC

**Container won't start (LXC):**
Enable nesting: `pct set <CTID> --features nesting=1` then restart the container.

**Port conflicts:**
Default ports: 8550 (dashboard), 3000 (WAHA), 5000 (LibreTranslate). Change them in `docker-compose.yml` if needed.

**Config file becomes a directory:**
If `config.yaml` doesn't exist before Docker starts, Docker creates it as a directory. Fix: `rm -rf config.yaml && touch config.yaml && docker compose up -d`.

## General

**No notifications being sent:**
1. Check Dashboard > Health for connector status
2. Check Dashboard > Logs for errors
3. Try Dashboard > Delivery > "Send Test Notification"
4. Verify your notifier config has valid credentials/URLs

**Messages being filtered out:**
Check your keyword filters in Dashboard > Filters. If `include_keywords` is set, only matching messages pass through.

**High memory usage:**
LibreTranslate can use significant memory (~500MB+). If running on a constrained system, consider disabling translation or using a remote LibreTranslate instance.

## macOS

**"Cannot connect to the Docker daemon":**
Open Docker Desktop from Applications and wait for the whale icon in the menu bar to stop animating. Then re-run `bash setup.sh`.

**Homebrew not found:**
Install Homebrew first: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`

**Port 8550 already in use:**
Check what's using it: `lsof -i :8550`. Stop the other process or change the port in `docker-compose.yml`.

## Windows

**"Docker is installed but not running":**
Open Docker Desktop from the Start menu. Wait for "Docker Desktop is running" in the system tray. Then re-run the setup script.

**PowerShell execution policy error:**
Run: `powershell -ExecutionPolicy Bypass -File setup.ps1`

**WSL2 not installed:**
Docker Desktop on Windows requires WSL2. If prompted, follow the Docker Desktop installer instructions to enable it, or run: `wsl --install` in an admin terminal and restart.

**Line ending issues (git clone on Windows):**
If you see errors about `\r` in shell scripts, configure git: `git config --global core.autocrlf input` and re-clone.
