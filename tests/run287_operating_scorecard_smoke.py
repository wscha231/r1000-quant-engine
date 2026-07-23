#!/usr/bin/env python3
"""Smoke checks for the canonical private Run287 operating scorecard."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_operating_scorecard import (  # noqa: E402
    build_scorecard,
    load_registry,
    render_report,
    validate_metric_migration,
    verify_canonical_source_bundle,
)
from tools.run287_paper_ledger_integrity import write_integrity_manifest  # noqa: E402
import tools.run287_paper_ledger_integrity as paper_integrity_module  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(
    root: Path,
    *,
    paper: bool = True,
    reset_count: int = 0,
    forged_verified_boolean: bool = False,
) -> Path:
    p6 = root / "p6.json"
    write_json(p6, {
        "rank_stability": {"mean_score_spearman": 0.6, "mean_top_10_overlap": 0.3, "mean_top_30_overlap": 0.4},
        "sector_etf_excess_status": "BLOCKED_MISSING_PINNED_SECTOR_ETF_CACHE",
        "selection_quality_delta": [{"selected_minus_control": 0.01}],
    })
    p6_metrics = root / "p6_metrics.csv"
    pd.DataFrame([{
        "window": "oos", "portfolio": "main", "cohort": "selected", "horizon_sessions": 63,
        "resolved_count": 10, "mean_return": 0.1, "median_return": 0.08,
        "mean_spy_excess": 0.02, "mean_qqq_excess": 0.01, "mean_sector_neutral_excess": 0.03,
    }]).to_csv(p6_metrics, index=False)
    p5 = root / "p5.json"
    portfolio = {
        "control_parity": {"expected": {"cagr": 0.35, "max_dd": -0.25, "sharpe": 1.2,
                                          "trade_count": 5, "total_fees_usd": 10}},
        "holding_statistics": {"completed_lot_count": 5, "median_holding_days": 30,
                               "pct_held_365d_plus": 0, "exit_reentry_churn_63_sessions": 1},
        "sell_taxonomy_counts": {"RISK_EXIT": 2},
        "counterfactual_summary": {"status": "NO_EVENTS"},
        "cost_sensitivity": {
            "25bps": {"control_fees": 10, "control_cagr": 0.35},
            "50bps": {"control_fees": 20, "control_cagr": 0.34},
            "100bps": {"control_fees": 40, "control_cagr": 0.32},
        },
    }
    write_json(p5, {"control_parity_passed": True,
                    "portfolios": {"main": portfolio, "concentrated": portfolio}})
    p4 = root / "p4.json"
    write_json(p4, {"double_count_check_passed": True, "reason_reconciliation_passed": True})
    p4_metrics = root / "p4_metrics.csv"
    pd.DataFrame([
        {"portfolio": name, "mode": "DGS3MO_CARRY", "average_reserve_weight": 0.2,
         "latest_reserve_weight": 0.1, "reserve_return_contribution_usd_vs_broker_cash": 100,
         "cash_interest_accrued_usd": 50, "reserve_turnover_usd": 0, "reserve_fees_usd": 0,
         "delta_cagr_pp_vs_broker_cash": 0.5}
        for name in ("main", "concentrated")
    ]).to_csv(p4_metrics, index=False)
    reasons = root / "reasons.json"
    write_json(reasons, [{"reason_weights": {"capacity_unallocated": 0.2, "crisis_reserve": 0,
                                              "reentry_pending": 0, "data_block_reserve": 0,
                                              "transaction_buffer": 0, "residual_cash": 0}}])
    crisis = root / "crisis.json"
    write_json(crisis, {
        "status": "REJECTED_POLICY_PROMOTION",
        "full_period": {"mdd_delta": 0.02, "cagr_delta": -0.1},
        "state_evaluation": {
            "defense_episode_count": 2, "false_defense_episode_count": 1,
            "cash_trap_snapshot_count": 3, "false_reentry_redefense_count": 1,
            "reentry_recovery_business_days": {
                level: {"median": index + 1} for index, level in enumerate(("25", "50", "75", "95"))
            },
        },
    })
    forward = root / "forward.json"
    write_json(forward, {
        "coverage": {"decision_date_count": 1},
        "review_readiness": {
            "status": "UNDERPOWERED", "review_ready": False,
            "distinct_true_forward_ticker_count": 10,
            "sample_checks": {"decision_week_blocks_21d": {"actual": 0},
                              "decision_week_blocks_63d": {"actual": 0}},
            "cohort_metrics": {"true_forward_arm": {
                horizon: {"completed_count": 0} for horizon in ("21d", "63d", "126d")
            }},
        },
    })
    paper_root = root / "paper"
    paper_path = paper_root / "summary.json"
    integrity_path = paper_root / "snapshot_integrity.json"
    if paper:
        paper_root.mkdir()
        write_json(paper_path, {"integrity": {"account_reset_count": reset_count}, "fill_count": 2})
        if forged_verified_boolean:
            write_json(integrity_path, {"verified": True})
        else:
            write_integrity_manifest(paper_root, as_of_date="2026-07-20")

    files = {
        "p6_selection_summary": (p6, "json", True, "historical", "selection_quality"),
        "p6_selection_metrics": (p6_metrics, "csv", True, "historical", "selection_quality"),
        "p5_hold_exit": (p5, "json", True, "historical", "holding_exit_execution"),
        "p4_reserve_summary": (p4, "json", True, "historical", "reserve"),
        "p4_reserve_metrics": (p4_metrics, "csv", True, "historical", "reserve"),
        "p4_main_reserve_reasons": (reasons, "json", True, "historical", "reserve"),
        "p4_concentrated_reserve_reasons": (reasons, "json", True, "historical", "reserve"),
        "p3_main_crisis": (crisis, "json", True, "historical", "risk_defense_reentry"),
        "p3_concentrated_crisis": (crisis, "json", True, "historical", "risk_defense_reentry"),
        "current_paper_summary": (paper_path, "json", False, "current_paper_execution", "execution_integrity"),
        "current_paper_integrity": (integrity_path, "json", False, "current_paper_execution", "execution_integrity"),
        "true_forward_summary": (forward, "json", True, "true_forward", "forward_evidence"),
    }
    sources = []
    for source_id, (path, fmt, required, lane, section) in files.items():
        sources.append({
            "id": source_id, "evidence_class": lane, "section": section,
            "path": str(path), "format": fmt,
            "expected_sha256": digest(path) if path.exists() else None,
            "as_of_date": "2026-07-10", "metric_mode": "fixture",
            "required": required, "disposition": "FIXTURE_SOURCE",
        })
    registry = root / "registry.json"
    write_json(registry, {
        "schema_version": "run287-operating-scorecard-source-registry-v1",
        "metric_definition_version": "run287-operating-scorecard-metrics-v1",
        "migration_note": "initial fixture", "scorecard_as_of_date": "2026-07-20",
        "sources": sources,
    })
    return registry


def test_scorecard_keeps_evidence_lanes_and_provenance_separate() -> None:
    with tempfile.TemporaryDirectory() as td:
        registry_path = make_fixture(Path(td))
        scorecard = build_scorecard(load_registry(registry_path), source_registry_path=registry_path)
        assert scorecard["headline_performance_trust"] == "TRUSTED"
        assert scorecard["scorecard_trusted"] is True
        assert scorecard["runtime_trust_manifest"]["paper_snapshot"]["status"] == "VERIFIED"
        assert scorecard["evidence_status"] == {
            "historical": "AVAILABLE_PARTIAL",
            "current_paper_execution": "AVAILABLE",
            "true_forward": "UNDERPOWERED",
        }
        assert scorecard["historical_acceptance_overwritten_by_forward"] is False
        assert scorecard["source_artifacts_copied"] is False
        assert len(scorecard["sources"]) == 12
        assert all(row["provenance"]["source_sha256"] for row in scorecard["metrics"] if row["status"] == "AVAILABLE")
        assert "UNAVAILABLE" in render_report(scorecard)


def test_missing_optional_paper_is_unavailable_not_zero() -> None:
    with tempfile.TemporaryDirectory() as td:
        registry_path = make_fixture(Path(td), paper=False)
        scorecard = build_scorecard(load_registry(registry_path), source_registry_path=registry_path)
        assert scorecard["scorecard_trusted"] is False
        assert "current_paper_runtime_manifest_unverified" in scorecard[
            "scorecard_trust_blockers"
        ]
        assert scorecard["evidence_status"]["current_paper_execution"] == "UNAVAILABLE"
        rows = [row for row in scorecard["metrics"] if row["evidence_class"] == "current_paper_execution"]
        assert rows and all(row["value"] is None for row in rows)


def test_current_paper_error_does_not_poison_historical_headline() -> None:
    with tempfile.TemporaryDirectory() as td:
        registry_path = make_fixture(Path(td), reset_count=1)
        scorecard = build_scorecard(load_registry(registry_path), source_registry_path=registry_path)
        assert scorecard["headline_performance_trust"] == "TRUSTED"
        assert scorecard["scorecard_trusted"] is False
        assert scorecard["evidence_status"]["historical"] == "AVAILABLE_PARTIAL"
        assert scorecard["evidence_status"]["current_paper_execution"] == "NOT_TRUSTED"
        assert any("account_reset_count" in value for value in scorecard["integrity_errors"])
        assert all(row["trust"] == "TRUSTED" for row in scorecard["headline_performance"].values())


def test_runtime_manifest_ignores_forged_verified_boolean() -> None:
    with tempfile.TemporaryDirectory() as td:
        registry_path = make_fixture(Path(td), forged_verified_boolean=True)
        scorecard = build_scorecard(
            load_registry(registry_path), source_registry_path=registry_path
        )
        assert scorecard["runtime_trust_manifest"]["trusted_boolean_fields_ignored"] is True
        assert scorecard["runtime_trust_manifest"]["paper_snapshot"]["status"] == "INTEGRITY_ERROR"
        assert scorecard["evidence_status"]["current_paper_execution"] == "NOT_TRUSTED"
        assert "paper_snapshot_hash_chain_unverified" in scorecard[
            "integrity_errors_by_lane"
        ]["current_paper_execution"]


def test_committed_source_registry_uses_verified_canonical_bundle() -> None:
    registry_path = ROOT / "docs" / "run287_operating_scorecard_sources.json"
    registry = load_registry(registry_path)
    assert all("_tmp_tests" not in str(row.get("path")) for row in registry["sources"])
    bundle, errors = verify_canonical_source_bundle(registry)
    assert errors == []
    assert bundle["status"] == "VERIFIED"
    assert bundle["source_count"] == 10
    assert bundle["verified_source_count"] == 10


def test_bundle_verifier_hashes_source_file_bytes() -> None:
    bundle_root = ROOT / "data_static" / "run287_operating_scorecard_sources_v1"
    with tempfile.TemporaryDirectory(dir=bundle_root) as td:
        root = Path(td)
        source = root / "source.json"
        write_json(source, {"value": 1})
        source_id = "fixture_historical"
        source_rel = source.relative_to(ROOT).as_posix()
        manifest = root / "manifest.json"
        write_json(
            manifest,
            {
                "schema_version": "run287-operating-scorecard-source-bundle-v1",
                "immutable": True,
                "sources": [
                    {"id": source_id, "path": source_rel, "sha256": digest(source)}
                ],
            },
        )
        registry = {
            "canonical_source_bundle_manifest": {
                "path": manifest.relative_to(ROOT).as_posix(),
                "expected_sha256": digest(manifest),
            },
            "sources": [
                {
                    "id": source_id,
                    "path": source_rel,
                    "expected_sha256": digest(source),
                    "evidence_class": "historical",
                    "required": True,
                    "disposition": "ABSORBED_SOURCE",
                }
            ],
        }
        verified, errors = verify_canonical_source_bundle(registry)
        assert errors == []
        assert verified["verified_source_count"] == 1
        unpinned = copy.deepcopy(registry)
        unpinned["canonical_source_bundle_manifest"]["expected_sha256"] = ""
        blocked, errors = verify_canonical_source_bundle(unpinned)
        assert blocked["status"] == "UNVERIFIED"
        assert errors == [
            "canonical_source_bundle_manifest_expected_sha256_missing"
        ]
        write_json(source, {"value": 2})
        blocked, errors = verify_canonical_source_bundle(registry)
        assert blocked["status"] == "INTEGRITY_ERROR"
        assert errors == [
            "canonical_source_bundle_source_hash_mismatch:fixture_historical"
        ]


def test_required_absorbed_source_cannot_escape_canonical_bundle() -> None:
    bundle_root = ROOT / "data_static" / "run287_operating_scorecard_sources_v1"
    with tempfile.TemporaryDirectory(dir=bundle_root) as manifest_td, \
            tempfile.TemporaryDirectory(dir=bundle_root.parent) as source_td:
        manifest_root = Path(manifest_td)
        outside_source = Path(source_td) / "source.json"
        write_json(outside_source, {"value": 1})
        traversal_path = (
            Path("data_static/run287_operating_scorecard_sources_v1")
            / ".."
            / Path(source_td).name
            / "source.json"
        ).as_posix()
        source_id = "escaped_required_absorbed"
        manifest = manifest_root / "manifest.json"
        write_json(
            manifest,
            {
                "schema_version": "run287-operating-scorecard-source-bundle-v1",
                "immutable": True,
                "sources": [
                    {
                        "id": source_id,
                        "path": traversal_path,
                        "sha256": digest(outside_source),
                    }
                ],
            },
        )
        registry = {
            "canonical_source_bundle_manifest": {
                "path": manifest.relative_to(ROOT).as_posix(),
                "expected_sha256": digest(manifest),
            },
            "sources": [
                {
                    "id": source_id,
                    "path": traversal_path,
                    "expected_sha256": digest(outside_source),
                    "evidence_class": "historical",
                    "required": True,
                    "disposition": "ABSORBED_SOURCE",
                }
            ],
        }
        bundle, errors = verify_canonical_source_bundle(registry)
        assert bundle["status"] == "INTEGRITY_ERROR"
        assert (
            "canonical_source_bundle_source_outside_root:"
            "escaped_required_absorbed"
        ) in errors
        assert (
            "canonical_source_bundle_manifest_path_outside_root:"
            "escaped_required_absorbed"
        ) in errors


def test_paper_summary_must_share_verified_manifest_directory() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        registry_path = make_fixture(root)
        registry = load_registry(registry_path)
        unattested = root / "unattested" / "summary.json"
        unattested.parent.mkdir()
        write_json(unattested, {"fill_count": 999, "integrity": {}})
        summary_spec = next(
            row for row in registry["sources"]
            if row["id"] == "current_paper_summary"
        )
        summary_spec["path"] = str(unattested)
        summary_spec["expected_sha256"] = digest(unattested)
        scorecard = build_scorecard(
            registry, source_registry_path=registry_path
        )
        assert scorecard["scorecard_trusted"] is False
        assert scorecard["runtime_trust_manifest"]["paper_snapshot"][
            "status"
        ] == "INTEGRITY_ERROR"
        assert "paper_summary_not_bound_to_snapshot_manifest" in scorecard[
            "integrity_errors_by_lane"
        ]["current_paper_execution"]
        paper_rows = [
            row for row in scorecard["metrics"]
            if row["evidence_class"] == "current_paper_execution"
        ]
        assert paper_rows
        assert all(row["status"] == "UNAVAILABLE" for row in paper_rows)
        assert all(row["value"] is None for row in paper_rows)


def test_unverified_p6_summary_suppresses_companion_metrics() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        registry_path = make_fixture(root)
        registry = load_registry(registry_path)
        p6_spec = next(
            row for row in registry["sources"]
            if row["id"] == "p6_selection_summary"
        )
        write_json(Path(p6_spec["path"]), {"rank_stability": {"mean_score_spearman": 0.99}})
        scorecard = build_scorecard(
            registry, source_registry_path=registry_path
        )
        assert "source_hash_mismatch:p6_selection_summary" in scorecard[
            "integrity_errors_by_lane"
        ]["historical"]
        selection_rows = [
            row for row in scorecard["metrics"]
            if row["section"] == "selection_quality"
        ]
        assert selection_rows
        assert all(row["status"] == "UNAVAILABLE" for row in selection_rows)
        assert all(row["value"] is None for row in selection_rows)


def test_paper_metrics_use_the_manifest_bound_summary_bytes() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        registry_path = make_fixture(root)
        registry = load_registry(registry_path)
        paper_root = root / "paper"
        summary_path = paper_root / "summary.json"
        original_verify = paper_integrity_module.verify_integrity_manifest
        republished = False

        def republish_then_verify(
            ledger_root: Path, *, require: bool = False
        ) -> dict[str, object]:
            nonlocal republished
            if not republished:
                republished = True
                write_json(
                    summary_path,
                    {"integrity": {"account_reset_count": 0}, "fill_count": 999},
                )
                write_integrity_manifest(paper_root, as_of_date="2026-07-21")
            return original_verify(ledger_root, require=require)

        with patch.object(
            paper_integrity_module,
            "verify_integrity_manifest",
            side_effect=republish_then_verify,
        ):
            scorecard = build_scorecard(
                registry, source_registry_path=registry_path
            )

        fill_count = next(
            row for row in scorecard["metrics"]
            if row["metric_id"] == "fill_count"
        )
        assert fill_count["status"] == "AVAILABLE"
        assert fill_count["value"] == 999
        assert fill_count["provenance"]["source_sha256"] == scorecard[
            "runtime_trust_manifest"
        ]["paper_snapshot"]["summary_sha256"]
        assert scorecard["runtime_trust_manifest"]["paper_snapshot"][
            "manifest_sha256"
        ] == digest(paper_root / "snapshot_integrity.json")
        manifest_source = next(
            row for row in scorecard["sources"]
            if row["source_id"] == "current_paper_integrity"
        )
        assert manifest_source["sha256"] == digest(
            paper_root / "snapshot_integrity.json"
        )


def test_blocked_p6_summary_cannot_absorb_stale_metrics() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        registry_path = make_fixture(root)
        registry = load_registry(registry_path)
        p6_spec = next(
            row for row in registry["sources"]
            if row["id"] == "p6_selection_summary"
        )
        p6_path = Path(p6_spec["path"])
        write_json(
            p6_path,
            {
                "status": "BLOCKED_PREDICTION_HEAD_INTEGRITY",
                "downstream_outcome_evaluation_executed": False,
                "valid_for_scorecard_absorption": False,
            },
        )
        p6_spec["expected_sha256"] = digest(p6_path)
        scorecard = build_scorecard(
            registry, source_registry_path=registry_path
        )
        assert scorecard["headline_performance_trust"] == "NOT_TRUSTED"
        assert "p6_source_invalid_for_scorecard_absorption" in scorecard[
            "integrity_errors_by_lane"
        ]["historical"]
        selection_rows = [
            row for row in scorecard["metrics"]
            if row["section"] == "selection_quality"
        ]
        assert selection_rows
        assert all(row["status"] == "UNAVAILABLE" for row in selection_rows)


def test_true_forward_bundle_error_does_not_poison_historical_lane() -> None:
    registry_path = ROOT / "docs" / "run287_operating_scorecard_sources.json"
    registry = copy.deepcopy(load_registry(registry_path))
    source_manifest_path = ROOT / registry["canonical_source_bundle_manifest"]["path"]
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    forward_item = next(
        row for row in source_manifest["sources"]
        if row["id"] == "true_forward_summary"
    )
    forward_item["path"] = (
        "data_static/run287_operating_scorecard_sources_v1/forward/wrong.json"
    )
    bundle_root = ROOT / "data_static" / "run287_operating_scorecard_sources_v1"
    with tempfile.TemporaryDirectory(dir=bundle_root) as td:
        manifest = Path(td) / "manifest.json"
        write_json(manifest, source_manifest)
        registry["canonical_source_bundle_manifest"] = {
            "path": manifest.relative_to(ROOT).as_posix(),
            "expected_sha256": digest(manifest),
        }
        scorecard = build_scorecard(
            registry, source_registry_path=registry_path
        )
        expected = "canonical_source_bundle_path_mismatch:true_forward_summary"
        assert expected in scorecard["integrity_errors_by_lane"]["true_forward"]
        assert expected not in scorecard["integrity_errors_by_lane"]["historical"]
        assert scorecard["headline_performance_trust"] == "TRUSTED"
        assert scorecard["evidence_status"]["true_forward"] == "NOT_TRUSTED"
        forward_source = next(
            row for row in scorecard["sources"]
            if row["source_id"] == "true_forward_summary"
        )
        assert forward_source["status"] == "BUNDLE_INTEGRITY_ERROR"
        forward_rows = [
            row for row in scorecard["metrics"]
            if row["evidence_class"] == "true_forward"
        ]
        assert forward_rows
        assert all(row["status"] == "UNAVAILABLE" for row in forward_rows)
        assert all(row["value"] is None for row in forward_rows)

        missing_source_manifest = json.loads(
            source_manifest_path.read_text(encoding="utf-8")
        )
        missing_source_manifest["sources"] = [
            row for row in missing_source_manifest["sources"]
            if row["id"] != "true_forward_summary"
        ]
        write_json(manifest, missing_source_manifest)
        missing_scorecard = build_scorecard(
            registry, source_registry_path=registry_path
        )
        missing_error = (
            "canonical_source_bundle_manifest_source_missing:"
            "true_forward_summary"
        )
        assert missing_error in missing_scorecard["integrity_errors_by_lane"][
            "true_forward"
        ]
        assert missing_error not in missing_scorecard["integrity_errors_by_lane"][
            "historical"
        ]
        scoped_manifest_error = (
            "canonical_source_bundle_manifest_hash_mismatch:"
            "true_forward_summary"
        )
        assert scoped_manifest_error in missing_scorecard[
            "integrity_errors_by_lane"
        ]["true_forward"]
        assert scoped_manifest_error not in missing_scorecard[
            "integrity_errors_by_lane"
        ]["historical"]
        assert missing_scorecard["headline_performance_trust"] == "TRUSTED"


def test_nonmanaged_bundle_member_is_a_global_integrity_failure() -> None:
    registry_path = ROOT / "docs" / "run287_operating_scorecard_sources.json"
    registry = copy.deepcopy(load_registry(registry_path))
    source_manifest_path = ROOT / registry["canonical_source_bundle_manifest"]["path"]
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    current_paper = next(
        row for row in registry["sources"]
        if row["id"] == "current_paper_summary"
    )
    source_manifest["sources"].append({
        "id": "current_paper_summary",
        "path": current_paper["path"],
        "sha256": "0" * 64,
    })
    bundle_root = ROOT / "data_static" / "run287_operating_scorecard_sources_v1"
    with tempfile.TemporaryDirectory(dir=bundle_root) as td:
        manifest = Path(td) / "manifest.json"
        write_json(manifest, source_manifest)
        registry["canonical_source_bundle_manifest"] = {
            "path": manifest.relative_to(ROOT).as_posix(),
            "expected_sha256": digest(manifest),
        }
        scorecard = build_scorecard(
            registry, source_registry_path=registry_path
        )
        error = (
            "canonical_source_bundle_manifest_source_unregistered:"
            "current_paper_summary"
        )
        assert error in scorecard["integrity_errors_by_lane"]["historical"]
        assert error in scorecard["integrity_errors_by_lane"]["true_forward"]
        assert error not in scorecard["integrity_errors_by_lane"][
            "current_paper_execution"
        ]
        assert scorecard["headline_performance_trust"] == "NOT_TRUSTED"


def test_metric_definition_change_requires_migration_note() -> None:
    previous = {"metric_definition_version": "v1"}
    try:
        validate_metric_migration(previous, {"metric_definition_version": "v2", "migration_note": ""})
    except ValueError as exc:
        assert "migration note" in str(exc)
    else:
        raise AssertionError("missing migration note must fail")
    validate_metric_migration(previous, {"metric_definition_version": "v2", "migration_note": "units changed"})


def main() -> int:
    test_scorecard_keeps_evidence_lanes_and_provenance_separate()
    test_missing_optional_paper_is_unavailable_not_zero()
    test_current_paper_error_does_not_poison_historical_headline()
    test_runtime_manifest_ignores_forged_verified_boolean()
    test_committed_source_registry_uses_verified_canonical_bundle()
    test_bundle_verifier_hashes_source_file_bytes()
    test_required_absorbed_source_cannot_escape_canonical_bundle()
    test_paper_summary_must_share_verified_manifest_directory()
    test_unverified_p6_summary_suppresses_companion_metrics()
    test_paper_metrics_use_the_manifest_bound_summary_bytes()
    test_blocked_p6_summary_cannot_absorb_stale_metrics()
    test_true_forward_bundle_error_does_not_poison_historical_lane()
    test_nonmanaged_bundle_member_is_a_global_integrity_failure()
    test_metric_definition_change_requires_migration_note()
    print("run287_operating_scorecard_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
