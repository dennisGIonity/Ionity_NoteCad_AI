# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
# Starts a brain API (SQLite in data\<Name>). Routers: Claude if a key is set, then the local Gemma in Ollama, then
# rules. Needs Ollama running (tools\start_local.ps1 in the companion starts it).
#   powershell -ExecutionPolicy Bypass -File tools\start_brain.ps1                 desktop brain on 127.0.0.1:8788
#   ... -Lan                                                                        and HTTPS on :9788 for phones on the LAN
#                                                       (Port + 1000; its own certificate in data\<Name>\tls, pinned by the phones)
#   ... -Name edge-node -Port 8789 -HubOnly                                         an Edge AI Node (sync hub) on :8789
#   ... -SyncTarget http://127.0.0.1:8789                                           sync this brain with that node
#   ... -Stop  [-Port 8789]                                                         stop the brain on that port
# Secrets (ANTHROPIC_API_KEY, NC_BRAIN_DEEPGRAM_KEY, NC_BRAIN_API_TOKEN, NC_BRAIN_SYNC_TOKEN, NC_BRAIN_SYNC_TARGET)
# come from E:\.claude\_vault\notecad.env only. -Lan writes a new NC_BRAIN_API_TOKEN there if none is set.
param(
  [string]$Root = (Resolve-Path "$PSScriptRoot\..\..\..").Path,
  [string]$Name = "brain",
  [int]$Port = 8788,
  [switch]$Lan,
  [switch]$HubOnly,
  [string]$WorkerId,
  [string]$SyncTarget,
  [switch]$NoWait,   # start and return; the caller checks /health
  [switch]$Stop
)
$data = Join-Path $Root "data\$Name"; $logs = Join-Path $data "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$pidFile = Join-Path $data "pid.txt"
$vault = "E:\.claude\_vault\notecad.env"

# the venv python.exe is a launcher with a child process, so stop by command line (and port), not by pid
function Stop-Brain {
  Get-CimInstance Win32_Process -Filter "name='python.exe'" |
    Where-Object { $_.CommandLine -match 'notecad_brain\.(api|serve)' -and $_.CommandLine -like "*--port $Port*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
Stop-Brain
if ($Stop) { Remove-Item $pidFile -ErrorAction SilentlyContinue; Write-Host "brain on :$Port stopped"; return }

function Read-Vault {
  $h = @{}
  if (Test-Path $vault) {
    Get-Content $vault | ForEach-Object { if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+)$') { $h[$Matches[1]] = $Matches[2].Trim() } }
  }
  return $h
}
$secrets = Read-Vault
if ($Lan -and -not $secrets["NC_BRAIN_API_TOKEN"]) {
  # a phone token: 32 random bytes, URL-safe; it lives only in the vault and in the pairing QR
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
  New-Item -ItemType Directory -Force (Split-Path $vault) | Out-Null
  Add-Content -Path $vault -Value "NC_BRAIN_API_TOKEN=$token"
  Write-Host "new phone token written to $vault"
  $secrets = Read-Vault
}

$env:NC_BRAIN_DB_URL         = "sqlite:///" + ($data -replace '\\', '/') + "/brain.db"
$env:NC_BRAIN_AUDIO_DIR      = Join-Path $data "audio"
$env:NC_BRAIN_ROUTERS        = "claude,local,rules"
$env:NC_BRAIN_LOCAL_BASE_URL = "http://127.0.0.1:11434"
$env:NC_BRAIN_LOCAL_MODEL    = "notecad-gemma4-e2b"
$env:NC_BRAIN_EMBED_BACKEND  = "openai"
$env:NC_BRAIN_EMBED_BASE_URL = "http://127.0.0.1:11434"
$env:NC_BRAIN_EMBED_MODEL    = "notecad-embeddinggemma"
$env:NC_BRAIN_COMPANION_URL  = "http://127.0.0.1:8787"
foreach ($k in $secrets.Keys) { Set-Item "env:$k" $secrets[$k] }

# per-instance settings win over the vault (the edge node must not sync with itself)
# plain HTTP stays on this PC; -Lan adds HTTPS on Port + 1000 (serve.py sets NC_BRAIN_BIND, _TLS_PORT, _TLS_CERT)
$env:NC_BRAIN_BIND = "127.0.0.1"
foreach ($k in "NC_BRAIN_TLS_PORT", "NC_BRAIN_TLS_CERT") { Remove-Item "env:$k" -ErrorAction SilentlyContinue }
$serveArgs = @("-m", "notecad_brain.serve", "--port", "$Port")
if ($Lan) { $serveArgs += "--lan" }
$env:NC_BRAIN_WORKER_ID = if ($WorkerId) { $WorkerId } elseif ($Name -eq "brain") { "desktop-$($env:COMPUTERNAME.ToLower())" } else { $Name }
if ($SyncTarget) { $env:NC_BRAIN_SYNC_TARGET = $SyncTarget }
elseif ($Name -ne "brain") { Remove-Item env:NC_BRAIN_SYNC_TARGET -ErrorAction SilentlyContinue }
# reset per-instance settings: start_notecad.ps1 runs the edge node and the brain in one PowerShell session
if ($secrets["NC_BRAIN_STT"]) { $env:NC_BRAIN_STT = $secrets["NC_BRAIN_STT"] } else { Remove-Item env:NC_BRAIN_STT -ErrorAction SilentlyContinue }
$env:NC_BRAIN_WORKER = if ($secrets["NC_BRAIN_WORKER"]) { $secrets["NC_BRAIN_WORKER"] } else { "1" }
if ($HubOnly) {
  # an Edge AI Node on this PC only stores and relays: no background worker, so Whisper and Gemma load once
  $env:NC_BRAIN_WORKER = "0"
  $env:NC_BRAIN_STT = "none"
}

$py = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$p = Start-Process $py -PassThru -WindowStyle Hidden -WorkingDirectory (Join-Path $PSScriptRoot "..") `
  -RedirectStandardOutput "$logs\api.out.log" -RedirectStandardError "$logs\api.err.log" `
  -ArgumentList $serveArgs
$p.Id | Set-Content $pidFile
$t = Get-Date
while (-not $NoWait -and ((Get-Date) - $t).TotalSeconds -lt 60) {
  $c = [System.Net.Sockets.TcpClient]::new()
  $up = try { $c.ConnectAsync("127.0.0.1", $Port).Wait(200) -and $c.Connected } catch { $false } finally { $c.Dispose() }
  if ($up) { try { if ((Invoke-WebRequest "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { break } } catch {} }
  Start-Sleep -Milliseconds 250
}
Write-Host "brain '$Name' on http://127.0.0.1:$Port  (worker $($env:NC_BRAIN_WORKER_ID); docs at /docs)"
if ($Lan) {
  Write-Host "HTTPS for phones on https://<this PC>:$($Port + 1000) (log: $logs\api.log). If phones cannot connect, once as admin:"
  Write-Host "  powershell -ExecutionPolicy Bypass -File services\allow_phones_firewall.ps1"
}
if ($env:NC_BRAIN_SYNC_TARGET) { Write-Host "syncing with $($env:NC_BRAIN_SYNC_TARGET -replace '://[^@/]*@', '://***@')" }
