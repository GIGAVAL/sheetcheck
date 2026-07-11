"""
sheet_index.py — SheetCheck

Reads an architectural drawing-set PDF and, for every page, prints the
sheet number and sheet title from the title block:

    page number | sheet number | sheet title

The actual extraction lives in extract.py (which caches results to disk,
so only the first run is slow). This module is just the table view.

Usage:
    python sheet_index.py bidset.pdf [--json]
"""

import json
import sys

from rich import box
from rich.console import Console
from rich.table import Table

from extract import extract_sheets, extract_title_block  # noqa: F401 (re-exported)

console = Console(highlight=False)


def build_index(pdf_path):
    """Return a list of (page_number, sheet_number, sheet_title)."""
    return [(s["page"], s["number"], s["title"]) for s in extract_sheets(pdf_path)]


def print_table(rows):
    table = Table(box=box.SIMPLE_HEAD, pad_edge=False)
    table.add_column("PAGE", justify="right")
    table.add_column("SHEET", style="bold")
    table.add_column("SHEET TITLE")
    for page_no, number, title in rows:
        table.add_row(str(page_no),
                      number or "[dim](none)[/]",
                      title or "[dim](none)[/]")
    console.print(table)


def run(pdf_path, as_json=False):
    rows = build_index(pdf_path)
    if as_json:
        print(json.dumps([{"page": pg, "number": num, "title": t}
                          for pg, num, t in rows], indent=2))
        return rows
    console.print("=" * 70)
    console.print("[bold]SHEET INDEX[/]")
    console.print("=" * 70)
    print_table(rows)
    found = sum(1 for _, num, _ in rows if num)
    console.print(f"{len(rows)} pages scanned — sheet number found on {found}.")
    return rows


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    run(args[0] if args else "bidset.pdf", as_json="--json" in sys.argv)


if __name__ == "__main__":
    main()
