"""Send the latest scan's top names to Telegram (no re-scan needed).

Reads the most recent output/scan_*.csv, re-applies the ranker, prints the
message, and sends it if Telegram creds are in .env.

    python3 run_notify.py            # send (or print + skip if no creds)
    python3 run_notify.py --dry-run  # print message only, never send
"""

import argparse
import csv
import glob
import os
import warnings

warnings.filterwarnings("ignore")

from config.universe import build_universe
from src.data.yf_provider import YFinanceProvider
from src.notify.detail import build_digest_messages
from src.notify.digest_log import append_digest_log
from src.notify.telegram import TelegramNotifier
from src.screen.profile import dedupe_dual_class
from src.valuation.blender import BlendResult


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _mos(x):
    try:
        return float(x.replace("%", "")) / 100.0
    except (TypeError, ValueError, AttributeError):
        return None


def load_blends(path):
    blends = []
    for r in csv.DictReader(open(path)):
        iv = _f(r["intrinsic"])
        qf = [s for s in (r.get("quality_flags") or "").split("; ") if s]
        mv = {k: _f(r[k]) for k in ("DCF", "DDM", "Comps") if _f(r.get(k)) is not None}
        plines = [s for s in (r.get("profile") or "").split(" | ") if s]
        blends.append(BlendResult(
            ticker=r["symbol"], company_name=r["name"] or None,
            price=_f(r["price"]), intrinsic_value=iv,
            margin_of_safety=_mos(r["margin_of_safety"]),
            confidence=r["confidence"] or "none",
            n_models=int(r["n_models"]) if r["n_models"] else 0,
            quality_flags=qf, model_values=mv,
            qualifies=(r.get("qualifies") == "True"), profile_lines=plines,
            ok=iv is not None,
        ))
    return blends


def select_qualifiers(blends, top_n=5):
    """Quality-compounder selection: only names that cleared every gate,
    ranked by upside (margin of safety), with dual-class duplicates collapsed."""
    q = [b for b in blends if b.qualifies and b.margin_of_safety is not None]
    q.sort(key=lambda b: b.margin_of_safety, reverse=True)
    return dedupe_dual_class(q)[:top_n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print only, don't send")
    args = ap.parse_args()

    files = sorted(glob.glob("output/scan_*.csv"))
    if not files:
        print("No scan CSV found in output/. Run run_scan.py first.")
        return
    latest = files[-1]
    as_of = os.path.basename(latest).replace("scan_", "").replace(".csv", "")
    top = select_qualifiers(load_blends(latest))

    # Build the rich per-stock detail (cached data -> fast for just the top 5).
    provider = YFinanceProvider()
    universe = build_universe()
    messages = build_digest_messages(top, provider, universe, as_of=as_of)

    print(f"--- digest ({len(messages)} message(s) from {latest}) ---")
    for m in messages:
        print(m + "\n")
    print("--- end ---\n")

    if args.dry_run:
        print("dry-run: not sending.")
        return
    notifier = TelegramNotifier()
    print("sent OK" if notifier.send_many(messages) else "not sent.")
    log_path = append_digest_log(top, as_of=as_of)
    print(f"logged {len(top)} pick(s) to {log_path}")


if __name__ == "__main__":
    main()
