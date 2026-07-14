#!/usr/bin/env python3
"""Audit the registered current score stack without ranking or selecting.

The tool requires a verified full selection context and the prior four-linear-
head dry-run.  It verifies the pinned CatBoost heads by batch/chunk parity,
reconstructs the registered adaptive ensemble and eligibility annotations twice
for deterministic parity, and emits rows in original ticker order.  It never
sorts by score, assigns a rank, chooses top-N, sizes, backtests, runs fullrun,
changes target books, or enables production/live trading.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
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
from r1000_pipeline import (  # noqa: E402
    add_core_fundamental_minimum_flags,
    add_model_score_columns,
    add_total_score_columns,
    apply_adaptive_ensemble_state,
    apply_focus_score_overlay,
    apply_latest_ranking_eligibility,
    apply_latest_sentiment_satellite_overlay,
    compute_adaptive_ensemble_state,
    compute_portfolio_sleeve_columns,
)
from tools import stage_run287_price_batch as checkpoint  # noqa: E402


SCHEMA_VERSION = "run287-current-score-stack-audit-v1"
PREDICTION_COLUMNS = [
    "pred_lin_ret",
    "pred_lin_p",
    "pred_future_winner_ret",
    "pred_future_winner_p",
    "pred_cat_ret",
    "pred_cat_p",
    "pred_rank",
]
PARITY_COLUMNS = [
    "pred_cat_ret",
    "pred_cat_p",
    "score_linear",
    "score_cat",
    "score_ranker",
    "risk_penalty",
    "score",
    "core_fundamental_minimum_pass",
    "future_winner_fundamental_pass",
    "early_scout_fundamental_pass",
    "portfolio_sleeve_label",
    "portfolio_candidate_gate_label",
    "ranking_eligible",
]


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return ""


def expected_input(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    audit = checkpoint.fingerprint(path)
    expected = str(expected_sha256 or "").lower().strip()
    audit.update(
        {
            "label": label,
            "expected_sha256": expected or None,
            "hash_matches": bool(
                expected and str(audit.get("sha256") or "").lower() == expected
            ),
        }
    )
    return audit


def manifest_record(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    section: str,
    name: str,
) -> tuple[Path, dict[str, Any]]:
    record = (manifest.get(section) or {}).get(name) or {}
    return checkpoint.verify_record(record, manifest_path, label=name)


def direct_record(
    manifest_path: Path,
    record: Mapping[str, Any],
    label: str,
) -> tuple[Path, dict[str, Any]]:
    return checkpoint.verify_record(record, manifest_path, label=label)


def source_files_unchanged(input_audits: Mapping[str, Mapping[str, Any]]) -> bool:
    return all(
        checkpoint.fingerprint(Path(str(audit.get("path") or ""))).get("sha256")
        == audit.get("sha256")
        for audit in input_audits.values()
        if audit.get("path") and audit.get("exists")
    )


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
        "status": "BLOCKED_CURRENT_SCORE_STACK_AUDIT",
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


def compare_frames(
    left: pd.DataFrame,
    right: pd.DataFrame,
    columns: list[str],
    tolerance: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for column in columns:
        if column not in left.columns or column not in right.columns:
            rows.append(
                {
                    "column": column,
                    "kind": "missing",
                    "max_absolute_error": np.nan,
                    "mismatch_count": len(left),
                    "parity_pass": False,
                }
            )
            continue
        left_numeric = pd.to_numeric(left[column], errors="coerce").astype(float)
        right_numeric = pd.to_numeric(right[column], errors="coerce").astype(float)
        numeric_candidate = bool(left_numeric.notna().any() or right_numeric.notna().any())
        if numeric_candidate:
            both_nan = left_numeric.isna() & right_numeric.isna()
            difference = (left_numeric - right_numeric).abs()
            matches = both_nan | difference.le(tolerance)
            max_error = float(difference.dropna().max()) if difference.notna().any() else 0.0
            mismatch_count = int((~matches).sum())
            kind = "numeric"
        else:
            left_text = left[column].fillna("").astype(str)
            right_text = right[column].fillna("").astype(str)
            mismatch_count = int(left_text.ne(right_text).sum())
            max_error = 0.0
            kind = "categorical"
        rows.append(
            {
                "column": column,
                "kind": kind,
                "max_absolute_error": max_error,
                "mismatch_count": mismatch_count,
                "parity_pass": mismatch_count == 0,
            }
        )
    return rows


def execute_stack(
    selection_context: pd.DataFrame,
    predictions: pd.DataFrame,
    cfg: EngineConfig,
    adaptive_state: Mapping[str, Any],
    regime_weights: Mapping[str, Any] | None,
) -> tuple[pd.DataFrame, list[str]]:
    frame = selection_context.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    prediction_frame = predictions.copy()
    prediction_frame["ticker"] = (
        prediction_frame["ticker"].astype(str).str.upper().str.strip()
    )
    frame = frame.merge(
        prediction_frame[["ticker", *PREDICTION_COLUMNS]],
        on="ticker",
        how="left",
        validate="one_to_one",
        sort=False,
    )
    original_order = selection_context["ticker"].astype(str).str.upper().str.strip().tolist()
    frame = frame.set_index("ticker").loc[original_order].reset_index()
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        frame = add_core_fundamental_minimum_flags(frame, cfg)
        frame = add_model_score_columns(
            frame,
            {
                "lin_ret": "pred_lin_ret",
                "lin_p": "pred_lin_p",
                "cat_ret": "pred_cat_ret",
                "cat_p": "pred_cat_p",
                "rank": "pred_rank",
            },
            cfg=cfg,
        )
        frame = apply_adaptive_ensemble_state(
            frame,
            dict(adaptive_state),
            regime_weights=dict(regime_weights or {}) or None,
        )
        frame = add_total_score_columns(
            frame,
            cfg,
            include_satellite=True,
            include_latest_only_satellite=not bool(cfg.strict_live_backtest_alignment),
        )
        frame = apply_focus_score_overlay(frame, cfg)
        frame = apply_latest_sentiment_satellite_overlay(frame, cfg)
        frame = compute_portfolio_sleeve_columns(frame, cfg)
        frame = apply_latest_ranking_eligibility(
            frame, cfg, context="Run287 non-ranking score-stack audit"
        )
    return frame, [line for line in captured.getvalue().splitlines() if line.strip()]


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = checkpoint.repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    valuation_date = checkpoint.clean_date(args.valuation_date)
    verifier_path = checkpoint.repo_path(args.verifier_manifest)
    feature_path = checkpoint.repo_path(args.feature_manifest)
    linear_path = checkpoint.repo_path(args.linear_dryrun_manifest)
    input_audits = {
        "verifier_manifest": expected_input(
            verifier_path, args.expected_verifier_sha256, "verifier_manifest"
        ),
        "feature_manifest": expected_input(
            feature_path, args.expected_feature_sha256, "feature_manifest"
        ),
        "linear_dryrun_manifest": expected_input(
            linear_path, args.expected_linear_dryrun_sha256, "linear_dryrun_manifest"
        ),
    }
    failures = [
        f"input_hash_mismatch:{name}"
        for name, audit in input_audits.items()
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

    verifier = checkpoint.read_json(verifier_path)
    feature = checkpoint.read_json(feature_path)
    linear = checkpoint.read_json(linear_path)
    relations = {
        "verifier_feature": (
            (verifier.get("source_inputs") or {}).get("feature_manifest") or {}
        ).get("sha256")
        == input_audits["feature_manifest"].get("sha256"),
        "linear_feature": (
            (linear.get("source_inputs") or {}).get("feature_manifest") or {}
        ).get("sha256")
        == input_audits["feature_manifest"].get("sha256"),
        "linear_verifier": (
            (linear.get("source_inputs") or {}).get("verifier_manifest") or {}
        ).get("sha256")
        == input_audits["verifier_manifest"].get("sha256"),
    }
    failures.extend(
        f"manifest_relation:{name}" for name, passed in relations.items() if not passed
    )
    contract_checks = {
        "verifier_ready": verifier.get("status")
        == "READY_COMPLETE_CURRENT_CROSS_SECTION_NONRANKING",
        "verifier_passed": verifier.get("complete_cross_section_verification_passed")
        is True,
        "linear_ready": linear.get("status")
        == "READY_CURRENT_MODEL_SCORE_DRYRUN_NONRANKING",
        "linear_scored": linear.get("model_scoring_executed") is True,
        "linear_unsorted": linear.get("score_sort_executed") is False,
        "linear_no_rank": linear.get("decision_ranking_allowed") is False,
        "feature_assembled": feature.get("status")
        == "CURRENT_CROSS_SECTION_ASSEMBLED_VERIFICATION_REQUIRED",
        "feature_no_rank": feature.get("decision_ranking_allowed") is False,
    }
    failures.extend(
        f"upstream_contract:{name}"
        for name, passed in contract_checks.items()
        if not passed
    )
    dates = {
        checkpoint.clean_date(item.get("valuation_price_cutoff_date"))
        for item in (verifier, feature, linear)
    } | {valuation_date}
    if dates != {valuation_date}:
        failures.append("valuation_date_mismatch:" + ",".join(sorted(dates)))

    record_specs = [
        (
            "selection_context",
            feature_path,
            feature,
            "outputs",
            "pilot_selection_context",
        ),
        ("raw_feature_frame", feature_path, feature, "outputs", "pilot_feature_frame"),
        ("scaled_input", feature_path, feature, "outputs", "pilot_scaled_model_input"),
        ("model_meta", feature_path, feature, "source_inputs", "model_meta"),
        ("preflight_manifest", feature_path, feature, "source_inputs", "preflight_manifest"),
        (
            "linear_predictions",
            linear_path,
            linear,
            "outputs",
            "ticker_order_model_predictions",
        ),
        (
            "verifier_ticker_audit",
            verifier_path,
            verifier,
            "outputs",
            "cross_section_ticker_audit",
        ),
    ]
    verified_paths: dict[str, Path] = {}
    for label, owner_path, owner, section, name in record_specs:
        path, audit = manifest_record(owner_path, owner, section, name)
        verified_paths[label] = path
        input_audits[label] = audit
        if audit.get("hash_matches") is not True:
            failures.append(f"input_hash_mismatch:{label}")
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    preflight_path = verified_paths["preflight_manifest"]
    preflight = checkpoint.read_json(preflight_path)
    nested_specs = {
        "cat_reg": (preflight.get("model_artifacts") or {}).get("files", {}).get("cat_reg") or {},
        "cat_cls": (preflight.get("model_artifacts") or {}).get("files", {}).get("cat_cls") or {},
        "model_bundle": (preflight.get("model_artifacts") or {}).get("files", {}).get("model_bundle") or {},
        "scored_oos": (preflight.get("engine_artifacts") or {}).get("scored_oos") or {},
    }
    for label, record in nested_specs.items():
        path, audit = direct_record(preflight_path, record, label)
        verified_paths[label] = path
        input_audits[label] = audit
        if audit.get("hash_matches") is not True:
            failures.append(f"input_hash_mismatch:{label}")
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    selection = pd.read_parquet(verified_paths["selection_context"])
    raw_frame = pd.read_parquet(verified_paths["raw_feature_frame"])
    scaled = pd.read_parquet(verified_paths["scaled_input"])
    linear_predictions = pd.read_csv(verified_paths["linear_predictions"], low_memory=False)
    ticker_audit = pd.read_csv(verified_paths["verifier_ticker_audit"], low_memory=False)
    model_meta = checkpoint.read_json(verified_paths["model_meta"])
    model_bundle = checkpoint.read_json(verified_paths["model_bundle"])
    scored_oos = pd.read_parquet(verified_paths["scored_oos"])
    model_features = [str(value) for value in model_meta.get("model_features") or []]
    expected_rows = int(args.expected_context_count)
    expected_features = int(args.expected_model_feature_count)
    frames = {
        "selection_context": selection,
        "raw_feature_frame": raw_frame,
        "scaled_input": scaled,
        "linear_predictions": linear_predictions,
    }
    for name, frame in frames.items():
        if len(frame) != expected_rows or "ticker" not in frame.columns:
            failures.append(f"row_or_ticker_contract:{name}")
        elif frame["ticker"].duplicated().any():
            failures.append(f"duplicate_ticker:{name}")
    if len(model_features) != expected_features:
        failures.append("model_feature_count_mismatch")
    if list(scaled.columns) != ["ticker", *model_features]:
        failures.append("scaled_schema_order_mismatch")
    ticker_orders = [
        frame["ticker"].astype(str).str.upper().str.strip().tolist()
        for frame in frames.values()
    ]
    if any(order != ticker_orders[0] for order in ticker_orders[1:]):
        failures.append("ticker_order_mismatch")
    selection_raw = selection.reindex(columns=model_features).apply(
        pd.to_numeric, errors="coerce"
    )
    persisted_raw = raw_frame.reindex(columns=model_features).apply(
        pd.to_numeric, errors="coerce"
    )
    raw_equal = (
        (selection_raw.isna() & persisted_raw.isna())
        | (selection_raw - persisted_raw).abs().le(float(args.parity_tolerance))
    )
    if not raw_equal.to_numpy().all():
        failures.append("selection_context_raw_model_mismatch")
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
        [regressor.predict(matrix[start : start + chunk_size]) for start in range(0, len(matrix), chunk_size)]
    )
    chunk_cls = np.concatenate(
        [
            classifier.predict_proba(matrix[start : start + chunk_size])[:, 1]
            for start in range(0, len(matrix), chunk_size)
        ]
    )
    cat_parity_rows = []
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

    predictions = linear_predictions[
        [
            "ticker",
            "pred_lin_ret",
            "pred_lin_p",
            "pred_future_winner_ret",
            "pred_future_winner_p",
        ]
    ].copy()
    predictions["pred_cat_ret"] = pred_cat_ret
    predictions["pred_cat_p"] = pred_cat_p
    predictions["pred_rank"] = 0.0
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
        abs(float((adaptive_state.get("weights") or {}).get(name, 0.0)) - float(stored_weights.get(name, 0.0)))
        for name in ("linear", "catboost", "ranker")
    )
    if weight_error > float(args.parity_tolerance):
        failures.append("adaptive_ensemble_weight_mismatch")
    if not bool(adaptive_state.get("active")):
        failures.append("adaptive_ensemble_inactive")

    first, first_logs = execute_stack(
        selection,
        predictions,
        cfg,
        adaptive_state,
        model_bundle.get("regime_ensemble_weights") or {},
    )
    second, second_logs = execute_stack(
        selection,
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
    eligible_before_quarantine = first["ranking_eligible"].map(checkpoint.boolish)
    ticker_audit["ticker"] = ticker_audit["ticker"].astype(str).str.upper().str.strip()
    quarantine_tickers = set(
        ticker_audit.loc[
            ticker_audit["corporate_action_quarantine"].map(checkpoint.boolish),
            "ticker",
        ]
    )
    quarantined = first["ticker"].astype(str).str.upper().str.strip().isin(quarantine_tickers)
    first["registered_ranking_eligible"] = eligible_before_quarantine
    first["corporate_action_quarantine"] = quarantined
    first["research_eligible_after_quarantine"] = eligible_before_quarantine & ~quarantined
    first["decision_ranking_allowed"] = False
    registered_eligible_count = int(eligible_before_quarantine.sum())
    research_eligible_count = int(first["research_eligible_after_quarantine"].sum())
    if registered_eligible_count != int(args.expected_registered_eligible_count):
        failures.append(
            f"registered_eligible_count:{registered_eligible_count}!="
            f"{int(args.expected_registered_eligible_count)}"
        )
    if first["ticker"].astype(str).str.upper().str.strip().tolist() != ticker_orders[0]:
        failures.append("score_stack_ticker_order_changed")
    if not np.isfinite(pd.to_numeric(first["score"], errors="coerce")).all():
        failures.append("score_nonfinite")
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
        "decision_ranking_allowed",
    ]
    output_columns = [column for column in output_columns if column in first.columns]
    stack_output = first[output_columns].copy()
    summary_rows = []
    for column in (
        "pred_lin_ret",
        "pred_lin_p",
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
                "linear_weight": float((adaptive_state.get("weights") or {}).get("linear", 0.0)),
                "catboost_weight": float((adaptive_state.get("weights") or {}).get("catboost", 0.0)),
                "ranker_weight": float((adaptive_state.get("weights") or {}).get("ranker", 0.0)),
                "stored_weight_max_absolute_error": weight_error,
                "model_bundle_fallback_used": fallback_used,
            }
        ]
    )
    frames_out = {
        "ticker_order_score_stack": stack_output,
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
        outputs[name] = {
            **checkpoint.fingerprint(path),
            "row_count": int(len(frame)),
        }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_CURRENT_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
        "contract_failures": [],
        "blockers": [
            "score_sort_and_rank_assignment_not_run",
            "top_n_and_selector_not_run",
            "portfolio_sizing_and_target_books_not_run",
            "historical_cagr_mdd_evidence_unchanged",
            "pit_universe_membership_not_clean",
            "corporate_action_quarantine:" + ",".join(sorted(quarantine_tickers)),
        ],
        "valuation_price_cutoff_date": valuation_date,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "score_stack_audit_passed": True,
        "model_scoring_executed": True,
        "catboost_scoring_executed": True,
        "adaptive_ensemble_executed": True,
        "ranking_eligibility_computed": True,
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
            "strict_live_backtest_alignment": bool(cfg.strict_live_backtest_alignment),
            "latest_only_satellite_included": not bool(cfg.strict_live_backtest_alignment),
            "adaptive_ensemble_active": bool(adaptive_state.get("active")),
            "adaptive_history_months": int(adaptive_state.get("history_months") or 0),
            "adaptive_model_bundle_fallback_used": fallback_used,
            "captured_engine_log_lines": first_logs,
            "second_run_log_lines_match": first_logs == second_logs,
        },
        "recommended_next_step": (
            "audit the Main and Concentrated selector functions in a no-write lane "
            "using only the registered eligible set; compare against prior targets, "
            "but do not size, emit target books, backtest or trade"
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
    parser.add_argument("--verifier-manifest", required=True)
    parser.add_argument("--expected-verifier-sha256", required=True)
    parser.add_argument("--feature-manifest", required=True)
    parser.add_argument("--expected-feature-sha256", required=True)
    parser.add_argument("--linear-dryrun-manifest", required=True)
    parser.add_argument("--expected-linear-dryrun-sha256", required=True)
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument("--expected-context-count", type=int, required=True)
    parser.add_argument("--expected-model-feature-count", type=int, required=True)
    parser.add_argument("--expected-registered-eligible-count", type=int, required=True)
    parser.add_argument("--chunk-size", type=int, default=137)
    parser.add_argument("--parity-tolerance", type=float, default=1e-12)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") in {
        "READY_CURRENT_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
        "BLOCKED_CURRENT_SCORE_STACK_AUDIT",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
