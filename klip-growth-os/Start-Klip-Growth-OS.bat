@echo off
REM Klip Growth OS launcher. Double-click (or use the desktop shortcut).
REM First run: creates a private Python environment and the local database.
REM Every run: starts the app in the background (if not already running) and opens the dashboard.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo Setting up Klip Growth OS for the first time. This takes a minute...
  where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
  if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Python 3.11+ is required. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run this again.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 ( echo Dependency install failed. & pause & exit /b 1 )
)

if not exist "data\growth_os.db" (
  ".venv\Scripts\python.exe" -m growth_os init
)

REM Starts hidden. If it is already running, this just opens the browser.
start "" ".venv\Scripts\pythonw.exe" -m growth_os serve --open
endlocal
