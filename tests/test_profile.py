"""Quality-on-a-dip gate logic — each gate passes/fails on real figures."""

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
    nis = over.get("nis", [300, 270, 250, 230, 200])    # growing (newest first)
    revs = over.get("revs", [1000, 950, 900, 860, 820])  # smooth, growing
    years = [2025, 2024, 2023, 2022, 2021]
    periods = [FinancialPeriod(fiscal_year=str(y), net_income=n, revenue=r,
                               eps_diluted=5.0, ebitda=n * 1.3)
               for y, n, r in zip(years, nis, revs)]
    return CompanyData(
        ticker=over.get("ticker", "GOOD"), company_name="Good Co", sector="Tech",
        beta=1.0, market_cap=5e10, total_debt=1e9, cash_and_equivalents=3e9,
        net_debt=-2e9, total_equity=2e10, shares_outstanding=1e9,
        return_3y=over.get("r3", 0.40), return_5y=over.get("r5", 0.80),
        above_long_ma=over.get("above", False),
        drawdown=over.get("dd", -0.15),                  # down 15% from high
        periods=periods,
    )


def _blend(mos=0.05):
    return BlendResult(ticker="GOOD", price=85, intrinsic_value=90,
                       margin_of_safety=mos, confidence="medium", n_models=3, ok=True)


def _ev(data, blend=None, sector="Information Technology"):
    return evaluate(data, blend or _blend(), sector, 0.12, CFG, EXSEC, set())


def test_quality_on_dip_passes_all():
    r = _ev(_good())
    assert r.qualifies, r.gates
    assert "→ multiple compression" in r.gates    # sentiment-not-deterioration read
    print("  clean quality-on-a-dip clears every gate  OK")


def test_excluded_sector_fails():
    assert not _ev(_good(), sector="Energy").gates["not excluded"][0]
    print("  Energy sector excluded  OK")


def test_no_pullback_fails():
    r = _ev(_good(dd=-0.02))   # only down 2% -> not a real pullback
    assert not r.gates["recent pullback"][0] and not r.qualifies
    print("  no recent pullback -> fails the trigger  OK")


def test_too_deep_collapse_fails():
    r = _ev(_good(dd=-0.70))   # down 70% -> likely real trouble, not a dip
    assert not r.gates["recent pullback"][0]
    print("  >50% collapse rejected (likely deterioration)  OK")


def test_earnings_falling_fails():
    r = _ev(_good(nis=[150, 200, 250, 300, 350]))  # newest lowest -> declining
    assert not r.gates["earnings intact"][0] and not r.qualifies
    print("  falling earnings (not multiple compression) fails  OK")


def test_downtrend_fails():
    r = _ev(_good(r3=-0.2, r5=-0.3, above=False))
    assert not r.gates["long-term uptrend"][0]
    print("  structural downtrend fails (not a pullback)  OK")


def test_low_margin_fails():
    r = _ev(_good(nis=[20, 18, 16, 14, 12]))  # ~2% margin on 1000 revenue
    assert not r.gates["healthy margins"][0]
    print("  thin margin fails  OK")


def test_above_fair_value_fails():
    r = _ev(_good(), blend=_blend(mos=-0.30))  # 30% ABOVE fair value
    assert not r.gates["at/below fair value"][0] and not r.qualifies
    print("  trading above fair value fails  OK")


def test_dedupe_dual_class():
    fox = BlendResult(ticker="FOX", company_name="Fox Corporation", ok=True)
    foxa = BlendResult(ticker="FOXA", company_name="Fox Corporation", ok=True)
    mo = BlendResult(ticker="MO", company_name="Altria Group, Inc.", ok=True)
    assert [b.ticker for b in dedupe_dual_class([fox, foxa, mo])] == ["FOX", "MO"]
    print("  FOX/FOXA collapsed to one  OK")


if __name__ == "__main__":
    tests = [test_quality_on_dip_passes_all, test_excluded_sector_fails,
             test_no_pullback_fails, test_too_deep_collapse_fails,
             test_earnings_falling_fails, test_downtrend_fails,
             test_low_margin_fails, test_above_fair_value_fails,
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
