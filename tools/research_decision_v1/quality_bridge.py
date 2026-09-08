"""Opt-in quality adapter for the existing V1 valuation, not a second engine.

No provider envelope, scenario, return hurdle, NONRANKING output, production
readiness or weight is mutated. The portfolio handoff remains deliberately
blocked until integration and upstream cash/FX/source-verification fixes pass.
"""
from __future__ import annotations

import copy
import math
from datetime import date
from typing import Any

from .data import digest, number, timestamp
from .quality import assess_quality, _closed, _require, _text
from .valuation import evaluate_security, scenario_price

VARIABLE_UNITS = {"revenue": "currency", "margin": "fraction", "multiple": "multiple",
                  "net_debt": "currency", "diluted_shares": "shares", "dividend": "currency_per_share"}
BINDING_FIELDS = {"binding_id", "claim_id", "scenario", "variable", "direction", "old_value",
                  "new_value", "unit", "currency", "period", "economic_driver_id", "quantification",
                  "baseline_scenarios_hash"}


def validate_bindings(packet: dict, quality: dict, security: dict, baseline: dict | None) -> dict:
    """Validate explicit numerical assumptions; never invent or apply a number.

    A reviewed assumption range is not an observed fact. The before/after output
    is a fixed-current-price counterfactual, not evidence of a previous executed
    book. All numeric changes in the comparison must be covered by one binding.
    """
    output = {"status": "not_requested", "entries": [], "blockers": [], "numeric_values_applied": False}
    bindings = packet.get("bindings", []) if isinstance(packet, dict) else []
    if not bindings:
        return output
    if not quality.get("schema_valid") or not quality.get("review_receipt_valid"):
        output.update(status="blocked", blockers=["bindings_require_reviewed_packet"])
        return output
    claimed = {c["claim_id"]: c for c in quality["claims"]}
    current = security.get("blocks", {}).get("scenario", {})
    payload = current.get("payload", {})
    scenarios = payload.get("scenarios", [])
    current_map = {s["name"]: s for s in scenarios if isinstance(s, dict) and "name" in s}
    baseline_map = {}
    if isinstance(baseline, dict):
        baseline_map = {s["name"]: s for s in baseline.get("scenarios", []) if isinstance(s, dict) and "name" in s}
    occupied, drivers, ids, verified_numeric = set(), set(), set(), []
    for b in bindings:
        try:
            _closed(b, BINDING_FIELDS, "binding_schema")
            for field in ("binding_id", "claim_id", "economic_driver_id"):
                _text(b[field], "binding_identifier")
            _require(b["binding_id"] not in ids, "duplicate_binding_id")
            ids.add(b["binding_id"])
            c = claimed.get(b["claim_id"], {})
            _require(c.get("effective_status") == "supported", "binding_claim_unverified_or_conflicted")
            variable = b["variable"]
            _require(variable in VARIABLE_UNITS, "binding_variable_not_supported")
            _require(b["unit"] == VARIABLE_UNITS[variable], "binding_unit_mismatch")
            _require(b["currency"] == security["currency"], "binding_currency_mismatch")
            _require(b["scenario"] in {"Bear", "Base", "Bull"}, "binding_scenario")
            _require(b["direction"] in {"increase", "decrease", "unchanged"}, "binding_direction")
            _closed(b["period"], {"start", "end"}, "binding_period")
            start, end = date.fromisoformat(b["period"]["start"]), date.fromisoformat(b["period"]["end"])
            _require(start < end, "binding_period")
            identity = (b["scenario"], variable)
            _require(identity not in occupied, "duplicate_variable_binding")
            occupied.add(identity)
            if b["new_value"] is None:
                _require(b["quantification"] is None and b["old_value"] is None and b["baseline_scenarios_hash"] is None,
                         "direction_only_must_not_encode_number")
                output["entries"].append({"binding_id": b["binding_id"], "claim_id": b["claim_id"],
                                          "variable": variable, "scenario": b["scenario"], "direction": b["direction"],
                                          "unit": b["unit"], "currency": b["currency"], "period": b["period"],
                                          "status": "direction_only", "value_changed": False})
                continue
            number(b["old_value"])
            new = number(b["new_value"])
            q = b["quantification"]
            _closed(q, {"kind", "low", "high", "rationale"}, "quantification_schema")
            _require(q["kind"] in {"source_range", "reviewed_scenario_assumption"}, "quantification_kind")
            _text(q["rationale"], "quantification_rationale")
            _require(number(q["low"]) <= new <= number(q["high"]), "quantification_range")
            direction = "increase" if new > b["old_value"] else "decrease" if new < b["old_value"] else "unchanged"
            _require(direction == b["direction"], "direction_value_mismatch")
            _require(isinstance(baseline, dict) and b["baseline_scenarios_hash"] == digest(baseline), "baseline_hash_mismatch")
            _require(baseline.get("method") == payload.get("method"), "baseline_method_mismatch")
            _require(b["period"] == current.get("report_period") == baseline.get("report_period"), "binding_period_mismatch")
            old_s, new_s = baseline_map[b["scenario"]], current_map[b["scenario"]]
            _require(number(old_s[variable]) == b["old_value"] and number(new_s[variable]) == new,
                     "binding_does_not_match_scenarios")
            # One economic driver may affect a different variable in a mutually
            # exclusive scenario, not both margin and multiple in the same one.
            driver = (b["economic_driver_id"], b["scenario"])
            _require(driver not in drivers, "economic_driver_double_count")
            drivers.add(driver)
            verified_numeric.append(identity)
            output["entries"].append({"binding_id": b["binding_id"], "claim_id": b["claim_id"],
                                      "variable": variable, "scenario": b["scenario"],
                                      "old_value": b["old_value"], "new_value": new, "unit": b["unit"],
                                      "currency": b["currency"], "period": b["period"],
                                      "quantification_kind": q["kind"], "status": "reviewed_numeric_link",
                                      "value_changed": new != b["old_value"]})
        except (ValueError, KeyError, TypeError):
            output["blockers"].append("invalid_binding_" + str(len(output["entries"])))
    if verified_numeric:
        try:
            _require(len(baseline_map) == len(current_map) == 3, "three_scenarios_required")
            differences = set()
            for name in ("Bear", "Base", "Bull"):
                a, b = baseline_map[name], current_map[name]
                _require(a["probability"] == b["probability"], "quality_cannot_change_probability")
                for variable in VARIABLE_UNITS:
                    if number(a[variable]) != number(b[variable]):
                        differences.add((name, variable))
            _require(differences <= set(verified_numeric), "unbound_scenario_changes")
            method = payload["method"]
            before = {name: scenario_price(s, method) for name, s in baseline_map.items()}
            after = {name: scenario_price(s, method) for name, s in current_map.items()}
            output["counterfactual"] = {"basis": "same_current_price_not_prior_execution",
                "baseline_hash": digest(baseline), "current_scenarios_hash": digest(scenarios),
                "target_prices_before": before, "target_prices_after": after,
                "target_price_deltas": {name: after[name] - before[name] for name in sorted(before)}}
        except (ValueError, KeyError, TypeError):
            output["blockers"].append("comparison_unbound_or_invalid")
    output["status"] = "blocked" if output["blockers"] else "verified_links_only"
    if output["blockers"]:
        output.pop("counterfactual", None)
    return output


