#!/usr/bin/env python3
"""Smoke test for broker-ledger account evaluation."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_account_evaluation import run  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_equity_curve(path: Path, start: str = "2019-06-03", end: str = "2026-06-12") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = date.fromisoformat(start)
    last = date.fromisoformat(end)
    rows = ["date,equity\n"]
    value = 100000.0
    while cur <= last:
        if cur.weekday() < 5:
            rows.append(f"{cur.isoformat()},{value:.2f}\n")
            value += 10.0
        cur += timedelta(days=1)
    path.write_text("".join(rows), encoding="utf-8")


def seed_portfolio(root: Path, portfolio: str, *, cagr: float, max_dd: float, sharpe: float) -> None:
    write_json(
        root / "broker_replay" / portfolio / "metrics.json",
        {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close",
            "valid_for_production": True,
            "start_date": "2019-06-03",
            "end_date": "2026-06-12",
            "years": 7.03,
            "starting_capital_usd": 100000,
            "ending_capital_usd": 400000,
            "cagr": cagr,
            "max_dd": max_dd,
            "sharpe": sharpe,
            "avg_cash_weight": 0.03,
            "trade_count": 10,
            "total_fees_usd": 123.45,
            "gross_traded_usd": 49380,
        },
    )
    write_equity_curve(root / "broker_replay" / portfolio / "equity_curve.csv")
    write_json(
        root / "broker_replay" / portfolio / "account_state_latest.json",
        {
            "portfolio_kind": portfolio,
            "as_of_date": "2026-06-12",
            "equity_usd": 400000,
            "cash_usd": 8000,
            "cash_weight": 0.02,
            "position_count": 7,
        },
    )
    write_json(
        root / "account_ledger_preview" / portfolio / "preview_metrics.json",
        {
            "status": "completed",
            "order_count": 4,
            "buy_count": 2,
            "sell_count": 2,
            "blocked_order_count": 0,
        },
    )
    write_json(
        root / "broker_trade_journal" / portfolio / "summary.json",
        {
            "status": "completed",
            "trade_count": 9,
            "win_rate": 0.66,
            "avg_realized_return": 0.08,
            "avg_holding_days": 55,
            "profit_factor": 2.1,
        },
    )


def test_account_evaluation_uses_broker_ledger_as_official_source() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "latest"
        out = Path(tmp) / "account_eval"
        seed_portfolio(root, "main", cagr=0.31, max_dd=-0.14, sharpe=1.2)
        seed_portfolio(root, "concentrated", cagr=0.49, max_dd=-0.16, sharpe=1.4)
        write_json(root / "backtest_metrics.json", {"strategy_cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
        write_json(root / "concentrated_backtest_metrics.json", {"strategy_cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
        write_json(root / "portfolio_goal_search" / "goal_search_summary.json", {"research_target_pass": True})
        write_json(
            root / "data_readiness" / "summary.json",
            {
                "status": "ready",
                "ready_for_fullrun": True,
                "ready_for_policy_replay": True,
                "free_data_coverage": {"known_gaps": []},
            },
        )
        write_json(
            root / "universe_health" / "universe_source_audit.json",
            {
                "status": "ready",
                "promotion_allowed": True,
                "r1000_base_count": 650,
                "min_r1000_base": 400,
            },
        )

        result = run(Namespace(latest_run=str(root), output_dir=str(out)))
        assert result["official_metric_mode"] == "broker_ledger_next_close"
        assert result["evidence_tier"] == "3_robust_candidate"
        assert result["research_ab_allowed"] is True
        assert result["promotion_allowed"] is False
        assert result["target_type"] == "interim_operating_gate"
        assert result["target_contract_status"] == "unresolved_user_decision_required"
        assert result["target_contract"]["canonical_mission"]["main"]["cagr"] == 0.35
        assert result["production_target_pass"] is False
        assert result["research_target_pass"] is True

        main = result["portfolios"][0]
        concentrated = result["portfolios"][1]
        assert main["portfolio"] == "main"
        assert main["target_type"] == "interim_operating_gate"
        assert main["canonical_cagr_target"] == 0.35
        assert main["canonical_max_dd_target"] == -0.25
        assert main["target_pass"] is True
        assert main["broker_ledger_actual_trading_days"] >= 252 * 7
        assert main["evidence_window_label"] == "research_7y"
        assert main["production_promotion_allowed"] is False
        assert main["legacy_cagr"] == 0.99
        assert concentrated["target_pass"] is False
        assert concentrated["canonical_max_dd_target"] == -0.25
        assert concentrated["cagr_gap_pp"] == 1.0
        official = json.loads((out / "official_metrics.json").read_text(encoding="utf-8"))
        assert official["target_type"] == "interim_operating_gate"
        assert official["evidence_tier"] == "3_robust_candidate"
        assert official["evidence_policy"]["evidence_label"] == "robust_candidate"
        assert official["target_contract"]["canonical_mission"]["concentrated"]["max_dd"] == -0.25
        assert (out / "portfolio_account_metrics.csv").exists()
        assert (out / "account_evaluation_report.md").exists()


if __name__ == "__main__":
    test_account_evaluation_uses_broker_ledger_as_official_source()
    print("account_evaluation_smoke: PASS")
