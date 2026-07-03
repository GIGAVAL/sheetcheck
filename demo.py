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
import sys
import urllib.request

import sheet_index
import cross_check
import sequence_check


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
    """Download url -> path with a simple progress line; skip if present."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print(f"  already downloaded ({os.path.getsize(path) // (1024*1024)} MB): {path}")
        return True
    if not url:
        print(f"  SKIP: no URL configured for {os.path.basename(path)} "
              f"(set ACADEMY_URL to enable).")
        return False

    print(f"  downloading {url}")

    def hook(blocks, block_size, total):
        if total > 0:
            pct = min(100, blocks * block_size * 100 // total)
            sys.stdout.write(f"\r    {pct:3d}%")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, path, reporthook=hook)
    print(f"\r    done ({os.path.getsize(path) // (1024*1024)} MB)")
    return True


def run_all_checks(pdf_path):
    print()
    sheet_index.run(pdf_path)
    print()
    cross_check.run(pdf_path)
    print()
    sequence_check.run(pdf_path)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    for spec in SETS:
        path = os.path.join(DATA_DIR, spec["filename"])
        print("=" * 70)
        print(f"{spec['name']}  —  {spec['firm']}")
        print("=" * 70)
        ok = download(spec["url"], path)
        if not ok:
            print("  (skipping checks for this set)\n")
            continue
        run_all_checks(path)
        print()


if __name__ == "__main__":
    main()
