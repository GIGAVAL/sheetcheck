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
    python sequence_check.py <set.pdf> [--json]

Exits non-zero on real problems (inversions, or gaps the index does not
share), so a set can gate a CI pipeline. Advisory-only gaps still pass.
"""

import json
import re
import sys

import pdfplumber
from rich.console import Console

from extract import extract_sheets
from profiles import detect_profile
from cross_check import parse_sheet_index, reconcile_cover

console = Console(highlight=False)


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


def analyze_rows(profile_name, block_rows, index_entries):
    """Run both sequence checks over already-extracted rows.

    Pure function over plain data (no PDF I/O), returns a JSON-serializable
    findings dict — the single source both the printed report and --json use.
    """
    index_numbers = {n for n, _ in index_entries}
    present_numbers = [num for _, num, _ in block_rows if num]

    inversions = order_inversions(block_rows, index_entries)
    gaps = numbering_gaps(present_numbers, index_numbers)

    result = {
        "check": "sequence_check",
        "profile": profile_name,
        "inversions": [
            {"page_a": pg_a, "number_a": num_a, "page_b": pg_b, "number_b": num_b}
            for pg_a, num_a, pg_b, num_b in inversions
        ],
        "gaps": [
            {"missing_number": num, "present_run": present, "in_index": in_index}
            for num, present, in_index in gaps
        ],
    }
    result["clean"] = not (result["inversions"]
                           or any(g["in_index"] for g in result["gaps"]))
    return result


def analyze(pdf_path):
    """Extract and sequence-check one PDF; returns the findings dict."""
    profile, block_rows, index_entries = _load(pdf_path)
    return analyze_rows(profile.name, block_rows, index_entries)


def print_report(res):
    console.print("=" * 70)
    console.print(f"[bold]SEQUENCE CHECK[/]   [dim]\\[{res['profile']} template][/]")
    console.print("=" * 70)

    console.print(f"[red]\\[A] PAGE ORDER[/] — PDF order vs index order ({len(res['inversions'])} break(s)):")
    if res["inversions"]:
        for inv in res["inversions"]:
            console.print(f"      page {inv['page_a']} ({inv['number_a']}) is followed by "
                          f"page {inv['page_b']} ({inv['number_b']}), "
                          f"but the index lists {inv['number_b']} before {inv['number_a']}.")
    else:
        console.print("      [green]none — pages follow the index order.[/]")
    console.print()

    console.print(f"[blue]\\[B] NUMBERING GAPS[/] — advisory ({len(res['gaps'])} gap(s)):")
    if res["gaps"]:
        for g in res["gaps"]:
            if g["in_index"]:
                console.print(f"      {g['missing_number']:<10} missing from run {g['present_run']}  "
                              f"— [red]ALSO in index (real omission)[/]")
            else:
                console.print(f"      [dim]{g['missing_number']:<10} missing from run {g['present_run']}  "
                              f"— also skipped by index (likely intentional)[/]")
    else:
        console.print("      [green]none — no skipped numbers within any run.[/]")
    console.print()

    console.print("RESULT:", "[bold red]DISCREPANCIES FOUND (see above).[/]" if not res["clean"]
                  else "[bold green]PASS — order is consistent (any gaps are also skipped by the index).[/]")


def run(pdf_path, as_json=False):
    result = analyze(pdf_path)
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)
    return result


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    result = run(args[0] if args else "bidset.pdf", as_json="--json" in sys.argv)
    sys.exit(0 if result["clean"] else 1)


if __name__ == "__main__":
    main()
