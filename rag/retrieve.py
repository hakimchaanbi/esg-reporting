"""
Phase 5a — the retrieval API Phase 5 calls
==========================================

This is the ONLY way generation code should read the knowledge corpus. It is a
thin layer over a numpy dot product whose real job is to make the UNSAFE query
the awkward one to write.

THE SAFETY DEFAULTS
    exclude_peer_reports = True   Toronto's and Manchester's own reports are
                                  style references, not facts about OUR three
                                  universities. One Toronto chunk literally
                                  says "reduced carbon by over 26,000 tons".
                                  That sentence landing in a Berkeley report
                                  would be a serious factual error that reads
                                  perfectly naturally.

    language = "en"               CLAUDE.md: deliverables must be English and
                                  French must not leak. One source is French.

    drop_quantities = False       Off by default: most figures in the corpus
                                  are harmless context ("$639 billion in ESG
                                  assets"). Turn it ON when generating a
                                  section that states numbers, so no figure can
                                  arrive from prose at all. Numbers belong to
                                  esg_master_dataset.csv and Jinja2 (CLAUDE.md
                                  §3), never to the model.

    Every hit carries its source and URL, so generated text can be attributed
    and any claim traced back.

USE
    from retrieve import retrieve
    for hit in retrieve("how should scope 2 emissions be reported?", k=4):
        print(hit.source, hit.score, hit.text)

CLI
    python retrieve.py "double materiality"
    python retrieve.py "campus carbon reduction" --include-peer-reports
    python retrieve.py "how to describe emissions" --drop-quantities
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import warnings
from dataclasses import dataclass

import numpy as np

from embed import MiniLMEmbedder, TfidfEmbedder

HERE = pathlib.Path(__file__).parent
INDEX_DIR = HERE / "index"
VECTORS = INDEX_DIR / "vectors.npy"
MANIFEST = INDEX_DIR / "index.json"

_state = None

# Queries the corpus LOOKS confident about but cannot actually answer.
#
# Found by evaluation, not by guesswork: "What are the exact disclosure
# requirements of GRI 305-1?" scores 0.536 -- comfortably above a weak-match
# threshold -- yet every hit is generic GRI marketing prose. The corpus holds
# EXPLAINERS about frameworks, never the normative text of a standard.
#
# A similarity score cannot detect this. It only ever says "closest chunk in
# the corpus", never "chunk that answers the question". So the dangerous case
# is caught by pattern instead, and the caller is pointed at the real source:
# standards/gri_disclosures.json (retrieved disclosure text) and the PDFs in
# standards/gri/.
DISCLOSURE_REF_RE = re.compile(
    r"\b(?:GRI\s*)?(\d{3})-(\d{1,2})\b|\bGRI\s*(\d{1,3})\b", re.IGNORECASE)

OUT_OF_SCOPE_NOTE = (
    "This corpus contains explainers ABOUT frameworks, not the normative text "
    "of any standard. For what a GRI disclosure actually requires, read "
    "standards/gri_disclosures.json or the PDFs in standards/gri/ — do not "
    "ground that claim in retrieved prose."
)


def check_query_scope(query: str) -> str | None:
    """Return a warning if the corpus cannot legitimately answer this query."""
    if DISCLOSURE_REF_RE.search(query):
        return OUT_OF_SCOPE_NOTE
    return None


@dataclass
class Hit:
    text: str
    source: str
    url: str
    source_type: str
    score: float
    has_quantity: bool
    chunk_id: str

    def cite(self) -> str:
        return f"{self.source} <{self.url}>"


def _load():
    """Load vectors + metadata + the matching embedder, once."""
    global _state
    if _state is not None:
        return _state

    if not VECTORS.exists() or not MANIFEST.exists():
        sys.exit(f"[stop] no index in {INDEX_DIR} — run build_index.py first.")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    vectors = np.load(VECTORS)

    backend = manifest["backend"]
    if backend == "tfidf":
        # Must reuse the exact vocabulary/IDF the index was built with.
        embedder = TfidfEmbedder.from_state(manifest["embedder_state"])
    elif backend == "minilm":
        if not MiniLMEmbedder.available():
            sys.exit("[stop] index was built with minilm but the model or its "
                     "dependencies are missing. Reinstall onnxruntime/"
                     "tokenizers, or rebuild with --backend tfidf.")
        embedder = MiniLMEmbedder()
    else:
        sys.exit(f"[stop] unknown backend {backend!r} in index.json")

    _state = (vectors, manifest, embedder)
    return _state


def backend_name() -> str:
    return _load()[1]["backend"]


def retrieve(query: str,
             k: int = 5,
             exclude_peer_reports: bool = True,
             language: str | None = "en",
             drop_quantities: bool = False,
             source_types: list[str] | None = None,
             min_score: float = 0.0) -> list[Hit]:
    """Search the knowledge corpus. Safe by default — see module docstring."""
    scope_warning = check_query_scope(query)
    if scope_warning:
        warnings.warn(f"{query!r}: {scope_warning}", stacklevel=2)

    vectors, manifest, embedder = _load()
    chunks = manifest["chunks"]
    texts = manifest["texts"]

    # Build the allowed-row mask BEFORE scoring, so a filtered-out chunk can
    # never occupy one of the k slots.
    allowed = np.ones(len(chunks), dtype=bool)
    for i, c in enumerate(chunks):
        if exclude_peer_reports and c["source_type"] == "peer_report":
            allowed[i] = False
        elif language and c["language"] != language:
            allowed[i] = False
        elif drop_quantities and c["has_quantity"]:
            allowed[i] = False
        elif source_types and c["source_type"] not in source_types:
            allowed[i] = False

    if not allowed.any():
        return []

    q = embedder.encode([query])[0]
    scores = vectors @ q                       # cosine: both sides normalised
    scores = np.where(allowed, scores, -np.inf)

    k = min(k, int(allowed.sum()))
    top = np.argpartition(-scores, k - 1)[:k] if k > 1 else [int(scores.argmax())]
    top = sorted(top, key=lambda i: -scores[i])

    hits = []
    for i in top:
        if not np.isfinite(scores[i]) or scores[i] < min_score:
            continue
        c = chunks[i]
        hits.append(Hit(text=texts[i],
                        source=c["source"],
                        url=c["url"],
                        source_type=c["source_type"],
                        score=float(scores[i]),
                        has_quantity=bool(c["has_quantity"]),
                        chunk_id=c["id"]))
    return hits


def as_context_block(hits: list[Hit]) -> str:
    """Format hits for an LLM prompt, keeping attribution attached."""
    return "\n\n".join(
        f"[{i}] source: {h.source} ({h.source_type})\n{h.text}"
        for i, h in enumerate(hits, 1))


def main():
    ap = argparse.ArgumentParser(description="Query the ESG knowledge corpus.")
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--include-peer-reports", action="store_true",
                    help="allow Toronto/Manchester chunks — style reference only")
    ap.add_argument("--drop-quantities", action="store_true",
                    help="exclude any chunk containing a figure")
    ap.add_argument("--any-language", action="store_true")
    args = ap.parse_args()

    hits = retrieve(args.query,
                    k=args.k,
                    exclude_peer_reports=not args.include_peer_reports,
                    language=None if args.any_language else "en",
                    drop_quantities=args.drop_quantities)

    print(f"backend: {backend_name()}\n")

    note = check_query_scope(args.query)
    if note:
        print(f"!! OUT OF SCOPE\n   {note}\n")

    if not hits:
        print("no results")
        return

    for i, h in enumerate(hits, 1):
        warn = "  [FIGURE]" if h.has_quantity else ""
        peer = "  [PEER INSTITUTION]" if h.source_type == "peer_report" else ""
        print(f"[{i}] {h.source}  ({h.source_type})  score={h.score:.3f}"
              f"{warn}{peer}")
        print(f"    {h.url}")
        text = " ".join(h.text.split())
        print(f"    {text[:320]}{'...' if len(text) > 320 else ''}\n")


if __name__ == "__main__":
    main()
