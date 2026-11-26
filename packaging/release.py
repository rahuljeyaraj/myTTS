"""The files of a GitHub release, made by .github/workflows/release.yml after the build.

    python packaging/release.py check-tag v1.0.0
    python packaging/release.py assets --out dist/release [--tag v1.0.0]

`assets` needs dist/myTTS (the build) and dist/myTTS-setup-<version>.exe. It writes:

    <out>/assets/myTTS-setup-<version>.exe
    <out>/assets/espeak-ng-<version>.tar.gz   the eSpeak NG source the build bundles (GPL-3.0)
    <out>/assets/phonemizer-<version>.tar.gz  the phonemizer sdist from PyPI (GPL-3.0)
    <out>/assets/SHA256SUMS.txt               for the three files above (`sha256sum -c` format)
    <out>/notes.md                            the release notes: CHANGELOG.md's section, then
                                              how to install and check the download

The eSpeak NG version is read from the bundled espeak-ng.dll and mapped to its upstream tag and
commit by notices.ESPEAK_SOURCE. The phonemizer version is the one installed in this Python,
which is the one PyInstaller bundled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))

import notices  # noqa: E402
from mytts import DISPLAY_NAME, __version__  # noqa: E402

ESPEAK_REPO = "https://github.com/espeak-ng/espeak-ng.git"


def check_tag(tag: str) -> str:
    """The version a `v<version>` tag names; fails unless it is mytts.__version__."""
    if tag != f"v{__version__}":
        raise SystemExit(f"Tag {tag} doesn't match the version in mytts/__init__.py ({__version__}): "
                         f"tag v{__version__}, or change __version__ first")
    return __version__


def changelog_section(text: str, version: str) -> str:
    """The body of the `## [<version>]` section of a Keep a Changelog file."""
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.M)
    m = heading.search(text)
    if not m:
        raise SystemExit(f"CHANGELOG.md has no section for {version}: add '## [{version}] - <date>'")
    rest = text[m.end():]
    end = re.search(r"^## |^\[[^\]]+\]: ", rest, re.M)
    body = (rest[:end.start()] if end else rest).strip()
    if not body:
        raise SystemExit(f"CHANGELOG.md's section for {version} is empty")
    return body


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def write_sums(files: list[Path], out: Path) -> dict[str, str]:
    sums = {f.name: sha256(f) for f in files}
    out.write_text("".join(f"{h}  {name}\n" for name, h in sums.items()), encoding="ascii", newline="\n")
    return sums


def espeak_source(dll: Path, out_dir: Path) -> tuple[Path, str, str]:
    """Archive the upstream source of the bundled eSpeak NG; returns (file, tag, commit)."""
    version = notices.espeak_version(dll)
    if version not in notices.ESPEAK_SOURCE:
        raise SystemExit(f"eSpeak NG {version}: add its source tag and commit to notices.ESPEAK_SOURCE")
    tag, commit = notices.ESPEAK_SOURCE[version]
    target = out_dir / f"espeak-ng-{version}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        def git(*args: str) -> str:
            return subprocess.run(["git", "-C", tmp, *args], check=True, capture_output=True, text=True).stdout.strip()

        git("init", "-q")
        git("fetch", "-q", "--depth", "1", ESPEAK_REPO, f"refs/tags/{tag}")
        got = git("rev-parse", "FETCH_HEAD^{commit}")
        if got != commit:
            raise SystemExit(f"eSpeak NG tag {tag} is commit {got} upstream, not {commit}")
        git("archive", "--format=tar.gz", f"--prefix=espeak-ng-{version}/", "-o", str(target.resolve()), commit)
    return target, tag, commit


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mytts-release"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def pypi_sdist(name: str, version: str, out_dir: Path) -> Path:
    """Download a distribution's sdist from PyPI and check it against PyPI's SHA-256."""
    info = json.loads(_get(f"https://pypi.org/pypi/{name}/{version}/json"))
    sdists = [u for u in info["urls"] if u["packagetype"] == "sdist"]
    if not sdists:
        raise SystemExit(f"{name} {version} has no sdist on PyPI")
    u = sdists[0]
    data = _get(u["url"])
    if hashlib.sha256(data).hexdigest() != u["digests"]["sha256"]:
        raise SystemExit(f"{u['filename']}: SHA-256 doesn't match PyPI's")
    target = out_dir / u["filename"]
    target.write_bytes(data)
    return target


def release_notes(version: str, changes: str, sums: dict[str, str], espeak: tuple[str, str, str],
                  phonemizer: tuple[str, str]) -> str:
    setup = f"{DISPLAY_NAME}-setup-{version}.exe"
    e_version, e_tag, e_commit = espeak
    p_version, p_file = phonemizer
    rows = "\n".join(f"| `{name}` | `{h}` |" for name, h in sums.items())
    return f"""{changes}

## Install

Download **{setup}** below and run it. It needs Windows 10 or 11 (64-bit), and no administrator rights or Python. Setup downloads the voice model (354 MB, once). It updates an installed copy in place, keeping the voice model and your settings.

The installer isn't code-signed yet, so Windows SmartScreen may show "Windows protected your PC". Click **More info**, then **Run anyway**. To check the download first, compare its SHA-256 with the one below (they are also in `SHA256SUMS.txt`):

```powershell
Get-FileHash .\\{setup}
```

| File | SHA-256 |
|---|---|
{rows}

## Source code

This release is built from the tag `v{version}`. The installer bundles eSpeak NG and phonemizer, which are GPL-3.0-or-later; their source is attached: `espeak-ng-{e_version}.tar.gz` (the upstream tag `{e_tag}`, commit `{e_commit}`, built without changes) and `{p_file}` (phonemizer {p_version}, from PyPI). `THIRD_PARTY_NOTICES.md` lists every bundled component.
"""


def assets(out: Path, tag: str | None) -> None:
    version = check_tag(tag) if tag else __version__
    dist = ROOT / "dist"
    setup = dist / f"{DISPLAY_NAME}-setup-{version}.exe"
    dll = dist / "myTTS" / "_internal" / "espeakng_loader" / "espeak-ng.dll"
    for p in (setup, dll):
        if not p.is_file():
            raise SystemExit(f"Missing {p}: build with packaging\\build.ps1 -Installer first")
    changes = changelog_section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version)

    if out.exists():
        shutil.rmtree(out)
    files = out / "assets"
    files.mkdir(parents=True)
    shutil.copyfile(setup, files / setup.name)
    espeak_file, e_tag, e_commit = espeak_source(dll, files)
    p_version = metadata.version("phonemizer")
    p_file = pypi_sdist("phonemizer", p_version, files)
    uploads = [files / setup.name, espeak_file, p_file]
    sums = write_sums(uploads, files / "SHA256SUMS.txt")
    notes = release_notes(version, changes, sums, (notices.espeak_version(dll), e_tag, e_commit),
                          (p_version, p_file.name))
    (out / "notes.md").write_text(notes, encoding="utf-8", newline="\n")
    for f in sorted(files.iterdir()):
        print(f"{f.name:40} {f.stat().st_size / 1e6:8.1f} MB")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check-tag", help="fail unless the tag is v<mytts.__version__>")
    c.add_argument("tag")
    a = sub.add_parser("assets", help="collect the release files and notes")
    a.add_argument("--out", type=Path, default=ROOT / "dist" / "release")
    a.add_argument("--tag", help="the tag being released (checked against the version)")
    args = p.parse_args(argv)
    if args.cmd == "check-tag":
        print(check_tag(args.tag))
    else:
        assets(args.out, args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
