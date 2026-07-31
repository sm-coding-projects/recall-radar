"""openFDA enforcement reports: food, drug, and device recalls.

See docs/sources.md#1-openfda--fda. Two upstream quirks drive this design:

* A search matching nothing returns **HTTP 404**, not an empty result set.
  FDA refreshes roughly weekly, so a daily incremental legitimately finds
  nothing most days -- treating 404 as an error would fail the cron job
  more often than not.
* `skip` caps at 25,000 while the device dataset holds ~39,600 records, so a
  skip-paginated backfill silently truncates. Backfill walks calendar-year
  windows instead; each window stays far below the cap.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Iterator

import httpx

from ..http import get
from ..models import NormalizedRecall
from ..util import (
    as_utc_datetime, clean, parse_compact_date, plausible_date, stable_hash,
)

log = logging.getLogger(__name__)

AGENCY = "FDA"
BASE_URL = "https://api.fda.gov"
ENDPOINTS = ("food", "drug", "device")

PAGE_SIZE = 1000       # documented maximum
MAX_SKIP = 25_000      # documented maximum
EARLIEST_YEAR = 2004   # openFDA enforcement data starts around here

# FDA publishes no per-recall permalink, so point at the official recalls index.
RECALLS_INDEX = "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts"

# A recall cannot plausibly be initiated decades before FDA reports it, so a
# huge gap means the initiation date is mistyped. Measured against the live
# archive, genuine gaps tail off smoothly to ~10 years (4 records) with a
# single outlier at 15.4 years -- then nothing until 82.9 and 1800.1 years,
# both of which are transposed digits:
#
#   Z-0139-2014  "19301211"  an Intuitive Surgical device reported in 2013
#   F-0880-2013  "02121207"  a transposition of "20121207"
#
# 20 years sits in that empty band: comfortably past every legitimate record,
# comfortably short of both corruptions.
MAX_INITIATION_LEAD = timedelta(days=round(365.25 * 20))


def fetch(
    client: httpx.Client,
    since: date | None = None,
    until: date | None = None,
    backfill: bool = False,
) -> Iterator[NormalizedRecall]:
    for endpoint in ENDPOINTS:
        if backfill:
            today = date.today()
            for year in range(EARLIEST_YEAR, today.year + 1):
                window_start = date(year, 1, 1)
                window_end = min(date(year, 12, 31), today)
                yield from _fetch_window(client, endpoint, window_start, window_end)
        else:
            yield from _fetch_window(client, endpoint, since, until)


def _fetch_window(
    client: httpx.Client,
    endpoint: str,
    since: date | None,
    until: date | None,
) -> Iterator[NormalizedRecall]:
    url = f"{BASE_URL}/{endpoint}/enforcement.json"
    search = _date_query(since, until)
    skip = 0

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE, "skip": skip, "sort": "report_date:desc"}
        if search:
            params["search"] = search

        try:
            payload = get(client, url, params=params).json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return  # "No matches found!" -- an empty window, not a failure.
            raise

        results = payload.get("results") or []
        for record in results:
            normalized = _normalize(record, endpoint)
            if normalized is not None:
                yield normalized

        skip += len(results)
        total = payload.get("meta", {}).get("results", {}).get("total", 0)
        if len(results) < PAGE_SIZE or skip >= total:
            return
        if skip >= MAX_SKIP:
            log.warning(
                "FDA %s: hit the %d skip cap with %d of %d records in window %s..%s; "
                "narrow the window to capture the remainder",
                endpoint, MAX_SKIP, skip, total, since, until,
            )
            return


def _date_query(since: date | None, until: date | None) -> str | None:
    if since is None and until is None:
        return None
    low = since.strftime("%Y%m%d") if since else "19000101"
    high = until.strftime("%Y%m%d") if until else date.today().strftime("%Y%m%d")
    return f"report_date:[{low} TO {high}]"


def _normalize(record: dict[str, Any], endpoint: str) -> NormalizedRecall | None:
    source_id = _source_id(record, endpoint)
    if source_id is None:
        return None

    # openFDA ships occasional transposed dates that parse cleanly but are
    # centuries off. Reject those and fall back to report_date, rather than
    # storing a value that sorts ahead of every real recall.
    recall_date = _guarded_date(record, "recall_initiation_date")
    report_date = _guarded_date(record, "report_date")

    # Absolute bounds alone cannot catch every mistyped date: "19301211" is a
    # perfectly ordinary-looking 1930, and the floor has to stay below 1973 to
    # preserve CPSC's genuine archive. Comparing the two fields catches it.
    if recall_date and report_date and (report_date - recall_date) > MAX_INITIATION_LEAD:
        log.warning(
            "FDA %s: recall_initiation_date %s precedes report_date %s by over "
            "%d years; ignoring it and using report_date",
            clean(record.get("recall_number")) or record.get("event_id"),
            recall_date, report_date, MAX_INITIATION_LEAD.days // 365,
        )
        recall_date = None

    return NormalizedRecall(
        agency=AGENCY,
        source_id=source_id,
        product=clean(record.get("product_description")),
        brand=clean(record.get("recalling_firm")),
        category=clean(record.get("product_type")) or endpoint.title(),
        hazard=clean(record.get("reason_for_recall")),
        classification=clean(record.get("classification")),
        recall_date=recall_date or report_date,
        published_at=as_utc_datetime(report_date),
        url=RECALLS_INDEX,
        raw=record,
    )


def _guarded_date(record: dict[str, Any], field: str) -> date | None:
    """Parse a date field, discarding implausible values with a warning."""
    raw = record.get(field)
    parsed = parse_compact_date(raw)
    checked = plausible_date(parsed)
    if parsed is not None and checked is None:
        log.warning(
            "FDA %s: implausible %s %r parsed as %s; ignoring",
            clean(record.get("recall_number")) or record.get("event_id"),
            field, raw, parsed,
        )
    return checked


def _source_id(record: dict[str, Any], endpoint: str) -> str | None:
    """`recall_number`, or a deterministic fallback when FDA leaves it blank.

    Unclassified recalls ship with an empty `recall_number` but are exactly the
    newest and most newsworthy rows, so they are kept under a synthetic id
    rather than dropped. The id is derived from stable fields so repeat runs
    upsert the same row instead of duplicating it.
    """
    recall_number = clean(record.get("recall_number"))
    if recall_number:
        return recall_number

    event_id = clean(record.get("event_id"))
    description = clean(record.get("product_description"))
    if not event_id and not description:
        return None  # Nothing stable to key on; skip rather than guess.
    return f"EVT-{endpoint}-{event_id or 'na'}-{stable_hash(description)}"
