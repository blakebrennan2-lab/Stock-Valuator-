"""Financial Modeling Prep implementation of `DataProvider`.

Uses FMP's current "stable" API (the legacy /api/v3 endpoints were retired for
new keys in Aug 2025). Free tier caps statement history at 5 years.

This is the ONLY file that knows FMP's URLs and field names. To swap sources,
write a sibling module exposing the same `get_company_data` and the rest of the
app is unaffected.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .cache import HttpCache
from .provider import CompanyData, DataProvider, FinancialPeriod, PeerMultiple

BASE_URL = "https://financialmodelingprep.com/stable"
FREE_TIER_MAX_HISTORY = 5  # FMP free tier rejects limit > 5


def _load_env(env_path: str) -> None:
    """Minimal .env loader (avoids a python-dotenv dependency)."""
    if not os.path.exists(env_path):
        return
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _to_float(value: Any) -> Optional[float]:
    """Coerce to float, returning None for missing/blank/garbage values."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class FMPProvider(DataProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[HttpCache] = None,
        history_years: int = FREE_TIER_MAX_HISTORY,
        peer_limit: int = 8,
    ) -> None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        _load_env(os.path.join(project_root, ".env"))
        self.api_key = api_key or os.environ.get("FMP_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "FMP_API_KEY not set. Add it to .env or pass api_key=..."
            )
        self.cache = cache or HttpCache(
            os.path.join(project_root, "cache", "fmp.sqlite")
        )
        self.history_years = min(history_years, FREE_TIER_MAX_HISTORY)
        self.peer_limit = peer_limit

    # ------------------------------------------------------------------ #
    # Low-level fetch                                                     #
    # ------------------------------------------------------------------ #
    def _fetch(self, endpoint: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """GET an endpoint and return a list of records.

        Never raises: network errors, HTTP errors, and FMP error payloads
        (which arrive as a dict or a bare string) all collapse to `[]` so the
        caller degrades gracefully.
        """
        query = dict(params)
        query["apikey"] = self.api_key
        url = f"{BASE_URL}/{endpoint}?{urllib.parse.urlencode(query)}"

        body = self.cache.get(url)
        if body is None:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "stock-valuator"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8")
                self.cache.set(url, body)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                return []

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return []

        if isinstance(data, list):
            return data
        # FMP signals errors as {"Error Message": ...} or a plain string.
        return []

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #
    def get_company_data(self, ticker: str) -> CompanyData:
        ticker = ticker.upper().strip()
        data = CompanyData(ticker=ticker)

        self._populate_profile(ticker, data)
        self._populate_periods(ticker, data)
        self._populate_balance_snapshot(ticker, data)
        self._populate_peers(ticker, data)
        return data

    def get_multiples(self, ticker: str) -> PeerMultiple:
        """P/E and P/B from `ratios`, EV/EBITDA from `key-metrics` (latest)."""
        ticker = ticker.upper().strip()
        pe = pb = ev_ebitda = None
        name = None

        ratio_rows = self._fetch("ratios", {"symbol": ticker, "limit": 1})
        if ratio_rows:
            pe = _to_float(ratio_rows[0].get("priceToEarningsRatio"))
            pb = _to_float(ratio_rows[0].get("priceToBookRatio"))

        km_rows = self._fetch("key-metrics", {"symbol": ticker, "limit": 1})
        if km_rows:
            ev_ebitda = _to_float(km_rows[0].get("evToEBITDA"))

        return PeerMultiple(symbol=ticker, name=name, pe=pe, ev_ebitda=ev_ebitda, pb=pb)

    # ------------------------------------------------------------------ #
    # Section builders                                                   #
    # ------------------------------------------------------------------ #
    def _populate_profile(self, ticker: str, data: CompanyData) -> None:
        rows = self._fetch("profile", {"symbol": ticker})
        if not rows:
            data.warnings.append("profile: no data returned")
            return
        p = rows[0]
        data.company_name = p.get("companyName")
        data.sector = p.get("sector")
        data.industry = p.get("industry")
        data.price = _to_float(p.get("price"))
        data.beta = _to_float(p.get("beta"))
        data.market_cap = _to_float(p.get("marketCap"))
        data.last_dividend = _to_float(p.get("lastDividend"))
        if data.beta is None:
            data.warnings.append("profile: beta missing (WACC will use fallback)")

    def _populate_periods(self, ticker: str, data: CompanyData) -> None:
        """Merge income, cash-flow, and ratio history into FinancialPeriods."""
        limit = {"limit": self.history_years}
        income = self._fetch("income-statement", {"symbol": ticker, **limit})
        cashflow = self._fetch("cash-flow-statement", {"symbol": ticker, **limit})
        ratios = self._fetch("ratios", {"symbol": ticker, **limit})

        if not income:
            data.warnings.append("income-statement: no data (DCF/Comps degraded)")
        if not cashflow:
            data.warnings.append("cash-flow-statement: no data (FCF unavailable)")
        if not ratios:
            data.warnings.append("ratios: no data (per-share metrics degraded)")

        cf_by_year = {r.get("fiscalYear"): r for r in cashflow}
        rt_by_year = {r.get("fiscalYear"): r for r in ratios}

        periods: List[FinancialPeriod] = []
        for inc in income:
            year = inc.get("fiscalYear")
            cf = cf_by_year.get(year, {})
            rt = rt_by_year.get(year, {})
            periods.append(
                FinancialPeriod(
                    fiscal_year=year,
                    period_end=inc.get("date"),
                    filing_date=inc.get("filingDate"),
                    # Income
                    revenue=_to_float(inc.get("revenue")),
                    ebit=_to_float(inc.get("ebit")),
                    ebitda=_to_float(inc.get("ebitda")),
                    net_income=_to_float(inc.get("netIncome")),
                    depreciation_amortization=_to_float(inc.get("depreciationAndAmortization")),
                    interest_expense=_to_float(inc.get("interestExpense")),
                    income_before_tax=_to_float(inc.get("incomeBeforeTax")),
                    income_tax_expense=_to_float(inc.get("incomeTaxExpense")),
                    eps=_to_float(inc.get("eps")),
                    eps_diluted=_to_float(inc.get("epsDiluted")),
                    shares_diluted=_to_float(inc.get("weightedAverageShsOutDil")),
                    # Cash flow
                    operating_cash_flow=_to_float(cf.get("operatingCashFlow")),
                    capital_expenditure=_to_float(cf.get("capitalExpenditure")),
                    free_cash_flow=_to_float(cf.get("freeCashFlow")),
                    change_in_working_capital=_to_float(cf.get("changeInWorkingCapital")),
                    dividends_paid=_to_float(cf.get("netDividendsPaid")),
                    # Ratios
                    effective_tax_rate=_to_float(rt.get("effectiveTaxRate")),
                    dividend_per_share=_to_float(rt.get("dividendPerShare")),
                    book_value_per_share=_to_float(rt.get("bookValuePerShare")),
                )
            )

        # FMP returns most-recent-first; sort defensively to guarantee it.
        periods.sort(key=lambda p: p.fiscal_year or "", reverse=True)
        data.periods = periods

    def _populate_balance_snapshot(self, ticker: str, data: CompanyData) -> None:
        rows = self._fetch("balance-sheet-statement", {"symbol": ticker, "limit": 1})
        if not rows:
            data.warnings.append("balance-sheet: no data (DCF equity bridge degraded)")
        else:
            b = rows[0]
            data.total_debt = _to_float(b.get("totalDebt"))
            data.cash_and_equivalents = _to_float(b.get("cashAndCashEquivalents"))
            data.cash_and_short_term_investments = _to_float(b.get("cashAndShortTermInvestments"))
            data.net_debt = _to_float(b.get("netDebt"))
            data.total_equity = _to_float(b.get("totalStockholdersEquity"))

        # Shares outstanding: latest diluted share count from income history.
        if data.latest and data.latest.shares_diluted is not None:
            data.shares_outstanding = data.latest.shares_diluted
        else:
            data.warnings.append("shares outstanding unavailable")

    def _populate_peers(self, ticker: str, data: CompanyData) -> None:
        peer_rows = self._fetch("stock-peers", {"symbol": ticker})
        if not peer_rows:
            data.warnings.append("stock-peers: none returned (Comps degraded)")
            return

        peers: List[PeerMultiple] = []
        for row in peer_rows[: self.peer_limit]:
            symbol = row.get("symbol")
            if not symbol:
                continue
            m = self.get_multiples(symbol)
            m.name = row.get("companyName")
            peers.append(m)
        data.peers = peers
        if not peers:
            data.warnings.append("peers resolved to empty (Comps degraded)")
