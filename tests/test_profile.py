"""Quality-compounder gate logic — each gate passes/fails on real figures."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.profile import ProfileConfig
from src.data.provider import CompanyData, FinancialPeriod
from src.screen.profile import dedupe_dual_class, evaluate
from src.valuation.blender import BlendResult

CFG = ProfileConfig()
EXSEC = {"Energy"}


def _good(**over):
    """A company that clears every gate; override fields to break one."""
    divs = over.get("divs", [2.0, 1.8, 1.6, 1.4, 1.2])      # rising
    nis = over.get("nis", [300, 270, 250, 230, 200])         # growing (newest first)
    revs = over.get("revs", [1000, 950, 900, 860, 820])      # smooth
    years = [2025, 2024, 2023, 2022, 2021]
    periods = [FinancialPeriod(fiscal_year=str(y), dividend_per_share=d,
                               net_income=n, revenue=r,
                               eps_diluted=5.0, ebitda=n * 1.3)
               for y, d, n, r in zip(years, divs, nis, revs)]
    return CompanyData(
        ticker=over.get("ticker", "GOOD"), company_name="Good Co", beta=1.0,
        market_cap=5e10, total_debt=1e9, cash_and_equivalents=3e9,
        net_debt=-2e9, total_equity=2e10, shares_outstanding=1e9,
        return_3y=over.get("r3", 0.40), return_5y=over.get("r5", 0.80),
        above_long_ma=over.get("above", True), periods=periods,
    )


def _blend(mos=0.30):
    return BlendResult(ticker="GOOD", price=70, intrinsic_value=100,
                       margin_of_safety=mos, confidence="high", n_models=3, ok=True)


def _ev(data, blend=None, sector="Information Technology", sec_med=0.12):
    return evaluate(data, blend or _blend(), sector, sec_med, CFG, EXSEC, set())


def test_quality_compounder_passes_all():
    r = _ev(_good())
    assert r.qualifies, r.gates
    assert all(ok for ok, _ in r.gates.values())
    print("  clean compounder clears every gate  OK")


def test_excluded_sector_fails():
    assert not _ev(_good(), sector="Energy").gates["not excluded"][0]
    print("  Energy sector excluded  OK")


def test_downtrend_fails():
    r = _ev(_good(r3=-0.1, r5=-0.2, above=False))
    assert not r.gates["uptrend"][0] and not r.qualifies
    print("  structural decliner fails uptrend  OK")


def test_flat_dividend_fails_streak():
    r = _ev(_good(divs=[1.5, 1.5, 1.5, 1.5, 1.5]))
    assert not r.gates["dividend streak"][0]
    print("  no rising-dividend streak fails  OK")


def test_shrinking_profit_fails():
    r = _ev(_good(nis=[150, 200, 250, 300, 350]))  # newest lowest -> declining
    assert not r.gates["profit growth"][0]
    print("  shrinking profits fail  OK")


def test_low_margin_fails():
    # net income tiny vs revenue -> margin below floor
    r = _ev(_good(nis=[20, 18, 16, 14, 12]))
    assert not r.gates["high margin"][0]
    print("  thin margin fails  OK")


def test_spiky_revenue_fails():
    r = _ev(_good(revs=[600, 1200, 400, 1000, 500]))
    assert not r.gates["revenue durability"][0]
    print("  spiky revenue fails durability  OK")


def test_not_undervalued_fails():
    r = _ev(_good(), blend=_blend(mos=0.05))  # below 20% floor
    assert not r.gates["undervalued"][0] and not r.qualifies
    print("  not-cheap-enough fails undervaluation  OK")


def test_dedupe_dual_class():
    # FOX/FOXA share a company name -> keep the first (cheapest, since pre-sorted).
    fox = BlendResult(ticker="FOX", company_name="Fox Corporation",
                      margin_of_safety=0.54, ok=True)
    foxa = BlendResult(ticker="FOXA", company_name="Fox Corporation",
                       margin_of_safety=0.49, ok=True)
    other = BlendResult(ticker="MO", company_name="Altria Group, Inc.",
                        margin_of_safety=0.18, ok=True)
    out = dedupe_dual_class([fox, foxa, other])
    assert [b.ticker for b in out] == ["FOX", "MO"], [b.ticker for b in out]
    print("  FOX/FOXA collapsed to one; distinct names kept  OK")


if __name__ == "__main__":
    tests = [test_quality_compounder_passes_all, test_excluded_sector_fails,
             test_downtrend_fails, test_flat_dividend_fails_streak,
             test_shrinking_profit_fails, test_low_margin_fails,
             test_spiky_revenue_fails, test_not_undervalued_fails,
             test_dedupe_dual_class]
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
