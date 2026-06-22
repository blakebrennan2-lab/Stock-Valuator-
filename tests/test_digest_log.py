"""Digest picks-log format (the record used to score calls vs outcomes)."""

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notify.digest_log import HEADER, append_digest_log
from src.valuation.blender import BlendResult


def _b(t, name, price, iv, mos, conf, n):
    return BlendResult(ticker=t, company_name=name, price=price, intrinsic_value=iv,
                       margin_of_safety=mos, confidence=conf, n_models=n, ok=True)


def test_append_picks_and_accumulate():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "picks.csv")
        top = [_b("LULU", "lululemon", 111.77, 319.16, 0.65, "medium", 2),
               _b("GDDY", "GoDaddy", 77.04, 190.59, 0.596, "medium", 2)]
        append_digest_log(top, as_of="2026-06-20", path=path)
        append_digest_log([_b("CNC", "Centene", 61.02, 129.85, 0.53, "medium", 2)],
                          as_of="2026-06-22", path=path)

        rows = list(csv.reader(open(path)))
        assert rows[0] == HEADER
        body = rows[1:]
        assert len(body) == 3  # accumulates across runs
        assert body[0][:7] == ["2026-06-20", "1", "LULU", "lululemon", "111.77",
                               "319.16", "65.0%"]
        assert body[2][0] == "2026-06-22" and body[2][2] == "CNC"
        print("  appends per-pick rows, accumulates across runs  OK")


def test_empty_digest_is_recorded():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "picks.csv")
        append_digest_log([], as_of="2026-07-01", path=path)
        rows = list(csv.reader(open(path)))
        assert rows[1][0] == "2026-07-01" and "no qualifiers" in rows[1][2]
        print("  empty digest still logs a dated 'no qualifiers' row  OK")


if __name__ == "__main__":
    tests = [test_append_picks_and_accumulate, test_empty_digest_is_recorded]
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
