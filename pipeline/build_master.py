"""
Phase 3b — join the credit-level scores to the field-level detail
=================================================================

Phase 3 produced two tables that describe the same thing at different zoom
levels, and nothing yet connected them:

    combined_esg_dataset.csv       191 rows — one per CREDIT.  "OP-6 scored
                                   8.01 of 16."  Has pillar, status, score.

    combined_credit_fields.csv   3,197 rows — one per FIELD.   "Scope 1
                                   stationary combustion = 134,957 t CO2e."
                                   Has units and value_type, but no score.

This joins them on (institution, credit_code) so every field row carries the
score context of the credit it came from, and every credit is present even when
it has no fields.

WHY AN OUTER JOIN, NOT AN INNER ONE
    TU Dublin's PA-4 and PA-5 (investment) have no field data at all — it is a
    public university with no endowment (CLAUDE.md §6.6). That absence is a
    genuine research finding about applying corporate ESG frameworks to higher
    education, not a gap to be quietly dropped. An inner join would delete it.
    They are kept as rows with has_detail = False.

⚠️  THE ONE TRAP IN THIS TABLE — READ BEFORE BUILDING THE DASHBOARD
    The join is one-to-many, so a credit's score is REPEATED on every one of its
    field rows. OP-6's 8.01 appears ~99 times. Summing the score column naively
    gives 14,242 instead of the true 638.15 — a 22x overcount that looks like a
    plausible number.

    Guard: the boolean column `credit_row_anchor` is True on exactly ONE row per
    (institution, credit_code). Any credit-level aggregate — total score, credit
    counts, pillar totals — must filter on it:

        Power BI :  CALCULATE(SUM(score), esg_master[credit_row_anchor] = TRUE)
        pandas   :  df[df.credit_row_anchor].score.sum()

    Field-level aggregates (summing tonnes CO2e, counting metrics) use the full
    table and filter on value_type instead.

    Also filter `value_type == "number"` before averaging value_numeric: years
    ("Performance year = 2023") are typed "year", not "number", precisely so
    they cannot drift into a metric average.

OUTPUT
    esg_master_dataset.csv   the analysis-ready table the dashboard and the
                             Phase 5 number-injection both read from.

RUN
    python -m pipeline.build_master
"""

import pandas as pd

from scrapers.institutions import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "Combined_universities_data"
SCORES_IN = DATA_DIR / "combined_esg_dataset.csv"
FIELDS_IN = DATA_DIR / "combined_credit_fields.csv"
OUTPUT = DATA_DIR / "esg_master_dataset.csv"

KEY = ["institution", "credit_code"]

COLUMN_ORDER = [
    # credit level (from the scorecard)
    "institution", "stars_version", "pillar", "category", "category_code",
    "credit_code", "credit_name", "status", "score", "max",
    # True on exactly one row per credit — see the trap warning above
    "credit_row_anchor",
    # field level (from the credit detail pages)
    "has_detail", "section", "field", "value", "units", "value_numeric",
    "value_type",
    # every URL cited in the answer; documents/manifest.csv says which of them
    # were retrievable
    "links",
]


