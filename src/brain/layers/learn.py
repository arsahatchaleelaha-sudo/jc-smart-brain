"""Learn layer — memory write + cache update + feedback."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import settings, cache_file
from ..models import ThinkRequest, ThinkResponse

logger = logging.getLogger("brain.learn")


# ─── Memory store (ก่อนจะทำ Postgres จริง — ใช้ JSON ไฟล์) ───────────────────


MEMORY_PATH = Path("./data/brain_memory.json")


def _load_memory() -> dict[str, Any]:
    if not MEMORY_PATH.exists():
        return {"sessions": {}, "feedback": [], "ts": 0}
    import json
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        return data
    except Exception as e:
        logger.warning("memory load failed: %s", e)
        return {"sessions": {}, "feedback": [], "ts": 0}


def _save_memory(data: dict[str, Any]) -> None:
    tmp = MEMORY_PATH.with_suffix(".tmp")
    tmp.write_text(
        __import__("json").dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.rename(MEMORY_PATH)


def write_memory(
    req: ThinkRequest,
    resp: ThinkResponse,
    feedback: str | None = None,
) -> None:
    """เขียน session + feedback ลง memory."""

    data = _load_memory()

    session_id = req.context.get("session_id") if req.context else None
    if session_id is None:
        session_id = f"mem-{int(time.time() * 1000)}"

    data["sessions"][session_id] = {
        "ts": datetime.utcnow().isoformat(),
        "query": req.query,
        "agent_id": req.agent_id,
        "owner_id": req.owner_id,
        "answer": resp.answer,
        "route": resp.route,
        "cost": resp.cost,
        "latency_ms": resp.latency_ms,
        "grounded": resp.grounded,
        "compliance": resp.compliance.model_dump() if resp.compliance else {},
        "sources": [s.model_dump() for s in resp.sources],
    }

    if feedback:
        data["feedback"].append({
            "ts": datetime.utcnow().isoformat(),
            "session_id": session_id,
            "query": req.query,
            "feedback": feedback,
        })

    data["ts"] = time.time()
    _save_memory(data)
    logger.debug("memory: wrote session %s + feedback=%s", session_id, bool(feedback))


def update_cache(resp: ThinkResponse) -> None:
    """อัปเดต cache — semantic/FAQ entry สำหรับคำถามที่ตอบแล้ว."""

    # จะ update semantic cache เมื่อมี LLM response และไม่ใช่ fallback
    if resp.route in ("cache_hit", "fallback") or resp.cost == 0:
        return  # ไม่ต้อง update cache สำหรับ cache_hit หรือ fallback ฟรี

    # semantic cache — เก็บคำตอบ + sources + route
    from ..layers.recall import _get_cache, _query_hash, CacheEntry, SourceDoc

    cache = _get_cache()
    qh = _query_hash(resp.answer)  # ใช้ answer เป็น key (ไม่ควรรม truly — ควรใช้ query hash + answer hash)

    entry = CacheEntry(
        query_hash=qh,
        answer=resp.answer,
        sources=[SourceDoc(**s) for s in resp.sources],
        route=resp.route,
        ttl_hours=24,
    )
    cache.semantic_store(qh, entry)
    logger.debug("cache: updated semantic entry for %s", qh[:8])


# ─── Public API ────────────────────────────────────────────────────────────────


async def learn(
    req: ThinkRequest,
    answer: str,
    chunks: list[dict[str, Any]],
    compliance_flags: list[str],
) -> None:
    """Post-process — เขียน memory + อัปเดต cache."""

    # เขียน session (ถ้ามี session_id)
    session_id = req.context.get("session_id") if req.context else None
    if session_id:
        # สร้าง response ชั่วคราวสำหรับ memory write
        resp = ThinkResponse(
            answer=answer,
            sources=[c.get("source", {}) for c in chunks if c.get("source")],
            compliance={"passed": len(compliance_flags) == 0, "flags": compliance_flags},
            grounded=bool(chunks),
            route="llm",
            cost=0.0,
            latency_ms=0,
            provenance={},
        )
        write_memory(req, resp)

    # อัปเดต cache (ถ้าเป็น LLM response)
    # ใน pipeline จริง เราจะ pass resp เข้ามา — ที่นี่เราจะอัปเดตจาก answer เฉยๆ
    # (ชั่วคราวก่อนที่ pipeline จะเปลี่ยน)
