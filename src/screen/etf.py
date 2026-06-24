"""ETF dip-screen: quality funds on a pullback within a long-term uptrend.

No fundamentals/DCF (a fund has no earnings) — purely trend + drawdown. Builds
the same chart/stats payload shape the web app uses for stocks, minus the
valuation models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config.etfs import ETF_UNIVERSE


@dataclass
class ETFConfig:
    min_pullback: float = 0.07     # down at least 7% from the 52-week high
    max_pullback: float = 0.40     # but not a >40% collapse
    require_uptrend: bool = True    # long-term uptrend (3y & 5y positive, or > long MA)
    top_n: int = 5


def _pct(x: Optional[float], signed=False) -> str:
    if x is None:
        return "—"
    return f"{x*100:+.0f}%" if signed else f"{x*100:.0f}%"


def _qualifies(data, cfg: ETFConfig):
    r3, r5, above = data.return_3y, data.return_5y, data.above_long_ma
    uptrend = (r3 is not None and r3 > 0 and r5 is not None and r5 > 0) or (above is True)
    dd = data.drawdown
    pullback = dd is not None and -cfg.max_pullback <= dd <= -cfg.min_pullback
    return (not cfg.require_uptrend or uptrend) and pullback, uptrend


def build_etf_payloads(provider, cfg: Optional[ETFConfig] = None) -> list:
    cfg = cfg or ETFConfig()
    out = []
    for ticker, name, category in ETF_UNIVERSE:
        try:
            data = provider.get_company_data(ticker)
        except Exception:
            continue
        if not data.price or data.drawdown is None:
            continue
        ok, uptrend = _qualifies(data, cfg)
        if not ok:
            continue
        dd = data.drawdown
        thesis = (f"{name} is down {abs(dd):.0%} from its 52-week high but is still in "
                  f"a long-term uptrend (3y {_pct(data.return_3y, True)}, "
                  f"5y {_pct(data.return_5y, True)}) — a pullback on a quality "
                  f"{category} fund, not a breakdown. (Funds are screened on trend + "
                  f"dip, not DCF — an ETF has no earnings.)")
        stats = [
            {"label": "Down from high", "value": _pct(dd)},
            {"label": "52-wk high", "value": f"${data.high_52w:,.2f}" if data.high_52w else "—"},
            {"label": "3-yr return", "value": _pct(data.return_3y, True)},
            {"label": "5-yr return", "value": _pct(data.return_5y, True)},
            {"label": "Category", "value": category},
            {"label": "Beta", "value": f"{data.beta:.2f}" if data.beta is not None else "—"},
        ]
        out.append({
            "ticker": ticker, "name": name, "category": category, "is_etf": True,
            "price": data.price, "drawdown": dd, "thesis": thesis, "stats": stats,
            "history": provider.get_price_history(ticker)
            if hasattr(provider, "get_price_history") else [],
            "intraday": provider.get_intraday(ticker)
            if hasattr(provider, "get_intraday") else {},
        })
    out.sort(key=lambda e: e["drawdown"])          # biggest pullback (most "on sale") first
    return out[: cfg.top_n]
