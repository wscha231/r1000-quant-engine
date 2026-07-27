#!/usr/bin/env python3
"""Fail-closed accepted-publication manifest regression tests."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_run287_accepted_publication_manifest import (  # noqa: E402
    READY_OUTCOME_FALSE_FIELDS,
    READY_STATUS,
    SKIPPED_OUTCOME_FALSE_FIELDS,
    build_manifest,
    sha256_file,
    verify_outcome_chain,
    verify_manifest,
)
from tools.run287_paper_ledger_integrity import write_integrity_manifest  # noqa: E402
from tools.run_daily_simulated_fill_ledger import preview_identity  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def accepted_manifest(latest: Path) -> dict:
    gate_path = latest / "run287_promotion_gate" / "promotion_gate.json"
    return build_manifest(
        latest_run=latest,
        source_commit_sha="a" * 40,
        workflow_identity="owner/repo/.github/workflows/daily.yml@refs/heads/master",
        run_id="123",
        run_attempt="1",
        expected_promotion_gate_sha256=sha256_file(gate_path),
    )


def assert_manifest_blocked(latest: Path, expected: str) -> None:
    try:
        accepted_manifest(latest)
    except ValueError as exc:
        assert expected in str(exc), str(exc)
    else:
        raise AssertionError(f"accepted publication was not blocked: {expected}")


def test_parent_anchor_status_cannot_be_resealed_around_empty_events() -> None:
    with TemporaryDirectory() as raw:
        latest = build_fixture(Path(raw))
        anchor_path = (
            latest / "run287_risk_outcome_parent_anchor" / "anchor.json"
        )
        outcome_path = (
            latest / "run287_risk_outcome_archive" / "summary.json"
        )
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        anchor.update(
            {
                "status": "VERIFIED_PARENT",
                "parent_summary_sha256": "b" * 64,
                "parent_summary_bytes": 1,
                "parent_as_of_date": "2026-07-21",
                "parent_acceptance_status": "QUARANTINED_LEGACY",
            }
        )
        write_json(anchor_path, anchor)
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        outcome["outcome_chain"].update(
            {
                "parent_anchor_sha256": sha256_file(anchor_path),
                "parent_anchor_status": "VERIFIED_PARENT",
                "parent_summary_sha256": "b" * 64,
                "parent_summary_bytes": 1,
                "parent_as_of_date": "2026-07-21",
                "parent_acceptance_status": "QUARANTINED_LEGACY",
            }
        )
        try:
            verify_outcome_chain(latest_run=latest, outcome=outcome)
        except ValueError as exc:
            assert "risk_outcome_parent_event_anchor_invalid" in str(exc)
        else:
            raise AssertionError(
                "VERIFIED_PARENT accepted an empty parent event prefix"
            )


def build_fixture(root: Path) -> Path:
    latest = root / "outputs"
    reports = latest / "reports"
    reports.mkdir(parents=True)
    source_root = latest / "run287_same_close_decision" / "20260722"
    source_root.mkdir(parents=True)
    targets = {
        "main": reports / "operating_main_target_book.csv",
        "concentrated": reports / "operating_concentrated_target_book.csv",
    }
    sources = {
        "main": source_root / "same_close_main_target_book.csv",
        "concentrated": source_root / "same_close_concentrated_target_book.csv",
    }
    for portfolio, path in targets.items():
        payload = (
            "rebalance_date,ticker,weight,portfolio_kind\n"
            f"2026-07-22,CASH,1.0,{portfolio}\n"
        )
        path.write_text(
            payload,
            encoding="utf-8",
        )
        sources[portfolio].write_text(payload, encoding="utf-8")

    paper = latest / "daily_simulated_fill_ledger"
    preview = latest / "account_ledger_preview"
    accepted_portfolios: dict[str, dict[str, str]] = {}
    for portfolio in ("main", "concentrated"):
        account_path = paper / portfolio / "account_state_latest.json"
        ledger_manifest_path = paper / portfolio / "manifest.json"
        effective_target_path = paper / portfolio / "effective_target_latest.csv"
        write_json(
            account_path,
            {
                "portfolio_kind": portfolio,
                "as_of_date": "2026-07-22",
                "new_order_generation_suppressed": False,
                "review_only": True,
                "live_trading_enabled": False,
            },
        )
        write_json(
            ledger_manifest_path,
            {
                "portfolio_kind": portfolio,
                "as_of_date": "2026-07-22",
                "new_order_generation_suppressed": False,
                "review_only": True,
                "live_trading_enabled": False,
            },
        )
        effective_target_path.write_bytes(targets[portfolio].read_bytes())
        source_hash = sha256_file(sources[portfolio])
        published_hash = sha256_file(targets[portfolio])
        assert source_hash == published_hash
        account_hash = sha256_file(account_path)
        preview_dir = preview / portfolio
        preview_dir.mkdir(parents=True)
        preview_dir.joinpath("orders_preview.csv").write_text(
            "ticker,side,status\nCASH,,NO_ORDER\n",
            encoding="utf-8",
        )
        preview_dir.joinpath("target_weights.csv").write_text(
            "ticker,target_weight\nCASH,1.0\n",
            encoding="utf-8",
        )
        identity = preview_identity(
            preview_dir=preview_dir,
            account_path=account_path,
            effective_target_path=effective_target_path,
            source_target_path=sources[portfolio],
            portfolio=portfolio,
            as_of_date=pd.Timestamp("2026-07-22"),
            preview_mode="EXECUTABLE_CANDIDATE",
        )
        write_json(
            preview_dir / "order_batch_manifest.json",
            {
                **identity,
                "schema_version": "account-ledger-preview-order-batch-v2",
                "portfolio_kind": portfolio,
                "as_of_date": "2026-07-22",
                "preview_mode": "EXECUTABLE_CANDIDATE",
                "new_order_generation_suppressed": False,
                "accepted_account_sha256": account_hash,
                "effective_target_sha256": sha256_file(effective_target_path),
                "source_target_sha256": source_hash,
                "orders_preview_sha256": sha256_file(
                    preview_dir / "orders_preview.csv"
                ),
                "target_weights_sha256": sha256_file(
                    preview_dir / "target_weights.csv"
                ),
            },
        )
        accepted_portfolios[portfolio] = {
            "source_target_path": str(sources[portfolio]),
            "source_target_sha256": source_hash,
            "published_target_path": str(targets[portfolio]),
            "published_target_sha256": published_hash,
            "account_state_sha256": account_hash,
            "ledger_manifest_sha256": sha256_file(ledger_manifest_path),
            "preview_identity_at_acceptance": identity["preview_identity_hash"],
            "preview_mode_at_acceptance": "EXECUTABLE_CANDIDATE",
        }
    write_json(
        paper / "summary.json",
        {
            "schema_version": "daily-simulated-fill-ledger-summary-v1",
            "status": "completed",
            "as_of_date": "2026-07-22",
            "new_order_generation_suppressed": False,
            "review_only": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
        },
    )
    write_json(
        paper / "accepted_publication.json",
        {
            "schema_version": "run287-paper-accepted-publication-v1",
            "status": "ACCEPTED_ATOMIC_PUBLICATION",
            "as_of_date": "2026-07-22",
            "transaction_mode": "SELECTED_TARGET",
            "portfolios": accepted_portfolios,
            "review_only": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
        },
    )
    paper_manifest = write_integrity_manifest(paper, as_of_date="2026-07-22")

    empty_sha256 = hashlib.sha256(b"").hexdigest()
    parent_anchor_path = (
        latest / "run287_risk_outcome_parent_anchor" / "anchor.json"
    )
    write_json(
        parent_anchor_path,
        {
            "schema_version": "run287-risk-outcome-parent-anchor-v1",
            "status": "GENESIS_EMPTY",
            "generated_at_utc": "2026-07-22T22:00:00Z",
            "parent_summary_sha256": "",
            "parent_summary_bytes": 0,
            "parent_event_log_sha256": empty_sha256,
            "parent_event_log_bytes": 0,
            "parent_event_count": 0,
            "parent_as_of_date": "",
            "carried_quarantined_prefix_event_count": 0,
            "parent_acceptance_status": "NO_PRIOR_STATE",
            "parent_accepted_manifest_sha256": "",
            "parent_accepted_manifest_bytes": 0,
            "parent_accepted_manifest_as_of_date": "",
            "review_only": True,
            "mechanism_promotion_allowed": False,
            "threshold_tuning_allowed": False,
            "stop_or_exit_rule_created": False,
            "selector_weights_changed": False,
            "cash_policy_changed": False,
            "portfolio_transition_allowed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "historical_cagr_mdd_evidence_changed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
        },
    )
    parent_anchor_sha256 = sha256_file(parent_anchor_path)
    write_json(
        latest / "run287_risk_outcome_archive" / "summary.json",
        {
            "schema_version": "run287-risk-outcome-archive-v1",
            "status": "SKIPPED_NO_DECISION_OBSERVATIONS",
            "as_of_date": "2026-07-22",
            "blockers": [],
            "review_only": True,
            "outcome_chain": {
                "schema_version": "run287-risk-outcome-chain-v1",
                "status": "VERIFIED_APPEND_ONLY",
                "parent_anchor_sha256": parent_anchor_sha256,
                "parent_anchor_status": "GENESIS_EMPTY",
                "parent_summary_sha256": "",
                "parent_summary_bytes": 0,
                "parent_event_log_sha256": empty_sha256,
                "parent_event_log_bytes": 0,
                "parent_event_count": 0,
                "parent_as_of_date": "",
                "carried_quarantined_prefix_event_count": 0,
                "parent_acceptance_status": "NO_PRIOR_STATE",
                "parent_accepted_manifest_sha256": "",
                "parent_accepted_manifest_bytes": 0,
                "parent_accepted_manifest_as_of_date": "",
                "current_event_log_sha256": empty_sha256,
                "current_event_log_bytes": 0,
                "current_event_count": 0,
                "current_as_of_date": "2026-07-22",
                "exact_parent_prefix_verified": True,
                "append_only_verified": True,
                "trusted_event_count": 0,
            },
            **{field: False for field in SKIPPED_OUTCOME_FALSE_FIELDS},
        },
    )
    write_json(
        latest / "run287_operating_scorecard" / "operating_scorecard.json",
        {
            "schema_version": "run287-operating-scorecard-v1",
            "scorecard_trusted": True,
            "scorecard_trust_blockers": [],
            "integrity_errors": [],
            "runtime_trust_manifest": {
                "paper_snapshot": {
                    "status": "VERIFIED",
                    "manifest_sha256": sha256_file(
                        paper / "snapshot_integrity.json"
                    ),
                    "snapshot_hash": paper_manifest["snapshot_hash"],
                }
            },
        },
    )
    write_json(
        latest / "run287_promotion_gate" / "promotion_gate.json",
        {
            "schema_version": "run287-promotion-gate-v1",
            "effective_promotion_state": "RESEARCH_ONLY",
            "source_hashes": {
                "contract_sha256": sha256_file(
                    ROOT / "data_static/run287_promotion_gate_contract.json"
                ),
                "state_sha256": sha256_file(
                    ROOT / "data_static/run287_promotion_state.json"
                ),
                "base_evidence_sha256": sha256_file(
                    ROOT / "data_static/run287_promotion_evidence_current.json"
                ),
                "approved_multiple_testing_pointer_sha256": sha256_file(
                    ROOT
                    / "data_static"
                    / "run287_multiple_testing_approved_pointer.json"
                ),
                "evidence_sha256": "f" * 64,
                "runtime_paper_integrity_sha256": sha256_file(
                    paper / "snapshot_integrity.json"
                ),
                "runtime_risk_outcome_parent_anchor_sha256":
                    parent_anchor_sha256,
                "runtime_risk_outcome_summary_sha256": sha256_file(
                    latest / "run287_risk_outcome_archive" / "summary.json"
                ),
                "runtime_scorecard_sha256": sha256_file(
                    latest
                    / "run287_operating_scorecard"
                    / "operating_scorecard.json"
                ),
            },
            "runtime_evidence_limitations": [],
            "runtime_observed_file_hashes": {
                "daily_simulated_fill_ledger/snapshot_integrity.json":
                    sha256_file(paper / "snapshot_integrity.json"),
                "run287_risk_outcome_parent_anchor/anchor.json":
                    parent_anchor_sha256,
                "run287_operating_scorecard/operating_scorecard.json":
                    sha256_file(
                        latest
                        / "run287_operating_scorecard"
                        / "operating_scorecard.json"
                    ),
                "run287_risk_outcome_archive/summary.json":
                    sha256_file(
                        latest / "run287_risk_outcome_archive" / "summary.json"
                    ),
            },
            "canonical_state_unchanged": True,
            "automatic_forward_transition_performed": False,
            "automatic_production_activation_performed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "fullrun_executed": False,
        },
    )
    user = latest / "user_current"
    user.mkdir()
    user.joinpath("02_target_weights.csv").write_text(
        "portfolio,ticker,target_weight\nmain,CASH,1.0\n",
        encoding="utf-8",
    )
    user.joinpath("03_order_preview.csv").write_text(
        "portfolio,ticker,status\nmain,CASH,NO_ORDER\n",
        encoding="utf-8",
    )
    write_json(
        user / "08_rebalance_decision.json",
        {"status": "REVIEW_ONLY", "as_of_date": "2026-07-22"},
    )
    write_json(
        user / "10_latest_close_performance.json",
        {
            "schema_version": "run287-latest-close-performance-v1",
            "status": "READY_LATEST_CLOSE_REVIEW_ONLY",
            "as_of_date": "2026-07-22",
            "review_only": True,
            "live_trading_enabled": False,
            "production_activation_allowed": False,
        },
    )
    return latest


def write_ready_outcome(latest: Path) -> dict:
    output = latest / "run287_risk_outcome_archive"
    cache_manifest = (
        latest
        / "run287_risk_outcome_price_cache"
        / "replay_price_cache_manifest.json"
    )
    write_json(
        cache_manifest,
        {
            "schema_version": "run287-replay-price-cache-manifest-v2",
            "book_inputs": [],
            "cache_files": {},
            "review_only": True,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
        },
    )
    event_log = output / "risk_outcome_events.jsonl"
    current_status = output / "current_status.csv"
    price_universe = output / "price_universe.csv"
    event_log.write_text('{"event_id":"event-1"}\n', encoding="utf-8")
    current_status.write_text(
        "observation_id,decision_date,outcome_21d_status\n"
        "observation-1,2026-04-13,completed\n",
        encoding="utf-8",
    )
    price_universe.write_text("ticker\nSPY\n", encoding="utf-8")
    parent_anchor_path = (
        latest / "run287_risk_outcome_parent_anchor" / "anchor.json"
    )
    parent_anchor = json.loads(
        parent_anchor_path.read_text(encoding="utf-8")
    )
    summary = {
        "schema_version": "run287-risk-outcome-archive-v1",
        "status": "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY",
        "as_of_date": "2026-07-22",
        "blockers": [],
        "outputs": {
            "event_log_sha256": sha256_file(event_log),
            "current_status_sha256": sha256_file(current_status),
            "price_universe_sha256": sha256_file(price_universe),
        },
        "source_inputs": {
            "price_cache_manifest_sha256": sha256_file(cache_manifest)
        },
        "outcome_chain": {
            "schema_version": "run287-risk-outcome-chain-v1",
            "status": "VERIFIED_APPEND_ONLY",
            "parent_anchor_sha256": sha256_file(parent_anchor_path),
            "parent_anchor_status": parent_anchor["status"],
            **{
                field: parent_anchor[field]
                for field in (
                    "parent_summary_sha256",
                    "parent_summary_bytes",
                    "parent_event_log_sha256",
                    "parent_event_log_bytes",
                    "parent_event_count",
                    "parent_as_of_date",
                    "carried_quarantined_prefix_event_count",
                    "parent_acceptance_status",
                    "parent_accepted_manifest_sha256",
                    "parent_accepted_manifest_bytes",
                    "parent_accepted_manifest_as_of_date",
                )
            },
            "current_event_log_sha256": sha256_file(event_log),
            "current_event_log_bytes": event_log.stat().st_size,
            "current_event_count": 1,
            "current_as_of_date": "2026-07-22",
            "exact_parent_prefix_verified": True,
            "append_only_verified": True,
            "trusted_event_count": 1,
        },
        "review_only": True,
        **{field: False for field in READY_OUTCOME_FALSE_FIELDS},
    }
    write_json(output / "summary.json", summary)
    gate_path = latest / "run287_promotion_gate" / "promotion_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["runtime_observed_file_hashes"][
        "run287_risk_outcome_archive/summary.json"
    ] = sha256_file(output / "summary.json")
    gate["runtime_observed_file_hashes"][
        "run287_risk_outcome_price_cache/replay_price_cache_manifest.json"
    ] = sha256_file(cache_manifest)
    gate["source_hashes"]["runtime_risk_outcome_summary_sha256"] = sha256_file(
        output / "summary.json"
    )
    gate["source_hashes"][
        "runtime_risk_price_cache_manifest_sha256"
    ] = sha256_file(cache_manifest)
    write_json(gate_path, gate)
    return summary


def test_manifest_binds_all_accepted_files_and_identity() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        manifest = accepted_manifest(latest)
        assert manifest["status"] == READY_STATUS
        assert manifest["as_of_date"] == "2026-07-22"
        assert manifest["source_identity"]["commit_sha"] == "a" * 40
        assert manifest["source_identity"]["promotion_gate_sha256"] == (
            sha256_file(
                latest / "run287_promotion_gate" / "promotion_gate.json"
            )
        )
        assert set(manifest["files"]) >= {
            "main_target",
            "concentrated_target",
            "paper_snapshot_integrity",
            "risk_outcome_parent_anchor",
            "risk_outcome_summary",
            "operating_scorecard",
            "promotion_gate",
            "user_target_weights",
            "user_order_preview",
            "user_rebalance_decision",
            "user_latest_close_performance",
            "main_source_target",
            "main_published_target",
            "main_account_state",
            "main_preview_manifest",
            "main_preview_effective_target",
            "main_preview_orders",
            "main_preview_target_weights",
            "concentrated_source_target",
            "concentrated_published_target",
            "concentrated_account_state",
            "concentrated_preview_manifest",
            "concentrated_preview_effective_target",
            "concentrated_preview_orders",
            "concentrated_preview_target_weights",
        }
        assert manifest["production_activation_allowed"] is False
        assert manifest["live_trading_enabled"] is False
        manifest_path = latest / "run287_accepted_publication" / "manifest.json"
        write_json(manifest_path, manifest)
        verified = verify_manifest(
            latest_run=latest,
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256_file(manifest_path),
        )
        assert verified == manifest


def test_skipped_outcome_requires_empty_blockers_and_safe_flags() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        summary_path = latest / "run287_risk_outcome_archive" / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["blockers"] = ["forged"]
        write_json(summary_path, summary)
        assert_manifest_blocked(latest, "risk_outcome_blockers_present")

    for field in SKIPPED_OUTCOME_FALSE_FIELDS:
        with TemporaryDirectory() as tmp:
            latest = build_fixture(Path(tmp))
            summary_path = (
                latest / "run287_risk_outcome_archive" / "summary.json"
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary[field] = True
            write_json(summary_path, summary)
            assert_manifest_blocked(
                latest,
                f"risk_outcome_unsafe_flag:{field}",
            )


def test_gate_step_hash_and_publish_time_reverification_are_fail_closed() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        gate_path = latest / "run287_promotion_gate" / "promotion_gate.json"
        expected = sha256_file(gate_path)
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["forged_after_gate_step"] = True
        write_json(gate_path, gate)
        try:
            build_manifest(
                latest_run=latest,
                source_commit_sha="a" * 40,
                workflow_identity=(
                    "owner/repo/.github/workflows/daily.yml@refs/heads/master"
                ),
                run_id="123",
                run_attempt="1",
                expected_promotion_gate_sha256=expected,
            )
        except ValueError as exc:
            assert "promotion_gate_step_output_sha256_mismatch" in str(exc)
        else:
            raise AssertionError("post-gate mutation was accepted")

    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        manifest = accepted_manifest(latest)
        manifest_path = latest / "run287_accepted_publication" / "manifest.json"
        write_json(manifest_path, manifest)
        sealed_manifest_sha256 = sha256_file(manifest_path)
        latest.joinpath("user_current/03_order_preview.csv").write_text(
            "forged\n",
            encoding="utf-8",
        )
        try:
            verify_manifest(
                latest_run=latest,
                manifest_path=manifest_path,
                expected_manifest_sha256=sealed_manifest_sha256,
            )
        except ValueError as exc:
            assert "accepted_publication_file_reverify_failed" in str(exc)
        else:
            raise AssertionError("publish-time mutation was accepted")

        resealed = json.loads(manifest_path.read_text(encoding="utf-8"))
        resealed["files"]["user_order_preview"]["sha256"] = sha256_file(
            latest / "user_current/03_order_preview.csv"
        )
        write_json(manifest_path, resealed)
        try:
            verify_manifest(
                latest_run=latest,
                manifest_path=manifest_path,
                expected_manifest_sha256=sealed_manifest_sha256,
            )
        except ValueError as exc:
            assert "accepted_publication_manifest_sha256_mismatch" in str(exc)
        else:
            raise AssertionError("resealed accepted manifest was accepted")


def test_publish_time_reverification_checks_every_paper_snapshot_file() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        manifest = accepted_manifest(latest)
        manifest_path = latest / "run287_accepted_publication" / "manifest.json"
        write_json(manifest_path, manifest)
        sealed_manifest_sha256 = sha256_file(manifest_path)
        snapshot_only_path = (
            latest
            / "daily_simulated_fill_ledger"
            / "summary.json"
        )
        snapshot_only_path.write_text(
            snapshot_only_path.read_text(encoding="utf-8") + "forged\n",
            encoding="utf-8",
        )
        try:
            verify_manifest(
                latest_run=latest,
                manifest_path=manifest_path,
                expected_manifest_sha256=sealed_manifest_sha256,
            )
        except ValueError as exc:
            assert "paper_snapshot_reverify_failed" in str(exc)
        else:
            raise AssertionError("unlisted paper snapshot mutation was accepted")


def test_tampered_contract_file_blocks_manifest() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        latest.joinpath("user_current/02_target_weights.csv").unlink()
        assert_manifest_blocked(
            latest, "accepted_publication_file_missing:user_target_weights"
        )


def test_latest_close_performance_is_required_and_reverified() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        latest_close = latest / "user_current/10_latest_close_performance.json"
        latest_close.unlink()
        assert_manifest_blocked(
            latest,
            "accepted_publication_file_missing:"
            "user_latest_close_performance",
        )

    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        manifest = accepted_manifest(latest)
        manifest_path = (
            latest / "run287_accepted_publication" / "manifest.json"
        )
        write_json(manifest_path, manifest)
        sealed_manifest_sha256 = sha256_file(manifest_path)
        latest_close = latest / "user_current/10_latest_close_performance.json"
        latest_close.write_text(
            latest_close.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        try:
            verify_manifest(
                latest_run=latest,
                manifest_path=manifest_path,
                expected_manifest_sha256=sealed_manifest_sha256,
            )
        except ValueError as exc:
            assert (
                "accepted_publication_file_reverify_failed:"
                "user_latest_close_performance"
            ) in str(exc)
        else:
            raise AssertionError(
                "mutated latest-close publication was accepted"
            )


def test_gate_observed_hash_must_bind_the_exact_runtime_scorecard() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        scorecard = (
            latest / "run287_operating_scorecard" / "operating_scorecard.json"
        )
        payload = json.loads(scorecard.read_text(encoding="utf-8"))
        payload["forged_after_gate"] = True
        write_json(scorecard, payload)
        assert_manifest_blocked(
            latest,
            "promotion_gate_runtime_anchor_mismatch:"
            "runtime_scorecard_sha256",
        )

    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        anchor_path = (
            latest
            / "run287_risk_outcome_parent_anchor"
            / "anchor.json"
        )
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        anchor["forged_after_gate"] = True
        write_json(anchor_path, anchor)
        assert_manifest_blocked(
            latest,
            "risk_outcome_chain_contract_invalid",
        )


def test_gate_observed_nonpublication_file_is_reverified_before_publish() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        observed = (
            latest
            / "run287_decision_observation_archive"
            / "candidate_risk_history.jsonl"
        )
        observed.parent.mkdir(parents=True)
        observed.write_text('{"event_id":"one"}\n', encoding="utf-8")
        gate_path = latest / "run287_promotion_gate" / "promotion_gate.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["runtime_observed_file_hashes"][
            "run287_decision_observation_archive/candidate_risk_history.jsonl"
        ] = sha256_file(observed)
        write_json(gate_path, gate)

        manifest = accepted_manifest(latest)
        manifest_path = latest / "run287_accepted_publication" / "manifest.json"
        write_json(manifest_path, manifest)
        sealed_manifest_sha256 = sha256_file(manifest_path)
        observed.write_text('{"event_id":"two"}\n', encoding="utf-8")
        try:
            verify_manifest(
                latest_run=latest,
                manifest_path=manifest_path,
                expected_manifest_sha256=sealed_manifest_sha256,
            )
        except ValueError as exc:
            assert "gate_observed_reverify_failed" in str(exc)
        else:
            raise AssertionError("gate-observed TOCTOU mutation was accepted")


def test_verified_parent_accepted_head_is_bound_and_reverified() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        parent_manifest_payload = accepted_manifest(latest)
        parent_manifest_path = (
            latest
            / "run287_risk_outcome_parent_accepted"
            / "manifest.json"
        )
        write_json(parent_manifest_path, parent_manifest_payload)
        parent_manifest_sha256 = sha256_file(parent_manifest_path)

        summary_path = latest / "run287_risk_outcome_archive/summary.json"
        parent_summary_bytes = summary_path.read_bytes()
        anchor_path = (
            latest / "run287_risk_outcome_parent_anchor/anchor.json"
        )
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        anchor.update(
            {
                "status": "VERIFIED_EMPTY_PARENT",
                "parent_summary_sha256": hashlib.sha256(
                    parent_summary_bytes
                ).hexdigest(),
                "parent_summary_bytes": len(parent_summary_bytes),
                "parent_as_of_date": "2026-07-22",
                "parent_acceptance_status": "VERIFIED_ACCEPTED_HEAD",
                "parent_accepted_manifest_sha256":
                    parent_manifest_sha256,
                "parent_accepted_manifest_bytes":
                    parent_manifest_path.stat().st_size,
                "parent_accepted_manifest_as_of_date": "2026-07-22",
            }
        )
        write_json(anchor_path, anchor)

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["outcome_chain"] = {
            "schema_version": "run287-risk-outcome-chain-v1",
            "status": "VERIFIED_APPEND_ONLY",
            "parent_anchor_sha256": sha256_file(anchor_path),
            "parent_anchor_status": anchor["status"],
            **{
                field: anchor[field]
                for field in (
                    "parent_summary_sha256",
                    "parent_summary_bytes",
                    "parent_event_log_sha256",
                    "parent_event_log_bytes",
                    "parent_event_count",
                    "parent_as_of_date",
                    "carried_quarantined_prefix_event_count",
                    "parent_acceptance_status",
                    "parent_accepted_manifest_sha256",
                    "parent_accepted_manifest_bytes",
                    "parent_accepted_manifest_as_of_date",
                )
            },
            "current_event_log_sha256": hashlib.sha256(b"").hexdigest(),
            "current_event_log_bytes": 0,
            "current_event_count": 0,
            "current_as_of_date": "2026-07-22",
            "exact_parent_prefix_verified": True,
            "append_only_verified": True,
            "trusted_event_count": 0,
        }
        write_json(summary_path, summary)

        gate_path = latest / "run287_promotion_gate/promotion_gate.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["source_hashes"][
            "runtime_risk_outcome_parent_anchor_sha256"
        ] = sha256_file(anchor_path)
        gate["source_hashes"][
            "runtime_risk_outcome_summary_sha256"
        ] = sha256_file(summary_path)
        gate["runtime_observed_file_hashes"][
            "run287_risk_outcome_parent_anchor/anchor.json"
        ] = sha256_file(anchor_path)
        gate["runtime_observed_file_hashes"][
            "run287_risk_outcome_archive/summary.json"
        ] = sha256_file(summary_path)
        gate["runtime_observed_file_hashes"][
            "run287_risk_outcome_parent_accepted/manifest.json"
        ] = parent_manifest_sha256
        write_json(gate_path, gate)

        manifest = accepted_manifest(latest)
        assert (
            manifest["outcome_chain"]["parent_accepted_manifest_sha256"]
            == parent_manifest_sha256
        )
        assert (
            manifest["gate_observed_files"][
                "run287_risk_outcome_parent_accepted/manifest.json"
            ]["sha256"]
            == parent_manifest_sha256
        )

        parent_payload = json.loads(
            parent_manifest_path.read_text(encoding="utf-8")
        )
        parent_payload["forged_after_acceptance"] = True
        write_json(parent_manifest_path, parent_payload)
        assert_manifest_blocked(
            latest,
            "risk_outcome_parent_accepted_manifest_mismatch",
        )


def test_missing_accepted_source_target_blocks_manifest() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        latest.joinpath(
            "run287_same_close_decision/20260722/same_close_main_target_book.csv"
        ).unlink()
        assert_manifest_blocked(
            latest, "accepted_publication_file_missing:main_source_target"
        )


def test_tampered_preview_or_identity_blocks_manifest() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        latest.joinpath("account_ledger_preview/main/orders_preview.csv").write_text(
            "ticker,side,status\nCASH,BUY,ready\n",
            encoding="utf-8",
        )
        assert_manifest_blocked(
            latest, "accepted_publication_sha256_mismatch:main_preview_orders"
        )

    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        manifest_path = (
            latest / "account_ledger_preview/main/order_batch_manifest.json"
        )
        preview_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        preview_manifest["preview_identity_hash"] = "f" * 64
        write_json(manifest_path, preview_manifest)
        assert_manifest_blocked(latest, "paper_preview_identity_mismatch:main")


def test_ready_outcome_requires_all_safety_and_output_hashes() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        write_ready_outcome(latest)
        manifest = accepted_manifest(latest)
        assert set(manifest["files"]) >= {
            "risk_outcome_event_log",
            "risk_outcome_current_status",
            "risk_outcome_price_universe",
        }

    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        summary = write_ready_outcome(latest)
        summary["blockers"] = ["forged_blocker"]
        write_json(latest / "run287_risk_outcome_archive/summary.json", summary)
        assert_manifest_blocked(latest, "risk_outcome_blockers_present")

    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        summary = write_ready_outcome(latest)
        summary_path = latest / "run287_risk_outcome_archive/summary.json"
        for field in READY_OUTCOME_FALSE_FIELDS:
            summary[field] = True
            write_json(summary_path, summary)
            assert_manifest_blocked(latest, f"risk_outcome_unsafe_flag:{field}")
            summary[field] = False

    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        write_ready_outcome(latest)
        latest.joinpath(
            "run287_risk_outcome_archive/risk_outcome_events.jsonl"
        ).write_text('{"event_id":"tampered"}\n', encoding="utf-8")
        assert_manifest_blocked(
            latest, "risk_outcome_chain_current_mismatch"
        )

    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        write_ready_outcome(latest)
        latest.joinpath("run287_risk_outcome_archive/current_status.csv").write_text(
            "observation_id\nforged\n", encoding="utf-8"
        )
        assert_manifest_blocked(
            latest,
            "accepted_publication_sha256_mismatch:risk_outcome_current_status",
        )

    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        write_ready_outcome(latest)
        latest.joinpath("run287_risk_outcome_archive/price_universe.csv").write_text(
            "ticker\nFAKE\n", encoding="utf-8"
        )
        assert_manifest_blocked(
            latest,
            "accepted_publication_sha256_mismatch:risk_outcome_price_universe",
        )


def test_duplicate_json_keys_in_bound_input_fail_closed() -> None:
    with TemporaryDirectory() as tmp:
        latest = build_fixture(Path(tmp))
        anchor_path = (
            latest / "run287_risk_outcome_parent_anchor" / "anchor.json"
        )
        anchor_path.write_text(
            '{"schema_version":"first","schema_version":"second"}',
            encoding="utf-8",
        )
        assert_manifest_blocked(latest, "duplicate_json_key:schema_version")


if __name__ == "__main__":
    tests = [
        value
        for key, value in sorted(globals().items())
        if key.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"run287_accepted_publication_manifest_smoke: {len(tests)} passed")
