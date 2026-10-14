<#
  Creates "Klip Growth OS" shortcuts on the Desktop and in the Start Menu.
  -AutoStart also starts it when you sign in to Windows, so scheduled jobs
  (6-hourly sync, daily checks, Monday reports) run whenever the computer is on.

  Run from the klip-growth-os folder:
    powershell -ExecutionPolicy Bypass -File windows\Install-Shortcut.ps1 [-AutoStart]
#>
param([switch]$AutoStart)
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root "Start-Klip-Growth-OS.bat"
$icon = Join-Path $root "growth_os\web\favicon.ico"
$shell = New-Object -ComObject WScript.Shell

function New-Link($path) {
  $lnk = $shell.CreateShortcut($path)
  $lnk.TargetPath = $target
  $lnk.WorkingDirectory = $root
  $lnk.IconLocation = $icon
  $lnk.WindowStyle = 7   # minimized: the console only appears during first-time setup
  $lnk.Description = "Klip Growth OS owner dashboard"
  $lnk.Save()
  Write-Host "Created $path"
}

New-Link (Join-Path ([Environment]::GetFolderPath("Desktop")) "Klip Growth OS.lnk")
New-Link (Join-Path ([Environment]::GetFolderPath("Programs")) "Klip Growth OS.lnk")
if ($AutoStart) {
  New-Link (Join-Path ([Environment]::GetFolderPath("Startup")) "Klip Growth OS.lnk")
  Write-Host "Klip Growth OS will start when you sign in."
}
Write-Host "Done. Double-click 'Klip Growth OS' on your desktop. Dashboard: http://127.0.0.1:8765/"
