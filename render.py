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
    DOT_RADIUS_PT, FRONT_MATTER_PAGES, HEADER_RULE_WIDTH_PT, INK_GRAY,
    LINE_WIDTH_PT, LiveArea, POINTS_PER_INCH, TRIM_H_IN, TRIM_W_IN,
    dot_grid_points, lined_rows, live_area, total_pages,
)

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

SERIF = "Lora"
SERIF_MEDIUM = "Lora-Medium"
SERIF_ITALIC = "Lora-Italic"

IMPRINT = "PRONTO PUBLISHING"
IMPRINT_TRACKING_PT = 2.2

PAGE_W_PT = TRIM_W_IN * POINTS_PER_INCH   # 432.0
PAGE_H_PT = TRIM_H_IN * POINTS_PER_INCH   # 648.0

PROMPT_FONT_SIZE = 11.5
PROMPT_LEADING = 15.5
PROMPT_MAX_LINES = 4                       # overflow -> hold (W7-003)
PROMPT_GAP_IN = 0.2                        # gap between prompt block and rows

FOLIO_FONT_SIZE = 9.0
FOLIO_BASELINE_IN = 0.375                  # from trim bottom, inside margins


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


def _draw_tracked_center(c, text: str, font: str, size: float,
                         tracking: float, y_pt: float) -> None:
    """Centered letter-tracked caps line. W3 PORTING_NOTES lesson #1:
    always reset setCharSpace(0) before ending the text object."""
    width = pdfmetrics.stringWidth(text, font, size) + tracking * max(len(text) - 1, 0)
    t = c.beginText((PAGE_W_PT - width) / 2.0, y_pt)
    t.setFont(font, size)
    t.setCharSpace(tracking)
    t.textOut(text)
    t.setCharSpace(0)
    c.drawText(t)


def _draw_center(c, text: str, font: str, size: float, y_pt: float) -> None:
    c.setFont(font, size)
    c.drawCentredString(PAGE_W_PT / 2.0, y_pt, text)


# ---------------------------------------------------------------------------
# Page painters
# ---------------------------------------------------------------------------

def _paint_half_title(c, title: str) -> None:
    _draw_center(c, title.upper(), SERIF_MEDIUM, 16.0, PAGE_H_PT * 0.62)


def _paint_title_page(c, title: str, subtitle: Optional[str],
                      author: str, imprint_display: str = IMPRINT) -> None:
    y = PAGE_H_PT * 0.66
    for line in wrap_text(title.upper(), SERIF_MEDIUM, 24.0, PAGE_W_PT * 0.72):
        _draw_center(c, line, SERIF_MEDIUM, 24.0, y)
        y -= 30.0
    if subtitle:
        y -= 6.0
        for line in wrap_text(subtitle, SERIF_ITALIC, 13.0, PAGE_W_PT * 0.7):
            _draw_center(c, line, SERIF_ITALIC, 13.0, y)
            y -= 17.0
    _draw_center(c, author, SERIF, 14.0, PAGE_H_PT * 0.38)
    _draw_tracked_center(c, imprint_display, SERIF, 9.5, IMPRINT_TRACKING_PT,
                         1.0 * POINTS_PER_INCH)


def _paint_copyright(c, year: int, author: str, isbn: Optional[str],
                     published_by: Optional[str] = None) -> None:
    lines = copyright_lines(year, author, isbn)
    if published_by:
        # E4: publisher flag line ahead of the machine's credit. The
        # Pronto credit line below never changes (governance §7).
        lines.insert(len(lines) - 3, f"Published by {published_by}")
    # Standard §3.4 sits low on the page, flush left within margins.
    y = 2.1 * POINTS_PER_INCH
    x = 1.0 * POINTS_PER_INCH
    c.setFont(SERIF, 9.0)
    gaps_after = {0 if not isbn else 1, len(lines) - 2}
    for i, line in enumerate(lines):
        c.drawString(x, y, line)
        y -= 13.0
        if i in gaps_after:
            y -= 8.0       # the \\[1em] breathing gaps of the LaTeX block
    del gaps_after


