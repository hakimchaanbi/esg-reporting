"""
Phase 5a — turn the knowledge corpus into retrievable, labelled chunks
======================================================================

WHAT THIS IS FOR
    Branch A (knowledge) teaches the LLM the LANGUAGE of ESG reporting -- what
    "double materiality" means, how a GRI disclosure is phrased, what tone a
    sustainability report takes. It is NOT a source of facts about Berkeley,
    Cork or TU Dublin. Those come from esg_master_dataset.csv and are injected
    by code, never written by the model (CLAUDE.md §3).

    Keeping that separation is the whole point of the labelling below.

THE CONTAMINATION RISK -- WHY EVERY CHUNK IS TAGGED
    Two of the 19 sources are OTHER UNIVERSITIES' OWN SUSTAINABILITY REPORTS
    (Toronto, Manchester). They are useful as writing-style examples, and
    genuinely dangerous as retrieval results. The Toronto file contains:

        "St. George campus has reduced carbon by over 26,000 tons"

    If that chunk is retrieved while writing the Berkeley report, the model may
    weave Toronto's figure into Berkeley's narrative. It would read perfectly
    naturally and be completely false.

    Measured across the corpus: only 8 quantity-mentions in 21,702 words, so the
    risk is narrow -- but it concentrates exactly where it does most damage.

    Defences, in order of strength:
      1. source_type = "peer_report" on those two files. retrieve() EXCLUDES
         peer reports by default; asking for them is a deliberate opt-in.
      2. has_quantity = True on any chunk containing a number with a unit or
         percent sign, so a caller can drop them regardless of source.
      3. language tagging -- one source is French and CLAUDE.md requires
         English-only deliverables. retrieve() filters to English by default.

WHAT THIS FILE DOES
    Reads knowledge_sources/*.txt, strips the 4-line scraper header into
    metadata, splits the body into overlapping paragraph-aware chunks, labels
    each chunk, and writes rag/chunks.jsonl. It does NOT embed -- build_index.py
    does that. Splitting the two means you can inspect and fix the chunking
    without paying for re-embedding.

RUN
    python chunk_corpus.py          (from rag/)
"""

import json
import pathlib
import re

SOURCES = pathlib.Path(__file__).parent.parent / "knowledge_sources"
SUMMARY = SOURCES / "_summary.csv"
OUT = pathlib.Path(__file__).parent / "chunks.jsonl"

# Aim for chunks big enough to carry a whole idea, small enough that a retrieval
# hit is mostly signal. These documents are short explainers, so ~1000 chars
# (roughly a long paragraph or two) keeps definitions intact.
TARGET_CHARS = 1000
OVERLAP_CHARS = 200
MIN_CHUNK_CHARS = 120      # below this a chunk is a fragment, not an idea
MIN_DOC_WORDS = 100        # below this the scrape effectively failed

# A curation decision, like the E/S/G pillar mapping in §8 -- not something the
# sources declare about themselves. Kept in one dict so it is easy to revise.
#
#   peer_report  another institution's OWN report. Style reference only;
#                excluded from retrieval by default. CONTAMINATION RISK.
#   framework    explains a reporting framework (GRI, CSRD, SASB, TCFD...)
#   definition   defines ESG / sustainability terms
#   rating       how ESG rating agencies work
#   stars        AASHE STARS itself -- the scheme our data comes from
#   context      background, neither definition nor framework
SOURCE_TYPES = {
    "toronto-annual-report": "peer_report",
    "manchester-sustain": "peer_report",
    "ibm-gri": "framework",
    "ibm-csrd": "framework",
    "ibm-sasb": "framework",
    "ibm-esg-frameworks": "framework",
    "ibm-esg-reporting": "framework",
    "gri-standards": "framework",
    "cambridge-esg": "definition",
    "cfi-esg": "definition",
    "ibm-esg": "definition",
    "robeco-esg-definition": "definition",
    "robeco-sustainability": "definition",
    "ibm-esg-history": "context",
    "worldbank-framework": "context",
    "msci-esg-ratings": "rating",
    "greenscope-agencies": "rating",
    "stars-about": "stars",
    "stars-technical-manual": "stars",
}

# A number carrying a unit or a percent sign -- i.e. a claim, not a year or a
# list index. Deliberately narrow: "2024" should not trip this, "26,000 tons"
# must.
QUANTITY_RE = re.compile(
    r"\b\d[\d,\.]*\s*(?:%|percent|tonnes?|tons?|kWh|MWh|GWh|"
    r"million|billion|USD|EUR|\$|€)\b",
    re.IGNORECASE,
)

HEADER_SEP = "=" * 60


