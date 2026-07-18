#!/usr/bin/env python3
"""Synthetic smoke for the hash-pinned Run287 selector provenance audit."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_run287_selector_provenance import (  # noqa: E402
    BLOCKED_STATUS,
    READY_STATUS,
    run_audit,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, lineterminator="\n")


def output_record(path: Path) -> dict:
    return {"path": str(path), "sha256": sha256(path)}


def source_record(path: Path) -> dict:
    return {
        "path": str(path),
        "sha256": sha256(path),
        "exists": True,
        "hash_matches": True,
    }


def build_fixture(base: Path) -> Path:
    decision_time = "2026-07-14T05:00:00+00:00"
    available = "2026-07-13T23:59:59+00:00"
    dynamic = base / "dynamic"
    manifests = {
        "decision_manifest": {"feature_available_from": available},
        "score_stack_manifest": {"feature_available_from": available},
        "price_manifest": {"score_available_from": "2026-07-14T04:55:00+00:00"},
        "macro_manifest": {"macro_available_from": "2026-07-13T20:15:00+00:00"},
        "holding_watch_summary": {"available_from": "2026-07-13T20:30:00+00:00"},
        "crisis_manifest": {"macro_available_from": "2026-07-13T20:15:00+00:00"},
        "soxx_manifest": {"valuation_price_cutoff_date": "2026-07-13"},
    }
    source_inputs: dict[str, dict] = {}
    for label, payload in manifests.items():
        path = dynamic / f"{label}.json"
        write_json(path, payload)
        source_inputs[label] = source_record(path)

    selector_dir = base / "selector"
    comparison_path = selector_dir / "comparison.csv"
    projection_path = selector_dir / "projection.csv"
    stages_path = selector_dir / "stages.csv"
    comparison = [
        {
            "portfolio_kind": "main",
            "scenario": "strict_registered_current",
            "ticker": "DIV",
            "marked_weight": 0.0,
            "official_prior_weight": 0.0,
            "advisory_weight": 0.8,
            "delta_vs_marked": 0.8,
            "delta_vs_official": 0.8,
            "action_vs_marked": "BUY",
            "action_vs_official": "BUY",
        },
        {
            "portfolio_kind": "main",
            "scenario": "strict_registered_current",
            "ticker": "CASH",
            "marked_weight": 1.0,
            "official_prior_weight": 1.0,
            "advisory_weight": 0.2,
            "delta_vs_marked": -0.8,
            "delta_vs_official": -0.8,
            "action_vs_marked": "SELL",
            "action_vs_official": "SELL",
        },
        {
            "portfolio_kind": "concentrated",
            "scenario": "strict_registered_current",
            "ticker": "OPCO",
            "marked_weight": 0.0,
            "official_prior_weight": 0.0,
            "advisory_weight": 0.8,
            "delta_vs_marked": 0.8,
            "delta_vs_official": 0.8,
            "action_vs_marked": "BUY",
            "action_vs_official": "BUY",
        },
        {
            "portfolio_kind": "concentrated",
            "scenario": "strict_registered_current",
            "ticker": "CASH",
            "marked_weight": 1.0,
            "official_prior_weight": 1.0,
            "advisory_weight": 0.2,
            "delta_vs_marked": -0.8,
            "delta_vs_official": -0.8,
            "action_vs_marked": "SELL",
            "action_vs_official": "SELL",
        },
    ]
    write_csv(comparison_path, comparison)
    write_csv(
        projection_path,
        [
            {
                "portfolio_kind": row["portfolio_kind"],
                "scenario": row["scenario"],
                "ticker": row["ticker"],
                "advisory_weight": row["advisory_weight"],
            }
            for row in comparison
        ],
    )
    write_csv(
        stages_path,
        [
            {
                "portfolio_kind": "main",
                "scenario": "strict_registered_current",
                "stage_sequence": 1,
                "stage_name": "assign_weights",
                "ticker": "DIV",
                "before_weight": 0.0,
                "after_weight": 0.8,
                "weight_delta": 0.8,
            },
            {
                "portfolio_kind": "concentrated",
                "scenario": "strict_registered_current",
                "stage_sequence": 1,
                "stage_name": "assign_weights",
                "ticker": "OPCO",
                "before_weight": 0.0,
                "after_weight": 0.8,
                "weight_delta": 0.8,
            },
        ],
    )
    selector_manifest_path = selector_dir / "manifest.json"
    write_json(
        selector_manifest_path,
        {
            "status": "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED",
            "valuation_price_cutoff_date": "2026-07-13",
            "generated_at_utc": "2026-07-14T02:00:00+00:00",
            "pinned_policy_commit": "fixture-policy",
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
            "scenario_summary": {
                "concentrated:strict_registered_current": {},
                "main:strict_registered_current": {},
            },
            "source_inputs": source_inputs,
            "outputs": {
                "marked_official_advisory_comparison": output_record(comparison_path),
                "advisory_policy_projection": output_record(projection_path),
                "advisory_policy_stage_audit": output_record(stages_path),
            },
        },
    )

    archive_dir = base / "archive"
    archive_positions = archive_dir / "latest_positions.csv"
    write_csv(archive_positions, comparison)
    archive_manifest_path = archive_dir / "manifest.json"
    write_json(
        archive_manifest_path,
        {
            "status": "READY_DECISION_OBSERVATION_ARCHIVE_REVIEW_ONLY",
            "history_counts": {"position": 4},
            "outputs": {"latest_positions": output_record(archive_positions)},
        },
    )

    funnel_dir = base / "funnel"
    queue_path = funnel_dir / "queue.csv"
    write_csv(queue_path, [{"ticker": "DIV"}])
    funnel_manifest_path = funnel_dir / "manifest.json"
    write_json(
        funnel_manifest_path,
        {
            "status": "READY_RESEARCH_ONLY_CANDIDATE_EVALUATION",
            "outputs": {"selector_reconciliation_queue": output_record(queue_path)},
        },
    )

    operating_dir = base / "operating"
    main_book = operating_dir / "main.csv"
    concentrated_book = operating_dir / "concentrated.csv"
    write_csv(main_book, [{"rebalance_date": "2026-07-13", "ticker": "OPMA", "weight": 1.0}])
    write_csv(
        concentrated_book,
        [{"rebalance_date": "2026-07-13", "ticker": "OPCO", "weight": 1.0}],
    )
    operating_summary_path = operating_dir / "summary.json"
    write_json(
        operating_summary_path,
        {"status": "completed", "generated_at_utc": "2026-07-14T01:00:00+00:00"},
    )

    paper_dir = base / "paper"
    paper_portfolios: dict[str, dict[str, Path]] = {}
    for kind, ticker, book in (
        ("main", "OPMA", main_book),
        ("concentrated", "OPCO", concentrated_book),
    ):
        portfolio_dir = paper_dir / kind
        positions_path = portfolio_dir / "positions.csv"
        account_path = portfolio_dir / "account.json"
        manifest_path = portfolio_dir / "manifest.json"
        write_csv(
            positions_path,
            [
                {
                    "as_of_date": "2026-07-13",
                    "ticker": ticker,
                    "shares": 3.0,
                    "price": 33.0,
                    "weight": 0.99,
                }
            ],
        )
        write_json(
            account_path,
            {
                "as_of_date": "2026-07-13",
                "equity_usd": 100.0,
                "cash_usd": 1.0,
                "cash_weight": 0.01,
            },
        )
        write_json(
            manifest_path,
            {
                "as_of_date": "2026-07-13",
                "target_effective_date": "2026-07-13",
                "target_sha256": sha256(book),
                "seeded_this_run": True,
                "fill_count": 0,
                "pending_order_count": 0,
                "rejection_count": 0,
                "event_sequence": 0,
            },
        )
        paper_portfolios[kind] = {
            "manifest": manifest_path,
            "account": account_path,
            "positions": positions_path,
        }
    paper_summary_path = paper_dir / "summary.json"
    write_json(
        paper_summary_path,
        {"status": "completed", "generated_at_utc": "2026-07-14T03:00:00+00:00"},
    )

    source_paths = {
        "selector_manifest": selector_manifest_path,
        "decision_archive_manifest": archive_manifest_path,
        "candidate_funnel_manifest": funnel_manifest_path,
        "operating_summary": operating_summary_path,
        "main_operating_book": main_book,
        "concentrated_operating_book": concentrated_book,
        "paper_summary": paper_summary_path,
        "main_paper_manifest": paper_portfolios["main"]["manifest"],
        "main_account_state": paper_portfolios["main"]["account"],
        "main_positions": paper_portfolios["main"]["positions"],
        "concentrated_paper_manifest": paper_portfolios["concentrated"]["manifest"],
        "concentrated_account_state": paper_portfolios["concentrated"]["account"],
        "concentrated_positions": paper_portfolios["concentrated"]["positions"],
    }
    contract_path = base / "contract.json"
    write_json(
        contract_path,
        {
            "schema_version": "fixture-contract",
            "as_of_date": "2026-07-13",
            "decision_time_utc": decision_time,
            "pinned_policy_commit": "fixture-policy",
            "expected_scenario_keys": [
                "concentrated:strict_registered_current",
                "main:strict_registered_current",
            ],
            "expected_archived_row_count": 4,
            "expected_divergence_tickers": ["DIV"],
            "source_files": {
                key: {"path": str(path), "sha256": sha256(path)}
                for key, path in source_paths.items()
            },
            "reason_codes": [
                "ADVISORY_CREATED_AFTER_OPERATING_NO_WRITE",
                "OPERATING_CREATED_BY_SEPARATE_EARLIER_SELECTOR",
                "PARALLEL_PATH_SELECTION_OVERLAP",
                "NEITHER_CURRENT_PATH_SELECTED",
                "CASH_RECONCILED_SEPARATELY",
            ],
            "divergence_reason_code": "ADVISORY_CREATED_AFTER_OPERATING_NO_WRITE",
            "cash_component_by_stage": {"assign_weights": "initial_unallocated_cash"},
            "tolerances": {
                "selector_weight": 1e-12,
                "weight_conservation": 1e-12,
                "cash_usd": 0.01,
            },
        },
    )
    return contract_path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="run287_selector_provenance_") as raw:
        base = Path(raw)
        contract = build_fixture(base)
        input_hashes = {
            path.relative_to(base).as_posix(): sha256(path)
            for path in base.rglob("*")
            if path.is_file()
        }
        first = run_audit(contract, base / "out1")
        assert first["status"] == READY_STATUS, first
        assert first["coverage"]["archived_selector_row_exact_count"] == 4
        assert first["coverage"]["divergence_reconciled_count"] == 1
        assert first["coverage"]["paper_share_exact_count"] == 2
        assert first["coverage"]["availability_violation_count"] == 0
        assert first["recoverable_implementation_leakage_count"] == 0
        assert not first["target_books_mutated"]
        assert not first["orders_generated"]
        assert not first["fullrun_executed"]

        second = run_audit(contract, base / "out2")
        assert second["status"] == READY_STATUS
        assert first["semantic_output_hashes"] == second["semantic_output_hashes"]

        for path in base.rglob("*"):
            if path.is_file() and "out1" not in path.parts and "out2" not in path.parts:
                key = path.relative_to(base).as_posix()
                assert input_hashes[key] == sha256(path), path

        contract_payload = json.loads(contract.read_text(encoding="utf-8"))
        operating = Path(contract_payload["source_files"]["main_operating_book"]["path"])
        operating.write_text(operating.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        blocked = run_audit(contract, base / "blocked")
        assert blocked["status"] == BLOCKED_STATUS
        assert "source_hash_mismatch:main_operating_book" in blocked["contract_failures"]
    print("run287 selector provenance audit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
