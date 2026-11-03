<#
.SYNOPSIS
  Start the NeuroSonic server as an independent background process (survives closing this window or Claude Code).

.DESCRIPTION
  Runs the documented launch command from this folder:
      ..\.venv-gpu\Scripts\python.exe neurosonic_app.py --host 0.0.0.0 --https
  (with -Cpu: ..\.venv\Scripts\python.exe, SSDLite on the CPU).
  The process is created through WMI (Win32_Process.Create), so it is not a child of the calling shell and is not
  stopped when that shell or terminal exits. Output goes to logs\neurosonic_<time>.log; the PID is written to
  data\neurosonic.pid. Stop it with STOP_NEUROSONIC.ps1.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\START_NEUROSONIC.ps1
  powershell -ExecutionPolicy Bypass -File .\START_NEUROSONIC.ps1 -VisionProvider off
  powershell -ExecutionPolicy Bypass -File .\START_NEUROSONIC.ps1 -Cpu
#>
param(
    [int]$Port = 8765,
    [switch]$Cpu,
    [ValidateSet("", "gemini", "mock", "off")][string]$VisionProvider = "",
    [string]$VisionModel = "",
    [int]$TimeoutSeconds = 180
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = if ($Cpu) { ".venv" } else { ".venv-gpu" }
$Python = Join-Path (Split-Path -Parent $Here) "$Venv\Scripts\python.exe"
$SetupPort = $Port + 1

if (-not (Test-Path $Python)) { Write-Host "ERROR: $Python not found." -ForegroundColor Red; exit 1 }

# Refuse to start if the ports are taken (do not kill anything here: use STOP_NEUROSONIC.ps1).
# A real connection test is used: on some systems Get-NetTCPConnection -State Listen returns nothing.
function Test-PortBusy([int]$p) {
    $c = New-Object System.Net.Sockets.TcpClient
    try { return $c.ConnectAsync("127.0.0.1", $p).Wait(700) } catch { return $false } finally { $c.Close() }
}
$running = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'neurosonic_app\.py' -and $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith((Split-Path -Parent $Here), [StringComparison]::OrdinalIgnoreCase) }
foreach ($p in @($Port, $SetupPort)) {
    if (Test-PortBusy $p) {
        Write-Host "ERROR: port $p is already in use." -ForegroundColor Red
        Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -gt 0 } |
            Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
                $o = Get-CimInstance Win32_Process -Filter "ProcessId=$_"
                Write-Host "       PID $($o.ProcessId) ($($o.Name)): $($o.CommandLine)" }
        Write-Host "       If this is an old NeuroSonic server, run .\STOP_NEUROSONIC.ps1 first."
        exit 1
    }
}
if ($running) {
    Write-Host "ERROR: a NeuroSonic server is already starting or running:" -ForegroundColor Red
    $running | ForEach-Object { Write-Host "       PID $($_.ProcessId): $($_.CommandLine)" }
    Write-Host "       Run .\STOP_NEUROSONIC.ps1 first."
    exit 1
}

$appArgs = "-u neurosonic_app.py --host 0.0.0.0 --https --port $Port"
if ($VisionProvider) { $appArgs += " --vision-provider $VisionProvider" }
if ($VisionModel) { $appArgs += " --vision-model $VisionModel" }

$LogDir = Join-Path $Here "logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Log = Join-Path $LogDir ("neurosonic_{0:yyyyMMdd_HHmmss}.log" -f (Get-Date))
# cmd.exe redirects the server's output to the log; the server itself runs with the project folder as its directory.
$cmdLine = "cmd.exe /d /c `"`"$Python`" $appArgs > `"$Log`" 2>&1`""

$startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $cmdLine; CurrentDirectory = $Here; ProcessStartupInformation = $startup }
if ($r.ReturnValue -ne 0) { Write-Host "ERROR: process creation failed (code $($r.ReturnValue))." -ForegroundColor Red; exit 1 }
$rootPid = $r.ProcessId
Set-Content -Path (Join-Path $Here "data\neurosonic.pid") -Value $rootPid -Encoding ascii
Write-Host "Started NeuroSonic ($Venv), launcher PID $rootPid; log: $Log"
Write-Host "Waiting for the server (model loading can take up to a minute) ..."

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$status = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if (-not (Get-Process -Id $rootPid -ErrorAction SilentlyContinue)) { break }
    # only trust the status once THIS process says it is listening (not some other server on the port)
    if (-not (Select-String -Path $Log -Pattern '^NeuroSonic running:' -Quiet -ErrorAction SilentlyContinue)) { continue }
    $json = & curl.exe -sk --max-time 3 "https://127.0.0.1:$Port/api/awareness/status" 2>$null
    if ($LASTEXITCODE -eq 0 -and $json) { try { $status = $json | ConvertFrom-Json; break } catch {} }
}
if (-not $status) {
    Write-Host "ERROR: the server did not answer within $TimeoutSeconds s. Last log lines:" -ForegroundColor Red
    if (Test-Path $Log) { Get-Content $Log -Tail 25 }
    exit 1
}

$d = $status.detector
Write-Host ""
Write-Host "NeuroSonic is running." -ForegroundColor Green
Write-Host ("  detector : {0} on {1} ({2}), frame interval {3} ms" -f $status.model, $d.device, $d.precision, $status.recommended_frame_ms)
if ($d.fallback_reason) { Write-Host "  fallback : $($d.fallback_reason)" -ForegroundColor Yellow }
$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.AddressState -eq "Preferred" } |
    Sort-Object { (Get-NetRoute -InterfaceIndex $_.InterfaceIndex -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | Measure-Object).Count } -Descending
Write-Host "  laptop   : https://127.0.0.1:$Port"
foreach ($ip in $ips) {
    Write-Host ("  iPhone   : https://{0}:{1}   (one-time setup page: http://{0}:{2})  [{3}]" -f $ip.IPAddress, $Port, $SetupPort, $ip.InterfaceAlias)
}
Write-Host "  log      : $Log"
Write-Host "  stop     : .\STOP_NEUROSONIC.ps1"
