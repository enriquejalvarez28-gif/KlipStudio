# Stops the background Klip Growth OS server (scheduled jobs pause until next start).
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*growth_os serve*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped process $($_.ProcessId)" }
