[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$caddyCommand = Get-Command caddy -ErrorAction SilentlyContinue
$caddyPath = if ($caddyCommand) { $caddyCommand.Source } else { "" }
if (-not $caddyPath) {
    $packageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    $candidate = Get-ChildItem -LiteralPath $packageRoot -Filter caddy.exe -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidate) { $caddyPath = $candidate.FullName }
}
if ($caddyPath) {
    & $caddyPath stop 2>$null
}

$listener = Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 8765 -ErrorAction SilentlyContinue
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($process.CommandLine -notlike "*StoryStudio*uvicorn*") {
        throw "Port 8765 belongs to an unexpected process; it was not stopped."
    }
    # Capture descendants before stopping Uvicorn. StoryStudio's supervised
    # llama.cpp router and loaded model are children and must not be orphaned.
    $allProcesses = @(Get-CimInstance Win32_Process)
    $tree = [System.Collections.Generic.List[int]]::new()
    function Add-ProcessTree([int]$ParentId) {
        foreach ($child in $allProcesses | Where-Object { $_.ParentProcessId -eq $ParentId }) {
            Add-ProcessTree ([int]$child.ProcessId)
            $tree.Add([int]$child.ProcessId)
        }
    }
    Add-ProcessTree ([int]$process.ProcessId)
    foreach ($processId in $tree) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $process.ProcessId -Force
}

Write-Host "StoryStudio and its public HTTPS proxy are stopped. Port 443 is available to other applications."
