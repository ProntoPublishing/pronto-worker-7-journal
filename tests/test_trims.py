"""
Trim registry tests — vendored alongside trims.py, identical in every
worker repo (imprint.py/qa.py pattern). Pins the registry's invariants
and the reference math against the fleet's established goldens.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import trims
from trims import (COLORING_TRIMS, COVER_TRIMS, GUTTER_BRACKETS,
                   INTERIOR_GEOMETRY, INTERIOR_TRIM_NAMES, INTERIOR_TRIMS,
                   JOURNAL_TRIMS, KDPPACK_TRIMS, PAPER_FACTORS_IN_PER_PAGE,
                   SPELLING_TO_NAME, TRIMS, build_literal_table,
                   canonical_by_dims, canonical_name, cover_dims_in,
                   gutter_floor_in, parse_trim_literal, spine_width_in)


class TestRegistry(unittest.TestCase):
    def test_locked_menu_present(self):
        self.assertEqual(
            set(TRIMS),
            {"5x8", "5.25x8", "5.5x8.5", "6x9", "6.14x9.21", "7x10",
             "8x10", "8.5x11", "8.25x11", "8.5x8.5"})

    def test_dims(self):
        self.assertEqual(TRIMS["6x9"].dims, (6.0, 9.0))
        self.assertEqual(TRIMS["5x8"].dims, (5.0, 8.0))
        self.assertEqual(TRIMS["5.25x8"].dims, (5.25, 8.0))
        self.assertEqual(TRIMS["5.5x8.5"].dims, (5.5, 8.5))
        self.assertEqual(TRIMS["6.14x9.21"].dims, (6.14, 9.21))
        self.assertEqual(TRIMS["8.25x11"].dims, (8.25, 11.0))

    def test_four_spelling_families_each(self):
        for spec in TRIMS.values():
            spellings = spec.spellings()
            self.assertEqual(len(spellings), 4, spec.name)
            self.assertEqual(spellings[0], spec.name)   # canonical = bare
            self.assertIn(" x ", spellings[1])
            self.assertIn('" x ', spellings[2])
            self.assertIn("×", spellings[3])

    def test_no_spelling_collisions(self):
        all_spellings = [s for spec in TRIMS.values()
                         for s in spec.spellings()]
        self.assertEqual(len(all_spellings), len(set(all_spellings)))
        self.assertEqual(len(SPELLING_TO_NAME), len(all_spellings))

    def test_known_literals_resolve(self):
        # The three legacy spelling families every worker accepted...
        for lit in ('6x9', '6" x 9"', '6" × 9"'):
            self.assertEqual(canonical_name(lit), "6x9", lit)
        # ...plus W7's bare-space family, now unified fleet-wide.
        self.assertEqual(canonical_name("6 x 9"), "6x9")
        self.assertEqual(canonical_name('8.5" × 11"'), "8.5x11")
        self.assertIsNone(canonical_name("4x6"))
        self.assertIsNone(canonical_name(None))


class TestSubsets(unittest.TestCase):
    def test_subset_membership(self):
        self.assertIn('5" × 8"', INTERIOR_TRIMS)
        self.assertIn('6.14" × 9.21"', INTERIOR_TRIMS)
        self.assertNotIn("8.5x11", INTERIOR_TRIMS)   # low-content only
        self.assertIn("8.5x11", COVER_TRIMS)
        self.assertEqual(COVER_TRIMS, KDPPACK_TRIMS)
        # Low-content lanes unchanged: three trims each.
        self.assertEqual(len(JOURNAL_TRIMS), 3 * 4)
        self.assertEqual(len(COLORING_TRIMS), 3 * 4)
        self.assertNotIn("5x8", JOURNAL_TRIMS)
        self.assertNotIn("5x8", COLORING_TRIMS)

    def test_dormant_trims_in_no_subset(self):
        for lit in ("8.25x11", "8.5x8.5", "7x10", '7" × 10"'):
            for table in (INTERIOR_TRIMS, COVER_TRIMS, KDPPACK_TRIMS,
                          JOURNAL_TRIMS, COLORING_TRIMS):
                self.assertNotIn(lit, table)

    def test_all_spellings_agree_on_dims(self):
        for table in (INTERIOR_TRIMS, COVER_TRIMS, JOURNAL_TRIMS,
                      COLORING_TRIMS):
            for literal, dims in table.items():
                self.assertEqual(
                    dims, TRIMS[SPELLING_TO_NAME[literal]].dims, literal)

    def test_canonical_by_dims(self):
        m = canonical_by_dims(("6x9", "8x10", "8.5x11"))
        self.assertEqual(m[(6.0, 9.0)], "6x9")
        self.assertEqual(m[(8.5, 11.0)], "8.5x11")
        self.assertEqual(len(m), 3)

    def test_parse_trim_literal(self):
        self.assertEqual(parse_trim_literal('5" × 8"', INTERIOR_TRIMS),
                         (5.0, 8.0))
        self.assertIsNone(parse_trim_literal("8.5x11", INTERIOR_TRIMS))
        self.assertIsNone(parse_trim_literal("", INTERIOR_TRIMS))
        self.assertIsNone(parse_trim_literal(None, INTERIOR_TRIMS))


class TestInteriorGeometry(unittest.TestCase):
    def test_rows_cover_interior_subset(self):
        self.assertEqual(set(INTERIOR_GEOMETRY), set(INTERIOR_TRIM_NAMES))

    def test_uniform_margins_ruling(self):
        for g in INTERIOR_GEOMETRY.values():
            self.assertEqual((g.top_in, g.bottom_in, g.inner_in, g.outer_in),
                             (0.75, 0.85, 0.85, 0.65), g.trim_name)

    def test_measures(self):
        expect = {"5x8": 3.50, "5.25x8": 3.75, "5.5x8.5": 4.00,
                  "6x9": 4.50, "6.14x9.21": 4.64}
        for name, m in expect.items():
            self.assertAlmostEqual(
                INTERIOR_GEOMETRY[name].text_measure_in, m, places=4)

    def test_title_sinks(self):
        # 2in x (h/9), rounded to 0.05; 6x9 keeps the shipped 2.00 exactly.
        expect = {"5x8": 1.80, "5.25x8": 1.80, "5.5x8.5": 1.90,
                  "6x9": 2.00, "6.14x9.21": 2.05}
        for name, sink in expect.items():
            self.assertEqual(INTERIOR_GEOMETRY[name].title_sink_in, sink)


class TestReferenceMath(unittest.TestCase):
    def test_spine_factors(self):
        self.assertEqual(PAPER_FACTORS_IN_PER_PAGE,
                         {"white": 0.002252, "cream": 0.0025,
                          "premium color": 0.002347})

    def test_spine_width_matches_w3_golden(self):
        # W3 golden: 74pp cream -> 0.185in spine (Perennial).
        self.assertAlmostEqual(spine_width_in(74, "cream"), 0.185, places=6)
        self.assertAlmostEqual(spine_width_in(74, ""), 0.185, places=6)

    def test_cover_dims_match_w3_golden(self):
        # Perennial: 6x9, spine 0.185 -> 12.435 x 9.25 full wrap.
        w, h = cover_dims_in((6.0, 9.0), 0.185)
        self.assertAlmostEqual(w, 12.435, places=6)
        self.assertAlmostEqual(h, 9.25, places=6)

    def test_gutter_brackets(self):
        for n, floor in ((24, 0.375), (150, 0.375), (151, 0.5), (300, 0.5),
                         (301, 0.625), (500, 0.625), (501, 0.75),
                         (700, 0.75), (701, 0.875), (828, 0.875)):
            self.assertEqual(gutter_floor_in(n), floor, n)
        self.assertIsNone(gutter_floor_in(23))
        self.assertIsNone(gutter_floor_in(829))

    def test_build_literal_table_shape(self):
        table = build_literal_table(("6x9",))
        self.assertEqual(len(table), 4)
        self.assertTrue(all(v == (6.0, 9.0) for v in table.values()))


if __name__ == "__main__":
    unittest.main()
