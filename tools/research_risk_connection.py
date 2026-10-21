"""Read-only research join of existing macro/reassessment/hold-policy functions.

build_risk_connection(request: dict, *, cutoff: str) accepts JSON mappings only:
  macro_context: unchanged chameleon-market-context-v2 object; observed_at: the
    time the caller actually observed that object, not its publication time.
  reassessment: {scope_id, expires_at, index, contract_identity}, with optional
    previous_snapshot, previous_contract_identity, previous_index_sha256,
    due_events. index and prior snapshot use the existing bridge's sealed
    contracts. A scope must contain the same complete MACRO-only comparison
    scope across calls; company inputs belong to their own upstream scopes.
  hold_policy: {portfolio: main|concentrated, available_at, incumbent?,
    challenger?, concentration?}. incumbent={record, score_median, score_sigma,
    rs_percentile, lifecycle_terminal}; challenger={record,lifecycle_terminal};
    concentration={control_rows,proposed_rows}. Policy parameters cannot be
    supplied: the existing LeadershipPersistencePolicy defaults are frozen.
    Records are existing scored-candidate records, with explicit hard-risk,
    PIT and lifecycle fields. Concentration rows are caller-supplied diagnostic
    comparisons, not targets generated or authorized by this adapter.
  company_research: optional bounded JSON research asset, retained unchanged.

Every section is optional. Missing/invalid stages remain individually BLOCKED.
Existing policy booleans are diagnostic output, never trading permission.
Neither supplied hashes/clocks nor fixture success authenticate an actual
source, current reference, historical PIT, ER, downside, cost or broker book.
No data lookup, write, dispatch, target proposal or preview activation occurs.
"""
from __future__ import annotations

import hashlib
import inspect
import math
from dataclasses import asdict, is_dataclass
from pathlib import Path

from tools import candidate_reassessment_bridge as bridge
from tools import chameleon_market_context_v2 as chameleon
from tools import free_market_context as context_rules

SCHEMA = "research-risk-connection-v1"
AUTHORITY = dict(
    source_authenticated=False, current_reference_authenticated=False,
    historical_pit_certified=False, broker_book_authenticated=False,
    a5_economic_proposal_eligible=False, economic_admission=False,
    er_calculated=False, ranking_allowed=False, portfolio_mutation_allowed=False,
    canonical_write=False, orders_allowed=False, orders_generated=False,
    weights_proposed=False, automatic_sell_allowed=False,
    specialist_dispatch=False, execute=False, preview_activation_allowed=False,
    production_activation_allowed=False, live_trading_enabled=False,
)
STAGES = ("macro_context", "reassessment", "incumbent", "challenger", "concentration")
TOP_KEYS = {"macro_context", "observed_at", "reassessment", "hold_policy", "company_research"}
NUMERIC_RECORD = {
    "alphaops_vnext_score", "rs_benchmark_1w", "rs_benchmark_3m",
    "price_above_ma50", "price_above_ma200", "rs_sector_3m",
    "industry_group_strength_score", "portfolio_risk_entry_block_score",
    "portfolio_stale_mega_leader_score",
}
TEXT_RECORD = {"ticker", "leader_tier", "sector", "industry_group", "primary_lane",
               "emerging_tenbagger_hard_reject_reason"}
BOOL_RECORD = {"top7_standalone_blocked", "pit_evidence_blocked"}


class RiskConnectionError(ValueError):
    pass


def _need(condition, reason):
    if not condition:
        raise RiskConnectionError(reason)


def _fields(value, required, optional=()):
    _need(type(value) is dict and required <= set(value)
          and set(value) <= required | set(optional), "UNEXPECTED_OR_MISSING_FIELDS")


def _number(value, *, nonnegative=False):
    _need(type(value) in (int, float) and math.isfinite(value)
          and (not nonnegative or value >= 0), "FINITE_NUMBER_REQUIRED")


def _result(value):
    if type(value) is tuple:
        return [_result(x) for x in value]
    return bridge.clean(value)


