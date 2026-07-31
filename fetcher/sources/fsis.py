"""USDA FSIS meat, poultry, and egg recalls plus public health alerts.

See docs/sources.md#3-usda-fsis.

NOTE ON ACCESS: fsis.usda.gov sits behind Akamai and rejects non-US traffic
with a blanket 403 across the whole domain -- homepage included. This adapter
therefore cannot be exercised from a non-US developer machine, but works
normally from GitHub Actions and Render US regions. The 403 path below raises
a message that says so explicitly, rather than a bare HTTPStatusError, because
otherwise it looks like a bug in this code.

The field mapping was reconstructed from three independent public consumers of
this API (a dbt staging model, a typed client, and a normalizer) and is
verified against live data on the first successful US-side run.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterator

import httpx

from ..http import get
from ..models import NormalizedRecall
from ..util import (
    as_utc_datetime, clean, join_distinct, parse_iso_date, strip_html,
)

log = logging.getLogger(__name__)

AGENCY = "FSIS"
BASE_URL = "https://www.fsis.usda.gov/fsis/api/recall/v/1"
CATEGORY = "Meat and Poultry"

GEO_BLOCK_HINT = (
    "FSIS returned HTTP 403. The whole fsis.usda.gov domain is geo-restricted "
    "to US traffic, so this is expected from a non-US IP and is not a bug in "
    "the adapter. Run this fetch from GitHub Actions or Render (US egress). "
    "See docs/sources.md#3-usda-fsis."
)


def fetch(
    client: httpx.Client,
    since: date | None = None,
    until: date | None = None,
    backfill: bool = False,
) -> Iterator[NormalizedRecall]:
    # The endpoint returns the full current set as one array with no
    # pagination, so date filtering is applied client-side. That keeps the
    # request identical between incremental and backfill runs.
    try:
        payload = get(client, BASE_URL).json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise RuntimeError(GEO_BLOCK_HINT) from exc
        raise

    for record in payload or []:
        normalized = _normalize(record)
        if normalized is None:
            continue
        if not backfill and normalized.recall_date is not None:
            if since and normalized.recall_date < since:
                continue
            if until and normalized.recall_date > until:
                continue
        yield normalized


def _normalize(record: dict[str, Any]) -> NormalizedRecall | None:
    source_id = clean(record.get("field_recall_number"))
    if not source_id:
        return None

    recall_date = parse_iso_date(record.get("field_recall_date"))
    reason = _as_text(record.get("field_recall_reason"))
    summary = strip_html(record.get("field_summary"))

    return NormalizedRecall(
        agency=AGENCY,
        source_id=source_id,
        product=_as_text(record.get("field_product_items")) or strip_html(record.get("field_title")),
        brand=_as_text(record.get("field_establishment")),
        category=CATEGORY,
        hazard=reason or summary,
        # Carries a 4th undocumented value, "Public Health Alert", alongside
        # Class I/II/III -- accepted rather than rejected.
        classification=clean(record.get("field_recall_classification")),
        recall_date=recall_date,
        published_at=as_utc_datetime(recall_date),
        url=clean(record.get("field_recall_url")),
        raw=record,
    )


def _as_text(value: object) -> str | None:
    """FSIS returns some fields as a list and others as an HTML string."""
    if isinstance(value, list):
        return join_distinct(strip_html(item) for item in value)
    return strip_html(value)
