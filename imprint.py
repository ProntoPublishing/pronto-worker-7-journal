"""
E4 Imprint Resolution (Imprint_Governance_v1, Manus SIGNED OFF
2026-07-19) — identical module vendored into every worker E4 touches.

Rules:
- Book Metadata `Imprint` link -> that flag, IF AND ONLY IF its
  `Bowker Canonical String` is recorded (Manus Amendment 2: no flag
  renders until registered). Linked but unregistered -> HOLD, never a
  silent substitute.
- No link -> the E4 Default row (Landfall Ink, governance §7) when
  ITS string is recorded; otherwise legacy PRONTO PUBLISHING —
  byte-identical to pre-E4 renders, which makes this module safe to
  deploy before Jesse's Bowker session fills the column.
- `canonical` is the character-for-character Bowker string (KDP
  exact-match surfaces: KDP imprint field, Bowker checklists).
  Display surfaces apply their own casing (covers upper-case).
- The Pronto credit line ("Interior design and typesetting by Pronto
  Publishing") is the MACHINE's credit and never changes (§7).

Author: Pronto Publishing
"""

from typing import Dict, Optional

LEGACY_IMPRINT = "Pronto Publishing"


class ImprintNotEligibleError(Exception):
    """Explicitly flagged book whose flag has no Bowker Canonical
    String — workers map this to a Review hold (Manus Amendment 2)."""


def resolve_imprint(book_metadata: Optional[Dict],
                    airtable_client) -> Dict[str, str]:
    """Returns {"flag", "canonical", "source"}."""
    bm = book_metadata or {}
    links = bm.get("Imprint") or []
    if links:
        rec = airtable_client.get_imprint(links[0])
        if rec is None:
            raise ImprintNotEligibleError(
                "linked Imprint record unreadable — cannot verify "
                "Bowker eligibility (Manus Amendment 2)")
        flag = (rec.get("Flag") or "").strip() or "(unnamed flag)"
        canonical = (rec.get("Bowker Canonical String") or "").strip()
        if not canonical:
            raise ImprintNotEligibleError(
                f"flag {flag!r} has no Bowker Canonical String recorded "
                f"— not E4-eligible until registered (Manus Amendment 2); "
                f"Jesse's Bowker session fills the column")
        return {"flag": flag, "canonical": canonical,
                "source": f"Book Metadata Imprint link ({flag})"}

    default = airtable_client.get_default_imprint()
    if default:
        canonical = (default.get("Bowker Canonical String") or "").strip()
        if canonical:
            return {"flag": (default.get("Flag") or "").strip(),
                    "canonical": canonical,
                    "source": "E4 default flag (no Imprint link)"}
    return {"flag": LEGACY_IMPRINT, "canonical": LEGACY_IMPRINT,
            "source": "legacy (no eligible flag — pre-E4 rendering)"}
