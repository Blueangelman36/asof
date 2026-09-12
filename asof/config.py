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
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as exc:
        raise ConfigError(_parser_problem(path, exc)) from None

    if parser.has_section("asof"):
        section = parser["asof"]
        cfg.include = _list(section.get("include", ""))
        extra = _list(section.get("exclude", ""))
        cfg.exclude = list(DEFAULT_EXCLUDE) + extra
        cfg.shell = section.get("shell", "").strip()
        cfg.fenced = _boolean(path, "asof", "fenced", section)
        if section.get("every", "").strip():
            cfg.default_every = _duration(path, "asof", "every", section["every"])

    for name in parser.sections():
        if name == "asof":
            continue
        section = parser[name]
        every = section.get("every", "").strip()
        cfg.claims[name] = Claim(
            name=name,
            run=section.get("run", "").strip(),
            every=_duration(path, name, "every", every) if every else cfg.default_every,
            tolerance=_tolerance(path, name, section.get("tolerance", "").strip()),
            why=" ".join(section.get("why", "").split()),
            owner=section.get("owner", "").strip(),
            cwd=section.get("cwd", "").strip(),
            timeout=_seconds(path, name, section.get("timeout", "60").strip()),
        )
    return cfg


def _parser_problem(path: Path, exc: configparser.Error) -> str:
    """Say where the config is wrong without quoting a Windows path object at anyone."""
    detail = " ".join(str(getattr(exc, "message", exc)).split())
    detail = detail.split(" file: ")[0].split(" While reading from ")[0].strip()
    lineno = getattr(exc, "lineno", None)
    if isinstance(exc, configparser.DuplicateSectionError):
        detail = f"section [{exc.section}] appears twice"
    elif isinstance(exc, configparser.DuplicateOptionError):
        detail = f"[{exc.section}] sets {exc.option} twice"
    where = f"{path.name} line {lineno}" if lineno else path.name
    return f"{where}: {detail or type(exc).__name__}"


def _where(path: Path, section: str, key: str) -> str:
    return f"{path.name} [{section}] {key}"


def _duration(path: Path, section: str, key: str, raw: str) -> float:
    try:
        return parse_duration(raw)
    except ConfigError as exc:
        raise ConfigError(f"{_where(path, section, key)}: {exc}") from None


def _tolerance(path: Path, section: str, raw: str) -> str:
    """Validate here so a typo is a message, not a traceback five frames later."""
    if not raw:
        return raw
    body = raw[:-1] if raw.endswith("%") else raw
    body = body.lstrip("+-±")
    try:
        float(body)
    except ValueError:
        raise ConfigError(
            f"{_where(path, section, 'tolerance')}: cannot read {raw!r} "
            "(use a number like 5, or a percentage like 10%)") from None
    return raw


def _seconds(path: Path, section: str, raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(
            f"{_where(path, section, 'timeout')}: cannot read {raw!r}, "
            "expected a number of seconds") from None
    if value <= 0:
        raise ConfigError(f"{_where(path, section, 'timeout')}: must be greater than zero")
    return value


def _boolean(path: Path, section: str, key: str, holder) -> bool:
    try:
        return holder.getboolean(key, fallback=False)
    except ValueError:
        raise ConfigError(
            f"{_where(path, section, key)}: expected yes or no") from None


def _list(raw: str) -> list[str]:
    parts: list[str] = []
    for chunk in raw.replace(",", "\n").splitlines():
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts
