"""
sequence_check.py — SheetCheck QA/QC check

Two order-related checks the index cross-check doesn't cover:

  [A] PAGE ORDER — do the PDF pages appear in the same order the sheet
      index lists them? Sheets bound out of order are a common assembly
      mistake even when no sheet is missing.

  [B] NUMBERING GAPS (advisory) — within a run of sheets that differ only
      in a trailing number (A2.1.1, A2.1.2, ...), is any value skipped?
      Some gaps are intentional, so this is advisory. For each gap we note
      whether the missing number is also absent from the index (both skip
      it -> probably intentional) or present in the index (a real omission).

Usage:
    python sequence_check.py <set.pdf>
"""

import re
import sys

import pdfplumber

from extract import extract_sheets
from profiles import detect_profile
from cross_check import parse_sheet_index, reconcile_cover


def _load(pdf_path):
    """Return (profile, block_rows in page order, ordered index entries)."""
    block_rows = [(s["page"], s["number"], s["title"]) for s in extract_sheets(pdf_path)]
    with pdfplumber.open(pdf_path) as pdf:
        profile = detect_profile(pdf)
        index_entries = parse_sheet_index(pdf.pages[profile.index_page - 1], profile)
    # Fill the cover so page 1 participates in the order check.
    index = dict(index_entries)
    missing = [n for n in index if n not in {b[1] for b in block_rows}]
    block_rows, _, _ = reconcile_cover(block_rows, index, missing)
    return profile, block_rows, index_entries


# --- [A] page order --------------------------------------------------------

def order_inversions(block_rows, index_entries):
    """Return adjacent pages whose sheets are in reversed index order."""
    index_pos = {number: i for i, (number, _) in enumerate(index_entries)}
    seq = [(pg, num) for pg, num, _ in sorted(block_rows) if num in index_pos]

    inversions = []
    for (pg_a, num_a), (pg_b, num_b) in zip(seq, seq[1:]):
        if index_pos[num_b] < index_pos[num_a]:
            inversions.append((pg_a, num_a, pg_b, num_b))
    return inversions


# --- [B] numbering gaps ----------------------------------------------------

def _split_trailing_number(number):
    """'A2.1.1' -> ('A2.1.', 1, ''); returns None if no digits."""
    runs = list(re.finditer(r"\d+", number))
    if not runs:
        return None
    last = runs[-1]
    return number[:last.start()], int(last.group()), number[last.end():]


def numbering_gaps(numbers, index_numbers):
    """Find skipped values within groups that share prefix+suffix.

    Returns a list of (missing_number, present_sorted, in_index_bool).
    """
    groups = {}
    for num in numbers:
        parsed = _split_trailing_number(num)
        if not parsed:
            continue
        prefix, value, suffix = parsed
        groups.setdefault((prefix, suffix), {})[value] = num

    gaps = []
    for (prefix, suffix), members in groups.items():
        values = sorted(members)
        if len(values) < 2:
            continue
        for v in range(values[0], values[-1] + 1):
            if v not in members:
                missing_number = f"{prefix}{v}{suffix}"
                gaps.append((missing_number, values, missing_number in index_numbers))
    return gaps


def print_report(profile, inversions, gaps):
    print("=" * 70)
    print(f"SEQUENCE CHECK   [{profile.name} template]")
    print("=" * 70)

    print(f"[A] PAGE ORDER — PDF order vs index order ({len(inversions)} break(s)):")
    if inversions:
        for pg_a, num_a, pg_b, num_b in inversions:
            print(f"      page {pg_a} ({num_a}) is followed by page {pg_b} ({num_b}), "
                  f"but the index lists {num_b} before {num_a}.")
    else:
        print("      none — pages follow the index order.")
    print()

    print(f"[B] NUMBERING GAPS — advisory ({len(gaps)} gap(s)):")
    if gaps:
        for missing_number, present, in_index in gaps:
            tag = "ALSO in index (real omission)" if in_index else "also skipped by index (likely intentional)"
            print(f"      {missing_number:<10} missing from run {present}  — {tag}")
    else:
        print("      none — no skipped numbers within any run.")
    print()

    real_problems = inversions or any(in_index for _, _, in_index in gaps)
    print("RESULT:", "DISCREPANCIES FOUND (see above)." if real_problems
          else "PASS — order is consistent (any gaps are also skipped by the index).")


def run(pdf_path):
    profile, block_rows, index_entries = _load(pdf_path)
    index_numbers = {n for n, _ in index_entries}
    present_numbers = [num for _, num, _ in block_rows if num]

    inversions = order_inversions(block_rows, index_entries)
    gaps = numbering_gaps(present_numbers, index_numbers)
    print_report(profile, inversions, gaps)


def main():
    run(sys.argv[1] if len(sys.argv) > 1 else "bidset.pdf")


if __name__ == "__main__":
    main()
