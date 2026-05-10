#!/usr/bin/env python3
"""Smoke checks for concentrated champion trade-learning artifacts."""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_concentrated_trade_journal import build  # noqa: E402
from tools.trade_insights import expand_signal_breakdown, load_journals  # noqa: E402


def _write_fixture(run: Path) -> None:
    reports = run / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "portfolio_mode": "concentrated_alpha",
                "target_stock_names": 3,
                "weighting_mode": "score_power",
                "rebalance_interval_months": 1,
                "strategy_cagr": 0.45,
                "sharpe": 1.6,
                "max_dd": -0.20,
                "comparison_objective": 0.55,
            }
        ]
    ).to_csv(reports / "concentrated_strategy_comparison.csv", index=False)
    rows = []
    for dt, ret in [("2020-01-31", 0.08), ("2020-02-28", -0.04), ("2020-03-31", 0.12)]:
        for ticker, weight, score in [("AAA", 0.5, 3.0), ("BBB", 0.3, 2.0), ("CCC", 0.2, 1.0)]:
            rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "weight": weight,
                    "raw_score": score,
                    "concentrated_score": score,
                    "period_forward_return": ret,
                    "weighted_forward_return": weight * ret,
                    "target_n": 3,
                    "target_stock_names": 3,
                    "weighting_mode": "score_power",
                    "active_rebalance_interval_months": 1,
                    "portfolio_monster_early_score": 0.7,
                    "entry_quality_score": 0.8,
                    "breakout_setup_quality_score": 0.6,
                    "selection_confirmation_score": 0.9,
                    "portfolio_risk_entry_block_score": 0.1,
                }
            )
    pd.DataFrame(rows).to_csv(reports / "concentrated_strategy_holdings.csv", index=False)
    pd.DataFrame(
        [
            {
                "rebalance_date": dt,
                "bench_return": bench,
                "target_n": 3,
                "target_stock_names": 3,
                "weighting_mode": "score_power",
                "active_rebalance_interval_months": 1,
            }
            for dt, bench in [("2020-01-31", 0.02), ("2020-02-28", -0.01), ("2020-03-31", 0.03)]
        ]
    ).to_csv(reports / "concentrated_strategy_monthly.csv", index=False)
    pd.DataFrame(
        [
            {"rebalance_date": "2020-01-31", "regime_label": "bull", "regime_state_score": 1},
            {"rebalance_date": "2020-02-28", "regime_label": "neutral", "regime_state_score": 0},
            {"rebalance_date": "2020-03-31", "regime_label": "bull", "regime_state_score": 1},
        ]
    ).to_csv(reports / "regime_by_month.csv", index=False)


def test_concentrated_journal_build_and_insight_load() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        _write_fixture(latest)
        out_dir = root / "concentrated_trade_journal"
        payload = build(latest, out_dir)
        assert payload["status"] == "completed"
        trades_path = out_dir / "trades.csv"
        assert trades_path.exists()
        trades = pd.read_csv(trades_path)
        assert not trades.empty
        assert set(trades["source_journal"]) == {"concentrated_champion"}
        combined = load_journals(trades_path, [trades_path])
        expanded = expand_signal_breakdown(combined)
        assert "feat_portfolio_monster_early_score" in expanded.columns
        assert expanded["feat_entry_quality_score"].max() > 0


def main() -> int:
    test_concentrated_journal_build_and_insight_load()
    print("concentrated_trade_learning_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
