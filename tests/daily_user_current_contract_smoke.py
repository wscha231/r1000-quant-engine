#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_daily_user_current_contract import build_contract  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_contract_writes_required_review_only_files() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        user_current = latest / "user_current"
        (latest / "user_portfolio_reports").mkdir(parents=True)
        user_current.mkdir(parents=True)

        write_json(
            latest / "data_freshness_contract" / "status.json",
            {
                "schema_version": "data-freshness-contract-v1",
                "status": "blocked",
                "selection_allowed": False,
                "promotion_allowed": False,
                "recommendation_status": "DO_NOT_USE_REVIEW_REQUIRED",
                "blockers": ["macro is stale"],
                "warnings": ["review only fixture"],
                "production_mutation_allowed": False,
            },
        )
        write_json(
            latest / "daily_operating_selection_refresh" / "summary.json",
            {
                "schema_version": "daily-operating-selection-refresh-v1",
                "daily_operating_refresh": True,
                "review_only": True,
                "canonical_production_sync": False,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "selection_allowed": False,
                "promotion_allowed": False,
                "source_of_truth_level": "GITHUB_ARTIFACT",
            },
        )
        write_json(user_current / "summary.json", {"schema_version": "user-current-report-v1", "status": "completed"})
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "row_type": "equity",
                    "ticker": "AAA",
                    "current_weight": 0.02,
                    "current_shares": 4,
                    "current_price": 100.0,
                },
                {
                    "portfolio_kind": "main",
                    "row_type": "equity",
                    "ticker": "OLD",
                    "current_weight": 0.03,
                    "current_shares": 3,
                    "current_price": 100.0,
                },
            ]
        ).to_csv(user_current / "01_current_holdings.csv", index=False)
        (user_current / "DAILY_REVIEW_ONLY.md").write_text(
            "# Daily Review-Only Current Output\n\n- review_only: `true`\n",
            encoding="utf-8",
        )
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "rank": 1,
                    "ticker": "AAA",
                    "company_name": "A Co",
                    "sector": "Tech",
                    "recommended_weight": 0.12,
                    "current_account_weight": 0.02,
                    "score": 3.4,
                    "reference_price": 100.0,
                    "reference_price_date": "2026-06-12",
                    "suggested_action": "BUY_OR_HOLD_TO_TARGET",
                    "buy_logic": "fixture leader",
                }
            ]
        ).to_csv(latest / "user_portfolio_reports" / "main_recommendation_latest.csv", index=False)

        payload = build_contract(
            type(
                "Args",
                (),
                {
                    "latest_run": str(latest),
                    "output_dir": str(user_current),
                    "source_run_id": "123",
                    "source_commit_sha": "abc",
                    "source_branch": "master",
                    "source_artifact_name": "daily-operating-selection-refresh-123",
                },
            )()
        )

        assert payload["status"] == "completed"
        for name in [
            "02_target_weights.csv",
            "03_order_preview.csv",
            "08_rebalance_decision.json",
            "09_daily_output_contract_summary.json",
        ]:
            assert (user_current / name).exists(), name

        target = pd.read_csv(user_current / "02_target_weights.csv")
        orders = pd.read_csv(user_current / "03_order_preview.csv")
        decision = json.loads((user_current / "08_rebalance_decision.json").read_text(encoding="utf-8"))
        daily = json.loads((latest / "daily_operating_selection_refresh" / "summary.json").read_text(encoding="utf-8"))
        summary = json.loads((user_current / "summary.json").read_text(encoding="utf-8"))
        notice = (user_current / "DAILY_REVIEW_ONLY.md").read_text(encoding="utf-8")

        assert target.iloc[0]["ticker"] == "AAA"
        assert abs(float(target.iloc[0]["current_weight"]) - 0.02) < 1e-9
        assert abs(float(target.iloc[0]["delta_weight"]) - 0.10) < 1e-9
        assert bool(target.iloc[0]["review_required"]) is True
        assert bool(target.iloc[0]["production_mutation_allowed"]) is False
        assert bool(orders.iloc[0]["human_approval_required"]) is True
        assert orders.iloc[0]["action"] == "REVIEW_REQUIRED"
        old_order = orders.loc[orders["ticker"].eq("OLD")].iloc[0]
        assert abs(float(old_order["current_weight"]) - 0.03) < 1e-9
        assert abs(float(old_order["target_weight"])) < 1e-9
        assert old_order["order_source"] == "current_snapshot_vs_target_review_only"
        assert decision["decision"] == "REVIEW_REQUIRED"
        assert decision["selection_allowed"] is False
        assert decision["promotion_allowed"] is False
        assert decision["production_promotion_allowed"] is False
        assert decision["live_trading_enabled"] is False
        assert decision["human_approval_required"] is True
        assert decision["snapshot_contract_pass"] is True
        assert daily["human_approval_required"] is True
        assert daily["production_promotion_allowed"] is False
        assert daily["current_snapshot_used_for_order_preview"] is True
        assert summary["production_promotion_allowed"] is False
        assert "production_promotion_allowed: `false`" in notice
        assert daily["snapshot_contract_pass"] is True
        assert daily["snapshot_contract"]["order_delta_weight_max_abs_drift"] < 1e-9
        assert summary["human_approval_required"] is True
        assert summary["current_snapshot_used_for_order_preview"] is True
        assert summary["snapshot_contract_pass"] is True
        assert "human_approval_required" in notice


