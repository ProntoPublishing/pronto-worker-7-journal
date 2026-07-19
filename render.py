"""
W7 Renderer — deterministic low-content interior PDF
=====================================================

ReportLab, invariant=1 (byte-identical on identical inputs), grayscale
only, Lora statics vendored (OFL — the W2 lesson: never trust the
image's fonts). Front matter PINNED at 4 pages (rev B): half-title
recto, blank verso, title recto, (c) verso; body opens recto on
page 5.

The (c) page wording is W2 1.7.3's Standard §3.4 block, byte-for-byte
at the line level (tests pin it against the captured fixture).

Author: Pronto Publishing
"""

import io
import os
from typing import Dict, List, Optional

from reportlab.lib.colors import black
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

from geometry import (
    DOT_PITCH_BY_TRIM, DOT_RADIUS_PT, FRONT_MATTER_PAGES,
    HEADER_RULE_WIDTH_PT, INK_GRAY, LINE_PITCH_BY_TRIM, LINE_WIDTH_PT,
    LiveArea, POINTS_PER_INCH, REFERENCE_TRIM, TRIM_CANONICAL,
    TRIM_H_IN, TRIM_TYPE_SCALE, TRIM_W_IN, dot_grid_points, lined_rows,
    live_area, total_pages,
)

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

SERIF = "Lora"
SERIF_MEDIUM = "Lora-Medium"
SERIF_ITALIC = "Lora-Italic"

IMPRINT = "PRONTO PUBLISHING"
IMPRINT_TRACKING_PT = 2.2

PAGE_W_PT = TRIM_W_IN * POINTS_PER_INCH   # 432.0 (6x9 reference)
PAGE_H_PT = TRIM_H_IN * POINTS_PER_INCH   # 648.0 (6x9 reference)

PROMPT_FONT_SIZE = 11.5
PROMPT_LEADING = 15.5
PROMPT_MAX_LINES = 4                       # overflow -> hold (W7-003)
PROMPT_GAP_IN = 0.2                        # gap between prompt block and rows

FOLIO_FONT_SIZE = 9.0
FOLIO_BASELINE_IN = 0.375                  # from trim bottom, inside margins


class _Page:
    """Per-trim layout context (trim expansion, 2026-07-19). E2's
    split: type sizes/leadings scale by TRIM_TYPE_SCALE (taste,
    drafted for Jesse's eyeball); positional anchors scale exactly by
    axis ratios vs the 6x9 reference (arithmetic). At 6x9 every factor
    is exactly 1.0, so all multiplications are float-exact no-ops and
    the goldens hold byte-identical."""

    def __init__(self, trim):
        self.trim = trim
        self.w_in, self.h_in = trim
        self.w_pt = self.w_in * POINTS_PER_INCH
        self.h_pt = self.h_in * POINTS_PER_INCH
        self.scale = TRIM_TYPE_SCALE[trim]
        self.rx = self.w_in / TRIM_W_IN     # axis ratios vs reference
        self.ry = self.h_in / TRIM_H_IN
        self.line_pitch = LINE_PITCH_BY_TRIM[trim]
        self.dot_pitch = DOT_PITCH_BY_TRIM[trim]


class PromptOverflowError(ValueError):
    """Prompt wraps past PROMPT_MAX_LINES at template size — editorial
    trim is human (W7-003 hold)."""

    def __init__(self, page_index: int, prompt: str, lines: int):
        self.page_index = page_index
        self.prompt = prompt
        self.lines = lines
        super().__init__(
            f"prompt for body page {page_index} wraps to {lines} lines "
            f"(max {PROMPT_MAX_LINES}): {prompt[:80]!r}")


