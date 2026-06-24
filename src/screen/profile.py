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

    # 2. Long-term uptrend (so a dip is a pullback, not a structural decline)
    r3, r5, above = data.return_3y, data.return_5y, data.above_long_ma
    trend_ok = (r3 is not None and r3 > 0 and r5 is not None and r5 > 0) or (above is True)
    td = [f"3y {r3:+.0%}" if r3 is not None else "3y n/a",
          f"5y {r5:+.0%}" if r5 is not None else "5y n/a"]
    g["long-term uptrend"] = (bool(trend_ok), ", ".join(td))

    # 3. Earnings intact & growing (the drop isn't from earnings falling)
    ni = [p.net_income for p in reversed(data.periods) if p.net_income is not None]
    if len(ni) >= cfg.min_profit_growth_years and ni[0] > 0 and ni[-1] > 0:
        cagr = (ni[-1] / ni[0]) ** (1.0 / (len(ni) - 1)) - 1.0
        ok = cagr >= cfg.profit_growth_min_cagr
        g["earnings intact"] = (ok, f"net income {cagr:+.0%}/yr over {len(ni)}y")
    else:
        cagr = None
        g["earnings intact"] = (False, f"insufficient/negative ({len(ni)}y)")

    # 4. Healthy margins
    nm = _net_margin(data)
    g["healthy margins"] = (nm is not None and nm >= cfg.net_margin_floor,
                            f"{nm:.0%} net margin" if nm is not None else "n/a")

    # 5. Durable revenue (low volatility of annual growth; not collapsing)
    revs = [p.revenue for p in reversed(data.periods) if p.revenue]
    growths = [revs[i + 1] / revs[i] - 1.0 for i in range(len(revs) - 1) if revs[i] > 0]
    rev_ok = (len(growths) >= 2 and statistics.pstdev(growths) <= cfg.max_revenue_growth_vol
              and revs[-1] >= revs[0])
    vol = statistics.pstdev(growths) if len(growths) >= 2 else None
    g["durable revenue"] = (rev_ok, f"growth vol {vol:.0%}" if vol is not None else "insufficient")

    # 6. Recent pullback (THE trigger) — down min..max % from the 52-week high
    dd = data.drawdown
    pull_ok = dd is not None and -cfg.max_pullback <= dd <= -cfg.min_pullback
    g["recent pullback"] = (bool(pull_ok),
                            f"down {abs(dd):.0%} from 52wk high" if dd is not None else "n/a")

    # 7. At or below fair value (not necessarily a deep discount)
    mos = blend.margin_of_safety if (blend and blend.ok) else None
    g["at/below fair value"] = (mos is not None and mos >= cfg.mos_floor,
                                f"MoS {mos:.0%}" if mos is not None else "n/a")

    res.qualifies = all(ok for ok, _ in g.values())
    # Multiple-compression read: dropped on price while earnings held -> sentiment.
    if pull_ok and cagr is not None and cagr >= 0:
        res.gates["→ multiple compression"] = (
            True, f"price down {abs(dd):.0%} while earnings grew {cagr:+.0%}/yr "
                  f"(sentiment, not deterioration)")
    return res


# --------------------------------------------------------------------------- #
# Tuning report: how many names pass, and how the count moves with strictness.
# --------------------------------------------------------------------------- #
def funnel_report(records, universe, cfg: ProfileConfig,
                  excluded_sectors: set, excluded_tickers: set) -> str:
    sec_med = sector_median_margins(records, universe)
    valued = [r for r in records if getattr(r, "data", None) and r.blend and r.blend.ok]

    def _eval(rec):
        sec = universe.get(rec.data.ticker)
        sec = sec.sector if sec else None
        return evaluate(rec.data, rec.blend, sec, sec_med.get(sec),
                        cfg, excluded_sectors, excluded_tickers)

    gate_pass = Counter()
    qualifiers = 0
    for rec in valued:
        r = _eval(rec)
        for name, (ok, _) in r.gates.items():
            if ok:
                gate_pass[name] += 1
        if r.qualifies:
            qualifiers += 1

    lines = ["=" * 60, "QUALITY-ON-A-DIP SCREEN — FUNNEL", "=" * 60,
             f"  Valued names:                {len(valued)}"]
    for name in ("not excluded", "long-term uptrend", "earnings intact",
                 "healthy margins", "durable revenue", "recent pullback",
                 "at/below fair value"):
        lines.append(f"  pass [{name}]:".ljust(34) + f"{gate_pass[name]}")
    lines.append("  " + "-" * 56)
    lines.append(f"  QUALIFY (all gates):         {qualifiers}")
    lines.append("=" * 60)
    return "\n".join(lines)
