#!/usr/bin/env python3
"""Smoke checks for trusted, replay-only Run287 catch-up price evidence."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_catchup_price_evidence import (  # noqa: E402
    BLOCKED_STATUS,
    ContractError,
    READY_STATUS,
    build,
    validate_github_compare_payload,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.run_daily_simulated_fill_ledger import (  # noqa: E402
    validate_replay_price_evidence,
)


RUN_ID = "29801446668"
SESSION_DATE = "2026-07-20"
ZIP_SHA256 = "a" * 64


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def source_row(
    ticker: str,
    *,
    latest_price_date: str = SESSION_DATE,
    price_available: bool = True,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "price_available": price_available,
        "price_missing_reason": "" if price_available else "missing",
        "latest_price_date": latest_price_date,
        "open": 100.0,
        "high": 105.0,
        "low": 98.0,
        "previous_close": 102.0,
        "adjusted_close": 101.5,
        "volume": 1_000_000.0,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
    }


def make_artifact(root: Path) -> tuple[Path, Path]:
    artifact = root / f"daily-operating-selection-refresh-{RUN_ID}"
    metadata = root / "github_artifact_metadata.json"
    write_json(
        metadata,
        {
            "schema_version": "github-artifact-download-metadata-v2",
            "run_id": RUN_ID,
            "artifact_id": "8484210406",
            "artifact_name": artifact.name,
            "artifact_zip_sha256": ZIP_SHA256,
            "artifact_api_digest": f"sha256:{ZIP_SHA256}",
            "artifact_captured_at_utc": "2026-07-21T05:00:00+00:00",
            "workflow_id": "296748480",
            "workflow_path": (
                ".github/workflows/"
                "daily_operating_selection_refresh.yml"
            ),
            "head_branch": "master",
            "head_sha": "b" * 40,
            "workflow_event": "schedule",
            "workflow_status": "completed",
            "workflow_conclusion": "failure",
            "workflow_created_at_utc": "2026-07-21T04:30:00+00:00",
            "workflow_updated_at_utc": "2026-07-21T05:10:00+00:00",
            "workflow_run_attempt": "1",
            "repository": "wscha231/r1000-quant-engine",
            "head_repository": "wscha231/r1000-quant-engine",
            "default_branch": "master",
            "current_default_head_sha": "c" * 40,
            "origin_verification_mode": "DEFAULT_BRANCH_ANCESTOR",
            "workflow_identity_verified": True,
            "repository_identity_verified": True,
            "head_lineage_verified": True,
        },
    )
    write_json(
        artifact / "outputs/daily_market_session_gate/session.json",
        {
            "schema_version": "daily-market-session-gate-v1",
            "status": "READY_COMPLETED_SESSION",
            "ready": True,
            "calendar": "NYSE",
            "session_date": SESSION_DATE,
            "market_close_utc": "2026-07-20T20:00:00+00:00",
            "checked_at_utc": "2026-07-21T04:37:12+00:00",
        },
    )
    write_json(
        artifact / "outputs/daily_market_snapshot/summary.json",
        {
            "schema_version": "daily-market-snapshot-v1",
            "status": "completed",
            "ticker_count": 3,
            "latest_price_date_min": "2026-07-17",
            "latest_price_date_max": SESSION_DATE,
            "generated_at_utc": "2026-07-21T04:52:38+00:00",
            "review_only": True,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
        },
    )
    snapshot = artifact / "outputs/daily_market_snapshot/market_snapshot.csv"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            source_row("AAA"),
            source_row("BBB"),
            source_row("OLD", latest_price_date="2026-07-17"),
        ]
    ).to_csv(snapshot, index=False)
    return artifact, metadata


def run_build(
    root: Path,
    artifact: Path,
    metadata: Path,
    *,
    tickers: list[str] | None = None,
    suffix: str = "",
) -> tuple[dict[str, object], Path, Path]:
    cache = root / f"cache{suffix}"
    evidence = root / f"evidence{suffix}.json"
    payload = build(
        Namespace(
            artifact_root=str(artifact),
            artifact_metadata=str(metadata),
            session_date=SESSION_DATE,
            ticker=["AAA", "BBB"] if tickers is None else tickers,
            output_cache=str(cache),
            output_evidence=str(evidence),
        )
    )
    return payload, cache, evidence


def test_materializes_only_exact_used_rows_with_provenance() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact, metadata = make_artifact(root)
        payload, cache, evidence = run_build(root, artifact, metadata)

        assert payload["status"] == READY_STATUS
        assert payload["contract_failures"] == []
        assert payload["materialized_ticker_count"] == 2
        assert payload["stale_source_row_count_excluded"] == 1
        assert payload["future_source_row_count"] == 0
        assert payload["replay_only"] is True
        assert payload["forward_promotion_eligible"] is False
        assert payload["production_mutation_allowed"] is False
        assert payload["live_trading_enabled"] is False
        assert payload["network_requests_executed"] == 0
        assert evidence.is_file()

        for ticker in ("AAA", "BBB"):
            price = pd.read_parquet(cache / px_cache_name(ticker))
            assert len(price) == 1
            assert pd.Timestamp(price.index[0]).date().isoformat() == SESSION_DATE
            assert list(price.columns) == [
                "Open",
                "High",
                "Low",
                "Close",
                "Adj Close",
                "Volume",
            ]
            assert float(price.iloc[0]["Close"]) == 102.0
            assert float(price.iloc[0]["Adj Close"]) == 101.5
        assert not (cache / px_cache_name("OLD")).exists()

        manifest = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["status"] == READY_STATUS
        assert manifest["artifact"]["run_id"] == RUN_ID
        assert manifest["artifact"]["expected_zip_sha256"] == ZIP_SHA256
        assert manifest["artifact"]["run_id_verified_against_artifact_root"] is True
        assert manifest["ticker_count"] == 2
        assert len(manifest["source_files"]) == 4
        assert all(len(item["sha256"]) == 64 for item in manifest["source_files"])
        assert all(len(item["sha256"]) == 64 for item in manifest["price_files"])
        assert manifest["replay_only"] is True
        assert manifest["forward_promotion_eligible"] is False

        all_payload, all_cache, _ = run_build(
            root,
            artifact,
            metadata,
            tickers=[],
            suffix="_all_exact",
        )
        assert all_payload["status"] == READY_STATUS
        assert all_payload["ticker_selection_mode"] == "ALL_EXACT_SESSION_TICKERS"
        assert all_payload["required_tickers"] == ["AAA", "BBB"]
        assert not (all_cache / px_cache_name("OLD")).exists()

        anomaly_artifact, anomaly_metadata = make_artifact(
            root / "reference_anomaly"
        )
        anomaly_snapshot = (
            anomaly_artifact
            / "outputs/daily_market_snapshot/market_snapshot.csv"
        )
        anomaly_frame = pd.read_csv(anomaly_snapshot)
        anomaly_frame.loc[
            anomaly_frame["ticker"] == "AAA",
            "open",
        ] = 106.0
        anomaly_frame.to_csv(anomaly_snapshot, index=False)
        anomaly_payload, anomaly_cache, _ = run_build(
            root / "reference_anomaly",
            anomaly_artifact,
            anomaly_metadata,
        )
        assert anomaly_payload["status"] == READY_STATUS
        assert anomaly_payload["ohlc_execution_eligible"] is False
        assert anomaly_payload["reference_ohlc_anomaly_count"] == 1
        assert anomaly_payload["reference_ohlc_anomalies"][0][
            "code"
        ] == "OPEN_OUTSIDE_LOW_HIGH"
        revalidated = validate_replay_price_evidence(
            price_cache=anomaly_cache,
            manifest_path=anomaly_cache / "manifest.json",
            as_of_date=pd.Timestamp(SESSION_DATE),
        )
        assert revalidated["ticker_count"] == 2


def test_fails_closed_on_stale_missing_duplicate_and_future_rows() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)

        artifact, metadata = make_artifact(root / "stale")
        payload, cache, _ = run_build(
            root / "stale",
            artifact,
            metadata,
            tickers=["OLD"],
        )
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == ["required_ticker_stale:OLD"]
        assert not cache.exists()

        artifact, metadata = make_artifact(root / "missing")
        payload, cache, _ = run_build(
            root / "missing",
            artifact,
            metadata,
            tickers=["MISSING"],
        )
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == ["required_ticker_missing:MISSING"]
        assert not cache.exists()

        artifact, metadata = make_artifact(root / "duplicate")
        snapshot = artifact / "outputs/daily_market_snapshot/market_snapshot.csv"
        frame = pd.read_csv(snapshot)
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
        frame.to_csv(snapshot, index=False)
        summary = artifact / "outputs/daily_market_snapshot/summary.json"
        value = json.loads(summary.read_text(encoding="utf-8"))
        value["ticker_count"] = 4
        write_json(summary, value)
        payload, cache, _ = run_build(root / "duplicate", artifact, metadata)
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == ["market_snapshot_duplicate_ticker"]
        assert not cache.exists()

        artifact, metadata = make_artifact(root / "future")
        snapshot = artifact / "outputs/daily_market_snapshot/market_snapshot.csv"
        frame = pd.read_csv(snapshot)
        frame.loc[frame["ticker"] == "OLD", "latest_price_date"] = "2026-07-21"
        frame.to_csv(snapshot, index=False)
        payload, cache, _ = run_build(root / "future", artifact, metadata)
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == ["market_snapshot_future_date"]
        assert not cache.exists()


def test_fails_closed_on_untrusted_time_identity_and_safety_flags() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)

        artifact, metadata = make_artifact(root / "capture")
        value = json.loads(metadata.read_text(encoding="utf-8"))
        value["artifact_captured_at_utc"] = "2026-07-21T04:50:00+00:00"
        write_json(metadata, value)
        payload, cache, _ = run_build(root / "capture", artifact, metadata)
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == [
            "market_snapshot_generated_after_artifact_capture"
        ]
        assert not cache.exists()

        artifact, metadata = make_artifact(root / "identity")
        value = json.loads(metadata.read_text(encoding="utf-8"))
        value["run_id"] = "999"
        value["artifact_name"] = "daily-operating-selection-refresh-999"
        write_json(metadata, value)
        payload, cache, _ = run_build(root / "identity", artifact, metadata)
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == ["artifact_root_run_id_mismatch"]
        assert not cache.exists()

        artifact, metadata = make_artifact(root / "unsafe")
        summary = artifact / "outputs/daily_market_snapshot/summary.json"
        value = json.loads(summary.read_text(encoding="utf-8"))
        value["live_trading_enabled"] = True
        write_json(summary, value)
        payload, cache, _ = run_build(root / "unsafe", artifact, metadata)
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == ["summary_live_trading_enabled"]
        assert not cache.exists()

        artifact, metadata = make_artifact(root / "origin")
        value = json.loads(metadata.read_text(encoding="utf-8"))
        value["head_branch"] = "untrusted-feature"
        write_json(metadata, value)
        payload, cache, _ = run_build(
            root / "origin",
            artifact,
            metadata,
        )
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == [
            "artifact_default_branch_identity_invalid"
        ]
        assert not cache.exists()

        artifact, metadata = make_artifact(root / "smuggling")
        value = json.loads(metadata.read_text(encoding="utf-8"))
        value["untrusted_override"] = True
        write_json(metadata, value)
        payload, cache, _ = run_build(
            root / "smuggling",
            artifact,
            metadata,
        )
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == [
            "artifact_metadata_schema"
        ]
        assert not cache.exists()


def test_github_compare_contract_accepts_real_shape_and_blocks_non_ancestors() -> None:
    source_sha = "b" * 40
    current_sha = "c" * 40
    validate_github_compare_payload(
        {
            "status": "ahead",
            "ahead_by": 3,
            "behind_by": 0,
            "base_commit": {"sha": source_sha},
            "merge_base_commit": {"sha": source_sha},
        },
        source_sha=source_sha,
        current_sha=current_sha,
    )
    validate_github_compare_payload(
        {
            "status": "identical",
            "ahead_by": 0,
            "behind_by": 0,
            "base_commit": {"sha": current_sha},
            "merge_base_commit": {"sha": current_sha},
        },
        source_sha=current_sha,
        current_sha=current_sha,
    )
    blocked = [
        {
            "status": "ahead",
            "ahead_by": 3,
            "behind_by": 1,
            "base_commit": {"sha": source_sha},
            "merge_base_commit": {"sha": source_sha},
        },
        {
            "status": "diverged",
            "ahead_by": 3,
            "behind_by": 1,
            "base_commit": {"sha": source_sha},
            "merge_base_commit": {"sha": "d" * 40},
        },
        {
            "status": "ahead",
            "ahead_by": True,
            "behind_by": 0,
            "base_commit": {"sha": source_sha},
            "merge_base_commit": {"sha": source_sha},
        },
    ]
    for payload in blocked:
        try:
            validate_github_compare_payload(
                payload,
                source_sha=source_sha,
                current_sha=current_sha,
            )
        except ContractError as exc:
            assert str(exc) == "artifact_source_not_current_default_ancestor"
        else:
            raise AssertionError("non-ancestor compare payload was accepted")


if __name__ == "__main__":
    test_materializes_only_exact_used_rows_with_provenance()
    test_fails_closed_on_stale_missing_duplicate_and_future_rows()
    test_fails_closed_on_untrusted_time_identity_and_safety_flags()
    test_github_compare_contract_accepts_real_shape_and_blocks_non_ancestors()
    print("run287_catchup_price_evidence_smoke: PASS")
