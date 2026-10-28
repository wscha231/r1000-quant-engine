"""Persist SEC research requests through existing A2, Registry and A3 interfaces.

No collector, scheduler, source admission, current A3 pointer or financial write.
The existing agent-board research root stores immutable artifacts and one atomic
Registry request manifest. Its successful readback proves local research storage.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys
import subprocess
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research import a2_research_intake_v1 as intake
from research import a3_candidate_packet_v1 as a3
from research import candidate_registry_v1 as registry
from tools import candidate_reassessment_bridge as bridge
from tools.run_form4_transaction_event_builder import build_ownership_research_events
from tools.run_sec_form4_parser import parse_form4_xml


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def actual_utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    # The caller owns an exclusive store lock; abandoned temporary bytes are not
    # an accepted manifest and may be replaced by the next owner.
    with temporary.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def put(root, value, *, raw=False):
    blob = value if raw else encoded(value)
    sha = digest(blob)
    path = root / "artifacts" / sha
    if path.exists():
        need(path.read_bytes() == blob, "IMMUTABLE_ARTIFACT_CONFLICT")
    else:
        atomic(path, blob)
    return {"path": "artifacts/" + sha, "sha256": sha}


def read_ref(root, ref):
    need(type(ref) is dict and set(ref) == {"path", "sha256"}, "REFERENCE_SHAPE")
    path = root / ref["path"]
    need(path.resolve().is_relative_to(root.resolve()) and not path.is_symlink(), "REFERENCE_SCOPE")
    raw = path.read_bytes()
    need(digest(raw) == ref["sha256"], "STORED_HASH_CONFLICT")
    return raw


def verify_store(root, state):
    """Read every committed request's actual bytes, including original SEC XML."""
    need(state.get("schema") == "sec-research-request-store-v1" and type(state.get("requests")) is dict,
         "REGISTRY_STORE_SCHEMA")
    for request in state["requests"].values():
        record = json.loads(read_ref(root, request["registry_ref"]))
        need(record["request_id"] == request["request_id"], "REGISTRY_REQUEST_ID")
        read_ref(root, record["a2_intake_ref"])
        receipt = json.loads(read_ref(root, request["source_receipt_ref"]))
        source_state(receipt, request.get("decision_at", request["created_at"]), historical_readback=True)
        events = [json.loads(read_ref(root, ref)) for ref in record["event_refs"]]
        need(digest(encoded(events)) == request["events_sha256"], "STORED_EVENT_SET")
        for event in events:
            need(event["event_id"] in receipt["event_scope"], "STORED_SOURCE_SCOPE")
        a2 = json.loads(read_ref(root, record["a2_intake_ref"]))
        need([e["event_id"] for e in a2["input"]["events"]] == [e["event_id"] for e in events], "STORED_A2_EVENT_SET")
        a3_refs = [json.loads(read_ref(root, ref)) for ref in record["a3_filing_review_refs"]]
        need([r["event_id"] for r in a3_refs] == [e["event_id"] for e in events], "STORED_A3_EVENT_SET")
        need(all(r["source_receipt_sha256"] == request["source_receipt_ref"]["sha256"] and
                 r["asset_id"] == record["asset_id"] and r["issuer_id"] == record["issuer_id"] for r in a3_refs), "STORED_A3_SOURCE_BINDING")
        need([r["raw_sha256"] for r in a3_refs] == [r["sha256"] for r in request["raw_refs"]], "STORED_RAW_LINKS")
        for ref in record["event_refs"] + record["a3_filing_review_refs"] + request["raw_refs"]:
            read_ref(root, ref)
        if record["existing_thesis_ref"]:
            read_ref(root, record["existing_thesis_ref"])
        read_ref(root, request["bridge_ref"])
    corrections = state.get("clock_corrections", {})
    need(type(corrections) is dict and corrections.keys() <= state["requests"].keys(), "CLOCK_CORRECTION_INDEX")
    for request_id, ref in corrections.items():
        correction = json.loads(read_ref(root, ref))
        need(correction.get("schema") == "sec-research-clock-correction-v1"
             and correction.get("request_id") == request_id, "CLOCK_CORRECTION_SCHEMA")
        original = state["requests"][request_id]
        need(correction["original_request_sha256"] == digest(encoded(original)), "CLOCK_CORRECTION_PARENT")
        corrected = correction["corrected_request"]
        need(corrected["request_id"] == request_id and corrected["notification_intent_id"] == original["notification_intent_id"]
             and corrected["original_accession"] == original["original_accession"], "CLOCK_CORRECTION_REQUEST_IDENTITY")
        verify_store(root, dict(schema="sec-research-request-store-v1", requests={request_id: corrected}))
        before_record = json.loads(read_ref(root, original["registry_ref"]))
        after_record = json.loads(read_ref(root, corrected["registry_ref"]))
        need(before_record["asset_id"] == after_record["asset_id"]
             and before_record["issuer_id"] == after_record["issuer_id"]
             and before_record["existing_thesis_ref"] == after_record["existing_thesis_ref"], "CLOCK_CORRECTION_SUBJECT")
        before = [json.loads(read_ref(root, r)) for r in before_record["event_refs"]]
        after = [json.loads(read_ref(root, r)) for r in after_record["event_refs"]]
        receipt = json.loads(read_ref(root, corrected["source_receipt_ref"]))
        proof = verify_clock_change(before, after, receipt,
            read_ref(root, correction["old_submissions_ref"]), read_ref(root, correction["current_submissions_ref"]))
        need(correction["proof"] == proof and correction["reason"] == "SOURCE_ACCEPTANCE_CLOCK_RECONCILIATION",
             "CLOCK_CORRECTION_PROOF")
    return state


