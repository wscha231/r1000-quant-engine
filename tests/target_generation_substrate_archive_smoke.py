#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.archive_target_generation_substrate import run, sha256_file  # noqa: E402


class Args:
    pass


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        cache = root / "cache_prices"
        out = root / "archive"
        candidate = latest / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("rebalance_date,ticker\n2026-01-31,AAA\n", encoding="utf-8")
        features = root / "data_pit" / "macro" / "long_crisis_daily_features.parquet"
        features.parent.mkdir(parents=True, exist_ok=True)
        features.write_bytes(b"features")
        thresholds = latest / "long_crisis_learning" / "best_thresholds.json"
        write_json(thresholds, {"threshold": 0.4})
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "aaa.parquet").write_bytes(b"price-a")
        (cache / "bbb.parquet").write_bytes(b"price-b")
        write_json(cache / "replay_price_cache_manifest.json", {"ticker_count": 2})
        write_json(
            latest / "alphaops_vnext" / "target_generation_input_manifest.json",
            {
                "candidate_book": {"sha256": sha256_file(candidate)},
                "price_cache": {"required_price_file_count": 2},
                "macro_crisis_inputs": {
                    "long_crisis_features": {"sha256": sha256_file(features)},
                    "long_crisis_thresholds": {"sha256": sha256_file(thresholds)},
                },
            },
        )

        args = Args()
        args.latest_run = str(latest)
        args.price_cache = str(cache)
        args.output_dir = str(out)
        args.long_crisis_features = str(features)
        args.long_crisis_thresholds = str(thresholds)
        payload = run(args)

        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["fullrun_dispatched"] is False
        assert payload["market_data_downloaded"] is False
        assert payload["target_book_regenerated"] is False
        assert payload["threshold_tuning_performed"] is False
        assert payload["production_promotion_allowed"] is False
        assert payload["candidate_book_sha_matches_manifest"] is True
        assert payload["long_crisis_features_sha_matches_manifest"] is True
        assert payload["long_crisis_thresholds_sha_matches_manifest"] is True
        assert payload["price_cache"]["price_file_count"] == 2
        assert (out / "cache_prices" / "aaa.parquet").exists()
        assert (out / "cache_prices" / "bbb.parquet").exists()
        assert (out / "data_pit" / "macro" / "long_crisis_daily_features.parquet").exists()
        assert (out / "summary.json").exists()
        assert (out / "report.md").exists()
    print("target_generation_substrate_archive_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
