"""
demo.py — SheetCheck end-to-end demo

Downloads two real, public architectural bid sets (from two different
architecture firms), then runs every QA check on both and prints the reports.

    python demo.py

Zero setup beyond:  pip install -r requirements.txt

The two PDFs are ~40 MB each; they download once into ./data and are reused
on later runs. The first run also spends ~1-2 min per set extracting title
blocks (results are cached to disk, so later runs are fast).
"""

import os
import urllib.request

from rich import box
from rich.console import Console
from rich.progress import (BarColumn, DownloadColumn, Progress, TextColumn,
                           TransferSpeedColumn)
from rich.table import Table

import sheet_index
import cross_check
import sequence_check

console = Console(highlight=False)


DATA_DIR = "data"

# Two public bid sets, two different architecture firms / title-block templates.
SETS = [
    {
        "name": "UCCS Cybersecurity & Space ISAC Expansion",
        "firm": "SmithGroup",
        "filename": "cybersecurity_bidset.pdf",
        "url": "https://pdc.uccs.edu/sites/g/files/kjihxj1346/files/inline-files/"
               "2021-0525_UCCS%20BID%20SET%20-%20Drawings.pdf",
    },
    {
        "name": "Holabird Academy PK-8 (Baltimore, MD)",
        "firm": "Grimm & Parker",
        "filename": "academy_bidset.pdf",
        # Public Architectural & Structural volume (PSC 30.240.15/17).
        "url": "https://www.cambuilds.com/wp-content/uploads/2017/06/"
               "Architectural-Structural-Holabird-Bid-Set-Drawings.pdf",
    },
]


def download(url, path):
    """Download url -> path with a progress bar; skip if already present."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        console.print(f"  [dim]already downloaded ({os.path.getsize(path) // (1024*1024)} MB): {path}[/]")
        return True
    if not url:
        console.print(f"  [yellow]SKIP:[/] no URL configured for {os.path.basename(path)} "
                      f"(set ACADEMY_URL to enable).")
        return False

    with Progress(
        TextColumn("  {task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(os.path.basename(path), total=None)

        def hook(blocks, block_size, total):
            if total > 0:
                progress.update(task, total=total,
                                completed=min(blocks * block_size, total))

        urllib.request.urlretrieve(url, path, reporthook=hook)
    return True


def run_all_checks(pdf_path):
    """Run every check; returns (cross_check_result, sequence_result)."""
    print()
    sheet_index.run(pdf_path)
    print()
    cc = cross_check.run(pdf_path)
    print()
    sq = sequence_check.run(pdf_path)
    return cc, sq


def _verdict(result, issues):
    if result["clean"]:
        return "[bold green]PASS[/]"
    return f"[bold red]{issues} finding(s)[/]"


def print_summary(outcomes):
    table = Table(title="SheetCheck — run summary", box=box.SIMPLE_HEAD)
    table.add_column("Set")
    table.add_column("Template")
    table.add_column("Index cross-check")
    table.add_column("Sequence check")
    for spec, cc, sq in outcomes:
        cc_issues = (len(cc["missing"]) + len(cc["extra"]) + len(cc["title_mismatches"])
                     + len(cc["duplicates"]) + len(cc["unreadable_pages"]))
        sq_issues = len(sq["inversions"]) + sum(1 for g in sq["gaps"] if g["in_index"])
        table.add_row(spec["name"], cc["profile"],
                      _verdict(cc, cc_issues), _verdict(sq, sq_issues))
    console.print(table)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    outcomes = []
    for spec in SETS:
        path = os.path.join(DATA_DIR, spec["filename"])
        console.print("=" * 70)
        console.print(f"[bold]{spec['name']}[/]  —  {spec['firm']}")
        console.print("=" * 70)
        ok = download(spec["url"], path)
        if not ok:
            console.print("  (skipping checks for this set)\n")
            continue
        outcomes.append((spec, *run_all_checks(path)))
        print()

    if outcomes:
        print_summary(outcomes)


if __name__ == "__main__":
    main()
