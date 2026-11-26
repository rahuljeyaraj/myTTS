# Job runner inside Windows Sandbox: runs each C:\in\queue\<name>.ps1 once, in its own
# PowerShell, with its output in C:\out\<name>.txt and C:\out\<name>.done when it ends.
$ErrorActionPreference = 'Continue'
Set-Content C:\out\agent.txt -Encoding ascii -Value "agent started $(Get-Date -Format s) as $env:USERNAME"
$started = @{}
while ($true) {
    foreach ($job in Get-ChildItem C:\in\queue -Filter *.ps1 -ErrorAction SilentlyContinue) {
        if ($started.ContainsKey($job.Name)) { continue }
        $started[$job.Name] = $true
        $base = Join-Path C:\out $job.BaseName
        $cmd = "& '$($job.FullName)' *>&1 | Out-File -Encoding ascii -Width 300 '$base.txt'; Set-Content '$base.done' 'done'"
        Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cmd
    }
    Start-Sleep -Milliseconds 700
}
