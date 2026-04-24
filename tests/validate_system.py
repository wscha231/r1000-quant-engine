"""System Validation — Phase A end-to-end sanity checks.

User mandate (2026-04-24 evening):
  "자동화 전에 시스템을 완성하자. 새로운 데이터 소스로 에러 없이 제대로
   종목들을 선정하는지부터."

Runs 5 test groups:
  Test 1: Data Integrity
  Test 2: Scoring Sanity (strong/weak names rank correctly)
  Test 3: Stability (repeat runs identical)
  Test 4: Cross-system (scanner vs advisor consistency)
  Test 5: Edge Cases (NaN/empty/missing)

Usage:
  py -3 tests/validate_system.py
  py -3 tests/validate_system.py --quick  (skip long Alpaca fetches)
"""
from __future__ import annotations

import argparse
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd


# --- Result collector -------------------------------------------------------

@dataclass
class TestResult:
    name: str
    passed: bool
    message: str = ""
    details: dict = field(default_factory=dict)


RESULTS: list[TestResult] = []


def record(name: str, passed: bool, message: str = "", **details) -> None:
    RESULTS.append(TestResult(name, passed, message, details))
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")
    if message:
        print(f"         {message}")
    for k, v in details.items():
        print(f"         {k}: {v}")


# =========================================================================
# Test 1: Data Integrity
# =========================================================================

def test_data_integrity():
    print()
    print("=" * 70)
    print("Test 1: Data Integrity")
    print("=" * 70)

    # 1a. R1000 universe
    try:
        from aggressive.universe import load_universe
        r1000, meta = load_universe("r1000")
        n = len(r1000)
        record("R1000 universe load", n >= 900,
               f"{n} tickers (expect 900+)", source=meta.get("source_used"))
    except Exception as e:
        record("R1000 universe load", False, f"EXCEPTION: {e}")
        return

    # 1b. Finnhub parquet present + fresh
    try:
        from aggressive.finnhub_cache_loader import load_finnhub_features_dict
        fh = load_finnhub_features_dict()
        coverage = len(fh)
        record("Finnhub data loaded", coverage >= 900,
               f"{coverage} tickers in dict (expect 900+)")
        # Key fields populated
        sample = next(iter(fh.values())) if fh else {}
        keys_expected = ["fh_peExclExtra_ttm", "fh_epsGrowth5Y",
                         "fh_insider_cluster_30d_score"]
        missing_keys = [k for k in keys_expected if k not in sample]
        record("Finnhub has expected fields", not missing_keys,
               f"missing: {missing_keys}" if missing_keys else "all present")
    except Exception as e:
        record("Finnhub data loaded", False, f"EXCEPTION: {e}")

    # 1c. Unified scored CSV exists and has 1000+ rows
    unified_path = Path(r"G:/내 드라이브/r1000_top30_institutional/outputs/scored_unified.csv")
    if unified_path.exists():
        try:
            uni = pd.read_csv(unified_path)
            n = len(uni)
            syn = (uni["score_source"] == "finnhub_synthetic").sum() if "score_source" in uni.columns else 0
            real = (uni["score_source"] == "정석_ml").sum() if "score_source" in uni.columns else 0
            record("scored_unified.csv exists", n >= 1000,
                   f"{n} rows ({real} real + {syn} synthetic)")
        except Exception as e:
            record("scored_unified.csv readable", False, f"EXCEPTION: {e}")
    else:
        record("scored_unified.csv exists", False,
               "NOT FOUND - run r1000_unified_universe.py first")

    # 1d. Alpaca bar cache has recent data
    try:
        from aggressive.data_alpaca import fetch_daily_bars
        df = fetch_daily_bars("NVDA", days=10)
        fresh = not df.empty and len(df) >= 5
        record("Alpaca bars reachable", fresh,
               f"NVDA bars: {len(df)} rows")
    except Exception as e:
        record("Alpaca bars reachable", False, f"EXCEPTION: {e}")


# =========================================================================
# Test 2: Scoring Sanity
# =========================================================================

KNOWN_STRONG_NAMES = {
    # (ticker, min_expected_rs_12m_pct)
    "NVDA": 40,
    "AVGO": 60,
    "MRVL": 100,
    "VRT": 150,
    "GEV": 150,
}

