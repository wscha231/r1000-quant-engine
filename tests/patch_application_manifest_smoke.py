#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from argparse import Namespace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_patch_application_manifest import build_manifest


def test_patch_application_manifest_records_research_only_separation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        (latest / "account_evaluation").mkdir(parents=True)
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            '{"official_metric_mode":"broker_ledger_next_close","valid_for_production":true}\n',
            encoding="utf-8",
        )
        integrated = latest / "integrated_theme_leader_crisis_replay"
        integrated.mkdir(parents=True)
        (integrated / "summary.json").write_text('{"status":"completed","case_failure_count":0}\n', encoding="utf-8")
        (integrated / "replay_gate_status.json").write_text('{"status":"passed"}\n', encoding="utf-8")
        (integrated / "promotion_gate_status.json").write_text(
            '{"status":"rejected","production_activation_allowed":false}\n',
            encoding="utf-8",
        )
        (integrated / "production_mutation_check.json").write_text('{"status":"passed"}\n', encoding="utf-8")
        (latest / "reports").mkdir()
        (latest / "reports" / "candidate_replay_book.csv").write_text("ticker,rebalance_date\nAAA,2026-01-31\n", encoding="utf-8")

        payload = build_manifest(
            Namespace(
                latest_run=str(latest),
                output=str(root / "manifest.json"),
                run_id="123",
                run_attempt="1",
                head_sha="abc",
                branch="codex/test",
                artifact_id="456",
                sidecar_profile="official",
                artifact_profile="official",
                gdrive_sync_mode="research",
                portfolio_policy="integrated_shadow",
                approved_target_policy_path="outputs/promotion_review/approved_target_policy.json",
            )
        )
        assert payload["production_applied"] is False
        assert payload["sidecar_only"] is True
        assert payload["production_mutated"] is False
        assert payload["candidate_replay_book_present"] is True
        assert payload["portfolio_policy"] == "integrated_shadow"
        assert payload["approved_target_policy_path"] == "outputs/promotion_review/approved_target_policy.json"
        assert payload["sidecar_applied_to_production"] is False
        assert payload["reason_not_applied_to_current_holdings"] == "research_only_sidecar_promotion_gate_not_passed"
        assert (latest / "replay_integrity" / "patch_application_manifest.json").exists()
        executed = {row["name"]: row["executed"] for row in payload["executed_sidecars"]}
        assert executed["integrated_theme_leader_crisis_replay"] is True
        assert executed["user_current_research_only_notice"] is False


def test_patch_application_manifest_records_alphaops_vnext_production() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        (latest / "account_evaluation").mkdir(parents=True)
        (latest / "alphaops_vnext").mkdir(parents=True)
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            '{"official_metric_mode":"broker_ledger_next_close","valid_for_production":true}\n',
            encoding="utf-8",
        )
        (latest / "alphaops_vnext" / "summary.json").write_text('{"status":"completed"}\n', encoding="utf-8")
        (latest / "alphaops_vnext" / "production_activation.json").write_text(
            '{"status":"applied","current_holdings_source":"alphaops_vnext_policy_target_book"}\n',
            encoding="utf-8",
        )
        payload = build_manifest(
            Namespace(
                latest_run=str(latest),
                output=str(root / "manifest.json"),
                run_id="123",
                run_attempt="1",
                head_sha="abc",
                branch="codex/test",
                artifact_id="456",
                sidecar_profile="official",
                artifact_profile="official",
                gdrive_sync_mode="research",
                portfolio_policy="alphaops_vnext_production",
                approved_target_policy_path="outputs/promotion_review/approved_target_policy.json",
            )
        )
        assert payload["production_applied"] is True
        assert payload["sidecar_only"] is False
        assert payload["production_mutated"] is True
        assert payload["current_holdings_source"] == "alphaops_vnext_policy_target_book"
        assert payload["reason_not_applied_to_current_holdings"] == "alphaops_vnext_production_replaced_operating_books"
        assert payload["alphaops_vnext_activation_status"] == "applied"


if __name__ == "__main__":
    test_patch_application_manifest_records_research_only_separation()
    test_patch_application_manifest_records_alphaops_vnext_production()
    print("patch_application_manifest_smoke: PASS")
