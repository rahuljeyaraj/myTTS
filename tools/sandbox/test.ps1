# myTTS clean-machine test. Runs inside Windows Sandbox as WDAGUtilityAccount.
# C:\in (read-only): the release files and this script. C:\out (writable): results.txt,
# the setup logs, the app log and screenshots.
param([string[]]$Steps = @('env', 'hashes', 'install', 'checks', 'tray', 'hotkey', 'update', 'uninstall', 'tasks'),
      [string]$Setup = '')

$ErrorActionPreference = 'Stop'
$In = 'C:\in'; $Out = 'C:\out'
$Results = Join-Path $Out ('results-{0:HHmmss}.txt' -f (Get-Date))  # a new file per run; never hold it open from the host
$App = Join-Path $env:LOCALAPPDATA 'Programs\mytts'
$Exe = Join-Path $App 'myTTS.exe'
$Models = Join-Path $env:LOCALAPPDATA 'mytts\models'
$Logs = Join-Path $env:LOCALAPPDATA 'mytts\logs'
$AppLog = Join-Path $Logs 'mytts.log'
if (-not $Setup) { $Setup = (Get-ChildItem $In -Filter 'myTTS-setup-*.exe' | Select-Object -First 1).FullName }
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$AppsKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\mytts_is1'
$StartLnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'myTTS.lnk'
$DesktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'myTTS.lnk'

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class W {
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  public static void Chord(params byte[] keys) {
    foreach (var k in keys) keybd_event(k, 0, 0, UIntPtr.Zero);
    System.Threading.Thread.Sleep(60);
    for (int i = keys.Length - 1; i >= 0; i--) keybd_event(keys[i], 0, 2, UIntPtr.Zero);
  }
}
'@
$VK = @{ Ctrl = 0x11; Alt = 0x12; Space = 0x20; Right = 0x27; A = 0x41 }

function Say([string]$Text) {
    $line = '[{0:HH:mm:ss}] {1}' -f (Get-Date), $Text
    Add-Content -LiteralPath $Results -Value $line -Encoding ascii
    Write-Host $line
}

function Check([string]$Name, [scriptblock]$Test) {
    try {
        $r = & $Test
        if ($r) { Say "PASS $Name" } else { Say "FAIL $Name" }
    } catch { Say "FAIL $Name : $_" }
}

function Invoke-Exe([string]$File, [string[]]$Arguments, [int]$TimeoutS = 600) {
    # Runs a program, waits for that process only, returns @{ Code; Out; Seconds }.
    $o = Join-Path $env:TEMP ('out-' + [guid]::NewGuid() + '.txt')
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath $File -ArgumentList $Arguments -PassThru -RedirectStandardOutput $o -WindowStyle Hidden
    $null = $p.Handle  # without this, ExitCode stays empty
    if (-not $p.WaitForExit($TimeoutS * 1000)) { $p.Kill(); throw "$File timed out" }
    $text = if (Test-Path $o) { Get-Content $o -Raw } else { '' }
    @{ Code = $p.ExitCode; Out = "$text".Trim(); Seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
}

function Invoke-Setup([string[]]$Arguments, [string]$LogName) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath $Setup -ArgumentList ($Arguments + "/LOG=$Out\$LogName") -PassThru
    $null = $p.Handle
    $p.WaitForExit()  # not -Wait: that also waits for the myTTS it restarts
    Say ("{0} {1}: exit {2} in {3:N1} s" -f (Split-Path $Setup -Leaf), ($Arguments -join ' '), $p.ExitCode, $sw.Elapsed.TotalSeconds)
    $p.ExitCode
}

function Wait-Log([string]$Pattern, [int]$TimeoutS = 30) {
    $end = (Get-Date).AddSeconds($TimeoutS)
    while ((Get-Date) -lt $end) {
        if ((Test-Path $AppLog) -and (Select-String -LiteralPath $AppLog -Pattern $Pattern -Quiet)) { return $true }
        Start-Sleep -Milliseconds 250
    }
    $false
}

function Get-App { @(Get-Process myTTS -ErrorAction SilentlyContinue) }