def _invoke(trace, function, *args, **kwargs):
    name = function.__module__ + "." + function.__name__
    module = inspect.getmodule(function)
    def identity(value):
        if is_dataclass(value):
            return asdict(value)
        if type(value) is dict:
            return {key: identity(item) for key, item in value.items()}
        if type(value) in (list, tuple):
            return [identity(item) for item in value]
        return value
    row = dict(function=name, input_sha256=bridge.digest(identity({"args": list(args), "kwargs": kwargs})),
               dependency_sha256=hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
               status="CALLED", output_sha256=None)
    trace.append(row)
    value = function(*args, **kwargs)
    out = _result(value)
    row.update(status="RETURNED", output_sha256=bridge.digest(out))
    return out


def _error(exc):
    # Existing domain errors are static contract codes. Never echo arbitrary
    # exception text, input values, credential-bearing paths, or tracebacks.
    if isinstance(exc, (RiskConnectionError, bridge.ReassessmentError, context_rules.ContextError)):
        reason = str(exc)
        if reason and len(reason) <= 100 and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in reason):
            return reason
    if isinstance(exc, ImportError):
        return "NATIVE_DEPENDENCY_UNAVAILABLE"
    return "EXISTING_CONTRACT_REJECTED_INPUT"


def _stage(status, reasons, result=None, input_value=None):
    return dict(status=status, reasons=reasons, result=result,
                input_sha256=None if input_value is None else bridge.digest(input_value),
                output_sha256=None if result is None else bridge.digest(result))


def _record(value):
    _need(type(value) is dict, "EXACT_CANDIDATE_RECORD_REQUIRED")
    _need(NUMERIC_RECORD | TEXT_RECORD | BOOL_RECORD <= set(value), "MISSING_CANDIDATE_EVIDENCE")
    for key in NUMERIC_RECORD:
        _number(value[key])
    for key in TEXT_RECORD:
        _need(type(value[key]) is str and (value[key] or key == "emerging_tenbagger_hard_reject_reason"),
              "CANDIDATE_TEXT_REQUIRED")
    for key in BOOL_RECORD:
        _need(type(value[key]) is bool, "EXPLICIT_RISK_BOOLEAN_REQUIRED")
    _need(not any(any(token in key.lower() for token in ("forward_return", "future_return", "outcome", "label_"))
                  for key in value), "FUTURE_LABEL_FIELDS_REJECTED")


def _macro(request, cutoff, trace):
    value = request.get("macro_context")
    _need(value is not None, "MISSING_MACRO_CONTEXT")
    _invoke(trace, chameleon.verify_context, value)
    decision, composed = bridge.stamp(cutoff), bridge.stamp(value["cutoff"])
    observed = bridge.stamp(request.get("observed_at"))
    _need(composed <= observed <= decision, "MACRO_CLOCK_ORDER")
    _need(type(value.get("macro")) is dict and bool(value["macro"]), "MISSING_MACRO_SERIES")
    effective_stale = set()
    for logical, item in value["macro"].items():
        _need(type(item) is dict and item.get("source_id") in chameleon.SERIES, "UNREGISTERED_MACRO_SOURCE")
        registered, unit, max_age, family = chameleon.SERIES[item["source_id"]]
        _need(logical == registered and item.get("unit") == unit and item.get("family") == family
              and item.get("truth_class") == "FREE_PROXY_CURRENT_VINTAGE", "MACRO_SEMANTIC_BINDING")
        available = bridge.stamp(item["available_at"])
        observation = bridge.day(item["observation_date"])
        _need(available <= composed and observation <= available.date().isoformat(), "FUTURE_MACRO_EVIDENCE")
        status = item.get("status")
        _need(status in {"OBSERVED", "STALE", "MISSING"}, "UNKNOWN_MACRO_STATUS")
        if status == "OBSERVED":
            _number(item.get("value"))
        else:
            _need(item.get("value") is None, "UNUSABLE_MACRO_VALUE")
        # Reapply only the registered existing freshness bound at this caller's
        # decision time. Do not redate an old current-vintage context as PIT.
        if (decision.date() - context_rules.iso_date(observation)).days > max_age:
            effective_stale.add(logical)
    rows = _invoke(trace, bridge.macro_rows_from_context, value, observed_at=request["observed_at"])
    for row in rows:
        if row["entity_id"] in effective_stale:
            row["status"] = "STALE"
            row["values"] = {"value": None}
    observed_count = sum(row["status"] == "OBSERVED" for row in rows)
    return dict(context_sha256=value["content_sha256"], context_cutoff=value["cutoff"],
                observed_at=request["observed_at"], cutoff=cutoff, rows=rows,
                observed_series_count=observed_count,
                unavailable_series_ids=sorted(row["entity_id"] for row in rows if row["status"] != "OBSERVED"),
                missing_families=value.get("missing_families", []),
                context_status=value.get("status"), evidence_class="UNAUTHENTICATED_CURRENT_VINTAGE_RESEARCH",
                historical_pit_certified=False, source_authenticated=False)


