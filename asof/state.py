"""``asof.lock`` - when each claim was last known to be true.

The lockfile is meant to be committed. That is the point: a number changing in
a document is one diff, and the moment someone stood behind it is another.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LOCK_NAME = "asof.lock"
VERSION = 1

# How stale a confirmation may be before re-stamping it is worth a file write.
# Staleness thresholds are days or months; an hour of slack is invisible to
# them and removes the churn entirely.
GRANULARITY = 3600


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def from_iso(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class State:
    def __init__(self, path: Path, data: dict | None = None):
        self.path = path
        self.data = data or {"version": VERSION, "claims": {}}
        self.dirty = False

    @classmethod
    def load(cls, root: Path) -> "State":
        path = root / LOCK_NAME
        if not path.is_file():
            return cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return cls(path)
        # A lockfile is generated, so a damaged one is not worth an error - but
        # it must not be trusted into a crash either. Anything not shaped like
        # a lockfile is treated as no lockfile, and the next check rebuilds it.
        if not isinstance(data, dict) or not isinstance(data.get("claims", {}), dict):
            return cls(path)
        data["claims"] = {
            name: entry for name, entry in data.get("claims", {}).items()
            if isinstance(entry, dict)
        }
        return cls(path, data)

    def entry(self, name: str) -> dict:
        return self.data["claims"].get(name, {})

    def checked_at(self, name: str) -> datetime | None:
        return from_iso(self.entry(name).get("checked", ""))

    def recorded_value(self, name: str) -> str | None:
        entry = self.entry(name)
        return entry.get("value") if "value" in entry else None

    def record(self, name: str, value: str, source: str, moment: datetime | None = None,
               force: bool = False) -> None:
        """Note that a claim was confirmed, without rewriting the file to say so twice.

        Staleness is measured in days, so re-stamping an unchanged claim every
        time anyone runs `asof check` buys nothing and costs a permanently
        dirty working tree - the lockfile is meant to be committed, and a file
        that changes on every read is a file people stop reading.
        """
        moment = moment or now()
        if not force:
            existing = self.entry(name)
            previous = from_iso(existing.get("checked", ""))
            unchanged = existing.get("value") == value and existing.get("source") == source
            if unchanged and previous and 0 <= (moment - previous).total_seconds() < GRANULARITY:
                return

        self.data["claims"][name] = {
            "value": value,
            "checked": to_iso(moment),
            "source": source,
        }
        self.dirty = True

    def forget(self, names) -> None:
        for name in list(names):
            if name in self.data["claims"]:
                del self.data["claims"][name]
                self.dirty = True

    def save(self) -> None:
        self.data["version"] = VERSION
        self.data["claims"] = dict(sorted(self.data["claims"].items()))
        self.path.write_text(
            json.dumps(self.data, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
        self.dirty = False
