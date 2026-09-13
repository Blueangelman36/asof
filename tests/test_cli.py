import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from asof import cli, config, core

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

    def test_deleting_a_marker_fails_by_default(self):
        # A checker that stays green when its markers vanish fails open.
        self.write("README.md", "The cap is 20 calls/hour. <!-- asof:cap -->")
        self.write("asof.ini", "[cap]\nevery = 90d\n")
        self.run_cli("check")
        self.write("README.md", "The cap is 20 calls/hour.")
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("ORPHAN", out)

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
        self.assertEqual(payload["items"][0]["id"], "customers")
        self.assertEqual(payload["items"][0]["value"], "12")


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
        self.assertEqual(payload["tool"], "asof")
        self.assertFalse(payload["blocked"])
        self.assertEqual(payload["items"][0]["value"], "8420")
        self.assertEqual(payload["items"][0]["where"]["path"], "README.md")

    def test_suggest_says_so_when_everything_is_claimed(self):
        self.write("README.md", "The dashboard listens on 8420. <!-- asof:port -->")
        code, out, _ = self.run_cli("suggest")
        self.assertEqual(code, 0)
        self.assertIn("already placed", out)

    def test_suggest_limit(self):
        self.write("README.md", "\n".join(
            f"We support {n},200 tenants of type {n}." for n in range(1, 6)))
        self.assertLessEqual(self.run_cli("suggest", "-n", "2")[1].count("paste after it"), 2)

    def test_agents_block_is_pasteable_markdown(self):
        code, out, _ = self.run_cli("agents")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("## "))
        self.assertIn("asof check --json", out)

    def test_agents_block_forbids_the_obvious_shortcut(self):
        # An agent told to make CI green can always do it by deleting the
        # marker. The block has to say not to, in as many words.
        out = self.run_cli("agents")[1]
        self.assertIn("Never delete an `asof:` comment", out)

    def test_agents_needs_no_config_or_repo(self):
        # It must work in a bare directory, before anything is set up.
        self.assertEqual(self.run_cli("agents")[0], 0)


class TestRemedies(Base):
    """Every failure says what to do about it, in the log and in the JSON."""

    def remedy_for(self, files):
        for name, text in files.items():
            self.write(name, text)
        payload = json.loads(self.run_cli("check", "--json")[1])
        return {row["id"]: row["remedy"] for row in payload["items"]}

    def test_drift_names_the_update_command(self):
        remedies = self.remedy_for({
            "README.md": "We have 47 x. <!-- asof:a -->",
            "asof.ini": f'[a]\nrun = {PY} -c "print(52)"\n'})
        self.assertIn("asof update a", remedies["a"])

    def test_an_inconsistency_says_to_keep_the_markers(self):
        remedies = self.remedy_for({
            "README.md": "47 <!-- asof:a -->", "docs.md": "52 <!-- asof:a -->"})
        self.assertIn("keep the `asof:a` comment", remedies["a"])

    def test_an_orphan_says_how_to_end_the_claim_properly(self):
        remedies = self.remedy_for({"README.md": "nothing", "asof.ini": "[a]\nevery=1d\n"})
        self.assertIn("delete [a] from asof.ini", remedies["a"])

    def test_a_broken_command_points_at_the_config(self):
        remedies = self.remedy_for({
            "README.md": "We have 47 x. <!-- asof:a -->",
            "asof.ini": "[a]\nrun = no-such-binary-xyz\n"})
        self.assertIn("asof.ini", remedies["a"])

    def test_a_healthy_claim_has_no_remedy(self):
        remedies = self.remedy_for({
            "README.md": "We have 47 x. <!-- asof:a -->",
            "asof.ini": f'[a]\nrun = {PY} -c "print(47)"\n'})
        self.assertEqual(remedies["a"], "")

    def test_the_remedy_appears_in_the_human_log_too(self):
        self.write("README.md", "47 <!-- asof:a -->")
        self.write("docs.md", "52 <!-- asof:a -->")
        out = self.run_cli("check")[1]
        self.assertIn("-> make these agree", out)

    def test_every_failing_status_has_one(self):
        for status in core.FAILING:
            with self.subTest(status=status):
                result = core.Result("n", config.Claim("n"), status)
                self.assertTrue(core.remedy(result))


