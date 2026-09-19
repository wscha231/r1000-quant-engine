"""Leakage-safe walk-forward analogue learning for News Event Alpha V1.

This module intentionally imports the stable event/outcome contract from
runtime.py and is invoked lazily by run_payload. A checkpoint may learn only
from fully resolved outcomes that ended before that checkpoint session.
"""
from __future__ import annotations

import statistics
from typing import Any, Iterable

from .runtime import (
    CHECKPOINTS,
    HORIZONS,
    _arm_membership,
    _cluster_stats,
    _sample_stats,
    digest,
    checkpoint_key, outcome_key, prediction_key, unique_index, utc, require_learning_origin,
)


def most_specific_arm(row: dict[str, Any]) -> str:
    if row.get("confirmed_combo"):
        return "CONFIRMED_COMBO"
    if row.get("official_direct") and row.get("business_substance"):
        return "OFFICIAL_DIRECT_SUBSTANCE"
    if row.get("official_direct"):
        return "OFFICIAL_DIRECT"
    return "ALL"


def build_walk_forward_impact_estimates(
    checkpoint_rows: Iterable[dict[str, Any]],
    outcome_rows: Iterable[dict[str, Any]],
    *,
    min_event_type_arm_n: int = 15,
    min_arm_n: int = 30,
    min_all_n: int = 50,
) -> list[dict[str, Any]]:
    """Create point-in-time historical-analogue impact estimates.

    Training rows are eligible only when their entire forward horizon has ended
    before the current checkpoint session. This is the central anti-leakage
    rule for historical learning.

    The displayed estimate is the robust median SPY excess return of the most
    specific adequately powered analogue cohort. It is evidence, not a target
    price, guaranteed return, or selector score.
    """
    checkpoints = list(checkpoint_rows)
    outcome_rows = list(outcome_rows)
    for row in checkpoints + outcome_rows:
        require_learning_origin(row)
    unique_index(outcome_rows, outcome_key, "input outcome")
    outcomes = [
        r
        for r in outcome_rows
        if r.get("outcome_status") == "RESOLVED"
        and r.get("excess_return") is not None
        and r.get("outcome_end_session")
        and r.get("label_available_at")
        and utc(r["label_available_at"]).date().isoformat() >= str(r["outcome_end_session"])
    ]
    unique_index(checkpoints, checkpoint_key, "walk-forward checkpoint")
    actual_index = unique_index(outcomes, outcome_key, "walk-forward outcome")
    estimates: list[dict[str, Any]] = []

    for row in checkpoints:
        current_session = str(row["checkpoint_session"])
        arm = most_specific_arm(row)
        event_type = str(row.get("event_type") or "OTHER")
        for horizon in HORIZONS:
            prior = [
                r
                for r in outcomes
                if r.get("label_contract") == row.get("label_contract")
                and (row.get("sample_origin") == "FORWARD_SHADOW"
                     or r.get("sample_origin") == "HISTORICAL_BACKFILL")
                and int(r.get("checkpoint", -1)) == int(row["checkpoint"])
                and int(r.get("horizon", -1)) == horizon
                and str(r.get("outcome_end_session")) < current_session
                and utc(r["label_available_at"]) < utc(row["decision_at"])
                and str(r.get("economic_event_id"))
                != str(row.get("economic_event_id"))
            ]
            tiers = [
                (
                    "EVENT_TYPE_ARM",
                    [
                        r
                        for r in prior
                        if str(r.get("event_type") or "OTHER") == event_type
                        and _arm_membership(r, arm)
                    ],
                    int(min_event_type_arm_n),
                    8,
                ),
                (
                    "ARM",
                    [r for r in prior if _arm_membership(r, arm)],
                    int(min_arm_n),
                    12,
                ),
                ("ALL", prior, int(min_all_n), 20),
            ]

            selected_tier = "UNDERPOWERED"
            selected: list[dict[str, Any]] = []
            required_n = None
            required_issuers = None
            for tier_name, candidate, n_floor, issuer_floor in tiers:
                issuer_n = len(
                    {
                        str(x.get("issuer_id") or x.get("security_id"))
                        for x in candidate
                    }
                )
                if len(candidate) >= n_floor and issuer_n >= issuer_floor:
                    selected_tier = tier_name
                    selected = candidate
                    required_n = n_floor
                    required_issuers = issuer_floor
                    break

            actual = actual_index.get(outcome_key(row, horizon))
            actual_excess = (
                float(actual["excess_return"])
                if actual is not None and actual.get("excess_return") is not None
                else None
            )

            base = {
                **{k: v for k, v in row.items() if k != "row_sha256"},
                "horizon": horizon,
                "analogue_arm": arm,
            }

            if selected:
                values = [float(x["excess_return"]) for x in selected]
                stats = _sample_stats(values)
                clusters = _cluster_stats(selected)
                training_latest = max(
                    str(x["outcome_end_session"]) for x in selected
                )
                estimate = float(stats["median_excess"])
                error = (
                    None if actual_excess is None else actual_excess - estimate
                )
                direction_correct = (
                    None
                    if actual_excess is None
                    else bool((estimate > 0) == (actual_excess > 0))
                )
                estimate_row = {
                    **base,
                    "analogue_status": "AVAILABLE",
                    "analogue_tier": selected_tier,
                    "analogue_event_type": (
                        event_type if selected_tier == "EVENT_TYPE_ARM" else "ALL"
                    ),
                    "training_n": int(stats["n"]),
                    "training_distinct_issuers": len(
                        {
                            str(x.get("issuer_id") or x.get("security_id"))
                            for x in selected
                        }
                    ),
                    "training_latest_outcome_end_session": training_latest,
                    "training_latest_label_available_at": max(
                        (x["label_available_at"] for x in selected), key=utc),
                    "analogue_median_excess": estimate,
                    "analogue_mean_excess": float(stats["mean_excess"]),
                    "analogue_q25_excess": float(stats["q25_excess"]),
                    "analogue_q75_excess": float(stats["q75_excess"]),
                    "analogue_positive_rate": float(
                        stats["win_rate_excess_gt0"]
                    ),
                    "analogue_cluster_ci95_low": clusters[
                        "issuer_year_cluster_ci95_mean_low"
                    ],
                    "analogue_cluster_ci95_high": clusters[
                        "issuer_year_cluster_ci95_mean_high"
                    ],
                    "actual_excess_return": actual_excess,
                    "prediction_error": error,
                    "direction_correct": direction_correct,
                    "minimum_n_used": required_n,
                    "minimum_issuers_used": required_issuers,
                }
            else:
                estimate_row = {
                    **base,
                    "analogue_status": "UNDERPOWERED",
                    "analogue_tier": "UNDERPOWERED",
                    "analogue_event_type": event_type,
                    "training_n": 0,
                    "training_distinct_issuers": 0,
                    "training_latest_outcome_end_session": None,
                    "training_latest_label_available_at": None,
                    "analogue_median_excess": None,
                    "analogue_mean_excess": None,
                    "analogue_q25_excess": None,
                    "analogue_q75_excess": None,
                    "analogue_positive_rate": None,
                    "analogue_cluster_ci95_low": None,
                    "analogue_cluster_ci95_high": None,
                    "actual_excess_return": actual_excess,
                    "prediction_error": None,
                    "direction_correct": None,
                    "minimum_n_used": None,
                    "minimum_issuers_used": None,
                }

            estimate_row["prediction_id"] = digest(prediction_key(estimate_row))
            estimate_row["estimate_kind"] = "RECONSTRUCTED_ANALOGUE_NOT_LIVE_ISSUANCE"
            estimate_row["estimate_sha256"] = digest(
                {
                    k: v
                    for k, v in estimate_row.items()
                    if k != "estimate_sha256"
                }
            )
            estimates.append(estimate_row)
    return estimates


