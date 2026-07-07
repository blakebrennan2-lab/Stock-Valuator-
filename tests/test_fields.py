"""Analyst-metrics payload validation (deterministic, no network).

Every figure in the Financial health / Capital allocation / change-our-mind
sections must trace to a reported number; a metric whose inputs are missing
must be OMITTED, never estimated.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.provider import CompanyData, FinancialPeriod
from src.valuation.blender import BlendResult
from src.web.fields import (
    MANUAL_RESEARCH, _capital_allocation, _change_mind, _health_stats,
)


def _data():
    """Hand-checkable synthetic: net cash, buybacks, dividend payer."""
    return CompanyData(
        ticker="TST", company_name="Test Corp", sector="Technology",
        price=50.0, beta=1.1, market_cap=5e9,
        total_debt=2e8, cash_and_equivalents=8e8, net_debt=2e8 - 8e8,
        total_equity=1e9, shares_outstanding=3e7, above_long_ma=True,
        periods=[  # most-recent-first
            FinancialPeriod(fiscal_year="2025", revenue=1e9, net_income=1.5e8,
                            ebit=2e8, ebitda=2.5e8, interest_expense=1e7,
                            effective_tax_rate=0.20, eps_diluted=5.0,
                            shares_diluted=3.0e7, free_cash_flow=1.2e8,
                            dividends_paid=-5e7, dividend_per_share=1.10,
                            capital_expenditure=-1e8, total_debt=2e8,
                            current_assets=6e8, current_liabilities=3e8),
            FinancialPeriod(fiscal_year="2024", revenue=9e8, net_income=1.2e8,
                            eps_diluted=4.0, shares_diluted=3.1e7,
                            free_cash_flow=1.0e8, dividend_per_share=1.00,
                            total_debt=2.5e8),
            FinancialPeriod(fiscal_year="2023", revenue=8e8, net_income=1.0e8,
                            eps_diluted=3.5, shares_diluted=3.2e7,
                            free_cash_flow=0.9e8, dividend_per_share=0.90,
                            total_debt=3e8),
        ],
    )


def _by_label(stats):
    return {s["label"]: s for s in stats}


def test_health_stats_hand_checked():
    h = _by_label(_health_stats(_data()))
    assert h["ROE (FY2025)"]["value"] == "15%"                # 150M / 1B
    assert h["ROIC (FY2025)"]["value"] == "13%"               # 200M*0.8 / 1.2B
    assert h["Interest coverage (FY2025)"]["value"] == "20.0x"  # 200M / 10M
    assert h["Net debt / EBITDA"]["value"] == "net cash"      # net debt < 0
    assert h["Current ratio (FY2025)"]["value"] == "2.0x"     # 600M / 300M
    assert h["FCF margin (FY2025)"]["value"] == "12%"         # 120M / 1B
    assert h["Revenue CAGR (2y)"]["value"] == "+12%/yr"       # (1/0.8)^0.5 - 1
    assert h["EPS CAGR (2y)"]["value"] == "+20%/yr"           # (5/3.5)^0.5 - 1
    assert all(s["src"] for s in h.values())                  # every figure sourced
    print("  ROE/ROIC/coverage/FCF margin/CAGRs all hand-checked, sourced  OK")


def test_health_omits_when_inputs_missing():
    d = _data()
    d.total_equity = None                      # no equity -> no ROE, no ROIC
    d.periods[0].interest_expense = None
    d.net_debt = 100.0                         # positive net debt, no coverage input
    d.total_debt, d.cash_and_equivalents = 300.0, 200.0
    h = _by_label(_health_stats(d))
    assert "ROE (FY2025)" not in h and "ROIC (FY2025)" not in h
    assert not any(k.startswith("Interest coverage") for k in h)
    print("  missing equity/interest -> ROE/ROIC/coverage omitted, not faked  OK")


def test_ownership_appended_when_present():
    h = _by_label(_health_stats(_data(), {"insiders": 0.07, "short_pct_float": 0.031}))
    assert h["Insider ownership"]["value"] == "7.0%"
    assert h["Short interest"]["value"] == "3.1%"
    assert "Institutional ownership" not in h   # not provided -> not shown
    print("  ownership shown only for the keys the source returned  OK")


def test_capital_allocation_lines():
    lines = " | ".join(_capital_allocation(_data()))
    assert "Dividends: $50.0M paid in FY2025" in lines
    assert "42% of free cash flow" in lines            # 50M / 120M
    assert "Buybacks: diluted share count down 6% over 2y" in lines  # 3.2e7 -> 3.0e7
    assert "Debt paydown: total debt down 33% over 2y ($300.0M → $200.0M)" in lines
    assert "capex 10% of revenue" in lines             # 100M / 1B
    print("  dividends, buybacks, debt paydown, reinvestment all traced  OK")


def test_liquidity_and_debt_omitted_when_missing():
    d = _data()
    d.periods[0].current_liabilities = None            # no liquidity inputs
    for p in d.periods[1:]:
        p.total_debt = None                            # only one debt point left
    h = _by_label(_health_stats(d))
    assert not any(k.startswith("Current ratio") for k in h)
    lines = " | ".join(_capital_allocation(d))
    assert "debt" not in lines.lower()                 # 1 point = no trend claimed
    print("  missing liquidity/debt history -> omitted, no trend fabricated  OK")


def test_debt_trend_directions():
    d = _data()
    for p, v in zip(d.periods, [4e8, 2.5e8, 3e8]):     # newest-first: rising to 400M
        p.total_debt = v
    up = " | ".join(_capital_allocation(d))
    assert "Leverage rising: total debt UP 33% over 2y" in up
    for p in d.periods:
        p.total_debt = 0.0
    assert "Debt-free across the past 3y" in " | ".join(_capital_allocation(d))
    print("  rising leverage flagged; debt-free stated plainly  OK")


def test_change_mind_tied_to_numbers():
    blend = BlendResult(ticker="TST", price=50.0, ok=True, intrinsic_value=70.0,
                        margin_of_safety=0.29, confidence="medium")
    bullets = " | ".join(_change_mind(blend, _data(), 0.15, 0.11))
    assert "$70.00" in bullets                    # fair value named
    assert "15%" in bullets and "5% quality floor" in bullets
    assert "+11% YoY" in bullets
    assert "$120.0M" in bullets                   # FCF named
    assert "200-day" in bullets                   # trend condition (above MA)
    print("  every change-our-mind bullet cites the live figure  OK")


def test_manual_research_is_static_not_computed():
    # The qualitative list must exist and clearly be judgment work, not data.
    assert len(MANUAL_RESEARCH) >= 4
    assert any("Moat" in x for x in MANUAL_RESEARCH)
    assert any("Management" in x for x in MANUAL_RESEARCH)
    assert any("litigation" in x.lower() for x in MANUAL_RESEARCH)
    print("  manual-research checklist present (moat, management, litigation)  OK")


if __name__ == "__main__":
    tests = [
        test_health_stats_hand_checked,
        test_health_omits_when_inputs_missing,
        test_ownership_appended_when_present,
        test_capital_allocation_lines,
        test_liquidity_and_debt_omitted_when_missing,
        test_debt_trend_directions,
        test_change_mind_tied_to_numbers,
        test_manual_research_is_static_not_computed,
    ]
    failed = 0
    for t in tests:
        try:
            print(f"- {t.__name__}")
            t()
        except AssertionError as e:
            failed += 1
            print(f"  FAIL: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
