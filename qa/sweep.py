"""An adversarial sweep over asof, kept because its numbers are claims.

The unit tests say what asof should do. This says what it should never do, over
a wide matrix of inputs nobody would write on purpose: never raise a traceback,
never exit 0 on a broken repo, never write a file a read-only command touched.

It is separate from the test suite because it is a different question. Tests
check behaviour one case at a time; this checks two properties across fifty.

    python qa/sweep.py            # run it, exit non-zero if anything failed
    python qa/sweep.py --count probes
"""

from __future__ import annotations

import contextlib
import json
import hashlib
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asof import cli  # noqa: E402

PY = sys.executable
MARK = "We have 1,247 users. <!-- asof:users -->\n"


class Repo:
    """A throwaway repo asof can be pointed at."""

    def __init__(self, files: dict):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel, content in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")

    def run(self, *argv) -> tuple:
        """Run the CLI in-process so a traceback is visible rather than an exit code."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(["-C", str(self.root), *argv])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue()

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(self.root).as_posix().encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()


# --------------------------------------------------------------------- probes
# Each is a repo asof must survive. Surviving means a clean exit code and a
# sentence, never a traceback.

def probe_cases() -> list[tuple[str, dict, tuple]]:
    slow = f'{PY} -c "import time;time.sleep(30)"'
    cases: list[tuple[str, dict, tuple]] = [
        # encodings and byte-level oddities
        ("utf-8 BOM", {"README.md": "﻿" + MARK}, ("check",)),
        ("utf-16 file in the tree", {"README.md": MARK, "n.md": MARK.encode("utf-16")}, ("check",)),
        ("latin-1 bytes", {"README.md": MARK, "x.md": b"caf\xe9 47 <!-- asof:c -->"}, ("check",)),
        ("binary file naming asof", {"README.md": MARK, "a.bin": b"\x00\x01asof:x 5"}, ("check",)),
        ("empty file", {"README.md": "", "b.md": MARK}, ("check",)),
        ("only a marker", {"README.md": "<!-- asof:x -->"}, ("check",)),
        ("no trailing newline", {"README.md": MARK.rstrip("\n")}, ("check",)),
        ("CRLF throughout", {"README.md": MARK.replace("\n", "\r\n")}, ("check",)),
        ("lone CR endings", {"README.md": MARK.replace("\n", "\r")}, ("check",)),
        ("a 200k character line", {"README.md": "x" * 200000 + " 47 <!-- asof:b -->\n"}, ("check",)),
        ("nul byte mid-file", {"README.md": MARK, "c.md": "47 <!-- asof:z -->\x00t"}, ("check",)),

        # malformed markers
        ("marker with no name", {"README.md": "47 <!-- asof: -->"}, ("check",)),
        ("punctuation-only name", {"README.md": "47 <!-- asof:--- -->"}, ("check",)),
        ("two markers, one line", {"README.md": "47 <!-- asof:a --><!-- asof:a -->"}, ("check",)),
        ("forward marker, nothing after", {"README.md": "<!-- asof:a> -->"}, ("check",)),
        ("deeply nested name", {"README.md": "47 <!-- asof:a/b/c/d.e-f -->"}, ("check",)),
        ("500 markers", {"README.md": "".join(f"{i} <!-- asof:n{i} -->\n" for i in range(500))},
         ("check",)),

        # malformed config
        ("bad duration", {"README.md": MARK, "asof.ini": "[users]\nevery = 30 fortnights\n"}, ("check",)),
        ("bad tolerance", {"README.md": MARK, "asof.ini": "[users]\ntolerance = abc\n"}, ("check",)),
        ("bad timeout", {"README.md": MARK, "asof.ini": "[users]\ntimeout = later\n"}, ("check",)),
        ("negative timeout", {"README.md": MARK, "asof.ini": "[users]\ntimeout = -5\n"}, ("check",)),
        ("config is json", {"README.md": MARK, "asof.ini": '{"users": 1}'}, ("check",)),
        ("duplicate section", {"README.md": MARK,
                               "asof.ini": "[users]\nevery=1d\n[users]\nevery=2d\n"}, ("check",)),
        ("duplicate option", {"README.md": MARK,
                              "asof.ini": "[users]\nevery=1d\nevery=2d\n"}, ("check",)),
        ("percent in a value", {"README.md": MARK, "asof.ini": "[users]\nwhy = 50% of it\n"}, ("check",)),

        # malformed lockfile
        ("lockfile is garbage", {"README.md": MARK, "asof.lock": "not json"}, ("check",)),
        ("lockfile is a list", {"README.md": MARK, "asof.lock": "[1,2,3]"}, ("check",)),
        ("lockfile claims is a list", {"README.md": MARK,
                                       "asof.lock": '{"claims":["users"]}'}, ("check",)),
        ("lockfile entry is a string", {"README.md": MARK,
                                        "asof.lock": '{"claims":{"users":"1,247"}}'}, ("check",)),
        ("lockfile bad timestamp", {"README.md": MARK,
                                    "asof.lock": '{"claims":{"users":{"value":"1,247",'
                                                 '"checked":"soon"}}}'}, ("check",)),

        # commands
        ("command prints many lines", {"README.md": MARK,
                                       "asof.ini": f'[users]\nrun = {PY} -c "print(1);print(1247)"\n'},
         ("check",)),
        ("command prints 100k", {"README.md": MARK,
                                 "asof.ini": f'[users]\nrun = {PY} -c "print(\'x\'*100000);print(1247)"\n'},
         ("check",)),
        ("command prints whitespace", {"README.md": MARK,
                                       "asof.ini": f'[users]\nrun = {PY} -c "print(\'   \')"\n'},
         ("check",)),
        ("command does not exist", {"README.md": MARK,
                                    "asof.ini": "[users]\nrun = no-such-binary-xyz\n"}, ("check",)),
        ("command times out", {"README.md": MARK,
                               "asof.ini": f"[users]\ntimeout = 1\nrun = {slow}\n"}, ("check",)),
        ("command prints raw bytes", {"README.md": MARK,
                                      "asof.ini": f'[users]\nrun = {PY} -c "import sys;'
                                                  f"sys.stdout.buffer.write(b'\\xff\\xfe')\"\n"},
         ("check",)),
        ("cwd points nowhere", {"README.md": MARK,
                                "asof.ini": f'[users]\ncwd = nope/nope\nrun = {PY} -c "print(1)"\n'},
         ("check",)),
    ]

    # numbers that are not really numbers
    for label, text in [
        ("huge number", "We have 99999999999999999999 users. <!-- asof:u -->"),
        ("tiny number", "We have 0.0000001 users. <!-- asof:u -->"),
        ("negative", "Delta is -47 today. <!-- asof:u -->"),
        ("range dash", "Between 50-99% of it. <!-- asof:u -->"),
        ("scientific notation", "About 1e9 rows. <!-- asof:u -->"),
        ("leading zeros", "Code 00047 applies. <!-- asof:u -->"),
        ("misused separators", "We have 1,24,7 users. <!-- asof:u -->"),
        ("fullwidth digits", "We have ４７ users. <!-- asof:u -->"),
        ("ip address", "Bind 127.0.0.1 there. <!-- asof:u -->"),
    ]:
        cases.append((f"number: {label}", {"README.md": text}, ("check",)))

    # the rest of the command line
    cases += [
        ("unknown claim name", {"README.md": MARK}, ("check", "ghost")),
        ("touch an unknown claim", {"README.md": MARK}, ("touch", "ghost")),
        ("update an unknown claim", {"README.md": MARK}, ("update", "ghost")),
        ("list with no claims", {}, ("list",)),
        ("suggest with no documents", {}, ("suggest",)),
        ("report into a missing folder", {"README.md": MARK}, ("report", "-o", "a/b/c.html")),
        ("negative limit", {"README.md": MARK}, ("suggest", "-n", "-3")),
    ]
    return cases


def run_probes(verbose: bool = False) -> list[str]:
    failures = []
    for name, files, argv in probe_cases():
        with Repo(files) as repo:
            try:
                code, output = repo.run(*argv)
            except Exception as exc:                      # noqa: BLE001 - the point
                failures.append(f"{name}: raised {type(exc).__name__}: {exc}")
                continue
        if code not in (0, 1, 2):
            failures.append(f"{name}: odd exit code {code}")
        elif verbose:
            print(f"  ok    {name} (exit {code})")
    return failures


# ----------------------------------------------------------------- invariants

def invariant_cases():
    """(name, callable) pairs. Each returns an error string, or None when happy."""

    mixed = {
        "README.md": ("We have 1,247 users. <!-- asof:users -->\n"
                      "The cap is 20 per hour. <!-- asof:cap -->\n"
                      "Port 8420 is the default. <!-- asof:port -->\n"),
        "docs/run.md": "Port 8420 in production. <!-- asof:port -->\n",
        "asof.ini": (f'[users]\nrun = {PY} -c "print(1247)"\n\n'
                     "[cap]\nevery = 90d\n\n[port]\nevery = 365d\n"),
    }

    def settles():
        with Repo(mixed) as r:
            r.run("check")
            if r.run("check") != r.run("check"):
                return "check output differs between identical runs"

    def lockfile_is_quiet():
        with Repo(mixed) as r:
            r.run("check")
            before = (r.root / "asof.lock").read_bytes()
            r.run("check")
            r.run("check")
            if before != (r.root / "asof.lock").read_bytes():
                return "asof.lock is rewritten by a check that changed nothing"

    def read_only(argv):
        def check():
            with Repo(mixed) as r:
                r.run("check")
                before = r.fingerprint()
                r.run(*argv)
                if before != r.fingerprint():
                    return f"`{' '.join(argv)}` modified the tree"
        return check

    def update_converges():
        with Repo({**mixed, "asof.ini": f'[users]\nrun = {PY} -c "print(1389)"\n'}) as r:
            r.run("update")
            once = r.fingerprint()
            r.run("update")
            if once != r.fingerprint():
                return "a second update made further changes"
            if r.run("check")[0] != 0:
                return "check is not clean after update"

    def runs_nothing(argv):
        def check():
            with Repo({}) as r:
                sentinel = r.root / "ran.txt"
                (r.root / "README.md").write_text(MARK, encoding="utf-8")
                (r.root / "asof.ini").write_text(
                    f'[users]\nrun = {PY} -c "open(r\'{sentinel}\',\'w\').write(\'x\')"\n',
                    encoding="utf-8")
                r.run(*argv)
                if sentinel.exists():
                    return f"`{' '.join(argv)}` executed a claim command"
        return check

    def deterministic_json():
        """Ages advance between runs; nothing else may.

        The point of the check is that claim order, statuses and values are
        stable - a report whose rows reshuffle is a report nobody can diff.
        """
        def stable(text):
            rows = json.loads(text)
            return [(row["name"], row["status"], row["document"], row["produced"])
                    for row in rows]

        with Repo(mixed) as r:
            r.run("check")
            shapes = {tuple(stable(r.run("check", "--json", "--no-record")[1]))
                      for _ in range(3)}
            if len(shapes) != 1:
                return "claim order, statuses or values move between identical runs"

    def finds_root_from_subdir():
        with Repo(mixed) as r:
            here = os.getcwd()
            try:
                os.chdir(r.root / "docs")
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                    with contextlib.suppress(SystemExit):
                        cli.main(["check"])
                if "users" not in out.getvalue():
                    return "running from a subdirectory did not find the repo root"
            finally:
                os.chdir(here)

    def exit_code(label, files, expected):
        def check():
            with Repo(files) as r:
                code = r.run("check")[0]
                if code != expected:
                    return f"{label} should exit {expected}, got {code}"
        return check

    def excluded_marker_is_not_silent():
        with Repo({"README.md": "47 <!-- asof:a -->",
                   "asof.ini": "[asof]\nexclude = README.md\n\n[a]\nevery=1d\n"}) as r:
            if r.run("check")[0] == 0:
                return "excluding a marked file passed silently"

    cases = [
        ("check settles and stays settled", settles),
        ("asof.lock does not churn", lockfile_is_quiet),
        ("update converges in one pass", update_converges),
        ("json output is deterministic", deterministic_json),
        ("finds the root from a subdirectory", finds_root_from_subdir),
        ("an excluded marker does not pass silently", excluded_marker_is_not_silent),
    ]
    for argv in (["list"], ["suggest"], ["check", "--no-record"]):
        cases.append((f"`{' '.join(argv)}` writes nothing", read_only(argv)))
    for argv in (["list"], ["suggest"], ["check", "--no-run"]):
        cases.append((f"`{' '.join(argv)}` runs nothing", runs_nothing(argv)))
    for label, files, expected in [
        ("a clean repo", {"README.md": "We have 47 x. <!-- asof:a -->",
                          "asof.ini": f'[a]\nrun = {PY} -c "print(47)"\n'}, 0),
        ("drift", {"README.md": "We have 47 x. <!-- asof:a -->",
                   "asof.ini": f'[a]\nrun = {PY} -c "print(52)"\n'}, 1),
        ("an inconsistency", {"README.md": "47 <!-- asof:a -->", "b.md": "52 <!-- asof:a -->"}, 1),
        ("a broken command", {"README.md": "We have 47 x. <!-- asof:a -->",
                              "asof.ini": "[a]\nrun = no-such-binary-xyz\n"}, 2),
        ("a deleted marker", {"README.md": "nothing", "asof.ini": "[a]\nevery = 1d\n"}, 1),
    ]:
        cases.append((f"exit code for {label} is {expected}",
                      exit_code(label, files, expected)))
    return cases


def run_invariants(verbose: bool = False) -> list[str]:
    failures = []
    for name, check in invariant_cases():
        try:
            problem = check()
        except Exception as exc:                          # noqa: BLE001 - the point
            problem = f"raised {type(exc).__name__}: {exc}"
        if problem:
            failures.append(f"{name}: {problem}")
        elif verbose:
            print(f"  ok    {name}")
    return failures


COUNTS = {
    "probes": lambda: len(probe_cases()),
    "invariants": lambda: len(invariant_cases()),
}


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "--count":
        if argv[2] not in COUNTS:
            print(f"usage: {argv[0]} --count {{{'|'.join(COUNTS)}}}", file=sys.stderr)
            return 2
        print(COUNTS[argv[2]]())
        return 0

    verbose = "-v" in argv
    print(f"{len(probe_cases())} hostile-input probes ...")
    probe_failures = run_probes(verbose)
    print(f"{len(invariant_cases())} invariants ...")
    invariant_failures = run_invariants(verbose)

    failures = probe_failures + invariant_failures
    for failure in failures:
        print(f"  FAIL  {failure}")
    total = len(probe_cases()) + len(invariant_cases())
    print(f"\n{total} checks, {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
