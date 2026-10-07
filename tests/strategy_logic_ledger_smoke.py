#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_strategy_logic_ledger_records_decision_attribution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        integrated = root / "integrated"
        (latest / "account_evaluation").mkdir(parents=True)
        (latest / "market_leader_challenger").mkdir()
        integrated.mkdir()
        (latest / "account_evaluation" / "official_metrics.json").write_text(
            json.dumps(
                {
                    "official_metric_mode": "broker_ledger_next_close",
                    "portfolios": {
                        "main": {"cagr": 0.20, "max_dd": -0.30, "sharpe": 1.0},
                        "concentrated": {
                            "cagr": 0.30,
                            "max_dd": -0.38,
                            "sharpe": 1.1,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "variant_id": "leader_n15",
                    "target_n": 15,
                    "cagr": 0.25,
                    "max_dd": -0.34,
                    "metric_mode": "broker_ledger_next_close",
                }
            ]
        ).to_csv(
            latest / "market_leader_challenger" / "grid_results.csv",
            index=False,
        )
        pd.DataFrame(
            [
                {
                    "case_id": "H",
                    "portfolio_kind": "main",
                    "purpose": "final_candidate",
                    "selection_layer": "multi_lane",
                    "lane_allocator_enabled": True,
                    "crisis_overlay": True,
                    "hold_replace_enabled": True,
                    "requested_target_n": 15,
                    "cagr": 0.26,
                    "max_dd": -0.24,
                    "covid_mdd": -0.18,
                    "rate_2022_mdd": -0.20,
                    "green_avg_cash": 0.03,
                    "reentry_lag_days": 10,
                    "cash_trap_days": 0,
                    "metric_mode": "broker_ledger_next_close",
                }
            ]
        ).to_csv(integrated / "ab_matrix.csv", index=False)

        out = root / "ledger"
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run_strategy_logic_ledger.py"),
                "--latest-run",
                str(latest),
                "--integrated-output",
                str(integrated),
                "--output-dir",
                str(out),
                "--run-id",
                "run-test",
                "--commit-sha",
                "abc123",
                "--artifact-id",
                "artifact-test",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        ledger = pd.read_csv(out / "strategy_logic_ledger.csv")
        required = {
            "buy_reason",
            "sell_reason",
            "hold_reason",
            "replace_reason",
            "crisis_action_reason",
            "case_id",
            "lane_allocator_enabled",
            "hold_replace_enabled",
            "target_n",
            "caps",
            "covid_mdd",
            "rate_2022_mdd",
            "green_avg_cash",
            "reentry_lag",
            "cash_trap_days",
            "lane_reason",
            "theme_reason",
            "evidence_reason",
        }
        assert required.issubset(ledger.columns)
        assert {
            "strategy_outcome_matrix.csv",
            "logic_family_summary.csv",
            "best_logic_by_regime.csv",
        }.issubset({path.name for path in out.iterdir()})
        assert "final_candidate" in set(ledger["strategy_family"])


def test_strategy_difference_reporter_contract_normal_and_optimized() -> None:
    for optimized in (False, True):
        cmd = [sys.executable]
        if optimized:
            cmd.append("-O")
        cmd.append(str(ROOT / "tests" / "strategy_difference_reporter_smoke.py"))
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "strategy_difference_reporter: PASS (16 tests)" in proc.stdout


def test_r0_all_legacy_parity_contract_normal_and_optimized() -> None:
    # Structural-only: this bridge can never declare economic R0 parity PASS.
    for optimized in (False, True):
        cmd = [sys.executable]
        if optimized:
            cmd.append("-O")
        cmd.append(
            str(ROOT / "tests" / "r0_all_legacy_full_control_parity_smoke.py")
        )
        env = dict(os.environ)
        env["R0_OPTIMIZED_CHILD"] = "1"
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (
            "r0_all_legacy_full_control_parity_smoke: "
            "PASS (22 structural tests)"
        ) in proc.stdout


def main() -> int:
    test_strategy_logic_ledger_records_decision_attribution()
    test_strategy_difference_reporter_contract_normal_and_optimized()
    test_r0_all_legacy_parity_contract_normal_and_optimized()
    print("strategy_logic_ledger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
