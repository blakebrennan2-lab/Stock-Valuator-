"""S&P 500 investable universe: load, exclude, tag, and group for Comps.

Per the agreed spec, Financials and Real Estate are excluded up front (standard
DCF/Comps break for banks/insurers/REITs) and logged as skipped. The list comes
through a `UniverseProvider`, so the source stays swappable.

Comps peers are built from THIS universe by GICS Sub-Industry (falling back to
Sector when a sub-industry is too thin), which is far more reliable than FMP's
`stock-peers` endpoint -- as the AAPL test showed (it returned random micro-caps).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.data.datahub_universe import DataHubUniverseProvider
from src.data.provider import Constituent, UniverseProvider

logger = logging.getLogger(__name__)

# GICS sectors excluded from the investable universe (per spec).
EXCLUDED_SECTORS = {"Financials", "Real Estate"}

# Minimum number of OTHER peers required before we trust a sub-industry group;
# below this we broaden to the GICS sector for a more robust Comps median.
MIN_SUBINDUSTRY_PEERS = 3


@dataclass
class Universe:
    """The filtered, tagged investable universe plus peer-grouping helpers."""

    kept: List[Constituent] = field(default_factory=list)
    skipped: List[Constituent] = field(default_factory=list)

    # Internal lookups (built in __post_init__)
    _by_symbol: Dict[str, Constituent] = field(default_factory=dict, repr=False)
    _by_sub_industry: Dict[str, List[str]] = field(default_factory=dict, repr=False)
    _by_sector: Dict[str, List[str]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for c in self.kept:
            self._by_symbol[c.symbol] = c
            if c.sub_industry:
                self._by_sub_industry.setdefault(c.sub_industry, []).append(c.symbol)
            if c.sector:
                self._by_sector.setdefault(c.sector, []).append(c.symbol)

    @property
    def symbols(self) -> List[str]:
        return [c.symbol for c in self.kept]

    def get(self, symbol: str) -> Optional[Constituent]:
        return self._by_symbol.get(symbol.upper())

    def peers_for(self, symbol: str) -> List[str]:
        """Comps peer group for `symbol`, excluding the symbol itself.

        Uses GICS Sub-Industry; if that yields fewer than
        `MIN_SUBINDUSTRY_PEERS` peers, broadens to the GICS Sector.
        """
        symbol = symbol.upper()
        c = self._by_symbol.get(symbol)
        if c is None:
            return []

        peers: List[str] = []
        if c.sub_industry:
            peers = [s for s in self._by_sub_industry.get(c.sub_industry, []) if s != symbol]
        if len(peers) < MIN_SUBINDUSTRY_PEERS and c.sector:
            peers = [s for s in self._by_sector.get(c.sector, []) if s != symbol]
        return peers

    def sector_breakdown(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for c in self.kept:
            counts[c.sector or "Unknown"] = counts.get(c.sector or "Unknown", 0) + 1
        return dict(sorted(counts.items()))


def build_universe(
    provider: Optional[UniverseProvider] = None,
    excluded_sectors: Optional[set] = None,
) -> Universe:
    """Fetch constituents, apply sector exclusions, and return a `Universe`.

    Skipped (financials/REITs) names are logged individually and retained in
    `Universe.skipped` for an auditable record of what was dropped and why.
    """
    provider = provider or DataHubUniverseProvider()
    excluded = excluded_sectors if excluded_sectors is not None else EXCLUDED_SECTORS

    constituents = provider.get_sp500_constituents()
    if not constituents:
        logger.error("Universe source returned no constituents; universe is empty.")
        return Universe()

    kept: List[Constituent] = []
    skipped: List[Constituent] = []
    for c in constituents:
        if c.sector in excluded:
            skipped.append(c)
            logger.info("SKIP %-6s %-28s [%s]", c.symbol, c.name or "", c.sector)
        else:
            kept.append(c)

    logger.info(
        "Universe built: %d kept, %d skipped (excluded sectors: %s)",
        len(kept), len(skipped), ", ".join(sorted(excluded)),
    )
    return Universe(kept=kept, skipped=skipped)
