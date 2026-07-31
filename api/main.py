from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from . import db, openapi_examples as ex
from .params import (
    DEFAULT_PAGE, DEFAULT_PER_PAGE, MAX_PER_PAGE,
    OptionalDate, OptionalText, PageNumber, PerPageNumber,
)
from .schemas import (
    ErrorDetail, ErrorResponse, Health, ItemResponse, ListResponse,
    Pagination, Recall,
)

log = logging.getLogger("api")

VERSION = "0.1.0"
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


PRODUCTION_URL = "https://recall-radar.onrender.com"

DESCRIPTION = """
One API for every US product recall.

The US government publishes recalls across several unrelated agencies, in
different shapes, with different quirks. **recall-radar** fetches them daily,
normalizes them into a single schema, and serves them as clean, searchable JSON.

### Coverage

| Agency | Covers | Records |
|---|---|---|
| **FDA** | Food, drug, and device recalls | 86,683 |
| **NHTSA** | Vehicles, tires, child seats | 15,138 |
| **CPSC** | Consumer products | 9,912 |

Currently **3 agencies, 111,733 recalls**, going back to 1973 for CPSC.
USDA FSIS (meat and poultry) is not yet included — its upstream API is
unreachable behind bot protection.

### Response shape

Every successful list response is `{data, pagination, meta}`; single-item
responses are `{data, meta}`. Every error is `{"error": {code, message, detail}}`.

### Refresh cadence

FDA data refreshes roughly weekly upstream; NHTSA and CPSC daily. Ingestion
runs every day at 06:00 UTC, so a day with no new FDA rows is normal.

### Authentication

Requests must carry the `X-RapidAPI-Proxy-Secret` header, which RapidAPI adds
automatically. `/health` is always open.
"""

TAGS_METADATA = [
    {"name": "recalls", "description": "Query, search, and look up recall records."},
    {"name": "meta", "description": "Service health. No authentication required."},
]

