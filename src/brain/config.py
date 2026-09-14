"""Config — อ่านค่าจาก env + .env และส่งเป็น settings object."""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BrainSettings(BaseSettings):
    """ค่าที่ Brain ต้องการ — ทุกค่ามี default  Chiron ทดลองรันได้โดยไม่ต้อง .env จริง."""

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # ชนิดของ vector store ที่ใช้
    # ค่าที่ยอมรับ: "sqlite" (เริ่มต้น, ไกว่าง่าย), "pgvector", "qdrant"
    vector_backend: str = "sqlite"

    # path / connection สำหรับ vector store
    # sqlite: path ไปยังไฟล์ db
    # pgvector: "postgresql+psycopg2://..."
    # qdrant: "http://localhost:6333"
    pg_vector_path: str = "./data/brain_vector.db"

    # cache
    cache_path: str = "./data/brain_cache.json"

    # KB (FAQ entries JSON)
    kb_faq_path: str = "./src/brain/kb/faq_entries.json"

    # server
    brain_env: str = "dev"
    brain_port: int = 8000

    # ขอบเขต cost ต่อ 1 คำถาม (guard จะเข้ามาแทนตอบถ้าเกิน)
    max_cost_per_query: float = 0.05

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def settings() -> BrainSettings:
    return BrainSettings()


# ─── path helpers ───────────────────────────────────────────────────────────────

def data_dir() -> Path:
    """目录ที่เก็บ db + cache — สร้างให้ 존재하면."""

    p = Path(settings().pg_vector_path).parent
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_file() -> Path:
    p = Path(settings().cache_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def kb_faq_path() -> Path:
    """ตรวจสอบว่า FAQ JSON มีอยู่จริง — คืน path."""
    p = Path(settings().kb_faq_path)
    if not p.exists():
        logger.warning("kb_faq_path not found: %s (will use default)", p)
        # fallback: ลอง path แบบ relative จาก project root
        fallback = Path(__file__).resolve().parent.parent.parent / "src" / "brain" / "kb" / "faq_entries.json"
        if fallback.exists():
            return fallback
        return p
    return p
