#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "select_daily_autolearning_source.py"
WORKFLOW = ROOT / ".github" / "workflows" / "daily_autolearning_scan.yml"


def load_tool():
    spec = importlib.util.spec_from_file_location("autolearning_source_gate", TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load source gate")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = load_tool()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_candidate(root: Path, *, as_of: str, mixed_hash: bool) -> Path:
    candidate = root / "candidate"
    (candidate / "reports").mkdir(parents=True)
    scored = candidate / "scored_latest.csv"
    scored.write_text(
        "rebalance_date,ticker,score\n"
        f"{as_of},BBB,0.8\n"
        f"{as_of},AAA,0.9\n",
        encoding="utf-8",
    )
    replay = candidate / "reports" / "candidate_replay_book.csv"
    replay.write_text(
        "rebalance_date,ticker,score\n"
        f"{as_of},AAA,0.9\n",
        encoding="utf-8",
    )
    source_sha = "a" * 40
    source_run_id = "12345"
    generated = f"{as_of}T23:00:00+00:00"
    watermarks = []
    for layer, cadence in (
        ("prices", 3),
        ("macro", 3),
        ("fundamentals", 7),
        ("form4", 5),
        ("13f", 100),
    ):
        watermarks.append(
            {
                "layer": layer,
                "latest_asof": as_of,
                "cadence_days": cadence,
                "status": "ok",
                "stats": {
                    "modified_utc": generated,
                    "sha256": hashlib.sha256(layer.encode()).hexdigest(),
                },
            }
        )
    scored_recorded = "0" * 64 if mixed_hash else sha(scored)
    snapshot = {
        "schema_version": "data-snapshot-manifest-v1",
        "source_run_id": source_run_id,
        "source_commit_sha": source_sha,
        "source_artifact_name": "official-broker-ledger-test-12345",
        "generated_at_utc": generated,
        "watermarks": watermarks,
        "files": [
            {
                "path": "/runner/outputs/scored_latest.csv",
                "sha256": scored_recorded,
            },
            {
                "path": "/runner/outputs/reports/candidate_replay_book.csv",
                "sha256": sha(replay),
            },
        ],
    }
    write_json(
        candidate / "data_freshness_contract" / "data_snapshot_manifest.json",
        snapshot,
    )
    write_json(
        candidate / "data_readiness" / "summary.json",
        {
            "ready_for_policy_replay": True,
            "effective_latest_target_date": as_of,
            "latest_observable_close_date": as_of,
        },
    )
    write_json(
        candidate / "universe_health" / "summary.json",
        {
            "status": "pass",
            "generated_at_utc": generated,
            "fallback_used": False,
            "primary_universe_source": "pit_membership",
            "scored_latest": {"max_date": as_of},
        },
    )
    write_json(
        candidate / "patch_application_manifest.json",
        {"run_id": source_run_id, "commit_sha": source_sha},
    )
    return candidate


def build_inventory(path: Path, *, conclusion: str, newer: bool) -> Path:
    source_sha = "a" * 40
    artifact = {
        "id": 77,
        "name": "official-broker-ledger-test-12345",
        "digest": "sha256:" + "b" * 64,
        "expired": False,
        "run_id": 12345,
        "head_sha": source_sha,
        "head_branch": "master",
    }
    upstream_time = "2026-07-28T01:00:00Z" if newer else "2026-07-27T22:00:00Z"
    workflows = {}
    for key in gate.UPSTREAM_WORKFLOWS:
        workflows[key] = {
            "run_id": 20000 + len(workflows),
            "head_sha": source_sha,
            "head_branch": "master",
            "conclusion": "success",
            "updated_at": upstream_time,
            "artifacts": [
                {
                    "id": 100 + len(workflows),
                    "name": f"{key}-artifact",
                    "digest": "sha256:" + hashlib.sha256(key.encode()).hexdigest(),
                    "expired": False,
                }
            ],
        }
    write_json(
        path,
        {
            "source_run": {
                "run_id": 12345,
                "head_sha": source_sha,
                "head_branch": "master",
                "conclusion": conclusion,
                "updated_at": "2026-07-27T23:00:00Z",
                "artifacts": [artifact],
            },
            "workflow_runs": workflows,
            "accepted_artifacts": [
                {
                    "id": 8919482287,
                    "name": "accepted-paper-catchup-2026-07-24-30975268034",
                    "digest": "sha256:" + "c" * 64,
                    "expired": False,
                    "run_id": 30975268034,
                    "head_sha": "d" * 40,
                    "head_branch": "master",
                    "workflow_conclusion": "success",
                    "workflow_path": ".github/workflows/daily_operating_selection_refresh.yml",
                }
            ],
        },
    )
    return path


def args(candidate: Path, inventory: Path, expected: str) -> Namespace:
    return Namespace(
        candidate_run=str(candidate),
        expected_session_date=expected,
        current_code_sha="e" * 40,
        github_repository="wscha231/r1000-quant-engine",
        github_token="",
        github_inventory=str(inventory),
        checked_at_utc="2026-08-22T06:00:00Z",
        output_dir="unused",
    )


def test_mixed_stale_source_fails_closed_and_is_deterministic() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = build_candidate(root, as_of="2026-06-24", mixed_hash=True)
        inventory = build_inventory(root / "inventory.json", conclusion="failure", newer=True)
        gate.git_is_ancestor = lambda older, current: True
        first = gate.evaluate(args(candidate, inventory, "2026-08-21"))
        second = gate.evaluate(args(candidate, inventory, "2026-08-21"))
        assert first == second
        assert first["ready_for_diagnostics"] is False
        assert first["status"] == "BLOCKED_STALE_OR_MIXED_INPUT"
        codes = {item["code"] for item in first["blockers"]}
        assert "SOURCE_RUN_NOT_SUCCESSFUL" in codes
        assert "CANDIDATE_BUNDLE_HASH_MISMATCH" in codes
        assert "INPUT_SESSION_MISMATCH" in codes
        assert "INPUT_STALE" in codes
        assert "NEWER_UPSTREAM_NOT_BOUND" in codes
        assert "CHRONOLOGICAL_GAP" in codes
        assert first["chronological_cursor"]["processed_through_date"] == "2026-07-24"
        assert first["chronological_cursor"]["earliest_unprocessed_session"] == "2026-07-27"
        assert all(value is False for value in first["safety"].values())


def test_current_hash_locked_source_can_reach_read_only_diagnostics() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = build_candidate(root, as_of="2026-07-27", mixed_hash=False)
        inventory = build_inventory(root / "inventory.json", conclusion="success", newer=False)
        gate.git_is_ancestor = lambda older, current: True
        payload = gate.evaluate(args(candidate, inventory, "2026-07-27"))
        assert payload["ready_for_diagnostics"] is True, payload["blockers"]
        assert payload["status"] == "READY_TRUSTED_CURRENT_BUNDLE"
        assert payload["blockers"] == []
        assert payload["safety"]["target_books_mutated"] is False
        assert payload["safety"]["paper_account_mutated"] is False
        assert payload["safety"]["promotion_allowed"] is False


def test_workflow_gates_every_diagnostic_before_execution() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for token in (
        "permissions:\n  actions: read\n  contents: read",
        "name: Resolve completed NYSE session",
        "id: source_gate",
        "python tools/select_daily_autolearning_source.py",
        "if: steps.source_gate.outputs.ready == 'yes'",
        "outputs/daily_autolearning_source_selection/",
    ):
        assert token in text, token
    source_index = text.index("id: source_gate")
    diagnostics_index = text.index("name: Run winner lifecycle diagnostics")
    assert source_index < diagnostics_index
    assert "contents: write" not in text
    assert "git push" not in text


def main() -> int:
    test_mixed_stale_source_fails_closed_and_is_deterministic()
    test_current_hash_locked_source_can_reach_read_only_diagnostics()
    test_workflow_gates_every_diagnostic_before_execution()
    print("daily_autolearning_source_selection_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
