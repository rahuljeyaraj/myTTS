# Drives the setup wizard and the uninstaller with real clicks, inside Windows Sandbox.
#   -Part install  a fresh install through the wizard with its defaults (it downloads the model)
#   -Part update   the wizard again over it, ticking "Start myTTS when I sign in", then a restart
#   -Part signin   after the restart: myTTS was started by the Run entry; then the uninstaller,
#                  answering "Remove the voice model"
# Results go to C:\out\wizard-<part>-<time>.txt, screenshots to C:\out\wizard-<part>-NN.png.
param([Parameter(Mandatory)][ValidateSet('install', 'update', 'signin')][string]$Part,
      [string]$Setup = '')

$ErrorActionPreference = 'Stop'
. C:\in\ui.ps1
$Out = 'C:\out'
$Results = Join-Path $Out ('wizard-{0}-{1:HHmmss}.txt' -f $Part, (Get-Date))
$App = Join-Path $env:LOCALAPPDATA 'Programs\mytts'
$Exe = Join-Path $App 'myTTS.exe'
$Data = Join-Path $env:LOCALAPPDATA 'mytts'
$Models = Join-Path $Data 'models'
$Logs = Join-Path $Data 'logs'
$AppLog = Join-Path $Logs 'mytts.log'
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$AppsKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\mytts_is1'
$StartLnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'myTTS.lnk'
$DesktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'myTTS.lnk'
$Flag = Join-Path $Out 'wizard-restarted.flag'
if (-not $Setup) { $Setup = (Get-ChildItem C:\in -Filter 'myTTS-setup-*.exe' | Select-Object -First 1).FullName }

if (-not ('M' -as [type])) {
Add-Type @'
using System; using System.Text; using System.Threading; using System.Runtime.InteropServices;
public static class M {
  public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, int x, int y, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, StringBuilder s);
  // WM_GETTEXT: GetWindowText does not read an edit control of another process.
  public static string GetText(IntPtr h) { var s = new StringBuilder(16384); SendMessage(h, 0x000D, (IntPtr)16384, s); return s.ToString(); }
  public static void ClickAt(int x, int y) {
    SetCursorPos(x, y); Thread.Sleep(80);
    mouse_event(2, 0, 0, 0, UIntPtr.Zero); Thread.Sleep(60); mouse_event(4, 0, 0, 0, UIntPtr.Zero);
  }
}
'@
}
$null = [M]::SetProcessDPIAware()  # the same pixels as the DPI-aware installer

function Say([string]$Text) {
    $line = '[{0:HH:mm:ss}] {1}' -f (Get-Date), $Text
    Add-Content -LiteralPath $Results -Value $line -Encoding ascii
    Write-Host $line
}

function Check([string]$Name, [scriptblock]$Test) {
    try { if (& $Test) { Say "PASS $Name" } else { Say "FAIL $Name" } } catch { Say "FAIL $Name : $_" }
}

function Get-App { @(Get-Process myTTS -ErrorAction SilentlyContinue) }

function Get-AppCommandLine { (Get-CimInstance Win32_Process -Filter "Name = 'myTTS.exe'" | Select-Object -First 1).CommandLine }

function Wait-For([scriptblock]$Test, [int]$TimeoutS = 30) {
    $end = (Get-Date).AddSeconds($TimeoutS)
    while ((Get-Date) -lt $end) { $r = & $Test; if ($r) { return $r }; Start-Sleep -Milliseconds 300 }
    $null
}

function Set-Front([IntPtr]$Handle) {
    foreach ($try in 1..10) {
        [U]::Chord(0x12)  # an Alt tap lets a background process take the foreground
        $null = [U]::SetForegroundWindow($Handle)
        Start-Sleep -Milliseconds 300
        if ([M]::GetForegroundWindow() -eq $Handle) { return $true }
    }
    $false
}

function Get-Visible([IntPtr]$Window) { @(Get-Controls $Window | Where-Object Visible) }

