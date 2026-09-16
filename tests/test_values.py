import unittest

from asof import values


class TestParse(unittest.TestCase):
    def test_plain_integer(self):
        v = values.parse("47")
        self.assertEqual(v.number, 47)
        self.assertEqual(v.scaled, 47)
        self.assertFalse(v.grouped)

    def test_grouped(self):
        v = values.parse("1,247")
        self.assertEqual(v.number, 1247)
        self.assertTrue(v.grouped)

    def test_multiplier(self):
        self.assertEqual(values.parse("10.4k").scaled, 10400)
        self.assertEqual(values.parse("1.2M").scaled, 1_200_000)
        self.assertEqual(values.parse("2B").scaled, 2_000_000_000)

    def test_multiplier_with_unit(self):
        v = values.parse("1.2GB")
        self.assertEqual(v.multiplier, "G")
        self.assertEqual(v.unit, "B")
        self.assertEqual(v.scaled, 1.2e9)

    def test_lowercase_m_is_not_mega(self):
        v = values.parse("250ms")
        self.assertEqual(v.multiplier, "")
        self.assertEqual(v.unit, "ms")
        self.assertEqual(v.scaled, 250)

    def test_percent(self):
        v = values.parse("99.9%")
        self.assertEqual(v.unit, "%")
        self.assertEqual(v.decimals, 1)

    def test_non_numeric(self):
        v = values.parse('"blue"')
        self.assertFalse(v.numeric)
        self.assertIsNone(v.scaled)

    def test_negative(self):
        self.assertEqual(values.parse("-3.5").number, -3.5)


class TestRenderLike(unittest.TestCase):
    def test_keeps_grouping(self):
        self.assertEqual(values.render_like(1389, values.parse("1,247")), "1,389")

    def test_keeps_multiplier(self):
        self.assertEqual(values.render_like(12400, values.parse("10.4k")), "12.4k")

    def test_keeps_unit_and_decimals(self):
        self.assertEqual(values.render_like(312, values.parse("250ms")), "312ms")
        self.assertEqual(values.render_like(99.42, values.parse("99.9%")), "99.4%")

    def test_keeps_space_and_rescales(self):
        # render_like takes a value in base units, so 5e9 bytes is "5 GB".
        self.assertEqual(values.render_like(5e9, values.parse("3 GB")), "5 GB")

    def test_grouping_with_decimals(self):
        self.assertEqual(values.render_like(1234567.8, values.parse("1,000.0")), "1,234,567.8")


class TestFind(unittest.TestCase):
    def test_last_wins(self):
        self.assertEqual(values.find_last("v2 handles 1,204 rps  <!-- ")[0], "1,204 rps")

    def test_first_for_forward_markers(self):
        self.assertEqual(values.find_first(" --> 88 seats")[0], "88")

    def test_empty_quotes_are_not_values(self):
        self.assertIsNone(values.find_last('"""'))

    def test_dates(self):
        self.assertEqual(values.find_last("audited 2026-09-11 by ")[0], "2026-09-11")

    def test_nothing_to_find(self):
        self.assertIsNone(values.find_last("no numbers here "))


class TestUnderscoreSeparators(unittest.TestCase):
    """Kotlin, Python, Rust and Java group thousands with underscores."""

    def tokens(self, text):
        return [t for t, _, _ in values.iter_values(text)]

    def test_an_underscored_literal_is_one_number(self):
        self.assertEqual(self.tokens("x = 18_000"), ["18_000"])
        self.assertEqual(values.parse("18_000").scaled, 18000)

    def test_several_groups(self):
        self.assertEqual(values.parse("1_000_000").scaled, 1_000_000)

    def test_it_matches_the_same_number_written_with_commas(self):
        self.assertTrue(values.compare(
            values.parse("18,000"), values.parse("18_000"), values.Tolerance("")))

    def test_an_identifier_is_not_a_number(self):
        # col_1_2 must not read as 1_2; groups have to be three digits.
        self.assertEqual(self.tokens("col_1_2 = 5"), ["1", "2", "5"])

    def test_a_trailing_identifier_number_still_reads(self):
        line = 'BELOW_18000("Below 18,000 ft", 18_000),'
        self.assertEqual(self.tokens(line), ["18000", '"Below 18,000 ft"', "18_000"])

    def test_updating_keeps_the_underscore_style(self):
        self.assertEqual(values.render_like(19500, values.parse("18_000")), "19_500")

    def test_updating_keeps_the_comma_style(self):
        self.assertEqual(values.render_like(1389, values.parse("1,247")), "1,389")