def readback(root):
    root = Path(root)
    path = root / "control_plane/candidate_registry/filing_requests.json"
    state = json.loads(path.read_bytes()) if path.exists() else {"schema": "sec-research-request-store-v1", "requests": {}}
    return verify_store(root, state)


def schema_inventory():
    values = {}
    for name, sha in intake.SCHEMAS.values():
        raw = (ROOT / "research/control_plane" / name).read_bytes()
        # Git LF schema identity is pinned by the existing intake. This is schema
        # checkout normalization only, never normalization of evidence bytes.
        if digest(raw) != sha:
            raw = raw.replace(b"\r\n", b"\n")
        need(digest(raw) == sha, "PINNED_SCHEMA_BYTES")
        values["SCHEMA:" + name] = raw
    return intake.MemoryArtifacts(values)


def source_state(receipt, decision_at, *, historical_readback=False):
    decision = bridge.stamp(decision_at)
    need(receipt.get("schema") == "sec-research-consumption-source-v1", "SOURCE_RECEIPT_SCHEMA")
    if receipt.get("status") == "PREREQUISITE_FAILED":
        return "PREREQUISITE_FAILED"
    if receipt.get("status") == "SOURCE_UNAVAILABLE":
        return "SOURCE_UNAVAILABLE"
    if receipt.get("status") not in {"CHECKED_NEW_OR_EXISTING", "CHECKED_NO_NEW"}:
        return "SOURCE_UNAVAILABLE"
    manifest = None
    original = receipt.get("original_manifest_utf8")
    if original is not None:
        need(type(original) is str and digest(original.encode("utf-8")) == receipt.get("original_manifest_sha256"),
             "ORIGINAL_SOURCE_MANIFEST_HASH")
        manifest = json.loads(original)
        need(manifest.get("status") == "completed" and manifest.get("schema_version") == "sec-form4-merge-shards-v2",
             "ORIGINAL_SOURCE_MANIFEST_STATUS")
        for derived, original_name in (("generation_id", "generation_id"), ("generated_at", "generated_at_utc"),
            ("last_successful_source_check", "last_successful_source_check"), ("latest_accepted_at", "latest_accepted_at"),
            ("source_coverage", "source_coverage"), ("current_eligible", "current_eligible")):
            need(receipt.get(derived) == manifest.get(original_name), "ORIGINAL_SOURCE_RECEIPT_BINDING")
        need(len(receipt.get("event_scope", {})) == manifest["current_source_transaction_rows"], "ORIGINAL_SOURCE_SCOPE_COUNT")
        for member in receipt["event_scope"].values():
            key = ":".join(member[k] for k in ("issuer_cik10", "accession", "form_type"))
            need(key in manifest["current_source_keys"], "ORIGINAL_SOURCE_SCOPE_MEMBER")
    else:
        need(receipt.get("source_scope") == "SYNTHETIC_CONTRACT_FIXTURE", "ORIGINAL_SOURCE_MANIFEST_REQUIRED")
    checked = bridge.stamp(receipt["last_successful_source_check"])
    generated = bridge.stamp(receipt["generated_at"])
    latest_raw = receipt.get("latest_accepted_at")
    latest = bridge.stamp(latest_raw) if latest_raw is not None else None
    need(checked <= generated <= decision, "SOURCE_CLOCK_ORDER")
    if manifest is not None and ("source_checks" in manifest or "source_filings" in manifest):
        verify_issuer_clocks(manifest, checked, generated, latest, receipt["event_scope"])
    elif manifest is not None and not historical_readback:
        need(False, "SOURCE_ISSUER_PROOF_REQUIRED")
    else:
        # Legacy committed requests retain their original conservative proof for
        # historical readback only. They cannot pass new current-generation intake.
        need(latest is not None and latest <= checked, "SOURCE_CLOCK_ORDER")
    need(latest is not None or receipt["status"] == "CHECKED_NO_NEW", "SOURCE_LATEST_ACCEPTANCE_REQUIRED")
    if decision >= checked + timedelta(hours=36):
        return "STALE"
    if receipt.get("current_eligible") is not True or receipt.get("source_coverage", {}).get("complete") is not True:
        return "SOURCE_UNAVAILABLE"
    return receipt["status"]


