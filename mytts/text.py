"""Text cleanup and sentence segmentation.

The reader window shows the *normalized* text and highlights one segment at a
time, so every Segment carries character offsets into that normalized string,
plus a separate `speech` string that is what actually gets synthesized.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_SEGMENT_CHARS = 220  # long sentences are split at clauses to keep latency low


@dataclass(frozen=True)
class Segment:
    start: int  # offset into the normalized text (inclusive)
    end: int  # offset into the normalized text (exclusive)
    speech: str  # cleaned text sent to the voice engine


_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"})
_SPACES = re.compile(r"[ \t  -   　]+")
_BULLET = re.compile(r"^(?:[-*+•◦▪‣·●○■□➤➢►>]+|#{1,6})\s+")
_TERMINAL = ".!?:;…"
_CLOSERS = "\"'”’»)]"

# A sentence ends at terminal punctuation (plus closing quotes/brackets) before whitespace.
_SENTENCE_END = re.compile(r"[.!?…。！？]+[\"'”’»)\]]*(?=\s|$)")
# Tokens that end in "." but rarely end a sentence.
_ABBREVIATIONS = frozenset(
    "mr mrs ms dr prof sr jr st mt vs no nos fig figs eq vol ch sec approx dept gen col lt "
    "sgt capt rev hon gov pres u.s u.k e.g i.e cf".split()
)
_CLAUSE_BREAK = re.compile(r"[,;:—–](?=\s)|\s[—–-]\s")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
_MARKDOWN = re.compile(r"\*\*|__|`+|~~")


def normalize(raw: str) -> str:
    """Clean pasted/selected text for display and reading.

    Removes invisible characters, collapses whitespace, and re-joins lines that
    were hard-wrapped (typical for PDFs and emails) while keeping real line
    breaks such as list items and headings.
    """
    text = unicodedata.normalize("NFC", raw).translate(_INVISIBLE).translate(_LIGATURES)
    for nl in ("\r\n", "\r", "\f", "\v", " ", " "):
        text = text.replace(nl, "\n")
    lines = [_SPACES.sub(" ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(_unwrap(lines))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _unwrap(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        prev = out[-1] if out else ""
        if prev and line and _is_soft_wrap(prev, line):
            if prev.endswith("-") and len(prev) > 1 and prev[-2].isalpha() and line[0].islower():
                out[-1] = prev[:-1] + line  # "exam-" + "ple" -> "example"
            else:
                out[-1] = f"{prev} {line}"
        else:
            out.append(line)
    return out


def _is_soft_wrap(prev: str, line: str) -> bool:
    if prev.rstrip(_CLOSERS)[-1:] in _TERMINAL or _BULLET.match(line):
        return False
    first = line[0]
    if first.islower():
        return True
    # A long line that stops mid-sentence was most likely wrapped by the source.
    return len(prev) >= 60 and (first.isalnum() or first in "\"'“‘(")


def segment(text: str, max_chars: int = MAX_SEGMENT_CHARS) -> list[Segment]:
    """Split normalized text into speakable segments (sentences, or clauses of long ones)."""
    segments: list[Segment] = []
    for line_match in re.finditer(r"[^\n]+", text):
        line, base = line_match.group(), line_match.start()
        start = 0
        for end in [*_sentence_ends(line), len(line)]:
            for a, b in _split_long(line, *_trim(line, start, end), max_chars):
                speech = speakable(line[a:b])
                if any(ch.isalnum() for ch in speech):
                    segments.append(Segment(base + a, base + b, speech))
            start = end
    return segments


def _sentence_ends(line: str) -> list[int]:
    ends = []
    for m in _SENTENCE_END.finditer(line):
        end = m.end()
        if end >= len(line):
            break
        if m.group().rstrip(_CLOSERS) == ".":
            token_match = re.search(r"(\S+)$", line[: m.start()])
            token = token_match.group(1).lstrip("\"'“‘«([") if token_match else ""
            if token.lower() in _ABBREVIATIONS:
                continue
            if len(token) == 1 and token.isupper():  # an initial: "J. K. Rowling"
                continue
            if token.isdigit() and token_match and token_match.start() == 0:  # "1. First item"
                continue
        following = line[end:].lstrip()[:1]
        if following.islower():  # "e.g. this", "“Really?” she asked"
            continue
        ends.append(end)
    return ends


def _trim(s: str, a: int, b: int) -> tuple[int, int]:
    while a < b and s[a].isspace():
        a += 1
    while b > a and s[b - 1].isspace():
        b -= 1
    return a, b


def _split_long(s: str, a: int, b: int, limit: int) -> list[tuple[int, int]]:
    spans = []
    while b - a > limit:
        window_start = a + int(limit * 0.3)
        window = s[window_start : a + limit]
        cut = -1
        for m in _CLAUSE_BREAK.finditer(window):
            cut = window_start + (m.end() if not m.group()[0].isspace() else m.start())
        if cut <= a:
            cut = s.rfind(" ", a, a + limit)
        if cut <= a:
            cut = a + limit  # one enormous "word"
        spans.append(_trim(s, a, cut))
        a, b = _trim(s, cut, b)
    if b > a:
        spans.append((a, b))
    return spans


def speakable(s: str) -> str:
    """Turn a display segment into text that reads well aloud."""
    s = _BULLET.sub("", s)
    s = _URL.sub(_say_url, s)
    s = _MARKDOWN.sub("", s)
    return _SPACES.sub(" ", s).strip()


def _say_url(m: re.Match) -> str:
    url = m.group()
    stripped = url.rstrip(".,;:!?)]'\"")
    host = re.sub(r"^(?:https?://)?(?:www\.)?", "", stripped, flags=re.IGNORECASE).split("/")[0]
    return f"link to {host}{url[len(stripped):]}"
