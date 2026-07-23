"""
Trim registry (Trims_v0 work order 2026-07-22) — the fleet's single
source of truth for what a trim size MEANS: dimensions, accepted
spellings, canonical names, spine math, gutter brackets, KDP bounds,
and the W2 interior geometry rows. Identical module vendored into
every worker (W2/W3/W4/W7/W8) — the imprint.py/qa.py pattern: no
cross-repo imports, byte-identity policed by sha compare + the
vendored tests/test_trims.py.

Doctrine:
- PARSEABLE is not RENDERABLE. The registry knows every trim the
  house has ruled on; each worker re-exports only its supported
  subset (INTERIOR_TRIMS, COVER_TRIMS, ...) as its accepted table.
  A trim outside a worker's subset keeps that worker's existing
  rejection posture (W3 hard-fail, W7/W8/W2 Review hold, W4
  arbitration hold) at the parse boundary — never a late KeyError.
- Spellings are unified fleet-wide at FOUR families per trim
  (bare '6x9', bare-space '6 x 9', ASCII-quoted '6" x 9"', and the
  U+00D7 form '6" × 9"') — this adopts W7's wider table everywhere
  and ends the 2026-07-22 recon's spelling drift. All spellings of
  one trim parse to identical dims; canonical name is the bare form.
- Workers' MATH stays local where it is adversarial by design (W4
  re-derives cover geometry so drift surfaces as an arbitration
  hold; qa.py re-derives everything). This module is the authority
  on the TABLE — what literals exist and what dims they mean — plus
  reference helpers for workers that already shared these constants.
- Uniform-margins type principle (Jesse's ruling 2026-07-23): every
  trade trim keeps the 6x9 margins (inner 0.85 / outer 0.65 /
  top 0.75 / bottom 0.85); the text measure floats with page width.
  CPL measured from corpus renders 2026-07-23: ~59 (5x8) to ~80
  (6.14x9.21; the shipped 6x9 reference measures 77); body stays
  11pt class / 1.066 stretch at every trim.

Author: Pronto Publishing
"""

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

TRIMS_VERSION = "1.0.0"

POINTS_PER_INCH = 72.0
BLEED_IN = 0.125

# Inches of spine per page (KDP spec G201953020; no additive constant
# — that is a hardcover-only term some calculators wrongly apply).
PAPER_FACTORS_IN_PER_PAGE: Dict[str, float] = {
    "white": 0.002252,
    "cream": 0.0025,
    "premium color": 0.002347,
}

# KDP paperback page bounds and the inside-margin (gutter) floor by
# TOTAL page count.
INTERIOR_MIN_PAGES = 24
INTERIOR_MAX_PAGES = 828
GUTTER_BRACKETS: Tuple[Tuple[int, int, float], ...] = (
    (24, 150, 0.375),
    (151, 300, 0.5),
    (301, 500, 0.625),
    (501, 700, 0.75),
    (701, 828, 0.875),
)


@dataclass(frozen=True)
class TrimSpec:
    name: str                   # canonical (bare) spelling
    width_in: float
    height_in: float
    category: str               # trade | large | low-content | square
    status: str                 # live | specced | dormant
    lane: str                   # one-line note: who renders it / why held

    @property
    def dims(self) -> Tuple[float, float]:
        return (self.width_in, self.height_in)

    def spellings(self) -> Tuple[str, ...]:
        """The four unified spelling families for this trim."""
        w = _fmt(self.width_in)
        h = _fmt(self.height_in)
        return (
            f"{w}x{h}",                 # bare
            f"{w} x {h}",               # bare-space
            f'{w}" x {h}"',             # ASCII-quoted
            f'{w}" × {h}"',        # U+00D7-quoted (live Tally form)
        )


def _fmt(v: float) -> str:
    s = f"{v:g}"
    return s


# The locked menu (work order 2026-07-22). Paperback rows; hardcover
# reuses these specs plus the dormant 8.25x11.
_SPECS: Tuple[TrimSpec, ...] = (
    TrimSpec("5x8", 5.0, 8.0, "trade", "live", "W2 interior (Trims v0)"),
    TrimSpec("5.25x8", 5.25, 8.0, "trade", "live", "W2 interior (Trims v0)"),
    TrimSpec("5.5x8.5", 5.5, 8.5, "trade", "live", "W2 interior (Trims v0)"),
    TrimSpec("6x9", 6.0, 9.0, "trade", "live",
             "W2 interior reference; W7 journal"),
    TrimSpec("6.14x9.21", 6.14, 9.21, "trade", "live",
             "W2 interior (Trims v0)"),
    TrimSpec("7x10", 7.0, 10.0, "large", "specced",
             "spec only — no W2 template yet (flagged, later ticket)"),
    TrimSpec("8x10", 8.0, 10.0, "low-content", "live",
             "W7 journal / W8 coloring (E2)"),
    TrimSpec("8.5x11", 8.5, 11.0, "low-content", "live",
             "W7 journal / W8 coloring (E2)"),
    TrimSpec("8.25x11", 8.25, 11.0, "large", "dormant",
             "hardcover-only (future hardcover ticket)"),
    TrimSpec("8.5x8.5", 8.5, 8.5, "square", "dormant",
             "children's/photo square (separate project-type ticket)"),
)

