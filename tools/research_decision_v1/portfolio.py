"""Conservative research proposals; no broker imports or order writers."""
from __future__ import annotations
import math
import re
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
        row.update(expected_total_return_krw=None, expected_net_return_krw=None, investment_rank=None, expected_return_rank=None,
                   investment_rank_local=None, expected_return_rank_local=None)
        if not row["valuation_ready"]: continue
        row.setdefault("four_questions_local", dict(row["four_questions"]))
        row["question_currency"] = "KRW"
        benchmark = context.get("benchmark_expected_returns", {}).get(row["market"])
        if benchmark is not None:
            number(benchmark)
            row["expected_excess_return"] = row["expected_total_return"] - benchmark
            row["benchmark_forecast_type"] = "SUBJECTIVE_SCENARIO"
        if not fx_valid:
            row["four_questions"].update(good_stock="unverified_fx", buy_price_now="unverified_fx")
            continue
        converted = []
        for s in row["scenarios"]:
            ratio = context["fx"]["scenario_rates"][s["name"]]/context["fx"]["spot"] if row["currency"] == "USD" else 1.
            converted.append({"name": s["name"], "probability": s["probability"], "total_return_krw": (1+s["total_return"])*ratio-1., "fx_ratio": ratio})
        mean = sum(s["probability"]*s["total_return_krw"] for s in converted)
        values = [s["total_return_krw"] for s in converted]
        utility = mean - 2*config["one_way_cost_bps"][row["market"]]/10000 - config["downside_penalty"]*max(0., -min(values)) - config["dispersion_penalty"]*(max(values)-min(values)+row["uncertainty"])
        row.update(scenarios_krw=converted, expected_total_return_krw=mean,
                   expected_net_return_krw=mean-2*config["one_way_cost_bps"][row["market"]]/10000,
                   investment_utility_krw=utility)
        row["four_questions"].update(good_stock="pass" if utility > 0 else "fail",
                                     buy_price_now="pass" if row["expected_net_return_krw"] >= config["new_entry_net_return"] else "wait")
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
    if not isinstance(positions, dict): raise ValueError("book_positions_invalid")
    if any(not isinstance(sid, str) or not re.fullmatch(r"(?:US:[A-Z0-9][A-Z0-9._-]*|KR:[0-9]{6})", sid) for sid in positions):
        raise ValueError("book_security_identity_invalid")
    for value in positions.values():
        if not 0 <= number(value) <= 1: raise ValueError("book_weight_invalid")
    cash = number(book["cash_weight"], nonnegative=True)
    if not math.isclose(sum(positions.values())+cash, 1., abs_tol=1e-10): raise ValueError("book_weights_do_not_sum_to_one")
    return {sid: weight for sid, weight in positions.items() if weight > 0}, cash


def constraint_audit(weights, securities, rows, context, config, prior=None):
    prior = prior or {}
    lookup = {r["security_id"]: r for r in rows}
    countries, country_counts, groups, violations, reviews = {}, {}, {}, [], []
    stress = 0.
    for sid, w in sorted(weights.items()):
        if w <= 0: continue
        s, row = securities[sid], lookup[sid]
        market = s["market"]; risk = s["blocks"]["risk"]["payload"]
        countries[market] = countries.get(market, 0.) + w
        country_counts[market] = country_counts.get(market, 0) + 1
        for group, exposure in risk["exposures"].items(): groups[group] = groups.get(group, 0.) + w*exposure
        fx_loss = max(0., 1-min(context["fx"]["scenario_rates"].values())/context["fx"]["spot"]) if market == "US" else 0.
        shock = max(row.get("downside_loss", 0.), risk["stress_loss"])
        stress += w * (1-(1-shock)*(1-fx_loss))
        local_capital = context["capital_krw"]/(context["fx"]["spot"] if market == "US" else 1.)
        if context["mode"] == "NEW_CAPITAL_RESEARCH" and w * local_capital > s["discovery"]["adv20_local"] * config["max_adv_participation"] + .01:
            violations.append(sid+":liquidity")
        if w > config["max_security_weight"]+1e-10: violations.append(sid+":concentration")
        if w > .05:
            reviews.append({"security_id": sid, "risk_review": True,
                            "concentration_review": w > .10, "weight": w,
                            "bear_case": row.get("strongest_bear_case"), "common_exposures": risk["exposures"],
                            "stress_loss": shock, "liquidity_checked": True})
    for sid in sorted(set(weights) | set(prior)):
        traded_weight = abs(weights.get(sid, 0.) - prior.get(sid, 0.))
        if traded_weight <= 1e-10: continue
        security = securities[sid]
        local_capital = context["capital_krw"] / (context["fx"]["spot"] if security["market"] == "US" else 1.)
        if traded_weight * local_capital > security["discovery"]["adv20_local"] * config["max_adv_participation"] + .01:
            violations.append(sid+":trade_liquidity")
        if security["blocks"]["risk"]["payload"]["liquidity_restriction"]:
            violations.append(sid+":trade_liquidity_restriction")
    gross = sum(weights.values())
    if gross > config["gross_caps"][context["regime"]["state"]] + 1e-10: violations.append("regime_gross_cap")
    for market, w in countries.items():
        if w > config["country_caps"][market]+1e-10: violations.append(market+":country_cap")
        if country_counts[market] > config["target_counts"][market]: violations.append(market+":country_count_cap")
    for group, w in groups.items():
        if w > config["group_caps"][group.split(":")[0]]+1e-10: violations.append(group+":common_risk_cap")
    if stress > config["max_stress_loss"]+1e-10: violations.append("stress_loss_cap")
    return {"country_exposure": countries, "country_counts": country_counts, "common_risk_exposure": groups, "gross_exposure": gross,
            "scenario_stress_loss": stress, "scenario_stress_limit": config["max_stress_loss"],
            "mdd_validated": False, "mdd_constraint_status": "NOT_OOS_TESTED",
            "correlation_model": "conservative_common_group_caps; no estimated_correlation_claim",
            "violations": sorted(set(violations)), "reviews": reviews}


