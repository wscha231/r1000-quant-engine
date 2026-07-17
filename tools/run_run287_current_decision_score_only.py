#!/usr/bin/env python3
"""Score one verified Run287 current-decision frame without ranking or selection.

This lane consumes exactly one hash-pinned current-decision manifest and the
scaled matrix/model metadata named by that manifest.  It runs only the four
frozen linear heads and independently checks every prediction against the
registered engine helpers.  It preserves source ticker order and emits
diagnostics only: no score sort, rank, top-N, selector, sizing, backtest,
fullrun, target-book write, production action, or live trade is allowed.
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

from r1000_pipeline import (  # noqa: E402
    logreg_predict_proba_from_meta,
    ridge_predict_from_meta,
)
from tools import stage_run287_price_batch as checkpoint  # noqa: E402
from tools.run_run287_current_model_score_dryrun import (  # noqa: E402
    HEADS,
    expected_input,
    git_head,
    independent_prediction,
    manifest_record,
    source_files_unchanged,
)


SCHEMA_VERSION = "run287-current-decision-score-only-v1"
READY_STATUS = "READY_CURRENT_DECISION_SCORE_ONLY_NONRANKING"
BLOCKED_STATUS = "BLOCKED_CURRENT_DECISION_SCORE_ONLY"
ALLOWED_DECISION_FRAME_SCHEMAS = frozenset(
    {
        "run287-current-decision-frame-v1",
        "run287-current-decision-frame-v2",
    }
)


def decision_frame_schema_supported(value: Any) -> bool:
    return str(value or "") in ALLOWED_DECISION_FRAME_SCHEMAS


def utc_timestamp(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


def normalized_tickers(values: pd.Series) -> pd.Series:
    return values.astype(str).str.upper().str.strip()


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
        "score_only": True,
        "model_scoring_executed": False,
        "decision_ranking_allowed": False,
        "score_sort_executed": False,
        "rank_executed": False,
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


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = checkpoint.repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")
    output_dir.mkdir(parents=True)

    valuation_date = checkpoint.clean_date(args.valuation_date)
    decision_path = checkpoint.repo_path(args.decision_frame_manifest)
    input_audits: dict[str, Any] = {
        "decision_frame_manifest": expected_input(
            decision_path,
            args.expected_decision_frame_sha256,
            "decision_frame_manifest",
        )
    }
    failures = [
        "input_hash_mismatch:decision_frame_manifest"
        for audit in input_audits.values()
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
    record_specs = [
        ("scaled_model_input", "outputs", "scaled_model_input"),
        ("selection_context", "outputs", "selection_context"),
        ("ticker_feature_coverage", "outputs", "ticker_feature_coverage"),
        ("model_meta", "source_inputs", "model_meta"),
    ]
    verified_paths: dict[str, Path] = {}
    for label, section, name in record_specs:
        path, audit = manifest_record(decision_path, decision, section, name)
        verified_paths[label] = path
        input_audits[label] = audit
        if audit.get("hash_matches") is not True:
            failures.append(f"input_hash_mismatch:{label}")

    coverage = decision.get("coverage") or {}
    decision_checks = {
        "schema": decision_frame_schema_supported(decision.get("schema_version")),
        "ready": decision.get("status") == "READY_COMPLETE_CURRENT_DECISION_FRAME",
        "current_data_complete": decision.get("current_decision_data_complete")
        is True,
        "scoring_prerequisite": decision.get(
            "research_model_scoring_prerequisite_passed"
        )
        is True,
        "ranking_disabled": decision.get("decision_ranking_allowed") is False,
        "selector_not_executed": decision.get("selector_executed") is False,
        "backtest_not_executed": decision.get("backtest_executed") is False,
        "fullrun_not_executed": decision.get("fullrun_executed") is False,
        "no_source_mutation": decision.get("source_inputs_mutated") is False,
        "no_target_book_mutation": decision.get("target_books_mutated") is False,
        "research_only": decision.get("research_only") is True,
        "production_disabled": decision.get("production_activation_allowed")
        is False,
        "live_disabled": decision.get("live_trading_enabled") is False,
        "future_feature_rows_zero": int(coverage.get("future_feature_row_count") or 0)
        == 0,
        "scaled_missing_neutral_violations_zero": int(
            coverage.get("scaled_missing_neutral_violation_count") or 0
        )
        == 0,
        "scaled_features_finite": float(
            coverage.get("scaled_model_feature_finite_ratio") or 0.0
        )
        == 1.0,
    }
    failures.extend(
        f"decision_frame_contract:{name}"
        for name, passed in decision_checks.items()
        if not passed
    )

    manifest_date = checkpoint.clean_date(
        decision.get("valuation_price_cutoff_date")
    )
    if {manifest_date, valuation_date} != {valuation_date}:
        failures.append(f"valuation_date_mismatch:{manifest_date}!={valuation_date}")
    available_from = utc_timestamp(decision.get("feature_available_from"))
    decision_time = utc_timestamp(decision.get("decision_time_utc"))
    if available_from is None or decision_time is None:
        failures.append("decision_time_or_feature_available_from_invalid")
    elif available_from > decision_time:
        failures.append("future_feature_leakage")

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
    model_meta = checkpoint.read_json(verified_paths["model_meta"])
    model_features = [str(value) for value in model_meta.get("model_features") or []]
    expected_rows = int(args.expected_context_count)
    expected_features = int(args.expected_model_feature_count)

    if int(coverage.get("decision_ticker_count") or -1) != expected_rows:
        failures.append("manifest_ticker_count_mismatch")
    if int(coverage.get("model_feature_count") or -1) != expected_features:
        failures.append("manifest_model_feature_count_mismatch")
    if len(model_features) != expected_features:
        failures.append(
            f"model_feature_count:{len(model_features)}!={expected_features}"
        )
    if list(scaled.columns) != ["ticker", *model_features]:
        failures.append("scaled_input_schema_order_mismatch")
    if "ticker" not in context or "ticker" not in ticker_coverage:
        failures.append("ticker_column_missing")
    if len(scaled) != expected_rows or scaled.get("ticker", pd.Series()).duplicated().any():
        failures.append("scaled_input_ticker_count_or_duplicate")
    if len(context) != expected_rows or context.get("ticker", pd.Series()).duplicated().any():
        failures.append("selection_context_ticker_count_or_duplicate")
    if len(ticker_coverage) != expected_rows or ticker_coverage.get(
        "ticker", pd.Series()
    ).duplicated().any():
        failures.append("ticker_coverage_count_or_duplicate")

    if not failures:
        scaled_tickers = normalized_tickers(scaled["ticker"])
        context_tickers = normalized_tickers(context["ticker"])
        coverage_tickers = normalized_tickers(ticker_coverage["ticker"])
        if scaled_tickers.tolist() != context_tickers.tolist():
            failures.append("selection_context_ticker_order_mismatch")
        if scaled_tickers.tolist() != coverage_tickers.tolist():
            failures.append("ticker_coverage_ticker_order_mismatch")

    matrix = scaled.reindex(columns=model_features).apply(
        pd.to_numeric, errors="coerce"
    ).to_numpy(dtype=float)
    if matrix.shape != (expected_rows, expected_features):
        failures.append("scaled_matrix_shape_mismatch")
    if not np.isfinite(matrix).all():
        failures.append("scaled_matrix_nonfinite")
    if bool(model_meta.get("ranking_enabled")):
        failures.append("frozen_model_meta_ranking_enabled")

    for output_name, (key, _) in HEADS.items():
        if output_name not in context:
            failures.append(f"prior_prediction_column_missing:{output_name}")
        spec = model_meta.get(key) or {}
        coefficient = np.asarray(spec.get("coef") or [], dtype=float)
        intercept = pd.to_numeric(
            pd.Series([spec.get("intercept")]), errors="coerce"
        ).iloc[0]
        if coefficient.shape != (expected_features,):
            failures.append(f"model_head_coefficient_shape:{key}")
        if not np.isfinite(coefficient).all() or not np.isfinite(intercept):
            failures.append(f"model_head_nonfinite:{key}")

    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    predictions: dict[str, np.ndarray] = {}
    parity_rows: list[dict[str, Any]] = []
    for output_name, (key, kind) in HEADS.items():
        independent = independent_prediction(matrix, model_meta, key, kind)
        engine = (
            ridge_predict_from_meta(matrix, model_meta, key=key)
            if kind == "ridge"
            else logreg_predict_proba_from_meta(matrix, model_meta, key=key)
        )
        difference = np.abs(independent - engine)
        max_error = float(difference.max()) if len(difference) else 0.0
        parity_pass = bool(
            np.isfinite(independent).all()
            and np.isfinite(engine).all()
            and max_error <= float(args.parity_tolerance)
        )
        parity_rows.append(
            {
                "output": output_name,
                "model_meta_key": key,
                "kind": kind,
                "row_count": len(engine),
                "max_absolute_error": max_error,
                "parity_tolerance": float(args.parity_tolerance),
                "engine_independent_parity_pass": parity_pass,
            }
        )
        if not parity_pass:
            failures.append(f"engine_independent_prediction_mismatch:{output_name}")
        predictions[output_name] = engine

    output = pd.DataFrame({"ticker": normalized_tickers(scaled["ticker"])})
    prior_delta = pd.DataFrame({"ticker": output["ticker"]})
    distribution_rows: list[dict[str, Any]] = []
    delta_rows: list[dict[str, Any]] = []
    for name, values in predictions.items():
        output[name] = values
        current = pd.Series(values, dtype=float)
        prior = pd.to_numeric(context[name], errors="coerce").reset_index(drop=True)
        overlap = np.isfinite(prior.to_numpy(dtype=float))
        delta = current - prior
        prior_delta[f"prior_{name}"] = prior
        prior_delta[f"current_{name}"] = current
        prior_delta[f"delta_{name}"] = delta
        distribution_rows.append(
            {
                "output": name,
                "row_count": len(current),
                "minimum": float(current.min()),
                "q25": float(current.quantile(0.25)),
                "median": float(current.median()),
                "mean": float(current.mean()),
                "q75": float(current.quantile(0.75)),
                "maximum": float(current.max()),
                "standard_deviation": float(current.std(ddof=0)),
            }
        )
        overlap_delta = delta.loc[overlap]
        delta_rows.append(
            {
                "output": name,
                "prior_finite_count": int(overlap.sum()),
                "current_finite_count": int(np.isfinite(current).sum()),
                "newly_scored_count": int((~overlap).sum()),
                "overlap_mean_delta": float(overlap_delta.mean()),
                "overlap_median_delta": float(overlap_delta.median()),
                "overlap_mean_absolute_delta": float(overlap_delta.abs().mean()),
                "overlap_max_absolute_delta": float(overlap_delta.abs().max()),
                "overlap_changed_count_at_tolerance": int(
                    (overlap_delta.abs() > float(args.parity_tolerance)).sum()
                ),
            }
        )

    output["decision_feature_complete"] = False
    output["decision_ranking_allowed"] = False
    prior_delta["decision_ranking_allowed"] = False
    score_values = output[list(HEADS)].to_numpy(dtype=float)
    if not np.isfinite(score_values).all():
        failures.append("score_only_prediction_nonfinite")
    if output["ticker"].tolist() != normalized_tickers(scaled["ticker"]).tolist():
        failures.append("ticker_order_changed")
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

    frames = {
        "ticker_order_model_predictions": output,
        "prior_prediction_delta": prior_delta,
        "prediction_head_parity_audit": pd.DataFrame(parity_rows),
        "prediction_distribution_summary": pd.DataFrame(distribution_rows),
        "prior_prediction_delta_summary": pd.DataFrame(delta_rows),
    }
    outputs: dict[str, Any] = {}
    for name, frame in frames.items():
        path = output_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        outputs[name] = {
            **checkpoint.fingerprint(path),
            "row_count": int(len(frame)),
        }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "contract_failures": [],
        "blockers": [
            "decision_feature_complete_false",
            "cross_sectional_score_stack_not_run",
            "score_sort_rank_and_top_n_not_run",
            "selector_sizing_and_target_book_not_run",
            "historical_cagr_mdd_evidence_unchanged",
            "pit_universe_membership_not_clean",
        ],
        "valuation_price_cutoff_date": valuation_date,
        "decision_time_utc": decision.get("decision_time_utc"),
        "feature_available_from": decision.get("feature_available_from"),
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "score_only": True,
        "model_head_contract": "frozen_meta_four_linear_heads_only",
        "model_meta_updated_at": model_meta.get("updated_at"),
        "model_meta_ranking_enabled": bool(model_meta.get("ranking_enabled")),
        "current_decision_frame_required_and_verified": True,
        "model_scoring_executed": True,
        "cross_sectional_score_stack_executed": False,
        "decision_feature_complete": False,
        "decision_ranking_allowed": False,
        "score_sort_executed": False,
        "rank_executed": False,
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
            "ticker_count": len(output),
            "model_feature_count": len(model_features),
            "prediction_head_count": len(HEADS),
            "finite_prediction_cell_count": int(np.isfinite(score_values).sum()),
            "prediction_cell_count": int(score_values.size),
            "engine_independent_parity_pass_count": sum(
                bool(row["engine_independent_parity_pass"]) for row in parity_rows
            ),
            "prior_prediction_min_finite_count": min(
                int(row["prior_finite_count"]) for row in delta_rows
            ),
            "newly_scored_max_count": max(
                int(row["newly_scored_count"]) for row in delta_rows
            ),
        },
        "recommended_next_step": (
            "run a separate pinned score-stack parity audit over this immutable "
            "ticker-order output; keep sorting, ranking, selection, sizing, target-book "
            "writes, backtests, fullrun, production, and live trading disabled"
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
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument("--expected-context-count", type=int, required=True)
    parser.add_argument("--expected-model-feature-count", type=int, required=True)
    parser.add_argument("--parity-tolerance", type=float, default=1e-12)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
