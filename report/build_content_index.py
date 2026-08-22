"""
Phase 6a — the GRI content index
================================

A GRI report is two things: the narrative, and the content index. The index is
the table that makes it *a GRI report* rather than a sustainability document —
one row per disclosure, saying where the answer is or why there isn't one.

NO LLM IS INVOLVED HERE, BY DESIGN.
    Every row is derived mechanically from three files you can open and read:

        standards/gri_disclosures.json   the questions GRI asks
        mapping/stars_gri_mapping.csv    which STARS field answers which
        esg_master_dataset.csv           the values themselves

    That means the index is checkable line by line. Every figure it prints is
    also written to the provenance CSV alongside the exact STARS credit and
    field it came from, so any number can be traced back to a row of the
    dataset without trusting this script.

FOUR STATUSES, ALL STANDARD IN REAL GRI INDEXES
    Reported            a confirmed equivalent / component / intensity mapping
                        with at least one populated value
    Partially reported  a confirmed `partial` mapping — overlaps the disclosure
                        without satisfying it; the caveat is printed with it
    Not reported        a confirmed gap_gri_side row — GRI asks, STARS does not
                        collect it. The reason is stated, not left as a dash
    Not assessed        no mapping row exists for this disclosure

RUN
    python -m report.build_content_index
    python -m report.build_content_index cork
"""

from __future__ import annotations

import argparse
import json
import re
import sys

import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from scrapers.institutions import PROJECT_ROOT, resolve  # noqa: E402

GRI_JSON = PROJECT_ROOT / "standards" / "gri_disclosures.json"
MAPPING = PROJECT_ROOT / "mapping" / "stars_gri_mapping.csv"
MASTER = PROJECT_ROOT / "Combined_universities_data" / "esg_master_dataset.csv"
OUT_DIR = PROJECT_ROOT / "report" / "output"

USABLE = {"equivalent", "component", "intensity"}


def disclosure_sort_key(number: str):
    """'305-1' sorts before '305-10'; '2-9' before '202-1'."""
    std, _, item = number.partition("-")
    try:
        return (int(std), int(item))
    except ValueError:
        return (9999, 0)


TRUNCATE_AT = 87


def cell_safe(text: str) -> str:
    """A pipe inside a value would end the table cell and shift every column.

    The credit parser collapses whitespace, so newlines cannot reach here, but
    nothing stops an institution writing a pipe in its prose — and since the
    second mapping pass, most mapped values ARE prose.
    """
    return text.replace("|", "\\|")


def merge_caveats(caveats: list[str]) -> str:
    """Join several rows' caveats without repeating the shared parts.

    Deduplicating whole caveat strings is not enough once a disclosure has
    several mapped fields. GRI 405-1 draws on six STARS fields whose caveats
    share three clauses — no age data, 405-1-a unanswered, TU Dublin's index
    unparseable — but combine them differently, so no two strings are equal and
    every shared clause printed two or three times. The note cell ran to a
    paragraph of repeats.

    So dedupe at sentence granularity instead, preserving order. Splitting after
    a full stop is crude — "Nov. 24, 2025" splits into two fragments — but the
    fragments are rejoined with a space in their original order, so the text is
    reconstructed exactly; only fragments that genuinely repeat are dropped.
    """
    seen, out = set(), []
    for fragment in (f.strip() for c in caveats
                     for f in re.split(r"(?<=\.)\s+", c.strip()) if f.strip()):
        if fragment not in seen:
            seen.add(fragment)
            out.append(fragment)
    return " ".join(out)


def format_value(row) -> str:
    """One STARS value, with its units, ready for a table cell."""
    if pd.isna(row.value) or str(row.value).strip() == "":
        return "not reported by the institution"
    value = str(row.value).strip()
    if len(value) > TRUNCATE_AT + 3:
        return cell_safe(value[:TRUNCATE_AT]) + "…"
    units = str(row.units).strip() if pd.notna(row.units) else ""
    return cell_safe(f"{value} {units}".strip())


