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
    python cross_check.py <set.pdf> [--json]

Exits non-zero when discrepancies are found, so a set can gate a CI pipeline.
"""

import json
import sys

import pdfplumber
from rich.console import Console
from rich.markup import escape

from extract import extract_sheets
from profiles import detect_profile

console = Console(highlight=False)


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


def analyze_rows(profile_name, index_page, index, block_rows):
    """Run every cross-check over already-extracted rows.

    Pure function over plain data (no PDF I/O), returns a JSON-serializable
    findings dict — the single source both the printed report and --json use.
    """
    missing, extra, mismatches, duplicates = cross_check(block_rows, index)
    block_rows, inferred, missing = reconcile_cover(block_rows, index, missing)

    block = {num: (pg, t) for pg, num, t in block_rows if num}
    unreadable = [pg for pg, num, _ in block_rows if not num]

    result = {
        "check": "cross_check",
        "profile": profile_name,
        "index_page": index_page,
        "index_count": len(index),
        "pages": len(block_rows),
        "matched": len(block),
        "inferred": [{"page": pg, "number": num, "title": t}
                     for pg, num, t in inferred],
        "missing": [{"number": num, "index_title": index[num]} for num in missing],
        "extra": [{"number": num, "page": block[num][0], "title": block[num][1]}
                  for num in extra],
        "title_mismatches": [
            {"number": num, "page": pg, "index_title": it, "sheet_title": bt}
            for num, pg, it, bt in mismatches
        ],
        "duplicates": [{"number": num, "pages": pages}
                       for num, pages in duplicates.items()],
        "unreadable_pages": unreadable,
    }
    result["clean"] = not (result["missing"] or result["extra"]
                           or result["title_mismatches"] or result["duplicates"]
                           or result["unreadable_pages"])
    return result


def analyze(pdf_path):
    """Extract, parse the index, and cross-check one PDF; returns the findings dict."""
    block_rows = [(s["page"], s["number"], s["title"]) for s in extract_sheets(pdf_path)]
    with pdfplumber.open(pdf_path) as pdf:
        profile = detect_profile(pdf)
        index = dict(parse_sheet_index(pdf.pages[profile.index_page - 1], profile))
    return analyze_rows(profile.name, profile.index_page, index, block_rows)


def print_report(res):
    console.print("=" * 70)
    console.print(f"[bold]SHEET INDEX CROSS-CHECK[/]   [dim]\\[{escape(res['profile'])} template][/]")
    console.print("=" * 70)
    console.print(f"Index (page {res['index_page']}) lists {res['index_count']} sheets.")
    console.print(f"Title blocks matched {res['matched']} sheets across {res['pages']} pages.")
    console.print()

    if res["inferred"]:
        console.print(f"[blue]\\[i] INFERRED[/] — page had no readable sheet number, matched by position ({len(res['inferred'])}):")
        for inf in res["inferred"]:
            console.print(f"      page {inf['page']} -> {inf['number']:<8} {escape(repr(inf['title']))}  [dim](cover/title sheet, inferred)[/]")
        console.print()

    console.print(f"[red]\\[A] MISSING[/] — in the index but not found in the set ({len(res['missing'])}):")
    if res["missing"]:
        for m in res["missing"]:
            console.print(f"      {m['number']:<10} [dim]index title:[/] {escape(repr(m['index_title']))}")
    else:
        console.print("      [green]none — every indexed sheet is present.[/]")
    console.print()

    console.print(f"[red]\\[B] EXTRA[/] — a page exists but the sheet isn't in the index ({len(res['extra'])}):")
    if res["extra"]:
        for e in res["extra"]:
            console.print(f"      {e['number']:<10} page {e['page']}: {escape(repr(e['title']))}")
    else:
        console.print("      [green]none — every sheet in the set is listed in the index.[/]")
    console.print()

    console.print(f"[yellow]\\[C] TITLE MISMATCH[/] — sheet present, but titles differ ({len(res['title_mismatches'])}):")
    if res["title_mismatches"]:
        for m in res["title_mismatches"]:
            console.print(f"      {m['number']}  (page {m['page']})")
            console.print(f"          [dim]index:[/] {escape(repr(m['index_title']))}")
            console.print(f"          [yellow]sheet:[/] {escape(repr(m['sheet_title']))}")
    else:
        console.print("      [green]none — all titles agree.[/]")
    console.print()

    if res["duplicates"]:
        console.print(f"[red]\\[!] DUPLICATE[/] sheet numbers on multiple pages ({len(res['duplicates'])}):")
        for d in res["duplicates"]:
            console.print(f"      {d['number']}: pages {d['pages']}")
        console.print()

    if res["unreadable_pages"]:
        console.print(f"[yellow]\\[!] UNREADABLE[/] — no sheet number could be read on page(s) {res['unreadable_pages']}.")
        console.print()

    console.print("RESULT:", "[bold green]PASS — set matches its index.[/]" if res["clean"]
                  else "[bold red]DISCREPANCIES FOUND (see above).[/]")


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
