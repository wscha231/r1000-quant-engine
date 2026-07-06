#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run287_same_artifact_repro_preflight import run  # noqa: E402


class Args:
    pass


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        official = root / "official"
        local_cache = root / "local_cache"
        out = root / "out"
        manifest = root / "target_generation_input_manifest.json"

        candidate = official / "outputs" / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("ticker,rebalance_date\nAAA,2026-01-31\n", encoding="utf-8")
        candidate_sha = "0" * 64
        from tools.run287_same_artifact_repro_preflight import sha256_file  # noqa: E402

        candidate_sha = sha256_file(candidate)

        price_manifest = official / "cache_prices" / "replay_price_cache_manifest.json"
        write_json(price_manifest, {"requested_end": "2026-07-03"})
        local_price_manifest = local_cache / "replay_price_cache_manifest.json"
        write_json(local_price_manifest, {"requested_end": "2026-07-03", "local": True})
        for ticker in ["AAA", "BBB"]:
            (local_cache / f"{ticker}.csv").write_text("Date,Close\n2026-01-01,1\n", encoding="utf-8")

        packaged_features = official / "outputs" / "crisis_signals" / "daily_features.parquet"
        packaged_features.parent.mkdir(parents=True, exist_ok=True)
        packaged_features.write_bytes(b"post-vnext")
        thresholds = official / "outputs" / "long_crisis_learning" / "best_thresholds.json"
        write_json(thresholds, {"threshold": 1})

        write_json(
            manifest,
            {
                "candidate_book": {"sha256": candidate_sha, "bytes": candidate.stat().st_size},
                "price_cache": {
                    "required_price_file_count": 2,
                    "manifest": {
                        "sha256": sha256_file(price_manifest),
                        "bytes": price_manifest.stat().st_size,
                    },
                },
                "macro_crisis_inputs": {
                    "long_crisis_features": {
                        "sha256": "f" * 64,
                        "bytes": 99,
                    },
                    "long_crisis_thresholds": {
                        "sha256": sha256_file(thresholds),
                        "bytes": thresholds.stat().st_size,
                    },
                },
                "code": {"github_sha": "missingcommit", "github_ref": "refs/heads/test"},
            },
        )

        args = Args()
        args.runner_manifest = str(manifest)
        args.official_artifact_root = str(official)
        args.local_full_candidate_cache = str(local_cache)
        args.output_dir = str(out)
        payload = run(args)

        assert payload["research_only"] is True
        assert payload["fullrun_dispatched"] is False
        assert payload["market_data_downloaded"] is False
        assert payload["target_book_regenerated"] is False
        assert payload["threshold_tuning_performed"] is False
        assert payload["new_alpha_hook_added"] is False
        assert payload["production_promotion_allowed"] is False
        assert payload["exact_reproduction_ready"] is False
        assert payload["approximate_reproduction_available"] is True
        assert payload["runner_fidelity_status"] == "same_artifact_repro_blocked"
        assert "runner_price_file_artifacts_missing" in payload["blockers"]
        assert "runner_long_crisis_features_missing_or_mismatch" in payload["blockers"]
        assert "runner_code_commit_unavailable" in payload["blockers"]
        assert (out / "summary.json").exists()
        assert (out / "input_availability.csv").exists()
        assert (out / "report.md").exists()
        report = (out / "report.md").read_text(encoding="utf-8")
        assert "same_artifact_repro_blocked" in report
    print("run287_same_artifact_repro_preflight_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
