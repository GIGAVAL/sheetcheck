# SheetCheck

### ▶︎ [Try the live demo — no install, runs in your browser](https://gigaval.github.io/sheetcheck/)

The real checks, running on real extraction output from both bid sets, with an
"inject a defect" mode so you can watch them catch a dropped sheet, a mis-titled
drawing, or a page bound out of order. It's one self-contained HTML file
([`docs/index.html`](docs/index.html)) — no download, no server, no Python.

---

QA/QC for architectural drawing-set PDFs. SheetCheck reads a bid set, pulls the
**sheet number and title out of every title block**, and checks the set against
its own **sheet index**, catching dropped sheets, unindexed sheets, mis-ordered
sheets, and title mismatches that are otherwise found by hand, sheet by sheet.

It runs on real, messy PDFs from **different architecture firms**, whose title
blocks are laid out completely differently, by detecting the template and
adapting.

## Why I built this

I've spent 14 years at large AEC firms in New York. QA/QC on a GMP set still means architects and engineers going page by page through hundreds of sheets of consultant documents, marking up Bluebeam by hand with notes and symbols. SheetCheck automates the text-verifiable slice of that work. I built it in a week, my first repo, to close my own tooling gap and to prove the workflow I want to bring to firms: a domain expert directing AI coding tools to ship something real. The checks are modeled on the drawing and coordination checklists large firms actually use.

---

## What it found on two real public bid sets

Two different projects, two different architects, two different title-block
templates. SheetCheck auto-detects which is which and runs the same checks on
both:

| Set | Firm | Title block | Sheets | Result |
|---|---|---|---|---|
| UCCS Cybersecurity & Space ISAC | **SmithGroup** | horizontal titles, 2-column index | 133 | ✅ **PASS**: every sheet matches the index |
| Holabird Academy PK-8 (Baltimore) | **Grimm & Parker** | titles rotated 90°, 3-column index | 96 | ⚠️ **partial set**: 199 of 294 indexed sheets absent + 1 unindexed sheet |

