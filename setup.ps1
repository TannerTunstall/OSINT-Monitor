# ============================================================
# OSINT Monitor — Windows Setup (PowerShell)
# Requires: Docker Desktop for Windows
# Run: powershell -ExecutionPolicy Bypass -File setup.ps1
# ============================================================

$ErrorActionPreference = "Stop"

function Info($msg) { Write-Host "[+] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "[x] $msg" -ForegroundColor Red; exit 1 }

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $AppDir

# ── Check Docker ─────────────────────────────────────────────

$dockerPath = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerPath) {
    $installDocker = Read-Host "Docker not found. Install Docker Desktop via winget? (y/n)"
    if ($installDocker -eq 'y') {
        Info "Installing Docker Desktop..."
        winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
        Write-Host ""
        Warn "Docker Desktop installed. Please:"
        Warn "  1. Open Docker Desktop from the Start menu"
        Warn "  2. Wait for it to finish starting"
        Warn "  3. Re-run this script"
        exit 0
    } else {
        Fail "Docker is required. Install from: https://www.docker.com/products/docker-desktop/"
    }
}

Info "Docker found."

# ── Verify Docker is running ─────────────────────────────────

try {
    docker info 2>$null | Out-Null
} catch {
    Fail "Docker is installed but not running. Open Docker Desktop and try again."
}

# ── Check docker compose ─────────────────────────────────────

try {
    docker compose version 2>$null | Out-Null
    $Compose = "docker compose"
} catch {
    Fail "docker compose not found. Update Docker Desktop to the latest version."
}

Info "Using: $Compose"

# ── Create minimal files if missing ──────────────────────────

if (-not (Test-Path ".env")) { New-Item -ItemType File -Path ".env" | Out-Null }

if (-not (Test-Path "config.yaml")) {
    Set-Content -Path "config.yaml" -Value "# OSINT Monitor - configure via web dashboard at :8550"
}

$dirs = @("data", "logs", "telegram_session", "whatsapp-data", "session")
foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
}

# ── Detect ARM for WAHA image tag ────────────────────────────

$arch = (Get-WmiObject Win32_Processor).Architecture
if ($arch -eq 12) {
    $env:WAHA_TAG = "arm"
    Info "ARM detected — using WAHA ARM image."
} else {
    $env:WAHA_TAG = "latest"
}

# ── Build and start ──────────────────────────────────────────

Info "Building and starting OSINT Monitor..."
docker compose up -d --build

# ── Print access URL ─────────────────────────────────────────

$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notlike "*Loopback*" -and $_.PrefixOrigin -ne "WellKnown" } | Select-Object -First 1).IPAddress
if (-not $ip) { $ip = "localhost" }

Write-Host ""
Write-Host "============================================================"
Write-Host "  OSINT Monitor is running." -ForegroundColor Green
Write-Host ""
Write-Host "  Open the dashboard to complete setup:"
Write-Host ""
Write-Host "    http://${ip}:8550"
Write-Host ""
Write-Host "  Everything is configured from the browser."
Write-Host "  No terminal needed after this point."
Write-Host "============================================================"