def build(institution, gri, mapping, master):
    """One row per GRI disclosure, for one institution."""
    inst_data = master[master.institution == institution.name]
    rows, provenance = [], []

    for standard, body in gri["standards"].items():
        for number, title in sorted(body["disclosures"].items(),
                                    key=lambda kv: disclosure_sort_key(kv[0])):
            for_disclosure = mapping[
                mapping.gri_disclosure.astype(str).str.strip() == number]
            hits = for_disclosure[for_disclosure.review_status == "confirmed"]

            if hits.empty:
                # A rejected row is not an absence of work — it is a candidate
                # mapping that was examined and found not to answer the
                # disclosure. Reporting that as "Not assessed" would hide the
                # review and understate what the project actually knows.
                turned_down = for_disclosure[
                    for_disclosure.review_status == "rejected"]
                if len(turned_down):
                    t = turned_down.iloc[0]
                    rows.append({
                        "standard": standard, "disclosure": number,
                        "title": title, "status": "Not reported",
                        "detail": "Assessed: the nearest STARS field "
                                  f"({t.stars_credit} / {t.stars_field}) was "
                                  "reviewed and rejected as an answer to this "
                                  "disclosure.",
                        "note": str(t.caveat) if pd.notna(t.caveat) else "",
                    })
                    continue
                rows.append({
                    "standard": standard, "disclosure": number, "title": title,
                    "status": "Not assessed", "detail": "", "note": "",
                })
                continue

            gaps = hits[hits.relationship == "gap_gri_side"]
            if len(gaps):
                g = gaps.iloc[0]
                rows.append({
                    "standard": standard, "disclosure": number, "title": title,
                    "status": "Not reported",
                    "detail": "No STARS data exists for this disclosure.",
                    "note": str(g.caveat) if pd.notna(g.caveat) else "",
                })
                continue

            # Gather every STARS field mapped to this disclosure that this
            # institution actually populated.
            values, missing, caveats = [], [], []
            for r in hits.itertuples(index=False):
                field = str(r.stars_field).strip()
                credit = str(r.stars_credit).strip()
                match = inst_data[(inst_data.credit_code == credit)
                                  & (inst_data.field == field)]
                if pd.notna(r.caveat) and str(r.caveat).strip():
                    caveats.append(str(r.caveat).strip())
                if match.empty:
                    missing.append(f"{credit} / {field}")
                    continue
                v = match.iloc[0]
                populated = pd.notna(v.value) and str(v.value).strip() != ""
                if populated:
                    values.append(f"**{field}**: {format_value(v)}")
                else:
                    missing.append(f"{credit} / {field}")
                provenance.append({
                    "institution": institution.name,
                    "gri_disclosure": number,
                    "gri_title": title,
                    "relationship": r.relationship,
                    "stars_credit": credit,
                    "stars_field": field,
                    "value": v.value if populated else "",
                    "units": v.units if populated and pd.notna(v.units) else "",
                    "populated": populated,
                })

            only_partial = set(hits.relationship) <= {"partial"}
            if not values:
                status = "Not reported"
                detail = ("Mapped to STARS, but this institution left every "
                          "mapped field blank.")
            elif only_partial:
                status = "Partially reported"
                detail = "<br>".join(values)
            else:
                status = "Reported"
                detail = "<br>".join(values)

            note = merge_caveats(caveats)
            if missing and values:
                note = (note + " ").strip() + (
                    f"Not populated by this institution: {'; '.join(missing[:3])}.")

            rows.append({"standard": standard, "disclosure": number,
                         "title": title, "status": status,
                         "detail": detail, "note": note.strip()})

    return pd.DataFrame(rows), pd.DataFrame(provenance)


def to_markdown(institution, index: pd.DataFrame, gri) -> str:
    counts = index.status.value_counts()
    reported = int(counts.get("Reported", 0))
    partial = int(counts.get("Partially reported", 0))
    not_reported = int(counts.get("Not reported", 0))
    not_assessed = int(counts.get("Not assessed", 0))

    lines = [
        f"# GRI content index — {institution.name}",
        "",
        "Prepared **with reference to** the GRI Standards. Source data: "
        f"[{institution.name} STARS Report]({institution.report_url}), "
        "AASHE, retrieved 2026-08. STARS data is used with attribution to AASHE.",
        "",
        f"| Reported | Partially reported | Not reported | Not assessed |",
        f"|---|---|---|---|",
        f"| {reported} | {partial} | {not_reported} | {not_assessed} |",
        "",
        "> **“With reference to”, not “in accordance with.”** GRI reserves "
        "*in accordance* for reports answering every Universal Disclosure "
        "(GRI 2) plus all disclosures for each material topic. This report "
        "does not, so it uses the weaker and correct claim.",
        "",
    ]

    for standard, body in gri["standards"].items():
        block = index[index.standard == standard]
        if block.empty:
            continue
        lines += [f"## {standard}: {body['title']}", "",
                  "| Disclosure | Status | Value / reason | Notes |",
                  "|---|---|---|---|"]
        for r in block.itertuples(index=False):
            detail = r.detail or "—"
            note = r.note or ""
            lines.append(
                f"| **{r.disclosure}** {r.title} | {r.status} | {detail} | {note} |")
        lines.append("")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("institutions", nargs="*")
    args = ap.parse_args()

    for path in (GRI_JSON, MAPPING, MASTER):
        if not path.exists():
            sys.exit(f"[stop] missing {path}")

    gri = json.loads(GRI_JSON.read_text(encoding="utf-8"))
    mapping = pd.read_csv(MAPPING)
    master = pd.read_csv(MASTER)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_prov = []
    for institution in resolve(args.institutions):
        index, provenance = build(institution, gri, mapping, master)
        all_prov.append(provenance)

        md_path = OUT_DIR / f"{institution.key}_gri_index.md"
        md_path.write_text(to_markdown(institution, index, gri), encoding="utf-8")

        c = index.status.value_counts()
        print(f"[ok] {institution.name}")
        print(f"     reported {int(c.get('Reported', 0)):2} · "
              f"partial {int(c.get('Partially reported', 0)):2} · "
              f"not reported {int(c.get('Not reported', 0)):2} · "
              f"not assessed {int(c.get('Not assessed', 0)):2}")
        print(f"     -> {md_path.relative_to(PROJECT_ROOT)}")

    prov = pd.concat(all_prov, ignore_index=True)
    prov_path = OUT_DIR / "index_provenance.csv"
    prov.to_csv(prov_path, index=False)
    print(f"\n[save] {len(prov)} traceable value rows -> "
          f"{prov_path.relative_to(PROJECT_ROOT)}")
    print("       every figure in every index, with the STARS credit and field "
          "it came from")


if __name__ == "__main__":
    main()
