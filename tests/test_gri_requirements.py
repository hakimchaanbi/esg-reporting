"""
Prove the stored GRI requirement text is VERBATIM, not paraphrased.

CLAUDE.md §3 forbids an LLM-authored mapping table, and the same logic applies
to the standard text the mapping is checked against. If a model had quietly
summarised "what 305-1 requires", every downstream check would be built on a
plausible invention.

standards/fetch_gri.py claims it copies GRI's own words with BeautifulSoup and
changes nothing but whitespace. This asserts that claim against the cached
source pages, line by line.

Comparison is done on letters and digits only, so the check survives whitespace
and punctuation handling but would still fail on any reworded sentence.

RUN
    python tests/test_gri_requirements.py
"""

import json
import pathlib
import re
import sys

from bs4 import BeautifulSoup

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
REQUIREMENTS = PROJECT_ROOT / "standards" / "gri_requirements.json"
DISCLOSURES = PROJECT_ROOT / "standards" / "gri_disclosures.json"

MIN_LINE = 40           # ignore fragments too short to prove anything
squash = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())

failures = []


def check(name: str, passed: bool, detail: str = ""):
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")
    if not passed:
        failures.append(name)


def source_text(cached: pathlib.Path) -> str:
    soup = BeautifulSoup(cached.read_text(encoding="utf-8", errors="replace"),
                         "lxml")
    for t in soup(["script", "style"]):
        t.decompose()
    return squash(soup.get_text(" "))


def main():
    if not REQUIREMENTS.exists():
        sys.exit(f"[stop] {REQUIREMENTS.name} not found — run "
                 f"python standards/fetch_gri.py")

    data = json.loads(REQUIREMENTS.read_text(encoding="utf-8"))
    reqs = data["requirements"]
    disclosures = json.loads(DISCLOSURES.read_text(encoding="utf-8"))

    print(f"\n1. Every stored line appears verbatim in the cached source\n")

    cache: dict[str, str] = {}
    checked_lines = paraphrased = 0
    offenders = []

    for num, rec in sorted(reqs.items()):
        src_path = PROJECT_ROOT / rec["cached_source"]
        if not src_path.exists():
            offenders.append(f"{num}: cached source missing")
            continue
        if rec["cached_source"] not in cache:
            cache[rec["cached_source"]] = source_text(src_path)
        haystack = cache[rec["cached_source"]]

        for line in rec["text"].split("\n"):
            if len(line) < MIN_LINE:
                continue
            checked_lines += 1
            if squash(line) not in haystack:
                paraphrased += 1
                if len(offenders) < 5:
                    offenders.append(f"{num}: {line[:90]}")

    check(f"{checked_lines} substantial lines all found in source",
          paraphrased == 0,
          f"{paraphrased} not found" + ("\n         " + "\n         ".join(offenders)
                                        if offenders else ""))

    print("\n2. Titles agree with the committed vocabulary\n")

    known = {n: t for b in disclosures["standards"].values()
             for n, t in b["disclosures"].items()}
    mismatched = [n for n, r in reqs.items()
                  if n in known and squash(known[n]) != squash(r["title"])]
    check("no title disagrees with gri_disclosures.json",
          not mismatched, f"mismatched: {mismatched}")

    print("\n3. Coverage of what the mapping actually cites\n")

    mapping = PROJECT_ROOT / "mapping" / "stars_gri_mapping.csv"
    if mapping.exists():
        import csv
        cited = set()
        with mapping.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = (row.get("gri_disclosure") or "").strip()
                if d:
                    cited.add(d)
        uncovered = sorted(d for d in cited if d not in reqs)
        check(f"all {len(cited)} disclosures cited by the mapping have text",
              not uncovered, f"missing: {uncovered}")

    print("\n4. Normative language survived extraction\n")

    shall = sum("shall report" in r["text"].lower() for r in reqs.values())
    check("most disclosures carry a 'shall report' clause",
          shall >= len(reqs) * 0.5,
          f"{shall} of {len(reqs)}")

    print()
    if failures:
        sys.exit(f"{len(failures)} check(s) FAILED: {failures}")
    print(f"All {len(reqs)} GRI requirement texts verified verbatim against "
          f"their cached sources.")


if __name__ == "__main__":
    main()
