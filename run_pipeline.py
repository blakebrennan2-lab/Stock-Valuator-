"""Scheduled entrypoint (daily): scan, save results, and send Telegram ONLY when
the pick list changes vs. the last send. Safe to run manually too.

    python3 run_pipeline.py
"""

import json
import os
import warnings

warnings.filterwarnings("ignore")

from datetime import date

from config.universe import build_universe
from src.data.yf_provider import YFinanceProvider
from src.notify.detail import build_digest_messages
from src.notify.digest_log import append_digest_log
from src.notify.telegram import TelegramNotifier
from src.pipeline.scan import Scanner, print_top, write_csv
from src.web.export import export_results

STATE_PATH = "state/last_sent.json"


def _load_last():
    """Previously-sent tickers, or None if we've never recorded any."""
    try:
        return set(json.load(open(STATE_PATH)).get("tickers", []))
    except (FileNotFoundError, ValueError):
        return None


def _save_last(tickers):
    os.makedirs("state", exist_ok=True)
    json.dump({"date": date.today().isoformat(), "tickers": sorted(tickers)},
              open(STATE_PATH, "w"), indent=2)


def main() -> None:
    universe = build_universe()
    print(f"Scanning {len(universe.symbols)} names via yfinance...\n")

    scanner = Scanner(YFinanceProvider(), universe)
    result = scanner.scan()

    write_csv(result)
    export_results(result, provider=scanner.provider)  # always refresh the app data
    print_top(result)

    # Send a digest EVERY run with the day's top 3 (or "nothing today").
    notifier = TelegramNotifier()
    messages = build_digest_messages(result.top, scanner.provider, universe,
                                     as_of=date.today().isoformat())
    sent = notifier.send_many(messages)
    print("Telegram: sent." if sent else "Telegram: not sent (creds/send error).")

    _save_last({b.ticker for b in result.top})
    append_digest_log(result.top, as_of=date.today().isoformat())
    print(f"Recorded {len(result.top)} pick(s) to {STATE_PATH} and the picks log.")


if __name__ == "__main__":
    main()
