"""The licenses folder of the self-contained build: license texts and THIRD_PARTY_NOTICES.md.

Called by packaging/mytts.spec after PyInstaller has collected the build, with the modules
and files it bundled. It finds the Python distributions they came from, copies their
license files, adds the components that are not Python packages (the Python runtime, Qt,
eSpeak NG, PortAudio, the PyInstaller bootloader), and writes
dist/myTTS/licenses/THIRD_PARTY_NOTICES.md. The same file is written to the repository
root, so the repository always shows what the last build bundled.
"""

from __future__ import annotations

import ctypes
import re
import shutil
import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# GPL-3.0, LGPL-3.0, Apache-2.0 and PortAudio texts, plus license files of packages whose wheels
# leave them out (packaging/licenses/<distribution>/).
COMMON = Path(__file__).resolve().parent / "licenses"

# eSpeak NG versions we know the exact source of. espeakng-loader builds espeak-ng.dll from
# the upstream tag with CMake and no patches. A new version fails the build until it is added
# here, so every release names (and M8 attaches) the right source.
ESPEAK_SOURCE = {
    "1.52.0": ("1.52.0", "4870adfa25b1a32b4361592f1be8a40337c58d6c"),
}

# Licenses that the package metadata doesn't state clearly (missing, a full text, or a choice).
LICENSE_OVERRIDES = {
    "espeakng-loader": "MIT",
    "kokoro-onnx": "MIT",
    "numpy": "BSD-3-Clause (bundled OpenBLAS: BSD-3-Clause; see its license files)",
    "phonemizer": "GPL-3.0-or-later",
    "PySide6_Essentials": "LGPL-3.0-only (used under the LGPL)",
    "shiboken6": "LGPL-3.0-only (used under the LGPL)",
}
URL_OVERRIDES = {"espeakng-loader": "https://github.com/thewh1teagle/espeakng-loader"}
# License files that don't apply to how the package is used here.
SKIP_FILES = {"LicenseRef-Qt-Commercial.txt"}
LICENSE_NAME = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|THIRDPARTYNOTICES|THIRD_PARTY_NOTICES)", re.I)


@dataclass
class Component:
    name: str
    version: str
    license: str
    url: str
    what: str = ""
    files: list[str] = field(default_factory=list)  # relative to the licenses folder
    note: str = ""


def _top(name: str) -> str:
    """The top-level import name of a module or a bundled file's path."""
    return name.replace("\\", "/").split("/")[0].split(".")[0]


def _dist_tops(d: metadata.Distribution) -> set[str]:
    tops = set()
    for f in d.files or []:
        first = f.parts[0]
        if first in ("..", "__pycache__") or first.endswith((".dist-info", ".egg-info", ".data")):
            continue
        tops.add(_top(first))
    return tops


def bundled_distributions(modules: list[str], files: list[str]) -> list[metadata.Distribution]:
    """The installed distributions that the build took modules or files from."""
    bundled = {_top(m) for m in modules} | {_top(f) for f in files}
    seen, result = set(), []
    for d in metadata.distributions():
        name = d.metadata["Name"]
        if name.lower() in seen or name.lower() == "mytts":
            continue
        if _dist_tops(d) & bundled:
            seen.add(name.lower())
            result.append(d)
    return sorted(result, key=lambda d: d.metadata["Name"].lower())


