"""Morning verification script - Phase V+F sanity check.

Run after waking up to confirm Finnhub collection completed and integration works.

Usage:
  py -3 aggressive/verify_phase_v_f.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from aggressive.finnhub_cache_loader import load_finnhub_live_from_cache_dir


def check_finnhub_collection():
    print("=" * 78)
    print("1. Finnhub Collection Status")
    print("=" * 78)
    d = load_finnhub_live_from_cache_dir()
    print(f"  Tickers collected: {len(d)}")
    if len(d) < 900:
        print(f"  [WARN] Expected ~1008, got {len(d)}. Collection incomplete?")
        print(f"  -> re-run: py -3 aggressive/finnhub_collector.py --mode full")
        return False
    # Key data coverage
    keys_of_interest = [
        "fh_peExclExtra_ttm", "fh_peg_5y", "fh_epsGrowth5Y",
        "fh_epsGrowthQuarterlyYoy", "fh_days_to_next_earnings",
        "fh_mspr_3m_avg", "fh_insider_cluster_30d_score",
        "fh_rec_bull_ratio",
    ]
    print()
    print("  Coverage by field:")
    for k in keys_of_interest:
        n_populated = sum(1 for row in d.values() if row.get(k) is not None)
        pct = n_populated / len(d) * 100
        print(f"    {k:<40} {n_populated:>4}/{len(d)} ({pct:>4.0f}%)")
    return True


def check_peg_fix(d: dict):
    """Show AAPL/NVDA/GOOG PEG before/after (from gdrive + Finnhub recompute)."""
    print()
    print("=" * 78)
    print("2. PEG Fix Verification (Before/After)")
    print("=" * 78)
    gdrive_path = Path(r"G:/내 드라이브/r1000_top30_institutional/outputs/portfolio_latest.csv")
    if not gdrive_path.exists():
        print("  [SKIP] gdrive portfolio_latest.csv not available")
        return
    try:
        gdrive = pd.read_csv(gdrive_path)
    except Exception as e:
        print(f"  [SKIP] could not read gdrive: {e}")
        return

    # Sample critical names
    critical = ["AAPL", "NVDA", "GOOG", "AMD", "AVGO", "JNJ",
                "BKNG", "WDC", "STX", "LITE", "MU", "COHR"]
    rows = []
    for t in critical:
        row = {"ticker": t}
        # Before (from gdrive)
        g = gdrive[gdrive["ticker"] == t]
        if not g.empty:
            r = g.iloc[0]
            row["peg_old"] = r.get("peg_final")
            row["forward_pe_old"] = r.get("forward_pe_final")
            row["weight_in_portfolio"] = r.get("weight")
        # After (from Finnhub)
        fh = d.get(t, {})
        row["peg_new"] = fh.get("fh_peg_5y")
        row["forward_pe_new"] = fh.get("fh_peExclExtra_ttm")
        row["eps_growth_5y"] = fh.get("fh_epsGrowth5Y")
        row["mspr_3m"] = fh.get("fh_mspr_3m_avg")
        row["days_to_earnings"] = fh.get("fh_days_to_next_earnings")
        rows.append(row)

    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    print()
    print(df.to_string(index=False))


def run_scanner_test():
    print()
    print("=" * 78)
    print("3. Scanner E2E Test (R1000 universe)")
    print("=" * 78)
    print("  Running full R1000 scan with Finnhub val_mult...")
    from aggressive.scanner import scan
    candidates = scan(universe_source="r1000", min_tech_score=60,
                      top_n=15, verbose=False)
    print()
    print(f"  Found {len(candidates)} ready candidates")
    print(f"  {'Rank':>4}  {'Ticker':<6} {'Final':>6} {'Tech':>5} "
          f"{'Phase':<8} {'ValM':>5}  Warnings")
    print("  " + "-" * 90)
    for i, c in enumerate(candidates[:15], 1):
        warns = ",".join(c.fundamental_warnings[:2])[:40]
        print(f"  {i:>4}  {c.ticker:<6} {c.final_score:>6.1f} "
              f"{c.tech_score:>5.1f} {c.theme_phase:<8} "
              f"{c.val_mult:>5.2f}  {warns}")


def main():
    ok = check_finnhub_collection()
    if ok:
        from aggressive.finnhub_cache_loader import load_finnhub_live_from_cache_dir
        d = load_finnhub_live_from_cache_dir()
        check_peg_fix(d)
        print()
        ans = input("Run full R1000 scanner test now? (~3-5 min) [y/N]: ")
        if ans.strip().lower() == "y":
            run_scanner_test()
    print()
    print("Verification complete.")


if __name__ == "__main__":
    main()
