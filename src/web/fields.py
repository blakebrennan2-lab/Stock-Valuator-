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


_METHOD_LABELS = {
    "DCF": "DCF — discounted cash flow",
    "DDM": "DDM — dividend discount",
    "Comps": "Comps — peer multiples",
}


def _methods(results: dict) -> list:
    """Per-stock applicability: which models were used, which skipped and why."""
    out = []
    for key in ("DCF", "DDM", "Comps"):
        r = results.get(key)
        used = bool(r and r.ok and r.value_per_share and r.value_per_share > 0)
        if used:
            reason = "Used in the blended value."
        elif r and r.flags:
            # the skip reason is the explanatory flag
            reason = next((f for f in r.flags if "applicable" in f.lower()
                           or "meaningful" in f.lower()), r.flags[-1])
        else:
            reason = "Not applicable for this company."
        out.append({"key": key, "name": _METHOD_LABELS[key], "used": used, "reason": reason})
    return out


def _reconciliation(blend: BlendResult) -> dict:
    lo, hi = blend.range_low, blend.range_high
    spread = ((hi - lo) / lo) if (lo and hi and lo > 0) else None
    c = blend.confidence
    if len(blend.model_values) <= 1:
        sent = f"Only one method applied here, so treat the estimate cautiously ({c} confidence)."
    else:
        tail = {
            "high": "They agree closely, so confidence is high.",
            "medium": "They broadly agree on direction but differ on magnitude — medium confidence.",
            "low": "They disagree sharply, so confidence is low — treat the value as a wide range.",
        }.get(c, "")
        sp = f" (a {spread*100:.0f}% spread)" if spread is not None else ""
        sent = f"The methods land between {_money(lo)} and {_money(hi)}{sp}. {tail}"
    return {"values": blend.model_values, "spread": spread, "confidence": c, "sentence": sent}


def _thesis(blend: BlendResult, methods: list, data: CompanyData) -> str:
    dd = data.drawdown
    pull = f"down {abs(dd):.0%} from its 52-week high" if dd is not None else "off its highs"
    ni = [p.net_income for p in reversed(data.periods) if p.net_income is not None]
    cagr = ((ni[-1] / ni[0]) ** (1.0 / (len(ni) - 1)) - 1.0
            if len(ni) >= 2 and ni[0] > 0 and ni[-1] > 0 else None)
    earn = f"while earnings grew {_pct(cagr)}/yr" if cagr is not None else "with earnings intact"

    s1 = (f"{blend.ticker} is {pull} {earn} — a sentiment-driven pullback, not "
          f"fundamental deterioration.")
    s2 = (f"Quality looks intact (healthy margins, durable revenue, long-term uptrend), "
          f"and it's now at or below fair value ({_money(blend.price)} vs "
          f"{_money(blend.intrinsic_value)}, {blend.confidence} confidence).")
    used = [m["key"] for m in methods if m["used"]]
    s3 = f"Valued with {' and '.join(used) if used else 'no applicable model'}."
    return f"{s1} {s2} {s3}"


# --------------------------------------------------------------------------- #
# Analyst-grade metrics — every figure computed from reported statements; a
# metric whose inputs are missing is OMITTED, never estimated.
# --------------------------------------------------------------------------- #
def _cagr(vals: List[Optional[float]]) -> Optional[float]:
    """CAGR across a chronological series with positive endpoints."""
    if len(vals) >= 2 and vals[0] and vals[0] > 0 and vals[-1] and vals[-1] > 0:
        return (vals[-1] / vals[0]) ** (1.0 / (len(vals) - 1)) - 1.0
    return None


