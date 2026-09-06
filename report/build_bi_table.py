"""
Phase 6b — tidy tables for the BI layer
=======================================

`esg_master_dataset.csv` is the right shape for provenance and the wrong shape
for charting. It is 3,199 rows at mixed grain: a credit score repeats on every
one of its field rows, numeric measurements sit beside prose answers, and STARS
scoring internals look exactly like ESG metrics.

This emits three tidy tables, each at ONE grain, each independently checkable:

    bi_scores.csv    one row per (institution, credit)      — what STARS scored
    bi_metrics.csv   one row per (institution, credit, field) — the measurements
    bi_coverage.csv  one row per (institution, GRI disclosure) — what we can report

NO LLM, and no new numbers: every value is copied from the master dataset or
from the mapping. `tests/test_bi_table.py` re-derives all three from source
without reusing this file's logic.

TWO TRAPS THESE TABLES EXIST TO CLOSE
    1. **The 22x score overcount.** A credit's score repeats on every field row,
       so a naive SUM(score) over the master table gives 14,242 against a true
       638.15. bi_scores.csv filters on `credit_row_anchor` so the sum is right
       by construction and no dashboard author has to remember (§5).
    2. **Scoring internals masquerading as metrics.** Fields named "Points
       earned for indicator OP 6.1" are typed `number` and are STARS bookkeeping,
       not ESG data. They are excluded from bi_metrics.csv.

⚠️ THE COMPARABILITY WARNING, CARRIED IN THE DATA
    Absolute totals are NOT comparable across these three institutions. Berkeley
    withdraws 2,092,006 cubic metres of water; Cork withdraws 54,153. Berkeley
    is simply far larger. A chart of raw totals says "Berkeley is worst at
    everything", which is false and is the first thing a supervisor will
    challenge.

    `is_intensity` marks the metrics normalised per person or per unit of floor
    area — the only fair cross-institution comparison. `comparable` marks the
    metrics all three institutions actually report. Chart on those; treat
    everything else as single-institution detail.

RUN
    python -m report.build_bi_table
"""

from __future__ import annotations

import json
import sys

import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from scrapers.institutions import PROJECT_ROOT, INSTITUTIONS  # noqa: E402

MASTER = PROJECT_ROOT / "Combined_universities_data" / "esg_master_dataset.csv"
MAPPING = PROJECT_ROOT / "mapping" / "stars_gri_mapping.csv"
GRI_JSON = PROJECT_ROOT / "standards" / "gri_disclosures.json"
OUT_DIR = PROJECT_ROOT / "report" / "output"

# Relationships that mean "this STARS field answers the disclosure", as opposed
# to recording an absence. Mirrors build_content_index.USABLE plus partial,
# which is reported but flagged.
ANSWERS = {"equivalent", "component", "intensity", "partial"}
CITABLE = {"equivalent", "component", "intensity"}

INTENSITY_RE = r"per person|per unit of floor area|per capita"

# ⚠️ TWO FIGURES ARE FAITHFULLY EXTRACTED AND STILL CANNOT BE COMPARED AT FACE
# VALUE. Both are the institutions' own reporting decisions, verified against
# their own submissions — nothing here is an extraction error, and the values
# stay in the table unchanged. What they get is a note that travels with them
# into any export, because a chart that ignores them draws a false conclusion.
#
# Suppressing the rows instead would be its own dishonesty: a metric that
# vanishes with no explanation looks like missing data rather than a finding.
COGEN_GAP = (
    "Under-count. Berkeley's stationary fuel is ~25x too small to produce the "
    "stationary-combustion emissions it reports in OP-6, and no fuel burns at "
    "that intensity. Its OP-6 methodology names gas from the campus "
    "cogeneration plant as a scope 1 source, while OP-5 records zero on-site "
    "non-renewable electricity — the plant is in the emissions inventory and "
    "absent from the energy one. Not a performance result.")

