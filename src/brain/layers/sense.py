"""Sense layer — classify intent, ดูว่าต้อง RAG ไหม, sensitive ไหม."""

from __future__ import annotations

import logging
import re
from typing import Any

from ..models import ThinkRequest

logger = logging.getLogger("brain.sense")

# คำถามที่ไม่ต้อง RAG — ตอบจาก static/canonical ได้ทันที
STATIC_INTENTS: set[str] = {
    "greeting", "smalltalk", "bye", "thanks",
    "what_is_pv", "what_is_pt", "what_is_ppi",
    "product_catalog_list", "company_info",
    "support_handoff", "learning_center_exists",
    "math_simple", "weather",
}

# คำถาม sensitive — ต้องระวัง compliance
SENSITIVE_KEYWORDS: list[str] = [
    "รวย", "รับประกัน", "แน่นอน", " hundred ", "percent", "รักษามะเร็ง",
    "โรคมะเร็ง", "โรคหาย", "ล้างแค้น", "ผล 한정한다",
    "รายได้ Guarantee", "รับประกันรายได้", "รับประกันผล",
    "หายจาก", "รักษาโรค", "ยา", "ยารักษา",
]


def sense(req: ThinkRequest) -> dict[str, Any]:
    """Classify คำถาม → intent, ดูว่าต้อง RAG ไหม, sensitive ไหม."""

    q = req.query.strip()
    q_lower = q.lower()

    # ---- intent ----
    intent = _classify_intent(q, q_lower)

    # ---- sensitive ----
    is_sensitive = any(kw in q_lower for kw in SENSITIVE_KEYWORDS)

    # ---- ต้อง RAG ไหม ----
    #   static intents → ไม่ต้อง RAG
    #   sensitive → ต้องมี citation + compliance check (RAG ช่วยได้ แต่ไม่ใช่เงื่อนไข)
    #   มี keywords บ่งชี้ว่ามีคำตอบใน KB → RAG ช่วย
    need_rag = intent not in STATIC_INTENTS

    return {
        "intent": intent,
        "is_sensitive": is_sensitive,
        "need_rag": need_rag,
        "query_lower": q_lower,
    }


def _classify_intent(q: str, q_lower: str) -> str:
    """ทำ simple keyword + pattern classification."""

    # greeting / smalltalk
    if any(w in q_lower for w in ["สวัสดี", "หวัดดี", "เฮ้ย", " hey ", "hi", " hello ", " สวัสดี", "จ้ะ", "ครับ", "ค่ะ"]):
        if len(q) < 10:
            return "greeting"
        return "smalltalk"

    # farewell
    if any(w in q_lower for w in ["ลาก่อน", "บาย", "ไปก่อน", "goodbye"]):
        return "bye"

    # ขอบคุณ
    if any(w in q_lower for w in ["ขอบคุณ", " thank ", "thank you"]):
        return "thanks"

    # PV / PT / PPI
    if "pv" in q_lower or "pv/" in q_lower or "pv คือ" in q_lower:
        return "what_is_pv"
    if "pt" in q_lower and ("คือ" in q_lower or "อะไร" in q_lower):
        return "what_is_pt"
    if "ppi" in q_lower:
        return "what_is_ppi"

    # ผลิตภัณฑ์ / catalog
    if any(w in q_lower for w in ["สินค้า", "ผลิตภัณฑ์", "catalog", "product", "스康ภัณฑ์"]):
        if "ทั้งหมด" in q or "อะไรบ้าง" in q or "ทั้ง" in q or "all" in q_lower:
            return "product_catalog_list"
        return "product_query"

    # บริษัท
    if any(w in q_lower for w in ["บริษัท", "j&c", "join", "coin"]):
        return "company_info"

    # เรียนรู้ / coaching
    if any(w in q_lower for w in ["เรียนรู้", "학습", "เริ่ม", "start", "เริ่มต้น", "learning", "coach", "โค้ช", "อบรม", "training", "learning center", "ศูนย์การเรียนรู้"]):
        return "learning_center_exists"

    # สนับสนุน / ติดต่อ
    if any(w in q_lower for w in ["ติดต่อ", "contact", "เจ้าหน้าที่", "support", "ช่วย", "help"]):
        return "support_handoff"

    # อวยพรวันเกิด
    if any(w in q_lower for w in ["วันเกิด", "อวยพร", "happy birthday", "birthday"]):
        return "birthday_wish"

    # คณิตศาสตร์พื้นฐาน
    if _looks_like_math(q_lower):
        return "math_simple"

    # ค้นหา / ตรวจ (ไม่มี keyword เฉพาะ → intent ทั่วไป)
    return "general"


def _looks_like_math(text: str) -> bool:
    """ตรวจว่าข้อความนี้เป็นโจทย์คณิตศาสตร์หรือไม่ (รวม Thai + digit mix)."""
    import re

    # ตัวเลข + ตัวดำเนินการชัดเจน: + - × ÷
    if re.search(r"\d+\s*[+\-×÷]\s*\d+", text):
        return True
    # Thai operators
    if re.search(r"\d+\s*(บวก|ลบ|คูณ|หาร)\s*\d+", text):
        return True
    # มีทั้งตัวเลขและคำว่าเท่ากับ/เท่าไหร่
    if re.search(r"\d", text) and any(w in text for w in ["เท่ากับ", "เท่าไหร่", "ได้เท่าไหร่", "= ?"]):
        return True
    # โจทย์ phrased เป็นคำถามคณิต
    if re.search(r"(กี่|เท่าไหร่)\s*(บาท|เหรียญ|ผล?\s*รวม|ค่า|คำตอบ)", text):
        return True
    return False
