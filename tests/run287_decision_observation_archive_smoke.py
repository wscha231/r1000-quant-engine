#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.archive_run287_decision_observation import (  # noqa: E402
    BLOCKED_STATUS,
    READY_STATUS,
    SKIPPED_STATUS,
    build,
    sha256_file,
)


POLICY = "15176b588d5bb0792bce1df6367758d795a8a33a"
SELECTOR_CONTRACT = "647475ceaf2109d7dc7c7dfd18865679de86dc5afd102a090481e118bab4a02f"
HOLDING_CONTRACT = "afc30695761d6ee6a35ea269b03257fbac2c1bbca9fe90cca9df47bcf5c35657"
CANDIDATE_CONTRACT = "8e03bc1ae2653cbd2104e3ce4dcba012920cff91e93c61d7e3f33beb60423345"
SCENARIOS = [
    ("main", "strict_registered_current"),
    ("main", "prior_hold_transition_bridge"),
    ("concentrated", "strict_registered_current"),
]


def fingerprint(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "exists": True,
        "sha256": sha256_file(path),
    }


def write_packet(root: Path, as_of: str, *, changed_weight: bool = False) -> tuple[Path, Path]:
    packet = root / f"packet_{as_of}"
    packet.mkdir(parents=True, exist_ok=True)
    comparison_rows = []
    for portfolio, scenario in SCENARIOS:
        weight = 0.61 if changed_weight else 0.60
        comparison_rows.extend(
            [
                {
                    "ticker": "AAA",
                    "marked_weight": 0.0,
                    "official_prior_weight": 0.0,
                    "advisory_weight": weight,
                    "delta_vs_marked": weight,
                    "delta_vs_official": weight,
                    "action_vs_marked": "BUY",
                    "action_vs_official": "BUY",
                    "portfolio_kind": portfolio,
                    "scenario": scenario,
                    "execution_allowed": False,
                    "held_risk_state": "",
                    "held_risk_advisory_action": "",
                    "held_risk_reason_codes": "",
                },
                {
                    "ticker": "CASH",
                    "marked_weight": 1.0,
                    "official_prior_weight": 1.0,
                    "advisory_weight": 1.0 - weight,
                    "delta_vs_marked": -weight,
                    "delta_vs_official": -weight,
                    "action_vs_marked": "SELL",
                    "action_vs_official": "SELL",
                    "portfolio_kind": portfolio,
                    "scenario": scenario,
                    "execution_allowed": False,
                    "held_risk_state": "",
                    "held_risk_advisory_action": "",
                    "held_risk_reason_codes": "",
                },
            ]
        )
    comparison_path = packet / "marked_official_advisory_comparison.csv"
    pd.DataFrame(comparison_rows).to_csv(comparison_path, index=False)
    scenario_summary = {
        f"{portfolio}:{scenario}": {
            "advisory_cash_weight": 1.0 - (0.61 if changed_weight else 0.60),
            "one_way_turnover_vs_marked": 0.60,
            "risk_watch_promotion_allowed": False,
            "proposed_new_entry_without_risk_watch_count": 1,
            "incremental_buy_risk_review_conflict_count": 0,
        }
        for portfolio, scenario in SCENARIOS
    }
    selector = {
        "schema_version": "run287-current-selector-no-write-v1",
        "status": "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED",
        "valuation_price_cutoff_date": as_of,
        "pinned_policy_commit": POLICY,
        "scenario_summary": scenario_summary,
        "selector_no_write_passed": True,
        "execution_allowed": False,
        "target_book_generation_allowed": False,
        "target_book_file_written": False,
        "target_books_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "review_gate": {"portfolio_transition_promotion_allowed": False},
        "source_inputs": {
            "selector_contract_manifest": {"sha256": SELECTOR_CONTRACT}
        },
        "outputs": {
            "marked_official_advisory_comparison": fingerprint(comparison_path)
        },
    }
    selector_path = packet / "manifest.json"
    selector_path.write_text(json.dumps(selector, indent=2), encoding="utf-8")

    risk_path = packet / "candidate_risk_watch.csv"
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "as_of_date": as_of,
                "risk_state": "WATCH",
                "advisory_action": "REVIEW_BEFORE_INCREMENTAL_BUY",
                "reason_codes": "volatility_spike",
                "price_exact_asof": True,
                "history_observations": 340,
                "return_1d": -0.04,
                "spy_excess_return_1d": -0.03,
                "return_21d": 0.02,
                "spy_excess_return_21d": 0.01,
                "drawdown_63d": -0.12,
                "volatility_ratio_21d_126d": 1.5,
                "idiosyncratic_shock": False,
                "opening_gap_shock": False,
                "trend_damage": False,
                "drawdown_damage": False,
                "volatility_spike": True,
                "data_reason": "",
                "forward_outcome_status": "UNRESOLVED",
                "normal_state_is_not_alpha_evidence": True,
                "portfolio_transition_allowed": False,
                "orders_generated": False,
                "target_books_mutated": False,
                "selector_weights_changed": False,
                "cash_policy_changed": False,
                "production_activation_allowed": False,
                "live_trading_enabled": False,
            }
        ]
    ).to_csv(risk_path, index=False)
    risk_summary = {
        "schema_version": "run287-candidate-risk-watch-v1",
        "status": "READY_CANDIDATE_RISK_REVIEW_ONLY",
        "candidate_risk_watch_passed": True,
        "as_of_date": as_of,
        "candidate_count": 1,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "historical_cagr_mdd_evidence_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "interpretation": {"portfolio_transition_allowed": False},
        "source_inputs": {
            "base_contract": {"sha256": HOLDING_CONTRACT},
            "candidate_contract": {"sha256": CANDIDATE_CONTRACT},
        },
        "outputs": {"candidate_risk_watch": fingerprint(risk_path)},
    }
    summary_path = packet / "summary.json"
    summary_path.write_text(json.dumps(risk_summary, indent=2), encoding="utf-8")
    return selector_path, summary_path


