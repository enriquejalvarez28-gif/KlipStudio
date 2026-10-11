#!/usr/bin/env bash
# Installs Santiago Muñoz's video-pizarra skill (github.com/santmun/video-pizarra)
# into ~/.claude/skills/video-pizarra, pinned to a reviewed commit.
# The upstream repo has no license, so it is fetched from the author instead of
# being copied into this public repo.
#
#   bash .claude/skills/klip-video-pizarra/scripts/install.sh            # install if missing
#   bash .claude/skills/klip-video-pizarra/scripts/install.sh --update   # move to the pinned commit
set -euo pipefail

REPO=https://github.com/santmun/video-pizarra.git
# Reviewed 2026-10-11: only network calls are Google Fonts, sunoapi.org (music, opt-in key)
# and AssemblyAI (voice-over word timing, opt-in key). Bump after reviewing a newer commit.
PIN=dc6adc4198027f26c60f5980c956e0a678e05aed
DEST=${VIDEO_PIZARRA_DIR:-$HOME/.claude/skills/video-pizarra}

if [ -d "$DEST/.git" ] && [ "${1:-}" != "--update" ]; then
  echo "video-pizarra already installed at $DEST ($(git -C "$DEST" rev-parse --short HEAD))"
  exit 0
fi

if [ ! -d "$DEST/.git" ]; then
  mkdir -p "$(dirname "$DEST")"
  git clone --quiet "$REPO" "$DEST"
fi
git -C "$DEST" fetch --quiet origin
git -C "$DEST" -c advice.detachedHead=false checkout --quiet "$PIN"
echo "video-pizarra installed at $DEST ($(git -C "$DEST" rev-parse --short HEAD))"

# Render dependencies: report what is missing instead of installing system packages.
for bin in node npx ffmpeg python3; do
  command -v "$bin" >/dev/null || echo "MISSING: $bin (see $DEST/README.md)"
done
python3 -c "import numpy, PIL" 2>/dev/null || echo "MISSING: python packages -> pip install numpy pillow"
