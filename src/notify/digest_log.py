"""Append each digest's picks to a running log for later scoring.

One row per pick per run (date, ticker, price, intrinsic, margin of safety,
confidence). Over time this lets you score the model's calls against actual
price outcomes before committing capital. Empty digests are logged too, so a
"nothing qualified" run is still on the record.
"""

from __future__ import annotations

import csv
import os
from datetime import date
from typing import List, Optional

from src.valuation.blender import BlendResult

DEFAULT_PATH = "state/picks_log.csv"  # committed so the cloud run accumulates it
HEADER = ["run_date", "rank", "symbol", "name", "price", "intrinsic",
          "margin_of_safety", "confidence", "n_models"]


def append_digest_log(
    top: List[BlendResult],
    as_of: Optional[str] = None,
    path: str = DEFAULT_PATH,
) -> str:
    as_of = as_of or date.today().isoformat()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    is_new = not os.path.exists(path)

    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if is_new:
            w.writerow(HEADER)
        if not top:
            w.writerow([as_of, "", "(no qualifiers)", "", "", "", "", "", ""])
            return path
        for i, b in enumerate(top, 1):
            w.writerow([
                as_of, i, b.ticker, b.company_name or "",
                f"{b.price:.2f}" if b.price is not None else "",
                f"{b.intrinsic_value:.2f}" if b.intrinsic_value is not None else "",
                f"{b.margin_of_safety*100:.1f}%" if b.margin_of_safety is not None else "",
                b.confidence, b.n_models,
            ])
    return path
