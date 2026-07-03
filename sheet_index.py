"""
sheet_index.py — SheetCheck

Reads an architectural drawing-set PDF and, for every page, prints the
sheet number and sheet title from the title block:

    page number | sheet number | sheet title

The actual extraction lives in extract.py (which caches results to disk,
so only the first run is slow). This module is just the table view.

Usage:
    python sheet_index.py bidset.pdf
"""

import sys

from extract import extract_sheets, extract_title_block  # noqa: F401 (re-exported)


def build_index(pdf_path):
    """Return a list of (page_number, sheet_number, sheet_title)."""
    return [(s["page"], s["number"], s["title"]) for s in extract_sheets(pdf_path)]


def print_table(rows):
    """Print an aligned text table with no external dependencies."""
    headers = ("PAGE", "SHEET", "SHEET TITLE")
    num_w = max(len(headers[1]), *(len(r[1]) for r in rows)) if rows else len(headers[1])
    pg_w = max(len(headers[0]), len(str(len(rows))))

    print(f"{headers[0]:>{pg_w}}  {headers[1]:<{num_w}}  {headers[2]}")
    print(f"{'-'*pg_w}  {'-'*num_w}  {'-'*len(headers[2])}")
    for page_no, number, title in rows:
        print(f"{page_no:>{pg_w}}  {(number or '(none)'):<{num_w}}  {title or '(none)'}")


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "bidset.pdf"
    rows = build_index(pdf_path)
    print_table(rows)

    found = sum(1 for _, num, _ in rows if num)
    print()
    print(f"{len(rows)} pages scanned — sheet number found on {found}.")


if __name__ == "__main__":
    main()
