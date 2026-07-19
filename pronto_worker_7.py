"""
Pronto Worker 7 - Journal/Planner Builder (W7 v0)
==================================================

Airtable Book Metadata (NO manuscript, NO W1) -> interior.pdf +
journal_manifest.json. Spec: W7_Journal_WorkOrder_v0 rev B (FROZEN
2026-07-18). Zero dependencies — the first such worker; Met is
vacuously 1, so the Active=false catalog flag and no-Zap-until-
ratified discipline are the real gates.

R7 postures (ratified — "can a human act on this without touching
code? Hold. Otherwise FAIL"):
- W7-001 template missing/unrecognized -> FAIL (unrecoverable input)
- W7-002 TOTAL pages (body + 4) outside KDP 24-828 -> hold; the note
  states BOTH numbers so the human sees the arithmetic
- W7-003 Prompted without prompts / too few / prompt overflow -> hold
  (editorial trim is human)
- W7-004 rendered page size != trim exactly, or page count != TOTAL
  -> FAIL (self-check; a wrong PDF is not human-fixable)
- metadata incomplete (Title/Author) -> hold (unnumbered, same gate
  machinery); trim outside the pinned table -> hold (trim expansion
  2026-07-19: 6x9 / 8x10 / 8.5x11 per the E2 pattern; anything else
  stays a business conversation, not a code path)

Writes Interior Page Count = TOTAL at completion — same field, same
semantics as W2 >=1.7.1; the COVER chain consumes it.

Author: Pronto Publishing
"""

import hashlib
import io
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pypdf import PdfReader

from geometry import (
    BODY_MAX, BODY_MIN, DEFAULT_BODY_PAGES, POINTS_PER_INCH,
    TOTAL_MAX, TOTAL_MIN, TRIM_CANONICAL, TEMPLATES,
    TrimRejectedError, parse_trim, total_pages,
)
from imprint import ImprintNotEligibleError, resolve_imprint
from manifest import build_journal_manifest
from render import PromptOverflowError, build_interior
from lib.airtable_client import AirtableClient
from lib.pronto_r2_client import ProntoR2Client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

WORKER_VERSION = "7.2.0-a1"

_PAGE_SIZE_TOL_PT = 0.01     # exactness at float-compare granularity


class HardFailError(Exception):
    """W7-001 / W7-004 / artifact write failure: Status -> Failed."""


class ReviewHold(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}" if code else message)


