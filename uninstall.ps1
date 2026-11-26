<#
.SYNOPSIS
    Removes myTTS installed by install.ps1.

.DESCRIPTION
    Closes myTTS if it is running, then removes its Start menu shortcut, its
    Windows startup entry, its entry in Settings > Apps, its Python environment
    and the voice model. Your settings (%APPDATA%\mytts) are kept unless you add
    -RemoveSettings.

.PARAMETER KeepModel
    Keep the voice model (%LOCALAPPDATA%\mytts\models), for example to install
    again later without downloading it again.

.PARAMETER RemoveSettings
    Also delete your settings.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File uninstall.ps1
#>
[CmdletBinding()]
param(
    [switch]$KeepModel,
    [switch]$RemoveSettings
)

Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'

$Root = Join-Path $env:LOCALAPPDATA 'mytts'
$Venv = Join-Path $Root 'venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Models = Join-Path $Root 'models'
$Settings = Join-Path $env:APPDATA 'mytts'
$Shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'myTTS.lnk'
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\mytts'
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'

$script:removed = 0
$script:failed = 0

function Write-Step([string]$Text) {
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Remove-Path([string]$Path, [string]$What) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Write-Step "Removing $What"
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force
        $script:removed++
    } catch {
        Write-Warning "Could not remove ${Path}: $($_.Exception.Message)"
        $script:failed++
    }
}

function Get-InstalledProcess {
    $prefix = $Venv.TrimEnd('\') + '\'
    @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $path = $null
        try { $path = $_.Path } catch { }
        $path -and $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
    })
}

# Windows can't delete a folder that is a process's current directory, and this
# script may have been started from inside the install folder.
Set-Location -LiteralPath $env:TEMP
[Environment]::CurrentDirectory = $env:TEMP

# 1. Close the installed copy if it is running (its files are locked while it runs).
$procs = Get-InstalledProcess
if ($procs) {
    Write-Step 'Closing myTTS'
    if (Test-Path $VenvPython) {
        $ErrorActionPreference = 'Continue'
        & $VenvPython -m mytts quit 2>$null | Out-Null
        $ErrorActionPreference = 'Stop'
    }
    $procs | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
    Get-InstalledProcess | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300
}

# 2. Start with Windows. Only the entry of this install: one that starts a
#    source checkout belongs to that checkout.
$run = Get-ItemProperty -Path $RunKey -ErrorAction SilentlyContinue
if ($run -and $run.PSObject.Properties['mytts'] -and
        $run.mytts.IndexOf($Root, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
    Write-Step 'Removing the Windows startup entry'
    Remove-ItemProperty -Path $RunKey -Name 'mytts'
    $script:removed++
}

# 3. Start menu shortcut and the Settings > Apps entry.
Remove-Path $Shortcut 'the Start menu shortcut'
Remove-Path $UninstallKey 'the Settings > Apps entry'

# 4. The program: Python environment, icon, this uninstaller's copy, the voice model.
Remove-Path $Venv 'the Python environment'
foreach ($file in 'mytts.ico', 'uninstall.ps1') {
    $path = Join-Path $Root $file
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
        $script:removed++
    }
}
if ($KeepModel) {
    if (Test-Path $Models) { Write-Host "Keeping the voice model in $Models" }
} else {
    Remove-Path $Models 'the voice model'
}
if ((Test-Path $Root) -and -not (Get-ChildItem -LiteralPath $Root -Force)) {
    Remove-Item -LiteralPath $Root -Force
}

# 5. Settings.
if ($RemoveSettings) {
    Remove-Path $Settings 'your settings'
} elseif (Test-Path $Settings) {
    Write-Host "Keeping your settings in $Settings (add -RemoveSettings to delete them)"
}

Write-Host ''
if ($script:failed) {
    Write-Host 'myTTS was only partly removed; see the warnings above.' -ForegroundColor Yellow
    exit 1
} elseif ($script:removed) {
    Write-Host 'myTTS is uninstalled.' -ForegroundColor Green
} else {
    Write-Host 'myTTS is not installed.'
}
