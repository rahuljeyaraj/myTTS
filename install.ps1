<#
.SYNOPSIS
    Installs mytts for the current user.

.DESCRIPTION
    Creates a Python environment in %LOCALAPPDATA%\mytts\venv, installs mytts and
    its dependencies into it, downloads the voice model (354 MB, once), and adds
    mytts to the Start menu and to Settings > Apps. No administrator rights are
    needed.

    Run it again after updating the source to update the installed copy. The
    voice model and your settings are kept.

.PARAMETER Startup
    Also start mytts in the notification area when you sign in to Windows.
    (The same as "Start with Windows" in the mytts settings.)

.PARAMETER NoModel
    Skip the voice model download. The reader window offers it on first start.

.PARAMETER NoLaunch
    Do not start mytts when the install finishes.

.PARAMETER Python
    The python.exe to build the environment from: Python 3.10 to 3.13, 64-bit.
    By default the newest suitable Python registered in Windows is used.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -Startup
#>
[CmdletBinding()]
param(
    [switch]$Startup,
    [switch]$NoModel,
    [switch]$NoLaunch,
    [string]$Python
)

Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'

$Source = $PSScriptRoot
$Root = Join-Path $env:LOCALAPPDATA 'mytts'
$Venv = Join-Path $Root 'venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$VenvPythonw = Join-Path $Venv 'Scripts\pythonw.exe'
$IconFile = Join-Path $Root 'mytts.ico'
$Shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'mytts.lnk'
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\mytts'
$AppId = 'mytts.app'  # must match APP_ID in mytts\ui\native.py
$MinMinor, $MaxMinor = 10, 13  # kokoro-onnx supports Python 3.10 to 3.13

function Write-Step([string]$Text) {
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Invoke-Checked {
    # Runs a program and stops the install if it fails: Invoke-Checked exe arg1 arg2 ...
    $exe, $rest = $args
    & $exe @rest
    if ($LASTEXITCODE -ne 0) { throw "This step failed (exit code $LASTEXITCODE): $exe $rest" }
}

# ------------------------------------------------------------------ Python

$Probe = "import struct, sys, sysconfig; print(sys.version_info[0], sys.version_info[1], struct.calcsize('P') * 8, int(bool(sysconfig.get_config_var('Py_GIL_DISABLED'))))"

function Get-PythonInfo([string]$Exe) {
    # The version of a usable interpreter (64-bit CPython 3.10 to 3.13, not free-threaded), or $null.
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) { return $null }
    $ErrorActionPreference = 'Continue'
    $out = & $Exe -c $Probe 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
    $major, $minor, $bits, $freeThreaded = "$out".Trim() -split '\s+' | ForEach-Object { [int]$_ }
    if ($major -ne 3 -or $minor -lt $MinMinor -or $minor -gt $MaxMinor -or $bits -ne 64 -or $freeThreaded) {
        return $null
    }
    [pscustomobject]@{ Exe = $Exe; Minor = $minor; Version = "3.$minor" }
}

