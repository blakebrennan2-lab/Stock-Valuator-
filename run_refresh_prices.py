"""Lightweight hourly refresh: update only the current picks' price, upside,
and chart history in docs/results.json. No full scan, no Telegram.

Cheap (a handful of tickers) and low rate-limit risk, so it can run often and
keep the app feeling live between the daily full re-analysis.
"""

import json
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

from src.data.yf_provider import YFinanceProvider

PATH = "docs/results.json"


def main() -> None:
    try:
        data = json.load(open(PATH))
    except FileNotFoundError:
        print("No results.json yet — run the full scan first.")
        return
    except ValueError:
        # Corrupt/conflicted JSON: don't crash; the daily full scan rewrites it.
        print("results.json is not valid JSON — skipping refresh (daily scan will rebuild).")
        return

    picks = data.get("picks", [])
    if not picks:
        print("No picks to refresh.")
        return

    # No cache: we want genuinely fresh prices each run (only a few tickers).
    provider = YFinanceProvider(use_cache=False)
    for p in picks:
        price = provider.get_quote(p["ticker"])
        if price:
            p["price"] = round(price, 2)
            iv = p.get("intrinsic")
            if iv:
                p["upside"] = (iv - price) / iv
        hist = provider.get_price_history(p["ticker"])
        if hist:
            p["history"] = hist
        intra = provider.get_intraday(p["ticker"])
        if intra:
            p["intraday"] = intra
        # Refresh headlines too, so the app's fallback news (used when the
        # client's live fetch fails) is at most an hour old, not a day.
        news = provider.get_news(p["ticker"])
        if news:
            p["news"] = news
        print(f"  {p['ticker']}: {p['price']} (upside {round((p.get('upside') or 0)*100)}%)")

    for e in data.get("etfs", []):
        price = provider.get_quote(e["ticker"])
        if price:
            e["price"] = round(price, 2)
        hist = provider.get_price_history(e["ticker"])
        if hist:
            e["history"] = hist
        intra = provider.get_intraday(e["ticker"])
        if intra:
            e["intraday"] = intra

    data["price_as_of"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    json.dump(data, open(PATH, "w"), indent=2)
    print(f"Refreshed {len(picks)} pick(s) + {len(data.get('etfs', []))} ETF(s) "
          f"at {data['price_as_of']}")


if __name__ == "__main__":
    main()
