#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_actual_results_hold_screen import run  # noqa: E402


def test_actual_results_hold_screen_passes_narrow_pit_candidate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        target_dir = latest / "alphaops_vnext"
        audit_dir = latest / "entry_exit_timing_audit"
        target_dir.mkdir(parents=True)
        audit_dir.mkdir(parents=True)
        target_path = target_dir / "official_concentrated_target_book.csv"
        rows: list[dict[str, object]] = []
        audit_rows: list[dict[str, object]] = []
        for idx in range(36):
            prior = pd.Timestamp("2020-01-31") + pd.DateOffset(months=idx)
            drop = prior + pd.DateOffset(months=1)
            ticker = f"WIN{idx:02d}"
            rows.append(
                {
                    "rebalance_date": prior.date().isoformat(),
                    "ticker": ticker,
                    "weight": 0.10,
                    "holding_state": "HOLD",
                    "hold_replace_decision": "keep_prior_holding",
                    "leader_tier": "DUAL_LEADER",
                    "rs_benchmark_3m": 0.10,
                    "rs_benchmark_6m": 0.20,
                    "price_above_ma200": 1.0,
                    "actual_results_score": 0.4,
                    "eps_revision_score": 0.1,
                    "event_reaction_score": 0.0,
                }
            )
            rows.append({"rebalance_date": drop.date().isoformat(), "ticker": f"NEW{idx:02d}", "weight": 0.10})
            audit_rows.append(
                {
                    "portfolio": "concentrated",
                    "ticker": ticker,
                    "sell_date": (drop + pd.Timedelta(days=1)).date().isoformat(),
                    "sold_forward_return_126d": 0.20,
                    "same_day_replacement_return_126d": 0.05,
                    "premature_sell_excess_126d": 0.15,
                    "premature_sell_candidate": True,
                }
            )
        for idx in range(10):
            prior = pd.Timestamp("2024-07-31") + pd.DateOffset(months=idx)
            drop = prior + pd.DateOffset(months=1)
            ticker = f"OOS{idx:02d}"
            rows.append(
                {
                    "rebalance_date": prior.date().isoformat(),
                    "ticker": ticker,
                    "weight": 0.10,
                    "holding_state": "HOLD",
                    "hold_replace_decision": "keep_prior_holding",
                    "leader_tier": "SECTOR_LEADER",
                    "rs_benchmark_3m": 0.08,
                    "rs_benchmark_6m": 0.16,
                    "price_above_ma200": 1.0,
                    "actual_results_score": 0.3,
                    "eps_revision_score": 0.0,
                    "event_reaction_score": 0.2,
                }
            )
            rows.append({"rebalance_date": drop.date().isoformat(), "ticker": f"NO{idx:02d}", "weight": 0.10})
            audit_rows.append(
                {
                    "portfolio": "concentrated",
                    "ticker": ticker,
                    "sell_date": (drop + pd.Timedelta(days=1)).date().isoformat(),
                    "sold_forward_return_126d": 0.18,
                    "same_day_replacement_return_126d": 0.08,
                    "premature_sell_excess_126d": 0.10,
                    "premature_sell_candidate": True,
                }
            )
        pd.DataFrame(rows).to_csv(target_path, index=False)
        pd.DataFrame(audit_rows).to_csv(audit_dir / "premature_sell_counterfactual.csv", index=False)

        payload = run(
            latest_run=latest,
            output_dir=root / "out",
            portfolio="concentrated",
            target_book=target_path,
            oos_start="2024-06-03",
        )

        assert payload["evidence_availability"]["actual_results_score_column_present"] is True
        assert payload["evidence_availability"]["actual_results_score_positive_rows"] >= 46
        primary = payload["primary_candidate"]
        assert primary["evaluation"]["screen_pass"] is True
        assert primary["evaluation"]["next_action"] == "design_default_off_hook_candidate"
        assert primary["summaries"]["full"]["rows"] >= 40
        assert primary["summaries"]["oos"]["rows"] >= 8
        assert (root / "out" / "candidate_rows.csv").exists()
        assert (root / "out" / "report.md").exists()


def test_actual_results_hold_screen_blocks_missing_actual_results() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        target_dir = latest / "alphaops_vnext"
        audit_dir = latest / "entry_exit_timing_audit"
        target_dir.mkdir(parents=True)
        audit_dir.mkdir(parents=True)
        target_path = target_dir / "official_concentrated_target_book.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2021-01-31",
                    "ticker": "AAA",
                    "weight": 0.10,
                    "holding_state": "HOLD",
                    "leader_tier": "DUAL_LEADER",
                    "rs_benchmark_3m": 0.10,
                    "rs_benchmark_6m": 0.20,
                    "price_above_ma200": 1.0,
                },
                {"rebalance_date": "2021-02-28", "ticker": "BBB", "weight": 0.10},
            ]
        ).to_csv(target_path, index=False)
        pd.DataFrame(
            [
                {
                    "portfolio": "concentrated",
                    "ticker": "AAA",
                    "sell_date": "2021-03-01",
                    "premature_sell_excess_126d": 0.20,
                }
            ]
        ).to_csv(audit_dir / "premature_sell_counterfactual.csv", index=False)

        payload = run(
            latest_run=latest,
            output_dir=root / "out",
            portfolio="concentrated",
            target_book=target_path,
            oos_start="2024-06-03",
        )

        assert payload["evidence_availability"]["actual_results_score_column_present"] is False
        assert payload["primary_candidate"]["evaluation"]["screen_pass"] is False


if __name__ == "__main__":
    test_actual_results_hold_screen_passes_narrow_pit_candidate()
    test_actual_results_hold_screen_blocks_missing_actual_results()
    print("actual_results_hold_screen_smoke: PASS")
