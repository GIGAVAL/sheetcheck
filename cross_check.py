"""
cross_check.py — SheetCheck QA/QC check

Cross-checks the drawing set against its own Sheet Index (the master list
of sheets, usually on page 2). Three things can go wrong in a real set:

  * MISSING  — the index lists a sheet, but no page in the PDF has it.
  * EXTRA    — a page exists whose sheet number isn't in the index.
  * MISMATCH — the sheet exists in both, but its title differs.

The title-block layout and index columns vary by architecture firm, so the
firm-specific bits come from a Profile (see profiles.py), detected from the
PDF automatically.

Usage:
    python cross_check.py <set.pdf>
"""

import sys

import pdfplumber

from extract import extract_sheets
from profiles import detect_profile


def parse_sheet_index(page, profile):
    """Return the sheet index as an ordered list of (number, title).

    Works for any number of columns: sheet numbers are found by the profile's
    pattern, then each title is the text to the right of its number up to the
    next number on the same row (which is the start of the next column).
    """
    words = [w for w in page.extract_words(extra_attrs=["size"])
             if w["size"] < profile.index_text_max_size]
    numbers = [w for w in words if profile.index_number_re.match(w["text"])]
    if not numbers:
        return []

    # Cluster number x-positions into columns so we can read down each column.
    xs = sorted({round(n["x0"]) for n in numbers})
    clusters = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= 40:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    def column_of(n):
        for i, cl in enumerate(clusters):
            if cl[0] - 1 <= round(n["x0"]) <= cl[-1] + 1:
                return i
        return len(clusters)

    numbers.sort(key=lambda n: (column_of(n), n["top"]))   # reading order

    entries = []
    for n in numbers:
        later = [m["x0"] for m in numbers
                 if abs(m["top"] - n["top"]) < 5 and m["x0"] > n["x1"]]
        right_bound = min(later) if later else n["x0"] + profile.index_title_fallback_width
        title_words = [w for w in words
                       if abs(w["top"] - n["top"]) < 5
                       and n["x1"] < w["x0"] < right_bound - 1]
        title = " ".join(w["text"] for w in sorted(title_words, key=lambda w: w["x0"]))
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
    """Infer the cover/title match for the one unreadable page, if unambiguous.

    Some firms draw the cover's sheet number as graphics (no selectable text),
    so it reads blank. When exactly one page is unreadable and exactly one
    unmatched index entry looks like a cover/title sheet, pair them.
    Returns (updated_block_rows, inferred, remaining_missing).
    """
    unreadable = [pg for pg, num, _ in block_rows if not num]
    markers = ("COVER", "TITLE SHEET")
    candidates = [m for m in missing if any(k in index[m].upper() for k in markers)]

    if len(unreadable) == 1 and len(candidates) == 1:
        page, number = unreadable[0], candidates[0]
        title = index[number]
        block_rows = [
            (pg, number, title) if pg == page else (pg, num, t)
            for pg, num, t in block_rows
        ]
        return block_rows, [(page, number, title)], [m for m in missing if m != number]

    return block_rows, [], missing


def print_report(profile, index, block_rows, missing, extra, mismatches, duplicates, inferred):
    found = sum(1 for _, num, _ in block_rows if num)
    still_unreadable = [pg for pg, num, _ in block_rows if not num]

    print("=" * 70)
    print(f"SHEET INDEX CROSS-CHECK   [{profile.name} template]")
    print("=" * 70)
    print(f"Index (page {profile.index_page}) lists {len(index)} sheets.")
    print(f"Title blocks matched {found} sheets across {len(block_rows)} pages.")
    print()

    if inferred:
        print(f"[i] INFERRED — page had no readable sheet number, matched by position ({len(inferred)}):")
        for page, number, title in inferred:
            print(f"      page {page} -> {number:<8} {title!r}  (cover/title sheet, inferred)")
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
        profile = detect_profile(pdf)
        index = dict(parse_sheet_index(pdf.pages[profile.index_page - 1], profile))

    missing, extra, mismatches, duplicates = cross_check(block_rows, index)
    block_rows, inferred, missing = reconcile_cover(block_rows, index, missing)
    print_report(profile, index, block_rows, missing, extra, mismatches, duplicates, inferred)


def main():
    run(sys.argv[1] if len(sys.argv) > 1 else "bidset.pdf")


if __name__ == "__main__":
    main()
