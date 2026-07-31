"""CPSC recalls via the SaferProducts.gov REST service.

See docs/sources.md#2-cpsc--saferproductsgov. This is the simplest source:
the response is a bare JSON array with no envelope and no pagination, and the
entire history is only ~9,900 records / 27 MB, so a backfill is one request.

Incrementals filter on LastPublishDate rather than RecallDate -- CPSC amends
published recalls (adding units, images, remedies) without moving RecallDate,
and those edits should flow through to us.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterator

import httpx

from ..http import get
from ..models import NormalizedRecall
from ..util import clean, join_distinct, parse_iso_date, parse_iso_datetime

AGENCY = "CPSC"
BASE_URL = "https://www.saferproducts.gov/RestWebServices/Recall"


def fetch(
    client: httpx.Client,
    since: date | None = None,
    until: date | None = None,
    backfill: bool = False,
) -> Iterator[NormalizedRecall]:
    params: dict[str, Any] = {"format": "json"}
    if not backfill:
        if since:
            params["LastPublishDateStart"] = since.isoformat()
        if until:
            params["LastPublishDateEnd"] = until.isoformat()

    payload = get(client, BASE_URL, params=params).json()
    for record in payload or []:
        normalized = _normalize(record)
        if normalized is not None:
            yield normalized


def _normalize(record: dict[str, Any]) -> NormalizedRecall | None:
    # Verified unique and always populated across all 9,912 historical records;
    # RecallID is a defensive fallback only.
    source_id = clean(record.get("RecallNumber")) or clean(record.get("RecallID"))
    if not source_id:
        return None

    products = record.get("Products") or []
    product = join_distinct(p.get("Name") for p in products) or clean(record.get("Title"))
    brand = join_distinct(m.get("Name") for m in record.get("Manufacturers") or [])
    category = join_distinct(p.get("Type") for p in products)
    hazard = join_distinct(h.get("Name") for h in record.get("Hazards") or [])
    remedy = join_distinct(o.get("Option") for o in record.get("RemedyOptions") or [])

    return NormalizedRecall(
        agency=AGENCY,
        source_id=source_id,
        product=product,
        brand=brand,
        category=category,
        hazard=hazard or clean(record.get("Description")),
        classification=remedy,
        recall_date=parse_iso_date(record.get("RecallDate")),
        published_at=parse_iso_datetime(record.get("LastPublishDate")),
        url=clean(record.get("URL")),
        raw=record,
    )
