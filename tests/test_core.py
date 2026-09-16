import re
import string
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from asof import config, core, report, state
from asof.core import Status

PY = sys.executable


def echo(text):
    """A portable shell command that prints ``text``."""
    return f'{PY} -c "print({text!r})"'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.now = state.now()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_check(self, *, run=True, at=None, record=True):
        cfg = config.load(self.root)
        st = state.State.load(self.root)
        results = core.check(self.root, cfg, st, run=run, record=record, now=at or self.now)
        if st.dirty:
            st.save()
        return {r.name: r for r in results}, st


class TestAutomaticClaims(Base):
    def test_matching_command_is_ok(self):
        self.write("README.md", "We have 47 integrations. <!-- asof:integrations -->")
        self.write("asof.ini", f"[integrations]\nrun = {echo('47')}\n")
        results, _ = self.run_check()
        self.assertIs(results["integrations"].status, Status.OK)

    def test_drift_is_reported_with_a_suggestion(self):
        self.write("README.md", "We have 1,247 users. <!-- asof:users -->")
        self.write("asof.ini", f"[users]\nrun = {echo('1389')}\n")
        results, _ = self.run_check()
        result = results["users"]
        self.assertIs(result.status, Status.DRIFT)
        self.assertEqual(result.suggestion, "1,389")

    def test_tolerance_absorbs_noise(self):
        self.write("README.md", "Latency is 250ms. <!-- asof:p99 -->")
        self.write("asof.ini", f"[p99]\nrun = {echo('262ms')}\ntolerance = 10%\n")
        results, _ = self.run_check()
        self.assertIs(results["p99"].status, Status.OK)

    def test_failing_command_is_an_error_not_a_drift(self):
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.write("asof.ini", f"[things]\nrun = {PY} -c \"raise SystemExit(3)\"\n")
        results, _ = self.run_check()
        self.assertIs(results["things"].status, Status.ERROR)
        self.assertIn("exit 3", results["things"].message)

    def test_silent_command_is_an_error(self):
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.write("asof.ini", f"[things]\nrun = {PY} -c \"pass\"\n")
        results, _ = self.run_check()
        self.assertIs(results["things"].status, Status.ERROR)

    def test_no_run_skips_instead_of_guessing(self):
        self.write("README.md", "We have 1,247 users. <!-- asof:users -->")
        self.write("asof.ini", f"[users]\nrun = {echo('1389')}\n")
        results, _ = self.run_check(run=False)
        self.assertIs(results["users"].status, Status.SKIPPED)


class TestUpdate(Base):
    def test_update_rewrites_every_place_and_keeps_style(self):
        self.write("README.md", "We have 1,247 users. <!-- asof:users -->")
        self.write("docs/about.md", "Serving 1,247 users. <!-- asof:users -->")
        self.write("asof.ini", f"[users]\nrun = {echo('1389')}\n")

        cfg = config.load(self.root)
        st = state.State.load(self.root)
        results = core.check(self.root, cfg, st, now=self.now)
        changed = core.update(self.root, results, st, self.now)
        st.save()

        self.assertEqual(len(changed), 1)
        self.assertIn("1,389 users", (self.root / "README.md").read_text(encoding="utf-8"))
        self.assertIn("1,389 users", (self.root / "docs/about.md").read_text(encoding="utf-8"))

        after, _ = self.run_check()
        self.assertIs(after["users"].status, Status.OK)


class TestManualClaims(Base):
    def test_first_sighting_is_recorded(self):
        self.write("README.md", "We have 12 customers. <!-- asof:customers -->")
        results, st = self.run_check()
        self.assertIs(results["customers"].status, Status.NEW)
        self.assertEqual(st.recorded_value("customers"), "12")

    def test_goes_stale_after_its_interval(self):
        self.write("README.md", "We have 12 customers. <!-- asof:customers -->")
        self.write("asof.ini", "[customers]\nevery = 90d\n")
        self.run_check()
        later = self.now + timedelta(days=91)
        results, _ = self.run_check(at=later)
        self.assertIs(results["customers"].status, Status.STALE)
        self.assertIn("wanted every 90d", results["customers"].message)

    def test_editing_by_hand_counts_as_verifying(self):
        self.write("README.md", "We have 12 customers. <!-- asof:customers -->")
        self.write("asof.ini", "[customers]\nevery = 90d\n")
        self.run_check()
        later = self.now + timedelta(days=91)
        self.write("README.md", "We have 15 customers. <!-- asof:customers -->")
        results, _ = self.run_check(at=later)
        self.assertIs(results["customers"].status, Status.OK)

    def test_touch_resets_the_clock(self):
        self.write("README.md", "We have 12 customers. <!-- asof:customers -->")
        self.write("asof.ini", "[customers]\nevery = 90d\n")
        self.run_check()
        later = self.now + timedelta(days=91)

        cfg = config.load(self.root)
        st = state.State.load(self.root)
        results = core.check(self.root, cfg, st, run=False, record=False, now=later)
        self.assertEqual(core.touch(st, results, ["customers"], later), ["customers"])
        st.save()

        results, _ = self.run_check(at=later)
        self.assertIs(results["customers"].status, Status.OK)

    def test_default_every_applies_to_undeclared_markers(self):
        self.write("README.md", "We have 12 customers. <!-- asof:customers -->")
        self.write("asof.ini", "[asof]\nevery = 30d\n")
        self.run_check()
        results, _ = self.run_check(at=self.now + timedelta(days=31))
        self.assertIs(results["customers"].status, Status.STALE)


