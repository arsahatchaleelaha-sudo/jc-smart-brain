"""FastAPI app — endpoint /brain + health + root."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import settings, kb_faq_path
from .models import ThinkRequest, ThinkResponse, BirthdayRequest, ComplianceResult
from .pipeline import think
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
    def birthday_endpoint(req: BirthdayRequest) -> dict[str, Any]:
        """ส่งอวยพรวันเกิดไปหา LINE user.

        Body: {"user_id": "LINE_MID", "wish_type": "general|partner|customer|short|long|funny|formal|line", "custom_text": "optional"}
        """
        import json

        user_id = req.user_id
        wish_type = req.wish_type
        custom_text = req.custom_text

        # Load birthday wishes
        faq_path = kb_faq_path()
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
    def generate_endpoint(req: dict[str, Any]) -> dict[str, Any]:
        """Generate image/video via Google Flow (useapi.net proxy).

        Body:
            {
                "type": "image|video|ugc",
                "prompt": "description",
                "model": "nano-banana-2-lite|veo-3.1-lite|omni-flash|...",
                "aspect_ratio": "16:9|9:16|landscape|portrait|1:1|...",
                "duration": 8,
                "count": 1,
                "output_dir": "/tmp/google_flow_out",
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
        from brain.integrations.google_flow import (
            generate_video_sync,
            generate_and_download_image,
            generate_and_download_video,
            ugc_pipeline,
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
        if gen_type in ("image", "video") and (not isinstance(prompt, str) or not prompt.strip()):
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
            scenes = [{"prompt": s.get("prompt", ""), "name": s.get("name", "")} for s in scenes_raw if isinstance(s, dict)]
            scenes = [s for s in scenes if isinstance(s["prompt"], str) and s["prompt"].strip() and isinstance(s["name"], str)]
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

        # Reject malformed optional fields before calling synchronous integrations.
        for key in ("model", "video_model", "aspect_ratio", "email", "filename", "output_dir", "start_image", "end_image"):
            if req.get(key) is not None and not isinstance(req[key], str):
                return {"status": "error", "detail": f"{key} must be a string"}
        if type(count) is not int or not 1 <= count <= 4:
            return {"status": "error", "detail": "count must be an integer from 1 to 4"}
        if type(duration) is not int or duration <= 0:
            return {"status": "error", "detail": "duration must be a positive integer"}
        if type(async_mode) is not bool:
            return {"status": "error", "detail": "async_mode must be a boolean"}
        if async_mode and gen_type != "video":
            return {"status": "error", "detail": "async_mode is supported only for video"}

        # Downloads from this public endpoint stay within its configured media root.
        import os
        from pathlib import Path
        media_root = Path(os.environ.get("FLOW_OUTPUT_DIR", "/tmp/google_flow_out")).resolve()
        requested_dir = Path(req.get("output_dir") or str(media_root))
        output_path = (requested_dir if requested_dir.is_absolute() else media_root / requested_dir).resolve()
        if not output_path.is_relative_to(media_root):
            return {"status": "error", "detail": "output_dir must be within FLOW_OUTPUT_DIR"}
        if filename and (Path(filename).name != filename or filename in (".", "..")):
            return {"status": "error", "detail": "filename must be a plain file name"}
        out_dir = str(output_path)

        if async_mode:
            result = generate_video_sync(
                prompt=prompt, model=model or DEFAULT_VIDEO_MODEL,
                aspect_ratio=aspect_ratio or "landscape", duration=duration,
                count=count, email=email, async_mode=True,
                start_image=req.get("start_image"), end_image=req.get("end_image"),
            )
            if "error" in result:
                return {"status": "error", "detail": result["error"]}
            return {**result, "status": "ok", "job_status": result.get("status"), "type": "video"}

        if gen_type == "image":
            if not _AVAILABLE:
                return {"status": "error", "detail": "Google Flow integration disabled — USEAPI_TOKEN not set"}
            result = generate_and_download_image(
                prompt=prompt,
                out_dir=out_dir,
                filename=filename or "image.jpg",
                model=model or DEFAULT_IMAGE_MODEL,
                aspect_ratio=aspect_ratio or "16:9",
                count=count, email=email,
            )
            if "error" in result:
                return {"status": "error", "detail": result["error"], "raw": result}
            urls = extract_image_urls(result)
            return {
                "status": "ok",
                "type": "image",
                "url": urls[0] if urls else None,
                "urls": urls,
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
                count=count, email=email,
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
                "urls": urls,
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
                video_model=req.get("video_model") or DEFAULT_VIDEO_MODEL,
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
