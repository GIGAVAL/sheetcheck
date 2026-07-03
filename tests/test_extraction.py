"""
Extraction tests — run against tiny synthetic PDFs (see fixtures.py), so the
whole file runs in well under a second with no 40 MB downloads.

These exercise the real extraction code: sheet-number/ title reading for both
templates, profile auto-detection, and index parsing for two and three columns.
"""

import pdfplumber
import pytest

from fixtures import smithgroup_sheet, grimm_parker_sheet, index_page
from profiles import SMITHGROUP, GRIMM_PARKER, detect_profile
from extract import extract_title_block, extract_sheets
from cross_check import parse_sheet_index


# --- sheet number ----------------------------------------------------------

def test_sheet_number_prefers_digit_over_cd(tmp_path):
    """The big 'CD' phase code sits next to the number at nearly the same size;
    the number is the only large token with a digit, so it must win."""
    p = tmp_path / "sg.pdf"
    smithgroup_sheet(str(p), sheet_number="A8.1.2", title_words=("INTERIOR", "ELEVATIONS"))
    with pdfplumber.open(str(p)) as pdf:
        number, _ = extract_title_block(pdf.pages[0], SMITHGROUP)
    assert number == "A8.1.2"


# --- horizontal title (SmithGroup) -----------------------------------------

def test_horizontal_title_read(tmp_path):
    p = tmp_path / "sg.pdf"
    smithgroup_sheet(str(p), title_words=("STRUCTURAL", "PLAN", "AND", "GENERAL", "NOTES"))
    with pdfplumber.open(str(p)) as pdf:
        _, title = extract_title_block(pdf.pages[0], SMITHGROUP)
    assert title == "STRUCTURAL PLAN AND GENERAL NOTES"


def test_double_struck_title_is_collapsed(tmp_path):
    """A title drawn twice ('fake bold') yields duplicated words; consecutive
    duplicates should collapse (this is real: page 18 of the cybersecurity set)."""
    p = tmp_path / "sg.pdf"
    smithgroup_sheet(str(p), title_words=("ROOF", "ROOF", "PLAN", "PLAN", "-", "-", "OVERALL", "OVERALL"))
    with pdfplumber.open(str(p)) as pdf:
        _, title = extract_title_block(pdf.pages[0], SMITHGROUP)
    assert title == "ROOF PLAN - OVERALL"


def test_reproduces_real_legends_typo(tmp_path):
    """Regression for a real defect SheetCheck caught in the cybersecurity set:
    sheet T0.0.2's title reads 'LEGENDS AND LEGENDS NOTES' (a drafter typo for
    'GENERAL'). The extractor must reproduce it VERBATIM — the two 'LEGENDS'
    are not adjacent, so dedup must not touch them, and the tool must not
    silently 'correct' the document. Faithful extraction is what lets the
    cross-check surface real errors."""
    p = tmp_path / "legends.pdf"
    smithgroup_sheet(str(p), sheet_number="T0.0.2",
                     title_words=("TECHNOLOGY", "INFRASTRUCTURE", "LEGENDS", "AND", "LEGENDS", "NOTES"))
    with pdfplumber.open(str(p)) as pdf:
        _, title = extract_title_block(pdf.pages[0], SMITHGROUP)
    assert title == "TECHNOLOGY INFRASTRUCTURE LEGENDS AND LEGENDS NOTES"


# --- rotated title (Grimm & Parker) ----------------------------------------

def test_rotated_title_read(tmp_path):
    p = tmp_path / "gp.pdf"
    grimm_parker_sheet(str(p), sheet_number="A-1.1",
                       title="PARTIAL FIRST FLOOR PLAN - AREA A")
    with pdfplumber.open(str(p)) as pdf:
        number, title = extract_title_block(pdf.pages[0], GRIMM_PARKER)
    assert number == "A-1.1"
    assert title == "PARTIAL FIRST FLOOR PLAN - AREA A"


# --- profile detection -----------------------------------------------------

def test_detects_smithgroup(tmp_path):
    p = tmp_path / "sg.pdf"
    smithgroup_sheet(str(p))
    with pdfplumber.open(str(p)) as pdf:
        assert detect_profile(pdf).name == "SmithGroup"


def test_detects_grimm_parker(tmp_path):
    p = tmp_path / "gp.pdf"
    grimm_parker_sheet(str(p))
    with pdfplumber.open(str(p)) as pdf:
        assert detect_profile(pdf).name == "Grimm & Parker"


# --- index parsing ---------------------------------------------------------

def test_index_two_columns(tmp_path):
    p = tmp_path / "idx2.pdf"
    entries = [("G1.1", "GENERAL"), ("A2.1.1", "FLOOR PLAN"),
               ("M0.2", "MECH"), ("E0.1", "ELEC")]
    index_page(str(p), entries, columns=[1010, 1600], architect="SMITHGROUP.COM")
    with pdfplumber.open(str(p)) as pdf:
        got = dict(parse_sheet_index(pdf.pages[0], SMITHGROUP))
    assert got == {"G1.1": "GENERAL", "A2.1.1": "FLOOR PLAN", "M0.2": "MECH", "E0.1": "ELEC"}


def test_index_three_columns(tmp_path):
    p = tmp_path / "idx3.pdf"
    entries = [("TS-1H", "TITLE SHEET"), ("A-1.1", "PLAN"), ("S-3.2H", "FRAMING"),
               ("K-1.1", "KITCHEN"), ("W-2.0", "PV"), ("C-1.00H", "CIVIL")]
    index_page(str(p), entries, columns=[1433, 1900, 2400], architect="GRIMM AND PARKER")
    with pdfplumber.open(str(p)) as pdf:
        got = dict(parse_sheet_index(pdf.pages[0], GRIMM_PARKER))
    assert got == dict(entries)


def test_index_number_pattern_rejects_consultant_name(tmp_path):
    """A consultant name like 'NV5' matched the old pattern and became a bogus
    index entry; SmithGroup numbers must contain a dot, so it's now rejected."""
    p = tmp_path / "idx.pdf"
    entries = [("G1.1", "GENERAL"), ("NV5", "SOME CONSULTANT NOTE")]
    index_page(str(p), entries, columns=[1010], architect="SMITHGROUP.COM")
    with pdfplumber.open(str(p)) as pdf:
        got = dict(parse_sheet_index(pdf.pages[0], SMITHGROUP))
    assert "G1.1" in got
    assert "NV5" not in got


# --- caching ---------------------------------------------------------------

def test_extract_sheets_caches(tmp_path):
    p = tmp_path / "sg.pdf"
    smithgroup_sheet(str(p), sheet_number="A1.1", title_words=("PLAN",))
    first = extract_sheets(str(p))
    assert (tmp_path / "sg.pdf.sheetcache.json").exists()
    second = extract_sheets(str(p))          # served from cache
    assert first == second
    assert first[0]["number"] == "A1.1"
