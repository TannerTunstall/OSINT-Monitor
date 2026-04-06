#!/bin/sh
# Fix ownership on bind-mounted volumes so appuser (UID 1000) can write.
# Runs as root, then drops to appuser for the application.

chown -R appuser:appuser /app/data /app/logs /app/session 2>/dev/null || true
chown appuser:appuser /app/config.yaml /app/.env /app/docker-compose.yml 2>/dev/null || true

# Allow appuser to access Docker socket for container management
# (WAHA, Signal, LibreTranslate, updates)
chmod 666 /var/run/docker.sock 2>/dev/null || true

exec su -s /bin/sh appuser -c "python -m src.main $*"
