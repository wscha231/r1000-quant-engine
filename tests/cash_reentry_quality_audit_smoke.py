#!/usr/bin/env python3
"""Smoke tests for Alpha Plane cash/reentry quality audit."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_cash_reentry_quality_audit import run  # noqa: E402


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _target_rows(portfolio: str) -> list[dict[str, object]]:
    return [
        {"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 0.50},
        {"rebalance_date": "2026-01-31", "ticker": "CASH", "weight": 0.50},
        {"rebalance_date": "2026-02-28", "ticker": "AAA", "weight": 0.55},
        {"rebalance_date": "2026-02-28", "ticker": "CASH", "weight": 0.45},
        {"rebalance_date": "2026-03-31", "ticker": "AAA", "weight": 0.85},
        {"rebalance_date": "2026-03-31", "ticker": "CASH", "weight": 0.15},
        {"rebalance_date": "2026-04-30", "ticker": "AAA", "weight": 0.85},
        {"rebalance_date": "2026-04-30", "ticker": "CASH", "weight": 0.15},
    ]


def _build_inputs(latest: Path, include_crisis: bool = True) -> None:
    reports = latest / "reports"
    _write_csv(reports / "operating_main_target_book.csv", _target_rows("main"))
    _write_csv(reports / "operating_concentrated_target_book.csv", _target_rows("concentrated"))
    if include_crisis:
        _write_csv(
            latest / "alphaops_vnext" / "daily_crisis_state.csv",
            [
                {"date": "2026-01-15", "crisis_state": "CRISIS_DEFENSE"},
                {"date": "2026-02-15", "crisis_state": "CRISIS_DEFENSE"},
                {"date": "2026-03-01", "crisis_state": "GREEN"},
                {"date": "2026-04-01", "crisis_state": "GREEN"},
            ],
        )
    for portfolio in ("main", "concentrated"):
        _write_json(latest / "broker_replay" / portfolio / "metrics.json", {"max_dd": -0.24})
        _write_json(latest / "legacy_monthly_broker_replay" / portfolio / "metrics.json", {"max_dd": -0.25})
        _write_csv(
            latest / "broker_replay" / portfolio / "cash_ledger.csv",
            [
                {"date": "2026-01-31", "cash_weight": 0.50},
                {"date": "2026-02-28", "cash_weight": 0.45},
                {"date": "2026-03-31", "cash_weight": 0.03},
                {"date": "2026-04-30", "cash_weight": 0.16},
            ],
        )
        _write_csv(
            latest / "broker_replay" / portfolio / "equity_curve.csv",
            [
                {"date": "2026-03-31", "equity": 1.0},
                {"date": "2026-04-20", "equity": 1.05},
                {"date": "2026-06-03", "equity": 1.12},
            ],
        )


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        latest = root / "latest"
        _build_inputs(latest)
        out_dir = root / "out"
        summary = run(
            latest,
            out_dir,
            source_run_id="cash-run-123",
            source_commit_sha="abc123",
            source_branch="codex/alpha-plane-measurement-audits-20260615",
            source_artifact_name="cash-reentry-test-artifact",
        )
        assert summary["status"] == "completed", summary
        assert summary["production_mutation_allowed"] is False, summary
        assert summary["metric_mode"] == "broker_ledger_next_close", summary
        assert summary["source_run_id"] == "cash-run-123", summary
        assert summary["source_of_truth_level"] == "GITHUB_ARTIFACT", summary
        assert summary["cash_trap_rows"] > 0, summary
        assert summary["cash_contract_drift_rows"] > 0, summary

        cash_drag = pd.read_csv(out_dir / "cash_drag_report.csv")
        by_regime = pd.read_csv(out_dir / "cash_by_regime.csv")
        by_crisis = pd.read_csv(out_dir / "cash_by_crisis_state.csv")
        reentry = pd.read_csv(out_dir / "reentry_lag_report.csv")
        rebound = pd.read_csv(out_dir / "missed_rebound_report.csv")
        assert "cash_trap_flag" in cash_drag.columns
        for col in ("target_cash_weight", "broker_cash_weight", "cash_drift", "cash_contract_drift_flag"):
            assert col in cash_drag.columns, col
        assert bool(cash_drag["cash_contract_drift_flag"].astype(bool).any()), cash_drag
        assert bool(cash_drag["cash_trap_flag"].astype(bool).any()), cash_drag
        assert "cash_reason" in cash_drag.columns
        assert "GREEN" in set(by_regime["crisis_bucket"])
        assert not by_crisis.empty
        assert "reentry_cash_normalization_days" in reentry.columns
        assert "missed_rebound_pct" in rebound.columns

        payload = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert payload["by_portfolio"]["main"]["green_avg_cash"] > 0.10

        missing_latest = root / "missing_crisis_latest"
        _build_inputs(missing_latest, include_crisis=False)
        missing_out = root / "missing_crisis_out"
        missing_summary = run(missing_latest, missing_out)
        assert missing_summary["missing_crisis_state_rows"] > 0, missing_summary
        missing_cash = pd.read_csv(missing_out / "cash_drag_report.csv")
        assert "MISSING" in set(missing_cash["crisis_bucket"]), missing_cash
        assert "GREEN" not in set(missing_cash["crisis_bucket"]), missing_cash
        assert set(missing_cash["cash_audit_status"]) == {"REVIEW_REQUIRED_MISSING_CRISIS_STATE"}, missing_cash
    print("cash reentry quality audit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
