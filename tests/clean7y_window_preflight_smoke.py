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
                "mom_1m": 0.05,
                "mom_3m": 0.10,
                "mom_6m": 0.20,
                "relative_strength_composite": 1.25,
                "price_above_ma200": 1.0,
                "rsi14": 62.0,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def write_manifest(root: Path, start: str = "2019-05-09") -> None:
    path = root / "manifests" / "replay_price_cache_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"start": start, "end": "2026-06-23", "status": "completed"}, indent=2),
        encoding="utf-8",
    )


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
    write_manifest(latest)

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
    assert status["first_decision_pit"]["feature_completeness"]["status"] == "pass"
    assert status["cache_manifest"]["start_pass"] is True
    assert status["projected_calendar_trading_days"]["pass"] is True
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
    write_manifest(stale)
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
    assert "candidate_replay_book_not_in_expected_clean7y_decision_window" in stale_status["blockers"]
    assert "target_books_not_in_expected_clean7y_decision_window" in stale_status["blockers"]

    too_early = base / "too_early"
    for rel in (
        "reports/candidate_replay_book.csv",
        "reports/operating_main_target_book.csv",
        "reports/operating_concentrated_target_book.csv",
        "alphaops_vnext/official_main_target_book.csv",
        "alphaops_vnext/official_concentrated_target_book.csv",
    ):
        write_book(too_early / rel, ["2019-03-29", "2019-05-31", "2019-06-28"])
    write_manifest(too_early)
    too_early_out = base / "too_early_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools" / "run_clean7y_window_preflight.py"),
            "--latest-run",
            str(too_early),
            "--output-dir",
            str(too_early_out),
            "--strict",
        ],
        cwd=REPO,
    )
    assert proc.returncode == 1
    too_early_status = json.loads((too_early_out / "status.json").read_text(encoding="utf-8"))
    assert too_early_status["files"]["candidate_replay_book"]["first_rebalance_date"] == "2019-03-29"
    assert "candidate_replay_book_not_in_expected_clean7y_decision_window" in too_early_status["blockers"]
    assert "target_books_not_in_expected_clean7y_decision_window" in too_early_status["blockers"]

    short_calendar = base / "short_calendar"
    for rel in (
        "reports/candidate_replay_book.csv",
        "reports/operating_main_target_book.csv",
        "reports/operating_concentrated_target_book.csv",
        "alphaops_vnext/official_main_target_book.csv",
        "alphaops_vnext/official_concentrated_target_book.csv",
    ):
        write_book(short_calendar / rel, ["2019-05-31", "2019-06-28"])
    write_manifest(short_calendar)
    short_calendar_out = base / "short_calendar_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools" / "run_clean7y_window_preflight.py"),
            "--latest-run",
            str(short_calendar),
            "--output-dir",
            str(short_calendar_out),
            "--end-date",
            "2026-05-01",
            "--strict",
        ],
        cwd=REPO,
    )
    assert proc.returncode == 1
    short_calendar_status = json.loads((short_calendar_out / "status.json").read_text(encoding="utf-8"))
    assert "projected_calendar_trading_days_below_7y" in short_calendar_status["blockers"]

    missing_features = base / "missing_features"
    for rel in (
        "reports/candidate_replay_book.csv",
        "reports/operating_main_target_book.csv",
        "reports/operating_concentrated_target_book.csv",
        "alphaops_vnext/official_main_target_book.csv",
        "alphaops_vnext/official_concentrated_target_book.csv",
    ):
        write_book(missing_features / rel, ["2019-05-31", "2019-06-28"])
    df = pd.read_csv(missing_features / "reports" / "candidate_replay_book.csv")
    df["mom_1m"] = 0.0
    df["mom_3m"] = 0.0
    df["mom_6m"] = 0.0
    df["relative_strength_composite"] = 0.0
    df.to_csv(missing_features / "reports" / "candidate_replay_book.csv", index=False)
    write_manifest(missing_features)
    missing_features_out = base / "missing_features_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools" / "run_clean7y_window_preflight.py"),
            "--latest-run",
            str(missing_features),
            "--output-dir",
            str(missing_features_out),
            "--strict",
        ],
        cwd=REPO,
    )
    assert proc.returncode == 1
    missing_features_status = json.loads((missing_features_out / "status.json").read_text(encoding="utf-8"))
    assert "first_decision_pit_check_failed" in missing_features_status["blockers"]

    print("clean7y_window_preflight_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