function Find-Button($Controls, [string]$Text) {
    # Matches without & and the arrows the classic wizard style adds ("< Back", "Next >").
    $Controls | Where-Object { $_.Enabled -and ($_.Text -replace '&', '' -replace '^< | >$', '') -eq $Text } | Select-Object -First 1
}

function Press($Control) { $null = [U]::PostMessage($Control.Handle, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) }  # BM_CLICK

function Get-Wizard { Get-Windows | Where-Object Class -eq 'TWizardForm' | Select-Object -First 1 }

function Click-LastTask($List, [int]$Attempt) {
    # Clicks the last item of the tasks list ("Start myTTS when I sign in"), a different spot each try.
    $count = [int][M]::SendMessage($List.Handle, 0x018B, [IntPtr]::Zero, [IntPtr]::Zero)     # LB_GETCOUNT
    $h = [int][M]::SendMessage($List.Handle, 0x01A1, [IntPtr]::Zero, [IntPtr]::Zero)         # LB_GETITEMHEIGHT
    $top = [int][M]::SendMessage($List.Handle, 0x018E, [IntPtr]::Zero, [IntPtr]::Zero)       # LB_GETTOPINDEX
    $r = New-Object M+RECT
    $null = [M]::GetWindowRect($List.Handle, [ref]$r)
    $x = $r.L + @((4 * $h), [int](1.7 * $h), (8 * $h))[($Attempt - 1) % 3]  # a comma binds before *
    $y = $r.T + 2 + ($count - 1 - $top) * $h + [int]($h / 2)
    Say "tasks list: $count items, $h px high, top $top; click $Attempt at ($x, $y), list at ($($r.L), $($r.T))"
    $wiz = Get-Wizard
    $null = Set-Front $wiz.Handle
    [M]::ClickAt($x, $y)
    Start-Sleep -Milliseconds 400
}

function Invoke-Wizard([switch]$TickStartup) {
    # Runs setup with its wizard, saves each page, and returns what it saw.
    $seen = [ordered]@{ Pages = @(); Memo = ''; Finished = ''; Code = $null; Ticked = $false }
    $p = Start-Process $Setup -ArgumentList "/LOG=$Out\setup-wizard-$Part.log" -PassThru
    $null = $p.Handle
    $n = 0; $last = ''; $attempt = 0
    $end = (Get-Date).AddMinutes(15)
    while ((Get-Date) -lt $end) {
        $w = Get-Wizard
        if (-not $w) { if ($p.HasExited) { break }; Start-Sleep -Milliseconds 500; continue }
        $c = Get-Visible $w.Handle
        $statics = @($c | Where-Object { $_.Class -eq 'TNewStaticText' -and $_.Text } | ForEach-Object Text)
        $buttons = @($c | Where-Object { $_.Class -eq 'TNewButton' -and $_.Text } | ForEach-Object { ($_.Text -replace '&', '') + $(if (-not $_.Enabled) { ' (off)' }) })
        $page = if ($statics) { $statics[0] } else { '(no title)' }
        $sig = "$page | $($buttons -join ', ')"
        if ($sig -ne $last) {
            $last = $sig; $n++
            Say "page $n : $sig"
            $seen.Pages += "$sig / $($statics -join ' / ')"
            Start-Sleep -Milliseconds 700  # let it draw
            if ($n -le 20) { $null = Save-Screen ('wizard-{0}-{1:00}' -f $Part, $n) }
            continue  # read the page again after the wait
        }
        $finish = Find-Button $c 'Finish'
        $install = Find-Button $c 'Install'
        $next = Find-Button $c 'Next'
        $list = $c | Where-Object Class -like '*CheckListBox*' | Select-Object -First 1
        if ($finish) {
            $seen.Finished = ($statics -join ' / ')
            Say "finished page: $($seen.Finished)"
            Press $finish
            break
        } elseif ($install) {
            $memo = $c | Where-Object Class -like '*Memo*' | Select-Object -First 1
            $seen.Memo = if ($memo) { [M]::GetText($memo.Handle) } else { '' }
            Say ("ready memo: " + ($seen.Memo -replace '\r?\n', ' | '))
            if ($TickStartup -and $seen.Memo -notmatch 'when I sign in' -and $attempt -lt 3) {
                Press (Find-Button $c 'Back'); $last = ''; Start-Sleep 1; continue
            }
            $seen.Ticked = $seen.Memo -match 'when I sign in'
            Press $install
        } elseif ($next) {
            if ($list -and $TickStartup -and $attempt -lt 3) { $attempt++; Click-LastTask $list $attempt }
            Press $next
        }
        Start-Sleep -Milliseconds 800
    }
    $p.WaitForExit(60000) | Out-Null
    $seen.Code = $p.ExitCode
    Say "setup exit code $($seen.Code)"
    [pscustomobject]$seen
}

