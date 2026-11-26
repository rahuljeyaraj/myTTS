"""The Windows installer (packaging/mytts.iss) and the licenses folder (packaging/notices.py).

These don't install anything. The script compiles in syntax-only mode when Inno Setup and a
build in dist\\myTTS are present.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mytts import __version__, autostart, models
from mytts.ui import native

ROOT = Path(__file__).resolve().parent.parent
ISS = ROOT / "packaging" / "mytts.iss"
sys.path.insert(0, str(ROOT / "packaging"))

import installer_assets  # noqa: E402
import notices  # noqa: E402


def _iscc() -> Path | None:
    import os

    found = shutil.which("ISCC.exe")
    candidates = [found] if found else []
    for base in (os.environ.get("LOCALAPPDATA", "") + r"\Programs", os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("ProgramFiles", "")):
        candidates.append(base + r"\Inno Setup 6\ISCC.exe")
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


def test_script_is_ascii():
    ISS.read_text(encoding="ascii")


def test_assets_and_defines(tmp_path):
    from PySide6.QtGui import QImage

    defines = installer_assets.write(tmp_path).read_text(encoding="utf-8")
    values = dict(re.findall(r'^#define (\w+) "(.*)"$', defines, re.M))
    assert values["AppVersion"] == __version__
    assert values["AppUserModelID"] == native.APP_ID
    assert values["ModelBaseUrl"] + "/" + values["ModelName"] == models.MODEL.url
    assert values["ModelSha256"] == models.MODEL.sha256 and int(values["ModelSize"]) == models.MODEL.size
    assert values["VoicesSha256"] == models.VOICES.sha256 and int(values["VoicesSize"]) == models.VOICES.size
    for name in values["SmallImages"].split(","):
        img = QImage(name)
        assert img.width() == img.height() >= 58
    for name in values["LargeImages"].split(","):
        img = QImage(name)
        assert abs(img.width() / img.height() - 164 / 314) < 0.01
    assert (tmp_path / "mytts.ico").stat().st_size > 1000


def test_run_entry_matches_the_app():
    # Setup writes the same "Start with Windows" entry as the app, so the app doesn't rewrite it.
    text = ISS.read_text(encoding="ascii")
    assert f"RunKey = '{autostart.RUN_KEY}';" in text
    assert f"RunValue = '{autostart.VALUE_NAME}';" in text
    assert "'\"' + AppExePath + '\" --tray'" in text
    assert "AppId=mytts\n" in text  # Settings > Apps key mytts_is1, which install.ps1 checks for
    assert "mytts_is1" in (ROOT / "install.ps1").read_text(encoding="ascii")


def test_script_compiles(tmp_path):
    iscc = _iscc()
    exe = ROOT / "dist" / "myTTS" / "myTTS.exe"
    if iscc is None or not exe.is_file():
        pytest.skip("needs Inno Setup 6 and a build in dist\\myTTS")
    installer_assets.write(tmp_path)
    r = subprocess.run([str(iscc), "/O-", f"/DAssetsDir={tmp_path}", str(ISS)],
                       capture_output=True, text=True, timeout=120)
    if "does not match mytts.__version__" in r.stdout + r.stderr:
        pytest.skip("dist\\myTTS is older than the source")
    assert r.returncode == 0, r.stdout + r.stderr


def test_bundled_distributions():
    names = {d.metadata["Name"] for d in notices.bundled_distributions(
        ["numpy._core.multiarray", "phonemizer.backend", "json", "mytts.engine"],
        ["PySide6/Qt6Core.dll", f"python3{sys.version_info[1]}.dll"],
    )}
    assert {"numpy", "phonemizer", "PySide6_Essentials"} <= names
    assert "pytest" not in names and "mytts" not in names


def test_espeak_version_is_known():
    import espeakng_loader

    dll = Path(espeakng_loader.get_library_path())
    assert notices.espeak_version(dll) in notices.ESPEAK_SOURCE


def test_licenses_folder(tmp_path):
    import espeakng_loader

    internal = tmp_path / "_internal" / "espeakng_loader"
    internal.mkdir(parents=True)
    shutil.copy(espeakng_loader.get_library_path(), internal / "espeak-ng.dll")
    path = notices.write(tmp_path, ["numpy", "phonemizer", "kokoro_onnx", "espeakng_loader"],
                         ["PySide6/Qt6Core.dll"], repo_copy=None)
    text = path.read_text(encoding="utf-8")
    assert "GNU GPL version 3" in text and "eSpeak NG" in text and "Kokoro-82M" in text
    licenses = tmp_path / "licenses"
    for name in ("myTTS-LICENSE.txt", "GPL-3.0.txt", "LGPL-3.0.txt", "Apache-2.0.txt", "PortAudio.txt"):
        assert (licenses / name).is_file()
    # Every license file the notices name is in the folder.
    for listed in re.findall(r"^- License files: (.*)$", text, re.M):
        rels = re.findall(r"`([^`]+)`", listed)
        assert len(rels) == len(set(rels)), f"listed twice: {listed}"
        for rel in rels:
            assert (licenses / rel).is_file(), rel
    # Files in .dist-info/licenses count whatever their name (numpy's dragon4_LICENSE.txt).
    numpy_files = {f.name for f in (licenses / "numpy").iterdir()}
    assert any("dragon4" in n for n in numpy_files), numpy_files