function Save-Screen([string]$Name) {
    $b = [Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object Drawing.Bitmap $b.Width, $b.Height
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
    $bmp.Save((Join-Path $Out "$Name.png"), [Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
}

function Stop-App {
    if (Get-App) { $null = Invoke-Exe $Exe @('quit') 30 }
    Start-Sleep 1
}

Say "=== myTTS sandbox test: $($Steps -join ', ')"

foreach ($step in $Steps) {
    Say "--- $step"
    try { switch ($step) {
        'env' {
            $os = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
            Say "Windows $($os.DisplayVersion) build $($os.CurrentBuild).$($os.UBR), user $env:USERNAME"
            $py = @(Get-Command python, python3, py -CommandType Application -ErrorAction SilentlyContinue)
            Check 'no Python on this machine' { $py.Count -eq 0 -and -not (Test-Path 'HKCU:\Software\Python') -and -not (Test-Path 'HKLM:\Software\Python') }
            $vc = Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall' |
                Get-ItemProperty | Where-Object { $_.PSObject.Properties['DisplayName'] -and $_.DisplayName -like '*Visual C++*' }
            Say "Visual C++ runtimes installed: $(@($vc).Count)"
            $dev = @(Get-CimInstance Win32_SoundDevice)
            Say "Sound devices: $($dev.Count) $(($dev | ForEach-Object Name) -join '; ')"
        }
        'hashes' {
            $dir = Split-Path $Setup  # the release files sit next to the installer
            $sums = Get-Content (Join-Path $dir 'SHA256SUMS.txt')
            foreach ($line in $sums) {
                $hash, $name = $line -split '\s+\*?', 2
                $file = Join-Path $dir $name
                Check "SHA-256 of $name" { (Test-Path $file) -and (Get-FileHash $file -Algorithm SHA256).Hash -eq $hash.ToUpper() }
            }
            $sig = Get-AuthenticodeSignature $Setup
            Say "Installer signature: $($sig.Status)"
        }
        'install' {
            $code = Invoke-Setup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'setup-install.log'
            Check 'silent install exit code 0' { $code -eq 0 }
        }
        'checks' {
            Check 'myTTS.exe installed' { Test-Path $Exe }
            Check 'unins000.exe next to it' { Test-Path (Join-Path $App 'unins000.exe') }
            Check 'licenses folder' { (Test-Path (Join-Path $App 'licenses\THIRD_PARTY_NOTICES.md')) }
            $k = Get-ItemProperty $AppsKey -ErrorAction SilentlyContinue
            Check 'Settings > Apps entry myTTS 1.0.0' { $k -and $k.DisplayName -eq 'myTTS' -and $k.DisplayVersion -eq '1.0.0' }
            Check 'Start menu shortcut' { Test-Path $StartLnk }
            Check 'no desktop shortcut by default' { -not (Test-Path $DesktopLnk) }
            Check 'no Run entry by default' { -not (Get-ItemProperty $RunKey -Name mytts -ErrorAction SilentlyContinue) }
            Check 'voice model downloaded by setup' { (Test-Path "$Models\kokoro-v1.0.onnx") -and (Test-Path "$Models\voices-v1.0.bin") }
            $r = Invoke-Exe $Exe @('--version') 30
            Check "--version prints 1.0.0 ($($r.Out))" { $r.Code -eq 0 -and $r.Out -match '1\.0\.0' }
            $r = Invoke-Exe $Exe @('download', '--verify') 300
            Check "download --verify ($($r.Seconds) s)" { $r.Code -eq 0 }
            $r = Invoke-Exe $Exe @('--self-test') 120
            Say ($r.Out -replace "`r?`n", ' | ')
            Check '--self-test' { $r.Code -eq 0 -and $r.Out -match 'Self-test passed' }
        }
        'tray' {
            Stop-App
            $sw = [Diagnostics.Stopwatch]::StartNew()
            Start-Process $Exe -ArgumentList '--tray'
            Check 'starts in the tray' { Wait-Log 'Started in the tray' 30 }
            Say ("started in {0:N1} s" -f $sw.Elapsed.TotalSeconds)
            Start-Sleep 3
            $p = Get-App | Select-Object -First 1
            Check 'one myTTS process' { (Get-App).Count -eq 1 }
            $outside = @($p.Modules | Where-Object {
                $_.FileName -notlike "$App\*" -and $_.FileName -notlike "$env:windir\*" -and $_.FileName -notlike "$env:TEMP\*espeak*"
            } | ForEach-Object FileName)
            Say "modules loaded: $($p.Modules.Count); outside the app, Windows and the espeak temp copy: $($outside -join ', ')"
            Check 'loads nothing from outside the app and Windows' { $outside.Count -eq 0 }
            Say ("memory: working set {0:N0} MB, private {1:N0} MB" -f ($p.WorkingSet64 / 1MB), ($p.PrivateMemorySize64 / 1MB))
        }
        'hotkey' {
            # Notepad is not in Sandbox: a plain window with a text box, in its own process.
            $n = Start-Process powershell -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'C:\in\textwin.ps1' -PassThru
            $end = (Get-Date).AddSeconds(20)
            while ((Get-Date) -lt $end) { $n.Refresh(); if ($n.MainWindowHandle -ne [IntPtr]::Zero) { break }; Start-Sleep -Milliseconds 300 }
            Start-Sleep 1
            foreach ($try in 1..10) {
                # A background process may not take the foreground; an Alt tap lets it (the usual workaround).
                [W]::Chord($VK.Alt)
                $null = [W]::SetForegroundWindow($n.MainWindowHandle)
                Start-Sleep -Milliseconds 300
                if ([W]::GetForegroundWindow() -eq $n.MainWindowHandle) { break }
            }
            Check 'the text window is in front' { [W]::GetForegroundWindow() -eq $n.MainWindowHandle }
            Start-Sleep -Milliseconds 500
            [W]::Chord($VK.Ctrl, $VK.A); Start-Sleep -Milliseconds 400
            $sw = [Diagnostics.Stopwatch]::StartNew()
            [W]::Chord($VK.Ctrl, $VK.Alt, $VK.Space)
            Check 'Ctrl+Alt+Space reads the selection' { Wait-Log 'Read selection: \d+ characters' 10 }
            Check 'it plays' { Wait-Log 'Player PLAYING' 15 }
            Say ("playing {0:N1} s after the key press" -f $sw.Elapsed.TotalSeconds)
            Start-Sleep 2; Save-Screen 'reader-playing'
            [W]::Chord($VK.Ctrl, $VK.Alt, $VK.Right); Start-Sleep 1
            [W]::Chord($VK.Ctrl, $VK.Alt, $VK.Space)
            Check 'pressed again, it pauses' { Wait-Log 'Player PAUSED' 10 }
            Save-Screen 'reader-paused'
            $p = Get-App | Select-Object -First 1
            Say ("memory after reading: working set {0:N0} MB, private {1:N0} MB" -f ($p.WorkingSet64 / 1MB), ($p.PrivateMemorySize64 / 1MB))
            Stop-Process $n -ErrorAction SilentlyContinue
        }
        'update' {
            Check 'myTTS is running before the update' { (Get-App).Count -eq 1 }
            $code = Invoke-Setup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'setup-update.log'
            Check 'silent update exit code 0' { $code -eq 0 }
            $end = (Get-Date).AddSeconds(20)
            while (-not (Get-App) -and (Get-Date) -lt $end) { Start-Sleep -Milliseconds 500 }
            $cmd = (Get-CimInstance Win32_Process -Filter "Name = 'myTTS.exe'" | Select-Object -First 1).CommandLine
            Check "running again in the tray after the update ($cmd)" { $cmd -match '--tray' }
        }
        'uninstall' {
            Copy-Item $AppLog (Join-Path $Out 'mytts-before-uninstall.log') -ErrorAction SilentlyContinue
            $u = Join-Path $App 'unins000.exe'
            $p = Start-Process $u -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru
            $p.WaitForExit()
            $end = (Get-Date).AddSeconds(30)  # unins000 hands over to a copy in TEMP
            while ((Test-Path $Exe) -and (Get-Date) -lt $end) { Start-Sleep -Milliseconds 500 }
            Start-Sleep 2
            Check 'app removed' { -not (Test-Path $Exe) }
            Check 'app not running' { (Get-App).Count -eq 0 }
            Check 'Apps entry removed' { -not (Test-Path $AppsKey) }
            Check 'Start menu shortcut removed' { -not (Test-Path $StartLnk) }
            Check 'logs removed' { -not (Test-Path $Logs) }
            Check 'voice model kept (silent uninstall)' { Test-Path "$Models\kokoro-v1.0.onnx" }
        }
        'tasks' {
            $code = Invoke-Setup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/TASKS=desktopicon,startup') 'setup-tasks.log'
            Check 'install with tasks exit code 0' { $code -eq 0 }
            $run = (Get-ItemProperty $RunKey -Name mytts -ErrorAction SilentlyContinue).mytts
            Check "Run entry ($run)" { $run -eq "`"$Exe`" --tray" }
            Check 'desktop shortcut' { Test-Path $DesktopLnk }
            $code = Invoke-Setup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'setup-keep.log'
            $run = (Get-ItemProperty $RunKey -Name mytts -ErrorAction SilentlyContinue).mytts
            Check 'a silent update keeps the Run entry' { $code -eq 0 -and $run -eq "`"$Exe`" --tray" }
            Check 'a silent update keeps the desktop shortcut' { Test-Path $DesktopLnk }
            Stop-App
            $p = Start-Process (Join-Path $App 'unins000.exe') -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru
            $p.WaitForExit()
            $end = (Get-Date).AddSeconds(30)
            while ((Test-Path $Exe) -and (Get-Date) -lt $end) { Start-Sleep -Milliseconds 500 }
            Start-Sleep 2
            Check 'uninstall removes the Run entry' { -not (Get-ItemProperty $RunKey -Name mytts -ErrorAction SilentlyContinue) }
            Check 'uninstall removes the desktop shortcut' { -not (Test-Path $DesktopLnk) }
        }
    } } catch { Say "ERROR in step $step (line $($_.InvocationInfo.ScriptLineNumber)): $_" }
}
Say '=== done'
