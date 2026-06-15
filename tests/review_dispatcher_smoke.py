#!/usr/bin/env python3
"""Smoke tests for guarded review workflow dispatch launcher."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_review_dispatcher import APPROVAL_TOKEN, run  # noqa: E402


def write_payloads(path: Path) -> None:
    payloads = [
        {
            "plan_id": "bootstrap_free_data_for_8y_window",
            "workflow_id": "free_data_lake_bootstrap.yml",
            "ref": "master",
            "requires_user_approval": True,
            "production_mutation_allowed": False,
            "inputs": {"latest_run": "cloud_results/full_rebuild/latest_global_alpha_universe", "price_mode": "target_books"},
        },
        {
            "plan_id": "full_rebuild_8y_official_after_data_bootstrap",
            "workflow_id": "full_rebuild_manual.yml",
            "ref": "master",
            "requires_user_approval": True,
            "production_mutation_allowed": False,
            "depends_on_plan_ids": ["bootstrap_free_data_for_8y_window"],
            "inputs": {
                "backtest_years": "8",
                "portfolio_policy": "alphaops_vnext_production",
                "cache_key_suffix": "official-8y-window",
            },
        },
        {
            "plan_id": "ab_conc_bull_floor_stock_min",
            "workflow_id": "full_rebuild_manual.yml",
            "ref": "master",
            "requires_user_approval": True,
            "production_mutation_allowed": False,
            "depends_on_plan_ids": ["full_rebuild_8y_official_after_data_bootstrap"],
            "inputs": {
                "backtest_years": "8",
                "portfolio_policy": "alphaops_vnext_production",
                "cache_key_suffix": "ab_conc_bull_floor_stock_min",
                "experiment_env_json": '{"PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED": "1"}',
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payloads, indent=2), encoding="utf-8")


def base_args(payloads: Path, out: Path, **overrides) -> Namespace:
    values = {
        "payloads": str(payloads),
        "output_dir": str(out),
        "repo": "wscha231/r1000-quant-engine",
        "gh_bin": "gh",
        "only": [],
        "completed_plan_id": [],
        "execute": False,
        "approval_token": "",
    }
    values.update(overrides)
    return Namespace(**values)


def test_review_dispatcher_dry_run_blocks_unmet_ab_dependency() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        payloads = root / "payloads.json"
        write_payloads(payloads)
        out = root / "dispatch"
        summary = run(base_args(payloads, out))
        assert summary["status"] == "dry_run_blocked"
        assert summary["ready_count"] == 1
        assert summary["blocked_count"] == 2
        blocked = [row for row in summary["plan_rows"] if row["status"] == "blocked"]
        assert [row["id"] for row in blocked] == [
            "full_rebuild_8y_official_after_data_bootstrap",
            "ab_conc_bull_floor_stock_min",
        ]
        assert "unmet_dependencies:bootstrap_free_data_for_8y_window" in blocked[0]["errors"]
        assert "unmet_dependencies:full_rebuild_8y_official_after_data_bootstrap" in blocked[1]["errors"]
        commands = (out / "dispatch_commands.sh").read_text(encoding="utf-8")
        assert "gh workflow run free_data_lake_bootstrap.yml" in commands
        assert "blocked: full_rebuild_8y_official_after_data_bootstrap" in commands
        assert "blocked: ab_conc_bull_floor_stock_min" in commands


def test_review_dispatcher_allows_official_rebuild_after_bootstrap_complete() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        payloads = root / "payloads.json"
        write_payloads(payloads)
        out = root / "dispatch"
        summary = run(
            base_args(
                payloads,
                out,
                only=["full_rebuild_8y_official_after_data_bootstrap"],
                completed_plan_id=["bootstrap_free_data_for_8y_window"],
            )
        )
        assert summary["status"] == "dry_run_ready"
        assert summary["ready_count"] == 1
        assert summary["blocked_count"] == 0
        commands = (out / "dispatch_commands.sh").read_text(encoding="utf-8")
        assert "gh workflow run full_rebuild_manual.yml" in commands
        assert "cache_key_suffix=official-8y-window" in commands


def test_review_dispatcher_allows_ab_after_dependency_marked_complete() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        payloads = root / "payloads.json"
        write_payloads(payloads)
        out = root / "dispatch"
        summary = run(
            base_args(
                payloads,
                out,
                only=["ab_conc_bull_floor_stock_min"],
                completed_plan_id=["full_rebuild_8y_official_after_data_bootstrap"],
            )
        )
        assert summary["status"] == "dry_run_ready"
        assert summary["ready_count"] == 1
        assert summary["blocked_count"] == 0
        assert "cache_key_suffix=ab_conc_bull_floor_stock_min" in (out / "dispatch_commands.sh").read_text(encoding="utf-8")


def test_review_dispatcher_execute_requires_approval_token() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        payloads = root / "payloads.json"
        write_payloads(payloads)
        out = root / "dispatch"
        summary = run(
            base_args(
                payloads,
                out,
                only=["bootstrap_free_data_for_8y_window"],
                execute=True,
                approval_token="",
            )
        )
        assert summary["status"] == "refused"
        assert summary["refusal_reason"] == "approval_token_mismatch"
        assert summary["dispatched_count"] == 0
        assert summary["approval_token_required"] == APPROVAL_TOKEN


def test_review_dispatcher_rejects_mutating_payload() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        payloads = root / "payloads.json"
        payloads.write_text(
            json.dumps(
                [
                    {
                        "plan_id": "bad_payload",
                        "workflow_id": "full_rebuild_manual.yml",
                        "requires_user_approval": True,
                        "production_mutation_allowed": True,
                        "inputs": {},
                    }
                ]
            ),
            encoding="utf-8",
        )
        summary = run(base_args(payloads, root / "dispatch"))
        assert summary["status"] == "dry_run_blocked"
        assert summary["blocked_count"] == 1
        assert "production_mutation_allowed_not_false" in summary["plan_rows"][0]["errors"]


def test_review_dispatcher_accepts_empty_payload_file() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        payloads = root / "payloads.json"
        payloads.write_text("[]\n", encoding="utf-8")
        out = root / "dispatch"
        summary = run(base_args(payloads, out))
        assert summary["status"] == "dry_run_ready"
        assert summary["selected_count"] == 0
        assert summary["ready_count"] == 0
        assert summary["blocked_count"] == 0
        assert (out / "dispatch_commands.sh").exists()
        assert (out / "report.md").exists()


if __name__ == "__main__":
    test_review_dispatcher_dry_run_blocks_unmet_ab_dependency()
    test_review_dispatcher_allows_official_rebuild_after_bootstrap_complete()
    test_review_dispatcher_allows_ab_after_dependency_marked_complete()
    test_review_dispatcher_execute_requires_approval_token()
    test_review_dispatcher_rejects_mutating_payload()
    test_review_dispatcher_accepts_empty_payload_file()
    print("review_dispatcher_smoke: PASS")
