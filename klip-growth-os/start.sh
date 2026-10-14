#!/usr/bin/env sh
# macOS/Linux launcher (same behaviour as Start-Klip-Growth-OS.bat).
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -q --disable-pip-version-check -r requirements.txt || exit 1
fi
[ -f data/growth_os.db ] || .venv/bin/python -m growth_os init
nohup .venv/bin/python -m growth_os serve --open >/dev/null 2>&1 &
echo "Klip Growth OS: http://127.0.0.1:8765/"
