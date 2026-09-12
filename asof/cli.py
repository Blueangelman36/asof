"""The ``asof`` command line."""

from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path

from . import __version__, config, core, report, scan, state, suggest
from .core import Status

# Orphan is in here on purpose. A claim whose marker has been deleted is a
# number nobody is watching any more, and a checker that stays green when its
# markers disappear fails open - the one thing a guard must never do.
DEFAULT_FAIL_ON = "drift,inconsistent,error,orphan"

SCAFFOLD = """; asof.ini - what each number in your documents is a claim about.
;
; Every section is one claim. The name matches an `asof:NAME` marker in a file.
;
;   run        a shell command whose last line of output is the true value
;   every      how often the claim must be re-verified (30d, 12h, 1y)
;   tolerance  how far it may drift before anyone cares (5, 10%)
;   why        a sentence for whoever reads this in a year
;   owner      who to ask

[asof]
; every = 90d
; exclude = CHANGELOG.md

"""

# Coding agents read the repository's instruction file and little else, so the
# way to be used by one is to be written down there - in behavioural terms, at
# the moment it matters, not as a description of what the tool is.
#
# The last rule is the load-bearing one. An agent told to make CI green can
# always do that by deleting the marker, and will, unless told plainly not to.
AGENTS_BLOCK = """## Checked numbers (`asof`)

Some numbers in this repository's documents carry a trailing comment like
`<!-- asof:dashboard-port -->` (or `# asof:dashboard-port` in config and code).
Those numbers are claims that CI verifies against wherever the value really
comes from, so they cannot quietly stop being true. `asof.ini` records what each
one means and who or what settles it.

What this asks of you:

- **Changing a marked number is expected.** Keep the `asof:` comment on its line.
- **Before changing a constant in code, ask whether a document states it too.**
  Run `asof check`. If a README and a config file both name the same value, they
  are one claim, and changing one without the other fails the build.
- **Never delete an `asof:` comment to make a check pass.** That switches the
  check off rather than fixing anything; `asof check` reports it as an orphan
  and fails anyway.
- **`asof check --json`** gives machine-readable results. Every failure carries a
  `remedy` field with the next step.

If `asof` is not on PATH, look for a vendored `asof.pyz` at the repository root
and run `python asof.pyz check` - it is the whole tool in one file and needs no
install step, no virtualenv and no network.
"""