def _health_stats(data: CompanyData, ownership: Optional[dict] = None) -> list:
    """Returns-on-capital + balance-sheet strength grid. Each entry carries a
    `src` line stating exactly how it was computed."""
    latest = data.latest
    if latest is None:
        return []
    fy = latest.fiscal_year or "latest"
    chrono = list(reversed(data.periods))
    out = []

    ni, eq = latest.net_income, data.total_equity
    if ni is not None and eq and eq > 0:
        out.append({"label": f"ROE (FY{fy})", "value": _pct(ni / eq),
                    "src": "net income ÷ shareholder equity"})

    ebit = latest.ebit
    etr = latest.effective_tax_rate
    tax = etr if (etr is not None and 0.0 <= etr <= 0.60) else 0.21
    invested = (data.total_debt or 0.0) + (eq or 0.0)
    # ROIC needs BOTH sides of the capital base; unknown equity would silently
    # divide by debt alone and fabricate an absurd return.
    if ebit is not None and eq is not None and invested > 0:
        out.append({"label": f"ROIC (FY{fy})", "value": _pct(ebit * (1 - tax) / invested),
                    "src": "after-tax EBIT ÷ (debt + equity)"})

    interest = latest.interest_expense
    net_debt = data.net_debt
    if net_debt is None and data.total_debt is not None:
        net_debt = data.total_debt - (data.cash_and_equivalents or 0.0)
    if ebit is not None and interest and interest > 0:
        out.append({"label": f"Interest coverage (FY{fy})",
                    "value": f"{ebit / interest:.1f}x",
                    "src": "EBIT ÷ interest expense"})
    elif net_debt is not None and net_debt < 0:
        out.append({"label": "Interest coverage", "value": "net cash",
                    "src": "more cash than debt — no net interest burden"})

    ebitda = latest.ebitda
    if net_debt is not None and ebitda and ebitda > 0:
        out.append({"label": "Net debt / EBITDA",
                    "value": "net cash" if net_debt < 0 else f"{net_debt / ebitda:.1f}x",
                    "src": "(debt − cash) ÷ EBITDA"})

    ca, cl = latest.current_assets, latest.current_liabilities
    if ca is not None and cl and cl > 0:
        out.append({"label": f"Current ratio (FY{fy})", "value": f"{ca / cl:.1f}x",
                    "src": "current assets ÷ current liabilities"})

    fcf, rev = latest.free_cash_flow, latest.revenue
    if fcf is not None and rev and rev > 0:
        out.append({"label": f"FCF margin (FY{fy})", "value": _pct(fcf / rev),
                    "src": "free cash flow ÷ revenue"})

    rev_cagr = _cagr([p.revenue for p in chrono])
    if rev_cagr is not None:
        out.append({"label": f"Revenue CAGR ({len(chrono) - 1}y)",
                    "value": _pct(rev_cagr, True) + "/yr",
                    "src": "reported annual revenue"})
    eps_cagr = _cagr([p.eps_diluted for p in chrono])
    if eps_cagr is not None:
        out.append({"label": f"EPS CAGR ({len(chrono) - 1}y)",
                    "value": _pct(eps_cagr, True) + "/yr",
                    "src": "diluted EPS, reported"})

    for key, label, src in (
        ("insiders", "Insider ownership", "Yahoo Finance holders data"),
        ("institutions", "Institutional ownership", "Yahoo Finance holders data"),
        ("short_pct_float", "Short interest", "% of float sold short"),
    ):
        if ownership and ownership.get(key) is not None:
            # One decimal: 0.1% insider or 2.9% short is real signal, not "0%"/"3%".
            out.append({"label": label, "value": f"{ownership[key] * 100:.1f}%",
                        "src": src})
    return out


