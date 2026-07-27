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

from tools.run_user_current_report import (
    build_report,
    load_latest_close_performance,
)


def test_latest_close_requires_trusted_scorecard_safety_envelope() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        latest = Path(tmp)
        scorecard_path = (
            latest
            / "run287_operating_scorecard"
            / "operating_scorecard.json"
        )
        scorecard_path.parent.mkdir(parents=True)
        payload = {
            "schema_version": "run287-latest-close-performance-v1",
            "status": "READY_LATEST_CLOSE_REVIEW_ONLY",
            "as_of_date": "2026-07-24",
            "latest_close_exact": True,
            "review_only": True,
            "live_trading_enabled": False,
            "production_activation_allowed": False,
            "historical_cagr_mdd_replacement_allowed": False,
            "promotion_evidence_allowed": False,
            "portfolios": {},
        }
        scorecard_path.write_text(
            json.dumps(
                {
                    "scorecard_trusted": True,
                    "latest_close_performance": payload,
                }
            ),
            encoding="utf-8",
        )
        assert load_latest_close_performance(latest) == payload
        payload["promotion_evidence_allowed"] = True
        scorecard_path.write_text(
            json.dumps(
                {
                    "scorecard_trusted": True,
                    "latest_close_performance": payload,
                }
            ),
            encoding="utf-8",
        )
        assert load_latest_close_performance(latest) == {}


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
        assert (
            "10_latest_close_performance.json"
            not in payload["missing_required_files"]
        )
        daily_payload = build_report(
            Namespace(
                latest_run=str(latest),
                price_cache=str(root / "cache_prices"),
                output_dir=str(root / "user_current_daily"),
                strict=False,
                require_latest_close=True,
            )
        )
        assert (
            "10_latest_close_performance.json"
            in daily_payload["missing_required_files"]
        )
        out = root / "user_current"
        context = json.loads((out / "07_research_sidecar_context.json").read_text(encoding="utf-8"))
        broker_rule = json.loads((out / "08_broker_rule_backtest.json").read_text(encoding="utf-8"))
        holdings = pd.read_csv(out / "01_current_holdings.csv")
        rationales = pd.read_csv(out / "07_name_rationales.csv")
        decision = json.loads((out / "08_rebalance_decision.json").read_text(encoding="utf-8"))
        summary = (out / "05_action_summary.md").read_text(encoding="utf-8")
        for name in [
            "02_target_weights.csv",
            "03_order_preview.csv",
            "07_name_rationales.csv",
            "08_rebalance_decision.json",
        ]:
            assert (out / name).exists(), name
        assert payload["production_applied"] is False
        assert payload["sidecar_only"] is True
        assert payload["production_policy"] == "production_baseline"
        assert payload["sidecar_applied_to_production"] is False
        assert payload["official_metric_mode"] == "broker_ledger_next_close"
        assert payload["daily_monitoring_backtest_status"] == "validated"
        assert context["current_holdings_source"] == "production_operating_target_book"
        assert broker_rule["daily_risk_overlay_validated"] is True
        assert holdings["backtest_metric_mode"].iloc[0] == "broker_ledger_next_close"
        assert rationales["ticker"].iloc[0] == "AAA"
        assert "membership_pit_status" in rationales.columns
        assert decision["review_only"] is True
        assert decision["live_trading_enabled"] is False
        assert decision["production_mutation_allowed"] is False
        assert decision["human_approval_required"] is True
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


