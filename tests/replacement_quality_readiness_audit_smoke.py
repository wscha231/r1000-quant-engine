#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_replacement_quality_readiness_audit import run  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_readiness_audit_blocks_broad_hook_and_bad_control() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        official = root / "official.json"
        baseline = root / "baseline.json"
        summary = root / "summary.json"
        fixed = root / "fixed.csv"
        hook = root / "hook.csv"
        _write_json(
            official,
            {
                "portfolios": {
                    "concentrated": {
                        "cagr": 0.45,
                        "max_dd": -0.23,
                        "starting_capital_usd": 100000.0,
                        "ending_capital_usd": 1350000.0,
                        "years": 7.0,
                        "start_date": "2019-01-01",
                        "end_date": "2026-01-01",
                    }
                }
            },
        )
        _write_json(
            baseline,
            {
                "metric_mode": "broker_ledger_next_close_cash_carry",
                "cagr": 0.49,
                "max_dd": -0.23,
                "starting_capital_usd": 100000.0,
                "ending_capital_usd": 1700000.0,
                "years": 7.0,
                "cash_interest_accrued_usd": 20000.0,
                "start_date": "2019-01-01",
                "end_date": "2026-01-01",
            },
        )
        _write_json(summary, {"baseline_metrics": str(baseline)})
        pd.DataFrame(
            [
                {
                    "rule": "rank_top15_and_revenue_ge10",
                    "rebalance_date": "2026-01-31",
                    "added_ticker": "WIN",
                    "removed_ticker": "OLD",
                    "replacement_weight": 0.2,
                }
            ]
        ).to_csv(fixed, index=False)
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "WIN",
                    "concentrated_replacement_quality_applied": True,
                    "concentrated_replacement_quality_added_ticker": "WIN",
                    "concentrated_replacement_quality_removed_ticker": "OLD",
                },
                {
                    "rebalance_date": "2026-02-28",
                    "ticker": "EXTRA",
                    "concentrated_replacement_quality_applied": True,
                    "concentrated_replacement_quality_added_ticker": "EXTRA",
                    "concentrated_replacement_quality_removed_ticker": "OTHER",
                },
            ]
        ).to_csv(hook, index=False)
        payload = run(
            argparse.Namespace(
                official_metrics=str(official),
                counterfactual_summary=str(summary),
                hook_target_book=str(hook),
                fixed_swaps=str(fixed),
                baseline_metrics="",
                output_dir=str(root / "out"),
                run_label="bad",
                portfolio="concentrated",
                cagr_tolerance=0.0025,
                ending_capital_tolerance_pct=0.01,
                swap_count_tolerance_pct=0.10,
            )
        )
        assert payload["status"] == "blocked"
        assert "control_not_reproduced" in payload["blockers"]
        assert "hook_broader_than_fixed_counterfactual" in payload["blockers"]
        assert "hook_swap_count_outside_tolerance" in payload["blockers"]
        assert payload["swap_diff"]["overlap_count"] == 1
        assert payload["swap_diff"]["hook_only_count"] == 1
        assert (root / "out" / "swap_diff.csv").exists()


