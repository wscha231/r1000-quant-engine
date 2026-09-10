"""US-only decision entry point over the hash-verified research core.

Reimplemented from PR 409 @ 3eb068e76d676ec3fc75288b645db8448615aa2d.
Only configuration scope, foreign-input rejection and the obsolete 5+2 output
label change. Valuation, quality, accounting and provenance gates are retained.
No source patching or runtime monkey-patching; legacy code stays immutable.
"""
from tools.research_decision_v1.data import (number, digest, validate_persistable_sources,
    reject_diagnostic_scores)
from tools.research_decision_v1.engine import (replay_export, validate_previous_record,
    evaluate_research_rows, rank_sensitivity, component_hashes, discovery_snapshot)
from tools.research_decision_v1.portfolio import (context_errors, add_fx_returns,
    propose, investment_eligible)


def validate_config(config):
    validate_persistable_sources(config)
    reject_diagnostic_scores(config)
    if type(config.get("fund_manager_rebalance", False)) is not bool:
        raise ValueError("fund_manager_rebalance_must_be_boolean")
    if config.get("schema_version") != "research-decision-config-v1" or config.get("horizon_months") != 12:
        raise ValueError("config_schema_or_horizon_invalid")
    for key in ("orders_allowed", "calibration_validated", "oos_validated", "production_promoted"):
        if config.get(key) is not False: raise ValueError("research_safety_flag_invalid")
    for key in ("downside_penalty", "dispersion_penalty", "new_entry_net_return", "hold_net_return", "replacement_improvement_buffer", "no_trade_weight_buffer", "minimum_weight", "max_security_weight", "max_adv_participation", "max_stress_loss", "min_downside_denominator", "sensitivity_fraction"):
        if not 0 < number(config[key]) <= 1: raise ValueError("config_fraction_invalid:"+key)
    if config["hold_net_return"] >= config["new_entry_net_return"]: raise ValueError("entry_hold_hysteresis_required")
    if config.get("market_profile") != "US_LISTED_USD_V1": raise ValueError("us_market_profile_required")
    if config["target_counts"] != {"US": 5, "KR": 0}: raise ValueError("target_count_contract_mismatch")
    if config["country_caps"] != {"US": 1., "KR": 0.}: raise ValueError("us_market_cap_contract")
    for key in ("country_caps", "group_caps", "gross_caps"):
        for value in config[key].values():
            if not 0 <= number(value) <= 1: raise ValueError("config_cap_invalid")
    for value in config["one_way_cost_bps"].values(): number(value, nonnegative=True)


