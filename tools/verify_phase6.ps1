# Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
#
# WABAKIPI verification kit (Phase 6, ADR 0013): run after pulling, on the PC with the GPU, models and real data.
# It backs up data\ first, updates the dependencies, times a cold and a warm start, runs the suites, the showcase,
# the golden notes with each switchable setting on and off, Whisper / Gemma / VRAM probes and capture-to-map, then
# writes docs\perf\phase6-wabakipi.md and prints a green/red table.
#
#   powershell -ExecutionPolicy Bypass -File tools\verify_phase6.ps1
#   ... -SkipInstall        do not run pip / npm.cmd ci
#   ... -SkipStartTiming    do not stop Ollama for a cold start (starts the stack once, untimed)
#   ... -Quick              skip the slow parts: Whisper variants and the Playwright map numbers
#   ... -Restore data\archive\pre-phase6-20261122-090000   stop IBMM and put that backup back
#                           (what is in data\ now is moved to data\archive\pre-restore-<time>\ first, never deleted)
#
# Secrets: none are read here. The services read E:\.claude\_vault\notecad.env through start_brain.ps1 as usual;
# nothing from the vault is printed or written to the report.
param(
  [string]$Restore,
  [switch]$SkipInstall,
  [switch]$SkipStartTiming,
  [switch]$Quick
)
$ErrorActionPreference = "Stop"
$Root    = (Resolve-Path "$PSScriptRoot\..").Path
$Data    = Join-Path $Root "data"
$Archive = Join-Path $Data "archive"
$Start   = Join-Path $Root "services\start_notecad.ps1"
$Brain   = Join-Path $Root "services\brain"
$Comp    = Join-Path $Root "services\companion"
$Py      = Join-Path $Brain ".venv\Scripts\python.exe"
$CompPy  = Join-Path $Comp ".venv\Scripts\python.exe"
$Desktop = Join-Path $Root "apps\desktop"
$Mobile  = Join-Path $Root "apps\mobile"
$Report  = Join-Path $Root "docs\perf\phase6-wabakipi.md"
$Stamp   = Get-Date -Format "yyyyMMdd-HHmmss"
$Work    = Join-Path $Data "verify\$Stamp"      # raw JSON and logs of this run (data\ is never committed)
$Rows    = New-Object System.Collections.ArrayList

