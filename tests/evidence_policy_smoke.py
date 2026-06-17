#!/usr/bin/env python3
"""Smoke tests for evidence tier classification."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.evidence_policy import TIER0, TIER1, TIER2, TIER3, TIER4, classify_evidence, write_outputs  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def seed_run(
    root: Path,
    *,
    years: float = 7.05,
    valid_for_production: bool = False,
    data_ready: bool = True,
    universe_count: int = 650,
    target_pass: bool = False,
    strengthened_pass: bool = False,
    cash_trap_false: bool | None = None,
) -> None:
    portfolios = {}
    for portfolio in ("main", "concentrated"):
        row = {
            "portfolio": portfolio,
            "status": "completed",
            "official_metric_mode": "broker_ledger_next_close",
            "valid_for_production": valid_for_production,
            "target_pass": target_pass,
            "strengthened_pass": strengthened_pass,
            "cagr": 0.36 if portfolio == "main" else 0.51,
            "max_dd": -0.22,
            "years": years,
            "broker_ledger_actual_trading_days": int(years * 252),
            "broker_ledger_window_gate": {
                "status": "ok" if valid_for_production else "invalid_window",
                "valid": valid_for_production,
                "years": years,
                "actual_trading_days": int(years * 252),
                "reasons": [] if valid_for_production else ["broker_ledger_years_below_8"],
            },
        }
        portfolios[portfolio] = row
        write_json(
            root / "broker_replay" / portfolio / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "valid_for_production": valid_for_production,
                "years": years,
                "days": int(years * 252),
                "cagr": row["cagr"],
                "max_dd": row["max_dd"],
            },
        )
    write_json(
        root / "account_evaluation" / "official_metrics.json",
        {
            "official_metric_mode": "broker_ledger_next_close",
            "production_target_pass": target_pass,
            "strengthened_pass": strengthened_pass,
            "portfolios": portfolios,
        },
    )
    write_json(
        root / "data_readiness" / "summary.json",
        {
            "status": "ready" if data_ready else "blocked",
            "ready_for_policy_replay": data_ready,
            "ready_for_fullrun": data_ready,
            "free_data_coverage": {"known_gaps": []},
        },
    )
    write_json(
        root / "universe_health" / "universe_source_audit.json",
        {
            "status": "ready" if universe_count >= 400 else "INVALID_UNIVERSE",
            "promotion_allowed": universe_count >= 400,
            "r1000_base_count": universe_count,
            "min_r1000_base": 400,
            "primary_universe_source": "current_constituents_proxy",
        },
    )
    if cash_trap_false is not None:
        write_json(root / "cash_reentry_quality" / "summary.json", {"status": "completed", "cash_trap_flag": not cash_trap_false, "cash_trap_rows": 0 if cash_trap_false else 3})


def seed_daily_user_current(root: Path) -> Path:
    out = root / "user_current"
    write_csv(out / "01_current_holdings.csv", "portfolio,ticker,current_weight\nmain,AAA,0.10\n")
    write_csv(out / "02_target_weights.csv", "portfolio,ticker,target_weight\nmain,AAA,0.10\n")
    write_csv(out / "03_order_preview.csv", "portfolio,ticker,action\nmain,AAA,HOLD\n")
    write_json(
        out / "08_rebalance_decision.json",
        {
            "review_only": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
            "canonical_production_sync": False,
            "human_approval_required": True,
        },
    )
    write_json(out / "09_daily_output_contract_summary.json", {"current_snapshot_used_for_order_preview": True, "live_trading_enabled": False, "production_mutation_allowed": False, "human_approval_required": True})
    return out


def test_dirty_7y_is_tier0() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_run(root, data_ready=False, universe_count=259)
        payload = classify_evidence(root)
        assert payload["tier"] == TIER0
        assert payload["research_ab_allowed"] is False
        assert any("data_readiness" in item for item in payload["tier0_blockers"])
        assert any("universe_starved" in item for item in payload["tier0_blockers"])


def test_clean_7y_is_research_tier1_not_do_not_use() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_run(root, years=7.05, valid_for_production=False)
        payload = classify_evidence(root)
        assert payload["tier"] == TIER1
        assert payload["evidence_label"] == "research_7y"
        assert payload["research_ab_allowed"] is True
        assert payload["promotion_allowed"] is False


def test_pre_broker_substrate_gate_block_forces_tier0() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_run(root, years=7.05, valid_for_production=False)
        write_json(
            root / "pre_broker_substrate_gate" / "summary.json",
            {
                "status": "blocked",
                "broker_replay_allowed": False,
                "evidence_tier_when_blocked": "0_do_not_use",
                "blockers": ["universe_health_promotion_not_allowed", "data_readiness_not_ready_for_policy_replay"],
                "recovery": {
                    "fallback_available": True,
                    "recommended_recovery_source": "committed_static_IWB_seed",
                    "recommended_recovery_reason": "static seed is available above floor",
                    "recovery_action": "repair_universe_from_fallback",
                },
            },
        )
        payload = classify_evidence(root)
        assert payload["tier"] == TIER0
        assert payload["research_ab_allowed"] is False
        assert payload["pre_broker_substrate_gate_pass"] is False
        assert "pre_broker_substrate_gate_blocked" in payload["tier0_blockers"]
        assert "pre_broker:universe_health_promotion_not_allowed" in payload["tier0_blockers"]
        assert payload["pre_broker_substrate_gate_recovery"]["recommended_recovery_source"] == "committed_static_IWB_seed"
        assert payload["pre_broker_substrate_gate_recovery"]["recovery_action"] == "repair_universe_from_fallback"
        assert Path(payload["source_files"]["pre_broker_substrate_gate"]).name == "summary.json"
        assert Path(payload["source_files"]["pre_broker_substrate_gate"]).parent.name == "pre_broker_substrate_gate"
        out = root / "out"
        write_outputs(payload, out)
        report = (out / "report.md").read_text(encoding="utf-8")
        assert "## Pre-Broker Recovery" in report
        assert "recommended_recovery_source: `committed_static_IWB_seed`" in report


def test_pre_broker_substrate_gate_pass_preserves_clean_7y_tier1() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_run(root, years=7.05, valid_for_production=False)
        write_json(
            root / "pre_broker_substrate_gate" / "summary.json",
            {
                "status": "pass",
                "broker_replay_allowed": True,
                "blockers": [],
            },
        )
        payload = classify_evidence(root)
        assert payload["tier"] == TIER1
        assert payload["research_ab_allowed"] is True
        assert payload["pre_broker_substrate_gate_pass"] is True


def test_clean_7y_daily_cash_false_is_tier2() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_run(root, cash_trap_false=True)
        user_current = seed_daily_user_current(root)
        payload = classify_evidence(root, user_current_dir=user_current)
        assert payload["tier"] == TIER2
        assert payload["ready_for_human_review_allowed"] is True
        assert payload["promotion_allowed"] is False


def test_clean_7y_with_proxy_10y_robustness_is_tier3() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_run(root, cash_trap_false=True)
        write_json(root / "evidence_policy" / "proxy_10y_robustness.json", {"proxy_10y_robustness_pass": True, "evidence_label": "proxy_10y"})
        payload = classify_evidence(root)
        assert payload["tier"] == TIER3
        assert payload["ready_for_human_review_allowed"] is True
        assert payload["promotion_allowed"] is False


def test_8y_targets_and_cash_pass_is_tier4() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_run(root, years=8.15, valid_for_production=True, target_pass=True, strengthened_pass=True, cash_trap_false=True)
        payload = classify_evidence(root)
        assert payload["tier"] == TIER4
        assert payload["promotion_allowed"] is True
        assert payload["requires_human_approval"] is True
        out = root / "out"
        write_outputs(payload, out)
        assert (out / "evidence_status.json").exists()
        assert "Clean 7-year broker-ledger evidence" in (out / "report.md").read_text(encoding="utf-8")


if __name__ == "__main__":
    test_dirty_7y_is_tier0()
    test_clean_7y_is_research_tier1_not_do_not_use()
    test_pre_broker_substrate_gate_block_forces_tier0()
    test_pre_broker_substrate_gate_pass_preserves_clean_7y_tier1()
    test_clean_7y_daily_cash_false_is_tier2()
    test_clean_7y_with_proxy_10y_robustness_is_tier3()
    test_8y_targets_and_cash_pass_is_tier4()
    print("evidence_policy_smoke: PASS")