def test_user_current_blocks_nested_invalid_official_metrics() -> None:
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
                    "as_of_date": "2026-06-15",
                    "snapshot_semantics": "current_broker_ledger_mark_to_market",
                    "account_source": "simulated_broker_replay",
                    "approval_status": "blocked_by_safety_audit",
                    "portfolio_kind": "concentrated",
                    "row_type": "stock",
                    "ticker": "SNDK",
                    "current_weight": 0.2,
                }
            ]
        ).to_csv(latest / "operating_snapshot" / "current_operating_holdings_latest.csv", index=False)
        invalid_portfolio = {
            "status": "completed",
            "valid_for_production": False,
            "verdict_status": "invalid_window",
            "data_readiness_status": "blocked",
            "data_readiness_policy_replay_ready": False,
            "target_pass": False,
            "strengthened_pass": False,
            "broker_ledger_window_gate": {
                "status": "invalid_window",
                "valid": False,
                "data_readiness": {
                    "status": "blocked",
                    "ready_for_policy_replay": False,
                },
            },
        }
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps(
                {
                    "official_metric_mode": "broker_ledger_next_close",
                    "production_target_pass": False,
                    "strengthened_pass": False,
                    "portfolios": {
                        "main": {**invalid_portfolio, "cagr": 0.3501, "max_dd": -0.2605},
                        "concentrated": {**invalid_portfolio, "cagr": 0.45, "max_dd": -0.2582},
                    },
                }
            ),
            encoding="utf-8",
        )
        for portfolio in ("main", "concentrated"):
            pd.DataFrame(
                [
                    {"date": "2019-06-03", "equity_usd": 100000, "cash_weight": 0.05},
                    {"date": "2026-06-15", "equity_usd": 200000, "cash_weight": 0.05},
                ]
            ).to_csv(latest / "broker_replay" / portfolio / "equity_curve.csv", index=False)
            (latest / "broker_replay" / portfolio / "metrics.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "metric_mode": "broker_ledger_next_close",
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
        out = root / "user_current"
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        rationales = pd.read_csv(out / "07_name_rationales.csv")
        decision = json.loads((out / "08_rebalance_decision.json").read_text(encoding="utf-8"))
        action_summary = (out / "05_action_summary.md").read_text(encoding="utf-8")
        readme = (out / "README_FIRST.md").read_text(encoding="utf-8")

        assert payload["action_status"] == "DO_NOT_TRADE"
        assert payload["valid_for_production"] is False
        assert payload["production_promotion_allowed"] is False
        assert payload["recommendation_status"] == "DO_NOT_USE_REVIEW_REQUIRED"
        assert any("invalid_window" in item for item in payload["production_blockers"])
        assert summary["production_promotion_allowed"] is False
        assert summary["name_rationale_rows"] == 1
        assert summary["current_snapshot_used_for_order_preview"] is True
        assert "selected_vs_retained" in rationales.columns
        assert decision["review_only"] is True
        assert "- valid_for_production: `False`" in action_summary
        assert "- production_promotion_allowed: `False`" in action_summary
        assert "- recommendation_status: `DO_NOT_USE_REVIEW_REQUIRED`" in action_summary
        assert "This is NOT a live broker account" in readme


def test_user_current_preserves_restored_snapshot_when_fresh_current_is_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        user_current = root / "user_current"
        (latest / "operating_snapshot").mkdir(parents=True)
        (latest / "account_evaluation").mkdir()
        (latest / "broker_replay" / "main").mkdir(parents=True)
        (latest / "broker_replay" / "concentrated").mkdir(parents=True)
        user_current.mkdir(parents=True)
        columns = [
            "as_of_date",
            "snapshot_semantics",
            "portfolio_kind",
            "row_type",
            "ticker",
            "current_shares",
            "current_price",
            "current_value_usd",
            "current_weight",
            "account_source",
            "approval_status",
        ]
        pd.DataFrame(columns=columns).to_csv(latest / "operating_snapshot" / "current_operating_holdings_latest.csv", index=False)
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-06-15",
                    "snapshot_semantics": "current_broker_ledger_mark_to_market",
                    "portfolio_kind": "main",
                    "row_type": "stock",
                    "ticker": "GOOG",
                    "current_shares": 10,
                    "current_price": 100,
                    "current_value_usd": 1000,
                    "current_weight": 0.1,
                    "account_source": "simulated_broker_replay",
                    "approval_status": "blocked_by_safety_audit",
                }
            ]
        ).to_csv(user_current / "01_current_holdings.csv", index=False)
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps({"official_metric_mode": "broker_ledger_next_close", "valid_for_production": False}),
            encoding="utf-8",
        )
        for portfolio in ("main", "concentrated"):
            pd.DataFrame(
                [
                    {"date": "2026-06-01", "equity_usd": 100000, "cash_weight": 0.05},
                    {"date": "2026-06-15", "equity_usd": 101000, "cash_weight": 0.05},
                ]
            ).to_csv(latest / "broker_replay" / portfolio / "equity_curve.csv", index=False)

        payload = build_report(Namespace(latest_run=str(latest), price_cache=str(root / "cache_prices"), output_dir=str(user_current), strict=False))
        holdings = pd.read_csv(user_current / "01_current_holdings.csv")
        summary = json.loads((user_current / "summary.json").read_text(encoding="utf-8"))
        action_summary = (user_current / "05_action_summary.md").read_text(encoding="utf-8")

        assert len(holdings) == 1
        assert holdings.iloc[0]["ticker"] == "GOOG"
        assert payload["current_holding_rows"] == 1
        assert payload["current_holdings_source_mode"] == "restored_user_current_snapshot"
        assert payload["current_holdings_snapshot_restored"] is True
        assert summary["current_holdings_missing"] is False
        assert "current_holdings_snapshot_source_mode: `restored_user_current_snapshot`" in action_summary


