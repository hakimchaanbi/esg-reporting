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

import hashlib
import json
import pathlib
import re
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from scrapers.institutions import INSTITUTIONS, PROJECT_ROOT  # noqa: E402

SOURCES = PROJECT_ROOT / "knowledge_sources"
SUMMARY = SOURCES / "_summary.csv"
MASTER = PROJECT_ROOT / "Combined_universities_data" / "esg_master_dataset.csv"
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


def chunk_knowledge() -> tuple[list[dict], list[tuple[str, str]]]:
    """Lane A — general ESG explainers. Teaches language, states no facts about
    our three universities."""
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
                "lane": "knowledge",
                "institution": "",          # by definition, not about any of ours
                "institution_key": "",
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

    return records, skipped


# ----------------------------------------------------------------------
# Lane C — what OUR universities actually said about themselves
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# REMOVED 2026-08-22 — the STARS narrative answers used to be chunked here.
#
# They were embedded so that Phase 5 could SEARCH for the prose answering a
# given GRI question. Phase 4's second pass (CLAUDE.md §16) then built the
# thing that search was approximating: a field-level index saying exactly which
# STARS field answers which disclosure. report/build_narrative.py:gather()
# reads those fields straight out of esg_master_dataset.csv.
#
# So the 1,049 prose chunks were a fuzzy route to material an exact lookup
# already had. Retrieval can return the wrong passage; a lookup keyed on
# (credit, field) cannot. Keeping both meant maintaining two paths to the same
# text, one of them strictly worse and unused.
#
# The `institution` LANE ITSELF STAYS — the evidence documents below live in
# it, they are institution-scoped, and they carry the same contamination risk
# that `LaneMisuse` exists to prevent. Only this source_type is gone.
#
# Recoverable from git history if the dashboard ever wants free-text search
# over the answers, which is a different job from grounding the report.
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# The institution lane — the evidence documents STARS answers link to
# ----------------------------------------------------------------------
MANIFEST = PROJECT_ROOT / "documents" / "manifest.csv"
DOC_TEXT = PROJECT_ROOT / "documents" / "text"

# Two filters, both deliberate — see the docstring below.
SPREADSHEET_EXT = {".xlsx", ".xlsm", ".xls"}
MAX_DOC_CHARS = 200_000


