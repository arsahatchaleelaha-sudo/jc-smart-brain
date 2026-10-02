"""Regression tests for the source, deployment, and endpoint audit."""
import base64
import json
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from brain.config import kb_faq_path
from brain.main import create_app
from brain.layers.guard import ComplianceChecker


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.mark.parametrize("query, expected", [
    ("pv คืออะไร", "Point Value"),
    ("อวยพรวันเกิด", "สุขสันต์วันเกิด"),
    ("123+456", "579"),
    ("มีผลิตภัณฑ์อะไรบ้าง", "ผลิตภัณฑ์ J&C"),
    ("หาสาขาใกล้ตัว", "Directory"),
    ("ขึ้น Platinum ยังไง", "Platinum"),
    ("สวัสดี", "หวัดดี"),
])
def test_requested_queries(client, query, expected):
    response = client.post("/brain", json={"query": query, "agent_id": "test"})
    assert response.status_code == 200
    body = response.json()
    assert expected in body["answer"]
    assert body["compliance"]["passed"] is True


def test_lottery_falls_back(client):
    body = client.post("/brain", json={"query": "หวยออกเลขอะไร"}).json()
    assert body["route"] == "fallback"
    assert body["grounded"] is False
    assert "ไม่พบ" in body["answer"]


@pytest.mark.parametrize("query, expected", [
    ("10+20", "30"), ("1 บวก 2", "3"), ("4*5", "20"),
    ("3.5 คูณ 2", "7.0"), ("10/4", "2.5"), ("-5-2", "-7"),
    ("1/0", "หารด้วยศูนย์"),
])
def test_calculator_does_not_reuse_example_answer(client, query, expected):
    body = client.post("/brain", json={"query": query}).json()
    assert body["route"] == "calculator"
    assert expected in body["answer"]


@pytest.mark.parametrize("payload", [{}, {"query": ""}, {"query": " \n "}])
def test_invalid_brain_requests(client, payload):
    assert client.post("/brain", json=payload).status_code == 422


def test_faq_schema_and_fallback_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    data = json.loads(kb_faq_path().read_text())
    assert sum(len(group) for group in data.values()) == 59
    for group in data.values():
        for entry in group.values():
            assert isinstance(entry["answer"], str) and entry["answer"].strip()
    from brain.layers.recall import _get_faq_store
    assert "Point Value" in _get_faq_store().lookup("pv คืออะไร")["answer"]
    from brain.layers.ground import _ingest_faq_into_bm25
    assert _ingest_faq_into_bm25() == 59


def test_birthday_outside_project_directory(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    response = client.post("/brain/birthday", json={"user_id": "TEST", "wish_type": "funny"})
    assert response.status_code == 200
    assert "PT" in response.json()["wish_text"]
    assert response.json()["pushed"] is False
    assert client.post("/brain/birthday", json={}).status_code == 422
    assert client.post("/brain/birthday", json={"user_id": "TEST", "wish_type": []}).status_code == 422


def test_memory_creates_directory(client):
    from brain.layers.learn import MEMORY_PATH
    body = client.post("/brain", json={"query": "หวยออกเลขอะไร", "context": {"session_id": "audit"}}).json()
    assert body["route"] == "fallback"
    session = json.loads(MEMORY_PATH.read_text())["sessions"]["audit"]
    assert session["query"] == "หวยออกเลขอะไร"
    assert session["route"] == "fallback"


def test_memory_failure_does_not_replace_answer(client, monkeypatch):
    from brain import pipeline
    async def fail(*args):
        raise OSError("read-only filesystem")
    monkeypatch.setattr(pipeline, "learn", fail)
    body = client.post("/brain", json={"query": "หวยออกเลขอะไร"}).json()
    assert "ไม่พบ" in body["answer"]


@pytest.mark.parametrize("answer, passed", [
    ("รับประกันรายได้แน่นอน", False),
    ("ไม่รับประกันรายได้", True),
    ("อย่ารับประกันรายได้ครับ", True),
    ("ไม่ใช้รักษาโรค ควรปรึกษาแพทย์", True),
    ("รักษามะเร็งได้", False),
    ("ไม่ใช่ยา แต่รักษามะเร็งได้", False),
    ("ไม่แพง รักษามะเร็งได้", False),
    ("ห้ามสร้างรีวิวปลอม, อวดอ้างรักษาโรค", True),
])
def test_guard_recognizes_negated_claims(answer, passed):
    assert ComplianceChecker().post_check("test", answer)["passed"] is passed


def test_faq_answers_are_guarded(client, monkeypatch):
    from brain.layers.recall import _get_faq_store
    _get_faq_store().entries["unsafe"] = {"answer": "รับประกันรายได้แน่นอน"}
    body = client.post("/brain", json={"query": "unsafe"}).json()
    assert body["compliance"]["passed"] is False
    assert "รับประกันรายได้" not in body["answer"]


def test_chunks_only_route(client, monkeypatch):
    from brain import pipeline
    async def ground(*args):
        return [{"text": "Audit knowledge", "source": {"doc": "audit"}}]
    monkeypatch.setattr(pipeline, "ground", ground)
    body = client.post("/brain", json={"query": "unknown-audit-query"}).json()
    assert body["route"] == "chunks-only"
    assert body["compliance"]["passed"] is True
    assert "Audit knowledge" in body["answer"]


def test_bm25_rebuilds_after_ingestion():
    from brain.layers.ground import BM25Retriever
    index = BM25Retriever()
    for text in ["alpha one", "beta two", "gamma three"]:
        index.add(text)
    assert index.search("alpha")
    index.add("uniqueword four")
    assert index.search("uniqueword")[0]["text"] == "uniqueword four"


def test_ground_import_without_chroma():
    script = "import sys; sys.modules['chromadb'] = None; import brain.layers.ground as g; assert g.PersistentClient is None; assert g.BM25Retriever"
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)


