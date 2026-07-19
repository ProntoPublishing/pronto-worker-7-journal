"""
W7 test battery (order §9): golden geometry at the TOTAL extremes
(24 / 828) plus the 124-total default, the rev B boundary-trap test
(body 150 / total 154), seeded gutter violation, page-count parity
(body + 4 = PDF pages = field written), determinism, idempotency,
seeded holds, and the (c) block byte-match against the captured W2
1.7.3 fixture.
"""

import hashlib
import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pypdf import PdfReader

from geometry import (
    BODY_MAX, BODY_MIN, FRONT_MATTER_PAGES, GutterBracketError,
    LINE_PITCH_IN, TOTAL_MAX, TOTAL_MIN, dot_grid_points,
    gutter_for_total, inside_margin_for_total, lined_rows, live_area,
    total_pages,
)
from render import build_interior, copyright_lines

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


# ---------------------------------------------------------------------------
# Geometry — pure functions, full precision
# ---------------------------------------------------------------------------

class TestGutterTable(unittest.TestCase):
    def test_bracket_boundaries_exact(self):
        # Every bracket edge, both sides (order §9: not just the middle).
        for total, expected in [(24, 0.375), (150, 0.375),
                                (151, 0.5), (300, 0.5),
                                (301, 0.625), (500, 0.625),
                                (501, 0.75), (700, 0.75),
                                (701, 0.875), (828, 0.875)]:
            self.assertEqual(gutter_for_total(total), expected,
                             f"total={total}")

    def test_outside_table_raises(self):
        for total in (23, 829, 0, -5):
            with self.assertRaises(GutterBracketError):
                gutter_for_total(total)

    def test_boundary_trap_body_150(self):
        # Rev B, named in the order: body 150 -> total 154 -> 0.5"
        # bracket. A body-count lookup selects 0.375" and manufactures
        # a violation exactly at the boundary — this test fails that
        # implementation by design.
        body = 150
        total = total_pages(body)
        self.assertEqual(total, 154)
        self.assertEqual(gutter_for_total(total), 0.5)
        self.assertEqual(gutter_for_total(body), 0.375,
                         "sanity: the WRONG lookup gives the smaller gutter")
        self.assertNotEqual(gutter_for_total(total), gutter_for_total(body))

    def test_bounds_derivation(self):
        self.assertEqual(BODY_MIN, TOTAL_MIN - FRONT_MATTER_PAGES)
        self.assertEqual(BODY_MAX, TOTAL_MAX - FRONT_MATTER_PAGES)
        self.assertEqual(total_pages(120), 124)


class TestLiveArea(unittest.TestCase):
    def test_default_total_recto_golden(self):
        # total 124 -> bracket 0.375 + pad 0.125 = 0.5 inside. Recto:
        # inside on the left. All exact binary fractions — exact equality.
        a = live_area(124, page_number=5)
        self.assertEqual((a.x0, a.y0, a.x1, a.y1),
                         (0.5, 0.625, 5.5, 8.375))

    def test_mirrored_margins_verso(self):
        a = live_area(124, page_number=6)
        self.assertEqual((a.x0, a.x1), (0.5, 5.5))
        # At the low bracket inside == outside (0.5) so assert at the
        # top bracket where the asymmetry is visible:
        recto = live_area(828, page_number=5)
        verso = live_area(828, page_number=6)
        self.assertEqual(recto.x0, 1.0)     # 0.875 + 0.125 comfort pad
        self.assertEqual(recto.x1, 5.5)
        self.assertEqual(verso.x0, 0.5)
        self.assertEqual(verso.x1, 5.0)

    def test_live_area_rederives_across_totals(self):
        # Rev B: a grid compliant at 124 total must re-derive at 828.
        self.assertNotEqual(live_area(124, 5), live_area(828, 5))
        self.assertEqual(inside_margin_for_total(124), 0.5)
        self.assertEqual(inside_margin_for_total(828), 1.0)


