"""DDM math validation.

Runs with plain `python3 tests/test_ddm.py` (no pytest needed) or under pytest.

  1. Hand-worked synthetic payer (round numbers, intermediates asserted).
  2. Frozen-input KO regression (real dividend history).
  3. Non-payer -> NOT APPLICABLE (ok=False, no fabricated number).
  4. Suspended dividend (latest = 0) -> NOT APPLICABLE.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.provider import CompanyData, FinancialPeriod
from src.models.ddm import DDMConfig, DDMModel


def _period(year, dps):
    return FinancialPeriod(fiscal_year=str(year), dividend_per_share=dps)


# --------------------------------------------------------------------------- #
# 1. Hand-worked synthetic payer
# --------------------------------------------------------------------------- #
# Dividends (oldest->newest): 1.00, 1.05, 1.1025, 1.157625, 1.21550625
#   => exactly 5% CAGR.  beta=1.0, rf=4%, ERP=5% => cost of equity = 9%.
#   g_high=5% (= historical), terminal g=2.5%, 5 explicit years, D0=1.21550625
#
# Stage-1 PVs sum to 5.440306 ; terminal value = D5*1.025/(0.09-0.025) = 24.4633
#   PV terminal = 24.4633 / 1.09^5 = 15.8994 ; two-stage value = 21.3397
# Gordon = 1.21550625*1.025/(0.09-0.025) = 19.1676
def test_handworked_payer():
    data = CompanyData(
        ticker="DIVCO",
        beta=1.0,
        periods=[
            _period(2025, 1.21550625),
            _period(2024, 1.157625),
            _period(2023, 1.1025),
            _period(2022, 1.05),
            _period(2021, 1.00),
        ],
    )
    cfg = DDMConfig(
        risk_free_rate=0.04, equity_risk_premium=0.05,
        terminal_growth=0.025, high_growth_years=5,
    )
    res = DDMModel(cfg).value(data)
    assert res.ok, res.flags

    c = res.audit["cost_of_equity"]
    assert abs(c["cost_of_equity"] - 0.09) < 1e-9, c["cost_of_equity"]
    assert abs(res.audit["growth"]["applied"] - 0.05) < 1e-9

    ts = res.audit["two_stage"]
    assert abs(ts["stage1"][0][1] - 1.2762815625) < 1e-9          # D1
    assert abs(ts["sum_pv_stage1"] - 5.440306) < 1e-3
    assert abs(ts["terminal_value"] - 24.46325) < 1e-3
    assert abs(res.base - 21.3397) < 1e-2, res.base
    assert abs(res.audit["gordon"]["value"] - 19.1676) < 1e-2
    assert res.low < res.base < res.high
    print(f"  synthetic two-stage = {res.base:.4f} (exp 21.3397), "
          f"gordon = {res.audit['gordon']['value']:.4f} (exp 19.1676)  OK")


# --------------------------------------------------------------------------- #
# 2. Frozen-input KO regression
# --------------------------------------------------------------------------- #
def test_ko_frozen():
    data = CompanyData(
        ticker="KO", company_name="The Coca-Cola Company", beta=0.354,
        periods=[
            _period(2025, 2.0402), _period(2024, 1.9399), _period(2023, 1.8395),
            _period(2022, 1.7597), _period(2021, 1.6806),
        ],
    )
    res = DDMModel().value(data)
    assert res.ok, res.flags
    assert abs(res.audit["cost_of_equity"]["cost_of_equity"] - 0.0607) < 5e-4
    # Low beta (0.354) -> raw coe 6.07% floored to the 9% discount-rate floor.
    assert abs(res.audit["discount_rate_used"] - 0.09) < 1e-9
    assert abs(res.audit["growth"]["applied"] - 0.0497) < 5e-4
    assert abs(res.base - 35.77) < 0.10, res.base
    assert abs(res.audit["gordon"]["value"] - 32.17) < 0.10
    print(f"  KO frozen two-stage = {res.base:.2f} (exp 35.77, r floored to 9%)  OK")


# --------------------------------------------------------------------------- #
# 3. Non-payer -> NOT APPLICABLE
# --------------------------------------------------------------------------- #
def test_non_payer_not_applicable():
    data = CompanyData(
        ticker="AMZN", beta=1.2,
        periods=[_period(2025, None), _period(2024, None), _period(2023, None)],
    )
    res = DDMModel().value(data)
    assert not res.ok
    assert res.value_per_share is None
    assert any("Not applicable" in f for f in res.flags), res.flags
    print("  non-payer -> NOT APPLICABLE (no number)  OK")


# --------------------------------------------------------------------------- #
# 4. Suspended dividend (latest = 0)
# --------------------------------------------------------------------------- #
def test_suspended_dividend():
    data = CompanyData(
        ticker="CUTCO", beta=1.0,
        periods=[  # most-recent-first: paid in the past, now zero
            _period(2025, 0.0), _period(2024, 0.0),
            _period(2023, 1.0), _period(2022, 1.0), _period(2021, 1.0),
        ],
    )
    res = DDMModel().value(data)
    assert not res.ok
    assert any("Not applicable" in f for f in res.flags), res.flags
    print("  suspended dividend -> NOT APPLICABLE  OK")


def test_token_dividend_not_meaningful():
    # Buyback-driven: rising but tiny dividend (yield ~0.5%, payout ~10%).
    data = CompanyData(
        ticker="BUYBACK", beta=1.0, price=100.0,
        periods=[
            FinancialPeriod(fiscal_year="2025", dividend_per_share=0.50, eps_diluted=5.0),
            FinancialPeriod(fiscal_year="2024", dividend_per_share=0.45, eps_diluted=4.5),
            FinancialPeriod(fiscal_year="2023", dividend_per_share=0.40, eps_diluted=4.0),
        ],
    )
    res = DDMModel().value(data)
    assert not res.ok
    assert any("Not meaningful" in f for f in res.flags), res.flags
    print("  token dividend (low yield/payout) -> DDM not meaningful  OK")


if __name__ == "__main__":
    tests = [
        test_handworked_payer,
        test_ko_frozen,
        test_non_payer_not_applicable,
        test_suspended_dividend,
        test_token_dividend_not_meaningful,
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