class TestConsistency(Base):
    def test_the_same_claim_in_two_places_must_agree(self):
        self.write("README.md", "We have 47 integrations. <!-- asof:integrations -->")
        self.write("site/index.html", "<p>52 integrations</p><!-- asof:integrations -->")
        results, _ = self.run_check()
        self.assertIs(results["integrations"].status, Status.INCONSISTENT)
        self.assertIn("52", results["integrations"].message)

    def test_agreement_across_formats_is_fine(self):
        self.write("README.md", "We have 1,247 users. <!-- asof:users -->")
        self.write("site/index.html", "<p>1247 users</p><!-- asof:users -->")
        results, _ = self.run_check()
        self.assertIsNot(results["users"].status, Status.INCONSISTENT)


class TestVersionClaims(Base):
    """The paths a real version claim goes through: split, drift, update."""

    def test_the_bug_as_reported(self):
        # asof read v3.10.0 as the number 0, so any command printing a version
        # drifted against a document that was telling the truth.
        self.write("README.md", "Requires Python v3.10.0 or newer. <!-- asof:py -->")
        self.write("asof.ini", f"[py]\nrun = {echo('3.10.0')}\n")
        results, _ = self.run_check()
        self.assertEqual(results["py"].document, "v3.10.0")
        self.assertIs(results["py"].status, Status.OK)

    def test_prose_and_config_agree_across_prefix_and_quotes(self):
        self.write("README.md", "Requires v3.10.0. <!-- asof:py -->")
        self.write("pyproject.toml", 'version = "3.10.0"  # asof:py')
        results, _ = self.run_check()
        self.assertIsNot(results["py"].status, Status.INCONSISTENT)

    def test_a_new_release_is_a_drift_not_a_match(self):
        self.write("README.md", "Current release: v2.4.1-rc.2 <!-- asof:rel -->")
        self.write("asof.ini", f"[rel]\nrun = {echo('2.4.1')}\n")
        results, _ = self.run_check()
        self.assertIs(results["rel"].status, Status.DRIFT)
        self.assertEqual(results["rel"].suggestion, "v2.4.1")

    def test_update_rewrites_a_version_in_its_own_style(self):
        readme = self.write("README.md", "Requires Python v3.10.0 or newer. <!-- asof:py -->")
        self.write("asof.ini", f"[py]\nrun = {echo('3.11.2')}\n")
        cfg = config.load(self.root)
        st = state.State.load(self.root)
        core.update(self.root, core.check(self.root, cfg, st, now=self.now), st, self.now)
        self.assertIn("v3.11.2 or newer", readme.read_text(encoding="utf-8"))

    def test_two_part_versions_need_type_version_to_split(self):
        self.write("README.md", "Python 3.10+ is required. <!-- asof:floor -->")
        self.write("ci.md", "CI runs Python 3.1 today. <!-- asof:floor -->")
        results, _ = self.run_check()
        self.assertIsNot(results["floor"].status, Status.INCONSISTENT,
                         "without type, 3.10 and 3.1 are the same decimal")
        self.write("asof.ini", "[floor]\ntype = version\n")
        results, _ = self.run_check()
        self.assertIs(results["floor"].status, Status.INCONSISTENT)

    def test_type_version_drift_on_a_two_part_floor(self):
        self.write("README.md", "Python 3.10+ is required. <!-- asof:floor -->")
        self.write("asof.ini", f"[floor]\ntype = version\nrun = {echo('3.1')}\n")
        results, _ = self.run_check()
        self.assertIs(results["floor"].status, Status.DRIFT)
        self.assertEqual(results["floor"].suggestion, "3.1")

    def test_update_does_not_turn_3_10_into_3_1(self):
        # The dangerous default: without `type = version`, 3.10 is the decimal
        # 3.1, and rendering at the document's precision would write "3.1+".
        readme = self.write("README.md", "Python 3.9+ is required. <!-- asof:floor -->")
        self.write("asof.ini", f"[floor]\nrun = {echo('3.10')}\n")
        cfg = config.load(self.root)
        st = state.State.load(self.root)
        results = core.check(self.root, cfg, st, now=self.now)
        self.assertEqual(results[0].suggestion, "3.10")
        core.update(self.root, results, st, self.now)
        self.assertIn("Python 3.10+", readme.read_text(encoding="utf-8"))

    def test_an_unknown_type_is_a_config_error(self):
        self.write("asof.ini", "[floor]\ntype = semver-ish\n")
        with self.assertRaises(config.ConfigError):
            config.load(self.root)

    def test_type_number_is_accepted_as_the_default(self):
        self.write("asof.ini", "[floor]\ntype = number\n")
        self.assertEqual(config.load(self.root).claims["floor"].kind, "")


