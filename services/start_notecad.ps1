# Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
#
# One command for the whole desktop stack, then a health table:
#   Ollama (Gemma 4 E2B + EmbeddingGemma, :11434) -> companion (:8787) -> brain (:8788, Whisper on the GPU) -> UI
#
#   powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1               start everything, open the app
#   ... -Showcase           also build the showcase farm if missing and open it on the map
#   ... -Ui dev             UI from the Vite dev server on http://127.0.0.1:5173 (hot reload, for UI work)
#   ... -Ui desktop         the Tauri window (apps\desktop\src-tauri, once built); falls back to the browser
#   ... -Ui none            no UI
#   ... -Rebuild            rebuild the UI (apps\desktop\dist) before starting
#   ... -NoOpen             do not open a browser
#   ... -Status             only show the health table
#   ... -Lan                phones on the farm network can reach the brain (token from the vault; "Pair a phone" in the app)
#   ... -EdgeNode           also run an Edge AI Node (sync hub, :8789, data\edge-node) and sync the brain with it
#   ... -Stop               stop the companion, brain, edge node and UI (Ollama keeps running unless this script started it)
param(
  [ValidateSet("auto", "browser", "dev", "desktop", "none")] [string]$Ui = "auto",
  [switch]$Showcase,
  [switch]$Rebuild,
  [switch]$NoOpen,
  [switch]$Status,
  [switch]$Stop,
  [switch]$Lan,
  [switch]$EdgeNode,
  [int]$TimeoutSec = 180
)
$ErrorActionPreference = "Stop"
$Root     = (Resolve-Path "$PSScriptRoot\..").Path
$App      = Join-Path $Root "apps\desktop"
$UiLogs   = Join-Path $Root "data\desktop\logs"
$Companion = Join-Path $PSScriptRoot "companion\tools\start_local.ps1"
$BrainPs  = Join-Path $PSScriptRoot "brain\tools\start_brain.ps1"
$BrainPy  = Join-Path $PSScriptRoot "brain\.venv\Scripts\python.exe"
$TauriExe = Join-Path $App "src-tauri\target\release\notecad-desktop.exe"
$Models   = @("notecad-gemma4-e2b", "notecad-embeddinggemma")

