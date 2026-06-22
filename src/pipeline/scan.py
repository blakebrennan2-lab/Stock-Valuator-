"""End-to-end scan: value the universe, blend, rank, emit the top undervalued.

Orchestration only -- all the logic lives in the providers, models, blender, and
ranker. One name failing never aborts the scan; it's recorded with its error and
the sweep continues.
"""

from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from config.exclusions import EXCLUDED_SECTORS, EXCLUDED_TICKERS
from config.profile import ProfileConfig
from config.universe import Universe, build_universe
from src.data.provider import CompanyData, DataProvider
from src.models.base import ValuationResult
from src.models.comps import CompsModel
from src.models.dcf import DCFModel
from src.models.ddm import DDMModel
from src.screen.profile import (
    ProfileResult, dedupe_dual_class, evaluate, funnel_report, sector_median_margins,
)
from src.valuation.blender import BlendResult, Blender


LEVERAGE_MAX = 3.5  # Net debt / EBITDA above this = balance-sheet risk


def assess_quality(data: CompanyData) -> List[str]:
    """Value-trap markers a trailing-FCF/dividend model can't otherwise see.

    These exclude a name from the top list (not from valuation) so secular
    decliners and over-levered balance sheets don't masquerade as 'cheap'.
    """
    flags: List[str] = []

    revs = [p.revenue for p in reversed(data.periods) if p.revenue is not None]
    if len(revs) >= 2 and revs[-1] < revs[0]:
        flags.append("revenue declining")

    ebitda = data.latest.ebitda if data.latest else None
    net_debt = data.net_debt
    if net_debt is None and data.total_debt is not None:
        net_debt = data.total_debt - (data.cash_and_equivalents or 0.0)
    if net_debt and ebitda and ebitda > 0:
        lev = net_debt / ebitda
        if lev > LEVERAGE_MAX:
            flags.append(f"high leverage ({lev:.1f}x ND/EBITDA)")

    return flags


@dataclass
class ScanRecord:
    blend: BlendResult
    results: Dict[str, ValuationResult] = field(default_factory=dict)
    data: Optional[CompanyData] = None
    profile: Optional[ProfileResult] = None
    error: str = ""


@dataclass
class ScanResult:
    records: List[ScanRecord] = field(default_factory=list)
    top: List[BlendResult] = field(default_factory=list)
    funnel: str = ""


class Scanner:
    def __init__(
        self,
        provider: DataProvider,
        universe: Optional[Universe] = None,
        profile_config: Optional[ProfileConfig] = None,
    ) -> None:
        self.provider = provider
        self.universe = universe or build_universe()
        self.dcf = DCFModel()
        self.ddm = DDMModel()
        self.comps = CompsModel(provider, self.universe)
        self.blender = Blender()
        self.profile_cfg = profile_config or ProfileConfig()

    # ------------------------------------------------------------------ #
    def value_one(self, symbol: str) -> ScanRecord:
        try:
            data = self.provider.get_company_data(symbol)
        except Exception as e:
            return ScanRecord(
                blend=BlendResult(ticker=symbol), error=str(e)[:120]
            )

        results = {
            "DCF": self.dcf.value(data),
            "DDM": self.ddm.value(data),
            "Comps": self.comps.value(data),
        }
        blend = self.blender.blend(
            list(results.values()),
            price=data.price,
            ticker=symbol,
            company_name=data.company_name,
        )
        blend.quality_flags = assess_quality(data)
        return ScanRecord(blend=blend, results=results, data=data)

    def scan(
        self,
        symbols: Optional[List[str]] = None,
        progress_every: int = 25,
        delay: float = 0.3,
    ) -> ScanResult:
        symbols = symbols or self.universe.symbols
        records: List[ScanRecord] = []
        for i, sym in enumerate(symbols, 1):
            records.append(self.value_one(sym))
            if progress_every and (i % progress_every == 0 or i == len(symbols)):
                print(f"  valued {i}/{len(symbols)}")
            if delay:
                time.sleep(delay)  # be polite to Yahoo; avoids rate-limit blanks

        # --- quality-compounder screen: gate, then rank survivors by upside ---
        sec_med = sector_median_margins(records, self.universe)
        for rec in records:
            if not rec.data:
                continue
            c = self.universe.get(rec.data.ticker)
            sec = c.sector if c else None
            rec.profile = evaluate(
                rec.data, rec.blend, sec, sec_med.get(sec),
                self.profile_cfg, EXCLUDED_SECTORS, EXCLUDED_TICKERS,
            )
            rec.blend.qualifies = rec.profile.qualifies
            rec.blend.profile_lines = rec.profile.lines()

        qualifiers = [r for r in records if r.profile and r.profile.qualifies]
        qualifiers.sort(key=lambda r: r.blend.margin_of_safety or 0.0, reverse=True)
        # Collapse dual-class duplicates (FOX/FOXA) before taking the top N.
        top = dedupe_dual_class([r.blend for r in qualifiers])[: self.profile_cfg.top_n]

        funnel = funnel_report(records, self.universe, self.profile_cfg,
                               EXCLUDED_SECTORS, EXCLUDED_TICKERS)
        return ScanResult(records=records, top=top, funnel=funnel)


# ---------------------------------------------------------------------- #
# Output
# ---------------------------------------------------------------------- #
def write_csv(result: ScanResult, path: Optional[str] = None) -> str:
    path = path or os.path.join("output", f"scan_{date.today().isoformat()}.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def flags(rec: ScanRecord, model: str) -> str:
        r = rec.results.get(model)
        return "; ".join(r.flags) if r else ""

    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "symbol", "name", "price", "intrinsic", "margin_of_safety",
            "confidence", "n_models", "qualifies", "upside", "profile",
            "quality_flags", "DCF", "DDM", "Comps",
            "low", "high", "DCF_flags", "DDM_flags", "Comps_flags", "error",
        ])
        for rec in result.records:
            b = rec.blend
            w.writerow([
                b.ticker, b.company_name or "", _r(b.price), _r(b.intrinsic_value),
                _r(b.margin_of_safety, pct=True), b.confidence, b.n_models,
                b.qualifies, _r(b.margin_of_safety, pct=True), " | ".join(b.profile_lines),
                "; ".join(b.quality_flags),
                _r(b.model_values.get("DCF")), _r(b.model_values.get("DDM")),
                _r(b.model_values.get("Comps")), _r(b.low), _r(b.high),
                flags(rec, "DCF"), flags(rec, "DDM"), flags(rec, "Comps"), rec.error,
            ])
    return path


def _r(x, pct: bool = False):
    if x is None:
        return ""
    return f"{x*100:.1f}%" if pct else f"{x:.2f}"


def print_top(result: ScanResult) -> None:
    if result.funnel:
        print("\n" + result.funnel)
    print("\n" + "=" * 78)
    print(f"TOP {len(result.top)} QUALITY COMPOUNDERS (cleared every gate), ranked by upside")
    print("=" * 78)
    if not result.top:
        print("  No names cleared every quality-compounder gate.")
        print("  (Honest empty result — nothing fits the profile right now.)")
        return
    print(f"  {'#':<3}{'Sym':<7}{'Price':>9}{'Intrinsic':>11}{'Upside':>8}"
          f"{'Conf':>8}   Name")
    for i, b in enumerate(result.top, 1):
        print(f"  {i:<3}{b.ticker:<7}{b.price:>9.2f}{b.intrinsic_value:>11.2f}"
              f"{b.margin_of_safety*100:>7.0f}%{b.confidence:>8}   "
              f"{(b.company_name or '')[:30]}")
        for line in b.profile_lines:
            print(f"        {line}")
