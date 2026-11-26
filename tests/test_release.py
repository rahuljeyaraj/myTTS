"""Checks on the release pipeline: packaging/release.py, the lock file and the workflows."""

import re
import sys
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from mytts import __version__

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

import release  # noqa: E402

WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _requirements(path: Path) -> list[Requirement]:
    lines = (l.split("#")[0].strip() for l in path.read_text(encoding="utf-8").splitlines())
    return [Requirement(l) for l in lines if l]


def _lock() -> dict[str, str]:
    pins = {}
    for r in _requirements(ROOT / "packaging" / "requirements-lock.txt"):
        (spec,) = r.specifier
        assert spec.operator == "==", f"{r} is not an exact pin"
        name = canonicalize_name(r.name)
        assert name not in pins, f"{r.name} is pinned twice"
        pins[name] = spec.version
    return pins


def test_lock_satisfies_the_requirements():
    pins = _lock()
    for file in (ROOT / "requirements.txt", ROOT / "packaging" / "requirements-build.txt"):
        for r in _requirements(file):
            name = canonicalize_name(r.name)
            assert name in pins, f"{r.name} from {file.name} is missing in requirements-lock.txt"
            assert r.specifier.contains(pins[name]), f"{r.name}=={pins[name]} doesn't satisfy {r} in {file.name}"


def test_lock_matches_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    deps = re.search(r"dependencies = \[(.*?)\]", text, re.S).group(1)
    pins = _lock()
    for dep in re.findall(r'"([^"]+)"', deps):
        r = Requirement(dep)
        assert r.specifier.contains(pins[canonicalize_name(r.name)]), dep


def test_python_version_file():
    # The release's Python (setup-python reads it; Dependabot filters the lock's updates by it).
    version = (ROOT / "packaging" / ".python-version").read_text(encoding="ascii").strip()
    assert re.fullmatch(r"3\.\d+\.\d+", version)
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    low, high = map(int, re.search(r'requires-python = ">=3\.(\d+),<3\.(\d+)"', text).groups())
    assert low <= int(version.split(".")[1]) < high


def test_python_ranges_agree():
    # pyproject.toml, install.ps1 and CI name the same Python versions: the locked CI job runs
    # the release's Python, and the other one the oldest supported version.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    low, high = map(int, re.search(r'requires-python = ">=3\.(\d+),<3\.(\d+)"', text).groups())
    ps1 = (ROOT / "install.ps1").read_text(encoding="ascii")
    assert tuple(map(int, re.search(r"\$MinMinor, \$MaxMinor = (\d+), (\d+)", ps1).groups())) == (low, high - 1)
    release_minor = ".".join((ROOT / "packaging" / ".python-version").read_text(encoding="ascii").split(".")[:2])
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    jobs = dict(re.findall(r'- python: "(3\.\d+)"\s+requirements: (.+)', ci))
    assert jobs[release_minor] == "-r packaging/requirements-lock.txt"
    assert f"3.{low}" in jobs and jobs[f"3.{low}"] != jobs[release_minor]


def test_check_tag():
    assert release.check_tag(f"v{__version__}") == __version__
    for bad in (__version__, f"v{__version__}.1", "v0.0.0-test"):
        with pytest.raises(SystemExit):
            release.check_tag(bad)


CHANGELOG = """# Changelog

## [Unreleased]

- Next thing.

## [1.1.0] - 2027-01-02

### Fixed

- A bug.

## [1.0.0] - 2026-12-01

- First.

[Unreleased]: https://example.invalid/compare/v1.1.0...HEAD
[1.1.0]: https://example.invalid/compare/v1.0.0...v1.1.0
"""


def test_changelog_section():
    assert release.changelog_section(CHANGELOG, "1.1.0") == "### Fixed\n\n- A bug."
    assert release.changelog_section(CHANGELOG, "1.0.0") == "- First."
    with pytest.raises(SystemExit):
        release.changelog_section(CHANGELOG, "1.0")  # no prefix matches
    with pytest.raises(SystemExit):
        release.changelog_section("## [2.0.0] - 2027-01-01\n\n## [1.0.0]\n- x\n", "2.0.0")  # empty


def test_changelog_has_the_current_version():
    # A version bump needs its changelog section: the release notes come from it.
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert release.changelog_section(text, __version__)


def test_notices_name_the_current_version():
    # The release build regenerates THIRD_PARTY_NOTICES.md and stops if it differs from the
    # committed copy, so a version bump must update its first line too.
    text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert f"myTTS {__version__} for Windows" in text


def test_sums_and_notes(tmp_path):
    a = tmp_path / f"myTTS-setup-{__version__}.exe"
    a.write_bytes(b"setup")
    b = tmp_path / "espeak-ng-1.52.0.tar.gz"
    b.write_bytes(b"")
    sums = release.write_sums([a, b], tmp_path / "SHA256SUMS.txt")
    lines = (tmp_path / "SHA256SUMS.txt").read_bytes().decode("ascii").splitlines()
    assert lines == [
        f"{sums[a.name]}  {a.name}",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  espeak-ng-1.52.0.tar.gz",
    ]
    notes = release.release_notes(__version__, "- Changes.", sums, ("1.52.0", "1.52.0", "4870adf"),
                                  ("3.6.0", "phonemizer-3.6.0.tar.gz"))
    assert notes.startswith("- Changes.\n")
    assert f"Get-FileHash .\\myTTS-setup-{__version__}.exe" in notes
    assert f"| `{a.name}` | `{sums[a.name]}` |" in notes
    assert "More info" in notes and "Run anyway" in notes
    assert f"`v{__version__}`" in notes and "phonemizer-3.6.0.tar.gz" in notes


def test_workflows_exist():
    assert {p.name for p in WORKFLOWS} == {"ci.yml", "release.yml"}


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_actions_are_pinned_to_commits(workflow):
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", workflow.read_text(encoding="utf-8"), re.M)
    assert uses
    for ref, comment in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), f"{ref} is not pinned to a commit SHA"
        assert re.fullmatch(r"\s*# v\d+(\.\d+)*", comment), f"{ref} needs a '# vX.Y.Z' comment"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_workflows_default_to_read_only(workflow):
    text = workflow.read_text(encoding="utf-8")
    assert re.search(r"^permissions:\n  contents: read$", text, re.M)
    assert text.count("contents: write") <= 1  # only the draft release job


def test_release_creates_a_draft_only():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    creates = re.findall(r"gh release create[^\n]*", text)
    assert creates and all("--draft" in c for c in creates)
    assert "gh release edit" not in text and "--draft=false" not in text
