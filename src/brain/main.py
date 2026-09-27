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
            "status": "ok",
            "wish_type": wish_type,
            "wish_text": wish_text[:100],
            "user_id": user_id or "default",
            "pushed": result.get("pushed"),
            "detail": result.get("detail", ""),
        }

    @app.post("/brain/generate")
    async def generate_endpoint(req: dict[str, Any]) -> dict[str, Any]:
        """Generate image/video via Google Flow (useapi.net proxy).

        Body:
            {
                "type": "image|video|ugc",
                "prompt": "description",
                "model": "nano-banana-2-lite|veo-3.1-lite|omni-flash|...",
                "aspect_ratio": "16:9|9:16|landscape|portrait|1:1|...",
                "duration": 8,
                "count": 1,
                "output_dir": "/tmp/flow_out",
                "filename": "asset.jpg|asset.mp4",
                "scenes": [{"prompt": "...", "name": "scene1"}, ...],  # for type=ugc
                "async_mode": false,
                "email": "...",
            }

        Returns:
            For image/video:  {"status": "ok"|"error", "url": "...", "local_path": "...", "credits_remaining": int}
            For ugc:          {"status": "ok"|"error", "clips": [...], "errors": [...], "n_scenes": int, "n_success": int}
            When disabled:    {"status": "error", "detail": "USEAPI_TOKEN not set"}
        """
        import asyncio

        from brain.integrations.google_flow import (
            generate_image_sync,
            generate_video_sync,
            generate_and_download_image,
            generate_and_download_video,
            ugc_pipeline,
            is_available,
            extract_image_urls,
            extract_video_urls,
            _AVAILABLE,
            DEFAULT_IMAGE_MODEL,
            DEFAULT_VIDEO_MODEL,
        )

        # ── validation first (works even without token) ──────────────────────────
        gen_type = req.get("type", "image")
        prompt = req.get("prompt", "")

        # prompt required for image/video; ugc uses scenes instead
        if gen_type in ("image", "video") and not prompt:
            return {"status": "error", "detail": "prompt is required"}

        if gen_type not in ("image", "video", "ugc"):
            return {"status": "error", "detail": f"unknown type: {gen_type!r}"}

        if gen_type == "ugc":
            # "scenes" key must be present and be a list
            if "scenes" not in req:
                return {"status": "error", "detail": "scenes array required for type=ugc"}
            scenes_raw = req["scenes"]
            if scenes_raw is None or not isinstance(scenes_raw, list):
                return {"status": "error", "detail": "scenes array required for type=ugc"}
            scenes = [{"prompt": s.get("prompt", ""), "name": s.get("name", "")} for s in scenes_raw]
            scenes = [s for s in scenes if s["prompt"]]
            if not scenes:
                return {"status": "error", "detail": "no valid scenes with prompt"}
        else:
            scenes = []

        # ── token check (after validation) ───────────────────────────────────────
        # For ugc, we still run ugc_pipeline to get shape keys (clips/errors/n_scenes/n_success)
        # even without a token — the pipeline will fail gracefully per-scene.

        model = req.get("model") or None
        aspect_ratio = req.get("aspect_ratio") or None
        duration = req.get("duration", 8)
        count = req.get("count", 1)
        out_dir = req.get("output_dir", "/tmp/google_flow_out")
        filename = req.get("filename") or None
        async_mode = req.get("async_mode", False)
        email = req.get("email") or None

        if gen_type == "image":
            if not _AVAILABLE:
                return {"status": "error", "detail": "Google Flow integration disabled — USEAPI_TOKEN not set"}
            result = generate_and_download_image(
                prompt=prompt,
                out_dir=out_dir,
                filename=filename or "image.jpg",
                model=model or DEFAULT_IMAGE_MODEL,
                aspect_ratio=aspect_ratio or "16:9",
            )
            if "error" in result:
                return {"status": "error", "detail": result["error"], "raw": result}
            urls = extract_image_urls(result)
            return {
                "status": "ok",
                "type": "image",
                "url": urls[0] if urls else None,
                "local_path": result.get("local_path"),
                "credits_remaining": result.get("remainingCredits"),
                "media": result.get("media"),
            }

        elif gen_type == "video":
            result = generate_and_download_video(
                prompt=prompt,
                out_dir=out_dir,
                filename=filename or "video.mp4",
                model=model or DEFAULT_VIDEO_MODEL,
                aspect_ratio=aspect_ratio or "landscape",
                duration=duration,
                start_image=req.get("start_image"),
                end_image=req.get("end_image"),
            )
            if "error" in result:
                return {"status": "error", "detail": result["error"], "raw": result}
            urls = extract_video_urls(result)
            thumb_urls = []
            for item in result.get("media", []):
                if item.get("thumbnailUrl"):
                    thumb_urls.append(item["thumbnailUrl"])
            return {
                "status": "ok",
                "type": "video",
                "url": urls[0] if urls else None,
                "thumbnail_url": thumb_urls[0] if thumb_urls else None,
                "local_path": result.get("local_path"),
                "credits_remaining": result.get("remainingCredits"),
                "media": result.get("media"),
            }

        else:  # ugc
            result = ugc_pipeline(
                scenes=scenes,
                out_dir=out_dir,
                image_model=model or DEFAULT_IMAGE_MODEL,
                video_model=req.get("video_model") or model or DEFAULT_VIDEO_MODEL,
                aspect_ratio=aspect_ratio or "9:16",
                video_duration=duration,
            )
            base = {
                "clips": result["clips"],
                "errors": result["errors"],
                "n_scenes": result["n_scenes"],
                "n_success": result["n_success"],
                "credits_remaining": result.get("credits_remaining"),
            }
            if result["errors"] and not result["clips"]:
                return {"status": "error", "detail": "all scenes failed", **base}
            return {
                "status": "ok" if not result["errors"] else "partial",
                **base,
            }

        # unreachable — gen_type is validated above as image|video|ugc

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc: Exception):
        logger.exception("unhandled: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal error"},
        )


# Instantiate at module level so `uvicorn brain.main:app` works.
app = create_app()
