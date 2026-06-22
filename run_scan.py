"""Run the full valuation scan and print the top undervalued names.

    python3 run_scan.py             # full investable universe
    python3 run_scan.py --limit 30  # first 30 names (quick check)
"""

import argparse
import warnings

warnings.filterwarnings("ignore")

from config.universe import build_universe
from src.data.yf_provider import YFinanceProvider
from src.pipeline.scan import Scanner, print_top, write_csv
from src.web.export import export_results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="value only the first N names (quick check)")
    args = ap.parse_args()

    universe = build_universe()
    symbols = universe.symbols
    if args.limit:
        symbols = symbols[: args.limit]

    print(f"Scanning {len(symbols)} names via yfinance...\n")
    scanner = Scanner(YFinanceProvider(), universe)
    result = scanner.scan(symbols)

    path = write_csv(result)
    json_path = export_results(result, provider=scanner.provider)  # docs/results.json
    print_top(result)
    print(f"\nFull per-name detail: {path}")
    print(f"Web data: {json_path}")


if __name__ == "__main__":
    main()
