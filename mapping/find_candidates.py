"""
Surface candidate STARS fields for every unmapped GRI disclosure.
=================================================================

The first mapping pass was numeric-biased: it went looking for tonnes and
megawatt-hours, so GRI 302/303/305/306 came out well covered and GRI 2 —
the mandatory General Disclosures, which are almost entirely prose questions —
was skipped wholesale. 46 of 67 disclosures ended up "Not assessed", several of
them for questions the universities had in fact answered.

This closes that gap by embedding each GRI disclosure's VERBATIM requirement
text and each distinct STARS field (name plus a real sample answer) with the
same MiniLM model the RAG layer uses, then ranking fields by cosine similarity.

WHAT THIS IS AND IS NOT
    It is a search tool. It proposes nothing and writes nothing to the mapping
    table — it prints candidates for a human to judge against the requirement
    text, exactly like the --review screen. Semantic similarity is a way of
    not having to read 985 field names 46 times; it is not evidence that a
    field answers a disclosure (CLAUDE.md §13: a score means "closest", never
    "correct").

RUN
    python -m mapping.find_candidates              unmapped disclosures only
    python -m mapping.find_candidates --all        every disclosure
    python -m mapping.find_candidates 2-9 2-23     specific ones
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "rag"))

from embed import MiniLMEmbedder  # noqa: E402

MASTER = ROOT / "Combined_universities_data" / "esg_master_dataset.csv"
MAPPING = ROOT / "mapping" / "stars_gri_mapping.csv"
GRI_JSON = ROOT / "standards" / "gri_disclosures.json"
REQUIREMENTS = ROOT / "standards" / "gri_requirements.json"

TOP_K = 6
MIN_SCORE = 0.30


def field_corpus(master: pd.DataFrame) -> pd.DataFrame:
    """One row per distinct (credit, field), with a real sample answer.

    The sample matters: "Notes about the information provided for this credit"
    tells you nothing, but its answer does.
    """
    rows = []
    for (credit, field), g in master[master.has_detail].groupby(
            ["credit_code", "field"], sort=False):
        populated = g[g.value.notna() & (g.value.astype(str).str.strip() != "")]
        if populated.empty:
            continue
        sample = str(populated.iloc[0].value)
        rows.append({
            "credit_code": credit,
            "field": str(field),
            "credit_name": str(populated.iloc[0].credit_name),
            "pillar": str(populated.iloc[0].pillar),
            "value_type": str(populated.iloc[0].value_type),
            "n_institutions": int(populated.institution.nunique()),
            "sample": sample[:200],
            "embed_text": f"{populated.iloc[0].credit_name}. {field}. {sample[:300]}",
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("disclosures", nargs="*", help="specific disclosure numbers")
    ap.add_argument("--all", action="store_true",
                    help="include disclosures that already have a mapping")
    ap.add_argument("-k", type=int, default=TOP_K)
    args = ap.parse_args()

    gri = json.loads(GRI_JSON.read_text(encoding="utf-8"))
    reqs = (json.loads(REQUIREMENTS.read_text(encoding="utf-8"))["requirements"]
            if REQUIREMENTS.exists() else {})
    mapping = pd.read_csv(MAPPING)
    master = pd.read_csv(MASTER)

    mapped = set(mapping.gri_disclosure.dropna().astype(str).str.strip())

    targets = []
    for standard, body in gri["standards"].items():
        for number, title in body["disclosures"].items():
            if args.disclosures and number not in args.disclosures:
                continue
            if not args.disclosures and not args.all and number in mapped:
                continue
            targets.append((standard, number, title))

    if not targets:
        print("nothing to do")
        return

    fields = field_corpus(master)
    print(f"[load] {len(fields)} distinct populated STARS fields")
    print(f"[load] {len(targets)} disclosure(s) to search\n")

    embedder = MiniLMEmbedder()
    field_vecs = embedder.encode(fields.embed_text.tolist())

    # The requirement text is what the field must actually satisfy; fall back to
    # the title only when the verbatim text was not extracted.
    queries = []
    for standard, number, title in targets:
        req = reqs.get(number, {}).get("text", "")
        queries.append(f"{title}. {req[:600]}" if req else title)
    query_vecs = embedder.encode(queries)

    for (standard, number, title), qv in zip(targets, query_vecs):
        scores = field_vecs @ qv
        order = np.argsort(-scores)[:args.k]
        print("=" * 96)
        print(f"{standard}  {number}  {title}")
        req = reqs.get(number, {}).get("text", "")
        if req:
            first = req.split("\n")[1] if "\n" in req else req
            print(f"   requires: {first[:88]}")
        print()
        shown = 0
        for i in order:
            if scores[i] < MIN_SCORE:
                continue
            f = fields.iloc[i]
            print(f"   {scores[i]:.3f}  {f.credit_code:6} [{f.value_type:12}] "
                  f"{f.n_institutions}/3  {f.field[:64]}")
            print(f"           e.g. {f['sample'][:96]}")
            shown += 1
        if not shown:
            print("   (nothing above threshold — likely a genuine gap)")
        print()


if __name__ == "__main__":
    main()
