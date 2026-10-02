"""Keep tests independent of local credentials, storage, and installed integrations."""
import pytest


@pytest.fixture(autouse=True)
def isolated_integrations(monkeypatch, tmp_path):
    from brain.config import settings
    from brain.integrations import google_flow, line_birthday
    from brain.layers import ground, learn, reason, recall

    monkeypatch.setattr(google_flow, "_AVAILABLE", False)
    monkeypatch.setattr(line_birthday, "_LINE_AVAILABLE", False)
    monkeypatch.setattr(settings(), "anthropic_api_key", "")
    monkeypatch.setattr(reason, "_client", None)
    monkeypatch.setattr(ground, "_get_store", lambda: None)
    monkeypatch.setattr(ground, "_bm25", None)
    monkeypatch.setattr(recall, "_faq_store", None)
    monkeypatch.setattr(learn, "MEMORY_PATH", tmp_path / "data" / "memory.json")