def test_readiness_audit_passes_aligned_case() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        official = root / "official.json"
        baseline = root / "baseline.json"
        summary = root / "summary.json"
        fixed = root / "fixed.csv"
        hook = root / "hook.csv"
        years = 7.0
        official_end = 100000.0 * (1.45**years)
        cash_interest = 1000.0
        baseline_end = official_end + cash_interest
        baseline_cagr = (baseline_end / 100000.0) ** (1.0 / years) - 1.0
        _write_json(
            official,
            {
                "portfolios": {
                    "concentrated": {
                        "cagr": 0.45,
                        "max_dd": -0.23,
                        "starting_capital_usd": 100000.0,
                        "ending_capital_usd": official_end,
                        "years": years,
                    }
                }
            },
        )
        _write_json(
            baseline,
            {
                "metric_mode": "broker_ledger_next_close_cash_carry",
                "cagr": baseline_cagr,
                "max_dd": -0.23,
                "starting_capital_usd": 100000.0,
                "ending_capital_usd": baseline_end,
                "years": years,
                "cash_interest_accrued_usd": cash_interest,
            },
        )
        _write_json(summary, {"baseline_metrics": str(baseline)})
        row = {
            "rebalance_date": "2026-01-31",
            "added_ticker": "WIN",
            "removed_ticker": "OLD",
            "replacement_weight": 0.2,
        }
        pd.DataFrame([{"rule": "rank_top15_and_revenue_ge10", **row}]).to_csv(fixed, index=False)
        pd.DataFrame(
            [
                {
                    "rebalance_date": row["rebalance_date"],
                    "ticker": "WIN",
                    "concentrated_replacement_quality_applied": True,
                    "concentrated_replacement_quality_added_ticker": row["added_ticker"],
                    "concentrated_replacement_quality_removed_ticker": row["removed_ticker"],
                }
            ]
        ).to_csv(hook, index=False)
        payload = run(
            argparse.Namespace(
                official_metrics=str(official),
                counterfactual_summary=str(summary),
                hook_target_book=str(hook),
                fixed_swaps=str(fixed),
                baseline_metrics="",
                output_dir=str(root / "out"),
                run_label="good",
                portfolio="concentrated",
                cagr_tolerance=0.0025,
                ending_capital_tolerance_pct=0.01,
                swap_count_tolerance_pct=0.10,
            )
        )
        assert payload["status"] == "ready_for_broker_ab"
        assert payload["blockers"] == []
        assert payload["control_reproduction"]["control_reproduced"] is True
        assert payload["swap_diff"]["hook_is_subset_of_fixed"] is True
        assert payload["swap_diff"]["hook_count_within_tolerance"] is True


def test_readiness_audit_blocks_underfiring_subset() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        official = root / "official.json"
        baseline = root / "baseline.json"
        summary = root / "summary.json"
        fixed = root / "fixed.csv"
        hook = root / "hook.csv"
        years = 7.0
        official_end = 100000.0 * (1.45**years)
        _write_json(
            official,
            {
                "portfolios": {
                    "concentrated": {
                        "cagr": 0.45,
                        "max_dd": -0.23,
                        "starting_capital_usd": 100000.0,
                        "ending_capital_usd": official_end,
                        "years": years,
                    }
                }
            },
        )
        _write_json(
            baseline,
            {
                "metric_mode": "broker_ledger_next_close_cash_carry",
                "cagr": 0.45,
                "max_dd": -0.23,
                "starting_capital_usd": 100000.0,
                "ending_capital_usd": official_end,
                "years": years,
                "cash_interest_accrued_usd": 0.0,
            },
        )
        _write_json(summary, {"baseline_metrics": str(baseline)})
        fixed_rows = [
            {
                "rule": "rank_top15_and_revenue_ge10",
                "rebalance_date": "2026-01-31",
                "added_ticker": "WIN1",
                "removed_ticker": "OLD1",
                "replacement_weight": 0.2,
            },
            {
                "rule": "rank_top15_and_revenue_ge10",
                "rebalance_date": "2026-02-28",
                "added_ticker": "WIN2",
                "removed_ticker": "OLD2",
                "replacement_weight": 0.2,
            },
        ]
        pd.DataFrame(fixed_rows).to_csv(fixed, index=False)
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "WIN1",
                    "concentrated_replacement_quality_applied": True,
                    "concentrated_replacement_quality_added_ticker": "WIN1",
                    "concentrated_replacement_quality_removed_ticker": "OLD1",
                }
            ]
        ).to_csv(hook, index=False)
        payload = run(
            argparse.Namespace(
                official_metrics=str(official),
                counterfactual_summary=str(summary),
                hook_target_book=str(hook),
                fixed_swaps=str(fixed),
                baseline_metrics="",
                output_dir=str(root / "out"),
                run_label="underfire",
                portfolio="concentrated",
                cagr_tolerance=0.0025,
                ending_capital_tolerance_pct=0.01,
                swap_count_tolerance_pct=0.10,
            )
        )
        assert payload["status"] == "blocked"
        assert "hook_swap_count_outside_tolerance" in payload["blockers"]
        assert "hook_broader_than_fixed_counterfactual" not in payload["blockers"]
        assert payload["swap_diff"]["hook_is_subset_of_fixed"] is True
        assert payload["swap_diff"]["hook_count_within_tolerance"] is False


def main() -> int:
    test_readiness_audit_blocks_broad_hook_and_bad_control()
    test_readiness_audit_passes_aligned_case()
    test_readiness_audit_blocks_underfiring_subset()
    print("replacement_quality_readiness_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
