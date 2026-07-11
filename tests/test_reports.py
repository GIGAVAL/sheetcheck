"""
Findings-dict tests — the analyze_rows() layer that feeds both the printed
reports and --json output. Pure functions over plain data, no PDFs.
"""

import json

from cross_check import analyze_rows as cross_analyze
from sequence_check import analyze_rows as sequence_analyze


# --- cross_check.analyze_rows ------------------------------------------------

def test_cross_findings_dict_flags_everything():
    block = [
        (1, "A1.1", "FLOOR PLAN"),        # matches index
        (2, "A1.2", "ROOF PLAN"),         # title differs -> mismatch
        (3, "A9.9", "EXTRA DETAIL"),      # not in index -> extra
    ]
    index = {
        "A1.1": "FLOOR PLAN",
        "A1.2": "ROOF PLAN - OVERALL",
        "A2.1": "CEILING PLAN",           # no page -> missing
    }
    res = cross_analyze("TestFirm", 2, index, block)

    assert res["check"] == "cross_check"
    assert res["profile"] == "TestFirm"
    assert res["missing"] == [{"number": "A2.1", "index_title": "CEILING PLAN"}]
    assert res["extra"] == [{"number": "A9.9", "page": 3, "title": "EXTRA DETAIL"}]
    assert [m["number"] for m in res["title_mismatches"]] == ["A1.2"]
    assert res["clean"] is False


def test_cross_findings_dict_clean_set():
    block = [(1, "A1.1", "FLOOR PLAN")]
    index = {"A1.1": "FLOOR PLAN"}
    res = cross_analyze("TestFirm", 2, index, block)
    assert res["clean"] is True
    assert res["matched"] == 1


def test_cross_findings_include_inferred_cover():
    """The graphics-only cover flows through reconciliation into the dict."""
    block = [(1, "", ""), (2, "G1.1", "GENERAL")]
    index = {"G0.0": "PROJECT COVER SHEET", "G1.1": "GENERAL"}
    res = cross_analyze("TestFirm", 2, index, block)
    assert res["inferred"] == [{"page": 1, "number": "G0.0",
                                "title": "PROJECT COVER SHEET"}]
    assert res["missing"] == []
    assert res["clean"] is True


def test_cross_findings_are_json_serializable():
    block = [(5, "A1.1", "PLAN"), (6, "A1.1", "PLAN")]   # duplicate number
    res = cross_analyze("TestFirm", 2, {"A1.1": "PLAN"}, block)
    round_tripped = json.loads(json.dumps(res))
    assert round_tripped["duplicates"] == [{"number": "A1.1", "pages": [5, 6]}]
    assert round_tripped["clean"] is False


# --- sequence_check.analyze_rows ---------------------------------------------

def test_sequence_findings_dict_flags_inversion_and_real_gap():
    index_entries = [("A1.1", "x"), ("A1.2", "x"), ("A1.3", "x"), ("A1.4", "x")]
    # A1.3 bound before A1.2, and A1.4 present while A1.3 missing from the run
    block = [(1, "A1.1", "x"), (2, "A1.4", "x"), (3, "A1.2", "x")]
    res = sequence_analyze("TestFirm", block, index_entries)

    assert res["check"] == "sequence_check"
    assert {"page_a": 2, "number_a": "A1.4", "page_b": 3,
            "number_b": "A1.2"} in res["inversions"]
    assert {"missing_number": "A1.3", "present_run": [1, 2, 4],
            "in_index": True} in res["gaps"]
    assert res["clean"] is False


def test_sequence_advisory_only_gaps_still_pass():
    """A gap the index also skips is advisory: reported, but clean stays True."""
    index_entries = [("A1.1", "x"), ("A1.2", "x"), ("A1.4", "x")]   # index skips A1.3 too
    block = [(1, "A1.1", "x"), (2, "A1.2", "x"), (3, "A1.4", "x")]
    res = sequence_analyze("TestFirm", block, index_entries)
    assert [g["in_index"] for g in res["gaps"]] == [False]
    assert res["clean"] is True


def test_sequence_findings_are_json_serializable():
    res = sequence_analyze("TestFirm", [(1, "A1.1", "x")], [("A1.1", "x")])
    assert json.loads(json.dumps(res))["clean"] is True
