"""Relative valuation (Comps) via peer multiples.

Method
------
1. Peer set from `universe.peers_for(ticker)` (GICS sub-industry, sector
   fallback) -- NOT FMP's unreliable stock-peers list.
2. For each peer fetch P/E, EV/EBITDA, P/B. Drop non-positive multiples
   (negative-earnings or negative-book peers produce nonsense), then take a
   trimmed median (drop high+low when >=5 peers).
3. Apply each median to the target's matching metric:
     - P/E       -> median * target EPS                 = implied price
     - EV/EBITDA -> median * target EBITDA = implied EV  -> equity bridge -> price
     - P/B       -> median * target book value/share     = implied price
   Drop any multiple where the target's own metric is non-positive.
4. Reconcile the valid implied prices into one figure (median of the methods,
   robust to one distorted multiple); range = min/max across methods.

Everything is recorded in `ValuationResult.audit`.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.data.provider import CompanyData, DataProvider, PeerMultiple
from src.models.base import ValuationModel, ValuationResult


@dataclass
class CompsConfig:
    min_peers_per_multiple: int = 2   # need at least this many to trust a median
    low_confidence_below: int = 3     # flag when a median rests on <3 peers
    trim_when_at_least: int = 5       # drop one high + one low at/above this n
    min_industry_peers: int = 2       # this many same-industry peers = a clean group
    size_lo: float = 0.2              # sector fallback: keep peers within 0.2x..
    size_hi: float = 5.0              # ..5x the target's market cap (drop the giants)


def _trimmed_median(values: List[float], trim_at: int) -> tuple:
    """Return (median, used_values). Trims one high + one low when large enough."""
    ordered = sorted(values)
    used = ordered[1:-1] if len(ordered) >= trim_at else ordered
    if not used:  # tiny set where trimming removed everything
        used = ordered
    return statistics.median(used), used


class CompsModel(ValuationModel):
    name = "Comps"

    def __init__(
        self,
        provider: DataProvider,
        universe=None,
        config: Optional[CompsConfig] = None,
    ) -> None:
        self.provider = provider
        self.universe = universe
        self.cfg = config or CompsConfig()

    # ------------------------------------------------------------------ #
    def _select_peers(self, data, candidates):
        """Pick genuinely comparable peers: same granular industry first; if too
        few, a size-matched sector subset (low confidence); else none.
        Returns (peers, basis, low_reliability)."""
        cfg = self.cfg

        def valid(pm):
            return any(v and v > 0 for v in (pm.pe, pm.ev_ebitda, pm.pb))

        if self.universe is None:  # tests / explicit peer lists
            return [pm for pm in candidates if valid(pm)], "provided peers", False

        def base_name(n):  # "Fox Corporation (Class B)" -> "fox corporation"
            return (n or "").split("(")[0].strip().lower()

        target = self.universe.get(data.ticker)
        target_sub = target.sub_industry if target else None
        target_base = base_name(target.name) if target else None

        annotated = []
        for pm in candidates:
            c = self.universe.get(pm.symbol)
            if c and not pm.sub_industry:
                pm.sub_industry = c.sub_industry
            # Exclude the target's own other share classes (FOX/FOXA, GOOG/GOOGL).
            if c and target_base and base_name(c.name) == target_base:
                continue
            annotated.append(pm)
        candidates = annotated

        same = [pm for pm in candidates
                if target_sub and pm.sub_industry == target_sub and valid(pm)]
        if len(same) >= cfg.min_industry_peers:
            return same, f"same industry — {target_sub}", False

        # Fallback: same sector but only size-comparable names (drop the giants),
        # and mark it low confidence since the business match is looser.
        tmc = data.market_cap
        if tmc:
            lo, hi = tmc * cfg.size_lo, tmc * cfg.size_hi
            sized = [pm for pm in candidates
                     if valid(pm) and pm.market_cap and lo <= pm.market_cap <= hi]
        else:
            sized = [pm for pm in candidates if valid(pm)]
        if len(sized) >= cfg.min_peers_per_multiple:
            return sized, "size-matched sector peers (no close industry match)", True
        if same:
            return same, f"only {len(same)} same-industry peer(s)", True
        return [], "no genuinely comparable peers", True

    # ------------------------------------------------------------------ #
    def value(
        self, data: CompanyData, peer_symbols: Optional[List[str]] = None
    ) -> ValuationResult:
        cfg = self.cfg
        result = ValuationResult(model=self.name, ticker=data.ticker)

        # --- Peer set -------------------------------------------------- #
        if peer_symbols is None:
            if self.universe is None:
                result.flags.append("No universe/peers provided; cannot run Comps")
                return result
            peer_symbols = self.universe.peers_for(data.ticker)
        if not peer_symbols:
            result.flags.append("No peers found for Comps")
            return result

        # --- Fetch candidate multiples, then pick genuine comparables -- #
        candidates: List[PeerMultiple] = [
            self.provider.get_multiples(sym) for sym in peer_symbols
        ]
        peer_multiples, basis, low_rel = self._select_peers(data, candidates)
        if not peer_multiples:
            result.flags.append(
                f"Not applicable: {basis} for {data.ticker} (won't compare to "
                f"unrelated companies)")
            result.audit = {"basis": basis, "candidates_considered": len(candidates)}
            return result
        if low_rel:
            result.low_reliability = True

        # Target metrics
        latest = data.latest
        target_eps = latest.eps_diluted if latest else None
        target_ebitda = latest.ebitda if latest else None
        target_bvps = latest.book_value_per_share if latest else None

        implied: Dict[str, float] = {}
        audit_multiples: Dict[str, dict] = {}

        # --- P/E ------------------------------------------------------- #
        pe_vals = [p.pe for p in peer_multiples if p.pe is not None and p.pe > 0]
        audit_multiples["pe"] = self._build_multiple(
            "P/E", pe_vals, target_eps, "EPS (diluted)", result
        )
        if audit_multiples["pe"].get("implied") is not None:
            implied["P/E"] = audit_multiples["pe"]["implied"]

        # --- EV/EBITDA (with EV->equity bridge) ----------------------- #
        ev_vals = [
            p.ev_ebitda for p in peer_multiples
            if p.ev_ebitda is not None and p.ev_ebitda > 0
        ]
        ev_audit = self._build_ev_multiple(ev_vals, target_ebitda, data, result)
        audit_multiples["ev_ebitda"] = ev_audit
        if ev_audit.get("implied") is not None:
            implied["EV/EBITDA"] = ev_audit["implied"]

        # --- P/B ------------------------------------------------------- #
        pb_vals = [p.pb for p in peer_multiples if p.pb is not None and p.pb > 0]
        audit_multiples["pb"] = self._build_multiple(
            "P/B", pb_vals, target_bvps, "Book value/share", result
        )
        if audit_multiples["pb"].get("implied") is not None:
            implied["P/B"] = audit_multiples["pb"]["implied"]

        # --- Reconcile ------------------------------------------------- #
        if not implied:
            result.flags.append("No valid multiples produced a Comps value")
            result.audit = {
                "basis": basis,
                "peers": [p.__dict__ for p in peer_multiples],
                "multiples": audit_multiples,
            }
            return result

        valid_values = list(implied.values())
        reconciled = statistics.median(valid_values)
        result.ok = True
        result.base = reconciled
        result.value_per_share = reconciled
        result.low = min(valid_values)
        result.high = max(valid_values)
        if basis.startswith("size-matched") or basis.startswith("only"):
            result.flags.append(f"Comps basis: {basis} — lower confidence")

        result.assumptions = {
            "peers_used": [p.symbol for p in peer_multiples],
            "methods_used": list(implied.keys()),
        }
        result.audit = {
            "basis": basis,
            "peers": [p.__dict__ for p in peer_multiples],
            "multiples": audit_multiples,
            "implied_by_method": implied,
            "reconciled_median": reconciled,
            "reconciled_mean": statistics.fmean(valid_values),
            "range": {"low": result.low, "high": result.high},
        }
        return result

    # ------------------------------------------------------------------ #
    def _build_multiple(
        self,
        label: str,
        peer_values: List[float],
        target_metric: Optional[float],
        metric_name: str,
        result: ValuationResult,
    ) -> dict:
        """Trimmed median * target metric = implied price (price-based multiples)."""
        cfg = self.cfg
        info: dict = {"peer_values": peer_values, "target_metric": target_metric}

        if len(peer_values) < cfg.min_peers_per_multiple:
            result.flags.append(
                f"{label}: only {len(peer_values)} valid peer(s); dropped"
            )
            return info
        if target_metric is None or target_metric <= 0:
            result.flags.append(
                f"{label}: target {metric_name} non-positive/missing; dropped"
            )
            return info

        median, used = _trimmed_median(peer_values, cfg.trim_when_at_least)
        info.update({"median": median, "used_values": used,
                     "implied": median * target_metric})
        if len(peer_values) < cfg.low_confidence_below:
            result.flags.append(f"{label}: low confidence ({len(peer_values)} peers)")
        return info

    def _build_ev_multiple(
        self,
        peer_values: List[float],
        target_ebitda: Optional[float],
        data: CompanyData,
        result: ValuationResult,
    ) -> dict:
        """EV/EBITDA: median * EBITDA = implied EV, then bridge EV -> per share."""
        cfg = self.cfg
        info: dict = {"peer_values": peer_values, "target_metric": target_ebitda}

        if len(peer_values) < cfg.min_peers_per_multiple:
            result.flags.append(
                f"EV/EBITDA: only {len(peer_values)} valid peer(s); dropped"
            )
            return info
        if target_ebitda is None or target_ebitda <= 0:
            result.flags.append("EV/EBITDA: target EBITDA non-positive/missing; dropped")
            return info
        shares = data.shares_outstanding
        if not shares or shares <= 0:
            result.flags.append("EV/EBITDA: shares missing; dropped")
            return info

        median, used = _trimmed_median(peer_values, cfg.trim_when_at_least)
        implied_ev = median * target_ebitda
        total_debt = data.total_debt or 0.0
        cash = data.cash_and_equivalents or 0.0
        equity_value = implied_ev - total_debt + cash
        per_share = equity_value / shares

        info.update({
            "median": median, "used_values": used,
            "implied_ev": implied_ev, "total_debt": total_debt, "cash": cash,
            "equity_value": equity_value, "shares": shares, "implied": per_share,
        })
        if len(peer_values) < cfg.low_confidence_below:
            result.flags.append(f"EV/EBITDA: low confidence ({len(peer_values)} peers)")
        return info
