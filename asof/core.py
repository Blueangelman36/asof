"""Checking claims, and putting them right again.

One *claim* is one name. It may be marked in several places - the same number
often appears in a README, a landing page and a pitch deck - so the unit of work
here is the group of markers that share a name.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from . import config, scan, state, values


class Status(str, Enum):
    OK = "ok"                      # the document is telling the truth
    DRIFT = "drift"                # the command disagrees with the document
    STALE = "stale"                # nobody has stood behind this in too long
    INCONSISTENT = "inconsistent"  # the same claim, two different numbers
    ERROR = "error"                # the command would not run
    ORPHAN = "orphan"              # configured, but no marker anywhere
    SKIPPED = "skipped"            # not re-run this time (--no-run)
    NEW = "new"                    # first sighting, now recorded


FAILING = {Status.DRIFT, Status.STALE, Status.INCONSISTENT, Status.ERROR, Status.ORPHAN}

SYMBOLS = {
    Status.OK: "ok",
    Status.DRIFT: "DRIFT",
    Status.STALE: "STALE",
    Status.INCONSISTENT: "SPLIT",
    Status.ERROR: "ERROR",
    Status.ORPHAN: "ORPHAN",
    Status.SKIPPED: "--",
    Status.NEW: "new",
}


@dataclass
class Result:
    name: str
    claim: config.Claim
    status: Status
    markers: list[scan.Marker] = field(default_factory=list)
    document: str = ""
    produced: str | None = None
    message: str = ""
    checked: datetime | None = None
    age: float | None = None
    suggestion: str | None = None

    @property
    def where(self) -> str:
        if not self.markers:
            return "-"
        first = self.markers[0].where
        extra = len(self.markers) - 1
        return f"{first} (+{extra})" if extra else first


def run_command(claim: config.Claim, root: Path, shell: str = "") -> tuple[bool, str, str]:
    """Run a claim's command. Returns (ok, output, error)."""
    cwd = root / claim.cwd if claim.cwd else root
    kwargs: dict = {}
    if shell:
        kwargs["executable"] = shell
    try:
        proc = subprocess.run(
            claim.run,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=claim.timeout,
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"timed out after {claim.timeout:g}s"
    except OSError as exc:
        return False, "", str(exc)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else "no output"
        return False, "", f"exit {proc.returncode}: {tail}"
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        return False, "", "command produced no output"
    return True, lines[-1], ""


def group_markers(markers: list[scan.Marker]) -> dict[str, list[scan.Marker]]:
    grouped: dict[str, list[scan.Marker]] = {}
    for marker in markers:
        grouped.setdefault(marker.name, []).append(marker)
    return grouped


def check(
    root: Path,
    cfg: config.Config,
    st: state.State,
    *,
    run: bool = True,
    only: list[str] | None = None,
    record: bool = True,
    now: datetime | None = None,
) -> list[Result]:
    """Evaluate every claim in the tree."""
    moment = now or state.now()
    markers = scan.scan_tree(root, cfg.include, cfg.exclude, cfg.fenced)
    grouped = group_markers(markers)

    names = sorted(set(grouped) | set(cfg.claims))
    if only:
        wanted = set(only)
        names = [n for n in names if n in wanted]

    return [
        _check_one(root, cfg, st, name, grouped.get(name, []), run, record, moment)
        for name in names
    ]


def _check_one(root, cfg, st, name, markers, run, record, moment) -> Result:
    claim = cfg.claim(name)
    checked = st.checked_at(name)
    age = (moment - checked).total_seconds() if checked else None

    if not markers:
        return Result(name, claim, Status.ORPHAN, [],
                      message="configured but never marked", checked=checked, age=age)

    tolerance = values.Tolerance(claim.tolerance)
    first = markers[0].value
    for other in markers[1:]:
        if not values.compare(first, other.value, tolerance):
            spread = ", ".join(f"{m.token} at {m.where}" for m in markers)
            return Result(name, claim, Status.INCONSISTENT, markers, document=first.raw,
                          message=f"one claim, several numbers: {spread}",
                          checked=checked, age=age)

    document = first.raw

    if claim.automatic and run:
        ok, output, error = run_command(claim, root, cfg.shell)
        if not ok:
            return Result(name, claim, Status.ERROR, markers, document=document,
                          message=error, checked=checked, age=age)
        produced = values.parse(output)
        if values.compare(first, produced, tolerance):
            if record:
                st.record(name, document, "run", moment)
            return Result(name, claim, Status.OK, markers, document=document,
                          produced=produced.raw, checked=moment, age=0.0)
        return Result(name, claim, Status.DRIFT, markers, document=document,
                      produced=produced.raw, checked=checked, age=age,
                      suggestion=_suggest(first, produced),
                      message=f"document says {document}, command says {produced.raw}")

    if claim.automatic and not run:
        status = Status.STALE if _too_old(claim, age) else Status.SKIPPED
        return Result(name, claim, status, markers, document=document,
                      checked=checked, age=age,
                      message="not re-run" if status is Status.SKIPPED else _aged(claim, age))

    # Manual claim: the document is the only source, so an edit counts as a check.
    # Only an actual write to the lockfile may reset the clock - a read-only pass
    # must not report a claim as freshly verified when nothing was recorded.
    recorded = st.recorded_value(name)
    if recorded is None:
        if not record:
            return Result(name, claim, Status.NEW, markers, document=document,
                          message="never recorded")
        st.record(name, document, "manual", moment)
        return Result(name, claim, Status.NEW, markers, document=document,
                      checked=moment, age=0.0, message="first sighting, recorded")
    if recorded != document:
        if not record:
            return Result(name, claim, Status.OK, markers, document=document,
                          checked=checked, age=age,
                          message=f"changed by hand, {recorded} -> {document}, not yet recorded")
        st.record(name, document, "manual", moment)
        return Result(name, claim, Status.OK, markers, document=document,
                      checked=moment, age=0.0,
                      message=f"changed by hand, {recorded} -> {document}")
    if _too_old(claim, age):
        return Result(name, claim, Status.STALE, markers, document=document,
                      checked=checked, age=age, message=_aged(claim, age))
    return Result(name, claim, Status.OK, markers, document=document, checked=checked, age=age)


def _too_old(claim: config.Claim, age: float | None) -> bool:
    return claim.every is not None and age is not None and age > claim.every


def _aged(claim: config.Claim, age: float | None) -> str:
    every = config.format_duration(claim.every) if claim.every else "?"
    seen = config.format_duration(age) if age else "?"
    return f"last verified {seen} ago, wanted every {every}"


def _suggest(document: values.Value, produced: values.Value) -> str:
    """What the document should say, written in the style it already uses."""
    if document.numeric and produced.numeric and produced.scaled is not None:
        if not document.unit or document.unit == produced.unit:
            return values.render_like(produced.scaled, document)
    return produced.raw


def update(root: Path, results: list[Result], st: state.State,
           moment: datetime | None = None) -> list[Result]:
    """Rewrite drifting documents to match their commands."""
    moment = moment or state.now()
    changed = []
    for result in results:
        if result.status is not Status.DRIFT or not result.suggestion:
            continue
        for marker in result.markers:
            scan.rewrite(root, marker, result.suggestion)
        st.record(result.name, result.suggestion, "run", moment)
        result.document, result.status = result.suggestion, Status.OK
        changed.append(result)
    return changed


def touch(st: state.State, results: list[Result], names: list[str],
          moment: datetime | None = None) -> list[str]:
    """Record that a human has just re-verified these claims by hand."""
    moment = moment or state.now()
    by_name = {r.name: r for r in results}
    done = []
    for name in names:
        result = by_name.get(name)
        if result is None or not result.markers:
            continue
        st.record(name, result.document, "manual", moment)
        done.append(name)
    return done


def exit_code(results: list[Result], fail_on: set[Status]) -> int:
    if Status.ERROR in fail_on and any(r.status is Status.ERROR for r in results):
        return 2
    return 1 if any(r.status in fail_on for r in results) else 0
