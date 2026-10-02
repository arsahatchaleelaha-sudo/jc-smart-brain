"""Learn layer — persist session responses and feedback."""

from __future__ import annotations

import logging
import time
from threading import RLock
from uuid import uuid4
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import ThinkRequest, ThinkResponse

logger = logging.getLogger("brain.learn")


# ─── Memory store (ก่อนจะทำ Postgres จริง — ใช้ JSON ไฟล์) ───────────────────


_memory_lock = RLock()

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
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MEMORY_PATH.with_suffix(".tmp")
    tmp.write_text(
        __import__("json").dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.rename(MEMORY_PATH)


def _write_memory(
    req: ThinkRequest,
    resp: ThinkResponse,
    feedback: str | None = None,
) -> None:
    """เขียน session + feedback ลง memory."""

    data = _load_memory()

    session_id = req.context.get("session_id") if req.context else None
    if session_id is None:
        session_id = f"mem-{uuid4().hex}"

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


def write_memory(req: ThinkRequest, resp: ThinkResponse, feedback: str | None = None) -> None:
    with _memory_lock:
        _write_memory(req, resp, feedback)


# ─── Public API ────────────────────────────────────────────────────────────────


async def learn(req: ThinkRequest, resp: ThinkResponse) -> None:
    """Persist the actual response when a caller supplies a session ID."""
    session_id = req.context.get("session_id") if req.context else None
    if isinstance(session_id, str) and session_id:
        write_memory(req, resp)
