"""
Phase 3 — combine the three scorecards into one dataset
=======================================================

Was Combined_universities_data/combine_universities.py. Moved out of the data
folder so code and data are not interleaved, and so it can share the pillar
mapping and file paths in scrapers/institutions.py.

It also now reads each institution's stars_csv from that institution's own
folder. Previously three identical copies of those CSVs sat in
Combined_universities_data/ as separate inputs — two copies of the same data
that could silently diverge. Those copies are gone.

WHAT IT DOES
    1. Stacks berkeley + cork + tudublin into a single table.
    2. Adds the E/S/G PILLAR column — the column that makes "compare E vs S vs
       G across universities" possible. STARS ships no such labels; the mapping
       is a reasoned curation decision documented in CLAUDE.md §8.
    3. Validates the result and prints a summary worth eyeballing.

RUN
    python -m pipeline.combine_scores

OUTPUT
    Combined_universities_data/combined_esg_dataset.csv   one row per credit
"""

from __future__ import annotations

import pandas as pd

from scrapers.institutions import PROJECT_ROOT, INSTITUTIONS, pillar_for

OUTPUT = PROJECT_ROOT / "Combined_universities_data" / "combined_esg_dataset.csv"

# All three current reports are STARS 3.0. Kept explicit because cross-version
# comparison is invalid (CLAUDE.md §6.4) and this column is what makes that
# checkable downstream.
STARS_VERSION = "3.0"


def load_one(institution) -> pd.DataFrame:
    path = institution.stars_csv
    if not path.exists():
        print(f"[skip] {path.name} not found — run "
              f"`python -m scrapers.scorecard {institution.key}` first.")
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["stars_version"] = STARS_VERSION
    print(f"[load] {path.name:24} {len(df):>3} rows")
    return df


def main():
    frames = [f for f in (load_one(i) for i in INSTITUTIONS.values())
              if not f.empty]
    if not frames:
        print("[stop] no input files found.")
        return

    df = pd.concat(frames, ignore_index=True)
    df["pillar"] = df["credit_code"].map(pillar_for)

    cols = ["institution", "stars_version", "pillar", "category",
            "category_code", "credit_code", "credit_name", "status",
            "score", "max"]
    df = df[[c for c in cols if c in df.columns]]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT, index=False)
    print(f"\n[save] {len(df)} rows -> {OUTPUT.name}")

    # ---------------- validation ----------------
    print("\n--- validation ---")
    print(f"  scores exceeding max (impossible): {len(df[df['score'] > df['max']])}")
    print(f"  duplicate institution+credit rows: "
          f"{df.duplicated(subset=['institution', 'credit_code']).sum()}")
    na = (df["status"].astype(str).str.strip() == "Not Applicable").sum()
    print(f"  'Not Applicable' credits (expected for TU Dublin investment): {na}")

    print("\n--- rows per institution ---")
    for inst, n in df["institution"].value_counts().items():
        print(f"  {inst:<34} {n}")

    print("\n--- pillar coverage (core E/S/G, scored credits only) ---")
    core = df[df["pillar"].isin(["Environmental", "Social", "Governance"])]
    pivot = (core.dropna(subset=["score"])
                 .pivot_table(index="institution", columns="pillar",
                              values="credit_code", aggfunc="count",
                              fill_value=0))
    print(pivot.to_string())

    print("\n--- Governance check (the pillar the university choice rests on) ---")
    gov = df[df["pillar"] == "Governance"]
    for inst in df["institution"].unique():
        g = gov[gov["institution"] == inst]
        print(f"  {inst:<34} {len(g.dropna(subset=['score']))}/{len(g)} "
              f"governance credits scored")


if __name__ == "__main__":
    main()