def _license(d: metadata.Distribution) -> str:
    md = d.metadata
    name = md["Name"]
    if name in LICENSE_OVERRIDES:
        return LICENSE_OVERRIDES[name]
    if md.get("License-Expression"):
        return md["License-Expression"]
    text = (md.get("License") or "").strip()
    if text and "\n" not in text and len(text) <= 60:
        return text
    classifiers = [c.split(" :: ")[-1] for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    return ", ".join(classifiers) or "see its license files"


def _url(d: metadata.Distribution) -> str:
    md = d.metadata
    urls = {}
    for entry in md.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls[label.strip().lower()] = url.strip()
    for key in ("homepage", "home", "source", "source code", "repository", "github"):
        if key in urls:
            return urls[key]
    return md.get("Home-page") or f"https://pypi.org/project/{md['Name']}/"


def _copy_license_files(d: metadata.Distribution, dest: Path) -> list[Path]:
    copied = []
    for f in d.files or []:
        if not LICENSE_NAME.match(f.name) or f.name in SKIP_FILES or f.suffix in (".py", ".pyc"):
            continue
        parts = f.parts
        if parts[0].endswith(".dist-info"):
            parts = parts[2:] if len(parts) > 2 and parts[1] == "licenses" else parts[1:]
        target = dest / "-".join(parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(d.locate_file(f), target)
        copied.append(target)
    return copied


def espeak_version(dll: Path) -> str:
    lib = ctypes.CDLL(str(dll))
    lib.espeak_Info.restype = ctypes.c_char_p
    lib.espeak_Info.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
    return lib.espeak_Info(None).decode()


def _copy(src: Path, licenses: Path, rel: str) -> str:
    target = licenses / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, target)
    return rel


def collect(licenses: Path, modules: list[str], files: list[str], internal: Path) -> list[Component]:
    """Copy the license texts into `licenses` and describe every bundled component."""
    from PySide6.QtCore import qVersion
    import PyInstaller

    for src in sorted(COMMON.glob("*.txt")):
        _copy(src, licenses, src.name)

    comps = []
    for d in bundled_distributions(modules, files):
        name = d.metadata["Name"]
        copied = _copy_license_files(d, licenses / name)
        extra = COMMON / name
        if extra.is_dir():
            for src in sorted(extra.iterdir()):
                copied.append(licenses / _copy(src, licenses, f"{name}/{src.name}"))
        rels = [p.relative_to(licenses).as_posix() for p in copied]
        lic = _license(d)
        if "LGPL-3.0" in lic:
            rels.append("LGPL-3.0.txt")
        if not rels:
            raise SystemExit(f"{name} ships no license file: add one to {extra}")
        comps.append(Component(name, d.version, lic, URL_OVERRIDES.get(name) or _url(d), "Python package", rels))

    py = Path(sys.base_prefix) / "LICENSE.txt"
    comps.append(Component(
        "Python", sys.version.split()[0], "PSF-2.0", "https://www.python.org/",
        "the Python runtime (python310.dll and the standard library), with the libraries it bundles: "
        "OpenSSL 1.1, libffi, bzip2, xz, zlib, expat and mpdecimal",
        [_copy(py, licenses, "Python/LICENSE.txt")],
    ))
    comps.append(Component(
        "Qt", qVersion(), "LGPL-3.0-only", "https://www.qt.io/",
        "Qt6Core, Qt6Gui, Qt6Network and Qt6Widgets and the Windows platform plugin, through PySide6",
        ["LGPL-3.0.txt", "GPL-3.0.txt"],
        "The Qt libraries are separate DLLs in the _internal\\PySide6 folder, so you can replace them with "
        "your own build of the same Qt version. Third-party code inside Qt and its licenses: "
        "https://doc.qt.io/qt-6/licenses-used-in-qt.html",
    ))
    espeak_dll = internal / "espeakng_loader" / "espeak-ng.dll"
    version = espeak_version(espeak_dll)
    if version not in ESPEAK_SOURCE:
        raise SystemExit(f"eSpeak NG {version}: add its source tag and commit to ESPEAK_SOURCE in {__file__}")
    tag, commit = ESPEAK_SOURCE[version]
    comps.append(Component(
        "eSpeak NG", version, "GPL-3.0-or-later", "https://github.com/espeak-ng/espeak-ng",
        "espeak-ng.dll and espeak-ng-data (turns text into phonemes), from espeakng-loader",
        ["GPL-3.0.txt"],
        f"Built without changes from the upstream tag {tag} (commit {commit}). The source is at "
        f"https://github.com/espeak-ng/espeak-ng/tree/{tag} and is attached to every myTTS release.",
    ))
    import sounddevice

    comps.append(Component(
        "PortAudio", sounddevice.get_portaudio_version()[1], "MIT", "https://www.portaudio.com/",
        "libportaudio64bit.dll (audio output), from sounddevice", ["PortAudio.txt"],
    ))
    comps.append(Component(
        "PyInstaller bootloader", PyInstaller.__version__, "GPL-2.0-or-later WITH Bootloader-exception",
        "https://pyinstaller.org/", "the start-up code in myTTS.exe",
        [_copy_license_files(metadata.distribution("pyinstaller"), licenses / "PyInstaller")[0]
         .relative_to(licenses).as_posix()],
        "The bootloader exception allows distributing programs built with PyInstaller under any license.",
    ))
    return comps


def render(comps: list[Component]) -> str:
    from mytts import DISPLAY_NAME, PROJECT_URL, __version__

    out = [
        "# Third-party notices",
        "",
        f"{DISPLAY_NAME} {__version__} for Windows (the installer and myTTS.exe) includes the software below. "
        "The license texts are in the `licenses` folder next to myTTS.exe "
        "(`%LOCALAPPDATA%\\Programs\\mytts\\licenses` by default).",
        "",
        "## How myTTS is licensed",
        "",
        f"- The myTTS source code is MIT licensed (`myTTS-LICENSE.txt`, and {PROJECT_URL}).",
        "- The program as distributed includes eSpeak NG and phonemizer, which are GPL-3.0-or-later. "
        "So the installer and myTTS.exe as a whole are distributed under the terms of the GNU GPL version 3 "
        "(`GPL-3.0.txt`). The MIT license is compatible with the GPL, and each part keeps its own license.",
        "- The complete source of myTTS for each release is the matching tag in the repository. "
        "The eSpeak NG source of the version it bundles is attached to each release.",
        "- The voice model (Kokoro-82M, Apache-2.0) is not part of the installer: setup downloads it.",
        "",
        "## Components",
        "",
        "| Component | Version | License | What it is |",
        "|---|---|---|---|",
    ]
    for c in comps:
        out.append(f"| [{c.name}]({c.url}) | {c.version} | {c.license} | {c.what} |")
    out += ["", "## Details", ""]
    for c in comps:
        out.append(f"### {c.name} {c.version}")
        out.append("")
        out.append(f"- License: {c.license}")
        out.append(f"- Project: {c.url}")
        out.append("- License files: " + ", ".join(f"`{f}`" for f in c.files))
        if c.note:
            out.append(f"- {c.note}")
        out.append("")
    out += [
        "## Downloaded by setup (not in the installer)",
        "",
        "### Kokoro-82M voice model",
        "",
        "- License: Apache-2.0 (`Apache-2.0.txt`)",
        "- Model: https://huggingface.co/hexgrad/Kokoro-82M, by hexgrad",
        "- The ONNX files `kokoro-v1.0.onnx` and `voices-v1.0.bin` come from the kokoro-onnx project "
        "(https://github.com/thewh1teagle/kokoro-onnx, release model-files-v1.1). Setup checks their SHA-256.",
        "",
        "## Microsoft runtime files",
        "",
        "`vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140*.dll`, `ucrtbase.dll` and the `api-ms-win-*.dll` "
        "files are Microsoft Visual C++ and Universal C runtime files, redistributed as Microsoft allows.",
        "",
    ]
    return "\n".join(out)


def write(dist: Path, modules: list[str], files: list[str], repo_copy: Path | None = ROOT / "THIRD_PARTY_NOTICES.md") -> Path:
    """Fill dist/licenses; return the path of the notices file."""
    licenses = dist / "licenses"
    if licenses.exists():
        shutil.rmtree(licenses)
    licenses.mkdir(parents=True)
    shutil.copyfile(ROOT / "LICENSE", licenses / "myTTS-LICENSE.txt")
    comps = collect(licenses, modules, files, dist / "_internal")
    text = render(comps)
    notices = licenses / "THIRD_PARTY_NOTICES.md"
    notices.write_text(text, encoding="utf-8", newline="\n")
    if repo_copy is not None and (not repo_copy.exists() or repo_copy.read_text(encoding="utf-8") != text):
        repo_copy.write_text(text, encoding="utf-8", newline="\n")
    return notices
