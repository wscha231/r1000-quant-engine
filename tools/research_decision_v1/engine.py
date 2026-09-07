"""Replayable market exports -> valuations -> research decisions -> evidence log."""
from __future__ import annotations
import copy
import math
from tools.research_decision_v1.data import canonical, digest, export_market, number, total_return_series, timestamp
from tools.research_decision_v1.valuation import evaluate_security
from tools.research_decision_v1.portfolio import context_errors, add_fx_returns, propose


def validate_config(config):
    if config.get("schema_version") != "research-decision-config-v1" or config.get("horizon_months") != 12:
        raise ValueError("config_schema_or_horizon_invalid")
    for key in ("orders_allowed", "calibration_validated", "oos_validated", "production_promoted"):
        if config.get(key) is not False: raise ValueError("research_safety_flag_invalid")
    for key in ("downside_penalty", "dispersion_penalty", "new_entry_net_return", "hold_net_return", "replacement_improvement_buffer", "no_trade_weight_buffer", "minimum_weight", "max_security_weight", "max_adv_participation", "max_stress_loss", "min_downside_denominator", "sensitivity_fraction"):
        if not 0 < number(config[key]) <= 1: raise ValueError("config_fraction_invalid:"+key)
    if config["hold_net_return"] >= config["new_entry_net_return"]: raise ValueError("entry_hold_hysteresis_required")
    if config["target_counts"] != {"US": 5, "KR": 2}: raise ValueError("target_count_contract_mismatch")
    for key in ("country_caps", "group_caps", "gross_caps"):
        for value in config[key].values():
            if not 0 <= number(value) <= 1: raise ValueError("config_cap_invalid")
    for value in config["one_way_cost_bps"].values(): number(value, nonnegative=True)


def replay_export(value):
    # Recompute from original input; supplied readiness/rank fields carry no authority.
    expected = export_market(value["input_snapshot"], value["market"])
    if canonical(value) != canonical(expected): raise ValueError("market_export_replay_mismatch")
    return expected


def discovery_snapshot(securities, config):
    groups = {}
    for s in securities:
        if not s["data_quality_pass"]: continue
        risk = s["blocks"]["risk"]["payload"]
        for group, exposure in risk["exposures"].items():
            if not exposure or not group.startswith(("industry:", "theme:")): continue
            key = s["market"] + "/" + group
            groups.setdefault(key, []).append((s, exposure))
    out = []
    for group, members in sorted(groups.items()):
        horizons = {}
        for h in (20, 60, 120, 240):
            available = [(s, e) for s, e in members if s["discovery"]["rs"][str(h)]["status"] == "available"]
            if len(available) < config["discovery_min_group_size"]:
                horizons[str(h)] = {"status": "missing", "reason": "insufficient_group_coverage", "count": len(available)}; continue
            observations = []
            for s, exposure in available:
                prices = s["blocks"]["price"]["payload"]
                tr = total_return_series(prices["bars"], prices["price_basis"])
                benchmark = total_return_series(prices["benchmark_bars"], prices["benchmark_price_basis"])
                r = tr[-1]/tr[-h-1]-1.; br = benchmark[-1]/benchmark[-h-1]-1.
                cap = s["discovery"]["price"]*s["blocks"]["financials"]["payload"]["ttm"]["diluted_shares"]*exposure
                observations.append((r, br, cap, exposure))
            ew = sum(r*e for r, _, _, e in observations)/sum(e for _, _, _, e in observations)
            cw = sum(r*c for r, _, c, _ in observations)/sum(c for _, _, c, _ in observations)
            base = sum(br*e for _, br, _, e in observations)/sum(e for _, _, _, e in observations)
            horizons[str(h)] = {"status": "available", "equal_weight_return": ew, "current_cap_weight_return": cw,
                               "log_rs_equal": math.log1p(ew)-math.log1p(base), "breadth": sum(r>br for r, br, _, _ in observations)/len(observations),
                               "largest_cap_share": max(c for _, _, c, _ in observations)/sum(c for _, _, c, _ in observations),
                               "count": len(observations), "historical_constituents_verified": False}
        out.append({"group": group, "horizons": horizons, "use": "discovery_only_no_ranking_or_size_points"})
    return out


def component_hashes(security):
    blocks = security.get("blocks", {})
    return {"price": digest(blocks.get("price")), "financials": digest(blocks.get("financials")),
            "estimates": digest({"scenario": blocks.get("scenario"), "estimates": security.get("optional", {}).get("estimates")}),
            "thesis": digest(blocks.get("thesis")), "risk": digest(blocks.get("risk")),
            "missing": digest({"blockers": security["blockers"], "optional": security.get("optional", {})})}


def rank_sensitivity(rows, securities, context, config, cutoff, fx_valid):
    for row in rows:
        if not row["valuation_ready"]: continue
        ranks = [row["investment_rank"]] if fx_valid else [row["investment_rank_local"]]
        variants = []
        for field in ("revenue", "margin", "multiple", "diluted_shares"):
            for delta in (-config["sensitivity_fraction"], config["sensitivity_fraction"]):
                altered = copy.deepcopy(securities[row["security_id"]])
                block = altered["blocks"]["scenario"]
                for s in block["payload"]["scenarios"]: s[field] *= 1+delta
                block["data_hash"] = digest(block["payload"])
                changed = evaluate_security(altered, config, cutoff)
                if not changed["valuation_ready"]:
                    variants.append({"field": field, "delta": delta, "rank": None, "reason": "perturbation_outside_valuation_domain"}); continue
                candidate_rows = [copy.deepcopy(r) if r["security_id"] != row["security_id"] else changed for r in rows]
                add_fx_returns(candidate_rows, context, config, fx_valid)
                rank = changed["investment_rank"] if fx_valid else changed["investment_rank_local"]
                ranks.append(rank); variants.append({"field": field, "delta": delta, "rank": rank})
        row["rank_sensitivity"] = {"best_rank": min(ranks), "worst_rank": max(ranks), "variants": variants,
                                   "type": "one_assumption_at_a_time_subjective_not_confidence_interval"}


