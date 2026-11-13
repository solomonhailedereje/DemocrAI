"""Hybrid retrieval index: dense embeddings (Ollama) + BM25 keywords.

Kept deliberately simple (numpy + JSONL, no vector DB): a few years of
meetings is only a few thousand chunks, which is tiny for numpy.
BM25 matters here because questions often contain names, party
abbreviations (GLP, FDP) and business numbers (GR Geschäft Nr. 03/2025)
that embeddings alone match poorly.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np
import requests

from .config import load_config, paths

STOPWORDS = set("""
aber alle als also am an auch auf aus bei bin bis da dann das dass dem den der des die dies
diese dieser du durch ein eine einem einen einer es für hat hatte ich ihr im in ist ja kann
man mit nach nicht noch nun nur ob oder sich sie sind so über um und uns von vor war was
wenn wer wie wir wird wo zu zum zur the a of and to is what who how
""".split())
TOKEN_RE = re.compile(r"[a-zäöüß0-9]+(?:[./][0-9]+)*", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


# --------------------------------------------------------------------------- embeddings

def embed(texts: list[str], batch: int = 32) -> np.ndarray:
    cfg = load_config()["retrieval"]
    vecs = []
    for i in range(0, len(texts), batch):
        r = requests.post(f"{cfg['ollama_url']}/api/embed",
                          json={"model": cfg["embed_model"], "input": texts[i : i + batch]}, timeout=600)
        r.raise_for_status()
        vecs.extend(r.json()["embeddings"])
        if len(texts) > batch:
            print(f"    embedded {min(i + batch, len(texts))}/{len(texts)}", end="\r")
    arr = np.asarray(vecs, dtype=np.float32)
    return arr / np.clip(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9, None)


# --------------------------------------------------------------------------- BM25

class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=np.float32)
        self.avg = float(self.len.mean()) if len(docs) else 1.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self.tf), dtype=np.float32)
        for t in set(query):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t)
                if f:
                    out[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return out


# --------------------------------------------------------------------------- index

def build_index(chunks: list[dict]) -> None:
    p = paths().index
    print(f"  embedding {len(chunks)} chunks with {load_config()['retrieval']['embed_model']} ...")
    vecs = embed([c["text"] for c in chunks])
    np.save(p / "embeddings.npy", vecs)
    with open(p / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (p / "meta.json").write_text(json.dumps({"embed_model": load_config()["retrieval"]["embed_model"],
                                             "n_chunks": len(chunks)}))
    print(f"\n  index saved to {p}")


@dataclass
class Hit:
    chunk: dict
    score: float      # hybrid score used for ranking
    dense: float      # cosine similarity, used for the "nothing relevant" threshold


class Retriever:
    def __init__(self, chunks: list[dict] | None = None, vecs: np.ndarray | None = None, embed_fn=embed):
        if chunks is None:
            p = paths().index
            if not (p / "chunks.jsonl").exists():
                raise FileNotFoundError("Index missing - run `gr-rag build-index` first.")
            chunks = [json.loads(l) for l in open(p / "chunks.jsonl", encoding="utf-8")]
            vecs = np.load(p / "embeddings.npy")
        self.chunks, self.vecs, self.embed_fn = chunks, vecs, embed_fn
        self.bm25 = BM25([tokenize(c["text"] + " " + c.get("meeting_title", "")) for c in chunks])
        self.cfg = load_config()["retrieval"]

    def mask(self, source_types: set[str] | None = None, date_from: str | None = None,
             date_to: str | None = None, meeting_ids: set[str] | None = None,
             time_range: tuple[float, float] | None = None) -> np.ndarray:
        """Boolean filter over all chunks. time_range only restricts transcript chunks."""
        m = np.ones(len(self.chunks), dtype=bool)
        for i, c in enumerate(self.chunks):
            if source_types and c["source_type"] not in source_types:
                m[i] = False
            elif date_from and (c.get("date") or "") < date_from:
                m[i] = False
            elif date_to and (c.get("date") or "9999") > date_to:
                m[i] = False
            elif meeting_ids and not (set(c.get("meeting_ids") or [c.get("meeting_id")]) & meeting_ids):
                m[i] = False
            elif time_range and c["source_type"] == "transcript" and not (
                    time_range[0] <= (c["start"] + c["end"]) / 2 <= time_range[1]):
                m[i] = False
        return m

    def search(self, query: str, top_k: int | None = None, **filters) -> list[Hit]:
        """filters: source_types, date_from, date_to, meeting_ids, time_range (see mask)."""
        top_k = top_k or self.cfg["top_k"]
        q = self.embed_fn([query])[0]
        dense = self.vecs @ q
        sparse = self.bm25.scores(tokenize(query))
        if sparse.max() > 0:
            sparse = sparse / sparse.max()
        w = self.cfg["dense_weight"]
        score = w * dense + (1 - w) * sparse
        score = np.where(self.mask(**filters), score, -np.inf)
        order = np.argsort(-score)[:top_k]
        return [Hit(self.chunks[i], float(score[i]), float(dense[i])) for i in order if np.isfinite(score[i])]
