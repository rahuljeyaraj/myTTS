# Times how long the copy that a silent update starts again takes to hold the mutex (3 updates),
# then uninstalls right after a silent update 5 times and reports anything left behind.
# Runs inside Windows Sandbox (see README.md); the uninstall logs go to C:\out\unins-<n>.log.
param([Parameter(Mandatory = $true)][string]$Setup)
$ErrorActionPreference = 'Continue'
$App = Join-Path $env:LOCALAPPDATA 'Programs\mytts'; $Exe = Join-Path $App 'myTTS.exe'
$sha = [Security.Cryptography.SHA1]::Create()
$hex = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($env:USERNAME.ToLower())) | ForEach-Object { $_.ToString('x2') })
$Name = "Local\mytts-$($hex.Substring(0, 12))"
function Held { $m = $null; if ([Threading.Mutex]::TryOpenExisting($Name, [ref]$m)) { $m.Dispose(); $true } else { $false } }
function Say($t) { '[{0:HH:mm:ss.fff}] {1}' -f (Get-Date), $t }
function Run-Setup { $p = Start-Process $Setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru; $p.WaitForExit(); $p.ExitCode }
function Ensure-Running {
    if (-not (Test-Path $Exe)) { Say "install: exit $(Run-Setup)" }
    if (-not (Held)) { Start-Process $Exe -ArgumentList '--tray'; $e = (Get-Date).AddSeconds(60); while (-not (Held) -and (Get-Date) -lt $e) { Start-Sleep -Milliseconds 100 } }
    Start-Sleep 3
    Say "running: $(Held)"
}
Say "mutex $Name"
foreach ($i in 1..3) {
    Ensure-Running
    $t0 = Get-Date; $code = Run-Setup; $t1 = Get-Date
    $e = $t1.AddSeconds(60)
    while (-not (Held) -and (Get-Date) -lt $e) { Start-Sleep -Milliseconds 50 }
    $t2 = Get-Date
    $p = Get-Process myTTS -ErrorAction SilentlyContinue | Sort-Object StartTime | Select-Object -Last 1
    Say ("update {0}: exit {1} in {2:N1} s; new copy started {3:N1} s before setup ended; mutex {4:N1} s after its start ({5:N1} s after setup ended)" -f `
        $i, $code, ($t1 - $t0).TotalSeconds, ($t1 - $p.StartTime).TotalSeconds, ($t2 - $p.StartTime).TotalSeconds, ($t2 - $t1).TotalSeconds)
}
foreach ($i in 1..5) {
    Ensure-Running
    $code = Run-Setup
    $u = Start-Process (Join-Path $App 'unins000.exe') -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=C:\out\unins-$i.log" -PassThru; $u.WaitForExit()
    $e = (Get-Date).AddSeconds(30)
    while ((Test-Path $Exe) -and (Get-Date) -lt $e) { Start-Sleep -Milliseconds 500 }
    Start-Sleep 2
    $left = @(Get-ChildItem $App -Recurse -File -ErrorAction SilentlyContinue).Count
    Say ("uninstall right after update {0}: setup exit {1}; exe left: {2}; files left: {3}; myTTS processes: {4}" -f $i, $code, (Test-Path $Exe), $left, @(Get-Process myTTS -ErrorAction SilentlyContinue).Count)
    Get-Process myTTS -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep 1
    if (Test-Path $App) { Remove-Item -Recurse -Force $App -ErrorAction SilentlyContinue }
}
Say 'done'
