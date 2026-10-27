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
