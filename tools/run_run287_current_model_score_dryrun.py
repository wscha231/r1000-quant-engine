#!/usr/bin/env python3
"""Run the four frozen Run287 linear model heads without ranking or selection.

The input must have passed the complete-current-cross-section verifier.  The
tool independently reproduces each matrix calculation and compares it with the
registered engine helper.  It emits ticker-order predictions and distribution
diagnostics only.  It never sorts by score, creates top-N cohorts, invokes the
cross-sectional score stack, selects, sizes, backtests, runs fullrun, changes a
target book, or authorizes production/live trading.
"""
from __future__ import annotations

import argparse
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

from r1000_pipeline import (  # noqa: E402
    logreg_predict_proba_from_meta,
    ridge_predict_from_meta,
)
from tools import stage_run287_price_batch as checkpoint  # noqa: E402


SCHEMA_VERSION = "run287-current-model-score-dryrun-v1"
HEADS = {
    "pred_lin_ret": ("ridge", "ridge"),
    "pred_lin_p": ("logreg", "logreg"),
    "pred_future_winner_ret": ("future_ridge", "ridge"),
    "pred_future_winner_p": ("future_logreg", "logreg"),
}


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
        "status": "BLOCKED_CURRENT_MODEL_SCORE_DRYRUN",
        "contract_failures": failures,
        "blockers": failures,
        "valuation_price_cutoff_date": valuation_date,
        "research_only": True,
        "dry_run_only": True,
        "model_scoring_executed": False,
        "decision_ranking_allowed": False,
        "score_sort_executed": False,
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


