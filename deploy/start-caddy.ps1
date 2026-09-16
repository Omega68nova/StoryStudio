param(
  [string]$CaddyExecutable = "",
  [string]$ExpectedPublicIp = "84.78.155.96"
)

$ErrorActionPreference = "Stop"
$configPath = (Resolve-Path (Join-Path $PSScriptRoot "Caddyfile")).Path
if (-not $CaddyExecutable) {
  $command = Get-Command caddy -ErrorAction SilentlyContinue
  if ($command) {
    $CaddyExecutable = $command.Source
  } else {
    $packageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    $candidate = Get-ChildItem -LiteralPath $packageRoot -Filter caddy.exe -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidate) { $CaddyExecutable = $candidate.FullName }
  }
}
if (-not (Test-Path -LiteralPath $CaddyExecutable -PathType Leaf)) {
  throw "Caddy was not found at '$CaddyExecutable'. Install Caddy or pass -CaddyExecutable."
}

try {
  $observedPublicIp = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 10).Trim()
} catch {
  throw "Public access was not started because the public IP could not be verified: $($_.Exception.Message)"
}
if ($observedPublicIp -ne $ExpectedPublicIp) {
  throw "Public access was not started. Expected public IP $ExpectedPublicIp but this connection reports $observedPublicIp. Update the Caddyfile and router configuration first."
}

& $CaddyExecutable validate --config $configPath --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw "Caddy rejected the public access configuration." }
& $CaddyExecutable run --config $configPath --adapter caddyfile
exit $LASTEXITCODE
