"""Conservative research proposals; no broker imports or order writers."""
from __future__ import annotations
import math
from tools.research_decision_v1.data import number, source_url, timestamp


def context_errors(context, config, cutoff):
    errors = []
    try:
        if context["decision_cutoff"] != cutoff: errors.append("context_cutoff_mismatch")
        if context["mode"] not in {"NEW_CAPITAL_RESEARCH", "EXISTING_BOOK_PROPOSAL"}: errors.append("invalid_account_mode")
        number(context["capital_krw"], positive=True)
        fx = context["fx"]
        if fx["status"] != "available" or fx["pair"] != "KRW_PER_USD": errors.append("fx_unavailable_or_pair_invalid")
        source_url(fx["source"]); number(fx["spot"], positive=True)
        age = (timestamp(cutoff)-timestamp(fx["observed_at"])).total_seconds()/3600
        if not 0 <= age <= config["fx_max_age_hours"]: errors.append("fx_future_or_stale")
        if fx["assumption_type"] != "SUBJECTIVE_SCENARIO" or set(fx["scenario_rates"]) != {"Bear", "Base", "Bull"}: errors.append("fx_scenarios_invalid")
        for value in fx["scenario_rates"].values(): number(value, positive=True)
    except (ValueError, KeyError, TypeError): errors.append("fx_or_capital_unverified")
    try:
        regime = context["regime"]; source_url(regime["source"])
        age = (timestamp(cutoff)-timestamp(regime["observed_at"])).total_seconds()/3600
        if not 0 <= age <= config["regime_max_age_hours"]: errors.append("regime_future_or_stale")
        if regime["state"] not in config["gross_caps"] or regime["state"] == "UNKNOWN" or not regime.get("rationale"):
            errors.append("regime_unverified")
    except (ValueError, KeyError, TypeError): errors.append("regime_unverified")
    return sorted(set(errors))


def add_fx_returns(rows, context, config, fx_valid):
    for row in rows:
        row.update(expected_total_return_krw=None, investment_rank=None, expected_return_rank=None,
                   investment_rank_local=None, expected_return_rank_local=None)
        if not row["valuation_ready"]: continue
        benchmark = context.get("benchmark_expected_returns", {}).get(row["market"])
        if benchmark is not None:
            number(benchmark)
            row["expected_excess_return"] = row["expected_total_return"] - benchmark
            row["benchmark_forecast_type"] = "SUBJECTIVE_SCENARIO"
        if not fx_valid: continue
        converted = []
        for s in row["scenarios"]:
            ratio = context["fx"]["scenario_rates"][s["name"]]/context["fx"]["spot"] if row["currency"] == "USD" else 1.
            converted.append({"name": s["name"], "probability": s["probability"], "total_return_krw": (1+s["total_return"])*ratio-1., "fx_ratio": ratio})
        mean = sum(s["probability"]*s["total_return_krw"] for s in converted)
        values = [s["total_return_krw"] for s in converted]
        utility = mean - 2*config["one_way_cost_bps"][row["market"]]/10000 - config["downside_penalty"]*max(0., -min(values)) - config["dispersion_penalty"]*(max(values)-min(values)+row["uncertainty"])
        row.update(scenarios_krw=converted, expected_total_return_krw=mean, investment_utility_krw=utility)
    # Deterministic ID tie-break; no momentum or NONRANKING values in either rank.
    for market in ("US", "KR"):
        group = [r for r in rows if r["market"] == market and r["valuation_ready"]]
        for rank, r in enumerate(sorted(group, key=lambda r: (-r["expected_total_return"], r["security_id"])), 1): r["expected_return_rank_local"] = rank
        for rank, r in enumerate(sorted(group, key=lambda r: (-r["investment_utility"], -r["expected_total_return"], r["security_id"])), 1): r["investment_rank_local"] = rank
    if fx_valid:
        group = [r for r in rows if r["valuation_ready"]]
        for rank, r in enumerate(sorted(group, key=lambda r: (-r["expected_total_return_krw"], r["security_id"])), 1): r["expected_return_rank"] = rank
        for rank, r in enumerate(sorted(group, key=lambda r: (-r["investment_utility_krw"], -r["expected_total_return_krw"], r["security_id"])), 1): r["investment_rank"] = rank


