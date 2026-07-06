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

from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.run287_parity_cache_restore import run  # noqa: E402


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
        runner = root / "runner"
        local_books = root / "local_books"
        cache = root / "cache"
        cache.mkdir()
        candidate = root / "candidate.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-31", "ticker": "AAA"},
                {"rebalance_date": "2026-01-31", "ticker": "BBB"},
            ]
        ).to_csv(candidate, index=False)
        write_json(
            runner / "target_generation_input_manifest.json",
            {
                "price_cache": {
                    "required_ticker_count": 2,
                    "required_price_file_count": 2,
                    "existing_price_file_count": 2,
                    "missing_price_file_count": 0,
                    "manifest": {"sha256": "abc"},
                }
            },
        )
        for portfolio in ["main", "concentrated"]:
            write_book(
                runner / f"official_{portfolio}_target_book.csv",
                [{"rebalance_date": "2026-01-31", "ticker": "AAA", "target_weight": 1.0}],
            )
            write_book(
                local_books / f"official_{portfolio}_target_book.csv",
                [{"rebalance_date": "2026-01-31", "ticker": "AAA", "target_weight": 0.9}],
            )
        args = Args()
        args.runner_manifest = str(runner / "target_generation_input_manifest.json")
        args.candidate_book = str(candidate)
        args.runner_book_root = str(runner)
        args.local_price_cache = str(cache)
        args.local_book_root = str(local_books)
        args.output_dir = str(root / "out")
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["fullrun_dispatched"] is False
        assert payload["market_data_downloaded"] is False
        assert payload["runner_parity_status"] == "parity_documented_gap"
        assert payload["runner_fidelity_status"] == "not_established"
        assert payload["residual_gap_classification"] == "cache_coverage_gap"
        assert payload["cache_audit"]["cache_coverage_status"] == "cache_coverage_gap"
        assert payload["cache_audit"]["local_missing_price_file_count"] == 2
        assert (root / "out" / "missing_bars.csv").exists()
        assert (root / "out" / "book_parity.csv").exists()
        assert (root / "out" / "report.md").exists()

        for ticker in ["AAA", "BBB"]:
            (cache / px_cache_name(ticker)).write_text("not parquet but present", encoding="utf-8")
        args.output_dir = str(root / "out_complete")
        complete_payload = run(args)
        assert complete_payload["runner_parity_status"] == "parity_documented_gap"
        assert complete_payload["runner_fidelity_status"] == "residual_documented"
        assert complete_payload["residual_gap_classification"] == "book_generation_gap"
        assert complete_payload["runner_parity_reason"] == "local_cache_coverage_complete_but_book_differs"
        assert complete_payload["cache_audit"]["cache_coverage_status"] == "cache_coverage_complete"
        assert complete_payload["cache_audit"]["local_missing_price_file_count"] == 0
        report = (root / "out_complete" / "report.md").read_text(encoding="utf-8")
        assert "runner_fidelity_status" in report
        assert "book_generation_gap" in report
    print("run287_parity_cache_restore_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
