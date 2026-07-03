"""
extract.py — SheetCheck shared extraction layer

Pulls the sheet number + title out of every title block. The sheet NUMBER
rule is the same for every firm (biggest font in the bottom-right corner that
has a digit in it); the sheet TITLE is firm-specific and driven by the Profile
(horizontal vs rotated text), see profiles.py.

Because parsing all the large pages is slow (~1-2 min), results are cached to
disk next to the PDF, keyed on the PDF's size+mtime and the profile used, so
only the first run pays that cost.

Public API:
    extract_title_block(page, profile) -> (sheet_number, sheet_title)
    extract_sheets(pdf_path)           -> [{"page", "number", "title"}, ...]
"""

import json
import os

import pdfplumber

from profiles import detect_profile, DEFAULT_PROFILE


# The title block is the info strip down the right edge of each sheet.
RIGHT_STRIP_FRAC = 0.90
LOWER_STRIP_FRAC = 0.60
NUMBER_MIN_SIZE = 30.0
LINE_BUCKET_PTS = 5


def _has_digit(text):
    return any(ch.isdigit() for ch in text)


def _sheet_number(page, words):
    """Biggest-font token in the title block that contains a digit."""
    w_page, h_page = page.width, page.height
    strip = [
        w for w in words
        if w["x0"] > RIGHT_STRIP_FRAC * w_page
        and w["top"] > LOWER_STRIP_FRAC * h_page
    ]
    candidates = [w for w in strip
                  if w["size"] > NUMBER_MIN_SIZE and _has_digit(w["text"])]
    if not candidates:
        return ""
    return max(candidates, key=lambda w: w["size"])["text"]


def _title_horizontal(page, words, profile):
    """Title as upright text at ~title_size pt in the title block strip."""
    w_page, h_page = page.width, page.height
    lo, hi = profile.title_size_range
    tokens = [
        w for w in words
        if w["x0"] > RIGHT_STRIP_FRAC * w_page
        and w["top"] > LOWER_STRIP_FRAC * h_page
        and lo < w["size"] < hi
    ]

    lines = {}
    for w in tokens:
        lines.setdefault(round(w["top"] / LINE_BUCKET_PTS), []).append(w)

    ordered = []
    for bucket in sorted(lines):
        row = sorted(lines[bucket], key=lambda w: w["x0"])
        ordered.extend(t["text"] for t in row)

    # Collapse "double-struck" titles ("ROOF ROOF PLAN PLAN").
    deduped = []
    for tok in ordered:
        if not deduped or deduped[-1] != tok:
            deduped.append(tok)
    return " ".join(deduped).strip()


def _title_rotated(page, profile):
    """Title set vertically (rotated 90 deg): the leftmost column of rotated
    glyphs in the title box, read bottom-to-top."""
    W, H = page.width, page.height
    x0lo, x0hi, tlo, thi = profile.title_box_frac
    chars = [
        c for c in page.chars
        if not c["upright"]
        and x0lo * W < c["x0"] < x0hi * W
        and tlo * H < c["top"] < thi * H
    ]
    if not chars:
        return ""

    # Each rotated line stacks vertically at a roughly constant x. Group by x
    # column; the leftmost column is the sheet title (columns to its right are
    # the project name and location).
    columns = {}
    for c in chars:
        columns.setdefault(round(c["x0"] / 12), []).append(c)

    left = min(columns)
    title_chars = sorted(columns[left], key=lambda c: -c["top"])  # bottom -> top
    return "".join(c["text"] for c in title_chars).strip()


def extract_title_block(page, profile):
    """Return (sheet_number, sheet_title) for one page, best-effort."""
    words = page.extract_words(extra_attrs=["size"])
    number = _sheet_number(page, words)
    if profile.title_mode == "rotated":
        title = _title_rotated(page, profile)
    else:
        title = _title_horizontal(page, words, profile)
    return number, title


# --- caching ---------------------------------------------------------------

def _cache_path(pdf_path):
    return pdf_path + ".sheetcache.json"


def _fingerprint(pdf_path):
    st = os.stat(pdf_path)
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


def extract_sheets(pdf_path, use_cache=True):
    """Extract every page's sheet number + title, using a disk cache.

    Returns a list of {"page": 1-based int, "number": str, "title": str}.
    """
    cache_file = _cache_path(pdf_path)
    fp = _fingerprint(pdf_path)

    if use_cache and os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            if cached.get("fingerprint") == fp:
                return cached["sheets"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    with pdfplumber.open(pdf_path) as pdf:
        profile = detect_profile(pdf)
        sheets = []
        for i, page in enumerate(pdf.pages, start=1):
            number, title = extract_title_block(page, profile)
            sheets.append({"page": i, "number": number, "title": title})

    if use_cache:
        try:
            with open(cache_file, "w") as f:
                json.dump({"fingerprint": fp, "profile": profile.name, "sheets": sheets}, f, indent=1)
        except OSError:
            pass

    return sheets
