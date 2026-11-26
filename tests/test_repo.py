"""The repository's own documents: local links and images resolve, and the community files exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ["README.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md",
        ".github/pull_request_template.md"]
COMMUNITY = DOCS + [".github/ISSUE_TEMPLATE/bug_report.yml", ".github/ISSUE_TEMPLATE/feature_request.yml",
                    ".github/ISSUE_TEMPLATE/config.yml", ".editorconfig", ".gitattributes", "LICENSE",
                    "THIRD_PARTY_NOTICES.md"]

LINK = re.compile(r"\]\(([^)\s]+)\)|<img [^>]*src=\"([^\"]+)\"")


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    s = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return s.replace(" ", "-")


def anchors(md: str) -> set[str]:
    return {slug(m) for m in re.findall(r"^#{1,6} (.+)$", md, re.MULTILINE)}


def local_links(md: str) -> list[str]:
    md = re.sub(r"```.*?```", "", md, flags=re.DOTALL)
    out = []
    for a, b in LINK.findall(md):
        target = a or b
        if not re.match(r"[a-z]+:", target):
            out.append(target)
    return out


@pytest.mark.parametrize("name", COMMUNITY)
def test_community_file_exists(name):
    assert (ROOT / name).is_file()


@pytest.mark.parametrize("name", DOCS)
def test_local_links_resolve(name):
    path = ROOT / name
    md = path.read_text(encoding="utf-8")
    for target in local_links(md):
        file, _, anchor = target.partition("#")
        dest = (path.parent / file).resolve() if file else path
        assert dest.exists(), f"{name}: {target} does not exist"
        if anchor and dest.suffix == ".md":
            assert anchor in anchors(dest.read_text(encoding="utf-8")), f"{name}: no heading for #{anchor}"


def test_readme_images_are_committed_files():
    md = (ROOT / "README.md").read_text(encoding="utf-8")
    images = [t for t in local_links(md) if t.endswith((".png", ".gif"))]
    assert {"docs/icon.png", "docs/demo.gif", "docs/settings.png"} <= set(images)


def test_media_is_binary_in_git():
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for ext in ("png", "gif", "mp4", "ico"):
        assert re.search(rf"^\*\.{ext} binary$", attrs, re.MULTILINE)


def test_issue_forms_have_the_required_keys():
    for name in ("bug_report.yml", "feature_request.yml"):
        text = (ROOT / ".github/ISSUE_TEMPLATE" / name).read_text(encoding="utf-8")
        for key in ("name:", "description:", "body:"):
            assert re.search(rf"^{key}", text, re.MULTILINE), f"{name} lacks {key}"
    bug = (ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml").read_text(encoding="utf-8")
    assert "mytts.log" in bug and "winver" in bug and "--version" in bug


def test_code_of_conduct_has_a_contact():
    text = (ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
    assert "[INSERT CONTACT METHOD]" not in text
    assert "Contributor Covenant" in text and "version 2.1" in text
