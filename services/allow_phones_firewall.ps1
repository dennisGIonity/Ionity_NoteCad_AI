# Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
#
# Lets phones on the farm network reach the IBMM brain (HTTPS :9788) and the Edge AI Node (HTTPS :9789).
# Plain HTTP (:8788, :8789) stays on this PC only; an older rule for those ports is removed here.
# Inbound TCP only, Private network profile only, and only from the local subnet.
# Run it once yourself, as Administrator (it asks for elevation if needed):
#   powershell -ExecutionPolicy Bypass -File services\allow_phones_firewall.ps1
#   ... -Check      show the rules and the network profile, change nothing
#   ... -Remove     delete the IBMM rules again
param([int[]]$Ports = @(9788, 9789), [switch]$Check, [switch]$Remove)

$group = "Ionity Business Mind Map (IBMM)"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)

function Show-State {
  Write-Host ""
  Write-Host "  Network profile:" -ForegroundColor Cyan
  Get-NetConnectionProfile | ForEach-Object {
    $c = if ($_.NetworkCategory -eq "Private") { "Green" } else { "Yellow" }
    Write-Host ("    {0,-28} {1}" -f $_.Name, $_.NetworkCategory) -ForegroundColor $c
  }
  Write-Host "  IBMM firewall rules:" -ForegroundColor Cyan
  $rules = @(Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue)
  if (-not $rules) { Write-Host "    none" -ForegroundColor Yellow }
  foreach ($r in $rules) {
    $port = ($r | Get-NetFirewallPortFilter).LocalPort
    $addr = ($r | Get-NetFirewallAddressFilter).RemoteAddress
    Write-Host ("    {0,-26} TCP {1,-5} {2,-8} from {3}  enabled={4}" -f $r.DisplayName, $port, $r.Profile, $addr, $r.Enabled) -ForegroundColor Green
  }
  Write-Host ""
}

if ($Check) { Show-State; return }

if (-not $isAdmin) {
  Write-Host "  Asking Windows for Administrator rights..." -ForegroundColor Yellow
  $argList = @("-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$PSCommandPath`"")
  if ($Remove) { $argList += "-Remove" }
  if ($PSBoundParameters.ContainsKey("Ports")) { $argList += @("-Ports", ($Ports -join ",")) }
  Start-Process powershell -Verb RunAs -ArgumentList $argList
  return
}

# replace our own rules only; nothing else in the firewall is touched
Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Remove) { Write-Host "  IBMM firewall rules removed." -ForegroundColor Yellow; Show-State; return }

foreach ($p in $Ports) {
  $name = if ($p -eq 9788) { "IBMM brain $p" } elseif ($p -eq 9789) { "IBMM edge node $p" } else { "IBMM $p" }
  try {
    # the firewall refuses '|' in a description
    New-NetFirewallRule -DisplayName $name -Group $group -Direction Inbound -Action Allow -Protocol TCP `
      -LocalPort $p -Profile Private -RemoteAddress LocalSubnet -ErrorAction Stop `
      -Description "Phones on the farm LAN reach IBMM. Policy 986 AED, License AED 900, Ionity Global (Pty) Ltd" | Out-Null
    Write-Host "  [ OK ] allowed TCP $p from the local subnet (Private networks)" -ForegroundColor Green
  } catch {
    Write-Host "  [FAIL] TCP ${p}: $($_.Exception.Message)" -ForegroundColor Red
  }
}

$public = @(Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq "Public" })
if ($public) {
  Write-Host ""
  Write-Host "  Note: this network is set to Public, so the Private-only rules do not apply on it:" -ForegroundColor Yellow
  $public | ForEach-Object { Write-Host "    $($_.Name)" -ForegroundColor Yellow }
  Write-Host "  If it is your own farm/office network, make it Private (Settings > Network > Properties), or run:" -ForegroundColor Yellow
  $public | ForEach-Object { Write-Host "    Set-NetConnectionProfile -InterfaceIndex $($_.InterfaceIndex) -NetworkCategory Private" -ForegroundColor Yellow }
}
Show-State
