"""Export a ScanResult to docs/results.json for the web app to display.

Contains the qualifying picks and, per pick, the full report (summary block +
DCF/DDM/Comps work). No secrets — safe to publish.
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Optional

from src.notify.detail import _peer_medians, build_stock_block
from src.web.report import render_comps, render_dcf, render_ddm

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
        # Only a handful of picks -> fetching news for each is cheap.
        news = (provider.get_news(b.ticker)
                if provider and hasattr(provider, "get_news") else None)

        # build_stock_block uses \n (Telegram); browsers need <br>.
        summary_html = (build_stock_block(b, data, comps, news).replace("\n", "<br>")
                        if data else "")
        picks.append({
            "ticker": b.ticker,
            "name": b.company_name or "",
            "price": b.price,
            "intrinsic": b.intrinsic_value,
            "upside": b.margin_of_safety,
            "confidence": b.confidence,
            "summary_html": summary_html,
            "dcf_html": render_dcf(results.get("DCF")),
            "ddm_html": render_ddm(results.get("DDM")),
            "comps_html": render_comps(comps),
        })

    payload = {
        "as_of": as_of,
        "count": len(picks),
        "picks": picks,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    return path
