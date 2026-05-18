#!/usr/bin/env python3
"""Tier-1 fast validation runner for code-level changes.

Catches syntax errors, schema regressions, and smoke-test breakages in
~30 seconds locally / ~2-3 minutes in CI. Designed so a developer can
run one command before pushing, or have GitHub Actions
(pr_validation.yml) run the same set on every push.

Validation tiers
================
    Tier 0 (this script, local)         ~30 s    code-level smoke
    Tier 1 (pr_validation.yml, CI)      ~2-3 min code-level smoke + leakage audit
    Tier 2 (alphaops_replay_sidecars_   10-30 min real-data sidecars rerun on
            manual.yml)                          prior full-rebuild artifacts
    Tier 3 (full_rebuild_manual.yml)    2-6 h    full data collection +
                                                 84-month backtest + replays

This runner does NOT exercise real-data sidecars or backtests. Use
Tier 2 for sidecar metric verification, Tier 3 for baseline rotation.

Usage
=====
    py -3 tools/run_pr_validation.py
    py -3 tools/run_pr_validation.py --include event_target_books_smoke
    py -3 tools/run_pr_validation.py --quiet

Exits 0 on full pass, non-zero on first failure. Failure output is
trimmed to the last 15 lines of stdout+stderr per failing test.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Force UTF-8 for child Python processes so leakage-audit em-dash prints
# do not crash on Windows cp949 consoles. No-op on Linux/CI where UTF-8
# is already default.
CHILD_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

# Top-tier smoke tests that exercise the broker-ledger replay path,
# weekly leader sidecar, broker position/execution policy, operating
# target books, and the leakage audit. Each is fast (< 30 s).
DEFAULT_TESTS: list[tuple[str, list[str]]] = [
    ("tests/smoke_test.py", []),
    ("tests/broker_ledger_replay_smoke.py", []),
    ("tests/broker_ledger_correctness_smoke.py", []),
    ("tests/broker_position_risk_replay_smoke.py", []),
    ("tests/broker_execution_policy_replay_smoke.py", []),
    ("tests/broker_market_circuit_replay_smoke.py", []),
    ("tests/broker_market_circuit_grid_smoke.py", []),
    ("tests/broker_replacement_swap_replay_smoke.py", []),
    ("tests/broker_crisis_reentry_replay_smoke.py", []),
    ("tests/operating_target_books_smoke.py", []),
    ("tests/event_target_books_smoke.py", []),
    ("tests/weekly_leader_target_books_smoke.py", []),
    ("tests/candidate_universe_fallback_smoke.py", []),
    ("tests/replay_price_cache_smoke.py", []),
    ("tests/main_v3_alpha_concentration_smoke.py", []),
    ("tests/concentrated_v2_challenger_smoke.py", []),
    ("tests/concentrated_broker_grid_smoke.py", []),
    ("tests/alpha_selector_broker_grid_smoke.py", []),
    ("tests/alpha_selector_market_circuit_grid_smoke.py", []),
    ("tests/alpha_selector_leader_circuit_grid_smoke.py", []),
    ("tests/alpha_selector_dynamic_regime_grid_smoke.py", []),
    ("tests/alpha_selector_shadow_drawdown_grid_smoke.py", []),
    ("tests/portfolio_system_guard_smoke.py", []),
    ("tests/operating_event_backtest_smoke.py", []),
    ("tests/auto_learning_evidence_smoke.py", []),
    ("tests/auto_learning_v2_smoke.py", []),
    ("tests/auto_policy_challenger_smoke.py", []),
    ("tests/cost_sensitivity_sidecar_smoke.py", []),
    ("tests/alpha_sprint_first_float_smoke.py", []),
    ("tests/trade_attribution_analysis_smoke.py", []),
    ("tests/neutral_regime_churn_filter_smoke.py", []),
    ("tests/macro_circuit_breaker_filter_smoke.py", []),
    ("tests/regime_capacity_filter_smoke.py", []),
    ("tests/cash_policy_reconciliation_smoke.py", []),
    ("tests/selection_quality_report_smoke.py", []),
    ("tests/leader_drop_diagnostics_smoke.py", []),
    ("tests/sec_cik_schema_smoke.py", []),
    ("tests/sec_form4_parser_smoke.py", []),
    ("tests/sec_pit_available_from_smoke.py", []),
    ("tests/market_circuit_attribution_smoke.py", []),
    ("tests/concentrated_proxy_to_broker_reconciliation_smoke.py", []),
    ("tests/audit_features.py", ["--no-runtime"]),
    ("tests/workflow_artifact_smoke.py", []),
    ("tests/survivorship_audit_smoke.py", []),
    ("tests/refresh_etf_top_holdings_smoke.py", []),
]


def run_one(rel_path: str, extra_args: list[str], quiet: bool) -> tuple[bool, float, str]:
    full = ROOT / rel_path
    if not full.exists():
        return False, 0.0, f"missing test file: {rel_path}"
    start = time.monotonic()
    cmd = [sys.executable, str(full), *extra_args]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=CHILD_ENV, encoding="utf-8", errors="replace")
    elapsed = time.monotonic() - start
    if proc.returncode != 0:
        combined = (proc.stdout + proc.stderr).strip()
        tail = "\n".join(combined.splitlines()[-15:]) if combined else "<no output>"
        return False, elapsed, tail
    if not quiet and proc.stdout.strip():
        last_line = proc.stdout.strip().splitlines()[-1]
        return True, elapsed, last_line
    return True, elapsed, ""


def main() -> int:
    # Ensure our own stdout can carry non-ASCII content from child test
    # outputs (e.g. em-dash in the leakage-audit banner) on Windows cp949.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Additional smoke test(s) to run; pass either 'name_smoke' or 'tests/name_smoke.py'.",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="If supplied, restrict to these tests (matched by substring against the path).",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress per-test tail output on success.")
    args = parser.parse_args()

    tests = list(DEFAULT_TESTS)
    for extra in args.include:
        path = extra if extra.startswith("tests/") else f"tests/{extra}"
        if not path.endswith(".py"):
            path += ".py"
        tests.append((path, []))
    if args.only:
        tests = [(p, a) for (p, a) in tests if any(token in p for token in args.only)]

    print("=" * 72)
    print(f"PR validation: {len(tests)} test files")
    print("=" * 72)
    failures: list[tuple[str, str]] = []
    total_start = time.monotonic()
    for rel_path, extra_args in tests:
        passed, elapsed, msg = run_one(rel_path, extra_args, args.quiet)
        mark = "PASS" if passed else "FAIL"
        joined_args = " ".join(extra_args)
        suffix = f"  {msg}" if (passed and msg and not args.quiet) else ""
        print(f"  [{mark}] {elapsed:6.2f}s  {rel_path} {joined_args}{suffix}".rstrip())
        if not passed:
            failures.append((rel_path, msg))
    total_elapsed = time.monotonic() - total_start
    print("=" * 72)
    print(f"Total: {total_elapsed:6.2f}s  ({len(tests) - len(failures)}/{len(tests)} passed)")
    if failures:
        print()
        print("Failures (last 15 lines each):")
        for rel_path, msg in failures:
            print()
            print(f"--- {rel_path} ---")
            print(msg)
        return 1
    print("OK -- all PR validation tests pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
