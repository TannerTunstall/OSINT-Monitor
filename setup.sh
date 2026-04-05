#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# OSINT Monitor — Cross-Platform Setup
# Supports: Ubuntu/Debian, macOS, other Linux distros
# Requires: Docker (installed automatically on supported systems)
# ============================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
fail()  { echo -e "${RED}[x]${NC} $1"; exit 1; }

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

OS="$(uname -s)"

# ── Install Docker if missing ────────────────────────────────

install_docker_linux() {
  if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO="$ID"
  else
    DISTRO="unknown"
  fi

  case "$DISTRO" in
    ubuntu|debian)
      info "Installing Docker via official repository (${DISTRO})..."
      apt-get update -qq
      apt-get install -y -qq ca-certificates curl gnupg
      install -m 0755 -d /etc/apt/keyrings
      curl -fsSL "https://download.docker.com/linux/${DISTRO}/gpg" | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
      chmod a+r /etc/apt/keyrings/docker.gpg
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/${DISTRO} $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
      apt-get update -qq
      apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
      systemctl enable --now docker
      ;;
    fedora|rhel|centos)
      info "Installing Docker via dnf (${DISTRO})..."
      dnf -y install dnf-plugins-core
      dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
      dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
      systemctl enable --now docker
      ;;
    arch|manjaro)
      info "Installing Docker via pacman (${DISTRO})..."
      pacman -Sy --noconfirm docker docker-compose
      systemctl enable --now docker
      ;;
    *)
      fail "Unsupported Linux distro: ${DISTRO}. Install Docker manually: https://docs.docker.com/engine/install/"
      ;;
  esac
}

if ! command -v docker &>/dev/null; then
  case "$OS" in
    Linux)
      install_docker_linux
      info "Docker installed."
      ;;
    Darwin)
      if command -v brew &>/dev/null; then
        warn "Docker not found. Installing Docker Desktop via Homebrew..."
        warn "You will need to open Docker Desktop after installation."
        brew install --cask docker
        echo ""
        warn "Docker Desktop installed but NOT running yet."
        warn "Please open Docker Desktop from Applications, wait for it to start,"
        warn "then re-run this script."
        exit 0
      else
        fail "Docker not found. Install Docker Desktop from: https://www.docker.com/products/docker-desktop/"
      fi
      ;;
    *)
      fail "Unsupported OS: ${OS}. Install Docker manually: https://docs.docker.com/get-docker/"
      ;;
  esac
else
  info "Docker already installed."
fi

# ── Verify Docker is running ────────────────────────────────

if ! docker info &>/dev/null 2>&1; then
  case "$OS" in
    Darwin)
      fail "Docker is installed but not running. Open Docker Desktop and try again."
      ;;
    *)
      fail "Docker is installed but not running. Start Docker with: sudo systemctl start docker"
      ;;
  esac
fi

# ── Check docker compose ────────────────────────────────────

if docker compose version &>/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE="docker-compose"
else
  fail "docker compose not found. Install Docker Compose: https://docs.docker.com/compose/install/"
fi

info "Using: $COMPOSE"

# ── Create minimal files if missing ──────────────────────────

touch "$APP_DIR/.env"

# config.yaml MUST exist as a file before Docker mounts it, otherwise Docker creates a directory
if [ ! -f "$APP_DIR/config.yaml" ]; then
  echo "# OSINT Monitor - configure via web dashboard at :8550" > "$APP_DIR/config.yaml"
fi

mkdir -p data logs telegram_session whatsapp-data session

# ── Detect ARM for WAHA image tag ────────────────────────────

ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then
  WAHA_VAL="arm"
  info "ARM detected — using WAHA ARM image."
else
  WAHA_VAL="latest"
fi

# Persist WAHA_TAG in .env so bare `docker compose up` always works
if grep -q "^WAHA_TAG=" "$APP_DIR/.env" 2>/dev/null; then
  sed -i.bak "s/^WAHA_TAG=.*/WAHA_TAG=${WAHA_VAL}/" "$APP_DIR/.env" && rm -f "$APP_DIR/.env.bak"
else
  echo "WAHA_TAG=${WAHA_VAL}" >> "$APP_DIR/.env"
fi

# ── Build and start ──────────────────────────────────────────

info "Building and starting OSINT Monitor..."
$COMPOSE up -d --build

# ── Print access URL ─────────────────────────────────────────

get_ip() {
  case "$OS" in
    Linux)  hostname -I 2>/dev/null | awk '{print $1}' ;;
    Darwin) ipconfig getifaddr en0 2>/dev/null || echo "localhost" ;;
    *)      echo "localhost" ;;
  esac
}

SERVER_IP=$(get_ip)

echo ""
echo "============================================================"
echo -e "  ${GREEN}OSINT Monitor is running.${NC}"
echo ""
echo "  Open the dashboard to complete setup:"
echo ""
echo "    http://${SERVER_IP}:8550"
echo ""
echo "  Everything is configured from the browser."
echo "  No terminal needed after this point."
echo "============================================================"
