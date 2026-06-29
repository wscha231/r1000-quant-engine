#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_helpers import px_cache_name  # noqa: E402
from tools.run_alphaops_vnext_policy_replay import apply_main_fast_crash_hedge  # noqa: E402


_ENV_KEYS = {
    "PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED",
    "R1000_MAIN_FAST_CRASH_HEDGE_TICKER",
    "R1000_MAIN_FAST_CRASH_HEDGE_BENCHMARK",
    "R1000_MAIN_FAST_CRASH_HEDGE_WEIGHT",
}


def _clear_env() -> None:
    for key in _ENV_KEYS:
        os.environ.pop(key, None)


def _price_cache(root: Path, include_hedge: bool = True) -> Path:
    cache = root / "cache_prices"
    cache.mkdir(parents=True, exist_ok=True)
    idx = pd.bdate_range("2020-01-01", periods=12)
    spy = pd.DataFrame(
        {
            "Open": [100, 101, 101, 100, 100, 100, 99, 98, 96, 94, 92, 90],
            "Close": [100, 101, 101, 100, 100, 100, 99, 98, 96, 94, 92, 90],
        },
        index=idx,
    )
    spy.to_parquet(cache / px_cache_name("SPY"))
    if include_hedge:
        sh = pd.DataFrame({"Open": [20] * len(idx), "Close": [20] * len(idx)}, index=idx)
        sh.to_parquet(cache / px_cache_name("SH"))
    return cache


def _book() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "rebalance_date": "2020-01-16",
                "ticker": "AAA",
                "weight": 0.40,
                "target_weight": 0.40,
                "portfolio_kind": "main",
                "selection_reason": "baseline",
            },
            {
                "rebalance_date": "2020-01-16",
                "ticker": "BBB",
                "weight": 0.30,
                "target_weight": 0.30,
                "portfolio_kind": "main",
                "selection_reason": "baseline",
            },
            {
                "rebalance_date": "2020-01-16",
                "ticker": "CASH",
                "weight": 0.30,
                "target_weight": 0.30,
                "portfolio_kind": "main",
                "selection_reason": "baseline_cash",
            },
        ]
    )


def test_default_off_returns_exact_input() -> None:
    _clear_env()
    with tempfile.TemporaryDirectory() as tmp:
        cache = _price_cache(Path(tmp))
        book = _book()
        out, summary, actions = apply_main_fast_crash_hedge(book, "main", price_cache=cache)
    pd.testing.assert_frame_equal(out, book)
    assert summary["status"] == "disabled"
    assert actions.empty


def test_enabled_main_adds_funded_hedge_and_preserves_total_gross() -> None:
    _clear_env()
    os.environ["PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cache = _price_cache(Path(tmp))
            out, summary, actions = apply_main_fast_crash_hedge(_book(), "main", price_cache=cache)
    finally:
        _clear_env()

    assert summary["status"] == "completed"
    assert summary["hedge_dates"] == 1
    assert summary["total_gross_leq_one"] is True
    assert len(actions) == 1
    assert float(actions.iloc[0]["hedge_weight"]) == 0.075
    assert round(float(out["weight"].sum()), 10) == 1.0
    hedge = out[out["ticker"].eq("SH")]
    assert len(hedge) == 1
    assert round(float(hedge.iloc[0]["weight"]), 10) == 0.075
    aaa = out[out["ticker"].eq("AAA")].iloc[0]
    bbb = out[out["ticker"].eq("BBB")].iloc[0]
    assert float(aaa["weight"]) < 0.40
    assert float(bbb["weight"]) < 0.30
    assert bool(hedge.iloc[0]["main_fast_crash_hedge_signal"])


def test_missing_hedge_price_blocks_without_mutation() -> None:
    _clear_env()
    os.environ["PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cache = _price_cache(Path(tmp), include_hedge=False)
            book = _book()
            out, summary, actions = apply_main_fast_crash_hedge(book, "main", price_cache=cache)
    finally:
        _clear_env()
    pd.testing.assert_frame_equal(out, book)
    assert summary["status"] == "blocked"
    assert summary["reason"] == "missing_hedge_or_benchmark_price"
    assert actions.empty


def test_concentrated_is_noop_even_when_enabled() -> None:
    _clear_env()
    os.environ["PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cache = _price_cache(Path(tmp))
            book = _book()
            out, summary, actions = apply_main_fast_crash_hedge(book, "concentrated", price_cache=cache)
    finally:
        _clear_env()
    pd.testing.assert_frame_equal(out, book)
    assert summary["status"] == "skipped"
    assert summary["reason"] == "main_only"
    assert actions.empty


if __name__ == "__main__":
    try:
        test_default_off_returns_exact_input()
        test_enabled_main_adds_funded_hedge_and_preserves_total_gross()
        test_missing_hedge_price_blocks_without_mutation()
        test_concentrated_is_noop_even_when_enabled()
        print("main_fast_crash_hedge_hook_smoke: PASS")
    finally:
        _clear_env()
