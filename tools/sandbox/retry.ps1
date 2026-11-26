# Tests how setup retries a failed voice model download, inside Windows Sandbox.
#
# Needs an installer that downloads from http://127.0.0.1:8765 instead of GitHub (see README.md)
# and the two model files in C:\in\retry\models. A small HTTP server in this script serves them
# and cuts off the downloads a scenario asks for, after the first megabyte.
#   once    a silent install; voices-v1.0.bin is cut off once: setup retries and gets it
#   always  a silent install; voices-v1.0.bin is always cut off: three tries, then setup installs
#           without the model and the model file that did download is not fetched again
#   wizard  the wizard; the server never answers for voices-v1.0.bin (WinINet error 12152, as
#           seen once from GitHub): the countdown, then the dialog with the plain message; then
#           the server works again and "Try again" downloads it
#   stop    the wizard; "Stop download" during the countdown, then "Install without it"
# Results go to C:\out\retry-<time>.txt (PASS or FAIL lines), with setup logs and screenshots.
param([string[]]$Scenarios = @('once', 'always', 'wizard', 'stop'),
      [string]$Setup = 'C:\in\retry\myTTS-setup-localserver.exe',
      [string]$Root = 'C:\in\retry\models',
      # Server mode (this script starts itself with these):
      # -How: 'body' sends the headers and 1 MB, then resets; 'noreply' closes without a word.
      [switch]$Serve, [string]$Cut = 'none', [int]$Times = 0, [string]$How = 'body', [string]$ServerLog = '')

$Port = 8765

if ($Serve) {
    # A minimal HTTP/1.1 server: HEAD and GET of the files in $Root, one connection at a time.
    $cutLeft = $Times
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    $listener.Start()
    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            $stream = $client.GetStream()
            $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::ASCII, $false, 1024, $true)
            $request = $reader.ReadLine()
            $headers = @()
            while (($line = $reader.ReadLine())) { $headers += $line }
            $method, $url, $null = $request -split ' '
            $name = [IO.Path]::GetFileName([Uri]::UnescapeDataString($url))
            $path = Join-Path $Root $name
            $note = ($headers | Where-Object { $_ -match '^Range:' }) -join ' '
            if ($method -eq 'GET' -and $name -eq $Cut -and $cutLeft -gt 0 -and $How -eq 'noreply') {
                $cutLeft--
                $what = 'closed without a reply'
            } elseif (-not $name -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
                $head = "HTTP/1.1 404 Not Found`r`nContent-Length: 0`r`nConnection: close`r`n`r`n"
                $stream.Write([Text.Encoding]::ASCII.GetBytes($head), 0, $head.Length)
                $what = '404'
            } else {
                $size = (Get-Item -LiteralPath $path).Length
                $head = "HTTP/1.1 200 OK`r`nContent-Type: application/octet-stream`r`nContent-Length: $size`r`nConnection: close`r`n`r`n"
                $stream.Write([Text.Encoding]::ASCII.GetBytes($head), 0, $head.Length)
                $what = 'headers'
                if ($method -eq 'GET') {
                    $file = [IO.File]::OpenRead($path)
                    try {
                        if ($name -eq $Cut -and $cutLeft -gt 0) {
                            $cutLeft--
                            $buf = New-Object byte[] (1MB)
                            $n = $file.Read($buf, 0, $buf.Length)
                            $stream.Write($buf, 0, $n)
                            $stream.Flush()
                            $client.Client.LingerState = New-Object Net.Sockets.LingerOption($true, 0)  # reset, not a clean close
                            $what = 'cut off after 1 MB'
                        } else {
                            $file.CopyTo($stream)
                            $what = "served $size bytes"
                        }
                    } finally { $file.Dispose() }
                }
            }
            Add-Content -LiteralPath $ServerLog -Encoding ascii -Value ('{0:HH:mm:ss.fff} {1} {2} {3} {4}' -f (Get-Date), $method, $name, $what, $note)
        } catch {
            Add-Content -LiteralPath $ServerLog -Encoding ascii -Value ('{0:HH:mm:ss.fff} error: {1}' -f (Get-Date), $_)
        } finally { $client.Close() }
    }
}

$ErrorActionPreference = 'Stop'
. C:\in\ui.ps1
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$Out = 'C:\out'
$Stamp = '{0:HHmmss}' -f (Get-Date)
$Results = Join-Path $Out "retry-$Stamp.txt"
$App = Join-Path $env:LOCALAPPDATA 'Programs\mytts'
$Models = Join-Path $env:LOCALAPPDATA 'mytts\models'
$Onnx = Join-Path $Models 'kokoro-v1.0.onnx'
$Voices = Join-Path $Models 'voices-v1.0.bin'
$script:Server = $null

