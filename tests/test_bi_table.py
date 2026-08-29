"""
Verify the BI tables against the master dataset, and prove the dashboard runs.

The dashboard is the one deliverable a supervisor will click through rather than
read, so "it started without crashing" is not enough — an HTTP 200 from the
Streamlit server only proves the server booted. Streamlit renders over a
WebSocket after the page loads, so a Python error inside the app never reaches
that first response. `streamlit.testing.v1.AppTest` executes the script properly
and surfaces exceptions, which is what is used here.

Five claims, each tested:
  1. Every value in bi_metrics.csv exists in esg_master_dataset.csv, for THAT
     institution, under THAT credit and field.
  2. bi_scores.csv counts each credit once — the anchored sum is 638.15, not the
     14,242 a naive aggregate of the master table produces (§5).
  3. Scoring internals ("Points earned for indicator…") are excluded from the
     metrics table; they are STARS bookkeeping, not ESG data.
  4. bi_coverage.csv agrees with the content index, though it is derived
     independently of it.
  5. The dashboard executes with no exception, and its comparison tab charts
     only normalised metrics — never an absolute total across institutions.

RUN
    python tests/test_bi_table.py
"""

import collections
import pathlib
import re
import sys

import pandas as pd

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUT = PROJECT_ROOT / "report" / "output"
MASTER = PROJECT_ROOT / "Combined_universities_data" / "esg_master_dataset.csv"

failures = []


def check(name: str, passed: bool, detail: str = ""):
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")
    if not passed:
        failures.append(name)


def main():
    for n in ("bi_scores", "bi_metrics", "bi_coverage"):
        if not (OUT / f"{n}.csv").exists():
            sys.exit("[stop] run: python -m report.build_bi_table")

    master = pd.read_csv(MASTER)
    scores = pd.read_csv(OUT / "bi_scores.csv")
    metrics = pd.read_csv(OUT / "bi_metrics.csv")
    coverage = pd.read_csv(OUT / "bi_coverage.csv")

    print("\n1. Every metric traces to the master dataset\n")

    mismatched = []
    for r in metrics.itertuples(index=False):
        hit = master[(master.institution == r.institution)
                     & (master.credit_code == r.credit_code)
                     & (master.field == r.field)]
        if hit.empty:
            mismatched.append(f"{r.credit_code}/{r.field[:30]}: no such row")
        elif float(hit.iloc[0].value_numeric) != float(r.value_numeric):
            mismatched.append(
                f"{r.credit_code}/{r.field[:30]}: {r.value_numeric} vs "
                f"{hit.iloc[0].value_numeric}")
    check(f"all {len(metrics)} metric values match the dataset",
          not mismatched, "; ".join(mismatched[:3]))

    print("\n2. Scores are counted once per credit, not once per field row\n")

    naive = pd.to_numeric(master.score, errors="coerce").sum()
    check("anchored sum is 638.15, not the 22x overcount",
          abs(scores.score.sum() - 638.15) < 0.01,
          f"anchored {scores.score.sum():,.2f} vs naive {naive:,.2f}")
    dupes = scores.groupby(["institution", "credit_code"]).size()
    check("no credit appears twice", (dupes == 1).all(),
          f"{(dupes > 1).sum()} duplicated")
    check("one row per credit in the dataset",
          len(scores) == master[master.credit_row_anchor == True].shape[0],  # noqa: E712
          f"{len(scores)} rows")

    print("\n3. STARS scoring internals are excluded from the metrics\n")

    internals = metrics[metrics.field.astype(str).str.startswith("Points earned")]
    check("no 'Points earned for indicator' rows", len(internals) == 0,
          f"{len(internals)} leaked")
    # Not vacuous: they exist in the source and had to be actively removed.
    in_master = master[master.field.astype(str).str.startswith("Points earned")]
    check("and they do exist in the source, so the filter did work",
          len(in_master) > 100, f"{len(in_master)} in the master dataset")

    print("\n4. Coverage agrees with the content index, derived separately\n")

    # Match DISCLOSURE rows specifically. Counting `"| Reported |"` anywhere in
    # the file is off by exactly one per status, because each index opens with a
    # summary table whose header cells contain those same strings. The first
    # version of this check did that and reported 26/16/39 against 25/15/38 —
    # the test was wrong, not the data.
    row_re = re.compile(
        r"^\| \*\*[\d-]+\*\*[^|]*\| "
        r"(Reported|Partially reported|Not reported|Not assessed) \|",
        re.MULTILINE)

    for md in sorted(OUT.glob("*_gri_index.md")):
        key = md.stem.replace("_gri_index", "")
        found = collections.Counter(row_re.findall(md.read_text(encoding="utf-8")))
        check(f"{key}: all 78 disclosure rows matched",
              sum(found.values()) == 78, f"matched {sum(found.values())}")
        for status in ("Reported", "Partially reported", "Not reported"):
            in_csv = len(coverage[(coverage.institution_key == key)
                                  & (coverage.status == status)])
            check(f"{key}: {status} — index {found[status]}, table {in_csv}",
                  found[status] == in_csv)

    print("\n5. The dashboard executes, and refuses absolute cross-comparison\n")

    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        check("streamlit is installed", False, "pip install streamlit")
    else:
        app = AppTest.from_file(str(PROJECT_ROOT / "report" / "dashboard.py"),
                                default_timeout=120)
        app.run()
        check("dashboard runs with no exception", not app.exception,
              str(app.exception[0].value)[:200] if app.exception else "")
        check("it rendered content", len(app.markdown) + len(app.title) > 3,
              f"{len(app.markdown)} markdown blocks, {len(app.title)} titles")

    # The design promise: the comparison view is intensity-only. Verified against
    # the data the tab actually charts, not against the source code.
    charted = metrics[metrics.is_intensity & metrics.comparable]
    absolute = charted[~charted.field.astype(str).str.contains(
        "per person|per unit of floor area", case=False)]
    check("the comparison set contains only normalised metrics",
          len(absolute) == 0, f"{len(absolute)} absolute metrics would be charted")
    check("and it is not empty", charted.field.nunique() >= 8,
          f"{charted.field.nunique()} intensity metrics, all three institutions")

    print()
    if failures:
        sys.exit(f"{len(failures)} check(s) FAILED: {failures}")
    print("BI tables verified against esg_master_dataset.csv, "
          "and the dashboard runs clean.")


if __name__ == "__main__":
    main()
