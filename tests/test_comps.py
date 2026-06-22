"""Comps math validation (deterministic, no network -- uses a fake provider).

  1. Hand-worked example: trimmed medians + three implied values + reconciliation.
  2. Negative target EPS -> P/E dropped.
  3. Negative target book value -> P/B dropped.
  4. Peer with negative P/B -> that peer filtered out.
  5. All multiples invalid -> ok=False (no fabricated number).
  6. Too few valid peers -> multiple dropped.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.provider import CompanyData, DataProvider, FinancialPeriod, PeerMultiple
from src.models.comps import CompsModel


class FakeProvider(DataProvider):
    """Returns canned multiples; get_company_data unused by Comps."""

    def __init__(self, table):
        self.table = table

    def get_company_data(self, ticker: str) -> CompanyData:  # pragma: no cover
        return CompanyData(ticker=ticker)

    def get_multiples(self, ticker: str) -> PeerMultiple:
        return self.table.get(ticker, PeerMultiple(symbol=ticker))


def _target(eps=None, ebitda=None, bvps=None, shares=100.0, debt=200.0, cash=50.0):
    return CompanyData(
        ticker="TGT",
        shares_outstanding=shares,
        total_debt=debt,
        cash_and_equivalents=cash,
        periods=[FinancialPeriod(
            fiscal_year="2025", eps_diluted=eps, ebitda=ebitda, book_value_per_share=bvps
        )],
    )


def _peers(pe_list, ev_list, pb_list):
    syms, table = [], {}
    for i, (pe, ev, pb) in enumerate(zip(pe_list, ev_list, pb_list)):
        s = f"P{i}"
        syms.append(s)
        table[s] = PeerMultiple(symbol=s, pe=pe, ev_ebitda=ev, pb=pb)
    return syms, table


# --------------------------------------------------------------------------- #
# 1. Hand-worked
# --------------------------------------------------------------------------- #
# P/E peers [10,12,14,16,100] -> trim -> [12,14,16] median 14 ; x EPS 5  = 70
# EV/EBITDA [8,9,10,11,50]    -> trim -> [9,10,11] median 10 ; x EBITDA 1000 = 10000 EV
#   equity = 10000 - 200 + 50 = 9850 ; / 100 sh = 98.50
# P/B [1,2,3,4,5]             -> trim -> [2,3,4]  median 3  ; x BVPS 10 = 30
# implied {P/E:70, EV/EBITDA:98.5, P/B:30} -> median 70 ; range 30..98.5
def test_handworked():
    syms, table = _peers([10, 12, 14, 16, 100], [8, 9, 10, 11, 50], [1, 2, 3, 4, 5])
    res = CompsModel(FakeProvider(table)).value(
        _target(eps=5, ebitda=1000, bvps=10), peer_symbols=syms
    )
    assert res.ok, res.flags
    m = res.audit["multiples"]
    assert m["pe"]["median"] == 14 and abs(m["pe"]["implied"] - 70) < 1e-9
    assert m["ev_ebitda"]["median"] == 10 and abs(m["ev_ebitda"]["implied"] - 98.5) < 1e-9
    assert m["pb"]["median"] == 3 and abs(m["pb"]["implied"] - 30) < 1e-9
    assert abs(res.base - 70) < 1e-9, res.base
    assert abs(res.low - 30) < 1e-9 and abs(res.high - 98.5) < 1e-9
    print(f"  hand-worked: P/E=70 EV/EBITDA=98.5 P/B=30 -> base {res.base}  OK")


# --------------------------------------------------------------------------- #
# 2. Negative target EPS -> P/E dropped
# --------------------------------------------------------------------------- #
def test_negative_target_eps_drops_pe():
    syms, table = _peers([10, 12, 14], [8, 9, 10], [1, 2, 3])
    res = CompsModel(FakeProvider(table)).value(
        _target(eps=-2, ebitda=1000, bvps=10), peer_symbols=syms
    )
    assert res.ok
    assert "P/E" not in res.audit["implied_by_method"]
    assert "EV/EBITDA" in res.audit["implied_by_method"]
    assert any("EPS" in f and "non-positive" in f for f in res.flags), res.flags
    print("  negative target EPS -> P/E dropped, others valid  OK")


# --------------------------------------------------------------------------- #
# 3. Negative target book -> P/B dropped
# --------------------------------------------------------------------------- #
def test_negative_target_book_drops_pb():
    syms, table = _peers([10, 12, 14], [8, 9, 10], [1, 2, 3])
    res = CompsModel(FakeProvider(table)).value(
        _target(eps=5, ebitda=1000, bvps=-4), peer_symbols=syms
    )
    assert res.ok
    assert "P/B" not in res.audit["implied_by_method"]
    assert any("Book value/share non-positive" in f for f in res.flags), res.flags
    print("  negative target book -> P/B dropped  OK")


# --------------------------------------------------------------------------- #
# 4. Peer with negative P/B -> filtered from the P/B set
# --------------------------------------------------------------------------- #
def test_negative_peer_pb_filtered():
    syms, table = _peers([10, 12, 14], [8, 9, 10], [2, -3, 4])  # one negative pb
    res = CompsModel(FakeProvider(table)).value(
        _target(eps=5, ebitda=1000, bvps=10), peer_symbols=syms
    )
    assert res.ok
    # Only 2 valid pb peers remain ([2,4]); median 3 -> implied 30.
    assert res.audit["multiples"]["pb"]["peer_values"] == [2, 4]
    assert abs(res.audit["multiples"]["pb"]["implied"] - 30) < 1e-9
    print("  negative peer P/B filtered out  OK")


# --------------------------------------------------------------------------- #
# 5. All invalid -> ok=False
# --------------------------------------------------------------------------- #
def test_all_invalid_returns_not_ok():
    syms, table = _peers([10, 12, 14], [8, 9, 10], [1, 2, 3])
    res = CompsModel(FakeProvider(table)).value(
        _target(eps=-1, ebitda=-5, bvps=-2), peer_symbols=syms
    )
    assert not res.ok
    assert res.value_per_share is None
    print("  all metrics invalid -> not ok, no number  OK")


# --------------------------------------------------------------------------- #
# 6. Too few peers -> dropped
# --------------------------------------------------------------------------- #
def test_too_few_peers():
    syms, table = _peers([10], [8], [1])  # 1 peer < min_peers_per_multiple
    res = CompsModel(FakeProvider(table)).value(
        _target(eps=5, ebitda=1000, bvps=10), peer_symbols=syms
    )
    assert not res.ok
    assert any("only 1 valid peer" in f for f in res.flags), res.flags
    print("  too few peers -> dropped  OK")


if __name__ == "__main__":
    tests = [
        test_handworked,
        test_negative_target_eps_drops_pe,
        test_negative_target_book_drops_pb,
        test_negative_peer_pb_filtered,
        test_all_invalid_returns_not_ok,
        test_too_few_peers,
    ]
    failed = 0
    for t in tests:
        try:
            print(f"- {t.__name__}")
            t()
        except AssertionError as e:
            failed += 1
            print(f"  FAIL: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
