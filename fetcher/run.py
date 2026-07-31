"""Fetch recalls from every source and upsert them.

    python -m fetcher.run                      # incremental, last 30 days
    python -m fetcher.run --backfill           # all available history
    python -m fetcher.run --agency FSIS        # one source only
    python -m fetcher.run --days 90            # custom incremental window

Runs are idempotent: records upsert on (agency, source_id), so re-running
never duplicates and always refreshes amended records.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from . import db
from .http import build_client
from .sources import ADAPTERS, DEFAULT_AGENCIES, UNAVAILABLE

log = logging.getLogger("fetcher")

DEFAULT_DAYS = 30


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fetcher.run", description=__doc__)
    parser.add_argument(
        "--backfill", action="store_true",
        help="pull all available history instead of the recent window",
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help=f"incremental window size in days (default: {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--agency", action="append", choices=sorted(ADAPTERS), metavar="AGENCY",
        help=(
            f"limit to one agency; repeatable. one of: {', '.join(sorted(ADAPTERS))}. "
            f"default runs {', '.join(DEFAULT_AGENCIES)} "
            f"(excluded by default: {', '.join(sorted(UNAVAILABLE))})"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="fetch and normalize but do not write to the database",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx logs every request at INFO, which drowns the per-agency summary.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    db.load_dotenv()
    # An explicit --agency always wins, so a blocked source can still be
    # retried on purpose without being in the nightly rotation.
    agencies = args.agency or DEFAULT_AGENCIES
    until = date.today()
    since = None if args.backfill else until - timedelta(days=args.days)

    mode = "backfill (all history)" if args.backfill else f"incremental ({since} .. {until})"
    log.info("mode: %s | agencies: %s", mode, ", ".join(agencies))

    conn = None if args.dry_run else db.connect()
    totals = db.UpsertCounts()
    failures: list[str] = []

    try:
        with build_client() as client:
            for agency in agencies:
                adapter = ADAPTERS[agency]
                try:
                    records = list(adapter.fetch(client, since=since, until=until, backfill=args.backfill))
                except Exception as exc:  # noqa: BLE001 - one bad source must not sink the rest
                    log.error("%-6s FAILED: %s", agency, exc)
                    failures.append(agency)
                    continue

                if args.dry_run:
                    counts = db.UpsertCounts(fetched=len(db.dedupe(records)))
                else:
                    counts = db.upsert(conn, records)

                log.info(
                    "%-6s fetched=%-6d inserted=%-6d updated=%-6d",
                    agency, counts.fetched, counts.inserted, counts.updated,
                )
                totals += counts
    finally:
        if conn is not None:
            conn.close()

    log.info(
        "TOTAL  fetched=%-6d inserted=%-6d updated=%-6d",
        totals.fetched, totals.inserted, totals.updated,
    )

    if failures:
        log.error("failed sources: %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