def read_book(context, ids, cutoff):
    if context["mode"] == "NEW_CAPITAL_RESEARCH":
        if context.get("book"): raise ValueError("new_capital_must_not_relabel_existing_book")
        return {}, 1.
    book = context.get("book", {})
    source_url(book["source"])
    if book.get("decision_cutoff") != cutoff or book.get("currency") != "KRW": raise ValueError("book_cutoff_or_currency_unverified")
    if not 0 <= (timestamp(cutoff)-timestamp(book["verified_at"])).total_seconds() <= 86400: raise ValueError("book_verification_stale")
    if book.get("pending_orders") != []: raise ValueError("pending_orders_require_reconciliation")
    positions = book["positions"]
    if not isinstance(positions, dict) or set(positions) - ids: raise ValueError("book_holdings_missing_from_risk_universe")
    for value in positions.values():
        if not 0 <= number(value) <= 1: raise ValueError("book_weight_invalid")
    cash = number(book["cash_weight"], nonnegative=True)
    if not math.isclose(sum(positions.values())+cash, 1., abs_tol=1e-10): raise ValueError("book_weights_do_not_sum_to_one")
    return dict(positions), cash


def constraint_audit(weights, securities, rows, context, config):
    lookup = {r["security_id"]: r for r in rows}
    countries, groups, violations, reviews = {}, {}, [], []
    stress = 0.
    for sid, w in sorted(weights.items()):
        if w <= 0: continue
        s, row = securities[sid], lookup[sid]
        market = s["market"]; risk = s["blocks"]["risk"]["payload"]
        countries[market] = countries.get(market, 0.) + w
        for group, exposure in risk["exposures"].items(): groups[group] = groups.get(group, 0.) + w*exposure
        fx_loss = max(0., 1-min(context["fx"]["scenario_rates"].values())/context["fx"]["spot"]) if market == "US" else 0.
        shock = max(row.get("downside_loss", 0.), risk["stress_loss"])
        stress += w * (1-(1-shock)*(1-fx_loss))
        local_capital = context["capital_krw"]/(context["fx"]["spot"] if market == "US" else 1.)
        if w * local_capital > s["discovery"]["adv20_local"] * config["max_adv_participation"] + .01: violations.append(sid+":liquidity")
        if w > config["max_security_weight"]+1e-10: violations.append(sid+":concentration")
        if w > .05:
            reviews.append({"security_id": sid, "risk_review": True,
                            "concentration_review": w > .10, "weight": w,
                            "bear_case": row.get("strongest_bear_case"), "common_exposures": risk["exposures"],
                            "stress_loss": shock, "liquidity_checked": True})
    gross = sum(weights.values())
    if gross > config["gross_caps"][context["regime"]["state"]] + 1e-10: violations.append("regime_gross_cap")
    for market, w in countries.items():
        if w > config["country_caps"][market]+1e-10: violations.append(market+":country_cap")
    for group, w in groups.items():
        if w > config["group_caps"][group.split(":")[0]]+1e-10: violations.append(group+":common_risk_cap")
    if stress > config["max_stress_loss"]+1e-10: violations.append("stress_loss_cap")
    return {"country_exposure": countries, "common_risk_exposure": groups, "gross_exposure": gross,
            "scenario_stress_loss": stress, "scenario_stress_limit": config["max_stress_loss"],
            "mdd_validated": False, "mdd_constraint_status": "NOT_OOS_TESTED",
            "correlation_model": "conservative_common_group_caps; no estimated_correlation_claim",
            "violations": sorted(set(violations)), "reviews": reviews}


