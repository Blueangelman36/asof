"""Parsing, comparing and re-formatting the values that claims are made of.

A value is whatever a human typed into a document: ``47``, ``1,247``, ``10.4k``,
``99.9%``, ``250ms``, ``1.2GB``, ``"blue"``, ``2026-09-11``. The job of this
module is to recognise those, compare one against another with a tolerance, and
- crucially - write a *new* number back in the *old* number's style, so that
updating a document does not also reformat it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Multiplier suffixes. Case matters: ``M`` is mega, ``m`` is not milli (it is
# almost always the start of a unit like ``ms``), so lowercase is left alone.
MULTIPLIERS = {"k": 1e3, "K": 1e3, "M": 1e6, "B": 1e9, "G": 1e9, "T": 1e12}

# Units that may legitimately follow a multiplier, so that ``1.2GB`` parses as
# 1.2 giga + bytes rather than as the unit "GB".
COMPOUND_UNITS = {
    "b", "B", "bps", "Bps", "B/s", "b/s", "iB", "iB/s",
    "Hz", "hz", "W", "J", "wh", "Wh", "eV", "m", "g", "s",
}

_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_SUFFIX = r"(?:%|[A-Za-zµ][A-Za-zµ/]*)?"

NUMBER_RE = re.compile(rf"(?P<num>{_NUMBER})(?P<suffix>{_SUFFIX})")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
QUOTED_RE = re.compile(r"""(?P<q>["'])(?P<body>(?:(?!(?P=q)).)*)(?P=q)""")

# Anything that can sit in a document and be claimed, in priority order.
_TOKEN_RE = re.compile(
    rf"""(?P<quoted>{QUOTED_RE.pattern})
       | (?P<date>{DATE_RE.pattern})
       | (?P<number>{NUMBER_RE.pattern})""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class Value:
    """A value as it appeared, plus enough structure to compare and re-render."""

    raw: str
    number: float | None = None
    multiplier: str = ""       # "k", "M", ... as written, "" if none
    unit: str = ""             # "ms", "B", "%", ... "" if none
    grouped: bool = False      # were thousands separated by commas?
    decimals: int = 0          # how many digits after the point
    space: str = ""            # whitespace between number and suffix

    @property
    def numeric(self) -> bool:
        return self.number is not None

    @property
    def scaled(self) -> float | None:
        """The value in base units, with any multiplier applied."""
        if self.number is None:
            return None
        return self.number * MULTIPLIERS.get(self.multiplier, 1.0)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.raw


def _split_suffix(suffix: str) -> tuple[str, str]:
    """Split a trailing run like ``GB`` into (multiplier, unit)."""
    if not suffix or suffix == "%":
        return "", suffix
    head, rest = suffix[0], suffix[1:]
    if head in MULTIPLIERS and (not rest or rest in COMPOUND_UNITS):
        return head, rest
    return "", suffix


def parse(text: str) -> Value:
    """Parse a single value token. Non-numeric text becomes an opaque Value."""
    text = text.strip()
    quoted = QUOTED_RE.fullmatch(text)
    if quoted:
        return Value(raw=text)

    m = re.fullmatch(rf"(?P<num>{_NUMBER})(?P<space>\s*)(?P<suffix>{_SUFFIX})", text)
    if not m:
        return Value(raw=text)

    digits = m.group("num")
    multiplier, unit = _split_suffix(m.group("suffix") or "")
    body = digits.replace(",", "")
    decimals = len(body.split(".")[1]) if "." in body else 0
    return Value(
        raw=text,
        number=float(body),
        multiplier=multiplier,
        unit=unit,
        grouped="," in digits,
        decimals=decimals,
        space=m.group("space") or "",
    )


def _claimable(m) -> bool:
    """An empty quoted string is punctuation, not a claim."""
    return bool(m.group(0).strip("\"'").strip())


def find_last(text: str) -> tuple[str, int, int] | None:
    """Find the last claimable token in ``text``. Returns (token, start, end)."""
    last = None
    for m in _TOKEN_RE.finditer(text):
        if _claimable(m):
            last = m
    if last is None:
        return None
    return last.group(0), last.start(), last.end()


def find_first(text: str) -> tuple[str, int, int] | None:
    """Find the first claimable token in ``text``. Returns (token, start, end)."""
    for m in _TOKEN_RE.finditer(text):
        if _claimable(m):
            return m.group(0), m.start(), m.end()
    return None


def _group(digits: str) -> str:
    neg = digits.startswith("-")
    digits = digits.lstrip("+-")
    whole, _, frac = digits.partition(".")
    out = f"{int(whole):,}"
    if frac:
        out = f"{out}.{frac}"
    return ("-" if neg else "") + out


def render_like(number: float, template: Value) -> str:
    """Render ``number`` (in base units) in the style of ``template``."""
    scale = MULTIPLIERS.get(template.multiplier, 1.0)
    shown = number / scale
    digits = f"{shown:.{template.decimals}f}"
    if template.grouped:
        digits = _group(digits)
    return f"{digits}{template.space}{template.multiplier}{template.unit}"


class Tolerance:
    """How far a value may drift before anyone should care."""

    def __init__(self, spec: str | None):
        self.spec = (spec or "").strip()
        self.relative = self.spec.endswith("%")
        body = self.spec[:-1] if self.relative else self.spec
        body = body.lstrip("+-\u00b1")
        self.amount = float(body) if body else 0.0

    def allows(self, expected: float, actual: float) -> bool:
        if self.amount == 0:
            return expected == actual
        limit = abs(expected) * self.amount / 100 if self.relative else self.amount
        return abs(expected - actual) <= limit

    def __bool__(self) -> bool:
        return self.amount != 0


def compare(document: Value, produced: Value, tolerance: Tolerance) -> bool:
    """Is the value in the document still an honest report of ``produced``?"""
    if document.numeric and produced.numeric:
        expected, actual = document.scaled, produced.scaled
        assert expected is not None and actual is not None
        if document.unit and produced.unit and document.unit != produced.unit:
            return False
        return tolerance.allows(expected, actual)
    return _loose(document.raw) == _loose(produced.raw)


def _loose(text: str) -> str:
    return text.strip().strip("\"'").casefold()
