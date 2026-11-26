# PyInstaller spec for the self-contained build: dist\myTTS\myTTS.exe plus its _internal folder.
#
# Build with packaging\build.ps1 (or: pyinstaller --noconfirm packaging\mytts.spec from the repo root).
# One-folder mode on purpose: it starts faster than one-file, antivirus flags it less, and the
# Qt DLLs stay separate, replaceable files as the LGPL requires.

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
BUILD = Path(workpath)
sys.path.insert(0, str(ROOT))

import mytts  # noqa: E402
from mytts.ui.icon import save_ico  # noqa: E402

VERSION = mytts.__version__
NAME = mytts.DISPLAY_NAME
ICON = BUILD / "mytts.ico"
save_ico(ICON)

numbers = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3]) + (0,)
copyright_line = next(line for line in (ROOT / "LICENSE").read_text(encoding="utf-8").splitlines()
                      if line.startswith("Copyright"))
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", NAME),
            StringStruct("FileDescription", NAME),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "mytts"),
            StringStruct("LegalCopyright", copyright_line.replace("(c)", "©")),
            StringStruct("OriginalFilename", f"{NAME}.exe"),
            StringStruct("ProductName", NAME),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

# Files the dependencies open at run time, which import analysis can't see.
datas = (
    collect_data_files("espeakng_loader")  # espeak-ng-data (phoneme tables, language dictionaries)
    + collect_data_files("kokoro_onnx")  # config.json (the phoneme vocabulary)
    + copy_metadata("kokoro-onnx")  # it logs its own version through importlib.metadata
)
binaries = collect_dynamic_libs("espeakng_loader")  # espeak-ng.dll, loaded by path with ctypes

EXCLUDES = [
    # Not used, but pulled in by optional imports of the dependencies.
    "tkinter", "sympy", "mpmath", "PIL", "matplotlib", "IPython", "pytest", "_pytest",
    "setuptools", "pkg_resources", "distutils", "pygments", "coloredlogs", "humanfriendly",
    "onnxruntime.quantization", "onnxruntime.tools", "onnxruntime.transformers",
    "onnxruntime.training",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,  # kokoro_onnx and phonemizer use assert for checks; keep them
)

# Qt: keep only the Windows platform plugin. The app draws its own icons and uses
# the built-in Fusion style; it needs no image formats, TLS, translations or
# software OpenGL. QtNetwork is used only for QLocalServer (the single instance).
QT_KEEP_PLUGINS = {"platforms/qwindows.dll"}
QT_DROP_DLLS = {"opengl32sw.dll", "qt6pdf.dll", "qt6svg.dll", "qt6opengl.dll", "qt6qml.dll",
                "qt6qmlmodels.dll", "qt6qmlmeta.dll", "qt6qmlworkerscript.dll", "qt6quick.dll",
                "qt6virtualkeyboard.dll"}
# sounddevice ships PortAudio for every platform; it loads libportaudio64bit.dll on 64-bit Windows.
# The ASIO builds are only used when SD_ENABLE_ASIO is set, which myTTS doesn't do.
PORTAUDIO_KEEP = {"libportaudio64bit.dll", "readme.md"}
# OpenSSL 3 comes with PySide6 for Qt's TLS plugin, which is left out. Python's own _ssl
# (used to download the voice model) links to OpenSSL 1.1, which stays.
DROP_TOP = {"libcrypto-3-x64.dll", "libssl-3-x64.dll"}


def keep(entry) -> bool:
    dest = entry[0].replace("\\", "/")
    low = dest.lower()
    if low in DROP_TOP:
        return False
    if low.startswith("_sounddevice_data/portaudio-binaries/"):
        return low.rsplit("/", 1)[-1] in PORTAUDIO_KEEP
    if low.startswith("pyside6/translations/"):
        return False
    if low.startswith("pyside6/plugins/"):
        return low[len("pyside6/plugins/"):] in QT_KEEP_PLUGINS
    if low.startswith("pyside6/") and low.rsplit("/", 1)[-1] in QT_DROP_DLLS:
        return False
    return True


a.binaries = [e for e in a.binaries if keep(e)]
a.datas = [e for e in a.datas if keep(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    icon=str(ICON),
    version=version_info,
    console=False,  # a windowed program: no console window opens
    # Errors in the app go to mytts.logs (log file and dialog). PyInstaller's own dialog stays on
    # for anything that fails before that is set up, such as a missing module.
    disable_windowed_traceback=False,
    upx=False,
    debug=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)

# COLLECT has built dist/myTTS by now. Add the licenses folder next to myTTS.exe (license texts
# and THIRD_PARTY_NOTICES.md, also written to the repository root).
sys.path.insert(0, str(ROOT / "packaging"))
import notices  # noqa: E402

notices.write(Path(DISTPATH) / NAME, [e[0] for e in a.pure], [e[0] for e in a.binaries + a.datas])