def args_for(
    selector: Path,
    risk: Path,
    output: Path,
    as_of: str,
    contract_hash: str,
) -> argparse.Namespace:
    return argparse.Namespace(
        selector_manifest=str(selector),
        expected_selector_sha256=sha256_file(selector),
        candidate_risk_summary=str(risk),
        expected_candidate_risk_sha256=sha256_file(risk),
        discover_root="",
        allow_missing=False,
        valuation_date=as_of,
        contract="docs/run287_decision_observation_archive_contract.json",
        expected_contract_sha256=contract_hash,
        output_dir=str(output),
    )


def main() -> None:
    contract = ROOT / "docs" / "run287_decision_observation_archive_contract.json"
    contract_hash = sha256_file(contract)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        output = root / "archive"
        selector, risk = write_packet(root, "2026-07-13")
        first = build(args_for(selector, risk, output, "2026-07-13", contract_hash))
        assert first["status"] == READY_STATUS, first
        assert first["appended_counts"] == {
            "decision": 1,
            "scenario": 3,
            "position": 6,
            "candidate_risk": 1,
        }
        assert first["distinct_decision_week_count"] == 1
        assert first["early_stability_review_ready"] is False
        assert first["archive_may_promote"] is False
        assert first["orders_generated"] is False

        second = build(args_for(selector, risk, output, "2026-07-13", contract_hash))
        assert second["status"] == READY_STATUS
        assert second["appended_counts"] == {
            "decision": 0,
            "scenario": 0,
            "position": 0,
            "candidate_risk": 0,
        }

        future_selector, future_risk = write_packet(root, "2026-07-20")
        future = build(
            args_for(future_selector, future_risk, output, "2026-07-20", contract_hash)
        )
        assert future["status"] == READY_STATUS
        assert future["distinct_decision_date_count"] == 2
        assert future["distinct_decision_week_count"] == 2
        assert future["history_counts"]["position"] == 12

        old_selector, old_risk = write_packet(root, "2026-07-06")
        old = build(args_for(old_selector, old_risk, output, "2026-07-06", contract_hash))
        assert old["status"] == BLOCKED_STATUS
        assert any("out-of-order observation" in item for item in old["contract_failures"])

        conflict_output = root / "conflict_archive"
        clean_selector, clean_risk = write_packet(root / "clean", "2026-07-13")
        assert build(
            args_for(clean_selector, clean_risk, conflict_output, "2026-07-13", contract_hash)
        )["status"] == READY_STATUS
        changed_selector, changed_risk = write_packet(
            root / "changed", "2026-07-13", changed_weight=True
        )
        conflict = build(
            args_for(
                changed_selector,
                changed_risk,
                conflict_output,
                "2026-07-13",
                contract_hash,
            )
        )
        assert conflict["status"] == BLOCKED_STATUS
        assert any("same-date decision observation changed" in item for item in conflict["contract_failures"])

        missing_output = root / "missing_archive"
        missing_args = argparse.Namespace(
            selector_manifest=None,
            expected_selector_sha256="",
            candidate_risk_summary=None,
            expected_candidate_risk_sha256="",
            discover_root=str(root / "does_not_exist"),
            allow_missing=True,
            valuation_date="2026-07-13",
            contract="docs/run287_decision_observation_archive_contract.json",
            expected_contract_sha256=contract_hash,
            output_dir=str(missing_output),
        )
        missing = build(missing_args)
        assert missing["status"] == SKIPPED_STATUS
        assert (missing_output / "last_ingestion.json").exists()
        assert not (missing_output / "manifest.json").exists()

    print("run287_decision_observation_archive_smoke: PASS")


if __name__ == "__main__":
    main()
