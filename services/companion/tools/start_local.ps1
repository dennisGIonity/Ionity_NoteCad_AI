# Ionity NoteCad - Companion | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
# Starts the companion on a Windows desktop.
#
#   Engine "ollama" (default): Ollama is signed, so it runs under Smart App Control / Device Guard.
#     Registers the downloaded GGUFs as notecad-gemma4-e2b and notecad-embeddinggemma (no second download)
#     and points the companion at http://127.0.0.1:11434.
#   Engine "llamacpp": llama-server.exe on :8080 / :8081. Unsigned, so it is blocked where Smart App Control is on.
#
#   .\tools\start_local.ps1                 start (add -NoApi for the model side only)
#   .\tools\start_local.ps1 -Stop           stop the companion API (and llama-servers)
param(
  [string]$Root    = (Resolve-Path "$PSScriptRoot\..\..\..").Path,   # the NoteCad folder
  [ValidateSet("ollama", "llamacpp")] [string]$Engine = "ollama",
  [string]$Model   = "gemma-4-E2B-it-Q4_K_M.gguf",
  [int]$Ctx = 8192,
  [switch]$NoApi,
  [switch]$Stop
)
$models = Join-Path $Root "models"
$data   = Join-Path $Root "data\companion"
$logs   = Join-Path $data "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$pidFile = Join-Path $data "pids.txt"

# the venv python.exe is a launcher with a child process, so the API is stopped by command line, not by pid
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like '*notecad_companion.api*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if ($Stop) {
  if (Test-Path $pidFile) {
    Get-Content $pidFile | ForEach-Object { Stop-Process -Id ([int]$_) -Force -ErrorAction SilentlyContinue }
    Remove-Item $pidFile
  }
  Write-Host "stopped"; return
}

function Wait-Url([string]$url, [int]$seconds = 180) {
  $t = Get-Date
  while (((Get-Date) - $t).TotalSeconds -lt $seconds) {
    try { if ((Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { return } } catch {}
    Start-Sleep -Milliseconds 700
  }
  throw "$url did not answer"
}

$pids = @()
if ($Engine -eq "ollama") {
  $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
  if (-not $ollama) { $ollama = Join-Path $Root "runtime\ollama\ollama.exe" }
  if (-not (Test-Path $ollama)) { throw "ollama.exe not found" }
  try { Wait-Url "http://127.0.0.1:11434/api/version" 3 } catch {
    $srv = Start-Process $ollama -ArgumentList "serve" -PassThru -WindowStyle Hidden `
      -RedirectStandardOutput "$logs\ollama.out.log" -RedirectStandardError "$logs\ollama.err.log"
    $pids += $srv.Id
    Wait-Url "http://127.0.0.1:11434/api/version"
  }
  $have = & $ollama list 2>$null | Out-String
  $mf = Join-Path $data "modelfiles"; New-Item -ItemType Directory -Force $mf | Out-Null
  if ($have -notmatch "notecad-gemma4-e2b") {
    "FROM $models\$Model`nPARAMETER num_ctx $Ctx`nPARAMETER temperature 0.6" | Set-Content "$mf\gemma.Modelfile" -Encoding ascii
    & $ollama create notecad-gemma4-e2b -f "$mf\gemma.Modelfile"
  }
  if ($have -notmatch "notecad-embeddinggemma") {
    "FROM $models\embeddinggemma-300M-Q8_0.gguf" | Set-Content "$mf\embed.Modelfile" -Encoding ascii
    & $ollama create notecad-embeddinggemma -f "$mf\embed.Modelfile"
  }
  $env:NC_COMPANION_OPENAI_BASE_URL = "http://127.0.0.1:11434"
  $env:NC_COMPANION_OPENAI_MODEL    = "notecad-gemma4-e2b"
  $env:NC_COMPANION_EMBED_BASE_URL  = "http://127.0.0.1:11434"
  $env:NC_COMPANION_EMBED_MODEL     = "notecad-embeddinggemma"
} else {
  $server = Join-Path $Root "runtime\llama.cpp\llama-server.exe"
  if (-not (Test-Path $server)) { throw "llama-server.exe not found" }
  $llm = Start-Process $server -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "$logs\llm.out.log" -RedirectStandardError "$logs\llm.err.log" -ArgumentList @(
    "-m", "`"$models\$Model`"", "--alias", "gemma-4-E2B-it", "--host", "127.0.0.1", "--port", "8080",
    "-ngl", "99", "-c", "$Ctx", "--jinja", "-fa", "on")
  $emb = Start-Process $server -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "$logs\embed.out.log" -RedirectStandardError "$logs\embed.err.log" -ArgumentList @(
    "-m", "`"$models\embeddinggemma-300M-Q8_0.gguf`"", "--alias", "embeddinggemma", "--host", "127.0.0.1",
    "--port", "8081", "--embedding", "--pooling", "mean", "-ngl", "99", "-c", "2048")
  $pids += $llm.Id, $emb.Id
  Wait-Url "http://127.0.0.1:8080/health"; Wait-Url "http://127.0.0.1:8081/health"
  $env:NC_COMPANION_OPENAI_BASE_URL = "http://127.0.0.1:8080"
  $env:NC_COMPANION_OPENAI_MODEL    = "gemma-4-E2B-it"
  $env:NC_COMPANION_EMBED_BASE_URL  = "http://127.0.0.1:8081"
  $env:NC_COMPANION_EMBED_MODEL     = "embeddinggemma"
}
$env:NC_COMPANION_LLM_BACKEND   = "openai"
$env:NC_COMPANION_EMBED_BACKEND = "openai"
$env:NC_COMPANION_DATA_DIR      = $data
$env:NC_COMPANION_BRAIN_URL     = "http://127.0.0.1:8788"   # open tasks and alerts for "what is left to do?"
Write-Host "model side ready ($Engine)"
if ($NoApi) { $pids | Set-Content $pidFile; return }

$py = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$api = Start-Process $py -PassThru -WindowStyle Hidden -WorkingDirectory (Join-Path $PSScriptRoot "..") `
  -RedirectStandardOutput "$logs\api.out.log" -RedirectStandardError "$logs\api.err.log" `
  -ArgumentList @("-m", "uvicorn", "notecad_companion.api:app", "--host", "127.0.0.1", "--port", "8787")
$pids += $api.Id
$pids | Set-Content $pidFile
Wait-Url "http://127.0.0.1:8787/health" 60
Write-Host "companion API on http://127.0.0.1:8787  (docs at /docs)"
