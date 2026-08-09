"""
Phase 3 — Structure: combine the three universities into one dataset
====================================================================

Takes the three separate scorecard CSVs and produces ONE clean, unified table
that the rest of the pipeline reads from.

WHAT IT DOES
    1. Stacks berkeley + cork + tudublin into a single table.
    2. Adds a PILLAR column (Environmental / Social / Governance / Context)
       by mapping each STARS credit to its ESG pillar. This is the column that
       makes "compare E vs S vs G across universities" possible.
    3. Flags the STARS version of each report, so mixed-version comparisons
       can be handled honestly downstream.
    4. Validates the result and prints a summary you can eyeball.

WHY A PILLAR COLUMN
    STARS organises credits by its own categories (OP, PA, AC...). Those aren't
    ESG pillars. This step translates STARS' vocabulary into E/S/G — the first
    half of the framework mapping, and what the dashboard groups by.

PILLAR MAPPING (STARS 3.0)
    OP  (Operations)               -> Environmental
    PA-1..PA-5                      -> Governance   (coordination, planning,
                                                     governance, investment)
    PA-6..PA-13                    -> Social        (climate, representation,
                                                     wellbeing, pay equity...)
    AC / EN                        -> Context       (academics, engagement —
                                                     real ESG-relevant, but not
                                                     a corporate E/S/G pillar)
    IL  (Innovation & Leadership)  -> Bonus         (bonus points, capped)
    PRE (Report Preface)           -> Preface       (no score)

RUN
    python combine_universities.py

INPUT   berkeley_stars.csv, cork_stars.csv, tudublin_stars.csv
OUTPUT  combined_esg_dataset.csv
"""

import pathlib
import pandas as pd

# ----------------------------------------------------------------------
# CONFIG — the three inputs and the STARS version each report used
# ----------------------------------------------------------------------
INPUTS = [
    ("berkeley_stars.csv", "3.0"),
    ("cork_stars.csv",     "3.0"),
    ("tudublin_stars.csv", "3.0"),
]
OUTPUT = pathlib.Path("combined_esg_dataset.csv")

# Governance = the first five PA credits; Social = the rest of PA.
GOVERNANCE_PA = {"PA-1", "PA-2", "PA-3", "PA-4", "PA-5"}


def pillar_for(category_code: str, credit_code: str) -> str:
    """Map a STARS credit to its ESG pillar."""
    if category_code == "OP":
        return "Environmental"
    if category_code == "PA":
        return "Governance" if credit_code in GOVERNANCE_PA else "Social"
    if category_code in ("AC", "EN"):
        return "Context"
    if category_code == "IL":
        return "Bonus"
    if category_code == "PRE":
        return "Preface"
    return "Unknown"


# ----------------------------------------------------------------------
# load + combine
# ----------------------------------------------------------------------
def load_one(path: str, version: str) -> pd.DataFrame:
    p = pathlib.Path(path)
    if not p.exists():
        print(f"[skip] {path} not found — run its scraper first.")
        return pd.DataFrame()
    df = pd.read_csv(p)
    df["stars_version"] = version
    print(f"[load] {path:<22} {len(df):>3} rows")
    return df


def main():
    frames = [load_one(path, ver) for path, ver in INPUTS]
    frames = [f for f in frames if not f.empty]
    if not frames:
        print("[stop] no input files found.")
        return

    df = pd.concat(frames, ignore_index=True)

    # add the pillar column
    df["pillar"] = df.apply(
        lambda r: pillar_for(str(r["category_code"]), str(r["credit_code"])), axis=1
    )

    # tidy column order
    cols = ["institution", "stars_version", "pillar", "category", "category_code",
            "credit_code", "credit_name", "status", "score", "max"]
    df = df[[c for c in cols if c in df.columns]]

    df.to_csv(OUTPUT, index=False)
    print(f"\n[save] {len(df)} rows -> {OUTPUT}")

    # ---------------- validation + summary ----------------
    print("\n--- validation ---")
    bad = df[df["score"] > df["max"]]
    print(f"  scores exceeding max (impossible): {len(bad)}")
    dupes = df.duplicated(subset=["institution", "credit_code"]).sum()
    print(f"  duplicate institution+credit rows: {dupes}")
    na = (df["status"].astype(str).str.strip() == "Not Applicable").sum()
    print(f"  'Not Applicable' credits (expected for TU Dublin investment): {na}")

    print("\n--- rows per institution ---")
    for inst, n in df["institution"].value_counts().items():
        print(f"  {inst:<34} {n}")

    print("\n--- pillar coverage (core E/S/G, scored credits only) ---")
    core = df[df["pillar"].isin(["Environmental", "Social", "Governance"])]
    pivot = (core.dropna(subset=["score"])
                 .pivot_table(index="institution", columns="pillar",
                              values="credit_code", aggfunc="count", fill_value=0))
    print(pivot.to_string())

    print("\n--- Governance check (the pillar the whole university choice rests on) ---")
    gov = df[df["pillar"] == "Governance"]
    for inst in df["institution"].unique():
        g = gov[gov["institution"] == inst]
        scored = g.dropna(subset=["score"])
        print(f"  {inst:<34} {len(scored)}/{len(g)} governance credits scored")


if __name__ == "__main__":
    main()
