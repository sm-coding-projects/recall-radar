"""NHTSA vehicle recalls via the ODI flat file.

See docs/sources.md#4-nhtsa. We deliberately do NOT use api.nhtsa.gov:
it has no date filter (recallsByVehicle needs make+model+year, so a full sweep
would be tens of thousands of requests) and its ReportReceivedDate field mixes
DD/MM/YYYY and MM/DD/YYYY, which cannot be parsed safely. The flat file has
clean YYYYMMDD dates, refreshes daily, and is a single download.

Two structural details:

* The file is ~309 MB uncompressed, so it is streamed from the zip rather than
  read into memory.
* It carries one row per campaign x make x model x year. Our table is one row
  per recall, so rows are grouped by CAMPNO and the vehicle fields aggregated.
  Without that grouping a single Ford campaign would insert hundreds of rows.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date
from typing import Any, Iterator

import httpx

from ..models import NormalizedRecall
from ..util import clean, join_distinct, parse_compact_date, as_utc_datetime

log = logging.getLogger(__name__)

AGENCY = "NHTSA"
FLAT_FILE_URL = "https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip"

# Field order from the official dictionary: static.nhtsa.gov/odi/ffdd/rcl/RCL.txt
COLUMNS = (
    "RECORD_ID", "CAMPNO", "MAKETXT", "MODELTXT", "YEARTXT", "MFGCAMPNO",
    "COMPNAME", "MFGNAME", "BGMAN", "ENDMAN", "RCLTYPECD", "POTAFF", "ODATE",
    "INFLUENCED_BY", "MFGTXT", "RCDATE", "DATEA", "RPNO", "FMVSS",
    "DESC_DEFECT", "CONEQUENCE_DEFECT", "CORRECTIVE_ACTION", "NOTES",
    "RCL_CMPT_ID", "MFR_COMP_NAME", "MFR_COMP_DESC", "MFR_COMP_PTNO",
    "DO_NOT_DRIVE", "PARK_OUTSIDE",
)

RECALL_TYPES = {
    "V": "Vehicle",
    "E": "Equipment",
    "C": "Child Restraint",
    "T": "Tire",
}


def fetch(
    client: httpx.Client,
    since: date | None = None,
    until: date | None = None,
    backfill: bool = False,
) -> Iterator[NormalizedRecall]:
    if backfill:
        since = until = None

    with client.stream("GET", FLAT_FILE_URL, timeout=300.0) as response:
        response.raise_for_status()
        payload = io.BytesIO(response.read())

    with zipfile.ZipFile(payload) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as handle:
            # Upstream is not valid UTF-8 throughout; latin-1 round-trips every
            # byte rather than raising partway through a 309 MB stream.
            text = io.TextIOWrapper(handle, encoding="latin-1", newline="")
            yield from _group_campaigns(text, since, until)


def _group_campaigns(
    lines: Iterator[str],
    since: date | None,
    until: date | None,
) -> Iterator[NormalizedRecall]:
    """Collapse rows to one record per CAMPNO.

    Rows for a campaign are contiguous in practice but not guaranteed to be,
    so campaigns are accumulated in a dict and emitted at the end. Only
    aggregates are retained -- never the raw rows -- to bound memory.
    """
    campaigns: dict[str, dict[str, Any]] = {}
    reader = csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)

    for row in reader:
        if len(row) < len(COLUMNS):
            continue
        record = dict(zip(COLUMNS, (cell.strip() for cell in row)))

        campno = clean(record.get("CAMPNO"))
        if not campno:
            continue

        received = parse_compact_date(record.get("RCDATE"))
        if since and (received is None or received < since):
            continue
        if until and (received is None or received > until):
            continue

        entry = campaigns.get(campno)
        if entry is None:
            entry = {"first": record, "makes": [], "models": [], "years": []}
            campaigns[campno] = entry
        entry["makes"].append(record.get("MAKETXT"))
        entry["models"].append(record.get("MODELTXT"))
        entry["years"].append(record.get("YEARTXT"))

    for campno, entry in campaigns.items():
        yield _normalize(campno, entry)


def _normalize(campno: str, entry: dict[str, Any]) -> NormalizedRecall:
    record = entry["first"]
    received = parse_compact_date(record.get("RCDATE"))
    created = parse_compact_date(record.get("DATEA"))

    # 9999 is the documented sentinel for "unknown / not applicable".
    years = sorted({y for y in entry["years"] if y and y != "9999"})
    models = join_distinct(entry["models"])
    year_range = f" ({years[0]}-{years[-1]})" if len(years) > 1 else (f" ({years[0]})" if years else "")
    product = f"{models}{year_range}" if models else clean(record.get("COMPNAME"))

    hazard = clean(record.get("DESC_DEFECT"))
    consequence = clean(record.get("CONEQUENCE_DEFECT"))  # misspelled upstream
    if hazard and consequence:
        hazard = f"{hazard} {consequence}"

    return NormalizedRecall(
        agency=AGENCY,
        source_id=campno,
        product=product,
        brand=join_distinct(entry["makes"]) or clean(record.get("MFGNAME")),
        category=clean(record.get("COMPNAME")),
        hazard=hazard or consequence,
        classification=RECALL_TYPES.get(clean(record.get("RCLTYPECD")) or "", clean(record.get("RCLTYPECD"))),
        recall_date=received,
        published_at=as_utc_datetime(created or received),
        url=f"https://www.nhtsa.gov/recalls?nhtsaId={campno}",
        raw={
            "CAMPNO": campno,
            "MFGNAME": record.get("MFGNAME"),
            "MFGCAMPNO": record.get("MFGCAMPNO"),
            "COMPNAME": record.get("COMPNAME"),
            "RCLTYPECD": record.get("RCLTYPECD"),
            "POTAFF": record.get("POTAFF"),
            "RCDATE": record.get("RCDATE"),
            "DATEA": record.get("DATEA"),
            "DESC_DEFECT": record.get("DESC_DEFECT"),
            "CONEQUENCE_DEFECT": record.get("CONEQUENCE_DEFECT"),
            "CORRECTIVE_ACTION": record.get("CORRECTIVE_ACTION"),
            "NOTES": record.get("NOTES"),
            "DO_NOT_DRIVE": record.get("DO_NOT_DRIVE"),
            "PARK_OUTSIDE": record.get("PARK_OUTSIDE"),
            "makes": sorted({m for m in entry["makes"] if m}),
            "models": sorted({m for m in entry["models"] if m}),
            "years": sorted({y for y in entry["years"] if y}),
        },
    )
