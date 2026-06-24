"""The screen profile — quality companies on a sentiment-driven dip.

The trigger is a recent pullback (down from the 52-week high) where the
fundamentals are still intact — earnings/revenue/margins stable-to-improving and
a long-term uptrend — i.e. the drop is multiple compression, not deterioration.
Valuation only has to be at/below fair value, not deeply discounted.

Every threshold lives here; the gate logic in src/screen/profile.py reads these
and never hard-codes a number.
"""

from dataclasses import dataclass


@dataclass
class ProfileConfig:
    # --- Recent-pullback trigger (the main signal) ---
    min_pullback: float = 0.10        # down at least 10% from the 52-week high
    max_pullback: float = 0.50        # but not a >50% collapse (likely real trouble)

    # --- Valuation: at or below fair value (not a deep discount) ---
    mos_floor: float = 0.0            # margin of safety >= 0 (price <= fair value)

    # --- Quality / fundamentals-intact ---
    require_uptrend: bool = True      # long-term uptrend (3y & 5y returns positive, or > long MA)
    min_profit_growth_years: int = 3  # need this many years of earnings history
    profit_growth_min_cagr: float = 0.0   # earnings stable-to-growing (no deterioration)
    net_margin_floor: float = 0.05    # healthy, profitable margins
    max_revenue_growth_vol: float = 0.20  # durable, non-spiky revenue

    # --- Output ---
    top_n: int = 3                    # top 3 quality-on-a-dip names daily
