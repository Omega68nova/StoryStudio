# StoryStudio remote access

StoryStudio itself remains bound to `127.0.0.1:8765`. Caddy is the only public process and proxies HTTPS/WebSocket traffic from `84.78.155.96:443`.

The reverse proxy also carries the app's `/sounds/` ambient library and authenticated `/media/` backgrounds. Keep `public/sounds` inside the StoryStudio installation; no additional Caddy file-server route or public filesystem access is required.

First open PowerShell in the StoryStudio project directory:

```powershell
cd C:\Users\Pavoi\Documents\GitHub\StoryStudio
```

1. Run `.\bootstrap-admin.ps1` locally and enter the initial administrator password when prompted.
2. Install Caddy with `winget install --id CaddyServer.Caddy --exact`. The launcher detects either the command or WinGet package automatically.
3. Forward public TCP 443 to TCP 443 on this Windows computer. Remove the old public 8765 forward.
4. In an elevated PowerShell, allow inbound TCP 443:
   `New-NetFirewallRule -DisplayName "StoryStudio HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow`
5. Start the application and public proxy manually with `.\run-public.ps1`.
6. When finished, run `.\stop-public.ps1` to stop StoryStudio and release port 443 for AnyDesk or other applications.

StoryStudio and Caddy do not start with Windows. The scripts under `deploy` that install logon tasks are optional and should not be run when manual startup is desired.

The launcher refuses to start Caddy if the currently observed public IP differs from the configured IP. Port 80 is not required: HTTP challenge support is disabled and Caddy uses TLS-ALPN on 443. Keep llama.cpp and ComfyUI on loopback only.

Caddy requests Let’s Encrypt’s `shortlived` ACME profile. Keep the startup task healthy because these IP-capable certificates last about six days and depend on automatic renewal.
