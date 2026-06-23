"""Dividend Discount Model (Gordon + two-stage).

Method
------
1. Build the annual dividend-per-share history. If the company doesn't pay a
   dividend, return a result with ok=False and a "not applicable" flag -- we
   never fabricate a number for a non-payer; the blender just drops DDM for it.
2. Dividend growth from history (CAGR), capped to a sane band.
3. Discount rate = CAPM cost of equity (rf + beta*ERP); 9% fallback if beta is
   missing, mirroring the DCF.
4. Two-stage value (base case that feeds the blend): explicit high-growth years
   then a Gordon terminal. A single-stage Gordon value is computed alongside for
   reference.
5. Bull/bear shift the high-growth rate and the discount rate together.

Every intermediate is recorded in `ValuationResult.audit`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.data.provider import CompanyData
from src.models.base import ValuationModel, ValuationResult


@dataclass
class DDMConfig:
    risk_free_rate: float = 0.043
    equity_risk_premium: float = 0.05  # standard long-run US ERP
    terminal_growth: float = 0.025     # <= long-run nominal GDP
    high_growth_years: int = 5
    growth_cap: float = 0.08           # mature-name ceiling on dividend growth
    growth_floor: float = 0.0          # don't project shrinking dividends
    coe_fallback: float = 0.09         # cost of equity when beta missing
    coe_floor: float = 0.09            # discount-rate floor (low-beta defensiveness)
    min_yield: float = 0.015           # below this, dividend is a token (buyback-driven)
    min_payout: float = 0.20           # below this payout ratio, DDM isn't meaningful
    min_spread: float = 0.04           # r - g >= this -> terminal multiple <= 25x
    growth_delta: float = 0.02         # scenario shift on high-growth rate
    rate_delta: float = 0.01           # scenario shift on discount rate


@dataclass
class CostOfEquity:
    beta: Optional[float]
    risk_free_rate: float
    equity_risk_premium: float
    cost_of_equity: float
    used_fallback: bool


class DDMModel(ValuationModel):
    name = "DDM"

    def __init__(self, config: Optional[DDMConfig] = None) -> None:
        self.cfg = config or DDMConfig()

    # ------------------------------------------------------------------ #
    def value(self, data: CompanyData) -> ValuationResult:
        cfg = self.cfg
        result = ValuationResult(model=self.name, ticker=data.ticker)

        # --- 1. Dividend history (oldest -> newest) -------------------- #
        div_series = [
            (p.fiscal_year, p.dividend_per_share)
            for p in reversed(data.periods)
            if p.dividend_per_share is not None
        ]
        positive = [d for _, d in div_series if d and d > 0]

        # Non-payer / no usable history -> NOT APPLICABLE (no forced number).
        if not positive:
            result.flags.append("Not applicable: no dividend history (non-payer)")
            result.audit = {"dividend_history": div_series}
            return result

        d0 = div_series[-1][1]
        if d0 is None or d0 <= 0:
            result.flags.append(
                "Not applicable: latest dividend is zero (suspended/non-payer)"
            )
            result.audit = {"dividend_history": div_series}
            return result

        # --- 1b. NOT MEANINGFUL when the dividend is a token payout ----- #
        # Buyback-driven names (low yield / low payout) would be grossly
        # undervalued by DDM, so we exclude it rather than show a misleading
        # co-equal number. Applies generally, not just to one company.
        yld = (d0 / data.price) if data.price else None
        eps = data.latest.eps_diluted if data.latest else None
        payout = (d0 / eps) if (eps and eps > 0) else None
        if (yld is not None and yld < cfg.min_yield) or \
           (payout is not None and payout < cfg.min_payout):
            yld_s = f"{yld:.1%}" if yld is not None else "n/a"
            pay_s = f"{payout:.0%}" if payout is not None else "n/a"
            result.flags.append(
                f"Not meaningful for this company: token dividend "
                f"(yield {yld_s}, payout {pay_s}) — returns cash via buybacks; "
                f"DDM excluded from the blend")
            result.audit = {"dividend_history": div_series, "yield": yld, "payout": payout}
            return result

        # --- 2. Growth from dividend history (CAGR), capped ------------ #
        oldest = next((d for _, d in div_series if d and d > 0), None)
        first_idx = next(i for i, (_, d) in enumerate(div_series) if d and d > 0)
        n_steps = (len(div_series) - 1) - first_idx
        historical_negative = False
        if oldest and oldest > 0 and n_steps >= 1:
            raw_growth = (d0 / oldest) ** (1.0 / n_steps) - 1.0
            method = f"CAGR over {n_steps + 1} dividend yrs"
        else:
            raw_growth = cfg.terminal_growth
            method = "fallback (insufficient history)"
        if raw_growth < 0:
            historical_negative = True
        applied_growth = max(cfg.growth_floor, min(cfg.growth_cap, raw_growth))
        growth_capped = applied_growth != raw_growth

        # --- 3. Discount rate (cost of equity), floored ---------------- #
        # Floor at coe_floor so low-beta names don't get a near-growth discount
        # rate, and keep r - g >= min_spread so the terminal multiple can't blow
        # up (1 / min_spread = max multiple).
        coe = self._cost_of_equity(data)
        r = max(coe.cost_of_equity, cfg.coe_floor, cfg.terminal_growth + cfg.min_spread)

        # --- 4. Two-stage (base) + single-stage Gordon ---------------- #
        base_scn = self._two_stage(d0, applied_growth, r)
        gordon_value = d0 * (1.0 + cfg.terminal_growth) / (r - cfg.terminal_growth)

        # --- 5. Bull / bear ------------------------------------------- #
        bull = self._two_stage(
            d0,
            min(cfg.growth_cap, applied_growth + cfg.growth_delta),
            max(cfg.terminal_growth + cfg.min_spread, r - cfg.rate_delta),
        )
        bear = self._two_stage(
            d0,
            max(cfg.growth_floor, applied_growth - cfg.growth_delta),
            r + cfg.rate_delta,
        )

        result.ok = True
        result.base = base_scn["value"]
        result.value_per_share = base_scn["value"]
        result.high = bull["value"]
        result.low = bear["value"]
        result.assumptions = {
            "risk_free_rate": cfg.risk_free_rate,
            "equity_risk_premium": cfg.equity_risk_premium,
            "terminal_growth": cfg.terminal_growth,
            "high_growth_years": cfg.high_growth_years,
            "growth_applied": applied_growth,
            "discount_rate": r,
        }
        result.audit = {
            "dividend_history": div_series,
            "d0": d0,
            "growth": {
                "method": method,
                "raw": raw_growth,
                "applied": applied_growth,
                "capped": growth_capped,
                "historical_negative": historical_negative,
            },
            "cost_of_equity": coe.__dict__,
            "discount_rate_used": r,
            "two_stage": base_scn,
            "gordon": {
                "d1": d0 * (1.0 + cfg.terminal_growth),
                "value": gordon_value,
            },
            "scenarios": {
                "bear": bear["value"],
                "base": base_scn["value"],
                "bull": bull["value"],
            },
        }
        if coe.used_fallback:
            result.flags.append("Discount rate used 9% fallback (beta missing)")
        if historical_negative:
            result.flags.append(
                "Historical dividend growth was negative; floored to 0%"
            )
        if growth_capped and not historical_negative:
            result.flags.append(
                f"Growth capped from {raw_growth:.1%} to {applied_growth:.1%}"
            )
        return result

    # ------------------------------------------------------------------ #
    def _cost_of_equity(self, data: CompanyData) -> CostOfEquity:
        cfg = self.cfg
        if data.beta is None:
            return CostOfEquity(
                beta=None,
                risk_free_rate=cfg.risk_free_rate,
                equity_risk_premium=cfg.equity_risk_premium,
                cost_of_equity=cfg.coe_fallback,
                used_fallback=True,
            )
        coe = cfg.risk_free_rate + data.beta * cfg.equity_risk_premium
        return CostOfEquity(
            beta=data.beta,
            risk_free_rate=cfg.risk_free_rate,
            equity_risk_premium=cfg.equity_risk_premium,
            cost_of_equity=coe,
            used_fallback=False,
        )

    # ------------------------------------------------------------------ #
    def _two_stage(self, d0: float, g_high: float, r: float) -> dict:
        """Explicit high-growth dividends + Gordon terminal, all discounted."""
        cfg = self.cfg
        g_term = cfg.terminal_growth

        stage1 = []  # (t, dividend, discount_factor, pv)
        div = d0
        sum_pv = 0.0
        for t in range(1, cfg.high_growth_years + 1):
            div = div * (1.0 + g_high)
            factor = (1.0 + r) ** t
            pv = div / factor
            sum_pv += pv
            stage1.append((t, div, factor, pv))

        last_div = stage1[-1][1]
        terminal_dividend = last_div * (1.0 + g_term)
        terminal_value = terminal_dividend / (r - g_term)
        tv_factor = (1.0 + r) ** cfg.high_growth_years
        pv_terminal = terminal_value / tv_factor

        value = sum_pv + pv_terminal
        return {
            "g_high": g_high,
            "discount_rate": r,
            "terminal_growth": g_term,
            "stage1": stage1,
            "sum_pv_stage1": sum_pv,
            "terminal_dividend": terminal_dividend,
            "terminal_value": terminal_value,
            "tv_discount_factor": tv_factor,
            "pv_terminal": pv_terminal,
            "value": value,
        }
