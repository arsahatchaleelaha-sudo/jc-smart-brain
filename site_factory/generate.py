from __future__ import annotations

import argparse
import html
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODEL_URL = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4.1-mini"
MAX_PROMPT = 6000


def safe_job_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    if not cleaned or len(cleaned) > 80:
        raise ValueError("invalid job id")
    return cleaned


def _fallback_html(prompt: str, title: str) -> str:
    safe_title = html.escape(title or "เว็บไซต์ของคุณ")
    safe_prompt = html.escape(prompt)
    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="เว็บไซต์ที่สร้างโดย JC SMART"><title>{safe_title}</title>
<style>
:root{{--ink:#12233f;--accent:#ff7a18;--accent2:#0b8f87;--paper:#fffaf2}}
*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,'Noto Sans Thai',sans-serif;color:var(--ink);background:linear-gradient(135deg,#fff 0%,var(--paper) 100%);line-height:1.65}}
main{{max-width:980px;margin:auto;padding:72px 24px}}.badge{{display:inline-block;padding:8px 14px;border-radius:999px;background:#e7faf7;color:#076a64;font-weight:700}}
h1{{font-size:clamp(2.4rem,7vw,5.5rem);line-height:1.04;margin:24px 0}}p{{font-size:1.15rem;max-width:720px}}.card{{margin-top:44px;padding:28px;border:1px solid #eadfce;border-radius:24px;background:#ffffffcc;box-shadow:0 18px 50px #12233f12}}
a{{display:inline-block;margin-top:24px;padding:13px 20px;border-radius:12px;background:var(--accent);color:white;text-decoration:none;font-weight:800}}
footer{{margin-top:60px;color:#657085;font-size:.9rem}}
</style></head><body><main><span class="badge">สร้างโดย JC SMART</span><h1>{safe_title}</h1>
<p>เว็บไซต์พร้อมใช้งาน รวดเร็ว และรองรับโทรศัพท์มือถือ</p><section class="card"><h2>รายละเอียด</h2><p>{safe_prompt}</p><a href="mailto:contact@example.com">ติดต่อเรา</a></section>
<footer>JC SMART • Generated securely</footer></main></body></html>"""


def _extract_html(text: str) -> str:
    match = re.search(r"<!doctype html.*?</html>", text, flags=re.I | re.S)
    if not match:
        match = re.search(r"<html.*?</html>", text, flags=re.I | re.S)
    return match.group(0).strip() if match else ""


def validate_site(page: str) -> None:
    lower = page.lower()
    required = ("<html", "</html>", "<meta name=\"viewport\"")
    if not all(item in lower for item in required):
        raise ValueError("generated page is incomplete")
    blocked = ("<script", "javascript:", "document.cookie", "localstorage", "eval(")
    if any(item in lower for item in blocked):
        raise ValueError("generated page contains blocked active content")
    if len(page.encode("utf-8")) > 750_000:
        raise ValueError("generated page is too large")


def _ask_model(prompt: str, title: str, token: str, model: str) -> str:
    instructions = (
        "Create one polished, mobile-first Thai/English static website as a single index.html. "
        "Return HTML only. Include all CSS inline. Do not use JavaScript, forms, trackers, embeds, "
        "remote images, remote fonts, or external assets. Be accurate and never invent contact details. "
        f"Site title: {title}\nUser request: {prompt}"
    )
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": instructions}],
        "temperature": 0.4,
        "max_tokens": 5000,
    }).encode()
    request = urllib.request.Request(
        MODEL_URL,
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.load(response)
    return _extract_html(data["choices"][0]["message"]["content"])


def generate(request_file: Path, output_root: Path) -> dict[str, Any]:
    request = json.loads(request_file.read_text(encoding="utf-8"))
    job_id = safe_job_id(str(request.get("job_id") or request_file.stem))
    prompt = str(request.get("prompt") or "").strip()[:MAX_PROMPT]
    if not prompt:
        raise ValueError("prompt is required")
    title = str(request.get("title") or "เว็บไซต์ของคุณ").strip()[:120]
    page = ""
    provider = "safe-template"
    error = None
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        try:
            page = _ask_model(prompt, title, token, os.getenv("SITE_MODEL", DEFAULT_MODEL))
            validate_site(page)
            provider = "github-models"
        except (KeyError, ValueError, TimeoutError, urllib.error.URLError) as exc:
            error = type(exc).__name__
            page = ""
    if not page:
        page = _fallback_html(prompt, title)
        validate_site(page)

    target = output_root / "sites" / job_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.html").write_text(page, encoding="utf-8")
    base_url = os.getenv(
        "SITE_BASE_URL", "https://arsahatchaleelaha-sudo.github.io/jc-smart-brain/sites"
    ).rstrip("/")
    status = {
        "job_id": job_id,
        "status": "ready",
        "url": f"{base_url}/{job_id}/",
        "provider": provider,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        status["model_fallback"] = error
    (target / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("--output", type=Path, default=Path("site_factory/public"))
    args = parser.parse_args()
    print(json.dumps(generate(args.request, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
