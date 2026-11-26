<#
.SYNOPSIS
Builds the self-contained myTTS.exe (no Python needed to run it) into dist\myTTS.

.DESCRIPTION
Uses the repository's .venv (Python 3.10 to 3.13), installs the pinned build tools into it,
and runs PyInstaller with packaging\mytts.spec. The result is dist\myTTS\myTTS.exe with its
_internal folder. The voice model is not bundled; it stays in %LOCALAPPDATA%\mytts\models.

.PARAMETER Python
The Python to run PyInstaller with. Default: .venv\Scripts\python.exe.

.PARAMETER SelfTest
After the build, run myTTS.exe --self-test (needs the voice model).

.PARAMETER Installer
Also build the installer, dist\myTTS-setup-<version>.exe, with Inno Setup 6 (packaging\mytts.iss).

.PARAMETER Iscc
The Inno Setup compiler. Default: ISCC.exe on PATH, or in the usual per-user or per-machine
Inno Setup 6 folder (winget install JRSoftware.InnoSetup).
#>
param(
    [string]$Python = '',
    [switch]$SelfTest,
    [switch]$Installer,
    [string]$Iscc = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $root '.venv\Scripts\python.exe' }
if (-not (Test-Path $Python)) { throw "Python not found: $Python (create the venv first, see ROADMAP.md)" }

Push-Location $root
try {
    & $Python -m pip install --disable-pip-version-check -q -r requirements.txt -r packaging\requirements-build.txt
    if ($LASTEXITCODE) { throw 'pip install failed' }

    $started = Get-Date
    & $Python -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build\pyinstaller packaging\mytts.spec
    if ($LASTEXITCODE) { throw 'PyInstaller failed' }

    $out = Join-Path $root 'dist\myTTS'
    $exe = Join-Path $out 'myTTS.exe'
    $bytes = (Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum
    $took = [int]((Get-Date) - $started).TotalSeconds
    Write-Host ('Built {0} ({1:N0} MB, {2} s)' -f $exe, ($bytes / 1MB), $took)

    if ($SelfTest) {
        # A windowed exe: Start-Process -Wait gives its exit code; its output goes to a file.
        $log = Join-Path $env:TEMP 'mytts-self-test.txt'
        $p = Start-Process $exe -ArgumentList '--self-test' -Wait -PassThru -NoNewWindow -RedirectStandardOutput $log
        Get-Content $log
        if ($p.ExitCode) { throw "Self-test failed (exit code $($p.ExitCode))" }
    }

    if ($Installer) {
        if (-not $Iscc) {
            $found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
            $candidates = @(
                $(if ($found) { $found.Source }),
                (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
                (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
                (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
            ) | Where-Object { $_ -and (Test-Path $_) }
            if (-not $candidates) { throw 'Inno Setup 6 not found: winget install JRSoftware.InnoSetup, or pass -Iscc' }
            $Iscc = @($candidates)[0]
        }
        & $Python packaging\installer_assets.py build\installer
        if ($LASTEXITCODE) { throw 'installer_assets.py failed' }
        $started = Get-Date
        & $Iscc /Q packaging\mytts.iss
        if ($LASTEXITCODE) { throw "Inno Setup failed (exit code $LASTEXITCODE)" }
        $setup = Get-ChildItem (Join-Path $root 'dist\myTTS-setup-*.exe') | Sort-Object LastWriteTime | Select-Object -Last 1
        $took = [int]((Get-Date) - $started).TotalSeconds
        Write-Host ('Built {0} ({1:N0} MB, {2} s)' -f $setup.FullName, ($setup.Length / 1MB), $took)
    }
}
finally {
    Pop-Location
}
