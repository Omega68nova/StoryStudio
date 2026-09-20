[CmdletBinding()]
param()

# Compatibility name for the filename requested in chat. The forwarded service
# still uses port 8765 so it matches stop8765.ps1 and the router configuration.
& (Join-Path $PSScriptRoot 'start8765.ps1')
exit $LASTEXITCODE