class TestTemplateGeometry(unittest.TestCase):
    def test_lined_rows_golden_124(self):
        rows = lined_rows(live_area(124, 5), header_rule=True)
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows[0], 8.375)            # header rule
        self.assertEqual(rows[1], 7.9375)           # 8.375 - 0.3125 - 0.125
        self.assertEqual(rows[-1], 0.75)            # last row above y0
        for a, b in zip(rows[1:], rows[2:]):
            self.assertEqual(a - b, LINE_PITCH_IN)

    def test_lined_rows_golden_828(self):
        rows = lined_rows(live_area(828, 5), header_rule=True)
        self.assertEqual(rows[0], 8.375)
        self.assertEqual(rows[1], 7.9375)
        self.assertEqual(len(rows), 25)   # height unchanged; width narrows

    def test_dot_grid_golden_828(self):
        # Recto at the top bracket: x 1.0..5.5 (4.5 wide), y 0.625..8.375.
        pts = dot_grid_points(live_area(828, 5))
        xs = sorted({p[0] for p in pts})
        ys = sorted({p[1] for p in pts})
        self.assertEqual((len(xs), len(ys)), (23, 40))
        self.assertEqual(len(pts), 23 * 40)
        pitch = 5.0 / 25.4
        self.assertAlmostEqual(xs[1] - xs[0], pitch, delta=1e-12)
        # centered: residual split evenly on both sides
        self.assertAlmostEqual(xs[0] - 1.0, 5.5 - xs[-1], delta=1e-12)
        self.assertAlmostEqual(ys[0] - 0.625, 8.375 - ys[-1], delta=1e-12)

    def test_dot_grid_golden_24(self):
        pts = dot_grid_points(live_area(24, 5))
        xs = sorted({p[0] for p in pts})
        self.assertEqual(len(xs), 26)     # 5.0" live width at 5mm pitch
        self.assertAlmostEqual(xs[0] - 0.5, 5.5 - xs[-1], delta=1e-12)


# ---------------------------------------------------------------------------
# (c) block — W2 1.7.3 wording byte-for-byte
# ---------------------------------------------------------------------------

class TestCopyrightBlock(unittest.TestCase):
    def test_matches_w2_fixture_bytes(self):
        with open(os.path.join(FIX, "w2_1_7_3_copyright_block.txt"),
                  encoding="utf-8") as f:
            expected = f.read().splitlines()
        got = copyright_lines(2026, "Test Author", "978-1-971041-06-3")
        self.assertEqual(got, expected)

    def test_isbn_absent_drops_line_only(self):
        with_isbn = copyright_lines(2026, "A", "X")
        without = copyright_lines(2026, "A", None)
        self.assertEqual([ln for ln in with_isbn if not ln.startswith("ISBN")],
                         without)


# ---------------------------------------------------------------------------
# Build — parity, determinism, front matter
# ---------------------------------------------------------------------------

def _build(template="Lined", body=20, prompts=None, **kw):
    args = dict(title="The Keeping Book",
                subtitle="A Gardener's Log Journal",
                author="E. J. Sandoval", template=template,
                body_pages=body, copyright_year=2026, prompts=prompts)
    args.update(kw)
    return build_interior(**args)


class TestBuild(unittest.TestCase):
    def test_parity_all_templates(self):
        for template in ("Lined", "Dot Grid", "Blank"):
            pdf, params = _build(template=template, body=20)
            n = len(PdfReader(io.BytesIO(pdf)).pages)
            self.assertEqual(n, 24, template)
            self.assertEqual(params["total_pages"], 24)

    def test_parity_prompted(self):
        prompts = [f"Day {i + 1}: note what changed." for i in range(20)]
        pdf, params = _build(template="Prompted", body=20, prompts=prompts)
        self.assertEqual(len(PdfReader(io.BytesIO(pdf)).pages), 24)
        self.assertEqual(params["total_pages"], 24)

    def test_determinism(self):
        p1, _ = _build(template="Dot Grid", body=20)
        p2, _ = _build(template="Dot Grid", body=20)
        self.assertEqual(hashlib.sha256(p1).hexdigest(),
                         hashlib.sha256(p2).hexdigest())

    def test_page_size_exact(self):
        pdf, _ = _build(body=20)
        for page in PdfReader(io.BytesIO(pdf)).pages:
            self.assertEqual(float(page.mediabox.width), 432.0)
            self.assertEqual(float(page.mediabox.height), 648.0)

    def test_copyright_page_text(self):
        pdf, _ = _build(body=20, isbn="978-1-971041-06-3")
        text = PdfReader(io.BytesIO(pdf)).pages[3].extract_text() or ""
        self.assertIn("Copyright", text)
        self.assertIn("978-1-971041-06-3", text)
        self.assertIn("prontopublishing.com", text)

    def test_blank_verso_is_empty(self):
        pdf, _ = _build(body=20)
        text = PdfReader(io.BytesIO(pdf)).pages[1].extract_text() or ""
        self.assertEqual(text.strip(), "")


# ---------------------------------------------------------------------------
# Worker contract
# ---------------------------------------------------------------------------

