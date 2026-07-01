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
        assert decision["live_trading_enabled"] is False
        assert decision["human_approval_required"] is True
        assert daily["human_approval_required"] is True
        assert daily["current_snapshot_used_for_order_preview"] is True
        assert summary["human_approval_required"] is True
        assert summary["current_snapshot_used_for_order_preview"] is True
        assert "human_approval_required" in notice


def test_contract_prefers_operating_target_books_over_user_reports() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        user_current = latest / "user_current"
        (latest / "user_portfolio_reports").mkdir(parents=True)
        (latest / "reports").mkdir(parents=True)
        user_current.mkdir(parents=True)
        write_json(
            latest / "data_freshness_contract" / "status.json",
            {
                "status": "pass",
                "selection_allowed": True,
                "promotion_allowed": False,
                "recommendation_status": "READY_FOR_OPERATING_SELECTION",
                "production_mutation_allowed": False,
            },
        )
        write_json(
            latest / "daily_operating_selection_refresh" / "summary.json",
            {
                "review_only": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "selection_allowed": True,
                "promotion_allowed": False,
            },
        )
        write_json(user_current / "summary.json", {"schema_version": "user-current-report-v1", "status": "completed"})
        pd.DataFrame(
            [
                {"portfolio_kind": "main", "ticker": "AAA", "current_weight": 0.10, "current_shares": 10, "current_price": 100.0},
            ]
        ).to_csv(user_current / "01_current_holdings.csv", index=False)
        pd.DataFrame(
            [
                {"portfolio_kind": "main", "rank": 1, "ticker": "RAW", "recommended_weight": 0.90, "score": 9.0},
            ]
        ).to_csv(latest / "user_portfolio_reports" / "main_recommendation_latest.csv", index=False)
        pd.DataFrame(
            [
                {"rebalance_date": "2026-06-29", "ticker": "AAA", "weight": 0.25, "Name": "A Co", "sector": "Tech"},
                {"rebalance_date": "2026-06-29", "ticker": "CASH", "weight": 0.75, "Name": "Cash", "sector": "Cash"},
            ]
        ).to_csv(latest / "reports" / "operating_main_target_book.csv", index=False)

        build_contract(
            type(
                "Args",
                (),
                {
                    "latest_run": str(latest),
                    "output_dir": str(user_current),
                    "source_run_id": "123",
                    "source_commit_sha": "abc",
                    "source_branch": "master",
                    "source_artifact_name": "fixture",
                },
            )()
        )

        target = pd.read_csv(user_current / "02_target_weights.csv")
        assert "RAW" not in set(target["ticker"])
        aaa = target.loc[target["ticker"].eq("AAA")].iloc[0]
        assert abs(float(aaa["target_weight"]) - 0.25) < 1e-9
        assert aaa["target_snapshot_semantics"] == "alphaops_vnext_operating_target"
        assert str(aaa["target_snapshot_hash"])


def main() -> int:
    test_contract_writes_required_review_only_files()
    test_contract_prefers_operating_target_books_over_user_reports()
    print("daily_user_current_contract_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