function Say([string]$Text) {
    $line = '[{0:HH:mm:ss}] {1}' -f (Get-Date), $Text
    Add-Content -LiteralPath $Results -Value $line -Encoding ascii
    Write-Host $line
}

function Check([string]$Name, [scriptblock]$Test) {
    try { if (& $Test) { Say "PASS $Name" } else { Say "FAIL $Name" } } catch { Say "FAIL $Name : $_" }
}

function Wait-For([scriptblock]$Test, [int]$TimeoutS = 30) {
    $end = (Get-Date).AddSeconds($TimeoutS)
    while ((Get-Date) -lt $end) { $r = & $Test; if ($r) { return $r }; Start-Sleep -Milliseconds 300 }
    $null
}

function Start-Server([string]$Cut, [int]$Times, [string]$Log, [string]$How = 'body') {
    Stop-Server
    $script:Server = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', $PSCommandPath, '-Serve', '-Root', $Root, '-Cut', $Cut, '-Times', $Times, '-How', $How, '-ServerLog', $Log
    $up = Wait-For { try { $c = [Net.Sockets.TcpClient]::new('127.0.0.1', $Port); $c.Close(); $true } catch { $false } } 20
    Say "server: cut $Cut $Times time(s) ($How), log $Log, up: $([bool]$up)"
}

function Stop-Server {
    if ($script:Server -and -not $script:Server.HasExited) { Stop-Process -Id $script:Server.Id -Force; $script:Server.WaitForExit(5000) | Out-Null }
}

function Requests([string]$Log, [string]$Name) { @(Get-Content -LiteralPath $Log | Where-Object { $_ -match " GET $([regex]::Escape($Name)) " }) }

function Seconds([string]$Line) { [TimeSpan]::Parse(($Line -split ' ')[0]).TotalSeconds }

function Reset-Model { if (Test-Path $Models) { Remove-Item $Models -Recurse -Force } }

function Invoke-Silent([string]$Name) {
    $log = Join-Path $Out "retry-$Name-setup-$Stamp.log"
    $p = Start-Process $Setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$log" -PassThru
    $p.WaitForExit(15 * 60 * 1000) | Out-Null
    Say "setup exit code $($p.ExitCode)"
    [pscustomobject]@{ Code = $p.ExitCode; Log = (Get-Content -LiteralPath $log -Raw) }
}

function Get-DialogText([IntPtr]$Handle) {
    # Task dialog text is not in child windows; UI Automation reads it.
    $root = [Windows.Automation.AutomationElement]::FromHandle($Handle)
    $all = $root.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition)
    (@($all | ForEach-Object { $_.Current.Name } | Where-Object { $_ }) | Select-Object -Unique) -join ' / '
}

function Get-Wizard { Get-Windows | Where-Object Class -eq 'TWizardForm' | Select-Object -First 1 }

function Get-TaskDialog {
    # The wizard runs in a second process (setup's .tmp copy), so look for any task dialog.
    Get-Windows | Where-Object { $_.Class -eq '#32770' -and (Get-Controls $_.Handle | Where-Object Class -eq 'DirectUIHWND') } | Select-Object -First 1
}

function Find-Button($Window, [string]$Text) {
    Get-Controls $Window.Handle | Where-Object { $_.Visible -and $_.Enabled -and ($_.Text -replace '&', '') -eq $Text } | Select-Object -First 1
}

function Press($Control) { $null = [U]::PostMessage($Control.Handle, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) }  # BM_CLICK