def _make_processor(bm=None):
    with patch.dict(os.environ, {"AIRTABLE_TOKEN": "t", "AIRTABLE_BASE_ID": "b"}), \
         patch("pronto_worker_7.ProntoR2Client"), \
         patch("pronto_worker_7.AirtableClient"):
        import pronto_worker_7 as w7
        p = w7.JournalProcessor()
    services = {
        "svcJournal": {"Status": "Paid", "Dependencies": [],
                       "Project": ["proj1"]},
    }
    p.airtable_client = MagicMock()
    p.airtable_client.get_service.side_effect = services.get
    p.airtable_client.get_project.return_value = {"Book Metadata": ["bm1"]}
    p.airtable_client.get_book_metadata.return_value = bm if bm is not None else {
        "Book Title": "The Keeping Book",
        "Subtitle": "A Gardener's Log Journal",
        "Author Name": "E. J. Sandoval",
        "Trim Size": {"name": "6x9"},
        "Low-Content Template": {"name": "Lined"},
        "Low-Content Page Count": 120,
    }
    # E4: default to the legacy path explicitly — a bare MagicMock is
    # truthy and silently impersonates an eligible imprint record.
    p.airtable_client.get_default_imprint.return_value = None
    p.airtable_client.get_imprint.return_value = None
    p.r2_client = MagicMock()
    p.r2_client.upload_file_bytes.return_value = {"public_url": "https://r2/i"}
    p.r2_client.upload_json.return_value = {"public_url": "https://r2/m"}
    return p


