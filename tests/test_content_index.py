"""
Prove every figure in the GRI content index came from the dataset.

The index is the first thing in this project that will be shown to someone
outside it, so "trust the generator" is not good enough. This checks the
generated Markdown against esg_master_dataset.csv directly — it does not
re-use the generator's own logic, so a bug in build_content_index.py cannot
also silence the test.

Three claims, each tested:
  1. Every value the index prints exists in the master dataset, for THAT
     institution, under THAT STARS field.
  2. Every disclosure the index calls "Reported" has at least one real value.
  3. Every disclosure GRI defines appears exactly once per index — nothing
     silently dropped, nothing duplicated.

RUN
    python tests/test_content_index.py
"""

import json
import pathlib
import re
import sys

import pandas as pd

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "report" / "output"
MASTER = PROJECT_ROOT / "Combined_universities_data" / "esg_master_dataset.csv"
GRI_JSON = PROJECT_ROOT / "standards" / "gri_disclosures.json"
PROVENANCE = OUT_DIR / "index_provenance.csv"

failures = []


def check(name: str, passed: bool, detail: str = ""):
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")
    if not passed:
        failures.append(name)


def main():
    if not PROVENANCE.exists():
        sys.exit("[stop] run: python -m report.build_content_index")

    master = pd.read_csv(MASTER)
    prov = pd.read_csv(PROVENANCE)
    gri = json.loads(GRI_JSON.read_text(encoding="utf-8"))
    known = {n for s in gri["standards"].values() for n in s["disclosures"]}

    print("\n1. Every printed figure traces to the dataset\n")

    mismatched, checked = [], 0
    for r in prov[prov.populated == True].itertuples(index=False):   # noqa: E712
        row = master[(master.institution == r.institution)
                     & (master.credit_code == r.stars_credit)
                     & (master.field == r.stars_field)]
        checked += 1
        if row.empty:
            mismatched.append(f"{r.gri_disclosure}: no such field in dataset "
                              f"({r.stars_credit} / {r.stars_field})")
            continue
        if str(row.iloc[0].value).strip() != str(r.value).strip():
            mismatched.append(
                f"{r.gri_disclosure} {r.stars_field}: index says {r.value!r}, "
                f"dataset says {row.iloc[0].value!r}")

    check(f"{checked} figures match the dataset exactly",
          not mismatched,
          "\n         ".join(mismatched[:5]))

    print("\n2. The markdown prints nothing the provenance does not record\n")

    for md in sorted(OUT_DIR.glob("*_gri_index.md")):
        text = md.read_text(encoding="utf-8")
        key = md.stem.replace("_gri_index", "")
        inst_prov = prov[prov.institution.str.lower().str.contains(
            {"berkeley": "berkeley", "cork": "cork",
             "tudublin": "dublin"}[key])]
        recorded = {str(v).strip() for v in inst_prov[inst_prov.populated == True].value}  # noqa: E712

        # Every "**Field**: value units" cell the generator emitted
        printed = re.findall(r"\*\*[^*]+\*\*: ([^<|]+)", text)
        unrecorded = []
        for p in printed:
            p = p.strip()
            if p.startswith("not reported"):
                continue
            if p.endswith("…"):
                # A long prose answer, cut short by the generator. The printed
                # text is a PREFIX of the dataset value, so the containment
                # runs the other way round than it does for a short value.
                # Getting this backwards made the test pass for the numeric
                # mapping and fail the moment prose disclosures were mapped.
                stem = p[:-1].replace("\\|", "|")
                ok = any(v.startswith(stem) for v in recorded)
            else:
                # Short value: printed as "value units", so it starts with the
                # raw value.
                ok = any(p.replace("\\|", "|").startswith(v) for v in recorded)
            if not ok:
                unrecorded.append(p[:60])

        check(f"{md.name}: {len(printed)} printed values all recorded",
              not unrecorded,
              f"unrecorded: {unrecorded[:3]}")

    print("\n3. 'Reported' always means a real value exists in the dataset\n")

    # This check used to look for a `Reported` row with an empty detail cell.
    # build_content_index.py sets status = "Reported" only inside the branch
    # where `values` is non-empty, and detail is those same values joined — so
    # an empty Reported cell is structurally impossible and the regex could
    # never match. It tested the generator's control flow against itself.
    #
    # The claim worth testing is different and stronger: a disclosure marked
    # Reported must have a populated value FOR THAT INSTITUTION IN THE MASTER
    # DATASET. That is checked here against the mapping and the CSV, without
    # consulting the generator or its provenance output.
    key_to_name = {"berkeley": "berkeley", "cork": "cork", "tudublin": "dublin"}
    mapping = pd.read_csv(PROJECT_ROOT / "mapping" / "stars_gri_mapping.csv")
    usable = mapping[(mapping.review_status == "confirmed")
                     & (~mapping.relationship.isin(
                         ["gap_gri_side", "gap_stars_side", "partial"]))]

    def has_real_value(institution_name: str, disclosure: str) -> bool:
        rows = usable[usable.gri_disclosure.astype(str).str.strip() == disclosure]
        for r in rows.itertuples(index=False):
            hit = master[(master.institution == institution_name)
                         & (master.credit_code == str(r.stars_credit).strip())
                         & (master.field == str(r.stars_field).strip())]
            if len(hit) and pd.notna(hit.iloc[0].value) \
                    and str(hit.iloc[0].value).strip():
                return True
        return False

    reported_re = re.compile(r"^\| \*\*([\d-]+)\*\*[^|]*\| Reported \|",
                             re.MULTILINE)

    for md in sorted(OUT_DIR.glob("*_gri_index.md")):
        text = md.read_text(encoding="utf-8")
        fragment = key_to_name[md.stem.replace("_gri_index", "")]
        name = next(n for n in master.institution.unique()
                    if fragment in n.lower())

        claimed = reported_re.findall(text)
        hollow = [d for d in claimed if not has_real_value(name, d)]
        check(f"{md.name}: all {len(claimed)} 'Reported' rows have a real value",
              not hollow and len(claimed) > 15, f"hollow: {hollow[:5]}")

    # POSITIVE CONTROL — the detector must fire on a disclosure that is mapped
    # only to a gap, so "Reported" would be a lie.
    berkeley = next(n for n in master.institution.unique() if "Berkeley" in n)
    gap_only = mapping[mapping.relationship == "gap_gri_side"] \
        .gri_disclosure.astype(str).str.strip().iloc[0]
    check("the check would catch a fabricated 'Reported' row",
          not has_real_value(berkeley, gap_only),
          f"{gap_only} is a declared gap and must not read as having a value")

    print("\n4. Every GRI disclosure appears exactly once\n")

    for md in sorted(OUT_DIR.glob("*_gri_index.md")):
        text = md.read_text(encoding="utf-8")
        listed = re.findall(r"^\| \*\*([\d-]+)\*\*", text, re.MULTILINE)
        dupes = {d for d in listed if listed.count(d) > 1}
        missing = known - set(listed)
        check(f"{md.name}: all {len(known)} disclosures, no duplicates",
              not dupes and not missing,
              f"missing={sorted(missing)[:5]} dupes={sorted(dupes)[:5]}")

    print()
    if failures:
        sys.exit(f"{len(failures)} check(s) FAILED: {failures}")
    print("Content index verified: every figure traces to esg_master_dataset.csv.")


if __name__ == "__main__":
    main()
