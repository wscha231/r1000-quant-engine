#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_concentrated_score_sizing_broker_ab as ab  # noqa: E402
from tools.concentrated_score_sizing_reweight import reweight_concentrated_records  # noqa: E402


def _records() -> list[dict[str, object]]:
    return [
        {"ticker": "LOW", "weight": 0.30, "target_weight": 0.30, "alphaops_vnext_score": 1.0},
        {"ticker": "MID", "weight": 0.25, "target_weight": 0.25, "alphaops_vnext_score": 2.0},
        {"ticker": "HIGH", "weight": 0.20, "target_weight": 0.20, "alphaops_vnext_score": 3.0},
    ]


def test_helper_preserves_gross_and_selected_tickers() -> None:
    rows, telemetry = reweight_concentrated_records(_records(), cap_mode="telemetry_only")

    assert [row["ticker"] for row in rows] == ["LOW", "MID", "HIGH"]
    assert round(sum(float(row["weight"]) for row in rows), 10) == 0.75
    assert telemetry["status"] == "applied"
    assert telemetry["stock_gross_before"] == telemetry["stock_gross_after"]


def test_cap30_waterfill_preserves_gross_when_feasible() -> None:
    rows, telemetry = reweight_concentrated_records(_records(), cap_mode="cap30_waterfill", single_cap=0.30)

    assert max(float(row["weight"]) for row in rows) <= 0.3000000001
    assert round(sum(float(row["weight"]) for row in rows), 10) == 0.75
    assert telemetry["gross_preservation_status"] == "gross_preserved"
    assert telemetry["cap_breach_count"] == 0


def test_cap30_infeasible_moves_residual_to_cash_status() -> None:
    rows, telemetry = reweight_concentrated_records(
        [
            {"ticker": "A", "weight": 0.50, "target_weight": 0.50, "alphaops_vnext_score": 1.0},
            {"ticker": "B", "weight": 0.45, "target_weight": 0.45, "alphaops_vnext_score": 2.0},
        ],
        cap_mode="cap30_waterfill",
        single_cap=0.30,
    )

    assert max(float(row["weight"]) for row in rows) <= 0.3000000001
    assert round(float(telemetry["cash_residual_weight"]), 10) == 0.35
    assert telemetry["gross_preservation_status"] == "cap_infeasible_cash_residual"


def test_constant_signal_returns_noop() -> None:
    records = [
        {"ticker": "A", "weight": 0.20, "target_weight": 0.20, "alphaops_vnext_score": 1.0},
        {"ticker": "B", "weight": 0.30, "target_weight": 0.30, "alphaops_vnext_score": 1.0},
    ]
    rows, telemetry = reweight_concentrated_records(records)

    assert rows == records
    assert telemetry["status"] == "no_signal_variation"


def _book() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date in ["2020-01-31", "2020-02-28"]:
        rows.extend(
            [
                {"rebalance_date": date, "ticker": "CASH", "weight": 0.25, "target_weight": 0.25, "alphaops_vnext_score": ""},
                {"rebalance_date": date, "ticker": "LOW", "weight": 0.30, "target_weight": 0.30, "alphaops_vnext_score": 1.0},
                {"rebalance_date": date, "ticker": "MID", "weight": 0.25, "target_weight": 0.25, "alphaops_vnext_score": 2.0},
                {"rebalance_date": date, "ticker": "HIGH", "weight": 0.20, "target_weight": 0.20, "alphaops_vnext_score": 3.0},
            ]
        )
    return pd.DataFrame(rows)


def test_generated_target_book_keeps_dates_and_ticker_set() -> None:
    book = _book()
    arm = {
        "arm": "blend75_rank_power1_5_cap30",
        "signal": "alphaops_vnext_score",
        "blend": 0.75,
        "rank_power": 1.5,
        "cap_mode": "cap30_waterfill",
    }
    generated, date_telemetry, stock_telemetry = ab.generate_arm_book(book, arm, single_cap=0.30)

    assert set(generated["rebalance_date"].astype(str)) == set(book["rebalance_date"].astype(str))
    assert set(generated["ticker"].astype(str)) == set(book["ticker"].astype(str))
    assert not date_telemetry.empty
    assert not stock_telemetry.empty


def test_delta_math_and_verdict_classification() -> None:
    rows = [
        {"arm": "baseline", "metric_mode": "broker_ledger_next_close", "cagr": 0.46, "max_dd": -0.2582, "sharpe": 1.4, "years": 7.05, "avg_cash_weight": 0.05, "trade_count": 10, "total_fees_usd": 100.0, "gross_traded_usd": 10000.0, "total_abs_weight_delta": 0.0, "cap_breach_count": 0},
        {"arm": "candidate", "metric_mode": "broker_ledger_next_close", "cagr": 0.466, "max_dd": -0.2580, "sharpe": 1.5, "years": 7.05, "avg_cash_weight": 0.05, "trade_count": 11, "total_fees_usd": 105.0, "gross_traded_usd": 10500.0, "total_abs_weight_delta": 1.0, "cap_breach_count": 0},
    ]
    rows = ab.add_deltas(rows)

    assert round(float(rows[1]["delta_cagr_pp"]), 4) == 0.6
    assert ab.classify(rows[1], rows[0]) == "research_pass_policy_candidate"


def test_harness_writes_summary_with_fake_broker() -> None:
    original = ab.run_broker_replay

    def fake_broker(**kwargs):
        arm = Path(kwargs["output_dir"]).parent.name
        cagr = {
            "baseline": 0.4624,
            "blend75_rank_power1_5_uncapped": 0.4724,
            "blend75_rank_power1_5_cap30": 0.4680,
            "blend50_rank_power1_5_cap30": 0.4650,
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
            "avg_cash_weight": 0.25,
            "trade_count": 10,
            "total_fees_usd": 100.0,
            "gross_traded_usd": 10000.0,
            "broker_metrics_path": str(Path(kwargs["output_dir"]) / "metrics.json"),
            "windows": {
                "oos": {"cagr": cagr, "max_dd": -0.10},
                "oos2": {"cagr": cagr, "max_dd": -0.12},
            },
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
                    price_cache=str(root / "cache_prices"),
                    output_dir=str(root / "ab"),
                    cost_bps=25.0,
                    max_fill_lag_days=7,
                    starting_capital=100000.0,
                    single_cap=0.30,
                )
            )
        finally:
            ab.run_broker_replay = original

        assert (root / "ab" / "summary.json").exists()
        assert (root / "ab" / "report.md").exists()
        assert payload["policy_candidates"]
        loaded = json.loads((root / "ab" / "summary.json").read_text(encoding="utf-8"))
        assert loaded["production_promotion_allowed"] is False


if __name__ == "__main__":
    test_helper_preserves_gross_and_selected_tickers()
    test_cap30_waterfill_preserves_gross_when_feasible()
    test_cap30_infeasible_moves_residual_to_cash_status()
    test_constant_signal_returns_noop()
    test_generated_target_book_keeps_dates_and_ticker_set()
    test_delta_math_and_verdict_classification()
    test_harness_writes_summary_with_fake_broker()
    print("concentrated_score_sizing_broker_ab_smoke: PASS")