app = FastAPI(
    title="recall-radar",
    version=VERSION,
    summary="A unified US product-recalls API: FDA, CPSC, and NHTSA in one searchable JSON feed.",
    description=DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    servers=[{"url": PRODUCTION_URL, "description": "Production"}],
    contact={"name": "recall-radar", "url": "https://github.com/sm-coding-projects/recall-radar"},
    license_info={"name": "Source data: US Government public domain"},
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

@app.get(
    "/health",
    response_model=Health,
    tags=["meta"],
    summary="Service health",
    operation_id="getHealth",
    response_description="Service status and the total number of recalls held.",
    responses={200: ex.json_example(ex.HEALTH_OK, "Service and database are both healthy.")},
)
def health() -> Health:
    """Liveness check, including a real database round-trip.

    **This endpoint never requires authentication**, so it can be used as an
    uptime check without exposing your proxy secret.

    Returns `200` even when the database is unreachable — with
    `"status": "degraded"` and `"database": "unavailable"` — so that a briefly
    suspended database does not flap an external health check. Use the
    `status` field, not the HTTP code, to distinguish the two.

    The `recalls` field is the total row count, and is `null` when degraded.
    """
    try:
        total = db.fetch_value("SELECT count(*) AS count FROM recalls")
        return Health(status="ok", database="ok", recalls=int(total or 0), version=VERSION)
    except Exception as exc:  # noqa: BLE001
        log.warning("health check: database unreachable: %s", exc)
        return Health(status="degraded", database="unavailable", recalls=None, version=VERSION)


@app.get(
    "/recalls",
    response_model=ListResponse[Recall],
    tags=["recalls"],
    summary="List recalls with filters and pagination",
    operation_id="listRecalls",
    response_description="A page of recalls, newest first, plus pagination metadata.",
    responses={
        200: ex.json_example(ex.LIST_RECALLS, "A page of matching recalls."),
        400: ex.BAD_REQUEST,
        422: ex.VALIDATION_ERROR,
        **ex.COMMON_ERRORS,
    },
)
def list_recalls(
    agency: Annotated[OptionalText, Query(
        description="Filter by agency, case-insensitive. Blank means no filter.",
        examples=["CPSC"],
    )] = None,
    category: Annotated[OptionalText, Query(
        description="Case-insensitive substring match on category. Blank means no filter.",
        examples=["Food"],
    )] = None,
    since: Annotated[OptionalDate, Query(
        description="Only recalls on or after this date. Blank means no lower bound.",
        examples=["2026-07-01"],
    )] = None,
    until: Annotated[OptionalDate, Query(
        description="Only recalls on or before this date. Blank means no upper bound.",
        examples=["2026-07-31"],
    )] = None,
    page: Annotated[PageNumber, Query(
        description="1-based page number. Blank defaults to 1.", examples=[1],
    )] = None,
    per_page: Annotated[PerPageNumber, Query(
        description=f"Results per page, max {MAX_PER_PAGE}. Blank defaults to {DEFAULT_PER_PAGE}.",
        examples=[25],
    )] = None,
) -> ListResponse[Recall]:
    """Browse recalls across all agencies, newest first.

    Results are ordered by `recall_date` descending. All filters are optional
    and combine with AND.

    - `agency` — exact match, case-insensitive (`FDA`, `CPSC`, `NHTSA`)
    - `category` — case-insensitive **substring** match, so `category=food`
      matches `Food`, and `category=brake` matches NHTSA component names
    - `since` / `until` — inclusive bounds on `recall_date` (`YYYY-MM-DD`)

    Pagination caps at **100 per page**; asking for more returns `422`.
    `pagination.total` is the count of all matches, not just this page, so you
    can size a full pull before making it.

    Passing a `since` later than `until` returns `400` rather than an empty
    page, so a swapped-argument bug surfaces instead of looking like no data.

    Every parameter may be sent blank (`?agency=&since=`) — a blank value means
    "not supplied", which is what API gateways emit for unset optional fields.
    """
    page = page or DEFAULT_PAGE
    per_page = per_page or DEFAULT_PER_PAGE

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


@app.get(
    "/recalls/latest",
    response_model=ListResponse[Recall],
    tags=["recalls"],
    summary="The 50 most recent recalls",
    operation_id="getLatestRecalls",
    response_description="The 50 newest recalls across all agencies.",
    responses={
        200: ex.json_example(ex.LATEST_RECALLS, "The 50 newest recalls."),
        **ex.COMMON_ERRORS,
    },
)
def latest_recalls() -> ListResponse[Recall]:
    """The 50 most recent recalls across all agencies, newest first.

    A fixed-size convenience feed for dashboards and alerting — no parameters,
    no pagination. `pagination` is `null` here by design.

    Equivalent to `/recalls?per_page=50`, but cheaper: it skips the `COUNT`
    query that `/recalls` runs to populate pagination.

    For anything filtered or deeper than 50 rows, use `/recalls`.
    """
    rows = db.fetch_all(
        f"""
        SELECT {RECALL_COLUMNS} FROM recalls
        ORDER BY recall_date DESC NULLS LAST, id DESC
        LIMIT %(limit)s
        """,
        {"limit": LATEST_LIMIT},
    )
    return ListResponse[Recall](data=[Recall(**row) for row in rows], meta={"limit": LATEST_LIMIT})


@app.get(
    "/recalls/search",
    response_model=ListResponse[Recall],
    tags=["recalls"],
    summary="Full-text search over recalls",
    operation_id="searchRecalls",
    response_description="Matching recalls ranked by relevance.",
    responses={
        200: ex.json_example(ex.SEARCH_RECALLS, "Recalls matching the query, most relevant first."),
        422: ex.VALIDATION_ERROR,
        **ex.COMMON_ERRORS,
    },
)
def search_recalls(
    q: Annotated[str, Query(
        min_length=2,
        description="Search query. Required, minimum 2 characters.",
        examples=["listeria"],
    )],
    agency: Annotated[OptionalText, Query(
        description="Optionally restrict to one agency. Blank means all agencies.",
        examples=["FDA"],
    )] = None,
    page: Annotated[PageNumber, Query(
        description="1-based page number. Blank defaults to 1.", examples=[1],
    )] = None,
    per_page: Annotated[PerPageNumber, Query(
        description=f"Results per page, max {MAX_PER_PAGE}. Blank defaults to {DEFAULT_PER_PAGE}.",
        examples=[25],
    )] = None,
) -> ListResponse[Recall]:
    """Postgres full-text search across product name, brand, and hazard text.

    Results are ranked by relevance, then by recall date.

    Supports web-search style operators:

    | Query | Meaning |
    |---|---|
    | `listeria cheese` | both words |
    | `"air bag"` | exact phrase |
    | `"air bag" -inflator` | phrase, excluding a term |
    | `salmonella or listeria` | either word |

    Matching is stemmed English, so `recalled` also matches `recall`.
    Punctuation and stray operators are handled gracefully rather than
    returning an error.

    Searching is the right tool for "is this product recalled?"; use
    `/recalls` when you want to browse or export a date range.

    `agency`, `page`, and `per_page` may be sent blank, which means "not
    supplied". `q` is required: an empty query returns `422`.
    """
    page = page or DEFAULT_PAGE
    per_page = per_page or DEFAULT_PER_PAGE

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


@app.get(
    "/recalls/{agency}/{source_id:path}",
    response_model=ItemResponse[Recall],
    tags=["recalls"],
    summary="Get one recall by agency and source ID",
    operation_id="getRecallById",
    response_description="The requested recall.",
    responses={
        200: ex.json_example(ex.SINGLE_RECALL, "The requested recall."),
        404: ex.NOT_FOUND,
        **ex.COMMON_ERRORS,
    },
)
def get_recall(
    agency: str = Path(
        ..., description="Agency code, case-insensitive.", examples=["NHTSA"],
    ),
    source_id: str = Path(
        ...,
        description="The agency's own recall identifier, exactly as it appears in `source_id`.",
        examples=["26V481000"],
    ),
) -> ItemResponse[Recall]:
    """Look up a single recall by the identifier its own agency uses.

    This is the stable, agency-native key — use it to re-fetch a recall you
    have already seen, rather than the internal `id`, which is not guaranteed
    stable across reloads.

    Identifier formats differ by agency:

    | Agency | Format | Example |
    |---|---|---|
    | FDA | `recall_number` | `D-0690-2026` |
    | CPSC | `RecallNumber` | `26636` |
    | NHTSA | NHTSA campaign number | `26V481000` |

    Identifiers containing `/` are accepted as-is and do not need encoding.

    Returns `404` if no recall matches that agency and identifier.
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


# --------------------------------------------------------------------------
# OpenAPI post-processing
# --------------------------------------------------------------------------

def _promote_parameter_examples(schema: dict[str, Any]) -> None:
    """Copy each parameter's schema-level example up to the parameter itself.

    FastAPI emits JSON-Schema style examples nested inside the parameter's
    schema (`schema.examples: ["listeria"]`). API consoles -- RapidAPI's test
    playground among them -- prefill their forms from the OpenAPI-style
    parameter-level `example` instead, and ignore the nested one.

    With nothing to prefill, the console submits blanks. That made two working
    endpoints look broken on the listing: `/recalls/search` returned 422
    (`q` is required and cannot be empty) and `/recalls/{agency}/{source_id}`
    returned 404 (the path collapsed to `/recalls//`).

    Hoisting the value fixes the console without weakening any validation --
    a caller who deliberately sends `q=` still gets a 422, which is correct.
    """
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get("parameters", []):
                examples = parameter.get("schema", {}).get("examples")
                if examples and "example" not in parameter:
                    parameter["example"] = examples[0]


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        summary=app.summary,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=app.servers,
        contact=app.contact,
        license_info=app.license_info,
    )
    _promote_parameter_examples(schema)
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
