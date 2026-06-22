"""Per-stock detail block: every line grounded in a real figure, no fabrication."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.provider import CompanyData, FinancialPeriod
from src.models.base import ValuationResult
from src.notify.detail import build_stock_block
from src.valuation.blender import BlendResult


def _data(eps=5.0):
    return CompanyData(
        ticker="TST", company_name="Test Corp", sector="Technology",
        beta=1.5, market_cap=5e9, total_debt=2e8, cash_and_equivalents=8e8,
        net_debt=2e8 - 8e8, total_equity=1e9, shares_outstanding=3e7,
        periods=[
            FinancialPeriod(fiscal_year="2025", revenue=1e9, net_income=1.5e8,
                            ebitda=2.5e8, eps_diluted=eps, free_cash_flow=1.2e8),
            FinancialPeriod(fiscal_year="2024", revenue=9e8, net_income=1.2e8,
                            ebitda=2.2e8, eps_diluted=4.0, free_cash_flow=1.0e8),
        ],
    )


def _blend():
    return BlendResult(
        ticker="TST", company_name="Test Corp", price=50.0, intrinsic_value=100.0,
        margin_of_safety=0.5, confidence="medium", n_models=2, ok=True,
        model_values={"DCF": 90.0, "Comps": 110.0},  # non-payer: no DDM
    )


def _comps():
    return ValuationResult(model="Comps", ticker="TST", ok=True,
                           audit={"multiples": {"pe": {"median": 20.0},
                                                "ev_ebitda": {"median": 12.0},
                                                "pb": {"median": 3.0}}})


def test_block_is_grounded_in_numbers():
    block = build_stock_block(_blend(), _data(), _comps(), news=None)
    assert "50% margin of safety" in block
    assert "DCF $90" in block and "Comps $110" in block and "DDM n/a" in block
    assert "+20%/yr over 2y" in block            # FCF 100->120
    assert "Net margin 15%" in block             # 150M / 1B
    assert "Net cash $600.0M" in block           # debt 200M - cash 800M
    assert "P/E 10.0 vs peer median 20.0" in block
    assert "high volatility (beta 1.50)" in block
    assert "Beta 1.50" in block and "Mkt cap $5.0B" in block
    print("  every line reflects the real figure  OK")


def test_missing_metric_omits_its_line():
    # No EPS -> no P/E bullet or stat (never fabricated).
    block = build_stock_block(_blend(), _data(eps=None), _comps(), news=None)
    assert "P/E" not in block
    assert "peer median" not in block
    print("  missing EPS -> P/E line omitted, not invented  OK")


def test_news_litigation_flagged_and_fallback():
    news = [{"title": "Test Corp faces SEC lawsuit over disclosures",
             "publisher": "Reuters", "date": "2026-06-01"}]
    block = build_stock_block(_blend(), _data(), _comps(), news=news)
    assert "⚠️" in block and "SEC lawsuit" in block and "2026-06-01" in block

    no_source = build_stock_block(_blend(), _data(), _comps(), news=None)
    assert "no litigation/news check wired in" in no_source   # no source wired
    wired_empty = build_stock_block(_blend(), _data(), _comps(), news=[])
    assert "No recent news returned (source wired)" in wired_empty
    print("  litigation flagged; no-source vs wired-empty fallbacks correct  OK")


if __name__ == "__main__":
    tests = [test_block_is_grounded_in_numbers,
             test_missing_metric_omits_its_line,
             test_news_litigation_flagged_and_fallback]
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