function Add-Row([string]$name, [string]$target, [string]$state, [string]$detail) {
  [void]$Rows.Add([pscustomobject]@{ Name = $name; Target = $target; State = $state; Detail = $detail })
  $col = switch ($state) { "OK" { "Green" } "INFO" { "Cyan" } "WARN" { "Yellow" } "OFF" { "DarkGray" } default { "Red" } }
  Write-Host ("        {0,-4} {1}: {2}" -f $state, $name, $detail) -ForegroundColor $col
}
function Show-Table {
  Write-Host ""
  Write-Host "  IBMM Phase 6 verification on $env:COMPUTERNAME" -ForegroundColor White
  foreach ($r in $Rows) {
    $tag, $col = switch ($r.State) {
      "OK"   { "[ OK ]", "Green" }
      "INFO" { "[ .. ]", "Cyan" }
      "WARN" { "[WARN]", "Yellow" }
      "OFF"  { "[ -- ]", "DarkGray" }
      default { "[FAIL]", "Red" }
    }
    Write-Host ("  {0} " -f $tag) -ForegroundColor $col -NoNewline
    Write-Host ("{0,-34}{1,-14}" -f $r.Name, $r.Target) -NoNewline
    Write-Host $r.Detail -ForegroundColor DarkGray
  }
  Write-Host ""
}
function Test-Port([int]$port, [int]$ms = 200) {
  $c = [System.Net.Sockets.TcpClient]::new()
  try { return $c.ConnectAsync("127.0.0.1", $port).Wait($ms) -and $c.Connected } catch { return $false } finally { $c.Dispose() }
}
function Step([string]$text) { Write-Host "  $text" -ForegroundColor Cyan }
function Invoke-Logged([string]$name, [scriptblock]$block) {
  # runs a native command, keeps its output in $Work\<name>.log, returns @{ Code; Text }
  $log = Join-Path $Work "$name.log"
  $ErrorActionPreference = "Continue"   # Windows PowerShell 5.1 turns a native command's stderr into an error under Stop
  $global:LASTEXITCODE = 0
  $raw = @(& $block 2>&1)
  $code = $LASTEXITCODE
  # a program that is not there is only an error record under Continue, with no exit code: count it as a failure
  if (@($raw | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] -and $_.FullyQualifiedErrorId -like "CommandNotFoundException*" }).Count) { $code = 127 }
  $out = @($raw | ForEach-Object { "$_" })
  $out | Set-Content -Path $log -Encoding UTF8
  return @{ Code = $code; Text = ($out -join "`n"); Log = $log }
}
function Read-Json([string]$path) {
  if (-not (Test-Path $path)) { return $null }
  try { return Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}
function Invoke-IbmmStop { & powershell -ExecutionPolicy Bypass -File $Start -Stop | Out-Null }
function Invoke-OllamaStop {
  Get-Process ollama, "ollama app", ollama_llama_server -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  for ($i = 0; $i -lt 50 -and (Test-Port 11434); $i++) { Start-Sleep -Milliseconds 200 }
}
function Invoke-IbmmStart([string[]]$extra) {
  $t = Get-Date
  & powershell -ExecutionPolicy Bypass -File $Start -NoOpen @extra | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
  $ok = (Test-Port 8788) -and (Test-Port 8787)
  return @{ Ok = $ok; Seconds = [math]::Round(((Get-Date) - $t).TotalSeconds, 1) }
}
function Copy-DataTo([string]$dest) {
  # everything in data\ except data\archive (and this kit's own data\verify), then check every file arrived
  New-Item -ItemType Directory -Force $dest | Out-Null
  $items = @(Get-ChildItem $Data -Force | Where-Object { $_.Name -ne "archive" -and $_.Name -ne "verify" })
  foreach ($i in $items) { Copy-Item -Path $i.FullName -Destination $dest -Recurse -Force }
  $src = @($items | ForEach-Object { if ($_.PSIsContainer) { Get-ChildItem $_.FullName -Recurse -File -Force } else { $_ } })
  $dst = @(Get-ChildItem $dest -Recurse -File -Force)
  $srcBytes = ($src | Measure-Object Length -Sum).Sum
  $dstBytes = ($dst | Measure-Object Length -Sum).Sum
  if ($src.Count -ne $dst.Count -or $srcBytes -ne $dstBytes) {
    throw "backup incomplete: $($dst.Count)/$($src.Count) files, $dstBytes/$srcBytes bytes in $dest"
  }
  return @{ Files = $dst.Count; MB = [math]::Round($dstBytes / 1MB, 1) }
}

# ------------------------------------------------------------------ -Restore
if ($Restore) {
  $from = $Restore
  if (-not [System.IO.Path]::IsPathRooted($from)) { $from = Join-Path $Root $from }
  if (-not (Test-Path (Join-Path $from "brain"))) { Write-Host "  $from is not an IBMM data backup (no brain folder)" -ForegroundColor Red; exit 1 }
  Step "Stopping IBMM"
  Invoke-IbmmStop
  $keep = Join-Path $Archive "pre-restore-$Stamp"
  Step "Keeping what is in data\ now: $keep"
  try { $k = Copy-DataTo $keep } catch { Write-Host "  $($_.Exception.Message): nothing restored" -ForegroundColor Red; exit 1 }
  Write-Host "        $($k.Files) files, $($k.MB) MB" -ForegroundColor DarkGray
  Get-ChildItem $Data -Force | Where-Object { $_.Name -ne "archive" } | Remove-Item -Recurse -Force
  Step "Restoring $from"
  Get-ChildItem $from -Force | ForEach-Object { Copy-Item -Path $_.FullName -Destination $Data -Recurse -Force }
  Write-Host "  Restored. Start with: powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1" -ForegroundColor Green
  exit 0
}

foreach ($need in @($Py, $Start)) {
  if (-not (Test-Path $need)) { Write-Host "  $need is missing: set up IBMM first (CLAUDE.md). Nothing was changed." -ForegroundColor Red; exit 1 }
}
New-Item -ItemType Directory -Force $Work | Out-Null
$t0 = Get-Date

# ------------------------------------------------------------------ 1-2. stop, back up (abort if the copy fails)
Step "[1/7] Stopping IBMM"
Invoke-IbmmStop
Step "[2/7] Backing up data\"
$Backup = Join-Path $Archive "pre-phase6-$Stamp"
try {
  $b = Copy-DataTo $Backup
  Add-Row "Data backup" "complete" "OK" "$($b.Files) files, $($b.MB) MB in data\archive\pre-phase6-$Stamp"
} catch {
  Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "  Aborted before anything else ran. data\ is unchanged." -ForegroundColor Red
  exit 1
}

# ------------------------------------------------------------------ 3. dependencies, cold and warm start
Step "[3/7] Dependencies and start-up"
if (-not $SkipInstall) {
  $r = Invoke-Logged "pip-brain" { & $Py -m pip install -q -e "$Comp" -e "$Brain[whisper-gpu,dev]" }
  Add-Row "Brain packages" "pip exit 0" $(if ($r.Code -eq 0) { "OK" } else { "FAIL" }) "see $($r.Log)"
  if (Test-Path $CompPy) {
    $r = Invoke-Logged "pip-companion" { & $CompPy -m pip install -q -e "$Comp[dev]" }
    Add-Row "Companion packages" "pip exit 0" $(if ($r.Code -eq 0) { "OK" } else { "FAIL" }) "see $($r.Log)"
  }
  foreach ($app in @($Desktop, $Mobile)) {
    Push-Location $app
    $name = Split-Path $app -Leaf
    $r = Invoke-Logged "npm-$name" { & npm.cmd ci --include=dev }   # NODE_ENV=production is machine-wide
    Pop-Location
    Add-Row "npm ci $name" "exit 0" $(if ($r.Code -eq 0) { "OK" } else { "FAIL" }) "see $($r.Log)"
  }
}
if ($SkipStartTiming) {
  $s = Invoke-IbmmStart @("-Rebuild", "-Showcase")
  Add-Row "Start (untimed)" "" $(if ($s.Ok) { "OK" } else { "FAIL" }) "$($s.Seconds) s with -Rebuild -Showcase"
} else {
  Invoke-OllamaStop   # a cold start: Ollama and the models load from disk
  $cold = Invoke-IbmmStart @("-Rebuild", "-Showcase")
  Add-Row "Cold start (-Rebuild -Showcase)" "was 37 s" $(if ($cold.Ok) { "INFO" } else { "FAIL" }) "$($cold.Seconds) s (includes the UI rebuild)"
  Invoke-IbmmStop
  $warm = Invoke-IbmmStart @("-Showcase")
  $st = "FAIL"; if ($warm.Ok) { $st = $(if ($warm.Seconds -lt 20) { "OK" } else { "WARN" }) }
  Add-Row "Warm start (-Showcase)" "< 20 s" $st "$($warm.Seconds) s"
}
if (-not ((Test-Port 8788) -and (Test-Port 8787) -and (Test-Port 11434))) {
  Show-Table
  Write-Host "  The stack is not up (brain :8788, companion :8787, Ollama :11434): see data\brain\logs. Backup: $Backup" -ForegroundColor Red
  exit 1
}

# VRAM: nvidia-smi samples every 500 ms for the rest of the run; the peak is read at the end
$vramLog = Join-Path $Work "vram.csv"
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$smiProc = $null
if ($smi) {
  $smiProc = Start-Process -FilePath $smi.Source -WindowStyle Hidden -PassThru `
    -ArgumentList @("--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits", "-lms", "500", "-f", "`"$vramLog`"")
}

# ------------------------------------------------------------------ 4a. suites
Step "[4/7] Test suites"
Push-Location $Brain
$r = Invoke-Logged "pytest-brain" { & $Py -m pytest -q -p no:cacheprovider }
$sum = ($r.Text -split "`n" | Where-Object { $_ -match "passed|failed" } | Select-Object -Last 1)
$pg = $(if ($env:NC_BRAIN_TEST_PG_URL) { "SQLite + Postgres" } else { "SQLite (NC_BRAIN_TEST_PG_URL not set)" })
Add-Row "Brain pytest" $pg $(if ($r.Code -eq 0) { "OK" } else { "FAIL" }) "$sum"
foreach ($chk in @("gen_sync_migration", "gen_rls_migration", "popia_inventory")) {
  $r = Invoke-Logged "check-$chk" { & $Py "tools\$chk.py" --check }
  Add-Row "$chk --check" "up to date" $(if ($r.Code -eq 0) { "OK" } else { "FAIL" }) (($r.Text -split "`n") | Select-Object -Last 1)
}
Pop-Location
Push-Location $Comp
$cpy = $(if (Test-Path $CompPy) { $CompPy } else { $Py })
$r = Invoke-Logged "pytest-companion" { & $cpy -m pytest -q -p no:cacheprovider }
$sum = ($r.Text -split "`n" | Where-Object { $_ -match "passed|failed" } | Select-Object -Last 1)
Add-Row "Companion pytest" "" $(if ($r.Code -eq 0) { "OK" } else { "FAIL" }) "$sum"
Pop-Location

# ------------------------------------------------------------------ 4b. showcase and golden notes
Step "[5/7] Showcase and golden notes"
Push-Location $Brain
function Invoke-FieldTest([string]$name, [string[]]$fargs, [hashtable]$envs) {
  $saved = @{}
  foreach ($k in $envs.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $envs[$k]) }
  try {
    $json = Join-Path $Work "$name.json"
    $r = Invoke-Logged $name { & $Py tools\field_test.py @fargs --out $json }
    return @{ Code = $r.Code; Json = (Read-Json $json); Text = $r.Text; Log = $r.Log }
  } finally {
    foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
  }
}
$typed = Invoke-FieldTest "showcase-typed" @("--showcase", "--routers", "local,rules", "--embed", "openai") @{}
$line = ($typed.Text -split "`n" | Where-Object { $_ -match "^showcase" } | Select-Object -Last 1)
Add-Row "Showcase typed (Gemma + rules)" "3/3" $(if ($typed.Code -eq 0) { "OK" } else { "FAIL" }) "$line; times in $($typed.Log)"
$rules = Invoke-FieldTest "showcase-rules" @("--showcase", "--routers", "rules") @{}
$line = ($rules.Text -split "`n" | Where-Object { $_ -match "^showcase" } | Select-Object -Last 1)
Add-Row "Showcase rules only" "3/3" $(if ($rules.Code -eq 0) { "OK" } else { "FAIL" }) "$line"
$samples = Join-Path $Data "samples\showcase"
if (Test-Path (Join-Path $samples "showcase_1.wav")) {
  $r = Invoke-Logged "showcase-spoken" { & $Py tools\seed_farm_showcase.py --reset-clean --audio $samples }
  $line = ($r.Text -split "`n" | Where-Object { $_ -match "^showcase" } | Select-Object -Last 1)
  Add-Row "Showcase spoken (live brain)" "3/3" $(if ($line -match "3/3") { "OK" } else { "FAIL" }) "$line; times in $($r.Log)"
} else { Add-Row "Showcase spoken" "3/3" "OFF" "no data\samples\showcase\showcase_1.wav" }
# golden notes: each setting that ADR 0013 put behind a switch, on and off, same notes, side by side
$golden = @()
foreach ($v in @(@{ Name = "golden-fastpath-on";  Env = @{ NC_BRAIN_RULES_FAST_PATH = "1" } },
                 @{ Name = "golden-fastpath-off"; Env = @{ NC_BRAIN_RULES_FAST_PATH = "0" } },
                 @{ Name = "golden-rules-only";   Env = @{} })) {
  $fa = $(if ($v.Name -eq "golden-rules-only") { @("--routers", "rules") } else { @("--routers", "local,rules", "--embed", "openai") })
  $g = Invoke-FieldTest $v.Name $fa $v.Env
  if ($g.Json) {
    $golden += [pscustomobject]@{ Variant = $v.Name; Right = "$($g.Json.right_first_time)/$($g.Json.events)"; Percent = $g.Json.percent; Seconds = $g.Json.seconds }
    $st = $(if ($v.Name -eq "golden-rules-only") { "INFO" } elseif ($g.Json.percent -ge 85) { "OK" } else { "WARN" })
    Add-Row ("Golden notes, " + ($v.Name -replace "^golden-", "")) ">= 85 %" $st "$($g.Json.right_first_time)/$($g.Json.events) = $($g.Json.percent) % in $($g.Json.seconds) s"
  } else { Add-Row ("Golden notes, " + ($v.Name -replace "^golden-", "")) ">= 85 %" "FAIL" "no result: see $($g.Log)" }
}
Pop-Location

