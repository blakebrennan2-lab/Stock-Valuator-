"""Structured per-pick data for the redesigned web UI.

All values computed from the model's own numbers (same helpers the Telegram
block uses) so the app renders a clean native layout instead of a wall of text —
without inventing anything.
"""

from __future__ import annotations

import statistics
from typing import List, Optional

from src.data.provider import CompanyData
from src.models.base import ValuationResult
from src.notify.detail import _DEFENSIVE, _CYCLICAL, _fcf_cagr, _peer_medians
from src.valuation.blender import BlendResult
from src.web.report import render_comps, render_dcf, render_ddm


def _money(x: Optional[float]) -> str:
    if x is None:
        return "—"
    a = abs(x)
    if a >= 1e12:
        return f"${x/1e12:.2f}T"
    if a >= 1e9:
        return f"${x/1e9:.1f}B"
    if a >= 1e6:
        return f"${x/1e6:.1f}M"
    return f"${x:,.2f}"


def _pct(x: Optional[float], signed=False) -> str:
    if x is None:
        return "—"
    return f"{x*100:+.0f}%" if signed else f"{x*100:.0f}%"


def stock_payload(blend: BlendResult, data: CompanyData,
                  comps: Optional[ValuationResult], results: dict,
                  history: list, news: Optional[list]) -> dict:
    latest = data.latest
    revenue = latest.revenue if latest else None
    prev_rev = data.periods[1].revenue if len(data.periods) > 1 else None
    rev_yoy = (revenue / prev_rev - 1) if (revenue and prev_rev and prev_rev > 0) else None
    ni = latest.net_income if latest else None
    net_margin = (ni / revenue) if (ni is not None and revenue) else None
    cagr, n_fcf = _fcf_cagr(data)

    total_debt, cash = data.total_debt, data.cash_and_equivalents
    net_debt = data.net_debt
    if net_debt is None and total_debt is not None:
        net_debt = total_debt - (cash or 0.0)
    equity = data.total_equity
    d_to_e = (total_debt / equity) if (total_debt is not None and equity and equity > 0) else None
    ebitda = latest.ebitda if latest else None
    nd_ebitda = (net_debt / ebitda) if (net_debt and ebitda and ebitda > 0) else None
    eps = latest.eps_diluted if latest else None
    pe = (blend.price / eps) if (blend.price and eps and eps > 0) else None
    peer_pe, _, _ = _peer_medians(comps)

    # --- key-stats grid (label, value) ---
    stats = [
        {"label": "Beta", "value": f"{data.beta:.2f}" if data.beta is not None else "—"},
        {"label": "Revenue", "value": _money(revenue)
         + (f"  ({_pct(rev_yoy, True)} YoY)" if rev_yoy is not None else "")},
        {"label": "Net margin", "value": _pct(net_margin) if net_margin is not None else "—"},
        {"label": "FCF growth", "value": _pct(cagr, True) + "/yr" if cagr is not None else "—"},
        {"label": "Market cap", "value": _money(data.market_cap)},
        {"label": "P/E", "value": (f"{pe:.1f}" if pe is not None else "—")
         + (f"  (peers {peer_pe:.1f})" if (pe and peer_pe) else "")},
        {"label": "Cash vs debt",
         "value": (f"net cash {_money(-net_debt)}" if (net_debt is not None and net_debt < 0)
                   else f"net debt {_money(net_debt)}" if net_debt is not None else "—")},
        {"label": "Debt/Equity", "value": f"{d_to_e:.1f}x" if d_to_e is not None else "—"},
    ]

    # --- why bullets ---
    why = [f"{_pct(blend.margin_of_safety)} below intrinsic value "
           f"({_money(blend.price)} vs {_money(blend.intrinsic_value)})"]
    mv = blend.model_values
    agree = ", ".join(f"{k} {_money(v)}" for k, v in mv.items())
    why.append(f"{blend.confidence} confidence across {blend.n_models} models — {agree}")
    if cagr is not None:
        why.append(f"Free cash flow {'grew' if cagr >= 0 else 'declined'} "
                   f"{_pct(cagr, True)}/yr over {n_fcf}y")
    if net_margin is not None:
        why.append(f"Net margin {_pct(net_margin)} on {_money(revenue)} revenue")
    if net_debt is not None:
        why.append(f"Net cash {_money(-net_debt)}" if net_debt < 0
                   else f"Net debt {_money(net_debt)}"
                   + (f" ({nd_ebitda:.1f}x EBITDA)" if nd_ebitda is not None else ""))
    if pe is not None and peer_pe is not None:
        why.append(f"P/E {pe:.1f} vs peer median {peer_pe:.1f}")

    # --- risks ---
    risks = list(blend.quality_flags)
    if d_to_e is not None and d_to_e > 1.0:
        risks.append(f"Leverage: debt/equity {d_to_e:.1f}x")
    if data.beta is not None and data.beta >= 1.3:
        risks.append(f"Volatile: beta {data.beta:.2f}")
    elif data.beta is not None and data.beta <= 0.8:
        risks.append(f"Defensive: beta {data.beta:.2f}")
    sec = data.sector or ""
    rec = ("lower (defensive sector)" if sec in _DEFENSIVE else
           "higher (cyclical sector)" if sec in _CYCLICAL else "moderate")
    if net_debt is not None and net_debt < 0:
        rec += " + net cash adds resilience"
    risks.append(f"Recession sensitivity {rec} [heuristic]")
    vals = [v for v in mv.values() if v]
    if len(vals) >= 2:
        cv = statistics.pstdev(vals) / statistics.fmean(vals)
        label = "wide" if cv > 0.4 else ("moderate" if cv > 0.2 else "tight")
        risks.append(f"Model spread {label} ({_pct(cv)}) — "
                     f"{'lower' if label != 'tight' else 'higher'} confidence")

    return {
        "ticker": blend.ticker,
        "name": blend.company_name or "",
        "price": blend.price,
        "intrinsic": blend.intrinsic_value,
        "upside": blend.margin_of_safety,
        "confidence": blend.confidence,
        "history": history,
        "stats": stats,
        "why": why,
        "risks": risks,
        "profile": blend.profile_lines,
        "news": news or [],
        "dcf_html": render_dcf(results.get("DCF")),
        "ddm_html": render_ddm(results.get("DDM")),
        "comps_html": render_comps(comps),
    }
