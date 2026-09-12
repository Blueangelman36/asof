"""Everything a QA pass found by feeding asof things nobody would write on purpose.

A tool that reads other people's files meets broken ones. The contract these
tests hold it to is narrow: say what is wrong in one line and exit 2. Never a
traceback, and never a quiet exit 0.
"""

import contextlib
import io
import sys
import time
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from asof import cli, config, core, state

PY = sys.executable
MARK = "We have 1,247 users. <!-- asof:users -->\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(["-C", str(self.root), *argv])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()


class TestBrokenConfig(Base):
    """A typo in asof.ini is a message, not a stack trace."""

    def assertPolite(self, ini, fragment):
        self.write("README.md", MARK)
        self.write("asof.ini", ini)
        code, _, err = self.run_cli("check")
        self.assertEqual(code, 2, err)
        self.assertTrue(err.startswith("asof:"), err)
        self.assertIn(fragment, err)

    def test_unreadable_duration(self):
        self.assertPolite("[users]\nevery = 30 fortnights\n", "cannot read duration")

    def test_unreadable_tolerance(self):
        self.assertPolite("[users]\ntolerance = abc\n", "tolerance")

    def test_unreadable_timeout(self):
        self.assertPolite("[users]\ntimeout = later\n", "seconds")

    def test_negative_timeout(self):
        self.assertPolite("[users]\ntimeout = -5\n", "greater than zero")

    def test_not_an_ini_file_at_all(self):
        self.assertPolite('{"users": 1}\n', "line 1")

    def test_duplicate_section(self):
        self.assertPolite("[users]\nevery=1d\n[users]\nevery=2d\n", "appears twice")

    def test_duplicate_option(self):
        self.assertPolite("[users]\nevery=1d\nevery=2d\n", "twice")

    def test_the_error_names_the_section_and_key(self):
        self.write("README.md", MARK)
        self.write("asof.ini", "[users]\nevery = whenever\n")
        err = self.run_cli("check")[2]
        self.assertIn("[users]", err)
        self.assertIn("every", err)


class TestBrokenLockfile(Base):
    """A lockfile is generated, so a damaged one rebuilds rather than complains."""

    def assertSurvives(self, lock):
        self.write("README.md", MARK)
        self.write("asof.lock", lock)
        code, out, err = self.run_cli("check")
        self.assertIn(code, (0, 1), err)
        self.assertIn("users", out)

    def test_not_json(self):
        self.assertSurvives("not json at all")

    def test_json_but_a_list(self):
        self.assertSurvives("[1, 2, 3]")

    def test_claims_is_not_a_mapping(self):
        self.assertSurvives('{"claims": ["users"]}')

    def test_an_entry_is_not_a_mapping(self):
        self.assertSurvives('{"claims": {"users": "1,247"}}')

    def test_unreadable_timestamp(self):
        self.assertSurvives('{"claims": {"users": {"value": "1,247", "checked": "soon"}}}')


class TestHostileFiles(Base):
    def test_a_bom_does_not_hide_a_marker(self):
        self.write("README.md", "﻿" + MARK)
        self.assertIn("users", self.run_cli("check")[1])

    def test_undecodable_files_are_skipped_not_fatal(self):
        self.write("README.md", MARK)
        self.write("other.md", "caf\xe9 47 <!-- asof:c -->".encode("latin-1"))
        self.write("blob.bin", b"\x00\x01asof:x 5")
        code, out, err = self.run_cli("check")
        self.assertIn(code, (0, 1), err)
        self.assertIn("users", out)

    def test_a_command_printing_undecodable_bytes(self):
        self.write("README.md", MARK)
        self.write("asof.ini",
                   f'[users]\nrun = {PY} -c "import sys;sys.stdout.buffer.write(b\'\\xff\\xfe\')"\n')
        self.assertIn(self.run_cli("check")[0], (1, 2))

    def test_a_command_that_hangs_is_killed(self):
        self.write("README.md", MARK)
        self.write("asof.ini",
                   f'[users]\ntimeout = 1\nrun = {PY} -c "import time;time.sleep(30)"\n')
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertIn("timed out", out)

    def test_the_timeout_is_a_limit_and_not_just_a_message(self):
        # shell=True means the child is a shell and the work is its child.
        # Kill only the shell and the grandchild keeps the pipes open, so the
        # read blocks for the full sleep while the report says "timed out".
        claim = config.Claim(
            "slow", run=f'{PY} -c "import time;time.sleep(30)"', timeout=1)
        started = time.monotonic()
        ok, _, err = core.run_command(claim, self.root)
        elapsed = time.monotonic() - started
        self.assertFalse(ok)
        self.assertIn("timed out", err)
        self.assertLess(elapsed, 15, f"timeout did not bound the run: took {elapsed:.1f}s")

    def test_a_command_that_leaves_a_child_behind_still_returns(self):
        spawn = (f'{PY} -c "import subprocess,sys;'
                 f'subprocess.Popen([sys.executable, chr(45)+chr(99), '
                 f"'import time;time.sleep(30)']);"
                 'import time;time.sleep(30)"')
        claim = config.Claim("spawner", run=spawn, timeout=1)
        started = time.monotonic()
        core.run_command(claim, self.root)
        self.assertLess(time.monotonic() - started, 20)


