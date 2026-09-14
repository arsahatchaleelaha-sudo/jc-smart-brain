"""Reason layer — LLM generation จาก chunks + citation."""

from __future__ import annotations

import logging
from typing import Any

import anthropic
import asyncio

from ..config import settings, data_dir
from ..models import ThinkRequest

logger = logging.getLogger("brain.reason")


# ─── LLM client ────────────────────────────────────────────────────────────────


class LLMClient:
    """Anthropic API wrapper — ใช้ Haiku สำหรับ classify/compliance, Sonnet สำหรับ reason."""

    def __init__(self, api_key: str) -> None:
        self.client = anthropic.Anthropic(api_key=api_key)

    def classify(self, query: str, context: str = "") -> dict[str, Any]:
        """classify intent / ตัดสินใจว่าต้อง RAG ไหม — Haiku, temp 0."""

        system = "คุณเป็นผู้ช่วย classifier สำคัญที่สุดสำหรับธุรกิจ J&C 태국語 มีหน้าที่วิเคราะห์คำถามและจัดประเภท เป็น 3 งาน: 1) จำแนก intent (general, product, faq, member, business, support, learning) 2) ตัดสินว่าต้องค้นหา knowledge base (RAG) หรือตอบจาก canonical เท่านั้น 3) บอกว่าคำถามนี้ sensitive ไหม (รายได้, สุขภาพ, ยา, เป็นทางการ)"

        user = f"คำถาม: {query}\n\nบริบท: {context}\n\nให้ตอบ JSON เท่านั้น: {{\"intent\": \"...\", \"need_rag\": true/false, \"sensitive\": true/false, \"confidence\": 0.0-1.0}}"

        try:
            resp = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                temperature=0.0,
                system=system,
                messages=[{"role": "user", "content": [{"type": "text", "text": user}]}],
            )
            import json
            text = resp.content[0].text
            # ล้าง markdown fencing ถ้ามี
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            return json.loads(text)
        except Exception as e:
            logger.warning("classify failed: %s", e)
            return {"intent": "general", "need_rag": False, "sensitive": False, "confidence": 0.0}

    def answer(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate answer จาก chunks + citation — Sonnet, temp 0.3.

        นี่คือ sync function — เรียกจาก asyncio.to_thread ใน reason().
        """

        system = (
            "คุณเป็นผู้ช่วยอัจฉริยะสำหรับธุรกิจ J&C (Join & Coin Corporation) "
            "ไทย語 แรก มีหน้าที่ตอบคำถามจากข้อมูลใน knowledge base เท่านั้น — "
            "ห้ามแต่ง, ห้ามคาดเดา, ถ้าไม่มีข้อมูลให้บอกว่าไม่พบ\n\n"
            "กฎสำคัญ:\n"
            "1. ตอบจาก chunks ที่ให้มาเท่านั้น — แนบ citation ทุกครั้ง (doc, chunk_id)\n"
            "2. ภาษาท่าทาง: เป็นกันเอง มีความรู้ มั่นใจ เหมาะกับผู้ใช้ LINE/มือถือ\n"
            "3. ให้ข้อมูลเสริมเมื่อจำเป็น: ช่องทางติดต่อ, ขั้นตอนต่อไป\n"
            "4. ถ้าไม่มีข้อมูลใน chunks: บอกว่าไม่พบ + เสนอทางเลือก (ถามเรื่องอื่น, ติดต่อเจ้าหน้าที่, เรียนรู้)\n"
            "5. ห้ามกล่าวอ้างรักษาโรค, รับประกันรายได้, หรือสรุปผลการทดลองจากงานวิจัยเป็นผลในคน\n"
            "6. สำหรับ product query: ให้ชื่อ, หมวด, PV (ถ้ามีใน chunks), และข้อควรระวังตามฉลาก\n"
            "7. สำหรับ member query: ให้อธิบายระบบ แต่ไม่ระบุค่าส่วนบุคคล\n"
            "8. ทำ JSON output ดังนี้เสมอ - {\"answer\": \"...\", \"sources\": [{\"doc\": \"...\", \"chunk_id\": \"...\"}]}\n"
            "และตอบใน markdown พร้อม citation ในวงเล็บครับ"
        )

        # chunks → context
        context_chunks = []
        for c in chunks:
            text = c.get("text", "")
            doc = c.get("source", {}).get("doc", "unknown")
            chunk_id = c.get("id", "unknown")
            if text:
                context_chunks.append(f"[แหล่งที่มา: {doc}#{chunk_id}]\n{text}")

        user = f"คำถาม: {query}\n\nข้อมูลที่มี:\n\n" + "\n\n".join(context_chunks) + "\n\nให้ตอบคำถามนี้โดยอ้างอิงแหล่งที่มาในข้างบนเท่านั้น หากไม่พบข้อมูลที่ต้องการในแหล่งที่มา ให้บอกว่าไม่พบและแนะนำทางเลือก"

        try:
            resp = self.client.messages.create(
                model="claude-sonnet-4-5-20251001",
                max_tokens=1024,
                temperature=0.3,
                system=system,
                messages=[{"role": "user", "content": [{"type": "text", "text": user}]}],
                timeout=15.0,  # 15 วินาที — มากพอให้ Sonnet ตอบ แต่ไม่ให้ติด forever
            )
            import json
            answer_text = resp.content[0].text.strip()
            # ล้าง markdown fencing
            if answer_text.startswith("```"):
                answer_text = answer_text.split("\n", 1)[1]
            if answer_text.endswith("```"):
                answer_text = answer_text[:-3]
            # ล้าง leading/trailing whitespace
            answer_text = answer_text.strip()

            # ลอง parse JSON output (ถ้า model ทำตาม instruction)
            sources: list[dict[str, Any]] = []
            final_answer = answer_text
            try:
                parsed = json.loads(answer_text)
                if isinstance(parsed, dict) and "answer" in parsed:
                    final_answer = parsed["answer"]
                    sources = parsed.get("sources", [])
                elif isinstance(parsed, list):
                    # ถ้า model ตอบ array — เอาตัวแรก
                    if parsed:
                        first = parsed[0]
                        if isinstance(first, dict) and "answer" in first:
                            final_answer = first["answer"]
                            sources = first.get("sources", [])
            except (json.JSONDecodeError, Exception):
                # ไม่ใช่ JSON — คือ markdown response ปกติ — ดึง sources จาก citation ใน text
                import re
                source_pattern = re.compile(r"แหล่งที่มา:\s*(.+?)(?:\[\w+#|`)")
                for m in source_pattern.finditer(answer_text):
                    doc = m.group(1).strip()
                    sources.append({"doc": doc, "chunk_id": "auto"})

            cost = _estimate_cost(resp)
            return {
                "answer": final_answer,
                "sources": sources,
                "cost": cost,
                "provenance": {"model": "claude-sonnet-4-5", "config": "v0.1.0"},
            }
        except Exception as e:
            logger.warning("answer failed: %s", e)
            return {
                "answer": "ขออภัยครับ เกิดข้อผิดพลาดขณะประมวลผลคำถาม กรุณาลองใหม่ในครู่หน้าครับ",
                "sources": [],
                "cost": 0.0,
                "provenance": {"model": "fallback", "config": "v0.1.0"},
            }


def _estimate_cost(resp: anthropic.types.Message) -> float:
    """ประมาณ cost จาก token count — ใช้ราคาปัจจุบัน (USD)."""

    try:
        usage = resp.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        # Claude Sonnet 4.5: ~$3/$15 ต่อ 1M tokens (input/output)
        cost = (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0
        return round(cost, 6)
    except Exception:
        return 0.0


_client: LLMClient | None = None


def _get_client() -> LLMClient | None:
    global _client
    if _client is None:
        key = settings().anthropic_api_key
        if key:
            try:
                _client = LLMClient(key)
            except Exception as e:
                logger.warning("llm client init failed: %s", e)
    return _client


# ─── Public API ───────────────────────────────────────────────────────────────


async def reason(
    req: ThinkRequest,
    chunks: list[dict[str, Any]],
    classified: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate answer จาก chunks — ใช้ Sonnet ถ้ามี API key, fallback เป็น chunks-only."""

    client = _get_client()

    if client is None:
        logger.debug("no LLM client — fallback to chunks-only")
        answer = _chunks_to_answer(req.query, chunks)
        return {
            "answer": answer,
            "sources": [c.get("source", {}) for c in chunks if c.get("source")],
            "cost": 0.0,
            "provenance": {"model": "chunks-only", "config": "v0.1.0"},
        }

    # มี client — เรียก Sonnet แบบไม่ block event loop
    result = await asyncio.to_thread(
        client.answer, req.query, chunks, req.options
    )
    return result


def _chunks_to_answer(query: str, chunks: list[dict[str, Any]]) -> str:
    """เมื่อไม่มี LLM — รวม chunks เป็นคำตอบพื้นฐาน."""

    if not chunks:
        return "ขออภัยครับ ผมไม่พบข้อมูลที่ยืนยันได้ในระบบสำหรับคำถามนี้ครับ\n\nแนะนำให้ตรวจสอบกับเจ้าหน้าที่ J&C หรือทักใน LINE @jcgroupthai เพื่อยืนยันครับ"

    # รวม chunks แรกๆ
    parts = []
    for c in chunks[:3]:
        text = c.get("text", "").strip()
        if text:
            parts.append(text)

    if not parts:
        return "ขออภัยครับ ผมไม่พบข้อมูลที่ยืนยันได้ในระบบสำหรับคำถามนี้ครับ"

    # เขียนคำตอบจาก chunks
    answer = "จากข้อมูลในระบบ:\n\n"
    for p in parts:
        # ตัดหัวข้อซ้ำ
        if len(p) > 300:
            p = p[:300] + "..."
        answer += f"- {p}\n"

    if len(answer) > 1000:
        answer = answer[:1000] + "\n...\n(ข้อมูลเพิ่มเติมกรุณาติดต่อเจ้าหน้าที่ J&C)"

    return answer
