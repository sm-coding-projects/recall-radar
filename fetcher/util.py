from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Iterable

_WS = re.compile(r"\s+")

# The oldest recall in any of our sources is CPSC's, from June 1973. A floor of
# 1900 is therefore generous while still catching mangled values.
EARLIEST_PLAUSIBLE_RECALL = date(1900, 1, 1)

# A recall cannot be initiated in the future. The small margin absorbs the
# timezone gap between an agency's clock and ours.
FUTURE_TOLERANCE = timedelta(days=2)


def clean(value: object) -> str | None:
    """Collapse whitespace; return None for anything empty."""
    if value is None:
        return None
    text = _WS.sub(" ", str(value)).strip()
    return text or None


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(value: object) -> str | None:
    """Drop tags and decode entities. FSIS ships HTML in several text fields."""
    if value is None:
        return None
    parser = _Stripper()
    parser.feed(str(value))
    parser.close()
    return clean("".join(parser.parts))


def parse_compact_date(value: object) -> date | None:
    """`YYYYMMDD` -> date. Used by openFDA and the NHTSA flat file."""
    text = clean(value)
    if not text or not text.isdigit() or len(text) != 8:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        # Real upstream values include impossible dates like 20200000.
        return None


def plausible_date(value: date | None, *, today: date | None = None) -> date | None:
    """Return the date, or None if it cannot be a real recall date.

    Upstream data carries occasional transposed digits that parse cleanly into
    absurd dates. The known case is openFDA's F-0880-2013, whose
    recall_initiation_date is "02121207" -- a transposition of "20121207" --
    which parses to 7 December 0212 and then sorts ahead of every genuine
    record.

    Callers treat a rejected value as missing and fall back to another date
    field, rather than storing something that is visibly wrong to a customer.
    """
    if value is None:
        return None
    if value < EARLIEST_PLAUSIBLE_RECALL:
        return None
    if value > (today or date.today()) + FUTURE_TOLERANCE:
        return None
    return value


def parse_iso_date(value: object) -> date | None:
    """`YYYY-MM-DD`, optionally with a time part. Used by CPSC and FSIS."""
    text = clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_iso_datetime(value: object) -> datetime | None:
    """Parse to an aware UTC datetime; naive input is assumed UTC."""
    text = clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def as_utc_datetime(value: date | None) -> datetime | None:
    """Widen a date to midnight UTC, for sources with no time component."""
    if value is None:
        return None
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def join_distinct(values: Iterable[object], sep: str = "; ", limit: int = 25) -> str | None:
    """Join while preserving order and dropping duplicates.

    NHTSA's flat file repeats a campaign once per make/model/year, so the
    aggregated `product`/`brand` fields would otherwise be enormous and
    mostly repetition. `limit` caps the runaway cases.
    """
    seen: dict[str, None] = {}
    for value in values:
        text = clean(value)
        if text:
            seen.setdefault(text, None)
    if not seen:
        return None
    items = list(seen)
    if len(items) > limit:
        remaining = len(items) - limit
        return sep.join(items[:limit]) + f" (+{remaining} more)"
    return sep.join(items)


def stable_hash(*parts: object, length: int = 8) -> str:
    """Deterministic short hash, so synthetic ids stay stable across runs."""
    joined = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:length]
