"""Compact reporting surfaces for News Event Alpha V1."""
from __future__ import annotations

from typing import Any, Iterable

from .runtime import HORIZONS


def build_top_event_impact_outlook(
    top_events: Iterable[dict[str, Any]],
    estimate_rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join bounded top-event display with interval analogue evidence.

    The full event universe remains in the immutable ledger. This view is
    intentionally bounded so routine reports do not dump every accumulated
    ticker.
    """
    estimates = list(estimate_rows)
    out: list[dict[str, Any]] = []
    for event in top_events:
        event_id = str(event["economic_event_id"])
        checkpoint = int(event["checkpoint"])
        by_horizon = {
            int(r["horizon"]): r
            for r in estimates
            if str(r.get("economic_event_id")) == event_id
            and int(r.get("checkpoint", -1)) == checkpoint
        }
        horizons: dict[str, Any] = {}
        for horizon in HORIZONS:
            row = by_horizon.get(horizon)
            if row is None:
                horizons[str(horizon)] = {
                    "status": "MISSING",
                    "analogue_median_excess": None,
                    "analogue_q25_excess": None,
                    "analogue_q75_excess": None,
                    "analogue_positive_rate": None,
                    "training_n": 0,
                    "training_distinct_issuers": 0,
                }
                continue
            horizons[str(horizon)] = {
                "status": row.get("analogue_status"),
                "analogue_tier": row.get("analogue_tier"),
                "analogue_median_excess": row.get("analogue_median_excess"),
                "analogue_q25_excess": row.get("analogue_q25_excess"),
                "analogue_q75_excess": row.get("analogue_q75_excess"),
                "analogue_positive_rate": row.get("analogue_positive_rate"),
                "training_n": row.get("training_n"),
                "training_distinct_issuers": row.get(
                    "training_distinct_issuers"
                ),
                "training_latest_outcome_end_session": row.get(
                    "training_latest_outcome_end_session"
                ),
            }
        out.append(
            {
                "economic_event_id": event_id,
                "security_id": event.get("security_id"),
                "issuer_id": event.get("issuer_id"),
                "checkpoint": checkpoint,
                "checkpoint_session": event.get("checkpoint_session"),
                "event_type": event.get("event_type"),
                "role": event.get("role"),
                "research_priority": event.get("research_priority"),
                "official_evidence": event.get("official_evidence"),
                "business_substance": event.get("business_substance"),
                "economic_value_confirmed": event.get(
                    "economic_value_confirmed"
                ),
                "economic_amount_usd": event.get("economic_amount_usd"),
                "economic_amount_kind": event.get("economic_amount_kind"),
                "pre_rs20": event.get("pre_rs20"),
                "pre_rs60": event.get("pre_rs60"),
                "event_day_excess": event.get("event_day_excess"),
                "event_volume_ratio20": event.get("event_volume_ratio20"),
                "post_rs_checkpoint": event.get("post_rs_checkpoint"),
                "theme_breadth_checkpoint": event.get(
                    "theme_breadth_checkpoint"
                ),
                "max_financing_risk": event.get("max_financing_risk"),
                "impact_outlook": horizons,
                "research_only": True,
                "investment_score": False,
            }
        )
    return out
