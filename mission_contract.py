"""Semantic identity for the official portfolio mission; target values live in config."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

MISSION_CONTRACT_ID = "portfolio-mission-v1"
OFFICIAL_METRIC_MODE = "broker_ledger_next_close"
HISTORICAL_UNBOUND = "historical_or_unbound_target_contract"


def canonical_mission(targets: dict[str, Any]) -> dict[str, Any]:
    """Project only mission semantics from the one authoritative target map."""
    if set(targets) != {"main", "concentrated"}:
        raise ValueError("mission_portfolios_invalid")
    values = {}
    for name in ("main", "concentrated"):
        target = targets[name]
        if not isinstance(target, dict) or set(target) != {"cagr", "max_dd"}:
            raise ValueError("mission_target_fields_invalid")
        pair = {}
        for source, output in (("cagr", "cagr_min"), ("max_dd", "max_dd_min")):
            value = target[source]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("mission_target_nonfinite_or_nonnumeric")
            pair[output] = float(value)
        values[name] = pair
    return {"contract_id": MISSION_CONTRACT_ID,
            "official_metric_mode": OFFICIAL_METRIC_MODE, "targets": values}


def mission_identity(targets: dict[str, Any]) -> dict[str, Any]:
    semantic = canonical_mission(targets)
    blob = json.dumps(semantic, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {"mission_contract_id": MISSION_CONTRACT_ID,
            "mission_contract_sha256": hashlib.sha256(blob).hexdigest(),
            "official_metric_mode": OFFICIAL_METRIC_MODE,
            "target_type": "canonical_mission",
            "mission_contract_values": semantic["targets"]}


def mission_binding_status(artifact: Any, identity: dict[str, Any]) -> str:
    """A prior PASS flag is current only when the original artifact is bound."""
    if not isinstance(artifact, dict):
        return HISTORICAL_UNBOUND
    if (artifact.get("mission_contract_id") != identity["mission_contract_id"]
            or artifact.get("mission_contract_sha256") != identity["mission_contract_sha256"]
            or artifact.get("official_metric_mode") != OFFICIAL_METRIC_MODE
            or artifact.get("mission_contract_values") != identity["mission_contract_values"]
            or artifact.get("target_type") != "canonical_mission"):
        return HISTORICAL_UNBOUND
    return "current_mission_contract"