def _register_fonts() -> None:
    if SERIF not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(SERIF, os.path.join(FONT_DIR, "Lora-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(SERIF_MEDIUM, os.path.join(FONT_DIR, "Lora-Medium.ttf")))
        pdfmetrics.registerFont(TTFont(SERIF_ITALIC, os.path.join(FONT_DIR, "Lora-Italic.ttf")))


# ---------------------------------------------------------------------------
# W2 1.7.3 (c)-page wording — Standard §3.4 [BOUND], pinned
# ---------------------------------------------------------------------------

def copyright_lines(year: int, author: str,
                    isbn: Optional[str]) -> List[str]:
    """The Standard §3.4 block as rendered text lines, W2 1.7.3
    wording byte-for-byte: (c) line, ISBN line when present (no
    colon), imprint credit, site, edition line."""
    lines = [f"Copyright © {year} {author}. All rights reserved."]
    if isbn:
        lines.append(f"ISBN {isbn}")
    lines += [
        "Interior design and typesetting by Pronto Publishing",
        "prontopublishing.com",
        f"First edition, {year}",
    ]
    return lines


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def wrap_text(text: str, font: str, size: float, max_width_pt: float) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(trial, font, size) <= max_width_pt or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_tracked_center(c, pg: _Page, text: str, font: str, size: float,
                         tracking: float, y_pt: float) -> None:
    """Centered letter-tracked caps line. W3 PORTING_NOTES lesson #1:
    always reset setCharSpace(0) before ending the text object."""
    width = pdfmetrics.stringWidth(text, font, size) + tracking * max(len(text) - 1, 0)
    t = c.beginText((pg.w_pt - width) / 2.0, y_pt)
    t.setFont(font, size)
    t.setCharSpace(tracking)
    t.textOut(text)
    t.setCharSpace(0)
    c.drawText(t)


def _draw_center(c, pg: _Page, text: str, font: str, size: float,
                 y_pt: float) -> None:
    c.setFont(font, size)
    c.drawCentredString(pg.w_pt / 2.0, y_pt, text)


# ---------------------------------------------------------------------------
# Page painters
# ---------------------------------------------------------------------------

def _paint_half_title(c, pg: _Page, title: str) -> None:
    _draw_center(c, pg, title.upper(), SERIF_MEDIUM, 16.0 * pg.scale,
                 pg.h_pt * 0.62)


def _paint_title_page(c, pg: _Page, title: str, subtitle: Optional[str],
                      author: str, imprint_display: str = IMPRINT) -> None:
    y = pg.h_pt * 0.66
    for line in wrap_text(title.upper(), SERIF_MEDIUM, 24.0 * pg.scale,
                          pg.w_pt * 0.72):
        _draw_center(c, pg, line, SERIF_MEDIUM, 24.0 * pg.scale, y)
        y -= 30.0 * pg.scale
    if subtitle:
        y -= 6.0 * pg.scale
        for line in wrap_text(subtitle, SERIF_ITALIC, 13.0 * pg.scale,
                              pg.w_pt * 0.7):
            _draw_center(c, pg, line, SERIF_ITALIC, 13.0 * pg.scale, y)
            y -= 17.0 * pg.scale
    _draw_center(c, pg, author, SERIF, 14.0 * pg.scale, pg.h_pt * 0.38)
    _draw_tracked_center(c, pg, imprint_display, SERIF, 9.5 * pg.scale,
                         IMPRINT_TRACKING_PT * pg.scale,
                         1.0 * pg.ry * POINTS_PER_INCH)


def _paint_copyright(c, pg: _Page, year: int, author: str,
                     isbn: Optional[str],
                     published_by: Optional[str] = None) -> None:
    lines = copyright_lines(year, author, isbn)
    if published_by:
        # E4: publisher flag line ahead of the machine's credit. The
        # Pronto credit line below never changes (governance §7).
        lines.insert(len(lines) - 3, f"Published by {published_by}")
    # Standard §3.4 sits low on the page, flush left within margins.
    # Anchors scale by exact axis ratios (E2 arithmetic rule).
    y = 2.1 * pg.ry * POINTS_PER_INCH
    x = 1.0 * pg.rx * POINTS_PER_INCH
    c.setFont(SERIF, 9.0 * pg.scale)
    gaps_after = {0 if not isbn else 1, len(lines) - 2}
    for i, line in enumerate(lines):
        c.drawString(x, y, line)
        y -= 13.0 * pg.scale
        if i in gaps_after:
            y -= 8.0 * pg.scale  # the \\[1em] breathing gaps of the LaTeX block
    del gaps_after


def _paint_lined(c, pg: _Page, area: LiveArea, header_rule: bool) -> None:
    rows = lined_rows(area, header_rule=header_rule, pitch=pg.line_pitch)
    c.setStrokeGray(INK_GRAY)
    for i, y in enumerate(rows):
        c.setLineWidth(HEADER_RULE_WIDTH_PT if (header_rule and i == 0)
                       else LINE_WIDTH_PT)
        c.line(area.x0 * POINTS_PER_INCH, y * POINTS_PER_INCH,
               area.x1 * POINTS_PER_INCH, y * POINTS_PER_INCH)
    c.setStrokeColor(black)


def _paint_dot_grid(c, pg: _Page, area: LiveArea) -> None:
    c.setFillGray(INK_GRAY)
    for x, y in dot_grid_points(area, pitch=pg.dot_pitch):
        c.circle(x * POINTS_PER_INCH, y * POINTS_PER_INCH,
                 DOT_RADIUS_PT, stroke=0, fill=1)
    c.setFillColor(black)


def _paint_prompt(c, pg: _Page, area: LiveArea, prompt: str,
                  body_index: int) -> LiveArea:
    """Prompt block at the top of the live area, house serif; returns
    the remaining live area for ruled rows below it."""
    size = PROMPT_FONT_SIZE * pg.scale
    leading = PROMPT_LEADING * pg.scale
    lines = wrap_text(prompt, SERIF_MEDIUM, size,
                      area.width * POINTS_PER_INCH)
    if len(lines) > PROMPT_MAX_LINES:
        raise PromptOverflowError(body_index, prompt, len(lines))
    c.setFillColor(black)
    y_pt = area.y1 * POINTS_PER_INCH - size
    c.setFont(SERIF_MEDIUM, size)
    for line in lines:
        c.drawString(area.x0 * POINTS_PER_INCH, y_pt, line)
        y_pt -= leading
    block_h_in = (len(lines) * leading) / POINTS_PER_INCH
    return LiveArea(x0=area.x0, y0=area.y0, x1=area.x1,
                    y1=area.y1 - block_h_in - PROMPT_GAP_IN * pg.scale)


def _paint_folio(c, pg: _Page, body_index: int) -> None:
    _draw_center(c, pg, str(body_index), SERIF, FOLIO_FONT_SIZE * pg.scale,
                 FOLIO_BASELINE_IN * POINTS_PER_INCH)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_interior(*, title: str, subtitle: Optional[str], author: str,
                   template: str, body_pages: int, copyright_year: int,
                   isbn: Optional[str] = None,
                   prompts: Optional[List[str]] = None,
                   page_numbers: bool = True,
                   header_rule: bool = True,
                   imprint_display: str = IMPRINT,
                   published_by: Optional[str] = None,
                   trim: tuple = REFERENCE_TRIM) -> tuple:
    """Render the full interior. Returns (pdf_bytes, params) where
    params is the geometry/typography record for the manifest.
    Prompted template requires prompts, one per body page (validation
    happens in the worker BEFORE render; render re-asserts). `trim`
    must be a pinned-table (w, h); the worker parses/holds upstream."""
    _register_fonts()
    total = total_pages(body_pages)
    pg = _Page(trim)

    if template == "Prompted":
        assert prompts is not None and len(prompts) >= body_pages, \
            "worker must validate prompts before render"

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(pg.w_pt, pg.h_pt),
                         invariant=1, initialFontName=SERIF)
    c.setTitle(f"{title} — interior")
    c.setAuthor(IMPRINT.title())

    # --- Front matter, PINNED at 4 pages ---
    _paint_half_title(c, pg, title)      # 1: half-title recto
    c.showPage()
    c.showPage()                         # 2: blank verso
    _paint_title_page(c, pg, title, subtitle, author,
                      imprint_display=imprint_display)   # 3: title recto
    c.showPage()
    _paint_copyright(c, pg, copyright_year, author, isbn,
                     published_by=published_by)  # 4: (c) verso
    c.showPage()

    # --- Body, opens recto on printed page 5 ---
    for i in range(body_pages):
        page_number = FRONT_MATTER_PAGES + i + 1
        area = live_area(total, page_number, trim=pg.trim)
        if template == "Lined":
            _paint_lined(c, pg, area, header_rule)
        elif template == "Dot Grid":
            _paint_dot_grid(c, pg, area)
        elif template == "Prompted":
            remaining = _paint_prompt(c, pg, area, prompts[i], i + 1)
            _paint_lined(c, pg, remaining, header_rule=False)
        elif template == "Blank":
            pass
        else:
            raise ValueError(f"unknown template {template!r}")
        if page_numbers:
            _paint_folio(c, pg, i + 1)
        c.showPage()

    c.save()
    params: Dict = {
        "template": template,
        "body_pages": body_pages,
        "front_matter_pages": FRONT_MATTER_PAGES,
        "total_pages": total,
        "page_numbers": page_numbers,
        "header_rule": header_rule if template in ("Lined",) else False,
        "imprint_display": imprint_display,
        "published_by": published_by,
        "fonts": [SERIF, SERIF_MEDIUM, SERIF_ITALIC],
        "trim": TRIM_CANONICAL[pg.trim],
        "trim_in": [pg.w_in, pg.h_in],
        "type_scale": pg.scale,
        "line_pitch_in": pg.line_pitch,
        "dot_pitch_in": pg.dot_pitch,
    }
    return buf.getvalue(), params
