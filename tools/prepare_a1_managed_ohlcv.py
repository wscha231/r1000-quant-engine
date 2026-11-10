"""Prepare existing A1 source reuse and A0-managed refresh; never perform I/O to a provider.

This is a roster/session adapter, not a collector, ledger or source-admission gate.
The existing Source controller must authenticate receipts and an execution contract.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from tools.run_daily_market_session_gate import evaluate_market_session, utc_timestamp

MAX_BYTES = 2_000_000
MAX_SYMBOLS = 1500
SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,13}")
SHA = re.compile(r"[0-9a-f]{64}")
A0 = "https://github.com/wscha231/r1000-quant-engine/issues/448"
ORIGINAL = "ad60fb7c4f2b8c34b2aa23ab7505e83eefc681c3bc2c6d78f6f9187a4ae79924"
CADENCE_SCHEMA = "a1-managed-tiered-cadence-v1"
MONITOR_CONTRACT = Path("docs/run287_daily_research_monitor_contract.json")


def require(value, code):
    if not value:
        raise ValueError(code)


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def load(path):
    # Bound the read itself, not only the subsequently allocated JSON object.
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    require(0 < len(raw) <= MAX_BYTES, "INPUT_SIZE")
    return json.loads(raw, object_pairs_hook=unique_object,
                      parse_constant=lambda _: require(False, "NONFINITE_JSON")), digest(raw)


def symbols(value):
    require(isinstance(value, list) and len(value) <= MAX_SYMBOLS
            and all(isinstance(t, str) and SYMBOL.fullmatch(t) for t in value), "ROSTER")
    require(value == sorted(set(value)), "ROSTER_ORDER_OR_DUPLICATE")
    return set(value)


def _aware(value):
    require(isinstance(value, str) and not value.endswith("-00:00")
            and re.search(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$", value),
            "CADENCE_EXPLICIT_CLOCK")
    return utc_timestamp(value)


def _week(session):
    from tools.run_daily_market_session_gate import mcal
    day = date.fromisoformat(session)
    require(day.isoformat() == session, "CADENCE_SESSION")
    monday = day - timedelta(days=day.weekday())
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=monday, end_date=monday + timedelta(days=4))
    require(not schedule.empty, "CADENCE_CALENDAR")
    return monday, schedule


def cadence_contract(value, *, not_before, expires_at):
    """Validate opt-in fields already covered by the immutable OWNER control hash."""
    require(isinstance(value, dict) and set(value) == {
        "schema", "roster_ref", "source_refs", "monitor_contract_sha256",
        "max_priority_candidates", "holdings_binding", "weekly_catchup"} and value["schema"] == CADENCE_SCHEMA,
        "CADENCE_CONTRACT")
    require(isinstance(value["monitor_contract_sha256"], str)
            and SHA.fullmatch(value["monitor_contract_sha256"]), "CADENCE_MONITOR_PIN")
    require(type(value["max_priority_candidates"]) is int
            and 0 <= value["max_priority_candidates"] <= 60, "CADENCE_CANDIDATE_BOUND")
    require(isinstance(value["source_refs"], list) and 1 <= len(value["source_refs"]) <= 32,
            "CADENCE_PROOF_BOUND")
    extra = value["weekly_catchup"]
    if extra is not None:
        require(isinstance(extra, dict) and set(extra) == {
            "mode", "week_start", "session", "not_before", "expires_at"}
            and extra["mode"] == "WEEKLY_CATCHUP", "CADENCE_WEEKLY_CONTRACT")
        monday, schedule = _week(extra["session"])
        require(extra["week_start"] == monday.isoformat()
                and extra["session"] == schedule.index[-1].strftime("%Y-%m-%d"),
                "CADENCE_WEEK_END_SESSION")
        start, end = _aware(extra["not_before"]), _aware(extra["expires_at"])
        # A separate exact-week contract never widens the global daily age guard.
        import pandas as pd
        monday_end = pd.Timestamp(monday + timedelta(days=7), tz="America/New_York").tz_convert("UTC")
        require(_aware(not_before) <= start < end <= _aware(expires_at)
                and end <= monday_end
                and start >= schedule.iloc[-1]["market_close"] + timedelta(minutes=120),
                "CADENCE_WEEKLY_WINDOW")
    return value


def cadence_market_gate(*, now_utc, cadence=None):
    ordinary = evaluate_market_session(now_utc=now_utc, min_close_age_minutes=120)
    if cadence is None or cadence["weekly_catchup"] is None:
        return ordinary
    extra = cadence["weekly_catchup"]
    now = utc_timestamp(now_utc)
    if not (_aware(extra["not_before"]) <= now < _aware(extra["expires_at"])):
        return ordinary
    monday, schedule = _week(extra["session"])
    close = schedule.iloc[-1]["market_close"]
    require(extra["week_start"] == monday.isoformat()
            and extra["session"] == schedule.index[-1].strftime("%Y-%m-%d")
            and close + timedelta(minutes=120) <= now
            and ordinary["latest_completed_session_date"] == extra["session"],
            "CADENCE_WEEKLY_SESSION_CONFLICT")
    return dict(ordinary, status="READY_EXPLICIT_WEEKLY_CATCHUP", ready=True,
                forced=False, selected_session_explicit=True, catchup_mode=True,
                session_date=extra["session"], market_close_utc=close.isoformat(),
                close_age_minutes=(now - close).total_seconds() / 60,
                weekly_contract_sha256=digest(encode(extra)))


def priority_roster(raw, *, expected_sha256, monitor_raw, monitor_sha256,
                    proof_objects, max_priority_candidates, holdings_binding, now_utc):
    """Parse externally hash-pinned evidence; never authenticate its own flags.

    The live caller obtains all expected pins from its independently validated
    OWNER control. Offline callers receive no execution/admission authority.
    UNKNOWN holdings are not an empty portfolio. Independent roles survive it.
    """
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES
            and isinstance(expected_sha256, str) and SHA.fullmatch(expected_sha256)
            and digest(raw) == expected_sha256, "CADENCE_ROSTER_HASH")
    require(type(monitor_raw) is bytes and 0 < len(monitor_raw) <= MAX_BYTES
            and digest(monitor_raw) == monitor_sha256, "CADENCE_MONITOR_HASH")
    value = json.loads(raw, object_pairs_hook=unique_object,
                       parse_constant=lambda _: require(False, "NONFINITE_JSON"))
    monitor = json.loads(monitor_raw, object_pairs_hook=unique_object,
                         parse_constant=lambda _: require(False, "NONFINITE_JSON"))
    from tools.run287_etf_rotation import policy as rotation_policy, universe
    config, _, _ = rotation_policy(monitor)
    etfs = set(universe(config))  # exact existing42, never a copied/invented list
    require(isinstance(value, dict) and set(value) == {
        "schema", "usage", "as_of", "available_at", "expires_at", "source_reference",
        "holdings", "roles"} and value["schema"] == "a1-managed-priority-roster-v1"
        and value["usage"] == "RESEARCH_ONLY", "CADENCE_ROSTER_SCHEMA")
    now = utc_timestamp(now_utc)
    require(_aware(value["as_of"]) <= _aware(value["available_at"]) <= now
            < _aware(value["expires_at"]), "CADENCE_ROSTER_STALE_OR_FUTURE")
    require(isinstance(value["source_reference"], str)
            and re.fullmatch(re.escape(A0) + r"#issuecomment-[0-9]+", value["source_reference"]),
            "CADENCE_SOURCE_REFERENCE")
    require(isinstance(proof_objects, dict) and 1 <= len(proof_objects) <= 32
            and all(isinstance(h, str) and SHA.fullmatch(h) and type(b) is bytes
                    and 0 < len(b) <= MAX_BYTES and digest(b) == h
                    for h, b in proof_objects.items())
            and sum(map(len, proof_objects.values())) <= 16 * 1024 * 1024,
            "CADENCE_SOURCE_PROOFS")

    def evidence(row):
        require(isinstance(row.get("source_sha256"), str)
                and row["source_sha256"] in proof_objects
                and isinstance(row.get("source_reference"), str)
                and 0 < len(row["source_reference"]) <= 500
                and row["source_reference"].startswith("https://"), "CADENCE_ROLE_SOURCE")
        require(row.get("scope") in {"RESEARCH_ONLY", "ACTUAL"}, "CADENCE_ROLE_SCOPE")
        require(_aware(row.get("as_of")) <= _aware(row.get("available_at")) <= now
                and _aware(row.get("available_at")) < _aware(row.get("expires_at")),
                "CADENCE_ROLE_FUTURE")
        return now < _aware(row.get("expires_at"))

    daily = {t: ["ETF"] for t in etfs}
    stale = {}
    holdings = value["holdings"]
    require(isinstance(holdings, dict) and holdings.get("status") in {
        "UNKNOWN", "VERIFIED", "NO_POSITIONS", "NOT_CONFIGURED"}
        and holdings.get("portfolio_mode") in {"RESEARCH_ONLY", "ACTUAL"}, "CADENCE_HOLDINGS")
    status = holdings["status"]
    if status == "UNKNOWN":
        require(holdings.get("tickers") is None and holdings_binding is None,
                "CADENCE_UNKNOWN_NOT_EMPTY")
        completeness = "UNKNOWN"
    else:
        binding_fields = {"portfolio_mode", "portfolio_kind", "status", "positions_sha256", "tickers",
                          "as_of", "available_at", "expires_at", "source_reference"}
        require(isinstance(holdings_binding, dict) and set(holdings_binding) == binding_fields
                and {k: holdings.get(k) for k in binding_fields} == holdings_binding
                and holdings.get("positions_sha256") == holdings.get("source_sha256")
                and holdings.get("scope") == holdings["portfolio_mode"], "CADENCE_HOLDINGS_EXTERNAL_BINDING")
        kind = holdings.get("portfolio_kind")
        require((holdings["portfolio_mode"] == "ACTUAL" and kind == "ACTUAL_ACCEPTED")
                or (holdings["portfolio_mode"] == "RESEARCH_ONLY" and kind in {
                    "RESEARCH_MODEL", "RESEARCH_NO_POSITIONS", "RESEARCH_NOT_CONFIGURED"}),
                "CADENCE_HOLDINGS_KIND")
        valid = evidence(holdings)
        names = symbols(holdings.get("tickers"))
        if status in {"NO_POSITIONS", "NOT_CONFIGURED"}:
            require(holdings["portfolio_mode"] == "RESEARCH_ONLY" and not names
                    and kind == "RESEARCH_" + status,
                    "CADENCE_EMPTY_HOLDINGS_SCOPE")
        else:
            require(names, "CADENCE_EMPTY_VERIFIED_HOLDINGS")
        completeness = ("NOT_CONFIGURED_RESEARCH" if status == "NOT_CONFIGURED" else "VERIFIED") if valid else "STALE"
        for ticker in names:
            if valid:
                daily.setdefault(ticker, []).append("HOLDING")
            else:
                stale[ticker] = ["STALE_HOLDING_EVIDENCE"]
    roles = value["roles"]
    require(isinstance(roles, list) and type(max_priority_candidates) is int
            and 0 <= max_priority_candidates <= 60 and len(roles) <= max_priority_candidates,
            "CADENCE_CANDIDATE_BOUND")
    seen, events = set(), set()
    for row in roles:
        require(isinstance(row, dict) and row.get("role") in {"PRIORITY", "OPPORTUNITY"},
                "CADENCE_ROLE")
        ticker = row.get("ticker")
        require(isinstance(ticker, str) and SYMBOL.fullmatch(ticker) and ticker not in seen,
                "CADENCE_ROLE_DUPLICATE")
        require(row.get("scope") == "RESEARCH_ONLY", "CADENCE_CANDIDATE_RESEARCH_SCOPE")
        seen.add(ticker)
        if row["role"] == "OPPORTUNITY":
            event = row.get("event_id")
            require(row.get("verification") in {"V1", "V2"} and isinstance(event, str)
                    and re.fullmatch(r"[A-Za-z0-9._:-]{8,100}", event) and event not in events,
                    "CADENCE_EVENT_UNVERIFIED")
            events.add(event)
        if evidence(row):
            daily.setdefault(ticker, []).append(row["role"])
        else:
            stale.setdefault(ticker, []).append("STALE_" + row["role"] + "_EVIDENCE")
    return dict(roster_sha256=expected_sha256, daily=daily, stale_roles=stale,
                holdings_status=status, holdings_completeness=completeness,
                overall_status="PARTIAL_HOLDINGS" if completeness != "VERIFIED" else "ROSTER_VERIFIED",
                etf_monitor_sha256=monitor_sha256, etf_count=len(etfs),
                source_authentication="EXTERNAL_OWNER_CONTROL_REQUIRED", source_admission=False)


def tier_schedule(roster, tracked, session):
    monday, schedule = _week(session)
    ending = schedule.index[-1].strftime("%Y-%m-%d")
    weekly_due = ending == session
    if not weekly_due:
        _, previous = _week((monday - timedelta(days=1)).isoformat())
        ending = previous.index[-1].strftime("%Y-%m-%d")
    ranks = {"HOLDING": 0, "ETF": 1, "PRIORITY": 2, "OPPORTUNITY": 3}
    daily = sorted(set(roster["daily"]) & set(tracked))
    return dict(roster_sha256=roster["roster_sha256"], daily=daily,
                role_rank={t: min(ranks[r] for r in roster["daily"][t]) for t in daily},
                weekly_due=weekly_due, weekly_target_session=ending,
                outside_scope=sorted(set(roster["daily"]) - set(tracked)),
                holdings_completeness=roster["holdings_completeness"],
                holdings_status=roster["holdings_status"], stale_roles=roster["stale_roles"])


def coverage_day(value, session):
    require(isinstance(value, str), "CADENCE_COVERAGE_DATE")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ValueError("CADENCE_COVERAGE_DATE") from None
    require(day.isoformat() == value and value <= session, "CADENCE_COVERAGE_DATE")
    return value


def tier_progress(scheduling, tracked, coverage, held, session):
    tracked = set(tracked)
    daily = set(scheduling["daily"])
    rows = {}
    for t in sorted(tracked):
        target = session if t in daily else scheduling["weekly_target_session"]
        seen = coverage_day(coverage[t], session) if t in coverage else None
        current = isinstance(seen, str) and seen >= target
        rows[t] = dict(tier="DAILY" if t in daily else "WEEKLY", target_session=target,
                       covered_through=seen, status="HELD" if t in held else
                       "CURRENT" if current else "PENDING", reason=held.get(t),
                       due=t in daily or scheduling["weekly_due"])
    counts = {tier: {state: sum(r["tier"] == tier and r["status"] == state for r in rows.values())
                     for state in ("CURRENT", "PENDING", "HELD")} for tier in ("DAILY", "WEEKLY")}
    reasons = {}
    for t in tracked & set(held):
        reason = held[t]
        require(isinstance(reason, str) and re.fullmatch(r"[A-Z_]{1,100}", reason), "CADENCE_HELD_REASON")
        reasons[reason] = reasons.get(reason, 0) + 1
    stale = {}
    for values in scheduling["stale_roles"].values():
        for reason in values:
            stale[reason] = stale.get(reason, 0) + 1
    return dict(by_tier=counts, weekly_due=scheduling["weekly_due"],
                weekly_target_session=scheduling["weekly_target_session"],
                pending=sum(r["status"] == "PENDING" for r in rows.values()),
                pending_daily=[t for t, r in rows.items() if r["tier"] == "DAILY" and r["status"] == "PENDING"],
                pending_weekly=[t for t, r in rows.items() if r["tier"] == "WEEKLY" and r["status"] == "PENDING"],
                held=sum(r["status"] == "HELD" for r in rows.values()),
                held_tickers=[t for t, r in rows.items() if r["status"] == "HELD"], held_reasons=reasons,
                outside_scope=scheduling["outside_scope"], outside_scope_reason="OUTSIDE_APPROVED_EXECUTION_SCOPE",
                holdings_completeness=scheduling["holdings_completeness"],
                stale_role_counts=stale, collection_approved_by_roster=False)


def inventory_rows(value):
    require(isinstance(value, dict) and value.get("schema") == "a1-retained-ohlcv-index-v1"
            and value.get("original_inventory_sha256") == ORIGINAL, "INVENTORY")
    rows = value.get("securities")
    require(isinstance(rows, list) and len(rows) == 820
            and all(isinstance(r, dict) for r in rows), "INVENTORY_COUNT")
    names = symbols([r.get("ticker") for r in rows])
    counts = dict(unique_tickers=len(names), alpaca_sip=0, twelve_data=0, overlap=0)
    for row in rows:
        providers = row.get("providers")
        require(isinstance(providers, list) and providers
                and len(providers) == len(set(providers))
                and set(providers) <= {"alpaca_sip", "twelve_data"}, "INVENTORY_PROVIDER")
        counts["alpaca_sip"] += "alpaca_sip" in providers
        counts["twelve_data"] += "twelve_data" in providers
        counts["overlap"] += len(providers) == 2
    require(value.get("counts") == counts == dict(
        unique_tickers=820, alpaca_sip=776, twelve_data=312, overlap=268), "INVENTORY_COUNTS")
    return {row["ticker"]: row for row in rows}


def policy_rows(value, inventory_sha):
    require(isinstance(value, dict) and value.get("schema") == "a1-managed-ohlcv-policy-v1"
            and type(value.get("revision")) is int and 1 <= value["revision"] <= 10000
            and value.get("inventory_sha256") == inventory_sha
            and value.get("baseline_inventory_sha256") == inventory_sha
            and value.get("control_reference") == A0, "POLICY_BINDING")
    require(type(value.get("refresh_delay_minutes")) is int
            and value["refresh_delay_minutes"] == 120, "REFRESH_DELAY")
    # A boolean in a config cannot turn this preparation adapter into a dispatcher.
    require(type(value.get("automatic_capture_enabled")) is bool
            and value.get("execution_authorization") is None, "CAPTURE_NOT_IMPLEMENTED")
    active = symbols(value.get("active_tickers"))
    watch = symbols(value.get("watch_tickers"))
    require(active.isdisjoint(watch) and len(active | watch) <= MAX_SYMBOLS, "ROSTER_OVERLAP")
    return active


def transition(policy, previous, previous_sha, retained, active, inventory_sha):
    if policy["revision"] == 1:
        require(previous is None and previous_sha is None
                and policy.get("previous_policy_sha256") is None
                and active == set(retained) and policy.get("watch_tickers") == []
                and policy.get("changes") == [], "BASELINE_ROSTER")
        return [], []
    expected = policy.get("previous_policy_sha256")
    require(isinstance(expected, str) and SHA.fullmatch(expected)
            and expected == previous_sha and isinstance(previous, dict), "PREVIOUS_POLICY")
    old = policy_rows(previous, inventory_sha)
    require(policy["revision"] == previous["revision"] + 1, "POLICY_REVISION")
    added, removed = sorted(active - old), sorted(old - active)
    require(set(policy["watch_tickers"]) == (set(previous["watch_tickers"]) | set(removed)) - active,
            "WATCH_HISTORY_MUST_BE_RETAINED")
    changes = policy.get("changes")
    require(isinstance(changes, list) and len(changes) <= 2 * MAX_SYMBOLS, "ROSTER_CHANGES")
    seen, event_ids = set(), set()
    for item in changes:
        require(isinstance(item, dict) and set(item) == {"ticker", "action", "event_id", "a0_reference"},
                "ROSTER_CHANGE")
        ticker, action = item["ticker"], item["action"]
        require(isinstance(ticker, str) and SYMBOL.fullmatch(ticker)
                and action in {"START_UPDATE", "MOVE_TO_WATCH"}, "ROSTER_CHANGE")
        pair = (ticker, action)
        event = item["event_id"]
        require(pair not in seen and isinstance(event, str)
                and re.fullmatch(r"[A-Za-z0-9._:-]{8,100}", event)
                and event not in event_ids, "DUPLICATE_CHANGE")
        require(isinstance(item["a0_reference"], str)
                and re.fullmatch(re.escape(A0) + r"#issuecomment-[0-9]+", item["a0_reference"]),
                "A0_CHANGE_REFERENCE")
        seen.add(pair)
        event_ids.add(event)
    require(seen == ({(t, "START_UPDATE") for t in added}
                     | {(t, "MOVE_TO_WATCH") for t in removed}), "ROSTER_CHANGE_MISMATCH")
    return added, removed


def prepare(inventory, policy, inventory_sha, gate, *, previous=None, previous_sha=None, now_utc=None,
            cadence=None, roster=None):
    retained = inventory_rows(inventory)
    active = policy_rows(policy, inventory_sha)
    watch = set(policy["watch_tickers"])
    added, removed = transition(policy, previous, previous_sha, retained, active, inventory_sha)
    require(isinstance(gate, dict) and gate.get("schema_version") == "daily-market-session-gate-v1"
            and gate.get("calendar") == "NYSE", "MARKET_GATE")
    checked = utc_timestamp(gate.get("checked_at_utc"))
    require(isinstance(gate.get("checked_at_utc"), str)
            and re.search(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$", gate["checked_at_utc"]), "MARKET_CLOCK")
    age = (utc_timestamp(now_utc) - checked).total_seconds()
    require(0 <= age <= 900, "MARKET_RECEIPT_STALE_OR_FUTURE")
    # Recompute using the existing exchange calendar. Force cannot bypass the buffer.
    require((cadence is None) == (roster is None), "CADENCE_PLAN_INPUTS")
    current = cadence_market_gate(now_utc=checked, cadence=cadence)
    require(gate.get("session_date") == current["session_date"]
            and gate.get("market_close_utc") == current["market_close_utc"], "MARKET_SESSION_CONFLICT")
    close = utc_timestamp(current["market_close_utc"]) if current["market_close_utc"] else None
    due = (close + timedelta(minutes=120)).isoformat() if close is not None else None
    rows = []
    for ticker in sorted(active | watch):
        prior = retained.get(ticker)
        rows.append(dict(ticker=ticker, management_state="FOCUS" if ticker in active else "WATCH",
                         price_tracking_requested=True,
                         next_action="VERIFY_EXISTING_COVERAGE" if prior else "BACKFILL_REVIEW_REQUIRED",
                         retained_providers=prior["providers"] if prior else [],
                         receipt_keys=prior.get("receipt_keys", []) if prior else [],
                         missing_interval=None, source_identity_verified=False,
                         source_admission=False, pit_verified=False))
    result = dict(schema="a1-managed-ohlcv-refresh-plan-v1",
                plan_id=digest(encode(dict(inventory_sha256=inventory_sha,
                    policy_sha256=digest(encode(policy)), session_date=current["session_date"]))),
                status="PREPARED_NO_CAPTURE" if current["ready"] else "SKIP_MARKET_WINDOW",
                checked_at_utc=checked.isoformat(), session_date=current["session_date"],
                market_close_utc=current["market_close_utc"], earliest_refresh_utc=due,
                market_ready=current["ready"], market_reason=current["status"],
                inventory_sha256=inventory_sha, policy_sha256=digest(encode(policy)),
                policy_hash_basis="canonical sorted JSON, not the original input file bytes",
                added=added, moved_to_watch=[dict(ticker=t, action="CONTINUE_TRACKING_RETAIN_HISTORY") for t in removed],
                updates_stopped=[], active_count=len(active), watch_count=len(watch), tracked_count=len(rows),
                retained_inventory_count=len(retained), requests=rows,
                a0_configuration_authentication="NOT_PERFORMED_BY_OFFLINE_ADAPTER",
                provider_requests=0, dispatches=0, collection_enabled=False,
                execution_status="BLOCKED_EXECUTION_CONTRACT_AND_ACCOUNT_RIGHTS",
                required_execution_evidence=["current account-bound private research retention/purpose terms",
                    "protected Source deployment and standing bounded maintenance authorization",
                    "original source receipts and actual per-security coverage/lifecycle/CA",
                    "same writer/owner-only storage/checkpoint/idempotency and cumulative costs"],
                original_campaigns_changed=False, source_admission=False, pit_verified=False,
                economic_authority=False)
    if roster is not None:
        schedule = tier_schedule(roster, active | watch, current["session_date"])
        result.update(cadence_sha256=digest(encode(cadence)), tier_schedule=schedule,
                      holdings_status=roster["holdings_status"], overall_status=roster["overall_status"])
        result["plan_id"] = digest(encode(dict(inventory_sha256=inventory_sha,
            policy_sha256=result["policy_sha256"], session_date=current["session_date"],
            cadence_sha256=result["cadence_sha256"], roster_sha256=roster["roster_sha256"])))
        for row in rows:
            row["refresh_tier"] = "DAILY" if row["ticker"] in schedule["daily"] else "WEEKLY"
    return result


def protect_output(path, inputs):
    output = Path(path)
    require(not output.is_symlink(), "OUTPUT_ALIAS")
    resolved = output.resolve()
    for item in inputs:
        history = Path(item).parent / "a1_ohlcv_managed_history"
        require(not resolved.is_relative_to(history.resolve()), "OUTPUT_ALIAS")
        require(resolved != Path(item).resolve(), "OUTPUT_ALIAS")
        require(not (output.exists() and Path(item).exists() and os.path.samefile(output, item)), "OUTPUT_ALIAS")
    return output


def write_report(path, payload, inputs):
    output = protect_output(path, inputs)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".managed-ohlcv-", dir=output.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encode(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(args):
    inputs = [args.inventory, args.policy, args.market_gate]
    try:
        inventory, inventory_sha = load(args.inventory)
        policy, policy_file_sha = load(args.policy)
        previous = previous_sha = None
        expected = policy.get("previous_policy_sha256") if isinstance(policy, dict) else None
        if expected is not None:
            require(isinstance(expected, str) and SHA.fullmatch(expected), "PREVIOUS_POLICY")
            path = Path(args.policy).parent / "a1_ohlcv_managed_history" / (expected + ".json")
            inputs.append(path)
            previous, previous_sha = load(path)
        gate, gate_sha = load(args.market_gate)
        report = prepare(inventory, policy, inventory_sha, gate,
                         previous=previous, previous_sha=previous_sha, now_utc=args.now_utc)
        report.update(policy_file_sha256=policy_file_sha, market_gate_sha256=gate_sha)
        head = os.environ.get("GITHUB_SHA", "")
        report["producer_code_sha"] = head if re.fullmatch(r"[0-9a-f]{40}", head) else None
        code = 0
    except (ValueError, OSError, TypeError, KeyError, OverflowError):
        # Failed preparation revokes an earlier success at this same output path.
        report = dict(schema="a1-managed-ohlcv-refresh-plan-v1", status="BLOCKED_INPUT",
                      provider_requests=0, dispatches=0, collection_enabled=False,
                      source_admission=False, pit_verified=False, economic_authority=False)
        code = 2
    write_report(args.output, report, inputs)
    return code, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--market-gate", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--now-utc", default=None)
    args = parser.parse_args()
    code, report = run(args)
    print(json.dumps({k: report[k] for k in ("status", "provider_requests", "dispatches", "collection_enabled")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
