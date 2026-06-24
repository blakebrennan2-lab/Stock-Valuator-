"""Export a ScanResult to docs/results.json for the web app.

Per pick: header, price history (for the chart), key stats, why-bullets, risks,
profile scorecard, news, and the DCF/DDM/Comps breakdown HTML. No secrets.
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Optional

from src.web.fields import stock_payload

DEFAULT_PATH = "docs/results.json"


def export_results(scan_result, path: str = DEFAULT_PATH, as_of: Optional[str] = None,
                   provider=None) -> str:
    as_of = as_of or date.today().isoformat()
    by_ticker = {r.blend.ticker: r for r in scan_result.records}

    picks = []
    for b in scan_result.top:
        rec = by_ticker.get(b.ticker)
        data = rec.data if rec else None
        results = rec.results if rec else {}
        comps = results.get("Comps")
        if data is None:
            continue
        # Only a handful of picks -> fetching history + news for each is cheap.
        history = provider.get_price_history(b.ticker) if (
            provider and hasattr(provider, "get_price_history")) else []
        intraday = provider.get_intraday(b.ticker) if (
            provider and hasattr(provider, "get_intraday")) else []
        news = provider.get_news(b.ticker) if (
            provider and hasattr(provider, "get_news")) else None
        picks.append(stock_payload(b, data, comps, results, history, news, intraday))

    payload = {"as_of": as_of, "count": len(picks), "picks": picks}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    return path