class TestOrphans(Base):
    def test_configured_but_unmarked(self):
        self.write("asof.ini", "[ghost]\nevery = 30d\n")
        results, _ = self.run_check()
        self.assertIs(results["ghost"].status, Status.ORPHAN)
        self.assertIn("no marker for it exists yet", results["ghost"].message)

    def test_a_deleted_marker_says_what_was_lost(self):
        # The failure that matters: somebody edits the sentence, the marker
        # goes with it, and the number stops being watched by anyone.
        self.write("README.md", "The cap is 20 calls/hour. <!-- asof:cap -->")
        self.write("asof.ini", "[cap]\nevery = 90d\n")
        self.run_check()
        self.write("README.md", "The cap is 20 calls/hour.")
        results, _ = self.run_check()
        self.assertIs(results["cap"].status, Status.ORPHAN)
        self.assertIn("was removed", results["cap"].message)
        self.assertIn("20", results["cap"].message)


class TestExitCodes(Base):
    def test_drift_fails_error_fails_harder(self):
        drift = core.Result("a", config.Claim("a"), Status.DRIFT)
        error = core.Result("b", config.Claim("b"), Status.ERROR)
        ok = core.Result("c", config.Claim("c"), Status.OK)
        self.assertEqual(core.exit_code([ok], core.FAILING), 0)
        self.assertEqual(core.exit_code([drift], core.FAILING), 1)
        self.assertEqual(core.exit_code([drift, error], core.FAILING), 2)
        self.assertEqual(core.exit_code([drift, error], set()), 0)


class TestConfig(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(config.parse_duration("30d"), 30 * 86400)
        self.assertEqual(config.parse_duration("1w 3d"), 10 * 86400)
        self.assertEqual(config.parse_duration("12h"), 12 * 3600)

    def test_bad_duration(self):
        with self.assertRaises(config.ConfigError):
            config.parse_duration("30 months")

    def test_format_duration(self):
        self.assertEqual(config.format_duration(86400 * 45), "45d")
        self.assertEqual(config.format_duration(3600 * 5), "5h")


class TestReport(Base):
    def test_renders_every_status_without_blowing_up(self):
        results = [
            core.Result(name, config.Claim(name, every=86400, why="because"), status,
                        document="47", age=43200)
            for name, status in zip(string.ascii_lowercase, Status)
        ]
        html = report.render(results, "demo")
        self.assertIn("<title>", html)
        for status in Status:
            self.assertIn(report.LABEL[status], html)
            self.assertIn(report.BLURB[status], html)

    def test_every_colour_is_defined_before_a_theme_block_redefines_it(self):
        # A token that only exists inside a media query renders one theme's
        # text on the other theme's ground.
        css = report.CSS
        base = css[css.index(":root{"):css.index("@media")]
        declared = set(re.findall(r"(--[a-z-]+):", base))
        used = set(re.findall(r"var\((--[a-z-]+)\)", css))
        self.assertEqual(used - declared, set())

    def test_both_themes_define_the_same_tokens(self):
        blocks = re.findall(r"\{([^{}]*--[a-z-]+:[^{}]*)\}", report.CSS)
        token_sets = [set(re.findall(r"(--[a-z-]+):", b)) for b in blocks]
        colours = [s for s in token_sets if "--ink" in s]
        self.assertEqual(len(colours), 3, "expected light, media-dark and stamped-dark")
        self.assertEqual(colours[1], colours[2])
        self.assertTrue(colours[1] <= colours[0])

    def test_the_body_paints_its_own_background(self):
        self.assertIn("background:var(--paper)", report.CSS)

    def test_escapes_document_values(self):
        claim = config.Claim("x", why="<script>alert(1)</script>")
        html = report.render([core.Result("x", claim, Status.OK, document="<b>")], "t")
        self.assertNotIn("<script>", html)


if __name__ == "__main__":
    unittest.main()
