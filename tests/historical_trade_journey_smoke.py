#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_historical_trade_journey import analyze  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def test_historical_trade_journey() -> None:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        latest = root / "latest"
        out = root / "journey"
        fields = [
            "rebalance_date",
            "ticker",
            "Name",
            "sector",
            "weight",
            "raw_score",
            "portfolio_sleeve_label",
            "period_forward_return",
            "weighted_forward_return",
            "regime_state",
        ]
        write_csv(
            latest / "reports" / "main_monthly_weights.csv",
            [
                {"rebalance_date": "2024-01-31", "ticker": "AAA", "Name": "AAA", "sector": "Tech", "weight": 0.20, "raw_score": 5.0, "portfolio_sleeve_label": "future_winner", "period_forward_return": 0.10, "weighted_forward_return": 0.020, "regime_state": "bull"},
                {"rebalance_date": "2024-02-29", "ticker": "AAA", "Name": "AAA", "sector": "Tech", "weight": 0.22, "raw_score": 5.5, "portfolio_sleeve_label": "future_winner", "period_forward_return": 0.20, "weighted_forward_return": 0.044, "regime_state": "bull"},
                {"rebalance_date": "2024-03-31", "ticker": "AAA", "Name": "AAA", "sector": "Tech", "weight": 0.24, "raw_score": 5.6, "portfolio_sleeve_label": "future_winner", "period_forward_return": -0.05, "weighted_forward_return": -0.012, "regime_state": "bull"},
                {"rebalance_date": "2024-01-31", "ticker": "BBB", "Name": "BBB", "sector": "Health", "weight": 0.15, "raw_score": 4.0, "portfolio_sleeve_label": "early_scout", "period_forward_return": 0.30, "weighted_forward_return": 0.045, "regime_state": "bull"},
            ],
            fields,
        )
        write_csv(
            latest / "reports" / "concentrated_strategy_holdings.csv",
            [
                {"rebalance_date": "2024-01-31", "ticker": "AAA", "Name": "AAA", "sector": "Tech", "weight": 1.0, "raw_score": 5.0, "portfolio_sleeve_label": "future_winner", "period_forward_return": 0.10, "weighted_forward_return": 0.10, "regime_state": "bull"},
                {"rebalance_date": "2024-01-31", "ticker": "AAA", "Name": "AAA", "sector": "Tech", "weight": 1.0, "raw_score": 5.0, "portfolio_sleeve_label": "future_winner", "period_forward_return": 0.10, "weighted_forward_return": 0.10, "regime_state": "bull"},
                {"rebalance_date": "2024-02-29", "ticker": "AAA", "Name": "AAA", "sector": "Tech", "weight": 1.0, "raw_score": 5.5, "portfolio_sleeve_label": "future_winner", "period_forward_return": 0.20, "weighted_forward_return": 0.20, "regime_state": "bull"},
                {"rebalance_date": "2024-02-29", "ticker": "AAA", "Name": "AAA", "sector": "Tech", "weight": 1.0, "raw_score": 5.5, "portfolio_sleeve_label": "future_winner", "period_forward_return": 0.20, "weighted_forward_return": 0.20, "regime_state": "bull"},
            ],
            fields,
        )
        write_csv(
            latest / "trade_journal" / "trades.csv",
            [
                {"trade_id": "1", "ticker": "AAA", "entry_date": "2024-01-31", "exit_date": "2024-03-31", "entry_score": 5.0, "entry_sleeve": "future_winner", "entry_regime_state": "bull", "exit_reason": "scheduled_rebalance", "holding_days": 60, "n_periods": 3, "realized_return": 0.254, "alpha_vs_benchmark": 0.10},
                {"trade_id": "2", "ticker": "BBB", "entry_date": "2024-01-31", "exit_date": "2024-01-31", "entry_score": 4.0, "entry_sleeve": "early_scout", "entry_regime_state": "bull", "exit_reason": "single_period_hold", "holding_days": 0, "n_periods": 1, "realized_return": 0.30, "alpha_vs_benchmark": 0.20},
            ],
            ["trade_id", "ticker", "entry_date", "exit_date", "entry_score", "entry_sleeve", "entry_regime_state", "exit_reason", "holding_days", "n_periods", "realized_return", "alpha_vs_benchmark"],
        )
        write_csv(
            latest / "portfolio_latest.csv",
            [
                {"ticker": "AAA", "Name": "AAA", "sector": "Tech", "weight": 0.24},
                {"ticker": "NEW", "Name": "New Co", "sector": "Tech", "weight": 0.10},
            ],
            ["ticker", "Name", "sector", "weight"],
        )

        summary = analyze(latest, out)
        assert summary["status"] == "completed"
        assert summary["max_run_months"] == 3
        assert summary["short_big_win_review_count"] >= 1
        assert (out / "report.md").exists()
        assert (out / "holding_runs.csv").exists()
        assert (out / "trade_summary_by_ticker.csv").exists()
        assert (out / "leader_rotation_timeline.csv").exists()
        assert (out / "current_vs_history.csv").exists()
        runs = read_rows(out / "holding_runs.csv")
        grid_runs = [row for row in runs if row["book"] == "concentrated_grid_presence" and row["ticker"] == "AAA"]
        assert len(grid_runs) == 1
        assert int(grid_runs[0]["months_held"]) == 2
        current = read_rows(out / "current_vs_history.csv")
        assert any(row["ticker"] == "NEW" and row["history_status"] == "new_unseen" for row in current)
        payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert payload["production_activation_allowed"] is False


if __name__ == "__main__":
    test_historical_trade_journey()
    print("historical_trade_journey_smoke: ok")
