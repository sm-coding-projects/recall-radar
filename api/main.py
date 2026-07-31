from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import db
from .schemas import (
    ErrorDetail, ErrorResponse, Health, ItemResponse, ListResponse,
    Pagination, Recall,
)

log = logging.getLogger("api")

VERSION = "0.1.0"
MAX_PER_PAGE = 100
DEFAULT_PER_PAGE = 25
LATEST_LIMIT = 50

PROXY_SECRET_HEADER = "X-RapidAPI-Proxy-Secret"
PUBLIC_PATHS = {"/health", "/", "/docs", "/redoc", "/openapi.json"}

RECALL_COLUMNS = """
    id, agency, source_id, product, brand, category, hazard,
    classification, recall_date, published_at, url, ingested_at
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    db.close_pool()


app = FastAPI(
    title="recall-radar",
    version=VERSION,
    description=(
        "A unified US product-recalls API aggregating FDA, CPSC, USDA FSIS, "
        "and NHTSA recalls into one searchable JSON feed."
    ),
    lifespan=lifespan,
)


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

@app.middleware("http")
async def verify_rapidapi_proxy_secret(request: Request, call_next):
    """Reject traffic that did not come through RapidAPI.

    Only enforced when RAPIDAPI_PROXY_SECRET is set, so local development and
    the free self-hosted path keep working unauthenticated. /health is always
    open -- Render's health checks cannot send the header.
    """
    secret = os.environ.get("RAPIDAPI_PROXY_SECRET")
    if secret and request.url.path not in PUBLIC_PATHS:
        provided = request.headers.get(PROXY_SECRET_HEADER)
        # compare_digest keeps the check constant-time; the `not provided`
        # guard is needed because compare_digest rejects None outright.
        if not provided or not secrets.compare_digest(provided, secret):
            return _error_response(
                401, "unauthorized",
                "Missing or invalid X-RapidAPI-Proxy-Secret header.",
            )
    return await call_next(request)


# --------------------------------------------------------------------------
# Error envelopes
# --------------------------------------------------------------------------

def _error_response(status: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message, detail=detail))
    return JSONResponse(status_code=status, content=payload.model_dump(exclude_none=True))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    codes = {400: "bad_request", 401: "unauthorized", 404: "not_found", 429: "rate_limited"}
    return _error_response(
        exc.status_code,
        codes.get(exc.status_code, "error"),
        exc.detail if isinstance(exc.detail, str) else "Request failed.",
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        422, "invalid_parameters", "One or more query parameters are invalid.",
        [{"field": ".".join(str(p) for p in e["loc"][1:]), "reason": e["msg"]} for e in exc.errors()],
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the detail, return a generic message -- never leak a connection
    # string or driver internals to a paying caller.
    log.exception("unhandled error on %s", request.url.path)
    return _error_response(500, "internal_error", "An unexpected error occurred.")


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/health", response_model=Health, tags=["meta"])
def health() -> Health:
    """Liveness plus a real database round-trip. Never requires auth."""
    try:
        total = db.fetch_value("SELECT count(*) AS count FROM recalls")
        return Health(status="ok", database="ok", recalls=int(total or 0), version=VERSION)
    except Exception as exc:  # noqa: BLE001
        log.warning("health check: database unreachable: %s", exc)
        return Health(status="degraded", database="unavailable", recalls=None, version=VERSION)


@app.get("/recalls", response_model=ListResponse[Recall], tags=["recalls"])
def list_recalls(
    agency: str | None = Query(None, description="Filter by agency: FDA, CPSC, FSIS, NHTSA."),
    category: str | None = Query(None, description="Case-insensitive substring match on category."),
    since: date | None = Query(None, description="Only recalls on/after this date (YYYY-MM-DD)."),
    until: date | None = Query(None, description="Only recalls on/before this date (YYYY-MM-DD)."),
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE),
) -> ListResponse[Recall]:
    """Recalls newest-first, with filters and pagination (max 100 per page)."""
    if since and until and since > until:
        raise HTTPException(400, "`since` must not be after `until`.")

    where, params = _build_filters(agency, category, since, until)
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = int(db.fetch_value(f"SELECT count(*) AS count FROM recalls {clause}", params) or 0)
    rows = db.fetch_all(
        f"""
        SELECT {RECALL_COLUMNS} FROM recalls {clause}
        ORDER BY recall_date DESC NULLS LAST, id DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    )

    return ListResponse[Recall](
        data=[Recall(**row) for row in rows],
        pagination=_paginate(page, per_page, total),
        meta={"filters": _active_filters(agency, category, since, until)},
    )


