"""S&P 500 constituents from the maintained datahub.io CSV.

FMP's constituents endpoint is paywalled on the free tier, so the index list
comes from a separate, free source. It lives behind `UniverseProvider` so it
can be swapped (Wikipedia, a paid FMP tier, a local CSV) without touching
`config/universe.py` or anything downstream.
"""

from __future__ import annotations

import csv
import io
import os
import urllib.error
import urllib.request
from typing import List, Optional

from .cache import HttpCache
from .provider import Constituent, UniverseProvider

DATAHUB_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/"
    "s-and-p-500-companies/main/data/constituents.csv"
)


class DataHubUniverseProvider(UniverseProvider):
    def __init__(self, cache: Optional[HttpCache] = None) -> None:
        if cache is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            # Membership changes rarely -- cache for a week.
            cache = HttpCache(
                os.path.join(project_root, "cache", "universe.sqlite"),
                ttl_seconds=7 * 24 * 3600,
            )
        self.cache = cache

    def get_sp500_constituents(self) -> List[Constituent]:
        body = self.cache.get(DATAHUB_CSV_URL)
        if body is None:
            try:
                req = urllib.request.Request(
                    DATAHUB_CSV_URL, headers={"User-Agent": "stock-valuator"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8")
                self.cache.set(DATAHUB_CSV_URL, body)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                return []

        constituents: List[Constituent] = []
        reader = csv.DictReader(io.StringIO(body))
        for row in reader:
            symbol = (row.get("Symbol") or "").strip()
            if not symbol:
                continue
            # Normalize class-share tickers to FMP's dot convention (BRK.B etc.)
            symbol = symbol.replace("-", ".")
            constituents.append(
                Constituent(
                    symbol=symbol,
                    name=(row.get("Security") or "").strip() or None,
                    sector=(row.get("GICS Sector") or "").strip() or None,
                    sub_industry=(row.get("GICS Sub-Industry") or "").strip() or None,
                )
            )
        return constituents
