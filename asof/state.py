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
        except (OSError, json.JSONDecodeError):
            return cls(path)
        data.setdefault("claims", {})
        return cls(path, data)

    def entry(self, name: str) -> dict:
        return self.data["claims"].get(name, {})

    def checked_at(self, name: str) -> datetime | None:
        return from_iso(self.entry(name).get("checked", ""))

    def recorded_value(self, name: str) -> str | None:
        entry = self.entry(name)
        return entry.get("value") if "value" in entry else None

    def record(self, name: str, value: str, source: str, moment: datetime | None = None) -> None:
        self.data["claims"][name] = {
            "value": value,
            "checked": to_iso(moment or now()),
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
