"""
W7 trim expansion battery (W7_Trim_Expansion_WorkOrder_v0, 2026-07-19)
=======================================================================

The E2 standard, applied to journal interiors: the 6x9 goldens are
BYTE-locked (sha256 pinned below, captured on 7.1.0-a1 before the
change); the two added trims get their own geometry goldens (exact or
1e-6), page-size/parity/determinism checks per template family, and
the pinned-table hold keeps holding.
"""

import hashlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pypdf import PdfReader

from geometry import (
    ACCEPTED_TRIM_LITERALS, DOT_PITCH_BY_TRIM, DOT_PITCH_IN,
    LINE_PITCH_BY_TRIM, LINE_PITCH_IN, REFERENCE_TRIM, TRIM_CANONICAL,
    TRIM_TYPE_SCALE, TrimRejectedError, dot_grid_points, lined_rows,
    live_area, parse_trim,
)
from render import build_interior

from test_w7 import _make_processor

TRIMS = ((6.0, 9.0), (8.0, 10.0), (8.5, 11.0))


# ---------------------------------------------------------------------------
# Trim parse — pinned literals, three spellings each
# ---------------------------------------------------------------------------

class TestParseTrim(unittest.TestCase):
    def test_all_pinned_literals(self):
        for literal, dims in ACCEPTED_TRIM_LITERALS.items():
            self.assertEqual(parse_trim(literal), dims, literal)

    def test_v3_form_spellings_exact(self):
        # The exact strings the Tally v3 form writes to Book Metadata
        # (U+00D7 multiplication sign) — the string that held soak #1.
        self.assertEqual(parse_trim('8.5" × 11"'), (8.5, 11.0))
        self.assertEqual(parse_trim('8" × 10"'), (8.0, 10.0))
        self.assertEqual(parse_trim('6" × 9"'), (6.0, 9.0))

    def test_empty_defaults_to_reference(self):
        self.assertEqual(parse_trim(None), REFERENCE_TRIM)
        self.assertEqual(parse_trim(""), REFERENCE_TRIM)
        self.assertEqual(parse_trim("  "), REFERENCE_TRIM)

    def test_outside_table_raises(self):
        for bad in ("5x8", '5.5" x 8.5"', "7x10", "A4", "6x9 "  "junk"):
            with self.assertRaises(TrimRejectedError):
                parse_trim(bad)

    def test_canonical_names_cover_table(self):
        self.assertEqual(set(ACCEPTED_TRIM_LITERALS.values()),
                         set(TRIM_CANONICAL.keys()))


# ---------------------------------------------------------------------------
# Pitch + scale tables — exact fractions at the E2 factors
# ---------------------------------------------------------------------------

class TestPitchTables(unittest.TestCase):
    def test_reference_aliases_agree(self):
        self.assertEqual(LINE_PITCH_BY_TRIM[REFERENCE_TRIM], LINE_PITCH_IN)
        self.assertEqual(DOT_PITCH_BY_TRIM[REFERENCE_TRIM], DOT_PITCH_IN)

    def test_line_pitch_exact_fractions(self):
        self.assertEqual(LINE_PITCH_BY_TRIM[(6.0, 9.0)], 5.0 / 16.0)
        self.assertEqual(LINE_PITCH_BY_TRIM[(8.0, 10.0)], 3.0 / 8.0)
        self.assertEqual(LINE_PITCH_BY_TRIM[(8.5, 11.0)], 13.0 / 32.0)

    def test_pitches_hit_the_e2_scale_factors_exactly(self):
        # 3/8 over 5/16 = 1.2; 13/32 over 5/16 = 1.3; 6mm/5mm = 1.2;
        # 6.5mm/5mm = 1.3 — the pinned values ARE the E2 factors.
        ref_line = LINE_PITCH_BY_TRIM[REFERENCE_TRIM]
        ref_dot = DOT_PITCH_BY_TRIM[REFERENCE_TRIM]
        for trim in TRIMS:
            factor = TRIM_TYPE_SCALE[trim]
            self.assertAlmostEqual(
                LINE_PITCH_BY_TRIM[trim] / ref_line, factor, delta=1e-9)
            self.assertAlmostEqual(
                DOT_PITCH_BY_TRIM[trim] / ref_dot, factor, delta=1e-9)

    def test_reference_scale_is_exactly_one(self):
        self.assertEqual(TRIM_TYPE_SCALE[REFERENCE_TRIM], 1.0)


