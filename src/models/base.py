"""Common contract for all three valuation models (DCF, DDM, Comps).

Each model consumes a `CompanyData` and returns a `ValuationResult`. The blender
later averages the `value_per_share` (base case) of every result where `ok` is
True, renormalizing weights over the valid subset.

`audit` holds the full intermediate trail so the math can be eyeballed and
regression-tested -- nothing in the valuation should be a black box.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.data.provider import CompanyData


@dataclass
class ValuationResult:
    model: str
    ticker: str

    # Base case is the single number that feeds the blend.
    value_per_share: Optional[float] = None

    # Sensitivity range carried alongside the base case.
    low: Optional[float] = None   # bear
    base: Optional[float] = None  # == value_per_share
    high: Optional[float] = None  # bull

    ok: bool = False
    low_reliability: bool = False  # value is technically computed but fragile
    relative_only: bool = False    # priced off an extreme-multiple peer group;
                                   # context only, must not anchor intrinsic value
    assumptions: Dict[str, Any] = field(default_factory=dict)
    audit: Dict[str, Any] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)


class ValuationModel(ABC):
    name: str = "base"

    @abstractmethod
    def value(self, data: CompanyData) -> ValuationResult:
        """Value one company. Must never raise on bad/missing data: return a
        `ValuationResult` with ok=False and an explanatory flag instead."""
        raise NotImplementedError
