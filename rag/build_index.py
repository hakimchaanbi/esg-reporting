"""
Phase 5a — embed the labelled chunks into a searchable index
============================================================

Reads rag/chunks.jsonl (from chunk_corpus.py), embeds every chunk, and writes:

    rag/index/vectors.npy   (n_chunks, dim) float32, L2-normalised
    rag/index/index.json    chunk metadata + which backend produced the vectors

There is no vector database. See embed.py for why: the corpus is 226 chunks,
which is 347 KB of floats, so exact cosine similarity is a single dot product
over a matrix that fits comfortably in RAM. ChromaDB is also uninstallable in
this environment (grpcio is blocked at the index level), but it would have been
the wrong tool regardless.

The backend name is written into index.json and checked at query time, so
vectors from different embedders can never be silently compared.

RUN
    python build_index.py                  best available backend
    python build_index.py --backend tfidf  force the offline fallback
"""

import argparse
import json
import pathlib
import sys

import numpy as np

from embed import MiniLMEmbedder, TfidfEmbedder, get_embedder

HERE = pathlib.Path(__file__).parent
CHUNKS = HERE / "chunks.jsonl"
INDEX_DIR = HERE / "index"
VECTORS = INDEX_DIR / "vectors.npy"
MANIFEST = INDEX_DIR / "index.json"

META_FIELDS = ("id", "lane", "institution", "institution_key", "source", "url",
               "source_type", "language", "has_quantity", "chunk_index",
               "words", "credit_code", "credit_name", "pillar", "section",
               "field")


def load_chunks() -> list[dict]:
    if not CHUNKS.exists():
        sys.exit(f"[stop] {CHUNKS} not found — run chunk_corpus.py first.")
    with CHUNKS.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["minilm", "tfidf"], default="minilm",
                    help="preferred backend; falls back to tfidf if minilm "
                         "dependencies or model are missing")
    ap.add_argument("--no-download", action="store_true",
                    help="never fetch the MiniLM model from HuggingFace")
    args = ap.parse_args()

    records = load_chunks()
    texts = [r["text"] for r in records]
    print(f"[load] {len(records)} chunks from {CHUNKS.name}")

    embedder = get_embedder(prefer=args.backend,
                            allow_download=not args.no_download)
    if isinstance(embedder, TfidfEmbedder):
        embedder.fit(texts)

    print(f"[model] backend={embedder.name} dim={embedder.dim}")
    if embedder.name == "tfidf":
        print("        LEXICAL fallback — matches shared words, misses synonyms.")
        print("        Re-run without --backend tfidf once onnxruntime installs.")

    vectors = embedder.encode(texts)
    if vectors.shape[0] != len(records):
        sys.exit(f"[stop] embedded {vectors.shape[0]} vectors for "
                 f"{len(records)} chunks")

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(VECTORS, vectors)

    manifest = {
        "backend": embedder.name,
        "dim": int(vectors.shape[1]),
        "count": len(records),
        "chunks": [{k: r[k] for k in META_FIELDS} for r in records],
        "texts": texts,
    }
    if isinstance(embedder, TfidfEmbedder):
        # The query must be projected through the same vocabulary and IDF.
        manifest["embedder_state"] = embedder.state()

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    size = VECTORS.stat().st_size + MANIFEST.stat().st_size
    print(f"[save] {vectors.shape[0]} x {vectors.shape[1]} vectors -> "
          f"{INDEX_DIR}  ({size / 1e6:.1f} MB total)")

    # ---- sanity: normalised vectors, and the filters actually bite ----
    norms = np.linalg.norm(vectors, axis=1)
    print(f"\n--- checks ---")
    print(f"  vectors L2-normalised: min={norms.min():.4f} max={norms.max():.4f} "
          f"(want ~1.000)")

    chunks = manifest["chunks"]
    knowledge = [c for c in chunks if c["lane"] == "knowledge"]
    institution = [c for c in chunks if c["lane"] == "institution"]

    peer = sum(c["source_type"] == "peer_report" for c in knowledge)
    nonen = sum(c["language"] != "en" for c in knowledge)
    quant = sum(c["has_quantity"] for c in chunks)
    default_pool = sum(
        c["source_type"] != "peer_report" and c["language"] == "en"
        for c in knowledge)

    print(f"  lane A (knowledge)  : {len(knowledge)} chunks, "
          f"{default_pool} in the default pool")
    print(f"    held back: {peer} peer-report, {nonen} non-English")
    print(f"  lane C (institution): {len(institution)} chunks, "
          f"NOT searchable without naming an institution")
    for inst in sorted({c["institution"] for c in institution}):
        n = sum(c["institution"] == inst for c in institution)
        print(f"    {inst[:36]:38} {n:4}")
    print(f"  droppable on request: {quant} chunks containing a figure")


if __name__ == "__main__":
    main()
