"""Scheduled entrypoint: scan the universe, save results, send the top to Telegram.

This is what the every-2-days scheduler invokes. Safe to run manually too.

    python3 run_pipeline.py
"""

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


def main() -> None:
    universe = build_universe()
    print(f"Scanning {len(universe.symbols)} names via yfinance...\n")

    scanner = Scanner(YFinanceProvider(), universe)
    result = scanner.scan()  # cached + polite delay + retry-on-empty

    path = write_csv(result)
    json_path = export_results(result, provider=scanner.provider)  # docs/results.json
    print_top(result)
    print(f"\nFull per-name detail: {path}")
    print(f"Web data: {json_path}")

    notifier = TelegramNotifier()
    messages = build_digest_messages(
        result.top, scanner.provider, universe, as_of=date.today().isoformat()
    )
    if notifier.send_many(messages):
        print("Telegram: sent.")
    else:
        print("Telegram: not sent (missing creds or send error).")

    log_path = append_digest_log(result.top, as_of=date.today().isoformat())
    print(f"Logged {len(result.top)} pick(s) to {log_path}")


if __name__ == "__main__":
    main()