# ---------------------------------------------------------------------------
# Live area at the new trims — margins physical, sheet grows
# ---------------------------------------------------------------------------

class TestLiveAreaPerTrim(unittest.TestCase):
    def test_8_5x11_recto_golden_124(self):
        # bracket 0.375 + pad 0.125 = 0.5 inside; all exact binaries.
        a = live_area(124, 5, trim=(8.5, 11.0))
        self.assertEqual((a.x0, a.y0, a.x1, a.y1),
                         (0.5, 0.625, 8.0, 10.375))

    def test_8x10_recto_golden_124(self):
        a = live_area(124, 5, trim=(8.0, 10.0))
        self.assertEqual((a.x0, a.y0, a.x1, a.y1),
                         (0.5, 0.625, 7.5, 9.375))

    def test_default_trim_unchanged(self):
        # The no-trim-argument call is the 6x9 reference — the
        # existing goldens' code path, untouched.
        self.assertEqual(live_area(124, 5), live_area(124, 5, trim=(6.0, 9.0)))

    def test_gutter_asymmetry_at_top_bracket_all_trims(self):
        # Gutter bracket boundaries are trim-independent (TOTAL-driven,
        # rev B); the sheet width changes, the margins don't.
        for trim in TRIMS:
            recto = live_area(828, 5, trim=trim)
            verso = live_area(828, 6, trim=trim)
            self.assertEqual(recto.x0, 1.0, trim)          # 0.875 + pad
            self.assertEqual(recto.x1, trim[0] - 0.5, trim)
            self.assertEqual(verso.x0, 0.5, trim)
            self.assertEqual(verso.x1, trim[0] - 1.0, trim)

    def test_boundary_trap_holds_at_all_trims(self):
        # body 150 -> total 154 -> 0.5" bracket, every trim.
        for trim in TRIMS:
            a_150 = live_area(154, 5, trim=trim)
            a_149 = live_area(153, 5, trim=trim)
            self.assertEqual(a_150.x0, 0.625, trim)   # 0.5 + 0.125 pad
            self.assertEqual(a_149.x0, 0.625, trim)   # 153 is in 151-300 too
            a_low = live_area(150, 5, trim=trim)
            self.assertEqual(a_low.x0, 0.5, trim)     # 0.375 + pad


# ---------------------------------------------------------------------------
# Template geometry goldens at the new trims (order §4: 1e-6)
# ---------------------------------------------------------------------------

