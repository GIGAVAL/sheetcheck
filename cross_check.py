"""
cross_check.py — SheetCheck QA/QC check

Cross-checks the drawing set against its own Sheet Index (the master list
of sheets printed on page 2). Three things can go wrong in a real set:

  * MISSING  — the index lists a sheet, but no page in the PDF has it.
  * EXTRA    — a page exists whose sheet number isn't in the index.
  * MISMATCH — the sheet exists in both, but its title differs.

The cover sheet is a special case: its title block is drawn as graphics,
so no sheet number can be read from it. When exactly one page is
unreadable and exactly one indexed "cover" sheet is unmatched, we infer
the match rather than reporting a false "missing".

Usage:
    python cross_check.py bidset.pdf
"""

import re
import sys

import pdfplumber

from extract import extract_sheets


# The sheet index on page 2 is a two-column list. Sheet numbers sit in two
# narrow x-bands; each title runs to the right of its number for a fixed
# column width. These bands come from measuring page 2 (see project notes).
INDEX_PAGE = 2
NUM_RE = re.compile(r"^[A-Z]{1,3}[0-9][0-9A-Z.]*$")
COL_BANDS = ((1000, 1050), (1590, 1650))
TITLE_COL_WIDTH = 545
INDEX_TEXT_MAX_SIZE = 12


def parse_sheet_index(page):
    """Return the sheet index as an ordered list of (number, title).

    Order is the index's own reading order: down column 1, then down
    column 2. Callers that want lookup can do ``dict(parse_sheet_index(...))``.
    """
    words = [w for w in page.extract_words(extra_attrs=["size"])
             if w["size"] < INDEX_TEXT_MAX_SIZE]

    def band(x0):
        for i, (lo, hi) in enumerate(COL_BANDS):
            if lo < x0 < hi:
                return i
        return None

    numbers = [w for w in words
               if NUM_RE.match(w["text"]) and "." in w["text"]
               and band(w["x0"]) is not None]
    numbers.sort(key=lambda w: (band(w["x0"]), w["top"]))   # reading order

    entries = []
    for n in numbers:
        right_edge = n["x0"] + TITLE_COL_WIDTH
        same_line = [w for w in words if abs(w["top"] - n["top"]) < 5
                     and n["x1"] < w["x0"] < right_edge]
        title = " ".join(w["text"] for w in sorted(same_line, key=lambda w: w["x0"]))
        entries.append((n["text"], title.strip()))
    return entries


def normalize(title):
    """Loosen a title for comparison: upper-case, collapse whitespace."""
    return " ".join(title.upper().split())


def cross_check(block_rows, index):
    """Compare title-block sheets against the index.

    block_rows: list of (page_number, sheet_number, sheet_title)
    index:      {sheet_number: title}

    Returns (missing, extra, mismatches, duplicates).
    """
    block = {}
    duplicates = {}
    for page_no, number, title in block_rows:
        if not number:
            continue
        if number in block:
            duplicates.setdefault(number, [block[number][0]]).append(page_no)
        else:
            block[number] = (page_no, title)

    block_nums, index_nums = set(block), set(index)
    missing = sorted(index_nums - block_nums)
    extra = sorted(block_nums - index_nums)

    mismatches = []
    for number in sorted(block_nums & index_nums):
        page_no, block_title = block[number]
        if normalize(block_title) != normalize(index[number]):
            mismatches.append((number, page_no, index[number], block_title))

    return missing, extra, mismatches, duplicates


def reconcile_cover(block_rows, index, missing):
    """Infer the cover match for the one unreadable page, if unambiguous.

    Returns (updated_block_rows, inferred, remaining_missing) where
    ``inferred`` is a list of (page, number, title).
    """
    unreadable = [pg for pg, num, _ in block_rows if not num]
    cover_missing = [m for m in missing if "COVER" in index[m].upper()]

    if len(unreadable) == 1 and len(cover_missing) == 1:
        page = unreadable[0]
        number = cover_missing[0]
        title = index[number]
        block_rows = [
            (pg, number, title) if pg == page else (pg, num, t)
            for pg, num, t in block_rows
        ]
        return block_rows, [(page, number, title)], [m for m in missing if m != number]

    return block_rows, [], missing


def print_report(index, block_rows, missing, extra, mismatches, duplicates, inferred):
    found = sum(1 for _, num, _ in block_rows if num)
    still_unreadable = [pg for pg, num, _ in block_rows if not num]

    print("=" * 70)
    print("SHEET INDEX CROSS-CHECK")
    print("=" * 70)
    print(f"Index (page {INDEX_PAGE}) lists {len(index)} sheets.")
    print(f"Title blocks matched {found} sheets across {len(block_rows)} pages.")
    print()

    if inferred:
        print(f"[i] INFERRED — page had no readable sheet number, matched by position ({len(inferred)}):")
        for page, number, title in inferred:
            print(f"      page {page} -> {number:<8} {title!r}  (cover sheet, inferred)")
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

    if still_unreadable:
        print(f"[!] UNREADABLE — no sheet number could be read on page(s) {still_unreadable}.")
        print()

    clean = not (missing or extra or mismatches or duplicates or still_unreadable)
    print("RESULT:", "PASS — set matches its index." if clean
          else "DISCREPANCIES FOUND (see above).")


def run(pdf_path):
    block_rows = [(s["page"], s["number"], s["title"]) for s in extract_sheets(pdf_path)]
    with pdfplumber.open(pdf_path) as pdf:
        index = dict(parse_sheet_index(pdf.pages[INDEX_PAGE - 1]))

    missing, extra, mismatches, duplicates = cross_check(block_rows, index)
    block_rows, inferred, missing = reconcile_cover(block_rows, index, missing)
    print_report(index, block_rows, missing, extra, mismatches, duplicates, inferred)


def main():
    run(sys.argv[1] if len(sys.argv) > 1 else "bidset.pdf")


if __name__ == "__main__":
    main()
