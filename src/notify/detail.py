"""Per-stock detail blocks for the digest.

EVERYTHING here is computed deterministically from the model's own numbers and
the data we already pull -- no LLM free-writes reasons or risks at send time, so
the digest can't invent facts. A bullet is only emitted when its underlying
figure exists; otherwise it's omitted. News/litigation lines come verbatim from
a real source (Yahoo) with dates, or say so when none is wired/returned.
"""

from __future__ import annotations

import html
import statistics
from typing import List, Optional

from datetime import date

from src.data.provider import CompanyData
from src.models.base import ValuationResult
from src.models.comps import CompsModel
from src.valuation.blender import BlendResult

# yfinance sector names -> recession-sensitivity heuristic
_DEFENSIVE = {"Consumer Defensive", "Healthcare", "Utilities"}
_CYCLICAL = {"Consumer Cyclical", "Industrials", "Basic Materials", "Energy"}

_LITIGATION_WORDS = (
    "lawsuit", "sue", "sued", "litigation", "sec ", "probe", "investigation",
    "settlement", "fraud", "antitrust", "recall", "subpoena", "charges",
)


def _b(x: Optional[float]) -> str:
    """Dollars -> $X.XB / $X.XM / $X."""
    if x is None:
        return "n/a"
    a = abs(x)
    if a >= 1e9:
        return f"${x/1e9:.1f}B"
    if a >= 1e6:
        return f"${x/1e6:.1f}M"
    return f"${x:,.0f}"


def _pct(x: Optional[float], signed: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x*100:+.0f}%" if signed else f"{x*100:.0f}%"


def _peer_medians(comps: Optional[ValuationResult]):
    if not comps or not comps.audit:
        return None, None, None
    m = comps.audit.get("multiples", {})
    g = lambda k: (m.get(k) or {}).get("median")
    return g("pe"), g("ev_ebitda"), g("pb")


def _fcf_cagr(data: CompanyData):
    fcf = [p.free_cash_flow for p in reversed(data.periods) if p.free_cash_flow]
    if len(fcf) < 2 or fcf[0] <= 0:
        return None, len(fcf)
    return (fcf[-1] / fcf[0]) ** (1.0 / (len(fcf) - 1)) - 1.0, len(fcf)


