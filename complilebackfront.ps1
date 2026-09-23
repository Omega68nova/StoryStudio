[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backendPath = Join-Path $projectRoot 'backend'
$frontendPath = Join-Path $projectRoot 'frontend'
$venvPython = Join-Path $backendPath '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'The backend virtual environment is missing. Run .\setup.ps1 first.'
}

Push-Location $backendPath
try {
    & $venvPython -m compileall app
    if ($LASTEXITCODE -ne 0) {
        throw "Backend compilation failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

Push-Location $frontendPath
try {
    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend build failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
