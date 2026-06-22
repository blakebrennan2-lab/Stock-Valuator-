"""Blacklist: tickers and sectors you never want in the digest.

Seeded with Energy (oil/gas). Add tickers or GICS sectors here to exclude them
without touching any logic. (Financials and Real Estate are already dropped
upstream in the universe because the models structurally don't fit them.)
"""

# GICS sectors to exclude from the quality-compounder screen.
EXCLUDED_SECTORS = {"Energy"}

# Individual tickers to blacklist (e.g. names you'd never buy).
EXCLUDED_TICKERS: set = set()