@app.get("/recalls/latest", response_model=ListResponse[Recall], tags=["recalls"])
def latest_recalls() -> ListResponse[Recall]:
    """The 50 most recent recalls across all agencies."""
    rows = db.fetch_all(
        f"""
        SELECT {RECALL_COLUMNS} FROM recalls
        ORDER BY recall_date DESC NULLS LAST, id DESC
        LIMIT %(limit)s
        """,
        {"limit": LATEST_LIMIT},
    )
    return ListResponse[Recall](data=[Recall(**row) for row in rows], meta={"limit": LATEST_LIMIT})


@app.get("/recalls/search", response_model=ListResponse[Recall], tags=["recalls"])
def search_recalls(
    q: str = Query(..., min_length=2, description="Full-text query over product, brand, and hazard."),
    agency: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE),
) -> ListResponse[Recall]:
    """Postgres full-text search, ranked by relevance.

    Uses websearch_to_tsquery so callers get quoted phrases, OR, and leading -
    for free, and so malformed input degrades instead of raising -- unlike
    to_tsquery, which errors on stray syntax.
    """
    params: dict[str, Any] = {"q": q}
    where = ["search_tsv @@ websearch_to_tsquery('english', %(q)s)"]
    if agency:
        where.append("agency = %(agency)s")
        params["agency"] = agency.upper()
    clause = " AND ".join(where)

    total = int(db.fetch_value(f"SELECT count(*) AS count FROM recalls WHERE {clause}", params) or 0)
    rows = db.fetch_all(
        f"""
        SELECT {RECALL_COLUMNS}
        FROM recalls
        WHERE {clause}
        ORDER BY ts_rank_cd(search_tsv, websearch_to_tsquery('english', %(q)s)) DESC,
                 recall_date DESC NULLS LAST, id DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    )

    return ListResponse[Recall](
        data=[Recall(**row) for row in rows],
        pagination=_paginate(page, per_page, total),
        meta={"query": q},
    )


@app.get("/recalls/{agency}/{source_id:path}", response_model=ItemResponse[Recall], tags=["recalls"])
def get_recall(
    agency: str = Path(..., description="FDA, CPSC, FSIS, or NHTSA."),
    source_id: str = Path(..., description="The agency's own recall identifier."),
) -> ItemResponse[Recall]:
    """A single recall by its agency-native id.

    source_id uses :path because agency identifiers legitimately contain
    slashes (some FSIS recall numbers do), which would otherwise 404.
    """
    row = db.fetch_one(
        f"SELECT {RECALL_COLUMNS} FROM recalls WHERE agency = %(agency)s AND source_id = %(source_id)s",
        {"agency": agency.upper(), "source_id": source_id},
    )
    if row is None:
        raise HTTPException(404, f"No {agency.upper()} recall with source_id '{source_id}'.")
    return ItemResponse[Recall](data=Recall(**row))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _build_filters(
    agency: str | None, category: str | None, since: date | None, until: date | None,
) -> tuple[list[str], dict[str, Any]]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if agency:
        where.append("agency = %(agency)s")
        params["agency"] = agency.upper()
    if category:
        where.append("category ILIKE %(category)s")
        params["category"] = f"%{category}%"
    if since:
        where.append("recall_date >= %(since)s")
        params["since"] = since
    if until:
        where.append("recall_date <= %(until)s")
        params["until"] = until
    return where, params


def _active_filters(
    agency: str | None, category: str | None, since: date | None, until: date | None,
) -> dict[str, Any]:
    filters = {
        "agency": agency.upper() if agency else None,
        "category": category,
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
    }
    return {k: v for k, v in filters.items() if v is not None}


def _paginate(page: int, per_page: int, total: int) -> Pagination:
    total_pages = (total + per_page - 1) // per_page
    return Pagination(
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )
