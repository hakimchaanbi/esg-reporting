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
    lane: str = "knowledge"
    institution: str = ""
    credit_code: str = ""
    pillar: str = ""

    def cite(self) -> str:
        if self.lane == "institution":
            return f"{self.institution}, STARS {self.credit_code} <{self.url}>"
        return f"{self.source} <{self.url}>"


class LaneMisuse(RuntimeError):
    """Raised when the institution lane is searched without naming one.

    Deliberately an exception, not a warning or a silent default. Returning
    every university's prose to a question about one of them is how Berkeley's
    achievements end up in Cork's report — and it would read perfectly well.
    """


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


def _top_indices(scores: np.ndarray, k: int) -> list[int]:
    """Indices of the k highest scores, best first."""
    if k <= 0:
        return []
    if k == 1:
        return [int(scores.argmax())]
    idx = np.argpartition(-scores, k - 1)[:k]
    return sorted((int(i) for i in idx), key=lambda i: -scores[i])


def known_institutions() -> list[str]:
    _, manifest, _ = _load()
    return sorted({c["institution"] for c in manifest["chunks"]
                   if c["institution"]})


def retrieve(query: str,
             k: int = 5,
             lane: str = "knowledge",
             institution: str | None = None,
             exclude_peer_reports: bool = True,
             language: str | None = "en",
             drop_quantities: bool = False,
             source_types: list[str] | None = None,
             pillars: list[str] | None = None,
             min_score: float = 0.0) -> list[Hit]:
    """Search the corpus. Safe by default — see module docstring.

    lane="knowledge"    general ESG explainers (default)
    lane="institution"  what one university said about itself —
                        REQUIRES institution=
    lane="all"          both; still requires institution= to reach lane C
    """
    if lane not in ("knowledge", "institution", "all"):
        raise ValueError(f"lane must be knowledge/institution/all, got {lane!r}")

    if lane in ("institution", "all") and not institution:
        available = ", ".join(known_institutions()) or "(index has no lane C)"
        raise LaneMisuse(
            f"lane={lane!r} needs institution=. Searching every university's "
            f"prose at once is how one institution's achievements end up in "
            f"another's report. Choose one of: {available}")

    if institution and institution not in known_institutions():
        raise LaneMisuse(
            f"unknown institution {institution!r}. "
            f"Choose one of: {', '.join(known_institutions())}")

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
        c_lane = c.get("lane", "knowledge")

        # --- lane gate: the institution filter is absolute -------------
        if lane != "all" and c_lane != lane:
            allowed[i] = False
            continue
        if c_lane == "institution" and c["institution"] != institution:
            allowed[i] = False
            continue

        # --- lane A filters (meaningless for lane C, hence the guard) --
        if c_lane == "knowledge":
            if exclude_peer_reports and c["source_type"] == "peer_report":
                allowed[i] = False
                continue
            if language and c["language"] != language:
                allowed[i] = False
                continue

        # --- applies to both lanes -------------------------------------
        # source_types spans lanes: "institution_prose" selects the STARS
        # answers, "document" the evidence PDFs behind them, and the lane A
        # values still work as before.
        if source_types and c["source_type"] not in source_types:
            allowed[i] = False
            continue
        if drop_quantities and c["has_quantity"]:
            allowed[i] = False
            continue
        if pillars and c.get("pillar") not in pillars:
            allowed[i] = False

    if not allowed.any():
        return []

    q = embedder.encode([query])[0]
    scores = vectors @ q                       # cosine: both sides normalised

    # lane="all" splits k between the lanes instead of taking a single top-k.
    #
    # Without this the institution lane simply wins: it has 1,049 chunks to the
    # knowledge lane's 226, and on any campus-flavoured question its prose is a
    # closer match. A plain top-k returned twelve institution chunks and zero
    # style guidance — useless for generation, which needs both "how an ESG
    # report is written" AND "what this university did".
    if lane == "all":
        lanes_of = np.array([c.get("lane", "knowledge") for c in chunks])
        k_inst = (k + 1) // 2                  # odd k favours the facts
        picks = []
        for lane_name, lane_k in (("institution", k_inst),
                                  ("knowledge", k - k_inst)):
            if lane_k <= 0:
                continue
            mask = allowed & (lanes_of == lane_name)
            if not mask.any():
                continue
            picks.extend(_top_indices(np.where(mask, scores, -np.inf),
                                      min(lane_k, int(mask.sum()))))
        top = sorted(picks, key=lambda i: -scores[i])
    else:
        top = _top_indices(np.where(allowed, scores, -np.inf),
                           min(k, int(allowed.sum())))

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
                        chunk_id=c["id"],
                        lane=c.get("lane", "knowledge"),
                        institution=c.get("institution", ""),
                        credit_code=c.get("credit_code", ""),
                        pillar=c.get("pillar", "")))
    return hits


def as_context_block(hits: list[Hit]) -> str:
    """Format hits for an LLM prompt, keeping attribution attached."""
    return "\n\n".join(
        f"[{i}] source: {h.source} ({h.source_type})\n{h.text}"
        for i, h in enumerate(hits, 1))


def main():
    ap = argparse.ArgumentParser(description="Query the ESG corpus.")
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--lane", default="knowledge",
                    choices=["knowledge", "institution", "all"])
    ap.add_argument("--institution", "-i",
                    help="required for --lane institution/all. Accepts a "
                         "substring, e.g. 'cork'")
    ap.add_argument("--pillar", action="append",
                    help="filter to a pillar (repeatable): Environmental, "
                         "Social, Governance, Context")
    ap.add_argument("--include-peer-reports", action="store_true",
                    help="allow Toronto/Manchester chunks — style reference only")
    ap.add_argument("--drop-quantities", action="store_true",
                    help="exclude any chunk containing a figure")
    ap.add_argument("--any-language", action="store_true")
    args = ap.parse_args()

    institution = args.institution
    if institution:
        # Accept either the short key ("tudublin") or any distinctive part of
        # the display name ("cork", "Berkeley"). "tudublin" is not a substring
        # of "Technological University Dublin", so key matching is not optional.
        _, manifest, _ = _load()
        keys = {c["institution_key"]: c["institution"]
                for c in manifest["chunks"] if c.get("institution_key")}
        needle = institution.lower()
        if needle in keys:
            institution = keys[needle]
            matches = [institution]
        else:
            matches = [n for n in known_institutions() if needle in n.lower()]
        if len(matches) != 1:
            print(f"'{institution}' matched {len(matches)} institutions. "
                  f"Choose one of:")
            for n in known_institutions():
                print(f"  {n}")
            return
        institution = matches[0]

    try:
        hits = retrieve(args.query,
                        k=args.k,
                        lane=args.lane,
                        institution=institution,
                        pillars=args.pillar,
                        exclude_peer_reports=not args.include_peer_reports,
                        language=None if args.any_language else "en",
                        drop_quantities=args.drop_quantities)
    except LaneMisuse as exc:
        print(f"!! {exc}")
        return

    print(f"backend: {backend_name()}   lane: {args.lane}"
          f"{'   institution: ' + institution if institution else ''}\n")

    note = check_query_scope(args.query)
    if note:
        print(f"!! OUT OF SCOPE\n   {note}\n")

    if not hits:
        print("no results")
        return

    for i, h in enumerate(hits, 1):
        warn = "  [FIGURE]" if h.has_quantity else ""
        peer = "  [PEER INSTITUTION]" if h.source_type == "peer_report" else ""
        label = (f"{h.institution} — {h.source} ({h.pillar})"
                 if h.lane == "institution"
                 else f"{h.source} ({h.source_type})")
        print(f"[{i}] {label}  score={h.score:.3f}{warn}{peer}")
        print(f"    {h.url}")
        text = " ".join(h.text.split())
        print(f"    {text[:320]}{'...' if len(text) > 320 else ''}\n")


if __name__ == "__main__":
    main()
