[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$port = 8765
$projectRoot = $PSScriptRoot
$backendPath = Join-Path $projectRoot 'backend'
$venvPython = Join-Path $backendPath '.venv\Scripts\python.exe'
$frontendIndex = Join-Path $projectRoot 'frontend\dist\index.html'
$logDirectory = Join-Path $projectRoot 'logs'
$stdoutLog = Join-Path $logDirectory 'story-studio-8765.log'
$stderrLog = Join-Path $logDirectory 'story-studio-8765.error.log'

function Test-IsStoryStudioProcess {
    param([Parameter(Mandatory)][int]$ProcessId)

    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $process) { return $false }

    $commandLine = [string]$process.CommandLine
    $executablePath = [string]$process.ExecutablePath
    return (
        $commandLine -like '*uvicorn app.main:app*' -and
        ($commandLine -like '*StoryStudio*' -or $executablePath -like '*StoryStudio*')
    )
}

if (-not (Test-Path -LiteralPath $venvPython) -or -not (Test-Path -LiteralPath $frontendIndex)) {
    throw 'StoryStudio is not set up. Run .\setup.ps1 first.'
}

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    $ownerIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($ownerIds.Count -eq 1 -and (Test-IsStoryStudioProcess -ProcessId $ownerIds[0])) {
        Write-Host "StoryStudio is already running on port $port."
        Write-Host "Local:  http://127.0.0.1:$port/"
        Write-Host "Remote: http://<your-public-ip>:$port/"
        exit 0
    }
    throw "Port $port is already used by another application. StoryStudio was not started."
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$process = Start-Process -FilePath $venvPython -ArgumentList @(
    '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', "$port"
) -WorkingDirectory $backendPath -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Seconds 1
    if ($process.HasExited) { break }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 2
        if ($health.status -eq 'ok') {
            $ready = $true
            break
        }
    } catch {
        # The application is still starting.
    }
}

if (-not $ready) {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    throw "StoryStudio did not become ready. Check '$stderrLog'."
}

Write-Host "StoryStudio is running directly on port $port (process $($process.Id))."
Write-Host "Local:  http://127.0.0.1:$port/"
Write-Host "Remote: http://<your-public-ip>:$port/"
Write-Warning 'Remote traffic is plain HTTP. Passwords, session cookies, story text, and media are not encrypted.'
Write-Host 'Run .\stop8765.ps1 when you are finished.'

