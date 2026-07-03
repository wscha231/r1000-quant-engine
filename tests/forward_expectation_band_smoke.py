#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_forward_expectation_band import run  # noqa: E402


class Args:
    pass


def test_forward_expectation_band_never_outputs_point_cagr() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger = root / "ledger.csv"
        fields = [
            "row_id",
            "schema_version",
            "event_type",
            "as_of_date",
            "portfolio_kind",
            "nav_usd",
            "period_return",
            "starting_nav_usd",
            "snapshot_hash",
            "public_snapshot_hash",
            "target_snapshot_hash",
            "broker_state_hash",
            "source_metric_mode",
            "research_only",
            "review_only",
            "correction_of_row_id",
            "correction_reason",
            "previous_row_hash",
            "created_at_utc",
            "row_hash",
        ]
        with ledger.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"event_type": "seed", "as_of_date": "2026-06-29", "portfolio_kind": "main", "nav_usd": "1000", "period_return": "0"})
            writer.writerow({"event_type": "valuation", "as_of_date": "2026-07-31", "portfolio_kind": "main", "nav_usd": "1100", "period_return": "0.1"})
            writer.writerow({"event_type": "seed", "as_of_date": "2026-06-29", "portfolio_kind": "concentrated", "nav_usd": "1000", "period_return": "0"})
            writer.writerow({"event_type": "valuation", "as_of_date": "2026-07-31", "portfolio_kind": "concentrated", "nav_usd": "900", "period_return": "-0.1"})
        args = Args()
        args.ledger = str(ledger)
        args.output_dir = str(root / "out")
        args.min_elapsed_days = 30
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["display_policy"] == "percentile_bands_only"
        assert payload["point_cagr_display_allowed"] is False
        assert payload["public_display_allowed"] is False
        assert "p50_return" in payload["bands"]
        forbidden_band_keys = {"point_cagr", "cagr_point", "expected_cagr"}
        assert not (forbidden_band_keys & set(payload["bands"]))
        assert "point_cagr" not in (root / "out" / "expectation_bands.csv").read_text(encoding="utf-8").lower()


def test_forward_expectation_band_blocks_seed_only_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger = root / "ledger.csv"
        fields = [
            "event_type",
            "as_of_date",
            "portfolio_kind",
            "nav_usd",
            "period_return",
        ]
        with ledger.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"event_type": "seed", "as_of_date": "2026-06-29", "portfolio_kind": "main", "nav_usd": "1000", "period_return": "0"})
            writer.writerow({"event_type": "seed", "as_of_date": "2026-06-29", "portfolio_kind": "concentrated", "nav_usd": "1000", "period_return": "0"})
        args = Args()
        args.ledger = str(ledger)
        args.output_dir = str(root / "out")
        args.min_elapsed_days = 30
        payload = run(args)
        assert payload["status"] == "insufficient_forward_history"
        assert payload["bands"] == {}
        assert payload["public_display_allowed"] is False
        csv_rows = list(csv.DictReader((root / "out" / "expectation_bands.csv").open(encoding="utf-8", newline="")))
        assert csv_rows == []


def main() -> int:
    test_forward_expectation_band_never_outputs_point_cagr()
    test_forward_expectation_band_blocks_seed_only_history()
    print("forward_expectation_band_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
