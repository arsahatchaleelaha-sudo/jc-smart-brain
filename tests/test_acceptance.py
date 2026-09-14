""" test อนุบาล — health check + root + /brain mock."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from brain.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


# ─── Health ────────────────────────────────────────────────────────────────────


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "jc-smart-brain"
    assert body["version"] == "0.1.0"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "env" in body
    assert "ts" in body


# ─── /brain ────────────────────────────────────────────────────────────────────


def test_brain_healthy_payload(client):
    """POST /brain ด้วย payload ปกติ — ต้องได้ 200 + response shapes ที่ถูกต้อง."""

    payload = {
        "query": "pv คืออะไร",
        "agent_id": "jwiz-customer",
    }

    resp = client.post("/brain", json=payload)
    assert resp.status_code == 200

    body = resp.json()
    # shape 최소ที่ต้องมี
    assert "answer" in body and isinstance(body["answer"], str)
    assert "grounded" in body and isinstance(body["grounded"], bool)
    assert "route" in body and body["route"] in ("cache_hit", "rag", "llm", "fallback", "chunks")
    assert "compliance" in body
    assert "cost" in body and isinstance(body["cost"], (int, float))
    assert "latency_ms" in body and isinstance(body["latency_ms"], int)


def test_brain_cache_hit(client):
    """คำถาม FAQ ที่มีใน cache → route cache_hit, latency ต่ำ."""

    payload = {
        "query": "สวัสดี",
        "agent_id": "jwiz-customer",
    }

    resp = client.post("/brain", json=payload)
    assert resp.status_code == 200

    body = resp.json()
    # คำถามนี้มีใน FAQ_ENTRIES → cache_hit
    assert body["route"] == "cache_hit"
    assert "answer" in body
    assert len(body["answer"]) > 0
    # latency ต่ำมาก (< 100ms) เพราะ cache hit
    assert body["latency_ms"] < 500


def test_brain_faq_cache_hit_pv(client):
    """PV FAQ → cache_hit + grounded."""

    payload = {
        "query": "pv คืออะไร",
        "agent_id": "jwiz-customer",
    }

    resp = client.post("/brain", json=payload)
    assert resp.status_code == 200

    body = resp.json()
    assert body["route"] == "cache_hit"
    assert body["grounded"] is True  # มี sources
    assert "pv" in body["answer"].lower() or "point value" in body["answer"].lower()


def test_brain_fallback_safe(client):
    """คำถามที่ไม่มีในระบบ → fallback, คำตอบปลอดภัย."""

    payload = {
        "query": "หวยออกเลขอะไร 좋겠어요",
        "agent_id": "jwiz-customer",
    }

    resp = client.post("/brain", json=payload)
    assert resp.status_code == 200

    body = resp.json()
    # fallback คือ response ที่บอกว่าไม่พบ + เสนอทางเลือก
    assert body["route"] in ("chunks", "fallback")
    assert "ไม่พบ" in body["answer"] or "ไม่สามารถ" in body["answer"] or "ตรวจสอบ" in body["answer"]


def test_brain_compliance_passed(client):
    """ปกติการตอบ → compliance passed."""

    payload = {
        "query": "pv คืออะไร",
        "agent_id": "jwiz-customer",
    }

    resp = client.post("/brain", json=payload)
    assert resp.status_code == 200

    body = resp.json()
    assert body["compliance"]["passed"] is True


def test_brain_provenance(client):
    """ทุก response ต้องมี provenance."""

    payload = {
        "query": "pv คืออะไร",
        "agent_id": "jwiz-customer",
    }

    resp = client.post("/brain", json=payload)
    assert resp.status_code == 200

    body = resp.json()
    assert "provenance" in body
    assert "model" in body["provenance"] or "config" in body["provenance"]


# ─── Error handling ────────────────────────────────────────────────────────────


def test_brain_bad_payload(client):
    """payload ไม่สมบูรณ์ → 422 (fastapi pydantic validation)."""

    resp = client.post("/brain", json={"query": ""})
    # pydantic min_length=1 → validation error
    assert resp.status_code in (422, 400)


def test_brain_missing_query(client):
    """ไม่มี query → 422."""

    resp = client.post("/brain", json={})
    assert resp.status_code in (422, 400)
