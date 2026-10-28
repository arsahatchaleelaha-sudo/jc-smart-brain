from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from site_factory.templates.sales_page import render_sales_page


def _get_github_var(name: str) -> str:
    """Fetch a GitHub Actions repository variable via the REST API.

    GitHub Actions repository variables are NOT automatically exposed as
    environment variables (unlike ``env:`` entries).  They must be read
    through the ``vars`` context or fetched via the API.  This helper lets
    ``generate.py`` work both locally (env vars) and in CI (GitHub var).
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    if not token or not repo:
        return ""
    try:
        req = urllib.request.Request(
            f"{api_url}/repos/{repo}/actions/variables/{name}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("value", "")
    except Exception:
        return ""


def _resolve_model_url() -> str:
    """Resolve the model endpoint URL.

    Precedence: env var → GitHub Actions variable → GitHub Models default.
    """
    val = os.environ.get("MODEL_URL")
    if val:
        return val
    val = os.environ.get("OPENAI_BASE_URL")
    if val:
        return val
    val = _get_github_var("OPENAI_BASE_URL")
    if val:
        return val
    return "https://models.github.ai/inference/chat/completions"


# Configurable model endpoint — defaults to GitHub Models but can be
# overridden via MODEL_URL or OPENAI_BASE_URL (e.g. for OpenRouter:
#   MODEL_URL=https://openrouter.ai/api/v1/chat/completions
#   OPENAI_API_KEY=<key>)
MODEL_URL = _resolve_model_url()
DEFAULT_MODEL = "openai/gpt-4o-mini"
MAX_PROMPT = 6000

# Pollinations.ai Classic API — free, anonymous (no key needed).
# Uses /v1/chat/completions (OpenAI-compatible). Model "openai" is an alias
# for GPT-OSS 20B. Falls back when GitHub Models API or OpenRouter is
# unavailable (account not enabled, no API key).
POLLINATIONS_URL = "https://text.pollinations.ai/v1/chat/completions"
POLLINATIONS_MODEL = "openai"


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
    """Extract a complete HTML document from model output.

    Handles truncated responses (model stops before ``</html>``) by
    appending the closing tag when needed.
    """
    # Try to find a complete HTML document
    match = re.search(r"<!doctype html.*?</html>", text, flags=re.I | re.S)
    if not match:
        match = re.search(r"<html.*?</html>", text, flags=re.I | re.S)
    if match:
        return match.group(0).strip()

    # Fallback: extract from <!doctype html> or <html> to end, then
    # ensure proper closure for truncated model responses.
    match = re.search(r"(?:<!doctype html|<html\b[^>]*>).*", text, flags=re.I | re.S)
    if match:
        content = match.group(0).strip()
        if not re.search(r"</html>\s*$", content, re.I):
            content += "\n</html>"
        return content

    return ""


def validate_site(page: str) -> None:
    lower = page.lower()
    required = ("<html", "</html>", "<meta name=\"viewport\"", "<body", "</style>")
    if not all(item in lower for item in required):
        raise ValueError("generated page is incomplete")
    blocked = ("<script", "javascript:", "document.cookie", "localstorage", "eval(")
    if any(item in lower for item in blocked):
        raise ValueError("generated page contains blocked active content")
    if len(page.encode("utf-8")) < 1000:
        raise ValueError("generated page is too small")
    if len(page.encode("utf-8")) > 750_000:
        raise ValueError("generated page is too large")


def _ask_single_api(prompt: str, title: str, token: str, model: str, api_url: str) -> str:
    """Single API call to a model endpoint. Returns HTML string or raises on error."""
    instructions = (
        "Create a mobile-first static website as a single HTML file. "
        "Write content in BOTH Thai (ภาษาไทย) AND English. "
        "Include Thai headings, product descriptions, and footer text. "
        "All CSS must be inline in a <style> tag. "
        "Do not use JavaScript, forms, trackers, embeds, remote images, or external fonts. "
        "Be accurate — never invent contact details or phone numbers. "
        f"Website title: {title}\nUser request: {prompt}"
    )
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": instructions}],
        "temperature": 0.4,
        "max_tokens": 5000,
    }).encode()
    request = urllib.request.Request(
        api_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.load(response)
    return _extract_html(data["choices"][0]["message"]["content"])


def _ask_model(prompt: str, title: str, token: str, model: str) -> tuple[str, str, str | None]:
    """Try primary model API (GitHub Models / OpenRouter), then Pollinations.ai free fallback.

    Returns (page_html, provider_name, model_fallback_error_or_None).
    - If primary succeeds:                       (page, "github-models", None)
    - If primary fails but Pollinations works:   (page, "pollinations", "<PrimaryError>")
    - If both fail:                              ("", "safe-template", "<PrimaryError>")
    """
    primary_error: str | None = None

    # Try primary API (GitHub Models API or OpenRouter via MODEL_URL)
    # Skip if MODEL_URL points to Pollinations.ai — that would exhaust the
    # 30s free rate-limit on the wrong model before the fallback tries the
    # correct model alias.
    if token and not MODEL_URL.startswith("https://text.pollinations.ai"):
        try:
            page = _ask_single_api(prompt, title, token, model, MODEL_URL)
            if page:
                validate_site(page)
                return page, "github-models", None
            primary_error = "empty-response"
        except Exception as exc:
            primary_error = exc.__class__.__name__

    # Try Pollinations.ai Classic API — free, no key needed, 1 req/30s per IP
    # Server can be overloaded (503); retry once after the suggested delay.
    for attempt in range(2):
        try:
            page = _ask_single_api(prompt, title, "", POLLINATIONS_MODEL, POLLINATIONS_URL)
            if page:
                validate_site(page)
                return page, "pollinations", primary_error
        except ValueError as exc:
            print(f"DEBUG: Pollinations.ai validation failed: {exc}", file=sys.stderr)
        except urllib.error.HTTPError as exc:
            print(f"DEBUG: Pollinations.ai fallback HTTPError {exc.code}", file=sys.stderr)
            if exc.code == 503 and attempt == 0:
                import time
                time.sleep(11)
                continue
        except Exception as exc:
            print(f"DEBUG: Pollinations.ai fallback {exc.__class__.__name__}: {exc}", file=sys.stderr)
        break

    return "", "safe-template", primary_error


def generate(request_file: Path, output_root: Path) -> dict[str, Any]:
    request = json.loads(request_file.read_text(encoding="utf-8"))
    job_id = safe_job_id(str(request.get("job_id") or request_file.stem))
    mode = str(request.get("mode") or "generic").strip().lower()
    prompt = str(request.get("prompt") or "").strip()[:MAX_PROMPT]
    title = str(request.get("title") or "เว็บไซต์ของคุณ").strip()[:120]
    if mode == "sales_page":
        spec = request.get("spec")
        if not isinstance(spec, dict):
            raise ValueError("sales_page spec is required")
        page = render_sales_page(spec, title=title)
        validate_site(page)
        provider = "jwiz-premium-template"
        error = None
    else:
        if not prompt:
            raise ValueError("prompt is required")
        page = ""
        provider = "safe-template"
        error = None
    # Prefer OPENAI_API_KEY (e.g. OpenRouter) over GITHUB_TOKEN so
    # the same env var name works across local and CI environments.
    token = os.getenv("OPENAI_API_KEY") or os.getenv("GITHUB_TOKEN", "").strip()
    if mode != "sales_page":
        try:
            page, provider, model_fallback = _ask_model(
                prompt, title, token, os.getenv("MODEL_NAME", DEFAULT_MODEL)
            )
            if model_fallback:
                error = model_fallback
            if page:
                validate_site(page)
        except (KeyError, ValueError, TimeoutError, urllib.error.URLError) as exc:
            error = type(exc).__name__
            page = ""
        if not page:
            page = _fallback_html(prompt, title)
            provider = "safe-template"
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
        "mode": mode,
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