def feasible_initial_weights(eligible, securities, rows, context, config):
    """Backfill count slots after actual liquidity/group/stress/minimum fitting."""
    clipped = set()
    while True:
        selected, count = [], {"US": 0, "KR": 0}
        for row in eligible:
            if row["security_id"] in clipped or count[row["market"]] >= config["target_counts"][row["market"]]: continue
            selected.append(row); count[row["market"]] += 1
        raw = {r["security_id"]: r["investment_utility_krw"] * securities[r["security_id"]]["blocks"]["thesis"]["payload"]["confidence"] / max(config["min_downside_denominator"], r["downside_loss"], securities[r["security_id"]]["blocks"]["risk"]["payload"]["stress_loss"]) for r in selected}
        total = sum(raw.values()); budget = config["gross_caps"][context["regime"]["state"]]
        weights = {sid: min(config["max_security_weight"], value/total*budget) if total else 0. for sid, value in raw.items()}
        for sid in weights:
            security = securities[sid]; fx = context["fx"]["spot"] if security["market"] == "US" else 1.
            cap = security["discovery"]["adv20_local"] * fx * config["max_adv_participation"] / context["capital_krw"]
            weights[sid] = min(weights[sid], cap)
        for market in ("US", "KR"):
            members = [sid for sid in weights if securities[sid]["market"] == market]
            amount = sum(weights[sid] for sid in members)
            scale = min(1., config["country_caps"][market]/amount) if amount else 1.
            for sid in members: weights[sid] *= scale
        for group in sorted({g for sid in weights for g in securities[sid]["blocks"]["risk"]["payload"]["exposures"]}):
            members = {sid: securities[sid]["blocks"]["risk"]["payload"]["exposures"].get(group, 0.) for sid in weights}
            exposure = sum(weights[sid]*value for sid, value in members.items())
            scale = min(1., config["group_caps"][group.split(":")[0]]/exposure) if exposure else 1.
            for sid, value in members.items():
                if value: weights[sid] *= scale
        audit = constraint_audit(weights, securities, rows, context, config)
        if audit["scenario_stress_loss"] > config["max_stress_loss"]:
            scale = config["max_stress_loss"]/audit["scenario_stress_loss"]
            weights = {sid: value*scale for sid, value in weights.items()}
        weights = {sid: math.floor(value*1e8)/1e8 if value >= config["minimum_weight"] else 0. for sid, value in weights.items()}
        failed = [row for row in selected if weights[row["security_id"]] <= 0]
        if not failed: return weights, clipped
        # Drop only the least-preferred failed member, then recompute the joint
        # constraints; the others may become feasible as group room is released.
        clipped.add(failed[-1]["security_id"])


