"""Curated set of major, liquid, low-cost ETFs for the ETF dip-screen.

A fund has no earnings/cash flows, so it can't be valued by DCF/DDM/Comps. The
ETF screen instead flags quality funds (broad market, sector, dividend) that have
pulled back within a long-term uptrend — "undervalued" = on a dip, not cheap on
fundamentals. No leveraged/inverse products.
"""

ETF_UNIVERSE = [
    ("SPY", "SPDR S&P 500", "US large-cap"),
    ("VOO", "Vanguard S&P 500", "US large-cap"),
    ("VTI", "Vanguard Total Stock Market", "US total market"),
    ("QQQ", "Invesco QQQ (Nasdaq-100)", "US tech / growth"),
    ("DIA", "SPDR Dow Jones Industrial", "US large-cap"),
    ("IWM", "iShares Russell 2000", "US small-cap"),
    ("SCHD", "Schwab US Dividend Equity", "US dividend"),
    ("VIG", "Vanguard Dividend Appreciation", "US dividend growth"),
    ("VYM", "Vanguard High Dividend Yield", "US dividend"),
    ("VEA", "Vanguard FTSE Developed Markets", "International developed"),
    ("VWO", "Vanguard FTSE Emerging Markets", "Emerging markets"),
    ("XLK", "Technology Select Sector SPDR", "Technology"),
    ("XLF", "Financial Select Sector SPDR", "Financials"),
    ("XLV", "Health Care Select Sector SPDR", "Health care"),
    ("XLE", "Energy Select Sector SPDR", "Energy"),
    ("XLY", "Consumer Discretionary SPDR", "Consumer discretionary"),
    ("XLP", "Consumer Staples SPDR", "Consumer staples"),
    ("XLI", "Industrial Select Sector SPDR", "Industrials"),
    ("XLU", "Utilities Select Sector SPDR", "Utilities"),
    ("XLB", "Materials Select Sector SPDR", "Materials"),
    ("XLC", "Communication Services SPDR", "Communication"),
    ("XLRE", "Real Estate Select Sector SPDR", "Real estate"),
    ("VGT", "Vanguard Information Technology", "Technology"),
    ("VHT", "Vanguard Health Care", "Health care"),
    ("SMH", "VanEck Semiconductor", "Semiconductors"),
    ("VNQ", "Vanguard Real Estate", "Real estate"),
    ("GLD", "SPDR Gold Shares", "Gold"),
]