# An `asof:NAME` marker is invisible in a rendered document and cryptic in a
# raw one. Anyone who meets it for the first time while editing a sentence
# deserves a sentence back, in the repo, not in this tool's README.
NOTE_PROMPT = """
Markers are invisible once a document is rendered, so nobody meets one until
they are editing a line and wondering whether to delete it. Paste this into
your README or CONTRIBUTING so they don't have to guess:

---8<---
### The `asof:` comments

Some numbers in these docs carry a comment like `<!-- asof:dashboard-port -->`.
That number is checked in CI against wherever it really comes from, so it
cannot quietly stop being true. `asof.ini` says what each one means.

Editing the number is fine and expected - just keep the comment on the line.
Deleting the comment turns the check off, and CI will say so.
---8<---
"""


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root or _find_root()).resolve()

    if args.command == "init":
        return cmd_init(root, args)
    if args.command == "agents":
        print(AGENTS_BLOCK, end="")
        return 0
    if args.command == "skill":
        return cmd_skill(root, args)

    try:
        cfg = config.load(root)
    except config.ConfigError as exc:
        print(f"asof: {exc}", file=sys.stderr)
        return 2
    st = state.State.load(root)

    handlers = {
        "check": lambda: cmd_check(root, cfg, st, args),
        "update": lambda: cmd_update(root, cfg, st, args),
        "list": lambda: cmd_list(root, cfg, st, args),
        "touch": lambda: cmd_touch(root, cfg, st, args),
        "suggest": lambda: cmd_suggest(root, cfg, args),
        "report": lambda: cmd_report(root, cfg, st, args),
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 0
    try:
        return handler()
    except core.UnknownClaim as exc:
        print(f"asof: {exc}", file=sys.stderr)
        if exc.known:
            print(f"       known claims: {', '.join(exc.known)}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asof",
        description="Every number in your docs is a claim about a moment that has already passed.",
    )
    parser.add_argument("--version", action="version", version=f"asof {__version__}")
    parser.add_argument("-C", "--root", help="directory to work in (default: nearest repo root)")
    subs = parser.add_subparsers(dest="command")

    init = subs.add_parser("init", help="write a starter asof.ini from the markers found")
    init.add_argument("-f", "--force", action="store_true", help="overwrite an existing config")

    check = subs.add_parser("check", help="re-establish every claim, and report what has rotted")
    check.add_argument("only", nargs="*", help="claim names to check (default: all)")
    check.add_argument("--no-run", action="store_true",
                       help="do not execute commands, only judge by age")
    check.add_argument("--fail-on", default=DEFAULT_FAIL_ON,
                       help=f"statuses that make this exit non-zero (default: {DEFAULT_FAIL_ON}; "
                            "use 'none' for never)")
    check.add_argument("--json", action="store_true", help="machine-readable output")
    check.add_argument("-q", "--quiet", action="store_true", help="only show what is wrong")
    check.add_argument("--no-record", action="store_true",
                       help="do not write asof.lock")

    update = subs.add_parser("update", help="rewrite drifting numbers to match their commands")
    update.add_argument("only", nargs="*", help="claim names to update (default: all)")
    update.add_argument("-n", "--dry-run", action="store_true",
                        help="show the edits without making them")

    listing = subs.add_parser("list", help="show every claim, its value and its age")
    listing.add_argument("only", nargs="*")
    listing.add_argument("--json", action="store_true")

    touch = subs.add_parser("touch", help="record that you have re-verified a claim by hand")
    touch.add_argument("names", nargs="+")

    subs.add_parser(
        "agents",
        help="print instructions to paste into AGENTS.md or CLAUDE.md")

    skill = subs.add_parser(
        "skill", help="install the Claude Code skill into .claude/skills/asof")
    skill.add_argument("-f", "--force", action="store_true",
                       help="overwrite an existing skill file")
    skill.add_argument("--print", dest="show", action="store_true",
                       help="write it to stdout instead of a file")

    sug = subs.add_parser(
        "suggest", help="list numbers in your docs that look like unclaimed claims")
    sug.add_argument("-n", "--limit", type=int, default=15,
                     help="how many to show (default 15, 0 for all)")
    sug.add_argument("--why", action="store_true", help="show why each one was picked")
    sug.add_argument("--json", action="store_true")

    rep = subs.add_parser("report", help="write an HTML board of every claim by age")
    rep.add_argument("-o", "--output", default="asof.html")
    rep.add_argument("--no-run", action="store_true")
    rep.add_argument("--open", action="store_true", help="print the path to open")
    return parser


def _find_root() -> Path:
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if config.find(candidate) or (candidate / ".git").exists():
            return candidate
    return here


# --------------------------------------------------------------------------- init


def cmd_init(root: Path, args) -> int:
    path = root / "asof.ini"
    if path.exists() and not args.force:
        print(f"{path.name} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    markers = scan.scan_tree(root, [], config.DEFAULT_EXCLUDE)
    grouped = core.group_markers(markers)
    body = [SCAFFOLD]
    for name, group in sorted(grouped.items()):
        body.append(f"[{name}]\n")
        body.append(f"; {group[0].where} says {group[0].token}\n")
        body.append("; run =\n")
        body.append("every = 90d\n")
        body.append("why =\n\n")
    path.write_text("".join(body), encoding="utf-8")

    if grouped:
        print(f"wrote {path.name} with {len(grouped)} claim(s) found in your files:")
        for name, group in sorted(grouped.items()):
            print(f"  {name:<24} {group[0].token:<12} {group[0].where}")
        print("\nFill in a `run` command for the ones a machine can answer.")
        print(NOTE_PROMPT)
    else:
        print(f"wrote {path.name}. No markers yet - add one to a document:")
        print("\n    We support 47 integrations.   <!-- asof:integrations -->\n")
    return 0


def cmd_skill(root: Path, args) -> int:
    """Write the packaged skill into the repository Claude Code will read it from."""
    body = resources.files("asof").joinpath("skill.md").read_text(encoding="utf-8")
    if args.show:
        print(body, end="")
        return 0

    target = root / ".claude" / "skills" / "asof" / "SKILL.md"
    if target.exists() and not args.force:
        if target.read_text(encoding="utf-8") == body:
            print(f"{target.relative_to(root).as_posix()} is already up to date.")
            return 0
        print(f"{target.relative_to(root).as_posix()} exists and differs "
              "(use --force to overwrite)", file=sys.stderr)
        return 1

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    print(f"wrote {target.relative_to(root).as_posix()}")
    print("Claude Code will pick it up in this project from now on.")
    return 0


# -------------------------------------------------------------------------- check


def cmd_check(root: Path, cfg, st, args) -> int:
    fail_on = _parse_fail_on(args.fail_on)   # before any command runs
    results = core.check(root, cfg, st, run=not args.no_run, only=args.only,
                         record=not args.no_record)
    if st.dirty and not args.no_record:
        st.save()

    if args.json:
        print(json.dumps([_as_dict(r) for r in results], indent=2))
    else:
        _print_table(results, quiet=args.quiet)

    return core.exit_code(results, fail_on)


def _parse_fail_on(raw: str) -> set[Status]:
    raw = raw.strip().lower()
    if raw in ("", "none"):
        return set()
    if raw == "all":
        return set(core.FAILING)
    wanted = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            wanted.add(Status(part))
        except ValueError:
            print(f"unknown status {part!r} in --fail-on", file=sys.stderr)
            raise SystemExit(2)
    return wanted


def _print_table(results: list[core.Result], quiet: bool = False) -> None:
    if not results:
        print("No claims yet. Mark one:\n")
        print("    We support 47 integrations.   <!-- asof:integrations -->\n")
        return

    shown = [r for r in results if not quiet or r.status in core.FAILING]
    if shown:
        width = max(len(r.name) for r in shown)
        vwidth = max(len(r.document or "-") for r in shown)
        for r in shown:
            tag = core.SYMBOLS[r.status]
            line = f"  {tag:<6} {r.name:<{width}}  {(r.document or '-'):<{vwidth}}  {r.where}"
            print(line)
            if r.message and r.status in core.FAILING:
                print(f"         {'':<{width}}  {r.message}")
            remedy = core.remedy(r)
            if remedy:
                print(f"         {'':<{width}}  -> {remedy}")

    tally = {}
    for r in results:
        tally[r.status] = tally.get(r.status, 0) + 1
    parts = [f"{n} {s.value}" for s, n in sorted(tally.items(), key=lambda kv: kv[0].value)]
    print(f"\n{len(results)} claim(s): " + ", ".join(parts))


def _as_dict(r: core.Result) -> dict:
    return {
        "name": r.name,
        "status": r.status.value,
        "document": r.document,
        "produced": r.produced,
        "message": r.message,
        "remedy": core.remedy(r),
        "checked": state.to_iso(r.checked) if r.checked else None,
        "age_seconds": round(r.age) if r.age is not None else None,
        "every_seconds": round(r.claim.every) if r.claim.every else None,
        "why": r.claim.why,
        "owner": r.claim.owner,
        "automatic": r.claim.automatic,
        "markers": [{"file": m.path.as_posix(), "line": m.line_no} for m in r.markers],
    }


# ------------------------------------------------------------------------- update


def cmd_update(root: Path, cfg, st, args) -> int:
    results = core.check(root, cfg, st, only=args.only, record=not args.dry_run)
    drifting = [r for r in results if r.status is Status.DRIFT]

    if not drifting:
        print("Nothing to update - no number disagrees with its command.")
        if st.dirty and not args.dry_run:
            st.save()
        return _report_leftovers(results)

    if args.dry_run:
        for r in drifting:
            for m in r.markers:
                print(f"  {m.where}: {m.token} -> {r.suggestion}")
        print(f"\n{len(drifting)} claim(s) would change. Drop --dry-run to write them.")
        _report_leftovers([r for r in results if r.status is not Status.DRIFT])
        return 1

    changed = core.update(root, drifting, st)
    st.save()
    for r in changed:
        for m in r.markers:
            print(f"  {m.where}: {m.token} -> {r.suggestion}")
    edits = sum(len(r.markers) for r in changed)
    print(f"\nUpdated {len(changed)} claim(s) across {edits} place(s).")
    return _report_leftovers(results)


def _report_leftovers(results: list[core.Result]) -> int:
    """Say what update could not fix, rather than exiting quietly on 'done'.

    Only drift has a right answer to write. A claim that reads differently in
    two files, or one whose command will not run, needs a person to decide -
    and a silent exit 0 would imply there was nothing left to decide.
    """
    left = [r for r in results if r.status in core.FAILING]
    if not left:
        return 0
    print(f"\n{len(left)} claim(s) update cannot settle - these need a person:")
    for r in left:
        print(f"  {core.SYMBOLS[r.status]:<6} {r.name}: {r.message}")
    return 1
    return 0


# --------------------------------------------------------------------------- list


def cmd_list(root: Path, cfg, st, args) -> int:
    results = core.check(root, cfg, st, run=False, only=args.only, record=False)
    if args.json:
        print(json.dumps([_as_dict(r) for r in results], indent=2))
        return 0
    if not results:
        print("No claims yet.")
        return 0
    width = max(len(r.name) for r in results)
    for r in results:
        seen = f"{config.format_duration(r.age):>6} ago" if r.age is not None else " never   "
        kind = "run" if r.claim.automatic else "hand"
        due = config.format_duration(r.claim.every) if r.claim.every else "-"
        print(f"  {r.name:<{width}}  {(r.document or '-'):>10}  {kind:<4}  "
              f"checked {seen}  every {due:<5}  {r.where}")
        if r.claim.why:
            print(f"  {'':<{width}}  {r.claim.why}")
    return 0


# -------------------------------------------------------------------------- touch


def cmd_touch(root: Path, cfg, st, args) -> int:
    results = core.check(root, cfg, st, run=False, record=False)
    done = core.touch(st, results, args.names)
    missing = sorted(set(args.names) - set(done))
    if done:
        st.save()
        print("Re-verified just now: " + ", ".join(done))
    for name in missing:
        print(f"no marker found for {name!r}", file=sys.stderr)
    return 1 if missing else 0


# ------------------------------------------------------------------------ suggest


def cmd_suggest(root: Path, cfg, args) -> int:
    markers = scan.scan_tree(root, cfg.include, cfg.exclude, cfg.fenced)
    claimed = {(m.path.as_posix(), m.line_no, m.start) for m in markers}
    found = suggest.collect(root, cfg, claimed)

    if args.json:
        print(json.dumps([{
            "value": c.token,
            "file": c.path.as_posix(),
            "line": c.line_no,
            "score": c.score,
            "name": c.suggested_name,
            "marker": c.marker,
            "echoes": c.echoes,
            "reasons": c.reasons,
            "context": c.context,
        } for c in found], indent=2))
        return 0

    if not found:
        if markers:
            print(f"Nothing unclaimed worth flagging - {len(markers)} marker(s) already placed.")
        else:
            print("No candidate numbers found in your documents.")
        return 0

    shown = found if args.limit == 0 else found[: args.limit]
    print(f"{len(found)} unclaimed number(s) in your documents. "
          "The ones written in more than one place come first,\n"
          "because those are already two people's job to remember:\n")
    for c in shown:
        print(f"  {c.token:<12} {c.where}")
        print(f"  {'':<12} {_clip(c.context)}")
        if c.echoes:
            print(f"  {'':<12} same number at {_clip(', '.join(c.echoes), 58)}")
        if c.sites:
            print(f"  {'':<12} also unclaimed at {_clip(', '.join(c.sites), 55)}")
        print(f"  {'':<12} paste after it:  {c.marker}")
        if args.why:
            for reason in c.reasons:
                print(f"  {'':<12}   - {reason}")
        print()

    if len(found) > len(shown):
        print(f"{len(found) - len(shown)} more. Use --limit 0 to see them all.")
    print("None of this is a claim yet. Paste a marker, then run: asof init")
    return 0


def _clip(text: str, width: int = 74) -> str:
    text = _printable(text)
    return text if len(text) <= width else text[: width - 1] + "..."


def _printable(text: str) -> str:
    """Quoted context comes from someone else's file, on someone else's console.

    A Windows terminal in a legacy code page cannot print an em dash, and a
    suggestion is not worth a UnicodeEncodeError, so anything the console
    cannot spell is replaced rather than raised.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return text.encode(encoding, "replace").decode(encoding, "replace")
    return text


# ------------------------------------------------------------------------- report


def cmd_report(root: Path, cfg, st, args) -> int:
    results = core.check(root, cfg, st, run=not args.no_run, record=False)
    out = root / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.render(results, root.name), encoding="utf-8")
    print(f"wrote {out.relative_to(root).as_posix() if out.is_relative_to(root) else out}")
    if args.open:
        print(out.as_uri())
    return 0


def entrypoint() -> None:  # pragma: no cover
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":  # pragma: no cover
    entrypoint()
