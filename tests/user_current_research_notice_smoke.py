#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from argparse import Namespace
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_user_current_report import build_report


def test_user_current_explains_research_sidecars_do_not_alter_holdings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        (latest / "operating_snapshot").mkdir(parents=True)
        (latest / "account_evaluation").mkdir()
        (latest / "broker_replay" / "main").mkdir(parents=True)
        (latest / "broker_replay" / "concentrated").mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-01-31",
                    "portfolio_kind": "main",
                    "row_type": "stock",
                    "ticker": "AAA",
                    "current_weight": 0.5,
                }
            ]
        ).to_csv(latest / "operating_snapshot" / "current_operating_holdings_latest.csv", index=False)
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps({"official_metric_mode": "broker_ledger_next_close", "valid_for_production": True}),
            encoding="utf-8",
        )
        for portfolio in ("main", "concentrated"):
            pd.DataFrame(
                [
                    {"date": "2026-01-02", "equity_usd": 100000, "cash_weight": 0.05},
                    {"date": "2026-01-31", "equity_usd": 101000, "cash_weight": 0.05},
                ]
            ).to_csv(latest / "broker_replay" / portfolio / "equity_curve.csv", index=False)
            (latest / "broker_replay" / portfolio / "metrics.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "metric_mode": "broker_ledger_next_close",
                        "cagr": 0.12,
                        "max_dd": -0.08,
                        "sharpe": 1.1,
                        "avg_cash_weight": 0.05,
                        "valid_for_production": True,
                    }
                ),
                encoding="utf-8",
            )
        (latest / "operating_event_backtest").mkdir()
        (latest / "operating_event_backtest" / "operating_event_backtest_summary.json").write_text(
            json.dumps(
                {
                    "daily_risk_overlay_validated": True,
                    "daily_risk_action_evidence_count": 3,
                    "full_nonmonthly_entry_replacement_validated": False,
                    "portfolios": [
                        {
                            "portfolio": "main",
                            "operating_event_backtest_status": "partial_daily_risk_overlay_validated",
                            "daily_risk_engine_backtest_completed": True,
                            "daily_risk_action_evidence": True,
                            "nonmonthly_risk_action_count": 2,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (latest / "integrated_theme_leader_crisis_replay").mkdir()
        (latest / "integrated_theme_leader_crisis_replay" / "replay_gate_status.json").write_text('{"status":"passed"}\n', encoding="utf-8")
        (latest / "integrated_theme_leader_crisis_replay" / "promotion_gate_status.json").write_text('{"status":"rejected","production_activation_allowed":false}\n', encoding="utf-8")

        payload = build_report(Namespace(latest_run=str(latest), price_cache=str(root / "cache_prices"), output_dir=str(root / "user_current"), strict=False))
        out = root / "user_current"
        context = json.loads((out / "07_research_sidecar_context.json").read_text(encoding="utf-8"))
        broker_rule = json.loads((out / "08_broker_rule_backtest.json").read_text(encoding="utf-8"))
        holdings = pd.read_csv(out / "01_current_holdings.csv")
        summary = (out / "05_action_summary.md").read_text(encoding="utf-8")
        assert payload["production_applied"] is False
        assert payload["sidecar_only"] is True
        assert payload["production_policy"] == "production_baseline"
        assert payload["sidecar_applied_to_production"] is False
        assert payload["official_metric_mode"] == "broker_ledger_next_close"
        assert payload["daily_monitoring_backtest_status"] == "validated"
        assert context["current_holdings_source"] == "production_operating_target_book"
        assert broker_rule["daily_risk_overlay_validated"] is True
        assert holdings["backtest_metric_mode"].iloc[0] == "broker_ledger_next_close"
        assert "official_broker_cagr" in holdings.columns
        assert "sidecar_applied_to_production" in summary
        assert "Broker Rule Backtest" in summary
        assert "Market Leader / Multi-Lane / Crisis outputs alter current holdings only after production activation" in summary
        assert "promotion_gate_status" in summary


def test_user_current_marks_alphaops_vnext_production_as_applied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        (latest / "operating_snapshot").mkdir(parents=True)
        (latest / "account_evaluation").mkdir()
        (latest / "broker_replay" / "main").mkdir(parents=True)
        (latest / "broker_replay" / "concentrated").mkdir(parents=True)
        (latest / "alphaops_vnext").mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-01-31",
                    "portfolio_kind": "main",
                    "row_type": "stock",
                    "ticker": "VNX",
                    "current_weight": 0.5,
                }
            ]
        ).to_csv(latest / "operating_snapshot" / "current_operating_holdings_latest.csv", index=False)
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps({"official_metric_mode": "broker_ledger_next_close", "valid_for_production": True}),
            encoding="utf-8",
        )
        for portfolio in ("main", "concentrated"):
            pd.DataFrame(
                [
                    {"date": "2026-01-02", "equity_usd": 100000, "cash_weight": 0.05},
                    {"date": "2026-01-31", "equity_usd": 101000, "cash_weight": 0.05},
                ]
            ).to_csv(latest / "broker_replay" / portfolio / "equity_curve.csv", index=False)
            (latest / "broker_replay" / portfolio / "metrics.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "metric_mode": "broker_ledger_next_close",
                        "cagr": 0.12,
                        "max_dd": -0.08,
                        "sharpe": 1.1,
                        "avg_cash_weight": 0.05,
                        "valid_for_production": True,
                    }
                ),
                encoding="utf-8",
            )
        (latest / "alphaops_vnext" / "production_activation.json").write_text(
            json.dumps(
                {
                    "status": "applied",
                    "production_policy": "alphaops_vnext_production",
                    "current_holdings_source": "alphaops_vnext_policy_target_book",
                }
            ),
            encoding="utf-8",
        )

        payload = build_report(Namespace(latest_run=str(latest), price_cache=str(root / "cache_prices"), output_dir=str(root / "user_current"), strict=False))
        context = json.loads((root / "user_current" / "07_research_sidecar_context.json").read_text(encoding="utf-8"))
        broker_rule = json.loads((root / "user_current" / "08_broker_rule_backtest.json").read_text(encoding="utf-8"))
        assert payload["production_applied"] is True
        assert payload["sidecar_only"] is False
        assert payload["production_policy"] == "alphaops_vnext_production"
        assert context["current_holdings_source"] == "alphaops_vnext_policy_target_book"
        assert broker_rule["official_metric_mode"] == "broker_ledger_next_close"


if __name__ == "__main__":
    test_user_current_explains_research_sidecars_do_not_alter_holdings()
    test_user_current_marks_alphaops_vnext_production_as_applied()
    print("user_current_research_notice_smoke: PASS")
