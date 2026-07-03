"""
extract.py — SheetCheck shared extraction layer

Pulling the sheet number + title out of all 133 title blocks is the slow
part (pdfplumber fully parses every large page, ~1-2 min total). Every
check would otherwise re-do that work, so this module does it once and
caches the result to disk next to the PDF.

The cache is keyed on the PDF's size and modification time, so it is used
only while the PDF is unchanged; replace the PDF and it re-extracts.

Public API:
    extract_title_block(page)  -> (sheet_number, sheet_title)
    extract_sheets(pdf_path)   -> [{"page": int, "number": str, "title": str}, ...]
"""

import json
import os

import pdfplumber


# --- Title-block geometry (see project notes) ------------------------------
# The title block is the info strip down the right edge of each sheet. Two
# font sizes make the important text easy to find without hard-coding pixel
# positions: the SHEET NUMBER prints ~41 pt, the SHEET TITLE ~22 pt.
RIGHT_STRIP_FRAC = 0.90
LOWER_STRIP_FRAC = 0.60
NUMBER_MIN_SIZE = 30.0
TITLE_SIZE_RANGE = (18.0, 26.0)
LINE_BUCKET_PTS = 5


def _has_digit(text):
    return any(ch.isdigit() for ch in text)


def extract_title_block(page):
    """Return (sheet_number, sheet_title) for one page, best-effort."""
    w_page, h_page = page.width, page.height
    words = page.extract_words(extra_attrs=["size"])

    strip = [
        w for w in words
        if w["x0"] > RIGHT_STRIP_FRAC * w_page
        and w["top"] > LOWER_STRIP_FRAC * h_page
    ]

    # Sheet number: biggest font that contains a digit (excludes the "CD"
    # phase code, which is nearly as large but has no digit).
    num_candidates = [
        w for w in strip
        if w["size"] > NUMBER_MIN_SIZE and _has_digit(w["text"])
    ]
    sheet_number = ""
    if num_candidates:
        sheet_number = max(num_candidates, key=lambda w: w["size"])["text"]

    # Sheet title: the ~22 pt text, grouped into lines and read top-to-bottom.
    lo, hi = TITLE_SIZE_RANGE
    title_tokens = [w for w in strip if lo < w["size"] < hi]

    lines = {}
    for w in title_tokens:
        bucket = round(w["top"] / LINE_BUCKET_PTS)
        lines.setdefault(bucket, []).append(w)

    tokens = []
    for bucket in sorted(lines):
        row = sorted(lines[bucket], key=lambda w: w["x0"])
        tokens.extend(t["text"] for t in row)

    # Collapse "double-struck" titles (word repeated at the same spot).
    deduped = []
    for tok in tokens:
        if not deduped or deduped[-1] != tok:
            deduped.append(tok)

    return sheet_number, " ".join(deduped).strip()


def _cache_path(pdf_path):
    return pdf_path + ".sheetcache.json"


def _fingerprint(pdf_path):
    st = os.stat(pdf_path)
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


def extract_sheets(pdf_path, use_cache=True):
    """Extract every page's sheet number + title, using a disk cache.

    Returns a list of dicts: {"page": 1-based int, "number": str, "title": str}.
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
            pass  # unreadable cache -> just re-extract

    sheets = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            number, title = extract_title_block(page)
            sheets.append({"page": i, "number": number, "title": title})

    if use_cache:
        try:
            with open(cache_file, "w") as f:
                json.dump({"fingerprint": fp, "sheets": sheets}, f, indent=1)
        except OSError:
            pass  # caching is best-effort

    return sheets