Say "=== retry tests ($Setup): $($Scenarios -join ', ')"
try {
    Get-Process myTTS -ErrorAction SilentlyContinue | Stop-Process -Force
    foreach ($s in $Scenarios) {
        Say "--- $s"
        Reset-Model
        $slog = Join-Path $Out "retry-$s-server.log"
        Remove-Item $slog -ErrorAction SilentlyContinue
        switch ($s) {
            'once' {
                Start-Server 'voices-v1.0.bin' 1 $slog
                $r = Invoke-Silent $s
                Check 'setup exit code 0' { $r.Code -eq 0 }
                Check 'both model files are there' { (Get-Item $Onnx).Length -eq (Get-Item "$Root\kokoro-v1.0.onnx").Length -and (Get-Item $Voices).Length -eq (Get-Item "$Root\voices-v1.0.bin").Length }
                Check 'the log names one failed try' { $r.Log -match 'failed \(try 1 of 3\)' -and $r.Log -notmatch 'try 2 of 3' }
                $v = Requests $slog 'voices-v1.0.bin'
                Check "voices-v1.0.bin requested twice ($($v.Count))" { $v.Count -eq 2 }
                Check 'the retry waited about 3 s' { ((Seconds $v[1]) - (Seconds $v[0])) -ge 3 }
                Check 'kokoro-v1.0.onnx requested once' { (Requests $slog 'kokoro-v1.0.onnx').Count -eq 1 }
            }
            'always' {
                Start-Server 'voices-v1.0.bin' 99 $slog
                $r = Invoke-Silent $s
                Check 'setup exit code 0 (it installs without the model)' { $r.Code -eq 0 -and (Test-Path "$App\myTTS.exe") }
                Check 'voices-v1.0.bin is not there' { -not (Test-Path $Voices) }
                Check 'kokoro-v1.0.onnx is there' { (Get-Item $Onnx).Length -eq (Get-Item "$Root\kokoro-v1.0.onnx").Length }
                Check 'the log names three failed tries' { $r.Log -match 'try 3 of 3' -and $r.Log -match 'Installing without the voice model' }
                $v = Requests $slog 'voices-v1.0.bin'
                Check "voices-v1.0.bin requested three times ($($v.Count))" { $v.Count -eq 3 }
                if ($v.Count -eq 3) { Say ('waits: {0:N1} s, {1:N1} s' -f ((Seconds $v[1]) - (Seconds $v[0])), ((Seconds $v[2]) - (Seconds $v[1]))) }
                Check 'waits of about 3 s and 6 s' { ((Seconds $v[1]) - (Seconds $v[0])) -ge 3 -and ((Seconds $v[2]) - (Seconds $v[1])) -ge 6 }
                Check 'kokoro-v1.0.onnx requested once (not fetched again)' { (Requests $slog 'kokoro-v1.0.onnx').Count -eq 1 }
            }
            { $_ -in 'wizard', 'stop' } {
                Start-Server 'voices-v1.0.bin' 99 $slog $(if ($s -eq 'wizard') { 'noreply' } else { 'body' })
                $log = Join-Path $Out "retry-$s-setup-$Stamp.log"
                $p = Start-Process $Setup -ArgumentList "/LOG=$log" -PassThru
                $null = $p.Handle
                $texts = @(); $shots = 0; $dialog = $null; $retried = $false; $installed = $false; $stopped = $false; $ask = $null; $stopAt = $null; $dialogAt = $null
                $end = (Get-Date).AddMinutes(10)
                while ((Get-Date) -lt $end -and -not $p.HasExited) {
                    $td = Get-TaskDialog
                    if ($td) {
                        if (-not $dialogAt) { $dialogAt = Get-Date }
                        Start-Sleep 1
                        $text = Get-DialogText $td.Handle
                        $null = Save-Screen "retry-$s-dialog$(if ($retried) { '-2' })"
                        if ($retried) { Say "a second dialog: $text"; break }
                        $dialog = $text
                        Say "dialog: $dialog"
                        if ($s -eq 'stop') {
                            $null = [U]::PostMessage($td.Handle, 0x0400 + 102, [IntPtr]2, [IntPtr]::Zero)  # TDM_CLICK_BUTTON, IDCANCEL: "Install without it"
                            $retried = $true
                            $null = Wait-For { -not (Get-TaskDialog) } 10
                            continue
                        }
                        Start-Server 'none' 0 (Join-Path $Out "retry-wizard-server2.log")
                        $null = [U]::PostMessage($td.Handle, 0x0400 + 102, [IntPtr]4, [IntPtr]::Zero)  # TDM_CLICK_BUTTON, IDRETRY: "Try again"
                        $retried = $true
                        $null = Wait-For { -not (Get-TaskDialog) } 10
                        continue
                    }
                    $w = Get-Wizard
                    if (-not $w) { Start-Sleep -Milliseconds 300; continue }
                    $c = @(Get-Controls $w.Handle | Where-Object { $_.Visible -and $_.Text })
                    $statics = ($c | Where-Object Class -eq 'TNewStaticText' | ForEach-Object Text) -join ' / '
                    if ($statics -match 'Trying again in' -and $texts -notcontains $statics) {
                        $texts += $statics; Say "download page: $statics"
                        if ($shots -lt 2) { $shots++; $null = Save-Screen "retry-$s-countdown-$shots" }
                        Say ("download page buttons: " + (($c | Where-Object Class -eq 'TNewButton' | ForEach-Object { ($_.Text -replace '&', '') + $(if (-not $_.Enabled) { ' (off)' }) }) -join ', '))
                    }
                    if ($statics -match 'Trying again in' -and $s -eq 'stop' -and -not $stopped) {
                        $stopped = $true
                        $btn = Find-Button $w 'Stop download'
                        Say "pressing Stop download during the countdown: $([bool]$btn)"
                        if ($btn) { Press $btn }
                        $ask = Wait-For { Get-Windows | Where-Object { $_.Class -eq '#32770' -and (Get-Controls $_.Handle | Where-Object { ($_.Text -replace '&', '') -eq 'Yes' }) } | Select-Object -First 1 } 10
                        if ($ask) {
                            Say ("question: " + ((Get-Controls $ask.Handle | Where-Object { $_.Visible -and $_.Text } | ForEach-Object Text) -join ' / '))
                            $null = Save-Screen 'retry-stop-question'
                            Press (Get-Controls $ask.Handle | Where-Object { ($_.Text -replace '&', '') -eq 'Yes' } | Select-Object -First 1)
                            $stopAt = Get-Date
                        } else { Say 'no question about stopping' }
                        continue
                    }
                    if ($statics -match 'Trying again in') { Start-Sleep -Milliseconds 200; continue }
                    $finish = Find-Button $w 'Finish'
                    if ($finish) { Press $finish; break }
                    # Install only once: after a failed download the Ready page shows again under
                    # the dialog, and a click there would start a second download.
                    $btn = Find-Button $w 'Install'
                    if ($btn -and -not $installed) { $installed = $true; Press $btn }
                    elseif (-not $btn -and -not $installed) { $btn = Find-Button $w 'Next'; if ($btn) { Press $btn } }
                    Start-Sleep -Milliseconds 800
                }
                $p.WaitForExit(60000) | Out-Null
                Say "setup exit code $($p.ExitCode)"
                Start-Sleep 5  # Finish starts myTTS
                Get-Process myTTS -ErrorAction SilentlyContinue | Stop-Process -Force
                if ($s -eq 'stop') {
                    Check 'it asked before stopping' { $ask }
                    Check 'the dialog came right after Stop' { $stopAt -and $dialogAt -and ($dialogAt - $stopAt).TotalSeconds -lt 2.5 }
                    Check 'the dialog says the download was stopped' { $dialog -match 'The download was stopped' -and $dialog -notmatch 'Details' }
                    Check 'no third try after Stop' { ($texts -join ' ') -notmatch 'try 3 of 3' -and (Requests $slog 'voices-v1.0.bin').Count -eq 1 }
                    Check 'setup exit code 0' { $p.ExitCode -eq 0 }
                    Check 'installed without voices-v1.0.bin' { (Test-Path "$App\myTTS.exe") -and -not (Test-Path $Voices) }
                    break
                }
                Check 'the download page counted down to each retry' { ($texts -join ' ') -match 'try 2 of 3' -and ($texts -join ' ') -match 'try 3 of 3' }
                Check 'the dialog has the plain message for a connection error' { $dialog -match 'connection to the download server failed or was cut off' -and $dialog -match 'connected to the internet' }
                Check 'the dialog offers installing without the model' { $dialog -match 'download the voice model later' }
                Check 'the details have no "Internal error" or "Worker thread" text' { $dialog -match 'Details: ' -and $dialog -notmatch 'Internal error|Worker thread' }
                Check '"Try again" downloaded the model' { $retried -and (Test-Path $Voices) -and (Get-Item $Voices).Length -eq (Get-Item "$Root\voices-v1.0.bin").Length }
                Check 'setup exit code 0' { $p.ExitCode -eq 0 }
                Check 'kokoro-v1.0.onnx requested once in all' { ((Requests $slog 'kokoro-v1.0.onnx').Count + (Requests (Join-Path $Out 'retry-wizard-server2.log') 'kokoro-v1.0.onnx').Count) -eq 1 }
            }
        }
        Stop-Server
    }
} catch { Say "ERROR (line $($_.InvocationInfo.ScriptLineNumber)): $_" } finally { Stop-Server }
Say '=== done'