function Get-Json([string]$url, [int]$timeout = 3) {
  try { return Invoke-RestMethod $url -TimeoutSec $timeout } catch { return $null }
}
function Test-Port([int]$port, [int]$ms = 200) {
  # Windows takes about 2 s to refuse a loopback connection over HTTP; a bare TCP connect with a short timeout
  # says "nothing there" at once, so optional parts (edge node, Vite) do not slow every health check
  $c = [System.Net.Sockets.TcpClient]::new()
  try { return $c.ConnectAsync("127.0.0.1", $port).Wait($ms) -and $c.Connected } catch { return $false } finally { $c.Dispose() }
}
function Test-Url([string]$url) {
  try { return (Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}
function Stop-ByCommandLine([string]$name, [string]$like) {
  Get-CimInstance Win32_Process -Filter "name='$name'" | Where-Object { $_.CommandLine -like $like } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
function Stop-Ui {
  Stop-ByCommandLine "node.exe" "*apps\desktop*vite*"
  Get-Process notecad-desktop -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

# ------------------------------------------------------------------ health
function Get-Health {
  $rows = @()
  $tags = Get-Json "http://127.0.0.1:11434/api/tags"
  $ps   = Get-Json "http://127.0.0.1:11434/api/ps"
  if (-not $tags) { $rows += [pscustomobject]@{ Name = "Ollama"; Port = ":11434"; State = "FAIL"; Detail = "not answering" } }
  else {
    $have = @($tags.models | ForEach-Object { $_.name -replace ':latest$', '' })
    $missing = @($Models | Where-Object { $have -notcontains $_ })
    $loaded = @($ps.models | ForEach-Object { "$($_.name -replace ':latest$', '') ($([math]::Round($_.size_vram / 1GB, 1)) GB GPU)" })
    if ($missing) { $rows += [pscustomobject]@{ Name = "Ollama"; Port = ":11434"; State = "FAIL"; Detail = "missing $($missing -join ', ')" } }
    else { $rows += [pscustomobject]@{ Name = "Ollama"; Port = ":11434"; State = "OK"; Detail = $(if ($loaded) { "loaded: " + ($loaded -join ', ') } else { "Gemma 4 E2B + EmbeddingGemma registered" }) } }
  }
  $c = Get-Json "http://127.0.0.1:8787/health"
  $rows += [pscustomobject]@{ Name = "Companion"; Port = ":8787"; State = $(if ($c.ok) { "OK" } else { "FAIL" })
    Detail = $(if ($c.ok) { "model $(if ($c.model) { $c.model } else { "none" }), embeddings $($c.embedder)" } else { "not answering" }) }
  $b = Get-Json "http://127.0.0.1:8788/api/health"
  if (-not $b.ok) { $rows += [pscustomobject]@{ Name = "Brain"; Port = ":8788"; State = "FAIL"; Detail = "not answering" } }
  else {
    $rows += [pscustomobject]@{ Name = "Brain"; Port = ":8788"; State = "OK"; Detail = "$($b.db), routers $($b.routers -replace '^chain:', '')" }
    $sttState = if ($null -eq $b.stt) { "OFF" } elseif ($b.stt_ready -eq $true) { "OK" } elseif ($b.stt_ready -eq $false) { "WAIT" } else { "FAIL" }
    $sttDetail = if ($null -eq $b.stt) { "no engine: pip install faster-whisper, or a Deepgram key in the vault" }
                 elseif ($b.stt_ready -eq $true) { "$($b.stt) on $($b.stt_device)" }
                 elseif ($b.stt_ready -eq $false) { "$($b.stt) loading" } else { "$($b.stt_ready)" }
    $rows += [pscustomobject]@{ Name = "Speech to text"; Port = ""; State = $sttState; Detail = $sttDetail }
  }
  $appOk = Test-Url "http://127.0.0.1:8788/app/"
  $rows += [pscustomobject]@{ Name = "Desktop UI"; Port = ":8788/app"; State = $(if ($appOk) { "OK" } else { "FAIL" })
    Detail = $(if ($appOk) { "http://127.0.0.1:8788/" } else { "not built: run with -Rebuild" }) }
  if ($Ui -eq "dev" -or (Test-Port 5173)) {
    $devOk = Test-Url "http://127.0.0.1:5173/"
    $rows += [pscustomobject]@{ Name = "UI dev server"; Port = ":5173"; State = $(if ($devOk) { "OK" } else { "WAIT" }); Detail = "http://127.0.0.1:5173/" }
  }
  if (Get-Process notecad-desktop -ErrorAction SilentlyContinue) {
    $rows += [pscustomobject]@{ Name = "Desktop window"; Port = ""; State = "OK"; Detail = "Tauri, Ctrl+Shift+Space to talk" }
  }
  if ($b.ok) {
    $sy = Get-Json "http://127.0.0.1:8788/api/v1/sync/status"
    if ($sy) {
      if ($sy.target) {
        $syState = if ($sy.last_error) { "WAIT" } elseif ($sy.last_sync_at) { "OK" } else { "WAIT" }
        $syDetail = "with $($sy.target), " + $(if ($sy.last_error) { $sy.last_error } elseif ($sy.last_sync_at) { "last $($sy.last_sync_at), $($sy.pending_changes) to send" } else { "first sync pending" })
      } else { $syState = "INFO"; $syDetail = "this PC only (no NC_BRAIN_SYNC_TARGET)" }
      $rows += [pscustomobject]@{ Name = "Sync"; Port = ""; State = $syState; Detail = $syDetail }
    }
    $pr = Get-Json "http://127.0.0.1:8788/api/v1/pairing"
    if ($pr) {
      $rows += [pscustomobject]@{ Name = "Phones"; Port = ""; State = $(if ($pr.ready) { "OK" } else { "OFF" })
        Detail = $(if ($pr.ready) { "LAN at $($pr.urls -join ', '): Pair a phone in the app" } else { "this PC only (start with -Lan)" }) }
    }
  }
  if ($EdgeNode -or (Test-Port 8789)) {
    $e = Get-Json "http://127.0.0.1:8789/api/health"
    $rows += [pscustomobject]@{ Name = "Edge AI Node"; Port = ":8789"; State = $(if ($e.ok) { "OK" } else { "FAIL" })
      Detail = $(if ($e.ok) { "sync hub, $($e.db)" } else { "not answering" }) }
  }
  if ($b.ok) {
    $ws = @(Get-Json "http://127.0.0.1:8788/api/v1/workspaces" | ForEach-Object { $_ })  # PS 5.1 hands back the array as one object
    $hasShow = @($ws | Where-Object { $_.id -eq "showcase" }).Count -gt 0
    $rows += [pscustomobject]@{ Name = "Workspaces"; Port = ""; State = "INFO"
      Detail = "$($ws.Count) on this machine" + $(if ($hasShow) { ", showcase ready" } else { "" }) }
  }
  return $rows
}

function Show-Health($rows) {
  Write-Host ""
  Write-Host "  NoteCad on $env:COMPUTERNAME" -ForegroundColor White
  foreach ($r in $rows) {
    $tag, $col = switch ($r.State) {
      "OK"   { "[ OK ]", "Green" }
      "WAIT" { "[WAIT]", "Yellow" }
      "OFF"  { "[ -- ]", "DarkGray" }
      "INFO" { "[ .. ]", "Cyan" }
      default { "[FAIL]", "Red" }
    }
    Write-Host ("  {0} " -f $tag) -ForegroundColor $col -NoNewline
    Write-Host ("{0,-15}{1,-11}" -f $r.Name, $r.Port) -NoNewline
    Write-Host $r.Detail -ForegroundColor DarkGray
  }
  Write-Host ""
}

if ($Status) { Show-Health (Get-Health); return }

if ($Stop) {
  Stop-Ui
  & $BrainPs -Stop | Out-Null
  & $BrainPs -Stop -Name edge-node -Port 8789 | Out-Null
  & $Companion -Stop | Out-Null
  Write-Host "  NoteCad stopped (companion, brain, edge node, UI)." -ForegroundColor Yellow
  return
}

# ------------------------------------------------------------------ start
$t0 = Get-Date
Write-Host "  [1/4] Ollama + companion" -ForegroundColor Cyan
& $Companion -NoWait | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }  # the brain starts while it loads
# load both models into the GPU now, so the first note is not the slow one; in the background, while the UI and
# the brain start (the brain's Whisper warm-up runs at the same time)
Add-Type -AssemblyName System.Net.Http
$http = [System.Net.Http.HttpClient]::new()
$http.Timeout = [TimeSpan]::FromSeconds(120)
$warming = foreach ($m in $Models) {
  $body = if ($m -like "*embed*") { @{ model = $m; input = "warm"; keep_alive = -1 } } else { @{ model = $m; prompt = ""; keep_alive = -1 } }
  $path = if ($m -like "*embed*") { "api/embed" } else { "api/generate" }
  $http.PostAsync("http://127.0.0.1:11434/$path", [System.Net.Http.StringContent]::new(($body | ConvertTo-Json), [Text.Encoding]::UTF8, "application/json"))
}

Write-Host "  [2/4] UI build" -ForegroundColor Cyan
$dist = Join-Path $App "dist\index.html"
# rebuild only when a source is newer than the build (or -Rebuild): an unchanged UI costs nothing at start
$stale = $false
if (Test-Path $dist) {
  $built = (Get-Item $dist).LastWriteTimeUtc
  $src = @(Get-ChildItem (Join-Path $App "src") -Recurse -File) + @(Get-Item (Join-Path $App "index.html"), (Join-Path $App "package-lock.json"), (Join-Path $App "vite.config.ts") -ErrorAction SilentlyContinue)
  $stale = @($src | Where-Object { $_.LastWriteTimeUtc -gt $built }).Count -gt 0
}
if ($Rebuild -or $stale -or -not (Test-Path $dist) -or $Ui -eq "dev") {
  if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Write-Host "        node.js not found: the UI cannot be built" -ForegroundColor Red }
  else {
    New-Item -ItemType Directory -Force $UiLogs | Out-Null
    Push-Location $App
    try {
      if (-not (Test-Path "node_modules\.bin\vite.cmd")) {
        Write-Host "        installing UI packages (first run)..." -ForegroundColor DarkGray
        cmd /c "npm.cmd ci --include=dev --no-audit --no-fund > `"$UiLogs\npm-ci.log`" 2>&1"
      }
      if ($Rebuild -or $stale -or -not (Test-Path $dist)) {
        Write-Host ("        building apps\desktop{0}..." -f $(if ($stale -and -not $Rebuild) { " (sources changed)" } else { "" })) -ForegroundColor DarkGray
        cmd /c "npm.cmd run build > `"$UiLogs\build.log`" 2>&1"
        if ($LASTEXITCODE -ne 0) { Write-Host "        build failed: see $UiLogs\build.log" -ForegroundColor Red }
      }
    } finally { Pop-Location }
  }
} else { Write-Host "        apps\desktop\dist is up to date" -ForegroundColor DarkGray }

Write-Host "  [3/4] brain" -ForegroundColor Cyan
$brainArgs = @{}
if ($Lan) { $brainArgs.Lan = $true }
if ($EdgeNode) {
  & $BrainPs -Name edge-node -Port 8789 -HubOnly -Lan:$Lan | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
  $brainArgs.SyncTarget = "http://127.0.0.1:8789"
}
& $BrainPs @brainArgs -NoWait | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }

Write-Host "  [4/4] UI" -ForegroundColor Cyan
Stop-Ui
$mode = $Ui
if ($mode -eq "auto") { $mode = if (Test-Path $TauriExe) { "desktop" } else { "browser" } }
if ($mode -eq "desktop" -and -not (Test-Path $TauriExe)) {
  Write-Host "        the Tauri window is not built yet (needs Rust): using the browser" -ForegroundColor Yellow
  $mode = "browser"
}
$query = if ($Showcase) { "?ws=showcase&view=map" } else { "" }
$open = $null
switch ($mode) {
  "dev" {
    New-Item -ItemType Directory -Force $UiLogs | Out-Null
    Start-Process cmd -WindowStyle Hidden -WorkingDirectory $App -ArgumentList "/c", "npm.cmd run dev > `"$UiLogs\vite.log`" 2>&1" | Out-Null
    $open = "http://127.0.0.1:5173/$query"
  }
  "desktop" { Start-Process $TauriExe | Out-Null }
  "browser" { $open = "http://127.0.0.1:8788/app/$query" }
}

# ------------------------------------------------------------------ wait until everything is green
try { [void][System.Threading.Tasks.Task]::WaitAll([System.Threading.Tasks.Task[]]@($warming), 120000) } catch {}
$http.Dispose()
$deadline = (Get-Date).AddSeconds($TimeoutSec)
do {
  $rows = Get-Health
  # a service that is down after 30 s will not come up by waiting longer; the speech model may take a minute
  $grace = ((Get-Date) - $t0).TotalSeconds -lt 30
  $waiting = @($rows | Where-Object { ($_.State -eq "WAIT" -or ($grace -and $_.State -eq "FAIL")) -and $_.Name -ne "Desktop UI" })
  if (-not $waiting) { break }
  Write-Host ("        waiting for {0}..." -f (($waiting | ForEach-Object { $_.Name }) -join ", ")) -ForegroundColor DarkGray
  Start-Sleep -Milliseconds 800
} while ((Get-Date) -lt $deadline)

if ($Showcase -and (Get-Json "http://127.0.0.1:8788/api/health").ok) {
  & $BrainPy (Join-Path $PSScriptRoot "brain\tools\seed_farm_showcase.py") | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
  $rows = Get-Health
}
Show-Health $rows
$bad = @($rows | Where-Object { $_.State -eq "FAIL" })
if ($bad) { Write-Host ("  Not ready: {0}. Logs: data\brain\logs, data\companion\logs, data\desktop\logs" -f (($bad | ForEach-Object { $_.Name }) -join ", ")) -ForegroundColor Red }
else { Write-Host ("  All green in {0:N0} s." -f ((Get-Date) - $t0).TotalSeconds) -ForegroundColor Green }
if ($open -and -not $NoOpen) {
  Write-Host "  Opening $open   (hold Space to talk, M for the map)" -ForegroundColor White
  Start-Process $open
}
if ($Showcase) {
  Write-Host "  Showcase notes: services\brain\.venv\Scripts\python.exe services\brain\tools\seed_farm_showcase.py --interactive" -ForegroundColor White
}