BOUNDARY_GAP = (
    "Boundary. Cork's PRE-3 narrative excludes its subsidiaries by name — "
    "Campus Accommodation, the Mardyke Arena, the Student Centre, the IMI — "
    "and rented multi-tenant buildings. Berkeley's covers everything under its "
    "operational control, residences and grounds included. Students in Campus "
    "Accommodation still count in Cork's FTE denominator while their "
    "residential use sits outside the numerator, biasing its per-person "
    "figures downward.")


def data_quality_note(row) -> str:
    """A known reason this row's figure cannot be read at face value, or "".

    Keyed on what was actually verified, not on a guess about which metrics
    "look odd": Berkeley's OP-5 energy against its own OP-6 emissions, and
    Cork's per-person figures against its own declared boundary.
    """
    if row.institution_key == "berkeley" and row.credit_code == "OP-5":
        return COGEN_GAP
    if row.institution_key == "cork" and "per person" in str(row.field).lower():
        return BOUNDARY_GAP
    return ""


def key_for(name: str) -> str:
    for inst in INSTITUTIONS.values():
        if inst.name == name:
            return inst.key
    return ""


def build_scores(master: pd.DataFrame) -> pd.DataFrame:
    """One row per credit. Anchored, so SUM(score) is the real total."""
    anchored = master[master.credit_row_anchor == True].copy()   # noqa: E712
    out = anchored[["institution", "credit_code", "credit_name", "category",
                    "category_code", "pillar", "status", "score", "max"]].copy()
    out["institution_key"] = out.institution.map(key_for)
    out["score"] = pd.to_numeric(out.score, errors="coerce")
    out["max"] = pd.to_numeric(out["max"], errors="coerce")
    # Percentage of available points. Null rather than inf where max is 0 —
    # PRE credits are narrative and score nothing out of nothing.
    out["pct_of_max"] = (out.score / out["max"].replace(0, pd.NA) * 100).round(1)
    return out.sort_values(["institution", "credit_code"]).reset_index(drop=True)


