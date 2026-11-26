"""Checks on install.ps1, uninstall.ps1 and packaging/build.ps1 that don't install or build anything."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from mytts.ui import native

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [ROOT / "install.ps1", ROOT / "uninstall.ps1", ROOT / "packaging" / "build.ps1"]


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_is_ascii(script):
    # Windows PowerShell 5.1 reads a file without a BOM in the ANSI code page.
    script.read_text(encoding="ascii")


def test_installer_matches_the_app():
    text = (ROOT / "install.ps1").read_text(encoding="ascii")
    assert f"$AppId = '{native.APP_ID}'" in text

    low, high = map(int, re.search(r"\$MinMinor, \$MaxMinor = (\d+), (\d+)", text).groups())
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'requires-python = ">=3.{low},<3.{high + 1}"' in pyproject


@pytest.mark.skipif(not shutil.which("powershell"), reason="needs Windows PowerShell")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_parses(script):
    path = str(script).replace("'", "''")
    check = (
        "$errors = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$null, [ref]$errors); "
        "$errors | ForEach-Object { $_.ToString() }; exit $errors.Count"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", check],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
