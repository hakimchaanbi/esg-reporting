"""
Phase 5a — embedding backends
=============================

WHY THERE ARE TWO, AND WHY THERE IS NO CHROMADB

    The plan (CLAUDE.md §11) said ChromaDB + sentence-transformers. Neither is
    used, but for one good reason and one that turned out to be false:

    * ChromaDB: an earlier version of this docstring said grpcio "is blocked at
      the package-index level" because pip reported "from versions: none".
      THAT WAS WRONG. It was a badly degraded network: pip could not read the
      index and reported that as the package not existing. On a healthy
      connection chromadb and grpcio install without incident, and both are
      now installed. Corrected here and in CLAUDE.md §13 — re-test an
      environment claim before writing it down as fact.
    * sentence-transformers needs PyTorch, ~2 GB. This one still holds: the
      same model is reachable through ONNX Runtime at 23 MB.

    That turned out not to matter, because a vector DATABASE was never the
    right tool here. The corpus is 226 chunks. 226 x 384 floats is 347 KB --
    it fits in RAM with room to spare, and exact cosine similarity over 226
    vectors is instant. Approximate nearest-neighbour indexes, client/server
    processes and telemetry stacks all exist to solve problems this corpus
    does not have.

    So: embeddings are a numpy array on disk, and search is a dot product.
    Every step is inspectable, which is also easier to defend in a viva than
    "the library did it".

THE TWO BACKENDS

    minilm  (preferred)  all-MiniLM-L6-v2, 384-dim, via onnxruntime.
                         SEMANTIC: "greenhouse gas emissions" and "carbon
                         output" score as similar despite sharing no words.
                         Needs onnxruntime + tokenizers, and downloads ~90 MB
                         of model from HuggingFace on first use (cached).

    tfidf   (fallback)   Pure numpy, zero new dependencies, works offline.
                         LEXICAL: matches on shared words only, so it misses
                         synonyms. Good enough to build and test the whole
                         pipeline, and it means a flaky network never blocks
                         progress.

    Both return L2-normalised float32 vectors, so cosine similarity is just a
    dot product and the rest of the code does not care which one ran. The
    backend name is recorded in the index so results are never silently
    compared across backends.

    get_embedder() picks minilm when its dependencies and model are available
    and falls back to tfidf otherwise, announcing which it chose.
"""

from __future__ import annotations

import json
import math
import pathlib
import re
import urllib.request
from collections import Counter

import numpy as np

HERE = pathlib.Path(__file__).parent
MODEL_DIR = HERE / "models" / "all-MiniLM-L6-v2"
HF_BASE = ("https://huggingface.co/sentence-transformers/"
           "all-MiniLM-L6-v2/resolve/main")
# int8-quantised build: 23 MB instead of 90 MB for the fp32 model.
#
# Chosen because this machine's link to the HuggingFace CDN runs at ~30 KB/s --
# 90 MB is over an hour, 23 MB is about twelve minutes. The accuracy cost of
# int8 quantisation on MiniLM retrieval is well under a percent, which is
# irrelevant when ranking 226 chunks; the download difference is not.
#
# quint8_avx2 matches this CPU (avx2, no avx512 -- checked in /proc/cpuinfo).
# For the full-precision model, swap in "onnx/model.onnx".
MODEL_FILES = {
    "model.onnx": "onnx/model_quint8_avx2.onnx",
    "tokenizer.json": "tokenizer.json",
}

TOKEN_RE = re.compile(r"[a-z][a-z0-9\-]+")
STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "are", "from", "have", "has",
    "not", "but", "all", "can", "その", "into", "each", "such", "may", "which",
    "their", "they", "there", "these", "those", "than", "then", "when", "what",
    "will", "would", "should", "could", "been", "being", "was", "were", "its",
    "also", "any", "other", "more", "most", "some", "how", "who", "our", "out",
    "about", "over", "under", "between", "within", "including", "well", "you",
}


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


# ----------------------------------------------------------------------
# TF-IDF — lexical fallback, no dependencies beyond numpy
# ----------------------------------------------------------------------
class TfidfEmbedder:
    """Classic TF-IDF with L2-normalised rows.

    Fitted on the corpus, so the vocabulary and IDF weights must be saved
    alongside the vectors -- a query embedded with a different vocabulary
    would be meaningless. state() / from_state() handle that.
    """

    name = "tfidf"

    def __init__(self, vocab: dict[str, int] | None = None,
                 idf: np.ndarray | None = None):
        self.vocab = vocab or {}
        self.idf = idf if idf is not None else np.zeros(0, dtype=np.float32)

    @property
    def dim(self) -> int:
        return len(self.vocab)

    def fit(self, texts: list[str]) -> "TfidfEmbedder":
        doc_freq: Counter[str] = Counter()
        for text in texts:
            doc_freq.update(set(tokenize(text)))

        # Drop hapax terms: they cannot connect two chunks, so they only add
        # dimensions and noise.
        terms = sorted(t for t, df in doc_freq.items() if df >= 2)
        self.vocab = {t: i for i, t in enumerate(terms)}

        n = len(texts)
        self.idf = np.array(
            [math.log((1 + n) / (1 + doc_freq[t])) + 1.0 for t in terms],
            dtype=np.float32)
        return self

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), max(self.dim, 1)), dtype=np.float32)
        for row, text in enumerate(texts):
            counts = Counter(tokenize(text))
            for term, tf in counts.items():
                j = self.vocab.get(term)
                if j is not None:
                    out[row, j] = (1.0 + math.log(tf)) * self.idf[j]
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-12)

    def state(self) -> dict:
        return {"vocab": self.vocab, "idf": self.idf.tolist()}

    @classmethod
    def from_state(cls, state: dict) -> "TfidfEmbedder":
        return cls(vocab=state["vocab"],
                   idf=np.array(state["idf"], dtype=np.float32))