def test_user_current_falls_back_to_committed_cloud_results_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        user_current = latest / "user_current"
        cloud_current = root / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe" / "user_current"
        (latest / "operating_snapshot").mkdir(parents=True)
        (latest / "account_evaluation").mkdir()
        (latest / "broker_replay" / "main").mkdir(parents=True)
        (latest / "broker_replay" / "concentrated").mkdir(parents=True)
        user_current.mkdir(parents=True)
        cloud_current.mkdir(parents=True)
        columns = [
            "as_of_date",
            "snapshot_semantics",
            "portfolio_kind",
            "row_type",
            "ticker",
            "current_shares",
            "current_price",
            "current_value_usd",
            "current_weight",
            "account_source",
            "approval_status",
        ]
        pd.DataFrame(columns=columns).to_csv(latest / "operating_snapshot" / "current_operating_holdings_latest.csv", index=False)
        pd.DataFrame(columns=columns).to_csv(user_current / "01_current_holdings.csv", index=False)
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-06-15",
                    "snapshot_semantics": "current_broker_ledger_mark_to_market",
                    "portfolio_kind": "concentrated",
                    "row_type": "stock",
                    "ticker": "SNDK",
                    "current_shares": 12,
                    "current_price": 50,
                    "current_value_usd": 600,
                    "current_weight": 0.2,
                    "account_source": "simulated_broker_replay",
                    "approval_status": "blocked_by_safety_audit",
                }
            ]
        ).to_csv(cloud_current / "01_current_holdings.csv", index=False)
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps({"official_metric_mode": "broker_ledger_next_close", "valid_for_production": False}),
            encoding="utf-8",
        )
        for portfolio in ("main", "concentrated"):
            pd.DataFrame(
                [
                    {"date": "2026-06-01", "equity_usd": 100000, "cash_weight": 0.05},
                    {"date": "2026-06-15", "equity_usd": 101000, "cash_weight": 0.05},
                ]
            ).to_csv(latest / "broker_replay" / portfolio / "equity_curve.csv", index=False)

        payload = build_report(Namespace(latest_run=str(latest), price_cache=str(root / "cache_prices"), output_dir=str(user_current), strict=False))
        holdings = pd.read_csv(user_current / "01_current_holdings.csv")
        action_summary = (user_current / "05_action_summary.md").read_text(encoding="utf-8")

        assert len(holdings) == 1
        assert holdings.iloc[0]["ticker"] == "SNDK"
        assert payload["current_holdings_source_mode"] == "committed_cloud_results_snapshot"
        assert payload["current_holdings_snapshot_restored"] is True
        assert payload["current_holdings_missing"] is False
        assert "current_holdings_snapshot_source_mode: `committed_cloud_results_snapshot`" in action_summary


