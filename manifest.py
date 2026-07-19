"""
W7 Manifest Builder — journal_manifest.json (spec §7)
======================================================

Doc 11: template + geometry params (incl. the gutter bracket and the
TOTAL-page math), page accounting, fonts, versions. A stranger audits
the build from this alone.

Author: Pronto Publishing
"""

from typing import Dict, List

from geometry import (
    BODY_MAX, BODY_MIN, FRONT_MATTER_PAGES, GUTTER_BRACKETS,
    INSIDE_COMFORT_PAD_IN, OUTSIDE_MARGIN_IN, TOTAL_MAX, TOTAL_MIN,
    gutter_for_total, inside_margin_for_total,
)

SPEC_VERSION = ("W7_Journal_WorkOrder_v0 rev B (FROZEN 2026-07-18) + "
                "W7_Trim_Expansion_WorkOrder_v0 (2026-07-19)")
MANIFEST_SCHEMA_VERSION = "journal_manifest.v1.1"


def build_journal_manifest(
    *,
    worker_version: str,
    inputs: Dict,
    params: Dict,               # from render.build_interior
    validation: List[dict],
    warnings: List[str],
    interior_sha256: str,
) -> Dict:
    total = params["total_pages"]
    return {
        "manifest_schema": MANIFEST_SCHEMA_VERSION,
        "spec_version": SPEC_VERSION,
        "worker_version": worker_version,
        "inputs": inputs,
        "page_accounting": {
            "body_pages": params["body_pages"],
            "front_matter_pages": FRONT_MATTER_PAGES,
            "front_matter_layout": "half-title recto / blank verso / "
                                   "title recto / copyright verso — "
                                   "body opens recto on page 5 (rev B pin)",
            "total_pages": total,
            "bounds": {"total": [TOTAL_MIN, TOTAL_MAX],
                       "body": [BODY_MIN, BODY_MAX]},
            "rule": "ALL KDP math runs on TOTAL, never body (rev B)",
        },
        "geometry": {
            "trim": params["trim"],
            "trim_in": params["trim_in"],
            "type_scale": params["type_scale"],
            "gutter_bracket_in": gutter_for_total(total),
            "gutter_bracket_table": [list(b) for b in GUTTER_BRACKETS],
            "gutter_selected_by": "TOTAL pages",
            "inside_margin_in": inside_margin_for_total(total),
            "inside_comfort_pad_in": INSIDE_COMFORT_PAD_IN,
            "outside_margin_in": OUTSIDE_MARGIN_IN,
            "line_pitch_in": params["line_pitch_in"],
            "dot_pitch_in": params["dot_pitch_in"],
            "template_params": params,
        },
        "validation": validation,
        "warnings": warnings,
        "artifacts": {
            "interior_pdf_sha256": interior_sha256,
            "determinism": ("byte-identical PDF on identical inputs: "
                            "ReportLab invariant=1, vendored Lora "
                            "statics, grayscale-only ink"),
        },
        "isbn_posture": (
            "Low-content: KDP neither requires nor assigns an ISBN. "
            "The (c) page carries the ISBN line only when Jesse's pool "
            "deliberately assigned one (spec §6); the checklist's "
            "low-content variant (E5) states the tradeoffs."
        ),
    }
