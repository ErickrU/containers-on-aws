"""PostgreSQL access through a psycopg 3 connection pool.

Start-up follows labs/CONTRACT.md §7: connect with backoff for up to 30 seconds, then fail with a
clear error (the entrypoint exits 1 and the platform restarts the task). ``ping`` backs the
``/readyz`` endpoint.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)


class DatabaseUnavailable(RuntimeError):
    """The database did not answer within the start-up budget."""


class Database:
    def __init__(self, url: str, *, min_size: int = 1, max_size: int = 4, name: str = "worker") -> None:
        self._pool = ConnectionPool(
            url,
            min_size=min_size,
            max_size=max_size,
            name=name,
            open=False,
            # Verify a connection before handing it out so a restarted database does not surface
            # as a failed UPDATE; the check costs one round trip.
            check=ConnectionPool.check_connection,
            kwargs={"autocommit": False, "connect_timeout": 5},
        )

    def open(self, timeout_seconds: float = 30.0) -> None:
        """Open the pool and wait until the database answers, retrying with exponential backoff."""
        self._pool.open(wait=False)
        deadline = time.monotonic() + timeout_seconds
        delay = 0.5
        attempt = 0
        while True:
            attempt += 1
            remaining = deadline - time.monotonic()
            try:
                self.ping(timeout=min(5.0, max(0.5, remaining)))
                log.info("database connected", extra={"attempts": attempt})
                return
            except Exception as exc:  # noqa: BLE001 - any failure here is "not ready yet"
                if time.monotonic() >= deadline:
                    raise DatabaseUnavailable(
                        f"database not reachable after {timeout_seconds:.0f}s ({attempt} attempts): {exc}"
                    ) from exc
                log.warning(
                    "database not ready, retrying",
                    extra={"attempt": attempt, "retry_in_seconds": delay, "error": str(exc).strip()},
                )
                time.sleep(min(delay, max(0.0, deadline - time.monotonic())))
                delay = min(delay * 2, 5.0)

    @contextmanager
    def connection(self, timeout: float | None = None) -> Iterator[psycopg.Connection]:
        """Borrow a connection; commits on success and rolls back when the block raises."""
        with self._pool.connection(timeout=timeout) as conn:
            yield conn

    def ping(self, timeout: float = 2.0) -> None:
        with self.connection(timeout=timeout) as conn:
            conn.execute("SELECT 1")

    def check(self) -> str:
        """Readiness check result: ``"ok"`` or ``"error: <reason>"``."""
        try:
            self.ping()
            return "ok"
        except Exception as exc:  # noqa: BLE001 - reported, not raised, on /readyz
            return f"error: {type(exc).__name__}: {str(exc).strip()[:200]}"

    def close(self, timeout: float = 5.0) -> None:
        self._pool.close(timeout=timeout)
