"""Tiny SQLite-backed HTTP response cache.

Fundamentals only change quarterly, so re-fetching 500 names every run would
burn the free-tier rate limit for nothing. We cache raw response bodies keyed
by URL with a TTL. Reruns within the TTL hit the DB instead of the network,
which also makes iterating on the AAPL print-out instant.
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Optional


class HttpCache:
    def __init__(self, path: str, ttl_seconds: int = 24 * 3600) -> None:
        self.ttl = ttl_seconds
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # check_same_thread=False keeps it usable if we later parallelize the scan
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            "  url TEXT PRIMARY KEY,"
            "  body TEXT NOT NULL,"
            "  fetched_at REAL NOT NULL"
            ")"
        )
        self._conn.commit()

    def get(self, url: str) -> Optional[str]:
        """Return the cached body if present and not expired, else None."""
        row = self._conn.execute(
            "SELECT body, fetched_at FROM responses WHERE url = ?", (url,)
        ).fetchone()
        if not row:
            return None
        body, fetched_at = row
        if time.time() - fetched_at > self.ttl:
            return None
        return body

    def set(self, url: str, body: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (url, body, fetched_at) VALUES (?, ?, ?)",
            (url, body, time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
