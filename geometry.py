"""
W7 Geometry — pure functions, full float precision
===================================================

Spec: W7_Journal_WorkOrder_v0 rev B (FROZEN 2026-07-18). Same
no-internal-rounding discipline as W3's geometry: constants are exact
fractions where possible, everything else carries full float
precision to the renderer; rounding happens only at draw time inside
ReportLab.

THE CENTRAL RULE (rev B): all KDP math runs on TOTAL printed pages,
never the customer-facing body count. TOTAL = body + FRONT_MATTER_PAGES
(pinned at 4: half-title recto, blank verso, title recto, (c) verso —
body opens recto on page 5). The gutter bracket is selected by TOTAL;
the boundary trap, named in the order: body 150 -> total 154 -> 0.5"
bracket. A body-count lookup selects 0.375" and manufactures a gutter
violation exactly at the boundary.

Author: Pronto Publishing
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Trim + page accounting (rev B pinned; trim table expanded per
# W7_Trim_Expansion_WorkOrder_v0 2026-07-19 — the E2 pattern)
# ---------------------------------------------------------------------------

# 6x9 remains the reference design; these constants are its dims and
# stay importable so the 6x9 goldens hold byte-identical.
TRIM_W_IN = 6.0
TRIM_H_IN = 9.0
POINTS_PER_INCH = 72.0

REFERENCE_TRIM: Tuple[float, float] = (TRIM_W_IN, TRIM_H_IN)

# Pinned trim table — the same three trims E2 gave W3, spelled the
# same way (ASCII "x" and U+00D7 variants both live in production
# Airtable data; the three-spellings lesson stands). Anything outside
# this table HOLDs in the worker — no silently-plausible untested
# geometry. 5x8 / 5.5x8.5 remain docketed with E2's.
# Trims v0 (2026-07-23): sourced from the vendored trims.py registry
# (JOURNAL_TRIMS). W7's four-spelling table was the fleet's widest —
# the registry adopted it fleet-wide, so this re-point is
# byte-equivalent for every previously accepted literal.
from trims import JOURNAL_TRIM_NAMES, JOURNAL_TRIMS as _JOURNAL_TRIMS
from trims import canonical_by_dims as _canonical_by_dims

ACCEPTED_TRIM_LITERALS: Dict[str, Tuple[float, float]] = dict(_JOURNAL_TRIMS)

# Canonical short name per dims — manifests and Operator Notes speak
# one spelling regardless of which literal the form sent.
TRIM_CANONICAL: Dict[Tuple[float, float], str] = _canonical_by_dims(
    JOURNAL_TRIM_NAMES)


class TrimRejectedError(ValueError):
    """Any trim outside the pinned table. The worker maps this to a
    Review HOLD (v0 posture that proved itself in soak run #1)."""


def parse_trim(value) -> Tuple[float, float]:
    """Airtable Trim Size literal -> (w, h) inches. Exact literal
    match against the pinned table; empty/None defaults to the 6x9
    reference (the low-content lane's historical default)."""
    literal = (str(value).strip() if value is not None else "")
    if not literal:
        return REFERENCE_TRIM
    if literal not in ACCEPTED_TRIM_LITERALS:
        raise TrimRejectedError(
            f"trim {literal!r} not in the pinned trim table "
            f"(accepted: {sorted(set(TRIM_CANONICAL.values()))}; widening "
            f"the table is a versioned spec change)")
    return ACCEPTED_TRIM_LITERALS[literal]


# E2's type-scale lesson, applied to journal interiors: the 6x9 pitch
# on 8.5x11 looks lost. Factors follow E2's map (geometric mean of the
# axis ratios, rounded to a clean stop): 8x10 -> 1.2, 8.5x11 -> 1.3.
# Pitches are pinned per trim as EXACT fractions at those factors —
# no runtime multiplication mud:
#   Lined:    5/16"  ->  3/8" (x1.2)  ->  13/32" (x1.3)
#   Dot grid: 5 mm   ->  6 mm (x1.2)  ->  6.5 mm (x1.3)
TRIM_TYPE_SCALE: Dict[Tuple[float, float], float] = {
    (6.0, 9.0): 1.0,
    (8.0, 10.0): 1.2,
    (8.5, 11.0): 1.3,
}

LINE_PITCH_BY_TRIM: Dict[Tuple[float, float], float] = {
    (6.0, 9.0): 5.0 / 16.0,
    (8.0, 10.0): 3.0 / 8.0,
    (8.5, 11.0): 13.0 / 32.0,
}

DOT_PITCH_BY_TRIM: Dict[Tuple[float, float], float] = {
    (6.0, 9.0): 5.0 / 25.4,
    (8.0, 10.0): 6.0 / 25.4,
    (8.5, 11.0): 6.5 / 25.4,
}

FRONT_MATTER_PAGES = 4          # half-title, blank, title, (c) — PINNED
TOTAL_MIN = 24                  # KDP floor, TOTAL pages
TOTAL_MAX = 828                 # KDP ceiling, TOTAL pages
BODY_MIN = TOTAL_MIN - FRONT_MATTER_PAGES    # 20
BODY_MAX = TOTAL_MAX - FRONT_MATTER_PAGES    # 824
DEFAULT_BODY_PAGES = 120

# ---------------------------------------------------------------------------
# KDP gutter table — pinned (rev A amendment 2), selected by TOTAL
# ---------------------------------------------------------------------------

GUTTER_BRACKETS: Tuple[Tuple[int, int, float], ...] = (
    (24, 150, 0.375),
    (151, 300, 0.5),
    (301, 500, 0.625),
    (501, 700, 0.75),
    (701, 828, 0.875),
)

# House margins. INSIDE = bracket floor + comfort pad; the pad keeps
# the live area visually balanced against the 0.5" outside margin at
# the low brackets without ever dipping under KDP's floor.
INSIDE_COMFORT_PAD_IN = 0.125
OUTSIDE_MARGIN_IN = 0.5
TOP_MARGIN_IN = 0.625
BOTTOM_MARGIN_IN = 0.625

# ---------------------------------------------------------------------------
# Template constants — exact fractions, no mm->in rounding mud
# ---------------------------------------------------------------------------

LINE_PITCH_IN = 5.0 / 16.0          # 0.3125" ruled pitch
DOT_PITCH_IN = 5.0 / 25.4           # 5 mm bullet-journal grid, exact
DOT_RADIUS_PT = 0.75
LINE_WIDTH_PT = 0.5
HEADER_RULE_WIDTH_PT = 1.1
HEADER_RULE_GAP_IN = 0.125          # gap between header rule and first row
INK_GRAY = 0.55                     # template ink (lines/dots), not text

TEMPLATES = ("Lined", "Dot Grid", "Blank", "Prompted")


class GutterBracketError(ValueError):
    """TOTAL outside every pinned bracket — FAIL posture (pinned-table
    discipline; §4). Unreachable when bounds are checked first, which
    is exactly why it must be loud if it ever fires."""


def total_pages(body_pages: int) -> int:
    return body_pages + FRONT_MATTER_PAGES


def gutter_for_total(total: int) -> float:
    """Inside-gutter FLOOR in inches for TOTAL printed pages."""
    for lo, hi, gutter in GUTTER_BRACKETS:
        if lo <= total <= hi:
            return gutter
    raise GutterBracketError(
        f"TOTAL {total} matches no pinned gutter bracket "
        f"({GUTTER_BRACKETS[0][0]}-{GUTTER_BRACKETS[-1][1]})")


def inside_margin_for_total(total: int) -> float:
    return gutter_for_total(total) + INSIDE_COMFORT_PAD_IN


@dataclass(frozen=True)
class LiveArea:
    """Printable region of one page, inches from bottom-left of trim."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def live_area(total: int, page_number: int,
              trim: Tuple[float, float] = REFERENCE_TRIM) -> LiveArea:
    """Live area for 1-based printed page number. Odd = recto (inside
    margin on the LEFT edge of the sheet as bound = left side of a
    recto), even = verso (inside on the right). Derived from
    (trim, TOTAL) — rev B: a grid compliant at one TOTAL must
    re-derive, not reuse, at another. Margins are physical (KDP's
    floors don't scale with trim); only the sheet grows."""
    inside = inside_margin_for_total(total)
    recto = page_number % 2 == 1
    left = inside if recto else OUTSIDE_MARGIN_IN
    right = OUTSIDE_MARGIN_IN if recto else inside
    trim_w, trim_h = trim
    return LiveArea(
        x0=left,
        y0=BOTTOM_MARGIN_IN,
        x1=trim_w - right,
        y1=trim_h - TOP_MARGIN_IN,
    )


# ---------------------------------------------------------------------------
# Template geometry — positions in inches within a LiveArea
# ---------------------------------------------------------------------------

def lined_rows(area: LiveArea, *, header_rule: bool = True,
               pitch: float = LINE_PITCH_IN) -> List[float]:
    """Y positions (page inches) of ruled lines, top to bottom. Rows
    descend from the top of the live area at exact pitch; the last row
    sits at or above y0. With header_rule, the first line is the rule
    and rows resume after HEADER_RULE_GAP_IN."""
    rows: List[float] = []
    y = area.y1
    if header_rule:
        rows.append(y)
        y -= pitch + HEADER_RULE_GAP_IN
    while y >= area.y0:
        rows.append(y)
        y -= pitch
    return rows


def dot_grid_points(area: LiveArea,
                    pitch: float = DOT_PITCH_IN) -> List[Tuple[float, float]]:
    """Dot centers (page inches). The grid is CENTERED in the live
    area: residual space is split evenly on both axes so the grid
    never crowds one edge."""
    import math
    nx = int(math.floor(area.width / pitch)) + 1
    ny = int(math.floor(area.height / pitch)) + 1
    x_start = area.x0 + (area.width - (nx - 1) * pitch) / 2.0
    y_start = area.y0 + (area.height - (ny - 1) * pitch) / 2.0
    return [(x_start + i * pitch, y_start + j * pitch)
            for j in range(ny) for i in range(nx)]