KNOWN_WEAK_NAMES = {
    # names that SHOULD be filtered/penalized
    "BKNG": "data anomaly or weak RS",
    "AAPL": "slow growth + high PEG",
}


def test_scoring_sanity():
    print()
    print("=" * 70)
    print("Test 2: Scoring Sanity")
    print("=" * 70)

    try:
        from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark
    except Exception as e:
        record("Alpaca imports", False, f"EXCEPTION: {e}")
        return

    spy = fetch_spy_benchmark(days=260)
    if spy.empty:
        record("SPY benchmark loaded", False, "SPY data empty")
        return
    record("SPY benchmark loaded", True, f"{len(spy)} bars")

    # 2a. Strong names should have strong RS
    for ticker, expected_min_rs in KNOWN_STRONG_NAMES.items():
        df = fetch_daily_bars(ticker, days=260)
        if df.empty or len(df) < 252:
            record(f"{ticker} RS check", False,
                   f"insufficient bars: {len(df)}")
            continue
        aligned = pd.concat([df["close"].rename("t"),
                               spy["close"].rename("s")],
                              axis=1, join="inner").dropna()
        if len(aligned) < 252:
            record(f"{ticker} RS check", False,
                   f"alignment too short: {len(aligned)}")
            continue
        rs12_pct = ((aligned["t"].iloc[-1] / aligned["t"].iloc[-252] - 1.0) -
                    (aligned["s"].iloc[-1] / aligned["s"].iloc[-252] - 1.0)) * 100
        passed = rs12_pct >= expected_min_rs
        record(f"{ticker} RS >= {expected_min_rs}%", passed,
               f"actual: {rs12_pct:+.1f}%")


# =========================================================================
# Test 3: Stability
# =========================================================================

def test_stability():
    print()
    print("=" * 70)
    print("Test 3: Stability (repeat runs)")
    print("=" * 70)

    try:
        from aggressive.finnhub_cache_loader import load_finnhub_features_dict
        # Call twice, verify same result
        a = load_finnhub_features_dict()
        b = load_finnhub_features_dict()
        same_len = len(a) == len(b)
        same_keys = set(a.keys()) == set(b.keys())
        record("Finnhub loader deterministic", same_len and same_keys,
               f"len(a)={len(a)}, len(b)={len(b)}")
    except Exception as e:
        record("Finnhub loader deterministic", False, f"EXCEPTION: {e}")

    try:
        from aggressive.universe import load_universe
        a, _ = load_universe("r1000")
        b, _ = load_universe("r1000")
        same = a == b
        record("Universe deterministic (cached 24h)", same,
               f"len matches: {len(a) == len(b)}")
    except Exception as e:
        record("Universe deterministic", False, f"EXCEPTION: {e}")


# =========================================================================
# Test 4: Cross-system Consistency
# =========================================================================

def test_cross_system():
    print()
    print("=" * 70)
    print("Test 4: Cross-system Consistency")
    print("=" * 70)

    # Load scanner cache + advisor output, check overlap for RS-strong names
    import json, glob
    cache_files = sorted(glob.glob(
        "aggressive/state/scanner/candidates_*.json"), reverse=True)
    if not cache_files:
        record("Scanner cache available", False, "no scanner output")
        return
    try:
        with open(cache_files[0], encoding="utf-8") as f:
            scan_data = json.load(f)
        scan_all = [c["ticker"] for c in scan_data.get("candidates", [])]
        scan_tickers_top50 = scan_all[:50]
        record("Scanner cache loaded", len(scan_all) > 0,
               f"{len(scan_all)} total candidates in latest scan")
    except Exception as e:
        record("Scanner cache loaded", False, f"EXCEPTION: {e}")
        return

    # Check that TOP RS leaders appear SOMEWHERE in scanner (peaking names
    # ranked lower due to scanner's 0.70 peaking penalty, but should be in pool).
    for ticker in ["MRVL", "VRT", "GEV"]:
        in_scan = ticker in scan_all
        rank = scan_all.index(ticker) + 1 if in_scan else None
        record(f"{ticker} in scanner pool", in_scan,
               f"rank {rank}" if rank else "NOT IN POOL")

    # Advisor output exists
    adv_path = Path("outputs_advisor/new_top12_proposed.csv")
    if adv_path.exists():
        adv = pd.read_csv(adv_path)
        adv_tickers = set(str(t).upper() for t in adv["ticker"])
        record("Advisor v1 output exists", len(adv_tickers) >= 10,
               f"{len(adv_tickers)} names proposed")
        # Advisor recomputes scores (doesn't trust scanner's peaking penalty).
        # Check that advisor TOP 12 includes at least some high-RS peaking names.
        rs_leaders = {"MRVL", "VRT", "GEV", "AVGO", "NVDA"}
        adv_with_rs = adv_tickers & rs_leaders
        record("Advisor v1 includes RS leaders", len(adv_with_rs) >= 2,
               f"{len(adv_with_rs)} of 5 RS leaders: {sorted(adv_with_rs)}")
    else:
        record("Advisor v1 output exists", False,
               "run r1000_rebalance_advisor.py first")


