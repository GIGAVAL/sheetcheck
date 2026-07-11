"""
checkset.py — SheetCheck checks-as-data engine

The check set lives in checks.yaml as DATA: each entry names one of the
small vocabulary of primitive check types defined here, plus parameters,
a severity, and a message template. This engine interprets the file; it
has no per-check logic of its own.

What that buys, compared to one script per check:

  * A new check within the vocabulary is a YAML entry, not code.
  * A firm-specific check set (re-grade a severity, silence a check,
    change a parameter) is a `firms:` override in the YAML, applied
    automatically when that firm's template is detected.
  * The check set itself is reviewable by a QA lead who doesn't read
    Python — and diffable, so "what do we check for firm X" has an
    exact, versioned answer.

cross_check.py and sequence_check.py remain the hand-written reference
implementations; the test suite proves this engine reproduces their
findings from the same data.

Usage:
    python checkset.py <set.pdf> [--json] [--checks checks.yaml]
    python checkset.py --list          # show the check set, no PDF needed

Exits non-zero when any error-severity finding is raised, so a set can
gate a CI pipeline.
"""

import argparse
import json
import sys

import pdfplumber
import yaml
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from extract import extract_sheets
from profiles import detect_profile
from cross_check import parse_sheet_index, reconcile_cover
from sequence_check import order_inversions, numbering_gaps

console = Console(highlight=False)

DEFAULT_CHECKS_FILE = "checks.yaml"
SEVERITIES = ("error", "warning", "note")

# Named title/text normalizers a check can compose in its params.
NORMALIZERS = {
    "uppercase": str.upper,
    "collapse_whitespace": lambda s: " ".join(s.split()),
    "strip": str.strip,
}


# --- the primitive vocabulary -----------------------------------------------
# Each primitive is a pure function (params, facts) -> list of evidence dicts.
# facts = {"index_entries": ordered [(number, title)],
#          "block_rows":    [(page, number, title)] in page order}
# A primitive may set "_severity" in an evidence dict to re-grade one finding
# (e.g. a numbering gap the index does not share stays advisory).

def _sheets_by_number(block_rows):
    """First page wins, matching cross_check; duplicates have their own check."""
    sheets = {}
    for pg, num, title in block_rows:
        if num and num not in sheets:
            sheets[num] = (pg, title)
    return sheets


def _set_difference(params, facts):
    index = dict(facts["index_entries"])
    sheets = _sheets_by_number(facts["block_rows"])
    if params["from"] == "index":
        return [{"number": n, "index_title": t}
                for n, t in facts["index_entries"] if n not in sheets]
    return [{"number": n, "page": sheets[n][0], "sheet_title": sheets[n][1]}
            for n in sorted(set(sheets) - set(index))]


def _field_mismatch(params, facts):
    steps = [NORMALIZERS[name] for name in params.get("normalize", [])]

    def norm(text):
        for step in steps:
            text = step(text)
        return text

    index = dict(facts["index_entries"])
    findings = []
    for num, (pg, title) in _sheets_by_number(facts["block_rows"]).items():
        if num in index and norm(title) != norm(index[num]):
            findings.append({"number": num, "page": pg,
                             "sheet_title": title, "index_title": index[num]})
    return findings


def _duplicate_key(params, facts):
    pages = {}
    for pg, num, _ in facts["block_rows"]:
        if num:
            pages.setdefault(num, []).append(pg)
    return [{"number": num, "pages": pgs}
            for num, pgs in pages.items() if len(pgs) > 1]


def _order_inversion(params, facts):
    return [{"page_a": pg_a, "number_a": num_a, "page_b": pg_b, "number_b": num_b}
            for pg_a, num_a, pg_b, num_b
            in order_inversions(facts["block_rows"], facts["index_entries"])]


def _run_gaps(params, facts):
    index_numbers = {n for n, _ in facts["index_entries"]}
    present = [num for _, num, _ in facts["block_rows"] if num]
    findings = []
    for missing_number, present_run, in_index in numbering_gaps(present, index_numbers):
        evidence = {
            "missing_number": missing_number,
            "present_run": present_run,
            "in_index": in_index,
            "qualifier": (" — the index lists it too (a real omission)" if in_index
                          else " — the index skips it too (likely intentional)"),
        }
        if in_index and params.get("escalate_if_in_index"):
            evidence["_severity"] = params["escalate_if_in_index"]
        findings.append(evidence)
    return findings


def _unreadable_page(params, facts):
    return [{"page": pg} for pg, num, _ in facts["block_rows"] if not num]


PRIMITIVES = {
    "set_difference": _set_difference,
    "field_mismatch": _field_mismatch,
    "duplicate_key": _duplicate_key,
    "order_inversion": _order_inversion,
    "run_gaps": _run_gaps,
    "unreadable_page": _unreadable_page,
}


# --- loading and resolving the check set ------------------------------------

def load_checks(path=DEFAULT_CHECKS_FILE):
    with open(path) as f:
        return yaml.safe_load(f)


