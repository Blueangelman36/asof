"""The ``asof.ini`` file: what each claim means and how to re-establish it."""

from __future__ import annotations

import configparser
import re
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAMES = ("asof.ini", ".asof.ini")

DURATION_RE = re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>[smhdwy])", re.IGNORECASE)
_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31557600}

DEFAULT_EXCLUDE = ["asof.lock", "asof.html", "*.min.js", "*.lock", "*.svg"]


class ConfigError(Exception):
    pass


def parse_duration(spec: str) -> float:
    """``30d`` -> seconds. Accepts compounds like ``1w 3d``."""
    spec = spec.strip()
    if not spec:
        raise ConfigError("empty duration")
    total = 0.0
    matched = 0
    for m in DURATION_RE.finditer(spec):
        total += float(m.group("n")) * _SECONDS[m.group("unit").lower()]
        matched += len(m.group(0))
    if matched < len(spec.replace(" ", "")):
        raise ConfigError(f"cannot read duration {spec!r} (use 30d, 12h, 1w, 1y)")
    return total


def format_duration(seconds: float) -> str:
    for unit, size in (("y", 31557600), ("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            n = seconds / size
            return f"{n:.0f}{unit}" if n >= 10 or n == int(n) else f"{n:.1f}{unit}"
    return f"{seconds:.0f}s"


@dataclass
class Claim:
    """The configured half of a claim - the marker in the document is the other."""

    name: str
    run: str = ""
    every: float | None = None
    tolerance: str = ""
    why: str = ""
    owner: str = ""
    cwd: str = ""
    timeout: float = 60.0

    @property
    def automatic(self) -> bool:
        return bool(self.run)


@dataclass
class Config:
    root: Path
    path: Path | None = None
    claims: dict[str, Claim] = field(default_factory=dict)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    default_every: float | None = None
    shell: str = ""
    fenced: bool = False

    def claim(self, name: str) -> Claim:
        """The configured claim, or a bare manual one for undeclared markers."""
        if name in self.claims:
            return self.claims[name]
        return Claim(name=name, every=self.default_every)


def find(root: Path) -> Path | None:
    for name in CONFIG_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def load(root: Path) -> Config:
    path = find(root)
    cfg = Config(root=root, path=path)
    if path is None:
        return cfg

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")

    if parser.has_section("asof"):
        section = parser["asof"]
        cfg.include = _list(section.get("include", ""))
        extra = _list(section.get("exclude", ""))
        cfg.exclude = list(DEFAULT_EXCLUDE) + extra
        cfg.shell = section.get("shell", "").strip()
        cfg.fenced = section.getboolean("fenced", fallback=False)
        if section.get("every", "").strip():
            cfg.default_every = parse_duration(section["every"])

    for name in parser.sections():
        if name == "asof":
            continue
        section = parser[name]
        every = section.get("every", "").strip()
        cfg.claims[name] = Claim(
            name=name,
            run=section.get("run", "").strip(),
            every=parse_duration(every) if every else cfg.default_every,
            tolerance=section.get("tolerance", "").strip(),
            why=" ".join(section.get("why", "").split()),
            owner=section.get("owner", "").strip(),
            cwd=section.get("cwd", "").strip(),
            timeout=float(section.get("timeout", "60")),
        )
    return cfg


def _list(raw: str) -> list[str]:
    parts: list[str] = []
    for chunk in raw.replace(",", "\n").splitlines():
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts
