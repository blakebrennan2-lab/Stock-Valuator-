"""Run the DDM on one ticker and print every intermediate value.

    python3 run_ddm.py            # KO
    python3 run_ddm.py AMZN       # non-payer -> shows NOT APPLICABLE path
"""

import sys

from src.data.fmp_provider import FMPProvider
from src.models.ddm import DDMModel


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "KO"
    data = FMPProvider().get_company_data(ticker)
    res = DDMModel().value(data)

    print("=" * 70)
    print(f"DDM — {data.company_name} ({data.ticker})")
    print("=" * 70)

    if not res.ok:
        print("\n  RESULT: NOT APPLICABLE")
        for f in res.flags:
            print(f"    -> {f}")
        hist = res.audit.get("dividend_history", [])
        shown = [(y, d) for y, d in hist if d]
        print(f"\n  Dividend history on file: "
              f"{shown if shown else 'none (no dividends paid)'}")
        return

    a = res.audit
    print("\n[1] DIVIDEND HISTORY  (oldest -> newest)")
    for year, dps in a["dividend_history"]:
        print(f"    FY {year}: ${dps:.4f}" if dps is not None else f"    FY {year}: N/A")
    print(f"    D0 (latest annual dividend): ${a['d0']:.4f}")

    g = a["growth"]
    print("\n[2] DIVIDEND GROWTH")
    print(f"    Method:        {g['method']}")
    print(f"    Raw CAGR:      {g['raw']:.2%}")
    print(f"    Applied:       {g['applied']:.2%}   (capped: {g['capped']}, "
          f"hist. negative: {g['historical_negative']})")

    c = a["cost_of_equity"]
    print("\n[3] DISCOUNT RATE (cost of equity, CAPM)")
    print(f"    Beta:                 {c['beta']}")
    print(f"    Risk-free rate:       {c['risk_free_rate']:.2%}")
    print(f"    Equity risk premium:  {c['equity_risk_premium']:.2%}")
    print(f"    Cost of equity:       {c['cost_of_equity']:.2%}"
          f"{'  [FALLBACK]' if c['used_fallback'] else '  (= rf + beta x ERP)'}")
    print(f"    Discount rate used:   {a['discount_rate_used']:.2%}")

    ts = a["two_stage"]
    print(f"\n[4] STAGE 1 — explicit dividends  (g_high={ts['g_high']:.2%}, "
          f"r={ts['discount_rate']:.2%})")
    print(f"    {'Yr':>3}  {'Dividend':>12}  {'Disc factor':>12}  {'PV':>12}")
    for t, div, factor, pv in ts["stage1"]:
        print(f"    {t:>3}  ${div:>10.4f}  {factor:>12.4f}  ${pv:>10.4f}")
    print(f"    Sum of PV (stage 1): ${ts['sum_pv_stage1']:.4f}")

    print(f"\n[5] STAGE 2 — terminal value  (terminal g={ts['terminal_growth']:.2%})")
    print(f"    Terminal dividend (D_N+1): ${ts['terminal_dividend']:.4f}")
    print(f"    Terminal value:            ${ts['terminal_value']:.4f}   "
          f"(= D / (r - g))")
    print(f"    Discount factor:           {ts['tv_discount_factor']:.4f}")
    print(f"    PV of terminal:            ${ts['pv_terminal']:.4f}")

    print("\n[6] VALUE PER SHARE")
    print(f"    Two-stage (base, feeds blend): ${ts['value']:.2f}")
    print(f"    Gordon single-stage (ref):     ${a['gordon']['value']:.2f}")

    s = a["scenarios"]
    print("\n[7] SCENARIO RANGE (two-stage)")
    print(f"    Bear: ${s['bear']:.2f}   Base: ${s['base']:.2f}   Bull: ${s['bull']:.2f}")
    if data.price:
        print(f"    Current price:        ${data.price:.2f}")
        mos = (s["base"] - data.price) / s["base"]
        print(f"    Margin of safety (base vs price): {mos:.1%}")

    if res.flags:
        print("\n[FLAGS]")
        for f in res.flags:
            print(f"    -> {f}")


if __name__ == "__main__":
    main()
