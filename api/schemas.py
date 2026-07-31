from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Recall(BaseModel):
    id: int
    agency: str
    source_id: str
    product: str | None = None
    brand: str | None = None
    category: str | None = None
    hazard: str | None = None
    classification: str | None = None
    recall_date: date | None = None
    published_at: datetime | None = None
    url: str | None = None
    ingested_at: datetime | None = None


class Pagination(BaseModel):
    page: int = Field(..., ge=1)
    per_page: int = Field(..., ge=1)
    total: int = Field(..., ge=0)
    total_pages: int = Field(..., ge=0)
    has_next: bool
    has_prev: bool


class ListResponse(BaseModel, Generic[T]):
    """Envelope for every successful list endpoint."""

    data: list[T]
    pagination: Pagination | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ItemResponse(BaseModel, Generic[T]):
    data: T
    meta: dict[str, Any] = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    code: str
    message: str
    detail: Any | None = None


class ErrorResponse(BaseModel):
    """Envelope for every failure. Always `{"error": {...}}`."""

    error: ErrorDetail


class Health(BaseModel):
    status: str
    database: str
    recalls: int | None = None
    version: str
