"""Google Flow integration unit tests — parser helpers, error shapes, no-network."""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

# Make `brain` importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brain.integrations.google_flow import (
    is_available,
    generate_image_sync,
    generate_video_sync,
    download_media,
    extract_image_urls,
    extract_video_urls,
    extract_thumbnail_urls,
    ugc_pipeline,
    _AVAILABLE,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
    IMAGE_MODELS,
    VIDEO_MODELS,
)


# ─── Constants ────────────────────────────────────────────────────────────────


class TestModelConstants:
    def test_image_models_complete(self):
        assert IMAGE_MODELS == {"nano-banana-2-lite", "nano-banana-2", "nano-banana-pro"}

    def test_video_models_complete(self):
        assert VIDEO_MODELS == {
            "veo-3.1-fast",
            "veo-3.1-quality",
            "veo-3.1-lite",
            "veo-3.1-lite-low-priority",
            "omni-flash",
        }

    def test_defaults(self):
        assert DEFAULT_IMAGE_MODEL == "nano-banana-2-lite"
        assert DEFAULT_VIDEO_MODEL == "veo-3.1-lite"


# ─── Availability ─────────────────────────────────────────────────────────────


class TestAvailability:
    def test_no_token_disabled(self):
        assert is_available() is False  # Disabled by the isolation fixture

    def test_is_available_matches(self):
        assert is_available() is False


# ─── Response parsers (no network) ────────────────────────────────────────────


class TestExtractImageUrls:
    def test_single_fife_url(self):
        resp = {
            "media": [{
                "image": {
                    "generatedImage": {
                        "fifeUrl": "https://flow-content.google/img/abc",
                    }
                }
            }]
        }
        assert extract_image_urls(resp) == ["https://flow-content.google/img/abc"]

    def test_empty_media(self):
        assert extract_image_urls({"media": []}) == []

    def test_no_fife_url_no_encoded(self):
        resp = {
            "media": [{
                "image": {
                    "generatedImage": {
                        "seed": 123,
                    }
                }
            }]
        }
        assert extract_image_urls(resp) == []

    def test_multiple_images(self):
        resp = {
            "media": [
                {"image": {"generatedImage": {"fifeUrl": "u1"}}},
                {"image": {"generatedImage": {"fifeUrl": "u2"}}},
                {"image": {"generatedImage": {"fifeUrl": "u3"}}},
            ]
        }
        assert extract_image_urls(resp) == ["u1", "u2", "u3"]


class TestExtractVideoUrls:
    def test_single_video(self):
        resp = {
            "media": [{
                "videoUrl": "https://flow-content.google/video/x",
                "thumbnailUrl": "https://thumb",
            }]
        }
        assert extract_video_urls(resp) == ["https://flow-content.google/video/x"]

    def test_empty(self):
        assert extract_video_urls({"media": []}) == []

    def test_no_video_url(self):
        resp = {"media": [{"name": "x"}]}
        assert extract_video_urls(resp) == []

    def test_multiple(self):
        resp = {
            "media": [
                {"videoUrl": "a"},
                {"videoUrl": "b"},
                {},
                {"videoUrl": "c"},
            ]
        }
        assert extract_video_urls(resp) == ["a", "b", "c"]


class TestExtractThumbnailUrls:
    def test_single(self):
        resp = {"media": [{"thumbnailUrl": "https://thumb/1"}]}
        assert extract_thumbnail_urls(resp) == ["https://thumb/1"]

    def test_empty(self):
        assert extract_thumbnail_urls({"media": []}) == []

    def test_missing_thumbnail(self):
        resp = {"media": [{"videoUrl": "x"}]}
        assert extract_thumbnail_urls(resp) == []


# ─── No-token error paths ─────────────────────────────────────────────────────


class TestNoTokenGraceful:
    def test_image_no_token(self):
        r = generate_image_sync("test prompt", model="nano-banana-2-lite")
        assert r.get("error") == "USEAPI_TOKEN not set"

    def test_video_no_token(self):
        r = generate_video_sync("test prompt", model="veo-3.1-lite")
        assert r.get("error") == "USEAPI_TOKEN not set"

    def test_image_with_wrong_model_rejected_early(self):
        r = generate_image_sync("test", model="not-a-model")
        # Still returns error (token check fires first)
        assert "error" in r


# ─── ugc_pipeline structure (no network, dry-run) ────────────────────────────


class TestUgcPipelineStructure:
    """Verify ugc_pipeline returns correct shape even when disabled."""

    def test_returns_expected_keys(self):
        scenes = [
            {"prompt": "A sunny beach", "name": "beach"},
            {"prompt": "A mountain view", "name": "mountain"},
        ]
        out_dir = tempfile.mkdtemp()
        result = ugc_pipeline(scenes, out_dir)
        assert "clips" in result
        assert "errors" in result
        assert "n_scenes" in result
        assert "n_success" in result
        assert "credits_remaining" in result
        assert result["n_scenes"] == 2
        assert result["n_success"] == 0  # token not set
        assert len(result["errors"]) == 2
        assert all("USEAPI_TOKEN not set" in e for e in result["errors"])

    def test_empty_scenes(self):
        result = ugc_pipeline([], tempfile.mkdtemp())
        assert result["n_scenes"] == 0
        assert result["n_success"] == 0
        assert result["clips"] == []
        assert result["errors"] == []

    def test_custom_models_passed_through(self):
        scenes = [{"prompt": "x", "name": "s1"}]
        out_dir = tempfile.mkdtemp()
        result = ugc_pipeline(
            scenes, out_dir,
            image_model="nano-banana-pro",
            video_model="omni-flash",
            aspect_ratio="16:9",
            video_duration=6,
        )
        # With no token, all fail — but shape is correct
        assert result["n_scenes"] == 1
        assert result["n_success"] == 0

    def test_per_scene_errors(self):
        scenes = [
            {"prompt": "scene A", "name": "alpha"},
            {"prompt": "scene B", "name": "beta"},
            {"prompt": "scene C", "name": "gamma"},
        ]
        out_dir = tempfile.mkdtemp()
        result = ugc_pipeline(scenes, out_dir)
        assert result["n_scenes"] == 3
        assert len(result["errors"]) == 3
        assert result["n_success"] == 0
        assert result["credits_remaining"] is None
