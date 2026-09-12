"""Finding claim markers in ordinary text files.

A marker is the literal ``asof:NAME``, written inside whatever passes for a
comment in the file it lives in. It binds the last value token *before* it on
the same line::

    We support 47 integrations.        <!-- asof:integrations -->
    TIMEOUT_MS = 250                   # asof:p99-latency
    replicas: 12                       # asof:prod-replicas

Write ``asof:NAME>`` instead to bind the first value *after* the marker, for
files where the comment has to come first.
"""

from __future__ import annotations

import fnmatch
import re
import os
from dataclasses import dataclass
from pathlib import Path

from . import values

MARKER = re.compile(
    r"asof\s*:\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._/-]*?)(?P<forward>>)?(?![A-Za-z0-9._/-])"
)

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".tox", ".idea", ".next", "target", "vendor", ".gradle",
}

MAX_BYTES = 2 * 1024 * 1024


@dataclass
class Marker:
    """One ``asof:NAME`` found in a file, with the value it lays claim to."""

    name: str
    path: Path
    line_no: int          # 1-based
    line: str
    start: int            # column span of the value within the line
    end: int
    forward: bool = False

    @property
    def token(self) -> str:
        return self.line[self.start:self.end]

    @property
    def value(self) -> values.Value:
        return values.parse(self.token)

    @property
    def where(self) -> str:
        return f"{self.path.as_posix()}:{self.line_no}"


def _is_probably_text(data: bytes) -> bool:
    return b"\x00" not in data


def walk(root: Path, include: list[str], exclude: list[str]):
    """Yield candidate files under ``root``, honouring include/exclude globs."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git"))
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if include and not any(fnmatch.fnmatch(rel, p) for p in include):
                continue
            if any(fnmatch.fnmatch(rel, p) for p in exclude):
                continue
            try:
                if full.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield full


OFF_RE = re.compile(r"asof\s*:\s*off(?![A-Za-z0-9._/-])")
FENCE_RE = re.compile(r"^\s{0,3}(```+|~~~+)")
# An inline code span may wrap across a line break, but never across a blank
# line. Getting that wrong invents claims out of a document's own examples.
INLINE_CODE_RE = re.compile(r"(?P<ticks>`+)[^\n]*?(?:\n(?!\s*\n)[^\n]*?)*?(?P=ticks)")
MARKDOWN = {".md", ".markdown", ".mdx"}


def _mask_inline_code(text: str) -> str:
    """Blank out `code spans`, preserving every line and column position."""
    return INLINE_CODE_RE.sub(
        lambda m: "".join(c if c == "\n" else " " for c in m.group(0)), text
    )


def readable(text: str, path: Path, fenced: bool):
    """Yield (line_no, line, searchable) for the parts of a file that speak.

    In Markdown, fenced blocks and inline code spans are showing syntax rather
    than making claims - a document that explains asof is full of example
    markers, and none of them are claims about that document. Only the search
    for markers is masked; the value a marker binds is read from the real line,
    so `47` in backticks is still a perfectly good number.
    """
    lines = text.splitlines()
    if path.suffix.lower() not in MARKDOWN or fenced:
        yield from ((n, line, line) for n, line in enumerate(lines, start=1))
        return

    # Drop fenced blocks first, then mask code spans across what is left, so a
    # span that wraps onto the next line is still masked as one span.
    kept: list[tuple[int, str]] = []
    in_fence = ""
    for line_no, line in enumerate(lines, start=1):
        fence = FENCE_RE.match(line)
        if fence and (not in_fence or line.strip().startswith(in_fence)):
            in_fence = "" if in_fence else fence.group(1)[0] * 3
            continue
        if not in_fence:
            kept.append((line_no, line))

    masked = _mask_inline_code("\n".join(line for _, line in kept)).split("\n")
    for (line_no, line), searchable in zip(kept, masked):
        yield line_no, line, searchable


def scan_text(text: str, path: Path, fenced: bool = False) -> list[Marker]:
    """Find every marker in ``text`` that successfully binds a value.

    A file that says ``asof:off`` where it would be heard is skipped entirely.
    """
    speaking = list(readable(text, path, fenced))
    if any(OFF_RE.search(searchable) for _, _, searchable in speaking):
        return []
    found: list[Marker] = []
    for line_no, line, searchable in speaking:
        for m in MARKER.finditer(searchable):
            forward = bool(m.group("forward"))
            if forward:
                tail = line[m.end():]
                hit = values.find_first(tail)
                offset = m.end()
            else:
                head = line[: m.start()]
                hit = values.find_last(head)
                offset = 0
            if hit is None:
                continue
            _, start, end = hit
            found.append(
                Marker(
                    name=m.group("name"),
                    path=path,
                    line_no=line_no,
                    line=line,
                    start=offset + start,
                    end=offset + end,
                    forward=forward,
                )
            )
    return found


def scan_tree(root: Path, include: list[str], exclude: list[str],
               fenced: bool = False) -> list[Marker]:
    """Scan a whole directory tree for markers."""
    markers: list[Marker] = []
    for path in walk(root, include, exclude):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not _is_probably_text(data[:4096]):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "asof" not in text:
            continue
        markers.extend(scan_text(text, path.relative_to(root), fenced))
    return markers


def rewrite(root: Path, marker: Marker, new_token: str) -> None:
    """Replace the value a marker points at, touching nothing else in the file.

    Nothing else means nothing else: every other byte in the file survives,
    including each line's own ending, trailing whitespace, and the presence or
    absence of a final newline. Reading with ``newline=""`` is what makes that
    true - the default translates CRLF to LF on the way in, which would turn a
    one-number change into a whole-file diff on Windows.
    """
    path = root / marker.path
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().splitlines(keepends=True)

    index = marker.line_no - 1
    body = lines[index]
    text = body.rstrip("\r\n")
    ending = body[len(text):]
    if text[marker.start:marker.end] != marker.token:
        raise ValueError(f"{marker.where}: file changed under us, not rewriting")

    lines[index] = text[: marker.start] + new_token + text[marker.end:] + ending
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(lines))