def independent_prediction(
    matrix: np.ndarray,
    meta: Mapping[str, Any],
    key: str,
    kind: str,
) -> np.ndarray:
    spec = meta.get(key) or {}
    coefficient = np.asarray(spec.get("coef") or [], dtype=float)
    intercept = float(spec.get("intercept") or 0.0)
    linear = matrix @ coefficient + intercept
    if kind == "ridge":
        return linear
    clipped = np.clip(linear, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = checkpoint.repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    valuation_date = checkpoint.clean_date(args.valuation_date)
    verifier_path = checkpoint.repo_path(args.verifier_manifest)
    feature_path = checkpoint.repo_path(args.feature_manifest)
    input_audits = {
        "verifier_manifest": expected_input(
            verifier_path, args.expected_verifier_sha256, "verifier_manifest"
        ),
        "feature_manifest": expected_input(
            feature_path, args.expected_feature_sha256, "feature_manifest"
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
    relation = (verifier.get("source_inputs") or {}).get("feature_manifest") or {}
    if str(relation.get("sha256") or "") != input_audits["feature_manifest"].get(
        "sha256"
    ):
        failures.append("verifier_feature_manifest_relation_mismatch")

    record_specs = [
        ("scaled_input", feature_path, feature, "outputs", "pilot_scaled_model_input"),
        ("model_meta", feature_path, feature, "source_inputs", "model_meta"),
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

    verifier_checks = {
        "ready": verifier.get("status")
        == "READY_COMPLETE_CURRENT_CROSS_SECTION_NONRANKING",
        "complete": verifier.get("complete_cross_section_verification_passed")
        is True,
        "scoring_prerequisite": verifier.get(
            "research_model_scoring_prerequisite_passed"
        )
        is True,
        "ranking_disabled": verifier.get("decision_ranking_allowed") is False,
        "scoring_not_preexecuted": verifier.get("model_scoring_executed") is False,
        "selector_not_executed": verifier.get("selector_executed") is False,
        "backtest_not_executed": verifier.get("backtest_executed") is False,
        "fullrun_not_executed": verifier.get("fullrun_executed") is False,
        "zero_network": int(verifier.get("network_requests_executed") or 0) == 0,
        "no_mutation": verifier.get("source_inputs_mutated") is False,
    }
    feature_checks = {
        "assembled": feature.get("status")
        == "CURRENT_CROSS_SECTION_ASSEMBLED_VERIFICATION_REQUIRED",
        "ranking_disabled": feature.get("decision_ranking_allowed") is False,
        "scoring_not_preexecuted": feature.get("model_scoring_executed") is False,
        "selector_not_executed": feature.get("selector_executed") is False,
        "backtest_not_executed": feature.get("backtest_executed") is False,
        "fullrun_not_executed": feature.get("fullrun_executed") is False,
        "zero_network": int(feature.get("network_requests_executed") or 0) == 0,
        "no_mutation": feature.get("source_inputs_mutated") is False,
    }
    failures.extend(
        f"verifier_contract:{name}"
        for name, passed in verifier_checks.items()
        if not passed
    )
    failures.extend(
        f"feature_contract:{name}" for name, passed in feature_checks.items() if not passed
    )
    dates = {
        checkpoint.clean_date(verifier.get("valuation_price_cutoff_date")),
        checkpoint.clean_date(feature.get("valuation_price_cutoff_date")),
        valuation_date,
    }
    if dates != {valuation_date}:
        failures.append("valuation_date_mismatch:" + ",".join(sorted(dates)))
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    scaled = pd.read_parquet(verified_paths["scaled_input"])
    ticker_audit = pd.read_csv(
        verified_paths["verifier_ticker_audit"], low_memory=False
    )
    model_meta = checkpoint.read_json(verified_paths["model_meta"])
    model_features = [str(value) for value in model_meta.get("model_features") or []]
    expected_count = int(args.expected_model_feature_count)
    expected_rows = int(args.expected_context_count)
    if len(model_features) != expected_count:
        failures.append(f"model_feature_count:{len(model_features)}!={expected_count}")
    if list(scaled.columns) != ["ticker", *model_features]:
        failures.append("scaled_input_schema_order_mismatch")
    if len(scaled) != expected_rows or scaled["ticker"].duplicated().any():
        failures.append("scaled_input_ticker_count_or_duplicate")
    matrix = scaled.reindex(columns=model_features).apply(
        pd.to_numeric, errors="coerce"
    ).to_numpy(dtype=float)
    if matrix.shape != (expected_rows, expected_count):
        failures.append("scaled_matrix_shape_mismatch")
    if not np.isfinite(matrix).all():
        failures.append("scaled_matrix_nonfinite")
    if bool(model_meta.get("ranking_enabled")):
        failures.append("frozen_model_meta_ranking_enabled")
    for key, _ in HEADS.values():
        spec = model_meta.get(key)
        coefficient = np.asarray((spec or {}).get("coef") or [], dtype=float)
        intercept = pd.to_numeric(
            pd.Series([(spec or {}).get("intercept")]), errors="coerce"
        ).iloc[0]
        if coefficient.shape != (expected_count,):
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
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    ticker_audit["ticker"] = ticker_audit["ticker"].astype(str).str.upper().str.strip()
    quarantine_tickers = set(
        ticker_audit.loc[
            ticker_audit.get("corporate_action_quarantine", False).map(checkpoint.boolish),
            "ticker",
        ]
    )
    output = pd.DataFrame({"ticker": scaled["ticker"].astype(str).str.upper().str.strip()})
    for name, values in predictions.items():
        output[name] = values
    output["corporate_action_quarantine"] = output["ticker"].isin(quarantine_tickers)
    output["decision_ranking_allowed"] = False
    if output["ticker"].tolist() != scaled["ticker"].astype(str).str.upper().str.strip().tolist():
        failures.append("ticker_order_changed")
    score_values = output[list(HEADS)].to_numpy(dtype=float)
    if not np.isfinite(score_values).all():
        failures.append("dryrun_prediction_nonfinite")

    all_missing_features = {
        str(value)
        for value in (
            (verifier.get("coverage") or {}).get("all_missing_neutral_features")
            or []
        )
    }
    missing_feature_rows: list[dict[str, Any]] = []
    for feature_name in sorted(all_missing_features):
        if feature_name not in model_features:
            failures.append(f"all_missing_feature_outside_model:{feature_name}")
            continue
        feature_index = model_features.index(feature_name)
        scaled_column = matrix[:, feature_index]
        for output_name, (key, _) in HEADS.items():
            coefficient = float(model_meta[key]["coef"][feature_index])
            max_contribution = float(np.max(np.abs(scaled_column * coefficient)))
            missing_feature_rows.append(
                {
                    "feature": feature_name,
                    "output": output_name,
                    "coefficient": coefficient,
                    "scaled_value_max_abs": float(np.max(np.abs(scaled_column))),
                    "contribution_max_abs": max_contribution,
                    "neutral_contribution_pass": max_contribution
                    <= float(args.parity_tolerance),
                }
            )
            if max_contribution > float(args.parity_tolerance):
                failures.append(
                    f"all_missing_feature_nonzero_contribution:{feature_name}:{output_name}"
                )
    unchanged = source_files_unchanged(input_audits)
    if not unchanged:
        failures.append("verified_source_file_mutated")
    if failures:
        return blocked_payload(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=valuation_date,
        )

    summary_rows: list[dict[str, Any]] = []
    for name in HEADS:
        values = pd.to_numeric(output[name], errors="coerce")
        summary_rows.append(
            {
                "output": name,
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
    frames = {
        "ticker_order_model_predictions": output,
        "prediction_head_parity_audit": pd.DataFrame(parity_rows),
        "prediction_distribution_summary": pd.DataFrame(summary_rows),
        "all_missing_feature_contribution_audit": pd.DataFrame(
            missing_feature_rows
        ),
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
        "status": "READY_CURRENT_MODEL_SCORE_DRYRUN_NONRANKING",
        "contract_failures": [],
        "blockers": [
            "cross_sectional_score_stack_not_run",
            "rank_and_top_n_not_run",
            "selector_and_target_book_not_run",
            "historical_cagr_mdd_evidence_unchanged",
            "pit_universe_membership_not_clean",
            "corporate_action_quarantine:" + ",".join(sorted(quarantine_tickers)),
        ],
        "valuation_price_cutoff_date": valuation_date,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "dry_run_only": True,
        "model_head_contract": "frozen_meta_four_linear_heads_only",
        "model_meta_updated_at": model_meta.get("updated_at"),
        "model_meta_ranking_enabled": bool(model_meta.get("ranking_enabled")),
        "complete_cross_section_required_and_verified": True,
        "model_scoring_executed": True,
        "cross_sectional_score_stack_executed": False,
        "decision_ranking_allowed": False,
        "score_sort_executed": False,
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
            "all_missing_neutral_feature_count": len(all_missing_features),
            "all_missing_feature_nonzero_contribution_count": 0,
            "corporate_action_quarantine_ticker_count": len(quarantine_tickers),
        },
        "recommended_next_step": (
            "audit the registered cross-sectional score stack in a second non-mutating "
            "lane, preserving ticker eligibility and corporate-action quarantine; do "
            "not sort, select, size or write target books until that parity gate passes"
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
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument("--expected-context-count", type=int, required=True)
    parser.add_argument("--expected-model-feature-count", type=int, required=True)
    parser.add_argument("--parity-tolerance", type=float, default=1e-12)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") in {
        "READY_CURRENT_MODEL_SCORE_DRYRUN_NONRANKING",
        "BLOCKED_CURRENT_MODEL_SCORE_DRYRUN",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
