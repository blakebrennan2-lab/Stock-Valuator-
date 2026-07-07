"""DCF math validation.

Runs with plain `python3 tests/test_dcf.py` (no pytest needed) or under pytest.

Two layers:
  1. A fully hand-worked synthetic example with round numbers, where every
     intermediate is computed by hand in the comments and asserted.
  2. A frozen-input AAPL regression (real FCF history, fixed market data) so the
     end-to-end pipeline can't silently drift.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.provider import CompanyData, FinancialPeriod
from src.models.dcf import DCFConfig, DCFModel


def _period(year, fcf, tax=None, interest=None):
    return FinancialPeriod(
        fiscal_year=str(year),
        free_cash_flow=fcf,
        effective_tax_rate=tax,
        interest_expense=interest,
    )


# --------------------------------------------------------------------------- #
# 1. Hand-worked synthetic example
# --------------------------------------------------------------------------- #
# FCF (oldest->newest): 100, 110, 121, 133.1, 146.41  => exactly 10% CAGR
#   (146.41/100)^(1/4) - 1 = 1.1 - 1 = 0.10
# beta=1.0, rf=4%, ERP=5%  => cost of equity = 4% + 1.0*5% = 9%
# debt = 0  => WACC = cost of equity = 9%
# terminal g = 2.5%, 5 explicit years, FCF0 = 146.41
#
# Projected FCF (growth 10%):
#   y1 161.051  y2 177.1561  y3 194.87171  y4 214.358881  y5 235.7947691
# Discount @ 9%:
#   PV1 147.753211  PV2 149.108745  PV3 150.476715  PV4 151.857262  PV5 153.250425
#   sum explicit PV          = 752.446358
# Terminal value = 235.7947691 * 1.025 / (0.09 - 0.025)
#                = 241.6896383 / 0.065 = 3718.302128
#   PV terminal  = 3718.302128 / 1.09^5 (=1.5386239549) = 2416.641
#   EV           = 752.446358 + 2416.641 = 3169.0876
# Equity (debt 0, cash 0) = 3169.0876 ; shares = 100 ; per share = 31.6909
def test_handworked_synthetic():
    data = CompanyData(
        ticker="TEST",
        beta=1.0,
        market_cap=10_000.0,   # any positive; debt=0 makes weight_e = 1
        total_debt=0.0,
        cash_and_equivalents=0.0,
        shares_outstanding=100.0,
        periods=[  # most-recent-first
            _period(2025, 146.41),
            _period(2024, 133.1),
            _period(2023, 121.0),
            _period(2022, 110.0),
            _period(2021, 100.0),
        ],
    )
    # Isolate the engine math: no fade, cap lifted so growth stays a flat 10%.
    cfg = DCFConfig(
        risk_free_rate=0.04,
        equity_risk_premium=0.05,
        terminal_growth=0.025,
        projection_years=5,
        fade=False,
        growth_cap=0.20,
        normalize_base=False,  # use latest FCF, not median, for clean math
    )
    res = DCFModel(cfg).value(data)
    assert res.ok, res.flags

    w = res.audit["wacc"]
    assert abs(w["cost_of_equity"] - 0.09) < 1e-9, w["cost_of_equity"]
    assert abs(w["wacc"] - 0.09) < 1e-9, w["wacc"]

    g = res.audit["growth"]
    assert abs(g["applied"] - 0.10) < 1e-9, g["applied"]

    # projection tuple is now (t, growth_t, fcf, factor, pv)
    proj = res.audit["base"]["projection"]
    assert abs(proj[0][2] - 161.051) < 1e-6, proj[0][2]          # y1 FCF
    assert abs(proj[4][2] - 235.7947691) < 1e-6, proj[4][2]      # y5 FCF
    assert abs(res.audit["base"]["sum_pv_explicit"] - 752.446358) < 1e-3
    assert abs(res.audit["base"]["terminal_value"] - 3718.302128) < 1e-2
    assert abs(res.audit["base"]["enterprise_value"] - 3169.0876) < 1e-2

    assert abs(res.base - 31.6909) < 1e-3, res.base
    # Range must bracket the base case.
    assert res.low < res.base < res.high
    print(f"  synthetic per-share = {res.base:.4f}  (expected 31.6909)  OK")


# --------------------------------------------------------------------------- #
# 2. Frozen-input AAPL regression
# --------------------------------------------------------------------------- #
# Real FCF history + market snapshot captured from the live run. Default config.
# AAPL's FCF actually peaked in FY2022 and is choppy-flat since, so the median
# of year-over-year growth rates is ~0% -- an honest read, not a real grower
# being over-damped. Hand-checked outputs: WACC 9.60%, growth ~0.0%, $64.19.
def test_aapl_frozen():
    data = CompanyData(
        ticker="AAPL",
        company_name="Apple Inc.",
        beta=1.086,
        market_cap=4_376_979_000_000.0,
        total_debt=112_377_000_000.0,
        cash_and_equivalents=35_934_000_000.0,
        shares_outstanding=15_004_697_000.0,
        periods=[
            _period(2025, 98_767_000_000.0, tax=0.1561, interest=0.0),
            _period(2024, 108_807_000_000.0, tax=0.2409, interest=0.0),
            _period(2023, 99_584_000_000.0, tax=0.1472, interest=3_933_000_000.0),
            _period(2022, 111_443_000_000.0, tax=0.1620, interest=2_931_000_000.0),
            _period(2021, 92_953_000_000.0, tax=0.1330, interest=2_645_000_000.0),
        ],
    )
    res = DCFModel().value(data)
    assert res.ok, res.flags

    assert abs(res.audit["wacc"]["wacc"] - 0.0960) < 5e-4, res.audit["wacc"]["wacc"]
    assert abs(res.audit["growth"]["applied"] - 0.0002) < 5e-4, res.audit["growth"]["applied"]
    # Median-YoY growth ~0% on flat FCF + median FCF base + WACC 9.6%: $64.19.
    assert abs(res.base - 64.19) < 0.10, res.base
    print(f"  AAPL frozen per-share = {res.base:.2f}  (expected 64.19)  OK")


# --------------------------------------------------------------------------- #
# 3. Graceful degradation
# --------------------------------------------------------------------------- #
def test_negative_fcf_skips():
    data = CompanyData(
        ticker="BAD",
        beta=1.0,
        shares_outstanding=100.0,
        periods=[_period(2025, -50.0), _period(2024, -40.0)],
    )
    res = DCFModel().value(data)
    assert not res.ok
    assert any("Not applicable" in f for f in res.flags), res.flags
    print("  negative-FCF correctly skipped  OK")


def test_missing_beta_uses_fallback():
    data = CompanyData(
        ticker="NOBETA",
        beta=None,
        market_cap=1_000.0,
        total_debt=0.0,
        cash_and_equivalents=0.0,
        shares_outstanding=100.0,
        periods=[
            _period(2025, 146.41), _period(2024, 133.1), _period(2023, 121.0),
            _period(2022, 110.0), _period(2021, 100.0),
        ],
    )
    res = DCFModel().value(data)
    assert res.ok
    assert res.audit["wacc"]["used_fallback"]
    assert abs(res.audit["wacc"]["wacc"] - 0.09) < 1e-9
    print("  missing-beta fallback to 9% WACC  OK")


def test_spike_does_not_inflate_growth():
    # Flat ~100 FCF then a one-off 2x spike in the latest year. The MEDIAN of the
    # year-over-year rates (0%, 0%, +100%) is 0% -- one anomalous year can't move
    # the middle of the distribution, so growth stays grounded in the trend.
    data = CompanyData(
        ticker="SPIKE", beta=1.0, market_cap=10_000.0, total_debt=0.0,
        cash_and_equivalents=0.0, shares_outstanding=100.0,
        periods=[
            _period(2025, 200.0), _period(2024, 100.0),
            _period(2023, 100.0), _period(2022, 100.0),
        ],
    )
    res = DCFModel().value(data)
    assert res.ok
    assert res.audit["growth"]["applied"] <= 0.02, res.audit["growth"]["applied"]
    print(f"  one-off spike ignored by median; growth={res.audit['growth']['applied']:.1%}  OK")


def test_sensitivity_grid():
    # Grid must anchor on the base case and move the right way: value falls as
    # WACC rises (left->right) and rises with growth (top->bottom).
    data = CompanyData(
        ticker="SENS", beta=1.0, market_cap=10_000.0, total_debt=0.0,
        cash_and_equivalents=0.0, shares_outstanding=100.0,
        periods=[
            _period(2025, 146.41), _period(2024, 133.1), _period(2023, 121.0),
            _period(2022, 110.0), _period(2021, 100.0),
        ],
    )
    res = DCFModel().value(data)
    assert res.ok
    s = res.audit["sensitivity"]
    base_cell = s["grid"][s["base_row"]][s["base_col"]]
    assert abs(base_cell - res.base) < 1e-9, (base_cell, res.base)
    for row in s["grid"]:                      # higher WACC -> lower value
        assert row[0] > row[1] > row[2], row
    for j in range(3):                         # higher growth -> higher value
        col = [s["grid"][i][j] for i in range(len(s["grid"]))]
        assert col == sorted(col), col
    print(f"  sensitivity grid anchored on base ${base_cell:,.2f}, monotonic  OK")


if __name__ == "__main__":
    tests = [
        test_handworked_synthetic,
        test_aapl_frozen,
        test_negative_fcf_skips,
        test_missing_beta_uses_fallback,
        test_spike_does_not_inflate_growth,
        test_sensitivity_grid,
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
