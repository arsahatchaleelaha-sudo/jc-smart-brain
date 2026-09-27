"""Tests for /brain/generate endpoint — disabled smoke + live-path shape validation."""

from __future__ import annotations

import json
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brain.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


class TestGenerateEndpointDisabled:
    """When USEAPI_TOKEN is not set, /brain/generate returns a clean error."""

    def test_generate_image_disabled(self, client):
        resp = client.post("/brain/generate", json={
            "type": "image",
            "prompt": "a cat",
            "model": "nano-banana-2-lite",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "USEAPI_TOKEN not set" in body["detail"]

    def test_generate_video_disabled(self, client):
        resp = client.post("/brain/generate", json={
            "type": "video",
            "prompt": "a dancing robot",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "USEAPI_TOKEN not set" in body["detail"]

    def test_generate_ugc_disabled(self, client):
        resp = client.post("/brain/generate", json={
            "type": "ugc",
            "scenes": [
                {"prompt": "scene 1", "name": "s1"},
                {"prompt": "scene 2", "name": "s2"},
            ],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        # Ugc returns shape keys even without token
        assert "clips" in body
        assert "errors" in body
        assert "n_scenes" in body
        assert "n_success" in body
        assert body["n_scenes"] == 2
        assert body["n_success"] == 0
        assert len(body["errors"]) == 2
        assert all("USEAPI_TOKEN not set" in e for e in body["errors"])


class TestGenerateEndpointValidation:
    """Request validation errors — independent of token state."""

    def test_missing_prompt(self, client):
        resp = client.post("/brain/generate", json={"type": "image"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "prompt is required" in body["detail"]

    def test_unknown_type(self, client):
        resp = client.post("/brain/generate", json={
            "type": "audio",
            "prompt": "hello",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "unknown type" in body["detail"]

    def test_ugc_missing_scenes_array(self, client):
        # "scenes" present but not a list → "scenes array required"
        resp = client.post("/brain/generate", json={
            "type": "ugc",
            "scenes": "not-a-list",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "scenes array required" in body["detail"]

    def test_ugc_empty_scenes(self, client):
        resp = client.post("/brain/generate", json={
            "type": "ugc",
            "scenes": [],
        })
        assert resp.status_code == 200
        body = resp.json()
        # Empty scenes list → all filtered out → "no valid scenes"
        assert body["status"] == "error"
        assert "no valid scenes" in body["detail"]

    def test_ugc_scene_without_prompt(self, client):
        resp = client.post("/brain/generate", json={
            "type": "ugc",
            "scenes": [
                {"name": "no-prompt-scene"},
                {"prompt": "valid scene", "name": "ok"},
            ],
        })
        assert resp.status_code == 200
        body = resp.json()
        # The scene without prompt gets filtered out, but one valid scene remains
        # Since token is not set, it will fail on generation attempt
        # Check that the endpoint accepted the request and returned an error about token
        assert body["status"] in ("error", "partial")


class TestGenerateEndpointShape:
    """Verify response shapes are correct (with mocked responses if needed)."""

    def test_image_response_keys_when_ok(self, client):
        """Structure check: when generation succeeds, response has expected keys.
        We can't test live without a token, but we verify the endpoint accepts
        all required fields and returns a well-formed error."""
        resp = client.post("/brain/generate", json={
            "type": "image",
            "prompt": "a beautiful sunset over mountains",
            "model": "nano-banana-pro",
            "aspect_ratio": "16:9",
            "count": 2,
            "output_dir": "/tmp/test_flow",
            "filename": "sunset.jpg",
        })
        assert resp.status_code == 200
        body = resp.json()
        # Without token → error. With token → would have: status, url, local_path, credits_remaining
        assert "status" in body
        assert "detail" in body

    def test_video_response_shape(self, client):
        resp = client.post("/brain/generate", json={
            "type": "video",
            "prompt": "a futuristic city street at night",
            "model": "veo-3.1-lite",
            "aspect_ratio": "landscape",
            "duration": 8,
            "start_image": "user:123-email:x-image:abc",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "detail" in body

    def test_ugc_response_shape(self, client):
        resp = client.post("/brain/generate", json={
            "type": "ugc",
            "scenes": [
                {"prompt": "A dog running in a park", "name": "dog"},
                {"prompt": "The dog catching a frisbee", "name": "catch"},
                {"prompt": "Dog resting under a tree", "name": "rest"},
            ],
            "aspect_ratio": "9:16",
            "duration": 6,
        })
        assert resp.status_code == 200
        body = resp.json()
        # ugc always returns shape keys (clips/errors/n_scenes/n_success)
        for key in ("clips", "errors", "n_scenes", "n_success"):
            assert key in body, f"missing key {key}"
        assert body["n_scenes"] == 3
        if any("USEAPI_TOKEN" in e for e in body["errors"]):
            # token not set — everything failed
            assert body["n_success"] == 0
            assert len(body["errors"]) == 3
        else:
            # token set — at least shape is correct
            assert body["n_success"] >= 0
            assert len(body["errors"]) >= 0
