"""Read-only admission from an authenticated monitor artifact to the strict runtime.

The caller must obtain run/artifact metadata with the existing GitHub monitor,
not from the ZIP. Hashes prove byte identity, not economic truth. Business LINK
approval comes from the separately reviewed repository contract, never a boolean
in a source bundle. No network, writer, collector, evaluator or universe engine.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

ROLES = ("base_universe", "securities", "prices", "etf_snapshots", "documents", "membership_events")
SCHEMA = "theme-etf-source-bundle-v1"
SAFETY = {"research_only": True, "orders_allowed": False,
          "target_book_write_allowed": False, "ledger_write_allowed": False,
          "production_activation_allowed": False, "fullrun_allowed": False}
FORBIDDEN = set(SAFETY) - {"research_only"} | {
    "orders_generated", "target_book_changed", "live_trading_enabled",
    "eligible_for_selector", "auto_promote", "decision_ranking_allowed"}


class AdmissionError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise AdmissionError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def utc(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "naive_timestamp")
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise AdmissionError("invalid_or_naive_timestamp") from None


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, "duplicate_json_key")
        out[key] = value
    return out


def _authority(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN:
                require(item is False, "forbidden_authority")
            if key == "research_only":
                require(item is True, "research_only_required")
            _authority(item)
    elif isinstance(value, list):
        for item in value:
            _authority(item)


def _json(raw):
    def reject_constant(_):
        raise AdmissionError("nonfinite_json")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_constant=reject_constant)
    _authority(value)
    return value


def blocked(reason, session):
    return {"schema": SCHEMA, "status": "BLOCKED", "reason": reason,
            "expected_session": session, "runtime_executed": False,
            "company_evaluator_executed": False, "end_to_end_ready": False,
            "safety": dict(SAFETY)}


def _member(archive, ref, policy, evidence):
    require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}, "invalid_object_reference")
    name = ref["path"]
    require(isinstance(name, str) and name.startswith(policy["member_root"])
            and "\\" not in name and not PurePosixPath(name).is_absolute()
            and all(p not in {".", "..", ""} for p in name.split("/")), "invalid_member_path")
    require(archive.namelist().count(name) == 1, "missing_or_duplicate_member")
    info = archive.getinfo(name)
    require(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16)
            and info.file_size <= policy["max_member_bytes"], "member_size_or_type")
    require(sum(x["bytes"] for k, x in evidence.items() if k != name) + info.file_size
            <= policy["max_bundle_bytes"], "bundle_size_limit")
    raw = archive.read(info)
    actual = sha(raw)
    require(actual == ref["sha256"], "member_hash_mismatch")
    evidence[name] = {"sha256": actual, "bytes": len(raw)}
    return raw


def _calendar_prices(prices, expected_session, cutoff, now):
    import pandas_market_calendars as mcal
    require(prices.get("basis") == "TOTAL_RETURN_INDEX" and prices.get("currency") == "USD"
            and prices.get("methodology_id") == "distributions_reinvested_v1"
            and prices.get("benchmark_id") == "SPY", "unapproved_return_basis")
    rows = prices["rows"]
    require(isinstance(rows, list) and rows, "prices_missing")
    sessions = [row["session"] for row in rows]
    first = min(sessions)
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", first) is not None, "invalid_price_session")
    require((now.date() - datetime.fromisoformat(first).date()).days <= 5000,
            "price_history_budget")
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(start_date=first, end_date=now.date())
    closed = schedule[schedule["market_close"] <= cutoff - timedelta(minutes=90)]
    require(not closed.empty and str(closed.index[-1].date()) == expected_session,
            "decision_session_mismatch")
    closes = {str(day.date()): close.to_pydatetime() for day, close in
              zip(schedule.index, schedule["market_close"])}
    benchmark = sorted(row["session"] for row in rows if row["security_id"] == "SPY")
    require(benchmark and benchmark[-1] == expected_session, "stale_benchmark")
    require(benchmark == [d for d in closes if benchmark[0] <= d <= expected_session],
            "benchmark_session_gap")
    for row in rows:
        require(row["session"] in closes and row["session"] <= expected_session,
                "nontrading_or_future_session")
        require(closes[row["session"]] <= utc(row["available_at"]) <= cutoff,
                "price_not_available_after_close")
        value = row["total_return_index"]
        require(not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value) and value > 0, "invalid_total_return_index")
    return rows


def _payload(parts, bundle, policy, expected_session, now):
    cutoff = utc(bundle["decision_at"])
    require(cutoff <= now, "future_decision")
    base = parts["base_universe"]
    ids = base["security_ids"]
    require(isinstance(ids, list) and all(isinstance(x, str) and x and x == x.strip().upper()
            for x in ids) and len(ids) == len(set(ids)), "invalid_base_identities")
    require(base.get("scope") == "FULL_BASE_UNIVERSE" and len(ids) >= policy["min_base_count"],
            "partial_base_universe")
    securities = parts["securities"]
    registry = {r["security_id"]: r for r in securities}
    require(len(registry) == len(securities) and set(ids).issubset(registry), "registry_coverage")
    for row in securities:
        require(row.get("issuer_id") and row.get("ticker") and row.get("currency") == "USD"
                and row.get("identity_verified") is True
                and isinstance(row.get("research_eligible"), bool), "security_identity_unverified")
    documents = parts["documents"]
    docs = {d["document_id"]: sha(canonical(d)) for d in documents}
    require(len(docs) == len(documents), "duplicate_document")
    events = parts["membership_events"]
    theme_by_security = {}
    for event in events:
        require(isinstance(event.get("reviewed"), bool), "membership_review_not_boolean")
        require(event["security_id"] in registry, "membership_identity_missing")
        if event["reviewed"]:
            approval = policy["approved_membership_reviews"].get(sha(canonical(event)))
            require(isinstance(approval, dict) and approval.get("decision") == "APPROVED_BUSINESS_RELATIONSHIP"
                    and approval.get("reviewer_id"), "membership_review_not_anchored")
            require(approval.get("reviewed_at") == event.get("reviewed_at"), "membership_review_time_mismatch")
            require(approval.get("document_hashes") and all(docs.get(k) == v for k, v in
                    approval["document_hashes"].items()), "membership_review_evidence_mismatch")
        # V1's resolver keys by security, not (theme, security). Fail closed
        # until that separate lifecycle fix is reviewed; never lose another link.
        theme_by_security.setdefault(event["security_id"], set()).add(event["theme_id"])
    require(all(len(v) == 1 for v in theme_by_security.values()), "multi_theme_lifecycle_not_supported")
    snapshots = parts["etf_snapshots"]
    by_fund = {}
    for snapshot in snapshots:
        require(snapshot.get("schema") != "etf-snapshot-v2", "raw_etf_evidence_required")
        require(snapshot.get("expected_unique_rows") == len(snapshot.get("rows", [])),
                "etf_expected_rows_mismatch")
        for row in snapshot["rows"]:
            require(isinstance(row.get("identity_verified"), bool), "etf_identity_not_boolean")
        by_fund.setdefault(snapshot["fund_id"], []).append(snapshot)
    for rows in by_fund.values():
        ordered = sorted(rows, key=lambda r: utc(r["observed_at"]))
        dates = [r["holdings_as_of"] for r in ordered]
        require(dates == sorted(dates), "late_etf_history_requires_separate_adapter")
    return {"schema": "theme-etf-runtime-v1", "decision_at": bundle["decision_at"],
            "base_universe": ids, "base_universe_available_at": base["available_at"],
            "securities": securities, "prices": _calendar_prices(parts["prices"], expected_session, cutoff, now),
            "benchmark_id": "SPY", "documents": documents, "membership_events": events,
            "etf_snapshots": snapshots}


def read_bundle(path: Path, run: dict, artifact: dict, policy: dict,
                expected_session: str, now: datetime) -> dict:
    """Called only at the existing monitor's authenticated artifact boundary.

    Missing producer support is BLOCKED, never an old-success fallback. Public
    entry points do not accept a user-supplied 'verified' receipt or trust policy.
    """
    try:
        require(run.get("head_branch") == "master"
                and (run.get("head_repository") or {}).get("full_name") == policy["repository"]
                and run.get("path") == policy["producer_workflow"]
                and run.get("event") in {"schedule", "workflow_dispatch"}
                and run.get("status") == "completed" and run.get("conclusion") == "success",
                "untrusted_or_failed_producer")
        require(re.fullmatch(r"[a-f0-9]{40}", run.get("head_sha", "")) is not None
                and type(run.get("id")) is int and type(run.get("run_attempt")) is int,
                "producer_identity_missing")
        require(utc(run["created_at"]) <= now, "future_producer")
        origin = artifact.get("workflow_run") or {}
        require(origin.get("id") == run["id"] and origin.get("head_sha") == run["head_sha"]
                and not artifact.get("expired") and type(artifact.get("id")) is int,
                "artifact_identity_mismatch")
        require(path.stat().st_size <= policy["max_artifact_bytes"], "artifact_size_limit")
        with path.open("rb") as handle:
            archive_hash = hashlib.file_digest(handle, "sha256").hexdigest()
        require(artifact.get("digest") == "sha256:" + archive_hash, "artifact_hash_mismatch")
        evidence = {}
        with zipfile.ZipFile(path) as archive:
            name = policy["bundle_member"].format(run_id=run["id"], run_attempt=run["run_attempt"])
            require(archive.namelist().count(name) == 1, "source_bundle_missing_or_duplicate")
            info = archive.getinfo(name)
            require(info.file_size <= policy["max_member_bytes"], "bundle_manifest_size_limit")
            raw = archive.read(info)
            evidence[name] = {"sha256": sha(raw), "bytes": len(raw)}
            bundle = _json(raw)
            require(bundle.get("schema") == SCHEMA and set(bundle["components"]) == set(ROLES),
                    "bundle_schema_or_components")
            producer = {"repository": policy["repository"], "workflow": run["path"],
                        "head_sha": run["head_sha"], "run_id": run["id"], "run_attempt": run["run_attempt"]}
            require(bundle.get("producer") == producer, "bundle_producer_mismatch")
            parts = {}
            for role in ROLES:
                refs = bundle["components"][role]
                component = _member(archive, refs["data"], policy, evidence)
                receipt = _json(_member(archive, refs["receipt"], policy, evidence))
                require(receipt.get("schema") == "theme-etf-component-receipt-v1"
                        and receipt.get("producer") == producer and receipt.get("role") == role
                        and receipt.get("data_sha256") == sha(component), "component_receipt_mismatch")
                require(receipt.get("status") in {"COLLECTED", "UNCHANGED"}
                        and receipt.get("failures") == [] and receipt.get("research_only") is True,
                        "component_not_usable")
                require(utc(receipt["validated_at"]) <= utc(bundle["decision_at"]), "future_receipt")
                require(receipt.get("raw_objects"), "raw_source_evidence_missing")
                for ref in receipt["raw_objects"]:
                    _member(archive, ref, policy, evidence)
                parts[role] = _json(component)
        payload = _payload(parts, bundle, policy, expected_session, now)
        # Import only after admission. Missing sparse-checkout runtime is a
        # deployment error, never silently substituted with the permissive core.
        from research.theme_etf_runtime_v1.strict import run_payload
        result = run_payload(payload)
        proposal = result["summary"]["universe"]["research_universe_proposal"]
        registry = {r["security_id"]: r for r in parts["securities"]}
        event_map = {e["event_id"]: e for e in parts["membership_events"]}
        # Emit the pending #445 MembershipReason shape; do not introduce another
        # composer or import its unmerged branch as a canonical dependency.
        reasons = []
        for sid, entry in sorted(result["active_memberships"].items()):
            event = event_map[entry["membership_event_id"]]
            reasons.append({"ticker": registry[sid]["ticker"],
                "reason_type": "REVIEWED_THEME_RESEARCH", "source_kind": "THEME",
                "polarity": "CANDIDATE", "status": "ACTIVE",
                "first_seen_at": event["observed_at"], "last_observed_at": event["observed_at"],
                "valid_until": "", "source_event_id": event["event_id"],
                "source_hash": sha(canonical(event)),
                "source_quality": "BUSINESS_REVIEW_PINNED_EVALUATION_PENDING",
                "security_type": "EQUITY", "notes": "theme_id=" + entry["theme_id"]})
        inventory = [{"security_id": sid, "status": "BLOCKED_COMPANY_EVALUATOR_RECEIPT_MISSING",
                      "expected_return_1m": None, "expected_return_3m": None,
                      "expected_return_6m": None, "expected_return_12m": None} for sid in proposal]
        channels = ["price", "fundamentals", "thesis", "valuation", "expected_return"]
        # This is a preview of #451's existing queue schema, not a second queue
        # writer. No price/evaluation completeness is invented for an added ID.
        queue = {"schema_version": "candidate-data-queue-v1", "as_of": bundle["decision_at"],
                 "items": [{"security_id": sid, "ticker": registry[sid]["ticker"],
                    "state": "DATA_PENDING", "membership_reasons": [r for r in reasons
                        if r["ticker"] == registry[sid]["ticker"]],
                    "required_channels": channels,
                    "channel_status": {c: "CONSUMER_RECEIPT_MISSING" for c in channels},
                    "next_action": "VERIFY_COMPANY_INPUTS_THEN_RUN_EXISTING_EVALUATOR",
                    "first_seen_at": registry[sid]["available_at"],
                    "last_checked_at": bundle["decision_at"]} for sid in proposal]}
        return {"schema": SCHEMA, "status": "ADMITTED_RESEARCH_ONLY", "reason": None,
                "expected_session": expected_session, "decision_at": bundle["decision_at"],
                "runtime_executed": True, "company_evaluator_executed": False,
                "end_to_end_ready": False, "producer": producer,
                "artifact_id": artifact["id"], "artifact_sha256": archive_hash,
                "input_sha256": sha(canonical(payload)), "evidence": evidence,
                "result": result, "membership_reasons": reasons,
                "membership_policy": {"score_bonus": 0.0, "eligible_for_selector": False},
                "data_queue_preview": queue,
                "evaluation_inventory": inventory, "safety": dict(SAFETY)}
    except (AdmissionError, ValueError, KeyError, TypeError, AttributeError, OverflowError,
            OSError, zipfile.BadZipFile) as exc:
        # No external text, filesystem paths or signed URLs in diagnostics.
        reason = str(exc) if isinstance(exc, AdmissionError) else "invalid_source_bundle"
        return blocked(reason, expected_session)


def observation(source, session):
    bridge = source.get("data", {}).get("theme_etf_bridge")
    if source.get("status") != "VERIFIED_ARTIFACT":
        return blocked("upstream_not_verified", session)
    if not bridge:
        return blocked("source_bundle_not_published", session)
    # Keep the full evidence/identities in the internal source object; reporting
    # exposes only explicit nonranking readiness and coverage fields.
    fields = ("schema", "status", "reason", "expected_session", "decision_at",
              "runtime_executed", "company_evaluator_executed", "end_to_end_ready", "safety")
    out = {key: bridge.get(key) for key in fields}
    if bridge.get("expected_session") != session:
        return blocked("stale_source_bundle", session)
    out["requested_security_count"] = len(bridge.get("evaluation_inventory", []))
    out["evaluated_security_count"] = 0
    out["evaluation_blocked_count"] = out["requested_security_count"]
    return out