def propose(rows, securities, context, config, common_errors, cutoff):
    reasons = {r["security_id"]: list(r["blockers"]) for r in rows}
    prior, cash_prior = {}, 1.
    errors = list(common_errors)
    try: prior, cash_prior = read_book(context, set(securities), cutoff)
    except (ValueError, KeyError, TypeError) as exc: errors.append("book:"+str(exc))
    proposal = {"mode": context.get("mode"), "ready": False, "orders_allowed": False,
                "broker_reconciled": False, "rows": [], "cash_weight": None,
                "constraints": {}, "blockers": errors, "capital_krw": context.get("capital_krw"),
                "capital_is_assumption": context.get("capital_is_assumption", False),
                "risk_limit_is_future_guarantee": False}
    if errors:
        for r in rows:
            r["four_questions"]["portfolio_value"] = "blocked_common_input"
            proposal["rows"].append({"security_id": r["security_id"], "action": "WAIT", "target_weight": 0. if context.get("mode") == "NEW_CAPITAL_RESEARCH" else None, "reasons": reasons[r["security_id"]] + errors})
        if context.get("mode") == "NEW_CAPITAL_RESEARCH": proposal["cash_weight"] = 1.; proposal["cash_is_unallocated_fallback"] = True
        return proposal
    eligible, count = [], {"US": 0, "KR": 0}
    for r in sorted(rows, key=lambda r: (r["investment_rank"] or 10**9, r["security_id"])):
        sid = r["security_id"]
        if not r["valuation_ready"]: continue
        s = securities[sid]; t, risk = s["blocks"]["thesis"]["payload"], s["blocks"]["risk"]["payload"]
        if risk["integrity_alert"] or risk["liquidity_restriction"] or not t["intact"] or t["company_quality"] != "pass":
            reasons[sid].append("thesis_quality_or_risk_gate"); continue
        threshold = config["hold_net_return"] if prior.get(sid, 0.) else config["new_entry_net_return"]
        if r["expected_net_return"] < threshold or r["investment_utility_krw"] <= 0:
            reasons[sid].append("net_return_or_risk_adjusted_utility_below_threshold"); continue
        if count[r["market"]] >= config["target_counts"][r["market"]]:
            reasons[sid].append("country_candidate_count_limit"); continue
        count[r["market"]] += 1; eligible.append(r)
    raw = {r["security_id"]: r["investment_utility_krw"] * securities[r["security_id"]]["blocks"]["thesis"]["payload"]["confidence"] / max(config["min_downside_denominator"], r["downside_loss"], securities[r["security_id"]]["blocks"]["risk"]["payload"]["stress_loss"]) for r in eligible}
    total = sum(raw.values()); budget = config["gross_caps"][context["regime"]["state"]]
    weights = {sid: min(config["max_security_weight"], value/total*budget) if total else 0. for sid, value in raw.items()}
    # Shrink for constraints; do not force cash into missing/low-conviction names.
    for sid in weights:
        s = securities[sid]; fx = context["fx"]["spot"] if s["market"] == "US" else 1.
        cap = s["discovery"]["adv20_local"] * fx * config["max_adv_participation"] / context["capital_krw"]
        weights[sid] = min(weights[sid], cap)
    for market in ("US", "KR"):
        members = [sid for sid in weights if securities[sid]["market"] == market]
        amount = sum(weights[sid] for sid in members)
        scale = min(1., config["country_caps"][market]/amount) if amount else 1.
        for sid in members: weights[sid] *= scale
    groups = sorted({g for sid in weights for g in securities[sid]["blocks"]["risk"]["payload"]["exposures"]})
    for group in groups:
        members = {sid: securities[sid]["blocks"]["risk"]["payload"]["exposures"].get(group, 0.) for sid in weights}
        exposure = sum(weights[sid]*e for sid, e in members.items())
        scale = min(1., config["group_caps"][group.split(":")[0]]/exposure) if exposure else 1.
        for sid, e in members.items():
            if e: weights[sid] *= scale
    audit = constraint_audit(weights, securities, rows, context, config)
    if audit["scenario_stress_loss"] > config["max_stress_loss"]:
        scale = config["max_stress_loss"]/audit["scenario_stress_loss"]
        weights = {sid: w*scale for sid, w in weights.items()}
    weights = {sid: math.floor(w*1e8)/1e8 if w >= config["minimum_weight"] else 0. for sid, w in weights.items()}
    if prior:
        # An intact incumbent is the actual opportunity-cost comparison.
        by_id = {r["security_id"]: r for r in rows}
        for sid, old in prior.items():
            s = securities[sid]; row = by_id[sid]
            if not row["valuation_ready"]:
                proposal["blockers"].append(sid+":incumbent_evidence_missing_preserve_book")
                continue
            thesis = s["blocks"]["thesis"]["payload"]
            risk = s["blocks"]["risk"]["payload"]
            if not thesis["intact"] or risk["integrity_alert"]:
                weights[sid] = 0.; reasons[sid].append("thesis_or_integrity_exit_proposal"); continue
            desired = weights.get(sid, 0.)
            if abs(desired-old) < config["no_trade_weight_buffer"]:
                weights[sid] = old; reasons[sid].append("no_trade_buffer"); continue
            if desired > old and not thesis["strengthened"]:
                weights[sid] = old; reasons[sid].append("add_requires_strengthened_thesis"); continue
            if desired < old:
                alternatives = [r for r in eligible if r["security_id"] not in prior]
                cost = 2 * config["one_way_cost_bps"][s["market"]]/10000
                benefit = max((r["investment_utility_krw"]-row["investment_utility_krw"] for r in alternatives), default=0.)
                if benefit <= config["replacement_improvement_buffer"]+cost:
                    weights[sid] = old; reasons[sid].append("keep_incumbent_replacement_not_cost_justified")
                else: reasons[sid].append("replacement_improves_incumbent_after_cost_buffer")
        if proposal["blockers"]:
            # Preserve the whole submitted book when incumbent risk cannot be measured.
            proposal.update(cash_weight=cash_prior, cash_is_unallocated_fallback=False)
            proposal["rows"] = [{"security_id": r["security_id"], "action": "HOLD" if prior.get(r["security_id"]) else "WAIT", "target_weight": prior.get(r["security_id"], 0.), "reasons": reasons[r["security_id"]]+proposal["blockers"]} for r in rows]
            return proposal
        # Retained positions consume budget first; proposals are never leveraged.
        existing_gross = sum(weights.get(sid, 0.) for sid in prior)
        new_gross = sum(w for sid, w in weights.items() if sid not in prior)
        scale = max(0., min(1., (budget-existing_gross)/new_gross)) if new_gross else 1.
        for sid in weights:
            if sid not in prior: weights[sid] *= scale
        # Preserve incumbents while fitting new proposals into the remaining
        # country/common-risk/stress room. An incumbent-only breach stays explicit.
        for market in ("US", "KR"):
            occupied = sum(weights.get(sid, 0.) for sid in prior if securities[sid]["market"] == market)
            new_ids = [sid for sid in weights if sid not in prior and securities[sid]["market"] == market]
            amount = sum(weights[sid] for sid in new_ids)
            factor = max(0., min(1., (config["country_caps"][market]-occupied)/amount)) if amount else 1.
            for sid in new_ids: weights[sid] *= factor
        for group in sorted({g for sid in weights for g in securities[sid]["blocks"]["risk"]["payload"]["exposures"]}):
            exposures = {sid: securities[sid]["blocks"]["risk"]["payload"]["exposures"].get(group, 0.) for sid in weights}
            occupied = sum(weights.get(sid, 0.)*exposures.get(sid, 0.) for sid in prior)
            amount = sum(weights[sid]*e for sid, e in exposures.items() if sid not in prior)
            factor = max(0., min(1., (config["group_caps"][group.split(":")[0]]-occupied)/amount)) if amount else 1.
            for sid, e in exposures.items():
                if sid not in prior and e: weights[sid] *= factor
        prior_stress = constraint_audit({sid: weights.get(sid, 0.) for sid in prior}, securities, rows, context, config)["scenario_stress_loss"]
        new_stress = constraint_audit({sid: w for sid, w in weights.items() if sid not in prior}, securities, rows, context, config)["scenario_stress_loss"]
        factor = max(0., min(1., (config["max_stress_loss"]-prior_stress)/new_stress)) if new_stress else 1.
        for sid in weights:
            if sid not in prior:
                weights[sid] *= factor
                if weights[sid] < config["minimum_weight"]: weights[sid] = 0.
    audit = constraint_audit(weights, securities, rows, context, config)
    # Existing-book no-trade preservation may conflict with hard risk caps. Surface
    # the conflict for review instead of silently overriding a thesis or a cap.
    proposal["blockers"] += audit["violations"]
    valuation_observed = any(r["valuation_ready"] for r in rows)
    proposal.update(ready=not audit["violations"] and valuation_observed, constraints=audit,
                    cash_weight=1-sum(weights.values()), cash_is_unallocated_fallback=not valuation_observed,
                    turnover=sum(abs(weights.get(sid, 0.)-prior.get(sid, 0.)) for sid in set(weights)|set(prior)),
                    estimated_one_way_cost_fraction=sum(abs(weights.get(sid, 0.)-prior.get(sid, 0.))*config["one_way_cost_bps"][securities[sid]["market"]]/10000 for sid in set(weights)|set(prior)),
                    tax_status="personal_income_tax_not_modeled; friction assumptions are not verified tax rates")
    for r in rows:
        sid = r["security_id"]; w, old = weights.get(sid, 0.), prior.get(sid, 0.)
        if old and w == 0: action = "EXCLUDE"
        elif old and w < old-1e-10: action = "REDUCE"
        elif old and w > old+1e-10: action = "ADD"
        elif old: action = "HOLD"
        elif w: action = "ENTER"
        elif not r["valuation_ready"]: action = "WAIT"
        else: action = "EXCLUDE" if "thesis_quality_or_risk_gate" in reasons[sid] else "WAIT"
        if w: reasons[sid].append("positive_scenario_utility_subject_to_risk_liquidity_cost_caps")
        elif not reasons[sid]: reasons[sid].append("allocation_below_minimum_or_risk_capacity")
        r["four_questions"]["portfolio_value"] = "pass_research_only" if w and proposal["ready"] else "wait_or_review"
        proposal["rows"].append({"security_id": sid, "action": action, "previous_weight": old, "target_weight": w, "reasons": reasons[sid]})
    return proposal
