"""yfinance implementation of `DataProvider` (free, full S&P 500 coverage).

FMP's free tier paywalls fundamentals for most symbols; yfinance (Yahoo) covers
the whole index. It lives behind the same `DataProvider` interface, so switching
between FMP and yfinance -- or to a paid source later -- is a one-line change at
the call site.

Trade-off: yfinance scrapes Yahoo, so it's slower and occasionally returns
partial data. Every field is therefore extracted defensively and degrades to
None + a warning rather than raising.
"""

from __future__ import annotations

import json
import os
import time
import warnings
from typing import List, Optional

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402  (yfinance pulls this in)
import yfinance as yf  # noqa: E402

from .cache import HttpCache
from .provider import (  # noqa: E402
    CompanyData, DataProvider, FinancialPeriod, PeerMultiple,
    company_from_json, company_to_json, multiples_from_json, multiples_to_json,
)


def _f(value) -> Optional[float]:
    """Coerce to float, mapping NaN/None/blank to None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row(df: Optional[pd.DataFrame], labels: List[str]) -> Optional[pd.Series]:
    """First matching row from a yfinance statement frame, or None."""
    if df is None or getattr(df, "empty", True):
        return None
    for label in labels:
        if label in df.index:
            return df.loc[label]
    return None


def _cell(series: Optional[pd.Series], col) -> Optional[float]:
    if series is None:
        return None
    try:
        return _f(series.get(col))
    except Exception:
        return None


class YFinanceProvider(DataProvider):
    def __init__(
        self,
        history_years: int = 5,
        cache: Optional[HttpCache] = None,
        cache_ttl_hours: int = 24,
        use_cache: bool = True,
        max_retries: int = 2,
        retry_backoff: float = 3.0,
    ) -> None:
        self.history_years = history_years
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        if cache is None and use_cache:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            cache = HttpCache(
                os.path.join(project_root, "cache", "yfinance.sqlite"),
                ttl_seconds=cache_ttl_hours * 3600,
            )
        self.cache = cache  # None disables caching

    @staticmethod
    def _yahoo_symbol(ticker: str) -> str:
        """Yahoo uses hyphens for class shares (BRK-B, BF-B); the universe and
        FMP use dots (BRK.B, BF.B). Translate at the boundary."""
        return ticker.upper().strip().replace(".", "-")

    # ------------------------------------------------------------------ #
    def get_company_data(self, ticker: str) -> CompanyData:
        ticker = ticker.upper().strip()

        cache_key = f"yf:company:v3:{ticker}:{self.history_years}"  # v3: + 52w drawdown
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                try:
                    return company_from_json(cached)
                except Exception:
                    pass  # corrupt entry -> fall through and refetch

        data = self._fetch_with_retry(ticker)
        if self.cache is not None and (data.price is not None or data.periods):
            self.cache.set(cache_key, company_to_json(data))
        return data

    def _fetch_with_retry(self, ticker: str) -> CompanyData:
        """Refetch on an empty result (transient Yahoo throttling), backing off
        between attempts. A genuinely dataless name still returns after the last
        try -- callers handle the empty CompanyData gracefully."""
        data = self._fetch_company_data(ticker)
        attempt = 0
        while attempt < self.max_retries and data.price is None and not data.periods:
            time.sleep(self.retry_backoff * (attempt + 1))
            data = self._fetch_company_data(ticker)
            attempt += 1
        return data

    def _fetch_company_data(self, ticker: str) -> CompanyData:
        data = CompanyData(ticker=ticker)
        t = yf.Ticker(self._yahoo_symbol(ticker))

        # --- profile / market snapshot (.info) ------------------------- #
        try:
            info = t.info or {}
        except Exception:
            info = {}
            data.warnings.append("yfinance .info unavailable")

        data.company_name = info.get("longName") or info.get("shortName")
        data.sector = info.get("sector")
        data.industry = info.get("industry")
        data.price = _f(info.get("currentPrice")) or _f(info.get("regularMarketPrice"))
        data.beta = _f(info.get("beta"))
        data.market_cap = _f(info.get("marketCap"))
        data.last_dividend = _f(info.get("lastDividendValue"))
        data.high_52w = _f(info.get("fiftyTwoWeekHigh"))
        if data.price and data.high_52w and data.high_52w > 0:
            data.drawdown = data.price / data.high_52w - 1.0  # negative = below high
        if data.beta is None:
            data.warnings.append("beta missing (WACC will use fallback)")

        # --- statements ----------------------------------------------- #
        try:
            income = t.income_stmt
            cashflow = t.cashflow
            balance = t.balance_sheet
        except Exception:
            income = cashflow = balance = None
            data.warnings.append("yfinance statements unavailable")

        # --- annual dividends per share (calendar-year sums) ----------- #
        div_by_year = {}
        try:
            divs = t.dividends
            if divs is not None and len(divs) > 0:
                div_by_year = divs.groupby(divs.index.year).sum().to_dict()
        except Exception:
            pass

        data.periods = self._build_periods(income, cashflow, balance, div_by_year, data)
        self._populate_balance_snapshot(balance, info, data)
        self._populate_price_metrics(t, data)
        return data

    def _populate_price_metrics(self, t, data: CompanyData) -> None:
        """3y/5y total-ish return and a long moving average from monthly closes."""
        try:
            hist = t.history(period="5y", interval="1mo")
            closes = [float(x) for x in hist["Close"].dropna().tolist()]
        except Exception:
            closes = []
        if len(closes) < 13:  # need a year-plus to say anything
            data.warnings.append("insufficient price history (uptrend gate degraded)")
            return
        last = closes[-1]
        data.return_5y = (last / closes[0] - 1.0) if closes[0] > 0 else None
        if len(closes) >= 37 and closes[-37] > 0:
            data.return_3y = last / closes[-37] - 1.0
        window = closes[-10:]  # ~10 months ≈ 200 trading days
        data.ma_long = sum(window) / len(window)
        ref_price = data.price or last
        data.above_long_ma = ref_price > data.ma_long if data.ma_long else None

    # ------------------------------------------------------------------ #
    def _build_periods(self, income, cashflow, balance, div_by_year, data):
        if income is None or getattr(income, "empty", True):
            data.warnings.append("no income statement (DCF/Comps degraded)")
            return []

        rev = _row(income, ["Total Revenue", "Operating Revenue"])
        ebit = _row(income, ["EBIT"])
        ebitda = _row(income, ["EBITDA", "Normalized EBITDA"])
        net_income = _row(income, ["Net Income"])
        da_inc = _row(income, ["Reconciled Depreciation"])
        interest = _row(income, ["Interest Expense"])
        pretax = _row(income, ["Pretax Income"])
        tax = _row(income, ["Tax Provision"])
        eps_b = _row(income, ["Basic EPS"])
        eps_d = _row(income, ["Diluted EPS"])
        shares_d = _row(income, ["Diluted Average Shares", "Basic Average Shares"])

        ocf = _row(cashflow, ["Operating Cash Flow"])
        capex = _row(cashflow, ["Capital Expenditure"])
        fcf = _row(cashflow, ["Free Cash Flow"])
        wc = _row(cashflow, ["Change In Working Capital"])
        divs_paid = _row(cashflow, ["Cash Dividends Paid", "Common Stock Dividend Paid"])
        da_cf = _row(cashflow, ["Depreciation And Amortization",
                                "Depreciation Amortization Depletion"])

        equity = _row(balance, ["Stockholders Equity", "Common Stock Equity"])

        periods: List[FinancialPeriod] = []
        for col in list(income.columns)[: self.history_years]:
            year = col.year
            shares_val = _cell(shares_d, col)
            equity_val = _cell(equity, col)
            pretax_val = _cell(pretax, col)
            tax_val = _cell(tax, col)
            etr = (tax_val / pretax_val) if (pretax_val and pretax_val > 0
                                             and tax_val is not None) else None
            bvps = (equity_val / shares_val) if (equity_val is not None
                                                 and shares_val) else None

            periods.append(FinancialPeriod(
                fiscal_year=str(year),
                period_end=str(col.date()),
                filing_date=None,  # yfinance doesn't expose filing dates
                revenue=_cell(rev, col),
                ebit=_cell(ebit, col),
                ebitda=_cell(ebitda, col),
                net_income=_cell(net_income, col),
                depreciation_amortization=_cell(da_inc, col) or _cell(da_cf, col),
                interest_expense=_cell(interest, col),
                income_before_tax=pretax_val,
                income_tax_expense=tax_val,
                eps=_cell(eps_b, col),
                eps_diluted=_cell(eps_d, col),
                shares_diluted=shares_val,
                operating_cash_flow=_cell(ocf, col),
                capital_expenditure=_cell(capex, col),
                free_cash_flow=_cell(fcf, col),
                change_in_working_capital=_cell(wc, col),
                dividends_paid=_cell(divs_paid, col),
                effective_tax_rate=etr,
                dividend_per_share=_f(div_by_year.get(year)),
                book_value_per_share=bvps,
            ))

        # newest first
        periods.sort(key=lambda p: p.fiscal_year or "", reverse=True)
        if not any(p.free_cash_flow is not None for p in periods):
            data.warnings.append("no free cash flow history (DCF unavailable)")
        return periods

    # ------------------------------------------------------------------ #
    def _populate_balance_snapshot(self, balance, info, data: CompanyData) -> None:
        if balance is not None and not getattr(balance, "empty", True):
            col = balance.columns[0]
            data.total_debt = _cell(_row(balance, ["Total Debt"]), col)
            data.cash_and_equivalents = _cell(
                _row(balance, ["Cash And Cash Equivalents"]), col)
            data.cash_and_short_term_investments = _cell(
                _row(balance, ["Cash Cash Equivalents And Short Term Investments",
                               "Cash And Cash Equivalents"]), col)
            data.net_debt = _cell(_row(balance, ["Net Debt"]), col)
            data.total_equity = _cell(
                _row(balance, ["Stockholders Equity", "Common Stock Equity"]), col)
        else:
            data.warnings.append("no balance sheet (DCF equity bridge degraded)")

        # Prefer current shares from .info; fall back to latest diluted.
        data.shares_outstanding = _f(info.get("sharesOutstanding"))
        if not data.shares_outstanding and data.latest:
            data.shares_outstanding = data.latest.shares_diluted
        if not data.total_debt and info.get("totalDebt"):
            data.total_debt = _f(info.get("totalDebt"))
        if not data.shares_outstanding:
            data.warnings.append("shares outstanding unavailable")

    # ------------------------------------------------------------------ #
    def get_multiples(self, ticker: str) -> PeerMultiple:
        ticker = ticker.upper().strip()

        cache_key = f"yf:multiples:v2:{ticker}"  # v2: + market_cap
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                try:
                    return multiples_from_json(cached)
                except Exception:
                    pass

        try:
            info = yf.Ticker(self._yahoo_symbol(ticker)).info or {}
        except Exception:
            info = {}
        pm = PeerMultiple(
            symbol=ticker,
            name=info.get("longName") or info.get("shortName"),
            pe=_f(info.get("trailingPE")),
            ev_ebitda=_f(info.get("enterpriseToEbitda")),
            pb=_f(info.get("priceToBook")),
            market_cap=_f(info.get("marketCap")),
        )
        if self.cache is not None and info:
            self.cache.set(cache_key, multiples_to_json(pm))
        return pm

    # ------------------------------------------------------------------ #
    def get_quote(self, ticker: str) -> Optional[float]:
        """Latest price (intraday-ish via fast_info), for the hourly refresh."""
        t = yf.Ticker(self._yahoo_symbol(ticker))
        for getter in (
            lambda: t.fast_info["last_price"],
            lambda: t.fast_info["lastPrice"],
            lambda: (t.info or {}).get("currentPrice"),
        ):
            try:
                v = getter()
                if v:
                    return float(v)
            except Exception:
                continue
        hist = self.get_price_history(ticker)
        return hist[-1][1] if hist else None

    def get_price_history(self, ticker: str) -> List[list]:
        """Full daily closes (~5y, every trading day) for the chart's longer
        ranges. -> [[YYYY-MM-DD, close]]."""
        ticker = ticker.upper().strip()
        cache_key = f"yf:history:v2:{ticker}"  # v2: full daily (no weekly thinning)
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                try:
                    return json.loads(cached)
                except Exception:
                    pass
        try:
            closes = yf.Ticker(self._yahoo_symbol(ticker)).history(
                period="5y", interval="1d")["Close"].dropna()
            out = [[ts.strftime("%Y-%m-%d"), round(float(v), 2)] for ts, v in closes.items()]
        except Exception:
            out = []
        if self.cache is not None and out:
            self.cache.set(cache_key, json.dumps(out))
        return out

    def get_intraday(self, ticker: str) -> dict:
        """Fine-grained intraday at multiple resolutions, like Apple Stocks:
        day = 1-minute (~390 pts), week = 5-minute, month = hourly.
        -> {'day': [...], 'week': [...], 'month': [...]} of ['YYYY-MM-DD HH:MM', close]."""
        ticker = ticker.upper().strip()
        cache_key = f"yf:intraday:v2:{ticker}"  # v2: multi-resolution dict
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                try:
                    return json.loads(cached)
                except Exception:
                    pass
        t = yf.Ticker(self._yahoo_symbol(ticker))
        specs = {"day": ("1d", "1m"), "week": ("5d", "5m"), "month": ("1mo", "60m")}
        out = {}
        for key, (period, interval) in specs.items():
            try:
                closes = t.history(period=period, interval=interval)["Close"].dropna()
                out[key] = [[ts.strftime("%Y-%m-%d %H:%M"), round(float(v), 2)]
                            for ts, v in closes.items()]
            except Exception:
                out[key] = []
        if self.cache is not None and any(out.values()):
            self.cache.set(cache_key, json.dumps(out))
        return out

    def get_news(self, ticker: str, limit: int = 4) -> List[dict]:
        """Recent headlines from Yahoo (real source) -> [{title, publisher, date}].

        Best-effort: returns [] if unavailable. Not a comprehensive litigation
        check -- just real, dated headlines the digest can surface verbatim.
        """
        ticker = ticker.upper().strip()
        cache_key = f"yf:news:{ticker}"
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                try:
                    return json.loads(cached)
                except Exception:
                    pass
        try:
            items = yf.Ticker(self._yahoo_symbol(ticker)).news or []
        except Exception:
            items = []

        out: List[dict] = []
        for it in items[:limit]:
            c = it.get("content") or it  # newer yfinance nests under "content"
            title = c.get("title")
            if not title:
                continue
            prov = (c.get("provider") or {}).get("displayName") or c.get("publisher")
            date = c.get("pubDate") or c.get("displayTime") or ""
            out.append({"title": title, "publisher": prov, "date": str(date)[:10]})

        if self.cache is not None and out:
            self.cache.set(cache_key, json.dumps(out))
        return out
