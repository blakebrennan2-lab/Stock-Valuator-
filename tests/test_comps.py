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

from src.data.provider import (
    CompanyData, Constituent, DataProvider, FinancialPeriod, PeerMultiple,
)
from src.models.comps import CompsModel


class FakeUniverse:
    def __init__(self, table):
        self.table = table

    def get(self, s):
        return self.table.get(s)

    def peers_for(self, s):
        return [k for k in self.table if k != s]


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
# P/E peers [10,12,14,16,100] -> 100 dropped by sanity cap (>60) -> [10,12,14,16]
#   n=4 (<5) so no trim -> median 13 ; x EPS 5 = 65
# EV/EBITDA [8,9,10,11,50]    -> all <=50 cap; n=5 trim -> [9,10,11] median 10 ; x EBITDA 1000 = 10000 EV
#   equity = 10000 - 200 + 50 = 9850 ; / 100 sh = 98.50
# P/B [1,2,3,4,5]             -> trim -> [2,3,4]  median 3  ; x BVPS 10 = 30
# implied {P/E:65, EV/EBITDA:98.5, P/B:30} -> median 65 ; range 30..98.5
def test_handworked():
    syms, table = _peers([10, 12, 14, 16, 100], [8, 9, 10, 11, 50], [1, 2, 3, 4, 5])
    res = CompsModel(FakeProvider(table)).value(
        _target(eps=5, ebitda=1000, bvps=10), peer_symbols=syms
    )
    assert res.ok, res.flags
    m = res.audit["multiples"]
    # The absurd P/E of 100 is dropped by the sanity cap before the median.
    assert 100 not in m["pe"]["peer_values"], m["pe"]["peer_values"]
    assert m["pe"]["median"] == 13 and abs(m["pe"]["implied"] - 65) < 1e-9
    assert m["ev_ebitda"]["median"] == 10 and abs(m["ev_ebitda"]["implied"] - 98.5) < 1e-9
    assert m["pb"]["median"] == 3 and abs(m["pb"]["implied"] - 30) < 1e-9
    assert abs(res.base - 65) < 1e-9, res.base
    assert abs(res.low - 30) < 1e-9 and abs(res.high - 98.5) < 1e-9
    print(f"  hand-worked: P/E=65 EV/EBITDA=98.5 P/B=30 -> base {res.base}  OK")


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


def test_target_multiples_in_audit():
    # The report shows the target's own multiples beside its peers.
    syms, table = _peers([10, 12, 14], [8, 9, 10], [1, 2, 3])
    data = _target(eps=5, ebitda=1000, bvps=10)
    data.price = 50.0
    data.market_cap = 5000.0     # EV = 5000 + 200 - 50 = 5150
    res = CompsModel(FakeProvider(table)).value(data, peer_symbols=syms)
    assert res.ok
    tm = res.audit["target_multiples"]
    assert abs(tm["pe"] - 10.0) < 1e-9, tm            # 50 / 5
    assert abs(tm["ev_ebitda"] - 5.15) < 1e-9, tm     # 5150 / 1000
    assert abs(tm["pb"] - 5.0) < 1e-9, tm             # 50 / 10
    print("  target's own P/E, EV/EBITDA, P/B recorded for the peer table  OK")


def test_extreme_peer_group_flagged_relative_only():
    # Individually-sane peers (all under the 60x/50x caps) whose MEDIAN is
    # extreme (44x P/E, 32x EV/EBITDA) = a richly-priced sector. The comp must
    # be flagged relative-only so the blender can't anchor a "buy" on it.
    syms, table = _peers([40, 44, 50], [30, 32, 34], [2, 3, 4])
    res = CompsModel(FakeProvider(table)).value(
        _target(eps=5, ebitda=1000, bvps=10), peer_symbols=syms
    )
    assert res.ok
    assert res.relative_only is True
    assert res.low_reliability is True
    assert any("extreme multiples" in f for f in res.flags), res.flags
    # Sane medians -> no flag.
    syms2, table2 = _peers([10, 12, 14], [8, 9, 10], [1, 2, 3])
    res2 = CompsModel(FakeProvider(table2)).value(
        _target(eps=5, ebitda=1000, bvps=10), peer_symbols=syms2
    )
    assert res2.ok and res2.relative_only is False
    print("  extreme peer medians -> relative-only; sane medians -> anchor  OK")


def test_peer_selection_industry_and_dual_class():
    # Target FOO (Broadcasting). FOOA = its own other share class (exclude).
    # BAR/BAZ = real broadcasting peers. QUX = unrelated industry (exclude).
    uni = FakeUniverse({
        "FOO": Constituent("FOO", "Foo Corp (Class B)", "Comm", "Broadcasting"),
        "FOOA": Constituent("FOOA", "Foo Corp (Class A)", "Comm", "Broadcasting"),
        "BAR": Constituent("BAR", "Bar Media", "Comm", "Broadcasting"),
        "BAZ": Constituent("BAZ", "Baz Media", "Comm", "Broadcasting"),
        "QUX": Constituent("QUX", "Qux Retail", "Cons", "Retail Stores"),
    })
    table = {s: PeerMultiple(symbol=s, pe=15, ev_ebitda=10, pb=2, market_cap=1e10)
             for s in uni.table}
    data = CompanyData(ticker="FOO", market_cap=1e10, shares_outstanding=100.0,
                       periods=[FinancialPeriod(fiscal_year="2025", eps_diluted=5.0,
                                                ebitda=1000.0, book_value_per_share=10.0)])
    res = CompsModel(FakeProvider(table), uni).value(data)
    assert res.ok, res.flags
    used = {p["symbol"] for p in res.audit["peers"]}
    assert used == {"BAR", "BAZ"}, used                 # same industry only
    assert "FOOA" not in used and "QUX" not in used      # no dual-class, no unrelated
    assert res.audit["basis"].startswith("same industry")
    print("  same-industry peers chosen; dual-class + unrelated excluded  OK")


if __name__ == "__main__":
    tests = [
        test_handworked,
        test_target_multiples_in_audit,
        test_extreme_peer_group_flagged_relative_only,
        test_peer_selection_industry_and_dual_class,
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