def build_metrics(master: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """One row per numeric measurement, with its GRI target where it has one."""
    num = master[(master.value_type == "number")
                 & master.value_numeric.notna()
                 # STARS scoring bookkeeping, not an ESG measurement (§10).
                 & ~master.field.astype(str).str.startswith("Points earned")
                 ].copy()

    answers = mapping[(mapping.review_status == "confirmed")
                      & mapping.relationship.isin(ANSWERS)]
    # A field can serve several disclosures; keep the strongest link so the
    # table stays one-row-per-measurement rather than fanning out.
    rank = {r: i for i, r in enumerate(
        ["equivalent", "component", "intensity", "partial"])}
    answers = (answers.assign(_r=answers.relationship.map(rank))
               .sort_values("_r")
               .drop_duplicates(subset=["stars_credit", "stars_field"]))
    lookup = answers.set_index(["stars_credit", "stars_field"])[
        ["gri_standard", "gri_disclosure", "relationship"]]

    out = num[["institution", "credit_code", "credit_name", "category",
               "pillar", "indicator", "section", "field", "units",
               "value_numeric"]].copy()
    out["institution_key"] = out.institution.map(key_for)

    joined = out.join(lookup, on=["credit_code", "field"])
    joined["mapped_to_gri"] = joined.gri_disclosure.notna()
    joined["is_intensity"] = joined.field.astype(str).str.contains(
        INTENSITY_RE, case=False, regex=True)

    # `comparable` = every institution reports this metric, so a chart of it is
    # a fair comparison rather than an accident of who answered.
    counts = joined.groupby(["credit_code", "field"]).institution.nunique()
    joined["comparable"] = joined.set_index(
        ["credit_code", "field"]).index.map(counts).values == len(INSTITUTIONS)

    # `comparable` answers "did all three report it?" and is deliberately left
    # alone here — a figure can be reported by everyone and still not mean the
    # same thing in each submission. That second question gets its own column
    # rather than being folded into the first, so a consumer of the CSV cannot
    # mistake "all three answered" for "these three numbers are like for like".
    joined["data_quality"] = joined.apply(data_quality_note, axis=1)

    return joined.sort_values(
        ["institution", "credit_code", "field"]).reset_index(drop=True)


def build_coverage(master: pd.DataFrame, mapping: pd.DataFrame,
                   gri: dict) -> pd.DataFrame:
    """One row per (institution, disclosure): can this university report it?

    Deliberately re-derived here rather than parsed back out of the content
    index markdown — a table built by scraping a rendered document inherits
    every formatting decision that document made.
    """
    rows = []
    for standard, body in gri["standards"].items():
        for number, title in body["disclosures"].items():
            for_disc = mapping[
                mapping.gri_disclosure.astype(str).str.strip() == number]
            confirmed = for_disc[for_disc.review_status == "confirmed"]

            for inst in INSTITUTIONS.values():
                inst_rows = master[master.institution == inst.name]
                status, n_values = "Not assessed", 0

                if len(confirmed):
                    if (confirmed.relationship == "gap_gri_side").any():
                        status = "Not reported"
                    else:
                        usable = confirmed[confirmed.relationship.isin(ANSWERS)]
                        for r in usable.itertuples(index=False):
                            hit = inst_rows[
                                (inst_rows.credit_code == str(r.stars_credit).strip())
                                & (inst_rows.field == str(r.stars_field).strip())]
                            if len(hit) and pd.notna(hit.iloc[0].value) \
                                    and str(hit.iloc[0].value).strip():
                                n_values += 1
                        if n_values == 0:
                            status = "Not reported"
                        elif set(usable.relationship) <= {"partial"}:
                            status = "Partially reported"
                        else:
                            status = "Reported"
                elif len(for_disc):          # examined and rejected
                    status = "Not reported"

                rows.append({
                    "institution": inst.name, "institution_key": inst.key,
                    "gri_standard": standard, "gri_disclosure": number,
                    "gri_title": title, "status": status,
                    "values_available": n_values,
                    "citable": bool(len(confirmed)
                                    and confirmed.relationship.isin(CITABLE).any()
                                    and n_values > 0),
                })
    return pd.DataFrame(rows)


def main():
    for path in (MASTER, MAPPING, GRI_JSON):
        if not path.exists():
            sys.exit(f"[stop] missing {path}")

    master = pd.read_csv(MASTER)
    mapping = pd.read_csv(MAPPING)
    gri = json.loads(GRI_JSON.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    scores = build_scores(master)
    metrics = build_metrics(master, mapping)
    coverage = build_coverage(master, mapping, gri)

    for name, df in (("bi_scores", scores), ("bi_metrics", metrics),
                     ("bi_coverage", coverage)):
        path = OUT_DIR / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"[save] {len(df):5} rows -> {path.relative_to(PROJECT_ROOT)}")

    # The assertion that matters: the anchored sum must be the real total, not
    # the 22x overcount a naive aggregate of the master table produces.
    naive = pd.to_numeric(master.score, errors="coerce").sum()
    real = scores.score.sum()
    print(f"\n[check] anchored score sum {real:,.2f} "
          f"(naive sum over the master table: {naive:,.2f})")
    assert real < naive / 10, "anchoring failed — scores are being double counted"

    comparable = metrics[metrics.comparable]
    print(f"[check] {metrics.field.nunique()} distinct metrics, "
          f"{comparable.field.nunique()} reported by all three")
    print(f"[check] {metrics[metrics.is_intensity].field.nunique()} intensity "
          f"metrics — the only fair cross-institution comparison")
    print(f"[check] {metrics.mapped_to_gri.sum()} of {len(metrics)} metric rows "
          f"carry a GRI disclosure")

    flagged = metrics[metrics.data_quality.astype(str) != ""]
    print(f"[check] {len(flagged)} rows carry a data-quality note, "
          f"{len(flagged[flagged.is_intensity])} of them intensity metrics — "
          f"these are reported faithfully but are NOT like-for-like")


if __name__ == "__main__":
    main()