def test_user_current_prefers_newer_committed_snapshot_over_stale_restored_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        user_current = latest / "user_current"
        cloud_current = root / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe" / "user_current"
        (latest / "operating_snapshot").mkdir(parents=True)
        (latest / "account_evaluation").mkdir()
        (latest / "broker_replay" / "main").mkdir(parents=True)
        (latest / "broker_replay" / "concentrated").mkdir(parents=True)
        user_current.mkdir(parents=True)
        cloud_current.mkdir(parents=True)
        columns = [
            "as_of_date",
            "snapshot_semantics",
            "portfolio_kind",
            "row_type",
            "ticker",
            "current_shares",
            "current_price",
            "current_value_usd",
            "current_weight",
            "account_source",
            "approval_status",
        ]
        pd.DataFrame(columns=columns).to_csv(latest / "operating_snapshot" / "current_operating_holdings_latest.csv", index=False)
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-05-22",
                    "snapshot_semantics": "current_broker_ledger_mark_to_market",
                    "portfolio_kind": "concentrated",
                    "row_type": "stock",
                    "ticker": "OLD",
                    "current_shares": 10,
                    "current_price": 20,
                    "current_value_usd": 200,
                    "current_weight": 0.4,
                    "account_source": "simulated_broker_replay",
                    "approval_status": "blocked_by_safety_audit",
                }
            ]
        ).to_csv(user_current / "01_current_holdings.csv", index=False)
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-06-15",
                    "snapshot_semantics": "current_broker_ledger_mark_to_market",
                    "portfolio_kind": "concentrated",
                    "row_type": "stock",
                    "ticker": "NEW",
                    "current_shares": 12,
                    "current_price": 50,
                    "current_value_usd": 600,
                    "current_weight": 0.2,
                    "account_source": "simulated_broker_replay",
                    "approval_status": "blocked_by_safety_audit",
                }
            ]
        ).to_csv(cloud_current / "01_current_holdings.csv", index=False)
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps({"official_metric_mode": "broker_ledger_next_close", "valid_for_production": False}),
            encoding="utf-8",
        )
        for portfolio in ("main", "concentrated"):
            pd.DataFrame(
                [
                    {"date": "2026-06-01", "equity_usd": 100000, "cash_weight": 0.05},
                    {"date": "2026-06-15", "equity_usd": 101000, "cash_weight": 0.05},
                ]
            ).to_csv(latest / "broker_replay" / portfolio / "equity_curve.csv", index=False)

        payload = build_report(Namespace(latest_run=str(latest), price_cache=str(root / "cache_prices"), output_dir=str(user_current), strict=False))
        holdings = pd.read_csv(user_current / "01_current_holdings.csv")

        assert len(holdings) == 1
        assert holdings.iloc[0]["ticker"] == "NEW"
        assert payload["current_holdings_source_mode"] == "committed_cloud_results_snapshot"
        assert "as_of_date=2026-06-15" in payload["current_holdings_source_detail"]


