[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backendPath = Join-Path $projectRoot 'backend'
$venvPython = Join-Path $backendPath '.venv\Scripts\python.exe'
$frontendIndex = Join-Path $projectRoot 'frontend\dist\index.html'

if (-not (Test-Path -LiteralPath $venvPython) -or -not (Test-Path -LiteralPath $frontendIndex)) {
    throw 'StoryStudio is not set up. Run .\setup.ps1 first.'
}

try {
    $existing = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
    if ($existing.status -eq 'ok') {
        Write-Host "StoryStudio is already running at http://127.0.0.1:$Port"
        exit 0
    }
} catch {
    # Nothing is listening yet; continue with normal startup.
}

Write-Host "StoryStudio is starting at http://127.0.0.1:$Port"
Push-Location $backendPath
try {
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