def summarize_walk_forward_performance(
    estimate_rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score only estimates that were available before their outcomes."""
    estimate_rows = list(estimate_rows)
    for row in estimate_rows:
        require_learning_origin(row)
    resolved = [
        r
        for r in estimate_rows
        if r.get("analogue_status") == "AVAILABLE"
        and r.get("actual_excess_return") is not None
        and r.get("analogue_median_excess") is not None
    ]
    out: list[dict[str, Any]] = []
    segments = sorted({(r["sample_origin"], r["label_contract"], r["model_version"]) for r in resolved})
    for origin, label_contract, model_version in segments:
        for checkpoint in CHECKPOINTS:
            for horizon in HORIZONS:
                group = [
                    r
                    for r in resolved
                    if r["sample_origin"] == origin
                    and r["label_contract"] == label_contract
                    and r["model_version"] == model_version
                    and int(r.get("checkpoint", -1)) == checkpoint
                    and int(r.get("horizon", -1)) == horizon
                ]
                if not group:
                    continue
                errors = [float(r["prediction_error"]) for r in group]
                abs_errors = [abs(x) for x in errors]
                predicted_positive = [
                    r
                    for r in group
                    if float(r["analogue_median_excess"]) > 0
                ]
                out.append(
                    {
                        "sample_origin": origin,
                        "label_contract": label_contract,
                        "model_version": model_version,
                        "checkpoint": checkpoint,
                        "horizon": horizon,
                        "n_predictions": len(group),
                        "distinct_issuers": len(
                            {
                                str(r.get("issuer_id") or r.get("security_id"))
                                for r in group
                            }
                        ),
                        "mean_absolute_error": statistics.fmean(abs_errors),
                        "median_absolute_error": statistics.median(abs_errors),
                        "mean_error": statistics.fmean(errors),
                        "direction_hit_rate": (
                            sum(bool(r["direction_correct"]) for r in group)
                            / len(group)
                        ),
                        "predicted_positive_n": len(predicted_positive),
                        "predicted_positive_actual_win_rate": (
                            sum(
                                float(r["actual_excess_return"]) > 0
                                for r in predicted_positive
                            )
                            / len(predicted_positive)
                            if predicted_positive
                            else None
                        ),
                        "predicted_positive_actual_median_excess": (
                            statistics.median(
                                float(r["actual_excess_return"])
                                for r in predicted_positive
                            )
                            if predicted_positive
                            else None
                        ),
                    }
                )
    return out