# ------------------------------------------------------------------ 4c. probes: routes, Gemma, Whisper variants
Step "[6/7] Probes"
Push-Location $Brain
$probe = Join-Path $Work "probe.json"
$r = Invoke-Logged "probe" { & $Py tools\perf_probe.py --only "memory,routes,gemma" --out $probe }
$p = Read-Json $probe
if ($p -and $p.gemma) {
  Add-Row "Gemma 4 E2B" "" "INFO" "$($p.gemma.tokens_per_s_p50) tok/s, first token $($p.gemma.ttft_ms_p50) ms (p50)"
} else { Add-Row "Gemma 4 E2B" "" "FAIL" "no numbers: see $($r.Log)" }
if ($p -and $p.routes) {
  $mm = $p.routes.'mindmap perf-2000'
  if ($mm -and $mm.p50_ms) { Add-Row "Mind map, 2,000 nodes (HTTP)" "was 244 ms" "INFO" "p50 $($mm.p50_ms) ms, p95 $($mm.p95_ms) ms" }
}
$whisper = @()
$variants = @(@{ N = "turbo float16 beam 5"; A = @() })
if (-not $Quick) {
  $variants += @(@{ N = "turbo int8_float16 beam 5"; A = @("--compute", "int8_float16") },
                 @{ N = "turbo float16 beam 1";      A = @("--beam", "1") },
                 @{ N = "turbo float16 beam 5 VAD";  A = @("--vad") },
                 @{ N = "turbo float16 batched 8";   A = @("--batched", "8") })
  if (Test-Path (Join-Path $Root "models\whisper\large-v3")) { $variants += @{ N = "large-v3 float16 beam 5"; A = @("--whisper-model", "large-v3") } }
}
$i = 0
foreach ($v in $variants) {
  $i++
  $wj = Join-Path $Work "whisper-$i.json"
  $r = Invoke-Logged "whisper-$i" { & $Py tools\perf_probe.py --only whisper @($v.A) --out $wj }
  $w = Read-Json $wj
  if ($w -and $w.whisper -and $w.whisper.rtf) {
    $whisper += [pscustomobject]@{ Variant = $v.N; RTF = $w.whisper.rtf; Audio = $w.whisper.audio_s; Proc = $w.whisper.proc_s }
    Add-Row "Whisper $($v.N)" "RTF < 1" $(if ($w.whisper.rtf -lt 1) { "OK" } else { "WARN" }) "RTF $($w.whisper.rtf) ($($w.whisper.proc_s) s for $($w.whisper.audio_s) s of audio)"
  } else { Add-Row "Whisper $($v.N)" "RTF < 1" "FAIL" "no numbers: see $($r.Log)" }
}
Pop-Location

