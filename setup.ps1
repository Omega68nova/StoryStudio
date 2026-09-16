[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backendPath = Join-Path $projectRoot 'backend'
$frontendPath = Join-Path $projectRoot 'frontend'
$venvPython = Join-Path $backendPath '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv (Join-Path $backendPath '.venv')
}

& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $backendPath 'requirements.txt')
Push-Location $frontendPath
try {
    npm install
    npm run build
} finally {
    Pop-Location
}

Write-Host 'StoryStudio is ready. On first setup run .\bootstrap-admin.ps1, then run .\start.ps1.'
