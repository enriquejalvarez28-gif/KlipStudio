# KLIP MEDIA — Lead Generation & Sales OS: one-time setup on Windows.
#
# Creates C:\KlipCreativeOS\KLIP-LEAD-OS with ONLY the Lead OS (Harvey) from
# the Git branch (sparse checkout: the website files are not checked out),
# a Python venv, the database, and the start/stop shortcuts.
#
# Run in PowerShell:
#   powershell -ExecutionPolicy Bypass -File setup-klip-lead-os.ps1
# Needs: Git, Python 3.11+ (py launcher), Claude Code logged in (claude login).
param(
  [string]$Root = "C:\KlipCreativeOS\KLIP-LEAD-OS",
  [string]$Repo = "https://github.com/enriquejalvarez28-gif/klipstudio.git",
  [string]$Branch = "claude/klip-studio-website-2mKDS",
  [string]$ResearchJson = ""
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path (Split-Path $Root) | Out-Null

if (-not (Test-Path "$Root\.git")) {
  git clone --filter=blob:none --sparse --branch $Branch --single-branch $Repo $Root
  Push-Location $Root
  git sparse-checkout set harvey-agent
  Pop-Location
} else {
  Push-Location $Root; git pull --ff-only; Pop-Location
}

$App = Join-Path $Root "harvey-agent"
Push-Location $App
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -e ".[jobs]"
if (-not (Test-Path ".env")) { Copy-Item .env.example .env; Write-Host "Created .env (fill in keys later; research works without them)." }
New-Item -ItemType Directory -Force -Path data | Out-Null
& .\.venv\Scripts\python.exe -c "import asyncio; from harvey.state import StateManager; asyncio.run(StateManager().init_db())"
if ($ResearchJson -and (Test-Path $ResearchJson)) {
  & .\.venv\Scripts\python.exe -m harvey.cli research import $ResearchJson
}
# Desktop-style shortcuts in the project root
Copy-Item deploy\windows\*.bat $Root -Force
Pop-Location

Write-Host ""
Write-Host "KLIP Lead OS is ready in $Root"
Write-Host "  Start:      $Root\Start-Harvey.bat     (agent + dashboard)"
Write-Host "  Dashboard:  http://127.0.0.1:5555/leads"
Write-Host "  Stop:       $Root\Stop-Harvey.bat"
