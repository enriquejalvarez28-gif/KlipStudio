#!/bin/sh
# Daily consistent SQLite backup, kept 14 days. Add to the server's crontab:
#   15 3 * * * /path/to/harvey-agent/deploy/server/backup.sh
# Copy data/backups off the server too (e.g. rclone to Google Drive) so a
# lost server doesn't lose the pipeline.
set -eu
cd "$(dirname "$0")/../.."
mkdir -p data/backups
stamp=$(date +%Y%m%d)
python3 -c "import sqlite3,sys; s=sqlite3.connect('data/harvey.db'); d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close()" "data/backups/harvey-$stamp.db"
cp data/gmail_token.json "data/backups/gmail_token-$stamp.json" 2>/dev/null || true
find data/backups -type f -mtime +14 -delete
