from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def init_pool() -> ConnectionPool:
    """Create the pool lazily.

    Render's free tier sleeps the instance, and Neon's free compute suspends
    when idle, so `open=False` plus a small pool avoids a burst of doomed
    connections at cold start. `check` recycles connections the database
    dropped while suspended, which otherwise surface as a stale-connection
    error on the first request after a sleep.
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=_database_url(),
            min_size=0,
            max_size=4,
            timeout=15.0,
            max_idle=120.0,
            check=ConnectionPool.check_connection,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def cursor() -> Iterator[Any]:
    pool = init_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        yield cur


def fetch_all(sql: str, params: object = None) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(sql: str, params: object = None) -> dict[str, Any] | None:
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_value(sql: str, params: object = None) -> Any:
    row = fetch_one(sql, params)
    if not row:
        return None
    return next(iter(row.values()))