@pytest.mark.parametrize("payload", [
    {"type": "ugc", "scenes": [None, 5, "invalid"]},
    {"prompt": ["invalid"]}, {"prompt": "cat", "count": "two"},
    {"prompt": "cat", "filename": "../outside.jpg"},
    {"prompt": "cat", "output_dir": "/etc"},
    {"prompt": "cat", "model": []},
])
def test_generate_rejects_malformed_requests(client, payload):
    response = client.post("/brain/generate", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "error"


def test_generate_forwards_options(client, monkeypatch):
    from brain.integrations import google_flow as flow
    received = {}
    def generate(**kwargs):
        received.update(kwargs)
        return {"media": [{"image": {"generatedImage": {"fifeUrl": "https://example.com/image"}}}]}
    monkeypatch.setattr(flow, "_AVAILABLE", True)
    monkeypatch.setattr(flow, "generate_and_download_image", generate)
    body = client.post("/brain/generate", json={"prompt": "cat", "count": 2, "email": "test@example.com"}).json()
    assert body["status"] == "ok"
    assert received["count"] == 2
    assert received["email"] == "test@example.com"


def test_generate_async_video(client, monkeypatch):
    from brain.integrations import google_flow as flow
    received = {}
    def generate(**kwargs):
        received.update(kwargs)
        return {"jobid": "job-test", "status": "created"}
    monkeypatch.setattr(flow, "generate_video_sync", generate)
    body = client.post("/brain/generate", json={"type": "video", "prompt": "cat", "async_mode": True}).json()
    assert body["jobid"] == "job-test"
    assert received["async_mode"] is True


def test_inline_image_creates_directory(monkeypatch, tmp_path):
    from brain.integrations import google_flow as flow
    monkeypatch.setattr(flow, "generate_image_sync", lambda *a, **kw: {"media": [{"image": {"generatedImage": {"encodedImage": base64.b64encode(b"image").decode()}}}]})
    result = flow.generate_and_download_image("cat", str(tmp_path / "new"))
    assert Path(result["local_path"]).read_bytes() == b"image"


def test_ugc_default_names_and_models(client, monkeypatch):
    from brain.integrations import google_flow as flow
    received = {}
    def pipeline(**kwargs):
        received.update(kwargs)
        return {"clips": [], "errors": [], "n_scenes": 1, "n_success": 0}
    monkeypatch.setattr(flow, "ugc_pipeline", pipeline)
    client.post("/brain/generate", json={"type": "ugc", "scenes": [{"prompt": "cat"}], "model": flow.DEFAULT_IMAGE_MODEL})
    assert received["video_model"] == flow.DEFAULT_VIDEO_MODEL


def test_all_faq_answers_pass_guard():
    for entries in json.loads(kb_faq_path().read_text()).values():
        for query, entry in entries.items():
            result = ComplianceChecker().post_check(query, entry["answer"], entry.get("sources"))
            assert result["passed"], (query, result["flags"])