def test_contract_blocks_missing_current_snapshot() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        user_current = latest / "user_current"
        (latest / "user_portfolio_reports").mkdir(parents=True)
        user_current.mkdir(parents=True)

        write_json(
            latest / "data_freshness_contract" / "status.json",
            {
                "schema_version": "data-freshness-contract-v1",
                "status": "pass",
                "selection_allowed": True,
                "promotion_allowed": False,
                "recommendation_status": "REVIEW_REQUIRED",
                "blockers": [],
                "warnings": [],
                "production_mutation_allowed": False,
            },
        )
        write_json(
            latest / "daily_operating_selection_refresh" / "summary.json",
            {
                "schema_version": "daily-operating-selection-refresh-v1",
                "daily_operating_refresh": True,
                "review_only": True,
                "canonical_production_sync": False,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "selection_allowed": True,
                "promotion_allowed": False,
                "source_of_truth_level": "GITHUB_ARTIFACT",
            },
        )
        write_json(user_current / "summary.json", {"schema_version": "user-current-report-v1", "status": "completed"})
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "rank": 1,
                    "ticker": "AAA",
                    "recommended_weight": 0.12,
                    "current_account_weight": 0.0,
                    "score": 3.4,
                }
            ]
        ).to_csv(latest / "user_portfolio_reports" / "main_recommendation_latest.csv", index=False)

        payload = build_contract(
            type(
                "Args",
                (),
                {
                    "latest_run": str(latest),
                    "output_dir": str(user_current),
                    "source_run_id": "124",
                    "source_commit_sha": "def",
                    "source_branch": "master",
                    "source_artifact_name": "daily-operating-selection-refresh-124",
                },
            )()
        )

        decision = json.loads((user_current / "08_rebalance_decision.json").read_text(encoding="utf-8"))
        daily = json.loads((latest / "daily_operating_selection_refresh" / "summary.json").read_text(encoding="utf-8"))
        assert payload["snapshot_contract_pass"] is False
        assert any("current holdings snapshot missing" in item for item in payload["snapshot_contract_blockers"])
        assert decision["decision"] == "REVIEW_REQUIRED"
        assert decision["snapshot_contract_pass"] is False
        assert any("snapshot_contract:" in item for item in decision["blockers"])
        assert daily["snapshot_contract_pass"] is False
        assert daily["current_snapshot_used_for_order_preview"] is False


