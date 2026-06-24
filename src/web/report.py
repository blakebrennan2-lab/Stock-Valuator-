"""Render each model's audit into compact HTML for the web report.

Reads the same `ValuationResult.audit` dicts the console runners print, so the
web report shows the identical "work" — projections, WACC, terminal value,
peer multiples — nothing re-derived or invented.
"""

from __future__ import annotations

from typing import Optional

from src.models.base import ValuationResult


def _m(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    a = abs(x)
    if a >= 1e9:
        return f"${x/1e9:,.1f}B"
    if a >= 1e6:
        return f"${x/1e6:,.1f}M"
    return f"${x:,.2f}"


def _pct(x: Optional[float], signed=False) -> str:
    if x is None:
        return "n/a"
    return f"{x*100:+.1f}%" if signed else f"{x*100:.1f}%"


def _na(res: Optional[ValuationResult], label: str) -> str:
    flags = "; ".join(res.flags) if (res and res.flags) else "not available"
    return f"<p class='na'><b>{label}:</b> {flags}</p>"


def render_dcf(res: Optional[ValuationResult]) -> str:
    if not res or not res.ok:
        return _na(res, "DCF")
    a, w, b = res.audit, res.audit["wacc"], res.audit["base"]
    rows = "".join(
        f"<tr><td>Y{t}</td><td>{_pct(g)}</td><td>{_m(fcf)}</td>"
        f"<td>{factor:.3f}</td><td>{_m(pv)}</td></tr>"
        for t, g, fcf, factor, pv in b["projection"]
    )
    return f"""
<h4>DCF — discounted free cash flow</h4>
<p>Base FCF (median of history): <b>{_m(a['fcf0'])}</b> ·
   growth applied <b>{_pct(a['growth']['applied'])}</b> (fades to terminal)</p>
<table><tr><th>WACC build</th><th></th></tr>
<tr><td>Beta</td><td>{w['beta']}</td></tr>
<tr><td>Risk-free + β·ERP</td><td>{_pct(w['cost_of_equity'])} cost of equity</td></tr>
<tr><td>After-tax cost of debt</td><td>{_pct(w['cost_of_debt_aftertax'])}</td></tr>
<tr><td>Weights (E/D)</td><td>{_pct(w['weight_equity'])} / {_pct(w['weight_debt'])}</td></tr>
<tr><td><b>WACC</b></td><td><b>{_pct(w['wacc'])}</b></td></tr></table>
<table><tr><th>Yr</th><th>Growth</th><th>Proj FCF</th><th>Disc</th><th>PV</th></tr>
{rows}</table>
<p>Sum of PV (explicit): <b>{_m(b['sum_pv_explicit'])}</b> ·
   terminal value <b>{_m(b['terminal_value'])}</b> →
   PV <b>{_m(b['pv_terminal'])}</b></p>
<p>Enterprise value <b>{_m(b['enterprise_value'])}</b> − debt {_m(b['total_debt'])}
   + cash {_m(b['cash'])} = equity <b>{_m(b['equity_value'])}</b><br>
   ÷ {b['shares']/1e6:,.0f}M shares = <b>${b['per_share']:,.2f}/share</b></p>
"""


def render_ddm(res: Optional[ValuationResult]) -> str:
    if not res or not res.ok:
        return _na(res, "DDM")
    a, ts = res.audit, res.audit["two_stage"]
    rows = "".join(
        f"<tr><td>Y{t}</td><td>${div:,.4f}</td><td>{factor:.3f}</td>"
        f"<td>${pv:,.4f}</td></tr>"
        for t, div, factor, pv in ts["stage1"]
    )
    return f"""
<h4>DDM — dividend discount</h4>
<p>Latest dividend <b>${a['d0']:,.4f}</b> · growth <b>{_pct(a['growth']['applied'])}</b>
   · discount rate <b>{_pct(a['discount_rate_used'])}</b></p>
<table><tr><th>Yr</th><th>Dividend</th><th>Disc</th><th>PV</th></tr>{rows}</table>
<p>Stage-1 PV <b>${ts['sum_pv_stage1']:,.2f}</b> · terminal value
   <b>${ts['terminal_value']:,.2f}</b> → PV <b>${ts['pv_terminal']:,.2f}</b></p>
<p>Two-stage value <b>${ts['value']:,.2f}/share</b>
   (single-stage Gordon ref: ${a['gordon']['value']:,.2f})</p>
"""


def render_comps(res: Optional[ValuationResult]) -> str:
    if not res or not res.ok:
        return _na(res, "Comps")
    a = res.audit
    prows = ""
    for p in a["peers"]:
        pe = f"{p['pe']:.1f}x" if p.get("pe") else "–"
        ev = f"{p['ev_ebitda']:.1f}x" if p.get("ev_ebitda") else "–"
        pb = f"{p['pb']:.1f}x" if p.get("pb") else "–"
        nm = p.get("name") or ""
        prows += (f"<tr><td>{p['symbol']}<div class='peernm'>{nm}</div></td>"
                  f"<td>{pe}</td><td>{ev}</td><td>{pb}</td></tr>")
    m = a["multiples"]

    def med(key):
        info = m.get(key, {})
        return (f"{info['median']:.1f}x → <b>${info['implied']:,.2f}</b>"
                if "implied" in info else "dropped")
    impl = " · ".join(f"{k} ${v:,.0f}" for k, v in a["implied_by_method"].items())
    basis = a.get("basis", "")
    peer_list = ", ".join(p["symbol"] for p in a["peers"])
    return f"""
<h4>Comps — peer multiples</h4>
<p>Peers used ({len(a['peers'])}): <b>{peer_list}</b><br>
   Basis: {basis}</p>
<table><tr><th>Peer</th><th>P/E</th><th>EV/EBITDA</th><th>P/B</th></tr>{prows}</table>
<p>Median P/E: {med('pe')}<br>
   Median EV/EBITDA: {med('ev_ebitda')}<br>
   Median P/B: {med('pb')}</p>
<p>Implied by method: {impl}<br>
   Reconciled (median): <b>${a['reconciled_median']:,.2f}/share</b></p>
"""
