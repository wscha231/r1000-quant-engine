#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_target_book_control_repro_audit import run  # noqa: E402


class Args:
    pass


def _args(root: Path, official: Path, generated: Path) -> Args:
    args = Args()
    args.official_book = str(official)
    args.generated_book = str(generated)
    args.output_dir = str(root / "audit")
    args.portfolio_kind = "concentrated"
    args.candidate_book = "candidate.csv"
    args.price_cache = "cache_prices"
    args.code_commit = "test"
    args.env_keys = "PHASE_TEST"
    args.weight_tolerance = 1e-9
    args.near_weight_tolerance = 1e-4
    args.max_ticker_mismatch_dates = 0
    return args


def test_exact_match_passes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = pd.DataFrame(
            [
                {"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 0.40},
                {"rebalance_date": "2026-01-31", "ticker": "CASH", "weight": 0.60},
            ]
        )
        official = root / "official.csv"
        generated = root / "generated.csv"
        book.to_csv(official, index=False)
        book.to_csv(generated, index=False)
        payload = run(_args(root, official, generated))
        assert payload["status"] == "completed"
        assert payload["exact_control_reproduced"] is True
        assert payload["near_control_reproduced"] is True


def test_ticker_and_weight_mismatch_are_reported() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        official = root / "official.csv"
        generated = root / "generated.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 0.40},
                {"rebalance_date": "2026-01-31", "ticker": "CASH", "weight": 0.60},
            ]
        ).to_csv(official, index=False)
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-31", "ticker": "BBB", "weight": 0.41},
                {"rebalance_date": "2026-01-31", "ticker": "CASH", "weight": 0.59},
                {"rebalance_date": "2026-02-28", "ticker": "BBB", "weight": 1.00},
            ]
        ).to_csv(generated, index=False)
        payload = run(_args(root, official, generated))
        assert payload["exact_control_reproduced"] is False
        assert payload["near_control_reproduced"] is False
        assert payload["generated_only_date_count"] == 1
        assert payload["ticker_mismatch_date_count"] >= 1
        assert payload["max_abs_weight_delta"] > 0
        assert (root / "audit" / "date_ticker_diff.csv").exists()
        assert (root / "audit" / "weight_delta.csv").exists()


def main() -> int:
    test_exact_match_passes()
    test_ticker_and_weight_mismatch_are_reported()
    print("target_book_control_repro_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
