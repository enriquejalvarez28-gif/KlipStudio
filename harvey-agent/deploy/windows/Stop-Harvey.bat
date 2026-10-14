@echo off
REM Stops Harvey and the dashboard. Safe: state is in SQLite; on the next
REM start Harvey reads replies and re-checks GoHighLevel before any send.
taskkill /FI "WINDOWTITLE eq KLIP Harvey*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq KLIP Dashboard*" /T /F >nul 2>&1
echo Harvey stopped.
