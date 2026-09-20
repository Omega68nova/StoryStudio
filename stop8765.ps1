[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$port = 8765
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)

if ($listeners.Count -eq 0) {
    Write-Host "Nothing is listening on port $port."
    exit 0
}

$ownerIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($ownerId in $ownerIds) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId" -ErrorAction SilentlyContinue
    if (-not $owner) { continue }

    $commandLine = [string]$owner.CommandLine
    $executablePath = [string]$owner.ExecutablePath
    $isStoryStudio = (
        $commandLine -like '*uvicorn app.main:app*' -and
        ($commandLine -like '*StoryStudio*' -or $executablePath -like '*StoryStudio*')
    )
    if (-not $isStoryStudio) {
        throw "Port $port belongs to an unexpected process ($ownerId); it was not stopped."
    }

    # Stop descendants first so supervised llama.cpp workers are not orphaned.
    $allProcesses = @(Get-CimInstance Win32_Process)
    $descendants = [System.Collections.Generic.List[int]]::new()
    function Add-ProcessTree([int]$ParentId) {
        foreach ($child in $allProcesses | Where-Object { $_.ParentProcessId -eq $ParentId }) {
            Add-ProcessTree ([int]$child.ProcessId)
            $descendants.Add([int]$child.ProcessId)
        }
    }

    Add-ProcessTree ([int]$ownerId)
    foreach ($childId in $descendants) {
        Stop-Process -Id $childId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $ownerId -Force -ErrorAction SilentlyContinue
}

for ($attempt = 0; $attempt -lt 10; $attempt++) {
    if (-not (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 250
}

if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "StoryStudio did not release port $port."
}

Write-Host "StoryStudio is stopped and port $port is free."

