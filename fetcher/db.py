from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import psycopg
from psycopg.types.json import Jsonb

from .models import NormalizedRecall

# Rows per statement. Each row carries a jsonb `raw` blob of a few KB, so this
# keeps a single round trip to roughly a megabyte.
CHUNK_SIZE = 200

UPSERT_SQL = """
INSERT INTO recalls (
    agency, source_id, product, brand, category, hazard,
    classification, recall_date, published_at, url, raw
)
VALUES {values}
ON CONFLICT (agency, source_id) DO UPDATE SET
    product        = EXCLUDED.product,
    brand          = EXCLUDED.brand,
    category       = EXCLUDED.category,
    hazard         = EXCLUDED.hazard,
    classification = EXCLUDED.classification,
    recall_date    = EXCLUDED.recall_date,
    published_at   = EXCLUDED.published_at,
    url            = EXCLUDED.url,
    raw            = EXCLUDED.raw,
    ingested_at    = now()
RETURNING (xmax = 0) AS inserted
"""


@dataclass
class UpsertCounts:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0

    def __iadd__(self, other: "UpsertCounts") -> "UpsertCounts":
        self.fetched += other.fetched
        self.inserted += other.inserted
        self.updated += other.updated
        return self


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit(
            "DATABASE_URL is not set. Copy .env.example to .env and fill it in, "
            "or export it in the environment."
        )
    return url


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or database_url())


def dedupe(records: Sequence[NormalizedRecall]) -> list[NormalizedRecall]:
    """Collapse duplicate (agency, source_id) pairs, keeping the last seen.

    Postgres raises 'ON CONFLICT DO UPDATE command cannot affect row a second
    time' if one statement touches the same conflict target twice, so this has
    to happen before the insert -- not as a nicety. Sources really do emit
    duplicates: overlapping openFDA date windows re-return boundary records,
    and CPSC can list a recall under several product entries.
    """
    by_key: dict[tuple[str, str], NormalizedRecall] = {}
    for record in records:
        by_key[(record.agency, record.source_id)] = record
    return list(by_key.values())


def upsert(conn: psycopg.Connection, records: Iterable[NormalizedRecall]) -> UpsertCounts:
    """Idempotent bulk upsert. Returns insert/update counts.

    Each chunk goes out as ONE multi-row INSERT rather than
    executemany(returning=True). psycopg pipelines executemany, and Neon's
    pooled endpoint drops the connection partway through a large pipeline
    ("SSL error: bad length"). A single statement per chunk avoids pipelining
    altogether and is faster besides.

    `xmax = 0` distinguishes a fresh insert from an update of an existing row.
    """
    batch = dedupe(list(records))
    counts = UpsertCounts(fetched=len(batch))

    with conn.cursor() as cur:
        for start in range(0, len(batch), CHUNK_SIZE):
            chunk = batch[start : start + CHUNK_SIZE]
            values = ", ".join(["(" + ", ".join(["%s"] * 11) + ")"] * len(chunk))
            params: list[Any] = []
            for r in chunk:
                params.extend((
                    r.agency, r.source_id, r.product, r.brand, r.category, r.hazard,
                    r.classification, r.recall_date, r.published_at, r.url,
                    Jsonb(r.raw) if r.raw else None,
                ))

            cur.execute(UPSERT_SQL.format(values=values), params)
            for (inserted,) in cur.fetchall():
                if inserted:
                    counts.inserted += 1
                else:
                    counts.updated += 1

            conn.commit()

    return counts


def apply_schema(conn: psycopg.Connection, sql: str) -> None:
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader so local runs don't need an extra dependency.

    Existing environment variables always win, which keeps CI (where
    DATABASE_URL is a repo secret) from being shadowed by a stray file.
    """
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


__all__ = [
    "UpsertCounts", "apply_schema", "connect", "database_url",
    "dedupe", "load_dotenv", "upsert", "json",
]
