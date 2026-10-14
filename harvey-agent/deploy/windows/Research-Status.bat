@echo off
cd /d "%~dp0harvey-agent"
.venv\Scripts\python.exe -m harvey.cli research list
.venv\Scripts\python.exe -m harvey.cli status
pause
