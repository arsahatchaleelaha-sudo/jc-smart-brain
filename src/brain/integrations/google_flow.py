"""Google Flow integration — generate images + video via useapi.net API v1.

Wraps the useapi.net Google Flow proxy to drive Google's Nano Banana (images),
Veo 3.1 (video), and Omni 1.1 Flash (audio-native video) models from the
JC SMART Brain pipeline.

Requires:
    USEAPI_TOKEN — API token from useapi.net ($15/mo subscription)
    USEAPI_EMAIL — (optional) Google Flow account email for load balancing

Env vars can be set in .env or exported before starting the Brain server.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any
from pathlib import Path

from ..config import settings

logger = logging.getLogger("brain.google_flow")

# ─── Config ───────────────────────────────────────────────────────────────────

_USEAPI_BASE = "https://api.useapi.net/v1/google-flow"
_TOKEN = settings().useapi_token
_EMAIL = settings().useapi_email

_AVAILABLE = bool(_TOKEN)
if not _AVAILABLE:
    logger.warning("USEAPI_TOKEN not set — Google Flow integration disabled")

# ─── Model constants ───────────────────────────────────────────────────────────

IMAGE_MODELS = {"nano-banana-2-lite", "nano-banana-2", "nano-banana-pro"}
VIDEO_MODELS = {
    "veo-3.1-fast",
    "veo-3.1-quality",
    "veo-3.1-lite",
    "veo-3.1-lite-low-priority",
    "omni-flash",
}
ALL_MODELS = IMAGE_MODELS | VIDEO_MODELS

# Default model choices (best ROI on Pro plan)
DEFAULT_IMAGE_MODEL = "nano-banana-2-lite"  # free on all plans, ~0.034/image
DEFAULT_VIDEO_MODEL = "veo-3.1-lite"  # 10 credits/gen on Pro, cheapest Veo
DEFAULT_OMNI_MODEL = "omni-flash"  # audio-native video with voices


def is_available() -> bool:
    """Check if Google Flow integration is configured."""
    return _AVAILABLE


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_TOKEN}",
        "Content-Type": "application/json",
    }


def _post(url: str, payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    """Synchronous POST to useapi.net. Returns parsed JSON response."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=_auth_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        logger.error("useapi POST %s → %d: %s", url, e.code, err_body[:500])
        return {"error": f"HTTP {e.code}", "detail": err_body[:1000]}
    except Exception as e:
        logger.error("useapi POST %s failed: %s", url, e)
        return {"error": str(e)}


def _get(url: str, timeout: int = 30) -> dict[str, Any]:
    """Synchronous GET from useapi.net."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}", "detail": err_body[:500]}
    except Exception as e:
        return {"error": str(e)}


# ─── Image generation ──────────────────────────────────────────────────────────


def generate_image_sync(
    prompt: str,
    model: str = DEFAULT_IMAGE_MODEL,
    aspect_ratio: str = "16:9",
    count: int = 1,
    seed: int | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    """Generate image(s) via Nano Banana. Returns useapi.net response dict.

    Response shape (on success):
        {
            "media": [
                {
                    "image": {
                        "generatedImage": {
                            "seed": 123,
                            "mediaGenerationId": "...",
                            "fifeUrl": "https://...",  # or "encodedImage": "base64..."
                            "prompt": "..."
                        }
                    }
                }
            ],
            "remainingCredits": 12345
        }
    """
    if not _AVAILABLE:
        return {"error": "USEAPI_TOKEN not set"}

    if model not in IMAGE_MODELS:
        return {"error": f"unknown image model: {model}"}

    payload: dict[str, Any] = {
        "prompt": prompt,
        "model": model,
        "aspectRatio": aspect_ratio,
        "count": count,
    }
    if seed is not None:
        payload["seed"] = seed
    if email or _EMAIL:
        payload["email"] = email or _EMAIL

    logger.info("google_flow image: model=%s count=%d prompt=%s", model, count, prompt[:80])
    result = _post(f"{_USEAPI_BASE}/images", payload, timeout=120)
    if "error" in result:
        logger.error("image gen failed: %s", result.get("detail", result.get("error")))
    else:
        logger.info("image gen OK: %d media, credits=%s",
                     len(result.get("media", [])),
                     result.get("remainingCredits", "?"))
    return result


async def generate_image(
    prompt: str,
    model: str = DEFAULT_IMAGE_MODEL,
    aspect_ratio: str = "16:9",
    count: int = 1,
    seed: int | None = None,
) -> dict[str, Any]:
    """Async wrapper for generate_image_sync."""
    return await asyncio.to_thread(
        generate_image_sync, prompt, model, aspect_ratio, count, seed
    )


def download_media(url: str, out_path: str) -> bool:
    """Download a media URL (image or video) to a local file."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        logger.info("downloaded %s → %s (%d bytes)", url[:80], out_path, len(data))
        return True
    except Exception as e:
        logger.error("download failed %s: %s", url[:80], e)
        return False


# ─── Video generation ──────────────────────────────────────────────────────────


