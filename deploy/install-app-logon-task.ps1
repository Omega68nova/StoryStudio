$ErrorActionPreference = "Stop"
$launcher = (Resolve-Path (Join-Path $PSScriptRoot "..\start.ps1")).Path
$argument = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "StoryStudio App" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Loopback StoryStudio application server" -Force
Write-Host "Installed the StoryStudio application logon task."
