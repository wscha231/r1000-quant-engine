#!/usr/bin/env python3
"""Audit the frozen Run287 score stack on one current decision frame.

This research-only lane consumes a hash-pinned current decision frame, its
verified four-linear-head output, and a previously READY score-stack manifest
that freezes the CatBoost/adaptive-engine artifacts.  It removes embedded
stale predictions before joining current heads, verifies prediction passthrough
and deterministic registered-stack parity, and emits ticker-order diagnostics.

It never sorts scores, assigns ranks, selects top-N, sizes positions, writes a
target book, backtests, runs fullrun, enables production, or trades.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import EngineConfig  # noqa: E402
from r1000_pipeline import compute_adaptive_ensemble_state  # noqa: E402
from tools import stage_run287_price_batch as checkpoint  # noqa: E402
from tools.run_run287_current_decision_score_only import (  # noqa: E402
    decision_frame_schema_supported,
    normalized_tickers,
    utc_timestamp,
)
from tools.run_run287_current_score_stack_audit import (  # noqa: E402
    PARITY_COLUMNS,
    PREDICTION_COLUMNS,
    compare_frames,
    direct_record,
    execute_stack,
    expected_input,
    git_head,
    manifest_record,
    source_files_unchanged,
)


SCHEMA_VERSION = "run287-current-decision-score-stack-audit-v1"
READY_STATUS = "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING"
BLOCKED_STATUS = "BLOCKED_CURRENT_DECISION_SCORE_STACK_AUDIT"
LINEAR_COLUMNS = [
    "pred_lin_ret",
    "pred_lin_p",
    "pred_future_winner_ret",
    "pred_future_winner_p",
]
ACTIVE_PREDICTION_COLUMNS = [*LINEAR_COLUMNS, "pred_cat_ret", "pred_cat_p"]
ANCHOR_ARTIFACTS = [
    "cat_reg",
    "cat_cls",
    "model_bundle",
    "scored_oos",
    "verifier_ticker_audit",
]


def blocked_payload(
    output_dir: Path,
    *,
    failures: list[str],
    input_audits: Mapping[str, Any],
    started: float,
    valuation_date: str,
) -> dict[str, Any]:
    unchanged = source_files_unchanged(input_audits)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "contract_failures": failures,
        "blockers": failures,
        "valuation_price_cutoff_date": valuation_date,
        "research_only": True,
        "score_stack_audit_passed": False,
        "model_scoring_executed": False,
        "ranking_eligibility_computed": False,
        "decision_ranking_allowed": False,
        "score_sort_executed": False,
        "rank_assignment_executed": False,
        "top_n_executed": False,
        "selector_executed": False,
        "target_book_generation_allowed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": not unchanged,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(input_audits),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {
            "git_head": git_head(),
            "builder": checkpoint.fingerprint(Path(__file__)),
        },
    }
    checkpoint.write_json(output_dir / "manifest.json", payload)
    return payload


def verify_owner_record(
    *,
    label: str,
    owner_path: Path,
    owner: Mapping[str, Any],
    section: str,
    name: str,
    verified_paths: dict[str, Path],
    input_audits: dict[str, Any],
    failures: list[str],
) -> None:
    path, audit = manifest_record(owner_path, owner, section, name)
    verified_paths[label] = path
    input_audits[label] = audit
    if audit.get("hash_matches") is not True:
        failures.append(f"input_hash_mismatch:{label}")


def prediction_activity_rows(
    predictions: pd.DataFrame, tolerance: float
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for column in ACTIVE_PREDICTION_COLUMNS:
        values = pd.to_numeric(predictions[column], errors="coerce")
        finite = values[np.isfinite(values)]
        standard_deviation = float(finite.std(ddof=0)) if len(finite) else np.nan
        maximum_absolute_value = (
            float(finite.abs().max()) if len(finite) else np.nan
        )
        active = bool(
            len(finite) == len(values)
            and maximum_absolute_value > tolerance
            and standard_deviation > tolerance
        )
        rows.append(
            {
                "prediction": column,
                "row_count": len(values),
                "finite_count": int(len(finite)),
                "unique_count": int(finite.nunique()),
                "maximum_absolute_value": maximum_absolute_value,
                "standard_deviation": standard_deviation,
                "nonzero_nonconstant_pass": active,
            }
        )
    return rows


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = checkpoint.repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")
    output_dir.mkdir(parents=True)

    valuation_date = checkpoint.clean_date(args.valuation_date)
    decision_path = checkpoint.repo_path(args.decision_frame_manifest)
    score_only_path = checkpoint.repo_path(args.score_only_manifest)
    anchor_path = checkpoint.repo_path(args.frozen_score_stack_manifest)
    input_audits: dict[str, Any] = {
        "decision_frame_manifest": expected_input(
            decision_path,
            args.expected_decision_frame_sha256,
            "decision_frame_manifest",
        ),
        "score_only_manifest": expected_input(
            score_only_path,
            args.expected_score_only_sha256,
            "score_only_manifest",
        ),
        "frozen_score_stack_manifest": expected_input(
            anchor_path,
            args.expected_frozen_score_stack_sha256,
            "frozen_score_stack_manifest",
        ),
    }
    failures = [
        f"input_hash_mismatch:{label}"
        for label, audit in input_audits.items()
        if audit.get("hash_matches") is not True
    ]
    if not valuation_date:
        failures.append("valuation_date_invalid")
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    decision = checkpoint.read_json(decision_path)
    score_only = checkpoint.read_json(score_only_path)
    anchor = checkpoint.read_json(anchor_path)
    decision_coverage = decision.get("coverage") or {}
    relations = {
        "score_only_to_decision_frame": (
            (score_only.get("source_inputs") or {}).get("decision_frame_manifest")
            or {}
        ).get("sha256")
        == input_audits["decision_frame_manifest"].get("sha256"),
    }
    checks = {
        "decision_schema": decision_frame_schema_supported(
            decision.get("schema_version")
        ),
        "decision_ready": decision.get("status")
        == "READY_COMPLETE_CURRENT_DECISION_FRAME",
        "decision_complete": decision.get("current_decision_data_complete") is True,
        "decision_scoring_prerequisite": decision.get(
            "research_model_scoring_prerequisite_passed"
        )
        is True,
        "score_only_schema": score_only.get("schema_version")
        == "run287-current-decision-score-only-v1",
        "score_only_ready": score_only.get("status")
        == "READY_CURRENT_DECISION_SCORE_ONLY_NONRANKING",
        "score_only_scored": score_only.get("model_scoring_executed") is True,
        "score_only_unsorted": score_only.get("score_sort_executed") is False,
        "anchor_schema": anchor.get("schema_version")
        == "run287-current-score-stack-audit-v1",
        "anchor_ready": anchor.get("status")
        == "READY_CURRENT_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
        "anchor_passed": anchor.get("score_stack_audit_passed") is True,
        "anchor_adaptive": anchor.get("adaptive_ensemble_executed") is True,
        "all_ranking_disabled": all(
            item.get("decision_ranking_allowed") is False
            for item in (decision, score_only, anchor)
        ),
        "all_selector_disabled": all(
            item.get("selector_executed") is False
            for item in (decision, score_only, anchor)
        ),
        "all_backtest_disabled": all(
            item.get("backtest_executed") is False
            for item in (decision, score_only, anchor)
        ),
        "all_fullrun_disabled": all(
            item.get("fullrun_executed") is False
            for item in (decision, score_only, anchor)
        ),
        "future_feature_rows_zero": int(
            decision_coverage.get("future_feature_row_count") or 0
        )
        == 0,
        "scaled_features_finite": float(
            decision_coverage.get("scaled_model_feature_finite_ratio") or 0.0
        )
        == 1.0,
    }
    failures.extend(
        f"manifest_relation:{name}" for name, passed in relations.items() if not passed
    )
    failures.extend(
        f"upstream_contract:{name}" for name, passed in checks.items() if not passed
    )
    current_dates = {
        checkpoint.clean_date(decision.get("valuation_price_cutoff_date")),
        checkpoint.clean_date(score_only.get("valuation_price_cutoff_date")),
        valuation_date,
    }
    if current_dates != {valuation_date}:
        failures.append("current_valuation_date_mismatch")
    available_from = utc_timestamp(decision.get("feature_available_from"))
    decision_time = utc_timestamp(decision.get("decision_time_utc"))
    if available_from is None or decision_time is None:
        failures.append("decision_time_or_feature_available_from_invalid")
    elif available_from > decision_time:
        failures.append("future_feature_leakage")

    verified_paths: dict[str, Path] = {}
    for label, section, name in (
        ("scaled_model_input", "outputs", "scaled_model_input"),
        ("selection_context", "outputs", "selection_context"),
        ("ticker_feature_coverage", "outputs", "ticker_feature_coverage"),
        ("model_meta", "source_inputs", "model_meta"),
    ):
        verify_owner_record(
            label=label,
            owner_path=decision_path,
            owner=decision,
            section=section,
            name=name,
            verified_paths=verified_paths,
            input_audits=input_audits,
            failures=failures,
        )
    verify_owner_record(
        label="linear_predictions",
        owner_path=score_only_path,
        owner=score_only,
        section="outputs",
        name="ticker_order_model_predictions",
        verified_paths=verified_paths,
        input_audits=input_audits,
        failures=failures,
    )
    anchor_inputs = anchor.get("source_inputs") or {}
    for label in ANCHOR_ARTIFACTS:
        path, audit = direct_record(anchor_path, anchor_inputs.get(label) or {}, label)
        verified_paths[label] = path
        input_audits[label] = audit
        if audit.get("hash_matches") is not True:
            failures.append(f"input_hash_mismatch:{label}")
    anchor_model_meta = anchor_inputs.get("model_meta") or {}
    if anchor_model_meta.get("sha256") != input_audits.get("model_meta", {}).get(
        "sha256"
    ):
        failures.append("frozen_anchor_model_meta_mismatch")
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    scaled = pd.read_parquet(verified_paths["scaled_model_input"])
    context = pd.read_parquet(verified_paths["selection_context"])
    ticker_coverage = pd.read_csv(
        verified_paths["ticker_feature_coverage"], low_memory=False
    )
    linear = pd.read_csv(verified_paths["linear_predictions"], low_memory=False)
    ticker_audit = pd.read_csv(
        verified_paths["verifier_ticker_audit"], low_memory=False
    )
    model_meta = checkpoint.read_json(verified_paths["model_meta"])
    model_bundle = checkpoint.read_json(verified_paths["model_bundle"])
    scored_oos = pd.read_parquet(verified_paths["scored_oos"])
    model_features = [str(value) for value in model_meta.get("model_features") or []]
    expected_rows = int(args.expected_context_count)
    expected_features = int(args.expected_model_feature_count)

    frames = {
        "scaled_model_input": scaled,
        "selection_context": context,
        "ticker_feature_coverage": ticker_coverage,
        "linear_predictions": linear,
    }
    for label, frame in frames.items():
        if "ticker" not in frame or len(frame) != expected_rows:
            failures.append(f"row_or_ticker_contract:{label}")
        elif frame["ticker"].duplicated().any():
            failures.append(f"duplicate_ticker:{label}")
    if int(decision_coverage.get("decision_ticker_count") or -1) != expected_rows:
        failures.append("manifest_ticker_count_mismatch")
    if len(model_features) != expected_features:
        failures.append("model_feature_count_mismatch")
    if list(scaled.columns) != ["ticker", *model_features]:
        failures.append("scaled_schema_order_mismatch")
    if any(column not in linear for column in LINEAR_COLUMNS):
        failures.append("linear_prediction_schema_missing")
    if not failures:
        orders = [normalized_tickers(frame["ticker"]).tolist() for frame in frames.values()]
        if any(order != orders[0] for order in orders[1:]):
            failures.append("ticker_order_mismatch")
    matrix = scaled.reindex(columns=model_features).apply(
        pd.to_numeric, errors="coerce"
    ).to_numpy(dtype=float)
    if matrix.shape != (expected_rows, expected_features) or not np.isfinite(matrix).all():
        failures.append("scaled_matrix_contract")
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    from catboost import CatBoostClassifier, CatBoostRegressor

    regressor = CatBoostRegressor()
    classifier = CatBoostClassifier()
    regressor.load_model(str(verified_paths["cat_reg"]))
    classifier.load_model(str(verified_paths["cat_cls"]))
    if len(regressor.get_feature_importance()) != expected_features:
        failures.append("cat_reg_feature_count_mismatch")
    if len(classifier.get_feature_importance()) != expected_features:
        failures.append("cat_cls_feature_count_mismatch")
    pred_cat_ret = np.asarray(regressor.predict(matrix), dtype=float)
    pred_cat_p = np.asarray(classifier.predict_proba(matrix)[:, 1], dtype=float)
    chunk_size = max(int(args.chunk_size), 1)
    chunk_reg = np.concatenate(
        [
            regressor.predict(matrix[start : start + chunk_size])
            for start in range(0, len(matrix), chunk_size)
        ]
    )
    chunk_cls = np.concatenate(
        [
            classifier.predict_proba(matrix[start : start + chunk_size])[:, 1]
            for start in range(0, len(matrix), chunk_size)
        ]
    )
    cat_parity_rows: list[dict[str, Any]] = []
    for name, batch, chunk in (
        ("pred_cat_ret", pred_cat_ret, chunk_reg),
        ("pred_cat_p", pred_cat_p, chunk_cls),
    ):
        error = float(np.max(np.abs(batch - chunk)))
        passed = bool(
            np.isfinite(batch).all()
            and np.isfinite(chunk).all()
            and error <= float(args.parity_tolerance)
        )
        cat_parity_rows.append(
            {
                "output": name,
                "batch_row_count": len(batch),
                "chunk_size": chunk_size,
                "max_absolute_error": error,
                "parity_tolerance": float(args.parity_tolerance),
                "batch_chunk_parity_pass": passed,
            }
        )
        if not passed:
            failures.append(f"catboost_batch_chunk_parity:{name}")

    predictions = linear[["ticker", *LINEAR_COLUMNS]].copy()
    predictions["ticker"] = normalized_tickers(predictions["ticker"])
    predictions["pred_cat_ret"] = pred_cat_ret
    predictions["pred_cat_p"] = pred_cat_p
    predictions["pred_rank"] = 0.0
    activity_rows = prediction_activity_rows(
        predictions, float(args.parity_tolerance)
    )
    for row in activity_rows:
        if not row["nonzero_nonconstant_pass"]:
            failures.append(f"prediction_inactive:{row['prediction']}")

    cfg = EngineConfig()
    adaptive_state = compute_adaptive_ensemble_state(
        scored_oos, cfg, as_of_date=pd.Timestamp(valuation_date)
    )
    fallback_used = False
    if not adaptive_state.get("active"):
        diagnostics = model_bundle.get("adaptive_ensemble_diagnostics") or {}
        adaptive_state = {
            "weights": model_bundle.get("adaptive_ensemble_weights") or {},
            "quality": diagnostics.get("quality") or {},
            "history_months": int(diagnostics.get("history_months") or 0),
            "active": bool(diagnostics.get("active")),
        }
        fallback_used = True
    stored_weights = model_bundle.get("adaptive_ensemble_weights") or {}
    weight_error = max(
        abs(
            float((adaptive_state.get("weights") or {}).get(name, 0.0))
            - float(stored_weights.get(name, 0.0))
        )
        for name in ("linear", "catboost", "ranker")
    )
    if weight_error > float(args.parity_tolerance):
        failures.append("adaptive_ensemble_weight_mismatch")
    if not bool(adaptive_state.get("active")):
        failures.append("adaptive_ensemble_inactive")

    first, first_logs = execute_stack(
        context,
        predictions,
        cfg,
        adaptive_state,
        model_bundle.get("regime_ensemble_weights") or {},
    )
    second, second_logs = execute_stack(
        context,
        predictions,
        cfg,
        adaptive_state,
        model_bundle.get("regime_ensemble_weights") or {},
    )
    stack_parity_rows = compare_frames(
        first, second, PARITY_COLUMNS, float(args.parity_tolerance)
    )
    if not all(bool(row["parity_pass"]) for row in stack_parity_rows):
        failures.append("registered_score_stack_nondeterministic")

    passthrough_rows = compare_frames(
        first,
        predictions,
        ACTIVE_PREDICTION_COLUMNS,
        float(args.parity_tolerance),
    )
    if not all(bool(row["parity_pass"]) for row in passthrough_rows):
        failures.append("fresh_prediction_passthrough_mismatch")
    eligible_before_quarantine = first["ranking_eligible"].map(checkpoint.boolish)
    ticker_audit["ticker"] = normalized_tickers(ticker_audit["ticker"])
    quarantine_tickers = set(
        ticker_audit.loc[
            ticker_audit["corporate_action_quarantine"].map(checkpoint.boolish),
            "ticker",
        ]
    )
    quarantined = normalized_tickers(first["ticker"]).isin(quarantine_tickers)
    first["registered_ranking_eligible"] = eligible_before_quarantine
    first["corporate_action_quarantine"] = quarantined
    first["research_eligible_after_quarantine"] = (
        eligible_before_quarantine & ~quarantined
    )
    first["decision_feature_complete"] = False
    first["decision_ranking_allowed"] = False
    registered_eligible_count = int(eligible_before_quarantine.sum())
    research_eligible_count = int(first["research_eligible_after_quarantine"].sum())
    if normalized_tickers(first["ticker"]).tolist() != normalized_tickers(
        scaled["ticker"]
    ).tolist():
        failures.append("score_stack_ticker_order_changed")
    if not np.isfinite(pd.to_numeric(first["score"], errors="coerce")).all():
        failures.append("score_nonfinite")
    if not source_files_unchanged(input_audits):
        failures.append("verified_source_file_mutated")
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    output_columns = [
        "ticker",
        *PREDICTION_COLUMNS,
        "score_linear",
        "score_cat",
        "score_ranker",
        "risk_penalty",
        "overheat_penalty",
        "score_model_core",
        "score_core",
        "score",
        "core_fundamental_fields_present",
        "core_fundamental_minimum_pass",
        "future_winner_fundamental_pass",
        "early_scout_fundamental_pass",
        "fundamental_lane_label",
        "portfolio_sleeve_label",
        "portfolio_candidate_gate_label",
        "registered_ranking_eligible",
        "corporate_action_quarantine",
        "research_eligible_after_quarantine",
        "decision_feature_complete",
        "decision_ranking_allowed",
    ]
    stack_output = first[
        [column for column in output_columns if column in first]
    ].copy()
    summary_rows: list[dict[str, Any]] = []
    for column in (
        "pred_lin_ret",
        "pred_lin_p",
        "pred_future_winner_ret",
        "pred_future_winner_p",
        "pred_cat_ret",
        "pred_cat_p",
        "score_linear",
        "score_cat",
        "risk_penalty",
        "score",
    ):
        values = pd.to_numeric(stack_output[column], errors="coerce")
        summary_rows.append(
            {
                "column": column,
                "row_count": len(values),
                "minimum": float(values.min()),
                "q25": float(values.quantile(0.25)),
                "median": float(values.median()),
                "mean": float(values.mean()),
                "q75": float(values.quantile(0.75)),
                "maximum": float(values.max()),
                "standard_deviation": float(values.std(ddof=0)),
            }
        )
    eligibility_summary = (
        first.groupby(
            ["portfolio_sleeve_label", "portfolio_candidate_gate_label"],
            dropna=False,
        )
        .agg(
            ticker_count=("ticker", "size"),
            registered_eligible_count=("registered_ranking_eligible", "sum"),
            research_eligible_after_quarantine_count=(
                "research_eligible_after_quarantine",
                "sum",
            ),
        )
        .reset_index()
    )
    adaptive_audit = pd.DataFrame(
        [
            {
                "active": bool(adaptive_state.get("active")),
                "history_months": int(adaptive_state.get("history_months") or 0),
                "linear_weight": float(
                    (adaptive_state.get("weights") or {}).get("linear", 0.0)
                ),
                "catboost_weight": float(
                    (adaptive_state.get("weights") or {}).get("catboost", 0.0)
                ),
                "ranker_weight": float(
                    (adaptive_state.get("weights") or {}).get("ranker", 0.0)
                ),
                "stored_weight_max_absolute_error": weight_error,
                "model_bundle_fallback_used": fallback_used,
            }
        ]
    )
    frames_out = {
        "ticker_order_score_stack": stack_output,
        "prediction_activity_audit": pd.DataFrame(activity_rows),
        "fresh_prediction_passthrough_audit": pd.DataFrame(passthrough_rows),
        "catboost_head_parity_audit": pd.DataFrame(cat_parity_rows),
        "registered_stack_determinism_audit": pd.DataFrame(stack_parity_rows),
        "adaptive_ensemble_audit": adaptive_audit,
        "score_distribution_summary": pd.DataFrame(summary_rows),
        "eligibility_summary": eligibility_summary,
    }
    outputs: dict[str, Any] = {}
    for name, frame in frames_out.items():
        path = output_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        outputs[name] = {**checkpoint.fingerprint(path), "row_count": int(len(frame))}

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "contract_failures": [],
        "blockers": [
            "decision_feature_complete_false",
            "score_sort_and_rank_assignment_not_run",
            "top_n_and_selector_not_run",
            "portfolio_sizing_and_target_books_not_run",
            "historical_cagr_mdd_evidence_unchanged",
            "pit_universe_membership_not_clean",
            "corporate_action_quarantine_carried_from_frozen_anchor:"
            + ",".join(sorted(quarantine_tickers)),
        ],
        "valuation_price_cutoff_date": valuation_date,
        "decision_time_utc": decision.get("decision_time_utc"),
        "feature_available_from": decision.get("feature_available_from"),
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "score_stack_audit_passed": True,
        "model_scoring_executed": True,
        "catboost_scoring_executed": True,
        "adaptive_ensemble_executed": True,
        "stale_prediction_columns_removed_before_join": True,
        "fresh_prediction_passthrough_verified": True,
        "ranking_eligibility_computed": True,
        "decision_feature_complete": False,
        "decision_ranking_allowed": False,
        "score_sort_executed": False,
        "rank_assignment_executed": False,
        "top_n_executed": False,
        "selector_executed": False,
        "target_book_generation_allowed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "pit_universe_label_clean": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "coverage": {
            "ticker_count": len(first),
            "model_feature_count": len(model_features),
            "active_prediction_head_count": sum(
                bool(row["nonzero_nonconstant_pass"]) for row in activity_rows
            ),
            "active_prediction_head_required_count": len(ACTIVE_PREDICTION_COLUMNS),
            "prediction_passthrough_pass_count": sum(
                bool(row["parity_pass"]) for row in passthrough_rows
            ),
            "prediction_passthrough_required_count": len(passthrough_rows),
            "registered_eligible_ticker_count": registered_eligible_count,
            "research_eligible_after_quarantine_count": research_eligible_count,
            "corporate_action_quarantine_ticker_count": len(quarantine_tickers),
            "catboost_head_parity_pass_count": sum(
                bool(row["batch_chunk_parity_pass"]) for row in cat_parity_rows
            ),
            "registered_stack_determinism_pass_count": sum(
                bool(row["parity_pass"]) for row in stack_parity_rows
            ),
            "registered_stack_determinism_check_count": len(stack_parity_rows),
        },
        "engine_contract": {
            "engine_artifact_anchor_valuation_date": anchor.get(
                "valuation_price_cutoff_date"
            ),
            "engine_artifact_anchor_status": anchor.get("status"),
            "strict_live_backtest_alignment": bool(
                cfg.strict_live_backtest_alignment
            ),
            "latest_only_satellite_included": not bool(
                cfg.strict_live_backtest_alignment
            ),
            "adaptive_ensemble_active": bool(adaptive_state.get("active")),
            "adaptive_history_months": int(
                adaptive_state.get("history_months") or 0
            ),
            "adaptive_model_bundle_fallback_used": fallback_used,
            "captured_engine_log_lines": first_logs,
            "second_run_log_lines_match": first_logs == second_logs,
            "frozen_corporate_action_quarantine_tickers": sorted(
                quarantine_tickers
            ),
        },
        "recommended_next_step": (
            "run a separate no-write Main/Concentrated selector audit over this "
            "immutable eligible ticker-order output; compare targets and turnover "
            "at 25/50/100 bps, but do not write books, backtest, run fullrun, or trade"
        ),
        "source_inputs": input_audits,
        "source_immutability": {"all_verified_files_unchanged": True},
        "outputs": outputs,
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {
            "git_head": git_head(),
            "builder": checkpoint.fingerprint(Path(__file__)),
        },
    }
    checkpoint.write_json(output_dir / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-frame-manifest", required=True)
    parser.add_argument("--expected-decision-frame-sha256", required=True)
    parser.add_argument("--score-only-manifest", required=True)
    parser.add_argument("--expected-score-only-sha256", required=True)
    parser.add_argument("--frozen-score-stack-manifest", required=True)
    parser.add_argument("--expected-frozen-score-stack-sha256", required=True)
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument("--expected-context-count", type=int, required=True)
    parser.add_argument("--expected-model-feature-count", type=int, required=True)
    parser.add_argument("--chunk-size", type=int, default=137)
    parser.add_argument("--parity-tolerance", type=float, default=1e-12)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