def verify_issuer_clocks(manifest, checked, generated, latest, event_scope):
    """Bind every indexed filing to its own checked issuer, keeping min freshness."""
    checks, filings = manifest.get("source_checks"), manifest.get("source_filings")
    coverage = manifest.get("source_coverage", {})
    need(type(checks) is list and bool(checks) and type(filings) is list,
         "SOURCE_ISSUER_PROOF_REQUIRED")
    need(len(checks) == coverage.get("requested") == coverage.get("checked"), "SOURCE_ISSUER_PROOF_COVERAGE")
    by_issuer = {}
    for row in checks:
        need(type(row) is dict and str(row.get("status", "")).startswith("CHECKED_"), "SOURCE_ISSUER_CHECK_REQUIRED")
        key = (row.get("cik10"), row.get("ticker"))
        need(isinstance(key[0], str) and len(key[0]) == 10 and key[0].isdigit()
             and isinstance(key[1], str) and bool(key[1]) and key not in by_issuer,
             "SOURCE_ISSUER_PROOF_IDENTITY")
        stamp = bridge.stamp(row["checked_at"])
        need(stamp <= generated, "SOURCE_ISSUER_CHECK_FUTURE")
        by_issuer[key] = stamp
    need(min(by_issuer.values()) == checked, "SOURCE_CHECK_MINIMUM_CONFLICT")
    accepted_values, indexed = [], {}
    for row in filings:
        need(type(row) is dict, "SOURCE_FILING_PROOF_REQUIRED")
        issuer = (row.get("issuer_cik10"), row.get("ticker"))
        need(issuer in by_issuer, "SOURCE_CORRESPONDING_ISSUER_CHECK_REQUIRED")
        accepted, available = bridge.stamp(row["accepted_at"]), bridge.stamp(row["available_at"])
        need(accepted <= by_issuer[issuer] and accepted <= available, "SOURCE_ISSUER_ACCEPTANCE_ORDER")
        key = ":".join([row["issuer_cik10"], row["accession"], row["form_type"]])
        need(key not in indexed, "SOURCE_FILING_PROOF_DUPLICATE")
        if key in manifest["current_source_keys"]:
            need(available <= generated, "SOURCE_CURRENT_AVAILABILITY_ORDER")
        indexed[key] = row
        accepted_values.append(accepted)
    need((max(accepted_values) if accepted_values else None) == latest, "SOURCE_LATEST_ACCEPTANCE_CONFLICT")
    need(set(manifest["current_source_keys"]).issubset(indexed), "SOURCE_CURRENT_FILING_PROOF_REQUIRED")
    for member in event_scope.values():
        key = ":".join(member[name] for name in ("issuer_cik10", "accession", "form_type"))
        proof = indexed.get(key)
        need(proof is not None and member.get("ticker") == proof["ticker"], "SOURCE_EVENT_ISSUER_BINDING")
        need(all(member.get(field) is not None and bridge.stamp(member[field]) == bridge.stamp(proof[field])
                 for field in ("accepted_at", "available_at")), "SOURCE_EVENT_CLOCK_BINDING")


def verify_ownership_generation(pit_root, *, decision_at):
    """Verify original generation, both physical formats and parser row counts."""
    import pandas as pd
    root = Path(pit_root)
    raw = (root / "sec_form4_merge_manifest.json").read_bytes()
    manifest = json.loads(raw)
    need(manifest.get("schema_version") == "sec-form4-merge-shards-v2" and
         manifest.get("status") == "completed", "SOURCE_GENERATION_NOT_COMPLETED")
    for name in ("form4_transactions", "sec_filings_index"):
        for suffix in ("csv", "parquet"):
            path = root / (name + "." + suffix)
            need(digest(path.read_bytes()) == manifest["output_sha256"][path.name], "SOURCE_FORMAT_HASH")
        parquet = pd.read_parquet(root / (name + ".parquet"))
        csv = pd.read_csv(root / (name + ".csv"), low_memory=False)
        summary = json.loads((root / (name + "_summary.json")).read_bytes())
        need(len(parquet) == len(csv) == summary["row_count"], "SOURCE_FORMAT_ROW_COUNT")
        need(summary["generation_id"] == manifest["generation_id"], "SOURCE_GENERATION_MISMATCH")
    frame = pd.read_parquet(root / "form4_transactions.parquet")
    need(len(frame) == manifest["transaction_rows"], "SOURCE_TRANSACTION_COUNT")
    receipt = dict(schema="sec-research-consumption-source-v1", original_manifest_sha256=digest(raw),
        original_manifest_utf8=raw.decode("utf-8"),
        generation_id=manifest["generation_id"],
        status="CHECKED_NEW_OR_EXISTING" if manifest["current_source_transaction_rows"] else "CHECKED_NO_NEW",
        generated_at=manifest["generated_at_utc"],
        last_successful_source_check=manifest["last_successful_source_check"],
        latest_accepted_at=manifest["latest_accepted_at"], source_coverage=manifest["source_coverage"],
        current_eligible=manifest["current_eligible"], original_decision_at=manifest["decision_at"],
        physical_output_sha256=manifest["output_sha256"],
        scope="CHECKED_BATCH_ONLY_NOT_WHOLE_UNIVERSE")
    keys = manifest["current_source_keys"]
    current = (frame.apply(lambda r: ":".join([str(r["issuer_cik10"]), str(r["accession_number"]), str(r["form_type"])]), axis=1).isin(keys)
               if not frame.empty else __import__("pandas").Series(False, index=frame.index, dtype=bool))
    need(int(current.sum()) == manifest["current_source_transaction_rows"], "SOURCE_CURRENT_SCOPE_COUNT")
    receipt["event_scope"] = {event["event_id"]: dict(document_sha256=event["document_sha256"],
        issuer_cik10=event["issuer_cik10"], accession=event["accession"], form_type=event["form_type"],
        ticker=event["ticker"], accepted_at=event["accepted_at"], available_at=event["available_at"])
        for event in build_ownership_research_events(frame[current])}
    source_state(receipt, decision_at)
    return receipt, frame[current].copy()


