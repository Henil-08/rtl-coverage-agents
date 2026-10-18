"""Knowledge base for the planner: public spec sheets and user guides, searched by keywords and
embeddings together."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent / "knowledge"
DOCS, INDEX, MODELS = ROOT / "docs", ROOT / "index", ROOT / ".models"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
WORDS, OVERLAP = 180, 40


REPO = ROOT.parent
UA = {"User-Agent": "Mozilla/5.0 (rtl-coverage-agents knowledge base)"}


def config() -> dict:
    return tomllib.loads((ROOT / "sources.toml").read_text())


def sources() -> list[dict]:
    return config().get("doc", [])


def _meta() -> dict:
    path = DOCS / "_meta.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _get(url: str, timeout: int = 90) -> tuple[bytes, str]:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(15 * (attempt + 1))
    raise RuntimeError("unreachable")


def _title_of(body: bytes, fallback: str) -> str:
    if body[:4] == b"%PDF":
        try:
            import io

            from pypdf import PdfReader

            logging.getLogger("pypdf").setLevel(logging.ERROR)
            t = (PdfReader(io.BytesIO(body)).metadata or {}).get("/Title")
            if t and len(str(t).strip()) > 3:
                return str(t).strip()
        except Exception:
            pass
        return fallback
    m = re.search(rb"<title[^>]*>(.*?)</title>", body[:20000], re.S | re.I)
    if m:
        import html

        return html.unescape(m.group(1).decode("utf-8", "replace")).strip()
    return fallback


def _save(doc_id: str, url: str, body: bytes, title: str | None, meta: dict) -> str:
    ext = ".pdf" if body[:4] == b"%PDF" else ".md" if url.endswith(".md") else ".html"
    (DOCS / f"{doc_id}{ext}").write_bytes(body)
    meta[doc_id] = {"title": title or _title_of(body, doc_id), "url": url}
    return f"downloaded {len(body) // 1024} KB"


def fetch(force: bool = False, progress=print) -> list[tuple[str, str]]:
    """Download every source in sources.toml that is not already in knowledge/docs."""
    from concurrent.futures import ThreadPoolExecutor

    DOCS.mkdir(parents=True, exist_ok=True)
    cfg, meta, out = config(), _meta(), []

    def one(doc: dict) -> tuple[str, str]:
        if list(DOCS.glob(f"{doc['id']}.*")) and not force:
            return doc["id"], "cached"
        try:
            body, ctype = _get(doc["url"])
        except Exception as e:
            return doc["id"], f"failed: {e}"
        if body[:4] != b"%PDF" and not doc["url"].endswith(".md") and "html" not in ctype:
            return doc["id"], f"failed: unexpected content type {ctype}"
        return doc["id"], _save(doc["id"], doc["url"], body, doc.get("title"), meta)

    with ThreadPoolExecutor(8) as pool:
        for doc_id, status in pool.map(one, cfg.get("doc", [])):
            out.append((doc_id, status))
            progress(f"{doc_id:<60} {status}")

    for rel in cfg.get("github_release", []):
        try:
            body, _ = _get(f"https://api.github.com/repos/{rel['repo']}/releases/latest")
            assets = [a for a in json.loads(body)["assets"] if a["name"].endswith(".pdf")]
        except Exception as e:
            out.append((rel["repo"], f"failed: {e}"))
            progress(f"{rel['repo']} release: failed: {e}")
            continue
        for a in assets:
            doc_id = re.sub(r"[^a-z0-9]+", "_", f"{rel['repo']}_{a['name'][:-4]}".lower())
            if list(DOCS.glob(f"{doc_id}.*")) and not force:
                status = "cached"
            else:
                try:
                    status = _save(doc_id, a["browser_download_url"], _get(a["browser_download_url"])[0],
                                   f"{rel.get('title', rel['repo'])}: {a['name']}", meta)
                except Exception as e:
                    status = f"failed: {e}"
            out.append((doc_id, status))
            progress(f"{doc_id:<60} {status}")

    for q in cfg.get("arxiv", []):
        time.sleep(3)
        api = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"search_query": q["query"], "max_results": q.get("max", 10), "sortBy": "relevance"})
        try:
            feed = _get(api)[0].decode("utf-8", "replace")
        except Exception as e:
            out.append((q["query"], f"failed: {e}"))
            progress(f"arXiv search {q['query']!r}: failed: {e}")
            continue
        for entry in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
            arx = re.search(r"<id>https?://arxiv.org/abs/([^<]+)</id>", entry).group(1)
            title = re.sub(r"\s+", " ", re.search(r"<title>(.*?)</title>", entry, re.S).group(1)).strip()
            doc_id = "arxiv_" + re.sub(r"[^a-z0-9]+", "_", arx.lower())
            if list(DOCS.glob(f"{doc_id}.*")) and not force:
                status = "cached"
            else:
                time.sleep(3)
                try:
                    status = _save(doc_id, f"https://arxiv.org/abs/{arx}", _get(f"https://arxiv.org/pdf/{arx}")[0],
                                   f"arXiv {arx}: {title}", meta)
                except Exception as e:
                    status = f"failed: {e}"
            out.append((doc_id, status))
            progress(f"{doc_id:<60} {status}")

    (DOCS / "_meta.json").write_text(json.dumps(meta, indent=1))
    return out


def _local_files() -> list[tuple[Path, dict]]:
    files = []
    for loc in config().get("local", []):
        for path in sorted(REPO.glob(loc["glob"])):
            rel = path.relative_to(REPO)
            files.append((path, {"id": str(rel), "title": f"{loc['title']}: {rel.name}", "url": str(rel)}))
    return files


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


_BAD_TITLE = re.compile(r"paper title|\.book$|\.docx?$|\.pdf$|final draft|^untitled|^microsoft word|^title$|copyright|all rights reserved|^\W*$", re.I)


def clean_title(title: str, first_text: str, fallback: str) -> str:
    """PDF metadata titles are often junk; fall back to the first real line of the document."""
    if title and len(title) > 6 and not _BAD_TITLE.search(title.strip()):
        return title.strip()
    for line in first_text.splitlines():
        line = line.strip()
        if 12 <= len(line) <= 120 and re.search(r"[A-Za-z]{4}", line) and not _BAD_TITLE.search(line):
            return line
    return fallback


def _chunks(text: str) -> list[str]:
    text = text.encode("utf-8", "replace").decode("utf-8").replace("\x00", " ")
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


def build(progress=print, embed: bool = True, local: bool = True) -> dict:
    """Chunk every downloaded document plus the local sources and write the index."""
    known = {d["id"]: d for d in sources()} | _meta()
    files = [(p, {"id": p.stem, "title": p.name, "url": "", **known.get(p.stem, {})})
             for p in sorted(DOCS.glob("*")) if p.suffix in (".pdf", ".html", ".htm", ".md", ".txt")]
    if local:
        files += _local_files()
    chunks = []
    for path, doc in files:
        n = 0
        try:
            pages = _pages(path)
        except Exception as e:
            progress(f"{path.name}: skipped ({e})")
            continue
        title = clean_title(doc.get("title", ""), pages[0][1] if pages else "", path.stem)
        for page, text in pages:
            for piece in _chunks(text):
                chunks.append({"doc": doc["id"], "title": title, "url": doc.get("url", ""),
                               "page": page, "text": piece})
                n += 1
        progress(f"{path.name}: {n} passages")
    INDEX.mkdir(parents=True, exist_ok=True)
    (INDEX / "chunks.json").write_text(json.dumps(chunks))
    embedded = False
    try:
        if not embed:
            raise RuntimeError("disabled")
        model, vecs = _embedder(), []
        texts = [c["text"] for c in chunks]
        for start in range(0, len(texts), 512):
            vecs.extend(model.passage_embed(texts[start:start + 512]))
            progress(f"embedded {min(start + 512, len(texts))}/{len(texts)} passages")
        vecs = np.array(vecs, dtype=np.float32)
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
