"""LINE integration — ส่งอวยพรวันเกิดไปหา LINE user.

ใช้ jarvis_line.py จาก jarvis-pipeline — push_text + push_audio
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("brain.line")

# Add jarvis-pipeline to path for jarvis_line import
_PIPELINE_DIR = Path(os.environ.get(
    "JARVIS_PIPELINE_DIR",
    str(Path.home() / "jarvis-pipeline"),
))
if _PIPELINE_DIR.exists() and str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

try:
    import jarvis_line
    _LINE_AVAILABLE = True
    logger.info("LINE module loaded from %s", _PIPELINE_DIR)
except ImportError as e:
    _LINE_AVAILABLE = False
    logger.warning("LINE module not available: %s", e)


def send_birthday_wish(
    user_id: str | None = None,
    wish_text: str = "",
    audio_path: str | None = None,
) -> dict[str, Any]:
    """ส่งอวยพรวันเกิดไปหา LINE user.

    Args:
        user_id: LINE MID ของ user (ถ้าไม่ระบุ ส่งไป default)
        wish_text: ข้อความอวยพร
        audio_path: path ไฟล์เสียง (ถ้ามี)

    Returns:
        {"pushed": bool, "status": int, "detail": str}
    """
    if not _LINE_AVAILABLE:
        logger.warning("LINE not available — cannot send birthday wish")
        return {"pushed": False, "status": 0, "detail": "LINE module not available"}

    if not wish_text:
        wish_text = (
            "🎂 สุขสันต์วันเกิดนะครับ! 🎉\n\n"
            "ขอให้มีความสุข สุขภาพแข็งแรง สมหวังทุกสิ่งครับ!\n\n"
            "— JC SMART 🧠 และทีมงาน J&C"
        )

    results = []

    # 1. Push text
    try:
        status, detail = jarvis_line.push_text(wish_text, to=user_id)
        results.append({"type": "text", "status": status, "detail": detail})
        logger.info("LINE push_text: %s %s", status, detail[:100])
    except Exception as e:
        logger.warning("LINE push_text failed: %s", e)
        results.append({"type": "text", "status": 0, "detail": str(e)})

    # 2. Push audio (ถ้ามี) — reserved for future TTS integration
    if audio_path and Path(audio_path).exists():
        logger.info("Audio push pending — would send: %s", audio_path)

    pushed = any(r.get("status") == 200 for r in results)
    return {
        "pushed": pushed,
        "results": results,
        "detail": "; ".join(r.get("detail", "")[:80] for r in results),
    }
