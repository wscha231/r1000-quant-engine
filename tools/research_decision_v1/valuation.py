"""Business-to-equity scenarios. No learned or legacy diagnostic score inputs."""
from __future__ import annotations
import copy
import math
from datetime import date
from tools.research_decision_v1.data import envelope_errors, number, timestamp


def target_date(cutoff):
    d = timestamp(cutoff).date()
    try: return d.replace(year=d.year+1).isoformat()
    except ValueError: return d.replace(year=d.year+1, day=28).isoformat()


def scenario_price(s, method):
    revenue = number(s["revenue"], positive=True)
    margin = number(s["margin"], positive=True)
    if margin > 1: raise ValueError("margin_above_one")
    multiple = number(s["multiple"], positive=True)
    shares = number(s["diluted_shares"], positive=True)
    debt = number(s["net_debt"])
    number(s["dividend"], nonnegative=True)
    if method not in {"EV_EBITDA", "PE"}: raise ValueError("unsupported_valuation_method")
    value = revenue * margin * multiple - (debt if method == "EV_EBITDA" else 0.)
    return max(0., value) / shares


def evaluate_security(security, config, cutoff):
    row = {"security_id": security["security_id"], "market": security["market"],
           "currency": security["currency"], "blockers": list(security["blockers"]),
           "discovery": copy.deepcopy(security.get("discovery")),
           "valuation_ready": False, "expected_total_return": None, "expected_excess_return": None,
           "statistical_loss_probability": None, "calibration_validated": False,
           "short_horizons": {str(h): {"return": None, "reason": "no_independent_horizon_evidence"} for h in (1, 3, 6)},
           "four_questions": {"good_company": "unverified", "good_stock": "unverified", "buy_price_now": "unverified", "portfolio_value": "unverified"}}
    block = security.get("blocks", {}).get("scenario")
    es = envelope_errors(block, security, cutoff)
    row["blockers"] += ["scenario:" + e for e in es]
    if row["blockers"]: return row
    try:
        if block["unit"] != "scenario_currency_and_shares" or block["accounting_basis"] != "RESEARCH_ASSUMPTION":
            raise ValueError("scenario_basis_or_unit_mismatch")
        p = block["payload"]
        if p["probability_type"] != "SUBJECTIVE_SCENARIO": raise ValueError("calibrated_forecast_not_implemented")
        if p["company_type"] != "PROFITABLE_OPERATING": raise ValueError("unsupported_company_type")
        if p["horizon_months"] != 12 or p["target_date"] != target_date(cutoff): raise ValueError("horizon_mismatch")
        if block["report_period"] != {"start": timestamp(cutoff).date().isoformat(), "end": p["target_date"]}: raise ValueError("scenario_period_mismatch")
        if not p.get("rationale"): raise ValueError("scenario_rationale_missing")
        ss = p["scenarios"]
        if len(ss) != 3 or {s["name"] for s in ss} != {"Bear", "Base", "Bull"}: raise ValueError("three_unique_scenarios_required")
        if any(not 0 <= number(s["probability"]) <= 1 for s in ss) or not math.isclose(sum(s["probability"] for s in ss), 1., abs_tol=1e-12):
            raise ValueError("probabilities_must_sum_to_one")
        if any(set(s) != {"name", "probability", "revenue", "margin", "multiple", "net_debt", "diluted_shares", "dividend"} for s in ss):
            raise ValueError("scenario_fields_invalid_or_double_counted_buyback")
        fundamental = security["blocks"]["financials"]["payload"]["ttm"]
        actual_metric = fundamental["ebitda"] if p["method"] == "EV_EBITDA" else fundamental["net_income"]
        if actual_metric <= 0: raise ValueError("valuation_metric_nonpositive")
        price = number(security["discovery"]["price"], positive=True)
        valued = []
        for s in sorted(ss, key=lambda s: {"Bear": 0, "Base": 1, "Bull": 2}[s["name"]]):
            target = scenario_price(s, p["method"])
            valued.append({**s, "target_price": target, "total_return": (target + s["dividend"]) / price - 1.})
        if [s["target_price"] for s in valued] != sorted(s["target_price"] for s in valued): raise ValueError("scenario_target_order_invalid")
        expected = sum(s["probability"] * s["total_return"] for s in valued)
        bear, base, bull = valued
        one_way = config["one_way_cost_bps"][security["market"]] / 10000.
        net = expected - 2 * one_way
        utility = net - config["downside_penalty"] * max(0., -bear["total_return"]) - config["dispersion_penalty"] * (bull["total_return"] - bear["total_return"])
        required_revenue = (price * base["diluted_shares"] + (base["net_debt"] if p["method"] == "EV_EBITDA" else 0.)) / (base["margin"] * base["multiple"])
        sensitivity = {}
        for field in ("margin", "multiple", "diluted_shares"):
            sensitivity[field] = []
            for delta in (-config["sensitivity_fraction"], config["sensitivity_fraction"]):
                changed = {**base, field: base[field] * (1 + delta)}
                sensitivity[field].append({"delta": delta, "target_price": scenario_price(changed, p["method"])})
        t = security["blocks"]["thesis"]["payload"]
        risk = security["blocks"]["risk"]["payload"]
        utility -= risk["uncertainty"] * config["dispersion_penalty"]
        row.update(valuation_ready=True, probability_type="SUBJECTIVE_SCENARIO", method=p["method"],
                   current_price=price, scenarios=valued, expected_total_return=expected,
                   expected_net_return=net, investment_utility=utility, downside_loss=max(0., -bear["total_return"]),
                   uncertainty=risk["uncertainty"], scenario_range=bull["total_return"]-bear["total_return"],
                   reverse_valuation={"required_revenue": required_revenue, "required_growth": required_revenue/fundamental["revenue"]-1,
                                      "conditional_on": "Base margin, multiple, future shares and debt; price only, excludes dividend"},
                   sensitivity=sensitivity, strongest_bear_case=t["strongest_bear_case"], catalyst=t["catalyst"],
                   invalidation_condition=t["invalidation_condition"], source_evidence=t["source_evidence"],
                   cost_assumption={"one_way_bps": config["one_way_cost_bps"][security["market"]], "income_tax_included": False},
                   four_questions={"good_company": t["company_quality"], "good_stock": "pass" if utility > 0 else "fail",
                                   "buy_price_now": "pass" if net >= config["new_entry_net_return"] else "wait", "portfolio_value": "pending_risk_constraints"})
    except (ValueError, KeyError, TypeError) as exc:
        row["blockers"].append("valuation:" + str(exc))
    return row
