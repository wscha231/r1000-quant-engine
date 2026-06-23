#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[1]


def write_book(path: Path, dates: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for dt in dates:
        rows.append(
            {
                "rebalance_date": dt,
                "ticker": "AAA",
                "weight": 1.0,
                "available_from": dt,
                "membership_available_from": dt,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def main() -> int:
    base = REPO / "_tmp_tests" / "clean7y_window_preflight"
    if base.exists():
        for p in sorted(base.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
    latest = base / "latest"
    for rel in (
        "reports/candidate_replay_book.csv",
        "reports/operating_main_target_book.csv",
        "reports/operating_concentrated_target_book.csv",
        "alphaops_vnext/official_main_target_book.csv",
        "alphaops_vnext/official_concentrated_target_book.csv",
    ):
        write_book(latest / rel, ["2019-05-31", "2019-06-28"])

    out = base / "out"
    subprocess.run(
        [
            sys.executable,
            str(REPO / "tools" / "run_clean7y_window_preflight.py"),
            "--latest-run",
            str(latest),
            "--output-dir",
            str(out),
            "--strict",
        ],
        cwd=REPO,
        check=True,
    )
    status = json.loads((out / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "pass", status
    assert status["monthly_test_dates_first"] == "2019-05-31"
    assert status["expected_first_decision_next_close_fill"] == "2019-06-03"
    assert status["first_decision_pit"]["pit_status"] == "pass"
    assert status["target_books_first_pass"] is True

    stale = base / "stale"
    for rel in (
        "reports/candidate_replay_book.csv",
        "reports/operating_main_target_book.csv",
        "reports/operating_concentrated_target_book.csv",
        "alphaops_vnext/official_main_target_book.csv",
        "alphaops_vnext/official_concentrated_target_book.csv",
    ):
        write_book(stale / rel, ["2019-06-28"])
    stale_out = base / "stale_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools" / "run_clean7y_window_preflight.py"),
            "--latest-run",
            str(stale),
            "--output-dir",
            str(stale_out),
            "--strict",
        ],
        cwd=REPO,
    )
    assert proc.returncode == 1
    stale_status = json.loads((stale_out / "status.json").read_text(encoding="utf-8"))
    assert "candidate_replay_book_not_rebuilt_to_expected_window" in stale_status["blockers"]
    assert "target_books_not_rebuilt_to_expected_window" in stale_status["blockers"]

    print("clean7y_window_preflight_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
