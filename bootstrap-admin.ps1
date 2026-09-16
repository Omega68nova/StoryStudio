[CmdletBinding()]
param([string]$Username = 'Omega')

$ErrorActionPreference = 'Stop'
$backendPath = Join-Path $PSScriptRoot 'backend'
$venvPython = Join-Path $backendPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'StoryStudio is not set up. Run .\setup.ps1 first.'
}
Push-Location $backendPath
try {
    & $venvPython -m app.bootstrap_admin --username $Username
} finally {
    Pop-Location
}
