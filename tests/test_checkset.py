"""
Checks-as-data engine tests — pure functions over plain data (no PDFs).

Covers the checkset.py engine: each primitive in the vocabulary, message
rendering, firm overrides (re-grade / silence / re-parameterize), loud
validation failures, and parity with the hand-written reference checks.
"""

import pytest
import yaml

from checkset import build_checkset, load_checks, run_checkset
from cross_check import cross_check
from sequence_check import order_inversions


# A faulted set exercising every check at once:
#   A2.1 indexed but absent, A9.9 present but unindexed, A1.2 mis-titled,
#   D1.1 duplicated, pages 4/5 bound out of index order, A3.3 skipped in a
#   run the index DOES list, page 9 unreadable.
BLOCK = [
    (1, "A1.1", "FLOOR PLAN"),
    (2, "A1.2", "ROOF PLAN"),
    (3, "A9.9", "EXTRA DETAIL"),
    (4, "D1.2", "DETAILS TWO"),
    (5, "D1.1", "DETAILS ONE"),
    (6, "D1.1", "DETAILS ONE"),
    (7, "A3.2", "SECTIONS"),
    (8, "A3.4", "SECTIONS"),
    (9, "", ""),
]
INDEX = [
    ("A1.1", "FLOOR PLAN"),
    ("A1.2", "ROOF PLAN - OVERALL"),
    ("A2.1", "CEILING PLAN"),
    ("D1.1", "DETAILS ONE"),
    ("D1.2", "DETAILS TWO"),
    ("A3.2", "SECTIONS"),
    ("A3.3", "SECTIONS"),
    ("A3.4", "SECTIONS"),
]
FACTS = {"block_rows": BLOCK, "index_entries": INDEX}

CHECKS = build_checkset(load_checks())


def findings_for(check_id, facts=FACTS, checks=CHECKS):
    result = run_checkset([c for c in checks if c["id"] == check_id], facts)
    return result["findings"]


# --- each primitive over the faulted set ------------------------------------

def test_missing_sheet_found_with_verbatim_index_title():
    # A3.3 is both a numbering gap and, like A2.1, an indexed-but-absent sheet.
    found = findings_for("missing-sheet")
    assert [f["evidence"]["number"] for f in found] == ["A2.1", "A3.3"]
    assert "'CEILING PLAN'" in found[0]["message"]
    assert found[0]["severity"] == "error"


def test_extra_sheet_found_with_page_evidence():
    found = findings_for("extra-sheet")
    assert [f["evidence"]["number"] for f in found] == ["A9.9"]
    assert found[0]["evidence"]["page"] == 3


def test_title_mismatch_found_and_normalization_forgives_case():
    found = findings_for("title-mismatch")
    assert [f["evidence"]["number"] for f in found] == ["A1.2"]

    agree = {"block_rows": [(1, "A1.1", "floor   plan")],
             "index_entries": [("A1.1", "FLOOR PLAN")]}
    assert findings_for("title-mismatch", agree) == []


def test_duplicate_number_found():
    found = findings_for("duplicate-number")
    assert found[0]["evidence"] == {"number": "D1.1", "pages": [5, 6]}


def test_page_order_inversion_found():
    found = findings_for("page-order")
    assert found[0]["evidence"] == {"page_a": 4, "number_a": "D1.2",
                                    "page_b": 5, "number_b": "D1.1"}


def test_numbering_gap_escalates_only_when_index_shares_it():
    found = findings_for("numbering-gap")
    assert [f["evidence"]["missing_number"] for f in found] == ["A3.3"]
    assert found[0]["severity"] == "error"        # index lists A3.3 -> escalated
    assert "real omission" in found[0]["message"]

    # The same gap with an index that also skips A3.3 stays a note.
    index_skips = {"block_rows": BLOCK,
                   "index_entries": [e for e in INDEX if e[0] != "A3.3"]}
    found = findings_for("numbering-gap", index_skips)
    assert found[0]["severity"] == "note"
    assert "likely intentional" in found[0]["message"]


def test_unreadable_page_found():
    found = findings_for("unreadable-page")
    assert found[0]["evidence"] == {"page": 9}


def test_clean_set_is_clean():
    clean = {"block_rows": [(1, "A1.1", "FLOOR PLAN"), (2, "A1.2", "ROOF PLAN")],
             "index_entries": [("A1.1", "FLOOR PLAN"), ("A1.2", "ROOF PLAN")]}
    result = run_checkset(CHECKS, clean)
    assert result["clean"] and result["findings"] == []


