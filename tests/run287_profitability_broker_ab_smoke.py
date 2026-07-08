#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_run287_profitability_broker_ab as mod  # noqa: E402


class Args:
    pass


def fake_replay(**kwargs):
    arm = kwargs["target_book"].parent.name
    base = {
        "status": "completed",
        "metric_mode": "broker_ledger_next_close_cash_carry",
        "cagr": 0.48,
        "max_dd": -0.23,
        "sharpe": 1.4,
        "years": 7.1,
        "start_date": "2019-06-03",
        "end_date": "2026-07-06",
        "avg_cash_weight": 0.30,
        "trade_count": 10,
        "total_fees_usd": 100.0,
        "gross_traded_usd": 10000.0,
        "cash_interest_accrued_usd": 1000.0,
        "windows": {
            "is": {"cagr": 0.30, "max_dd": -0.18},
            "oos": {"cagr": 0.90, "max_dd": -0.22},
        },
    }
    if arm == "profitability_top_quintile_tilt10":
        base["cagr"] = 0.486
    elif arm == "profitability_top_quintile_tilt05":
        base["cagr"] = 0.482
    return base


def test_profitability_broker_ab_research_only_and_preserves_cash() -> None:
    original_replay = mod.run_broker_replay
    mod.run_broker_replay = fake_replay
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / "latest" / "alphaops_vnext"
            latest.mkdir(parents=True)
            rows = []
            for date in ["2025-01-31", "2025-02-28"]:
                rows.append(
                    {
                        "rebalance_date": date,
                        "ticker": "CASH",
                        "weight": 0.20,
                        "target_weight": 0.20,
                        "profitability_inflection_score": "",
                        "portfolio_kind": "concentrated",
                    }
                )
                for idx, score in enumerate([0.1, 0.3, 0.5, 0.7, 0.9]):
                    rows.append(
                        {
                            "rebalance_date": date,
                            "ticker": f"T{idx}",
                            "weight": 0.16,
                            "target_weight": 0.16,
                            "profitability_inflection_score": score,
                            "effective_single_weight_cap": 0.30,
                            "portfolio_kind": "concentrated",
                        }
                    )
            pd.DataFrame(rows).to_csv(latest / "official_concentrated_target_book.csv", index=False)
            args = Args()
            args.latest_run = str(root / "latest")
            args.target_book = ""
            args.portfolio_kind = "concentrated"
            args.price_cache = str(root / "cache_prices")
            args.signal = "profitability_inflection_score"
            args.tilt_strengths = "0.05,0.10"
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
            payload = mod.run(args)
            assert payload["status"] == "completed"
            assert payload["research_only"] is True
            assert payload["candidate_allowed"] is False
            assert payload["fullrun_dispatched"] is False
            assert payload["new_alpha_hook_added"] is False
            assert payload["used_forward_return_in_ranking"] is False
            assert payload["production_promotion_allowed"] is False
            assert payload["positive_arms"]
            assert (root / "out" / "concentrated" / "summary.json").exists()
            metrics = pd.read_csv(root / "out" / "concentrated" / "arm_metrics.csv")
            assert metrics["cash_abs_delta_sum"].max() <= 1e-9
            assert "profitability_top_quintile_tilt10" in set(metrics["arm"])
    finally:
        mod.run_broker_replay = original_replay


def test_tilt_strength_parser_allows_one_pass_and_blocks_invalid() -> None:
    assert mod.parse_tilt_strengths("0.05") == [0.05]
    assert mod.parse_tilt_strengths("0.05, 0.05, 0.10") == [0.05, 0.10]
    arms = mod.build_arms("profitability_inflection_score", tilt_strengths=[0.05])
    assert [arm["arm"] for arm in arms] == ["baseline", "profitability_top_quintile_tilt05"]
    try:
        mod.parse_tilt_strengths("0")
    except ValueError as exc:
        assert "invalid tilt strength" in str(exc)
    else:
        raise AssertionError("zero tilt strength should be rejected")


def main() -> int:
    test_profitability_broker_ab_research_only_and_preserves_cash()
    test_tilt_strength_parser_allows_one_pass_and_blocks_invalid()
    print("run287_profitability_broker_ab_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
