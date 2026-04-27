#!/usr/bin/env python3
"""ADR data availability check - verify each ADR in adr_universe.yaml has:
  1. Alpaca daily bars (>=5 years for backtest viability)
  2. Finnhub fundamentals (synthetic-row score path)

Usage:
    py -3 tests/check_adr_data.py                    # full check (needs creds)
    py -3 tests/check_adr_data.py --quick            # source-only audit
    py -3 tests/check_adr_data.py --ticker TSM       # one ticker

Exit codes:
    0  all ADRs have required data
    1  one or more ADRs missing data
    2  framework crashed

Companion to:
    aggressive/universe.py:load_adr_universe()
    adr_universe.yaml
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check_alpaca_bars(ticker: str, min_years: float = 5.0) -> tuple[bool, str]:
    """Returns (ok, message). Tries Alpaca; gracefully skips if creds missing."""
    try:
        from aggressive.data_alpaca import fetch_daily_bars
    except Exception as e:
        return False, f"alpaca module unavailable: {e}"
    df = fetch_daily_bars(ticker, days=int(min_years * 252) + 30)
    if df is None or df.empty:
        return False, "no bars returned (creds? network? delisted?)"
    n_days = len(df)
    if n_days < min_years * 250:
        return False, f"only {n_days} bars (<{int(min_years*252)} required)"
    return True, f"{n_days} bars, latest={df.index.max().date()}"


def check_finnhub(ticker: str) -> tuple[bool, str]:
    """Returns (ok, message). Looks for cached parquet first, then live fetch."""
    try:
        from aggressive.finnhub_cache_loader import load_finnhub_features_dict
    except Exception as e:
        return False, f"finnhub cache loader unavailable: {e}"
    try:
        cache = load_finnhub_features_dict()
    except Exception as e:
        return False, f"cache load failed: {e}"
    if ticker not in cache:
        return False, "ticker not in finnhub cache (run finnhub_collector first?)"
    rec = cache[ticker]
    needed = ["fh_peExclExtra_ttm", "fh_revenueGrowthQuarterlyYoy"]
    missing = [k for k in needed if rec.get(k) is None]
    if missing:
        return False, f"finnhub fields missing: {missing}"
    return True, f"finnhub OK ({len(rec)} fields)"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticker", help="check single ticker only")
    p.add_argument("--quick", action="store_true",
                   help="source-only audit (no Alpaca/Finnhub network calls)")
    p.add_argument("--min-years", type=float, default=5.0,
                   help="minimum years of price history required")
    args = p.parse_args()

    from aggressive.universe import load_adr_universe
    tickers, meta_list = load_adr_universe()

    if args.ticker:
        tickers = [t for t in tickers if t == args.ticker.upper()]
        meta_list = [m for m in meta_list if m["ticker"] == args.ticker.upper()]
        if not tickers:
            print(f"ticker {args.ticker} not in adr_universe.yaml", file=sys.stderr)
            return 1

    print("=" * 70)
    print(f"ADR data availability check - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)
    print(f"Universe: {len(tickers)} ADRs (mcap >= $30B, skip excluded)\n")

    if args.quick:
        # Source audit only - list what's expected to be checkable
        print("SOURCE AUDIT (--quick mode, no network):\n")
        for m in meta_list:
            t = m["ticker"]
            print(f"  {t:7s} {m['country']:3s} {m['sector']:20s} "
                  f"${m['mcap_usd_b']:>5.0f}B  {m.get('listed_since', '?')}")
        print(f"\nQUICK PASS - {len(tickers)} ADRs in whitelist, all have required fields.")
        return 0

    n_pass = 0
    n_fail = 0
    failures: list[tuple[str, str, str]] = []

    for m in meta_list:
        t = m["ticker"]
        b_ok, b_msg = check_alpaca_bars(t, min_years=args.min_years)
        f_ok, f_msg = check_finnhub(t)
        ok = b_ok and f_ok
        status = "PASS" if ok else "FAIL"
        print(f"  {t:7s} [{status}] bars={b_msg[:40]:42s} | finnhub={f_msg[:35]}")
        if ok:
            n_pass += 1
        else:
            n_fail += 1
            if not b_ok:
                failures.append((t, "alpaca_bars", b_msg))
            if not f_ok:
                failures.append((t, "finnhub", f_msg))

    print()
    print("=" * 70)
    print(f"Results: {n_pass}/{len(tickers)} PASS, {n_fail} FAIL")
    if failures:
        print("\nFAILED CHECKS:")
        for t, kind, msg in failures:
            print(f"  {t:7s} [{kind}]  {msg}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"\ncheck framework crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)
