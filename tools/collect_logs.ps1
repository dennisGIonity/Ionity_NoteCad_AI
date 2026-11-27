# Ionity Business Mind Map (IBMM) - Beta 1 log collector | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
#
# Zips what a bug report needs: the health table, PC details and the log files. Never the database, recordings,
# models or the vault (keys). The zip goes to your Desktop; look inside before you send it if you like.
#
#   powershell -ExecutionPolicy Bypass -File tools\collect_logs.ps1 -Root D:\IBMM
param([Parameter(Mandatory = $true)] [string]$Root)
$ErrorActionPreference = "Continue"   # collect what is there; one failing probe must not stop the rest
$Root = (Resolve-Path $Root).Path
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$work = Join-Path $env:TEMP "IBMM_logs_$stamp"
New-Item -ItemType Directory -Force $work | Out-Null

# PC details
$os  = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$info = @(
  "IBMM Beta 1 log bundle  $(Get-Date -Format s)",
  "Folder:  $Root",
  "Windows: $($os.Caption) $($os.Version) build $($os.BuildNumber)",
  "CPU:     $($cpu.Name)",
  ("RAM:     {0:N1} GB" -f ($os.TotalVisibleMemorySize / 1MB))
)
foreach ($c in @("python --version", "node --version", "ollama --version",
                 "nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv,noheader")) {
  $exe, $rest = $c.Split(" ", 2)
  if (Get-Command $exe -ErrorAction SilentlyContinue) {
    $out = try { (& $exe @($rest.Split(" ")) 2>&1 | Out-String).Trim() } catch { "error: $_" }
    $info += "${exe}: $out"
  } else { $info += "${exe}: not found" }
}
$info | Set-Content (Join-Path $work "pc.txt") -Encoding utf8

# health table and the services' own health answers
$start = Join-Path $Root "services\start_notecad.ps1"
if (Test-Path $start) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File $start -Status 2>&1 | Out-File (Join-Path $work "status.txt") -Encoding utf8
}
foreach ($u in @("http://127.0.0.1:8788/api/health", "http://127.0.0.1:8787/health", "http://127.0.0.1:11434/api/ps")) {
  $name = ($u -replace "[^a-z0-9]+", "_").Trim("_") + ".json"
  try { (Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 3).Content | Set-Content (Join-Path $work $name) -Encoding utf8 }
  catch { "not answering: $_" | Set-Content (Join-Path $work $name) -Encoding utf8 }
}

# log files only (data\<part>\logs\*), never data\archive, audio or databases
$data = Join-Path $Root "data"
if (Test-Path $data) {
  Get-ChildItem $data -Directory | Where-Object { $_.Name -ne "archive" } | ForEach-Object {
    $logs = Join-Path $_.FullName "logs"
    if (Test-Path $logs) {
      $dest = Join-Path $work $_.Name
      New-Item -ItemType Directory -Force $dest | Out-Null
      Get-ChildItem $logs -File | Where-Object { $_.Extension -in ".log", ".txt" -or $_.Name -like "*.log.*" } |
        Copy-Item -Destination $dest
    }
  }
}

$zip = Join-Path ([Environment]::GetFolderPath("Desktop")) "IBMM_logs_$($env:COMPUTERNAME)_$stamp.zip"
Compress-Archive -Path (Join-Path $work "*") -DestinationPath $zip -Force
Remove-Item $work -Recurse -Force
Write-Host "  Saved $zip" -ForegroundColor Green
Write-Host "  Attach it to your bug report (dennis.g@ionity.digital)."
