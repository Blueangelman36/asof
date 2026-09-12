import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from asof import cli

PY = sys.executable


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(["-C", str(self.root), *argv])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()


class TestCheck(Base):
    def test_clean_repo_exits_zero(self):
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.write("asof.ini", f'[things]\nrun = {PY} -c "print(47)"\n')
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("things", out)

    def test_drift_exits_one(self):
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.write("asof.ini", f'[things]\nrun = {PY} -c "print(52)"\n')
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("DRIFT", out)

    def test_error_exits_two(self):
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.write("asof.ini", f'[things]\nrun = {PY} -c "raise SystemExit(9)"\n')
        self.assertEqual(self.run_cli("check")[0], 2)

    def test_fail_on_none_always_exits_zero(self):
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.write("asof.ini", f'[things]\nrun = {PY} -c "print(52)"\n')
        self.assertEqual(self.run_cli("check", "--fail-on", "none")[0], 0)

    def test_unknown_status_is_rejected_before_anything_runs(self):
        marker = self.root / "ran.txt"
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.write("asof.ini",
                   f'[things]\nrun = {PY} -c "open(r\'{marker}\',\'w\').write(\'x\');print(47)"\n')
        code, _, err = self.run_cli("check", "--fail-on", "nonsense")
        self.assertEqual(code, 2)
        self.assertIn("nonsense", err)
        self.assertFalse(marker.exists(), "a bad flag must not run any commands")

    def test_no_record_leaves_no_lockfile(self):
        self.write("README.md", "We have 12 customers. <!-- asof:customers -->")
        self.run_cli("check", "--no-record")
        self.assertFalse((self.root / "asof.lock").exists())

    def test_json_output_is_json(self):
        self.write("README.md", "We have 12 customers. <!-- asof:customers -->")
        _, out, _ = self.run_cli("check", "--json")
        payload = json.loads(out)
        self.assertEqual(payload[0]["name"], "customers")
        self.assertEqual(payload[0]["document"], "12")


class TestUpdate(Base):
    def test_dry_run_changes_nothing(self):
        readme = self.write("README.md", "We have 1,247 users. <!-- asof:users -->")
        self.write("asof.ini", f'[users]\nrun = {PY} -c "print(1389)"\n')
        code, out, _ = self.run_cli("update", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("1,389", out)
        self.assertIn("1,247", readme.read_text(encoding="utf-8"))

    def test_update_writes_and_then_checks_clean(self):
        readme = self.write("README.md", "We have 1,247 users. <!-- asof:users -->")
        self.write("asof.ini", f'[users]\nrun = {PY} -c "print(1389)"\n')
        self.assertEqual(self.run_cli("update")[0], 0)
        self.assertIn("1,389", readme.read_text(encoding="utf-8"))
        self.assertEqual(self.run_cli("check")[0], 0)

    def test_update_with_nothing_to_do(self):
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.write("asof.ini", f'[things]\nrun = {PY} -c "print(47)"\n')
        code, out, _ = self.run_cli("update")
        self.assertEqual(code, 0)
        self.assertIn("Nothing to update", out)

    def test_update_admits_what_it_cannot_settle(self):
        # Drift has a right answer to write. An inconsistency does not, and
        # update must not exit 0 as though the repo were clean.
        self.write("README.md", "We have 1,247 users. <!-- asof:users -->\n"
                                "Port 8080. <!-- asof:port -->")
        self.write("docs/run.md", "Port 9090. <!-- asof:port -->")
        self.write("asof.ini", f'[users]\nrun = {PY} -c "print(1389)"\n')
        code, out, _ = self.run_cli("update")
        self.assertEqual(code, 1)
        self.assertIn("1,389", out)
        self.assertIn("need a person", out)
        self.assertIn("port", out)

    def test_update_with_only_unsettleable_claims(self):
        self.write("README.md", "Port 8080. <!-- asof:port -->")
        self.write("docs/run.md", "Port 9090. <!-- asof:port -->")
        code, out, _ = self.run_cli("update")
        self.assertEqual(code, 1)
        self.assertIn("Nothing to update", out)
        self.assertIn("need a person", out)


class TestOtherCommands(Base):
    def test_init_lists_what_it_found(self):
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        code, out, _ = self.run_cli("init")
        self.assertEqual(code, 0)
        self.assertIn("things", out)
        self.assertIn("[things]", (self.root / "asof.ini").read_text(encoding="utf-8"))

    def test_init_refuses_to_clobber(self):
        self.write("asof.ini", "[kept]\nevery = 1d\n")
        self.assertEqual(self.run_cli("init")[0], 1)
        self.assertIn("[kept]", (self.root / "asof.ini").read_text(encoding="utf-8"))
        self.assertEqual(self.run_cli("init", "--force")[0], 0)

    def test_list_reports_unchecked_claims(self):
        self.write("README.md", "We have 12 customers. <!-- asof:customers -->")
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("never", out)

    def test_touch_complains_about_unknown_names(self):
        self.write("README.md", "We have 12 customers. <!-- asof:customers -->")
        code, _, err = self.run_cli("touch", "ghost")
        self.assertEqual(code, 1)
        self.assertIn("ghost", err)

    def test_report_writes_a_page(self):
        self.write("README.md", "We have 12 customers. <!-- asof:customers -->")
        self.assertEqual(self.run_cli("report", "-o", "board.html")[0], 0)
        self.assertIn("<title>", (self.root / "board.html").read_text(encoding="utf-8"))

    def test_suggest_points_at_the_repeated_number(self):
        self.write("README.md", "The dashboard listens on 8420 by default.")
        self.write("config.toml", "dashboard_port = 8420")
        code, out, _ = self.run_cli("suggest")
        self.assertEqual(code, 0)
        self.assertIn("8420", out)
        self.assertIn("config.toml:1", out)
        self.assertIn("<!-- asof:", out)

    def test_suggest_json(self):
        self.write("README.md", "The dashboard listens on 8420 by default.")
        self.write("config.toml", "dashboard_port = 8420")
        payload = json.loads(self.run_cli("suggest", "--json")[1])
        self.assertEqual(payload[0]["value"], "8420")
        self.assertEqual(payload[0]["file"], "README.md")

    def test_suggest_says_so_when_everything_is_claimed(self):
        self.write("README.md", "The dashboard listens on 8420. <!-- asof:port -->")
        code, out, _ = self.run_cli("suggest")
        self.assertEqual(code, 0)
        self.assertIn("already placed", out)

    def test_suggest_limit(self):
        self.write("README.md", "\n".join(
            f"We support {n},200 tenants of type {n}." for n in range(1, 6)))
        self.assertLessEqual(self.run_cli("suggest", "-n", "2")[1].count("paste after it"), 2)

    def test_no_command_prints_help(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main()
