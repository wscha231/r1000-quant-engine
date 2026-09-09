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

from .data import MARKETS, digest, envelope_errors, export_market, number, timestamp
from .quality import assess_quality, _closed, _require, _text
from .valuation import evaluate_security, scenario_price, target_date

VARIABLE_UNITS = {"revenue": "currency", "margin": "fraction", "multiple": "multiple",
                  "net_debt": "currency", "diluted_shares": "shares", "dividend": "currency_per_share"}
BINDING_FIELDS = {"binding_id", "claim_id", "scenario", "variable", "direction", "old_value",
                  "new_value", "unit", "currency", "period", "economic_driver_id", "quantification",
                  "baseline_scenarios_hash"}


BASELINE_FIELDS = {"schema_version", "security_id", "market", "currency", "data_kind",
                   "decision_cutoff", "method", "report_period", "scenarios"}
SCENARIO_FIELDS = {"name", "probability", *VARIABLE_UNITS}


def _scenario_map(rows: Any, method: str) -> dict:
    """Validate scenario domains before emitting a numeric comparison."""
    _require(method in {"PE", "EV_EBITDA"}, "unsupported_valuation_method")
    _require(isinstance(rows, list) and len(rows) == 3, "three_scenarios_required")
    result = {}
    for row in rows:
        _closed(row, SCENARIO_FIELDS, "scenario_fields")
        name = row["name"]
        _require(name in {"Bear", "Base", "Bull"} and name not in result, "scenario_identity")
        _require(0 <= number(row["probability"]) <= 1, "scenario_probability")
        number(scenario_price(row, method), nonnegative=True)  # V1 domain plus finite output.
        result[name] = row
    _require(math.isclose(sum(r["probability"] for r in rows), 1., abs_tol=1e-12), "probability_sum")
    prices = [scenario_price(result[name], method) for name in ("Bear", "Base", "Bull")]
    values = [prices[i] + result[name]["dividend"] for i, name in enumerate(("Bear", "Base", "Bull"))]
    for numbers in (prices, values):
        for value in numbers: number(value, nonnegative=True)
        _require(all(a <= b or math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
                     for a, b in zip(numbers, numbers[1:])), "scenario_order")
    return result


def _numeric_context(packet: dict, quality: dict, security: dict, baseline: dict) -> tuple:
    """Current envelopes and baseline identities must agree before using bytes.

    The baseline is a reviewed counterfactual at the current cutoff, not an
    attestation that an old portfolio or historical market snapshot existed.
    """
    cutoff = quality["decision_cutoff"]
    _require(packet["security_id"] == quality["security_id"] == security["security_id"], "quality_security_mismatch")
    _require(packet["data_kind"] == quality["data_kind"] and quality["data_kind"] in {"REAL", "SYNTHETIC"}, "quality_data_kind")
    _require(security.get("data_kind", quality["data_kind"]) == quality["data_kind"], "security_data_kind")
    market = security["market"]
    _require(market in MARKETS and security["currency"] == MARKETS[market][0] and
             security["security_id"].startswith(market + ":"), "security_market_currency")
    _closed(baseline, BASELINE_FIELDS, "baseline_schema")
    _require(baseline["schema_version"] == "quality-scenario-baseline-v1", "baseline_version")
    for field in ("security_id", "market", "currency"):
        _require(baseline[field] == security[field], "baseline_identity_mismatch")
    _require(baseline["data_kind"] == quality["data_kind"] and baseline["decision_cutoff"] == cutoff, "baseline_kind_cutoff")
    current = security.get("blocks", {}).get("scenario")
    _require(not envelope_errors(current, security, cutoff), "scenario_envelope_not_admitted")
    _require(current["unit"] == "scenario_currency_and_shares" and
             current["accounting_basis"] == "RESEARCH_ASSUMPTION", "scenario_basis_unit")
    payload = current["payload"]
    _require(payload["probability_type"] == "SUBJECTIVE_SCENARIO" and
             payload["company_type"] == "PROFITABLE_OPERATING", "scenario_semantics")
    _require(type(payload["horizon_months"]) is int and payload["horizon_months"] == 12 and
             payload["target_date"] == target_date(cutoff), "scenario_horizon")
    _require(current["report_period"] == baseline["report_period"] ==
             {"start": timestamp(cutoff).date().isoformat(), "end": target_date(cutoff)}, "scenario_period")
    _text(payload["rationale"], "scenario_rationale")
    _require(baseline["method"] == payload["method"], "baseline_method")
    return (current, payload, _scenario_map(payload["scenarios"], payload["method"]),
            _scenario_map(baseline["scenarios"], payload["method"]))



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
    current, payload, current_map, baseline_map = {}, {}, {}, {}
    numeric = any(isinstance(b, dict) and b.get("new_value") is not None for b in bindings)
    if numeric:
        try:
            current, payload, current_map, baseline_map = _numeric_context(packet, quality, security, baseline)
        except (ValueError, KeyError, TypeError, AttributeError):
            output.update(status="blocked", blockers=["numeric_context_not_admitted"])
            return output
    scenarios = payload.get("scenarios", [])
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
            values_before = {name: before[name] + baseline_map[name]["dividend"] for name in before}
            values_after = {name: after[name] + current_map[name]["dividend"] for name in after}
            comparison = {"basis": "same_current_price_not_prior_execution",
                "baseline_hash": digest(baseline), "current_scenarios_hash": digest(scenarios),
                "currency": security["currency"], "value_unit": "currency_per_share",
                "target_prices_before": before, "target_prices_after": after,
                "target_price_deltas": {name: after[name] - before[name] for name in sorted(before)},
                "terminal_values_before": values_before, "terminal_values_after": values_after,
                "terminal_value_deltas": {name: values_after[name] - values_before[name] for name in sorted(before)},
                "return_status": "price_not_admitted", "current_price": None,
                "total_return_deltas": None, "expected_total_return_delta": None,
                "costs_and_personal_taxes_included": False}
            # Target value is meaningful without a current price. A percentage
            # return is not; never replace a missing/rejected price with a value.
            try:
                _require(not any(str(b).startswith("price:") for b in security.get("blockers", [])), "price_blocked")
                # Replay the canonical H1 price admission, independently of
                # missing financials. A caller-supplied discovery value is not
                # evidence of admission and must match the verified bars.
                price_input = {k: security[k] for k in ("security_id", "market", "currency")}
                price_input.update(ticker=security["security_id"].split(":", 1)[1],
                    listing_board=security.get("listing_board"),
                    blocks={"price": security["blocks"].get("price")})
                replay = export_market({"schema_version": "research-input-v1",
                    "market": security["market"], "data_kind": quality["data_kind"],
                    "decision_cutoff": quality["decision_cutoff"], "securities": [price_input]},
                    security["market"])["securities"][0]
                _require(not any(b.startswith("price:") for b in replay["blockers"]), "price_not_admitted")
                price = number(replay["discovery"]["price"], positive=True)
                _require(price == number(security["discovery"]["price"], positive=True), "price_discovery_mismatch")
            except (ValueError, KeyError, TypeError):
                pass
            else:
                old_returns = {name: number(values_before[name] / price - 1.) for name in before}
                new_returns = {name: number(values_after[name] / price - 1.) for name in after}
                deltas = {name: new_returns[name] - old_returns[name] for name in before}
                comparison.update(return_status="available", current_price=price,
                    total_returns_before=old_returns, total_returns_after=new_returns,
                    total_return_deltas=deltas,
                    expected_total_return_delta=sum(current_map[name]["probability"] * deltas[name] for name in before))
            output["counterfactual"] = comparison
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
