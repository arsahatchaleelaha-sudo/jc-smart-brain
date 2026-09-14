"""FastAPI app — endpoint /brain + health + root."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .config import settings
from .models import ThinkRequest, ThinkResponse, SourceDoc, ComplianceResult
from .pipeline import think
from .layers.guard import guard as guard_fn
from .integrations.line_birthday import send_birthday_wish

logger = logging.getLogger("brain")


def create_app() -> FastAPI:
    app = FastAPI(
        title="JC SMART Brain",
        description="สมองกลางที่ Jwiz และ agent อื่นเรียกใช้ — cache-first, grounded, compliance-guarded",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": "jc-smart-brain", "version": "0.1.0"}

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "jc-smart-brain",
            "env": settings().brain_env,
            "version": "0.1.0",
            "ts": time.time(),
        }

    @app.post("/brain", response_model=ThinkResponse, response_model_exclude_none=True)
    async def brain_endpoint(req: ThinkRequest) -> ThinkResponse:
        """สมองกลาง — รับคำถามมา คิด ตอบ โดยยึด grounded + compliance."""

        t0 = time.perf_counter()
        try:
            resp: ThinkResponse = await think(req)
        except Exception as exc:
            logger.exception("brain error: %s", exc)
            # Fallback: ตอบแบบปลอดภัย ถ้า system ล่ม
            resp = ThinkResponse(
                answer="ขออภัยครับ ขณะนี้ระบบกำลังประมวลผล กรุณาลองใหม่ในครู่หน้าครับ",
                sources=[],
                compliance=ComplianceResult(passed=True, flags=[]),
                grounded=False,
                route="fallback",
                cost=0.0,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                provenance={"model": "fallback", "config": "v0.1.0"},
            )
        resp.latency_ms = int((time.perf_counter() - t0) * 1000)
        return resp

    @app.post("/brain/birthday")
    async def birthday_endpoint(req: dict[str, Any]) -> dict[str, Any]:
        """ส่งอวยพรวันเกิดไปหา LINE user.

        Body: {"user_id": "LINE_MID", "wish_type": "general|partner|customer|short|long|funny|formal|line", "custom_text": "optional"}
        """
        import json
        from pathlib import Path

        user_id = req.get("user_id")
        wish_type = req.get("wish_type", "general")
        custom_text = req.get("custom_text", "")

        # Load birthday wishes
        faq_path = settings().kb_faq_path
        with open(faq_path, "r", encoding="utf-8") as f:
            faq = json.loads(f.read())

        birthdays = faq.get("birthdays", {})

        # Map wish_type to trigger key
        type_map = {
            "general": "อวยพรวันเกิด",
            "partner": "อวยพรวันเกิด พาร์ทเนอร์",
            "team": "อวยพรวันเกิด ลูกทีม",
            "customer": "อวยพรวันเกิด ลูกค้า",
            "leader": "อวยพรวันเกิด ผู้นำ",
            "short": "อวยพรวันเกิด สั้นๆ",
            "long": "อวยพรวันเกิด ยาวๆ",
            "funny": "อวยพรวันเกิด ตลกๆ",
            "formal": "อวยพรวันเกิด ทางการ",
            "line": "อวยพรวันเกิด กลุ่ม LINE",
        }

        trigger = type_map.get(wish_type, "อวยพรวันเกิด")
        entry = birthdays.get(trigger, birthdays.get("อวยพรวันเกิด", {}))
        wish_text = custom_text if custom_text else entry.get("answer", "🎂 สุขสันต์วันเกิดนะครับ!")

        # Send via LINE
        result = send_birthday_wish(
            user_id=user_id,
            wish_text=wish_text,
        )

        return {
            "status": "ok" if result.get("pushed") else "error",
            "wish_type": wish_type,
            "wish_text": wish_text[:100],
            "user_id": user_id or "default",
            "pushed": result.get("pushed"),
            "detail": result.get("detail", ""),
        }

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc: Exception):
        logger.exception("unhandled: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal error"},
        )


# Instantiate at module level so `uvicorn brain.main:app` works.
app = create_app()
