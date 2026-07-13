"""Blend the three model outputs into one intrinsic value per name.

Per the agreed spec: equal-weight the models that produced a usable value,
renormalizing over the valid subset. A non-payer (DDM "not applicable") or a
negative-FCF name (DCF skipped) simply contributes nothing and the remaining
models split the weight evenly.

A confidence label is attached from (a) how many models fired and (b) how much
they agree (dispersion). The ranker uses it so the top-5 isn't dominated by
single-model, high-variance guesses.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.models.base import ValuationResult


@dataclass
class BlendResult:
    ticker: str
    company_name: Optional[str] = None
    price: Optional[float] = None

    ok: bool = False
    inconclusive: bool = False                # methods too divergent to value confidently
    intrinsic_value: Optional[float] = None   # equal-weight blend (base cases)
    low: Optional[float] = None               # blended bear
    high: Optional[float] = None              # blended bull
    range_low: Optional[float] = None         # min across models' central values
    range_high: Optional[float] = None        # max across models' central values
    margin_of_safety: Optional[float] = None  # (intrinsic - price) / intrinsic

    models_used: List[str] = field(default_factory=list)
    model_values: Dict[str, float] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)
    n_models: int = 0
    dispersion: Optional[float] = None        # coeff. of variation across models
    confidence: str = "none"                  # high / medium / low / none
    quality_flags: List[str] = field(default_factory=list)  # value-trap markers
    qualifies: bool = False                    # cleared every quality-compounder gate
    profile_lines: List[str] = field(default_factory=list)  # per-trait gate scores
    notes: List[str] = field(default_factory=list)


class Blender:
    def __init__(self, mos_price: bool = True) -> None:
        # mos_price kept for symmetry/extension; MoS computed when price given.
        self.mos_price = mos_price

    def blend(
        self,
        results: List[ValuationResult],
        price: Optional[float] = None,
        ticker: Optional[str] = None,
        company_name: Optional[str] = None,
    ) -> BlendResult:
        ticker = ticker or (results[0].ticker if results else "?")
        out = BlendResult(ticker=ticker, company_name=company_name, price=price)

        valid = [
            r for r in results
            if r.ok and r.value_per_share is not None and r.value_per_share > 0
        ]
        if not valid:
            out.notes.append("No valid model produced a value")
            return out

        # --- Guardrail: drop a method whose value is wildly far from BOTH the
        # price and the other methods (a likely-broken input, e.g. a DCF whose
        # growth collapsed). Never let it into the headline or range.
        items = [(r.model, r.value_per_share) for r in valid]

        def is_broken(v, others):
            ref = statistics.median(others) if others else price
            if not ref or ref <= 0:
                return False
            far_group = v < ref * 0.4 or v > ref * 2.5
            far_price = bool(price and price > 0 and (v < price * 0.4 or v > price * 2.5))
            return far_group and far_price

        kept, dropped = [], []
        for m, v in items:
            others = [vv for mm, vv in items if mm != m]
            (dropped if (len(items) >= 2 and is_broken(v, others)) else kept).append((m, v))
        for m, v in dropped:
            note = f"{m} ${v:,.0f} excluded — far from price & peers (likely broken input)"
            out.notes.append(note + (" — DCF growth suspect" if m == "DCF" else ""))

        # A method priced off an extreme-multiple peer group may contextualize
        # but never anchor the verdict: when any grounded method survived,
        # demote the relative-only one instead of blending bubble math in.
        rel_flag = {r.model: getattr(r, "relative_only", False) for r in valid}
        if any(not rel_flag.get(m, False) for m, _ in kept):
            for m, v in [kv for kv in kept if rel_flag.get(kv[0], False)]:
                kept.remove((m, v))
                out.notes.append(
                    f"{m} ${v:,.0f} shown for context only — peer group at "
                    "extreme multiples")

        kept_vals = [v for _, v in kept]
        out.models_used = [m for m, _ in kept]
        out.model_values = dict(kept)
        out.n_models = len(kept)
        out.weights = {m: 1.0 / len(kept) for m, _ in kept} if kept else {}

        if not kept_vals:
            out.inconclusive = True
            out.confidence = "inconclusive"
            out.notes.append("inconclusive — too uncertain to value confidently")
            out.ok = True
            return out

        # A single surviving method that wildly disagrees with the market has
        # nothing to corroborate it (the others were n/a or excluded). Don't
        # publish it as a confident value — call it inconclusive. If that method
        # is the DCF, its growth input is the usual culprit.
        if len(kept_vals) == 1 and price and price > 0:
            v = kept_vals[0]
            if v < price * 0.4 or v > price * 2.5:
                m = out.models_used[0]
                out.intrinsic_value = v
                out.range_low = out.range_high = v
                out.inconclusive = True
                out.confidence = "inconclusive"
                out.notes.append(
                    f"inconclusive — only {m} produced a value and it is far from "
                    "the market (nothing to corroborate it)"
                    + (" — DCF growth suspect" if m == "DCF" else ""))
                out.ok = True
                return out

        out.range_low, out.range_high = min(kept_vals), max(kept_vals)
        # Even after dropping outliers, if the survivors still diverge wildly,
        # don't publish a giant range — call it inconclusive.
        if len(kept_vals) >= 2 and out.range_high / out.range_low > 3.0:
            out.intrinsic_value = statistics.median(kept_vals)
            out.inconclusive = True
            out.confidence = "inconclusive"
            out.notes.append("inconclusive — methods diverge too much to value confidently")
            out.ok = True
            return out

        out.intrinsic_value = statistics.median(kept_vals)
        lows = [r.low for r in valid if r.model in out.model_values
                and r.low is not None and r.low > 0]
        highs = [r.high for r in valid if r.model in out.model_values
                 and r.high is not None and r.high > 0]
        out.low = statistics.median(lows) if lows else None
        out.high = statistics.median(highs) if highs else None
        if len(kept_vals) >= 2:
            out.dispersion = statistics.pstdev(kept_vals) / out.intrinsic_value

        out.confidence = self._confidence(len(kept_vals), out.dispersion)
        if any(getattr(r, "low_reliability", False) for r in valid
               if r.model in out.model_values):
            out.confidence = "low"
            out.notes.append("a contributing model is flagged fragile")

        if price and price > 0:
            out.margin_of_safety = (out.intrinsic_value - price) / out.intrinsic_value

        out.ok = True
        return out

    @staticmethod
    def _confidence(n: int, dispersion: Optional[float]) -> str:
        if n >= 3 and dispersion is not None and dispersion <= 0.35:
            return "high"
        if n >= 2 and (dispersion is None or dispersion <= 0.60):
            return "medium"
        return "low"  # single model, or wide disagreement
