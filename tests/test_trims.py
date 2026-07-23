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
from trims import (BINDING_HARDCOVER, BINDING_PAPERBACK, COLORING_TRIMS,
                   COVER_TRIMS, GUTTER_BRACKETS, HARDCOVER_TRIM_NAMES,
                   HARDCOVER_TRIMS, HC_MAX_PAGES, HC_MIN_PAGES,
                   INTERIOR_GEOMETRY, INTERIOR_TRIM_NAMES, INTERIOR_TRIMS,
                   INTERIOR_TRIMS_BY_BINDING, JOURNAL_TRIMS, KDPPACK_TRIMS,
                   PAPER_FACTORS_IN_PER_PAGE, SPELLING_TO_NAME, TRIMS,
                   build_literal_table, canonical_by_dims, canonical_name,
                   cover_dims_in, gutter_floor_in, hardcover_cover_dims_in,
                   hardcover_panel_dims_in, hardcover_spine_width_in,
                   interior_page_bounds, parse_trim_literal, spine_width_in)


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

    def test_unshipped_trims_out_of_paperback_subsets(self):
        # 7x10 + 8.25x11 are LIVE for hardcover only (Hardcover v0);
        # 8.5x8.5 stays dormant everywhere.
        for lit in ("8.25x11", "8.5x8.5", "7x10", '7" × 10"'):
            for table in (INTERIOR_TRIMS, COVER_TRIMS, KDPPACK_TRIMS,
                          JOURNAL_TRIMS, COLORING_TRIMS):
                self.assertNotIn(lit, table)
        self.assertIn("7x10", HARDCOVER_TRIMS)
        self.assertIn('8.25" × 11"', HARDCOVER_TRIMS)
        self.assertNotIn("8.5x8.5", HARDCOVER_TRIMS)
        self.assertNotIn("5x8", HARDCOVER_TRIMS)     # no 5x8 hardcover at KDP
        self.assertEqual(len(HARDCOVER_TRIMS), 5 * 4)

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
    def test_rows_cover_both_bindings(self):
        self.assertEqual(set(INTERIOR_GEOMETRY),
                         set(INTERIOR_TRIM_NAMES) | set(HARDCOVER_TRIM_NAMES))

    def test_uniform_margins_ruling_trade_sizes(self):
        for name in INTERIOR_TRIM_NAMES:
            g = INTERIOR_GEOMETRY[name]
            self.assertEqual((g.top_in, g.bottom_in, g.inner_in, g.outer_in),
                             (0.75, 0.85, 0.85, 0.65), name)
            self.assertEqual((g.class_pt, g.leading_stretch), (11, 1.066), name)

    def test_big_trim_12pt_ruling(self):
        g7 = INTERIOR_GEOMETRY["7x10"]
        self.assertEqual((g7.class_pt, g7.inner_in, g7.outer_in,
                          g7.leading_stretch), (12, 1.0, 0.8, 1.066))
        self.assertAlmostEqual(g7.text_measure_in, 5.2, places=4)
        g8 = INTERIOR_GEOMETRY["8.25x11"]
        self.assertEqual((g8.class_pt, g8.inner_in, g8.outer_in,
                          g8.leading_stretch), (12, 1.35, 1.35, 1.15))
        self.assertAlmostEqual(g8.text_measure_in, 5.55, places=4)

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


class TestHardcoverKDPGoldens(unittest.TestCase):
    """Every value pinned here was returned by KDP's own cover
    calculator (measurements-table sweep, 2026-07-23). Our functions
    must reproduce the calculator to its displayed 3dp."""

    # (page_count, paper) -> KDP spine width (in)
    SPINE_GOLDENS = {
        (76, "white"): 0.360, (100, "white"): 0.414, (110, "white"): 0.437,
        (150, "white"): 0.527, (151, "white"): 0.529, (200, "white"): 0.639,
        (250, "white"): 0.752, (300, "white"): 0.865, (400, "white"): 1.090,
        (500, "white"): 1.315, (550, "white"): 1.428,
        (200, "cream"): 0.689, (200, "premium color"): 0.658,
    }

    # trim name -> KDP full cover (w, h) at 200pp white
    FULL_GOLDENS = {
        "5.5x8.5": (13.214, 9.917),
        "6x9": (14.214, 10.417),
        "6.14x9.21": (14.494, 10.627),
        "7x10": (16.214, 11.417),
        "8.25x11": (18.714, 12.417),
    }

    def test_spine_matches_calculator(self):
        for (pc, paper), golden in self.SPINE_GOLDENS.items():
            ours = hardcover_spine_width_in(pc, paper)
            self.assertAlmostEqual(round(ours, 3), golden, places=3,
                                   msg=f"{pc}pp {paper}")

    def test_full_cover_matches_calculator(self):
        spine = hardcover_spine_width_in(200, "white")
        for name, (gw, gh) in self.FULL_GOLDENS.items():
            w, h = hardcover_cover_dims_in(TRIMS[name].dims, spine)
            self.assertAlmostEqual(round(w, 3), gw, places=3, msg=name)
            self.assertAlmostEqual(round(h, 3), gh, places=3, msg=name)

    def test_panel_matches_calculator(self):
        # KDP front cover row: 6.197 x 9.236 for 6x9.
        pw, ph = hardcover_panel_dims_in((6.0, 9.0))
        self.assertAlmostEqual(round(pw, 3), 6.197, places=3)
        self.assertAlmostEqual(round(ph, 3), 9.236, places=3)

    def test_bounds_from_calculator_config(self):
        self.assertEqual((HC_MIN_PAGES, HC_MAX_PAGES), (76, 550))
        self.assertEqual(interior_page_bounds(BINDING_HARDCOVER), (76, 550))
        self.assertEqual(interior_page_bounds(BINDING_PAPERBACK), (24, 828))

    def test_binding_subsets(self):
        self.assertIs(INTERIOR_TRIMS_BY_BINDING[BINDING_PAPERBACK],
                      INTERIOR_TRIMS)
        self.assertIs(INTERIOR_TRIMS_BY_BINDING[BINDING_HARDCOVER],
                      HARDCOVER_TRIMS)


if __name__ == "__main__":
    unittest.main()
