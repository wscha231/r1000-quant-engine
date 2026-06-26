#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
TOOL = REPO_ROOT / "tools" / "build_pit_membership_by_month.py"


def run_tool(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, str(TOOL), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_clean_date_range_membership_expands_and_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "membership.csv"
        out = root / "out"
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "date_from": "2020-01-01",
                    "date_to": "2020-03-31",
                    "membership_available_from": "2019-12-15",
                },
                {
                    "ticker": "BBB",
                    "date_from": "2020-01-01",
                    "date_to": "2020-03-31",
                    "membership_available_from": "2019-12-15",
                },
            ]
        ).to_csv(src, index=False)
        result = run_tool(
            [
                "--membership-file",
                str(src),
                "--output-dir",
                str(out),
                "--start-date",
                "2020-01-01",
                "--end-date",
                "2020-03-31",
                "--coverage-floor",
                "2",
                "--source-provenance-status",
                "reviewed",
            ]
        )
        assert result.returncode == 0, result.stderr
        rows = pd.read_csv(out / "pit_membership_by_month.csv")
        assert rows["rebalance_date"].nunique() == 3
        assert len(rows) == 6
        audit = read_json(out / "pit_membership_audit.json")
        manifest = read_json(out / "pit_membership_producer_manifest.json")
        assert audit["pit_universe_label_clean"] is True
        assert audit["coverage_pass"] is True
        assert manifest["production_mutation_allowed"] is False


def test_clean_source_without_provenance_stays_blocked() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "membership.csv"
        out = root / "out"
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "date_from": "2020-01-01",
                    "date_to": "2020-03-31",
                    "membership_available_from": "2019-12-15",
                }
            ]
        ).to_csv(src, index=False)
        result = run_tool(
            [
                "--membership-file",
                str(src),
                "--output-dir",
                str(out),
                "--start-date",
                "2020-01-01",
                "--end-date",
                "2020-03-31",
                "--coverage-floor",
                "1",
            ]
        )
        assert result.returncode == 0, result.stderr
        audit = read_json(out / "pit_membership_audit.json")
        assert audit["pit_universe_label_clean"] is False
        assert "source_provenance_review_required" in audit["blockers"]


def test_missing_available_from_stays_blocked() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "membership.csv"
        out = root / "out"
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "rebalance_date": "2020-01-31",
                }
            ]
        ).to_csv(src, index=False)
        result = run_tool(
            [
                "--membership-file",
                str(src),
                "--output-dir",
                str(out),
                "--start-date",
                "2020-01-01",
                "--end-date",
                "2020-03-31",
                "--coverage-floor",
                "1",
            ]
        )
        assert result.returncode == 0, result.stderr
        audit = read_json(out / "pit_membership_audit.json")
        assert audit["pit_universe_label_clean"] is False
        assert "unknown_membership_available_from" in audit["blockers"]


def test_current_constituents_source_blocks_clean_label() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "membership.csv"
        out = root / "out"
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "date_from": "2020-01-01",
                    "date_to": "2020-03-31",
                    "membership_available_from": "2020-01-01",
                }
            ]
        ).to_csv(src, index=False)
        result = run_tool(
            [
                "--membership-file",
                str(src),
                "--output-dir",
                str(out),
                "--start-date",
                "2020-01-01",
                "--end-date",
                "2020-03-31",
                "--source-kind",
                "current_constituents_proxy",
                "--coverage-floor",
                "1",
            ]
        )
        assert result.returncode == 0, result.stderr
        audit = read_json(out / "pit_membership_audit.json")
        assert audit["pit_universe_label_clean"] is False
        assert audit["current_constituents_proxy_rows"] == 3
        assert "current_constituents_proxy_rows_present" in audit["blockers"]


if __name__ == "__main__":
    test_clean_date_range_membership_expands_and_passes()
    test_clean_source_without_provenance_stays_blocked()
    test_missing_available_from_stays_blocked()
    test_current_constituents_source_blocks_clean_label()
    print("pit_membership_producer_smoke: PASS")
