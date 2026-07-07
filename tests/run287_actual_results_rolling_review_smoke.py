#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_run287_actual_results_rolling_review as mod  # noqa: E402


class Args:
    pass


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_equity(arm: str) -> pd.DataFrame:
    dates = list(pd.date_range("2020-01-31", "2026-06-30", freq="ME"))
    dates.append(pd.Timestamp("2026-07-06"))
    cutoff = pd.Timestamp("2024-06-30")
    pre = [date for date in dates if date <= cutoff]
    post = [date for date in dates if date > cutoff]
    rows = []
    for date in dates:
        if arm == "actual_results_top_quintile_tilt10":
            if date <= cutoff:
                idx = pre.index(date)
                equity = 100000.0 + (650000.0 - 100000.0) * idx / max(len(pre) - 1, 1)
            else:
                idx = post.index(date)
                equity = 650000.0 + (750000.0 - 650000.0) * idx / max(len(post) - 1, 1)
        else:
            if date <= cutoff:
                idx = pre.index(date)
                equity = 100000.0 + (300000.0 - 100000.0) * idx / max(len(pre) - 1, 1)
            else:
                idx = post.index(date)
                equity = 300000.0 + (600000.0 - 300000.0) * idx / max(len(post) - 1, 1)
        rows.append({"date": date.date().isoformat(), "equity_usd": equity})
    return pd.DataFrame(rows)


def fake_replay(**kwargs):
    arm = kwargs["target_book"].parent.name
    portfolio_kind = kwargs.get("portfolio_kind", "main")
    out = kwargs["output_dir"]
    out.mkdir(parents=True, exist_ok=True)
    make_equity(arm).to_csv(out / "equity_curve.csv", index=False)
    is_candidate = arm == "actual_results_top_quintile_tilt10"
    if portfolio_kind == "concentrated":
        if arm == "baseline":
            cagr, max_dd = 0.4866, -0.2296
        elif arm == "actual_results_top_quintile_tilt05":
            cagr, max_dd = 0.4828, -0.2319
        else:
            cagr, max_dd = 0.4781, -0.2339
        return {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close_cash_carry",
            "cagr": cagr,
            "max_dd": max_dd,
            "sharpe": 1.5,
            "years": 6.4,
            "start_date": "2020-01-31",
            "end_date": "2026-07-06",
            "days": 2350,
            "starting_capital_usd": 100000.0,
            "ending_capital_usd": 1200000.0,
            "avg_cash_weight": 0.40,
            "trade_count": 10,
            "total_fees_usd": 100.0,
            "gross_traded_usd": 10000.0,
            "cash_interest_accrued_usd": 1000.0,
            "windows": {
                "is": {"status": "completed", "cagr": cagr - 0.05, "max_dd": max_dd, "years": 4.4},
                "oos": {"status": "completed", "cagr": cagr + 0.10, "max_dd": max_dd - 0.005, "years": 2.0},
                "oos2": {"status": "completed", "cagr": cagr + 0.02, "max_dd": max_dd - 0.005, "years": 3.5},
            },
        }
    return {
        "status": "completed",
        "metric_mode": "broker_ledger_next_close_cash_carry",
        "cagr": 0.36 if is_candidate else 0.32,
        "max_dd": -0.10,
        "sharpe": 1.2,
        "years": 6.4,
        "start_date": "2020-01-31",
        "end_date": "2026-07-06",
        "days": 2350,
        "starting_capital_usd": 100000.0,
        "ending_capital_usd": 750000.0 if is_candidate else 600000.0,
        "avg_cash_weight": 0.20,
        "trade_count": 10,
        "total_fees_usd": 100.0,
        "gross_traded_usd": 10000.0,
        "cash_interest_accrued_usd": 1000.0,
        "windows": {
            "is": {
                "status": "completed",
                "cagr": 0.50 if is_candidate else 0.28,
                "max_dd": -0.10,
                "years": 4.4,
                "start_date": "2020-01-31",
                "end_date": "2024-06-30",
                "days": 1612,
                "starting_capital_usd": 100000.0,
                "ending_capital_usd": 650000.0 if is_candidate else 300000.0,
            },
            "oos": {
                "status": "completed",
                "cagr": 0.10 if is_candidate else 0.40,
                "max_dd": -0.08,
                "years": 2.0,
                "start_date": "2024-07-01",
                "end_date": "2026-07-06",
                "days": 735,
                "starting_capital_usd": 650000.0 if is_candidate else 300000.0,
                "ending_capital_usd": 750000.0 if is_candidate else 600000.0,
            },
            "oos2": {
                "status": "completed",
                "cagr": 0.30 if is_candidate else 0.29,
                "max_dd": -0.08,
                "years": 3.5,
                "start_date": "2023-01-03",
                "end_date": "2026-07-06",
                "days": 1278,
                "starting_capital_usd": 250000.0 if is_candidate else 180000.0,
                "ending_capital_usd": 750000.0 if is_candidate else 600000.0,
            },
        },
    }