def evaluate_with_quality(security: dict, config: dict, cutoff: str, *, packet: Any,
                          corpus: Any, receipt: Any, data_kind: str,
                          baseline: dict | None = None) -> dict:
    """Use actual V1 valuation and return an explicitly non-portfolio sidecar.

    Callers must use the source-pinned H1/H2 runtime; this API is not a substitute
    for export replay. It never clears an existing input blocker. The old
    company_quality label is ignored by this adapter, including in nested output.
    """
    quality = assess_quality(packet, corpus, receipt, security_id=security["security_id"],
                             data_kind=data_kind, cutoff=cutoff)
    # Quality analysis happens first and survives V1's early return on price/data.
    valuation = evaluate_security(copy.deepcopy(security), copy.deepcopy(config), cutoff)
    company = quality["company_assessment"]
    valuation["four_questions"]["good_company"] = company
    bridge = validate_bindings(packet, quality, security, baseline)
    questions = copy.deepcopy(valuation["four_questions"])
    if company != "pass" or bridge["status"] == "blocked":
        questions["good_stock"] = "fail" if company == "fail" else "unverified"
        questions["buy_price_now"] = "wait" if valuation["valuation_ready"] else "unverified"
    questions["portfolio_value"] = "blocked_pending_portfolio_integration"
    valuation["four_questions"] = copy.deepcopy(questions)
    return {"schema_version": "research-quality-valuation-sidecar-v1", "security_id": security["security_id"],
            "data_kind": data_kind, "decision_cutoff": cutoff, "quality": quality, "valuation": valuation,
            "scenario_links": bridge, "four_questions": questions,
            "legacy_company_label_used": False, "orders_allowed": False,
            "portfolio_proposal_ready": False, "production_promoted": False, "oos_validated": False,
            "integration_scope": "quality_to_existing_valuation_only",
            "blockers": sorted(set(valuation["blockers"] + quality["blockers"] + bridge["blockers"] +
                                   ["portfolio_integration_and_upstream_review_pending"]))}