def same_semantics(left, right):
    """Exact JSON semantics, allowing only finite int/float representation changes."""
    if type(left) is dict and type(right) is dict:
        return left.keys() == right.keys() and all(same_semantics(left[k], right[k]) for k in left)
    if type(left) is list and type(right) is list:
        return len(left) == len(right) and all(same_semantics(a, b) for a, b in zip(left, right))
    if type(left) in (int, float) and type(right) in (int, float):
        return (left == right and (type(left) is int or math.isfinite(left))
                and (type(right) is int or math.isfinite(right)))
    return type(left) is type(right) and left == right


def verify_clock_change(before, after, receipt, old_raw, current_raw):
    """Only explicit, source-bound acceptance/availability clock derivation.

    Raw physical hashes and the collector's canonical JSON content hash are
    deliberately different identities. No fixed DST offset is inferred.
    """
    need(bool(before) and len(before) == len(after), "CLOCK_CORRECTION_EVENT_COUNT")
    before = sorted(before, key=lambda e: e["event_id"])
    after = sorted(after, key=lambda e: e["event_id"])
    need(len({e["event_id"] for e in before}) == len(before)
         and [e["event_id"] for e in before] == [e["event_id"] for e in after], "CLOCK_CORRECTION_EVENT_SET")
    need(all(e["family"] == "OWNERSHIP" and not e["is_amendment"] for e in before + after),
         "CLOCK_CORRECTION_NON_AMENDMENT_ONLY")
    accession, issuer, ticker = before[0]["accession"], before[0]["issuer_cik10"], before[0]["ticker"]
    need(all((e["accession"], e["issuer_cik10"], e["ticker"]) == (accession, issuer, ticker)
             for e in before + after), "CLOCK_CORRECTION_ONE_FILING")
    from tools.run_sec_submissions_collector import validate_submissions
    payloads, entries = [], []
    for raw in (old_raw, current_raw):
        need(type(raw) is bytes and len(raw) <= 2 * 1024 * 1024, "CLOCK_CORRECTION_SUBMISSIONS_BUDGET")
        value = json.loads(raw)
        validate_submissions(value, issuer)
        need(str(value.get("cik", "")).zfill(10) == issuer, "CLOCK_CORRECTION_SUBMISSIONS_ISSUER")
        recent = value["filings"]["recent"]
        matches = [i for i, a in enumerate(recent["accessionNumber"]) if a == accession]
        need(len(matches) == 1, "CLOCK_CORRECTION_SUBMISSIONS_ACCESSION")
        i = matches[0]
        entries.append({k: recent[k][i] for k in
            ("accessionNumber", "form", "filingDate", "primaryDocument", "acceptanceDateTime")})
        payloads.append(value)
    need({k: v for k, v in entries[0].items() if k != "acceptanceDateTime"}
         == {k: v for k, v in entries[1].items() if k != "acceptanceDateTime"}, "CLOCK_CORRECTION_FILING_IDENTITY")
    manifest = json.loads(receipt.get("original_manifest_utf8", "{}"))
    checks = [c for c in manifest.get("source_checks", []) if c.get("cik10") == issuer and c.get("ticker") == ticker]
    need(len(checks) == 1 and checks[0].get("payload_sha256") == digest(encoded(payloads[1])),
         "CLOCK_CORRECTION_CURRENT_PAYLOAD_BINDING")
    changed = False
    deltas = []
    for old, new in zip(before, after):
        for event, entry in ((old, entries[0]), (new, entries[1])):
            need(event["form_type"] == entry["form"] and event["source_row"]["filing_date"] == entry["filingDate"],
                 "CLOCK_CORRECTION_EVENT_FILING")
            need(bridge.stamp(event["accepted_at"]) == bridge.stamp(entry["acceptanceDateTime"])
                 == bridge.stamp(event["source_row"]["accepted_at"]), "CLOCK_CORRECTION_ACCEPTANCE_BINDING")
            need(bridge.stamp(event["available_at"]) == bridge.stamp(event["source_row"]["available_from"]),
                 "CLOCK_CORRECTION_AVAILABILITY_BINDING")
        old_delay = bridge.stamp(old["available_at"]) - bridge.stamp(old["accepted_at"])
        new_delay = bridge.stamp(new["available_at"]) - bridge.stamp(new["accepted_at"])
        need(old_delay == new_delay and old_delay >= timedelta(0), "CLOCK_CORRECTION_SAFETY_DELAY")
        def without_clocks(e):
            value = json.loads(encoded(e))
            for field in ("accepted_at", "available_at"):
                del value[field]
            for field in ("accepted_at", "available_from"):
                del value["source_row"][field]
            return value
        need(same_semantics(without_clocks(old), without_clocks(new)), "CLOCK_CORRECTION_NONCLOCK_CONFLICT")
        delta = (bridge.stamp(new["accepted_at"]) - bridge.stamp(old["accepted_at"])).total_seconds()
        changed |= delta != 0
        deltas.append(dict(event_id=old["event_id"], before_accepted_at=old["accepted_at"],
            after_accepted_at=new["accepted_at"], before_available_at=old["available_at"],
            after_available_at=new["available_at"], delta_seconds=delta))
    need(changed, "CLOCK_CORRECTION_NO_CHANGE")
    return dict(old_physical_sha256=digest(old_raw), current_physical_sha256=digest(current_raw),
        current_collector_content_sha256=digest(encoded(payloads[1])), events=deltas,
        upstream_cause="UNKNOWN", historical_pit_certified=False, automatic_investment_authority=False)


