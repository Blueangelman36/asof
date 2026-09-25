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

# The least slack an unchanged confirmation gets before it is re-stamped.
# Staleness thresholds are days or months; an hour is invisible to them.
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

    def recorded_files(self, name: str) -> list[str] | None:
        """Files that carried this claim when it was last recorded.

        Files, not line numbers: a line moves every time somebody edits above
        it, and a lockfile that churns is a lockfile people stop reading.
        None means the claim predates this record and nothing can be concluded.
        """
        files = self.entry(name).get("files")
        return list(files) if isinstance(files, list) else None

    def record(self, name: str, value: str, source: str, moment: datetime | None = None,
               force: bool = False, files: list[str] | None = None,
               every: float | None = None) -> None:
        """Note that a claim was confirmed, without rewriting the file to say so twice.

        The lockfile is meant to be committed, and a file that changes on every
        read is a file people stop reading. So a confirmation that changes
        nothing - same value, same source, same files - moves the clock only
        when the clock is about to matter: once the stamp is half way through
        the claim's shelf life (`every`). A claim with no shelf life can never
        go stale, so its stamp stays where the value was last established.

        `files` of None keeps whatever files were recorded before.
        """
        moment = moment or now()
        existing = self.entry(name)
        if files is None and isinstance(existing.get("files"), list):
            files = existing["files"]
        if not force:
            previous = from_iso(existing.get("checked", ""))
            unchanged = (existing.get("value") == value
                         and existing.get("source") == source
                         and existing.get("files") == (list(files) if files is not None else None))
            if unchanged and previous:
                age = (moment - previous).total_seconds()
                # A stamp from the future is a clock problem, and rewriting it is the fix.
                if 0 <= age and (every is None or age < max(GRANULARITY, every / 2)):
                    return

        entry = {"value": value, "checked": to_iso(moment), "source": source}
        if files is not None:
            entry["files"] = list(files)
        self.data["claims"][name] = entry
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
