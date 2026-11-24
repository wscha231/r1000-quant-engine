#!/usr/bin/env python3
"""Read-only Run287 chronological gap diagnostics, without provider requests."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.run287_paper_gap_preflight import assess

A = "a" * 64
B = "b" * 64
C = "c" * 64


def receipt() -> dict:
    return {
        "schema_version": "run287-paper-immutable-head-selection-v1",
        "status": "VERIFIED_LINEAR_IMMUTABLE_PAPER_HEAD_SELECTED",
        "heads_root": "/tmp/verified/heads",
        "immutable_head_count": 3,
        "root_snapshot_hash": A,
        "terminal_snapshot_hash": C,
        "selected_snapshot_hash": C,
        "selected_head_dir": "/tmp/verified/heads/" + C,
        "selected_as_of_date": "2026-07-27",
        "chain_snapshot_hashes": [A, B, C],
    }


def assess_with(**kwargs):
    values = dict(selection=receipt(), remote_head=C, requested_session="2026-07-28",
                  completed_sessions=["2026-07-28"], durable_ready=True)
    values.update(kwargs)
    return assess(**values)


def refuses(**kwargs):
    try:
        assess_with(**kwargs)
    except (TypeError, ValueError):
        return
    raise AssertionError("invalid inputs must fail closed")


def run() -> None:
    single = assess_with()
    assert single["status"] == "READY_EXACT_SUCCESSOR"
    assert single["next_missing_session"] == "2026-07-28"
    assert single["missing_nyse_session_count"] == 1
    assert single["paper_ledger_mutated"] is False
    assert single["trade_authorization_granted"] is False
    assert single["owner_scope_attestation_verified"] is False
    assert single["catchup_evidence_admitted"] is False
    gap = assess_with(requested_session="2026-11-19", completed_sessions=[
        "2026-07-28", "2026-07-29", "2026-07-30", "2026-11-19"])
    assert gap["status"] == "BLOCKED_SESSION_GAP"
    assert gap["next_missing_session"] == "2026-07-28"
    assert gap["missing_nyse_session_count"] == 4
    assert assess_with(requested_session="2026-07-27", completed_sessions=[])["status"] == "ALREADY_AT_REQUESTED_SESSION"
    assert assess_with(requested_session="2026-07-24", completed_sessions=[])["status"] == "BLOCKED_REQUEST_BEFORE_PAPER"
    refuses(durable_ready=False)
    refuses(remote_head=B)
    refuses(selection=None)
    refuses(selection={**receipt(), "status": "UNVERIFIED"})
    refuses(selection={**receipt(), "immutable_head_count": True})
    refuses(selection={**receipt(), "chain_snapshot_hashes": [A, C, C]})
    refuses(selection={**receipt(), "selected_as_of_date": "2026-02-30"})
    refuses(selection={**receipt(), "selected_head_dir": "/tmp/attacker"})
    refuses(selection={**receipt(), "invented": True})
    refuses(requested_session="2026-11-19", completed_sessions=["2026-07-29", "2026-07-28", "2026-11-19"])
    refuses(requested_session="2026-11-19", completed_sessions=["2026-07-28"])
    refuses(requested_session="2026-11-19", completed_sessions=["2026-07-28", "2026-07-28", "2026-11-19"])
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)
        receipt_path = path / "selection.json"
        out = path / "out.json"
        receipt_path.write_text(json.dumps({**receipt(), "selected_as_of_date": "2026-02-30"}))
        proc = subprocess.run([sys.executable, str(ROOT / "tools/run287_paper_gap_preflight.py"),
            "--selection", str(receipt_path), "--requested-session", "2026-07-28",
            "--remote-terminal-sha256", C, "--durable-ready", "yes", "--output", str(out)],
            capture_output=True, text=True, check=False)
        assert proc.returncode == 2, proc.stderr
        assert json.loads(out.read_text())["status"] == "BLOCKED_UNVERIFIED_PAPER_FRONTIER_OR_CALENDAR"
    workflow = ROOT / ".github/workflows/daily_operating_selection_refresh.yml"
    if workflow.is_file():
        text = workflow.read_text(encoding="utf-8")
        marker = "- name: Preflight verified paper frontier before daily price refresh"
        assert text.count(marker) == 1
        assert text.index("- name: Restore persistent data and operating outputs") < text.index(marker)
        assert text.index(marker) < text.index("- name: Refresh current price cache")
        section = text[text.index(marker):text.index("- name: Enforce durable Drive for chronological catch-up")]
        assert "steps.market.outputs.catchup_mode != 'yes'" in section
        assert "--remote-terminal-sha256" in section
        assert "--durable-ready" in section
        assert "--selection" in section
        assert "run287_paper_gap_preflight.py" in section
        assert "--output outputs/daily_operating_selection_refresh/paper_gap_preflight.json" in section
    print("run287_paper_gap_preflight_smoke: PASS")


if __name__ == "__main__":
    run()
