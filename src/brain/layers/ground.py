"""Ground layer — hybrid BM25 + vector retrieve + rerank.

BM25 data is in-memory (process-local). Auto-ingest FAQ entries on first use.
"""

from __future__ import annotations

import json
import hashlib
import logging
from typing import Any

try:
    from chromadb import PersistentClient
    from chromadb.config import Settings
except ImportError:
    PersistentClient = None
    Settings = None

from ..config import settings, kb_faq_path
from ..models import ThinkRequest

logger = logging.getLogger("brain.ground")

# ─── vector store (chromadb, เก็บถาวร) ─────────────────────────────────────────


class VectorStore:
    """ฝาก vector + metadata ใน Chromadb ถาวร — เริ่มต้นด้วย sqlite backend."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.client = self._connect()

    def _connect(self):
        if PersistentClient is None:
            return None
        try:
            return PersistentClient(path=self.path, settings=Settings(allow_reset=True))
        except Exception as e:
            logger.warning("vector store connect failed: %s", e)
            return None

    def ensure_collection(self, name: str = "jc_smart_kb") -> Any:
        if self.client is None:
            logger.warning("no vector client — skip retrieval")
            return None
        try:
            coll = self.client.get_or_create_collection(
                name=name,
                metadata={"description": "JC SMART Brain knowledge base"},
            )
            return coll
        except Exception as e:
            logger.warning("collection get/create failed: %s", e)
            return None

    def add_documents(self, docs: list[dict[str, Any]]) -> int:
        coll = self.ensure_collection()
        if coll is None or not docs:
            return 0
        ids = [d["id"] for d in docs]
        texts = [d["text"] for d in docs]
        metadatas = [d.get("metadata", {}) for d in docs]
        try:
            coll.add(documents=texts, ids=ids, metadatas=metadatas)
            logger.info("added %d documents to vector store", len(docs))
            return len(docs)
        except Exception as e:
            logger.warning("add documents failed: %s", e)
            return 0

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        coll = self.ensure_collection()
        if coll is None:
            logger.warning("no vector client — skip retrieval")
            return []

        try:
            count = coll.count()
            if count == 0:
                return []
            result = coll.query(
                query_texts=[query_text],
                n_results=min(n_results, count),
                where=where,
            )
            docs: list[dict[str, Any]] = []
            if result.get("ids") and result["ids"][0]:
                for i, doc_id in enumerate(result["ids"][0]):
                    doc = {
                        "id": doc_id,
                        "text": result["documents"][0][i] if result["documents"] else "",
                        "metadata": result["metadatas"][0][i] if result["metadatas"] else {},
                        "distance": result["distances"][0][i] if result["distances"] else 0.0,
                    }
                    docs.append(doc)
            return docs
        except Exception as e:
            logger.warning("query failed: %s", e)
            return []


# ─── singleton ──────────────────────────────────────────────────────────────────

_store: VectorStore | None = None


def _get_store() -> VectorStore | None:
    global _store
    if _store is None:
        try:
            _store = VectorStore(settings().pg_vector_path)
        except Exception as e:
            logger.warning("vector store init failed: %s", e)
    return _store


# ─── BM25 retriever (keyword) ──────────────────────────────────────────────────


try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None  # type: ignore[misc,assignment]


class BM25Retriever:
    """BM25 keyword retriever — ใช้ raw text ก่อนจะทำ embedding."""

    def __init__(self) -> None:
        self.documents: list[str] = []
        self.bm25 = None
        self.tokenized: list[list[str]] = []

    def add(self, text: str) -> None:
        self.bm25 = None
        self.documents.append(text)
        toks = _tokenize(text)
        self.tokenized.append(toks)

    def _rebuild(self) -> None:
        if BM25Okapi is None or not self.tokenized:
            self.bm25 = None
            return
        try:
            self.bm25 = BM25Okapi(self.tokenized)
        except Exception as e:
            logger.warning("bm25 rebuild failed: %s", e)
            self.bm25 = None

    def search(self, query: str, n: int = 5) -> list[dict[str, Any]]:
        if self.bm25 is None:
            self._rebuild()
        if self.bm25 is None:
            return _simple_similarity(self.documents, query, n)

        toks = _tokenize(query)
        try:
            scores = self.bm25.get_scores(toks)
        except Exception:
            return _simple_similarity(self.documents, query, n)

        ranked = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True,
        )[:n]
        return [
            {"text": self.documents[i], "score": float(score), "index": i}
            for i, score in ranked
            if score > 0
        ]


def _tokenize(text: str) -> list[str]:
    """tokenize เบื้องต้น — Thai + English, ตัด punctuation."""
    import re
    toks = re.findall(r"[\wก-๙]{2,}", text.lower())
    return toks


def _simple_similarity(docs: list[str], query: str, n: int) -> list[dict[str, Any]]:
    """cosine similarity แบบง่าย — เมื่อไม่มี BM25."""
    from collections import Counter
    import math

    q_toks = _tokenize(query)
    if not q_toks:
        return []

    def vec(toks: list[str]) -> Counter:
        return Counter(toks)

    q_vec = vec(q_toks)
    q_norm = math.sqrt(sum(v * v for v in q_vec.values()))
    if q_norm == 0:
        return []

    results = []
    for i, doc in enumerate(docs):
        d_vec = vec(_tokenize(doc))
        d_norm = math.sqrt(sum(v * v for v in d_vec.values()))
        if d_norm == 0:
            continue
        dot = sum(q_vec.get(t, 0) * d_vec.get(t, 0) for t in q_vec)
        sim = dot / (q_norm * d_norm)
        if sim > 0:
            results.append({"text": doc, "score": sim, "index": i})

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:n]


_bm25: BM25Retriever | None = None


def _get_bm25() -> BM25Retriever | None:
    global _bm25
    if _bm25 is None:
        _bm25 = BM25Retriever()
    return _bm25


def _ingest_faq_into_bm25() -> int:
    """ ingest FAQ JSON entries เข้า BM25 แบบ lazy — เรียกครั้งแรกที่ต้องการ.

    รันครั้งเดียวต่อ process — ครั้งต่อไปไม่ทำซ้ำ.
    """
    bm25 = _get_bm25()
    if bm25 is None:
        return 0
    if bm25.documents:
        return len(bm25.documents)  # already ingested

    try:
        faq_path = kb_faq_path()

        with open(faq_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        count = 0
        for group, entries in data.items():
            for trigger, entry in entries.items():
                answer = entry.get("answer", "")
                if answer:
                    bm25.add(answer)
                    count += 1

        bm25._rebuild()
        logger.info("BM25 auto-ingested %d FAQ entries from %s", count, faq_path)
        return count
    except Exception as e:
        logger.warning("BM25 FAQ ingest failed: %s", e)
        return 0


# ─── Retrieval pipeline ─────────────────────────────────────────────────────────


async def ground(req: ThinkRequest, classified: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Hybrid retrieve: BM25 keyword + vector semantic (ถ้ามี) → เป็น chunks."""

    # Auto-ingest FAQ เข้า BM25 ครั้งแรก (lazy)
    _ingest_faq_into_bm25()

    chunks: list[dict[str, Any]] = []

    # 1. BM25 keyword
    bm25 = _get_bm25()
    if bm25 is not None:
        keyword_results = bm25.search(req.query, n=5)
        for r in keyword_results:
            idx = r.get("index", 0)
            chunks.append({
                "id": f"bm25-{idx}",
                "text": r.get("text", ""),
                "source": {"doc": "jc-smart kb", "chunk_id": f"bm25-{idx}"},
                "score": r.get("score", 0.0),
                "backend": "bm25",
            })

    # 2. Vector semantic (ถ้า vector store พร้อม)
    store = _get_store()
    if store is not None:
        vector_results = store.query(req.query, n_results=5)
        for r in vector_results:
            chunks.append({
                "id": r.get("id", f"vec-{len(chunks)}"),
                "text": r.get("text", ""),
                "source": {"doc": r.get("metadata", {}).get("doc", "unknown"), "chunk_id": r.get("id")},
                "distance": r.get("distance", 0),
                "backend": "vector",
            })

    # deduplicate โดย text similarity (เบื้องต้น)
    seen_texts: set[str] = set()
    dedup: list[dict[str, Any]] = []
    for c in chunks:
        t = c.get("text", "").strip().lower()
        if t and t not in seen_texts:
            seen_texts.add(t)
            dedup.append(c)

    logger.info("ground: %d chunks (after dedup)", len(dedup))
    return dedup


def ingest_texts(texts: list[str], docs: list[str] | None = None) -> int:
    """ ingest ข้อความลง vector store + BM25."""

    if docs is None:
        docs = ["jc-smart kb"] * len(texts)

    # BM25
    bm25 = _get_bm25()
    if bm25 is not None:
        for t in texts:
            bm25.add(t)

    # Vector
    store = _get_store()
    if store is not None:
        docs_to_add = []
        for i, t in enumerate(texts):
            docs_to_add.append({
                "id": hashlib.sha256(t.encode()).hexdigest(),
                "text": t,
                "metadata": {"doc": docs[i] if i < len(docs) else "jc-smart kb"},
            })
        store.add_documents(docs_to_add)

    logger.info("ingested %d texts", len(texts))
    return len(texts)