"""Read a hash-linked, nonranking score export without running the model.

Only exact ZIP members referenced by the verified upstream receipt are read.
This consumer validates transport, provenance and the producer's declared
contract; it does not certify model performance or accepted portfolio state.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from tools.run287_code_identity import code_identity_failures

READY_UPSTREAM = {
    "READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
    "READY_EXISTING_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
}
HEADS = ("pred_lin_ret", "pred_lin_p", "pred_future_winner_ret",
         "pred_future_winner_p", "pred_cat_ret", "pred_cat_p")
SAFE_FALSE = ("backtest_executed", "fullrun_executed", "selector_executed",
              "decision_ranking_allowed", "production_activation_allowed",
              "live_trading_enabled")
ROW_FLAGS = ("registered_ranking_eligible", "corporate_action_quarantine",
             "research_eligible_after_quarantine", "data_complete",
             "critical_data_complete", "missing_neutral_applied")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def utc(value: str) -> datetime:
    require(isinstance(value, str), "score_time_missing")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("score_time_invalid") from None
    require(result.tzinfo is not None, "score_timezone_required")
    return result.astimezone(timezone.utc)


def finite(value) -> float:
    require(not isinstance(value, bool), "score_numeric_invalid")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError("score_numeric_invalid") from None
    require(math.isfinite(result), "score_numeric_invalid")
    return result


def flag(value) -> bool:
    # CSV exports from pandas use True/False. Do not accept truthy strings.
    require(type(value) is bool or value in ("True", "False"), "score_boolean_invalid")
    return value is True or value == "True"


def member_path(raw: str, repository: str) -> str:
    require(isinstance(raw, str), "score_path_missing")
    name = repository.split("/")[-1]
    root = f"/home/runner/work/{name}/{name}/"
    if raw.startswith(root):
        raw = raw[len(root):]
    require(raw.startswith("outputs/") and "\\" not in raw
            and not any(p in ("", ".", "..") for p in raw.split("/"))
            and not any(c in raw for c in (":", "?", "#", "\x00")), "score_path_invalid")
    return raw


def reference(record: dict, repository: str) -> tuple[str, str]:
    require(isinstance(record, dict), "score_reference_missing")
    digest = record.get("sha256")
    require(isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest) is not None,
            "score_reference_hash_invalid")
    return member_path(record.get("path"), repository), digest


def read_score_handoff(path: Path, upstream: dict, repository: str, limit: int) -> tuple[dict, dict]:
    """Read the root receipt's explicit graph, including original paths on reuse."""
    evidence, data = {}, {}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()

        def read(label: str, record: dict, suffix: str = ".json"):
            name, digest = reference(record, repository)
            require(name.endswith(suffix), "score_member_type_invalid")
            require(names.count(name) == 1, "score_member_missing_or_duplicate")
            info = archive.getinfo(name)
            require(not info.is_dir() and info.file_size <= limit, "score_member_size_invalid")
            raw = archive.read(info)
            require(hashlib.sha256(raw).hexdigest() == digest, "score_member_hash_mismatch")
            evidence["score_" + label] = {"member": name, "sha256": digest, "bytes": len(raw)}
            if suffix == ".json":
                value = json.loads(raw.decode("utf-8-sig"))
                require(isinstance(value, dict), "score_manifest_invalid")
            else:
                reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
                fields = reader.fieldnames or []
                require(len(fields) == len(set(fields)), "score_duplicate_columns")
                value = list(reader)
                require(all(None not in row for row in value), "score_row_shape_invalid")
            data[label] = value
            return value

        bundle = read("bundle", upstream.get("source_bundle"))
        inputs = bundle.get("inputs") or {}
        read("decision", inputs.get("decision_manifest"))
        stack = read("stack", inputs.get("score_stack_manifest"))
        stack_inputs = stack.get("source_inputs") or {}
        require(reference(stack_inputs.get("decision_frame_manifest"), repository)
                == reference(inputs.get("decision_manifest"), repository), "score_decision_link_mismatch")
        linear = read("linear", stack_inputs.get("score_only_manifest"))
        require(reference((linear.get("source_inputs") or {}).get("decision_frame_manifest"), repository)
                == reference(inputs.get("decision_manifest"), repository), "score_linear_link_mismatch")
        read("rows", (stack.get("outputs") or {}).get("ticker_order_score_stack"), ".csv")
    return data, evidence