def run_decisions(exports, context, config, previous=None):
    validate_config(config)
    if not exports: raise ValueError("market_exports_required")
    clean = [replay_export(e) for e in exports]
    if len({e["market"] for e in clean}) != len(clean): raise ValueError("duplicate_market_export")
    cutoffs = {e["decision_cutoff"] for e in clean}
    kinds = {e["data_kind"] for e in clean}
    if len(cutoffs) != 1: raise ValueError("cross_market_cutoff_mismatch")
    if len(kinds) != 1: raise ValueError("synthetic_and_real_must_not_mix")
    cutoff, kind = next(iter(cutoffs)), next(iter(kinds))
    securities = {s["security_id"]: s for e in clean for s in e["securities"]}
    if not securities: raise ValueError("empty_research_universe")
    rows = [evaluate_security(s, config, cutoff) for sid, s in sorted(securities.items())]
    common_errors = context_errors(context, config, cutoff)
    fx_valid = not any(x.startswith("fx") for x in common_errors)
    add_fx_returns(rows, context, config, fx_valid)
    rank_sensitivity(rows, securities, context, config, cutoff, fx_valid)
    proposal = propose(rows, securities, context, config, common_errors, cutoff)
    old = {}
    if previous:
        if timestamp(previous["decision_cutoff"]) > timestamp(cutoff): raise ValueError("previous_decision_after_cutoff")
        if previous["data_kind"] != kind: raise ValueError("previous_data_kind_mismatch")
        supplied_hash = previous["decision_hash"]
        if digest({k: v for k, v in previous.items() if k != "decision_hash"}) != supplied_hash: raise ValueError("previous_hash_mismatch")
        old = {r["security_id"]: r for r in previous["ranking"]}
    ledger = []
    for r in rows:
        r["component_hashes"] = component_hashes(securities[r["security_id"]])
        p = old.get(r["security_id"])
        changes = [k for k, value in r["component_hashes"].items() if p and p["component_hashes"].get(k) != value]
        if previous and previous["config_hash"] != digest(config): changes.append("config")
        if previous and previous["context_hash"] != digest(context): changes.append("portfolio_context_or_fx_or_regime")
        if not p: changes = ["initial_observation"]
        if p and p.get("investment_rank") != r["investment_rank"] and not changes: changes.append("peer_cross_section_change")
        r["rank_change_reasons"] = changes or ["unchanged"]
        ledger.append({"security_id": r["security_id"], "previous_investment_rank": p.get("investment_rank") if p else None,
                       "investment_rank": r["investment_rank"], "changes": r["rank_change_reasons"],
                       "component_hashes": r["component_hashes"]})
    coverage = [{"security_id": sid, "data_quality_pass": s["data_quality_pass"], "blockers": s["blockers"],
                 "optional": {k: {"status": v["status"], "reason": v.get("reason"), "http": v.get("http")} for k, v in s.get("optional", {}).items()},
                 "price_sessions": s["discovery"]["history_sessions"] if s.get("discovery") else 0,
                 "quarter_count": len(s.get("blocks", {}).get("financials", {}).get("payload", {}).get("recent_quarters", [])),
                 "annual_count": len(s.get("blocks", {}).get("financials", {}).get("payload", {}).get("recent_annual", [])),
                 "historical_pit_verified": False} for sid, s in sorted(securities.items())]
    selected = {market: sum(p["target_weight"] is not None and p["target_weight"]>0 for p in proposal["rows"] if securities[p["security_id"]]["market"] == market) for market in ("US", "KR")}
    readiness = {"research_pipeline_ready": True, "data_quality_pass": all(s["data_quality_pass"] for s in securities.values()),
                 "research_ranking_ready": any(r["valuation_ready"] for r in rows) and fx_valid,
                 "research_universe_fully_covered": all(r["valuation_ready"] for r in rows),
                 "portfolio_proposal_ready": proposal["ready"], "target_5_plus_2_complete": selected == config["target_counts"],
                 "return_calibration_validated": False, "oos_validated": False, "broker_reconciled": False,
                 "production_promoted": False, "orders_allowed": False}
    decision = {"schema_version": "research-decision-v1", "data_kind": kind, "decision_cutoff": cutoff,
                "mode": context["mode"], "config_hash": digest(config), "context_hash": digest(context),
                "input_export_hashes": sorted(e["export_hash"] for e in clean),
                "previous_decision_hash": previous["decision_hash"] if previous else None,
                "readiness": readiness, "ranking": rows, "portfolio_proposal": proposal,
                "coverage": coverage, "industry_discovery": discovery_snapshot(list(securities.values()), config),
                "decision_ledger": ledger}
    decision["decision_hash"] = digest(decision)
    return decision
