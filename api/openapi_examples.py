"""Example payloads for the OpenAPI schema.

Kept out of main.py so the route handlers stay readable. Every example below
is a real response captured from the live service, not an invented one -- so
what a buyer sees on RapidAPI matches what they actually get back.
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

FDA_RECALL: dict[str, Any] = {
    "id": 100,
    "agency": "FDA",
    "source_id": "D-0690-2026",
    "product": (
        "BD ChloraPrep Clear, (2% w/v chlorhexidine gluconate (CHG) and 70% v/v "
        "isopropyl alcohol), 60 x 1 mL applicators/carton, STERILE SOLUTION, "
        "CareFusion 123, LLC, El Paso, TX. NDC 54365-400-31"
    ),
    "brand": "CareFusion 213, LLC",
    "category": "Drugs",
    "hazard": (
        "Lack of Assurance of Sterility: Affected product may exhibit an open or "
        "incomplete seal on the packaging of the applicator"
    ),
    "classification": "Class II",
    "recall_date": "2026-07-09",
    "published_at": "2026-07-22T00:00:00Z",
    "url": "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts",
    "ingested_at": "2026-07-31T04:07:23.113838Z",
}

CPSC_RECALL: dict[str, Any] = {
    "id": 401,
    "agency": "CPSC",
    "source_id": "26636",
    "product": "Sviyatp Pool Drain Covers",
    "brand": None,
    "category": None,
    "hazard": (
        "The recalled drain covers violate the entrapment protection standards of "
        "the Virginia Graeme Baker Pool and Spa Safety Act (VGBA), posing deadly "
        "entrapment and drowning hazards to consumers."
    ),
    "classification": "Refund",
    "recall_date": "2026-07-23",
    "published_at": "2026-07-24T00:00:00Z",
    "url": (
        "https://www.cpsc.gov/Recalls/2026/Sviyatp-Pool-Drain-Covers-Recalled-Due-to-"
        "Risk-of-Serious-Injury-or-Death-from-Entrapment-and-Drowning-Hazards"
    ),
    "ingested_at": "2026-07-31T04:07:22.046254Z",
}

NHTSA_RECALL: dict[str, Any] = {
    "id": 513,
    "agency": "NHTSA",
    "source_id": "26V481000",
    "product": "AMG GLB35 4MATIC; C 300; C 300 4MATIC; CLE 300 4MATIC (+24 more) (2019-2026)",
    "brand": "MERCEDES-BENZ",
    "category": "LATCHES/LOCKS/LINKAGES:DOORS:LOCK",
    "hazard": (
        "The micro-switch in the driver's door lock may corrode and fail to detect an "
        "open door, preventing the electronic parking brake from engaging "
        "automatically. This may result in a vehicle rollaway."
    ),
    "classification": "Vehicle",
    "recall_date": "2026-07-24",
    "published_at": "2026-07-27T00:00:00Z",
    "url": "https://www.nhtsa.gov/recalls?nhtsaId=26V481000",
    "ingested_at": "2026-07-31T04:07:31.164779Z",
}


# --------------------------------------------------------------------------
# Envelopes
# --------------------------------------------------------------------------

def json_example(example: Any, description: str) -> dict[str, Any]:
    return {"description": description, "content": {"application/json": {"example": example}}}


HEALTH_OK = {
    "status": "ok",
    "database": "ok",
    "recalls": 111733,
    "version": "0.1.0",
}

HEALTH_DEGRADED = {
    "status": "degraded",
    "database": "unavailable",
    "recalls": None,
    "version": "0.1.0",
}

LIST_RECALLS = {
    "data": [CPSC_RECALL, NHTSA_RECALL],
    "pagination": {
        "page": 1,
        "per_page": 25,
        "total": 9912,
        "total_pages": 397,
        "has_next": True,
        "has_prev": False,
    },
    "meta": {"filters": {"agency": "CPSC", "since": "2026-07-01"}},
}

LATEST_RECALLS = {
    "data": [NHTSA_RECALL, CPSC_RECALL, FDA_RECALL],
    "pagination": None,
    "meta": {"limit": 50},
}

SEARCH_RECALLS = {
    "data": [FDA_RECALL],
    "pagination": {
        "page": 1,
        "per_page": 25,
        "total": 7498,
        "total_pages": 300,
        "has_next": True,
        "has_prev": False,
    },
    "meta": {"query": "listeria"},
}

SINGLE_RECALL = {"data": NHTSA_RECALL, "meta": {}}


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

def _error(code: str, message: str, detail: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        error["detail"] = detail
    return {"error": error}


UNAUTHORIZED = json_example(
    _error("unauthorized", "Missing or invalid X-RapidAPI-Proxy-Secret header."),
    "The request did not come through RapidAPI.",
)

NOT_FOUND = json_example(
    _error("not_found", "No FDA recall with source_id 'H-9999-2099'."),
    "No recall matches that agency and source_id.",
)

BAD_REQUEST = json_example(
    _error("bad_request", "`since` must not be after `until`."),
    "The parameters parsed correctly but do not make sense together.",
)

VALIDATION_ERROR = json_example(
    _error(
        "invalid_parameters",
        "One or more query parameters are invalid.",
        [{"field": "per_page", "reason": "Input should be less than or equal to 100"}],
    ),
    "A parameter failed validation, e.g. per_page above 100 or a malformed date.",
)

INTERNAL_ERROR = json_example(
    _error("internal_error", "An unexpected error occurred."),
    "Unexpected server error. Details are logged server-side, never returned.",
)

# Applied to every authenticated route.
COMMON_ERRORS: dict[int | str, dict[str, Any]] = {
    401: UNAUTHORIZED,
    500: INTERNAL_ERROR,
}
