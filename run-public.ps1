[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$appLauncher = (Resolve-Path (Join-Path $PSScriptRoot "start.ps1")).Path
$caddyLauncher = (Resolve-Path (Join-Path $PSScriptRoot "deploy\start-caddy.ps1")).Path

function Test-StoryStudioHealth {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
        return $health.status -eq "ok"
    } catch {
        return $false
    }
}

if (-not (Test-StoryStudioHealth)) {
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $appLauncher
    ) -WindowStyle Hidden
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-StoryStudioHealth) { $ready = $true; break }
    }
    if (-not $ready) { throw "StoryStudio did not become ready on 127.0.0.1:8765." }
}

$httpsListener = Get-NetTCPConnection -State Listen -LocalPort 443 -ErrorAction SilentlyContinue
if (-not $httpsListener) {
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $caddyLauncher
    ) -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        Start-Sleep -Seconds 1
        if (Get-NetTCPConnection -State Listen -LocalPort 443 -ErrorAction SilentlyContinue) { break }
    }
}

if (-not (Get-NetTCPConnection -State Listen -LocalPort 443 -ErrorAction SilentlyContinue)) {
    throw "Caddy did not begin listening on HTTPS port 443."
}

Write-Host "StoryStudio is running locally at http://127.0.0.1:8765"
Write-Host "Public access is available at https://84.78.155.96/"
Write-Host "Run .\stop-public.ps1 when you are finished to release port 443."