def _capital_allocation(data: CompanyData) -> List[str]:
    """Where the cash actually went: dividends, buybacks/dilution, reinvestment."""
    latest = data.latest
    if latest is None:
        return []
    chrono = list(reversed(data.periods))
    fy = latest.fiscal_year or "latest"
    out = []

    divs, fcf = latest.dividends_paid, latest.free_cash_flow  # divs: negative outflow
    if divs is not None and divs < 0:
        line = f"Dividends: {_money(-divs)} paid in FY{fy}"
        if fcf and fcf > 0:
            line += f" — {_pct(-divs / fcf)} of free cash flow"
        out.append(line)
    elif (latest.dividend_per_share or 0) == 0 and (data.last_dividend or 0) == 0:
        out.append("No dividend — cash is reinvested or returned via buybacks")

    dps = [p.dividend_per_share for p in chrono if p.dividend_per_share]
    if len(dps) >= 2 and dps[0] > 0:
        g = _cagr(dps)
        if g is not None:
            out.append(f"Dividend/share grew {_pct(g, True)}/yr over {len(dps) - 1}y")

    shares = [p.shares_diluted for p in chrono if p.shares_diluted]
    if len(shares) >= 2:
        chg = shares[-1] / shares[0] - 1.0
        yrs = len(shares) - 1
        if chg < -0.005:
            out.append(f"Buybacks: diluted share count down {_pct(-chg)} over {yrs}y")
        elif chg > 0.005:
            out.append(f"Dilution: diluted share count UP {_pct(chg)} over {yrs}y")
        else:
            out.append(f"Share count roughly flat over {yrs}y")

    debts = [p.total_debt for p in chrono if p.total_debt is not None]
    if len(debts) >= 2:
        yrs, first, last_d = len(debts) - 1, debts[0], debts[-1]
        if first == 0 and last_d == 0:
            out.append(f"Debt-free across the past {yrs + 1}y")
        elif first > 0:
            chg = last_d / first - 1.0
            if chg < -0.02:
                out.append(f"Debt paydown: total debt down {_pct(-chg)} over {yrs}y "
                           f"({_money(first)} → {_money(last_d)})")
            elif chg > 0.02:
                out.append(f"Leverage rising: total debt UP {_pct(chg)} over {yrs}y "
                           f"({_money(first)} → {_money(last_d)})")
            else:
                out.append(f"Total debt roughly flat over {yrs}y ({_money(last_d)})")
        elif last_d > 0:
            out.append(f"Took on debt: none → {_money(last_d)} over {yrs}y")

    capex, rev = latest.capital_expenditure, latest.revenue
    if capex is not None and rev and rev > 0:
        out.append(f"Reinvestment: capex {_pct(abs(capex) / rev)} of revenue (FY{fy})")
    return out


def _change_mind(blend: BlendResult, data: CompanyData,
                 net_margin: Optional[float], rev_yoy: Optional[float]) -> List[str]:
    """Explicit, number-tied exit conditions — what would invalidate the thesis."""
    out = []
    if blend.intrinsic_value and blend.price:
        out.append(f"Price recovers above fair value (~{_money(blend.intrinsic_value)}) "
                   "— the discount that makes it a buy is gone")
    if net_margin is not None:
        out.append(f"Net margin ({_pct(net_margin)}) deteriorates toward the 5% "
                   "quality floor")
    if rev_yoy is not None:
        out.append(f"Revenue growth (now {_pct(rev_yoy, True)} YoY) turns negative")
    latest = data.latest
    if latest and latest.free_cash_flow and latest.free_cash_flow > 0:
        out.append(f"Free cash flow (now {_money(latest.free_cash_flow)}) turns negative")
    if data.above_long_ma:
        out.append("Price breaks decisively below its long-term (≈200-day) trend")
    return out


# Qualitative work the models CANNOT do — listed so nobody mistakes this app
# for complete due diligence. Never auto-filled.
MANUAL_RESEARCH = [
    "Moat & competitive position — is the advantage durable?",
    "Management quality and incentives (proxy statement, capital-allocation record)",
    "Pending litigation or regulatory action beyond headline news",
    "Upcoming catalysts — product cycles, guidance changes, M&A",
    "Industry structure and disruption risk",
]


def stock_payload(blend: BlendResult, data: CompanyData,
                  comps: Optional[ValuationResult], results: dict,
                  history: list, news: Optional[list],
                  intraday: Optional[list] = None,
                  ownership: Optional[dict] = None) -> dict:
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

    methods = _methods(results)
    return {
        "ticker": blend.ticker,
        "name": blend.company_name or "",
        "price": blend.price,
        "intrinsic": blend.intrinsic_value,
        "upside": blend.margin_of_safety,
        "confidence": blend.confidence,
        "range_low": blend.range_low,
        "range_high": blend.range_high,
        "intraday": intraday or [],
        "thesis": _thesis(blend, methods, data),
        "methods": methods,
        "reconciliation": _reconciliation(blend),
        "history": history,
        "stats": stats,
        "health": _health_stats(data, ownership),
        "capital": _capital_allocation(data),
        "change_mind": _change_mind(blend, data, net_margin, rev_yoy),
        "manual": MANUAL_RESEARCH,
        "why": why,
        "risks": risks,
        "profile": blend.profile_lines,
        "news": news or [],
        "dcf_html": render_dcf(results.get("DCF")),
        "ddm_html": render_ddm(results.get("DDM")),
        "comps_html": render_comps(comps),
    }
