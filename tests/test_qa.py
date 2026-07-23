"""
QA Reviewer v0 unit tests — vendored alongside qa.py, identical in
every producing worker repo (imprint.py pattern). Three layers match
the module: pure-check tests on literal facts (no PDFs), extraction
tests on in-memory pypdf fixtures, and driver/report tests.
"""

import io
import hashlib
import os
import sys
import unittest
import zipfile
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pypdf import PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, NameObject,
                           NumberObject)

import qa
from qa import (ARTIFACT_COVER, ARTIFACT_INTERIOR, ARTIFACT_KDP_ZIP,
                FontFact, ImageFact, PdfFacts, QAConfig, QASpec,
                check_fonts_embedded, check_gutter_declared,
                check_image_dpi, check_page_count, check_page_geometry,
                check_pdf_integrity, check_r2_object, check_spine_posture,
                expected_cover_dims, extract_pdf_facts, extract_zip_facts,
                gutter_floor_in, review)

TRIM_6X9 = (6.0, 9.0)


def blank_pdf_bytes(pages=1, width_pt=432.0, height_pt=648.0):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width_pt, height=height_pt)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def pdf_with_resources(resources_updates):
    """One blank 6x9 page whose /Resources carry the given entries —
    enough for the extraction layer, which only reads dict keys."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=432.0, height=648.0)
    resources = DictionaryObject()
    for key, value in resources_updates.items():
        resources[NameObject(key)] = value
    page[NameObject("/Resources")] = resources
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def font_dict(base="/FakeSans", descriptor=None, subtype="/TrueType"):
    d = DictionaryObject()
    d[NameObject("/Type")] = NameObject("/Font")
    d[NameObject("/Subtype")] = NameObject(subtype)
    d[NameObject("/BaseFont")] = NameObject(base)
    if descriptor is not None:
        d[NameObject("/FontDescriptor")] = descriptor
    return d


def image_dict(px_w, px_h):
    d = DictionaryObject()
    d[NameObject("/Subtype")] = NameObject("/Image")
    d[NameObject("/Width")] = NumberObject(px_w)
    d[NameObject("/Height")] = NumberObject(px_h)
    return d


def spec(artifact_type=ARTIFACT_INTERIOR, trim=TRIM_6X9, page_count=120,
         **kw):
    return QASpec(artifact_type=artifact_type, trim=trim,
                  page_count=page_count, **kw)


def facts(page_count=120, size_pt=(432.0, 648.0), fonts=(), images=()):
    return PdfFacts(page_count, tuple([size_pt] * page_count),
                    tuple(fonts), tuple(images))


class TestPageCount(unittest.TestCase):
    def test_bounds_table(self):
        for n, ok in ((23, False), (24, True), (828, True), (829, False)):
            v = check_page_count(facts(page_count=n),
                                 spec(page_count=n))
            self.assertEqual(v.ok, ok, n)
            self.assertEqual(v.severity, "pass" if ok else "fail")

    def test_expected_mismatch_fails(self):
        v = check_page_count(facts(page_count=120), spec(page_count=124))
        self.assertFalse(v.ok)
        self.assertIn("counted 120 != expected 124", v.detail)

    def test_cover_must_be_one_page(self):
        one = PdfFacts(1, ((900.0, 666.0),), (), ())
        self.assertTrue(check_page_count(
            one, spec(ARTIFACT_COVER, page_count=120)).ok)
        two = PdfFacts(2, ((900.0, 666.0),) * 2, (), ())
        self.assertFalse(check_page_count(
            two, spec(ARTIFACT_COVER, page_count=120)).ok)


class TestPageGeometry(unittest.TestCase):
    def test_trim_exact_passes(self):
        self.assertTrue(check_page_geometry(facts(), spec()).ok)

    def test_tolerance_edges(self):
        just_in = facts(size_pt=(432.0 + 0.07, 648.0))
        self.assertTrue(check_page_geometry(just_in, spec()).ok)
        just_out = facts(size_pt=(432.0 + 0.08, 648.0))
        v = check_page_geometry(just_out, spec())
        self.assertFalse(v.ok)
        self.assertEqual(v.severity, "fail")
        self.assertIn("page 1", v.detail)

    def test_cover_wrap_recomputed(self):
        exp_w, exp_h = expected_cover_dims(120, "cream", TRIM_6X9)
        self.assertAlmostEqual(exp_w, 0.125 + 6 + 120 * 0.0025 + 6 + 0.125)
        self.assertAlmostEqual(exp_h, 0.125 + 9 + 0.125)
        good = PdfFacts(1, ((exp_w * 72.0, exp_h * 72.0),), (), ())
        self.assertTrue(check_page_geometry(
            good, spec(ARTIFACT_COVER, page_count=120)).ok)
        bad = PdfFacts(1, ((exp_w * 72.0 + 1.0, exp_h * 72.0),), (), ())
        v = check_page_geometry(bad, spec(ARTIFACT_COVER, page_count=120))
        self.assertFalse(v.ok)
        self.assertIn("expected", v.detail)

    def test_unknown_paper_fails(self):
        one = PdfFacts(1, ((900.0, 666.0),), (), ())
        v = check_page_geometry(
            one, spec(ARTIFACT_COVER, page_count=120, paper="parchment"))
        self.assertFalse(v.ok)


class TestFontsAndImages(unittest.TestCase):
    def test_missing_embedding_fails(self):
        v = check_fonts_embedded(facts(fonts=(
            FontFact("Lora", True, False), FontFact("FakeSans", False, False))))
        self.assertFalse(v.ok)
        self.assertEqual(v.severity, "fail")
        self.assertIn("FakeSans", v.detail)
        self.assertNotIn("Lora", v.detail)

    def test_type3_and_zero_fonts_pass(self):
        self.assertTrue(check_fonts_embedded(
            facts(fonts=(FontFact("Glyphy", False, True),))).ok)
        self.assertTrue(check_fonts_embedded(facts()).ok)

    def test_dpi_lower_bound(self):
        # 6in-wide page: 1800px -> exactly 300dpi lower bound.
        ok = facts(page_count=1, images=(ImageFact(0, "/Im1", 1800, 2700),))
        self.assertTrue(check_image_dpi(ok).ok)
        low = facts(page_count=1, images=(ImageFact(0, "/Im1", 1799, 2700),))
        v = check_image_dpi(low)
        self.assertFalse(v.ok)
        self.assertEqual(v.severity, "warn")   # one-sided test never hard-fails
        self.assertIn("p1 /Im1", v.detail)

    def test_tiny_masks_skipped(self):
        v = check_image_dpi(facts(page_count=1,
                                  images=(ImageFact(0, "/Mask", 8, 8),)))
        self.assertTrue(v.ok)


class TestGutterAndSpine(unittest.TestCase):
    def test_bracket_table(self):
        for n, floor in ((24, 0.375), (150, 0.375), (151, 0.5), (300, 0.5),
                         (301, 0.625), (500, 0.625), (501, 0.75),
                         (700, 0.75), (701, 0.875), (828, 0.875)):
            self.assertEqual(gutter_floor_in(n), floor, n)

    def test_declared_vs_floor(self):
        ok = check_gutter_declared(
            spec(page_count=151, inside_margin_in=0.5))
        self.assertTrue(ok.ok)
        bad = check_gutter_declared(
            spec(page_count=151, inside_margin_in=0.375))
        self.assertFalse(bad.ok)
        self.assertEqual(bad.severity, "fail")

    def test_no_declaration_is_note(self):
        v = check_gutter_declared(spec())
        self.assertTrue(v.ok)
        self.assertEqual(v.severity, "note")

    def test_spine_posture_notes(self):
        blank = check_spine_posture(
            spec(ARTIFACT_COVER, page_count=78))
        self.assertEqual(blank.severity, "note")
        self.assertIn("blank", blank.detail)
        allowed = check_spine_posture(
            spec(ARTIFACT_COVER, page_count=79))
        self.assertIn("permitted", allowed.detail)


class TestIntegrityAndExtraction(unittest.TestCase):
    def test_known_bad_bytes(self):
        for bad in (b"", b"%PDF-1.4 truncated" + b"x" * 2000,
                    blank_pdf_bytes(4)[:600]):
            v = check_pdf_integrity(bad)
            self.assertFalse(v.ok, bad[:20])
            self.assertEqual(v.severity, "fail")

    def test_not_a_pdf_header(self):
        v = check_pdf_integrity(b"PK\x03\x04" + b"\x00" * 4096)
        self.assertFalse(v.ok)
        self.assertIn("%PDF-", v.detail)

    def test_blank_pages_extract(self):
        f = extract_pdf_facts(blank_pdf_bytes(pages=3))
        self.assertEqual(f.page_count, 3)
        self.assertEqual(f.page_sizes_pt[0], (432.0, 648.0))
        self.assertEqual(f.fonts, ())
        self.assertEqual(f.images, ())

    def test_font_and_image_extraction(self):
        embedded_fd = DictionaryObject()
        embedded_fd[NameObject("/FontFile2")] = NumberObject(1)
        data = pdf_with_resources({
            "/Font": DictionaryObject({
                NameObject("/F1"): font_dict("/GoodSans", embedded_fd),
                NameObject("/F2"): font_dict("/BadSans", None),
            }),
            "/XObject": DictionaryObject({
                NameObject("/Im1"): image_dict(600, 900),
            }),
        })
        f = extract_pdf_facts(data)
        by_name = {ff.base_name: ff for ff in f.fonts}
        self.assertTrue(by_name["/GoodSans"].embedded)
        self.assertFalse(by_name["/BadSans"].embedded)
        self.assertEqual(f.images, (ImageFact(0, "/Im1", 600, 900),))


def build_zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestZipChecks(unittest.TestCase):
    def setUp(self):
        self.interior = blank_pdf_bytes(pages=120)
        exp_w, exp_h = expected_cover_dims(120, "cream", TRIM_6X9)
        cover = blank_pdf_bytes(pages=1, width_pt=exp_w * 72.0,
                                height_pt=exp_h * 72.0)
        # A one-blank-page fixture is ~450 bytes — below the (correct)
        # 1KB integrity floor. Trailing whitespace after %%EOF is legal.
        self.cover = cover + b" " * (qa.MIN_PDF_BYTES + 64 - len(cover))
        self.members = {
            "interior.pdf": self.interior,
            "cover.pdf": self.cover,
            "metadata.json": b"{}",
            "metadata.txt": b"meta",
            "upload_checklist.md": b"# checklist",
        }
        self.shas = {name: hashlib.sha256(data).hexdigest()
                     for name, data in self.members.items()}

    def zip_spec(self, **kw):
        base = dict(
            artifact_type=ARTIFACT_KDP_ZIP, trim=TRIM_6X9, page_count=120,
            manifest_member_shas=self.shas,
            sibling_interior_sha256=self.shas["interior.pdf"],
            sibling_cover_sha256=self.shas["cover.pdf"])
        base.update(kw)
        return QASpec(**base)

    def test_good_zip_passes(self):
        result = review(artifact=build_zip(self.members),
                        spec=self.zip_spec(), config=QAConfig())
        self.assertTrue(result.passed, result.report_lines())

    def test_missing_member_fails(self):
        members = dict(self.members)
        del members["cover.pdf"]
        result = review(artifact=build_zip(members), spec=self.zip_spec(),
                        config=QAConfig())
        checks = {v.check for v in result.hard_fails}
        self.assertIn("zip_members", checks)
        self.assertIn("zip_custody_cover", checks)

    def test_substituted_member_fails_custody(self):
        members = dict(self.members)
        members["interior.pdf"] = blank_pdf_bytes(pages=124)
        result = review(artifact=build_zip(members), spec=self.zip_spec(),
                        config=QAConfig())
        checks = {v.check for v in result.hard_fails}
        self.assertIn("zip_member_shas", checks)
        self.assertIn("zip_custody_interior", checks)

    def test_sha_prefix_normalized(self):
        prefixed = {k: "sha256:" + v for k, v in self.shas.items()}
        result = review(
            artifact=build_zip(self.members),
            spec=self.zip_spec(
                manifest_member_shas=prefixed,
                sibling_interior_sha256="sha256:" + self.shas["interior.pdf"],
                sibling_cover_sha256="sha256:" + self.shas["cover.pdf"]),
            config=QAConfig())
        self.assertTrue(result.passed, result.report_lines())

    def test_not_a_zip_fails(self):
        result = review(artifact=b"not a zip at all",
                        spec=self.zip_spec(), config=QAConfig())
        self.assertFalse(result.passed)
        self.assertEqual(result.hard_fails[0].check, "zip_integrity")


class TestR2Check(unittest.TestCase):
    def _r2(self):
        r2 = MagicMock()
        r2.bucket_name = "pronto-artifacts"
        return r2

    def test_present_passes(self):
        r2 = self._r2()
        r2.s3_client.head_object.return_value = {"ContentLength": 10}
        self.assertTrue(check_r2_object(r2, "k", 10).ok)

    def test_missing_fails(self):
        r2 = self._r2()
        err = Exception("boom")
        err.response = {"Error": {"Code": "404"}}
        r2.s3_client.head_object.side_effect = err
        v = check_r2_object(r2, "k", 10)
        self.assertFalse(v.ok)
        self.assertEqual(v.severity, "fail")

    def test_size_mismatch_fails(self):
        r2 = self._r2()
        r2.s3_client.head_object.return_value = {"ContentLength": 9}
        v = check_r2_object(r2, "k", 10)
        self.assertFalse(v.ok)
        self.assertEqual(v.severity, "fail")

    def test_transient_error_warns(self):
        r2 = self._r2()
        r2.s3_client.head_object.side_effect = ConnectionError("flake")
        v = check_r2_object(r2, "k", 10)
        self.assertFalse(v.ok)
        self.assertEqual(v.severity, "warn")   # infra flake never gates


class TestDriverAndReport(unittest.TestCase):
    def _good_interior(self):
        return blank_pdf_bytes(pages=120)

    def test_pass_fields_both_modes(self):
        data = self._good_interior()
        for cfg in (QAConfig(gating_enabled=False),
                    QAConfig(gating_enabled=True)):
            result = review(artifact=data, spec=spec(), config=cfg)
            self.assertTrue(result.passed, result.report_lines())
            fields = result.airtable_fields(cfg)
            self.assertEqual(fields["QA Status"], "Pass")
            self.assertIn("QA Report", fields)
            self.assertFalse(result.should_block(cfg))

    def test_report_only_fail_is_inert(self):
        result = review(artifact=self._good_interior(),
                        spec=spec(page_count=999), config=QAConfig())
        self.assertFalse(result.passed)
        cfg = QAConfig(gating_enabled=False)
        fields = result.airtable_fields(cfg)
        self.assertNotIn("QA Status", fields)      # Pending stays Pending
        self.assertIn("Fail (report-only)", fields["QA Report"])
        self.assertFalse(result.should_block(cfg))

    def test_gating_fail_blocks(self):
        cfg = QAConfig(gating_enabled=True)
        result = review(artifact=self._good_interior(),
                        spec=spec(page_count=999), config=cfg)
        fields = result.airtable_fields(cfg)
        self.assertEqual(fields["QA Status"], "Fail")
        self.assertTrue(result.should_block(cfg))
        blocked = result.blocked_fields()
        self.assertIs(blocked["Blocked"], True)
        self.assertIn("page_count", blocked["Blocked Reason"])

    def test_unknown_type_fails_loudly(self):
        result = review(artifact=self._good_interior(),
                        spec=spec(artifact_type="Mystery Artifact"),
                        config=QAConfig())
        self.assertEqual(result.hard_fails[0].check, "qa_dispatch")

    def test_unreadable_pdf_no_cascade(self):
        result = review(artifact=b"%PDF-" + b"\x00" * 2000, spec=spec(),
                        config=QAConfig())
        self.assertEqual(len(result.hard_fails), 1)
        self.assertEqual(result.hard_fails[0].check, "pdf_integrity")

    def test_bytes_and_path_agree(self):
        import tempfile
        data = self._good_interior()
        with tempfile.NamedTemporaryFile(suffix=".pdf",
                                         delete=False) as fh:
            fh.write(data)
            path = fh.name
        try:
            cfg = QAConfig()
            a = review(artifact=data, spec=spec(), config=cfg)
            b = review(artifact=path, spec=spec(), config=cfg)
            self.assertEqual(a.airtable_fields(cfg), b.airtable_fields(cfg))
        finally:
            os.unlink(path)

    def test_deterministic_and_timestamp_free(self):
        import re
        cfg = QAConfig()
        data = self._good_interior()
        first = review(artifact=data, spec=spec(), config=cfg)
        second = review(artifact=data, spec=spec(), config=cfg)
        self.assertEqual(first.airtable_fields(cfg),
                         second.airtable_fields(cfg))
        self.assertIsNone(
            re.search(r"\d{4}-\d{2}-\d{2}",
                      first.airtable_fields(cfg)["QA Report"]))

    def test_report_truncation_deterministic(self):
        cfg = QAConfig(max_report_chars=200)
        result = review(artifact=self._good_interior(), spec=spec(),
                        config=cfg)
        report = result.airtable_fields(cfg)["QA Report"]
        self.assertLessEqual(len(report), 200)
        self.assertIn("truncated", report)

    def test_config_from_env(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"QA_GATING_ENABLED": "true"}):
            self.assertTrue(QAConfig.from_env().gating_enabled)
        with patch.dict(os.environ, {"QA_GATING_ENABLED": "0"}):
            self.assertFalse(QAConfig.from_env().gating_enabled)
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(QAConfig.from_env().gating_enabled)


class TestHardcoverBinding(unittest.TestCase):
    """qa 0.2.0: binding-aware cover geometry + page bounds. Expected
    hardcover dims re-derived from KDP's metric spec (wrap 15mm, panel
    +5/+6mm, spine board 4.8mm)."""

    def _hc_cover_bytes(self, trim=(6.0, 9.0), pages=200):
        exp_w, exp_h = qa.expected_cover_dims(pages, "white", trim,
                                              "hardcover")
        data = blank_pdf_bytes(pages=1, width_pt=exp_w * 72.0,
                               height_pt=exp_h * 72.0)
        return data + b" " * max(0, qa.MIN_PDF_BYTES + 64 - len(data))

    def test_hardcover_expected_dims_match_kdp_goldens(self):
        # KDP calculator: 6x9 200pp white -> 14.214 x 10.417
        w, h = qa.expected_cover_dims(200, "white", (6.0, 9.0), "hardcover")
        self.assertAlmostEqual(round(w, 3), 14.214, places=3)
        self.assertAlmostEqual(round(h, 3), 10.417, places=3)
        # 8.25x11 -> 18.714 x 12.417
        w, h = qa.expected_cover_dims(200, "white", (8.25, 11.0), "hardcover")
        self.assertAlmostEqual(round(w, 3), 18.714, places=3)
        self.assertAlmostEqual(round(h, 3), 12.417, places=3)

    def test_hardcover_cover_passes_as_hardcover_fails_as_paperback(self):
        data = self._hc_cover_bytes()
        hc_spec = QASpec(artifact_type=ARTIFACT_COVER, trim=(6.0, 9.0),
                         page_count=200, paper="white", binding="hardcover")
        pb_spec = QASpec(artifact_type=ARTIFACT_COVER, trim=(6.0, 9.0),
                         page_count=200, paper="white")
        hc = review(artifact=data, spec=hc_spec, config=QAConfig())
        self.assertTrue(hc.passed, hc.report_lines())
        pb = review(artifact=data, spec=pb_spec, config=QAConfig())
        self.assertIn("page_geometry",
                      {v.check for v in pb.hard_fails})

    def test_hardcover_page_bounds(self):
        for n, ok in ((75, False), (76, True), (550, True), (551, False)):
            facts_n = facts(page_count=n)
            v = check_page_count(
                facts_n, QASpec(artifact_type=ARTIFACT_INTERIOR,
                                trim=TRIM_6X9, page_count=n,
                                binding="hardcover"))
            self.assertEqual(v.ok, ok, n)
        # paperback bounds unchanged: 100pp fine, 24 fine
        v = check_page_count(facts(page_count=24),
                             spec(page_count=24))
        self.assertTrue(v.ok)

    def test_hardcover_spine_posture_note(self):
        v = check_spine_posture(QASpec(artifact_type=ARTIFACT_COVER,
                                       trim=TRIM_6X9, page_count=76,
                                       paper="white", binding="hardcover"))
        self.assertEqual(v.severity, "note")
        self.assertIn("legibility", v.detail)

    def test_default_binding_is_paperback(self):
        self.assertEqual(spec().binding, "paperback")


if __name__ == "__main__":
    unittest.main()