def test_user_current_contract_aligns_current_target_rationales_and_cash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out = root / "user_current"
        (latest / "operating_snapshot").mkdir(parents=True)
        (latest / "account_evaluation").mkdir()
        (latest / "broker_replay" / "main").mkdir(parents=True)
        (latest / "broker_replay" / "concentrated").mkdir(parents=True)
        (latest / "user_portfolio_reports").mkdir(parents=True)
        (latest / "data_freshness_contract").mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-06-22",
                    "snapshot_semantics": "current_broker_ledger_mark_to_market",
                    "portfolio_kind": "main",
                    "row_type": "stock",
                    "ticker": "OLD",
                    "current_shares": 10,
                    "current_price": 40,
                    "current_value_usd": 400,
                    "current_weight": 0.4,
                    "account_source": "simulated_broker_replay",
                    "approval_status": "blocked_by_safety_audit",
                },
                {
                    "as_of_date": "2026-06-22",
                    "snapshot_semantics": "current_broker_ledger_mark_to_market",
                    "portfolio_kind": "main",
                    "row_type": "cash",
                    "ticker": "CASH",
                    "current_shares": 0,
                    "current_price": 1,
                    "current_value_usd": 600,
                    "current_weight": 0.6,
                    "account_source": "simulated_broker_replay",
                    "approval_status": "blocked_by_safety_audit",
                },
            ]
        ).to_csv(latest / "operating_snapshot" / "current_operating_holdings_latest.csv", index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "NEW",
                    "recommended_weight": 0.7,
                    "current_account_weight": 0.0,
                    "rank": 1,
                    "company_name": "New Leader",
                    "sector": "Information Technology",
                    "portfolio_sleeve_label": "MARKET_LEADER",
                    "score": 99.0,
                    "suggested_action": "BUY_OR_HOLD_TO_TARGET",
                    "buy_logic": "new canonical target",
                },
                {
                    "ticker": "CASH",
                    "recommended_weight": 0.3,
                    "current_account_weight": 0.6,
                    "rank": 2,
                    "company_name": "Cash reserve",
                    "sector": "Cash",
                    "suggested_action": "RESERVE_CASH",
                    "buy_logic": "canonical cash target",
                },
            ]
        ).to_csv(latest / "user_portfolio_reports" / "main_recommendation_latest.csv", index=False)
        (latest / "data_freshness_contract" / "status.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "selection_allowed": True,
                    "promotion_allowed": False,
                    "recommendation_status": "READY_FOR_OPERATING_SELECTION",
                    "warnings": [],
                    "blockers": [],
                }
            ),
            encoding="utf-8",
        )
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps({"official_metric_mode": "broker_ledger_next_close", "valid_for_production": False}),
            encoding="utf-8",
        )
        for portfolio in ("main", "concentrated"):
            pd.DataFrame(
                [
                    {"date": "2026-06-01", "equity_usd": 100000, "cash_weight": 0.05},
                    {"date": "2026-06-22", "equity_usd": 101000, "cash_weight": 0.05},
                ]
            ).to_csv(latest / "broker_replay" / portfolio / "equity_curve.csv", index=False)

        build_report(Namespace(latest_run=str(latest), price_cache=str(root / "cache_prices"), output_dir=str(out), strict=False))

        current = pd.read_csv(out / "01_current_holdings.csv")
        target = pd.read_csv(out / "02_target_weights.csv")
        orders = pd.read_csv(out / "03_order_preview.csv")
        rationales = pd.read_csv(out / "07_name_rationales.csv")
        cash = json.loads((out / "02_cash_summary.json").read_text(encoding="utf-8"))

        assert "portfolio" in current.columns
        assert set(current["portfolio"]) == {"main"}
        assert set(target["ticker"]) == {"NEW", "CASH"}
        assert set(orders["ticker"]) == {"OLD", "NEW", "CASH"}
        assert set(rationales["ticker"]) == {"OLD", "NEW", "CASH"}
        by_ticker = {str(row["ticker"]): row for row in rationales.to_dict("records")}
        assert by_ticker["NEW"]["target_weight"] == 0.7
        assert by_ticker["NEW"]["canonical_target_weight"] == 0.7
        assert by_ticker["NEW"]["current_weight"] == 0.0
        assert by_ticker["NEW"]["selected_vs_retained"] == "new_target_candidate"
        assert bool(by_ticker["NEW"]["is_new_buy_signal"]) is True
        assert by_ticker["OLD"]["target_weight"] == 0.0
        assert by_ticker["OLD"]["canonical_target_weight"] == 0.0
        assert by_ticker["OLD"]["replay_retention_weight"] == 0.4
        assert cash["by_portfolio"]["main"]["target_cash_weight"] == 0.3
        assert cash["by_portfolio"]["main"]["canonical_target_cash_weight"] == 0.3
        assert cash["by_portfolio"]["main"]["target_cash_weight_semantics"] == "canonical target cash from 02_target_weights.csv"


if __name__ == "__main__":
    test_latest_close_requires_trusted_scorecard_safety_envelope()
    test_user_current_explains_research_sidecars_do_not_alter_holdings()
    test_user_current_marks_alphaops_vnext_production_as_applied()
    test_user_current_blocks_nested_invalid_official_metrics()
    test_user_current_preserves_restored_snapshot_when_fresh_current_is_empty()
    test_user_current_falls_back_to_committed_cloud_results_snapshot()
    test_user_current_prefers_newer_committed_snapshot_over_stale_restored_snapshot()
    test_user_current_contract_aligns_current_target_rationales_and_cash()
    print("user_current_research_notice_smoke: PASS")
