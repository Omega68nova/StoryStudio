param([string]$CaddyExecutable = "")

# A per-user logon task is used because caddy.exe is a console process rather
# than a native Windows service. It does not require storing a user password.
$ErrorActionPreference = "Stop"
$launcher = (Resolve-Path (Join-Path $PSScriptRoot "start-caddy.ps1")).Path
if ($CaddyExecutable) {
  $argument = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`" -CaddyExecutable `"$CaddyExecutable`""
} else {
  $argument = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
}
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "StoryStudio Caddy" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "HTTPS reverse proxy for StoryStudio" -Force
Write-Host "Installed the StoryStudio Caddy logon task. Forward router TCP 443 to this computer and remove the public TCP 8765 forward."
