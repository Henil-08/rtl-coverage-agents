"""Knowledge base for the planner: public spec sheets and user guides, searched by keywords and
embeddings together."""

from __future__ import annotations

import json
import logging
import os
import re
import tomllib
import urllib.request
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent / "knowledge"
DOCS, INDEX, MODELS = ROOT / "docs", ROOT / "index", ROOT / ".models"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
WORDS, OVERLAP = 180, 40


def sources() -> list[dict]:
    return tomllib.loads((ROOT / "sources.toml").read_text())["doc"]


def fetch(force: bool = False) -> list[tuple[str, str]]:
    """Download every listed document that is not already in knowledge/docs. Returns (id, status)."""
    DOCS.mkdir(parents=True, exist_ok=True)
    out = []
    for doc in sources():
        existing = list(DOCS.glob(f"{doc['id']}.*"))
        if existing and not force:
            out.append((doc["id"], "cached"))
            continue
        req = urllib.request.Request(doc["url"], headers={"User-Agent": "Mozilla/5.0 (rtl-coverage-agents)"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body, ctype = resp.read(), resp.headers.get("Content-Type", "")
        except Exception as e:
            out.append((doc["id"], f"failed: {e}"))
            continue
        ext = ".pdf" if body[:4] == b"%PDF" else ".md" if doc["url"].endswith(".md") else ".html"
        if ext == ".html" and "html" not in ctype:
            out.append((doc["id"], f"failed: unexpected content type {ctype}"))
            continue
        (DOCS / f"{doc['id']}{ext}").write_bytes(body)
        out.append((doc["id"], f"downloaded {len(body) // 1024} KB"))
    return out


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in ("p", "li", "h1", "h2", "h3", "h4", "tr", "pre", "br", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _pages(path: Path) -> list[tuple[int | None, str]]:
    if path.suffix == ".pdf":
        from pypdf import PdfReader

        logging.getLogger("pypdf").setLevel(logging.ERROR)
        return [(i + 1, p.extract_text() or "") for i, p in enumerate(PdfReader(path).pages)]
    raw = path.read_text(errors="replace")
    if path.suffix in (".html", ".htm"):
        parser = _Text()
        parser.feed(raw)
        raw = "".join(parser.parts)
    return [(None, raw)]


def _chunks(text: str) -> list[str]:
    words = re.sub(r"\s+", " ", text).split(" ")
    out = []
    for start in range(0, max(1, len(words) - OVERLAP), WORDS - OVERLAP):
        piece = " ".join(words[start:start + WORDS]).strip()
        if len(piece) > 120:
            out.append(piece)
    return out


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _embedder():
    # the xet transfer client stalls on some networks; plain HTTPS is fine for a 66 MB model
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from fastembed import TextEmbedding

    return TextEmbedding(EMBED_MODEL, cache_dir=str(MODELS))


def build(progress=print, embed: bool = True) -> dict:
    """Chunk every file in knowledge/docs and write the index."""
    meta = {d["id"]: d for d in sources()}
    chunks = []
    for path in sorted(DOCS.glob("*")):
        if path.suffix not in (".pdf", ".html", ".htm", ".md", ".txt"):
            continue
        doc = meta.get(path.stem, {"id": path.stem, "title": path.name, "url": ""})
        n = 0
        for page, text in _pages(path):
            for piece in _chunks(text):
                chunks.append({"doc": doc["id"], "title": doc["title"], "url": doc["url"], "page": page, "text": piece})
                n += 1
        progress(f"{path.name}: {n} passages")
    INDEX.mkdir(parents=True, exist_ok=True)
    (INDEX / "chunks.json").write_text(json.dumps(chunks))
    embedded = False
    try:
        if not embed:
            raise RuntimeError("disabled")
        vecs = np.array(list(_embedder().passage_embed([c["text"] for c in chunks])), dtype=np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
        np.save(INDEX / "vectors.npy", vecs)
        embedded = True
    except Exception as e:
        progress(f"embeddings skipped, keyword search only: {e}")
    info = {"chunks": len(chunks), "docs": len({c["doc"] for c in chunks}), "embeddings": embedded}
    (INDEX / "info.json").write_text(json.dumps(info))
    load.cache_clear()
    return info


class KnowledgeBase:
    def __init__(self, chunks: list[dict], vectors: np.ndarray | None):
        from rank_bm25 import BM25Okapi

        self.chunks = chunks
        self.vectors = vectors
        self.bm25 = BM25Okapi([_tokens(c["text"]) for c in chunks])
        self._embed = None

    def stats(self) -> dict:
        docs = {}
        for c in self.chunks:
            docs.setdefault(c["doc"], {"title": c["title"], "url": c["url"], "passages": 0})["passages"] += 1
        return {"passages": len(self.chunks), "embeddings": self.vectors is not None, "docs": docs}

    def search(self, query: str, k: int = 5) -> list[dict]:
        """Reciprocal rank fusion of BM25 and embedding similarity."""
        bm = self.bm25.get_scores(_tokens(query))
        ranks = [np.argsort(-bm)[:50]]
        if self.vectors is not None:
            try:
                if self._embed is None:
                    self._embed = _embedder()
                q = np.array(next(iter(self._embed.query_embed(query))), dtype=np.float32)
                ranks.append(np.argsort(-(self.vectors @ (q / (np.linalg.norm(q) + 1e-9))))[:50])
            except Exception:
                pass
        fused: dict[int, float] = {}
        for order in ranks:
            for r, i in enumerate(order):
                fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (60 + r)
        best = sorted(fused, key=fused.get, reverse=True)[:k]
        return [{**self.chunks[i], "score": round(fused[i], 4), "query": query} for i in best]


@lru_cache(maxsize=1)
def load() -> KnowledgeBase | None:
    if not (INDEX / "chunks.json").exists():
        return None
    chunks = json.loads((INDEX / "chunks.json").read_text())
    if not chunks:
        return None
    vec_path = INDEX / "vectors.npy"
    return KnowledgeBase(chunks, np.load(vec_path) if vec_path.exists() else None)