class TestVersions(unittest.TestCase):
    """A version is one value. Read as numbers, v3.10.0 claims 0."""

    def last(self, text):
        hit = values.find_last(text)
        return hit[0] if hit else None

    def same(self, a, b, kind=""):
        return values.compare(values.parse(a), values.parse(b), values.Tolerance(""), kind)

    # --- reading -----------------------------------------------------------

    def test_a_v_prefixed_version_is_one_token(self):
        self.assertEqual(self.last("Requires Python v3.10.0 or newer. "), "v3.10.0")

    def test_a_three_part_version_needs_no_prefix(self):
        self.assertEqual(self.last("Built against 3.10.0 today "), "3.10.0")

    def test_a_pre_release_is_part_of_the_version(self):
        self.assertEqual(self.last("Ships 2.4.1-rc.2 today "), "2.4.1-rc.2")

    def test_pep_440_pre_releases(self):
        self.assertEqual(self.last("Try 3.13.0rc1 now "), "3.13.0rc1")

    def test_build_metadata_is_part_of_the_version(self):
        self.assertEqual(self.last("Tagged 1.0.0+build.7 "), "1.0.0+build.7")

    def test_sentence_punctuation_is_not(self):
        self.assertEqual(self.last("Requires v3.10.0."), "v3.10.0")
        self.assertEqual(self.last("Requires v3.10.0, at least"), "v3.10.0")

    def test_a_runtime_name_glued_on_the_front(self):
        self.assertEqual(self.last("see /usr/lib/python3.10.4 "), "3.10.4")

    def test_a_v_inside_a_word_is_not_a_prefix(self):
        self.assertEqual(self.last("the dev3.1 branch "), "3.1")

    def test_an_address_is_one_token_and_the_port_still_reads(self):
        self.assertEqual(self.last("Bind 127.0.0.1:8420 "), "8420")
        tokens = [t for t, _, _ in values.iter_values("Bind 127.0.0.1 here")]
        self.assertEqual(tokens, ["127.0.0.1"])

    def test_a_quoted_version_is_still_a_version(self):
        v = values.parse('"3.10.0"')
        self.assertEqual(v.version, "3.10.0")
        self.assertEqual(v.quote, '"')

    def test_a_version_is_not_a_number(self):
        self.assertFalse(values.parse("v3.10.0").numeric)

    def test_plain_decimals_are_untouched(self):
        self.assertEqual(values.parse("2.5").number, 2.5)
        self.assertEqual(self.last("tolerance is 2.5 kHz here"), "2.5 kHz")

    # --- comparing ---------------------------------------------------------

    def test_prefix_and_quotes_do_not_matter(self):
        self.assertTrue(self.same("v3.10.0", '"3.10.0"'))
        self.assertTrue(self.same("V3.10.0", "3.10.0"))

    def test_a_trailing_zero_component_does_not_matter(self):
        self.assertTrue(self.same("v3.10", "3.10.0"))

    def test_build_metadata_does_not_matter(self):
        self.assertTrue(self.same("1.0.0+build.7", "v1.0.0"))

    def test_a_pre_release_does(self):
        self.assertFalse(self.same("2.4.1-rc.2", "2.4.1"))
        self.assertFalse(self.same("2.4.1-rc.2", "2.4.1-rc.3"))

    def test_components_compare_as_integers(self):
        self.assertFalse(self.same("v3.10.0", "3.1.0"))
        self.assertTrue(self.same("v03.010.0", "3.10.0"))

    def test_two_part_decimals_are_ambiguous_without_being_told(self):
        # 3.10 and 3.1 are the same decimal. Nothing in the text says which a
        # reader meant, so the default stays numeric - and says so here.
        self.assertTrue(self.same("3.10", "3.1"))

    def test_type_version_settles_the_ambiguity(self):
        self.assertFalse(self.same("3.10", "3.1", kind="version"))
        self.assertTrue(self.same("3.10", "3.10.0", kind="version"))

    def test_one_unmistakable_side_makes_both_versions(self):
        self.assertFalse(self.same("3.1", "v3.10"))

    # --- writing -----------------------------------------------------------

    def test_an_update_keeps_the_prefix(self):
        self.assertEqual(values.render_version_like(values.parse("3.11.0"),
                                                    values.parse("v3.10.0")), "v3.11.0")

    def test_an_update_keeps_the_quotes(self):
        self.assertEqual(values.render_version_like(values.parse("3.11.0"),
                                                    values.parse('"3.10.0"')), '"3.11.0"')

    def test_an_update_does_not_add_a_prefix_that_was_not_there(self):
        self.assertEqual(values.render_version_like(values.parse("v3.11.0"),
                                                    values.parse("3.10.0")), "3.11.0")