def read_summary_flags() -> dict:
    """The scraper's own QA flags (FRENCH / THIN / EMPTY / SALES-PAGE).

    Trusted over re-detection: a human checked these when the corpus was built
    (CLAUDE.md §7).
    """
    flags = {}
    if not SUMMARY.exists():
        return flags
    import csv
    with SUMMARY.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            flags[row["source"]] = (row.get("flags") or "").strip()
    return flags


def parse_document(path: pathlib.Path) -> tuple[dict, str]:
    """Split the 4-line scraper header off the body and return (meta, body)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    head, _, body = raw.partition(HEADER_SEP)

    meta = {"source": path.stem, "url": ""}
    for line in head.splitlines():
        if line.startswith("SOURCE:"):
            meta["source"] = line.split(":", 1)[1].strip()
        elif line.startswith("URL:"):
            meta["url"] = line.split(":", 1)[1].strip()

    return meta, body.strip()


def split_paragraphs(body: str) -> list[str]:
    """trafilatura emits one paragraph per line; treat blank lines as breaks."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", body)]
    return [p for p in paras if p]


def chunk_paragraphs(paras: list[str]) -> list[str]:
    """Greedily pack paragraphs to TARGET_CHARS, then overlap by OVERLAP_CHARS.

    Paragraph-aware rather than fixed-width so a chunk rarely starts or ends
    mid-sentence -- retrieval quality depends on chunks being readable alone.
    A single paragraph longer than the target is split on sentence boundaries.
    """
    chunks, current = [], ""

    def flush():
        nonlocal current
        if len(current.strip()) >= MIN_CHUNK_CHARS:
            chunks.append(current.strip())
        current = ""

    for para in paras:
        if len(para) > TARGET_CHARS:
            flush()
            for sentence in re.split(r"(?<=[.!?])\s+", para):
                if len(current) + len(sentence) + 1 > TARGET_CHARS and current:
                    flush()
                current = f"{current} {sentence}".strip()
            flush()
            continue

        if len(current) + len(para) + 1 > TARGET_CHARS and current:
            tail = current[-OVERLAP_CHARS:] if OVERLAP_CHARS else ""
            flush()
            # Carry the tail forward so an idea spanning a chunk boundary is
            # still findable from either side.
            current = tail.strip()

        current = f"{current}\n{para}".strip()

    flush()
    return chunks


def main():
    flags = read_summary_flags()
    records, skipped = [], []

    for path in sorted(SOURCES.glob("*.txt")):
        meta, body = parse_document(path)
        source = meta["source"]
        words = len(body.split())

        if words < MIN_DOC_WORDS:
            skipped.append((source, f"only {words} words — scrape failed"))
            continue

        source_flags = flags.get(source, "")
        language = "fr" if "FRENCH" in source_flags else "en"
        source_type = SOURCE_TYPES.get(source, "context")

        for i, text in enumerate(chunk_paragraphs(split_paragraphs(body))):
            records.append({
                "id": f"{source}::{i:03d}",
                "text": text,
                "source": source,
                "url": meta["url"],
                "source_type": source_type,
                "language": language,
                "has_quantity": bool(QUANTITY_RE.search(text)),
                "chunk_index": i,
                "chars": len(text),
                "words": len(text.split()),
                "scraper_flags": source_flags,
            })

    with OUT.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---------------- summary ----------------
    print(f"[save] {len(records)} chunks -> {OUT}")

    if skipped:
        print(f"\n--- skipped {len(skipped)} document(s) ---")
        for name, why in skipped:
            print(f"  {name:26} {why}")

    by_type = {}
    for r in records:
        by_type.setdefault(r["source_type"], []).append(r)
    print("\n--- chunks by source_type ---")
    for t, rs in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        note = "  <-- excluded from retrieval by default" if t == "peer_report" else ""
        print(f"  {t:12} {len(rs):4} chunks{note}")

    quantity = [r for r in records if r["has_quantity"]]
    print(f"\n--- chunks containing a quantity: {len(quantity)} ---")
    for r in quantity:
        snippet = QUANTITY_RE.search(r["text"])
        print(f"  {r['id']:34} [{r['source_type']:11}] ...{snippet.group(0)}")

    fr = [r for r in records if r["language"] != "en"]
    print(f"\n--- non-English chunks: {len(fr)} "
          f"(filtered out by default; CLAUDE.md requires English deliverables) ---")
    for r in fr[:3]:
        print(f"  {r['id']}")
    if len(fr) > 3:
        print(f"  ... and {len(fr) - 3} more")

    sizes = sorted(r["chars"] for r in records)
    print(f"\n--- chunk size (chars) ---")
    print(f"  min {sizes[0]}  median {sizes[len(sizes)//2]}  max {sizes[-1]}")
    print(f"  total {sum(sizes):,} chars across {len(records)} chunks")


if __name__ == "__main__":
    main()
