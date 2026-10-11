# Windows (Enrique's production PC): installs video-pizarra into %USERPROFILE%\.claude\skills
# pinned to the same reviewed commit as install.sh.
#   powershell -ExecutionPolicy Bypass -File .claude\skills\klip-video-pizarra\scripts\install.ps1
$ErrorActionPreference = 'Stop'
$Repo = 'https://github.com/santmun/video-pizarra.git'
$Pin  = 'dc6adc4198027f26c60f5980c956e0a678e05aed'
$Dest = if ($env:VIDEO_PIZARRA_DIR) { $env:VIDEO_PIZARRA_DIR } else { Join-Path $env:USERPROFILE '.claude\skills\video-pizarra' }

if (-not (Test-Path (Join-Path $Dest '.git'))) {
  New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
  git clone --quiet $Repo $Dest
}
git -C $Dest fetch --quiet origin
git -C $Dest -c advice.detachedHead=false checkout --quiet $Pin
Write-Host "video-pizarra installed at $Dest"

# Also make the Klip wrapper available outside this repo.
$Wrapper = Join-Path $env:USERPROFILE '.claude\skills\klip-video-pizarra'
Copy-Item -Recurse -Force (Join-Path $PSScriptRoot '..') $Wrapper
Write-Host "klip-video-pizarra copied to $Wrapper"

foreach ($bin in 'node','npx','ffmpeg','python') {
  if (-not (Get-Command $bin -ErrorAction SilentlyContinue)) { Write-Host "MISSING: $bin" }
}
