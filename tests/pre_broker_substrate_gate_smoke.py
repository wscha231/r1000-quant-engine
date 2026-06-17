#!/usr/bin/env python3
"""Smoke tests for the pre-broker universe/data substrate gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.check_pre_broker_substrate_gate import classify_pre_broker_substrate, main, write_outputs  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seed_run(root: Path, *, universe_ok: bool = True, data_ok: bool = True) -> None:
    write_json(
        root / "universe_health" / "universe_source_audit.json",
        {
            "status": "pass" if universe_ok else "invalid_universe",
            "verdict_code": "PASS" if universe_ok else "INVALID_UNIVERSE",
            "promotion_allowed": universe_ok,
            "hard_fail_before_expensive_rebuild": not universe_ok,
            "r1000_base_count": 525 if universe_ok else 259,
            "min_r1000_base": 400,
            "primary_universe_source": "current_constituents_proxy" if universe_ok else "missing",
            "fallback_used": False,
            "fallback_available": True,
            "recommended_recovery_source": "none_required" if universe_ok else "committed_static_IWB_seed",
            "recommended_recovery_reason": "universe health already passes" if universe_ok else "static seed is available above floor",
            "recovery_action": "none_required" if universe_ok else "repair_universe_from_fallback",
            "monthly_universe_health_pass": universe_ok,
            "blockers": [] if universe_ok else ["scored R1000 base below floor: 259 < 400"],
        },
    )
    write_json(
        root / "data_readiness" / "summary.json",
        {
            "status": "ok" if data_ok else "blocked",
            "ready_for_policy_replay": data_ok,
            "blockers": [] if data_ok else ["future_available_from_rows_present"],
            "warnings": [],
        },
    )


def test_pre_broker_gate_passes_clean_substrate() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_run(latest)
        payload = classify_pre_broker_substrate(latest)
        assert payload["status"] == "pass", payload
        assert payload["broker_replay_allowed"] is True, payload
        assert payload["blockers"] == [], payload
        write_outputs(payload, Path(tmp) / "out")
        assert (Path(tmp) / "out" / "summary.json").exists()
        assert "broker_replay_allowed: `true`" in (Path(tmp) / "out" / "report.md").read_text(encoding="utf-8")


def test_pre_broker_gate_blocks_starved_universe() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_run(latest, universe_ok=False)
        payload = classify_pre_broker_substrate(latest)
        assert payload["status"] == "blocked", payload
        assert payload["broker_replay_allowed"] is False, payload
        assert "universe_health_promotion_not_allowed" in payload["blockers"], payload
        assert "universe_health_hard_fail_before_expensive_rebuild" in payload["blockers"], payload
        assert any(str(item).startswith("scored_r1000_base_below_floor") for item in payload["blockers"]), payload
        assert payload["evidence_tier_when_blocked"] == "0_do_not_use", payload
        assert payload["universe_health"]["fallback_available"] is True, payload
        assert payload["universe_health"]["recommended_recovery_source"] == "committed_static_IWB_seed", payload
        assert payload["recovery"]["recommended_recovery_source"] == "committed_static_IWB_seed", payload
        assert payload["recovery"]["recovery_action"] == "repair_universe_from_fallback", payload
        write_outputs(payload, Path(tmp) / "out")
        report = (Path(tmp) / "out" / "report.md").read_text(encoding="utf-8")
        assert "## Recovery" in report
        assert "recommended_recovery_source: `committed_static_IWB_seed`" in report


def test_pre_broker_gate_blocks_dirty_data_readiness() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_run(latest, data_ok=False)
        payload = classify_pre_broker_substrate(latest)
        assert payload["status"] == "blocked", payload
        assert "data_readiness_not_ready_for_policy_replay" in payload["blockers"], payload
        assert "data_readiness_blockers_present" in payload["blockers"], payload


def test_pre_broker_gate_strict_exits_nonzero() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        out = Path(tmp) / "out"
        seed_run(latest, universe_ok=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "check_pre_broker_substrate_gate.py",
                "--latest-run",
                str(latest),
                "--output-dir",
                str(out),
                "--strict",
            ]
            assert main() == 2
        finally:
            sys.argv = old_argv
        assert (out / "summary.json").exists()
        payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert payload["broker_replay_allowed"] is False


if __name__ == "__main__":
    test_pre_broker_gate_passes_clean_substrate()
    test_pre_broker_gate_blocks_starved_universe()
    test_pre_broker_gate_blocks_dirty_data_readiness()
    test_pre_broker_gate_strict_exits_nonzero()
    print("pre_broker_substrate_gate_smoke: PASS")