class TestJsonEnvelope(Base):
    """One shape, so a caller learns it once and reuses it across commands."""

    AGREED = {"tool", "version", "checked", "blocked", "counts", "items"}
    ITEM_KEYS = {"id", "status", "where", "why", "detail"}

    def payload(self, *argv):
        return json.loads(self.run_cli(*argv)[1])

    def setUp(self):
        super().setUp()
        self.write("README.md", "Port 8420. <!-- asof:port -->\n")
        self.write("config.toml", "port = 8500  # asof:port\n")
        self.write("asof.ini", "[port]\nwhy = Two files name this port.\nevery = 30d\n")

    def test_check_wears_the_envelope(self):
        payload = self.payload("check", "--json")
        self.assertEqual(self.AGREED, self.AGREED & set(payload))
        self.assertEqual(payload["tool"], "asof")
        self.assertEqual(payload["checked"], len(payload["items"]))

    def test_list_and_suggest_wear_the_same_one(self):
        for argv in (["list", "--json"], ["suggest", "--json"], ["why", "port", "--json"]):
            with self.subTest(argv=argv):
                payload = self.payload(*argv)
                self.assertEqual(self.AGREED, self.AGREED & set(payload))
                self.assertEqual(payload["tool"], "asof")

    def test_every_item_leads_with_the_agreed_keys(self):
        for argv in (["check", "--json"], ["list", "--json"], ["suggest", "--json"]):
            with self.subTest(argv=argv):
                for item in self.payload(*argv)["items"]:
                    self.assertEqual(self.ITEM_KEYS, self.ITEM_KEYS & set(item))

    def test_blocked_agrees_with_the_exit_code(self):
        code, out, _ = self.run_cli("check", "--json")
        self.assertEqual(json.loads(out)["blocked"], code != 0)

    def test_blocked_is_false_when_nothing_is_wrong(self):
        self.write("config.toml", "port = 8420  # asof:port\n")
        code, out, _ = self.run_cli("check", "--json")
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["blocked"])

    def test_read_only_commands_never_claim_to_block(self):
        for argv in (["list", "--json"], ["suggest", "--json"], ["why", "port", "--json"]):
            with self.subTest(argv=argv):
                self.assertFalse(self.payload(*argv)["blocked"])

    def test_counts_add_up_to_the_items(self):
        payload = self.payload("check", "--json")
        self.assertEqual(sum(payload["counts"].values()), len(payload["items"]))

    def test_where_points_at_the_first_marker(self):
        item = self.payload("check", "--json")["items"][0]
        self.assertEqual(item["where"], {"path": "README.md", "line": 1})
        self.assertEqual(len(item["locations"]), 2)

    def test_a_claim_with_no_marker_has_no_where(self):
        self.write("asof.ini", "[ghost]\nevery = 1d\n")
        (self.root / "README.md").unlink()
        (self.root / "config.toml").unlink()
        self.assertIsNone(self.payload("check", "--json")["items"][0]["where"])


class TestWhy(Base):
    """`asof why NAME` answers the question somebody has when they meet a marker."""

    def setUp(self):
        super().setUp()
        self.write("README.md", "Dashboard on port 8420. <!-- asof:port -->\n")
        self.write("config.toml", "port = 8420  # asof:port\n")
        self.write("asof.ini", "[port]\nevery = 180d\nowner = @platform\n"
                               "why = Both files name this port independently.\n")
        self.run_cli("check")

    def test_it_says_what_the_claim_is_and_why(self):
        code, out, _ = self.run_cli("why", "port")
        self.assertEqual(code, 0)
        self.assertIn("port", out)
        self.assertIn("8420", out)
        self.assertIn("Both files name this port independently.", out)

    def test_it_says_who_settles_it_and_when_it_is_due(self):
        out = self.run_cli("why", "port")[1]
        self.assertIn("by hand, every 180d", out)
        self.assertIn("@platform", out)
        self.assertIn("due in", out)

    def test_it_names_every_place_the_claim_is_marked(self):
        out = self.run_cli("why", "port")[1]
        self.assertIn("README.md:1", out)
        self.assertIn("config.toml:1", out)

    def test_an_automatic_claim_shows_its_command(self):
        self.write("asof.ini", f'[port]\nrun = {PY} -c "print(8420)"\n')
        self.assertIn("by running:", self.run_cli("why", "port")[1])

    def test_it_runs_no_commands(self):
        sentinel = self.root / "ran.txt"
        self.write("asof.ini",
                   f'[port]\nrun = {PY} -c "open(r\'{sentinel}\',\'w\').write(\'x\')"\n')
        self.run_cli("why", "port")
        self.assertFalse(sentinel.exists(), "why explains; check verifies")

    def test_it_writes_nothing(self):
        before = (self.root / "asof.lock").read_bytes()
        self.run_cli("why", "port")
        self.assertEqual(before, (self.root / "asof.lock").read_bytes())

    def test_an_unknown_name_is_an_error(self):
        code, _, err = self.run_cli("why", "tyop")
        self.assertEqual(code, 2)
        self.assertIn("no such claim", err)

    def test_several_names_at_once(self):
        self.write("README.md", "Port 8420. <!-- asof:port -->\n"
                                "We have 12 customers. <!-- asof:customers -->\n")
        out = self.run_cli("why", "port", "customers")[1]
        self.assertIn("customers", out)
        self.assertIn("port", out)

    def test_a_failing_claim_says_what_to_do(self):
        self.write("config.toml", "port = 8500  # asof:port\n")
        out = self.run_cli("why", "port")[1]
        self.assertIn("make these agree", out)