def evaluate_score_handoff(source: dict, session: str, now: datetime) -> tuple[dict, dict]:
    """Return valid ticker-order diagnostics or one explicit blocking reason."""
    result = {"status": "UNAVAILABLE", "ready": False, "score_as_of": None,
              "decision_ranking_allowed": False, "verified_ticker_count": 0}
    try:
        require(source.get("status") == "VERIFIED_ARTIFACT"
                and source.get("artifact_hash_verified") is True, "score_source_not_verified")
        data = source.get("data") or {}
        upstream = data.get("upstream") or {}
        require(upstream.get("status") in READY_UPSTREAM
                and upstream.get("upstream_ready") is True, "score_upstream_not_ready")
        require(not source.get("score_handoff_error"), source.get("score_handoff_error", "score_handoff_invalid"))
        handoff = data.get("score_handoff") or {}
        require(bool(handoff), "score_handoff_missing")
        bundle, decision, linear, stack = (handoff.get(k) or {} for k in ("bundle", "decision", "linear", "stack"))
        result["score_as_of"] = stack.get("valuation_price_cutoff_date")
        for obj, schema, status in (
            (bundle, "run287-exact-packet-input-source-bundle-v1", "READY_EXACT_PACKET_INPUT_SOURCE_PATHS_REVIEW_ONLY"),
            (decision, "run287-current-decision-frame-v1", "READY_COMPLETE_CURRENT_DECISION_FRAME"),
            (linear, "run287-current-decision-score-only-v1", "READY_CURRENT_DECISION_SCORE_ONLY_NONRANKING"),
            (stack, "run287-current-decision-score-stack-audit-v1", "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING"),
        ):
            require(obj.get("schema_version") == schema and obj.get("status") == status, "score_manifest_not_ready")
            require(obj.get("valuation_price_cutoff_date") == session, "score_session_mismatch")
            require(obj.get("research_only") is True, "score_research_boundary_invalid")
        require(upstream.get("valuation_price_cutoff_date") == session, "score_upstream_session_mismatch")
        for obj in (decision, linear, stack):
            require(all(obj.get(k) is False for k in SAFE_FALSE), "score_execution_boundary_invalid")
        require(all(stack.get(k) is False for k in
                    ("target_books_mutated", "source_inputs_mutated", "target_book_generation_allowed",
                     "score_sort_executed", "rank_assignment_executed", "top_n_executed")),
                "score_execution_boundary_invalid")
        require(not stack.get("contract_failures")
                and all(stack.get(k) is True for k in
                        ("score_stack_audit_passed", "fresh_prediction_passthrough_verified",
                         "stale_prediction_columns_removed_before_join", "model_scoring_executed",
                         "catboost_scoring_executed", "adaptive_ensemble_executed"))
                and stack.get("stale_prediction_suffix_collision_count") == 0
                and (stack.get("source_immutability") or {}).get("all_verified_files_unchanged") is True,
                "score_producer_audit_failed")
        require(decision.get("current_decision_data_complete") is True
                and decision.get("research_model_scoring_prerequisite_passed") is True, "score_decision_incomplete")
        available, decision_time, executed = (utc(stack.get(k)) for k in
                                             ("feature_available_from", "decision_time_utc", "executed_at_utc"))
        require(available <= decision_time <= executed <= now, "score_time_order_invalid")
        require(decision_time.date().isoformat() >= session, "score_decision_before_close_date")
        for obj in (decision, linear):
            require(utc(obj.get("feature_available_from")) == available
                    and utc(obj.get("decision_time_utc")) == decision_time, "score_input_time_mismatch")
        require(utc(linear.get("executed_at_utc")) <= executed, "score_execution_time_mismatch")
        run = source.get("run") or {}
        require(run.get("conclusion") == "success" and run.get("status") == "completed", "score_run_not_successful")
        require(utc(run.get("created_at")) <= now, "score_future_run")
        identity = bundle.get("code_identity") or {}
        require(not code_identity_failures(identity), "score_code_identity_invalid")
        code_sha = identity.get("source_commit_sha")
        require(code_sha == run.get("head_sha") == (stack.get("code") or {}).get("git_head"),
                "score_code_identity_mismatch")
        anchor = (stack.get("source_inputs") or {}).get("frozen_score_stack_manifest") or {}
        model_meta = (stack.get("source_inputs") or {}).get("model_meta") or {}
        require(all(isinstance(obj.get("sha256"), str)
                    and re.fullmatch(r"[a-f0-9]{64}", obj["sha256"]) for obj in (anchor, model_meta)),
                "score_model_identity_missing")
        require(all(obj.get("hash_matches") is True for obj in (anchor, model_meta))
                and all(((obj.get("source_inputs") or {}).get("model_meta") or {}).get("sha256")
                        == model_meta["sha256"] for obj in (decision, linear)), "score_model_identity_mismatch")
        coverage = stack.get("coverage") or {}
        require(all(coverage.get(k) == 6 for k in ("active_prediction_head_count", "active_prediction_head_required_count",
                                                  "prediction_passthrough_pass_count", "prediction_passthrough_required_count")),
                "score_prediction_heads_invalid")
        rows = handoff.get("rows") or []
        count = len(rows)
        require(count >= 2 and count == coverage.get("ticker_count")
                == ((stack.get("outputs") or {}).get("ticker_order_score_stack") or {}).get("row_count"),
                "score_row_count_mismatch")
        indexed = {}
        for row in rows:
            ticker = row.get("ticker")
            require(isinstance(ticker, str) and re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", ticker) is not None,
                    "score_ticker_invalid")
            require(ticker not in indexed, "score_duplicate_ticker")
            require(not flag(row.get("decision_ranking_allowed")), "score_row_ranking_boundary_invalid")
            values = {key: finite(row.get(key)) for key in ("score", *HEADS)}
            values.update({key: flag(row.get(key)) for key in ROW_FLAGS})
            values["critical_missing_fields"] = str(row.get("critical_missing_fields") or "")
            indexed[ticker] = values
        for head in HEADS:
            require(len({r[head] for r in indexed.values()}) > 1, "score_prediction_head_constant")
        result.update(status="VERIFIED_CURRENT_NONRANKING_SCORES", ready=True, verified_ticker_count=count,
                      decision_time_utc=decision_time.isoformat(), feature_available_from=available.isoformat(),
                      executed_at_utc=executed.isoformat(), engine_code_sha=code_sha,
                      model_anchor_sha256=anchor["sha256"], model_meta_sha256=model_meta["sha256"],
                      evidence=source.get("files", {}).get("score_stack"),
                      meaning="Validated producer export; score scale and predictive value are not revalidated here.")
        return result, indexed
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]+", str(exc)) else "score_contract_invalid"
        result.update(status=reason.upper(), reason=reason)
        return result, {}
