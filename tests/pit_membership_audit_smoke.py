#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_account_evaluation import pit_universe_label_clean  # noqa: E402
from tools.run_pit_membership_audit import REQUIRED_COLUMNS, audit_membership_file  # noqa: E402
from tools.run_universe_health_audit import build_payload  # noqa: E402


def write_membership(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(REQUIRED_COLUMNS)
    if any("membership_end_date" in row for row in rows):
        fieldnames.insert(4, "membership_end_date")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def clean_row(ticker: str, date: str = "2020-01-31") -> dict[str, object]:
    return {
        "rebalance_date": date,
        "ticker": ticker,
        "membership_source": "historical_membership_file",
        "membership_available_from": "2019-12-15",
        "membership_end_date": "",
        "universe_label": "historical_membership_file",
        "official_r1000_membership_proven": False,
        "proxy_universe_flag": False,
        "survivorship_status": "clean",
        "delisted_coverage_status": "clean",
        "ticker_change_coverage_status": "clean",
        "membership_pit_status": "clean",
    }


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_clean_historical_membership_passes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        membership = root / "membership.csv"
        write_membership(membership, [clean_row("AAA"), clean_row("BBB")])

        result = audit_membership_file(membership, root / "out", coverage_floor=2)
        audit = result["audit"]
        assert audit["status"] == "pass"
        assert audit["pit_universe_label_clean"] is True
        assert audit["historical_universe_pit_clean"] is True
        assert audit["production_promotion_allowed"] is True
        assert pit_universe_label_clean(audit) is True
        assert load_json(root / "out" / "pit_membership_audit.json")["status"] == "pass"


def test_future_membership_blocks_clean_label() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        row = clean_row("AAA")
        row["membership_available_from"] = "2020-02-15"
        membership = root / "membership.csv"
        write_membership(membership, [row])

        audit = audit_membership_file(membership, root / "out", coverage_floor=1)["audit"]
        assert audit["status"] == "blocked"
        assert audit["pit_universe_label_clean"] is False
        assert audit["membership_available_from_future_rows"] == 1
        assert "future_membership_available_from" in audit["blockers"]
        assert pit_universe_label_clean(audit) is False


def test_missing_membership_available_from_blocks_clean_label() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        row = clean_row("AAA")
        row["membership_available_from"] = ""
        membership = root / "membership.csv"
        write_membership(membership, [row])

        audit = audit_membership_file(membership, root / "out", coverage_floor=1)["audit"]
        assert audit["status"] == "blocked"
        assert audit["pit_universe_label_clean"] is False
        assert audit["unknown_membership_available_from_rows"] == 1
        assert "unknown_membership_available_from" in audit["blockers"]


def test_current_constituents_proxy_blocks_clean_label() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        row = clean_row("AAA")
        row["membership_source"] = "current_constituents_proxy"
        row["universe_label"] = "current_constituents_proxy"
        row["proxy_universe_flag"] = True
        membership = root / "membership.csv"
        write_membership(membership, [row])

        audit = audit_membership_file(membership, root / "out", coverage_floor=1)["audit"]
        assert audit["status"] == "blocked"
        assert audit["pit_universe_label_clean"] is False
        assert audit["current_constituents_proxy_rows"] == 1
        assert "current_constituents_proxy_rows_present" in audit["blockers"]
        assert pit_universe_label_clean(audit) is False


def test_universe_health_wires_pit_membership_audit_without_loosening_breadth_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        reports.mkdir(parents=True)
        rows = [
            {
                "ticker": f"T{i:04d}",
                "feature_date": "2020-01-31",
                "universe_source": "historical_membership_file",
            }
            for i in range(2)
        ]
        write_simple_csv(latest / "scored_latest.csv", rows)
        write_simple_csv(reports / "candidate_replay_book.csv", rows)
        membership = root / "membership.csv"
        write_membership(membership, [clean_row("T0000"), clean_row("T0001")])

        args = Namespace(
            latest_run=str(latest),
            price_cache=str(root / "cache_prices"),
            output_dir=str(root / "audit"),
            min_r1000_base=2,
            universe_mode="global_alpha_universe",
            pit_membership_file=str(membership),
            pit_membership_coverage_floor=2,
            strict=False,
        )
        payload = build_payload(args)
        assert payload["promotion_allowed"] is True
        assert payload["production_promotion_allowed"] is True
        assert payload["pit_universe_label_clean"] is True
        assert payload["pit_membership_audit"]["status"] == "pass"


def write_simple_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    test_clean_historical_membership_passes()
    test_future_membership_blocks_clean_label()
    test_missing_membership_available_from_blocks_clean_label()
    test_current_constituents_proxy_blocks_clean_label()
    test_universe_health_wires_pit_membership_audit_without_loosening_breadth_gate()
    print("pit_membership_audit_smoke: PASS")