function Get-TrayStarts { if (Test-Path $AppLog) { @(Select-String -LiteralPath $AppLog -Pattern 'Started in the tray').Count } else { 0 } }

Say "=== wizard part $Part ($Setup)"
try { switch ($Part) {
    'install' {
        Check 'no myTTS installed yet' { -not (Test-Path $Exe) -and -not (Test-Path $Models) }
        $r = Invoke-Wizard
        Check 'setup exit code 0' { $r.Code -eq 0 }
        Check 'it asked for the folder' { ($r.Pages -join ' ') -match 'Browse' }
        Check 'it showed the model download page' { ($r.Pages -join ' ') -match 'Downloading the voice model' }
        Check 'the Ready page lists no extra tasks' { $r.Memo -and $r.Memo -notmatch 'Additional tasks' }
        Check 'the finished page names the hotkey' { $r.Finished -match 'Ctrl\+Alt\+Space' }
        Check 'the model is there' { (Test-Path "$Models\kokoro-v1.0.onnx") -and (Test-Path "$Models\voices-v1.0.bin") }
        Check 'no Run entry and no desktop shortcut' { -not (Get-ItemProperty $RunKey -Name mytts -ErrorAction SilentlyContinue) -and -not (Test-Path $DesktopLnk) }
        Check 'Finish starts myTTS' { Wait-For { (Get-App).Count -ge 1 } 30 }
        Say "command line: $(Get-AppCommandLine)"
        Start-Sleep 6
        $null = Save-Screen 'wizard-install-launched'
        Say ("windows: " + ((Get-Windows | Where-Object Process -eq 'myTTS' | ForEach-Object Title) -join '; '))
    }
    'update' {
        Check 'myTTS is running before the update' { (Get-App).Count -ge 1 }
        $r = Invoke-Wizard -TickStartup
        Check 'setup exit code 0' { $r.Code -eq 0 }
        Check 'no folder page on an update' { ($r.Pages -join ' ') -notmatch 'Browse' }
        Check 'no download on an update (the model is there)' { ($r.Pages -join ' ') -notmatch 'Downloading the voice model' }
        Check 'the Ready page lists the sign-in task' { $r.Ticked }
        Check 'the Ready page does not list the desktop shortcut' { $r.Memo -notmatch 'desktop' }
        $run = (Get-ItemProperty $RunKey -Name mytts -ErrorAction SilentlyContinue).mytts
        Check "Run entry ($run)" { $run -eq "`"$Exe`" --tray" }
        Check 'no desktop shortcut' { -not (Test-Path $DesktopLnk) }
        Check 'Finish starts myTTS again' { Wait-For { (Get-App).Count -ge 1 } 30 }
        Start-Sleep 4
        $q = Start-Process $Exe -ArgumentList 'quit' -PassThru -WindowStyle Hidden; $q.WaitForExit(30000) | Out-Null
        Check 'myTTS quit before the restart' { Wait-For { (Get-App).Count -eq 0 } 15 }
        # In case the Sandbox does not run its logon command again after a restart.
        $agent = 'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\in\agent.ps1'
        $runOnce = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
        if (-not (Test-Path $runOnce)) { $null = New-Item $runOnce }  # a new Sandbox has none
        Set-ItemProperty $runOnce -Name 'sandbox-agent' -Value $agent
        Set-Content $Flag -Encoding ascii -Value (Get-TrayStarts)
        Say "restarting (tray starts in the log so far: $(Get-TrayStarts))"
        & shutdown.exe /r /t 3
    }
    'signin' {
        $before = [int](Get-Content $Flag)
        $ok = Wait-For { (Get-App).Count -ge 1 -and (Get-TrayStarts) -gt $before } 120
        Check 'myTTS started at sign-in and is in the tray' { $ok }
        $proc = Get-CimInstance Win32_Process -Filter "Name = 'myTTS.exe'" | Select-Object -First 1
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.ParentProcessId)" -ErrorAction SilentlyContinue
        Say "command line: $($proc.CommandLine); parent: $(if ($parent) { $parent.Name } else { "process $($proc.ParentProcessId), gone" })"
        Check 'started with --tray' { $proc.CommandLine -match '--tray' }
        Check 'one copy' { (Get-App).Count -eq 1 }
        $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
        Say ("booted {0:HH:mm:ss}, myTTS started {1:HH:mm:ss}" -f $boot, (Get-Process -Id $proc.ProcessId).StartTime)
        $null = Save-Screen 'wizard-signin'

        Say '--- uninstall from its own window'
        $u = Start-Process (Join-Path $App 'unins000.exe') -PassThru
        $ask = Wait-For { Get-Windows | Where-Object { $_.Class -eq '#32770' -and $_.Title -like '*Uninstall*' } | Select-Object -First 1 } 30
        Check 'it asks before removing' { $ask }
        Say ("question: " + ((Get-Visible $ask.Handle | Where-Object Text | ForEach-Object Text) -join ' / '))
        $null = Save-Screen 'wizard-uninstall-01'
        Press (Find-Button (Get-Visible $ask.Handle) 'Yes')
        $td = Wait-For { Get-Windows | Where-Object { $_.Class -eq '#32770' -and (Get-Controls $_.Handle | Where-Object Class -eq 'DirectUIHWND') } | Select-Object -First 1 } 60
        Check 'it asks about the voice model' { $td }
        Start-Sleep 1
        $null = Save-Screen 'wizard-uninstall-02'
        $null = [U]::PostMessage($td.Handle, 0x0400 + 102, [IntPtr]6, [IntPtr]::Zero)  # TDM_CLICK_BUTTON, IDYES: "Remove the voice model"
        $gone = Wait-For { -not (Get-Windows | Where-Object Handle -eq $td.Handle) } 5
        if (-not $gone) {
            Say 'TDM_CLICK_BUTTON did nothing; pressing Enter (the default, Keep it)'
            $null = Set-Front $td.Handle; [U]::Chord(0x0D)
        }
        $done = Wait-For { Get-Windows | Where-Object { $_.Class -eq '#32770' -and $_.Title -like '*Uninstall*' -and (Find-Button (Get-Visible $_.Handle) 'OK') } | Select-Object -First 1 } 90
        if ($done) {
            Say ("last message: " + ((Get-Visible $done.Handle | Where-Object Text | ForEach-Object Text) -join ' / '))
            $null = Save-Screen 'wizard-uninstall-03'
            Press (Find-Button (Get-Visible $done.Handle) 'OK')
        }
        Check 'it says it is done' { $done }
        $null = Wait-For { -not (Test-Path $Exe) } 30
        Start-Sleep 2
        Check 'app removed' { -not (Test-Path $App) }
        Check 'app not running' { (Get-App).Count -eq 0 }
        Check 'Apps entry removed' { -not (Test-Path $AppsKey) }
        Check 'Start menu shortcut removed' { -not (Test-Path $StartLnk) }
        Check 'Run entry removed' { -not (Get-ItemProperty $RunKey -Name mytts -ErrorAction SilentlyContinue) }
        Check 'voice model removed (as answered)' { -not (Test-Path $Models) }
        Check "nothing left in $Data" { -not (Test-Path $Data) }
        $settings = Join-Path $env:APPDATA 'mytts'
        Say "settings folder kept: $(Test-Path $settings)"
    }
} } catch { Say "ERROR in part $Part (line $($_.InvocationInfo.ScriptLineNumber)): $_" }
Say '=== done'