def test_actual_results_rolling_review_mixed_and_research_only() -> None:
    original_replay = mod.run_broker_replay
    mod.run_broker_replay = fake_replay
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / "latest" / "alphaops_vnext"
            latest.mkdir(parents=True)
            rows = []
            for date in ["2020-01-31", "2022-01-31", "2024-06-30", "2025-01-31", "2026-06-30"]:
                rows.append(
                    {
                        "rebalance_date": date,
                        "ticker": "CASH",
                        "weight": 0.20,
                        "target_weight": 0.20,
                        "actual_results_score": "",
                        "portfolio_kind": "main",
                    }
                )
                for idx, score in enumerate([0.1, 0.3, 0.5, 0.7, 0.9]):
                    rows.append(
                        {
                            "rebalance_date": date,
                            "ticker": f"T{idx}",
                            "weight": 0.16,
                            "target_weight": 0.16,
                            "actual_results_score": score,
                            "effective_single_weight_cap": 0.30,
                            "portfolio_kind": "main",
                        }
                    )
            pd.DataFrame(rows).to_csv(latest / "official_main_target_book.csv", index=False)
            parity = root / "parity" / "summary.json"
            survivorship = root / "survivorship" / "summary.json"
            write_json(parity, {"runner_parity_status": "parity_documented_gap", "runner_parity_reason": "fixture"})
            write_json(
                survivorship,
                {
                    "label": "proxy",
                    "method": "fixture",
                    "unmeasured_component": "delisted_exclusion",
                    "survivorship_inflation_estimate_cagr_pp": 0.0,
                    "survivorship_inflation_estimate": {
                        "cagr_pp_lower_bound": 0.0,
                        "label": "proxy",
                        "method": "fixture",
                        "unmeasured_component": "delisted_exclusion",
                    },
                },
            )
            args = Args()
            args.latest_run = str(root / "latest")
            args.target_book = ""
            args.portfolio_kind = "main"
            args.target_arm = "actual_results_top_quintile_tilt10"
            args.price_cache = str(root / "cache_prices")
            args.output_dir = str(root / "out")
            args.cost_bps = 25.0
            args.max_fill_lag_days = 7
            args.starting_capital = 100000.0
            args.single_cap = 0.30
            args.cash_carry_mode = "risk_free_rate"
            args.cash_rate_source = "DGS3MO"
            args.cash_rate_path = ""
            args.cash_rate_lag_days = 1
            args.cash_carry_haircut_bps = 50.0
            args.cash_carry_day_count = 365
            args.replay_end_date = "2026-07-06"
            args.official_baseline_end_date = "2026-07-06"
            args.rolling_months = [12, 24, 36]
            args.parity_summary = str(parity)
            args.survivorship_summary = str(survivorship)
            payload = mod.run(args)
            assert payload["status"] == "completed"
            assert payload["decision_label"] == "mixed_headline_pass_oos_cagr_worse"
            assert payload["research_only"] is True
            assert payload["candidate_allowed"] is False
            assert payload["fullrun_dispatched"] is False
            assert payload["new_alpha_hook_added"] is False
            assert payload["threshold_tuning_performed"] is False
            assert payload["production_promotion_allowed"] is False
            assert payload["live_trading_enabled"] is False
            assert payload["runner_parity_status"] == "parity_documented_gap"
            assert payload["survivorship_inflation_label"] == "proxy"
            assert payload["measurement_contract_acceptance_allowed"] is False
            assert "runner_parity_not_exact" in payload["measurement_contract_acceptance_blockers"]
            full = next(row for row in payload["window_rows"] if row["window_group"] == "fixed" and row["window"] == "full")
            oos = next(row for row in payload["window_rows"] if row["window_group"] == "fixed" and row["window"] == "oos_from_2024_07_01")
            assert full["candidate_contract_pass"] is True
            assert oos["delta_cagr_pp"] < -0.25
            assert (root / "out" / "summary.json").exists()
            assert (root / "out" / "window_metrics.csv").exists()
            assert (root / "out" / "report.md").exists()
    finally:
        mod.run_broker_replay = original_replay


