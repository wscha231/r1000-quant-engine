#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_decision_cadence_review import build_review  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price(cache: Path, ticker: str, start: float, drift: float) -> None:
    dates = pd.bdate_range("2025-01-02", periods=230)
    values = [start * ((1.0 + drift) ** i) for i in range(len(dates))]
    pd.DataFrame(
        {
            "Open": values,
            "Close": values,
            "Adj Close": values,
            "Volume": [2_000_000] * len(dates),
        },
        index=dates,
    ).to_parquet(cache / px_cache_name(ticker))


def test_decision_cadence_outputs_mid_month_reentry_review() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        cache = root / "cache_prices"
        out = root / "decision_cadence"
        (latest / "operating_snapshot").mkdir(parents=True)
        (latest / "reports").mkdir(parents=True)
        (latest / "daily_crisis_monitor").mkdir(parents=True)
        cache.mkdir(parents=True)

        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "ticker": "AAA",
                    "current_weight": 0.35,
                    "current_value_usd": 35000,
                }
            ]
        ).to_csv(latest / "operating_snapshot" / "current_operating_holdings_latest.csv", index=False)
        pd.DataFrame(
            [
                {"rebalance_date": "2025-11-14", "ticker": "AAA", "weight": 0.35},
                {"rebalance_date": "2025-11-14", "ticker": "CCC", "weight": 0.25},
            ]
        ).to_csv(latest / "reports" / "operating_main_target_book.csv", index=False)
        pd.DataFrame([{"rebalance_date": "2025-11-14", "ticker": "AAA", "weight": 1.0}]).to_csv(
            latest / "reports" / "operating_concentrated_target_book.csv",
            index=False,
        )
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2025-11-14",
                    "ticker": "CCC",
                    "score": 9.0,
                    "rs_benchmark_3m": 0.20,
                    "rs_benchmark_6m": 0.35,
                    "forward_pe_final": 24.0,
                    "leader_state": "HOLD",
                    "primary_lane": "MARKET_LEADER",
                }
            ]
        ).to_csv(latest / "reports" / "candidate_replay_book.csv", index=False)
        (latest / "daily_crisis_monitor" / "summary.json").write_text(
            json.dumps({"state": "REENTRY_READY", "raw_state": "REENTRY_READY"}),
            encoding="utf-8",
        )

        write_price(cache, "AAA", 100.0, -0.0004)
        write_price(cache, "CCC", 50.0, 0.003)
        write_price(cache, "SPY", 400.0, 0.0002)
        write_price(cache, "QQQ", 350.0, 0.0003)

        summary = build_review(
            Namespace(
                latest_run=str(latest),
                price_cache=str(cache),
                output_dir=str(out),
                max_watchlist_candidates=10,
            )
        )
        assert summary["daily_full_universe_rerank"] is False
        assert summary["weekly_full_universe_rerank"] is False
        assert summary["mid_month_reentry_allowed"] is True
        assert summary["mid_month_reentry_requires_full_universe_rerank"] is False
        assert "mid_month_reentry_ready" in summary["event_triggers_active"]
        abcd = summary["abcd_cadence_challenger"]
        assert abcd["contract_ready"] is True
        assert abcd["accepted_champion"] == "A"
        assert abcd["recommended_operating_candidate"] == "D"
        assert abcd["historical_backtest_executed"] is False
        assert set(abcd["arms"]) == {"A", "B", "C", "D"}
        assert abcd["arms"]["D"]["routine_rebalance"] == "last_nyse_session_of_month"
        assert abcd["arms"]["D"]["turnover_controls"]["weekly_full_universe_rerank"] is False
        assert (out / "daily_holdings_review.csv").exists()
        assert (out / "weekly_watchlist_refresh.csv").exists()
        assert (out / "monthly_event_rerank_plan.json").exists()
        assert (out / "abcd_cadence_preregistration.json").exists()
        weekly = pd.read_csv(out / "weekly_watchlist_refresh.csv")
        assert "ADD_CANDIDATE_REVIEW" in set(weekly["weekly_review_action"].astype(str))
        report = (out / "decision_cadence_report.md").read_text(encoding="utf-8")
        assert "re-entry does not wait for month-end" in report
        assert "Preregistered A/B/C/D comparison" in report


if __name__ == "__main__":
    test_decision_cadence_outputs_mid_month_reentry_review()
    print("decision_cadence_review_smoke: PASS")
