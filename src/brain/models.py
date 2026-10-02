"""Pydantic models — request/response ที่ผ่าน /brain."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ─── Request ────────────────────────────────────────────────────────────────────


class ThinkRequest(BaseModel):
    """สิ่งที่ Jwiz/agent อื่น POST เข้า /brain."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="คำถามหรือข้อความจากผู้ใช้",
    )
    agent_id: str = Field(
        "jwiz-customer",
        min_length=1,
        max_length=64,
        description="ใครถาม (예: jwiz-customer, jwiz-admin, future-agent)",
    )
    owner_id: str | None = Field(
        None,
        max_length=128,
        description="lead/user id สำหรับ memory (ถ้ามี)",
    )
    context: dict[str, Any] | None = Field(
        None,
        description="ข้อมูลเสริม: session_id, recent_turns, ฯลฯ",
    )
    options: dict[str, Any] | None = Field(
        None,
        description="เช่น require_citation, max_cost, fallback_ok",
    )


    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


class BirthdayRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    wish_type: str = "general"
    custom_text: str = Field(default="", max_length=5000)

    @field_validator("user_id")
    @classmethod
    def nonblank_user(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_id must not be blank")
        return value.strip()


# ─── Response ───────────────────────────────────────────────────────────────────


class SourceDoc(BaseModel):
    """เอกสารแหล่งที่มาอย่างหนึ่ง."""

    doc: str = ""
    chunk_id: str | None = None
    title: str | None = None
    url: str | None = None
    page: int | None = None


class ComplianceResult(BaseModel):
    """ผลลัพธ์ compliance check."""

    passed: bool
    flags: list[str] = Field(default_factory=list)
    message: str | None = None


class ThinkResponse(BaseModel):
    """สิ่งที่ /brain ส่งกลับ."""

    answer: str
    sources: list[SourceDoc] = Field(default_factory=list)
    compliance: ComplianceResult
    grounded: bool
    route: str = Field(
        ...,
        description="cache_hit | calculator | chunks-only | llm_reason | fallback",
    )
    cost: float = Field(default=0.0, ge=0.0)
    latency_ms: int = Field(default=0, ge=0)
    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="model, config version, ฯลฯ",
    )
    ts: datetime = Field(default_factory=datetime.utcnow)


# ─── Internal ────────────────────────────────────────────────────────────────────


class CacheEntry(BaseModel):
    """entry หนึ่งใน semantic/FAQ cache."""

    query_hash: str
    answer: str
    sources: list[SourceDoc] = Field(default_factory=list)
    route: str
    ts: datetime = Field(default_factory=datetime.utcnow)
    ttl_hours: int = 24
