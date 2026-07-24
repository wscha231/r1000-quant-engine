#!/usr/bin/env python3
"""Smoke coverage for immutable Run287 catch-up target evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_catchup_target_evidence import (
    BLOCKED_STATUS,
    READY_STATUS,
    build,
)
from tools.run_daily_simulated_fill_ledger import normalized_target, target_hash


SESSION = "2026-07-17"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_artifact(root: Path) -> tuple[Path, Path]:
    artifact = root / "daily-operating-selection-refresh-123"
    reports = artifact / "outputs/reports"
    preview_root = artifact / "outputs/account_ledger_preview"
    reports.mkdir(parents=True)
    portfolios: dict[str, dict] = {}
    allocations = {
        "main": [("AAA", 0.60), ("BBB", 0.30), ("CASH", 0.10)],
        "concentrated": [("CCC", 0.70), ("DDD", 0.30)],
    }
    for portfolio, rows in allocations.items():
        source = reports / f"operating_{portfolio}_target_book.csv"
        frame = pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-07-16",
                    "ticker": ticker,
                    "weight": weight,
                    "Name": ticker,
                }
                for ticker, weight in rows
            ]
            + [
                {
                    "rebalance_date": SESSION,
                    "ticker": ticker,
                    "weight": weight,
                    "Name": ticker,
                }
                for ticker, weight in rows
            ]
        )
        frame.to_csv(source, index=False)
        normalized = normalized_target(source, portfolio, pd.Timestamp(SESSION))
        preview = preview_root / portfolio
        preview.mkdir(parents=True)
        normalized.to_csv(preview / "target_weights.csv", index=False)
        non_cash = normalized.loc[
            ~normalized["ticker"].isin({"CASH", "__CASH__"}), "target_weight"
        ].sum()
        cash = normalized.loc[
            normalized["ticker"].isin({"CASH", "__CASH__"}), "target_weight"
        ].sum()
        write_json(
            preview / "preview_metrics.json",
            {
                "schema_version": "account-ledger-preview-v1",
                "status": "completed",
                "portfolio_kind": portfolio,
                "as_of_date": SESSION,
                "account_state_as_of_date": SESSION,
                "target_count": len(normalized),
                "target_stock_weight": float(non_cash),
                "target_cash_weight": float(cash),
            },
        )
        write_json(
            preview / "order_batch_manifest.json",
            {
                "schema_version": "account-ledger-preview-order-batch-v1",
                "portfolio_kind": portfolio,
                "as_of_date": SESSION,
            },
        )
        portfolios[portfolio] = {
            "schema_version": "daily-simulated-fill-ledger-manifest-v1",
            "portfolio_kind": portfolio,
            "as_of_date": SESSION,
            "target_effective_date": SESSION,
            "target_sha256": sha256(source),
            "target_hash": target_hash(normalized),
            "review_only": True,
            "simulated": True,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
        }
    write_json(
        artifact / "outputs/daily_simulated_fill_ledger/summary.json",
        {
            "schema_version": "daily-simulated-fill-ledger-summary-v1",
            "status": "completed",
            "as_of_date": SESSION,
            "review_only": True,
            "simulated": True,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
            "portfolios": portfolios,
        },
    )
    metadata = root / "artifact_metadata.json"
    write_json(
        metadata,
        {
            "schema_version": "github-artifact-download-metadata-v2",
            "run_id": "123",
            "artifact_id": "456",
            "artifact_name": artifact.name,
            "artifact_zip_sha256": "a" * 64,
            "artifact_api_digest": f"sha256:{'a' * 64}",
            "artifact_captured_at_utc": "2026-07-18T02:05:00+00:00",
            "workflow_id": "789",
            "workflow_path": ".github/workflows/daily_operating_selection_refresh.yml",
            "head_branch": "master",
            "head_sha": "b" * 40,
            "workflow_event": "workflow_dispatch",
            "workflow_status": "completed",
            "workflow_conclusion": "success",
            "workflow_created_at_utc": "2026-07-18T01:00:00+00:00",
            "workflow_updated_at_utc": "2026-07-18T02:10:00+00:00",
            "workflow_run_attempt": "1",
            "repository": "example/repo",
            "head_repository": "example/repo",
            "default_branch": "master",
            "current_default_head_sha": "c" * 40,
            "origin_verification_mode": "DEFAULT_BRANCH_ANCESTOR",
            "workflow_identity_verified": True,
            "repository_identity_verified": True,
            "head_lineage_verified": True,
        },
    )
    return artifact, metadata


def run_build(root: Path, artifact: Path, metadata: Path) -> tuple[dict, Path, Path]:
    output = root / "target_evidence"
    status = root / "status.json"
    payload = build(
        argparse.Namespace(
            artifact_root=str(artifact),
            artifact_metadata=str(metadata),
            session_date=SESSION,
            output_target_dir=str(output),
            output_evidence=str(status),
        )
    )
    return payload, output, status


def test_materializes_original_target_bytes_with_ledger_and_preview_binding() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact, metadata = make_artifact(root)
        payload, output, status = run_build(root, artifact, metadata)
        assert payload["status"] == READY_STATUS
        assert payload["target_evidence_materialized"] is True
        assert status.is_file()
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["replay_only"] is True
        assert manifest["targets_recomputed"] is False
        for portfolio in ("main", "concentrated"):
            original = (
                artifact
                / "outputs/reports"
                / f"operating_{portfolio}_target_book.csv"
            )
            restored = output / f"operating_{portfolio}_target_book.csv"
            assert restored.read_bytes() == original.read_bytes()
            target = manifest["targets"][portfolio]
            assert target["ledger_binding_verified"] is True
            assert target["preview_binding_verified"] is True
            assert target["source_target"]["sha256"] == target["materialized_target"]["sha256"]


def test_fails_closed_on_source_sha_preview_or_future_mismatch() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)

        artifact, metadata = make_artifact(root / "sha")
        source = artifact / "outputs/reports/operating_main_target_book.csv"
        source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        payload, output, _ = run_build(root / "sha", artifact, metadata)
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == ["source_target_sha_mismatch:main"]
        assert not output.exists()

        artifact, metadata = make_artifact(root / "preview")
        preview = artifact / "outputs/account_ledger_preview/main/target_weights.csv"
        frame = pd.read_csv(preview)
        frame.loc[frame["ticker"] == "AAA", "target_weight"] = 0.59
        frame.to_csv(preview, index=False)
        payload, output, _ = run_build(root / "preview", artifact, metadata)
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == [
            "preview_target_normalized_hash_mismatch:main"
        ]
        assert not output.exists()

        artifact, metadata = make_artifact(root / "future")
        source = artifact / "outputs/reports/operating_main_target_book.csv"
        frame = pd.read_csv(source)
        future = frame.iloc[[0]].copy()
        future["rebalance_date"] = "2026-07-20"
        pd.concat([frame, future], ignore_index=True).to_csv(source, index=False)
        summary = artifact / "outputs/daily_simulated_fill_ledger/summary.json"
        value = json.loads(summary.read_text(encoding="utf-8"))
        value["portfolios"]["main"]["target_sha256"] = sha256(source)
        write_json(summary, value)
        payload, output, _ = run_build(root / "future", artifact, metadata)
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == ["source_target_future_rows:main"]
        assert not output.exists()


if __name__ == "__main__":
    test_materializes_original_target_bytes_with_ledger_and_preview_binding()
    test_fails_closed_on_source_sha_preview_or_future_mismatch()
    print("run287_catchup_target_evidence_smoke: PASS")
