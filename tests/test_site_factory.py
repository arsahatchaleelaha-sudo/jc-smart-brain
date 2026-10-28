import json
import urllib.request

import pytest

from site_factory.generate import _ask_single_api, generate, safe_job_id, validate_site


def test_safe_job_id():
    assert safe_job_id("LINE Group 123") == "line-group-123"
    with pytest.raises(ValueError):
        safe_job_id("***")


def test_rejects_active_content():
    with pytest.raises(ValueError):
        validate_site('<html><meta name="viewport"><script>alert(1)</script></html>')


def test_accepts_plain_html_model_response(monkeypatch):
    page = """<!doctype html><html lang="th"><head>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body { color: #123; }</style></head><body>
    <h1>Production QC</h1><p>เว็บไซต์พร้อมใช้งาน</p>
    </body></html>"""

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return page.encode("utf-8")

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=90: FakeResponse(),
    )
    result = _ask_single_api("สร้างเว็บ", "Production QC", "", "openai", "https://example.test")
    assert "Production QC" in result
    assert result.lower().startswith("<!doctype html")


def test_generates_safe_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    request = tmp_path / "demo.json"
    request.write_text(json.dumps({
        "job_id": "demo-1",
        "title": "ร้านกาแฟ",
        "prompt": "ร้านกาแฟไทย"
    }, ensure_ascii=False))
    status = generate(request, tmp_path / "public")
    page = (tmp_path / "public/sites/demo-1/index.html").read_text()
    assert status["status"] == "ready"
    assert status["provider"] == "safe-template"
    assert status["mode"] == "generic"
    assert "ร้านกาแฟไทย" in page
    assert "<script" not in page.lower()


def test_generates_premium_sales_page(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    request = tmp_path / "sales.json"
    request.write_text(json.dumps({
        "job_id": "sales-1",
        "title": "COLLA MAX",
        "mode": "sales_page",
        "spec": {
            "brand": "COLLA MAX",
            "eyebrow": "PREMIUM INGREDIENTS",
            "headline": "ดูแลตัวเองให้ต่อเนื่องได้จริง",
            "subheadline": "หน้า premium sales page สำหรับทดสอบ",
            "price": "199",
            "cta_label": "คุยกับ JWIZ ใน LINE",
            "cta_url": "https://jwizs.com/api/v1/go/JZTEST01",
            "features": [
                {
                    "kicker": "01",
                    "title": "ข้อมูลชัดเจน",
                    "body": "ใช้ข้อมูลที่อนุมัติ"
                }
            ],
            "faq": [
                {
                    "question": "ถามข้อมูลเพิ่มได้ที่ไหน?",
                    "answer": "คุยกับ JWIZ ใน LINE"
                }
            ]
        }
    }, ensure_ascii=False))
    status = generate(request, tmp_path / "public")
    page = (tmp_path / "public/sites/sales-1/index.html").read_text()
    assert status["status"] == "ready"
    assert status["provider"] == "jwiz-premium-template"
    assert status["mode"] == "sales_page"
    assert "ดูแลตัวเองให้ต่อเนื่องได้จริง" in page
    assert "https://jwizs.com/api/v1/go/JZTEST01" in page
    assert "คุยกับ JWIZ ใน LINE" in page
    assert "<script" not in page.lower()


def test_sales_page_requires_structured_spec(tmp_path):
    request = tmp_path / "sales.json"
    request.write_text(json.dumps({
        "job_id": "sales-2",
        "title": "COLLA MAX",
        "mode": "sales_page"
    }))
    with pytest.raises(ValueError, match="sales_page spec is required"):
        generate(request, tmp_path / "public")