function Find-Python {
    # Pythons registered in Windows (PEP 514) come first; PATH only if none of them fits.
    $registered = @()
    foreach ($hive in 'HKCU:', 'HKLM:') {
        $base = "$hive\Software\Python\PythonCore"
        if (-not (Test-Path $base)) { continue }
        foreach ($key in Get-ChildItem $base) {
            $installPath = Join-Path $key.PSPath 'InstallPath'
            if (-not (Test-Path $installPath)) { continue }
            $props = Get-ItemProperty $installPath
            if ($props.PSObject.Properties['ExecutablePath']) {
                $registered += $props.ExecutablePath
            } elseif ($props.PSObject.Properties['(default)']) {
                $registered += Join-Path $props.'(default)' 'python.exe'
            }
        }
    }
    $onPath = @(Get-Command python3.13, python3.12, python3.11, python3.10, python3, python `
        -CommandType Application -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
    foreach ($group in @($registered), $onPath) {
        $found = @($group | Select-Object -Unique | ForEach-Object { Get-PythonInfo $_ } | Where-Object { $_ })
        if ($found) { return $found | Sort-Object Minor -Descending | Select-Object -First 1 }
    }
    $null
}

function Get-VenvHome {
    # The base interpreter's folder recorded in pyvenv.cfg.
    $cfg = Join-Path $Venv 'pyvenv.cfg'
    if (-not (Test-Path $cfg)) { return $null }
    foreach ($line in Get-Content $cfg) {
        if ($line -match '^\s*home\s*=\s*(.+?)\s*$') { return $Matches[1] }
    }
    $null
}

# ------------------------------------------------------------ running copy

function Get-InstalledProcess {
    $prefix = $Venv.TrimEnd('\') + '\'
    @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $path = $null
        try { $path = $_.Path } catch { }
        $path -and $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
    })
}

function Stop-Installed {
    # Files of a running copy are locked, so close it before changing the environment.
    $procs = Get-InstalledProcess
    if (-not $procs) { return }
    Write-Step 'Closing the running copy of mytts'
    if (Test-Path $VenvPython) {
        $ErrorActionPreference = 'Continue'
        & $VenvPython -m mytts quit 2>$null | Out-Null
    }
    $procs | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
    Get-InstalledProcess | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300
}

# ---------------------------------------------------------------- shortcut

$ShortcutCode = @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

namespace MyttsSetup
{
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    class CShellLink { }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
    interface IShellLinkW
    {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder file, int cch, IntPtr findData, uint flags);
        void GetIDList(out IntPtr pidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder name, int cch);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder dir, int cch);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string dir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder args, int cch);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
        void GetHotkey(out short hotkey);
        void SetHotkey(short hotkey);
        void GetShowCmd(out int showCmd);
        void SetShowCmd(int showCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int cch, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
        void Resolve(IntPtr hwnd, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct PropertyKey
    {
        public Guid FormatId;
        public uint PropertyId;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct PropVariant
    {
        public ushort Type;
        public ushort Reserved1, Reserved2, Reserved3;
        public IntPtr Value;
        public IntPtr Value2;
    }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    interface IPropertyStore
    {
        void GetCount(out uint count);
        void GetAt(uint index, out PropertyKey key);
        void GetValue(ref PropertyKey key, out PropVariant value);
        void SetValue(ref PropertyKey key, ref PropVariant value);
        void Commit();
    }

    public static class Shortcut
    {
        // A .lnk file with an AppUserModelID, which WScript.Shell cannot set.
        public static void Create(string lnk, string target, string arguments, string workDir,
                                  string icon, string description, string appId)
        {
            var link = (IShellLinkW)new CShellLink();
            try
            {
                link.SetPath(target);
                link.SetArguments(arguments);
                link.SetWorkingDirectory(workDir);
                link.SetIconLocation(icon, 0);
                link.SetDescription(description);
                var key = new PropertyKey
                {
                    FormatId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),  // PKEY_AppUserModel_ID
                    PropertyId = 5
                };
                var value = new PropVariant { Type = 31 /* VT_LPWSTR */, Value = Marshal.StringToCoTaskMemUni(appId) };
                try
                {
                    var store = (IPropertyStore)link;
                    store.SetValue(ref key, ref value);
                    store.Commit();
                }
                finally
                {
                    Marshal.FreeCoTaskMem(value.Value);
                }
                ((IPersistFile)link).Save(lnk, true);
            }
            finally
            {
                Marshal.ReleaseComObject(link);
            }
        }
    }
}
'@

# --------------------------------------------------------------------- main

try {
    if (-not (Test-Path (Join-Path $Source 'pyproject.toml'))) {
        throw "install.ps1 must stay in the mytts source folder (pyproject.toml was not found next to it)."
    }
    $identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    $elevated = $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($elevated) {
        Write-Warning ('This PowerShell window runs as administrator. mytts is installed for the current ' +
            'user and does not need that. It will not be started from here, so it does not run elevated.')
    }

    # 1. A Python environment of its own.
    if ($Python) {
        $base = Get-PythonInfo $Python
        if (-not $base) { throw "$Python is not a usable Python. mytts needs 64-bit Python 3.$MinMinor to 3.$MaxMinor." }
    }
    $venvOk = Get-PythonInfo $VenvPython
    $sameBase = -not $Python -or ((Get-VenvHome) -eq (Split-Path -Parent (Resolve-Path $Python).Path))
    if ($venvOk -and $sameBase) {
        Write-Step "Updating the Python environment in $Venv (Python $($venvOk.Version))"
        Stop-Installed
    } else {
        if (-not $Python) {
            $base = Find-Python
            if (-not $base) {
                throw ("mytts needs 64-bit Python 3.$MinMinor to 3.$MaxMinor, and none was found. Install it with " +
                    "'winget install Python.Python.3.12' or from python.org, then run install.ps1 again.")
            }
        }
        Write-Step "Creating the Python environment in $Venv (Python $($base.Version))"
        Stop-Installed
        if (Test-Path $Venv) { Remove-Item -LiteralPath $Venv -Recurse -Force }
        New-Item -ItemType Directory -Force $Root | Out-Null
        Invoke-Checked $base.Exe -m venv $Venv
    }

    # 2. mytts and its dependencies. mytts itself is always reinstalled, so the
    #    current source is installed even when the version number did not change.
    #    It is built from a copy: pip builds in place, and setuptools' build\ folder
    #    in the source would otherwise collect files that later builds still package.
    Write-Step 'Installing mytts and its dependencies'
    Invoke-Checked $VenvPython -m pip install --quiet --disable-pip-version-check --upgrade pip
    Invoke-Checked $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $Source 'requirements.txt')
    $stage = Join-Path ([IO.Path]::GetTempPath()) "mytts-install-$PID"
    try {
        New-Item -ItemType Directory -Force $stage | Out-Null
        foreach ($item in 'mytts', 'pyproject.toml', 'README.md', 'LICENSE') {
            Copy-Item -LiteralPath (Join-Path $Source $item) -Destination $stage -Recurse
        }
        Invoke-Checked $VenvPython -m pip install --quiet --disable-pip-version-check --no-deps --force-reinstall $stage
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
    $version = (& $VenvPython -c 'import mytts; print(mytts.__version__)').Trim()

    # 3. The voice model.
    if ($NoModel) {
        Write-Step 'Skipping the voice model; the reader window offers the download on first start'
    } else {
        Write-Step 'Checking the voice model'
        & $VenvPython -m mytts download
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'The voice model was not downloaded. The reader window offers the download again on first start.'
        }
    }

    # 4. Start menu shortcut, with the app icon and the app's AppUserModelID.
    Write-Step 'Adding mytts to the Start menu'
    Invoke-Checked $VenvPython -c 'import sys; from mytts.ui.icon import save_ico; save_ico(sys.argv[1])' $IconFile
    if (-not ('MyttsSetup.Shortcut' -as [type])) { Add-Type -TypeDefinition $ShortcutCode }
    [MyttsSetup.Shortcut]::Create($Shortcut, $VenvPythonw, '-m mytts', $Root, $IconFile,
        'Read selected text aloud with natural offline voices', $AppId)

    # 5. Settings > Apps entry, with an uninstaller that works without the source folder.
    $uninstaller = Join-Path $Root 'uninstall.ps1'
    Copy-Item -LiteralPath (Join-Path $Source 'uninstall.ps1') -Destination $uninstaller -Force
    $sizeKb = [int]((Get-ChildItem -LiteralPath $Root -Recurse -File -Force | Measure-Object Length -Sum).Sum / 1KB)
    New-Item -Path $UninstallKey -Force | Out-Null
    $entry = @{
        DisplayName     = 'mytts'
        DisplayVersion  = $version
        DisplayIcon     = $IconFile
        InstallLocation = $Root
        UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$uninstaller`""
    }
    foreach ($name in $entry.Keys) { New-ItemProperty -Path $UninstallKey -Name $name -Value $entry[$name] -Force | Out-Null }
    foreach ($name in 'NoModify', 'NoRepair') {
        New-ItemProperty -Path $UninstallKey -Name $name -Value 1 -PropertyType DWord -Force | Out-Null
    }
    New-ItemProperty -Path $UninstallKey -Name EstimatedSize -Value $sizeKb -PropertyType DWord -Force | Out-Null

    # 6. Start with Windows, if asked. The app writes the same Run entry from its settings.
    if ($Startup) {
        Write-Step 'Starting mytts when you sign in to Windows'
        Invoke-Checked $VenvPython -c 'from mytts import autostart; autostart.set_enabled(True)'
    }

    Write-Host ''
    Write-Host "mytts $version is installed." -ForegroundColor Green
    Write-Host 'Select text in any app and press the hotkey (Ctrl+Alt+Space unless you changed it).'
    Write-Host 'Start it from the Start menu; remove it from Settings > Apps or with uninstall.ps1.'
    if (-not $NoLaunch -and -not $elevated) {
        Start-Process -FilePath $Shortcut
    }
} catch {
    Write-Host ''
    Write-Host "Install failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
