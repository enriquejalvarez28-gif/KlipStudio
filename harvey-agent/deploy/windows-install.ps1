# Registers Harvey as a Windows scheduled task that starts when you log in
# and restarts if it stops. Harvey sleeps outside its work_schedule shifts
# on its own, so it can stay running all the time.
#
# Run from the harvey-agent folder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File deploy\windows-install.ps1
# Remove it:
#   Unregister-ScheduledTask -TaskName "Harvey (Klip Studio)" -Confirm:$false

$dir = (Get-Location).Path
$python = Join-Path $dir ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No venv found. Run: py -3.13 -m venv .venv; .venv\Scripts\pip install -e ." }
New-Item -ItemType Directory -Force -Path (Join-Path $dir "data") | Out-Null

$action = New-ScheduledTaskAction -Execute "cmd.exe" `
  -Argument "/c `"$python`" -m harvey.main >> data\harvey.log 2>&1" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "Harvey (Klip Studio)" -Action $action -Trigger $trigger `
  -Settings $settings -Description "Harvey sales agent for The Klip Studio" -Force | Out-Null
Start-ScheduledTask -TaskName "Harvey (Klip Studio)"
Write-Host "Harvey is running. Log: $dir\data\harvey.log"
