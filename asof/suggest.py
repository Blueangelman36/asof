"""Finding the numbers in a project that are worth claiming.

Adopting asof on an existing repo means answering "which numbers here are
actually claims?", and grepping for digits answers it badly: most numbers in a
document are list markers, version strings, ports inside example URLs, or the
`2` in "two ways to do this".

The signal that works is repetition. A number written in a README *and* in a
config file is a constant stated twice by two people who will not both remember
to change it. That is exactly the shape of claim asof is for, and it needs no
language model to spot - only a count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import scan, values

# Where prose lives. Numbers here are candidates; numbers anywhere else in the
# tree are corroboration for them.
DOCUMENTS = {".md", ".markdown", ".mdx", ".rst", ".txt", ".html", ".htm", ".adoc"}

COMMENT_STYLE = {
    "<!-- asof:{name} -->": {".md", ".markdown", ".mdx", ".html", ".htm", ".xml", ".svg"},
    "// asof:{name}": {".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".c", ".h",
                       ".cpp", ".java", ".kt", ".swift", ".scala", ".css", ".scss"},
    ".. asof:{name}": {".rst"},
}
DEFAULT_COMMENT = "# asof:{name}"

# Words that tend to sit next to a number someone is asserting, rather than a
# number that is just passing through.
CLAIM_WORDS = re.compile(
    r"\b(support|supports|supported|handle|handles|serve|serves|up to|at least|"
    r"at most|default|defaults|maximum|minimum|max|min|limit|limited|restricted|"
    r"cap|capped|currently|today|about|roughly|around|approximately|per|"
    r"we have|there are|costs?|takes?|requires?|runs? on|ships? with|"
    r"customers|users|integrations|seats|tenants|regions|languages)\b",
    re.IGNORECASE,
)

ORDERED_LIST_RE = re.compile(r"^\s*\d+[.)]\s")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
SLUG_WORDS_RE = re.compile(r"[A-Za-z][A-Za-z-]*")

# Words that name nothing. A claim called "the" or "because" is worse than one
# left as NAME, because it looks like it was chosen.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "been", "but", "by",
    "can", "do", "does", "for", "from", "has", "have", "if", "in", "into", "is",
    "it", "its", "of", "on", "or", "so", "than", "that", "the", "then", "there",
    "these", "they", "this", "to", "up", "was", "were", "when", "which", "will",
    "with", "you", "your", "we", "our", "all", "any", "more", "most", "not",
    "over", "under", "out", "off", "each", "just", "only", "still", "about",
}
CLOSING_PUNCTUATION = set(").,;:!?]}>\"'/*-–—")

MAX_ECHO_SCORE = 10
# Above this many files, a value is a constant of the language rather than a
# claim. 50 and 100 and 24 are everywhere; 8420 and 2,500 are somebody's decision.
COMMON_ENOUGH_TO_IGNORE = 5


@dataclass
class Candidate:
    """One unclaimed number, and the case for claiming it."""

    token: str
    value: values.Value
    path: Path
    line_no: int
    line: str
    start: int
    end: int
    echoes: list[str] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)   # other places the same value is written
    reasons: list[str] = field(default_factory=list)
    score: int = 0

    @property
    def where(self) -> str:
        return f"{self.path.as_posix()}:{self.line_no}"

    @property
    def marker(self) -> str:
        """A ready-to-paste marker in this file's comment syntax."""
        for template, suffixes in COMMENT_STYLE.items():
            if self.path.suffix.lower() in suffixes:
                return template.format(name=self.suggested_name)
        return DEFAULT_COMMENT.format(name=self.suggested_name)

    @property
    def suggested_name(self) -> str:
        return _name_from_context(self.line, self.start, self.end)

    @property
    def context(self) -> str:
        return " ".join(self.line.split())


def _useful_words(words: list[str]) -> list[str]:
    return [w for w in (x.lower().strip("-") for x in words) if w and w not in STOPWORDS]


def _name_from_context(line: str, start: int, end: int) -> str:
    """Guess a claim name from the words either side of the number.

    A number at the end of a phrase - ``(default 2.5 kHz)`` - is described by
    what comes before it, not after, so the punctuation immediately following
    decides which way to look. When neither side offers a real word, say NAME
    and let the person naming the claim do it.
    """
    tail = line[end:end + 48].lstrip()
    closed = bool(tail) and tail[0] in CLOSING_PUNCTUATION

    after = _useful_words(SLUG_WORDS_RE.findall(line[end:end + 48]))
    before = _useful_words(SLUG_WORDS_RE.findall(line[max(0, start - 48):start]))
    words = (before[-2:] or after[:2]) if closed else (after[:2] or before[-2:])

    slug = "-".join(w for w in words if len(w) > 1)
    return slug or "NAME"


def _inside_dotted_run(line: str, start: int, end: int) -> bool:
    """Is this number a piece of something like 127.0.0.1 or 1.2.3?

    A dotted run is one identifier, not a sequence of claims. Without this,
    every IP address in a document suggests two numbers, neither of which
    anybody would ever want to track.
    """
    if start >= 2 and line[start - 1] == "." and line[start - 2].isdigit():
        return True
    return end + 1 < len(line) and line[end] == "." and line[end + 1].isdigit()


HTML = {".html", ".htm"}
HTML_CODE_RE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)

