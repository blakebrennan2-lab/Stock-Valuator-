"""Telegram message formatting (no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notify.telegram import TelegramNotifier
from src.valuation.blender import BlendResult


def _b(ticker, name, price, intrinsic, mos, conf, n):
    return BlendResult(
        ticker=ticker, company_name=name, price=price, intrinsic_value=intrinsic,
        margin_of_safety=mos, confidence=conf, n_models=n, ok=True,
    )


def test_format_top():
    top = [
        _b("AOS", "A. O. Smith Corporation", 58.22, 110.02, 0.47, "medium", 3),
        _b("MO", "Altria Group, Inc.", 69.12, 107.18, 0.355, "high", 3),
    ]
    msg = TelegramNotifier(token="x", chat_id="y").format_top(top, as_of="2026-06-20")
    assert "Top 2 Undervalued" in msg
    assert "1. AOS" in msg and "A. O. Smith Corporation" in msg
    assert "+47% MoS" in msg
    assert "high confidence · 3 models" in msg
    assert "2026-06-20" in msg
    print("  formats top list with MoS/confidence  OK")


def test_format_escapes_html():
    top = [_b("XYZ", "Tom & Jerry <Inc>", 10, 20, 0.5, "medium", 2)]
    msg = TelegramNotifier(token="x", chat_id="y").format_top(top)
    assert "Tom &amp; Jerry &lt;Inc&gt;" in msg  # escaped, won't break HTML parse
    print("  escapes &/</> in company names  OK")


def test_format_empty_is_honest():
    msg = TelegramNotifier(token="x", chat_id="y").format_top([], as_of="2026-06-20")
    assert "No names cleared" in msg
    print("  empty list -> honest 'nothing qualifies' message  OK")


def test_not_configured_skips_send():
    # Independent of .env: clear the instance to simulate missing creds.
    n = TelegramNotifier()
    n.token = None
    n.chat_id = None
    assert not n.configured
    assert n.send_message("hi") is False  # no creds -> skip, no crash
    print("  missing creds -> skips send, returns False  OK")


if __name__ == "__main__":
    tests = [test_format_top, test_format_escapes_html,
             test_format_empty_is_honest, test_not_configured_skips_send]
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