class TestFaithfulRendering(unittest.TestCase):
    """Rendering may round a value. It may not delete digits it was given."""

    def render(self, produced, template):
        return values.render_faithfully(values.parse(produced), values.parse(template))

    def test_rounding_to_the_documents_precision_still_happens(self):
        self.assertEqual(self.render("99.42", "99.9%"), "99.4%")

    def test_a_trailing_zero_is_not_rounding(self):
        # "3.10" at the document's one decimal is "3.1": same number, different
        # Python. Losing it is damage, not formatting.
        self.assertEqual(self.render("3.10", "3.9"), "3.10")

    def test_the_documents_style_survives(self):
        self.assertEqual(self.render("1389", "1,247"), "1,389")
        self.assertEqual(self.render("12400", "10.4k"), "12.4k")
        self.assertEqual(self.render("312", "250ms"), "312ms")

    def test_a_unit_is_kept_when_digits_are_preserved(self):
        self.assertEqual(self.render("2.50 kHz", "1.5 kHz"), "2.50 kHz")

    def test_extra_precision_that_changes_the_value_is_still_rounded(self):
        self.assertEqual(self.render("3.14159", "2.7"), "3.1")


class TestRangeDashes(unittest.TestCase):
    """A dash between two numbers is a range, not a minus sign."""

    def tokens(self, text):
        return [t for t, _, _ in values.iter_values(text)]

    def test_a_percentage_range(self):
        self.assertEqual(self.tokens("restricted to 50-99% here"), ["50", "99%"])

    def test_a_plain_range(self):
        self.assertEqual(self.tokens("takes 10-20 seconds"), ["10", "20"])

    def test_a_real_negative_survives(self):
        self.assertEqual(self.tokens("drift of -47 points"), ["-47"])

    def test_a_negative_after_a_word_survives(self):
        self.assertEqual(self.tokens("delta was -3.5 overall"), ["-3.5"])

    def test_the_span_still_matches_the_token(self):
        text = "restricted to 50-99% here"
        for token, start, end in values.iter_values(text):
            self.assertEqual(text[start:end], token)


