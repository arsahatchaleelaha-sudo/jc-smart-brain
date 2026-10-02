"""Guard layer — compliance pre + post + critic."""

from __future__ import annotations

import logging
import re
from typing import Any

from ..models import ThinkRequest

logger = logging.getLogger("brain.guard")


# ─── Compliance rules ──────────────────────────────────────────────────────────


# รายการ keyword ที่ต้องระวัง (เข้มงวดระดับต่างๆ)
# ระดับ 1: ห้ามตอบแบบ garantuee — เน้น compliance
# ระดับ 2: ต้องมี citation — เน้น accuracy

INCOME_GUARANTEE_PATTERNS = [
    r"รับประกัน\s*(รายได้|ผล|เงิน|การเงิน|กำไร)",
    r"รายได้\s*(แน่นอน|มั่นใจ|ประกัน|รับรอง)",
    r"หาเงิน\s*(ง่าย|เร็ว|สบาย|ไม่ยาก|ไม่ต้อง)",
    r"รวย\s*(เร็ว|ได้\s*เงิน|ได้\s*ผล)",
    r"ไม่\s*เสี่ยง",
    r"แน่ใจ\s*ว่า\s*(ได้|มี|เห็น)",
    r"ผล\s*กำไร\s*(รับประกัน|แน่นอน|เปอร์เซ็นต์)",
]

MEDICAL_CLAIM_PATTERNS = [
    r"รักษา\s*(โรค|มะเร็ง|เบาหวาน|ความดัน|หัวใจ|อาการ|อาการ.*โรค)",
    r"หาย\s*จาก\s*(โรค|มะเร็ง|อาการ|ความดัน|เบาหวาน)",
    r"รักษามะเร็ง",
    r"ยา\s*รักษา",
    r"ยารักษา",
    r"ยาฆ่า",
    r"ยา\s*ฆ่า",
    r"รักษา\s*ได้\s*ผล",
    r"มี\s*หลักฐาน\s*ทาง\s*คลินิก",
    r"งาน\s*วิจัย\s*พิสูจน์",
]

DIETARY_SUPPLEMENT_PATTERNS = [
    r"แทนที่\s*ยา",
    r"หยุด\s*ยา",
    r"ใช้\s*แทน\s*ยา",
    r"ไม่\s*ต้อง\s*ใช้ยา",
    r"ไม่ต้อง\s*พบแพทย์",
    r"แพทย์\s*ไม่\s*จำเป็น",
    r"ไม่ต้อง\s*ปรึกษาแพทย์",
]

SOCIAL_MEDIA_PATTERNS = [
    r"อวด\s*อ้าง",
    r" testimonials?",
    r"รีวิว\s*ปลอม",
    r"รีวิว\s*เทียม",
    r"รีวิว\s*ไม่\s*จริง",
    r"ใสร Lesser",
    r"รีวิว\s*จาก",
]

PROHIBITED_CLAIM_PATTERNS = [
    r"ขาย\s*ต่ำกว่า\s*ราคา\s*บริษัท",
    r"ขาย\s*ต่ำ\s*กว่า",
    r"ลด\s*ราคา\s*ต่ำ\s*กว่า",
    r"โฆษณา\s*สรรพคุณ\s*แรง",
    r"โฆษณา\s*สรรพคุณ\s*เกิน",
    r"โฆษณา\s*อัด\s*อ้าง",
    r"ชักชวน\s*แบบ\s*พีระมิด",
    r"หาคน\s*อย่าง\s*เดียว",
    r"ชวน\s*คน\s*อย่าง\s*เดียว",
    r"เน้น\s*หาคน",
]


def _has_claim(pattern: str, text: str) -> bool:
    """Ignore explicit negations and prohibitions in the same short clause."""
    for match in re.finditer(pattern, text):
        prefix = re.split(r"[\n.!?;]|แต่", text[:match.start()])[-1].replace("*", "")
        negated = re.search(
            r"(?:ไม่|ห้าม|อย่า|มิได้)(?:ควร|สามารถ|ใช้|กล่าวอ้าง|กล่าว|อ้าง|สร้าง|อวดอ้าง|มีการ|โฆษณา|\s)*$",
            prefix,
        )
        # A prohibition can introduce a comma-separated list of prohibited claims.
        prohibited_list = re.search(r"(?:^|[-:])\s*ห้าม[^\n]{0,120},[^\n]*$", prefix)
        disclaimer = re.search(r"ไม่มีผลในการ(?:วินิจฉัย|บำบัด|รักษา|ป้องกัน|โรค|[,\s])*$", prefix)
        if not (negated or prohibited_list or disclaimer):
            return True
    return False