def test_contract_propagates_pre_broker_substrate_blockers() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        user_current = latest / "user_current"
        (latest / "user_portfolio_reports").mkdir(parents=True)
        user_current.mkdir(parents=True)

        write_json(
            latest / "data_freshness_contract" / "status.json",
            {
                "schema_version": "data-freshness-contract-v1",
                "status": "pass",
                "selection_allowed": True,
                "promotion_allowed": False,
                "recommendation_status": "READY_FOR_OPERATING_SELECTION",
                "blockers": [],
                "warnings": [],
                "production_mutation_allowed": False,
            },
        )
        write_json(
            latest / "daily_operating_selection_refresh" / "summary.json",
            {
                "schema_version": "daily-operating-selection-refresh-v1",
                "daily_operating_refresh": True,
                "review_only": True,
                "canonical_production_sync": False,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "selection_allowed": True,
                "promotion_allowed": False,
                "source_of_truth_level": "GITHUB_ARTIFACT",
            },
        )
        write_json(
            latest / "pre_broker_substrate_gate" / "summary.json",
            {
                "status": "blocked",
                "broker_replay_allowed": False,
                "blockers": ["universe_health_promotion_not_allowed"],
                "recovery": {
                    "fallback_available": True,
                    "recommended_recovery_source": "committed_static_IWB_seed",
                    "recovery_action": "repair_universe_from_fallback",
                },
            },
        )
        write_json(user_current / "summary.json", {"schema_version": "user-current-report-v1", "status": "completed"})
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "row_type": "equity",
                    "ticker": "AAA",
                    "current_weight": 0.02,
                    "current_shares": 4,
                    "current_price": 100.0,
                }
            ]
        ).to_csv(user_current / "01_current_holdings.csv", index=False)
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "rank": 1,
                    "ticker": "AAA",
                    "recommended_weight": 0.12,
                    "current_account_weight": 0.02,
                    "score": 3.4,
                }
            ]
        ).to_csv(latest / "user_portfolio_reports" / "main_recommendation_latest.csv", index=False)

        payload = build_contract(
            type(
                "Args",
                (),
                {
                    "latest_run": str(latest),
                    "output_dir": str(user_current),
                    "source_run_id": "125",
                    "source_commit_sha": "ghi",
                    "source_branch": "master",
                    "source_artifact_name": "daily-operating-selection-refresh-125",
                },
            )()
        )

        decision = json.loads((user_current / "08_rebalance_decision.json").read_text(encoding="utf-8"))
        daily = json.loads((latest / "daily_operating_selection_refresh" / "summary.json").read_text(encoding="utf-8"))
        summary = json.loads((user_current / "09_daily_output_contract_summary.json").read_text(encoding="utf-8"))
        assert payload["selection_allowed"] is False
        assert payload["recommendation_status"] == "DO_NOT_USE_REVIEW_REQUIRED"
        assert "universe_health_promotion_not_allowed" in payload["substrate_blockers"]
        assert payload["substrate_recovery"]["recommended_recovery_source"] == "committed_static_IWB_seed"
        assert decision["selection_allowed"] is False
        assert decision["pre_broker_substrate_gate_status"] == "blocked"
        assert any("substrate:" in item for item in decision["blockers"])
        assert daily["selection_allowed"] is False
        assert daily["substrate_recovery"]["recovery_action"] == "repair_universe_from_fallback"
        assert summary["pre_broker_broker_replay_allowed"] is False


def test_contract_honors_daily_summary_substrate_blockers() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        user_current = latest / "user_current"
        (latest / "user_portfolio_reports").mkdir(parents=True)
        user_current.mkdir(parents=True)

        write_json(
            latest / "data_freshness_contract" / "status.json",
            {
                "schema_version": "data-freshness-contract-v1",
                "status": "pass",
                "selection_allowed": True,
                "promotion_allowed": True,
                "recommendation_status": "READY_FOR_OPERATING_SELECTION",
                "blockers": [],
                "warnings": [],
                "production_mutation_allowed": False,
            },
        )
        write_json(
            latest / "daily_operating_selection_refresh" / "summary.json",
            {
                "schema_version": "daily-operating-selection-refresh-v1",
                "daily_operating_refresh": True,
                "review_only": True,
                "canonical_production_sync": False,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "selection_allowed": False,
                "promotion_allowed": False,
                "selection_blockers": ["universe_health_selection_blocked"],
                "recommendation_status": "DO_NOT_USE_REVIEW_REQUIRED",
                "source_of_truth_level": "GITHUB_ARTIFACT",
            },
        )
        write_json(user_current / "summary.json", {"schema_version": "user-current-report-v1", "status": "completed"})
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "row_type": "equity",
                    "ticker": "AAA",
                    "current_weight": 0.02,
                    "current_shares": 4,
                    "current_price": 100.0,
                }
            ]
        ).to_csv(user_current / "01_current_holdings.csv", index=False)
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "rank": 1,
                    "ticker": "AAA",
                    "recommended_weight": 0.12,
                    "current_account_weight": 0.02,
                    "score": 3.4,
                }
            ]
        ).to_csv(latest / "user_portfolio_reports" / "main_recommendation_latest.csv", index=False)

        payload = build_contract(
            type(
                "Args",
                (),
                {
                    "latest_run": str(latest),
                    "output_dir": str(user_current),
                    "source_run_id": "126",
                    "source_commit_sha": "jkl",
                    "source_branch": "master",
                    "source_artifact_name": "daily-operating-selection-refresh-126",
                },
            )()
        )

        decision = json.loads((user_current / "08_rebalance_decision.json").read_text(encoding="utf-8"))
        daily = json.loads((latest / "daily_operating_selection_refresh" / "summary.json").read_text(encoding="utf-8"))
        summary = json.loads((user_current / "09_daily_output_contract_summary.json").read_text(encoding="utf-8"))
        assert payload["selection_allowed"] is False
        assert payload["promotion_allowed"] is False
        assert payload["production_promotion_allowed"] is False
        assert payload["recommendation_status"] == "DO_NOT_USE_REVIEW_REQUIRED"
        assert "daily_summary_selection_allowed=false" in payload["blockers"]
        assert "daily_summary: universe_health_selection_blocked" in payload["blockers"]
        assert decision["selection_allowed"] is False
        assert decision["promotion_allowed"] is False
        assert decision["production_promotion_allowed"] is False
        assert daily["selection_allowed"] is False
        assert daily["promotion_allowed"] is False
        assert daily["production_promotion_allowed"] is False
        assert summary["selection_allowed"] is False
        assert summary["promotion_allowed"] is False
        assert summary["production_promotion_allowed"] is False


