# Restart Agora from a tool (a Claude session), outside the tool's Windows job (D-218).
# Ends the tray first (or it would start the old server again), asks the server to stop cleanly,
# then starts a fresh tray with start_detached.ps1.
$ErrorActionPreference = "SilentlyContinue"

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "backend\.desktop\.tray" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

try { Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/api/system/quit" -TimeoutSec 10 | Out-Null } catch {}

$gone = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    $left = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "backend\.launch" }
    if (-not $left) { $gone = $true; break }
}
if (-not $gone) {
    Write-Output "server did not stop in 60 seconds; ending it"
    $left | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-Sleep -Seconds 2
}

& (Join-Path $PSScriptRoot "start_detached.ps1")