class TestTemplateGeometryPerTrim(unittest.TestCase):
    def test_lined_rows_8_5x11_golden(self):
        area = live_area(124, 5, trim=(8.5, 11.0))
        rows = lined_rows(area, header_rule=True,
                          pitch=LINE_PITCH_BY_TRIM[(8.5, 11.0)])
        self.assertEqual(rows[0], 10.375)                    # header rule
        self.assertAlmostEqual(rows[1], 10.375 - 0.40625 - 0.125, delta=1e-6)
        for a, b in zip(rows[1:], rows[2:]):
            self.assertAlmostEqual(a - b, 0.40625, delta=1e-6)
        self.assertGreaterEqual(rows[-1], area.y0)
        self.assertEqual(len(rows), 24)   # 1 rule + 23 rows at 13/32"

    def test_lined_rows_8x10_golden(self):
        area = live_area(124, 5, trim=(8.0, 10.0))
        rows = lined_rows(area, header_rule=True,
                          pitch=LINE_PITCH_BY_TRIM[(8.0, 10.0)])
        self.assertEqual(rows[0], 9.375)
        self.assertAlmostEqual(rows[1], 9.375 - 0.375 - 0.125, delta=1e-6)
        for a, b in zip(rows[1:], rows[2:]):
            self.assertAlmostEqual(a - b, 0.375, delta=1e-6)
        self.assertGreaterEqual(rows[-1], area.y0)
        # 8.875 down to 0.625 at 3/8" is exactly 23 rows (22 steps),
        # + the header rule = 24.
        self.assertEqual(len(rows), 24)

    def test_dot_grid_8_5x11_golden(self):
        area = live_area(124, 5, trim=(8.5, 11.0))
        pts = dot_grid_points(area, pitch=DOT_PITCH_BY_TRIM[(8.5, 11.0)])
        xs = sorted({p[0] for p in pts})
        ys = sorted({p[1] for p in pts})
        pitch = 6.5 / 25.4
        # 7.5" x 9.75" live area at 6.5mm pitch
        self.assertEqual(len(xs), int(7.5 / pitch) + 1)
        self.assertEqual(len(ys), int(9.75 / pitch) + 1)
        self.assertAlmostEqual(xs[1] - xs[0], pitch, delta=1e-6)
        # centered: residual split evenly on both axes
        self.assertAlmostEqual(xs[0] - area.x0, area.x1 - xs[-1], delta=1e-6)
        self.assertAlmostEqual(ys[0] - area.y0, area.y1 - ys[-1], delta=1e-6)

    def test_dot_grid_8x10_centered(self):
        area = live_area(124, 5, trim=(8.0, 10.0))
        pts = dot_grid_points(area, pitch=DOT_PITCH_BY_TRIM[(8.0, 10.0)])
        xs = sorted({p[0] for p in pts})
        ys = sorted({p[1] for p in pts})
        self.assertAlmostEqual(xs[0] - area.x0, area.x1 - xs[-1], delta=1e-6)
        self.assertAlmostEqual(ys[0] - area.y0, area.y1 - ys[-1], delta=1e-6)


# ---------------------------------------------------------------------------
# Build — 6x9 BYTE-LOCK + new-trim goldens per template family
# ---------------------------------------------------------------------------

def _build(trim=REFERENCE_TRIM, template="Lined", body=20, prompts=None, **kw):
    args = dict(title="The Keeping Book",
                subtitle="A Gardener's Log Journal",
                author="E. J. Sandoval", template=template,
                body_pages=body, copyright_year=2026, prompts=prompts,
                trim=trim)
    args.update(kw)
    return build_interior(**args)


# sha256 of the 7.1.0-a1 renderer's output for these exact inputs,
# captured 2026-07-19 BEFORE the trim expansion. If any of these move,
# the 6x9 lane changed — that is a spec event, not a refactor.
BYTE_LOCK_6X9 = {
    "Lined": "db01b103af2dc7c4851d1e995720f49b5f129ec96eb7344ca5c7126e5d93b59a",
    "Dot Grid": "ba8bb0e509ff854b42b0114de501154f679141aaff7764ea3ec1da7493ece6a6",
    "Blank": "344031c793edd5771b022e55bcba280187a90e1bc631526e2416b8967f414e4b",
    "Prompted": "15e3637a0c53738295903c85b01d18e0f8165ed876597d4cac93f49e0286b2e1",
}

PROMPTS_20 = [f"Day {i + 1}: note what changed." for i in range(20)]

EXPECT_PT = {
    (6.0, 9.0): (432.0, 648.0),
    (8.0, 10.0): (576.0, 720.0),
    (8.5, 11.0): (612.0, 792.0),
}


class TestByteLock6x9(unittest.TestCase):
    def test_locked_hashes(self):
        for template, expected in BYTE_LOCK_6X9.items():
            prompts = PROMPTS_20 if template == "Prompted" else None
            pdf, _ = _build(template=template, prompts=prompts)
            self.assertEqual(hashlib.sha256(pdf).hexdigest(), expected,
                             f"6x9 {template} bytes moved")


