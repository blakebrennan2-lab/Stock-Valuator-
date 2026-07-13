"""Blender + Ranker validation (deterministic, no network).

  Blender: equal-weight over valid models; renormalize when one is missing;
           confidence from count + dispersion; MoS from price.
  Ranker:  20% floor, min-models gate, sort by MoS, top-N, empty when nothing
           qualifies.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models.base import ValuationResult
from src.valuation.blender import Blender
from src.valuation.ranker import Ranker, RankerConfig


def _res(model, value, low=None, high=None, ok=True):
    return ValuationResult(
        model=model, ticker="T", value_per_share=value, base=value,
        low=low, high=high, ok=ok,
    )


# --------------------------------------------------------------------------- #
# Blender
# --------------------------------------------------------------------------- #
def test_blend_three_median():
    # Median-of-models drops the outlier: median(90,60,150)=90, not mean 100.
    results = [_res("DCF", 150, 100, 200), _res("DDM", 60, 50, 80),
               _res("Comps", 90, 70, 110)]
    b = Blender().blend(results, price=72, ticker="T")
    assert b.ok
    assert abs(b.intrinsic_value - 90) < 1e-9            # median, outlier dropped
    assert b.weights == {"DCF": 1/3, "DDM": 1/3, "Comps": 1/3}
    assert abs(b.low - 70) < 1e-9                        # median of [100,50,70]
    assert abs(b.high - 110) < 1e-9                      # median of [200,80,110]
    assert abs(b.margin_of_safety - (90-72)/90) < 1e-9   # 20%
    assert b.n_models == 3
    print(f"  3-model median blend = {b.intrinsic_value} (outlier 150 dropped) "
          f"MoS={b.margin_of_safety:.0%}  OK")


def test_blend_renormalizes_when_model_missing():
    # DDM not applicable (ok=False) -> only DCF + Comps split 50/50.
    results = [_res("DCF", 100), _res("DDM", None, ok=False), _res("Comps", 200)]
    b = Blender().blend(results, price=100, ticker="T")
    assert b.n_models == 2
    assert abs(b.intrinsic_value - 150) < 1e-9
    assert set(b.weights.values()) == {0.5}
    assert "DDM" not in b.models_used
    print(f"  renormalized 2-model blend = {b.intrinsic_value} (DDM dropped)  OK")


def test_blend_excludes_broken_method():
    # A DCF that collapsed to $10 while DDM/Comps and price all cluster ~$105 is
    # a likely-broken input: drop it, don't drag the range down to $10, and flag
    # the DCF growth as suspect.
    results = [_res("DCF", 10, 8, 12), _res("DDM", 100, 90, 110),
               _res("Comps", 110, 95, 125)]
    b = Blender().blend(results, price=105, ticker="T")
    assert b.ok and not b.inconclusive
    assert "DCF" not in b.model_values, b.model_values
    assert b.n_models == 2
    assert abs(b.intrinsic_value - 105) < 1e-9             # median(100,110)
    assert abs(b.range_low - 100) < 1e-9                   # broken $10 not in range
    assert any("growth suspect" in n for n in b.notes), b.notes
    print(f"  broken DCF $10 excluded; blend={b.intrinsic_value} range "
          f"{b.range_low}-{b.range_high}, growth flagged  OK")


def test_blend_inconclusive_when_survivors_diverge():
    # Two methods survive the outlier check (each is far from the OTHER but not
    # also far from price) yet disagree >3x: too uncertain to publish a number.
    results = [_res("DCF", 50, 40, 60), _res("Comps", 200, 180, 220)]
    b = Blender().blend(results, price=120, ticker="T")
    assert b.ok and b.inconclusive
    assert b.confidence == "inconclusive"
    assert b.margin_of_safety is None      # no headline MoS published
    assert Ranker().rank([b]) == []        # never surfaced as a buy
    print("  divergent survivors -> inconclusive, no MoS, not ranked  OK")


def test_blend_demotes_relative_only_comps():
    # The Dell case: cash-flow DCF says $194, Comps says $742 off a peer group
    # at extreme multiples. The relative-only comp must NOT anchor the verdict:
    # blend = DCF alone -> an honest OVERVALUED margin, not a +42% "buy".
    dcf = _res("DCF", 194, 160, 240)
    comps = _res("Comps", 742, 380, 1100)
    comps.relative_only = True
    b = Blender().blend([dcf, comps], price=427, ticker="DELL")
    assert b.ok and not b.inconclusive
    assert b.models_used == ["DCF"], b.models_used
    assert abs(b.intrinsic_value - 194) < 1e-9
    assert b.margin_of_safety < -1.0            # deeply negative = overvalued
    assert any("context only" in n for n in b.notes), b.notes
    # But when the relative-only comp is ALL that survived, it still values
    # (flagged low), rather than silently vanishing.
    only = _res("Comps", 130, 110, 150); only.relative_only = True
    b2 = Blender().blend([only, _res("DCF", None, ok=False)], price=100, ticker="T")
    assert b2.ok and b2.models_used == ["Comps"]
    print("  extreme-peer Comps demoted to context; DCF anchors verdict  OK")


def test_blend_lone_method_far_from_price_is_inconclusive():
    # Only DCF fires (DDM/Comps n/a) and it lands at $84 vs a $365 price -- a
    # lone, uncorroborated method that wildly disagrees with the market. This is
    # the MSFT case: don't publish $84 as a confident value, call it inconclusive
    # and flag DCF growth.
    results = [_res("DCF", 84), _res("DDM", None, ok=False),
               _res("Comps", None, ok=False)]
    b = Blender().blend(results, price=365, ticker="MSFT")
    assert b.ok and b.inconclusive
    assert b.confidence == "inconclusive"
    assert b.margin_of_safety is None
    assert any("growth suspect" in n for n in b.notes), b.notes
    assert Ranker().rank([b]) == []
    print("  lone DCF far from price -> inconclusive, growth flagged  OK")


def test_blend_lone_method_near_price_still_values():
    # A single method that broadly agrees with the market (within band) is still
    # a usable value -- we only bail when it wildly disagrees.
    results = [_res("Comps", 130, 110, 150), _res("DCF", None, ok=False),
               _res("DDM", None, ok=False)]
    b = Blender().blend(results, price=100, ticker="T")
    assert b.ok and not b.inconclusive
    assert abs(b.intrinsic_value - 130) < 1e-9
    assert abs(b.margin_of_safety - (130 - 100) / 130) < 1e-9
    print("  lone Comps near price -> still valued (MoS published)  OK")


def test_blend_none_valid():
    results = [_res("DCF", None, ok=False), _res("DDM", None, ok=False)]
    b = Blender().blend(results, price=100, ticker="T")
    assert not b.ok and b.intrinsic_value is None
    print("  no valid models -> blend not ok  OK")


def test_confidence_levels():
    tight = [_res("DCF", 100), _res("DDM", 105), _res("Comps", 95)]
    assert Blender().blend(tight, ticker="T").confidence == "high"
    one = [_res("Comps", 100), _res("DCF", None, ok=False),
           _res("DDM", None, ok=False)]
    assert Blender().blend(one, ticker="T").confidence == "low"
    print("  confidence high (tight,3) / low (single model)  OK")


# --------------------------------------------------------------------------- #
# Ranker
# --------------------------------------------------------------------------- #
def _blend(ticker, intrinsic, price, n_models=2):
    results = [_res("DCF", intrinsic), _res("Comps", intrinsic)][:n_models]
    return Blender().blend(results, price=price, ticker=ticker)


def test_ranker_floor_and_sort():
    blends = [
        _blend("CHEAP", 200, 100),   # MoS 50%
        _blend("OK", 130, 100),      # MoS 23%
        _blend("MEH", 110, 100),     # MoS 9%  -> below 20% floor
        _blend("RICH", 90, 100),     # MoS -11% -> filtered
    ]
    top = Ranker().rank(blends)
    assert [b.ticker for b in top] == ["CHEAP", "OK"], [b.ticker for b in top]
    print(f"  ranked: {[b.ticker for b in top]} (floor screened MEH/RICH)  OK")


def test_ranker_empty_when_nothing_qualifies():
    blends = [_blend("A", 105, 100), _blend("B", 90, 100)]  # 5%, -11%
    assert Ranker().rank(blends) == []
    print("  expensive market -> empty top list (feature)  OK")


def test_ranker_min_models_gate():
    blends = [
        _blend("SOLID", 200, 100, n_models=2),   # MoS 50%, 2 models
        _blend("SHAKY", 300, 100, n_models=1),   # MoS 67% but 1 model -> gated
    ]
    top = Ranker(RankerConfig(min_models=2)).rank(blends)
    assert [b.ticker for b in top] == ["SOLID"], [b.ticker for b in top]
    print("  min-models gate drops single-model SHAKY despite higher MoS  OK")


def test_ranker_quality_gate():
    # A high-MoS name flagged as a value trap must be excluded.
    trap = _blend("TRAP", 200, 100)        # MoS 50%, medium
    trap.quality_flags = ["revenue declining"]
    clean = _blend("CLEAN", 150, 100)      # MoS 33%, medium, no flags
    top = Ranker().rank([trap, clean])
    assert [b.ticker for b in top] == ["CLEAN"], [b.ticker for b in top]
    print("  quality gate drops value-trap TRAP despite higher MoS  OK")


def test_low_reliability_forces_low_confidence():
    r1 = _res("DCF", 100)
    r1.low_reliability = True   # e.g. terminal-dominated DCF
    r2 = _res("Comps", 105)
    b = Blender().blend([r1, r2], price=50, ticker="T")
    assert b.confidence == "low", b.confidence
    assert abs(b.range_low - 100) < 1e-9 and abs(b.range_high - 105) < 1e-9
    print("  fragile model -> LOW confidence + model range exposed  OK")


def test_ranker_confidence_gate():
    # A 'low' confidence name with huge MoS must not appear in the top list.
    low = _res("Comps", 300)  # single model -> low confidence
    low_blend = Blender().blend([low], price=100, ticker="NOISY")
    low_blend.n_models = 2  # force past min_models so only the conf gate can stop it
    good = _blend("REAL", 200, 100)  # 2 models -> medium
    top = Ranker().rank([low_blend, good])
    assert [b.ticker for b in top] == ["REAL"], [b.ticker for b in top]
    print("  confidence gate drops 'low' NOISY despite higher MoS  OK")


if __name__ == "__main__":
    tests = [
        test_blend_three_median,
        test_blend_renormalizes_when_model_missing,
        test_blend_excludes_broken_method,
        test_blend_inconclusive_when_survivors_diverge,
        test_blend_demotes_relative_only_comps,
        test_blend_lone_method_far_from_price_is_inconclusive,
        test_blend_lone_method_near_price_still_values,
        test_blend_none_valid,
        test_confidence_levels,
        test_ranker_floor_and_sort,
        test_ranker_empty_when_nothing_qualifies,
        test_ranker_min_models_gate,
        test_ranker_confidence_gate,
        test_ranker_quality_gate,
        test_low_reliability_forces_low_confidence,
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