def run_decisions(exports, context, config, previous=None, *, quality_bundle=None):
    validate_config(config)
    if not exports: raise ValueError("market_exports_required")
    clean = [replay_export(e) for e in exports]
    if len({e["market"] for e in clean}) != len(clean): raise ValueError("duplicate_market_export")
    cutoffs = {e["decision_cutoff"] for e in clean}
    kinds = {e["data_kind"] for e in clean}
    if len(cutoffs) != 1: raise ValueError("cross_market_cutoff_mismatch")
    if len(kinds) != 1: raise ValueError("synthetic_and_real_must_not_mix")
    cutoff, kind = next(iter(cutoffs)), next(iter(kinds))
    validate_persistable_sources(context, real=kind == "REAL")
    reject_diagnostic_scores(context)
    old = validate_previous_record(previous, kind, cutoff) if previous is not None else {}
    securities = {s["security_id"]: s for e in clean for s in e["securities"]}
    if not securities: raise ValueError("empty_research_universe")
    rows = evaluate_research_rows(securities, config, cutoff, kind, quality_bundle)
    if context.get("base_currency") != "USD" or any(s["market"] != "US" or s["currency"] != "USD" for s in securities.values()):
        raise ValueError("us_profile_market_or_currency")
    if any(not sid.startswith("US:") for sid in context.get("book", {}).get("positions", {})):
        raise ValueError("us_profile_foreign_holding")
    common_errors = context_errors(context, config, cutoff)
    if context.get("base_currency") == "USD" and all(s["currency"] == "USD" for s in securities.values()):
        # No foreign asset or conversion in this portfolio. An unrelated KRW
        # feed must not be a dependency of an entirely USD-native decision.
        common_errors = [e for e in common_errors if not e.startswith("fx")]
    fx_valid = not any(x.startswith("fx") for x in common_errors)
    add_fx_returns(rows, context, config, fx_valid)
    rank_sensitivity(rows, securities, context, config, cutoff, fx_valid)
    proposal = propose(rows, securities, context, config, common_errors, cutoff)
    ledger = []
    for r in rows:
        r["component_hashes"] = component_hashes(securities[r["security_id"]])
        if quality_bundle is not None:
            q=r["quality_assessment"]
            r["component_hashes"].update(
                quality_evidence=q.get("semantic_hash") or digest(None),
                quality_review=digest({"method":q["method_version"],"subject":q.get("review_subject_hash"),
                    "receipt":q.get("review_receipt_hash"),
                    "valid":q["review_receipt_valid"],"assessment":q["company_assessment"],
                    "links":r["scenario_links"]["status"]}))
        p = old.get(r["security_id"])
        changes = ["evidence_provenance" if k == "optional_provenance" else k for k, value in r["component_hashes"].items()
                   if p and k in p["component_hashes"] and p["component_hashes"][k] != value]
        if p and set(p["component_hashes"]) != set(r["component_hashes"]): changes.append("component_contract_change")
        changes = sorted(set(changes))
        if previous and previous["config_hash"] != digest(config): changes.append("config")
        if previous and previous["context_hash"] != digest(context): changes.append("portfolio_context_or_fx_or_regime")
        if not p: changes = ["initial_observation"]
        if p and p.get("investment_rank") != r["investment_rank"] and not set(changes) - {"evidence_provenance"}: changes.append("peer_cross_section_change")
        r["rank_change_reasons"] = changes or ["unchanged"]
        ledger.append({"security_id": r["security_id"], "previous_investment_rank": p.get("investment_rank") if p else None,
                       "investment_rank": r["investment_rank"], "changes": r["rank_change_reasons"],
                       "component_hashes": r["component_hashes"]})
    for sid in sorted(set(old)-set(securities)):
        ledger.append({"security_id": sid, "previous_investment_rank": old[sid].get("investment_rank"),
                       "investment_rank": None, "status": "removed_from_research_universe",
                       "changes": ["missing", "removed_from_research_universe"],
                       "component_hashes": None, "previous_component_hashes": old[sid].get("component_hashes"),
                       "portfolio_action": None})
    coverage = [{"security_id": sid, "data_quality_pass": s["data_quality_pass"], "blockers": s["blockers"],
                 "optional": {k: {"status": v["status"], "reason": v.get("reason"), "http": v.get("http")} for k, v in s.get("optional", {}).items()},
                 "price_sessions": s["discovery"]["history_sessions"] if s.get("discovery") else 0,
                 "quarter_count": len(s.get("blocks", {}).get("financials", {}).get("payload", {}).get("recent_quarters", [])),
                 "annual_count": len(s.get("blocks", {}).get("financials", {}).get("payload", {}).get("recent_annual", [])),
                 "historical_pit_verified": False} for sid, s in sorted(securities.items())]
    admitted_ids = {r["security_id"] for r in rows if r["valuation_ready"] and investment_eligible(r)}
    selected = {market: sum(p["target_weight"] is not None and p["target_weight"]>0 and p["security_id"] in admitted_ids
                            for p in proposal["rows"] if p["security_id"].split(":")[0] == market) for market in ("US", "KR")}
    held_evidence_complete = all(p["target_weight"] is not None and
        (p["target_weight"] == 0 or p["security_id"] in admitted_ids) for p in proposal["rows"])
    readiness = {"research_pipeline_ready": True, "data_quality_pass": all(s["data_quality_pass"] for s in securities.values()),
                 "research_ranking_ready": any(r["valuation_ready"] and investment_eligible(r) for r in rows) and fx_valid,
                 "research_universe_fully_covered": all(r["valuation_ready"] and investment_eligible(r) for r in rows) and held_evidence_complete,
                 "portfolio_proposal_ready": proposal["ready"], "target_scope_complete": proposal["ready"] and selected == config["target_counts"],
                 "return_calibration_validated": False, "oos_validated": False, "broker_reconciled": False,
                 "production_promoted": False, "orders_allowed": False}
    decision = {"schema_version": "research-decision-v1", "data_kind": kind, "decision_cutoff": cutoff,
                "mode": context["mode"], "config_hash": digest(config), "context_hash": digest(context),
                "input_export_hashes": sorted(e["export_hash"] for e in clean),
                "previous_decision_hash": previous["decision_hash"] if previous else None,
                "readiness": readiness, "ranking": rows, "portfolio_proposal": proposal,
                "coverage": coverage, "industry_discovery": discovery_snapshot(list(securities.values()), config),
                "decision_ledger": ledger,
                "workflow": {"mode":"QUALITY_CONNECTED_RESEARCH" if quality_bundle is not None else "LEGACY_RESEARCH_BASELINE",
                    "quality_bundle_hash":digest(quality_bundle) if quality_bundle is not None else None,
                    "universe_count":len(rows), "market_admitted_count":sum(s["data_quality_pass"] for s in securities.values()),
                    "valuation_count":sum(r["valuation_ready"] for r in rows),
                    "quality_eligible_count":sum(investment_eligible(r) for r in rows) if quality_bundle is not None else None,
                    "fx_ready":fx_valid, "funding_ready":proposal.get("funding") is not None,
                    "proposal_ready":proposal["ready"], "oos_validated":False,
                    "realized_performance_available":False, "orders_allowed":False}}
    decision["decision_hash"] = digest(decision)
    return decision
