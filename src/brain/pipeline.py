"""Pipeline — orchestrate 6 layers: sense → recall → ground → reason → guard → learn.

SENSE + RECALL ทำแบบขนานกันได้ (ทั้งคู่คำนวณจาก req อย่างเดียว).
ถ้า cache hit — จบเลย (route=cache_hit, เร็วที่สุด).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import settings
from .models import ThinkRequest, ThinkResponse, SourceDoc, ComplianceResult

logger = logging.getLogger("brain")

# layer imports — อาจยังไม่มีทุกชั้นตอนเริ่มต้น แต่ pipeline ต้องรันได้โดยข้ามชั้นที่ยังไม่พร้อม
try:
    from .layers.sense import sense
except ImportError:
    sense = None
try:
    from .layers.recall import recall
except ImportError:
    recall = None
try:
    from .layers.ground import ground
except ImportError:
    ground = None
try:
    from .layers.reason import reason
except ImportError:
    reason = None
try:
    from .layers.guard import guard
except ImportError:
    guard = None
try:
    from .layers.learn import learn
except ImportError:
    learn = None


def _determine_route(
    reason_available: bool,
    chunks: list[dict[str, Any]],
    used_reason: bool,
) -> str:
    """กำหนด route ตามสิ่งที่เกิดขึ้นจริง."""
    if not chunks:
        return "fallback"
    if reason_available and used_reason:
        return "llm_reason"
    if chunks and not reason_available:
        return "chunks-only"
    # reason available but not used (no chunks, or guard blocked)
    if reason_available and not used_reason:
        return "fallback"
    return "chunks-only"


async def think(req: ThinkRequest) -> ThinkResponse:
    """วิ่งผ่าน 6 layers — SENSE+RECALL ทำแบบขนานกันได้.

    ถ้า cache hit — จบเลย (route=cache_hit, เร็วที่สุด, ฿0).
    ถ้าไม่ hit — วิ่ง GROUND → REASON → GUARD → LEARN.
    """

    arithmetic = _calculate(req.query)
    if arithmetic is not None:
        return ThinkResponse(
            answer=arithmetic, compliance=ComplianceResult(passed=True),
            grounded=False, route="calculator", provenance={"model": "calculator"},
        )

    # ── SENSE + RECALL: ทำแบบขนานกัน (ทั้งคู่ read-only จาก req) ──────────────
    sense_result: dict[str, Any] = {}
    cache_result: dict[str, Any] | None = None

    async def _run_sense() -> dict[str, Any]:
        if sense is not None:
            return sense(req)
        return {}

    async def _run_recall() -> dict[str, Any] | None:
        if recall is not None:
            return await recall(req, {})
        return None

    if sense is not None or recall is not None:
        s, r = await asyncio.gather(_run_sense(), _run_recall(), return_exceptions=True)
        if not isinstance(s, Exception):
            sense_result = s
        else:
            logger.warning("sense layer error: %s", s)
        if isinstance(r, dict):
            cache_result = r
        elif isinstance(r, Exception):
            logger.warning("recall layer error: %s", r)

    # ── ถ้า cache hit — จบเลย ───────────────────────────────────────────────────
    if cache_result and cache_result.get("hit"):
        cr = cache_result
        logger.info("recall: cache hit — returning fast (%s)", cr.get("route", "?"))
        checked = await guard(req, cr["answer"], [{"source": source} for source in cr.get("sources", [])]) if guard else {"passed": True, "flags": []}
        return ThinkResponse(
            answer=cr["answer"] if checked["passed"] else "ขออภัยครับ คำถามนี้ผมไม่สามารถตอบได้เนื่องจากเหตุผลด้านนโยบายครับ",
            sources=cr.get("sources", []),
            compliance=ComplianceResult(passed=checked["passed"], flags=checked["flags"]),
            grounded=cr.get("grounded", False),
            route=cr.get("route", "cache_hit"),
            cost=0.0,
            latency_ms=0,
            provenance={"model": cr.get("provenance", {}).get("model", "cache"), "config": "v0.1.0"},
        )

    logger.debug("sense result: need_rag=%s", sense_result.get("need_rag"))

    # ── 3. GROUND — hybrid retrieve (BM25 + vector) → chunks + sources ─────────
    chunks: list[dict[str, Any]] = []
    if ground is not None:
        chunks = await ground(req, sense_result)
        logger.info("ground: %d chunks", len(chunks))
    else:
        logger.debug("ground layer not ready — no retrieval")

    # ── 4. REASON — LLM generate จาก chunks เท่านั้น ────────────────────────────
    answer: str = ""
    provenance: dict[str, Any] = {}
    cost: float = 0.0
    used_reason = False
    if reason is not None and chunks:
        reason_result = await reason(req, chunks, sense_result)
        answer = reason_result.get("answer", "")
        provenance = reason_result.get("provenance", {})
        cost = reason_result.get("cost", 0.0)
        used_reason = provenance.get("model") not in ("chunks-only", "fallback")
        logger.info("reason: answer len=%d cost=%.4f", len(answer), cost)
    elif chunks:
        answer = _answer_from_chunks(req.query, chunks)
        provenance = {"model": "chunks-only", "config": "v0.1.0"}
        cost = 0.0
    else:
        answer = "ขออภัยครับ ผมไม่พบข้อมูลที่ยืนยันได้ในระบบสำหรับคำถามนี้ครับ"
        provenance = {"model": "fallback", "config": "v0.1.0"}
        cost = 0.0

    # ── 5. GUARD — compliance pre + post + critic ──────────────────────────────
    compliance_flags: list[str] = []
    compliance_passed = True
    if guard is not None:
        guard_result = await guard(req, answer, chunks)
        compliance_flags = guard_result.get("flags", [])
        compliance_passed = guard_result.get("passed", True)
        if not guard_result.get("passed", True):
            answer = "ขออภัยครับ คำถามนี้ผมไม่สามารถตอบได้เนื่องจากเหตุผลด้านนโยบายครับ"
            provenance["compliance_blocked"] = True
        logger.info("guard: passed=%s flags=%s", guard_result.get("passed", True), compliance_flags)
    else:
        logger.debug("guard layer not ready — skipping compliance post-check")

    response = ThinkResponse(
        answer=answer,
        sources=[SourceDoc(**c["source"]) for c in chunks if "source" in c] if chunks else [],
        compliance=ComplianceResult(passed=compliance_passed, flags=compliance_flags),
        grounded=bool(chunks) and provenance.get("model") != "fallback",
        route=("fallback" if provenance.get("model") == "fallback" else
               "chunks-only" if provenance.get("model") == "chunks-only" else
               _determine_route(reason is not None, chunks, used_reason)),
        cost=cost,
        latency_ms=0,
        provenance=provenance,
    )

    # ── 6. LEARN — เขียน memory, อัปเดต cache, feedback ───────────────────────
    if learn is not None:
        try:
            await learn(req, response)
        except Exception:
            logger.exception("memory write failed")
        logger.debug("learn: done")

    return response


def _answer_from_chunks(query: str, chunks: list[dict[str, Any]]) -> str:
    """สร้างคำตอบจาก chunks ตรงๆ (ใช้เมื่อ reason layer ยังไม่พร้อม)."""
    if not chunks:
        return "ไม่พบข้อมูล"
    parts = []
    for c in chunks[:5]:
        text = c.get("text", "")
        if text:
            parts.append(text.strip())
    if not parts:
        return "ไม่พบข้อมูล"
    combined = " ".join(parts)
    if len(combined) > 800:
        combined = combined[:800] + "..."
    return f"จากข้อมูลในระบบ: {combined}"


def _calculate(query: str) -> str | None:
    """Evaluate exactly two decimal operands without evaluating Python code."""
    import re
    from decimal import Decimal, localcontext
    match = re.fullmatch(
        r"\s*([+-]?\d+(?:\.\d+)?)\s*(บวก|ลบ|คูณ|หาร|[+*/×÷-])\s*"
        r"([+-]?\d+(?:\.\d+)?)\s*(?:เท่ากับ(?:เท่าไหร่|เท่าไร)?|=\s*\??)?\s*",
        query,
    )
    if not match:
        return None
    left, operator, right = match.groups()
    with localcontext() as ctx:
        ctx.prec = max(28, len(left) + len(right) + 10)
        a, b = Decimal(left), Decimal(right)
        if operator in ("/", "÷", "หาร") and b == 0:
            return "ไม่สามารถหารด้วยศูนย์ได้ครับ"
        if operator in ("+", "บวก"):
            result = a + b
        elif operator in ("-", "ลบ"):
            result = a - b
        elif operator in ("*", "×", "คูณ"):
            result = a * b
        else:
            result = a / b
    return f"{left} {operator} {right} = **{result:f}**"