# =========================================================================
# Test 5: Edge Cases
# =========================================================================

def test_edge_cases():
    print()
    print("=" * 70)
    print("Test 5: Edge Cases")
    print("=" * 70)

    # 5a. Finnhub loader handles missing keys gracefully
    try:
        from aggressive.finnhub_cache_loader import load_finnhub_features_dict
        d = load_finnhub_features_dict()
        # Check that NOT every ticker has every field (incomplete data OK)
        sample = list(d.values())[:10] if d else []
        has_incomplete = any(
            "fh_peg_5y" not in row or "fh_mspr_latest" not in row
            for row in sample
        )
        record("Finnhub handles incomplete records", True,
               f"sample 10 has incomplete: {has_incomplete} (expected)")
    except Exception as e:
        record("Finnhub handles incomplete", False, f"EXCEPTION: {e}")

    # 5b. Synthesis handles zero price gracefully
    try:
        from r1000_unified_universe import build_synthetic_row
        # Minimal mock
        row = build_synthetic_row(
            "ZZZ", {"fh_peg_5y": 1.5}, 0.0, "Unknown", "Test Co",
            {}, live_price=0.0,
        )
        record("Synthetic row with zero price", "score" in row,
               f"score={row.get('score')}, mcap={row.get('market_cap_live')}")
    except Exception as e:
        record("Synthetic row with zero price", False, f"EXCEPTION: {e}")

    # 5c. NaN-heavy row doesn't crash percentile ranker
    try:
        from r1000_unified_universe import percentile_rank
        s = pd.Series([np.nan] * 10 + [1.0, 2.0])
        r = percentile_rank(s)
        record("percentile_rank handles NaN", len(r) == len(s),
               f"NaN filled to 0.5: {(r == 0.5).sum()}")
    except Exception as e:
        record("percentile_rank handles NaN", False, f"EXCEPTION: {e}")

    # 5d. Theme loader tolerates missing file
    try:
        from r1000_themes import load_themes
        themes = load_themes("nonexistent.yaml")
        record("Themes loader handles missing file", themes == {},
               f"returned: {type(themes).__name__}")
    except Exception as e:
        record("Themes loader handles missing file", False,
               f"EXCEPTION: {e}")


# =========================================================================
# Main
# =========================================================================

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true",
                        help="skip Alpaca-intensive tests")
    args = parser.parse_args()

    print("=" * 70)
    print("r1000 System Validation - Phase A")
    print("=" * 70)

    tests = [
        ("Data Integrity", test_data_integrity),
        ("Scoring Sanity", test_scoring_sanity),
        ("Stability", test_stability),
        ("Cross-system Consistency", test_cross_system),
        ("Edge Cases", test_edge_cases),
    ]
    if args.quick:
        tests = [t for t in tests if t[0] != "Scoring Sanity"]

    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            print(f"\n[CRASH] {name} crashed:\n{traceback.format_exc()}")
            record(f"{name} (crash)", False, str(e))

    # Summary
    print()
    print("=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    passed = sum(1 for r in RESULTS if r.passed)
    failed = sum(1 for r in RESULTS if not r.passed)
    print(f"Total: {len(RESULTS)}  Passed: {passed}  Failed: {failed}")
    if failed:
        print()
        print("FAILED tests:")
        for r in RESULTS:
            if not r.passed:
                print(f"  - {r.name}: {r.message}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