class TestBuildPerTrim(unittest.TestCase):
    def test_parity_size_determinism_all_trims_all_templates(self):
        for trim in TRIMS:
            w_pt, h_pt = EXPECT_PT[trim]
            for template in ("Lined", "Dot Grid", "Blank", "Prompted"):
                prompts = PROMPTS_20 if template == "Prompted" else None
                pdf1, params = _build(trim=trim, template=template,
                                      prompts=prompts)
                pdf2, _ = _build(trim=trim, template=template,
                                 prompts=prompts)
                label = f"{trim}/{template}"
                self.assertEqual(hashlib.sha256(pdf1).hexdigest(),
                                 hashlib.sha256(pdf2).hexdigest(),
                                 f"determinism {label}")
                reader = PdfReader(io.BytesIO(pdf1))
                self.assertEqual(len(reader.pages), 24, label)
                for page in reader.pages:
                    self.assertEqual(float(page.mediabox.width), w_pt, label)
                    self.assertEqual(float(page.mediabox.height), h_pt, label)
                self.assertEqual(params["trim"], TRIM_CANONICAL[trim])
                self.assertEqual(params["type_scale"], TRIM_TYPE_SCALE[trim])

    def test_soak_case_8_5x11_lined_120(self):
        # Soak run #1's exact shape: 8.5x11 Lined 120 body pages.
        pdf, params = _build(trim=(8.5, 11.0), template="Lined", body=120,
                             title="The Soak Door Journal", subtitle=None,
                             author="Pronto House")
        reader = PdfReader(io.BytesIO(pdf))
        self.assertEqual(len(reader.pages), 124)
        self.assertEqual(float(reader.pages[0].mediabox.width), 612.0)
        self.assertEqual(float(reader.pages[0].mediabox.height), 792.0)
        self.assertEqual(params["total_pages"], 124)
        self.assertEqual(params["line_pitch_in"], 13.0 / 32.0)


# ---------------------------------------------------------------------------
# Worker — the soak case completes; the pinned-table hold keeps holding
# ---------------------------------------------------------------------------

class TestWorkerPerTrim(unittest.TestCase):
    def test_soak_case_completes_zero_touch(self):
        p = _make_processor(bm={
            "Book Title": "The Soak Door Journal",
            "Author Name": "Pronto House",
            "Trim Size": {"name": '8.5" × 11"'},
            "Low-Content Template": {"name": "Lined"},
            "Low-Content Page Count": 120,
        })
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Complete", result)
        self.assertEqual(result["total_pages"], 124)
        fields = p.airtable_client.update_service.call_args_list[-1].args[1]
        self.assertEqual(fields["Interior Page Count"], 124)
        self.assertIn('"trim": "8.5x11"', fields["Operator Notes"])
        manifest = p.r2_client.upload_json.call_args.kwargs["data"]
        self.assertEqual(manifest["geometry"]["trim"], "8.5x11")
        self.assertEqual(manifest["geometry"]["trim_in"], [8.5, 11.0])
        self.assertEqual(manifest["geometry"]["line_pitch_in"], 13.0 / 32.0)

    def test_8x10_completes(self):
        p = _make_processor(bm={
            "Book Title": "T", "Author Name": "A",
            "Trim Size": {"name": '8" × 10"'},
            "Low-Content Template": {"name": "Dot Grid"},
            "Low-Content Page Count": 120,
        })
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Complete", result)
        manifest = p.r2_client.upload_json.call_args.kwargs["data"]
        self.assertEqual(manifest["geometry"]["trim"], "8x10")
        self.assertEqual(manifest["geometry"]["dot_pitch_in"], 6.0 / 25.4)

    def test_6x9_still_completes_with_multiplication_sign(self):
        p = _make_processor(bm={
            "Book Title": "T", "Author Name": "A",
            "Trim Size": {"name": '6" × 9"'},
            "Low-Content Template": {"name": "Blank"},
            "Low-Content Page Count": 120,
        })
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Complete", result)

    def test_docketed_trim_still_holds(self):
        p = _make_processor(bm={
            "Book Title": "T", "Author Name": "A",
            "Trim Size": {"name": '5.5" x 8.5"'},
            "Low-Content Template": {"name": "Lined"},
            "Low-Content Page Count": 120,
        })
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Review")
        self.assertIn("not in the pinned trim table", result["review_reason"])


if __name__ == "__main__":
    unittest.main()
