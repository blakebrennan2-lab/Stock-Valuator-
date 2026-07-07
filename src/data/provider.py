"""Data-source-agnostic interface for the valuation models.

The rest of the app depends ONLY on the dataclasses and the `DataProvider`
abstract base class defined here. Swapping FMP for another source (yfinance,
Tiingo, a paid FMP tier, etc.) means writing a new subclass of `DataProvider`
that returns these same dataclasses -- no model code changes.

Everything is `Optional`: any field can be `None` when the source is missing
data. Downstream models must treat `None` as "unavailable" and flag/skip
rather than assume zero.
"""

from __future__ import annotations

import dataclasses
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class FinancialPeriod:
    """One fiscal year of merged income / cash-flow / balance / ratio data.

    Carries the inputs all three models pull from history: free-cash-flow
    components, dividends, EPS, and per-share book value. `filing_date` is the
    date this data actually became public -- used later to avoid look-ahead.
    """

    fiscal_year: Optional[str] = None
    period_end: Optional[str] = None
    filing_date: Optional[str] = None

    # Income statement
    revenue: Optional[float] = None
    ebit: Optional[float] = None
    ebitda: Optional[float] = None
    net_income: Optional[float] = None
    depreciation_amortization: Optional[float] = None
    interest_expense: Optional[float] = None
    income_before_tax: Optional[float] = None
    income_tax_expense: Optional[float] = None
    eps: Optional[float] = None
    eps_diluted: Optional[float] = None
    shares_diluted: Optional[float] = None

    # Cash flow statement (free-cash-flow inputs)
    operating_cash_flow: Optional[float] = None
    capital_expenditure: Optional[float] = None
    free_cash_flow: Optional[float] = None
    change_in_working_capital: Optional[float] = None
    dividends_paid: Optional[float] = None  # total cash, negative outflow

    # Balance sheet (per-period, for debt trend + liquidity)
    total_debt: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None

    # Derived / ratio-sourced
    effective_tax_rate: Optional[float] = None
    dividend_per_share: Optional[float] = None
    book_value_per_share: Optional[float] = None


@dataclass
class PeerMultiple:
    """A sector peer and the relative-valuation multiples Comps needs."""

    symbol: str
    name: Optional[str] = None
    pe: Optional[float] = None          # price / earnings
    ev_ebitda: Optional[float] = None   # enterprise value / EBITDA
    pb: Optional[float] = None          # price / book
    market_cap: Optional[float] = None  # for size-comparability filtering
    sub_industry: Optional[str] = None  # GICS sub-industry (granular comparability)


@dataclass
class CompanyData:
    """Everything the DCF, DDM, and Comps models need for one ticker.

    `periods` is ordered most-recent-first. `latest` convenience properties
    pull from `periods[0]` so callers don't reach into the list directly.
    """

    ticker: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None

    # Market snapshot
    price: Optional[float] = None
    beta: Optional[float] = None
    market_cap: Optional[float] = None
    last_dividend: Optional[float] = None

    # Latest balance-sheet snapshot (for DCF bridge: EV -> equity)
    total_debt: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    cash_and_short_term_investments: Optional[float] = None
    net_debt: Optional[float] = None
    total_equity: Optional[float] = None        # book value of equity
    shares_outstanding: Optional[float] = None

    # Price-trend metrics (uptrend gate + recent-pullback trigger)
    return_3y: Optional[float] = None
    return_5y: Optional[float] = None
    ma_long: Optional[float] = None         # ~10-month (≈200-day) SMA
    above_long_ma: Optional[bool] = None
    high_52w: Optional[float] = None        # 52-week high
    drawdown: Optional[float] = None        # (price - high_52w)/high_52w, negative

    # History (most recent first) and peers
    periods: List[FinancialPeriod] = field(default_factory=list)
    peers: List[PeerMultiple] = field(default_factory=list)

    # Non-fatal issues encountered while assembling (printed for transparency)
    warnings: List[str] = field(default_factory=list)

    @property
    def latest(self) -> Optional[FinancialPeriod]:
        return self.periods[0] if self.periods else None


@dataclass
class Constituent:
    """One index member with the GICS classification Comps/exclusions need."""

    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None        # GICS Sector
    sub_industry: Optional[str] = None  # GICS Sub-Industry (finer peer grouping)


class DataProvider(ABC):
    """Contract every fundamentals source must satisfy.

    One method, by design: hand it a ticker, get back a fully-populated
    `CompanyData`. Sources fan out to whatever endpoints they need internally.
    """

    @abstractmethod
    def get_company_data(self, ticker: str) -> CompanyData:
        """Fetch and normalize all model inputs for `ticker`.

        Implementations must never raise on missing data -- populate what they
        can, leave the rest `None`, and append a note to `CompanyData.warnings`.
        """
        raise NotImplementedError

    @abstractmethod
    def get_multiples(self, ticker: str) -> PeerMultiple:
        """Fetch just the valuation multiples (P/E, EV/EBITDA, P/B) for one
        ticker. Used by Comps to price each peer. Missing values come back as
        `None`; never raises."""
        raise NotImplementedError


class UniverseProvider(ABC):
    """Contract for the index-membership source (kept separate from
    fundamentals so each can be swapped independently)."""

    @abstractmethod
    def get_sp500_constituents(self) -> List[Constituent]:
        """Return current S&P 500 members. Must not raise: return [] on failure."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# (De)serialization -- used by providers that cache assembled objects (e.g.
# yfinance, whose responses are DataFrames, not cacheable HTTP bodies).
# --------------------------------------------------------------------------- #
def company_to_json(data: CompanyData) -> str:
    return json.dumps(dataclasses.asdict(data))


def company_from_json(s: str) -> CompanyData:
    d = json.loads(s)
    d["periods"] = [FinancialPeriod(**p) for p in d.get("periods", [])]
    d["peers"] = [PeerMultiple(**pm) for pm in d.get("peers", [])]
    return CompanyData(**d)


def multiples_to_json(pm: PeerMultiple) -> str:
    return json.dumps(dataclasses.asdict(pm))


def multiples_from_json(s: str) -> PeerMultiple:
    return PeerMultiple(**json.loads(s))