def chunk_documents() -> list[dict]:
    """Climate plans, policies, pay-gap reports — the evidence behind the answers.

    120 documents were downloaded and 109 yielded text, but only 81 are indexed.
    The two exclusions are the point:

    SPREADSHEETS ARE EXCLUDED (18 docs, 8.7M chars). A procurement ledger or a
    course inventory chunked into "12345 | Office Depot | 45.20" produces
    embeddings that mean nothing and match everything. They are data, not prose;
    the numbers they contain belong in the data layer. The extracted text stays
    on disk for reference.

    DOCUMENTS OVER 200k CHARS ARE EXCLUDED (10 docs, 8.9M chars). Not only for
    volume: one 300k document yields ~350 chunks by itself and drowns the
    corpus in a single voice. Checked individually, the excluded set is two
    Environmental Impact Reports for a building project, campus design
    standards, Ireland's national government review (not about UCC at all), and
    a duplicate. None is about a university's sustainability performance.

    Duplicates are dropped by content hash: the same document is sometimes
    linked from two credits under two URLs, and indexing it twice would give it
    double weight in every search.
    """
    if not MANIFEST.exists() or not DOC_TEXT.is_dir():
        print("[warn] no document manifest — skipping evidence documents. "
              "Run: python -m scrapers.fetch_documents && "
              "python -m scrapers.extract_documents")
        return []

    manifest = pd.read_csv(MANIFEST)
    ok = manifest[manifest.extract_status == "ok"].copy()
    by_name = {i.name: i for i in INSTITUTIONS.values()}

    records, seen_hashes = [], {}
    kept = skipped_sheet = skipped_big = skipped_dupe = 0

    for r in ok.itertuples(index=False):
        name = str(r.original_name)
        ext = "." + name.lower().rsplit(".", 1)[-1] if "." in name else ""

        if ext in SPREADSHEET_EXT:
            skipped_sheet += 1
            continue
        if r.text_chars > MAX_DOC_CHARS:
            skipped_big += 1
            continue

        path = DOC_TEXT / (str(r.local_file).rsplit(".", 1)[0] + ".txt")
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8", errors="replace")

        digest = hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()
        if digest in seen_hashes:
            skipped_dupe += 1
            continue
        seen_hashes[digest] = name

        institution = by_name.get(r.institution)
        if institution is None:
            continue

        kept += 1
        for i, text in enumerate(chunk_paragraphs(split_paragraphs(body))):
            records.append({
                "id": f"doc::{institution.key}::{str(r.local_file)[:12]}::{i:04d}",
                # The filename is prepended for the same reason the field name
                # is on STARS answers: a paragraph from "Climate-Action-Plan"
                # means more when you know which document it came from.
                "text": f"{name}\n{text}",
                "lane": "institution",
                "institution": institution.name,
                "institution_key": institution.key,
                "source": name[:80],
                "url": str(r.url),
                "source_type": "document",
                "language": "en",
                "has_quantity": bool(QUANTITY_RE.search(text)),
                "chunk_index": i,
                "chars": len(text),
                "words": len(text.split()),
                "scraper_flags": "",
                "credit_code": str(r.credit_code),
                "credit_name": "",
                "pillar": "",
                "section": "",
                "field": str(r.field)[:120],
            })

    print(f"[docs] {kept} indexed  "
          f"({skipped_sheet} spreadsheets, {skipped_big} oversized, "
          f"{skipped_dupe} duplicates excluded)")
    return records


def main():
    knowledge, skipped = chunk_knowledge()
    documents = chunk_documents()
    records = knowledge + documents

    # Lane A rows have no Lane C fields and vice versa; fill so every row in
    # chunks.jsonl has the same shape and the index builder stays simple.
    for r in records:
        for key in ("credit_code", "credit_name", "pillar", "section",
                    "field", "institution_key"):
            r.setdefault(key, "")

    with OUT.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[save] {len(records)} chunks -> {OUT.name}")
    print(f"       knowledge lane   (how to write)  {len(knowledge):5}")
    print(f"       institution lane (evidence docs) {len(documents):5}")

    if skipped:
        print(f"\n--- skipped {len(skipped)} document(s) ---")
        for name, why in skipped:
            print(f"  {name:26} {why}")

    print("\n--- lane A: chunks by source_type ---")
    by_type = {}
    for r in knowledge:
        by_type.setdefault(r["source_type"], []).append(r)
    for t, rs in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        note = "  <-- excluded by default" if t == "peer_report" else ""
        print(f"  {t:12} {len(rs):4} chunks{note}")

    fr = [r for r in knowledge if r["language"] != "en"]
    print(f"  {'french':12} {len(fr):4} chunks  <-- excluded by default")

    print("\n--- institution lane: chunks per institution ---")
    for inst in sorted({r["institution"] for r in documents}):
        rows = [r for r in documents if r["institution"] == inst]
        quant = sum(r["has_quantity"] for r in rows)
        print(f"  {inst[:34]:36} {len(rows):4} chunks  "
              f"{sum(r['chars'] for r in rows):>7,} chars  "
              f"{quant:3} with a figure")

    quantity = [r for r in records if r["has_quantity"]]
    print(f"\n--- chunks containing a figure: {len(quantity)} "
          f"(droppable via drop_quantities) ---")

    sizes = sorted(r["chars"] for r in records)
    print(f"\n--- chunk size (chars) ---")
    print(f"  min {sizes[0]}  median {sizes[len(sizes)//2]}  max {sizes[-1]}")
    print(f"  total {sum(sizes):,} chars across {len(records)} chunks")


if __name__ == "__main__":
    main()
