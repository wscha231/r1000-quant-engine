#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_earnings_estimate_archive_manifest import build_manifest  # noqa: E402


def test_manifest_records_hashes_and_append_only_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        snapshot_dir = root / "data_pit" / "events" / "earnings_estimates"
        snapshot_dir.mkdir(parents=True)
        snapshot = snapshot_dir / "estimates_20260709.parquet"
        signals = root / "data_pit" / "events" / "earnings_revision_signals.parquet"
        out_dir = root / "outputs" / "earnings_estimates_daily"
        out_dir.mkdir(parents=True)
        summary = out_dir / "summary.json"
        collector_log = out_dir / "collector.log"
        manifest = out_dir / "archive_manifest.json"
        index = snapshot_dir / "archive_index.jsonl"
        queue_summary = out_dir / "incremental_universe_summary.json"
        queue_checkpoint = snapshot_dir / "collection_checkpoint.json"
        queue_csv = out_dir / "collection_queue.csv"
        queue_report = out_dir / "collection_queue_report.md"
        snapshot.write_bytes(b"snapshot-bytes")
        signals.write_bytes(b"signals-bytes")
        summary.write_text(
            json.dumps(
                {
                    "status": "blocked_partial_coverage",
                    "reason": "coverage_below_80pct_warn_only",
                    "ticker_count_requested": 50,
                    "request_snapshot_rows": 36,
                    "request_has_forward_estimate_rows": 2,
                    "snapshot_rows": 36,
                    "has_forward_estimate_rows": 2,
                    "estimate_coverage_ratio": 0.04,
                    "stored_estimate_coverage_ratio": 0.04,
                    "same_day_snapshot_merged": False,
                    "coverage_ratio": 0.72,
                    "fetch_sources": ["fmp", "finnhub"],
                    "vendor_order": ["fmp", "finnhub"],
                    "max_errors": 5000,
                    "entitlement_circuit_threshold": 3,
                    "vendor_entitlement_circuit": {
                        "run_scoped": True,
                        "persistent_vendor_block_written": False,
                        "tripped_vendors": ["fmp", "finnhub"],
                        "estimated_estimate_http_requests_avoided": 441,
                    },
                    "vendor_estimate_access": True,
                    "vendor_blocked_errors": True,
                    "error_count": 102,
                    "error_budget_count": 6,
                    "entitlement_error_warn_only_count": 96,
                    "entitlement_error_probe_count": 0,
                    "snapshot_path": str(snapshot),
                    "backtest_acceptance_allowed": False,
                    "production_activation_allowed": False,
                    "live_trading_enabled": False,
                }
            ),
            encoding="utf-8",
        )
        collector_log.write_text("masked url apikey=*** token=***\n", encoding="utf-8")
        queue_summary.write_text(
            json.dumps(
                {
                    "schema_version": "forward-estimate-collection-queue-v2",
                    "status": "ready_for_forward_archive_incremental",
                    "output_ticker_count": 3,
                    "current_universe_ticker_count": 993,
                    "eligible_universe_ticker_count": 992,
                    "non_equity_placeholder_ticker_count": 1,
                    "universe_source_mode": "coverage_file_seed",
                    "canonical_universe": {"sha256": "canonical-sha"},
                    "snapshot_source_aggregate_sha256": "snapshot-source-sha",
                    "queue_state_counts": {"fresh_success_reused": 13, "missing": 130},
                    "selection_reason_counts": {"missing_snapshot": 3},
                }
            ),
            encoding="utf-8",
        )
        queue_checkpoint.write_text("{}\n", encoding="utf-8")
        queue_csv.write_text("ticker,queue_state\nAAA,missing\n", encoding="utf-8")
        queue_report.write_text("# Queue\n", encoding="utf-8")

        payload = build_manifest(
            snapshot_dir=str(snapshot_dir),
            signals=str(signals),
            summary=str(summary),
            collector_log=str(collector_log),
            manifest=str(manifest),
            index=str(index),
            run_id="29015925250",
            run_attempt="1",
            head_sha="abc123",
            ref="master",
            workflow="Earnings Estimates Daily Archive",
            artifact_name="earnings-estimates-daily-29015925250",
            shard_id="shard_000",
            shard_file="outputs/forward_estimate_universe_plan_20260709/shards/shard_000.csv",
            shard_mode="rotating_shard",
            queue_summary=str(queue_summary),
            queue_checkpoint=str(queue_checkpoint),
            queue_csv=str(queue_csv),
            queue_report=str(queue_report),
        )

        assert payload["verdict"] == "archive_manifest_written"
        assert payload["collector_status"] == "blocked_partial_coverage"
        assert payload["estimate_coverage_ratio"] == 0.04
        assert payload["request_snapshot_rows"] == 36
        assert payload["request_has_forward_estimate_rows"] == 2
        assert payload["same_day_snapshot_merged"] is False
        assert payload["backtest_acceptance_allowed"] is False
        assert payload["production_activation_allowed"] is False
        assert payload["live_trading_enabled"] is False
        assert payload["files"]["snapshot"]["sha256"]
        assert payload["files"]["signals"]["sha256"]
        assert payload["shard_id"] == "shard_000"
        assert payload["shard_file"].endswith("shard_000.csv")
        assert payload["shard_mode"] == "rotating_shard"
        assert payload["collector_max_errors"] == 5000
        assert payload["entitlement_circuit_threshold"] == 3
        assert payload["vendor_entitlement_circuit"]["tripped_vendors"] == ["fmp", "finnhub"]
        assert payload["error_count"] == 102
        assert payload["error_budget_count"] == 6
        assert payload["collection_queue_status"] == "ready_for_forward_archive_incremental"
        assert payload["collection_universe_ticker_count"] == 993
        assert payload["collection_eligible_ticker_count"] == 992
        assert payload["collection_non_equity_placeholder_ticker_count"] == 1
        assert payload["files"]["collection_queue_checkpoint"]["sha256"]
        assert payload["text_secret_scan"]["unmasked_secret_pattern_found"] is False
        assert payload["text_secret_scan"]["scans"][1]["masked_url_credential_markers_present"] is True
        persisted = json.loads(manifest.read_text(encoding="utf-8"))
        assert persisted["artifact_name"] == "earnings-estimates-daily-29015925250"
        rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        assert rows[0]["run_id"] == "29015925250"
        assert rows[0]["shard_id"] == "shard_000"
        assert rows[0]["shard_mode"] == "rotating_shard"
        assert rows[0]["collector_max_errors"] == 5000
        assert rows[0]["entitlement_circuit_tripped_vendors"] == ["fmp", "finnhub"]
        assert rows[0]["estimated_estimate_http_requests_avoided"] == 441
        assert rows[0]["error_budget_count"] == 6
        assert rows[0]["entitlement_error_warn_only_count"] == 96
        assert rows[0]["request_snapshot_rows"] == 36
        assert rows[0]["same_day_snapshot_merged"] is False
        assert rows[0]["collection_universe_ticker_count"] == 993
        assert rows[0]["collection_queue_checkpoint_sha256"]
        assert rows[0]["snapshot_sha256"] == payload["files"]["snapshot"]["sha256"]

        payload2 = build_manifest(
            snapshot_dir=str(snapshot_dir),
            signals=str(signals),
            summary=str(summary),
            collector_log=str(collector_log),
            manifest=str(manifest),
            index=str(index),
            run_id="29015925250",
            run_attempt="1",
            head_sha="abc123",
            ref="master",
            workflow="Earnings Estimates Daily Archive",
            artifact_name="earnings-estimates-daily-29015925250",
            shard_id="shard_000",
            shard_file="outputs/forward_estimate_universe_plan_20260709/shards/shard_000.csv",
            shard_mode="rotating_shard",
            queue_summary=str(queue_summary),
            queue_checkpoint=str(queue_checkpoint),
            queue_csv=str(queue_csv),
            queue_report=str(queue_report),
        )
        assert payload2["verdict"] == "archive_manifest_written"
        rows2 = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
        assert len(rows2) == 1


if __name__ == "__main__":
    test_manifest_records_hashes_and_append_only_index()
    print("earnings_estimate_archive_manifest_smoke: PASS")
