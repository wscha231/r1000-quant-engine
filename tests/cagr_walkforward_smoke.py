#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from uuid import uuid4

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_cagr_walkforward import run


@contextmanager
def local_tempdir():
    override = os.environ.get("R1000_TEST_TMPDIR")
    if not override:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            yield tmp
        return

    path = Path(override) / f"cagr_walkforward_{os.getpid()}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equity_at(day: date) -> float:
    start = date(2023, 1, 1)
    years = (day - start).days / 365.25
    return 100.0 * (1.10**years)


def write_known_curve(root: Path, portfolio: str) -> list[Path]:
    dates = [
        date(2023, 1, 1),
        date(2023, 12, 31),
        date(2024, 1, 1),
        date(2024, 12, 31),
        date(2025, 1, 1),
        date(2025, 12, 31),
        date(2026, 1, 1),
        date(2026, 6, 30),
    ]
    curve_path = root / "broker_replay" / portfolio / "equity_curve.csv"
    metrics_path = root / "broker_replay" / portfolio / "metrics.json"
    write_csv(curve_path, pd.DataFrame({"date": [d.isoformat() for d in dates], "equity": [equity_at(d) for d in dates]}))
    write_json(
        metrics_path,
        {
            "metric_mode": "broker_ledger_next_close",
            "cagr": 0.10,
            "windows": {"oos": {"cagr": 0.30}},
        },
    )
    return [curve_path, metrics_path]


def assert_known_answer(summary: dict) -> None:
    assert summary["schema_version"] == "cagr-walkforward-v1"
    assert summary["metric_mode"] == "broker_ledger_next_close"
    assert len(summary["windows"]) == 4
    assert summary["windows"][-1]["year"] == 2026
    assert summary["windows"][-1]["end_date"] == "2026-06-30"
    for window in summary["windows"]:
        assert window["status"] == "completed", window
        assert math.isclose(window["cagr"], 0.10, rel_tol=0.0, abs_tol=1e-9), window
    assert math.isclose(summary["walk_forward_cagr_avg"], 0.10, rel_tol=0.0, abs_tol=1e-9)
    expected_inflation = summary["single_oos_cagr"] / summary["walk_forward_cagr_avg"]
    assert math.isclose(summary["inflation_indicator"], expected_inflation, rel_tol=0.0, abs_tol=1e-9)
    assert summary["verdict"] == "single_oos_inflated_vs_rolling_avg"


def test_known_answer_and_no_mutation() -> None:
    with local_tempdir() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out = root / "out"
        input_files = []
        for portfolio in ("main", "concentrated"):
            input_files.extend(write_known_curve(latest, portfolio))
        before = {path: sha256(path) for path in input_files}

        payload = run(latest, out)

        assert (out / "main_summary.json").exists()
        assert (out / "concentrated_summary.json").exists()
        assert (out / "report.md").exists()
        assert_known_answer(payload["summaries"]["main"])
        assert_known_answer(payload["summaries"]["concentrated"])
        after = {path: sha256(path) for path in input_files}
        assert before == after


def test_empty_curve_is_insufficient() -> None:
    with local_tempdir() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out = root / "out"
        for portfolio in ("main", "concentrated"):
            write_csv(latest / "broker_replay" / portfolio / "equity_curve.csv", pd.DataFrame({"date": [], "equity": []}))
            write_json(latest / "broker_replay" / portfolio / "metrics.json", {"metric_mode": "broker_ledger_next_close"})

        payload = run(latest, out)

        assert payload["summaries"]["main"]["verdict"] == "insufficient_data"
        assert payload["summaries"]["concentrated"]["verdict"] == "insufficient_data"
        assert payload["summaries"]["main"]["completed_window_count"] == 0


def main() -> int:
    test_known_answer_and_no_mutation()
    test_empty_curve_is_insufficient()
    print("cagr_walkforward_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
