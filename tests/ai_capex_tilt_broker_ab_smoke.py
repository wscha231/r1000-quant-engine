#!/usr/bin/env python3
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_ai_capex_tilt_broker_ab as ab  # noqa: E402


def _book() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date in ["2020-01-31", "2024-07-31"]:
        rows.extend(
            [
                {"rebalance_date": date, "ticker": "CASH", "weight": 0.10, "target_weight": 0.10, "sector": "Cash"},
                {
                    "rebalance_date": date,
                    "ticker": "MEM",
                    "Name": "Memory Leader",
                    "weight": 0.25,
                    "target_weight": 0.25,
                    "sector": "Information Technology",
                    "industry_group": "Semiconductor Memory",
                    "theme": "HBM memory tight supply",
                    "rs_benchmark_3m": 0.20,
                    "actual_results_score": 1.0,
                    "period_forward_return": 0.20,
                    "effective_single_weight_cap": 0.30,
                },
                {
                    "rebalance_date": date,
                    "ticker": "NET",
                    "Name": "Networking Leader",
                    "weight": 0.25,
                    "target_weight": 0.25,
                    "sector": "Information Technology",
                    "industry_group": "Communication Equipment",
                    "theme": "AI ethernet networking",
                    "rs_benchmark_3m": 0.18,
                    "actual_results_score": 0.0,
                    "period_forward_return": 0.15,
                    "effective_single_weight_cap": 0.30,
                },
                {
                    "rebalance_date": date,
                    "ticker": "OTHER",
                    "Name": "Other Stock",
                    "weight": 0.40,
                    "target_weight": 0.40,
                    "sector": "Industrials",
                    "industry_group": "Machinery",
                    "rs_benchmark_3m": -0.02,
                    "actual_results_score": 0.0,
                    "period_forward_return": -0.05,
                    "effective_single_weight_cap": 0.50,
                },
            ]
        )
    return pd.DataFrame(rows)


def test_generate_arm_book_preserves_ticker_set_and_cash() -> None:
    book = _book()
    arm = next(item for item in ab.ARMS if item["arm"] == "ai_bottleneck_momentum_tilt15")
    generated, date_telemetry, stock_telemetry, signal_meta = ab.generate_arm_book(
        book,
        arm,
        default_single_cap=0.30,
        earnings_signals=pd.DataFrame(),
    )

    assert set(generated["ticker"].astype(str)) == set(book["ticker"].astype(str))
    assert not date_telemetry.empty
    assert not stock_telemetry.empty
    assert signal_meta["earnings_signal_status"] == "missing_or_empty"
    cash = generated[generated["ticker"].eq("CASH")]
    assert round(float(cash["target_weight"].sum()), 10) == 0.20
    assert int(date_telemetry["eligible_count"].sum()) == 4
    assert float(date_telemetry["total_abs_weight_delta"].sum()) > 0


def test_earnings_arm_is_narrower_than_momentum_only() -> None:
    book = _book()
    momentum = next(item for item in ab.ARMS if item["arm"] == "ai_bottleneck_momentum_tilt15")
    earnings = next(item for item in ab.ARMS if item["arm"] == "ai_bottleneck_momentum_earnings_tilt15")
    _m_book, m_dates, _m_stocks, _ = ab.generate_arm_book(book, momentum, default_single_cap=0.30, earnings_signals=pd.DataFrame())
    _e_book, e_dates, _e_stocks, _ = ab.generate_arm_book(book, earnings, default_single_cap=0.30, earnings_signals=pd.DataFrame())

    assert int(m_dates["eligible_count"].sum()) > int(e_dates["eligible_count"].sum())
    assert int(e_dates["eligible_count"].sum()) == 2


def test_harness_writes_summary_with_fake_broker() -> None:
    original = ab.run_broker_replay

    def fake_broker(**kwargs):
        arm = Path(kwargs["output_dir"]).parent.name
        cagr = {
            "baseline": 0.4624,
            "ai_bottleneck_momentum_tilt15": 0.4700,
            "ai_bottleneck_momentum_earnings_tilt15": 0.4640,
        }[arm]
        return {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close",
            "cagr": cagr,
            "max_dd": -0.2582,
            "sharpe": 1.4,
            "years": 7.05,
            "start_date": "2019-06-03",
            "end_date": "2026-06-22",
            "avg_cash_weight": 0.10,
            "trade_count": 10,
            "total_fees_usd": 100.0,
            "gross_traded_usd": 10000.0,
            "broker_metrics_path": str(Path(kwargs["output_dir"]) / "metrics.json"),
            "windows": {"oos": {"cagr": cagr, "max_dd": -0.10}},
        }

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        (latest / "alphaops_vnext").mkdir(parents=True)
        target = latest / "alphaops_vnext" / "official_concentrated_target_book.csv"
        _book().to_csv(target, index=False)
        (root / "cache_prices").mkdir()
        ab.run_broker_replay = fake_broker
        try:
            payload = ab.run(
                Namespace(
                    latest_run=str(latest),
                    target_book="",
                    portfolio_kind="concentrated",
                    price_cache=str(root / "cache_prices"),
                    earnings_signals="",
                    output_dir=str(root / "ab"),
                    cost_bps=25.0,
                    max_fill_lag_days=7,
                    starting_capital=100000.0,
                    single_cap=0.30,
                )
            )
        finally:
            ab.run_broker_replay = original

        assert (root / "ab" / "concentrated" / "summary.json").exists()
        loaded = json.loads((root / "ab" / "concentrated" / "summary.json").read_text(encoding="utf-8"))
        assert loaded["policy_candidates"]
        assert payload["production_promotion_allowed"] is False


if __name__ == "__main__":
    test_generate_arm_book_preserves_ticker_set_and_cash()
    test_earnings_arm_is_narrower_than_momentum_only()
    test_harness_writes_summary_with_fake_broker()
    print("ai_capex_tilt_broker_ab_smoke: PASS")
