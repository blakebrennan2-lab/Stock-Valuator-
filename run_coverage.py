"""Coverage check: how many S&P 500 names return complete data via yfinance.

Walks the investable universe, pulls each name through the provider, and
classifies what each model could actually run on. Writes a per-name CSV and
prints a summary.

    python3 run_coverage.py
"""

import csv
import os
import time
import warnings

warnings.filterwarnings("ignore")

from config.universe import build_universe
from src.data.yf_provider import YFinanceProvider


def assess(data):
    fcf_years = sum(1 for p in data.periods if p.free_cash_flow is not None)
    latest = data.latest
    latest_fcf_pos = bool(latest and latest.free_cash_flow and latest.free_cash_flow > 0)
    has_eps = bool(latest and latest.eps_diluted is not None)
    has_bvps = bool(latest and latest.book_value_per_share is not None)
    has_ebitda = bool(latest and latest.ebitda is not None and latest.ebitda > 0)
    has_shares = bool(data.shares_outstanding and data.shares_outstanding > 0)
    has_price = data.price is not None
    is_payer = any(p.dividend_per_share and p.dividend_per_share > 0 for p in data.periods)

    dcf_ready = fcf_years >= 2 and latest_fcf_pos and has_shares
    comps_ready = has_shares and (has_eps or has_ebitda or has_bvps)
    full = (has_price and fcf_years >= 2 and has_eps and has_bvps
            and has_ebitda and has_shares)
    return {
        "price": has_price, "beta": data.beta is not None, "fcf_years": fcf_years,
        "eps": has_eps, "bvps": has_bvps, "ebitda": has_ebitda, "shares": has_shares,
        "payer": is_payer, "dcf_ready": dcf_ready, "comps_ready": comps_ready,
        "full": full,
    }


def main() -> None:
    provider = YFinanceProvider()
    universe = build_universe()
    symbols = universe.symbols
    total = len(symbols)
    print(f"Coverage check over {total} investable names...\n")

    rows = []
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        try:
            data = provider.get_company_data(sym)
            a = assess(data)
            a["error"] = ""
        except Exception as e:  # never let one bad name kill the sweep
            a = {k: False for k in ("price", "beta", "eps", "bvps", "ebitda",
                                    "shares", "payer", "dcf_ready", "comps_ready", "full")}
            a["fcf_years"] = 0
            a["error"] = str(e)[:80]
        a["symbol"] = sym
        a["sector"] = (universe.get(sym).sector if universe.get(sym) else "")
        rows.append(a)
        if i % 25 == 0 or i == total:
            print(f"  {i}/{total}  ({time.time()-t0:.0f}s elapsed)")
        time.sleep(0.1)  # be polite to Yahoo

    os.makedirs("output", exist_ok=True)
    csv_path = "output/coverage.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "sector", "full", "dcf_ready", "comps_ready", "payer",
                    "fcf_years", "price", "beta", "eps", "bvps", "ebitda", "shares", "error"])
        for r in rows:
            w.writerow([r["symbol"], r["sector"], r["full"], r["dcf_ready"],
                        r["comps_ready"], r["payer"], r["fcf_years"], r["price"],
                        r["beta"], r["eps"], r["bvps"], r["ebitda"], r["shares"], r["error"]])

    # ---- summary ---- #
    def pct(n):
        return f"{n} ({n/total*100:.0f}%)"

    full = sum(r["full"] for r in rows)
    dcf = sum(r["dcf_ready"] for r in rows)
    comps = sum(r["comps_ready"] for r in rows)
    payers = sum(r["payer"] for r in rows)
    failed = sum(1 for r in rows if not r["price"] and r["fcf_years"] == 0)
    any_model = sum(1 for r in rows if r["dcf_ready"] or r["comps_ready"])

    print("\n" + "=" * 60)
    print("COVERAGE SUMMARY")
    print("=" * 60)
    print(f"  Universe (investable):     {total}")
    print(f"  Full data (all fields):    {pct(full)}")
    print(f"  DCF-ready:                 {pct(dcf)}")
    print(f"  Comps-ready (target side): {pct(comps)}")
    print(f"  Valuable by >=1 model:     {pct(any_model)}")
    print(f"  Dividend payers (DDM):     {pct(payers)}")
    print(f"  Fetch failures (no data):  {pct(failed)}")
    print(f"\n  Per-name detail: {csv_path}")
    print(f"  Total time: {time.time()-t0:.0f}s")

    # Show a few problem names for visibility.
    problems = [r for r in rows if not r["full"]][:15]
    if problems:
        print("\n  Sample of incomplete names:")
        for r in problems:
            miss = [k for k in ("price", "eps", "bvps", "ebitda", "shares")
                    if not r[k]]
            note = r["error"] or f"missing: {', '.join(miss) or 'fcf_years<2'}"
            print(f"    {r['symbol']:<6} {note}")


if __name__ == "__main__":
    main()
