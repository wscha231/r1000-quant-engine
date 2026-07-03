#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.update_forward_service_ledger import run  # noqa: E402


class Args:
    pass


def _args(root: Path, seed: Path, nav: Path | None = None, correction_reason: str = "") -> Args:
    args = Args()
    args.seed_csv = str(seed)
    args.nav_csv = str(nav or "")
    args.ledger = str(root / "forward_paper_ledger.csv")
    args.summary = str(root / "summary.json")
    args.correction_reason = correction_reason
    return args


def _write_seed(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "freeze_date",
                "portfolio_kind",
                "starting_nav_usd",
                "snapshot_hash",
                "public_snapshot_hash",
                "target_snapshot_hash",
                "broker_state_hash",
                "source_metric_mode",
                "research_only",
                "review_only",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "freeze_date": "2026-06-29",
                "portfolio_kind": "main",
                "starting_nav_usd": "1000",
                "snapshot_hash": "snap",
                "public_snapshot_hash": "snap",
                "target_snapshot_hash": "target",
                "broker_state_hash": "broker",
                "source_metric_mode": "broker_ledger_next_close",
                "research_only": "True",
                "review_only": "True",
            }
        )


def _write_nav(path: Path, nav: str, correction_of: str = "") -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["as_of_date", "portfolio_kind", "nav_usd", "correction_of_row_id"])
        writer.writeheader()
        writer.writerow(
            {
                "as_of_date": "2026-07-31",
                "portfolio_kind": "main",
                "nav_usd": nav,
                "correction_of_row_id": correction_of,
            }
        )


def test_forward_ledger_is_append_only_and_hash_chained() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed = root / "seed.csv"
        nav = root / "nav.csv"
        _write_seed(seed)
        payload = run(_args(root, seed))
        assert payload["status"] == "completed"
        assert payload["appended_rows"] == 1

        _write_nav(nav, "1100")
        payload = run(_args(root, seed, nav))
        assert payload["status"] == "completed"
        assert payload["appended_rows"] == 1
        rows = list(csv.DictReader((root / "forward_paper_ledger.csv").open(encoding="utf-8", newline="")))
        assert len(rows) == 2
        assert rows[1]["previous_row_hash"] == rows[0]["row_hash"]
        assert rows[1]["snapshot_hash"] == "snap"
        assert rows[1]["period_return"] == "0.1000000000"

        duplicate = run(_args(root, seed, nav))
        assert duplicate["status"] == "blocked"
        assert duplicate["reason"] == "duplicate_event_requires_correction_record"

        _write_nav(nav, "1090", correction_of=rows[1]["row_id"])
        corrected = run(_args(root, seed, nav, correction_reason="vendor_price_correction"))
        assert corrected["status"] == "completed"
        rows = list(csv.DictReader((root / "forward_paper_ledger.csv").open(encoding="utf-8", newline="")))
        assert rows[-1]["event_type"] == "correction"
        assert rows[-1]["correction_of_row_id"] == rows[1]["row_id"]


def main() -> int:
    test_forward_ledger_is_append_only_and_hash_chained()
    print("forward_service_ledger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
