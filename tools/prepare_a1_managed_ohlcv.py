"""Prepare existing A1 source reuse and A0-managed refresh; never perform I/O to a provider.

This is a roster/session adapter, not a collector, ledger or source-admission gate.
The existing Source controller must authenticate receipts and an execution contract.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
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
    require(value.get("automatic_capture_enabled") is False
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


def prepare(inventory, policy, inventory_sha, gate, *, previous=None, previous_sha=None, now_utc=None):
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
    current = evaluate_market_session(now_utc=checked, min_close_age_minutes=120)
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
    return dict(schema="a1-managed-ohlcv-refresh-plan-v1",
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


def write_report(path, payload, inputs):
    output = Path(path)
    require(not output.is_symlink(), "OUTPUT_ALIAS")
    resolved = output.resolve()
    for item in inputs:
        require(resolved != Path(item).resolve(), "OUTPUT_ALIAS")
        require(not (output.exists() and Path(item).exists() and os.path.samefile(output, item)), "OUTPUT_ALIAS")
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
