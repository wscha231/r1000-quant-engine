#!/usr/bin/env python3
"""Smoke tests for review-only A/B result verifier."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_ab_result_verifier import run  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seed_run(
    root: Path,
    *,
    cagr: float,
    max_dd: float,
    is_cagr: float,
    years: float,
    target_pass: bool,
    strengthened_pass: bool,
    valid_for_production: bool = True,
    trading_days: int = 2050,
    system_acceptance: bool = True,
    hard_blockers: int = 0,
    production_activation_allowed: bool = False,
    oos_lock: bool = True,
    oos_lock_pass: bool = True,
    oos_is_ratio: float = 1.8,
) -> None:
    row = {
        "portfolio": "concentrated",
        "status": "completed",
        "official_metric_mode": "broker_ledger_next_close",
        "valid_for_production": valid_for_production,
        "target_pass": target_pass,
        "strengthened_pass": strengthened_pass,
        "tier2_failing": [] if strengthened_pass else ["is_cagr_min"],
        "cagr": cagr,
        "cagr_target": 0.50,
        "max_dd": max_dd,
        "max_dd_target": -0.28,
        "is_cagr": is_cagr,
        "oos_cagr": 0.55,
        "sharpe": 1.55,
        "avg_cash_weight": 0.35,
        "years": years,
        "start_date": "2018-06-01",
        "end_date": "2026-06-12",
        "broker_ledger_actual_trading_days": trading_days,
        "broker_ledger_window_gate": {
            "status": "ok" if valid_for_production else "invalid_window",
            "valid": valid_for_production,
            "reasons": [] if valid_for_production else ["broker_ledger_years_below_8"],
            "trading_days_estimate": trading_days,
        },
    }
    write_json(
        root / "account_evaluation" / "official_metrics.json",
        {
            "official_metric_mode": "broker_ledger_next_close",
            "production_target_pass": target_pass,
            "strengthened_pass": strengthened_pass,
            "portfolios": {"concentrated": row},
        },
    )
    write_json(
        root / "broker_replay" / "concentrated" / "metrics.json",
        {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close",
            "valid_for_production": valid_for_production,
            "cagr": cagr,
            "max_dd": max_dd,
            "years": years,
            "days": trading_days,
            "windows": {"is": {"cagr": is_cagr}, "oos": {"cagr": 0.55}},
        },
    )
    write_json(
        root / "is_attribution" / "summary.json",
        {
            "concentrated": {
                "is_cagr": is_cagr,
                "oos_cagr": 0.55,
                "leak_year_tags": {"2021": "healthy"},
                "structural_underinvestment_bull_years": [],
            }
        },
    )
    if system_acceptance:
        effective_blockers = hard_blockers + (0 if oos_lock_pass else 1)
        status = "production_evidence_ready" if effective_blockers == 0 else "not_ready"
        requirements = [
            {
                "requirement_id": "attribution_package_year_mdd_name",
                "status": "pass" if hard_blockers == 0 else "fail",
                "hard_blocker": hard_blockers != 0,
            }
        ]
        if oos_lock:
            requirements.append(
                {
                    "requirement_id": "oos_holdout_lock",
                    "status": "pass" if oos_lock_pass else "fail",
                    "hard_blocker": not oos_lock_pass,
                }
            )
        write_json(
            root / "system_acceptance_audit" / "summary.json",
            {
                "status": status,
                "production_activation_allowed": production_activation_allowed,
                "hard_blocker_count": effective_blockers,
                "requirements": requirements,
            },
        )
    if oos_lock:
        failures = [] if oos_lock_pass else ["oos_is_cagr_ratio_above_lock"]
        write_json(
            root / "oos_lock" / "summary.json",
            {
                "status": "pass" if oos_lock_pass else "fail",
                "lock_pass": oos_lock_pass,
                "hard_blocker_count": 0 if oos_lock_pass else 1,
                "production_activation_allowed": False,
                "config": {"oos_start": "2024-07-01", "max_oos_is_cagr_ratio": 3.0},
                "failures": {} if oos_lock_pass else {"concentrated": failures},
                "portfolios": {
                    "concentrated": {
                        "status": "pass" if oos_lock_pass else "fail",
                        "cagr_is": is_cagr,
                        "cagr_oos": 0.55,
                        "oos_is_cagr_ratio": oos_is_ratio,
                        "max_oos_is_cagr_ratio": 3.0,
                        "failures": failures,
                    }
                },
            },
        )


def args(baseline: Path, candidates: list[Path], out: Path) -> Namespace:
    return Namespace(
        baseline_run=str(baseline),
        candidate_run=[str(path) for path in candidates],
        output_dir=str(out),
        portfolio="concentrated",
        min_cagr_delta_pp=0.0,
        min_is_cagr_delta_pp=0.5,
        max_mdd_regression_pp=1.0,
        allow_missing_evidence=False,
    )


def test_verifier_marks_clean_candidate_review_promotable() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(candidate, cagr=0.52, max_dd=-0.26, is_cagr=0.31, years=8.10, target_pass=True, strengthened_pass=True)
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "review_candidate_ready"
        assert payload["production_activation_allowed"] is False
        row = payload["candidates"][0]
        assert row["decision"] == "promote_candidate_review_only"
        assert row["review_valid_for_promotion"] is True
        assert row["is_cagr_delta_vs_baseline_pp"] > 8.0
        assert (root / "out" / "candidate_verdicts.csv").exists()


def test_verifier_rejects_is_cagr_regression_even_if_headline_passes() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.51, max_dd=-0.25, is_cagr=0.32, years=8.10, target_pass=True, strengthened_pass=True)
        seed_run(candidate, cagr=0.53, max_dd=-0.25, is_cagr=0.30, years=8.10, target_pass=True, strengthened_pass=True)
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "rejected"
        row = payload["candidates"][0]
        assert row["decision"] == "reject_regression"
        assert any("is_cagr_delta_below_min" in issue for issue in row["issues"])


def test_verifier_invalidates_short_candidate_window() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=7.50,
            trading_days=1800,
            target_pass=True,
            strengthened_pass=True,
            valid_for_production=False,
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "rejected"
        row = payload["candidates"][0]
        assert row["decision"] == "invalid_window"
        assert "broker_ledger_years_below_8" in row["issues"]


def test_verifier_blocks_missing_acceptance_evidence() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=8.10,
            target_pass=True,
            strengthened_pass=True,
            system_acceptance=False,
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "blocked"
        row = payload["candidates"][0]
        assert row["decision"] == "blocked_missing_evidence"
        assert "system_acceptance_audit_missing" in row["issues"]


def test_verifier_blocks_missing_oos_lock_evidence() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=8.10,
            target_pass=True,
            strengthened_pass=True,
            oos_lock=False,
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "blocked"
        row = payload["candidates"][0]
        assert row["decision"] == "blocked_missing_evidence"
        assert "oos_lock_summary_missing" in row["issues"]
        assert "oos_holdout_lock:missing" in row["issues"]


def test_verifier_blocks_failed_oos_lock() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=8.10,
            target_pass=True,
            strengthened_pass=True,
            oos_lock_pass=False,
            oos_is_ratio=5.5,
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "blocked"
        row = payload["candidates"][0]
        assert row["decision"] == "blocked_oos_lock"
        assert "oos_is_cagr_ratio_above_lock" in row["issues"]


def test_verifier_carries_dispatch_context_for_queue_closure() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(candidate, cagr=0.52, max_dd=-0.26, is_cagr=0.31, years=8.10, target_pass=True, strengthened_pass=True)
        ns = args(baseline, [candidate], root / "out")
        ns.experiment_id = "conc_continuation_winner_relaxation"
        ns.payload_hash = "payload-ready"
        ns.workflow_run_id = "27599999999"
        ns.dispatch_run_id = "dispatcher-smoke"
        payload = run(ns)
        row = payload["candidates"][0]
        assert payload["dispatch_context"]["experiment_id"] == "conc_continuation_winner_relaxation"
        assert row["experiment_id"] == "conc_continuation_winner_relaxation"
        assert row["payload_hash"] == "payload-ready"
        assert row["workflow_run_id"] == "27599999999"
        assert row["dispatch_run_id"] == "dispatcher-smoke"
        assert row["candidate_run"] == "candidate"


if __name__ == "__main__":
    test_verifier_marks_clean_candidate_review_promotable()
    test_verifier_rejects_is_cagr_regression_even_if_headline_passes()
    test_verifier_invalidates_short_candidate_window()
    test_verifier_blocks_missing_acceptance_evidence()
    test_verifier_blocks_missing_oos_lock_evidence()
    test_verifier_blocks_failed_oos_lock()
    test_verifier_carries_dispatch_context_for_queue_closure()
    print("ab_result_verifier_smoke: PASS")
