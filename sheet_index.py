"""
sheet_index.py — SheetCheck

Reads an architectural drawing-set PDF and, for every page, pulls the
sheet number and sheet title out of the title block (the info strip that
runs down the right-hand edge of each sheet). Prints a table of:

    page number | sheet number | sheet title

Usage:
    python sheet_index.py bidset.pdf
"""

import sys
import pdfplumber


# --- How we locate things in the title block -------------------------------
#
# Every sheet in this set uses the same title-block template. Two font sizes
# make the important text easy to find without hard-coding pixel positions:
#
#   * The SHEET NUMBER (e.g. "A8.1.2") is printed very large (~41 pt) in the
#     bottom-right corner. A "CD" phase code sits next to it at nearly the
#     same size, but the sheet number is the only big token that has a digit
#     in it — so "biggest font that contains a digit" reliably picks it.
#
#   * The SHEET TITLE (e.g. "INTERIOR ELEVATIONS") is printed at ~22 pt just
#     above the sheet number. It can wrap across a few lines, so we group the
#     title tokens into lines by their vertical position and read top-to-bottom.
#
# We only look inside the title-block strip: the right 10% of the page width,
# lower 40% of the page height. Using ratios (not fixed coordinates) keeps this
# working even if a page's size differs slightly.

RIGHT_STRIP_FRAC = 0.90   # x must be past 90% of page width
LOWER_STRIP_FRAC = 0.60   # y must be past 60% of page height (top-down)

NUMBER_MIN_SIZE = 30.0            # sheet number is ~41 pt; ignore small text
TITLE_SIZE_RANGE = (18.0, 26.0)  # sheet title is ~22 pt
LINE_BUCKET_PTS = 5              # tokens within this many pts share a line


def has_digit(text):
    return any(ch.isdigit() for ch in text)


def extract_title_block(page):
    """Return (sheet_number, sheet_title) for one page, best-effort."""
    w_page, h_page = page.width, page.height
    words = page.extract_words(extra_attrs=["size"])

    # Keep only tokens inside the title-block strip.
    strip = [
        w for w in words
        if w["x0"] > RIGHT_STRIP_FRAC * w_page
        and w["top"] > LOWER_STRIP_FRAC * h_page
    ]

    # --- Sheet number: biggest font that contains a digit -----------------
    num_candidates = [
        w for w in strip
        if w["size"] > NUMBER_MIN_SIZE and has_digit(w["text"])
    ]
    sheet_number = ""
    if num_candidates:
        sheet_number = max(num_candidates, key=lambda w: w["size"])["text"]

    # --- Sheet title: the ~22 pt text, grouped into lines -----------------
    lo, hi = TITLE_SIZE_RANGE
    title_tokens = [w for w in strip if lo < w["size"] < hi]

    lines = {}  # vertical bucket -> tokens on that line
    for w in title_tokens:
        bucket = round(w["top"] / LINE_BUCKET_PTS)
        lines.setdefault(bucket, []).append(w)

    tokens = []
    for bucket in sorted(lines):                       # top of page -> bottom
        row = sorted(lines[bucket], key=lambda w: w["x0"])   # left -> right
        tokens.extend(t["text"] for t in row)

    # Some titles are "double-struck" in the PDF (drawn twice at the same
    # spot to look bold), which yields "ROOF ROOF PLAN PLAN". Collapse any
    # word that simply repeats the word right before it.
    deduped = []
    for tok in tokens:
        if not deduped or deduped[-1] != tok:
            deduped.append(tok)

    sheet_title = " ".join(deduped).strip()
    return sheet_number, sheet_title


def build_index(pdf_path):
    """Return a list of (page_number, sheet_number, sheet_title)."""
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            number, title = extract_title_block(page)
            rows.append((i, number, title))
    return rows


def print_table(rows):
    """Print an aligned text table with no external dependencies."""
    headers = ("PAGE", "SHEET", "SHEET TITLE")
    num_w = max(len(headers[1]), *(len(r[1]) for r in rows)) if rows else len(headers[1])
    pg_w = max(len(headers[0]), len(str(len(rows))))

    print(f"{headers[0]:>{pg_w}}  {headers[1]:<{num_w}}  {headers[2]}")
    print(f"{'-'*pg_w}  {'-'*num_w}  {'-'*len(headers[2])}")
    for page_no, number, title in rows:
        number = number or "(none)"
        title = title or "(none)"
        print(f"{page_no:>{pg_w}}  {number:<{num_w}}  {title}")


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "bidset.pdf"
    rows = build_index(pdf_path)
    print_table(rows)

    found = sum(1 for _, num, _ in rows if num)
    print()
    print(f"{len(rows)} pages scanned — sheet number found on {found}.")


if __name__ == "__main__":
    main()