# ----------------------------------------------------------------------
# MiniLM — semantic, via onnxruntime
# ----------------------------------------------------------------------
class MiniLMEmbedder:
    """all-MiniLM-L6-v2 through ONNX Runtime, with mean pooling.

    Mean pooling over the token embeddings, masked so padding contributes
    nothing, then L2 normalise -- this is exactly what sentence-transformers
    does for this model, so the vectors are equivalent.
    """

    name = "minilm"
    dim = 384

    def __init__(self):
        import onnxruntime
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding()
        self.session = onnxruntime.InferenceSession(
            str(MODEL_DIR / "model.onnx"),
            providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self.session.get_inputs()}

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        vectors = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            encoded = self.tokenizer.encode_batch(batch)

            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)

            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)

            hidden = self.session.run(None, feed)[0]          # (b, tokens, 384)

            m = mask[:, :, None].astype(np.float32)
            pooled = (hidden * m).sum(axis=1) / np.maximum(m.sum(axis=1), 1e-9)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            vectors.append((pooled / np.maximum(norms, 1e-12)).astype(np.float32))

        return np.vstack(vectors) if vectors else np.zeros((0, self.dim), np.float32)

    @staticmethod
    def available() -> bool:
        try:
            import onnxruntime  # noqa: F401
            import tokenizers   # noqa: F401
        except ImportError:
            return False
        return all((MODEL_DIR / f).exists() for f in MODEL_FILES)

    @staticmethod
    def download(quiet: bool = False) -> bool:
        """Fetch the ONNX model and tokenizer. ~90 MB, once, RESUMABLE.

        Resume matters here: the first attempt died at 86 of 90 MB on a link
        running at ~60 KB/s, and a non-resuming download throws all of that
        away on every retry. huggingface_hub handles range-resume, retries and
        caching; the urllib path below is a fallback that does its own range
        resume and, critically, never deletes a partial file.
        """
        MODEL_DIR.mkdir(parents=True, exist_ok=True)

        # Plain HTTP range-resume is tried FIRST, not huggingface_hub. On this
        # network the hub's hf-xet transfer backend stalled at 0 bytes for ten
        # minutes, while the direct CDN fetch below reached 86 of 90 MB. The
        # hub stays as a fallback in case the direct URL layout ever changes.
        for local, remote in MODEL_FILES.items():
            target = MODEL_DIR / local
            if target.exists() and target.stat().st_size > 0:
                continue

            if MiniLMEmbedder._resume_download(
                    f"{HF_BASE}/{remote}", target, quiet):
                continue

            try:
                from huggingface_hub import hf_hub_download
            except ImportError:
                return False

            if not quiet:
                print(f"[fetch] falling back to huggingface_hub for {remote}")
            try:
                cached = hf_hub_download(
                    repo_id="sentence-transformers/all-MiniLM-L6-v2",
                    filename=remote)
                target.write_bytes(pathlib.Path(cached).read_bytes())
            except Exception as exc:                       # noqa: BLE001
                if not quiet:
                    print(f"[warn] hub download failed too: {exc}")
                return False

        return True

    @staticmethod
    def _resume_download(url: str, target: pathlib.Path, quiet: bool) -> bool:
        """Range-resume into target.part, then rename. Keeps partials."""
        part = target.with_suffix(target.suffix + ".part")
        have = part.stat().st_size if part.exists() else 0

        for attempt in range(1, 9):
            req = urllib.request.Request(url)
            if have:
                req.add_header("Range", f"bytes={have}-")
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    if have and resp.status != 206:
                        have = 0                     # server ignored the range
                    mode = "ab" if have else "wb"
                    with part.open(mode) as out:
                        while chunk := resp.read(1 << 20):
                            out.write(chunk)
                            have += len(chunk)
                part.rename(target)
                if not quiet:
                    print(f"[ok]    {target.name}  "
                          f"{target.stat().st_size / 1e6:.1f} MB")
                return True
            except Exception as exc:                       # noqa: BLE001
                have = part.stat().st_size if part.exists() else 0
                if not quiet:
                    print(f"[retry {attempt}/8] {have / 1e6:.1f} MB kept — {exc}")

        return False


# ----------------------------------------------------------------------
def get_embedder(prefer: str = "minilm", allow_download: bool = True):
    """Return the best available backend, saying out loud which one it is."""
    if prefer == "minilm":
        try:
            import onnxruntime  # noqa: F401
            import tokenizers   # noqa: F401
            deps = True
        except ImportError:
            deps = False

        if deps:
            if not MiniLMEmbedder.available() and allow_download:
                MiniLMEmbedder.download()
            if MiniLMEmbedder.available():
                return MiniLMEmbedder()
            print("[warn] minilm model unavailable — falling back to tfidf")
        else:
            print("[warn] onnxruntime/tokenizers not installed — "
                  "falling back to tfidf")

    return TfidfEmbedder()
