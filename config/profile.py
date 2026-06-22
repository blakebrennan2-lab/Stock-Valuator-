"""The quality-compounder profile — every threshold in one place.

Tighten or loosen the screen by editing these numbers only; the gate logic in
src/screen/profile.py reads them and never hard-codes a threshold.
"""

from dataclasses import dataclass


@dataclass
class ProfileConfig:
    # --- Undervaluation (ranked on this after gating) ---
    mos_floor: float = 0.20            # margin of safety must clear this

    # --- Long-term uptrend (no structural decliners) ---
    require_uptrend: bool = True       # 3y & 5y returns positive, OR price > long MA

    # --- Rising-dividend streak ---
    min_dividend_streak: int = 3       # consecutive years of higher dividend/share

    # --- Profit growth ---
    min_profit_growth_years: int = 3   # need at least this many years of net income
    profit_growth_min_cagr: float = 0.0  # net income CAGR must exceed this (>0 = growing)

    # --- Margins (high, and beat the sector) ---
    net_margin_floor: float = 0.10     # absolute net-margin floor
    require_above_sector_margin: bool = True  # also beat the sector median

    # --- Revenue durability (penalize spiky / one-off revenue) ---
    max_revenue_growth_vol: float = 0.15  # max std-dev of annual revenue growth

    # --- Output ---
    top_n: int = 5
