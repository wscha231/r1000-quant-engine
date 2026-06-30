#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def _metrics(cagr: float, max_dd: float) -> dict[str, object]:
    return {
        "metric_mode": "broker_ledger_next_close",
        "cagr": cagr,
        "max_dd": max_dd,
        "sharpe": 1.25,
        "years": 7.05,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _target_dir(root: Path) -> Path:
    target = root / "targets"
    target.mkdir(parents=True)
    _write_json(target / "main_fast_crash_hedge.json", {"status": "completed", "hedge_dates": 2})
    pd.DataFrame(
        [
            {"rebalance_date": "2020-03-31", "ticker": "SH", "weight": 0.075},
        ]
    ).to_csv(target / "main_fast_crash_hedge_actions.csv", index=False)
    pd.DataFrame(
        [
            {
                "rebalance_date": "2025-01-31",
                "ticker": "EARLY",
                "weight": 0.04,
                "concentrated_cashfunded_early_entry_applied": True,
            }
        ]
    ).to_csv(target / "official_concentrated_target_book.csv", index=False)
    return target


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "verify_alphaops_goal_artifact.py"), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_passing_metrics_and_hook_telemetry() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        tmp = Path(tmp_raw)
        main = tmp / "main_metrics.json"
        concentrated = tmp / "concentrated_metrics.json"
        out = tmp / "out"
        _write_json(main, _metrics(0.36, -0.247))
        _write_json(concentrated, _metrics(0.51, -0.249))
        target = _target_dir(tmp)

        proc = _run(
            "--main-metrics",
            str(main),
            "--concentrated-metrics",
            str(concentrated),
            "--target-dir",
            str(target),
            "--output-dir",
            str(out),
            "--expect-pit-unclean",
        )

        assert proc.returncode == 0, proc.stdout + proc.stderr
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["status"] == "pass"
        assert summary["portfolios"]["main"]["pass"] is True
        assert summary["portfolios"]["concentrated"]["pass"] is True
        assert summary["hook_checks"]["main_hedge_dates"] == 2
        assert summary["hook_checks"]["concentrated_early_entry_applied_rows"] == 1
        assert summary["production_blocker"]["production_promotion_allowed"] is False


def test_failing_metrics_return_nonzero() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        tmp = Path(tmp_raw)
        main = tmp / "main_metrics.json"
        concentrated = tmp / "concentrated_metrics.json"
        _write_json(main, _metrics(0.34, -0.247))
        _write_json(concentrated, _metrics(0.51, -0.249))
        target = _target_dir(tmp)

        proc = _run(
            "--main-metrics",
            str(main),
            "--concentrated-metrics",
            str(concentrated),
            "--target-dir",
            str(target),
            "--expect-pit-unclean",
        )

        assert proc.returncode == 1
        assert "Overall status: **fail**" in proc.stdout


if __name__ == "__main__":
    test_passing_metrics_and_hook_telemetry()
    test_failing_metrics_return_nonzero()
    print("alphaops_goal_verifier_smoke: PASS")
