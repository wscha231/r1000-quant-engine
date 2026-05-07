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


def test_e1_e5_report_only_adapters(tmp: Path) -> None:
    outputs_root = tmp / "experiments_report_only"
    result = run_cmd(
        [
            "tools/run_aggressive_lab.py",
            "--experiment-id",
            "E1_auto_feature_gates_on",
            "--experiment-id",
            "E5_orchestrator_balanced",
            "--outputs-root",
            str(outputs_root),
        ]
    )
    assert_ok(result)

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
    for exp_id in ["E1_auto_feature_gates_on", "E5_orchestrator_balanced"]:
        exp_dir = outputs_root / exp_id
        missing = [name for name in required if not (exp_dir / name).exists()]
        assert not missing, f"{exp_id} missing outputs: {missing}"
        gate = json.loads((exp_dir / "gate_report.json").read_text(encoding="utf-8"))
        assert gate["control"] is False
        assert gate["passed_discovery"] is False

    e1 = json.loads((outputs_root / "E1_auto_feature_gates_on" / "metrics.json").read_text(encoding="utf-8"))
    assert e1["status"] == "candidate_only"
    assert e1["backtest_executed"] is False
    assert e1["proposal_count"] == 4
    assert e1["promotion_approved"] is False

    e5 = json.loads((outputs_root / "E5_orchestrator_balanced" / "metrics.json").read_text(encoding="utf-8"))
    assert e5["status"] == "snapshot_report_only"
    assert e5["backtest_executed"] is False
    assert e5["proposed_cash_target"] <= e5["current_cash_target"]
    assert (outputs_root / "E5_orchestrator_balanced" / "proposed_unified_target_latest.csv").exists()


def test_full_aggressive_matrix_runner(tmp: Path) -> None:
    outputs_root = tmp / "experiments_full"
    result = run_cmd(
        [
            "tools/run_aggressive_experiment_matrix.py",
            "--outputs-root",
            str(outputs_root),
        ]
    )
    assert_ok(result)
    expected = [
        "E0_baseline_latest",
        "E1_auto_feature_gates_on",
        "E2_main_v2_balanced",
        "E3_main_v2_aggressive",
        "E4_concentrated_balanced",
        "E5_orchestrator_balanced",
        "E6_risk_sensing_on",
        "E7_tactical_bull_only",
        "E8_alpha_sprint_sidecar",
        "E9_kitchen_sink_all_on",
    ]
    for exp_id in expected:
        exp_dir = outputs_root / exp_id
        assert (exp_dir / "metrics.json").exists(), exp_id
        assert (exp_dir / "experiment_report.md").exists(), exp_id
        assert (exp_dir / "gate_report.json").exists(), exp_id
    assert (outputs_root / "experiment_matrix_ranking.md").exists()
    summary = json.loads((outputs_root / "experiment_matrix_summary.json").read_text(encoding="utf-8"))
    assert len(summary["rows"]) == len(expected)
    e6 = json.loads((outputs_root / "E6_risk_sensing_on" / "metrics.json").read_text(encoding="utf-8"))
    assert e6["backtest_executed"] is True
    assert e6["maxdd_delta_pp"] > 0
    e9 = json.loads((outputs_root / "E9_kitchen_sink_all_on" / "metrics.json").read_text(encoding="utf-8"))
    assert e9["never_promote_to_production"] is True


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_regression_attribution(tmp)
        test_e0_lab_runner(tmp)
        test_e1_e5_report_only_adapters(tmp)
        test_full_aggressive_matrix_runner(tmp)
    print("aggressive lab smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
