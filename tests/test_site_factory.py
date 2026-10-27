import json

import pytest

from site_factory.generate import generate, safe_job_id, validate_site


def test_safe_job_id():
    assert safe_job_id("LINE Group 123") == "line-group-123"
    with pytest.raises(ValueError):
        safe_job_id("***")


def test_rejects_active_content():
    with pytest.raises(ValueError):
        validate_site('<html><meta name="viewport"><script>alert(1)</script></html>')


def test_generates_safe_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    request = tmp_path / "demo.json"
    request.write_text(json.dumps({"job_id": "demo-1", "title": "ร้านกาแฟ", "prompt": "ร้านกาแฟไทย"}))
    status = generate(request, tmp_path / "public")
    page = (tmp_path / "public/sites/demo-1/index.html").read_text()
    assert status["status"] == "ready"
    assert status["provider"] == "safe-template"
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
            "headline": "ดูแลตัวเองให้ต่อเนื่องได้จริง",
            "subheadline": "Premium editorial sales page",
            "price": "199",
            "cta_url": "https://jwizs.com/go/JZTEST01",
            "cta_label": "คุยกับ JWIZ ใน LINE",
            "features": [
                {"kicker": "01", "title": "Tripeptide", "body": "ข้อมูลตัวอย่าง"}
            ],
            "faq": [
                {"question": "หนึ่งกล่องมีกี่ซอง?", "answer": "10 ซอง"}
            ]
        }
    }, ensure_ascii=False))
    status = generate(request, tmp_path / "public")
    page = (tmp_path / "public/sites/sales-1/index.html").read_text()
    assert status["status"] == "ready"
    assert status["provider"] == "jwiz-premium-template"
    assert status["mode"] == "sales_page"
    assert "ดูแลตัวเองให้ต่อเนื่องได้จริง" in page
    assert "https://jwizs.com/go/JZTEST01" in page
    assert "คุยกับ JWIZ ใน LINE" in page
    assert "<script" not in page.lower()


def test_sales_page_requires_structured_spec(tmp_path):
    request = tmp_path / "bad-sales.json"
    request.write_text(json.dumps({
        "job_id": "bad-sales",
        "title": "Bad",
        "mode": "sales_page"
    }))
    with pytest.raises(ValueError, match="sales_page spec is required"):
        generate(request, tmp_path / "public")