def _reassessment(request, macro, cutoff, trace):
    value = request.get("reassessment")
    _need(value is not None, "MISSING_REASSESSMENT_INPUT")
    _fields(value, {"scope_id", "expires_at", "index", "contract_identity"},
            {"previous_snapshot", "previous_contract_identity", "previous_index_sha256", "due_events"})
    _need(macro is not None, "MACRO_CONTEXT_NOT_VERIFIED")
    previous = value.get("previous_snapshot")
    if previous is not None:
        _invoke(trace, bridge.verify, previous, "review-observation-snapshot-v1")
        # This adapter produces only complete macro scopes. A company row in
        # the prior scope must not become a false financial-source disappearance
        # merely because this adapter cannot produce its current replacement.
        _need(type(previous.get("rows")) is list and all(
            type(row) is dict and row.get("family") in {"MACRO", "OPTIONS"}
            and row.get("entity_kind") == "MACRO_SERIES" for row in previous["rows"]),
            "PRIOR_SCOPE_NOT_MACRO_ONLY")
    current = _invoke(trace, bridge.snapshot, macro["rows"], scope_id=value["scope_id"],
                      cutoff=cutoff, expires_at=value["expires_at"])
    plan = _invoke(trace, bridge.plan_reassessment, previous, current,
                   value["index"], now=cutoff, contract_identity=value["contract_identity"],
                   previous_contract_identity=value.get("previous_contract_identity"),
                   previous_index_sha256=value.get("previous_index_sha256"), due_events=value.get("due_events"))
    proposals = _invoke(trace, bridge.a0_parameter_proposals, plan)
    return dict(snapshot=current, plan=plan, a0_parameter_proposals=proposals,
                meaning="REVIEW_INPUT_ONLY_NOT_COMPLETION_DISPATCH_OR_ECONOMIC_PERMISSION")


