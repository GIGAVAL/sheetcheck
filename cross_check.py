"""
cross_check.py — SheetCheck QA/QC check

Cross-checks the drawing set against its own Sheet Index (the master list
of sheets printed on page 2). Three things can go wrong in a real set:

  * MISSING  — the index lists a sheet, but no page in the PDF has it
               (a sheet was dropped when the set was assembled).
  * EXTRA    — a page exists whose sheet number isn't in the index
               (a sheet was added but the index wasn't updated).
  * MISMATCH — the sheet exists in both, but its title on the drawing
               doesn't match the title in the index (a title was edited
               in one place but not the other).

It reuses the title-block extractor from sheet_index.py so both the
"what's actually in the set" and "what the index claims" come from the
same PDF, parsed the same way.

Usage:
    python cross_check.py bidset.pdf
"""

import re
import sys

import pdfplumber

from sheet_index import build_index, extract_title_block  # noqa: F401


# The sheet index on page 2 is a two-column list. Sheet numbers sit in two
# narrow x-bands; each title runs to the right of its number for a fixed
# column width. These bands come from measuring page 2 (see project notes).
INDEX_PAGE = 2                      # 1-based page number of the sheet index
NUM_RE = re.compile(r"^[A-Z]{1,3}[0-9][0-9A-Z.]*$")
COL_BANDS = ((1000, 1050), (1590, 1650))   # x0 ranges of the two number columns
TITLE_COL_WIDTH = 545               # how far right of the number the title runs
INDEX_TEXT_MAX_SIZE = 12            # index text is ~9.6 pt; ignore larger text


def parse_sheet_index(page):
    """Return {sheet_number: title} parsed from the sheet-index page."""
    words = [w for w in page.extract_words(extra_attrs=["size"])
             if w["size"] < INDEX_TEXT_MAX_SIZE]

    def in_a_column(x0):
        return any(lo < x0 < hi for lo, hi in COL_BANDS)

    numbers = [w for w in words
               if NUM_RE.match(w["text"]) and "." in w["text"]
               and in_a_column(w["x0"])]

    index = {}
    for n in numbers:
        right_edge = n["x0"] + TITLE_COL_WIDTH
        same_line = [w for w in words
                     if abs(w["top"] - n["top"]) < 5          # same row
                     and n["x1"] < w["x0"] < right_edge]      # to the right, in column
        title = " ".join(w["text"] for w in sorted(same_line, key=lambda w: w["x0"]))
        index[n["text"]] = title.strip()
    return index


def normalize(title):
    """Loosen a title for comparison: upper-case, collapse whitespace."""
    return " ".join(title.upper().split())


def cross_check(block_rows, index):
    """Compare title-block sheets against the index.

    block_rows: list of (page_number, sheet_number, sheet_title)
    index:      {sheet_number: title}

    Returns (missing, extra, mismatches, duplicates).
    """
    # Map each sheet number found in the set to the page(s) it appears on.
    block = {}          # number -> (page, title)
    duplicates = {}     # number -> [pages]  (same sheet number on >1 page)
    for page_no, number, title in block_rows:
        if not number:
            continue
        if number in block:
            duplicates.setdefault(number, [block[number][0]]).append(page_no)
        else:
            block[number] = (page_no, title)

    block_nums = set(block)
    index_nums = set(index)

    missing = sorted(index_nums - block_nums)
    extra = sorted(block_nums - index_nums)

    mismatches = []
    for number in sorted(block_nums & index_nums):
        page_no, block_title = block[number]
        index_title = index[number]
        if normalize(block_title) != normalize(index_title):
            mismatches.append((number, page_no, index_title, block_title))

    return missing, extra, mismatches, duplicates


def print_report(index, block_rows, missing, extra, mismatches, duplicates):
    found = sum(1 for _, num, _ in block_rows if num)
    unreadable = [pg for pg, num, _ in block_rows if not num]
    print("=" * 70)
    print("SHEET INDEX CROSS-CHECK")
    print("=" * 70)
    print(f"Index (page {INDEX_PAGE}) lists {len(index)} sheets.")
    print(f"Title blocks found {found} sheets across {len(block_rows)} pages.")
    if unreadable:
        # A page with no readable sheet number can't be matched, so it will
        # look like a "missing" index entry below. Surface it here so the two
        # are easy to connect (the cover sheet is the usual culprit — its
        # title block is drawn as graphics, not selectable text).
        print(f"NOTE: no sheet number could be read on page(s) {unreadable} "
              f"— likely the cover. Any 'MISSING' entry below may just be one of these.")
    print()

    print(f"[A] MISSING — in the index but not found in the set ({len(missing)}):")
    if missing:
        for number in missing:
            print(f"      {number:<10} index title: {index[number]!r}")
    else:
        print("      none — every indexed sheet is present.")
    print()

    print(f"[B] EXTRA — a page exists but the sheet isn't in the index ({len(extra)}):")
    if extra:
        block = {num: (pg, t) for pg, num, t in block_rows if num}
        for number in extra:
            pg, t = block[number]
            print(f"      {number:<10} page {pg}: {t!r}")
    else:
        print("      none — every sheet in the set is listed in the index.")
    print()

    print(f"[C] TITLE MISMATCH — sheet present, but titles differ ({len(mismatches)}):")
    if mismatches:
        for number, page_no, index_title, block_title in mismatches:
            print(f"      {number}  (page {page_no})")
            print(f"          index: {index_title!r}")
            print(f"          sheet: {block_title!r}")
    else:
        print("      none — all titles agree.")
    print()

    if duplicates:
        print(f"[!] DUPLICATE sheet numbers on multiple pages ({len(duplicates)}):")
        for number, pages in duplicates.items():
            print(f"      {number}: pages {pages}")
        print()

    clean = not (missing or extra or mismatches or duplicates)
    print("RESULT:", "PASS — set matches its index." if clean
          else "DISCREPANCIES FOUND (see above).")


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "bidset.pdf"
    with pdfplumber.open(pdf_path) as pdf:
        index = parse_sheet_index(pdf.pages[INDEX_PAGE - 1])
        block_rows = [
            (i, *extract_title_block(page))
            for i, page in enumerate(pdf.pages, start=1)
        ]

    missing, extra, mismatches, duplicates = cross_check(block_rows, index)
    print_report(index, block_rows, missing, extra, mismatches, duplicates)


if __name__ == "__main__":
    main()
