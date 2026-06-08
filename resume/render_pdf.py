"""
Resume PDF renderer.
Converts the Markdown produced by tailor._save_markdown() into a clean,
ATS-friendly single-column PDF using fpdf2 (pure Python, no system deps).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fpdf import FPDF

# fpdf2 subsets embedded fonts and logs every dropped glyph table at INFO. That
# floods server.log/briefing.log on every render, so keep it to real warnings.
logging.getLogger("fontTools").setLevel(logging.WARNING)

# ── Layout constants ──────────────────────────────────────────────────────────
# Tightened for single-page rendering at senior/staff resume density.
MARGIN      = 14        # mm left/right
TOP_MARGIN  = 9         # mm top
BOT_MARGIN  = 7         # mm bottom
PAGE_W      = 210       # A4
CONTENT_W   = PAGE_W - 2 * MARGIN

# Font sizes
SIZE_NAME    = 18
SIZE_SECTION = 10
SIZE_BODY    = 9
SIZE_META    = 8.5
SIZE_CONTACT = 8.5

# Line heights (mm)
LH_BODY    = 3.9
LH_META    = 3.5
LH_SECTION = 4.6
LH_CONTACT = 4.2

# ── Colors (R, G, B) ─────────────────────────────────────────────────────────
# Accent: Deep teal (#0F4C5C) — modern AI/tech professional
# Applied to: name + section headers + rules. Body text stays neutral.
BLACK      = (15,  15,  15)
DARK_GRAY  = (50,  50,  50)
MID_GRAY   = (110, 110, 110)
RULE_GRAY  = (190, 190, 190)
ACCENT     = (15,  76,  92)   # #0F4C5C deep teal
RULE_TEAL  = (120, 175, 185)  # lighter teal for section rules

# ── Font: Arial Unicode (ships with macOS, full Unicode) ─────────────────────
# Falls back to the built-in Helvetica core font when the TTF isn't present
# (e.g. on a non-macOS machine), with Unicode punctuation transliterated to
# ASCII so the core font's latin-1 encoder never chokes.
FONT_PATH = "/Library/Fonts/Arial Unicode.ttf"
_HAS_TTF  = os.path.exists(FONT_PATH)
FONT_NAME = "ArialUnicode" if _HAS_TTF else "Helvetica"
BULLET    = "•" if _HAS_TTF else "-"

_FALLBACK_MAP = str.maketrans({
    "•": "-", "–": "-", "—": "-", "→": "->", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
})


# ── Markdown helpers ──────────────────────────────────────────────────────────

def _strip(text: str) -> str:
    """Remove **bold**, *italic*, and [link](url) markers."""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*',     r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    if not _HAS_TTF:
        text = text.translate(_FALLBACK_MAP)
    return text


# ── PDF class ─────────────────────────────────────────────────────────────────

class _PDF(FPDF):
    def header(self): pass
    def footer(self): pass

    def _load_fonts(self):
        """Register Arial Unicode for all styles (called once after add_page).
        No-op when falling back to the built-in Helvetica core font."""
        if not _HAS_TTF:
            return
        self.add_font(FONT_NAME, style="",  fname=FONT_PATH)
        self.add_font(FONT_NAME, style="B", fname=FONT_PATH)
        self.add_font(FONT_NAME, style="I", fname=FONT_PATH)

    def rule(self):
        """Thin teal horizontal line under section headings."""
        self.set_draw_color(*RULE_TEAL)
        self.set_line_width(0.4)
        y = self.get_y()
        self.line(MARGIN, y, PAGE_W - MARGIN, y)

    def section_heading(self, text: str):
        self.ln(1.5)
        self.set_font(FONT_NAME, "B", SIZE_SECTION)
        self.set_text_color(*ACCENT)
        self.cell(0, LH_SECTION, text.upper(), new_x="LMARGIN", new_y="NEXT")
        self.rule()
        self.ln(0.8)

    def job_header(self, text: str):
        self.set_font(FONT_NAME, "B", SIZE_BODY + 0.5)
        self.set_text_color(*DARK_GRAY)
        self.multi_cell(0, LH_BODY, _strip(text), new_x="LMARGIN", new_y="NEXT")

    def job_meta(self, text: str):
        self.set_font(FONT_NAME, "I", SIZE_META)
        self.set_text_color(*MID_GRAY)
        self.cell(0, LH_META, _strip(text), new_x="LMARGIN", new_y="NEXT")

    def two_col_row(self, left: str, right: str, *, bold: bool, italic: bool):
        """Render `left` flush-left and `right` flush-right on the same line.

        Used for: Company / Location and Title / Date rows.
        """
        style = "B" if bold else ("I" if italic else "")
        size  = SIZE_BODY + 0.5 if bold else SIZE_META
        color = DARK_GRAY if bold else MID_GRAY
        lh    = LH_BODY if bold else LH_META

        self.set_font(FONT_NAME, style, size)
        self.set_text_color(*color)

        y_start = self.get_y()
        self.set_xy(MARGIN, y_start)
        self.cell(CONTENT_W, lh, _strip(left), align="L")
        # Reset to same Y to overlay the right-aligned cell on the same line
        self.set_xy(MARGIN, y_start)
        self.cell(CONTENT_W, lh, _strip(right), align="R", new_x="LMARGIN", new_y="NEXT")

    def bullet(self, text: str):
        self.set_font(FONT_NAME, "", SIZE_BODY)
        self.set_text_color(*DARK_GRAY)
        self.set_x(MARGIN + 2)
        self.cell(3, LH_BODY, BULLET)
        self.set_x(MARGIN + 5)
        self.multi_cell(CONTENT_W - 5, LH_BODY, _strip(text), new_x="LMARGIN", new_y="NEXT")

    def skill_row(self, category: str, skills: str):
        """Render '**Category:** skills...' as a single wrapped line using inline bold."""
        category = category.rstrip(":").strip()
        self.set_font(FONT_NAME, "", SIZE_BODY)
        self.set_text_color(*DARK_GRAY)
        self.set_x(MARGIN)
        self.multi_cell(
            0, LH_BODY,
            f"**{category}:** {_strip(skills)}",
            markdown=True,
            new_x="LMARGIN",
            new_y="NEXT",
        )

    def edu_row(self, text: str):
        self.set_font(FONT_NAME, "", SIZE_BODY)
        self.set_text_color(*DARK_GRAY)
        self.multi_cell(0, LH_BODY, _strip(text), new_x="LMARGIN", new_y="NEXT")

    def plain(self, text: str):
        self.set_font(FONT_NAME, "", SIZE_BODY)
        self.set_text_color(*DARK_GRAY)
        self.multi_cell(0, LH_BODY, _strip(text), new_x="LMARGIN", new_y="NEXT")


# ── Renderer ──────────────────────────────────────────────────────────────────

def render_pdf(md_path: Path, pdf_path: Path) -> None:
    """Parse *md_path* and write a clean PDF to *pdf_path*."""
    lines = md_path.read_text(encoding="utf-8").splitlines()

    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=BOT_MARGIN)
    pdf.add_page()
    pdf._load_fonts()
    pdf.set_margins(MARGIN, TOP_MARGIN, MARGIN)
    pdf.set_y(TOP_MARGIN)

    prev_was_h1 = False

    for raw in lines:
        line = raw.rstrip()

        # Skip blank lines (we control spacing ourselves)
        if not line:
            prev_was_h1 = False
            continue

        # Skip trailing note
        if line.startswith("*Note:") or line.startswith("---"):
            continue

        # H1 — candidate name (in accent color)
        if line.startswith("# "):
            name = line[2:].strip()
            pdf.set_font(FONT_NAME, "B", SIZE_NAME)
            pdf.set_text_color(*ACCENT)
            pdf.cell(0, 8, name, new_x="LMARGIN", new_y="NEXT", align="C")
            prev_was_h1 = True
            continue

        # Contact line — the plain-text line immediately after H1
        if prev_was_h1:
            contact = _strip(line)
            pdf.set_font(FONT_NAME, "", SIZE_CONTACT)
            pdf.set_text_color(*MID_GRAY)
            pdf.cell(0, LH_CONTACT, contact, new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.ln(1.5)
            prev_was_h1 = False
            continue

        prev_was_h1 = False

        # H2 — section heading
        if line.startswith("## "):
            pdf.section_heading(line[3:].strip())
            continue

        # Tab-separated two-column line: "LEFT\tRIGHT"
        # Used for job-header rows (Company \t Location) and (Title \t Date).
        if "\t" in line:
            left, right = line.split("\t", 1)
            left, right = left.strip(), right.strip()
            is_bold   = left.startswith("**") and left.endswith("**")
            is_italic = (left.startswith("*") and left.endswith("*")
                         and not is_bold)
            pdf.two_col_row(left, right, bold=is_bold, italic=is_italic)
            continue

        # Bullet
        if line.startswith("- "):
            pdf.bullet(line[2:])
            continue

        # Skills row: **Category:** value
        skill_match = re.match(r'\*\*([^*]+)\*\*[:\s]*(.*)', line)
        if skill_match and "**" in line:
            category = skill_match.group(1).strip()
            skills   = skill_match.group(2).strip()
            # Distinguish job header (**Company** — Title) from skill row (has colon after **)
            if line.rstrip().endswith("*") or ("—" in line and ":" not in line.split("**")[1]):
                pdf.job_header(line)
            else:
                pdf.skill_row(category, skills)
            continue

        # Italic line *...*  (job meta: location | dates)
        if line.startswith("*") and line.endswith("*") and not line.startswith("**"):
            pdf.job_meta(line[1:-1])
            pdf.ln(0.3)
            continue

        # Everything else (summary paragraph, plain edu lines, etc.)
        pdf.plain(line)

    pdf.output(str(pdf_path))
