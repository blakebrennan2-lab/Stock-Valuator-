"""Fetch one ticker through the data layer and print every field with labels.

Usage:
    python3 run_aapl.py            # defaults to AAPL
    python3 run_aapl.py MSFT
"""

import sys

from src.data.fmp_provider import FMPProvider
from src.data.provider import CompanyData


def fmt(value, kind: str = "num") -> str:
    """Human-readable formatting with explicit 'N/A (missing)' for None."""
    if value is None:
        return "N/A (missing)"
    if kind == "money":  # large dollar figures
        return f"${value:,.0f}"
    if kind == "count":  # share counts (not dollars)
        return f"{value:,.0f}"
    if kind == "num":
        return f"{value:,.2f}"
    if kind == "mult":
        return f"{value:.2f}x"
    if kind == "pct":
        return f"{value * 100:.2f}%"
    return str(value)


def hr(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def print_company(d: CompanyData) -> None:
    hr(f"COMPANY OVERVIEW — {d.ticker}")
    print(f"  Name:               {fmt(d.company_name, 'raw')}")
    print(f"  Sector:             {fmt(d.sector, 'raw')}")
    print(f"  Industry:           {fmt(d.industry, 'raw')}")
    print(f"  Current price:      {fmt(d.price, 'num')}")
    print(f"  Beta:               {fmt(d.beta, 'num')}")
    print(f"  Market cap:         {fmt(d.market_cap, 'money')}")
    print(f"  Last dividend:      {fmt(d.last_dividend, 'num')}")

    hr("BALANCE-SHEET SNAPSHOT (latest)")
    print(f"  Shares outstanding: {fmt(d.shares_outstanding, 'count')}")
    print(f"  Total debt:         {fmt(d.total_debt, 'money')}")
    print(f"  Cash & equiv.:      {fmt(d.cash_and_equivalents, 'money')}")
    print(f"  Cash & ST invest.:  {fmt(d.cash_and_short_term_investments, 'money')}")
    print(f"  Net debt:           {fmt(d.net_debt, 'money')}")
    print(f"  Total equity (BV):  {fmt(d.total_equity, 'money')}")

    hr(f"FINANCIAL HISTORY — {len(d.periods)} year(s), most recent first")
    for p in d.periods:
        print(f"\n  -- FY {fmt(p.fiscal_year, 'raw')}  (period end {fmt(p.period_end, 'raw')}, "
              f"filed {fmt(p.filing_date, 'raw')}) --")
        print("    [Free cash flow inputs]")
        print(f"      Revenue:                {fmt(p.revenue, 'money')}")
        print(f"      EBIT:                   {fmt(p.ebit, 'money')}")
        print(f"      EBITDA:                 {fmt(p.ebitda, 'money')}")
        print(f"      Net income:             {fmt(p.net_income, 'money')}")
        print(f"      D&A:                    {fmt(p.depreciation_amortization, 'money')}")
        print(f"      Operating cash flow:    {fmt(p.operating_cash_flow, 'money')}")
        print(f"      Capital expenditure:    {fmt(p.capital_expenditure, 'money')}")
        print(f"      Free cash flow:         {fmt(p.free_cash_flow, 'money')}")
        print(f"      Chg. working capital:   {fmt(p.change_in_working_capital, 'money')}")
        print(f"      Income before tax:      {fmt(p.income_before_tax, 'money')}")
        print(f"      Income tax expense:     {fmt(p.income_tax_expense, 'money')}")
        print(f"      Effective tax rate:     {fmt(p.effective_tax_rate, 'pct')}")
        print(f"      Interest expense:       {fmt(p.interest_expense, 'money')}")
        print("    [Per-share / dividend / book value]")
        print(f"      EPS:                    {fmt(p.eps, 'num')}")
        print(f"      EPS (diluted):          {fmt(p.eps_diluted, 'num')}")
        print(f"      Diluted shares:         {fmt(p.shares_diluted, 'count')}")
        print(f"      Dividend per share:     {fmt(p.dividend_per_share, 'num')}")
        print(f"      Dividends paid (total): {fmt(p.dividends_paid, 'money')}")
        print(f"      Book value per share:   {fmt(p.book_value_per_share, 'num')}")

    hr(f"SECTOR PEERS & MULTIPLES — {len(d.peers)} peer(s)")
    print(f"  {'Symbol':<8}{'P/E':>12}{'EV/EBITDA':>14}{'P/B':>12}   Name")
    print(f"  {'-'*6:<8}{'-'*10:>12}{'-'*10:>14}{'-'*10:>12}   {'-'*20}")
    for peer in d.peers:
        print(f"  {peer.symbol:<8}{fmt(peer.pe, 'mult'):>12}"
              f"{fmt(peer.ev_ebitda, 'mult'):>14}{fmt(peer.pb, 'mult'):>12}   "
              f"{peer.name or ''}")

    hr("DATA-QUALITY WARNINGS")
    if d.warnings:
        for w in d.warnings:
            print(f"  ⚠ {w}")
    else:
        print("  none — all fields populated")


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    provider = FMPProvider()
    data = provider.get_company_data(ticker)
    print_company(data)


if __name__ == "__main__":
    main()