class JournalProcessor:
    """Main Worker 7 processor."""

    def __init__(self):
        self.worker_name = "worker_7_journal"
        self.worker_version = WORKER_VERSION
        self.r2_client = ProntoR2Client(
            account_id=os.getenv('R2_ACCOUNT_ID'),
            access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
            secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
            bucket_name=os.getenv('R2_BUCKET_NAME', 'pronto-artifacts'),
            public_base_url=os.getenv('R2_PUBLIC_BASE_URL')
        )
        self.airtable_client = AirtableClient()

    # ------------------------------------------------------------------

    def check_idempotency(self, service, service_id):
        status = service.get('Status')
        if status == 'Complete' and service.get('Artifact URL'):
            return {'status': 'already_complete',
                    'message': 'Service already processed',
                    'service_id': service_id}
        if status == 'Processing':
            return {'status': 'already_processing',
                    'message': 'Service is currently being processed',
                    'service_id': service_id}
        if status == 'Review':
            return {'status': 'in_review',
                    'message': 'Service is held for human review',
                    'service_id': service_id}
        return None

    def claim(self, service_id):
        self.airtable_client.update_service(service_id, {
            'Status': 'Processing',
            'Started At': datetime.now(timezone.utc).isoformat(),
            'Worker Version': self.worker_version,
        })
        logger.info(f"Claimed service {service_id}: Status -> Processing")

    def process_service(self, service_id, already_claimed=False):
        started_at = datetime.now(timezone.utc)
        logger.info(f"Starting Worker 7 for service {service_id}")
        try:
            service = self.airtable_client.get_service(service_id)
            if not service:
                raise HardFailError(f"Service {service_id} not found")
            if not already_claimed:
                noop = self.check_idempotency(service, service_id)
                if noop:
                    return noop
                self.claim(service_id)
            return self._process_claimed(service_id, service, started_at)
        except ReviewHold as h:
            self._hold_service(service_id, str(h))
            return {'success': True, 'service_id': service_id,
                    'status': 'Review', 'review_reason': str(h)}
        except Exception as e:
            logger.error(f"Processing failed: {e}", exc_info=True)
            self._fail_service(service_id, str(e))
            return {'success': False, 'service_id': service_id,
                    'error': str(e)}

    # ------------------------------------------------------------------

    def _process_claimed(self, service_id, service, started_at):
        verdicts: List[dict] = []
        warnings: List[str] = []

        bm = self._get_book_metadata(service)
        if bm is None:
            raise ReviewHold("", "no Book Metadata linked to the project")

        # --- Metadata completeness (hold) ---
        title = (bm.get("Book Title") or "").strip()
        subtitle = (bm.get("Subtitle") or "").strip() or None
        author = (bm.get("Author Name") or "").strip()
        if not title or not author:
            raise ReviewHold("", f"metadata incomplete: Title={title!r} "
                                 f"Author={author!r}")
        verdicts.append({"check": "metadata_required", "ok": True,
                         "detail": "title/author present"})

        # --- Trim (pinned three-trim table; outside it -> hold — the
        # posture that proved itself in soak run #1) ---
        try:
            trim = parse_trim(self._select_name(bm.get("Trim Size")))
        except TrimRejectedError as e:
            raise ReviewHold("", str(e))
        trim_name = TRIM_CANONICAL[trim]
        verdicts.append({"check": "trim", "ok": True, "detail": trim_name})

        # --- Template (W7-001: FAIL) ---
        template = self._select_name(bm.get("Low-Content Template"))
        if not template or template not in TEMPLATES:
            raise HardFailError(
                f"Low-Content Template missing/unrecognized: {template!r} "
                f"(accepted: {', '.join(TEMPLATES)}) (W7-001)")
        verdicts.append({"check": "template", "ok": True, "detail": template})

        # --- Page accounting on TOTAL (W7-002: hold, both numbers) ---
        raw_count = bm.get("Low-Content Page Count")
        body = int(raw_count) if raw_count else DEFAULT_BODY_PAGES
        total = total_pages(body)
        if not (TOTAL_MIN <= total <= TOTAL_MAX):
            raise ReviewHold(
                "W7-002",
                f"body {body} -> total {total} outside KDP's "
                f"{TOTAL_MIN}-{TOTAL_MAX} total-page bounds; body must be "
                f"{BODY_MIN}-{BODY_MAX}")
        verdicts.append({"check": "page_bounds", "ok": True,
                         "detail": f"body {body} -> total {total}"})

        # --- Prompts (W7-003: hold) ---
        prompts: Optional[List[str]] = None
        if template == "Prompted":
            prompts = self._split_lines(bm.get("Prompt Set"))
            if not prompts:
                raise ReviewHold("W7-003",
                                 "Prompted template with no Prompt Set — "
                                 "prompts are editorial content (Doc 14)")
            if len(prompts) < body:
                raise ReviewHold(
                    "W7-003",
                    f"Prompt Set has {len(prompts)} prompts for {body} "
                    f"body pages — one per page required")
            verdicts.append({"check": "prompts", "ok": True,
                             "detail": f"{len(prompts)} prompts for "
                                       f"{body} pages"})

        isbn = (bm.get("ISBN") or "").strip() or None

        # --- E4 imprint resolution (Manus Amendment 2 gate) ---
        try:
            imprint = resolve_imprint(bm, self.airtable_client)
        except ImprintNotEligibleError as e:
            raise ReviewHold("", str(e))
        legacy = imprint["source"].startswith("legacy")
        verdicts.append({"check": "imprint", "ok": True,
                         "detail": f"{imprint['flag']} ({imprint['source']})"})

        # --- Render ---
        try:
            pdf_bytes, params = build_interior(
                title=title, subtitle=subtitle, author=author,
                template=template, body_pages=body,
                copyright_year=datetime.now(timezone.utc).year,
                isbn=isbn, prompts=prompts,
                imprint_display=imprint["canonical"].upper(),
                published_by=None if legacy else imprint["canonical"],
                trim=trim)
        except PromptOverflowError as e:
            raise ReviewHold("W7-003", str(e))

        # --- Self-check (W7-004: FAIL) — page size per the PARSED trim ---
        page_w_pt = trim[0] * POINTS_PER_INCH
        page_h_pt = trim[1] * POINTS_PER_INCH
        reader = PdfReader(io.BytesIO(pdf_bytes))
        n = len(reader.pages)
        if n != total:
            raise HardFailError(
                f"self-check: rendered {n} pages, expected TOTAL {total} "
                f"(W7-004)")
        for idx, page in enumerate(reader.pages):
            box = page.mediabox
            w, h = float(box.width), float(box.height)
            if abs(w - page_w_pt) > _PAGE_SIZE_TOL_PT or \
               abs(h - page_h_pt) > _PAGE_SIZE_TOL_PT:
                raise HardFailError(
                    f"self-check: page {idx + 1} is {w}x{h}pt, expected "
                    f"{page_w_pt}x{page_h_pt}pt exactly (W7-004)")
        verdicts.append({"check": "self_check", "ok": True,
                         "detail": f"{n} pages at "
                                   f"{trim[0]}x{trim[1]}in exact"})

        # --- Manifest + upload ---
        sha = hashlib.sha256(pdf_bytes).hexdigest()
        m = build_journal_manifest(
            worker_version=self.worker_version,
            inputs={
                "source": "Book Metadata (no manuscript — low-content lane)",
                "title": title, "subtitle": subtitle, "author": author,
                "template": template, "isbn": isbn,
                "prompt_count": len(prompts) if prompts else None,
                "imprint": imprint,
            },
            params=params, validation=verdicts, warnings=warnings,
            interior_sha256=sha)

        pdf_key = f"services/{service_id}/interior.pdf"
        manifest_key = f"services/{service_id}/journal_manifest.json"
        try:
            pdf_up = self.r2_client.upload_file_bytes(
                object_key=pdf_key, data=pdf_bytes,
                content_type="application/pdf")
            manifest_up = self.r2_client.upload_json(
                object_key=manifest_key, data=m)
        except Exception as e:
            raise HardFailError(f"artifact write failure: {e}")

        duration = (datetime.now(timezone.utc) - started_at).total_seconds()
        notes = {
            "template": template,
            "trim": trim_name,
            "body_pages": body,
            "total_pages": total,
            "gutter_bracket_in": m["geometry"]["gutter_bracket_in"],
            "interior_sha256": sha[:16],
            "manifest_url": manifest_up["public_url"],
            "duration_seconds": duration,
        }
        if warnings:
            notes["warnings"] = warnings
        self.airtable_client.update_service(service_id, {
            "Status": "Complete",
            "Finished At": datetime.now(timezone.utc).isoformat(),
            "Artifact URL": pdf_up["public_url"],
            "Artifact Key": pdf_key,
            "Artifact Type": "Interior PDF",
            "Interior Page Count": total,
            "Operator Notes": f"Journal build: {json.dumps(notes, indent=2)}",
        }, typecast=True)

        logger.info("Done: Complete")
        return {"success": True, "service_id": service_id,
                "status": "Complete", "interior_url": pdf_up["public_url"],
                "manifest_url": manifest_up["public_url"],
                "template": template, "body_pages": body,
                "total_pages": total, "duration_seconds": duration}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _select_name(value):
        """Airtable singleSelect values arrive as str or {name} dict."""
        if isinstance(value, dict):
            return value.get("name")
        return value

    def _get_book_metadata(self, service):
        project_links = service.get('Project', [])
        if not project_links:
            return None
        project = self.airtable_client.get_project(project_links[0])
        if not project:
            return None
        links = project.get('Book Metadata', [])
        return self.airtable_client.get_book_metadata(links[0]) if links else None

    @staticmethod
    def _split_lines(value):
        if not value:
            return []
        return [ln.strip() for ln in str(value).splitlines() if ln.strip()]

    def _hold_service(self, service_id, reason):
        self.airtable_client.update_service(service_id, {
            'Status': 'Review',
            'Finished At': datetime.now(timezone.utc).isoformat(),
            'Operator Notes': f"Journal build HELD: {reason}",
        }, typecast=True)
        logger.info(f"Held service {service_id}: Status -> Review")

    def _fail_service(self, service_id, error_message):
        self.airtable_client.update_service(service_id, {
            'Status': 'Failed',
            'Finished At': datetime.now(timezone.utc).isoformat(),
            'Error Log': error_message,
        })
        logger.info(f"Failed service {service_id}: Status -> Failed")


def main():
    if len(sys.argv) < 2:
        print("Usage: python pronto_worker_7.py <service_id>")
        sys.exit(1)
    processor = JournalProcessor()
    result = processor.process_service(sys.argv[1])
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get('success') or result.get('status') else 1)


if __name__ == '__main__':
    main()
