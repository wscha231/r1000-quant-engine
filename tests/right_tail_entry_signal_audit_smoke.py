#!/usr/bin/env python3
"""Smoke tests for right-tail entry signal audit."""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_right_tail_entry_signal_audit import run  # noqa: E402


def _write_fixture(root: Path) -> Path:
    latest = root / "latest"
    for portfolio in ("main", "concentrated"):
        broker = latest / "broker_replay" / portfolio
        broker.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-06-23",
                    "ticker": "AAA",
                    "realized_pnl_usd": 120_000,
                    "unrealized_pnl_usd": 80_000,
                },
                {
                    "as_of_date": "2026-06-23",
                    "ticker": "BBB",
                    "realized_pnl_usd": 10_000,
                    "unrealized_pnl_usd": 5_000,
                },
            ]
        ).to_csv(broker / "positions_latest.csv", index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "side": "BUY",
                    "date": "2024-01-02",
                    "signal_date": "2023-12-29",
                    "fill_price": 100.0,
                    "reason": "target_rebalance",
                },
                {
                    "ticker": "BBB",
                    "side": "BUY",
                    "date": "2024-02-01",
                    "signal_date": "2024-01-31",
                    "fill_price": 50.0,
                    "reason": "target_rebalance",
                },
            ]
        ).to_csv(broker / "trades.csv", index=False)

    reports = latest / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "rebalance_date": "2023-12-29",
                "ticker": "AAA",
                "score": 99.0,
                "sector": "Technology",
                "industry_group": "Semiconductors",
                "portfolio_sleeve_label": "MARKET_LEADER",
                "rs_benchmark_3m": 0.25,
                "rs_benchmark_6m": 0.40,
                "price_above_ma200": 1.0,
                "oneil_leadership_score": 0.90,
                "future_winner_scout_score": 0.95,
                "industry_group_strength_score": 0.80,
                "h6_dynamic_leader_score": 0.70,
                "eps_revision_score": 0.65,
                "actual_results_score": 0.85,
                "entry_quality_score": 0.75,
                "overheat_penalty": 0.0,
                "period_forward_return": 9.99,
            },
            {
                "rebalance_date": "2023-12-29",
                "ticker": "ZZZ",
                "score": 10.0,
                "rs_benchmark_3m": -0.05,
            },
            {
                "rebalance_date": "2024-01-31",
                "ticker": "BBB",
                "score": 5.0,
                "rs_benchmark_3m": -0.02,
            },
        ]
    ).to_csv(reports / "candidate_replay_book.csv", index=False)

    alphaops = latest / "alphaops_vnext"
    alphaops.mkdir(parents=True, exist_ok=True)
    for portfolio in ("main", "concentrated"):
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2023-12-29",
                    "ticker": "AAA",
                    "weight": 0.20,
                    "leader_tier": "DUAL_LEADER",
                    "primary_lane": "MARKET_LEADER",
                }
            ]
        ).to_csv(alphaops / f"official_{portfolio}_target_book.csv", index=False)
    return latest


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        latest = _write_fixture(root)
        out = root / "out"
        payload = run(latest, out, ("main", "concentrated"), top_n=1)
        assert payload["schema_version"] == "right-tail-entry-signal-audit-v1"
        assert payload["research_only"] is True
        assert payload["used_forward_return_in_ranking"] is False
        assert (out / "summary.json").exists()
        assert (out / "winner_entry_signals.csv").exists()
        assert (out / "report.md").exists()
        for portfolio in ("main", "concentrated"):
            block = payload["portfolios"][portfolio]
            assert block["status"] == "completed", block
            assert block["winner_count"] == 1, block
            assert block["selected_at_entry_count"] == 1, block
            assert block["skill_evidence_count"] == 1, block
            assert block["avg_presence_blocks"] == 1.0, block
            assert block["fragmented_capture_count"] == 0, block
            assert block["total_capture_drop_count"] == 0, block
            assert block["total_capture_reentry_count"] == 0, block
            assert block["total_sell_count"] == 0, block
            rows = pd.read_csv(out / portfolio / "winner_entry_signals.csv")
            assert rows.loc[0, "ticker"] == "AAA"
            assert rows.loc[0, "entry_signal_date"] == "2023-12-29"
            assert bool(rows.loc[0, "selected_in_target_at_entry"]) is True
            assert bool(rows.loc[0, "used_forward_return_in_ranking"]) is False
            assert int(rows.loc[0, "entry_signal_stack_count"]) >= 5
            assert int(rows.loc[0, "months_in_target"]) == 1
            assert int(rows.loc[0, "presence_blocks"]) == 1
            assert int(rows.loc[0, "capture_drop_count"]) == 0
            assert pd.isna(rows.loc[0, "first_capture_drop_date"]) or rows.loc[0, "first_capture_drop_date"] == ""
            assert bool(rows.loc[0, "capture_fragmented_flag"]) is False
            assert "period_forward_return" not in rows.columns
    print("right-tail entry signal audit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
