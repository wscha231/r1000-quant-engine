#!/usr/bin/env python3
from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_fixed_book_cashfunded_early_entry_ab as ab  # noqa: E402


def _book() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"rebalance_date": "2020-01-31", "ticker": "CASH", "weight": 0.10, "target_weight": 0.10},
            {"rebalance_date": "2020-01-31", "ticker": "AAA", "weight": 0.45, "target_weight": 0.45},
            {"rebalance_date": "2020-01-31", "ticker": "BBB", "weight": 0.45, "target_weight": 0.45},
            {"rebalance_date": "2020-02-28", "ticker": "CASH", "weight": 0.02, "target_weight": 0.02},
            {"rebalance_date": "2020-02-28", "ticker": "AAA", "weight": 0.49, "target_weight": 0.49},
            {"rebalance_date": "2020-02-28", "ticker": "BBB", "weight": 0.49, "target_weight": 0.49},
        ]
    )


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "rebalance_date": "2020-01-31",
                "ticker": "CCC",
                "variant_id": "concentrated_N5",
                "future_winner_scout_score": 9.0,
                "breakout_setup_quality_score": 0.80,
                "crisis_state": "BULL",
                "primary_lane": "scout",
                "forward_126d_excess": 0.30,
            },
            {
                "rebalance_date": "2020-01-31",
                "ticker": "AAA",
                "variant_id": "concentrated_N5",
                "future_winner_scout_score": 10.0,
                "breakout_setup_quality_score": 0.95,
                "crisis_state": "BULL",
            },
            {
                "rebalance_date": "2020-02-28",
                "ticker": "DDD",
                "variant_id": "concentrated_N5",
                "future_winner_scout_score": 11.0,
                "breakout_setup_quality_score": 0.40,
                "crisis_state": "BULL",
            },
            {
                "rebalance_date": "2020-02-28",
                "ticker": "EEE",
                "variant_id": "concentrated_N5",
                "future_winner_scout_score": 8.0,
                "breakout_setup_quality_score": 0.90,
                "crisis_state": "CRISIS_DEFENSE",
            },
        ]
    )


def test_build_arm_book_cash_funded_non_sticky_entry() -> None:
    generated, audit, info = ab.build_arm_book(_book(), _candidates(), arm="entry_w5p8", allow_crisis=False)

    assert info["applied_count"] == 1
    jan = generated[generated["rebalance_date"].astype(str).eq("2020-01-31")]
    assert "CCC" in set(jan["ticker"])
    assert round(float(jan[jan["ticker"].eq("CASH")]["weight"].sum()), 10) == 0.042
    assert round(float(jan["weight"].sum()), 10) == 1.0
    assert bool(jan[jan["ticker"].eq("CCC")]["concentrated_cashfunded_early_entry_applied"].iloc[0]) is True
    assert audit.loc[audit["rebalance_date"].eq("2020-01-31"), "forward_labels_used_for_ranking"].eq(False).all()

    feb = generated[generated["rebalance_date"].astype(str).eq("2020-02-28")]
    assert "DDD" not in set(feb["ticker"])
    assert "EEE" not in set(feb["ticker"])
    assert audit.loc[audit["rebalance_date"].eq("2020-02-28"), "status"].iloc[0] == "blocked_top_candidate_low_breakout_quality"


def test_baseline_is_noop() -> None:
    generated, audit, info = ab.build_arm_book(_book(), _candidates(), arm="baseline", allow_crisis=False)
    assert info["applied_count"] == 0
    assert audit.empty
    assert set(generated["ticker"]) == set(_book()["ticker"])


def test_harness_writes_summary_with_fake_broker() -> None:
    original = ab.run_broker_replay

    def fake_broker(**kwargs):
        arm = Path(kwargs["output_dir"]).parent.name
        cagr = {"baseline": 0.4875, "entry_w5p8": 0.5010}[arm]
        assert kwargs["cash_carry_mode"] == "risk_free_rate"
        assert kwargs["replay_end_date"] == "2026-06-29"
        return {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close_cash_carry",
            "cagr": cagr,
            "max_dd": -0.248,
            "sharpe": 1.5,
            "years": 7.05,
            "start_date": "2019-06-03",
            "end_date": "2026-06-29",
            "avg_cash_weight": 0.06,
            "trade_count": 12,
            "end_date_matches_official": True,
            "broker_metrics_path": str(Path(kwargs["output_dir"]) / "metrics.json"),
        }

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "target.csv"
        candidates = root / "candidates.csv"
        _book().to_csv(target, index=False)
        _candidates().to_csv(candidates, index=False)
        (root / "prices").mkdir()

        ab.run_broker_replay = fake_broker
        try:
            payload = ab.run(
                Namespace(
                    target_book=str(target),
                    candidate_source=str(candidates),
                    variant_id="concentrated_N5",
                    price_cache=str(root / "prices"),
                    output_dir=str(root / "ab"),
                    portfolio_kind="concentrated",
                    arms="baseline,entry_w5p8",
                    starting_capital=100000.0,
                    cost_bps=25.0,
                    max_fill_lag_days=7,
                    cash_carry_mode="risk_free_rate",
                    cash_rate_path="",
                    cash_rate_source="DGS3MO",
                    cash_rate_lag_days=1,
                    cash_carry_haircut_bps=50.0,
                    cash_carry_day_count=365,
                    replay_end_date="2026-06-29",
                    official_baseline_end_date="2026-06-29",
                    allow_crisis=False,
                )
            )
        finally:
            ab.run_broker_replay = original

        assert payload["policy_candidates"]
        assert payload["production_activation_allowed"] is False
        assert payload["forward_labels_used_for_ranking"] is False
        assert (root / "ab" / "entry_w5p8" / "early_entry_audit.csv").exists()


if __name__ == "__main__":
    test_build_arm_book_cash_funded_non_sticky_entry()
    test_baseline_is_noop()
    test_harness_writes_summary_with_fake_broker()
    print("fixed_book_cashfunded_early_entry_ab_smoke: PASS")
