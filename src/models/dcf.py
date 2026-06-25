"""Discounted Cash Flow model (unlevered FCF -> enterprise value -> equity).

Method
------
1. Base FCF growth from historical free cash flow (CAGR over available years),
   capped to a sane band so one anomalous year can't dominate.
2. Project N years of FCF at that growth rate.
3. Discount each year's FCF at a per-stock WACC (CAPM cost of equity blended
   with after-tax cost of debt by market-value weights; 9% fallback when beta
   is missing, per spec).
4. Gordon-growth terminal value on the final projected FCF, discounted back.
5. Sum of PVs = enterprise value. Bridge EV -> equity (less debt, plus cash),
   divide by shares = intrinsic value per share.

The base case feeds the blend; bull/bear shift growth and WACC together to
bracket it. Every intermediate is recorded in `ValuationResult.audit`.

Assumption / known simplification: we use reported free cash flow (CFO - capex)
as the FCF series and discount at WACC, then subtract net debt. This is the
common practitioner shortcut; it slightly understates equity for heavily levered
firms (levered FCF discounted at WACC). Documented here so it's not a surprise.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import List, Optional

from src.data.provider import CompanyData
from src.models.base import ValuationModel, ValuationResult


@dataclass
class DCFConfig:
    risk_free_rate: float = 0.043      # ~10Y Treasury
    equity_risk_premium: float = 0.05  # standard long-run US ERP
    terminal_growth: float = 0.025     # <= long-run nominal GDP
    projection_years: int = 5
    growth_cap: float = 0.08           # mature-name ceiling on near-term FCF growth
    growth_floor: float = -0.05        # min base growth
    fade: bool = True                  # fade growth from g0 -> terminal over horizon
    normalize_base: bool = True        # use median FCF as base (smooths cyclical peaks)
    cost_of_equity_floor: float = 0.09  # equity holders demand >= this
    wacc_floor: float = 0.09           # no equity valued below a 9% discount rate
    default_beta: float = 1.0          # used only inside CAPM if beta present-but-odd
    wacc_fallback: float = 0.09        # whole-WACC fallback when beta missing
    cost_of_debt_spread: float = 0.01  # over rf, when interest/debt can't price it
    default_tax_rate: float = 0.21     # US statutory, when effective rate missing
    # Terminal growth is tied to the firm's own trend, clamped to
    # [0, terminal_growth] -- no assuming a declining business grows at GDP forever.
    # Scenario shifts (applied to base growth and base WACC).
    growth_delta: float = 0.03
    wacc_delta: float = 0.01
    min_wacc_spread: float = 0.04      # WACC - g >= this -> terminal multiple <= 25x
    # Reliability sanity checks.
    max_terminal_share: float = 0.75   # flag if terminal PV > this share of EV
    multiple_flag_ratio: float = 1.8   # flag if DCF-implied FCF multiple >> market's


@dataclass
class WaccBreakdown:
    beta: Optional[float]
    risk_free_rate: float
    equity_risk_premium: float
    cost_of_equity: float
    cost_of_debt_pretax: float
    cost_of_debt_aftertax: float
    tax_rate: float
    equity_value: float
    debt_value: float
    weight_equity: float
    weight_debt: float
    wacc: float
    used_fallback: bool
    notes: List[str]


class DCFModel(ValuationModel):
    name = "DCF"

    def __init__(self, config: Optional[DCFConfig] = None) -> None:
        self.cfg = config or DCFConfig()

    # ------------------------------------------------------------------ #
    def value(self, data: CompanyData) -> ValuationResult:
        cfg = self.cfg
        result = ValuationResult(model=self.name, ticker=data.ticker)

        # --- 1. FCF history (oldest -> newest) -------------------------- #
        # periods are most-recent-first; reverse for a chronological series.
        fcf_series = [
            (p.fiscal_year, p.free_cash_flow)
            for p in reversed(data.periods)
            if p.free_cash_flow is not None
        ]
        if len(fcf_series) < 2:
            result.flags.append("Insufficient FCF history (<2 years); cannot run DCF")
            return result

        latest_fcf = fcf_series[-1][1]  # most recent
        if latest_fcf is None or latest_fcf <= 0:
            result.flags.append(
                "Not applicable: latest free cash flow is negative or zero")
            return result

        # Erratic FCF: negative in several years -> DCF unreliable.
        negatives = sum(1 for _, f in fcf_series if f is not None and f < 0)
        if negatives > len(fcf_series) / 2:
            result.flags.append(
                f"Not applicable: free cash flow was negative in {negatives} of "
                f"{len(fcf_series)} years (erratic)")
            return result

        # --- 1b. Robust base level --------------------------------------- #
        values = [f for _, f in fcf_series]
        positive_fcf = [f for f in values if f and f > 0]
        if cfg.normalize_base and positive_fcf:
            fcf0 = statistics.median(positive_fcf)   # robust to a one-off spike year
        else:
            fcf0 = latest_fcf

        # --- 2. Sustainable growth = MEDIAN of annual YoY growth rates ---- #
        # The median ignores a single one-off spike/trough (it can't move the
        # middle of N rates) WITHOUT flattening a consistent grower the way
        # damping every year to the median did. Then capped and faded.
        yoy = [values[i + 1] / values[i] - 1.0
               for i in range(len(values) - 1)
               if values[i] and values[i] > 0 and values[i + 1] is not None]
        if yoy:
            raw_growth = statistics.median(yoy)
            growth_method = f"median YoY FCF growth over {len(yoy)} yrs"
        else:
            raw_growth = cfg.terminal_growth
            growth_method = "fallback (insufficient FCF history)"
        applied_growth = max(cfg.growth_floor, min(cfg.growth_cap, raw_growth))
        growth_capped = applied_growth != raw_growth

        # Terminal growth tied to the firm's own trend, clamped to [0, cap]:
        # a flat/declining business does NOT grow at GDP forever.
        terminal_g = max(0.0, min(cfg.terminal_growth, applied_growth))

        # --- 3. WACC --------------------------------------------------- #
        wacc = self._compute_wacc(data)

        # --- 4. Base scenario + full audit ----------------------------- #
        base_scn = self._run_scenario(fcf0, applied_growth, wacc.wacc, data, terminal_g)
        if base_scn is None:
            result.flags.append("Could not bridge EV to equity (missing shares)")
            return result

        # --- 5. Bull / bear ------------------------------------------- #
        bull = self._run_scenario(
            fcf0, min(cfg.growth_cap, applied_growth + cfg.growth_delta),
            wacc.wacc - cfg.wacc_delta, data,
            max(0.0, min(cfg.terminal_growth, applied_growth + cfg.growth_delta)),
        )
        bear = self._run_scenario(
            fcf0, max(cfg.growth_floor, applied_growth - cfg.growth_delta),
            wacc.wacc + cfg.wacc_delta, data, terminal_g,
        )

        result.ok = True
        result.base = base_scn["per_share"]
        result.value_per_share = base_scn["per_share"]
        result.high = bull["per_share"] if bull else None
        result.low = bear["per_share"] if bear else None

        result.assumptions = {
            "risk_free_rate": cfg.risk_free_rate,
            "equity_risk_premium": cfg.equity_risk_premium,
            "terminal_growth": cfg.terminal_growth,
            "projection_years": cfg.projection_years,
            "growth_applied": applied_growth,
        }
        # --- 6. Reliability sanity checks ----------------------------- #
        ev = base_scn["enterprise_value"]
        terminal_share = base_scn["pv_terminal"] / ev if ev > 0 else 0.0
        market_ev = ((data.market_cap or 0.0) + (data.total_debt or 0.0)
                     - (data.cash_and_equivalents or 0.0))
        market_mult = market_ev / fcf0 if fcf0 > 0 else None
        dcf_mult = ev / fcf0 if fcf0 > 0 else None

        result.audit = {
            "fcf_history": fcf_series,
            "fcf0": fcf0,
            "growth": {
                "method": growth_method, "raw": raw_growth,
                "applied": applied_growth, "capped": growth_capped,
            },
            "terminal_growth_used": terminal_g,
            "wacc": wacc.__dict__,
            "base": base_scn,
            "terminal_share": terminal_share,
            "market_multiple": market_mult,
            "dcf_multiple": dcf_mult,
            "scenarios": {
                "bear": bear["per_share"] if bear else None,
                "base": base_scn["per_share"],
                "bull": bull["per_share"] if bull else None,
            },
        }
        if negatives >= 1:
            result.low_reliability = True
            result.flags.append(
                f"FCF was negative in {negatives} year(s) — treat with caution")
        if wacc.used_fallback:
            result.flags.append("WACC used 9% fallback (beta missing)")
        if growth_capped:
            result.flags.append(
                f"Growth capped from {raw_growth:.1%} to {applied_growth:.1%}")
        if terminal_share > cfg.max_terminal_share:
            result.low_reliability = True
            result.flags.append(
                f"Terminal value is {terminal_share:.0%} of DCF — fragile")
        if market_mult and dcf_mult and dcf_mult > market_mult * cfg.multiple_flag_ratio:
            result.low_reliability = True
            result.flags.append(
                f"DCF implies {dcf_mult:.0f}x FCF vs market's {market_mult:.0f}x")
        return result

    # ------------------------------------------------------------------ #
    def _compute_wacc(self, data: CompanyData) -> WaccBreakdown:
        cfg = self.cfg
        notes: List[str] = []

        # Tax rate from latest effective rate, else statutory default.
        tax_rate = cfg.default_tax_rate
        if data.latest and data.latest.effective_tax_rate is not None:
            etr = data.latest.effective_tax_rate
            if 0.0 <= etr <= 0.60:  # guard against odd one-off rates
                tax_rate = etr
            else:
                notes.append(f"effective tax rate {etr:.1%} out of band; used default")

        # Whole-WACC fallback when beta is missing (per spec).
        if data.beta is None:
            notes.append("beta missing -> fixed 9% WACC fallback")
            return WaccBreakdown(
                beta=None,
                risk_free_rate=cfg.risk_free_rate,
                equity_risk_premium=cfg.equity_risk_premium,
                cost_of_equity=cfg.wacc_fallback,
                cost_of_debt_pretax=0.0,
                cost_of_debt_aftertax=0.0,
                tax_rate=tax_rate,
                equity_value=data.market_cap or 0.0,
                debt_value=data.total_debt or 0.0,
                weight_equity=1.0,
                weight_debt=0.0,
                wacc=cfg.wacc_fallback,
                used_fallback=True,
                notes=notes,
            )

        beta = data.beta
        cost_of_equity = cfg.risk_free_rate + beta * cfg.equity_risk_premium
        if cost_of_equity < cfg.cost_of_equity_floor:
            notes.append(
                f"cost of equity {cost_of_equity:.1%} floored to "
                f"{cfg.cost_of_equity_floor:.1%}"
            )
            cost_of_equity = cfg.cost_of_equity_floor

        # Cost of debt: interest expense / total debt, else rf + spread.
        debt_value = data.total_debt or 0.0
        interest = data.latest.interest_expense if data.latest else None
        if interest and debt_value > 0 and interest > 0:
            cost_of_debt_pretax = interest / debt_value
        else:
            cost_of_debt_pretax = cfg.risk_free_rate + cfg.cost_of_debt_spread
            notes.append("cost of debt estimated as rf + spread (no usable interest)")
        cost_of_debt_aftertax = cost_of_debt_pretax * (1.0 - tax_rate)

        equity_value = data.market_cap or 0.0
        total_cap = equity_value + debt_value
        if total_cap <= 0:
            notes.append("no market cap/debt -> 100% equity weighting")
            weight_equity, weight_debt = 1.0, 0.0
        else:
            weight_equity = equity_value / total_cap
            weight_debt = debt_value / total_cap

        wacc = weight_equity * cost_of_equity + weight_debt * cost_of_debt_aftertax
        if wacc < cfg.wacc_floor:
            # Stops the "depressed price -> tiny equity weight -> ~5% WACC ->
            # looks cheap" circularity for heavily levered names.
            notes.append(f"WACC {wacc:.1%} floored to {cfg.wacc_floor:.1%}")
            wacc = cfg.wacc_floor
        return WaccBreakdown(
            beta=beta,
            risk_free_rate=cfg.risk_free_rate,
            equity_risk_premium=cfg.equity_risk_premium,
            cost_of_equity=cost_of_equity,
            cost_of_debt_pretax=cost_of_debt_pretax,
            cost_of_debt_aftertax=cost_of_debt_aftertax,
            tax_rate=tax_rate,
            equity_value=equity_value,
            debt_value=debt_value,
            weight_equity=weight_equity,
            weight_debt=weight_debt,
            wacc=wacc,
            used_fallback=False,
            notes=notes,
        )

    # ------------------------------------------------------------------ #
    def _run_scenario(
        self, fcf0: float, growth: float, wacc: float, data: CompanyData,
        terminal_g: float,
    ) -> Optional[dict]:
        """Project, discount, terminal, EV, and bridge to per-share."""
        cfg = self.cfg
        g = terminal_g
        # Keep WACC safely above terminal growth so the Gordon term is sane.
        wacc = max(wacc, g + cfg.min_wacc_spread)

        # Growth fades linearly from the initial (capped) rate g0 in year 1 to
        # the terminal rate by the final year -- a defensible glide path rather
        # than a constant high rate that cliffs into perpetuity.
        g0 = growth
        n = cfg.projection_years
        projection = []  # (year_index, growth_t, fcf, discount_factor, pv)
        fcf = fcf0
        sum_pv = 0.0
        for t in range(1, n + 1):
            if cfg.fade and n > 1:
                growth_t = g0 + (g - g0) * (t - 1) / (n - 1)
            else:
                growth_t = g0
            fcf = fcf * (1.0 + growth_t)
            factor = (1.0 + wacc) ** t
            pv = fcf / factor
            sum_pv += pv
            projection.append((t, growth_t, fcf, factor, pv))

        last_fcf = projection[-1][2]  # tuple: (t, growth_t, fcf, factor, pv)
        terminal_value = last_fcf * (1.0 + g) / (wacc - g)
        tv_factor = (1.0 + wacc) ** cfg.projection_years
        pv_terminal = terminal_value / tv_factor

        enterprise_value = sum_pv + pv_terminal

        shares = data.shares_outstanding
        if not shares or shares <= 0:
            return None
        total_debt = data.total_debt or 0.0
        cash = data.cash_and_equivalents or 0.0
        equity_value = enterprise_value - total_debt + cash
        per_share = equity_value / shares

        return {
            "growth": growth,
            "wacc": wacc,
            "terminal_growth": g,
            "projection": projection,
            "sum_pv_explicit": sum_pv,
            "terminal_value": terminal_value,
            "tv_discount_factor": tv_factor,
            "pv_terminal": pv_terminal,
            "enterprise_value": enterprise_value,
            "total_debt": total_debt,
            "cash": cash,
            "equity_value": equity_value,
            "shares": shares,
            "per_share": per_share,
        }
