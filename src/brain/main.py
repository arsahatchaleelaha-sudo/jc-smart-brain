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

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc: Exception):
        logger.exception("unhandled: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal error"},
        )


# Instantiate at module level so `uvicorn brain.main:app` works.
app = create_app()
