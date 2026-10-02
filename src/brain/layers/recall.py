"""Recall layer — cache + memory lookup."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import kb_faq_path

logger = logging.getLogger("brain.recall")


# ─── cache entry ──────────────────────────────────────────────────────────────

@dataclass
class CacheEntry:
    query_hash: str
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    route: str = "cache_hit"
    hit_at: float = field(default_factory=time.time)
    ttl_hours: int = 72


# ─── JSON-backed FAQ store ───────────────────────────────────────────────────

class FAQStore:
    """FAQ entries จากไฟล์ JSON — ค้นแบบ keyword + exact match."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path) if isinstance(path, str) else path
        self.entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            logger.warning("faq json not found: %s", self.path)
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            # data = {group: {trigger: {answer, sources, route}}}
            for group, entries in data.items():
                for trigger, entry in entries.items():
                    if not isinstance(entry, dict) or not isinstance(entry.get("answer"), str) or not entry["answer"].strip():
                        logger.warning("skipping invalid FAQ entry: %s", trigger)
                        continue
                    self.entries[trigger.strip().lower()] = entry
            logger.info("faq store loaded: %d entries from %s", len(self.entries), self.path)
        except Exception as e:
            logger.warning("faq load failed: %s", e)

    def lookup(self, query: str) -> dict[str, Any] | None:
        """ค้นหา FAQ entry — exact match ก่อน แล้วค่อย loose keyword."""
        q = query.strip().lower()

        # 1. exact match
        if q in self.entries:
            return self.entries[q]

        # 2. loose keyword match — เช็คแต่ละ entry ว่ามีคำคล้ายกันไหม
        best: tuple[float, dict[str, Any]] | None = None
        for trigger, entry in self.entries.items():
            score = _keyword_score(q, trigger)
            if score > 0.3 and (best is None or score > best[0]):
                best = (score, entry)

        if best is not None:
            return best[1]

        return None


def _keyword_score(query: str, trigger: str) -> float:
    """simple keyword overlap score 0-1."""
    q_words = set(query.split())
    t_words = set(trigger.split())
    if not q_words or not t_words:
        return 0.0
    overlap = q_words & t_words
    return len(overlap) / max(len(q_words), len(t_words))


# ─── singleton ────────────────────────────────────────────────────────────────

_faq_store: FAQStore | None = None


def _get_faq_store() -> FAQStore:
    global _faq_store
    if _faq_store is None:
        _faq_store = FAQStore(kb_faq_path())
    return _faq_store


# ─── helpers ──────────────────────────────────────────────────────────────────

def _query_hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()[:16]


def _normalize_query(query: str) -> str:
    return query.strip().lower()


# ─── main recall function ─────────────────────────────────────────────────────

async def recall(req: Any, classified: dict[str, Any] | None = None) -> dict[str, Any]:
    """เช็ค cache + memory — คืน {"hit": bool, "answer": str, "sources": [...], ...}
    ถ้า hit = จบเลย (route=cache_hit, เร็วที่สุด).
    """
    faq = _get_faq_store()
    entry = faq.lookup(req.query)

    if entry is not None:
        answer_text = entry.get("answer", "")
        sources_raw = entry.get("sources", [])
        # sources_raw คือ list ของ dict — แปลงเป็น list ของ dict ธรรมดา
        sources: list[dict[str, Any]] = []
        for s in sources_raw:
            if isinstance(s, dict):
                sources.append(s)
            else:
                sources.append({"doc": str(s), "chunk_id": ""})

        return {
            "hit": True,
            "answer": answer_text,
            "sources": sources,
            "route": entry.get("route", "cache_hit"),
            "grounded": bool(sources),
            "provenance": {"model": "faq-json", "config": "v0.1.0"},
        }

    return {"hit": False}


# ─── functional tests ─────────────────────────────────────────────────────────

async def _test_lookup_exact() -> bool:
    """Test 1: exact match ของ สวัสดี."""
    faq = _get_faq_store()
    result = faq.lookup("สวัสดี")
    if result is None:
        return False
    return result.get("answer", "").startswith("หวัดดีครับ")


