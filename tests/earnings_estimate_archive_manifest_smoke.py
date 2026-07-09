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
        snapshot.write_bytes(b"snapshot-bytes")
        signals.write_bytes(b"signals-bytes")
        summary.write_text(
            json.dumps(
                {
                    "status": "blocked_partial_coverage",
                    "reason": "coverage_below_80pct_warn_only",
                    "ticker_count_requested": 50,
                    "snapshot_rows": 36,
                    "has_forward_estimate_rows": 2,
                    "estimate_coverage_ratio": 0.04,
                    "coverage_ratio": 0.72,
                    "fetch_sources": ["fmp", "finnhub"],
                    "vendor_order": ["fmp", "finnhub"],
                    "vendor_estimate_access": True,
                    "vendor_blocked_errors": True,
                    "error_count": 102,
                    "snapshot_path": str(snapshot),
                    "backtest_acceptance_allowed": False,
                    "production_activation_allowed": False,
                    "live_trading_enabled": False,
                }
            ),
            encoding="utf-8",
        )
        collector_log.write_text("masked url apikey=*** token=***\n", encoding="utf-8")

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
        )

        assert payload["verdict"] == "archive_manifest_written"
        assert payload["collector_status"] == "blocked_partial_coverage"
        assert payload["estimate_coverage_ratio"] == 0.04
        assert payload["backtest_acceptance_allowed"] is False
        assert payload["production_activation_allowed"] is False
        assert payload["live_trading_enabled"] is False
        assert payload["files"]["snapshot"]["sha256"]
        assert payload["files"]["signals"]["sha256"]
        assert payload["shard_id"] == "shard_000"
        assert payload["shard_file"].endswith("shard_000.csv")
        assert payload["shard_mode"] == "rotating_shard"
        assert payload["text_secret_scan"]["unmasked_secret_pattern_found"] is False
        assert payload["text_secret_scan"]["scans"][1]["masked_url_credential_markers_present"] is True
        persisted = json.loads(manifest.read_text(encoding="utf-8"))
        assert persisted["artifact_name"] == "earnings-estimates-daily-29015925250"
        rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        assert rows[0]["run_id"] == "29015925250"
        assert rows[0]["shard_id"] == "shard_000"
        assert rows[0]["shard_mode"] == "rotating_shard"
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
        )
        assert payload2["verdict"] == "archive_manifest_written"
        rows2 = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
        assert len(rows2) == 1


if __name__ == "__main__":
    test_manifest_records_hashes_and_append_only_index()
    print("earnings_estimate_archive_manifest_smoke: PASS")
