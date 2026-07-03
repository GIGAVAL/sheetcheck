"""
profiles.py — SheetCheck title-block profiles

Every architecture firm draws its title block differently: the sheet title
may be horizontal or rotated 90 degrees, the sheet index may have two or
three columns, sheet numbers may or may not use dashes. Rather than hard-code
one firm's layout, SheetCheck keeps a small profile per template and detects
which one a PDF uses from the architect's name stamped on the sheets.

Adding support for a new firm = adding one Profile below.

Two things are the SAME across the firms we've seen and so live in extract.py,
not here: the page is one big landscape sheet, and the sheet NUMBER is the
biggest font in the bottom-right corner that contains a digit.
"""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    name: str

    # Detection: if any of these strings appears in the sampled page text
    # (upper-cased), the PDF is treated as this firm's template.
    architect_markers: tuple

    # --- sheet title ---
    # "horizontal": title is upright text at ~title_size pt near the number.
    # "rotated": title is set vertically (rotated 90 deg); read it from chars.
    title_mode: str
    title_size_range: tuple = (18.0, 26.0)          # horizontal only
    # rotated only: box to look in, as fractions of page (x0lo, x0hi, toplo, tophi).
    title_box_frac: tuple = (0.915, 0.985, 0.64, 0.86)

    # --- sheet index (the master list of sheets) ---
    index_page: int = 2
    index_number_re: "re.Pattern" = field(default=None)
    index_text_max_size: float = 12.0
    # When a row has no further number to the right, a title runs at most
    # this many points past its number.
    index_title_fallback_width: float = 545.0


SMITHGROUP = Profile(
    name="SmithGroup",
    architect_markers=("SMITHGROUP", "SMITHGROUP.COM"),
    title_mode="horizontal",
    title_size_range=(18.0, 26.0),
    index_page=2,
    # e.g. G1.1, A2.1.1, M0.2 — letters, a digit, then one or more ".x" groups.
    # Requiring a dot group rejects consultant names like "NV5" that would
    # otherwise match (real SmithGroup sheet numbers always have a dot).
    index_number_re=re.compile(r"^[A-Z]{1,3}[0-9][0-9A-Z]*(?:\.[0-9A-Z]+)+$"),
    index_title_fallback_width=545.0,
)

GRIMM_PARKER = Profile(
    name="Grimm & Parker",
    architect_markers=("GRIMM AND PARKER", "GRIMM & PARKER"),
    title_mode="rotated",
    # Rotated titles read bottom-to-top, so a long title's tail rises high on
    # the page; the box must reach up far enough (top 0.55) not to clip it.
    # upright=False filtering keeps the grid labels/notes above out of it.
    title_box_frac=(0.912, 0.987, 0.55, 0.90),
    index_page=2,
    # e.g. A-1.1, TS-1H, C-1.00H, S-3.2H — a dash, and at least one digit.
    index_number_re=re.compile(r"^[A-Z]{1,3}-[0-9A-Z.]*[0-9][0-9A-Z.]*$"),
    index_text_max_size=13.0,   # G&P index text is ~12.4 pt
    index_title_fallback_width=430.0,   # keep the rightmost column clear of the revision table
)

PROFILES = (SMITHGROUP, GRIMM_PARKER)
DEFAULT_PROFILE = SMITHGROUP


def detect_profile(pdf, sample_pages=(0, 4, 1)):
    """Return the Profile whose architect marker appears in the PDF.

    Reads the text of a few pages and looks for each firm's name. Falls back
    to DEFAULT_PROFILE if nothing matches (with the name recorded so callers
    can warn).
    """
    text = []
    for i in sample_pages:
        if i < len(pdf.pages):
            text.append((pdf.pages[i].extract_text() or "").upper())
    blob = "\n".join(text)

    for profile in PROFILES:
        if any(marker in blob for marker in profile.architect_markers):
            return profile
    return DEFAULT_PROFILE
