import tempfile
import unittest
from pathlib import Path

from asof import config, scan, suggest


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

    def collect(self):
        cfg = config.load(self.root)
        markers = scan.scan_tree(self.root, cfg.include, cfg.exclude, cfg.fenced)
        claimed = {(m.path.as_posix(), m.line_no, m.start) for m in markers}
        return suggest.collect(self.root, cfg, claimed)

    def tokens(self):
        return [c.token for c in self.collect()]


class TestWhatGetsSuggested(Base):
    def test_a_number_repeated_in_config_outranks_one_that_is_not(self):
        self.write("README.md", "The dashboard listens on 8420 by default.\n"
                                "We also mention 7314 once, in passing.")
        self.write("config.toml", "dashboard_port = 8420")
        found = self.collect()
        self.assertEqual(found[0].token, "8420")
        self.assertIn("other file", " ".join(found[0].reasons))

    def test_code_in_a_config_file_is_evidence_but_never_a_suggestion(self):
        self.write("README.md", "The dashboard listens on 8420 by default.")
        self.write("config.toml", "dashboard_port = 8420")
        self.assertEqual([c.where for c in self.collect()], ["README.md:1"])

    def test_an_already_claimed_number_is_not_suggested_again(self):
        self.write("README.md", "The dashboard listens on 8420. <!-- asof:port -->")
        self.write("config.toml", "dashboard_port = 8420")
        self.assertNotIn("8420", self.tokens())

    def test_fenced_examples_are_not_suggested(self):
        self.write("README.md", "```\nport = 8420\n```\n")
        self.write("config.toml", "dashboard_port = 8420")
        self.assertEqual(self.collect(), [])

    def test_ip_addresses_do_not_become_two_suggestions(self):
        self.write("README.md", "Bind address is 127.0.0.1 and the port is 8420.")
        self.write("config.toml", "port = 8420")
        self.assertNotIn("127.0", self.tokens())
        self.assertNotIn("0.1", self.tokens())

    def test_semver_is_one_identifier_not_a_pile_of_numbers(self):
        self.write("README.md", "We ship version 1.2.3 of the schema right now.")
        self.assertEqual(self.tokens(), [])

    def test_the_same_value_in_three_places_is_one_suggestion(self):
        self.write("README.md", "Windows are 24h wide.\nThe 24h view is default.\n"
                                "A 24h range is plenty.")
        found = [c for c in self.collect() if c.token == "24h"]
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0].sites), 2)


class TestRanking(Base):
    def test_a_round_number_everywhere_is_not_treated_as_corroborated(self):
        self.write("README.md", "It resolves 50% of traffic without credits.")
        for name in ("a.css", "b.py", "c.js"):
            self.write(name, "x = 50")
        reasons = " ".join(self.collect()[0].reasons)
        self.assertIn("round number", reasons)
        self.assertNotIn("must agree", reasons)

    def test_a_distinctive_number_elsewhere_is_corroboration(self):
        self.write("README.md", "The tolerance is 2.5 kHz in the field.")
        self.write("aliases.toml", "tolerance_hz = 2500")
        reasons = " ".join(self.collect()[0].reasons)
        self.assertIn("must agree", reasons)

    def test_a_value_in_very_many_files_is_a_constant_not_a_claim(self):
        self.write("README.md", "The buffer holds 1024 frames at a time.")
        for i in range(8):
            self.write(f"src/mod{i}.py", "SIZE = 1024")
        reasons = " ".join(self.collect()[0].reasons)
        self.assertIn("constant, not a claim", reasons)

    def test_numbered_list_items_are_pushed_down(self):
        self.write("README.md", "1. First step here.\n\nWe support 4,200 tenants today.")
        self.assertEqual(self.collect()[0].token, "4,200")

    def test_nothing_worth_saying_yields_nothing(self):
        self.write("README.md", "1. one\n2. two\n3. three\n")
        self.assertEqual(self.collect(), [])


class TestSuggestedNames(unittest.TestCase):
    def name(self, line, needle):
        start = line.index(needle)
        return suggest._name_from_context(line, start, start + len(needle))

    def test_the_noun_after_the_number(self):
        self.assertEqual(self.name("We support 47 integrations today.", "47"),
                         "integrations-today")

    def test_stopwords_are_skipped(self):
        self.assertEqual(self.name("and with 100% of the traffic", "100%"), "traffic")

    def test_a_closing_bracket_means_look_backwards(self):
        self.assertEqual(self.name("tolerance (default 2.5 kHz) because it drifts",
                                   "2.5 kHz"), "tolerance-default")

    def test_no_real_word_either_side_gives_a_placeholder(self):
        self.assertEqual(suggest._name_from_context("| 12 |", 2, 4), "NAME")


class TestPasteReadyMarkers(Base):
    def marker_for(self, filename):
        self.write(filename, "The limit is 4,200 requests per second.")
        return self.collect()[0].marker

    def test_markdown_gets_an_html_comment(self):
        self.assertTrue(self.marker_for("README.md").startswith("<!-- asof:"))

    def test_html_gets_an_html_comment(self):
        self.assertTrue(self.marker_for("page.html").startswith("<!-- asof:"))

    def test_plain_text_falls_back_to_a_hash(self):
        self.assertTrue(self.marker_for("NOTES.txt").startswith("# asof:"))

    def test_the_marker_it_suggests_actually_binds_that_value(self):
        # Paste the suggestion in and the scanner must find the number it named.
        self.write("README.md", "We support 4,200 tenants today.")
        candidate = self.collect()[0]
        line = f"We support 4,200 tenants today.  {candidate.marker}"
        markers = scan.scan_text(line, Path("README.md"))
        self.assertEqual([(m.name, m.token) for m in markers],
                         [(candidate.suggested_name, "4,200")])


if __name__ == "__main__":
    unittest.main()