def generate_video_sync(
    prompt: str,
    model: str = DEFAULT_VIDEO_MODEL,
    aspect_ratio: str = "landscape",
    duration: int = 8,
    count: int = 1,
    seed: int | None = None,
    start_image: str | None = None,
    end_image: str | None = None,
    resolution: str | None = None,  # "360p" for omni-flash cost reduction
    email: str | None = None,
    async_mode: bool = False,
) -> dict[str, Any]:
    """Generate video via Veo 3.1 or Omni 1.1 Flash. Returns useapi.net response dict.

    For Veo models, the endpoint auto-polls and returns final result (60-180s).
    Set async_mode=True to get a job ID back immediately and poll separately.

    Response shape (completed, sync mode):
        {
            "media": [
                {
                    "videoUrl": "https://flow-content.google/video/...",
                    "thumbnailUrl": "https://...",
                    "mediaGenerationId": "..."
                }
            ],
            "remainingCredits": 12345
        }

    Response shape (async mode):
        {"jobid": "j...", "status": "created", ...}
    """
    if not _AVAILABLE:
        return {"error": "USEAPI_TOKEN not set"}

    if model not in VIDEO_MODELS:
        return {"error": f"unknown video model: {model}"}

    payload: dict[str, Any] = {
        "prompt": prompt,
        "model": model,
        "aspectRatio": aspect_ratio,
        "duration": duration,
        "count": count,
        "async": async_mode,
    }
    if seed is not None:
        payload["seed"] = seed
    if start_image:
        payload["startImage"] = start_image
    if end_image:
        payload["endImage"] = end_image
    if resolution:
        payload["resolution"] = resolution
    if email or _EMAIL:
        payload["email"] = email or _EMAIL

    # Video gen takes 60-180s; give 300s for sync mode
    timeout = 30 if async_mode else 300
    logger.info("google_flow video: model=%s dur=%ds prompt=%s", model, duration, prompt[:80])
    result = _post(f"{_USEAPI_BASE}/videos", payload, timeout=timeout)
    if "error" in result:
        logger.error("video gen failed: %s", result.get("detail", result.get("error")))
    else:
        if async_mode:
            logger.info("video job created: %s", result.get("jobid", "?"))
        else:
            logger.info("video gen OK: %d media, credits=%s",
                         len(result.get("media", [])),
                         result.get("remainingCredits", "?"))
    return result


async def generate_video(
    prompt: str,
    model: str = DEFAULT_VIDEO_MODEL,
    aspect_ratio: str = "landscape",
    duration: int = 8,
    count: int = 1,
    seed: int | None = None,
    start_image: str | None = None,
    end_image: str | None = None,
    resolution: str | None = None,
) -> dict[str, Any]:
    """Async video generation. Runs sync POST in thread to avoid blocking."""
    return await asyncio.to_thread(
        generate_video_sync,
        prompt, model, aspect_ratio, duration, count, seed,
        start_image, end_image, resolution, None, False,
    )


# ─── Job polling (for async mode) ──────────────────────────────────────────────


def get_job_status(job_id: str) -> dict[str, Any]:
    """Get job status by job ID."""
    return _get(f"{_USEAPI_BASE}/jobs/{job_id}", timeout=30)