def main():
    if not SCORES_IN.exists() or not FIELDS_IN.exists():
        print(f"[stop] need both {SCORES_IN.name} and {FIELDS_IN.name}.")
        print("       run: python -m pipeline.combine_scores")
        print("            python -m scrapers.parse_credit_pages")
        return

    scores = pd.read_csv(SCORES_IN)
    fields = pd.read_csv(FIELDS_IN)
    print(f"[load] {len(scores):>5} credit rows   from {SCORES_IN.name}")
    print(f"[load] {len(fields):>5} field rows    from {FIELDS_IN.name}")

    # The scorecard is authoritative for pillar, category and credit_name — it
    # was validated in Phase 3. Drop the field table's copies so the join can't
    # produce _x/_y duplicates that quietly diverge later.
    fields = fields.drop(columns=["pillar", "category", "credit_name"],
                         errors="ignore")

    merged = scores.merge(fields, on=KEY, how="outer", indicator=True)

    # A credit with no detail pages still gets exactly one row, with the field
    # columns empty. This is what keeps TU Dublin PA-4/PA-5 visible.
    merged["has_detail"] = merged["_merge"] != "left_only"

    orphan_fields = merged[merged["_merge"] == "right_only"]
    merged = merged.drop(columns="_merge")

    merged = merged.sort_values(
        ["institution", "category_code", "credit_code", "section", "field"],
        kind="stable", na_position="last"
    ).reset_index(drop=True)

    # Mark one row per credit AFTER sorting, so the anchor is the first row of
    # each credit block rather than an arbitrary one.
    merged["credit_row_anchor"] = ~merged.duplicated(subset=KEY, keep="first")

    merged = merged[[c for c in COLUMN_ORDER if c in merged.columns]]

    merged.to_csv(OUTPUT, index=False)
    print(f"\n[save] {len(merged)} rows -> {OUTPUT}")

    # ------------------------------------------------------------------
    # validation — every one of these was a real failure mode at some point
    # ------------------------------------------------------------------
    print("\n--- validation ---")

    # A field row that matched no credit would mean the two scrapes disagree
    # about which credits exist. Must be zero.
    print(f"  field rows with no matching credit : {len(orphan_fields)} (must be 0)")
    if len(orphan_fields):
        print("    " + str(sorted(orphan_fields.credit_code.unique())[:12]))

    # Row count must be conserved: every field row survives, plus one row for
    # each credit that has no fields.
    no_detail = merged[~merged.has_detail]
    expected = len(fields) + len(no_detail)
    ok = "OK" if len(merged) == expected else "MISMATCH"
    print(f"  row count conserved                : {len(merged)} == "
          f"{len(fields)} fields + {len(no_detail)} detail-less credits [{ok}]")

    # Scores must not have been duplicated by the one-to-many join. The anchor
    # column is the thing the dashboard will rely on, so validate it directly
    # rather than validating a drop_duplicates() the dashboard won't run.
    src_total = scores.score.sum()
    anchored = merged[merged.credit_row_anchor]
    ok = "OK" if abs(src_total - anchored.score.sum()) < 0.01 else "MISMATCH"
    print(f"  total score via credit_row_anchor  : {src_total:.2f} vs "
          f"{anchored.score.sum():.2f} [{ok}]")

    ok = "OK" if len(anchored) == len(scores) else "MISMATCH"
    print(f"  anchor rows == credits             : {len(anchored)} vs "
          f"{len(scores)} [{ok}]")
    print(f"  (naive SUM(score) would give {merged.score.sum():,.0f} — "
          f"{merged.score.sum() / src_total:.0f}x too high)")

    print("\n--- credits with no detail fields (expected, not a bug) ---")
    if no_detail.empty:
        print("  (none)")
    for _, r in no_detail.iterrows():
        print(f"  {r.institution[:34]:36} {r.credit_code:7} "
              f"{str(r.credit_name)[:34]:36} status={r.status}")

    print("\n--- fields per institution ---")
    for inst in sorted(merged.institution.unique()):
        m = merged[(merged.institution == inst) & merged.has_detail]
        nums = (m.value_type == "number").sum()
        print(f"  {inst[:34]:36} {len(m):5} fields  {nums:4} numeric  "
              f"{m.credit_code.nunique():3} credits")

    print("\n--- numeric coverage by pillar (what the dashboard can plot) ---")
    nums = merged[merged.value_type == "number"]
    pivot = nums.pivot_table(index="pillar", columns="institution",
                             values="value", aggfunc="count", fill_value=0)
    print(pivot.to_string())

    print("\n--- comparability spot-check: same field, all three universities ---")
    # If the join and the parse are both right, a standard STARS field should
    # appear for every institution with the same units.
    probe = "Annual scope 1 and 2 GHG emissions"
    hit = merged[merged.field == probe]
    if hit.empty:
        print(f"  '{probe}' not found")
    for _, r in hit.iterrows():
        print(f"  {r.institution[:34]:36} {r.value:>12}  {r.units}")


if __name__ == "__main__":
    main()