def build_stock_block(
    blend: BlendResult,
    data: CompanyData,
    comps: Optional[ValuationResult] = None,
    news: Optional[List[dict]] = None,
) -> str:
    latest = data.latest
    price, iv, mos = blend.price, blend.intrinsic_value, blend.margin_of_safety
    name = html.escape(blend.company_name or data.company_name or "")
    mv = blend.model_values

    # ---- derived figures (all may be None) ---- #
    revenue = latest.revenue if latest else None
    prev_rev = data.periods[1].revenue if len(data.periods) > 1 else None
    rev_yoy = (revenue / prev_rev - 1) if (revenue and prev_rev and prev_rev > 0) else None
    ni = latest.net_income if latest else None
    net_margin = (ni / revenue) if (ni is not None and revenue) else None
    cagr, n_fcf = _fcf_cagr(data)

    total_debt = data.total_debt
    cash = data.cash_and_equivalents
    net_debt = data.net_debt
    if net_debt is None and total_debt is not None:
        net_debt = total_debt - (cash or 0.0)
    equity = data.total_equity
    d_to_e = (total_debt / equity) if (total_debt is not None and equity and equity > 0) else None
    ebitda = latest.ebitda if latest else None
    nd_ebitda = (net_debt / ebitda) if (net_debt and ebitda and ebitda > 0) else None

    eps = latest.eps_diluted if latest else None
    target_pe = (price / eps) if (price and eps and eps > 0) else None
    peer_pe, peer_ev, peer_pb = _peer_medians(comps)

    # ---- WHY IT SCREENS (facts, only if backed by a number) ---- #
    why: List[str] = []
    if iv and mos is not None:
        why.append(f"💰 ${price:,.2f} vs intrinsic ${iv:,.2f} — {_pct(mos)} margin of safety")
    models = f"DCF ${mv['DCF']:,.0f}" if mv.get("DCF") else "DCF n/a"
    models += f" · DDM ${mv['DDM']:,.0f}" if mv.get("DDM") else " · DDM n/a"
    models += f" · Comps ${mv['Comps']:,.0f}" if mv.get("Comps") else " · Comps n/a"
    why.append(f"📊 {blend.confidence} confidence ({blend.n_models} models): {models}")
    if cagr is not None:
        verb = "grew" if cagr >= 0 else "declined"
        why.append(f"📈 Free cash flow {verb} {_pct(cagr, signed=True)}/yr over {n_fcf}y")
    if net_margin is not None:
        why.append(f"🏭 Net margin {_pct(net_margin)} on {_b(revenue)} revenue")
    if net_debt is not None:
        if net_debt < 0:
            why.append(f"🏦 Net cash {_b(-net_debt)} (more cash than debt)")
        else:
            lev = f", {nd_ebitda:.1f}× EBITDA" if nd_ebitda is not None else ""
            why.append(f"🏦 Net debt {_b(net_debt)}{lev}")
    if target_pe is not None and peer_pe is not None:
        why.append(f"🏷️ P/E {target_pe:.1f} vs peer median {peer_pe:.1f}")

    # ---- KEY STATS ---- #
    stats = (
        f"📌 Beta {data.beta:.2f}" if data.beta is not None else "📌 Beta n/a"
    )
    stats += f" · Rev {_b(revenue)}"
    if rev_yoy is not None:
        stats += f" ({_pct(rev_yoy, signed=True)} YoY)"
    stats += f" · Cash {_b(cash)} vs Debt {_b(total_debt)}"
    if net_debt is not None:
        stats += (f" (net cash {_b(-net_debt)})" if net_debt < 0
                  else f" (net debt {_b(net_debt)})")
    stats += f" · Mkt cap {_b(data.market_cap)}"
    if target_pe is not None:
        stats += f" · P/E {target_pe:.1f}"
        if peer_pe is not None:
            stats += f" (peers {peer_pe:.1f})"

    # ---- RISKS (data-driven) ---- #
    risks: List[str] = []
    for f in blend.quality_flags:  # already-computed trap markers
        risks.append(f"flagged: {f}")
    if d_to_e is not None and d_to_e > 1.0:
        risks.append(f"leverage debt/equity {d_to_e:.1f}×")
    if data.beta is not None and data.beta >= 1.3:
        risks.append(f"high volatility (beta {data.beta:.2f})")
    elif data.beta is not None and data.beta <= 0.8:
        risks.append(f"defensive (beta {data.beta:.2f})")
    # recession sensitivity heuristic from sector + balance sheet
    sec = data.sector or ""
    if sec in _DEFENSIVE:
        rec = "lower (defensive sector)"
    elif sec in _CYCLICAL:
        rec = "higher (cyclical sector)"
    else:
        rec = "moderate"
    if net_debt is not None and net_debt < 0:
        rec += " + net cash adds resilience"
    risks.append(f"recession sensitivity {rec} [heuristic]")
    # Spread across the three model values: wide disagreement = lower confidence.
    vals = [v for v in mv.values() if v]
    if len(vals) >= 2:
        mean = statistics.fmean(vals)
        cv = (statistics.pstdev(vals) / mean) if mean else 0.0
        label = "wide" if cv > 0.40 else ("moderate" if cv > 0.20 else "tight")
        conf = "lower" if label != "tight" else "higher"
        risks.append(f"{label} spread across {len(vals)} models ({_pct(cv)}) "
                     f"→ {conf} confidence")

    # ---- NEWS / LITIGATION (verbatim from real source, or explicit none) ---- #
    news_lines: List[str] = []
    if news:
        for item in news[:2]:
            t = html.escape(item.get("title", ""))
            flag = "⚠️ " if any(w in (item.get("title", "").lower())
                                for w in _LITIGATION_WORDS) else ""
            meta = " · ".join(x for x in (item.get("publisher"), item.get("date")) if x)
            news_lines.append(f"   {flag}{t} <i>({html.escape(meta)})</i>")
        news_block = "📰 Recent news (not a full legal check):\n" + "\n".join(news_lines)
    elif news is None:
        # No news source wired into this provider.
        news_block = "📰 no litigation/news check wired in"
    else:
        # Source wired, but nothing recent returned.
        news_block = "📰 No recent news returned (source wired) — not a full legal check."

    # ---- assemble ---- #
    parts = [f"<b>{blend.ticker} — {name}</b>"]
    parts.append("\n".join(why))
    if blend.profile_lines:
        parts.append("✅ Profile fit:\n" + "\n".join("   " + html.escape(p)
                                                     for p in blend.profile_lines))
    parts.append(stats)
    parts.append("⚠️ Risks: " + "; ".join(risks))
    parts.append(news_block)
    return "\n".join(parts)


def build_digest_messages(top, provider, universe, as_of=None,
                          title="Quality on a Dip"):
    """Header + one richly-detailed message per stock (keeps each under Telegram's
    length limit). Fetches cached data and runs Comps for peer medians + news."""
    as_of = as_of or date.today().isoformat()
    if not top:
        return [
            f"<b>🟢 Nothing today</b>\n<i>{as_of}</i>\n\n"
            "No quality-on-a-dip setups right now — no strong company pulled back "
            "on sentiment while staying at/below fair value. (Screen ran fine.)"
        ]
    header = (
        f"<b>📉 Top {len(top)} {title}</b>\n"
        f"<i>as of {as_of} · strong fundamentals, recently pulled back, ≤ fair value</i>"
    )

    messages = [header]
    comps_model = CompsModel(provider, universe)
    for b in top:
        data = provider.get_company_data(b.ticker)
        comps = comps_model.value(data)
        news = provider.get_news(b.ticker) if hasattr(provider, "get_news") else None
        messages.append(build_stock_block(b, data, comps, news))
    messages.append(
        "<i>Mechanical model output — not investment advice or legal due diligence.</i>"
    )
    return messages