class TestWorker(unittest.TestCase):
    def test_happy_path_completes(self):
        p = _make_processor()
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Complete", result)
        self.assertEqual(result["total_pages"], 124)
        fields = p.airtable_client.update_service.call_args_list[-1].args[1]
        self.assertEqual(fields["Artifact Type"], "Interior PDF")
        self.assertEqual(fields["Interior Page Count"], 124)
        notes = json.loads(fields["Operator Notes"].split(": ", 1)[1])
        self.assertEqual(notes["gutter_bracket_in"], 0.375)

    def test_template_missing_fails_w7_001(self):
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Low-Content Page Count": 120})
        result = p.process_service("svcJournal")
        self.assertFalse(result["success"])
        self.assertIn("W7-001", result["error"])
        fields = p.airtable_client.update_service.call_args_list[-1].args[1]
        self.assertEqual(fields["Status"], "Failed")

    def test_template_unrecognized_fails_w7_001(self):
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Low-Content Template": {"name": "Spiral"},
                                "Low-Content Page Count": 120})
        result = p.process_service("svcJournal")
        self.assertIn("W7-001", result["error"])

    def test_bounds_hold_w7_002_shows_both_numbers(self):
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Low-Content Template": {"name": "Blank"},
                                "Low-Content Page Count": 826})
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Review")
        self.assertIn("W7-002", result["review_reason"])
        self.assertIn("826", result["review_reason"])   # body number
        self.assertIn("830", result["review_reason"])   # total number
        self.assertIn("824", result["review_reason"])   # actionable max

    def test_bounds_hold_floor(self):
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Low-Content Template": {"name": "Blank"},
                                "Low-Content Page Count": 19})
        result = p.process_service("svcJournal")
        self.assertIn("W7-002", result["review_reason"])

    def test_boundary_trap_completes_at_body_150(self):
        # body 150 -> total 154 -> 0.5" bracket; worker must Complete
        # and record the CORRECT bracket.
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Low-Content Template": {"name": "Lined"},
                                "Low-Content Page Count": 150})
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Complete", result)
        fields = p.airtable_client.update_service.call_args_list[-1].args[1]
        notes = json.loads(fields["Operator Notes"].split(": ", 1)[1])
        self.assertEqual(notes["total_pages"], 154)
        self.assertEqual(notes["gutter_bracket_in"], 0.5)

    def test_prompted_without_prompts_holds_w7_003(self):
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Low-Content Template": {"name": "Prompted"},
                                "Low-Content Page Count": 20})
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Review")
        self.assertIn("W7-003", result["review_reason"])

    def test_prompted_too_few_holds_w7_003(self):
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Low-Content Template": {"name": "Prompted"},
                                "Low-Content Page Count": 20,
                                "Prompt Set": "one\ntwo\nthree"})
        result = p.process_service("svcJournal")
        self.assertIn("W7-003", result["review_reason"])
        self.assertIn("3 prompts for 20", result["review_reason"])

    def test_prompt_overflow_holds_w7_003(self):
        long_prompt = ("Describe, in as much detail as you can manage "
                       "before the light goes, ") * 12
        prompts = [long_prompt] + ["short"] * 19
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Low-Content Template": {"name": "Prompted"},
                                "Low-Content Page Count": 20,
                                "Prompt Set": "\n".join(prompts)})
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Review")
        self.assertIn("W7-003", result["review_reason"])
        self.assertIn("wraps", result["review_reason"])

    def test_metadata_incomplete_holds(self):
        p = _make_processor(bm={"Book Title": "", "Author Name": "A",
                                "Low-Content Template": {"name": "Lined"}})
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Review")
        self.assertIn("metadata incomplete", result["review_reason"])

    def test_unsupported_trim_holds(self):
        # 5x8 stays docketed with E2's — outside the pinned table -> hold.
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Trim Size": {"name": "5x8"},
                                "Low-Content Template": {"name": "Lined"},
                                "Low-Content Page Count": 120})
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Review")
        self.assertIn("not in the pinned trim table", result["review_reason"])

    def test_self_check_fails_w7_004(self):
        # Module-attribute swap (the W6 harness pattern): a doctored
        # build that renders one page short must FAIL, not Complete.
        import pronto_worker_7 as w7
        p = _make_processor()
        real = w7.build_interior

        def short_build(**kw):
            pdf, params = real(**{**kw, "body_pages": kw["body_pages"] - 1})
            params["body_pages"] = kw["body_pages"]
            params["total_pages"] = kw["body_pages"] + 4
            return pdf, params
        w7.build_interior = short_build
        try:
            result = p.process_service("svcJournal")
        finally:
            w7.build_interior = real
        self.assertFalse(result["success"])
        self.assertIn("W7-004", result["error"])
        fields = p.airtable_client.update_service.call_args_list[-1].args[1]
        self.assertEqual(fields["Status"], "Failed")

    def test_e4_linked_flag_without_bowker_string_holds(self):
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Low-Content Template": {"name": "Lined"},
                                "Low-Content Page Count": 120,
                                "Imprint": ["impKeeping"]})
        p.airtable_client.get_imprint.return_value = {
            "Flag": "The Keeping Books"}   # no Bowker Canonical String
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Review")
        self.assertIn("not E4-eligible", result["review_reason"])

    def test_e4_linked_eligible_flag_renders(self):
        p = _make_processor(bm={"Book Title": "T", "Author Name": "A",
                                "Low-Content Template": {"name": "Lined"},
                                "Low-Content Page Count": 120,
                                "Imprint": ["impKeeping"]})
        p.airtable_client.get_imprint.return_value = {
            "Flag": "The Keeping Books",
            "Bowker Canonical String": "The Keeping Books"}
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Complete", result)
        manifest = p.r2_client.upload_json.call_args.kwargs["data"]
        imp = manifest["inputs"]["imprint"]
        self.assertEqual(imp["canonical"], "The Keeping Books")
        self.assertEqual(manifest["geometry"]["template_params"]
                         ["published_by"], "The Keeping Books")

    def test_e4_default_eligible_flag_applies_without_link(self):
        p = _make_processor()
        p.airtable_client.get_default_imprint.return_value = {
            "Flag": "Landfall Ink",
            "Bowker Canonical String": "Landfall Ink", "E4 Default": True}
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Complete", result)
        manifest = p.r2_client.upload_json.call_args.kwargs["data"]
        self.assertEqual(manifest["inputs"]["imprint"]["canonical"],
                         "Landfall Ink")

    def test_e4_legacy_when_nothing_eligible(self):
        p = _make_processor()
        result = p.process_service("svcJournal")
        self.assertEqual(result.get("status"), "Complete", result)
        manifest = p.r2_client.upload_json.call_args.kwargs["data"]
        imp = manifest["inputs"]["imprint"]
        self.assertEqual(imp["canonical"], "Pronto Publishing")
        self.assertIn("legacy", imp["source"])
        self.assertIsNone(manifest["geometry"]["template_params"]
                          ["published_by"])

    def test_idempotency_noop(self):
        p = _make_processor()
        p.airtable_client.get_service.side_effect = lambda sid: {
            "Status": "Complete", "Artifact URL": "https://r2/interior.pdf"}
        result = p.process_service("svcJournal")
        self.assertEqual(result["status"], "already_complete")
        p.airtable_client.update_service.assert_not_called()


if __name__ == "__main__":
    unittest.main()
