#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run287_book_fidelity_residual_audit import run  # noqa: E402


class Args:
    pass


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_book(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runner_root = root / "runner"
        local_root = root / "local"
        out = root / "out"
        runner_manifest = runner_root / "target_generation_input_manifest.json"
        local_manifest = local_root / "target_generation_input_manifest.json"
        parity = root / "parity.json"

        env = {
            "PHASE_MAIN_POST_SELECTION_TOPN_FILTER_ENABLED": "1",
            "R1000_MAIN_POST_SELECTION_TOP_N": "14",
        }
        write_json(
            runner_manifest,
            {
                "schema_version": "alphaops-vnext-target-generation-input-manifest-v1",
                "code": {"github_ref": "refs/heads/x", "github_sha": "runner-sha"},
                "candidate_book": {"sha256": "candidate"},
                "candidate_row_count": 10,
                "price_cache": {
                    "required_ticker_count": 2,
                    "existing_price_file_count": 2,
                    "missing_price_file_count": 0,
                    "manifest": {"sha256": "runner-cache"},
                },
                "macro_crisis_inputs": {
                    "long_crisis_features": {"sha256": "features"},
                    "long_crisis_thresholds": {"sha256": "thresholds"},
                },
                "operating_append_end_date": "",
                "env": env,
            },
        )
        write_json(
            local_manifest,
            {
                "schema_version": "alphaops-vnext-target-generation-input-manifest-v1",
                "code": {"github_ref": "", "github_sha": ""},
                "candidate_book": {"sha256": "candidate"},
                "candidate_row_count": 10,
                "price_cache": {
                    "required_ticker_count": 2,
                    "existing_price_file_count": 2,
                    "missing_price_file_count": 0,
                    "manifest": {"sha256": "local-cache"},
                },
                "macro_crisis_inputs": {
                    "long_crisis_features": {"sha256": "features"},
                    "long_crisis_thresholds": {"sha256": "thresholds"},
                },
                "operating_append_end_date": "2026-01-31",
                "env": env,
            },
        )
        write_json(
            parity,
            {
                "runner_parity_status": "parity_documented_gap",
                "cache_audit": {
                    "cache_coverage_complete": True,
                    "cache_coverage_status": "cache_coverage_complete",
                    "cache_manifest_sha_matches_runner": False,
                },
            },
        )
        for portfolio in ["main", "concentrated"]:
            write_book(
                runner_root / f"official_{portfolio}_target_book.csv",
                [
                    {"rebalance_date": "2026-01-31", "ticker": "AAA", "target_weight": 0.40},
                    {"rebalance_date": "2026-01-31", "ticker": "CASH", "target_weight": 0.60},
                ],
            )
            write_book(
                local_root / f"official_{portfolio}_target_book.csv",
                [
                    {"rebalance_date": "2026-01-31", "ticker": "BBB", "target_weight": 0.41},
                    {"rebalance_date": "2026-01-31", "ticker": "CASH", "target_weight": 0.59},
                ],
            )
        args = Args()
        args.runner_book_root = str(runner_root)
        args.local_book_root = str(local_root)
        args.runner_manifest = str(runner_manifest)
        args.local_manifest = str(local_manifest)
        args.parity_summary = str(parity)
        args.output_dir = str(out)
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["fullrun_dispatched"] is False
        assert payload["market_data_downloaded"] is False
        assert payload["runner_parity_status"] == "parity_documented_gap"
        assert payload["runner_fidelity_status"] == "residual_documented"
        assert payload["residual_gap_classification"] == "book_generation_gap"
        assert "price_cache_manifest_sha_mismatch" in payload["residual_source_candidates"]
        assert "code_provenance_missing_or_mismatch" in payload["residual_source_candidates"]
        assert "operating_append_end_date_mismatch" in payload["residual_source_candidates"]
        assert "book_generation_gap" in payload["residual_source_candidates"]
        assert payload["env_mismatch_count"] == 0
        assert payload["book_audit"]["book_parity_exact"] is False
        assert (out / "summary.json").exists()
        assert (out / "manifest_diff.csv").exists()
        assert (out / "book_gap_by_date.csv").exists()
        assert (out / "ticker_gap.csv").exists()
        assert "book_generation_gap" in (out / "report.md").read_text(encoding="utf-8")
    print("run287_book_fidelity_residual_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
