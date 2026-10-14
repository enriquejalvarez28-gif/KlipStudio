@echo off
REM Starts the KLIP dashboard and the Harvey agent (works only inside its
REM work_schedule shifts; sending stays off until approved in harvey.yaml).
cd /d "%~dp0harvey-agent"
if not exist data mkdir data
start "KLIP Dashboard" /min .venv\Scripts\python.exe -c "from harvey.dashboard import start_dashboard; start_dashboard()"
start "KLIP Harvey" /min cmd /c ".venv\Scripts\python.exe -m harvey.main >> data\harvey.log 2>&1"
timeout /t 3 >nul
start "" http://127.0.0.1:5555/leads
echo Harvey started. Log: %CD%\data\harvey.log
