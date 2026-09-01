#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_main_hedge_overlay_broker_ab as hedge  # noqa: E402


def px_cache_name(ticker: str) -> str:
    return f"{hashlib.sha1(str(ticker).upper().encode('utf-8')).hexdigest()[:16]}.parquet"


def write_px(cache: Path, ticker: str, values: list[float]) -> None:
    dates = pd.bdate_range("2020-01-01", periods=len(values))
    pd.DataFrame({"Close": values, "Open": values}, index=dates).to_parquet(cache / px_cache_name(ticker))


def sample_book() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"rebalance_date": "2020-02-28", "ticker": "AAA", "weight": 0.60, "target_weight": 0.60},
            {"rebalance_date": "2020-02-28", "ticker": "BBB", "weight": 0.30, "target_weight": 0.30},
            {"rebalance_date": "2020-02-28", "ticker": "CASH", "weight": 0.10, "target_weight": 0.10},
        ]
    )


def test_build_hedged_book_funded_total_gross() -> None:
    book = hedge.normalize_book(sample_book())
    dates = pd.bdate_range("2020-01-01", periods=60)
    spy = pd.DataFrame({"close": [100.0 - i for i in range(60)]}, index=dates)
    arm = {"arm": "fast_crash_hedge", "kind": "fast_crash", "hedge_weight": 0.075, "cash_raise": 0.0}
    out, actions = hedge.build_hedged_book(book, arm=arm, hedge_ticker="SH", benchmark_px=spy, states={})

    assert "SH" in set(out["ticker"])
    assert float(out.loc[out["ticker"].eq("SH"), "weight"].sum()) == 0.075
    assert float(out["weight"].sum()) <= 1.0000001
    assert int(actions["hedge_weight"].gt(0).sum()) == 1


def test_missing_hedge_price_blocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        alpha = latest / "alphaops_vnext"
        alpha.mkdir(parents=True)
        sample_book().to_csv(alpha / "official_main_target_book.csv", index=False)
        crisis = pd.DataFrame([{"date": "2020-02-28", "crisis_state": "GREEN"}])
        crisis.to_csv(alpha / "daily_crisis_state.csv", index=False)
        cache = root / "cache_prices"
        cache.mkdir()
        write_px(cache, "SPY", [100.0] * 80)
        payload = hedge.run(
            Namespace(
                latest_run=str(latest),
                target_book="",
                crisis_state="",
                price_cache=str(cache),
                output_dir=str(root / "out"),
                hedge_ticker="SH",
                benchmark_ticker="SPY",
                cost_bps=25.0,
                max_fill_lag_days=7,
                starting_capital=100000.0,
            )
        )
        assert payload["status"] == "blocked"
        assert payload["reason"] == "blocked_missing_hedge_price"


def test_harness_writes_summary_with_fake_broker() -> None:
    original = hedge.run_broker_replay

    def fake_broker(**kwargs):
        arm = Path(kwargs["output_dir"]).parent.name
        cagr = 0.34 if arm == "baseline_main" else 0.336
        max_dd = -0.260 if arm == "baseline_main" else -0.249
        return {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close",
            "portfolio_kind": "main",
            "cagr": cagr,
            "max_dd": max_dd,
            "sharpe": 1.23,
            "trade_count": 10,
            "total_fees_usd": 100.0,
        }

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        alpha = latest / "alphaops_vnext"
        alpha.mkdir(parents=True)
        sample_book().to_csv(alpha / "official_main_target_book.csv", index=False)
        pd.DataFrame([{"date": "2020-02-28", "crisis_state": "CRISIS_DEFENSE"}]).to_csv(alpha / "daily_crisis_state.csv", index=False)
        cache = root / "cache_prices"
        cache.mkdir()
        write_px(cache, "SPY", [100.0 - i for i in range(80)])
        write_px(cache, "SH", [100.0 + i * 0.2 for i in range(80)])
        hedge.run_broker_replay = fake_broker
        try:
            payload = hedge.run(
                Namespace(
                    latest_run=str(latest),
                    target_book="",
                    crisis_state="",
                    price_cache=str(cache),
                    output_dir=str(root / "out"),
                    hedge_ticker="SH",
                    benchmark_ticker="SPY",
                    cost_bps=25.0,
                    max_fill_lag_days=7,
                    starting_capital=100000.0,
                )
            )
        finally:
            hedge.run_broker_replay = original

        assert (root / "out" / "summary.json").exists()
        assert (root / "out" / "arm_metrics.csv").exists()
        assert payload["production_activation_allowed"] is False
        assert any(row["ab_verdict"] == "research_pass_main_mdd_candidate" for row in payload["arms"])
        loaded = json.loads((root / "out" / "summary.json").read_text(encoding="utf-8"))
        assert loaded["research_only"] is True


if __name__ == "__main__":
    test_build_hedged_book_funded_total_gross()
    test_missing_hedge_price_blocks()
    test_harness_writes_summary_with_fake_broker()
    print("main_hedge_overlay_broker_ab_smoke: PASS")
