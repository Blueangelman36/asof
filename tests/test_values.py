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
        self.assertEqual(values.find_last("v2 handles 1,204 rps  <!-- ")[0], "1,204")

    def test_first_for_forward_markers(self):
        self.assertEqual(values.find_first(" --> 88 seats")[0], "88")

    def test_empty_quotes_are_not_values(self):
        self.assertIsNone(values.find_last('"""'))

    def test_dates(self):
        self.assertEqual(values.find_last("audited 2026-09-11 by ")[0], "2026-09-11")

    def test_nothing_to_find(self):
        self.assertIsNone(values.find_last("no numbers here "))


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