def _paint_lined(c, area: LiveArea, header_rule: bool) -> None:
    rows = lined_rows(area, header_rule=header_rule)
    c.setStrokeGray(INK_GRAY)
    for i, y in enumerate(rows):
        c.setLineWidth(HEADER_RULE_WIDTH_PT if (header_rule and i == 0)
                       else LINE_WIDTH_PT)
        c.line(area.x0 * POINTS_PER_INCH, y * POINTS_PER_INCH,
               area.x1 * POINTS_PER_INCH, y * POINTS_PER_INCH)
    c.setStrokeColor(black)


def _paint_dot_grid(c, area: LiveArea) -> None:
    c.setFillGray(INK_GRAY)
    for x, y in dot_grid_points(area):
        c.circle(x * POINTS_PER_INCH, y * POINTS_PER_INCH,
                 DOT_RADIUS_PT, stroke=0, fill=1)
    c.setFillColor(black)


def _paint_prompt(c, area: LiveArea, prompt: str,
                  body_index: int) -> LiveArea:
    """Prompt block at the top of the live area, house serif; returns
    the remaining live area for ruled rows below it."""
    lines = wrap_text(prompt, SERIF_MEDIUM, PROMPT_FONT_SIZE,
                      area.width * POINTS_PER_INCH)
    if len(lines) > PROMPT_MAX_LINES:
        raise PromptOverflowError(body_index, prompt, len(lines))
    c.setFillColor(black)
    y_pt = area.y1 * POINTS_PER_INCH - PROMPT_FONT_SIZE
    c.setFont(SERIF_MEDIUM, PROMPT_FONT_SIZE)
    for line in lines:
        c.drawString(area.x0 * POINTS_PER_INCH, y_pt, line)
        y_pt -= PROMPT_LEADING
    block_h_in = (len(lines) * PROMPT_LEADING) / POINTS_PER_INCH
    return LiveArea(x0=area.x0, y0=area.y0, x1=area.x1,
                    y1=area.y1 - block_h_in - PROMPT_GAP_IN)


def _paint_folio(c, body_index: int) -> None:
    _draw_center(c, str(body_index), SERIF, FOLIO_FONT_SIZE,
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
                   published_by: Optional[str] = None) -> tuple:
    """Render the full interior. Returns (pdf_bytes, params) where
    params is the geometry/typography record for the manifest.
    Prompted template requires prompts, one per body page (validation
    happens in the worker BEFORE render; render re-asserts)."""
    _register_fonts()
    total = total_pages(body_pages)

    if template == "Prompted":
        assert prompts is not None and len(prompts) >= body_pages, \
            "worker must validate prompts before render"

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(PAGE_W_PT, PAGE_H_PT),
                         invariant=1, initialFontName=SERIF)
    c.setTitle(f"{title} — interior")
    c.setAuthor(IMPRINT.title())

    # --- Front matter, PINNED at 4 pages ---
    _paint_half_title(c, title)          # 1: half-title recto
    c.showPage()
    c.showPage()                         # 2: blank verso
    _paint_title_page(c, title, subtitle, author,
                      imprint_display=imprint_display)   # 3: title recto
    c.showPage()
    _paint_copyright(c, copyright_year, author, isbn,
                     published_by=published_by)  # 4: (c) verso
    c.showPage()

    # --- Body, opens recto on printed page 5 ---
    for i in range(body_pages):
        page_number = FRONT_MATTER_PAGES + i + 1
        area = live_area(total, page_number)
        if template == "Lined":
            _paint_lined(c, area, header_rule)
        elif template == "Dot Grid":
            _paint_dot_grid(c, area)
        elif template == "Prompted":
            remaining = _paint_prompt(c, area, prompts[i], i + 1)
            _paint_lined(c, remaining, header_rule=False)
        elif template == "Blank":
            pass
        else:
            raise ValueError(f"unknown template {template!r}")
        if page_numbers:
            _paint_folio(c, i + 1)
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
    }
    return buf.getvalue(), params