# ------------------------------------------------------------------ 4d. the map: capture to map, 2,000 nodes, fold
$perf = Join-Path $Data "desktop\perf.jsonl"
if (-not $Quick) {
  Push-Location $Desktop
  $before = $(if (Test-Path $perf) { @(Get-Content $perf).Count } else { 0 })
  $r = Invoke-Logged "playwright-perf" { & npx.cmd playwright test e2e/perf.spec.ts e2e/fold.spec.ts -g "2,000|capture to map" }
  Pop-Location
  $new = $(if (Test-Path $perf) { @(Get-Content $perf | Select-Object -Skip $before | ForEach-Object { $_ | ConvertFrom-Json }) } else { @() })
  $c2m = $new | Where-Object { $_.name -eq "capture-to-map" } | Select-Object -Last 1
  if ($c2m -and $null -ne $c2m.value.redraw_ms) {
    Add-Row "Capture to map" "< 1000 ms" $(if ($c2m.value.redraw_ms -lt 1000) { "OK" } else { "FAIL" }) "redraw $($c2m.value.redraw_ms) ms after action.applied"
  } else { Add-Row "Capture to map" "< 1000 ms" "FAIL" "no number: see $($r.Log)" }
  $p2k = $new | Where-Object { $_.name -eq "perf-2000" } | Select-Object -Last 1
  if ($p2k) {
    Add-Row "2,000-node map panning" "60 fps" "INFO" "$($p2k.value.fps) fps, $($p2k.value.long_frames) long frames, first draw $($p2k.value.first_draw_ms) ms (compare with the panel's idle rate)"
  }
  Add-Row "Playwright map + fold perf" "pass" $(if ($r.Code -eq 0) { "OK" } else { "FAIL" }) "see $($r.Log)"
}