def _hold_stage(name, value, portfolio, trace):
    # Lazy native import. Missing installed dependencies block only these policy
    # stages; macro and retained company research remain available.
    from tools import run287_hold_exit_policy as policy_module
    policy = policy_module.LeadershipPersistencePolicy()
    runtime_context = {}
    if name == "incumbent":
        _fields(value, {"record", "score_median", "score_sigma", "rs_percentile", "lifecycle_terminal"})
        _record(value["record"])
        _number(value["score_median"])
        _number(value["score_sigma"], nonnegative=True)
        _number(value["rs_percentile"])
        _need(0 <= value["rs_percentile"] <= 1, "RS_PERCENTILE_RANGE")
        _need(type(value["lifecycle_terminal"]) is bool, "EXPLICIT_LIFECYCLE_REQUIRED")
        replay = inspect.getmodule(policy_module.holding_state)
        # These existing feature toggles can influence native holding_state.
        # Bind their actual values and code; do not change the environment.
        runtime_context = dict(
            shakeout_guard_prod_enabled=_invoke(trace, replay.shakeout_guard_prod_enabled),
            shakeout_guard_warning_suppress_enabled=_invoke(trace, replay.shakeout_guard_warning_suppress_enabled))
        raw = _invoke(trace, policy_module.incumbent_protection, value["record"], portfolio=portfolio,
                      score_median=value["score_median"], score_sigma=value["score_sigma"],
                      rs_percentile=value["rs_percentile"], lifecycle_terminal=value["lifecycle_terminal"], policy=policy)
    elif name == "challenger":
        _fields(value, {"record", "lifecycle_terminal"})
        _record(value["record"])
        _need(type(value["lifecycle_terminal"]) is bool, "EXPLICIT_LIFECYCLE_REQUIRED")
        raw = _invoke(trace, policy_module.challenger_eligible, value["record"],
                      lifecycle_terminal=value["lifecycle_terminal"], policy=policy)
    else:
        _fields(value, {"control_rows", "proposed_rows"})
        for key in ("control_rows", "proposed_rows"):
            rows = value[key]
            _need(type(rows) is list and 0 < len(rows) <= bridge.MAX_ROWS, "CONCENTRATION_ROWS_REQUIRED")
            seen = set()
            for row in rows:
                _need(type(row) is dict and type(row.get("ticker")) is str and row["ticker"].strip(), "POSITION_ID_REQUIRED")
                ticker = row["ticker"].strip().upper()
                _need(ticker not in seen, "DUPLICATE_POSITION")
                seen.add(ticker)
                _number(row.get("weight"), nonnegative=True)
                _need(row["weight"] <= 1, "WEIGHT_RANGE")
                if ticker not in policy_module.CASH_TICKERS:
                    _need(all(type(row.get(k)) is str and row[k].strip() and row[k].upper() != "UNKNOWN"
                              for k in ("sector", "industry_group")), "MISSING_EXPOSURE_IDENTITY")
            _need(sum(row["weight"] for row in rows) <= 1 + 1e-12, "COMPARISON_WEIGHT_TOTAL")
        raw = _invoke(trace, policy_module.concentration_not_worse,
                      value["control_rows"], value["proposed_rows"], portfolio=portfolio)
    return dict(existing_policy_result=raw, policy=policy.audit(), runtime_policy_context=runtime_context,
                meaning="EXISTING_POLICY_DIAGNOSTIC_NOT_HOLD_SELL_BUY_OR_REPLACEMENT_AUTHORITY")