def propose(rows, securities, context, config, common_errors, cutoff):
    reasons = {r["security_id"]: list(r["blockers"]) for r in rows}
    prior, cash_prior = {}, 1.
    errors = list(common_errors)
    book_valid = False
    try:
        prior, cash_prior = read_book(context, set(securities), cutoff)
        book_valid = True
        if set(prior)-set(securities): errors.append("book_holdings_missing_from_risk_universe")
    except (ValueError, KeyError, TypeError) as exc: errors.append("book:"+str(exc))
    proposal = {"mode": context.get("mode"), "ready": False, "orders_allowed": False,
                "broker_reconciled": False, "rows": [], "cash_weight": None,
                "constraints": {}, "blockers": errors, "capital_krw": context.get("capital_krw"),
                "capital_is_assumption": context.get("capital_is_assumption", False),
                "risk_limit_is_future_guarantee": False}
    if errors:
        for r in rows:
            r["four_questions"]["portfolio_value"] = "blocked_common_input"
            sid = r["security_id"]
            weight = prior.get(sid, 0.) if book_valid else (0. if context.get("mode") == "NEW_CAPITAL_RESEARCH" else None)
            proposal["rows"].append({"security_id": sid, "action": "HOLD" if prior.get(sid) else "WAIT", "target_weight": weight, "reasons": reasons[sid] + errors})
        for sid in sorted(set(prior)-set(securities)):
            proposal["rows"].append({"security_id": sid, "action": "HOLD", "target_weight": prior[sid],
                                    "reasons": ["incumbent_missing_evidence_preserve_book", *errors],
                                    "four_questions": {"good_company": "unverified", "good_stock": "unverified", "buy_price_now": "unverified", "portfolio_value": "blocked_missing_evidence"}})
        if book_valid and context.get("mode") == "EXISTING_BOOK_PROPOSAL":
            proposal.update(cash_weight=cash_prior, cash_is_unallocated_fallback=False)
        if context.get("mode") == "NEW_CAPITAL_RESEARCH": proposal["cash_weight"] = 1.; proposal["cash_is_unallocated_fallback"] = True
        return proposal
    eligible = []
    for r in sorted(rows, key=lambda r: (r["investment_rank"] or 10**9, r["security_id"])):
        sid = r["security_id"]
        if not r["valuation_ready"]: continue
        s = securities[sid]; t, risk = s["blocks"]["thesis"]["payload"], s["blocks"]["risk"]["payload"]
        if risk["integrity_alert"] or risk["liquidity_restriction"] or not t["intact"] or t["company_quality"] != "pass":
            reasons[sid].append("thesis_quality_or_risk_gate"); continue
        threshold = config["hold_net_return"] if prior.get(sid, 0.) else config["new_entry_net_return"]
        if r["expected_net_return_krw"] < threshold or r["investment_utility_krw"] <= 0:
            reasons[sid].append("net_return_or_risk_adjusted_utility_below_threshold"); continue
        eligible.append(r)
    budget = config["gross_caps"][context["regime"]["state"]]
    weights, clipped = feasible_initial_weights(eligible, securities, rows, context, config)
    for sid in clipped: reasons[sid].append("allocation_below_minimum_after_feasibility_fit")
    if prior:
        # An intact incumbent is the actual opportunity-cost comparison.
        by_id = {r["security_id"]: r for r in rows}
        replacement_ids = set()
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
                alternatives = [r for r in eligible if r["security_id"] not in prior
                                and weights.get(r["security_id"], 0.) >= config["minimum_weight"]]
                cost = 2 * config["one_way_cost_bps"][s["market"]]/10000
                benefit = max((r["investment_utility_krw"]-row["investment_utility_krw"] for r in alternatives), default=0.)
                if benefit <= config["replacement_improvement_buffer"]+cost:
                    weights[sid] = old; reasons[sid].append("keep_incumbent_replacement_not_cost_justified")
                else: replacement_ids.add(sid)
        if proposal["blockers"]:
            # Preserve the whole submitted book when incumbent risk cannot be measured.
            proposal.update(cash_weight=cash_prior, cash_is_unallocated_fallback=False)
            for row in rows: row["four_questions"]["portfolio_value"] = "blocked_incumbent_evidence"
            proposal["rows"] = [{"security_id": r["security_id"], "action": "HOLD" if prior.get(r["security_id"]) else "WAIT", "target_weight": prior.get(r["security_id"], 0.), "reasons": reasons[r["security_id"]]+proposal["blockers"]} for r in rows]
            return proposal
        def fit_new_capacity():
            # Every purchase, including an ADD, shares the room left by the
            # retained portion of the book. Fitting only new names can borrow cash.
            baseline = {sid: min(w, prior.get(sid, 0.)) for sid, w in weights.items()}
            buys = {sid: w-baseline[sid] for sid, w in weights.items()}
            new_ids = [sid for sid, w in buys.items() if sid not in prior and w > 0]
            amount = sum(buys.values())
            factor = max(0., min(1., (budget-sum(baseline.values()))/amount)) if amount else 1.
            for sid in buys: buys[sid] *= factor
            for market in ("US", "KR"):
                occupied_ids = [sid for sid in prior if baseline.get(sid, 0.) > 0 and securities[sid]["market"] == market]
                new_members = sorted((sid for sid in new_ids if securities[sid]["market"] == market),
                                     key=lambda sid: (by_id[sid]["investment_rank"], sid))
                slots = max(0, config["target_counts"][market]-len(occupied_ids))
                for sid in new_members[slots:]:
                    buys[sid] = 0.
                    if "retained_incumbent_count_capacity" not in reasons[sid]: reasons[sid].append("retained_incumbent_count_capacity")
                members = [sid for sid in buys if securities[sid]["market"] == market]
                occupied = sum(baseline[sid] for sid in members)
                amount = sum(buys[sid] for sid in members)
                factor = max(0., min(1., (config["country_caps"][market]-occupied)/amount)) if amount else 1.
                for sid in members: buys[sid] *= factor
            for group in sorted({g for sid in weights for g in securities[sid]["blocks"]["risk"]["payload"]["exposures"]}):
                exposures = {sid: securities[sid]["blocks"]["risk"]["payload"]["exposures"].get(group, 0.) for sid in weights}
                occupied = sum(baseline[sid]*e for sid, e in exposures.items())
                amount = sum(buys[sid]*e for sid, e in exposures.items())
                factor = max(0., min(1., (config["group_caps"][group.split(":")[0]]-occupied)/amount)) if amount else 1.
                for sid, e in exposures.items():
                    if e: buys[sid] *= factor
            prior_stress = constraint_audit(baseline, securities, rows, context, config)["scenario_stress_loss"]
            buy_stress = constraint_audit(buys, securities, rows, context, config)["scenario_stress_loss"]
            factor = max(0., min(1., (config["max_stress_loss"]-prior_stress)/buy_stress)) if buy_stress else 1.
            for sid in buys:
                buys[sid] *= factor
                if sid not in prior and buys[sid] < config["minimum_weight"]: buys[sid] = 0.
                if sid in prior and 0 < buys[sid] < config["no_trade_weight_buffer"]:
                    buys[sid] = 0.
                    if "no_trade_buffer_after_capacity_fit" not in reasons[sid]: reasons[sid].append("no_trade_buffer_after_capacity_fit")
                weights[sid] = baseline[sid]+buys[sid]

        # Credit each feasible new purchase at most once. Restoring an incumbent
        # can consume count/group room and shrink a replacement again, so replay
        # monotonically; if it does not settle, preserve these incumbents.
        settled = False
        for _ in range(len(prior)+2):
            fit_new_capacity()
            capacity = {sid: w for sid, w in weights.items() if sid not in prior and w > 0}
            restored = False
            for sid in sorted(replacement_ids, key=lambda sid: (by_id[sid]["investment_utility_krw"], sid)):
                needed = prior[sid]-weights.get(sid, 0.)
                cost = 2*config["one_way_cost_bps"][securities[sid]["market"]]/10000
                alternatives = sorted((other for other in capacity if
                    by_id[other]["investment_utility_krw"]-by_id[sid]["investment_utility_krw"] > config["replacement_improvement_buffer"]+cost),
                    key=lambda other: (by_id[other]["investment_rank"], other))
                supported = min(needed, sum(capacity[other] for other in alternatives))
                if supported < config["no_trade_weight_buffer"]: supported = 0.
                if supported < needed-1e-10:
                    weights[sid] = prior[sid]-supported; restored = True
                remaining = supported
                for other in alternatives:
                    used = min(remaining, capacity[other]); capacity[other] -= used; remaining -= used
            if not restored:
                settled = True; break
        if not settled:
            for sid in replacement_ids: weights[sid] = prior[sid]
            fit_new_capacity()
        for sid in replacement_ids:
            reasons[sid].append("replacement_improves_incumbent_after_cost_buffer" if weights.get(sid, 0.) < prior[sid]-1e-10
                                else "keep_incumbent_no_feasible_replacement_capacity")
        for sid, old in prior.items():
            if weights.get(sid, 0.) <= 0: continue
            row = by_id[sid]
            if row["expected_net_return_krw"] < config["hold_net_return"] or row["investment_utility_krw"] <= 0:
                proposal["blockers"].append(sid+":held_below_hold_hurdle_requires_review")
                reasons[sid].append("preserved_intact_thesis_requires_valuation_review")
    audit = constraint_audit(weights, securities, rows, context, config, prior)
    # Existing-book no-trade preservation may conflict with hard risk caps. Surface
    # the conflict for review instead of silently overriding a thesis or a cap.
    proposal["blockers"] += audit["violations"]
    valuation_observed = any(r["valuation_ready"] for r in rows)
    proposal.update(ready=not proposal["blockers"] and valuation_observed, constraints=audit,
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
        if w and r.get("investment_utility_krw", 0.) > 0: reasons[sid].append("positive_scenario_utility_subject_to_risk_liquidity_cost_caps")
        elif not reasons[sid]: reasons[sid].append("allocation_below_minimum_or_risk_capacity")
        r["four_questions"]["portfolio_value"] = "pass_research_only" if w and proposal["ready"] else "wait_or_review"
        proposal["rows"].append({"security_id": sid, "action": action, "previous_weight": old, "target_weight": w, "reasons": reasons[sid]})
    return proposal
