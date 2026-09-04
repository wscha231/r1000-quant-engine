#!/usr/bin/env python3
"""Smoke checks for trusted, replay-only Run287 catch-up price evidence."""
from __future__ import annotations

import hashlib
import json
import shutil
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
from tools.build_run287_catchup_price_capture import (  # noqa: E402
    CAPTURE_SCHEMA,
    CAPTURE_STATUS,
    PLAN_SCHEMA,
    PLAN_STATUS,
    SAFETY_ENVELOPE,
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


def file_record(path: Path, artifact: Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(artifact).as_posix(),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def convert_to_multi_session_capture(artifact: Path, metadata: Path) -> Path:
    metadata_payload = json.loads(metadata.read_text(encoding="utf-8"))
    metadata_payload["workflow_event"] = "workflow_dispatch"
    metadata_payload["workflow_conclusion"] = "success"
    metadata_payload["workflow_created_at_utc"] = "2026-07-21T21:20:00+00:00"
    metadata_payload["artifact_captured_at_utc"] = "2026-07-21T22:00:00+00:00"
    metadata_payload["workflow_updated_at_utc"] = "2026-07-21T22:10:00+00:00"
    write_json(metadata, metadata_payload)
    capture = artifact / "outputs/run287_catchup_price_capture"
    capture.mkdir(parents=True)
    plan = capture / "plan.json"
    ticker_book = capture / "ticker_union.csv"
    selection = capture / "paper_selection.json"
    source_price = capture / "source_price_cache_manifest.json"
    marker = artifact / "run287_catchup_price_capture_artifact_root.json"
    ticker_union = ["AAA", "BBB", "QQQ", "SMH", "SOXX", "SPY"]
    ticker_sources = {
        "fixture": ["AAA", "BBB"],
        "required": ["QQQ", "SMH", "SOXX", "SPY"],
    }
    ticker_book.write_text(
        "ticker\n" + "\n".join(ticker_union) + "\n",
        encoding="utf-8",
    )
    write_json(selection, {"fixture": "selection"})
    selection_raw = selection.read_bytes()
    paper = {
        "canonical_manifest": {"fixture": True},
        "immutable_heads": {
            "selection_sha256": hashlib.sha256(selection_raw).hexdigest(),
            "selection_bytes": len(selection_raw),
        },
    }
    cache_files = {
        ticker: {
            "file": px_cache_name(ticker),
            "sha256": str(index) * 64,
            "bytes": 100 + index,
        }
        for index, ticker in enumerate(ticker_union, start=1)
    }
    write_json(
        source_price,
        {
            "schema_version": "run287-replay-price-cache-manifest-v2",
            "status": "completed",
            "exact_operating_universe": True,
            "refresh_through_date": "2026-07-21",
            "refresh_through_exact_coverage": True,
            "refresh_through_ticker_count": len(ticker_union),
            "refresh_through_exact_ticker_count": len(ticker_union),
            "cache_files": cache_files,
            "review_only": True,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
        },
    )
    write_json(
        marker,
        {
            "schema_version": "run287-catchup-price-capture-artifact-root-v1",
            "capture_manifest_path": (
                "outputs/run287_catchup_price_capture/manifest.json"
            ),
            "repository": "wscha231/r1000-quant-engine",
            "source_sha": "b" * 40,
            "run_id": RUN_ID,
            "read_only": True,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
        },
    )
    records = []
    for session in (SESSION_DATE, "2026-07-21"):
        close = f"{session}T20:00:00+00:00"
        checked = f"{session}T21:31:00+00:00"
        generated = f"{session}T21:32:00+00:00"
        base = capture / "sessions" / session / "outputs"
        gate = base / "daily_market_session_gate/session.json"
        summary = base / "daily_market_snapshot/summary.json"
        snapshot = base / "daily_market_snapshot/market_snapshot.csv"
        report = base / "daily_market_snapshot/report.md"
        gate.parent.mkdir(parents=True, exist_ok=True)
        summary.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            gate,
            {
                "schema_version": "daily-market-session-gate-v1",
                "status": "READY_FORCED_CATCHUP_SESSION",
                "ready": True,
                "calendar": "NYSE",
                "session_date": session,
                "market_close_utc": close,
                "checked_at_utc": checked,
            },
        )
        write_json(
            summary,
            {
                "schema_version": "daily-market-snapshot-v1",
                "status": "completed",
                "asof_date": session,
                "ticker_count": len(ticker_union),
                "latest_price_date_min": session,
                "latest_price_date_max": session,
                "exact_asof_close_required": True,
                "exact_asof_close_count": len(ticker_union),
                "exact_asof_close_missing_count": 0,
                "exact_asof_close_missing_tickers": [],
                "generated_at_utc": generated,
                "review_only": True,
                "production_mutation_allowed": False,
                "live_trading_enabled": False,
            },
        )
        pd.DataFrame(
            [source_row(ticker, latest_price_date=session) for ticker in ticker_union]
        ).to_csv(snapshot, index=False)
        report.write_text("# capture fixture\n", encoding="utf-8")
        records.append(
            {
                "session_date": session,
                "official_market_close_utc": close,
                "ticker_count": len(ticker_union),
                "files": {
                    "market_session_gate": file_record(gate, artifact),
                    "market_snapshot_csv": file_record(snapshot, artifact),
                    "market_snapshot_summary": file_record(summary, artifact),
                    "market_snapshot_report": file_record(report, artifact),
                },
            }
        )
    ticker_book_raw = ticker_book.read_bytes()
    plan_payload = {
        "schema_version": PLAN_SCHEMA,
        "status": PLAN_STATUS,
        "generated_at_utc": "2026-07-21T21:31:00+00:00",
        "canonical_as_of_date": "2026-07-17",
        "through_session_date": "2026-07-21",
        "pending_sessions": [SESSION_DATE, "2026-07-21"],
        "pending_session_count": 2,
        "ticker_union": ticker_union,
        "ticker_union_count": len(ticker_union),
        "ticker_sources": ticker_sources,
        "ticker_book": {
            "path": "ticker_union.csv",
            "bytes": len(ticker_book_raw),
            "sha256": hashlib.sha256(ticker_book_raw).hexdigest(),
        },
        "paper": paper,
        **SAFETY_ENVELOPE,
    }
    write_json(plan, plan_payload)
    manifest = {
        "schema_version": CAPTURE_SCHEMA,
        "status": CAPTURE_STATUS,
        "generated_at_utc": "2026-07-21T21:33:00+00:00",
        "source": {
            "repository": "wscha231/r1000-quant-engine",
            "source_sha": "b" * 40,
            "run_id": RUN_ID,
            "run_attempt": "1",
            "event_name": "workflow_dispatch",
            "job_key": "capture_catchup_evidence",
        },
        "canonical_as_of_date": "2026-07-17",
        "through_session_date": "2026-07-21",
        "pending_session_count": 2,
        "ticker_union": ticker_union,
        "ticker_union_count": len(ticker_union),
        "ticker_sources": ticker_sources,
        "paper": paper,
        "capture_plan": file_record(plan, artifact),
        "ticker_book": file_record(ticker_book, artifact),
        "source_price_cache_manifest": file_record(source_price, artifact),
        "source_price_cache_files": cache_files,
        "artifact_root_marker": file_record(marker, artifact),
        "sessions": records,
        **SAFETY_ENVELOPE,
    }
    write_json(capture / "manifest.json", manifest)
    shutil.rmtree(artifact / "outputs/daily_market_session_gate")
    shutil.rmtree(artifact / "outputs/daily_market_snapshot")
    return capture


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


def test_multi_session_capture_selects_exact_session_and_binds_whole_tree() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact, metadata = make_artifact(root)
        capture = convert_to_multi_session_capture(artifact, metadata)
        payload, cache, _ = run_build(root, artifact, metadata)
        assert payload["status"] == READY_STATUS
        assert payload["source_layout"] == "MULTI_SESSION_READ_ONLY_CAPTURE"
        manifest = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["source_layout"] == "MULTI_SESSION_READ_ONLY_CAPTURE"
        assert any(
            row["label"] == "catchup_price_capture_manifest"
            for row in manifest["source_files"]
        )

        other_summary = (
            capture
            / "sessions/2026-07-21/outputs/daily_market_snapshot/summary.json"
        )
        other_summary.write_bytes(other_summary.read_bytes() + b" ")
        blocked, blocked_cache, _ = run_build(
            root, artifact, metadata, suffix="_tampered_capture"
        )
        assert blocked["status"] == BLOCKED_STATUS
        assert blocked["contract_failures"] == [
            "capture_session_market_snapshot_summary_hash"
        ]
        assert not blocked_cache.exists()

        gap_root = root / "gap"
        gap_artifact, gap_metadata = make_artifact(gap_root)
        gap_capture = convert_to_multi_session_capture(
            gap_artifact, gap_metadata
        )
        gap_plan_path = gap_capture / "plan.json"
        gap_plan = json.loads(gap_plan_path.read_text(encoding="utf-8"))
        gap_plan["pending_sessions"] = ["2026-07-21"]
        write_json(gap_plan_path, gap_plan)
        gap_manifest_path = gap_capture / "manifest.json"
        gap_manifest = json.loads(
            gap_manifest_path.read_text(encoding="utf-8")
        )
        gap_manifest["capture_plan"] = file_record(
            gap_plan_path, gap_artifact
        )
        write_json(gap_manifest_path, gap_manifest)
        gap_payload, gap_cache, _ = run_build(
            gap_root,
            gap_artifact,
            gap_metadata,
            suffix="_gap",
        )
        assert gap_payload["status"] == BLOCKED_STATUS
        assert gap_payload["contract_failures"] == [
            "capture_plan_session_sequence"
        ]
        assert not gap_cache.exists()


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
    test_multi_session_capture_selects_exact_session_and_binds_whole_tree()
    test_fails_closed_on_stale_missing_duplicate_and_future_rows()
    test_fails_closed_on_untrusted_time_identity_and_safety_flags()
    test_github_compare_contract_accepts_real_shape_and_blocks_non_ancestors()
    print("run287_catchup_price_evidence_smoke: PASS")