def test_error_findings_make_the_set_unclean():
    result = run_checkset(CHECKS, FACTS)
    assert not result["clean"]
    assert result["counts"]["error"] >= 4     # missing, extra, duplicate, order


# --- parity with the hand-written reference checks --------------------------

def test_engine_reproduces_cross_check_and_sequence_check():
    """The YAML-driven engine and the reference implementations must agree on
    the same faulted data — the engine is a representation change, not a
    behavior change."""
    missing, extra, mismatches, duplicates = cross_check(BLOCK, dict(INDEX))
    inversions = order_inversions(BLOCK, INDEX)

    result = run_checkset(CHECKS, FACTS)
    by_check = {}
    for f in result["findings"]:
        by_check.setdefault(f["check"], []).append(f["evidence"])

    assert [e["number"] for e in by_check["missing-sheet"]] == missing
    assert [e["number"] for e in by_check["extra-sheet"]] == extra
    assert [e["number"] for e in by_check["title-mismatch"]] == [m[0] for m in mismatches]
    assert {e["number"]: e["pages"] for e in by_check["duplicate-number"]} == duplicates
    assert [(e["page_a"], e["number_a"], e["page_b"], e["number_b"])
            for e in by_check["page-order"]] == inversions


# --- the check set is data: overrides and validation ------------------------

FIRM_OVERRIDE_DOC = """
version: 1
checks:
  - id: missing-sheet
    label: Indexed sheet absent from the set
    type: set_difference
    params: {from: index, minus: sheets}
    severity: error
    message: "{number} is missing."
  - id: numbering-gap
    label: Skipped value inside a numbering run
    type: run_gaps
    severity: note
    message: "{missing_number} skipped{qualifier}."
firms:
  "Volume-by-Volume Firm":
    missing-sheet: {severity: note}
    numbering-gap: {enabled: false}
"""


def test_firm_override_regrades_and_silences_without_code():
    data = yaml.safe_load(FIRM_OVERRIDE_DOC)

    base = build_checkset(data)
    assert [c["id"] for c in base] == ["missing-sheet", "numbering-gap"]
    assert base[0]["severity"] == "error"

    firm = build_checkset(data, firm="Volume-by-Volume Firm")
    assert [c["id"] for c in firm] == ["missing-sheet"]          # gap check silenced
    assert firm[0]["severity"] == "note"                         # error re-graded

    # A partial volume now passes for that firm (notes never fail a set).
    partial = {"block_rows": [(1, "A1.1", "PLAN")],
               "index_entries": [("A1.1", "PLAN"), ("S1.1", "FRAMING")]}
    assert not run_checkset(base, partial)["clean"]
    assert run_checkset(firm, partial)["clean"]


def test_new_check_is_a_yaml_entry_not_code():
    """A check the codebase never shipped, defined purely as data."""
    doc = yaml.safe_load("""
    checks:
      - id: strict-title-match
        label: Titles must match exactly (no normalization)
        type: field_mismatch
        severity: error
        message: "{number}: {sheet_title!r} != {index_title!r}"
    """)
    checks = build_checkset(doc)
    facts = {"block_rows": [(1, "A1.1", "floor plan")],
             "index_entries": [("A1.1", "FLOOR PLAN")]}
    found = run_checkset(checks, facts)["findings"]
    assert len(found) == 1 and found[0]["severity"] == "error"


def test_unknown_type_fails_loudly_at_load_time():
    doc = yaml.safe_load("""
    checks:
      - {id: bad, label: x, type: telepathy, severity: error, message: x}
    """)
    with pytest.raises(ValueError, match="telepathy"):
        build_checkset(doc)


def test_unknown_severity_fails_loudly_at_load_time():
    doc = yaml.safe_load("""
    checks:
      - {id: bad, label: x, type: duplicate_key, severity: catastrophic, message: x}
    """)
    with pytest.raises(ValueError, match="catastrophic"):
        build_checkset(doc)


def test_shipped_checks_yaml_is_valid_and_complete():
    """The repo's checks.yaml resolves cleanly and covers every finding the
    reference checks can raise."""
    ids = {c["id"] for c in CHECKS}
    assert ids == {"missing-sheet", "extra-sheet", "title-mismatch",
                   "duplicate-number", "page-order", "numbering-gap",
                   "unreadable-page"}