def test_concentrated_actual_results_rolling_review_rejects_below_50() -> None:
    original_replay = mod.run_broker_replay
    mod.run_broker_replay = fake_replay
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / "latest" / "alphaops_vnext"
            latest.mkdir(parents=True)
            rows = []
            for date in ["2020-01-31", "2022-01-31", "2024-06-30", "2025-01-31", "2026-06-30"]:
                rows.append(
                    {
                        "rebalance_date": date,
                        "ticker": "CASH",
                        "weight": 0.40,
                        "target_weight": 0.40,
                        "actual_results_score": "",
                        "portfolio_kind": "concentrated",
                    }
                )
                for idx, score in enumerate([0.1, 0.3, 0.5, 0.7, 0.9]):
                    rows.append(
                        {
                            "rebalance_date": date,
                            "ticker": f"C{idx}",
                            "weight": 0.12,
                            "target_weight": 0.12,
                            "actual_results_score": score,
                            "effective_single_weight_cap": 0.30,
                            "portfolio_kind": "concentrated",
                        }
                    )
            pd.DataFrame(rows).to_csv(latest / "official_concentrated_target_book.csv", index=False)
            parity = root / "parity" / "summary.json"
            survivorship = root / "survivorship" / "summary.json"
            write_json(parity, {"runner_parity_status": "parity_documented_gap", "runner_parity_reason": "fixture"})
            write_json(
                survivorship,
                {
                    "label": "proxy",
                    "method": "fixture",
                    "unmeasured_component": "delisted_exclusion",
                    "survivorship_inflation_estimate_cagr_pp": 0.0,
                    "survivorship_inflation_estimate": {
                        "cagr_pp_lower_bound": 0.0,
                        "label": "proxy",
                        "method": "fixture",
                        "unmeasured_component": "delisted_exclusion",
                    },
                },
            )
            args = Args()
            args.latest_run = str(root / "latest")
            args.target_book = ""
            args.portfolio_kind = "concentrated"
            args.target_arm = "actual_results_top_quintile_tilt05"
            args.price_cache = str(root / "cache_prices")
            args.output_dir = str(root / "out")
            args.cost_bps = 25.0
            args.max_fill_lag_days = 7
            args.starting_capital = 100000.0
            args.single_cap = 0.30
            args.cash_carry_mode = "risk_free_rate"
            args.cash_rate_source = "DGS3MO"
            args.cash_rate_path = ""
            args.cash_rate_lag_days = 1
            args.cash_carry_haircut_bps = 50.0
            args.cash_carry_day_count = 365
            args.replay_end_date = "2026-07-06"
            args.official_baseline_end_date = "2026-07-06"
            args.rolling_months = [12, 24, 36]
            args.parity_summary = str(parity)
            args.survivorship_summary = str(survivorship)
            payload = mod.run(args)
            assert payload["status"] == "completed"
            assert payload["portfolio_kind"] == "concentrated"
            assert payload["target_cagr"] == 0.50
            assert payload["decision_label"] == "reject_headline_contract_not_restored"
            assert payload["candidate_allowed"] is False
            assert payload["fullrun_dispatched"] is False
            assert payload["new_alpha_hook_added"] is False
            assert payload["threshold_tuning_performed"] is False
            assert payload["production_promotion_allowed"] is False
            full = next(row for row in payload["window_rows"] if row["window_group"] == "fixed" and row["window"] == "full")
            assert full["candidate_contract_pass"] is False
            assert full["candidate_cagr"] < 0.50
            assert "runner_parity_not_exact" in payload["measurement_contract_acceptance_blockers"]
            assert (root / "out" / "summary.json").exists()
            assert (root / "out" / "window_metrics.csv").exists()
            assert (root / "out" / "report.md").exists()
    finally:
        mod.run_broker_replay = original_replay


def main() -> int:
    test_actual_results_rolling_review_mixed_and_research_only()
    test_concentrated_actual_results_rolling_review_rejects_below_50()
    print("run287_actual_results_rolling_review_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