def effective_request(root, state, request_id):
    """Derived view of a state returned by readback; original bytes stay intact."""
    ref = state.get("clock_corrections", {}).get(request_id)
    return (json.loads(read_ref(root, ref))["corrected_request"] if ref else state["requests"].get(request_id))


def verify_ownership_event(event, raw):
    row = event["source_row"]
    need(digest(raw) == event["document_sha256"], "RAW_DOCUMENT_HASH")
    filing = dict(cik10=event["issuer_cik10"], ticker=event["ticker"],
        accession_number=event["accession"], form_type=event["form_type"],
        accepted_at=event["accepted_at"], available_from=event["available_at"],
        filing_date=row.get("filing_date"), filing_url=row.get("filing_url"))
    rebuilt = build_ownership_research_events(__import__("pandas").DataFrame(
        parse_form4_xml(raw.decode("utf-8"), event["accession"], filing)))
    match = next((r for r in rebuilt if r["event_id"] == event["event_id"]), None)
    need(match is not None, "RAW_EVENT_IDENTITY")
    # Only the collector's optional _source_file decoration is outside XML semantics.
    expected = {k: v for k, v in row.items() if k != "_source_file"}
    need(same_semantics(match["source_row"], expected), "RAW_EVENT_SEMANTICS")


def consume(events, *, receipt, raw_by_hash, identities, output_root, decision_at,
            existing_theses=None, amendment_parents=None, clock_correction=None):
    """One serial local research transaction; manifest commits last after readback.

    A request is one accession/security, even with multiple transaction rows.
    Replaying a filing through another generation cannot duplicate it or alert.
    No alert delivery is implemented; stable notification intents are recorded.
    """
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "control_plane/candidate_registry/.writer.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("x") as stream:
        stream.write("SEC_RESEARCH_SINGLE_WRITER")
    current_path = root / "control_plane/candidate_registry/consumption_attempt.json"
    try:
        generated_at = actual_utc_now()
        atomic(current_path, encoded(dict(status="BUILDING", generated_at=generated_at, decision_at=decision_at, current_eligible=False)))
        need(bridge.stamp(decision_at) <= bridge.stamp(generated_at), "FUTURE_DECISION")
        state = readback(root)
        status = source_state(receipt, decision_at)
        # Preserve decision-relative provenance checks above. Current intake must
        # also age the unchanged Source check against captured execution UTC;
        # historical stored readback remains a separate, non-admitting path.
        if status in {"CHECKED_NEW_OR_EXISTING", "CHECKED_NO_NEW"}:
            status = source_state(receipt, generated_at)
        attempt = dict(schema="sec-research-consumption-attempt-v1", status=status,
            decision_at=decision_at, generated_at=generated_at, source_status=status,
            last_successful_source_check=receipt.get("last_successful_source_check"),
            latest_accepted_at=receipt.get("latest_accepted_at"), source_coverage=receipt.get("source_coverage"),
            current_eligible=status in {"CHECKED_NEW_OR_EXISTING", "CHECKED_NO_NEW"},
            created_requests=[], replayed_requests=[], corrected_requests=[], notification_intents_created=0,
            notifications_sent=0, selector_eligible=False, orders_allowed=False, research_only=True)
        if status in {"STALE", "SOURCE_UNAVAILABLE", "PREREQUISITE_FAILED"}:
            attempt["reason"] = {"STALE": "SOURCE_CHECK_EXPIRED", "SOURCE_UNAVAILABLE": "SOURCE_CHECK_OR_COVERAGE_FAILED",
                                 "PREREQUISITE_FAILED": "CONSUMER_PREREQUISITE_FAILED"}[status]
            atomic(current_path, encoded(attempt))
            return attempt
        if status == "CHECKED_NO_NEW":
            need(not events, "NO_NEW_STATUS_WITH_EVENTS")
            attempt["stored_requests"] = len(state["requests"])
            atomic(current_path, encoded(attempt))
            return attempt
        subjects = json.loads(identities)["rows"]
        thesis = existing_theses or {}
        parents = amendment_parents or {}
        grouped = {}
        for event in events:
            member = receipt.get("event_scope", {}).get(event["event_id"])
            expected_scope = dict(document_sha256=event["document_sha256"], issuer_cik10=event["issuer_cik10"],
                accession=event["accession"], form_type=event["form_type"])
            if isinstance(member, dict) and "accepted_at" in member:
                expected_scope.update(ticker=event["ticker"], accepted_at=event["accepted_at"], available_at=event["available_at"])
            need(member == expected_scope, "EVENT_OUTSIDE_CHECKED_SOURCE_SCOPE")
            matches = [s for s in subjects if event.get("ticker") in s["tickers"] and
                       s["issuer_id"] == "CIK:" + str(event["issuer_cik10"])]
            need(len(matches) == 1, "EXACT_SECURITY_MAPPING_REQUIRED")
            subject = matches[0]
            grouped.setdefault((event["accession"], subject["security_id"]), []).append(event)
        receipt_ref = put(root, receipt)
        if clock_correction is not None:
            need(len(grouped) == 1 and set(clock_correction) ==
                 {"expected_original_request_sha256", "old_submissions", "current_submissions"}, "CLOCK_CORRECTION_EXPLICIT_SCOPE")
        memory = schema_inventory()
        for (accession, sid), rows in sorted(grouped.items()):
            rows.sort(key=lambda r: r["event_id"])
            need(len({r["event_id"] for r in rows}) == len(rows), "DUPLICATE_EVENT_IN_REQUEST")
            subject = next(s for s in subjects if s["security_id"] == sid)
            request_id = "SEC_REQUEST:" + digest(encoded([accession, sid]))
            immutable = digest(encoded(rows))
            is_amendment = any(r["is_amendment"] for r in rows)
            need(accession not in parents or is_amendment, "PARENT_FOR_NON_AMENDMENT")
            original_request = state["requests"].get(request_id)
            old = effective_request(root, state, request_id)
            correction_proof = None
            correcting = False
            if clock_correction is not None:
                need(original_request is not None and clock_correction["expected_original_request_sha256"] ==
                     digest(encoded(original_request)), "CLOCK_CORRECTION_EXPECTED_PARENT")
                original_record = json.loads(read_ref(root, original_request["registry_ref"]))
                original_events = [json.loads(read_ref(root, ref)) for ref in original_record["event_refs"]]
                correction_proof = verify_clock_change(original_events, rows, receipt,
                    clock_correction["old_submissions"], clock_correction["current_submissions"])
            if old:
                if old["events_sha256"] != immutable:
                    old_record = json.loads(read_ref(root, old["registry_ref"]))
                    old_events = [json.loads(read_ref(root, ref)) for ref in old_record["event_refs"]]
                    if not same_semantics(old_events, rows):
                        need(correction_proof is not None and request_id not in state.get("clock_corrections", {}),
                             "CONFLICTING_ACCESSION_SECURITY_EVENTS")
                        correcting = True
                need(not is_amendment or parents.get(accession) in (None, old["original_accession"]),
                     "AMENDMENT_REPLAY_LINEAGE_CONFLICT")
            original = old["original_accession"] if old and is_amendment else parents.get(accession)
            parent_id = "SEC_REQUEST:" + digest(encoded([original, sid])) if original else None
            if is_amendment:
                need(original and parent_id in state["requests"], "AMENDMENT_LINEAGE_REQUIRED")
                parent_record = json.loads(read_ref(root, state["requests"][parent_id]["registry_ref"]))
                parent_event = json.loads(read_ref(root, parent_record["event_refs"][0]))
                need(all(r.get("original_submission_date") == parent_event["source_row"].get("filing_date")
                         for r in rows), "AMENDMENT_ORIGINAL_DATE_CONFLICT")
                need(all(r["form_type"].removesuffix("/A") == parent_event["form_type"].removesuffix("/A")
                         for r in rows), "AMENDMENT_ORIGINAL_FORM_CONFLICT")
            if old and not correcting:
                attempt["replayed_requests"].append(request_id)
                continue
            if correcting:
                # Preserve the supplied, previously verified thesis relationship.
                prior_thesis = json.loads(read_ref(root, original_request["registry_ref"]))["existing_thesis_ref"]
                need(sid not in thesis or thesis[sid] == prior_thesis, "CLOCK_CORRECTION_THESIS_CONFLICT")
                if prior_thesis:
                    thesis = dict(thesis)
                    thesis[sid] = prior_thesis
            if sid in thesis:
                linked = json.loads(read_ref(root, thesis[sid]))
                need(linked.get("schema") in {"a3-candidate-packet-v1", "candidate-registry-filing-request-v1"}
                     and linked.get("asset_id") == sid and linked.get("issuer_id") == subject["issuer_id"],
                     "EXISTING_THESIS_SUBJECT_OR_SCHEMA_CONFLICT")
            a2_rows, event_refs, a3_refs, raw_refs, observations = [], [], [], [], []
            for event in rows:
                need(event["family"] == "OWNERSHIP", "13F_AUTHENTICATED_ADAPTER_NOT_YET_AVAILABLE")
                raw = raw_by_hash[event["document_sha256"]]
                verify_ownership_event(event, raw)
                accepted, available = bridge.stamp(event["accepted_at"]), bridge.stamp(event["available_at"])
                collected = bridge.stamp(receipt["generated_at"])
                need(accepted <= available <= collected, "FILING_CLOCK_ORDER")
                event_refs.append(put(root, event))
                raw_refs.append(put(root, raw, raw=True))
                a3_refs.append(put(root, a3.filing_review_reference(event, security_id=sid,
                    issuer_id=subject["issuer_id"], raw=raw, source_receipt_sha256=receipt_ref["sha256"])))
                expiry = (bridge.stamp(receipt["last_successful_source_check"]) + timedelta(hours=36)).isoformat()
                claim = "SEC acceptance proxy; " + event["event_type"] + "; content review only; venue/trade unverified"
                a2_rows.append(dict(event_id=event["event_id"], cohort_id="SEC:" + accession,
                    event_family="FILING", observed_at=receipt["generated_at"], published_at=event["accepted_at"],
                    available_at=event["available_at"], collected_at=receipt["generated_at"], expires_at=expiry,
                    source_graph_artifact_id=None, source_graph_sha256=None, primary_source="SEC_FILING",
                    verification_level="V0", claim=claim, verified_fact=None,
                    issuer_ids=[subject["issuer_id"]], security_ids=[sid], tickers=[event["ticker"]], asset_ids=[sid],
                    themes=[], industry_ids=[], underlyings=[], transmission_channel="FILING_CONTENT_REVIEW",
                    affected_pillars=["earnings_revision_operating_acceleration", "valuation_margin_of_safety"],
                    horizon="1M", materiality="LOW", invalidation="Review actual disclosure and existing thesis",
                    state="WATCH" if sid in thesis or parent_id else "DISCOVERED", assessment_eligible=False,
                    score_contribution=0, requires_a3_refresh=True, authority=intake.closed()))
                observations.append(dict(family="FILING", provider="SEC", entity_kind="SECURITY", entity_id=sid,
                    metric="FILING:" + event["event_id"], fiscal_period=None,
                    observation_period=accepted.date().isoformat(), identity={"accession": accession},
                    values={"event_type": event["event_type"], "source_observed_at": receipt["generated_at"]},
                    status="OBSERVED", available_at=event["available_at"], collected_at=receipt["generated_at"],
                    revision_id=accession, source_sha256=event["document_sha256"], causal_event_id=event["event_id"]))
            envelope = dict(schema_version="a2-event-handoff-v1", as_of=decision_at, events=a2_rows,
                            research_only=True, authority=intake.closed())
            a2 = intake.validate_events(encoded(envelope), cutoff=decision_at, artifact_resolver=memory, identities=identities)
            a2_ref = put(root, dict(input=envelope, result=a2))
            snapshot = bridge.snapshot(observations, scope_id=request_id, cutoff=decision_at, expires_at=expiry)
            index = bridge.exposure_index(candidates=[dict(asset_id=sid, issuer_id=subject["issuer_id"])],
                edges=[], available_at=decision_at, expires_at=expiry)
            identity = dict(code_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
                config_sha256=digest(encoded({"source_max_age_hours": 36, "research_only": True})),
                model_version="RESEARCH_ONLY", parameters_sha256=digest(encoded(envelope)),
                dependency_sha256=digest(encoded({str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in
                    (Path(__file__), ROOT / "tools/candidate_reassessment_bridge.py", Path(intake.__file__),
                     Path(a3.__file__), Path(registry.__file__))})))
            plan = bridge.plan_reassessment(None, snapshot, index, now=decision_at, contract_identity=identity)
            record = registry.filing_request_record(request_id=request_id, asset_id=sid, issuer_id=subject["issuer_id"],
                event_refs=event_refs, intake_ref=a2_ref, a3_filing_refs=a3_refs,
                existing_thesis_ref=thesis.get(sid), supersedes_request_id=parent_id)
            built_request = dict(request_id=request_id, events_sha256=immutable,
                registry_ref=put(root, record), bridge_ref=put(root, plan), raw_refs=raw_refs,
                source_receipt_ref=receipt_ref, notification_intent_id=request_id,
                original_accession=original, decision_at=decision_at, created_at=actual_utc_now())
            if correcting:
                correction = dict(schema="sec-research-clock-correction-v1", request_id=request_id,
                    reason="SOURCE_ACCEPTANCE_CLOCK_RECONCILIATION",
                    original_request_sha256=digest(encoded(original_request)), corrected_request=built_request,
                    old_submissions_ref=put(root, clock_correction["old_submissions"], raw=True),
                    current_submissions_ref=put(root, clock_correction["current_submissions"], raw=True), proof=correction_proof)
                state.setdefault("clock_corrections", {})[request_id] = put(root, correction)
                attempt["corrected_requests"].append(request_id)
            else:
                state["requests"][request_id] = built_request
                attempt["created_requests"].append(request_id)
        # Verify every pending artifact before the single manifest commit.
        verify_store(root, state)
        atomic(root / "control_plane/candidate_registry/filing_requests.json", encoded(state))
        verified = readback(root)
        attempt.update(status="COMPLETED_RESEARCH_STORAGE", stored_requests=len(verified["requests"]),
            registry_manifest_sha256=digest(encoded(verified)),
            notification_intents_created=len(attempt["created_requests"]),
            registry_current_admission=False, a3_assessment_complete=False)
        atomic(current_path, encoded(attempt))
        return attempt
    except Exception:
        atomic(current_path, encoded(dict(schema="sec-research-consumption-attempt-v1",
            status="FAILED_VALIDATION_OR_STORAGE", generated_at=actual_utc_now(), decision_at=decision_at, current_eligible=False,
            new_signals=0, research_only=True, orders_allowed=False)))
        raise
    finally:
        lock.unlink()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pit-root", required=True)
    parser.add_argument("--raw-dir", required=True, help="Existing Form345 XML cache; read only")
    parser.add_argument("--identities", required=True, help="Explicit existing US identity assertions JSON")
    parser.add_argument("--accession", required=True, help="One exact filing accession; no whole-universe inference")
    parser.add_argument("--amendment-parent-accession", default="", help="Explicit original accession for the selected Form3/4/5 amendment")
    parser.add_argument("--output-dir", default="outputs/agent_board")
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--clock-correction", action="store_true", help="Explicit immutable clock-only derivation; never an SEC amendment")
    parser.add_argument("--clock-correction-old-submissions", default="")
    parser.add_argument("--clock-correction-current-submissions", default="")
    parser.add_argument("--clock-correction-expected-parent-sha256", default="")
    args = parser.parse_args()
    # Revoke prior current success before *any* source, identity or raw-file read.
    # A hash-valid old Registry remains historical after a failed CLI attempt.
    def refused(status):
        return consume([], receipt=dict(schema="sec-research-consumption-source-v1", status=status),
            raw_by_hash={}, identities=b"{}", output_root=Path(args.output_dir), decision_at=args.decision_at)
    refused("PREREQUISITE_FAILED")
    correction = None
    try:
        supplied = [args.clock_correction_old_submissions, args.clock_correction_current_submissions,
                    args.clock_correction_expected_parent_sha256]
        need((args.clock_correction and all(supplied)) or (not args.clock_correction and not any(supplied)),
             "CLOCK_CORRECTION_EXPLICIT_ARGUMENTS")
        if args.clock_correction:
            import re
            need(re.fullmatch(r"[0-9a-f]{64}", args.clock_correction_expected_parent_sha256) is not None,
                 "CLOCK_CORRECTION_PARENT_HASH")
            paths = [Path(p) for p in supplied[:2]]
            need(all(p.is_file() and p.stat().st_size <= 2 * 1024 * 1024 for p in paths),
                 "CLOCK_CORRECTION_SUBMISSIONS_BUDGET")
            correction = dict(expected_original_request_sha256=supplied[2], old_submissions=paths[0].read_bytes(),
                              current_submissions=paths[1].read_bytes())
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps(refused("PREREQUISITE_FAILED"), sort_keys=True))
        return 2
    try:
        receipt, frame = verify_ownership_generation(args.pit_root, decision_at=args.decision_at)
    except (OSError, ValueError, KeyError, TypeError):
        result = refused("SOURCE_UNAVAILABLE")
        print(json.dumps(result, sort_keys=True))
        return 2
    if receipt["status"] == "CHECKED_NO_NEW":
        result = consume([], receipt=receipt, raw_by_hash={}, identities=b"{}",
            output_root=Path(args.output_dir), decision_at=args.decision_at)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["current_eligible"] else 2
    try:
        selected = frame[frame["accession_number"] == args.accession].copy()
        need(not selected.empty, "ACCESSION_NOT_IN_CURRENT_SOURCE_SCOPE")
        events = build_ownership_research_events(selected)
        is_amendment = any(event["is_amendment"] for event in events)
        parent = args.amendment_parent_accession
        need(not is_amendment or parent, "AMENDMENT_LINEAGE_REQUIRED")
        need(not parent or is_amendment, "PARENT_FOR_NON_AMENDMENT")
        if parent:
            import re
            need(re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", parent) is not None
                 and parent != args.accession, "AMENDMENT_PARENT_ACCESSION_INVALID")
        parents = {args.accession: parent} if parent else {}
        hashes = {event["document_sha256"] for event in events}
        raw_by_hash = {}
        paths = list(Path(args.raw_dir).glob(args.accession.replace("-", "") + "_*.xml"))
        need(len(paths) <= 20, "ACCESSION_DOCUMENT_BUDGET")
        for path in paths:
            raw = path.read_bytes()
            if digest(raw) in hashes:
                raw_by_hash[digest(raw)] = raw
        identity_bytes = Path(args.identities).read_bytes()
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps(refused("PREREQUISITE_FAILED"), sort_keys=True))
        return 2
    result = consume(events, receipt=receipt, raw_by_hash=raw_by_hash,
        identities=identity_bytes, output_root=Path(args.output_dir), decision_at=args.decision_at,
        amendment_parents=parents, clock_correction=correction)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["current_eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
