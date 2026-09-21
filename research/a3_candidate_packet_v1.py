"""A3 cross-market candidate packet contract.

This module aggregates reviewed research artifacts. It never promotes a research
scenario into validated expected return and never writes selector, portfolio,
target, ledger, or order state.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any

SCHEMA = "a3-candidate-packet-v1"
RESULT_SCHEMA = "a3-candidate-packet-v1-result"
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024

ARTIFACT_KINDS = {
    "METHODOLOGY_RESULT",
    "MOAT_RESULT",
    "MARKET_VALUATION_SNAPSHOT",
    "SOURCE_GRAPH",
    "VALIDATED_ER_EVALUATION",
}
MOAT_APPLICABILITY = {"REQUIRED", "NOT_APPLICABLE_UNDERLYING"}
THESIS_STATUSES = {"POSITIVE", "INTACT", "WATCH", "NEGATIVE", "INVALID"}
ER_HORIZONS = ("1m", "3m", "6m", "12m")
BRIDGE_HORIZONS = ("12m", "24m")
CASES = ("bear", "base", "bull")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,199}$")
ArtifactResolver = Callable[[str, str], bytes]


class A3CandidatePacketError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise A3CandidatePacketError(code)


def _text(value: Any, code: str, limit: int = 2000) -> str:
    _require(isinstance(value, str), code)
    value = value.strip()
    _require(bool(value) and len(value) <= limit, code)
    return value


def _identifier(value: Any, code: str) -> str:
    value = _text(value, code, 200)
    _require(bool(_ID.fullmatch(value)), code)
    return value


def _number(value: Any, code: str, lower: float | None = None, upper: float | None = None) -> float:
    _require(not isinstance(value, bool) and isinstance(value, (int, float)), code)
    value = float(value)
    _require(math.isfinite(value), code)
    _require(lower is None or value >= lower, code)
    _require(upper is None or value <= upper, code)
    return value


def _stamp(value: Any, code: str) -> datetime:
    value = _text(value, code, 80)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        out = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise A3CandidatePacketError(code) from exc
    _require(out.tzinfo is not None and out.utcoffset() is not None, code)
    return out


def _hash(value: Any, code: str) -> str:
    value = _text(value, code, 64).lower()
    _require(bool(_HEX64.fullmatch(value)), code)
    return value


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_ref(
    ref: Any,
    *,
    expected_kind: str,
    asset_id: str,
    issuer_id: str,
    as_of: datetime,
    resolver: ArtifactResolver,
) -> tuple[dict[str, Any], str]:
    _require(isinstance(ref, dict), f"artifact_ref_object:{expected_kind}")
    _require(ref.get("kind") == expected_kind, f"artifact_kind:{expected_kind}")
    artifact_id = _identifier(ref.get("artifact_id"), f"artifact_id:{expected_kind}")
    digest = _hash(ref.get("sha256"), f"artifact_sha256:{expected_kind}")
    available_at = _stamp(ref.get("available_at"), f"artifact_available_at:{expected_kind}")
    _require(available_at <= as_of, f"future_artifact:{expected_kind}")
    _require(ref.get("review_status") == "REVIEWED", f"artifact_review_status:{expected_kind}")
    _require(callable(resolver), "artifact_resolver_required")
    try:
        raw = resolver(artifact_id, digest)
    except Exception as exc:
        raise A3CandidatePacketError(f"artifact_unavailable:{expected_kind}") from exc
    _require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_ARTIFACT_BYTES, f"artifact_bytes:{expected_kind}")
    _require(hashlib.sha256(raw).hexdigest() == digest, f"artifact_hash_mismatch:{expected_kind}")
    try:
        value = json.loads(raw)
    except Exception as exc:
        raise A3CandidatePacketError(f"artifact_json:{expected_kind}") from exc
    _require(isinstance(value, dict), f"artifact_json_object:{expected_kind}")
    _require(value.get("asset_id") == asset_id, f"artifact_asset_identity:{expected_kind}")
    if expected_kind not in {"MARKET_VALUATION_SNAPSHOT", "VALIDATED_ER_EVALUATION"}:
        _require(value.get("issuer_id") == issuer_id, f"artifact_issuer_identity:{expected_kind}")
    return value, digest


def _validate_methodology(value: dict[str, Any]) -> None:
    _require(value.get("schema") == "investment-methodology-v1-result", "methodology_schema")
    _require(value.get("status") == "COMPLETE_RESEARCH_REVIEW", "methodology_status")
    _require(value.get("selector_eligible") is False, "methodology_selector_authority")
    _require(value.get("portfolio_weight_effect") == 0.0, "methodology_portfolio_authority")
    _require(value.get("oos_validated") is False, "methodology_oos_authority")


def _validate_moat(value: dict[str, Any]) -> None:
    _require(value.get("schema") == "moat-quality-v2-result", "moat_schema")
    _require(value.get("status") == "COMPLETE_RESEARCH_REVIEW", "moat_status")
    _require(value.get("selector_eligible") is False, "moat_selector_authority")
    _require(value.get("portfolio_weight_effect") == 0.0, "moat_portfolio_authority")
    _require(value.get("oos_validated") is False, "moat_oos_authority")


def _validate_market(value: dict[str, Any], as_of: datetime) -> None:
    _require(value.get("schema") == "a3-market-valuation-snapshot-v1", "market_schema")
    _require(value.get("data_quality") == "REVIEWED_OBSERVED", "market_data_quality")
    _require(value.get("research_only") is True, "market_research_only")
    _require(_stamp(value.get("available_at"), "market_available_at") <= as_of, "future_market_snapshot")
    _number(value.get("price"), "market_price", 0.0)
    _text(value.get("currency"), "market_currency", 12)
    _identifier(value.get("benchmark_id"), "market_benchmark_id")
    for h in (20, 60, 120, 240):
        _number(value.get(f"return_{h}d"), f"market_return_{h}d", -1.0)
        _number(value.get(f"benchmark_return_{h}d"), f"benchmark_return_{h}d", -1.0)
        _number(value.get(f"rs_{h}d"), f"market_rs_{h}d")


def _validate_source_graph(value: dict[str, Any]) -> None:
    _require(value.get("schema") == "a3-source-graph-v1", "source_graph_schema")
    _require(value.get("review_status") == "REVIEWED", "source_graph_status")
    _require(value.get("research_only") is True, "source_graph_research_only")
    _require(isinstance(value.get("sources"), list) and bool(value["sources"]), "source_graph_sources")


def _validate_bridge(bridge: Any) -> dict[str, Any]:
    _require(isinstance(bridge, dict) and set(bridge) == set(BRIDGE_HORIZONS), "scenario_bridge_horizons")
    normalized: dict[str, Any] = {}
    for horizon in BRIDGE_HORIZONS:
        cases = bridge[horizon]
        _require(isinstance(cases, dict) and set(cases) == set(CASES), f"scenario_cases:{horizon}")
        out = {}
        ordered = []
        for case in CASES:
            row = cases[case]
            _require(isinstance(row, dict), f"scenario_row:{horizon}:{case}")
            ret = _number(row.get("return"), f"scenario_return:{horizon}:{case}", -1.0)
            ordered.append(ret)
            assumptions = row.get("assumptions")
            _require(isinstance(assumptions, list) and bool(assumptions), f"scenario_assumptions:{horizon}:{case}")
            out[case] = {
                "return": ret,
                "assumptions": [_text(x, f"scenario_assumption:{horizon}:{case}", 1200) for x in assumptions],
            }
            # Scenario research must not smuggle unvalidated probabilities or ER.
            _require("probability" not in row, f"unvalidated_scenario_probability:{horizon}:{case}")
        _require(ordered == sorted(ordered), f"scenario_return_order:{horizon}")
        normalized[horizon] = out
    return normalized


def _validate_validated_er(value: dict[str, Any], benchmark_id: str) -> dict[str, Any]:
    _require(value.get("validation_status") == "WALK_FORWARD_VALIDATED", "er_not_walk_forward_validated")
    _require(value.get("benchmark_id") == benchmark_id, "er_benchmark_mismatch")
    _require(value.get("net_of_costs") is True, "er_not_net_of_costs")
    _require(value.get("unit") == "RETURN_FRACTION", "er_unit")
    horizons = {}
    for h in ER_HORIZONS:
        er = _number(value.get(f"expected_return_{h}"), f"er:{h}", -1.0)
        bench = _number(value.get(f"benchmark_expected_return_{h}"), f"benchmark_er:{h}", -1.0)
        horizons[h] = {
            "expected_return": er,
            "benchmark_expected_return": bench,
            "expected_alpha": er - bench,
        }
    _number(value.get("expected_drawdown"), "er_expected_drawdown", 0.0, 1.0)
    _number(value.get("downside_probability"), "er_downside_probability", 0.0, 1.0)
    return horizons


def evaluate_packet(packet: Any, cutoff: str, artifact_resolver: ArtifactResolver) -> dict[str, Any]:
    _require(isinstance(packet, dict), "packet_object")
    _require(packet.get("schema") == SCHEMA, "schema")
    asset_id = _identifier(packet.get("asset_id"), "asset_id")
    issuer_id = _identifier(packet.get("issuer_id"), "issuer_id")
    _identifier(packet.get("country"), "country")
    _identifier(packet.get("asset_class"), "asset_class")
    as_of = _stamp(packet.get("as_of"), "as_of")
    reviewed_at = _stamp(packet.get("reviewed_at"), "reviewed_at")
    cutoff_stamp = _stamp(cutoff, "cutoff")
    _require(as_of <= reviewed_at <= cutoff_stamp, "packet_time_order")
    _require(packet.get("review_status") == "RESEARCH_REVIEWED", "review_status")

    refs = packet.get("artifacts")
    _require(isinstance(refs, dict), "artifacts_object")
    required = {"methodology", "market_valuation", "source_graph"}
    _require(required <= set(refs), "required_artifacts")

    method, method_hash = _load_ref(
        refs["methodology"], expected_kind="METHODOLOGY_RESULT",
        asset_id=asset_id, issuer_id=issuer_id, as_of=as_of, resolver=artifact_resolver,
    )
    _validate_methodology(method)

    market, market_hash = _load_ref(
        refs["market_valuation"], expected_kind="MARKET_VALUATION_SNAPSHOT",
        asset_id=asset_id, issuer_id=issuer_id, as_of=as_of, resolver=artifact_resolver,
    )
    _validate_market(market, as_of)

    graph, graph_hash = _load_ref(
        refs["source_graph"], expected_kind="SOURCE_GRAPH",
        asset_id=asset_id, issuer_id=issuer_id, as_of=as_of, resolver=artifact_resolver,
    )
    _validate_source_graph(graph)

    moat_applicability = packet.get("moat_applicability")
    _require(moat_applicability in MOAT_APPLICABILITY, "moat_applicability")
    moat_hash = None
    if moat_applicability == "REQUIRED":
        _require("moat" in refs, "moat_artifact_required")
        moat, moat_hash = _load_ref(
            refs["moat"], expected_kind="MOAT_RESULT",
            asset_id=asset_id, issuer_id=issuer_id, as_of=as_of, resolver=artifact_resolver,
        )
        _validate_moat(moat)
    else:
        _require("moat" not in refs, "moat_artifact_not_applicable")

    thesis = packet.get("thesis")
    _require(isinstance(thesis, dict), "thesis_object")
    _require(thesis.get("status") in THESIS_STATUSES, "thesis_status")
    _text(thesis.get("counter_thesis"), "counter_thesis", 2400)
    catalysts = thesis.get("catalysts")
    invalidations = thesis.get("invalidation_conditions")
    _require(isinstance(catalysts, list) and bool(catalysts), "catalysts")
    _require(isinstance(invalidations, list) and bool(invalidations), "invalidation_conditions")
    for x in catalysts:
        _text(x, "catalyst", 1200)
    for x in invalidations:
        _text(x, "invalidation_condition", 1200)

    scenario_bridge = _validate_bridge(packet.get("scenario_research"))
    benchmark_id = market["benchmark_id"]

    validated_er_ref = refs.get("validated_er")
    validated_er = None
    er_hash = None
    if validated_er_ref is not None:
        er_value, er_hash = _load_ref(
            validated_er_ref, expected_kind="VALIDATED_ER_EVALUATION",
            asset_id=asset_id, issuer_id=issuer_id, as_of=as_of, resolver=artifact_resolver,
        )
        validated_er = _validate_validated_er(er_value, benchmark_id)

    status = "VALIDATED_ER_LINKED" if validated_er is not None else "SCENARIO_RESEARCH_COMPLETE"
    return {
        "schema": RESULT_SCHEMA,
        "status": status,
        "asset_id": asset_id,
        "issuer_id": issuer_id,
        "as_of": packet["as_of"],
        "reviewed_at": packet["reviewed_at"],
        "benchmark_id": benchmark_id,
        "methodology_sha256": method_hash,
        "moat_sha256": moat_hash,
        "market_valuation_sha256": market_hash,
        "source_graph_sha256": graph_hash,
        "validated_er_sha256": er_hash,
        "scenario_research": scenario_bridge,
        "validated_er": validated_er,
        "validated_expected_return_available": validated_er is not None,
        "scenario_probabilities_allowed": False,
        "scenario_research_is_expected_return": False,
        "historical_pit_certified": False,
        "selector_eligible": False,
        "portfolio_weight_effect": 0.0,
        "target_book_write_allowed": False,
        "orders_allowed": False,
        "production_authority": False,
        "packet_sha256": canonical_sha256(packet),
    }


__all__ = [
    "A3CandidatePacketError",
    "ARTIFACT_KINDS",
    "BRIDGE_HORIZONS",
    "CASES",
    "ER_HORIZONS",
    "MOAT_APPLICABILITY",
    "RESULT_SCHEMA",
    "SCHEMA",
    "THESIS_STATUSES",
    "canonical_sha256",
    "evaluate_packet",
]