class TestUnknownNames(Base):
    """A claim name that matches nothing is a typo, and typos must not pass CI."""

    def setUp(self):
        super().setUp()
        self.write("README.md", MARK)

    def test_check_rejects_it(self):
        code, _, err = self.run_cli("check", "tyop")
        self.assertEqual(code, 2)
        self.assertIn("no such claim: tyop", err)
        self.assertIn("users", err)          # says what does exist

    def test_update_rejects_it(self):
        self.assertEqual(self.run_cli("update", "tyop")[0], 2)

    def test_list_rejects_it(self):
        self.assertEqual(self.run_cli("list", "tyop")[0], 2)

    def test_a_real_name_still_works(self):
        self.assertIn(self.run_cli("check", "users")[0], (0, 1))


class TestLockfileChurn(Base):
    """The lockfile is meant to be committed, so it must not change on every read."""

    def test_an_unchanged_claim_is_not_restamped(self):
        self.write("README.md", MARK)
        self.run_cli("check")
        before = (self.root / "asof.lock").read_bytes()
        self.run_cli("check")
        self.run_cli("check")
        self.assertEqual(before, (self.root / "asof.lock").read_bytes())

    def test_a_changed_value_is_recorded_at_once(self):
        self.write("README.md", MARK)
        self.run_cli("check")
        before = (self.root / "asof.lock").read_bytes()
        self.write("README.md", "We have 1,389 users. <!-- asof:users -->\n")
        self.run_cli("check")
        self.assertNotEqual(before, (self.root / "asof.lock").read_bytes())

    def test_an_old_stamp_is_refreshed(self):
        st = state.State(self.root / "asof.lock")
        moment = state.now()
        st.record("a", "47", "run", moment)
        st.dirty = False
        st.record("a", "47", "run", moment + timedelta(seconds=30))
        self.assertFalse(st.dirty, "a fresh stamp should not be rewritten")
        st.record("a", "47", "run", moment + timedelta(hours=3))
        self.assertTrue(st.dirty, "a stamp hours old should be refreshed")

    def test_touch_always_moves_the_clock(self):
        st = state.State(self.root / "asof.lock")
        moment = state.now()
        st.record("a", "47", "manual", moment)
        st.dirty = False
        st.record("a", "47", "manual", moment + timedelta(seconds=5), force=True)
        self.assertTrue(st.dirty)


class TestReadOnlyCommands(Base):
    """list and suggest must never write, and never run anybody's commands."""

    def setUp(self):
        super().setUp()
        self.sentinel = self.root / "ran.txt"
        self.write("README.md", MARK)
        self.write("asof.ini",
                   f'[users]\nrun = {PY} -c "open(r\'{self.sentinel}\',\'w\').write(\'x\')"\n')

    def test_list_runs_nothing(self):
        self.run_cli("list")
        self.assertFalse(self.sentinel.exists())

    def test_suggest_runs_nothing(self):
        self.run_cli("suggest")
        self.assertFalse(self.sentinel.exists())

    def test_no_run_runs_nothing(self):
        self.run_cli("check", "--no-run")
        self.assertFalse(self.sentinel.exists())


class TestOutputPaths(Base):
    def test_report_creates_the_folder_it_was_pointed_at(self):
        self.write("README.md", MARK)
        code, _, err = self.run_cli("report", "-o", "build/pages/board.html")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.root / "build/pages/board.html").is_file())


class TestSettling(Base):
    """Statuses settle after the first sighting and stay put."""

    def test_check_is_stable_from_the_second_run(self):
        self.write("README.md", MARK + "The cap is 20. <!-- asof:cap -->\n")
        self.run_cli("check")
        second = self.run_cli("check")
        third = self.run_cli("check")
        self.assertEqual(second, third)

    def test_json_output_is_identical_across_runs(self):
        self.write("README.md", MARK)
        self.run_cli("check")
        first = self.run_cli("check", "--json")[1]
        self.assertEqual(first, self.run_cli("check", "--json")[1])


class TestExcludedMarkers(Base):
    def test_excluding_a_marked_file_does_not_silently_pass(self):
        self.write("README.md", MARK)
        self.write("asof.ini", "[asof]\nexclude = README.md\n\n[users]\nevery = 1d\n")
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("ORPHAN", out)


class TestConfigUnits(unittest.TestCase):
    def test_tolerance_validation_accepts_what_the_docs_promise(self):
        for spec in ("5", "10%", "±5", "0.5", ""):
            with self.subTest(spec=spec):
                self.assertEqual(config._tolerance(Path("asof.ini"), "s", spec), spec)

    def test_tolerance_validation_rejects_nonsense(self):
        with self.assertRaises(config.ConfigError):
            config._tolerance(Path("asof.ini"), "s", "quite a lot")


class TestUnknownClaimCarriesContext(unittest.TestCase):
    def test_it_lists_what_does_exist(self):
        exc = core.UnknownClaim(["tyop"], ["users", "cap"])
        self.assertEqual(exc.unknown, ["tyop"])
        self.assertIn("users", exc.known)


if __name__ == "__main__":
    unittest.main()
