#!/usr/bin/env python3
"""Focused semantic mission identity and historical PASS boundaries."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from r1000_config import PORTFOLIO_MISSION_TARGETS
from mission_contract import canonical_mission, mission_identity, mission_binding_status
from tools.run287_promotion_gate import DEFAULT_CONTRACT, DEFAULT_STATE, DEFAULT_EVIDENCE, evaluate_gate
from tools import run_agent_board as board


def main() -> None:
    original = mission_identity(PORTFOLIO_MISSION_TARGETS)
    other = copy.deepcopy(PORTFOLIO_MISSION_TARGETS)
    other["main"]["cagr"] = 0.36
    assert original["mission_contract_sha256"] != mission_identity(other)["mission_contract_sha256"]
    assert original == mission_identity({**PORTFOLIO_MISSION_TARGETS})
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = root / "r1000_config.py"
        config.write_text("PORTFOLIO_MISSION_TARGETS = " + repr(PORTFOLIO_MISSION_TARGETS) + "\n", encoding="utf-8")
        previous = board.REPO_ROOT
        try:
            board.REPO_ROOT = root
            before = board.mission_targets()
            config.write_text(config.read_text(encoding="utf-8") + "UNRELATED_SETTING = 99\n", encoding="utf-8")
            after = board.mission_targets()
            assert before["source_sha256"] != after["source_sha256"]
            assert before["mission_contract_sha256"] == after["mission_contract_sha256"]
        finally:
            board.REPO_ROOT = previous
    assert canonical_mission(PORTFOLIO_MISSION_TARGETS)["targets"]["main"]["cagr_min"] == 0.35
    assert mission_binding_status({"target_pass": True}, original) == "historical_or_unbound_target_contract"
    assert mission_binding_status({**original, "target_type": "diagnostic_interim", "target_pass": True}, original) == "historical_or_unbound_target_contract"
    for invalid in (float("nan"), float("inf"), True):
        candidate = copy.deepcopy(other)
        candidate["main"]["cagr"] = invalid
        try:
            mission_identity(candidate)
            assert False, "invalid mission value was accepted"
        except ValueError:
            pass

    contract = json.loads(DEFAULT_CONTRACT.read_text())
    state = json.loads(DEFAULT_STATE.read_text())
    evidence = json.loads(DEFAULT_EVIDENCE.read_text())
    actual = evaluate_gate(contract, state, evidence)
    assert actual["historical_gate"]["passed"] is False
    assert actual["historical_numeric_mission_pass"] is False
    assert actual["historical_target_contract_status"] == "historical_or_unbound_target_contract"
    forged = copy.deepcopy(evidence)
    forged["historical"]["full_pass"] = True
    assert evaluate_gate(contract, state, forged)["historical_gate"]["checks"]["full_pass"] is False
    forged["historical"].update(original)
    assert evaluate_gate(contract, state, forged)["historical_gate"]["checks"]["full_pass"] is False
    print("mission_contract_smoke: PASS")


if __name__ == "__main__":
    main()
