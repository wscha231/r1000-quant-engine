#!/usr/bin/env python3
"""Smoke tests for report-only aggressive lab tooling."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def assert_ok(result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode != 0:
        raise AssertionError(f"command failed ({result.returncode}):\n{result.stdout}")


def test_regression_attribution(tmp: Path) -> None:
    out_md = tmp / "regression.md"
    out_json = tmp / "regression.json"
    result = run_cmd(
        [
            "tools/regression_attribution.py",
            "--out",
            str(out_md),
            "--json-out",
            str(out_json),
        ]
    )
    assert_ok(result)
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "main_metric_deltas" in payload
    assert "portfolio_diff" in payload
    assert out_md.exists()


def test_e0_lab_runner(tmp: Path) -> None:
    outputs_root = tmp / "experiments"
    result = run_cmd(
        [
            "tools/run_aggressive_lab.py",
            "--experiment-id",
            "E0_baseline_latest",
            "--outputs-root",
            str(outputs_root),
        ]
    )
    assert_ok(result)
    exp_dir = outputs_root / "E0_baseline_latest"
    required = [
        "metrics.json",
        "equity_curve.csv",
        "monthly_allocations.csv",
        "sleeve_returns.csv",
        "turnover.csv",
        "stress_windows.csv",
        "trade_journal_summary.md",
        "experiment_report.md",
        "gate_report.json",
    ]
    missing = [name for name in required if not (exp_dir / name).exists()]
    assert not missing, f"missing outputs: {missing}"
    metrics = json.loads((exp_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["experiment_id"] == "E0_baseline_latest"
    assert metrics["control"] is True
    gate = json.loads((exp_dir / "gate_report.json").read_text(encoding="utf-8"))
    assert gate["control"] is True
    assert gate["passed_discovery"] is False


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_regression_attribution(tmp)
        test_e0_lab_runner(tmp)
    print("aggressive lab smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