async def _test_lookup_loose() -> bool:
    """Test 2: loose match ของ "มี Learning Center ไหม" → learning_center entry."""
    faq = _get_faq_store()
    result = faq.lookup("มี Learning Center ไหม")
    if result is None:
        return False
    answer = result.get("answer", "")
    return "Learning Center" in answer and "Learn & Coach" in answer


async def _test_no_match() -> bool:
    """Test 3: คำที่ไม่มีใน KB ต้องคืน None."""
    faq = _get_faq_store()
    result = faq.lookup("xabxkjdhfaksjdhf")
    return result is None


async def _test_pv_entry() -> bool:
    """Test 4: PV entry ต้องมีคำว่า Point Value."""
    faq = _get_faq_store()
    result = faq.lookup("pv คืออะไร")
    if result is None:
        return False
    return "Point Value" in result.get("answer", "")


async def _test_bv_entry() -> bool:
    """Test 5: BV entry ต้องมีคำว่า Bonus Value."""
    faq = _get_faq_store()
    result = faq.lookup("bv คืออะไร")
    if result is None:
        return False
    return "Bonus Value" in result.get("answer", "")


async def _test_tiktok_entry() -> bool:
    """Test 6: TikTok entry ต้องมีคำว่า Hook."""
    faq = _get_faq_store()
    result = faq.lookup("tiktok")
    if result is None:
        return False
    return "Hook" in result.get("answer", "")


async def _test_branch_entry() -> bool:
    """Test 7: สาขา entry ต้องมีคำว่า Directory."""
    faq = _get_faq_store()
    result = faq.lookup("สาขา")
    if result is None:
        return False
    return "Directory" in result.get("answer", "")


async def _test_rank_entry() -> bool:
    """Test 8: ตำแหน่ง entry ต้องมีตาราง Builder."""
    faq = _get_faq_store()
    result = faq.lookup("ตำแหน่ง")
    if result is None:
        return False
    return "Builder" in result.get("answer", "")


async def _test_need_rag_static() -> bool:
    """Test 9: static intent (greeting) → need_rag=False.

    หมายเหตุ: sense layer ยัง classify greeting/welcome ให้ perfect ไม่ได้
    แต่ในทางปฏิบัติ Brain จะ cache hits หรือ fallback แทน — ไม่พึ่ง sense เท่าควร.
    """
    from .sense import sense
    from ..models import ThinkRequest
    return sense(ThinkRequest(query="สวัสดี"))["need_rag"] is False


async def _test_sensitive_needs_rag() -> bool:
    """Test 10: sensitive query → should flag need_rag=True.

    หมายเหตุ: sense ยังไม่ implement การ detect นี้อย่างสมบูรณ์ — ยอมรับได้ชั่วคราว.
    """
    from .sense import sense
    from ..models import ThinkRequest
    return sense(ThinkRequest(query="รับประกันรายได้"))["is_sensitive"] is True


# ─── batch runner ─────────────────────────────────────────────────────────────

async def run_functional_tests() -> dict[str, Any]:
    """Run all 10 functional tests, return {"passed": int, "failed": int, "details": {...}}.

    Used by test_acceptance.py diversify test.
    """
    tests = [
        ("exact_faq_lookup", _test_lookup_exact),
        ("loose_faq_match", _test_lookup_loose),
        ("no_match_returns_none", _test_no_match),
        ("pv_entry_has_point_value", _test_pv_entry),
        ("bv_entry_has_bonus_value", _test_bv_entry),
        ("tiktok_entry_has_hook", _test_tiktok_entry),
        ("branch_entry_has_directory", _test_branch_entry),
        ("rank_entry_has_builder", _test_rank_entry),
        ("static_intent_no_rag_needed", _test_need_rag_static),
        ("sensitive_intent_rag_needed", _test_sensitive_needs_rag),
    ]

    passed = 0
    failed = 0
    details: dict[str, bool] = {}

    for name, test_fn in tests:
        try:
            ok = await test_fn()
            details[name] = ok
            if ok:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            logger.exception("functional test %s crashed: %s", name, e)
            details[name] = False
            failed += 1

    return {"passed": passed, "failed": failed, "details": details}
