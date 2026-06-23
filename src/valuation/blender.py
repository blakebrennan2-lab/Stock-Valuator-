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

        n = len(valid)
        weight = 1.0 / n
        out.model_values = {r.model: r.value_per_share for r in valid}
        out.weights = {r.model: weight for r in valid}
        out.models_used = [r.model for r in valid]
        out.n_models = n

        values = list(out.model_values.values())
        # Median-of-models, not mean: with 3 models the outlier is dropped
        # entirely (e.g. a blown-up DCF), while staying equal-treatment. With 2
        # models the median equals the mean.
        out.intrinsic_value = statistics.median(values)

        lows = [r.low for r in valid if r.low is not None and r.low > 0]
        highs = [r.high for r in valid if r.high is not None and r.high > 0]
        out.low = statistics.median(lows) if lows else None
        out.high = statistics.median(highs) if highs else None

        if n >= 2:
            mean = out.intrinsic_value
            out.dispersion = (statistics.pstdev(values) / mean) if mean else None

        # Range across the valid models' central estimates (the disagreement).
        out.range_low = min(values)
        out.range_high = max(values)

        out.confidence = self._confidence(n, out.dispersion)
        # A model flagged as fragile (e.g. terminal-dominated DCF, or an implied
        # multiple far above the market) forces LOW confidence regardless of CV.
        if any(getattr(r, "low_reliability", False) for r in valid):
            out.confidence = "low"
            out.notes.append("a contributing model is flagged fragile")

        if price and price > 0 and out.intrinsic_value:
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