TRIMS: Dict[str, TrimSpec] = {spec.name: spec for spec in _SPECS}

# Every spelling of every registered trim -> canonical name. Collision
# check lives in tests/test_trims.py.
SPELLING_TO_NAME: Dict[str, str] = {
    literal: spec.name
    for spec in _SPECS
    for literal in spec.spellings()
}


def build_literal_table(names: Iterable[str]) -> Dict[str, Tuple[float, float]]:
    """A worker's accepted-literal table (drop-in for the per-repo
    ACCEPTED_TRIM_LITERALS dicts this module replaces)."""
    table: Dict[str, Tuple[float, float]] = {}
    for name in names:
        spec = TRIMS[name]
        for literal in spec.spellings():
            table[literal] = spec.dims
    return table


def canonical_by_dims(names: Iterable[str]) -> Dict[Tuple[float, float], str]:
    """dims -> canonical name, scoped to a worker's supported subset
    (W7's TRIM_CANONICAL shape)."""
    return {TRIMS[name].dims: name for name in names}


# --- Per-worker supported subsets (parseable != renderable) ---------

INTERIOR_TRIM_NAMES = ("5x8", "5.25x8", "5.5x8.5", "6x9", "6.14x9.21")
COVER_TRIM_NAMES = INTERIOR_TRIM_NAMES + ("8x10", "8.5x11")
KDPPACK_TRIM_NAMES = COVER_TRIM_NAMES
JOURNAL_TRIM_NAMES = ("6x9", "8x10", "8.5x11")
COLORING_TRIM_NAMES = ("8.5x11", "8x10", "6x9")   # W8's curated order

INTERIOR_TRIMS = build_literal_table(INTERIOR_TRIM_NAMES)
COVER_TRIMS = build_literal_table(COVER_TRIM_NAMES)
KDPPACK_TRIMS = build_literal_table(KDPPACK_TRIM_NAMES)
JOURNAL_TRIMS = build_literal_table(JOURNAL_TRIM_NAMES)
COLORING_TRIMS = build_literal_table(COLORING_TRIM_NAMES)


# --- W2 interior geometry rows (uniform-margins ruling) -------------

@dataclass(frozen=True)
class InteriorGeometry:
    trim_name: str
    top_in: float
    bottom_in: float
    inner_in: float
    outer_in: float
    title_sink_in: float        # system title page \vspace* sink
    cpl_estimate: Tuple[int, int]   # MEASURED band (corpus renders 2026-07-23)

    @property
    def text_measure_in(self) -> float:
        return round(TRIMS[self.trim_name].width_in
                     - self.inner_in - self.outer_in, 4)


_UNIFORM = dict(top_in=0.75, bottom_in=0.85, inner_in=0.85, outer_in=0.65)

INTERIOR_GEOMETRY: Dict[str, InteriorGeometry] = {
    # title_sink = 2in scaled by trim height / 9, rounded to 0.05
    # (6x9 keeps the shipped 2.00in exactly — byte-stability).
    "5x8": InteriorGeometry("5x8", title_sink_in=1.80,
                            cpl_estimate=(58, 61), **_UNIFORM),
    "5.25x8": InteriorGeometry("5.25x8", title_sink_in=1.80,
                               cpl_estimate=(63, 65), **_UNIFORM),
    "5.5x8.5": InteriorGeometry("5.5x8.5", title_sink_in=1.90,
                                cpl_estimate=(67, 69), **_UNIFORM),
    "6x9": InteriorGeometry("6x9", title_sink_in=2.00,
                            cpl_estimate=(76, 79), **_UNIFORM),
    "6.14x9.21": InteriorGeometry("6.14x9.21", title_sink_in=2.05,
                                  cpl_estimate=(79, 81), **_UNIFORM),
}


# --- Reference math helpers (shared arithmetic, not worker law) -----

def parse_trim_literal(value: Optional[str],
                       table: Dict[str, Tuple[float, float]]
                       ) -> Optional[Tuple[float, float]]:
    """Exact-literal lookup against a worker subset table. Returns
    None for absent/unknown — each worker maps that to ITS posture
    (hold/fail/default); this module never chooses for them."""
    literal = (str(value).strip() if value is not None else "")
    if not literal:
        return None
    return table.get(literal)


def canonical_name(value: Optional[str]) -> Optional[str]:
    """Any registered spelling -> canonical name (fleet-wide, not
    subset-scoped); None if unregistered."""
    literal = (str(value).strip() if value is not None else "")
    return SPELLING_TO_NAME.get(literal)


def spine_width_in(page_count: int, paper: str) -> float:
    return page_count * PAPER_FACTORS_IN_PER_PAGE[
        (paper or "cream").strip().lower()]


def cover_dims_in(trim: Tuple[float, float],
                  spine_in: float) -> Tuple[float, float]:
    trim_w, trim_h = trim
    return (BLEED_IN + trim_w + spine_in + trim_w + BLEED_IN,
            BLEED_IN + trim_h + BLEED_IN)


def gutter_floor_in(total_pages: int) -> Optional[float]:
    for lo, hi, floor in GUTTER_BRACKETS:
        if lo <= total_pages <= hi:
            return floor
    return None
