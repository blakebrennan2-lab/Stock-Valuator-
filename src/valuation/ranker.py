"""Rank blended valuations by margin of safety and surface the top names.

The 20% MoS floor is the important rule: we only flag names that are at least
20% below intrinsic value, so a flat/expensive market legitimately returns
fewer than 5 (or zero) names instead of the five least-overvalued stocks dressed
up as buys. A `min_models` gate keeps single-model, low-confidence guesses out
of the list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.valuation.blender import BlendResult


@dataclass
class RankerConfig:
    mos_floor: float = 0.20            # only surface names >=20% undervalued
    top_n: int = 5
    min_models: int = 2               # require agreement of >=2 models
    exclude_confidence: tuple = ("low", "inconclusive")  # keep noise/unscorable out
    require_quality: bool = True       # drop names with value-trap quality flags


class Ranker:
    def __init__(self, config: RankerConfig = None) -> None:
        self.cfg = config or RankerConfig()

    def rank(self, blends: List[BlendResult]) -> List[BlendResult]:
        cfg = self.cfg
        qualified = [
            b for b in blends
            if b.ok
            and b.price and b.price > 0
            and b.margin_of_safety is not None
            and b.margin_of_safety >= cfg.mos_floor
            and b.n_models >= cfg.min_models
            and b.confidence not in cfg.exclude_confidence
            and not (cfg.require_quality and b.quality_flags)
        ]
        # Primary: margin of safety. Tie-break: more models, then tighter spread.
        qualified.sort(
            key=lambda b: (
                b.margin_of_safety,
                b.n_models,
                -(b.dispersion if b.dispersion is not None else 0.0),
            ),
            reverse=True,
        )
        return qualified[: cfg.top_n]