def build_risk_connection(request: dict, *, cutoff: str) -> dict:
    """Return hash-bound research diagnostics; never authorize an economic action."""
    trace = []
    stages = {name: _stage("BLOCKED", ["INPUT_NOT_PROVIDED"]) for name in STAGES}
    company = None
    request_hash = None
    input_errors = {}
    safe_cutoff = None
    try:
        _need(type(request) is dict, "REQUEST_MAPPING_REQUIRED")
        cleaned = {}
        for key, value in request.items():
            _need(type(key) is str, "JSON_KEY")
            try:
                cleaned[key] = bridge.clean(value)
            except (ValueError, TypeError, OverflowError, RecursionError) as exc:
                input_errors[key] = _error(exc)
        company = cleaned.get("company_research")
        _need(set(request) <= TOP_KEYS, "UNEXPECTED_REQUEST_FIELDS")
        request = cleaned
        bridge.stamp(cutoff)
        safe_cutoff = cutoff
        if not input_errors:
            request_hash = bridge.digest(request)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        reason = _error(exc)
        stages = {name: _stage("BLOCKED", [reason]) for name in STAGES}
    else:
        macro = None
        try:
            _need(not (set(input_errors) & {"macro_context", "observed_at"}), "INVALID_MACRO_INPUT_JSON")
            macro = _macro(request, cutoff, trace)
            reasons = [] if macro["observed_series_count"] else ["NO_CURRENT_OBSERVED_MACRO_SERIES"]
            stages["macro_context"] = _stage("BLOCKED" if reasons else "DIAGNOSTIC_ONLY", reasons,
                                              macro, request.get("macro_context"))
        except (ValueError, TypeError, KeyError, OverflowError, ImportError) as exc:
            stages["macro_context"] = _stage("BLOCKED", [_error(exc)], input_value=request.get("macro_context"))
        try:
            _need("reassessment" not in input_errors, "INVALID_REASSESSMENT_INPUT_JSON")
            result = _reassessment(request, macro, cutoff, trace)
            stages["reassessment"] = _stage("DIAGNOSTIC_ONLY", [], result, request.get("reassessment"))
        except (ValueError, TypeError, KeyError, OverflowError, ImportError) as exc:
            stages["reassessment"] = _stage("BLOCKED", [_error(exc)], input_value=request.get("reassessment"))
        hold = request.get("hold_policy")
        try:
            _need("hold_policy" not in input_errors, "INVALID_POLICY_INPUT_JSON")
            _need(hold is not None, "MISSING_HOLD_POLICY_INPUT")
            _fields(hold, {"portfolio", "available_at"}, {"incumbent", "challenger", "concentration"})
            _need(hold["portfolio"] in {"main", "concentrated"}, "PORTFOLIO_KIND")
            _need(bridge.stamp(hold["available_at"]) <= bridge.stamp(cutoff), "FUTURE_POLICY_EVIDENCE")
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            for name in STAGES[2:]:
                stages[name] = _stage("BLOCKED", [_error(exc)])
        else:
            for name in STAGES[2:]:
                try:
                    _need(name in hold, "MISSING_POLICY_STAGE_INPUT")
                    result = _hold_stage(name, hold[name], hold["portfolio"], trace)
                    stages[name] = _stage("DIAGNOSTIC_ONLY", [], result, hold[name])
                except (ValueError, TypeError, KeyError, OverflowError, ImportError) as exc:
                    stages[name] = _stage("BLOCKED", [_error(exc)], input_value=hold.get(name))
    completed = sum(stage["status"] == "DIAGNOSTIC_ONLY" for stage in stages.values())
    output = dict(schema=SCHEMA, cutoff=safe_cutoff, input_sha256=request_hash, input_errors=input_errors,
                  status="BLOCKED" if not completed else "RESEARCH_DIAGNOSTICS_ONLY" if completed == len(STAGES)
                  else "PARTIAL_RESEARCH_DIAGNOSTICS", stages=stages, call_trace=trace,
                  company_research=company, company_research_sha256=None if company is None else bridge.digest(company),
                  a5_blockers=["SOURCE_CURRENT_AND_BROKER_BOOK_NOT_AUTHENTICATED",
                               "ACTUAL_ER_DOWNSIDE_COST_IDENTITY_AND_PORTFOLIO_CLOCKS_NOT_ADMITTED",
                               "INDEPENDENT_A6_AND_EXPLICIT_ECONOMIC_APPROVAL_NOT_PRESENT"],
                  limitation="FIXTURE_OR_HASH_PARITY_IS_NOT_ACTUAL_SOURCE_PIT_OR_ECONOMIC_ADMISSION", **AUTHORITY)
    try:
        sealed = bridge.seal(output)
        # seal checks the payload before adding its content hash. Verify the
        # complete envelope too, so the public result stays within the budget.
        return bridge.clean(sealed)
    except bridge.ReassessmentError as exc:
        # A valid company asset can leave insufficient room for diagnostics.
        # Retain its hash, refuse the whole output, and never truncate research
        # into a success-looking partial asset or expose an unbounded exception.
        output.update(status="BLOCKED", company_research=None, call_trace=[],
                      input_errors={"output": _error(exc)}, output_refusal=_error(exc),
                      stages={name: _stage("BLOCKED", ["OUTPUT_SEAL_REFUSED"]) for name in STAGES})
        return bridge.clean(bridge.seal(output))
