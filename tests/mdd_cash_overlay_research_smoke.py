#!/usr/bin/env python3
"""Smoke test for MDD cash overlay research sidecar."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_mdd_cash_overlay_research import run  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def seed_portfolio(root: Path, portfolio: str) -> None:
    base = root / "broker_replay" / portfolio
    base.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2026-01-02", periods=8)
    # The crisis signal appears before the deepest damage. A no-lookahead
    # overlay cannot avoid the first down day, but should reduce later MDD.
    equity = [100000, 100000, 90000, 70000, 60000, 65000, 75000, 85000]
    pd.DataFrame(
        {
            "date": [d.date().isoformat() for d in dates],
            "equity_usd": equity,
            "cash_usd": [0.0] * len(dates),
            "cash_weight": [0.0] * len(dates),
            "stock_value_usd": equity,
            "position_count": [1] * len(dates),
            "fill_mode": ["next_close"] * len(dates),
        }
    ).to_csv(base / "equity_curve.csv", index=False)
    pd.DataFrame(
        [
            {"date": dates[0].date().isoformat(), "ticker": "AAA", "side": "BUY", "gross_value": 100000, "cash_delta": -100000},
            {"date": dates[4].date().isoformat(), "ticker": "AAA", "side": "SELL", "gross_value": 50000, "cash_delta": 50000},
        ]
    ).to_csv(base / "trades.csv", index=False)
    pd.DataFrame(
        {
            "date": [d.date().isoformat() for d in dates],
            "ticker": ["AAA"] * len(dates),
            "market_value_usd": equity,
            "weight": [1.0] * len(dates),
        }
    ).to_csv(base / "holdings_daily.csv", index=False)
    write_json(
        base / "metrics.json",
        {
            "status": "completed",
            "cagr": -0.2,
            "sharpe": -1.0,
            "max_dd": -0.4,
            "max_dd_peak_date": dates[0].date().isoformat(),
            "max_dd_trough_date": dates[4].date().isoformat(),
            "avg_cash_weight": 0.0,
        },
    )


def test_mdd_cash_overlay_reduces_drawdown_without_future_labels() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "latest"
        out = Path(tmp) / "out"
        seed_portfolio(root, "main")
        seed_portfolio(root, "concentrated")
        dates = pd.bdate_range("2026-01-02", periods=8)
        (root / "alphaops_vnext").mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "date": [d.date().isoformat() for d in dates],
                "crisis_state": [
                    "GREEN",
                    "DEFENSE_REVIEW",
                    "CRISIS_DEFENSE",
                    "CRISIS_DEFENSE",
                    "CRISIS_DEFENSE",
                    "REENTRY_READY",
                    "GREEN",
                    "GREEN",
                ],
            }
        ).to_csv(root / "alphaops_vnext" / "daily_crisis_state.csv", index=False)

        summary = run(
            latest_run=root,
            output_dir=out,
            crisis_state=None,
            portfolios=["main", "concentrated"],
            cost_bps=0.0,
            confirm_days=1,
            release_step=0.10,
            change_band=0.01,
            enable_equity_breaker=True,
        )
        main = summary["portfolios"]["main"]
        assert main["status"] == "completed"
        assert main["overlay_metrics"]["max_dd"] > main["base_metrics"]["max_dd"]
        assert main["cash_action_count"] > 0
        actions = pd.read_csv(out / "main" / "cash_actions.csv")
        assert actions.iloc[0]["signal_date"] == dates[1].date().isoformat()
        assert actions.iloc[0]["cash_action"] == "RAISE_CASH"
        assert (out / "summary.json").exists()
        assert (out / "main" / "mdd_trade_window.csv").exists()


if __name__ == "__main__":
    test_mdd_cash_overlay_reduces_drawdown_without_future_labels()
    print("mdd_cash_overlay_research_smoke: PASS")