# ------------------------------------------------------------------ VRAM peak
if ($smiProc) { Stop-Process -Id $smiProc.Id -Force -ErrorAction SilentlyContinue }
$peak = $null; $total = $null
if (Test-Path $vramLog) {
  $vals = @(Get-Content $vramLog | ForEach-Object { $f = $_ -split ","; if ($f.Count -ge 2) { [pscustomobject]@{ Used = [int]$f[0].Trim(); Total = [int]$f[1].Trim() } } })
  if ($vals.Count) { $peak = ($vals | Measure-Object Used -Maximum).Maximum; $total = $vals[0].Total }
}
if ($peak) {
  Add-Row "Peak VRAM (whole GPU)" "< 8 GB, headroom" $(if ($peak -lt 0.95 * $total) { "OK" } else { "WARN" }) "$peak of $total MB"
} else { Add-Row "Peak VRAM" "< 8 GB" "OFF" "nvidia-smi not found" }

# ------------------------------------------------------------------ 5. report
Step "[7/7] Report: docs\perf\phase6-wabakipi.md"
$commit = (& git -C $Root rev-parse --short HEAD) 2>$null
$md = New-Object System.Collections.ArrayList
[void]$md.Add("<!--")
[void]$md.Add("  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI")
[void]$md.Add("  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>")
[void]$md.Add("  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved")
[void]$md.Add("  Web: https://www.ionity.today | Ref: https://www.ionity.co.za")
[void]$md.Add("-->")
[void]$md.Add("")
[void]$md.Add("# Phase 6 verification on WABAKIPI")
[void]$md.Add("")
[void]$md.Add("Written by ``tools\verify_phase6.ps1`` on $(Get-Date -Format 'd MMMM yyyy HH:mm') at commit ``$commit``, on $env:COMPUTERNAME. Every number here is **WABAKIPI**. Backup taken first: ``data\archive\pre-phase6-$Stamp``. Raw output: ``data\verify\$Stamp``.")
[void]$md.Add("")
[void]$md.Add("| Check | Target | Result | Detail |")
[void]$md.Add("|---|---|---|---|")
foreach ($r in $Rows) { [void]$md.Add("| $($r.Name) | $($r.Target) | $($r.State) | $($r.Detail -replace '\|', '/') |") }
if ($golden.Count) {
  [void]$md.Add(""); [void]$md.Add("## Golden notes, each setting on and off"); [void]$md.Add("")
  [void]$md.Add("| Variant | Right first time | % | s |"); [void]$md.Add("|---|---|---|---|")
  foreach ($g in $golden) { [void]$md.Add("| $($g.Variant) | $($g.Right) | $($g.Percent) | $($g.Seconds) |") }
}
if ($whisper.Count) {
  [void]$md.Add(""); [void]$md.Add("## Whisper (showcase recordings)"); [void]$md.Add("")
  [void]$md.Add("| Variant | RTF | Processing s | Audio s |"); [void]$md.Add("|---|---|---|---|")
  foreach ($w in $whisper) { [void]$md.Add("| $($w.Variant) | $($w.RTF) | $($w.Proc) | $($w.Audio) |") }
  [void]$md.Add(""); [void]$md.Add("Accuracy for each variant: the ``texts`` in ``data\verify\$Stamp\whisper-*.json``; Afrikaans WER: ``tools\afrikaans_wer.py``.")
}
[void]$md.Add("")
[void]$md.Add("References: Phase 6 on WABAKIPI (28 October 2026): warm start 17.5-19.4 s, capture to map 266 ms, 2,000-node map payload 244 ms, golden notes 20/21 with Gemma + rules (``docs\BUILD_STATUS.md``). Cloud numbers (not comparable): ``docs\perf\baseline-phase6-cloud.md``.")
$md | Set-Content -Path $Report -Encoding UTF8

$bad = @($Rows | Where-Object { $_.State -eq "FAIL" })
Show-Table
Write-Host ("  Report: docs\perf\phase6-wabakipi.md   Backup: data\archive\pre-phase6-{0}   ({1:N0} s)" -f $Stamp, ((Get-Date) - $t0).TotalSeconds) -ForegroundColor White
if ($bad.Count) {
  Write-Host ("  {0} check(s) failed: {1}" -f $bad.Count, (($bad | ForEach-Object { $_.Name }) -join ", ")) -ForegroundColor Red
  Write-Host "  To put the data back: powershell -ExecutionPolicy Bypass -File tools\verify_phase6.ps1 -Restore data\archive\pre-phase6-$Stamp" -ForegroundColor Yellow
  exit 1
}
Write-Host "  All checks passed or informational." -ForegroundColor Green
exit 0
