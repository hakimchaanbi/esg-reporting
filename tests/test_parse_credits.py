"""
Check the credit-detail parse against values read by eye from the raw HTML.

Was verify_v3.py at the project root.

More rows is not the same as correct rows — the old parser produced 354 rows
per institution and every one was boilerplate. The strongest check here is the
arithmetic one: the scope 1 and 2 components extracted from Berkeley OP-6 sum
to a total that STARS states in a SEPARATE field. The parser never sees that
total, so the sum only balances if every value and every unit was read right.

RUN
    python tests/test_parse_credits.py
"""

import pathlib
import sys

import pandas as pd

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MASTER = PROJECT_ROOT / "Combined_universities_data" / "combined_credit_fields.csv"

failures = []


def check(name: str, passed: bool, detail: str = ""):
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")
    if not passed:
        failures.append(name)


def main():
    if not MASTER.exists():
        sys.exit(f"[stop] {MASTER} not found — run "
                 f"`python -m scrapers.parse_credit_pages` first.")

    df = pd.read_csv(MASTER)
    op6 = df[(df.institution.str.contains("Berkeley")) & (df.credit_code == "OP-6")]

    print("\n1. Figures match what is visible in the raw HTML\n")
    expected = {
        "Scope 1 GHG emissions from stationary combustion": 134957.0,
        "Scope 1 GHG emissions from mobile combustion": 1676.0,
        "Scope 1 GHG fugitive emissions": 76.0,
        "Scope 2 GHG emissions from off-site sources of electricity (market-based)": 1256.0,
    }
    for field, want in expected.items():
        hit = op6[op6.field == field]
        got = hit.value_numeric.iloc[0] if len(hit) else None
        check(f"{field[:52]} == {want:,.0f}", got == want, f"got {got}")

    print("\n2. The components sum to the total STARS reports separately\n")
    parts = sum(expected.values())
    total_row = op6[op6.field == "Annual scope 1 and 2 GHG emissions"]
    total = total_row.value_numeric.iloc[0] if len(total_row) else None
    check("scope 1 + scope 2 components == reported total",
          total is not None and abs(parts - total) < 1,
          f"{parts:,.0f} vs {total:,.0f}" if total else "total not found")

    print("\n3. Units are in their own column, never left inside the value\n")
    leaked = df[df.value.astype(str).str.contains(
        "Metric tons|Megawatt|Cubic meters", na=False)
        & (df.value_type == "number")]
    check("no numeric value contains its units", len(leaked) == 0,
          f"{len(leaked)} leaked")

    print("\n4. The boilerplate bug has not returned\n")
    for inst, g in df.groupby("institution"):
        n = g.field.nunique()
        check(f"{inst[:34]} has many distinct questions", n > 500,
              f"{n} distinct")

    print("\n5. Known-absent data is absent, not invented\n")
    tud = df[(df.institution.str.contains("Dublin"))
             & (df.credit_code.isin(["PA-4", "PA-5"]))]
    check("TU Dublin PA-4/PA-5 have no fields (no endowment — CLAUDE.md §6.6)",
          len(tud) == 0, f"{len(tud)} rows")

    print()
    if failures:
        sys.exit(f"{len(failures)} check(s) FAILED: {failures}")
    print("All parse checks passed.")


if __name__ == "__main__":
    main()
