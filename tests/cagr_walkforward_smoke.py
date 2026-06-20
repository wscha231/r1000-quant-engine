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
    start = date(2020, 1, 1)
    years = (day - start).days / 365.25
    return 100.0 * (1.10**years)


def equity_at_rate(day: date, *, start: date, start_equity: float, annual_rate: float) -> float:
    years = (day - start).days / 365.25
    return start_equity * ((1.0 + annual_rate) ** years)


def write_known_curve(root: Path, portfolio: str) -> list[Path]:
    dates = [
        date(2020, 1, 1),
        date(2020, 12, 31),
        date(2021, 1, 1),
        date(2021, 12, 31),
        date(2022, 1, 1),
        date(2022, 12, 31),
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
    assert summary["schema_version"] == "cagr-walkforward-v5"
    assert summary["metric_mode"] == "broker_ledger_next_close"
    assert len(summary["windows"]) == 7
    assert summary["completed_full_year_count"] == 6
    assert summary["completed_partial_year_count"] == 1
    assert summary["windows"][-1]["year"] == 2026
    assert summary["windows"][-1]["end_date"] == "2026-06-30"
    assert summary["windows"][-1]["partial"] is True
    assert summary["windows"][-1]["included_in_average"] is False
    assert len(summary["partial_year_cagrs_for_reference_only"]) == 1
    assert summary["partial_year_cagrs_for_reference_only"][0]["year"] == 2026
    assert summary["full_years_in_average"] == [2020, 2021, 2022, 2023, 2024, 2025]
    assert summary["partial_years_for_reference_only"] == [2026]
    for window in summary["windows"]:
        assert window["status"] == "completed", window
        assert math.isclose(window["cagr"], 0.10, rel_tol=0.0, abs_tol=1e-9), window
        assert math.isclose(window["max_drawdown"], 0.0, rel_tol=0.0, abs_tol=1e-9), window
    assert math.isclose(summary["walk_forward_cagr_avg"], 0.10, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(summary["partial_year_day_weighted_cagr_avg"], 0.10, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(summary["partial_year_day_weighted_cagr_geomean"], 0.10, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(summary["full_max_drawdown"], 0.0, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(summary["worst_full_year_max_drawdown"], 0.0, rel_tol=0.0, abs_tol=1e-9)
    assert len(summary["partial_year_max_drawdowns_for_reference_only"]) == 1
    assert math.isclose(
        summary["partial_year_max_drawdowns_for_reference_only"][0]["max_drawdown"],
        0.0,
        rel_tol=0.0,
        abs_tol=1e-9,
    )
    assert summary["single_oos_cagr_source"] == "metrics"
    expected_inflation = summary["single_oos_cagr"] / summary["walk_forward_cagr_avg"]
    assert math.isclose(summary["inflation_indicator"], expected_inflation, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(summary["inflation_indicator"], 3.0, rel_tol=0.0, abs_tol=1e-9)
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
        assert payload["summaries"]["main"]["completed_full_year_count"] == 0
        assert payload["summaries"]["main"]["completed_partial_year_count"] == 0


def test_fallback_unavailable_yields_unavailable_verdict() -> None:
    with local_tempdir() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out = root / "out"
        for portfolio in ("main", "concentrated"):
            dates = [
                date(2020, 1, 1),
                date(2020, 12, 31),
                date(2021, 1, 1),
                date(2021, 12, 31),
                date(2022, 1, 1),
                date(2022, 12, 31),
                date(2023, 1, 1),
                date(2023, 12, 31),
                date(2024, 1, 1),
                date(2024, 12, 31),
                date(2025, 1, 1),
                date(2025, 12, 31),
                date(2026, 1, 1),
                date(2026, 6, 30),
            ]
            curve_path = latest / "broker_replay" / portfolio / "equity_curve.csv"
            metrics_path = latest / "broker_replay" / portfolio / "metrics.json"
            write_csv(
                curve_path,
                pd.DataFrame({"date": [d.isoformat() for d in dates], "equity": [equity_at(d) for d in dates]}),
            )
            write_json(metrics_path, {"metric_mode": "broker_ledger_next_close", "cagr": 0.10})

        payload = run(latest, out)
        summary = payload["summaries"]["main"]

        assert summary["single_oos_cagr"] is None
        assert summary["single_oos_cagr_source"] == "unavailable"
    assert math.isclose(summary["walk_forward_cagr_avg"], 0.10, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(summary["partial_year_day_weighted_cagr_avg"], 0.10, rel_tol=0.0, abs_tol=1e-9)
    assert summary["inflation_indicator"] is None
    assert summary["partial_year_day_weighted_inflation_indicator"] is None
    assert summary["verdict"] == "single_oos_unavailable"


def test_partial_windows_excluded_from_average() -> None:
    with local_tempdir() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out = root / "out"
        for portfolio in ("main", "concentrated"):
            dates = [
                date(2020, 1, 1),
                date(2020, 12, 31),
                date(2021, 1, 1),
                date(2021, 12, 31),
                date(2022, 1, 1),
                date(2022, 12, 31),
                date(2023, 1, 1),
                date(2023, 12, 31),
                date(2024, 1, 1),
                date(2024, 12, 31),
                date(2025, 1, 1),
                date(2025, 12, 31),
                date(2026, 1, 1),
                date(2026, 6, 30),
            ]
            equity_values = [equity_at(d) for d in dates[:-1]]
            partial_start = dates[-2]
            partial_start_equity = equity_values[-1]
            equity_values.append(
                equity_at_rate(dates[-1], start=partial_start, start_equity=partial_start_equity, annual_rate=1.00)
            )
            curve_path = latest / "broker_replay" / portfolio / "equity_curve.csv"
            metrics_path = latest / "broker_replay" / portfolio / "metrics.json"
            write_csv(curve_path, pd.DataFrame({"date": [d.isoformat() for d in dates], "equity": equity_values}))
            write_json(
                metrics_path,
                {"metric_mode": "broker_ledger_next_close", "cagr": 0.10, "windows": {"oos": {"cagr": 0.10}}},
            )

        payload = run(latest, out)
        summary = payload["summaries"]["main"]

        assert summary["completed_full_year_count"] == 6
        assert summary["completed_partial_year_count"] == 1
        assert math.isclose(summary["walk_forward_cagr_avg"], 0.10, rel_tol=0.0, abs_tol=1e-9)
        assert summary["partial_year_day_weighted_cagr_avg"] > summary["walk_forward_cagr_avg"]
        assert summary["partial_year_day_weighted_cagr_avg"] < 1.00
        assert summary["partial_year_day_weighted_verdict"] == "single_oos_consistent_with_rolling_avg"
        assert summary["partial_year_cagrs_for_reference_only"][0]["year"] == 2026
        assert summary["partial_year_cagrs_for_reference_only"][0]["cagr"] > 0.90


def test_mid_2019_window_is_clean_7y_and_covers_covid_crash() -> None:
    with local_tempdir() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out = root / "out"
        start = date(2019, 6, 3)
        dates = [
            start,
            date(2019, 12, 31),
            date(2020, 1, 1),
            date(2020, 2, 19),
            date(2020, 3, 23),
            date(2020, 12, 31),
            date(2021, 1, 1),
            date(2021, 12, 31),
            date(2022, 1, 1),
            date(2022, 12, 31),
            date(2023, 1, 1),
            date(2023, 12, 31),
            date(2024, 1, 1),
            date(2024, 12, 31),
            date(2025, 1, 1),
            date(2025, 12, 31),
            date(2026, 1, 1),
            date(2026, 6, 30),
        ]
        for portfolio in ("main", "concentrated"):
            curve_path = latest / "broker_replay" / portfolio / "equity_curve.csv"
            metrics_path = latest / "broker_replay" / portfolio / "metrics.json"
            write_csv(
                curve_path,
                pd.DataFrame(
                    {
                        "date": [d.isoformat() for d in dates],
                        "equity": [equity_at_rate(d, start=start, start_equity=100.0, annual_rate=0.10) for d in dates],
                    }
                ),
            )
            write_json(
                metrics_path,
                {"metric_mode": "broker_ledger_next_close", "cagr": 0.10, "windows": {"oos": {"cagr": 0.10}}},
            )

        payload = run(latest, out)
        summary = payload["summaries"]["main"]

        assert summary["observed_start_date"] == "2019-06-03"
        assert summary["clean_7y_research_baseline_status"] == "pass"
        assert summary["covid_crash_coverage_status"] == "covered"
        assert summary["full_years_in_average"] == [2020, 2021, 2022, 2023, 2024, 2025]
        assert summary["partial_years_for_reference_only"] == [2019, 2026]


def test_post_covid_start_is_not_clean_7y_and_does_not_cover_crash() -> None:
    with local_tempdir() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out = root / "out"
        start = date(2020, 5, 1)
        dates = [
            start,
            date(2020, 12, 31),
            date(2021, 1, 1),
            date(2021, 12, 31),
            date(2022, 1, 1),
            date(2022, 12, 31),
            date(2023, 1, 1),
            date(2023, 12, 31),
            date(2024, 1, 1),
            date(2024, 12, 31),
            date(2025, 1, 1),
            date(2025, 12, 31),
            date(2026, 1, 1),
            date(2026, 6, 30),
        ]
        for portfolio in ("main", "concentrated"):
            curve_path = latest / "broker_replay" / portfolio / "equity_curve.csv"
            metrics_path = latest / "broker_replay" / portfolio / "metrics.json"
            write_csv(
                curve_path,
                pd.DataFrame(
                    {
                        "date": [d.isoformat() for d in dates],
                        "equity": [equity_at_rate(d, start=start, start_equity=100.0, annual_rate=0.10) for d in dates],
                    }
                ),
            )
            write_json(metrics_path, {"metric_mode": "broker_ledger_next_close", "cagr": 0.10})

        payload = run(latest, out)
        summary = payload["summaries"]["main"]

        assert summary["observed_start_date"] == "2020-05-01"
        assert summary["clean_7y_research_baseline_status"] == "insufficient_observed_window"
        assert summary["covid_crash_coverage_status"] == "not_covered"
        assert summary["partial_years_for_reference_only"] == [2020, 2026]
        assert summary["verdict"] == "single_oos_unavailable"


def test_midyear_start_is_included_as_partial_reference() -> None:
    with local_tempdir() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out = root / "out"
        start = date(2019, 6, 3)
        dates = [
            start,
            date(2019, 12, 31),
            date(2020, 1, 1),
            date(2020, 12, 31),
            date(2021, 1, 1),
            date(2021, 12, 31),
            date(2022, 1, 1),
            date(2022, 12, 31),
            date(2023, 1, 1),
            date(2023, 12, 31),
            date(2024, 1, 1),
            date(2024, 12, 31),
            date(2025, 1, 1),
            date(2025, 12, 31),
            date(2026, 1, 1),
            date(2026, 6, 30),
        ]
        for portfolio in ("main", "concentrated"):
            curve_path = latest / "broker_replay" / portfolio / "equity_curve.csv"
            metrics_path = latest / "broker_replay" / portfolio / "metrics.json"
            write_csv(
                curve_path,
                pd.DataFrame(
                    {
                        "date": [d.isoformat() for d in dates],
                        "equity": [equity_at_rate(d, start=start, start_equity=100.0, annual_rate=0.10) for d in dates],
                    }
                ),
            )
            write_json(metrics_path, {"metric_mode": "broker_ledger_next_close", "cagr": 0.10})

        payload = run(latest, out)
        summary = payload["summaries"]["main"]

        assert len(summary["windows"]) == 8
        assert summary["completed_full_year_count"] == 6
        assert summary["completed_partial_year_count"] == 2
        assert summary["full_years_in_average"] == [2020, 2021, 2022, 2023, 2024, 2025]
        assert summary["partial_years_for_reference_only"] == [2019, 2026]
        assert summary["windows"][0]["year"] == 2019
        assert summary["windows"][0]["partial"] is True
        assert summary["windows"][0]["included_in_average"] is False
        assert math.isclose(summary["windows"][0]["cagr"], 0.10, rel_tol=0.0, abs_tol=1e-9)
        assert math.isclose(summary["walk_forward_cagr_avg"], 0.10, rel_tol=0.0, abs_tol=1e-9)
        assert math.isclose(summary["partial_year_day_weighted_cagr_avg"], 0.10, rel_tol=0.0, abs_tol=1e-9)
        assert math.isclose(summary["partial_year_day_weighted_cagr_geomean"], 0.10, rel_tol=0.0, abs_tol=1e-9)


def main() -> int:
    test_known_answer_and_no_mutation()
    test_empty_curve_is_insufficient()
    test_fallback_unavailable_yields_unavailable_verdict()
    test_partial_windows_excluded_from_average()
    test_mid_2019_window_is_clean_7y_and_covers_covid_crash()
    test_post_covid_start_is_not_clean_7y_and_does_not_cover_crash()
    test_midyear_start_is_included_as_partial_reference()
    print("cagr_walkforward_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