**On the SmithGroup set** (`RESULT: PASS`):
- All 133 sheets are present, correctly numbered, and their titles match the index.
- The **cover sheet** has no selectable sheet number (it's drawn as graphics), so
  SheetCheck *infers* it (`page 1 → G0.0 "PROJECT COVER SHEET"`) instead of raising
  a false alarm.
- It faithfully reproduces a **real drafter typo**: sheet `T0.0.2`'s title reads
  `TECHNOLOGY INFRASTRUCTURE LEGENDS AND LEGENDS NOTES` (should be "GENERAL"). The
  tool reports what's actually on the sheet, it neither "corrects" nor garbles it,
  so a reviewer sees the error. (There's a regression test for exactly this string.)

**On the Grimm & Parker set** (`RESULT: DISCREPANCIES FOUND`), and these are the
*right* discrepancies to find:
- This PDF is the **Architectural & Structural volume** of a larger project. Its
  index lists all **294** sheets across every discipline (civil, MEP, landscape,
  photovoltaics…), but only **96** are in this file. SheetCheck reports the 199
  absent sheets, i.e. it correctly detects a **partial set**.
- It finds **1 sheet in the set that the index never lists**: `A-4.2a "BUILDING
  SECTIONS"` (page 34), an inserted sheet nobody added to the index.
- Its titles are set **rotated 90°**; SheetCheck reads them (e.g. `A-1.1 → "PARTIAL
  FIRST FLOOR PLAN - AREA A"`). Two of 96 titles are imperfect, see
  [Known limitations](#known-limitations); they're reported honestly, not hidden.

---

## Try it yourself

```bash
git clone https://github.com/GIGAVAL/sheetcheck && cd sheetcheck
pip install -r requirements.txt
python demo.py
```

`demo.py` downloads both public bid sets (~100 MB total, into `./data/`) and runs
every check on both, printing the QA reports. That's the whole setup.

> First run: the downloads plus title-block extraction take a few minutes (it prints
> progress as it reads each set). Results are cached to disk next to each PDF, so
> **every later run is ~1 second**.

Run a single check on a single set:

```bash
python cross_check.py data/cybersecurity_bidset.pdf     # set vs. its index
python sheet_index.py data/academy_bidset.pdf           # page / number / title table
python sequence_check.py data/cybersecurity_bidset.pdf  # order + numbering gaps
```

---

## The checks

- **`sheet_index.py`**, the raw extraction: a table of *page → sheet number →
  sheet title* for every page. This is the foundation the others build on.
- **`cross_check.py`**: compares the set against the sheet index on page 2 and
  reports **MISSING** (indexed but absent), **EXTRA** (present but unindexed),
  **TITLE MISMATCH**, and duplicate numbers.
- **`sequence_check.py`**: checks that pages are **bound in index order** and
  flags **numbering gaps** within a discipline (advisory: it notes whether the
  index also skips the number, i.e. whether the gap is intentional).

---

## How it works

- **[pdfplumber](https://github.com/jsvine/pdfplumber)** extracts text with position,
  size, and orientation. (The sets are vector PDFs: no OCR needed. SheetCheck
  verifies text is extractable rather than assuming it.)
- **Font size, not pixel coordinates**, locates the important text. The sheet number
  is the biggest token in the bottom-right corner *that contains a digit*, which
  cleanly beats the same-size `CD` phase code sitting next to it.
- **Template profiles** (`profiles.py`) hold the firm-specific bits: horizontal vs.
  90°-rotated titles, 2- vs. 3-column indexes, sheet-number patterns. The firm is
  **auto-detected** from the architect's name stamped on the sheets. Adding a new
  firm is one `Profile` entry.
- **Caching** (`extract.py`) keys on the PDF's size + mtime, so the slow extraction
  happens once.

---

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

**23 tests, ~0.2 s.** They run against tiny PDFs generated on the fly with reportlab
(no 40 MB downloads), and cover both templates end-to-end: number-vs-`CD`
disambiguation, horizontal and rotated title reading, 2- and 3-column index parsing,
profile detection, and every check's logic. Including:

- `test_reproduces_real_legends_typo`: reproduces the real `LEGENDS AND LEGENDS
  NOTES` defect, proving the extractor reports real content verbatim.
- `test_index_number_pattern_rejects_consultant_name`: guards a real false positive
  (the consultant name "NV5" once parsed as a sheet number).

---

## Known limitations

Reported honestly rather than hidden:

- **Two of the Grimm & Parker titles are imperfect.** On one enlarged-plan sheet
  (`A-5.5`) the rotated-title reader picks up rotated *dimension strings* that sit in
  the title column; on one structural sheet the index's own title is clipped at the
  column edge. 94 of 96 titles read cleanly.
- **Profiles are per-firm.** Two templates are supported today; a third firm needs a
  new `Profile` (and, if its title block is exotic, a new title reader). The
  architecture is built for this: the firm-specific logic is isolated in one file.
- The sheet index is assumed to be on page 2 (configurable per profile).

---

## Design notes

A few decisions that shaped the code, and why:

- **Font size over coordinates (or OCR).** Title blocks differ by firm, but
  typography is stable *within* a firm: the sheet number is the biggest token in
  the corner, the title is the next size down. Keying on size instead of hard-coded
  pixels is what let the same extractor survive a 96-page set from a different
  architect. The load-bearing insight, *the sheet number is the biggest corner
  token **with a digit***, is what separates it from the same-size `CD` phase code.
- **Firm-specific logic lives in one file.** `profiles.py` isolates every difference
  (title orientation, index columns, number pattern, detection marker). Supporting a
  new architect is a data change, one `Profile`, not a code change scattered across
  the checks. The firm is detected from the architect's name stamped on the sheets,
  so the right profile is chosen automatically.
- **Extraction and checks are separate, and extraction is cached.** The slow,
  I/O-heavy PDF parsing happens once and is memoized to disk; the checks are pure
  functions over plain lists/dicts. That split is why the checks are trivially
  unit-testable (no PDFs) and why the second run is instant.
- **Report, don't "correct."** A QA tool's value is surfacing what's actually on the
  sheet. So the extractor reproduces the real `LEGENDS AND LEGENDS NOTES` typo
  verbatim rather than auto-fixing it, and the checks distinguish real findings
  (a partial set, an unindexed sheet) from tool blind spots (the graphics-only cover,
  which is inferred, not flagged).

### What I'd build next

- **A third firm, and a calibration harness.** Adding profiles by hand-measuring a
  title block doesn't scale. The next step is a small tool that samples a set and
  proposes a profile (title size/orientation, index columns) for review.
- **Machine-readable output + CI gating.** Emit JSON/CSV and exit non-zero on
  discrepancies, so a set can be checked automatically on every issue in a pipeline.
- **Confidence scores.** Flag low-confidence extractions (like the two rotated
  academy titles) for human review instead of silently reporting them.
- **Cross-check beyond the index.** Compare sheet references, revision clouds, and
  issue dates against the project manual, the next tier of real QA/QC.

## Project layout

```
extract.py          shared title-block extraction + disk cache
profiles.py         per-firm templates + architect auto-detection
sheet_index.py      page → number → title table
cross_check.py      set vs. sheet index
sequence_check.py   page order + numbering gaps
demo.py             download both sets, run everything
tests/              pytest suite + fixture generator
```