class TestSpacedUnits(unittest.TestCase):
    """``2.5 kHz`` is one value; ``47 integrations`` is a value and a noun."""

    def find(self, text):
        hit = values.find_last(text)
        return hit[0] if hit else None

    def test_unit_after_a_space_is_part_of_the_value(self):
        self.assertEqual(self.find("tolerance (default 2.5 kHz) because"), "2.5 kHz")
        self.assertEqual(self.find("tail latency is 250 ms"), "250 ms")
        self.assertEqual(self.find("we store 1.2 GB per day"), "1.2 GB")
        self.assertEqual(self.find("resolved 99.9 % of traffic"), "99.9 %")

    def test_a_bare_noun_is_not_a_unit(self):
        self.assertEqual(self.find("We support 47 integrations."), "47")
        self.assertEqual(self.find("There are 12 customers today"), "12")
        self.assertEqual(self.find("84 unrecognised events collapsed"), "84")

    def test_a_bare_multiplier_after_a_space_counts(self):
        self.assertEqual(self.find("about 10 k requests"), "10 k")

    def test_spans_are_exact(self):
        text = "tolerance is 2.5 kHz here"
        token, start, end = values.find_last(text)
        self.assertEqual(text[start:end], token)

    def test_spaced_units_survive_a_round_trip(self):
        parsed = values.parse(self.find("tolerance is 2.5 kHz here"))
        self.assertEqual(parsed.scaled, 2500)
        self.assertEqual(values.render_like(3000, parsed), "3.0 kHz")

    def test_a_unit_already_attached_is_not_extended(self):
        self.assertEqual(self.find("250ms of budget"), "250ms")

    def test_quoted_values_and_dates_are_left_alone(self):
        self.assertEqual(self.find('effort = "low"'), '"low"')
        self.assertEqual(self.find("audited 2026-09-11 by hand"), "2026-09-11")

    def test_a_newline_is_not_a_space(self):
        self.assertEqual(self.find("we saw 47\nms of nothing"), "47")


class TestQuotedNumbers(unittest.TestCase):
    """Config files quote what prose writes bare. One claim spans both."""

    def test_a_quoted_number_is_a_number(self):
        v = values.parse('"99"')
        self.assertTrue(v.numeric)
        self.assertEqual(v.scaled, 99)
        self.assertEqual(v.quote, '"')

    def test_single_quotes_too(self):
        self.assertEqual(values.parse("'8420'").scaled, 8420)

    def test_html_attribute_matches_prose_percentage(self):
        # README: "restricted to 50-99%".  index.html: max="99"
        self.assertTrue(values.compare(
            values.parse("99%"), values.parse('"99"'), values.Tolerance("")))

    def test_toml_string_version_matches_bare_version(self):
        self.assertTrue(values.compare(
            values.parse("3.11"), values.parse('"3.11"'), values.Tolerance("")))

    def test_a_quoted_word_is_still_a_word(self):
        v = values.parse('"claude-opus-5"')
        self.assertFalse(v.numeric)
        self.assertTrue(values.compare(
            values.parse('"low"'), values.parse("low"), values.Tolerance("")))

    def test_updating_writes_back_inside_the_quotes(self):
        self.assertEqual(values.render_like(101, values.parse('"99"')), '"101"')
        self.assertEqual(values.render_like(8500, values.parse("'8420'")), "'8500'")


class TestTolerance(unittest.TestCase):
    def test_exact_by_default(self):
        t = values.Tolerance("")
        self.assertTrue(t.allows(10, 10))
        self.assertFalse(t.allows(10, 11))

    def test_absolute(self):
        t = values.Tolerance("5")
        self.assertTrue(t.allows(100, 104))
        self.assertFalse(t.allows(100, 106))

    def test_relative(self):
        t = values.Tolerance("10%")
        self.assertTrue(t.allows(100, 109))
        self.assertFalse(t.allows(100, 111))

    def test_plus_minus_sign(self):
        self.assertEqual(values.Tolerance("±5").amount, 5)


class TestCompare(unittest.TestCase):
    def test_formatting_is_irrelevant(self):
        self.assertTrue(values.compare(
            values.parse("1,247"), values.parse("1247"), values.Tolerance("")))

    def test_multiplier_is_irrelevant(self):
        self.assertTrue(values.compare(
            values.parse("10k"), values.parse("10000"), values.Tolerance("")))

    def test_mismatched_units_never_match(self):
        self.assertFalse(values.compare(
            values.parse("250ms"), values.parse("250s"), values.Tolerance("50%")))

    def test_strings_compare_loosely(self):
        self.assertTrue(values.compare(
            values.parse('"Blue"'), values.parse("blue"), values.Tolerance("")))


if __name__ == "__main__":
    unittest.main()
