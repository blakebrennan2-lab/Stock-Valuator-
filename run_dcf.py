"""Run the DCF on one ticker and print every intermediate value for auditing.

    python3 run_dcf.py           # AAPL
    python3 run_dcf.py MSFT
"""

import sys

from src.data.fmp_provider import FMPProvider
from src.models.dcf import DCFModel


def money(x):
    return f"${x:,.1f}M" if x is not None else "N/A"


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    data = FMPProvider().get_company_data(ticker)
    res = DCFModel().value(data)

    print("=" * 74)
    print(f"DCF — {data.company_name} ({data.ticker})")
    print("=" * 74)

    if not res.ok:
        print("  DCF did not produce a value:")
        for f in res.flags:
            print(f"    ⚠ {f}")
        return

    a = res.audit
    # Note: FMP figures are already in absolute dollars; divide by 1e6 for "M".
    print("\n[1] HISTORICAL FREE CASH FLOW  (oldest -> newest)")
    for year, fcf in a["fcf_history"]:
        print(f"    FY {year}: {money(fcf/1e6)}")

    g = a["growth"]
    print("\n[2] GROWTH RATE")
    print(f"    Method:        {g['method']}")
    print(f"    Raw CAGR:      {g['raw']:.2%}")
    print(f"    Applied:       {g['applied']:.2%}   (capped: {g['capped']})")
    print(f"    Base FCF (FY most recent): {money(a['fcf0']/1e6)}")

    w = a["wacc"]
    print("\n[3] WACC BREAKDOWN")
    print(f"    Beta:                 {w['beta']}")
    print(f"    Risk-free rate:       {w['risk_free_rate']:.2%}")
    print(f"    Equity risk premium:  {w['equity_risk_premium']:.2%}")
    print(f"    Cost of equity:       {w['cost_of_equity']:.2%}   "
          f"(= rf + beta x ERP)")
    print(f"    Cost of debt (pre):   {w['cost_of_debt_pretax']:.2%}")
    print(f"    Tax rate:             {w['tax_rate']:.2%}")
    print(f"    Cost of debt (post):  {w['cost_of_debt_aftertax']:.2%}")
    print(f"    Equity value (E):     {money(w['equity_value']/1e6)}")
    print(f"    Debt value (D):       {money(w['debt_value']/1e6)}")
    print(f"    Weight equity:        {w['weight_equity']:.2%}")
    print(f"    Weight debt:          {w['weight_debt']:.2%}")
    print(f"    --> WACC:             {w['wacc']:.2%}"
          f"{'  [FALLBACK]' if w['used_fallback'] else ''}")
    for note in w["notes"]:
        print(f"      note: {note}")

    b = a["base"]
    print("\n[4] PROJECTED FCF, DISCOUNTED  (base case)")
    print(f"    growth={b['growth']:.2%}  wacc={b['wacc']:.2%}  "
          f"terminal g={b['terminal_growth']:.2%}")
    print(f"    {'Yr':>3}  {'Growth':>8}  {'Projected FCF':>16}  {'Disc factor':>12}  {'PV':>16}")
    for t, growth_t, fcf, factor, pv in b["projection"]:
        print(f"    {t:>3}  {growth_t:>7.2%}  {money(fcf/1e6):>16}  "
              f"{factor:>12.4f}  {money(pv/1e6):>16}")
    print(f"    Sum of PV (explicit years): {money(b['sum_pv_explicit']/1e6)}")

    print("\n[5] TERMINAL VALUE")
    print(f"    Last projected FCF:   {money(b['projection'][-1][2]/1e6)}")
    print(f"    Terminal value:       {money(b['terminal_value']/1e6)}   "
          f"(= FCF_N x (1+g) / (WACC - g))")
    print(f"    Discount factor:      {b['tv_discount_factor']:.4f}")
    print(f"    PV of terminal:       {money(b['pv_terminal']/1e6)}")

    print("\n[6] ENTERPRISE VALUE -> EQUITY BRIDGE")
    print(f"    Enterprise value:     {money(b['enterprise_value']/1e6)}")
    print(f"      - Total debt:       {money(b['total_debt']/1e6)}")
    print(f"      + Cash & equiv.:    {money(b['cash']/1e6)}")
    print(f"    = Equity value:       {money(b['equity_value']/1e6)}")
    print(f"    / Shares outstanding: {b['shares']/1e6:,.1f}M")
    print(f"    = VALUE PER SHARE:    ${b['per_share']:,.2f}")

    s = a["scenarios"]
    print("\n[7] SCENARIO RANGE")
    print(f"    Bear: ${s['bear']:,.2f}   Base: ${s['base']:,.2f}   "
          f"Bull: ${s['bull']:,.2f}")
    print(f"    Current price:        ${data.price:,.2f}")
    if data.price:
        mos = (s["base"] - data.price) / s["base"]
        print(f"    Margin of safety (base vs price): {mos:.1%}")

    if res.flags:
        print("\n[FLAGS]")
        for f in res.flags:
            print(f"    ⚠ {f}")


if __name__ == "__main__":
    main()
