import tempfile
import unittest
from pathlib import Path

from asof import config, scan


def names(markers):
    return [(m.name, m.token) for m in markers]


class TestScanText(unittest.TestCase):
    def test_binds_the_value_before_it(self):
        got = scan.scan_text("We support 47 integrations.  <!-- asof:integrations -->",
                             Path("a.md"))
        self.assertEqual(names(got), [("integrations", "47")])

    def test_works_in_any_comment_syntax(self):
        text = "\n".join([
            "TIMEOUT_MS = 250   # asof:p99",
            "replicas: 12  # asof:replicas",
            "const seats = 4_000;  // asof:seats",
        ])
        got = dict(names(scan.scan_text(text, Path("a.txt"))))
        self.assertEqual(got["p99"], "250")
        self.assertEqual(got["replicas"], "12")

    def test_forward_marker(self):
        got = scan.scan_text("<!-- asof:seats> --> 1,204 seats", Path("a.md"))
        self.assertEqual(names(got), [("seats", "1,204")])
        self.assertTrue(got[0].forward)

    def test_marker_without_a_value_is_ignored(self):
        self.assertEqual(scan.scan_text("nothing here  # asof:ghost", Path("a.txt")), [])

    def test_dotted_and_dashed_names(self):
        got = scan.scan_text("9 # asof:prod.web-servers", Path("a.txt"))
        self.assertEqual(got[0].name, "prod.web-servers")

    def test_off_switch_disables_the_file(self):
        text = "asof:off\nWe support 47 things. <!-- asof:things -->"
        self.assertEqual(scan.scan_text(text, Path("a.md")), [])

    def test_off_does_not_swallow_similar_names(self):
        got = scan.scan_text("3 # asof:offices", Path("a.txt"))
        self.assertEqual(got[0].name, "offices")


class TestMarkdownFences(unittest.TestCase):
    SAMPLE = "\n".join([
        "We support 47 integrations. <!-- asof:integrations -->",
        "",
        "```markdown",
        "We support 9999 widgets. <!-- asof:example -->",
        "```",
        "",
        "And 12 more. <!-- asof:more -->",
    ])

    def test_fences_are_skipped_in_markdown(self):
        got = names(scan.scan_text(self.SAMPLE, Path("R.md")))
        self.assertEqual(got, [("integrations", "47"), ("more", "12")])

    def test_fences_can_be_opted_back_in(self):
        got = names(scan.scan_text(self.SAMPLE, Path("R.md"), fenced=True))
        self.assertEqual(len(got), 3)

    def test_fences_only_apply_to_markdown(self):
        got = names(scan.scan_text(self.SAMPLE, Path("R.txt")))
        self.assertEqual(len(got), 3)

    def test_tilde_fences(self):
        text = "~~~\n5 <!-- asof:hidden -->\n~~~\n7 <!-- asof:shown -->"
        self.assertEqual(names(scan.scan_text(text, Path("R.md"))), [("shown", "7")])


class TestInlineCode(unittest.TestCase):
    def test_markers_in_code_spans_are_documentation(self):
        text = "Write `asof:NAME` in a comment. We have 47 of them. <!-- asof:real -->"
        self.assertEqual(names(scan.scan_text(text, Path("R.md"))), [("real", "47")])

    def test_off_inside_code_spans_does_not_disable_the_file(self):
        # The README explains `asof:off`. That must not switch the README off.
        text = "Put `asof:off` in a file to skip it.\n\nWe have 47 things. <!-- asof:things -->"
        self.assertEqual(names(scan.scan_text(text, Path("R.md"))), [("things", "47")])

    def test_off_outside_code_spans_still_disables_the_file(self):
        text = "asof:off\n\nWe have 47 things. <!-- asof:things -->"
        self.assertEqual(scan.scan_text(text, Path("R.md")), [])

    def test_a_value_inside_backticks_is_still_a_value(self):
        text = "We have `47` integrations. <!-- asof:integrations -->"
        self.assertEqual(names(scan.scan_text(text, Path("R.md"))), [("integrations", "47")])

    def test_masking_preserves_columns(self):
        line = "a `code` b 47 c"
        self.assertEqual(len(scan._mask_inline_code(line)), len(line))

    def test_a_code_span_wrapped_onto_the_next_line_is_still_code(self):
        # asof's own README wraps a long example across a line break. Masking
        # line by line would turn that example into two real claims.
        text = ("share a line the same way: `20<!-- asof:per-hour --> calls/hour,\n"
                "200<!-- asof:per-day -->/day`.\n"
                "\n"
                "We have 47 things. <!-- asof:things -->")
        self.assertEqual(names(scan.scan_text(text, Path("R.md"))), [("things", "47")])

    def test_masking_preserves_line_structure(self):
        text = "a `one\ntwo` b\nc 47 d"
        self.assertEqual(scan._mask_inline_code(text).count("\n"), text.count("\n"))
        self.assertEqual(len(scan._mask_inline_code(text)), len(text))

    def test_a_stray_backtick_does_not_swallow_the_document(self):
        text = "an unmatched ` tick\n\nWe have 47 things. <!-- asof:things -->"
        self.assertEqual(names(scan.scan_text(text, Path("R.md"))), [("things", "47")])

    def test_code_spans_only_matter_in_markdown(self):
        text = "x = 3  # see `asof:pinned`"
        self.assertEqual(names(scan.scan_text(text, Path("a.py"))), [("pinned", "3")])


class TestTreeAndRewrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_scan_tree_finds_across_files(self):
        self.write("README.md", "We have 47 integrations. <!-- asof:integrations -->")
        self.write("docs/one.md", "Also 47 integrations. <!-- asof:integrations -->")
        self.write("noise.bin", "\x00\x01binary asof:nope")
        got = scan.scan_tree(self.root, [], [])
        self.assertEqual(len(got), 2)

    def test_include_and_exclude(self):
        self.write("README.md", "8 <!-- asof:a -->")
        self.write("CHANGELOG.md", "9 <!-- asof:b -->")
        self.assertEqual(len(scan.scan_tree(self.root, ["README.md"], [])), 1)
        self.assertEqual(len(scan.scan_tree(self.root, [], ["CHANGELOG.md"])), 1)

    def test_generated_lockfiles_are_not_scanned(self):
        # A lockfile is thousands of numbers and integrity hashes, none of them
        # a claim, and mining one dominated the runtime of a small repo.
        self.write("README.md", "We have 47 things. <!-- asof:a -->")
        for name in ("package-lock.json", "pnpm-lock.yaml", "npm-shrinkwrap.json",
                     "go.sum", "yarn.lock", "app/package-lock.json"):
            self.write(name, "47 <!-- asof:junk -->")
        found = {m.name for m in scan.scan_tree(self.root, [], config.DEFAULT_EXCLUDE)}
        self.assertEqual(found, {"a"})

    def test_an_exclude_matches_by_name_anywhere(self):
        self.write("README.md", "8 <!-- asof:a -->")
        self.write("deep/nested/notes.md", "9 <!-- asof:b -->")
        found = {m.name for m in scan.scan_tree(self.root, [], ["notes.md"])}
        self.assertEqual(found, {"a"})

    def test_skips_dot_git(self):
        self.write(".git/config", "8 # asof:a")
        self.assertEqual(scan.scan_tree(self.root, [], []), [])

    def test_skips_a_virtualenv_whatever_it_is_called(self):
        # Found by installing asof from a public URL into a venv named `v`:
        # it scanned its own installed source and invented a claim from the
        # example in its help text.
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.write("v/pyvenv.cfg", "home = /usr/bin")
        self.write("v/Lib/site-packages/other/cli.py", "8420  # asof:borrowed")
        found = [m.name for m in scan.scan_tree(self.root, [], [])]
        self.assertEqual(found, ["things"])

    def test_skips_site_packages_even_without_a_venv_marker(self):
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.write("lib/site-packages/dep/readme.md", "9000 <!-- asof:theirs -->")
        found = [m.name for m in scan.scan_tree(self.root, [], [])]
        self.assertEqual(found, ["things"])

    def test_a_project_that_is_itself_a_venv_root_still_scans(self):
        # pyvenv.cfg at the root means the user pointed asof at a venv on
        # purpose; refusing to scan anything at all would be unhelpful.
        self.write("pyvenv.cfg", "home = /usr/bin")
        self.write("README.md", "We have 47 things. <!-- asof:things -->")
        self.assertEqual([m.name for m in scan.scan_tree(self.root, [], [])], ["things"])

    def test_rewrite_touches_only_the_value(self):
        path = self.write("README.md", "We have 1,247 users today.  <!-- asof:users -->\ntail\n")
        marker = scan.scan_tree(self.root, [], [])[0]
        scan.rewrite(self.root, marker, "1,389")
        self.assertEqual(path.read_text(encoding="utf-8"),
                         "We have 1,389 users today.  <!-- asof:users -->\ntail\n")

    def rewrite_bytes(self, raw: bytes, new_token: str = "1,389") -> bytes:
        (self.root / "README.md").write_bytes(raw)
        marker = scan.scan_tree(self.root, [], [])[0]
        scan.rewrite(self.root, marker, new_token)
        return (self.root / "README.md").read_bytes()

    def test_rewrite_keeps_crlf_line_endings(self):
        raw = b"# Notes\r\n\r\nWe have 1,247 users. <!-- asof:users -->\r\nlast\r\n"
        self.assertEqual(
            self.rewrite_bytes(raw),
            b"# Notes\r\n\r\nWe have 1,389 users. <!-- asof:users -->\r\nlast\r\n")

    def test_rewrite_keeps_trailing_whitespace_and_tabs(self):
        raw = b"We have 1,247 users. <!-- asof:users -->   \n\tindented \n"
        self.assertEqual(
            self.rewrite_bytes(raw),
            b"We have 1,389 users. <!-- asof:users -->   \n\tindented \n")

    def test_rewrite_keeps_a_missing_final_newline(self):
        raw = b"We have 1,247 users. <!-- asof:users -->"
        self.assertFalse(self.rewrite_bytes(raw).endswith(b"\n"))

    def test_rewrite_keeps_mixed_line_endings(self):
        raw = b"crlf line\r\nWe have 1,247 users. <!-- asof:users -->\nlf line\n"
        self.assertEqual(
            self.rewrite_bytes(raw),
            b"crlf line\r\nWe have 1,389 users. <!-- asof:users -->\nlf line\n")

    def test_rewrite_changes_exactly_the_value_bytes(self):
        raw = b"We have 1,247 users. <!-- asof:users -->\r\n"
        out = self.rewrite_bytes(raw, "1,389")
        self.assertEqual(len(out), len(raw))
        self.assertEqual(sum(a != b for a, b in zip(raw, out)), 3)  # 247 -> 389

    def test_rewrite_refuses_when_the_file_moved(self):
        self.write("README.md", "We have 1,247 users. <!-- asof:users -->")
        marker = scan.scan_tree(self.root, [], [])[0]
        self.write("README.md", "Completely different 5 text. <!-- asof:users -->")
        with self.assertRaises(ValueError):
            scan.rewrite(self.root, marker, "1,389")


if __name__ == "__main__":
    unittest.main()
