<#
.SYNOPSIS
  Stop NeuroSonic servers (and only NeuroSonic servers).

.DESCRIPTION
  Finds processes whose command line runs neurosonic_app.py from a WOAD-Research virtual environment (the venv
  launcher, its base-Python child and the cmd.exe wrapper that START_NEUROSONIC.ps1 creates) and stops them.
  Other Python processes are never touched. History is in data\neurosonic.sqlite3 and is kept.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\STOP_NEUROSONIC.ps1            # every NeuroSonic server
  powershell -ExecutionPolicy Bypass -File .\STOP_NEUROSONIC.ps1 -Port 8765 # only the one on port 8765
  powershell -ExecutionPolicy Bypass -File .\STOP_NEUROSONIC.ps1 -WhatIf    # list, do not stop
#>
param([int]$Port = 0, [switch]$WhatIf)
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = Split-Path -Parent $Here   # F:\Projects\WOAD-Research

$all = Get-CimInstance Win32_Process
$byPid = @{}; foreach ($p in $all) { $byPid[[int]$p.ProcessId] = $p }

# venv launchers that run neurosonic_app.py from this project's .venv / .venv-gpu
$launchers = $all | Where-Object {
    $_.CommandLine -match 'neurosonic_app\.py' -and $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith($Project, [StringComparison]::OrdinalIgnoreCase) }
if ($Port -gt 0) {
    $launchers = $launchers | Where-Object {
        $m = [regex]::Match($_.CommandLine, '--port\s+(\d+)')
        $p = if ($m.Success) { [int]$m.Groups[1].Value } else { 8765 }
        $p -eq $Port }
}

$targets = New-Object System.Collections.Generic.List[object]
foreach ($l in $launchers) {
    $targets.Add($l)
    # base-interpreter child(ren) that do the actual work
    $all | Where-Object { $_.ParentProcessId -eq $l.ProcessId -and $_.CommandLine -match 'neurosonic_app\.py' } |
        ForEach-Object { $targets.Add($_) }
    # cmd.exe wrapper created by START_NEUROSONIC.ps1
    $parent = $byPid[[int]$l.ParentProcessId]
    if ($parent -and $parent.Name -eq 'cmd.exe' -and $parent.CommandLine -match 'neurosonic_app\.py') { $targets.Add($parent) }
}

if ($targets.Count -eq 0) {
    Write-Host "No NeuroSonic server is running$(if ($Port) { " on port $Port" })."
} else {
    foreach ($t in $targets) {
        Write-Host ("{0} PID {1,-6} {2}" -f $(if ($WhatIf) { "would stop" } else { "stopping  " }), $t.ProcessId, $t.CommandLine)
        if (-not $WhatIf) { Stop-Process -Id $t.ProcessId -Force -ErrorAction SilentlyContinue }
    }
}
if (-not $WhatIf) {
    Start-Sleep -Seconds 1
    $pidFile = Join-Path $Here "data\neurosonic.pid"
    if ((Test-Path $pidFile) -and -not (Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue)) {
        Remove-Item $pidFile -Force
    }
    $still = $targets | Where-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
    if ($still) { Write-Host "WARNING: still running: $(($still | ForEach-Object ProcessId) -join ', ')" -ForegroundColor Yellow; exit 1 }
    if ($targets.Count) { Write-Host "Stopped $($targets.Count) process(es)." -ForegroundColor Green }
}
