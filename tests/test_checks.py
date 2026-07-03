"""
Check-logic tests — pure functions over plain data (no PDFs), so these are
instant. They cover the QA logic: index cross-check, cover reconciliation,
numbering gaps, and page-order verification.
"""

from cross_check import cross_check, reconcile_cover, normalize
from sequence_check import numbering_gaps, order_inversions


# --- cross_check -----------------------------------------------------------

def test_cross_check_flags_missing_extra_and_mismatch():
    block = [
        (1, "A1.1", "FLOOR PLAN"),        # matches index
        (2, "A1.2", "ROOF PLAN"),         # title differs from index -> mismatch
        (3, "A9.9", "EXTRA DETAIL"),      # not in index -> extra
    ]
    index = {
        "A1.1": "FLOOR PLAN",
        "A1.2": "ROOF PLAN - OVERALL",    # differs
        "A2.1": "CEILING PLAN",           # no page -> missing
    }
    missing, extra, mismatches, duplicates = cross_check(block, index)
    assert missing == ["A2.1"]
    assert extra == ["A9.9"]
    assert [m[0] for m in mismatches] == ["A1.2"]
    assert duplicates == {}


def test_cross_check_ignores_whitespace_and_case():
    block = [(1, "A1.1", "floor   plan")]
    index = {"A1.1": "FLOOR PLAN"}
    _, _, mismatches, _ = cross_check(block, index)
    assert mismatches == []


def test_legends_typo_agreement_is_not_a_mismatch():
    """The real T0.0.2 typo: BOTH the sheet and the index say 'LEGENDS AND
    LEGENDS NOTES'. Because they agree, it is correctly NOT flagged as a title
    mismatch — the tool reports what the document says, typo and all. (The typo
    is caught by faithful extraction; see test_extraction.py.)"""
    title = "TECHNOLOGY INFRASTRUCTURE LEGENDS AND LEGENDS NOTES"
    block = [(110, "T0.0.2", title)]
    index = {"T0.0.2": title}
    _, _, mismatches, _ = cross_check(block, index)
    assert mismatches == []


def test_cross_check_detects_duplicate_sheet_numbers():
    block = [(5, "A1.1", "PLAN"), (6, "A1.1", "PLAN")]
    index = {"A1.1": "PLAN"}
    _, _, _, duplicates = cross_check(block, index)
    assert duplicates == {"A1.1": [5, 6]}


def test_normalize():
    assert normalize("  Floor   Plan ") == "FLOOR PLAN"


# --- cover reconciliation --------------------------------------------------

def test_reconcile_cover_infers_single_unreadable_page():
    block = [(1, "", ""), (2, "G1.1", "GENERAL")]     # page 1 unreadable
    index = {"G0.0": "PROJECT COVER SHEET", "G1.1": "GENERAL"}
    missing = ["G0.0"]
    new_block, inferred, remaining = reconcile_cover(block, index, missing)
    assert inferred == [(1, "G0.0", "PROJECT COVER SHEET")]
    assert remaining == []
    assert (1, "G0.0", "PROJECT COVER SHEET") in new_block


def test_reconcile_cover_is_noop_when_ambiguous():
    """Two unreadable pages -> can't safely infer which is the cover."""
    block = [(1, "", ""), (2, "", "")]
    index = {"G0.0": "PROJECT COVER SHEET"}
    missing = ["G0.0"]
    new_block, inferred, remaining = reconcile_cover(block, index, missing)
    assert inferred == []
    assert remaining == ["G0.0"]


# --- numbering gaps --------------------------------------------------------

def test_numbering_gap_present_in_index_is_a_real_omission():
    # A2.1.3 is skipped in the set but the index lists it -> real omission.
    numbers = ["A2.1.1", "A2.1.2", "A2.1.4"]
    index_numbers = {"A2.1.1", "A2.1.2", "A2.1.3", "A2.1.4"}
    gaps = numbering_gaps(numbers, index_numbers)
    assert ("A2.1.3", [1, 2, 4], True) in gaps


def test_numbering_gap_absent_from_index_is_intentional():
    numbers = ["A2.1.1", "A2.1.2", "A2.1.4"]
    index_numbers = {"A2.1.1", "A2.1.2", "A2.1.4"}   # index also skips .3
    gaps = numbering_gaps(numbers, index_numbers)
    assert ("A2.1.3", [1, 2, 4], False) in gaps


def test_no_gap_for_single_member_run():
    numbers = ["A4.1.2"]              # only one in the run -> not a gap
    assert numbering_gaps(numbers, set()) == []


# --- page order ------------------------------------------------------------

def test_order_inversion_detected():
    index_entries = [("A1.1", "x"), ("A1.2", "x"), ("A1.3", "x")]
    # pages bound out of order: A1.3 before A1.2
    block = [(1, "A1.1", "x"), (2, "A1.3", "x"), (3, "A1.2", "x")]
    inv = order_inversions(block, index_entries)
    assert (2, "A1.3", 3, "A1.2") in inv


def test_order_ok_when_pages_follow_index():
    index_entries = [("A1.1", "x"), ("A1.2", "x"), ("A1.3", "x")]
    block = [(1, "A1.1", "x"), (2, "A1.2", "x"), (3, "A1.3", "x")]
    assert order_inversions(block, index_entries) == []
