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

import collections
import pathlib
import sys

import pandas as pd

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MASTER = PROJECT_ROOT / "Combined_universities_data" / "combined_credit_fields.csv"

sys.path.insert(0, str(PROJECT_ROOT))
from scrapers.institutions import INSTITUTIONS       # noqa: E402

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

    print("\n6. Headings: no sub-section leaks past the indicator that ended it\n")

    # STARS nests <h5> sub-sections inside numbered <h4> indicators. The parser
    # used to read only <h5>, so an <h4>-only header did not reset anything and
    # the previous sub-section carried across the boundary: OP-6's `Gross floor
    # area of building space` (indicator 6.2) came out labelled "Scope 3 GHG
    # emissions" (indicator 6.1).
    #
    # This re-walks the cached HTML with its OWN heading tracker rather than
    # importing the parser's, so a repeat of the same mistake cannot pass.
    from bs4 import BeautifulSoup                                # noqa: E402

    def triples_from_html(path):
        """(field, indicator, section) for every title, in document order.

        A multiset, not a dict: a question can legitimately be asked twice on
        one page under different indicators — PA-9 asks "Does the institution
        have the required data…" under both 9.1 and 9.2 — and keying by name
        would silently compare the second occurrence against the first one's
        heading. That mistake made this test fail against a correct parser.
        """
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"),
                             "lxml")
        out, indicator, section = [], "", ""
        for el in soup.find_all(["div", "span"]):
            css = el.get("class") or []
            if "field-header" in css:
                h4, h5 = el.find("h4"), el.find("h5")
                if h4:
                    indicator = " ".join(h4.get_text(" ").split())
                    section = ""            # a new indicator ends the old h5
                if h5:
                    section = " ".join(h5.get_text(" ").split())
            elif "scorecardFieldTitle" in css:
                name = " ".join(el.get_text().split()).rstrip(":")
                out.append((name, indicator, section))
        return collections.Counter(out)

    mismatched, compared = [], 0
    for inst in INSTITUTIONS.values():
        cache = PROJECT_ROOT / inst.folder / inst.cache_dirname
        rows = df[df.institution == inst.name]
        for code, group in rows.groupby("credit_code"):
            page = cache / f"{code}.html"
            if not page.exists():
                continue
            want = triples_from_html(page)
            got = collections.Counter(
                (str(r.field),
                 str(r.indicator) if pd.notna(r.indicator) else "",
                 str(r.section) if pd.notna(r.section) else "")
                for r in group.itertuples(index=False))
            compared += sum(got.values())
            for triple, n in (got - want).items():
                mismatched.append(
                    f"{inst.key} {code}: {n}x {triple[0][:30]!r} claims "
                    f"({triple[1][:26]!r}, {triple[2][:20]!r})")

    check(f"{compared} fields carry the heading that precedes them in the HTML",
          not mismatched, "\n         ".join(mismatched[:4]))
    check("the heading comparison is not vacuous", compared > 3000,
          f"{compared} fields compared")

    named = df[(df.credit_code == "OP-6")
               & (df.field == "Gross floor area of building space")]
    bad = named[named.section.fillna("").str.contains("Scope 3")]
    check("OP-6 gross floor area is not filed under 'Scope 3 GHG emissions'",
          len(bad) == 0 and len(named) > 0,
          f"{len(named)} rows, indicator="
          f"{named.indicator.dropna().unique()[:1]}")

    print()
    if failures:
        sys.exit(f"{len(failures)} check(s) FAILED: {failures}")
    print("All parse checks passed.")


if __name__ == "__main__":
    main()
