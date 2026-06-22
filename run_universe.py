"""Build the investable universe and print a summary so it can be eyeballed.

    python3 run_universe.py
"""

import logging

from config.universe import EXCLUDED_SECTORS, build_universe


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    universe = build_universe()

    print("\n" + "=" * 72)
    print("UNIVERSE SUMMARY")
    print("=" * 72)
    total = len(universe.kept) + len(universe.skipped)
    print(f"  Total constituents fetched: {total}")
    print(f"  Kept (investable):          {len(universe.kept)}")
    print(f"  Skipped (excluded):         {len(universe.skipped)}  "
          f"[{', '.join(sorted(EXCLUDED_SECTORS))}]")

    print("\n" + "=" * 72)
    print("KEPT — SECTOR BREAKDOWN")
    print("=" * 72)
    for sector, count in universe.sector_breakdown().items():
        print(f"  {sector:<28} {count:>3}")

    print("\n" + "=" * 72)
    print(f"SKIPPED NAMES ({len(universe.skipped)})")
    print("=" * 72)
    for c in universe.skipped:
        print(f"  {c.symbol:<7}{(c.name or ''):<32} {c.sector}")

    print("\n" + "=" * 72)
    print("PEER-GROUP SPOT CHECKS (for Comps)")
    print("=" * 72)
    for sym in ["AAPL", "MSFT", "XOM", "JNJ", "WMT"]:
        c = universe.get(sym)
        if c is None:
            print(f"\n  {sym}: not in investable universe")
            continue
        peers = universe.peers_for(sym)
        print(f"\n  {sym} ({c.name}) — {c.sub_industry}")
        print(f"    {len(peers)} peers: {', '.join(peers) if peers else '(none)'}")


if __name__ == "__main__":
    main()
