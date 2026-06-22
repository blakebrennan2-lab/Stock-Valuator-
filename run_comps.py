"""Run Comps on one ticker and print every intermediate value.

    python3 run_comps.py          # AAPL
    python3 run_comps.py MSFT
"""

import sys

from config.universe import build_universe
from src.data.fmp_provider import FMPProvider
from src.models.comps import CompsModel


def f2(x, suffix=""):
    return f"{x:.2f}{suffix}" if x is not None else "N/A"


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    provider = FMPProvider()
    universe = build_universe()
    data = provider.get_company_data(ticker)
    peers = universe.peers_for(ticker)

    res = CompsModel(provider, universe).value(data, peer_symbols=peers)

    print("=" * 78)
    print(f"COMPS — {data.company_name} ({data.ticker})")
    print("=" * 78)

    c = data.latest
    print("\n[TARGET METRICS]")
    print(f"    EPS (diluted):       {f2(c.eps_diluted)}")
    print(f"    EBITDA:              ${c.ebitda/1e6:,.0f}M" if c.ebitda else "    EBITDA: N/A")
    print(f"    Book value/share:    {f2(c.book_value_per_share)}")
    print(f"    Shares / debt / cash for EV bridge: "
          f"{data.shares_outstanding/1e6:,.0f}M / "
          f"${(data.total_debt or 0)/1e6:,.0f}M / ${(data.cash_and_equivalents or 0)/1e6:,.0f}M")

    a = res.audit
    print(f"\n[PEERS & MULTIPLES]  ({len(a['peers'])} peers from universe)")
    print(f"    {'Symbol':<8}{'P/E':>10}{'EV/EBITDA':>12}{'P/B':>10}")
    for p in a["peers"]:
        print(f"    {p['symbol']:<8}{f2(p['pe'], 'x'):>10}"
              f"{f2(p['ev_ebitda'], 'x'):>12}{f2(p['pb'], 'x'):>10}")

    if not res.ok:
        print("\n  COMPS did not produce a value:")
        for flag in res.flags:
            print(f"    -> {flag}")
        return

    m = a["multiples"]
    print("\n[TRIMMED MEDIANS & IMPLIED VALUES]")

    def show(key, label, target_label):
        info = m[key]
        if "median" not in info:
            print(f"    {label}: DROPPED  (valid peers: "
                  f"{len(info['peer_values'])}, target: {f2(info['target_metric'])})")
            return
        print(f"    {label}:")
        print(f"      valid peer values: {[round(v, 2) for v in info['peer_values']]}")
        print(f"      after trim:        {[round(v, 2) for v in info['used_values']]}")
        print(f"      median multiple:   {info['median']:.2f}x")
        print(f"      x target {target_label}: {f2(info['target_metric'])}")
        if key == "ev_ebitda":
            print(f"      = implied EV:      ${info['implied_ev']/1e6:,.0f}M")
            print(f"        - debt + cash -> equity ${info['equity_value']/1e6:,.0f}M "
                  f"/ {info['shares']/1e6:,.0f}M sh")
        print(f"      => IMPLIED PRICE:  ${info['implied']:.2f}")

    show("pe", "P/E", "EPS")
    show("ev_ebitda", "EV/EBITDA", "EBITDA")
    show("pb", "P/B", "BVPS")

    print("\n[RECONCILIATION]")
    for method, val in a["implied_by_method"].items():
        print(f"    {method:<10} ${val:.2f}")
    print(f"    {'-'*22}")
    print(f"    Median (base):  ${a['reconciled_median']:.2f}   <- feeds blend")
    print(f"    Mean (ref):     ${a['reconciled_mean']:.2f}")
    print(f"    Range:          ${a['range']['low']:.2f} - ${a['range']['high']:.2f}")

    if data.price:
        print(f"\n    Current price:  ${data.price:.2f}")
        mos = (a["reconciled_median"] - data.price) / a["reconciled_median"]
        print(f"    Margin of safety (base vs price): {mos:.1%}")

    if res.flags:
        print("\n[FLAGS]")
        for flag in res.flags:
            print(f"    -> {flag}")


if __name__ == "__main__":
    main()