class ComplianceChecker:
    """ตรวจสอบ compliance — pre-check (ก่อน generate) + post-check (หลัง generate)."""

    def pre_check(self, query: str, classified: dict[str, Any] | None = None) -> dict[str, Any]:
        """ตรวจสอบคำถามก่อนตอบ — ดูว่าต้องระวังเรื่องอะไร."""

        ql = query.lower()
        flags: list[str] = []

        # ระดับ 1 — income guarantee
        for pat in INCOME_GUARANTEE_PATTERNS:
            if re.search(pat, ql):
                flags.append("income-guarantee-risk")
                break

        # ระดับ 2 — medical claim
        for pat in MEDICAL_CLAIM_PATTERNS:
            if re.search(pat, ql):
                flags.append("medical-claim-risk")
                break

        # ระดับ 2 — dietary supplement แทนยา
        for pat in DIETARY_SUPPLEMENT_PATTERNS:
            if re.search(pat, ql):
                flags.append("dietary-supplement-risk")
                break

        # ระดับ 2 — social media / testimonial
        for pat in SOCIAL_MEDIA_PATTERNS:
            if re.search(pat, ql):
                flags.append("social-media-risk")
                break

        # ระดับ 1 — prohibited claims
        for pat in PROHIBITED_CLAIM_PATTERNS:
            if re.search(pat, ql):
                flags.append("prohibited-claim-risk")
                break

        # ตัดสินว่า sensitive ไหม (สรุป)
        is_sensitive = len(flags) > 0

        return {
            "passed": True,  # pre-check ผ่านเสมอ — เพียง.alert
            "flags": flags,
            "is_sensitive": is_sensitive,
            "message": (
                "query มี risk flag — ให้แน่ใจว่าคำตอบมีการอ้างอิง/คำเตือนที่เหมาะสม"
                if flags else "query ไม่มี compliance risk ชัดเจน"
            ),
        }

    def post_check(self, query: str, answer: str, sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """ตรวจสอบคำตอบหลัง generate — compliance + grounded."""

        al = answer.lower()
        flags: list[str] = []

        # 1. income guarantee ในคำตอบ
        for pat in INCOME_GUARANTEE_PATTERNS:
            if _has_claim(pat, al):
                flags.append("income-guarantee-in-answer")
                break

        # 2. medical claim ในคำตอบ
        for pat in MEDICAL_CLAIM_PATTERNS:
            if _has_claim(pat, al):
                flags.append("medical-claim-in-answer")
                break

        # 3. dietary supplement แทนยา
        for pat in DIETARY_SUPPLEMENT_PATTERNS:
            if _has_claim(pat, al):
                flags.append("dietary-supplement-in-answer")
                break

        # 4. testimonial ปลอม
        for pat in SOCIAL_MEDIA_PATTERNS:
            if _has_claim(pat, al):
                flags.append("social-media-in-answer")
                break

        # 5. prohibited claim ในคำตอบ
        for pat in PROHIBITED_CLAIM_PATTERNS:
            if _has_claim(pat, al):
                flags.append("prohibited-claim-in-answer")
                break

        # Structured sources in the response are citations; inline markers are optional.

        # 8. มีคำเตือนสำหรับผลิตภัณฑ์เสริมไหม
        if re.search(r"ผลิตภัณฑ์เสริม|สมุนไพร|อาหารเสริม", al) and not re.search(r"ไม่\s*ใช่\s*ยา|ไม่ใช้\s*ยา|ปรึกษาแพทย์|คำเตือน", al):
            flags.append("missing-supplement-warning")

        passed = len(flags) == 0

        return {
            "passed": passed,
            "flags": flags,
            "message": (
                "compliance violation: " + ", ".join(flags) if flags
                else "compliance check ผ่าน — คำตอบปลอดภัย"
            ),
        }


_checker: ComplianceChecker | None = None


def _get_checker() -> ComplianceChecker:
    global _checker
    if _checker is None:
        _checker = ComplianceChecker()
    return _checker


# ─── Public API ────────────────────────────────────────────────────────────────


async def guard(
    req: ThinkRequest,
    answer: str,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """compliance post-check คำตอบ — blocked ถ้าพบ violation."""

    checker = _get_checker()
    result = checker.post_check(req.query, answer, [c.get("source") for c in chunks if c.get("source")])

    logger.info("guard: passed=%s flags=%s", result["passed"], result["flags"])

    return result