def build_checkset(data, firm=None):
    """Resolve the YAML document into the list of enabled checks for a firm.

    Firm overrides (severity / enabled / params, keyed by check id) are merged
    over the base entries; params merge key-by-key, everything else replaces.
    Validates against the primitive vocabulary so a typo in the YAML fails
    loudly, at load time.
    """
    overrides = (data.get("firms") or {}).get(firm) or {}
    checks = []
    for entry in data["checks"]:
        check = {**entry, "params": dict(entry.get("params") or {})}
        override = overrides.get(check["id"]) or {}
        check.update({k: v for k, v in override.items() if k != "params"})
        check["params"].update(override.get("params") or {})

        if check["type"] not in PRIMITIVES:
            raise ValueError(
                f"check {check['id']!r}: unknown type {check['type']!r} "
                f"(vocabulary: {', '.join(sorted(PRIMITIVES))})")
        if check["severity"] not in SEVERITIES:
            raise ValueError(
                f"check {check['id']!r}: unknown severity {check['severity']!r} "
                f"(one of: {', '.join(SEVERITIES)})")
        if check.get("enabled", True):
            checks.append(check)
    return checks


# --- running -----------------------------------------------------------------

def run_checkset(checks, facts):
    """Run every enabled check over already-extracted rows.

    Pure function over plain data (no PDF I/O), returns a JSON-serializable
    findings dict — the single source both the printed report and --json use.
    """
    findings = []
    for check in checks:
        for evidence in PRIMITIVES[check["type"]](check["params"], facts):
            severity = evidence.pop("_severity", check["severity"])
            findings.append({
                "check": check["id"],
                "severity": severity,
                "message": check["message"].format(**evidence),
                "evidence": evidence,
            })
    counts = {s: sum(f["severity"] == s for f in findings) for s in SEVERITIES}
    return {"findings": findings, "counts": counts, "clean": counts["error"] == 0}


def analyze(pdf_path, checks_path=DEFAULT_CHECKS_FILE):
    """Extract one PDF and run the (firm-resolved) check set over it."""
    block_rows = [(s["page"], s["number"], s["title"]) for s in extract_sheets(pdf_path)]
    with pdfplumber.open(pdf_path) as pdf:
        profile = detect_profile(pdf)
        index_entries = parse_sheet_index(pdf.pages[profile.index_page - 1], profile)
    # Fill the graphics-only cover before checking, as the other checks do.
    index = dict(index_entries)
    missing = [n for n in index if n not in {b[1] for b in block_rows}]
    block_rows, _, _ = reconcile_cover(block_rows, index, missing)

    checks = build_checkset(load_checks(checks_path), firm=profile.name)
    result = run_checkset(checks, {"index_entries": index_entries,
                                   "block_rows": block_rows})
    return {"check": "checkset", "checks_file": checks_path,
            "profile": profile.name, "checks_run": [c["id"] for c in checks],
            **result}


# --- reporting ---------------------------------------------------------------

SEVERITY_STYLE = {"error": "red", "warning": "yellow", "note": "blue"}


def print_checkset(checks):
    table = Table(title=f"The check set ({DEFAULT_CHECKS_FILE})", title_justify="left")
    table.add_column("id")
    table.add_column("severity")
    table.add_column("type", style="dim")
    table.add_column("what it catches")
    for c in checks:
        table.add_row(c["id"], f"[{SEVERITY_STYLE[c['severity']]}]{c['severity']}[/]",
                      c["type"], c["label"])
    console.print(table)
    console.print("[dim]Every row is a YAML entry, not code — edit checks.yaml "
                  "to tune, silence, or re-grade a check, globally or per firm.[/]")


def print_report(res):
    console.print("=" * 70)
    console.print(f"[bold]CHECK SET[/]   [dim]\\[{escape(res['profile'])} template · "
                  f"{len(res['checks_run'])} checks from {res['checks_file']}][/]")
    console.print("=" * 70)

    for severity in SEVERITIES:
        found = [f for f in res["findings"] if f["severity"] == severity]
        style = SEVERITY_STYLE[severity]
        console.print(f"[{style}]{severity.upper()}[/] ({len(found)}):")
        if found:
            for f in found:
                console.print(f"      [dim]{f['check']:<18}[/] {escape(f['message'])}")
        else:
            console.print("      [green]none.[/]")
        console.print()

    console.print("RESULT:", "[bold green]PASS — no error-severity findings.[/]" if res["clean"]
                  else "[bold red]DISCREPANCIES FOUND (see above).[/]")


def main():
    parser = argparse.ArgumentParser(description="Run the checks.yaml check set on a drawing set.")
    parser.add_argument("pdf", nargs="?", default="bidset.pdf")
    parser.add_argument("--checks", default=DEFAULT_CHECKS_FILE,
                        help="check-set YAML to run (default: checks.yaml)")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    parser.add_argument("--list", action="store_true",
                        help="show the check set and exit (no PDF needed)")
    args = parser.parse_args()

    if args.list:
        print_checkset(build_checkset(load_checks(args.checks)))
        return

    result = analyze(args.pdf, checks_path=args.checks)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)
    sys.exit(0 if result["clean"] else 1)


if __name__ == "__main__":
    main()