async def wait_for_job(job_id: str, poll_interval: float = 10.0, max_wait: float = 600.0) -> dict[str, Any]:
    """Poll job status until completed or failed. Returns final job dict."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        job = await asyncio.to_thread(get_job_status, job_id)
        status = job.get("status", "unknown")
        logger.debug("job %s status: %s", job_id[:20], status)
        if status == "completed":
            return job
        if status == "failed":
            logger.error("job failed: %s", job.get("error", "unknown"))
            return job
        await asyncio.sleep(poll_interval)
    return {"error": "timeout", "jobid": job_id, "status": "timeout"}


# ─── High-level helpers ────────────────────────────────────────────────────────


def extract_image_urls(response: dict[str, Any]) -> list[str]:
    """Extract image URLs from a completed image generation response."""
    urls = []
    for item in response.get("media", []):
        img = item.get("image", {}).get("generatedImage", {})
        if img.get("fifeUrl"):
            urls.append(img["fifeUrl"])
        elif img.get("encodedImage"):
            # Image came inline as base64 — save and return as data URL
            pass  # caller should handle download_media for fifeUrl
    return urls


def extract_video_urls(response: dict[str, Any]) -> list[str]:
    """Extract video URLs from a completed video generation response."""
    urls = []
    for item in response.get("media", []):
        if item.get("videoUrl"):
            urls.append(item["videoUrl"])
    return urls


def extract_thumbnail_urls(response: dict[str, Any]) -> list[str]:
    """Extract thumbnail URLs from a completed video generation response."""
    urls = []
    for item in response.get("media", []):
        if item.get("thumbnailUrl"):
            urls.append(item["thumbnailUrl"])
    return urls


def generate_and_download_image(
    prompt: str,
    out_dir: str,
    filename: str = "image.jpg",
    model: str = DEFAULT_IMAGE_MODEL,
    aspect_ratio: str = "16:9",
    count: int = 1,
    email: str | None = None,
) -> dict[str, Any]:
    """Generate an image and download it to out_dir/filename. Returns result dict."""
    result = generate_image_sync(prompt, model=model, aspect_ratio=aspect_ratio, count=count, email=email)
    if "error" in result:
        return result
    os.makedirs(out_dir, exist_ok=True)
    urls = extract_image_urls(result)
    if not urls:
        # Try base64 inline
        for item in result.get("media", []):
            img = item.get("image", {}).get("generatedImage", {})
            if img.get("encodedImage"):
                out_path = os.path.join(out_dir, filename)
                try:
                    with open(out_path, "wb") as f:
                        f.write(base64.b64decode(img["encodedImage"], validate=True))
                except (ValueError, OSError) as exc:
                    return {**result, "error": f"inline image write failed: {exc}"}
                return {**result, "local_path": out_path}
        return {**result, "error": "no image URL in response"}
    out_path = os.path.join(out_dir, filename)
    if download_media(urls[0], out_path):
        return {**result, "local_path": out_path, "url": urls[0]}
    return {**result, "error": "download failed", "url": urls[0]}


def generate_and_download_video(
    prompt: str,
    out_dir: str,
    filename: str = "video.mp4",
    model: str = DEFAULT_VIDEO_MODEL,
    aspect_ratio: str = "landscape",
    duration: int = 8,
    start_image: str | None = None,
    end_image: str | None = None,
    count: int = 1,
    email: str | None = None,
) -> dict[str, Any]:
    """Generate a video (sync mode) and download it to out_dir/filename."""
    result = generate_video_sync(
        prompt, model=model, aspect_ratio=aspect_ratio, duration=duration,
        start_image=start_image, end_image=end_image, count=count, email=email,
    )
    if "error" in result:
        return result
    urls = extract_video_urls(result)
    if not urls:
        return {**result, "error": "no video URL in response"}
    out_path = os.path.join(out_dir, filename)
    if download_media(urls[0], out_path):
        return {**result, "local_path": out_path, "url": urls[0]}
    return {**result, "error": "download failed", "url": urls[0]}


# ─── UGC pipeline: image gen → video gen → assemble ────────────────────────────


def ugc_pipeline(
    scenes: list[dict[str, str]],
    out_dir: str,
    image_model: str = DEFAULT_IMAGE_MODEL,
    video_model: str = DEFAULT_VIDEO_MODEL,
    aspect_ratio: str = "9:16",
    video_duration: int = 8,
) -> dict[str, Any]:
    """UGC pipeline: for each scene, generate image → generate video → download.

    Args:
        scenes: list of {"prompt": "scene description", "name": "scene1"}
        out_dir: output directory
        image_model: Nano Banana model for image gen
        video_model: Veo/Omni model for video gen
        aspect_ratio: "9:16" for shorts/reels, "16:9" for landscape
        video_duration: 4/6/8 seconds per clip

    Returns:
        {"clips": [paths], "error": None | str, "credits_remaining": int}
    """
    os.makedirs(out_dir, exist_ok=True)
    clips = []
    errors = []
    total_credits = None

    for i, scene in enumerate(scenes):
        name = Path(scene.get("name") or f"scene{i+1}").name
        prompt = scene["prompt"]
        logger.info("UGC scene %d/%d: %s", i + 1, len(scenes), name)

        # Step 1: Generate image
        img_result = generate_and_download_image(
            prompt=prompt,
            out_dir=out_dir,
            filename=f"{name}.jpg",
            model=image_model,
            aspect_ratio=aspect_ratio,
        )
        if "error" in img_result:
            errors.append(f"{name} image: {img_result['error']}")
            continue
        if "remainingCredits" in img_result:
            total_credits = img_result["remainingCredits"]
        logger.info("  image OK: %s", img_result.get("local_path", "?"))

        # Step 2: Generate video from that image (start frame)
        img_media_id = None
        for item in img_result.get("media", []):
            gen_img = item.get("image", {}).get("generatedImage", {})
            img_media_id = gen_img.get("mediaGenerationId", img_media_id)

        vid_result = generate_and_download_video(
            prompt=f"Animate this scene: {prompt}",
            out_dir=out_dir,
            filename=f"{name}.mp4",
            model=video_model,
            aspect_ratio="portrait" if aspect_ratio == "9:16" else "landscape",
            duration=video_duration,
            start_image=img_media_id,
        )
        if "error" in vid_result:
            errors.append(f"{name} video: {vid_result['error']}")
            continue
        if "remainingCredits" in vid_result:
            total_credits = vid_result["remainingCredits"]
        clips.append(vid_result.get("local_path", ""))
        logger.info("  video OK: %s", vid_result.get("local_path", "?"))

    return {
        "clips": clips,
        "errors": errors,
        "credits_remaining": total_credits,
        "n_scenes": len(scenes),
        "n_success": len(clips),
    }
