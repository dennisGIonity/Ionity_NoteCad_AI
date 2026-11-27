# Ionity Business Mind Map (IBMM) - Beta 1 set-up | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
#
# One-time install of IBMM on a tester's Windows PC. Safe to run again: finished steps are skipped.
#
#   powershell -ExecutionPolicy Bypass -File tools\setup_ibmm.ps1 -Root D:\IBMM             NVIDIA PC
#   powershell -ExecutionPolicy Bypass -File tools\setup_ibmm.ps1                        run from inside the IBMM folder
#   powershell -ExecutionPolicy Bypass -File tools\setup_ibmm.ps1 -Root D:\IBMM -CpuOnly    no NVIDIA card
#   ... -SkipModels      do not download the Gemma models (3.4 GB)
#   ... -SkipUi          do not build the desktop app
#   ... -Python <exe>    use this python.exe instead of looking for one
#
# Needs: Python 3.11+ (3.13 / 3.14 recommended), Node.js 22+ (24 LTS recommended), Ollama. Writes only inside -Root.
param(
  [string]$Root = "",   # the IBMM folder; empty: the folder this script is in (tools\..), else the package's source\IBMM
  [switch]$CpuOnly,
  [switch]$SkipModels,
  [switch]$SkipUi,
  [string]$Python = ""
)
$ErrorActionPreference = "Stop"

function Step([string]$t) { Write-Host ""; Write-Host "  == $t" -ForegroundColor Cyan }
function Ok([string]$t)   { Write-Host "  [ OK ]  $t" -ForegroundColor Green }
function Warn([string]$t) { Write-Host "  [WARN]  $t" -ForegroundColor Yellow }
function Fail([string]$t) { Write-Host "  [FAIL]  $t" -ForegroundColor Red; exit 1 }
function Check-Exit([string]$what) { if ($LASTEXITCODE -ne 0) { Fail "$what failed (exit $LASTEXITCODE). See the messages above." } }

# ------------------------------------------------------------------ 0. the folder
if (-not $Root) {
  foreach ($c in (Join-Path $PSScriptRoot ".."), (Join-Path $PSScriptRoot "..\source\IBMM")) {
    if (Test-Path (Join-Path $c "services\start_notecad.ps1")) { $Root = $c; break }
  }
  if (-not $Root) { Fail "Give the IBMM folder: -Root D:\IBMM" }
}
if (-not (Test-Path $Root)) { Fail "$Root does not exist. Copy source\IBMM from the package there first." }
$Root = (Resolve-Path $Root).Path
if (-not (Test-Path (Join-Path $Root "services\start_notecad.ps1"))) {
  Fail "$Root does not look like IBMM (services\start_notecad.ps1 is missing). Point -Root at the copied source\IBMM folder."
}
if ($Root -match "\s") { Warn "The path has spaces ($Root). It should work, but a path without spaces is safer." }
Write-Host ""
Write-Host "  Ionity Business Mind Map (IBMM) - Beta 1 set-up" -ForegroundColor White
Write-Host "  Folder: $Root"

# ------------------------------------------------------------------ 1. prerequisites
Step "1/5  Checking what is installed"

# Python: -Python, then the py launcher (newest first), then python on PATH
$py = $null; $pyArgs = @()
if ($Python) {
  if (-not (Test-Path $Python)) { Fail "-Python $Python not found" }
  $py = $Python
} else {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    $ErrorActionPreference = "Continue"   # Windows PowerShell 5.1 turns a native command's stderr into errors
    foreach ($v in "3.14", "3.13", "3.12", "3.11") {
      & py "-$v" -c "import sys" 2>$null | Out-Null
      if ($LASTEXITCODE -eq 0) { $py = "py"; $pyArgs = @("-$v"); break }
    }
    $ErrorActionPreference = "Stop"
  }
  if (-not $py -and (Get-Command python -ErrorAction SilentlyContinue)) { $py = "python" }
}
if (-not $py) { Fail "Python not found. Install Python 3.13 or 3.14 from python.org (tick 'Add python.exe to PATH') and open a new PowerShell window." }
$pyVer = (& $py @pyArgs -c "import sys; print('%d.%d.%d' % sys.version_info[:3])").Trim()
Check-Exit "Python"
$maj, $min = $pyVer.Split(".")[0..1] | ForEach-Object { [int]$_ }
if ($maj -lt 3 -or ($maj -eq 3 -and $min -lt 11)) { Fail "Python $pyVer is too old: IBMM needs 3.11 or newer (3.13 / 3.14 recommended)." }
Ok "Python $pyVer"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $SkipUi) {
  if (-not $node) { Fail "Node.js not found. Install Node.js 24 LTS from nodejs.org and open a new PowerShell window (or use -SkipUi)." }
  $nodeVer = (& node --version).Trim()
  if ([int]($nodeVer.TrimStart("v").Split(".")[0]) -lt 22) { Fail "Node.js $nodeVer is too old: IBMM needs 22 or newer (24 LTS recommended)." }
  Ok "Node.js $nodeVer"
}

$ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollama -and (Test-Path (Join-Path $Root "runtime\ollama\ollama.exe"))) { $ollama = Join-Path $Root "runtime\ollama\ollama.exe" }
if ($ollama) { Ok "Ollama ($ollama)" } else { Warn "Ollama not found. Install it from ollama.com/download/windows before you start IBMM." }

$gpu = $false
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
  $ErrorActionPreference = "Continue"
  $gpuName = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null | Select-Object -First 1)
  $gpuExit = $LASTEXITCODE
  $ErrorActionPreference = "Stop"
  if ($gpuExit -eq 0 -and $gpuName) { $gpu = $true; Ok "NVIDIA $gpuName" }
}
if (-not $gpu -and -not $CpuOnly) {
  Warn "No NVIDIA card found: installing for CPU only (voice notes will be slower; typed notes are fine)."
  $CpuOnly = $true
}
$free = (Get-PSDrive ($Root.Substring(0, 1))).Free / 1GB
if ($free -lt 12) { Warn ("Only {0:N1} GB free on {1}: about 12 GB is needed (models, speech model, environments)." -f $free, $Root.Substring(0, 2)) }
else { Ok ("{0:N0} GB free on {1}" -f $free, $Root.Substring(0, 2)) }

# ------------------------------------------------------------------ 2. Python environments
Step "2/5  Python environments (a few minutes)"
$whisper = if ($CpuOnly) { "whisper" } else { "whisper-gpu" }
$svc = Join-Path $Root "services"
foreach ($s in @(
    @{ name = "companion"; pkgs = @("-e", (Join-Path $svc "companion")) },
    @{ name = "brain";     pkgs = @("-e", (Join-Path $svc "companion"), "-e", ((Join-Path $svc "brain") + "[$whisper]")) })) {
  $venv = Join-Path $svc "$($s.name)\.venv"
  $vpy  = Join-Path $venv "Scripts\python.exe"
  if (-not (Test-Path $vpy)) {
    Write-Host "  creating services\$($s.name)\.venv"
    & $py @pyArgs -m venv $venv; Check-Exit "Creating the $($s.name) environment"
  }
  & $vpy -m pip install --disable-pip-version-check -q -U pip; Check-Exit "Updating pip ($($s.name))"
  Write-Host "  installing the $($s.name)$(if ($s.name -eq 'brain') { " (with $whisper)" })"
  & $vpy -m pip install --disable-pip-version-check -q @($s.pkgs); Check-Exit "Installing the $($s.name)"
  Ok "$($s.name) environment ready"
}

# ------------------------------------------------------------------ 3. models
Step "3/5  AI models (about 3.4 GB)"
$models = Join-Path $Root "models"
if ($SkipModels) { Warn "skipped (-SkipModels)" }
else {
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $svc "companion\tools\get_models.ps1") -Dest $models
  Check-Exit "Downloading the models"
  foreach ($f in "gemma-4-E2B-it-Q4_K_M.gguf", "embeddinggemma-300M-Q8_0.gguf") {
    if (-not (Test-Path (Join-Path $models $f))) { Fail "$f is missing in $models. Run the set-up again." }
  }
  Ok "Gemma 4 E2B and EmbeddingGemma in $models"
}
Write-Host "  The speech model (Whisper large-v3-turbo, about 1.6 GB) downloads by itself on the first start."

# ------------------------------------------------------------------ 4. desktop app
Step "4/5  Desktop app"
if ($SkipUi) { Warn "skipped (-SkipUi)" }
else {
  Push-Location (Join-Path $Root "apps\desktop")
  try {
    & npm.cmd ci --include=dev --no-audit --no-fund; Check-Exit "npm ci"
    & npm.cmd run build; Check-Exit "Building the desktop app"
  } finally { Pop-Location }
  if (-not (Test-Path (Join-Path $Root "apps\desktop\dist\index.html"))) { Fail "the build left no apps\desktop\dist\index.html" }
  Ok "built apps\desktop\dist"
}

# ------------------------------------------------------------------ 5. done
Step "5/5  Done"
Ok "IBMM is installed in $Root"
Write-Host ""
Write-Host "  Start it (first time, with the demo farm):" -ForegroundColor White
Write-Host "    cd $Root"
Write-Host "    powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Showcase"
Write-Host ""
Write-Host "  The first start downloads the speech model and can take a few minutes. Then open http://127.0.0.1:8788/"
if (-not $ollama) { Write-Host "  Install Ollama first (ollama.com/download/windows)." -ForegroundColor Yellow }
