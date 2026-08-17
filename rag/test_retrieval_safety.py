"""
Prove the retrieval safety defaults actually hold.

retrieve.py claims another university's figures cannot reach a report by
accident, and that French cannot leak into an English deliverable. Those claims
are worth nothing untested — this is the test.

The adversarial case is real, not invented: knowledge_sources/toronto-annual-
report.txt contains "St. George campus has reduced carbon by over 26,000 tons".
A query about campus carbon reduction is exactly what a report-writing prompt
would ask, and that chunk is exactly what a naive index would return.

RUN
    python test_retrieval_safety.py         (from rag/)
"""

import sys

from retrieve import (LaneMisuse, check_query_scope, known_institutions,
                      retrieve)

BAIT = "campus carbon emissions reduction progress in tons"

failures = []


def check(name: str, passed: bool, detail: str = ""):
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")
    if not passed:
        failures.append(name)


def main():
    print("1. A query designed to surface Toronto's figure\n")

    default = retrieve(BAIT, k=8)
    peers = [h for h in default if h.source_type == "peer_report"]
    check("default retrieval returns no peer-institution chunks",
          not peers,
          f"got {len(default)} hits from: "
          f"{sorted({h.source for h in default})}")

    opted_in = retrieve(BAIT, k=8, exclude_peer_reports=False)
    peers_in = [h for h in opted_in if h.source_type == "peer_report"]
    check("the same query DOES reach them when explicitly opted in",
          bool(peers_in),
          f"{len(peers_in)} peer chunk(s): "
          f"{sorted({h.source for h in peers_in})}"
          if peers_in else
          "none returned — the bait query may no longer match; "
          "check the corpus rather than assuming the filter works")

    print("\n2. Language isolation\n")

    fr_bait = "notation extra-financiere des agences ESG"
    fr_default = retrieve(fr_bait, k=8)
    check("French source never appears under the English default",
          all(h.source != "greenscope-agencies" for h in fr_default),
          f"sources: {sorted({h.source for h in fr_default})}")

    fr_open = retrieve(fr_bait, k=8, language=None)
    check("French source is reachable when language filter is lifted",
          any(h.source == "greenscope-agencies" for h in fr_open),
          f"sources: {sorted({h.source for h in fr_open})}")

    print("\n3. Number suppression for figure-bearing sections\n")

    quant = retrieve("ESG assets under management growth", k=8)
    quant_dropped = retrieve("ESG assets under management growth", k=8,
                             drop_quantities=True)
    check("drop_quantities removes every chunk containing a figure",
          all(not h.has_quantity for h in quant_dropped),
          f"without flag: {sum(h.has_quantity for h in quant)} figure-bearing; "
          f"with flag: {sum(h.has_quantity for h in quant_dropped)}")

    print("\n4. Confident-looking answers to questions the corpus cannot answer\n")

    # Measured: this query scores 0.536 — above any sane weak-match threshold —
    # while every hit is generic GRI prose containing nothing about 305-1.
    # A similarity score cannot catch this, so a pattern check must.
    for q in ("What are the exact disclosure requirements of GRI 305-1?",
              "what does GRI 302 require",
              "explain disclosure 403-9"):
        check(f"flagged out of scope: {q[:44]!r}",
              check_query_scope(q) is not None)

    check("ordinary questions are NOT flagged",
          check_query_scope("how should we describe our emissions?") is None)

    print("\n5. Lane C — one university's prose cannot reach another's report\n")

    # Lane C is 1,049 chunks of institution-specific claims. Leaking Berkeley's
    # into Cork's section is the Toronto failure again, internally, at 20x the
    # volume. The filter is not a default that can be overridden — it is a
    # required argument.
    try:
        retrieve("what sustainability initiatives exist", lane="institution")
        check("searching lane C without an institution raises", False,
              "it returned results instead of refusing")
    except LaneMisuse:
        check("searching lane C without an institution raises", True)

    try:
        retrieve("anything", lane="institution", institution="Oxford")
        check("an unknown institution raises", False, "it was accepted")
    except LaneMisuse:
        check("an unknown institution raises", True)

    institutions = known_institutions()
    check("index knows exactly the three institutions", len(institutions) == 3,
          ", ".join(institutions))

    CAMPUS_Q = "campus sustainability strategy and climate commitments"
    for target in institutions:
        hits = retrieve(CAMPUS_Q, k=10, lane="institution", institution=target)
        others = {h.institution for h in hits} - {target}
        check(f"asking about {target[:30]} returns only its own prose",
              not others and bool(hits),
              f"{len(hits)} hits, foreign institutions: {others or 'none'}")

    print("\n6. The two lanes stay separate\n")

    knowledge_hits = retrieve(CAMPUS_Q, k=10)
    check("the default (knowledge) lane returns no institution prose",
          all(h.lane == "knowledge" for h in knowledge_hits),
          f"lanes returned: {sorted({h.lane for h in knowledge_hits})}")

    both = retrieve(CAMPUS_Q, k=12, lane="all",
                    institution=institutions[0])
    lanes = {h.lane for h in both}
    check("lane='all' can reach both, still scoped to one institution",
          lanes == {"knowledge", "institution"}
          and all(h.institution in ("", institutions[0]) for h in both),
          f"lanes: {sorted(lanes)}")

    print("\n7. Attribution is always available\n")

    hits = retrieve("what is double materiality", k=3)
    check("every hit carries a source and a URL",
          bool(hits) and all(h.source and h.url for h in hits),
          f"e.g. {hits[0].cite()}" if hits else "no hits")

    print()
    if failures:
        sys.exit(f"{len(failures)} safety check(s) FAILED: {failures}")
    print("All retrieval safety defaults hold. Another institution's figures "
          "cannot reach a report by accident.")


if __name__ == "__main__":
    main()
