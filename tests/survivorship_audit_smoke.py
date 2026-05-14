#!/usr/bin/env python3
"""Smoke test for tools/run_survivorship_audit.py.

Verifies the audit:
  1. Handles missing membership file gracefully (status='blocked').
  2. Correctly identifies delisted vs survivor tickers from a synthetic
     membership table.
  3. Reads price cache parquet for coverage stats.
  4. Computes coverage_ratio and hard_gate_flip_eligible flag.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_survivorship_audit import run_audit, safe_load_membership, price_cache_coverage  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2019-01-02") -> None:
    """Write a synthetic price parquet at cache_dir/{ticker}.parquet."""
    idx = pd.bdate_range(start=start, periods=len(closes))
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1_000_000] * len(closes)}, index=idx)
    df.to_parquet(cache_dir / f"{ticker}.parquet")


def test_missing_membership_returns_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        out = root / "audit.json"
        payload = run_audit(
            membership_path=root / "no_such_file.csv",
            price_cache=cache,
            output_path=out,
        )
        assert payload["status"] == "blocked", payload
        assert payload["delisted_count"] == 0
        assert out.exists()


def test_distinguishes_delisted_from_survivor() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        # 3 tickers in past universe, 2 still survive at latest, 1 delisted.
        member_df = pd.DataFrame([
            {"ticker": "ALIVE1", "rebalance_date": "2025-01-31"},
            {"ticker": "ALIVE2", "rebalance_date": "2025-01-31"},
            {"ticker": "DEAD1",  "rebalance_date": "2025-01-31"},
            {"ticker": "ALIVE1", "rebalance_date": "2025-02-28"},
            {"ticker": "ALIVE2", "rebalance_date": "2025-02-28"},
            # DEAD1 dropped at latest date.
        ])
        membership_path = root / "membership.csv"
        member_df.to_csv(membership_path, index=False)
        # Write price caches: full coverage for ALIVE1, sparse for DEAD1.
        _write_px(cache, "ALIVE1", [100.0] * 300)
        _write_px(cache, "ALIVE2", [100.0] * 300)
        _write_px(cache, "DEAD1", [100.0] * 100)  # below default 252 min_cache_days
        out = root / "audit.json"
        payload = run_audit(
            membership_path=membership_path,
            price_cache=cache,
            output_path=out,
            min_tenure_months=1,
            min_cache_days=252,
            min_delisted_count=1,
            coverage_threshold=0.85,
        )
        assert payload["status"] == "completed", payload
        assert payload["delisted_count"] == 1, payload
        assert payload["survivor_count"] == 2, payload
        assert payload["delisted_covered_count"] == 0, payload  # DEAD1 sparse
        assert payload["delisted_uncovered_count"] == 1, payload
        assert payload["coverage_ratio"] == 0.0, payload
        assert payload["hard_gate_flip_eligible"] is False, payload


def test_hard_gate_eligible_when_coverage_passes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        # Generate 100 delisted tickers (DEAD001..DEAD100) all with adequate cache.
        rows = []
        for i in range(1, 101):
            rows.append({"ticker": f"DEAD{i:03d}", "rebalance_date": "2024-01-31"})
        # 5 survivors in 2025.
        for i in range(1, 6):
            rows.append({"ticker": f"ALIVE{i:03d}", "rebalance_date": "2024-01-31"})
            rows.append({"ticker": f"ALIVE{i:03d}", "rebalance_date": "2025-01-31"})
        member_df = pd.DataFrame(rows)
        membership_path = root / "membership.csv"
        member_df.to_csv(membership_path, index=False)
        # All DEAD tickers have full coverage.
        for i in range(1, 101):
            _write_px(cache, f"DEAD{i:03d}", [100.0] * 300)
        out = root / "audit.json"
        payload = run_audit(
            membership_path=membership_path,
            price_cache=cache,
            output_path=out,
            min_tenure_months=1,
            min_cache_days=252,
            min_delisted_count=100,
            coverage_threshold=0.85,
        )
        assert payload["status"] == "completed", payload
        assert payload["delisted_count"] == 100, payload
        assert payload["delisted_covered_count"] == 100, payload
        assert payload["coverage_ratio"] == 1.0, payload
        assert payload["hard_gate_flip_eligible"] is True, payload


def test_price_cache_coverage_handles_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        cov = price_cache_coverage(cache, "NOTFOUND")
        assert cov["has_data"] is False
        assert cov["num_days"] == 0


def main() -> int:
    test_missing_membership_returns_blocked()
    test_distinguishes_delisted_from_survivor()
    test_hard_gate_eligible_when_coverage_passes()
    test_price_cache_coverage_handles_missing()
    print("survivorship_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
