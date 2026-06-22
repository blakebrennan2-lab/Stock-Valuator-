"""Quality-compounder screen: a company must clear EVERY gate to be eligible;
survivors are then ranked by upside (margin of safety).

All gates read thresholds from ProfileConfig — no number is hard-coded here.
Every gate returns (passed, human-readable detail with the real figure) so each
pick can show exactly how it scores on every trait.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

from config.profile import ProfileConfig
from src.data.provider import CompanyData
from src.valuation.blender import BlendResult


@dataclass
class ProfileResult:
    ticker: str
    upside: Optional[float] = None
    qualifies: bool = False
    gates: Dict[str, Tuple[bool, str]] = field(default_factory=dict)

    def lines(self) -> List[str]:
        return [f"{'✓' if ok else '✗'} {name}: {detail}"
                for name, (ok, detail) in self.gates.items()]


def dedupe_dual_class(blends):
    """Collapse multiple share classes of one company (e.g. FOX/FOXA, GOOG/GOOGL)
    to a single entry. Assumes `blends` is already ordered by upside, so the
    first occurrence (cheapest class) is kept."""
    seen, out = set(), []
    for b in blends:
        key = (b.company_name or b.ticker).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


def _net_margin(data: CompanyData) -> Optional[float]:
    l = data.latest
    if l and l.net_income is not None and l.revenue and l.revenue > 0:
        return l.net_income / l.revenue
    return None


def sector_median_margins(records, universe) -> Dict[str, float]:
    """Median latest net margin per GICS sector, across everything valued."""
    by: Dict[str, List[float]] = defaultdict(list)
    for rec in records:
        d = getattr(rec, "data", None)
        if not d:
            continue
        nm = _net_margin(d)
        c = universe.get(d.ticker)
        if nm is not None and c and c.sector:
            by[c.sector].append(nm)
    return {sec: statistics.median(v) for sec, v in by.items() if v}


def evaluate(
    data: CompanyData,
    blend: Optional[BlendResult],
    gics_sector: Optional[str],
    sector_median_margin: Optional[float],
    cfg: ProfileConfig,
    excluded_sectors: set,
    excluded_tickers: set,
) -> ProfileResult:
    res = ProfileResult(
        ticker=data.ticker,
        upside=blend.margin_of_safety if (blend and blend.ok) else None,
    )
    g = res.gates

    # 1. Not on the exclusion list
    excluded = data.ticker in excluded_tickers or (gics_sector in excluded_sectors)
    g["not excluded"] = (not excluded,
                         f"{gics_sector or '?'}" + (" [blacklisted]" if excluded else ""))

    # 2. Long-term uptrend: (3y & 5y positive) OR price above long MA
    r3, r5, above = data.return_3y, data.return_5y, data.above_long_ma
    trend_ok = (r3 is not None and r3 > 0 and r5 is not None and r5 > 0) or (above is True)
    td = [f"3y {r3:+.0%}" if r3 is not None else "3y n/a",
          f"5y {r5:+.0%}" if r5 is not None else "5y n/a",
          "above long MA" if above else ("below long MA" if above is not None else "MA n/a")]
    g["uptrend"] = (bool(trend_ok), ", ".join(td))

    # 3. Rising-dividend streak (consecutive years of higher dividend/share)
    divs = [p.dividend_per_share for p in data.periods]  # newest first
    streak = 0
    for i in range(len(divs) - 1):
        a, b = divs[i], divs[i + 1]
        if a and b and a > b:
            streak += 1
        else:
            break
    g["dividend streak"] = (streak >= cfg.min_dividend_streak, f"{streak}y rising")

    # 4. Growing profits over several years
    ni = [p.net_income for p in reversed(data.periods) if p.net_income is not None]
    if len(ni) >= cfg.min_profit_growth_years and ni[0] > 0 and ni[-1] > 0:
        cagr = (ni[-1] / ni[0]) ** (1.0 / (len(ni) - 1)) - 1.0
        ok = cagr >= cfg.profit_growth_min_cagr and ni[-1] > ni[0]
        g["profit growth"] = (ok, f"{cagr:+.0%}/yr over {len(ni)}y")
    else:
        g["profit growth"] = (False, f"insufficient/negative ({len(ni)}y)")

    # 5. High margin (absolute floor and above sector median)
    nm = _net_margin(data)
    if nm is None:
        g["high margin"] = (False, "n/a")
    else:
        ok = nm >= cfg.net_margin_floor and (
            not cfg.require_above_sector_margin
            or (sector_median_margin is not None and nm > sector_median_margin)
        )
        sm = f" vs sector {sector_median_margin:.0%}" if sector_median_margin is not None else ""
        g["high margin"] = (ok, f"{nm:.0%}{sm}")

    # 6. Durable revenue (low volatility of annual growth = repeat business)
    revs = [p.revenue for p in reversed(data.periods) if p.revenue]
    growths = [revs[i + 1] / revs[i] - 1.0 for i in range(len(revs) - 1) if revs[i] > 0]
    if len(growths) >= 2:
        vol = statistics.pstdev(growths)
        g["revenue durability"] = (vol <= cfg.max_revenue_growth_vol, f"growth vol {vol:.0%}")
    else:
        g["revenue durability"] = (False, "insufficient")

    # 7. Undervalued by the model
    mos = blend.margin_of_safety if (blend and blend.ok) else None
    g["undervalued"] = (mos is not None and mos >= cfg.mos_floor,
                        f"MoS {mos:.0%}" if mos is not None else "n/a")

    res.qualifies = all(ok for ok, _ in g.values())
    return res


# --------------------------------------------------------------------------- #
# Tuning report: how many names pass, and how the count moves with strictness.
# --------------------------------------------------------------------------- #
def funnel_report(records, universe, cfg: ProfileConfig,
                  excluded_sectors: set, excluded_tickers: set,
                  thresholds=(0.15, 0.20, 0.25, 0.30, 0.40)) -> str:
    sec_med = sector_median_margins(records, universe)
    valued = [r for r in records if getattr(r, "data", None) and r.blend and r.blend.ok]

    def _eval(rec, mos):
        sec = universe.get(rec.data.ticker)
        sec = sec.sector if sec else None
        return evaluate(rec.data, rec.blend, sec, sec_med.get(sec),
                        replace(cfg, mos_floor=mos), excluded_sectors, excluded_tickers)

    # Per-gate pass counts and "pass all except undervaluation" at base MoS.
    gate_pass = Counter()
    pass_ex_under = 0
    for rec in valued:
        r = _eval(rec, cfg.mos_floor)
        for name, (ok, _) in r.gates.items():
            if ok:
                gate_pass[name] += 1
        if all(ok for n, (ok, _) in r.gates.items() if n != "undervalued"):
            pass_ex_under += 1

    lines = ["=" * 60, "QUALITY-COMPOUNDER SCREEN — FUNNEL", "=" * 60,
             f"  Valued names:                {len(valued)}"]
    for name in ("not excluded", "uptrend", "dividend streak", "profit growth",
                 "high margin", "revenue durability"):
        lines.append(f"  pass [{name}]:".ljust(32) + f"{gate_pass[name]}")
    lines.append(f"  pass ALL quality gates (pre-MoS): {pass_ex_under}")
    lines.append("  " + "-" * 56)
    lines.append("  Qualifiers (all gates incl. undervaluation) by MoS floor:")
    for thr in thresholds:
        n = sum(1 for rec in valued if _eval(rec, thr).qualifies)
        lines.append(f"    MoS ≥ {thr:.0%}:  {n}")
    lines.append("=" * 60)
    return "\n".join(lines)