# Units that measure a layout, never a claim about the world. A stylesheet is
# wall-to-wall numbers and not one of them is a promise to anybody.
LAYOUT_UNITS = {"px", "pt", "em", "rem", "vh", "vw", "ch", "ex", "fr", "deg"}


def _mask_html_code(text: str) -> str:
    """Blank out <script> and <style> bodies, keeping every line and column.

    A single-file web app is mostly stylesheet, so mining it for claims returns
    padding values. This applies to *discovery* only - a marker somebody put
    inside a script on purpose is still a marker, because they meant it.
    """
    return HTML_CODE_RE.sub(
        lambda m: "".join(c if c == "\n" else " " for c in m.group(0)), text)


def _numbers_in(text: str, path: Path, fenced: bool):
    """Yield (line_no, line, token, start, end) for every value in a file.

    Masking preserves column positions, so a span found in the searchable copy
    of a line addresses the same characters in the real one.
    """
    raw = text.splitlines()
    if path.suffix.lower() in HTML:
        text = _mask_html_code(text)
    for line_no, _, searchable in scan.readable(text, path, fenced):
        line = raw[line_no - 1]          # quote the real line, search the masked one
        for token, start, end in values.iter_values(searchable):
            if _inside_dotted_run(line, start, end):
                continue
            if values.parse(line[start:end]).unit in LAYOUT_UNITS:
                continue
            yield line_no, line, line[start:end], start, end


def _read(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _distinctive(value: values.Value) -> bool:
    """Is this number specific enough that two files sharing it means something?

    Repetition is the whole signal, and small round numbers ruin it: 50 and 100
    and 24 appear in every stylesheet in the world. A number with a fractional
    part, a thousands separator, or four digits was chosen by somebody.
    """
    scaled = abs(value.scaled or 0)
    return value.decimals > 0 or value.grouped or scaled >= 1000


def collect(root: Path, cfg, claimed_spans: set[tuple[str, int, int]]) -> list[Candidate]:
    """Find unclaimed numbers in documents, and score them by how claim-like they are."""
    candidates: list[Candidate] = []
    seen: dict[float, list[tuple[str, str]]] = {}   # scaled value -> [(file, where)]

    for path in scan.walk(root, cfg.include, cfg.exclude):
        text = _read(path)
        if text is None or scan.OFF_RE.search(text):
            continue
        rel = path.relative_to(root)
        document = rel.suffix.lower() in DOCUMENTS
        for line_no, line, token, start, end in _numbers_in(text, rel, cfg.fenced):
            value = values.parse(token)
            if value.scaled is None:
                continue
            seen.setdefault(value.scaled, []).append(
                (rel.as_posix(), f"{rel.as_posix()}:{line_no}"))
            if not document or (rel.as_posix(), line_no, start) in claimed_spans:
                continue
            candidates.append(Candidate(token, value, rel, line_no, line, start, end))

    for candidate in candidates:
        _score(candidate, seen)
    return _group([c for c in candidates if c.score > 0])


def _group(candidates: list[Candidate]) -> list[Candidate]:
    """One row per value, not one per sighting.

    A README that says "24h" in three paragraphs has one number in it, and
    three identical suggestions would just be three chances to lose patience.
    """
    best: dict[tuple, Candidate] = {}
    for c in sorted(candidates, key=lambda c: (-c.score, c.path.as_posix(), c.line_no)):
        key = (c.value.scaled, c.value.unit)
        if key in best:
            best[key].sites.append(c.where)
        else:
            best[key] = c
    return sorted(best.values(), key=lambda c: (-c.score, c.path.as_posix(), c.line_no))


def _score(c: Candidate, seen: dict[float, list[tuple[str, str]]]) -> None:
    here = c.where
    others = [w for _, w in seen.get(c.value.scaled or 0, []) if w != here]
    files = {w.rsplit(":", 1)[0] for w in others} - {c.path.as_posix()}
    c.echoes = sorted(dict.fromkeys(others))[:4]

    if files and _distinctive(c.value) and len(files) <= COMMON_ENOUGH_TO_IGNORE:
        c.score += min(MAX_ECHO_SCORE, 5 * len(files))
        c.reasons.append(f"written in {len(files)} other file(s) too, so two places must agree")
    elif files and not _distinctive(c.value):
        c.reasons.append("appears elsewhere, but it is a round number, so that means little")
    elif files:
        c.reasons.append(f"appears in {len(files)} files, which makes it a constant, not a claim")
    elif others:
        c.score += 1
        c.reasons.append("written more than once in this file")

    if c.value.unit:
        c.score += 3
        c.reasons.append(f"carries a unit ({c.value.unit})")
    if c.value.grouped:
        c.score += 2
        c.reasons.append("written with thousands separators, so somebody counted")
    if CLAIM_WORDS.search(c.line):
        c.score += 2
        c.reasons.append("sits in a sentence that asserts something")
    if (c.value.scaled or 0) >= 10:
        c.score += 1

    if ORDERED_LIST_RE.match(c.line) and c.start < 6:
        c.score -= 4
        c.reasons.append("looks like a numbered list item")
    if HEADING_RE.match(c.line):
        c.score -= 1
    if abs(c.value.scaled or 0) < 10 and not c.value.unit and not files:
        c.score -= 2
    if 1900 <= (c.value.scaled or 0) <= 2100 and not c.value.unit and not files:
        c.score -= 2
        c.reasons.append("might just be a year")