class TestSkill(Base):
    """The Claude Code skill, and the one copy of it that is allowed to exist."""

    REPO = Path(__file__).resolve().parent.parent

    def test_it_installs_where_claude_code_looks(self):
        code, out, err = self.run_cli("skill")
        self.assertEqual(code, 0, err)
        target = self.root / ".claude" / "skills" / "asof" / "SKILL.md"
        self.assertTrue(target.is_file())
        self.assertIn("skills/asof/SKILL.md", out)

    def test_it_has_the_frontmatter_a_skill_needs(self):
        self.run_cli("skill")
        body = (self.root / ".claude/skills/asof/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(body.startswith("---\n"))
        self.assertIn("\nname: asof\n", body)
        self.assertRegex(body, r"\ndescription: \S")

    def test_the_description_names_the_moments_it_should_trigger(self):
        body = self.run_cli("skill", "--print")[1]
        description = body.split("description:", 1)[1].split("\n", 1)[0]
        for trigger in ("fails", "adopt", "constant"):
            self.assertIn(trigger, description.lower())

    def test_running_it_twice_is_not_an_error(self):
        self.assertEqual(self.run_cli("skill")[0], 0)
        code, out, _ = self.run_cli("skill")
        self.assertEqual(code, 0)
        self.assertIn("already up to date", out)

    def test_it_refuses_to_clobber_a_modified_skill(self):
        self.run_cli("skill")
        target = self.root / ".claude/skills/asof/SKILL.md"
        target.write_text("---\nname: asof\n---\nmine now", encoding="utf-8")
        self.assertEqual(self.run_cli("skill")[0], 1)
        self.assertIn("mine now", target.read_text(encoding="utf-8"))
        self.assertEqual(self.run_cli("skill", "--force")[0], 0)
        self.assertNotIn("mine now", target.read_text(encoding="utf-8"))

    def test_this_repo_ships_exactly_what_the_package_ships(self):
        # Two copies exist: the one pip installs and the one you read on
        # GitHub. They are the same file or they are a lie.
        packaged = (self.REPO / "asof" / "skill.md").read_text(encoding="utf-8")
        checked_in = (self.REPO / ".claude" / "skills" / "asof" / "SKILL.md").read_text(
            encoding="utf-8")
        self.assertEqual(packaged, checked_in,
                         "run `asof skill --force` to regenerate .claude/skills/asof")


class TestSingleFileBuild(unittest.TestCase):
    """The zipapp is how asof reaches a repo that will not pip install it."""

    def test_it_builds_and_runs_with_no_install(self):
        import subprocess

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import build_pyz

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "asof.pyz"
            build_pyz.build(target)
            self.assertTrue(target.is_file())

            work = Path(tmp) / "repo"
            work.mkdir()
            (work / "README.md").write_text("47 <!-- asof:a -->", encoding="utf-8")
            (work / "docs.md").write_text("52 <!-- asof:a -->", encoding="utf-8")
            proc = subprocess.run([PY, str(target), "-C", str(work), "check"],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("SPLIT", proc.stdout)

    def test_the_skill_survives_the_zipapp(self):
        # importlib.resources has to reach inside the archive, not the filesystem.
        import subprocess

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import build_pyz

        with tempfile.TemporaryDirectory() as tmp:
            target = build_pyz.build(Path(tmp) / "asof.pyz")
            proc = subprocess.run([PY, str(target), "skill", "--print"],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("name: asof", proc.stdout)

    def test_it_carries_no_bytecode(self):
        import zipfile

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import build_pyz

        with tempfile.TemporaryDirectory() as tmp:
            target = build_pyz.build(Path(tmp) / "asof.pyz")
            names = zipfile.ZipFile(target).namelist()
            self.assertFalse([n for n in names if "__pycache__" in n or n.endswith(".pyc")])


class TestHelp(Base):
    def test_no_command_prints_help(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main()