def test_contract_blocks_missing_pre_broker_substrate_status() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        user_current = latest / "user_current"
        (latest / "user_portfolio_reports").mkdir(parents=True)
        user_current.mkdir(parents=True)

        write_json(
            latest / "data_freshness_contract" / "status.json",
            {
                "schema_version": "data-freshness-contract-v1",
                "status": "pass",
                "selection_allowed": True,
                "promotion_allowed": True,
                "recommendation_status": "READY_FOR_OPERATING_SELECTION",
                "blockers": [],
                "warnings": [],
                "production_mutation_allowed": False,
            },
        )
        write_json(
            latest / "daily_operating_selection_refresh" / "summary.json",
            {
                "schema_version": "daily-operating-selection-refresh-v1",
                "daily_operating_refresh": True,
                "review_only": True,
                "canonical_production_sync": False,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "selection_allowed": True,
                "promotion_allowed": False,
                "source_of_truth_level": "GITHUB_ARTIFACT",
            },
        )
        write_json(user_current / "summary.json", {"schema_version": "user-current-report-v1", "status": "completed"})
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "row_type": "equity",
                    "ticker": "AAA",
                    "current_weight": 0.02,
                    "current_shares": 4,
                    "current_price": 100.0,
                }
            ]
        ).to_csv(user_current / "01_current_holdings.csv", index=False)
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "rank": 1,
                    "ticker": "AAA",
                    "recommended_weight": 0.12,
                    "current_account_weight": 0.02,
                    "score": 3.4,
                }
            ]
        ).to_csv(latest / "user_portfolio_reports" / "main_recommendation_latest.csv", index=False)

        payload = build_contract(
            type(
                "Args",
                (),
                {
                    "latest_run": str(latest),
                    "output_dir": str(user_current),
                    "source_run_id": "127",
                    "source_commit_sha": "mno",
                    "source_branch": "master",
                    "source_artifact_name": "daily-operating-selection-refresh-127",
                },
            )()
        )

        decision = json.loads((user_current / "08_rebalance_decision.json").read_text(encoding="utf-8"))
        summary = json.loads((user_current / "09_daily_output_contract_summary.json").read_text(encoding="utf-8"))
        assert payload["selection_allowed"] is False
        assert payload["promotion_allowed"] is False
        assert payload["production_promotion_allowed"] is False
        assert payload["recommendation_status"] == "DO_NOT_USE_REVIEW_REQUIRED"
        assert "pre_broker_substrate_gate_missing" in payload["substrate_blockers"]
        assert "pre_broker_broker_replay_allowed_missing" in payload["substrate_blockers"]
        assert decision["selection_allowed"] is False
        assert decision["promotion_allowed"] is False
        assert decision["production_promotion_allowed"] is False
        assert summary["selection_allowed"] is False
        assert summary["promotion_allowed"] is False
        assert summary["production_promotion_allowed"] is False


def main() -> int:
    test_contract_writes_required_review_only_files()
    test_contract_blocks_missing_current_snapshot()
    test_contract_propagates_pre_broker_substrate_blockers()
    test_contract_honors_daily_summary_substrate_blockers()
    test_contract_blocks_missing_pre_broker_substrate_status()
    print("daily_user_current_contract_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
