"""Read producer evidence for the optional Theme/ETF consumer; never run producers.

This verifies the archived research receipt and its dynamic source graph. Fixed
policy input hashes are compared to repository pins, not opened as portfolios.
It does not certify accepted paper state or execute recovery/score generation.
"""
from __future__ import annotations

import hashlib
from datetime import date
import math
from pathlib import Path
import re
import zipfile

from tools.run287_code_identity import code_identity_failures
from tools.run287_research_score_handoff import reference, utc, require
from tools.theme_etf_source_bridge import decode_evidence_json

ROOT = Path(__file__).resolve().parents[1]
SAFE_FALSE = ("backtest_executed", "fullrun_executed", "orders_generated",
              "target_books_mutated", "production_activation_allowed", "live_trading_enabled")
READY = "READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY"
REUSED = "READY_EXISTING_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY"
BUNDLE_SCHEMA = "run287-exact-packet-input-source-bundle-v1"
BUNDLE_STATUS = "READY_EXACT_PACKET_INPUT_SOURCE_PATHS_REVIEW_ONLY"
# Ordered stages emitted by run_run287_exact_packet_upstream.execute().
STAGES = (
    ("scored_latest", "run_run287_scored_latest_refresh", "READY_RESEARCH_SCORED_LATEST", "session_date", "price_manifest"),
    ("macro", "build_run287_macro_sidecar", "READY_CONSERVATIVE_MACRO_SIDECAR", "valuation_close_date", "macro_manifest"),
    ("benchmark_event", "build_run287_benchmark_event_sidecar", "READY_CONSERVATIVE_BENCHMARK_EVENT_SIDECAR", "valuation_close_date", None),
    ("recent_sec", "collect_run287_recent_sec_delta", "READY_RECENT_SEC_ACCEPTED_DELTA", "valuation_price_cutoff_date", None),
    ("recent_companyfacts", "fetch_run287_recent_companyfacts", "READY_RECENT_COMPANYFACTS_DELTA", None, None),
    ("decision_frame", "build_run287_current_decision_frame", "READY_COMPLETE_CURRENT_DECISION_FRAME", "valuation_price_cutoff_date", "decision_manifest"),
    ("score_only", "run_run287_current_decision_score_only", "READY_CURRENT_DECISION_SCORE_ONLY_NONRANKING", "valuation_price_cutoff_date", None),
    ("score_stack", "run_run287_current_decision_score_stack_audit", "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING", "valuation_price_cutoff_date", "score_stack_manifest"),
    ("crisis", "build_run287_current_crisis_state_sidecar", "READY_CURRENT_CRISIS_STATE_NONSELECTING", "valuation_price_cutoff_date", "crisis_manifest"),
    ("selector_benchmark", "recover_run287_selector_benchmark_price", "READY_SELECTOR_BENCHMARK_PRICE_NONSELECTING", "valuation_price_cutoff_date", "soxx_manifest"),
)
OUTPUTS = {"decision_manifest": ("selection_context",), "score_stack_manifest": ("ticker_order_score_stack",),
           "crisis_manifest": ("current_crisis_state",), "macro_manifest": ("market_component_audit",),
           "price_manifest": ("provider_price_overlap.parquet", "scored_latest.csv"), "soxx_manifest": ("price_file",)}
EDGES = (("decision_manifest", "scored_latest_manifest", "price_manifest"),
         ("decision_manifest", "macro_manifest", "macro_manifest"),
         ("score_stack_manifest", "decision_frame_manifest", "decision_manifest"),
         ("crisis_manifest", "macro_manifest", "macro_manifest"),
         ("soxx_manifest", "crisis_manifest", "crisis_manifest"))
STAGE_EDGES = (("benchmark_event", "macro_manifest", "macro"),
               ("recent_companyfacts", "delta_manifest", "recent_sec"),
               ("decision_frame", "scored_latest_manifest", "scored_latest"),
               ("decision_frame", "macro_manifest", "macro"),
               ("decision_frame", "benchmark_manifest", "benchmark_event"),
               ("decision_frame", "sec_delta_manifest", "recent_sec"),
               ("decision_frame", "companyfacts_manifest", "recent_companyfacts"),
               ("score_only", "decision_frame_manifest", "decision_frame"),
               ("score_stack", "decision_frame_manifest", "decision_frame"),
               ("score_stack", "score_only_manifest", "score_only"),
               ("crisis", "macro_manifest", "macro"),
               ("selector_benchmark", "crisis_manifest", "crisis"))
STAGE_BUDGETS = {"scored_latest": "scored_latest_provider_batches", "macro": "macro",
                 "benchmark_event": "benchmark", "recent_sec": "recent_sec",
                 "recent_companyfacts": "companyfacts", "selector_benchmark": "selector_benchmark"}


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def declared_requests(obj):
    for key in ("network_requests_executed", "network_download_batch_count"):
        if obj.get(key) is not None:
            require(integer(obj[key]), "upstream_manifest_requests_invalid")
            return obj[key]
    return 0


def same_fields(actual, expected):
    return isinstance(actual, dict) and all(type(actual.get(k)) is type(v) and actual[k] == v
                                           for k, v in expected.items())


def recovery_observed_ready(receipt):
    """Require the preflight's actual absence proof and matching parent mode."""
    from tools.build_run287_risk_outcome_parent_anchor import KNOWN_LEGACY_SAFETY_MIGRATIONS
    from tools.run287_paper_ledger_integrity import INTEGRITY_SCHEMA, PAPER_INTEGRITY_VERIFIER_RECEIPT_SCHEMA
    observed = receipt.get("observed_state")
    if not same_fields(observed, {"remote_accepted_head_discovery_confirmed": True,
            "remote_committed_accepted_head_count": 0, "remote_committed_accepted_head_absence_proven": True}):
        return False
    legacy, paper = observed.get("legacy_parent"), observed.get("paper_ledger")
    if not isinstance(legacy, dict) or not isinstance(paper, dict):
        return False
    if receipt.get("status") == "READY_ONE_TIME_GENESIS":
        expected = {"state": "PROVEN_ABSENT", "summary_sha256": "", "summary_bytes": 0,
                    "event_log_sha256": hashlib.sha256(b"").hexdigest(), "event_log_bytes": 0,
                    "event_count": 0, "byte_exact_allowlist_match": False, "review_only": True}
        if set(legacy) != set(expected) or not same_fields(legacy, expected):
            return False
    else:
        pin = KNOWN_LEGACY_SAFETY_MIGRATIONS.get(legacy.get("summary_sha256")) if digest(legacy.get("summary_sha256")) else None
        if not pin or not same_fields(legacy, {"state": "PRESENT_FETCHED", "byte_exact_allowlist_match": True,
                "review_only": True, "as_of_date": pin["as_of_date"], "status": pin["status"],
                "allowlist_evidence_workflow_run_id": pin["evidence_workflow_run_id"]}):
            return False
        if (not integer(legacy.get("summary_bytes"), 1) or not integer(legacy.get("event_log_bytes"))
                or not integer(legacy.get("event_count")) or not digest(legacy.get("event_log_sha256"))):
            return False
        if legacy["event_log_bytes"] == 0 and (legacy["event_count"] != 0
                or legacy["event_log_sha256"] != hashlib.sha256(b"").hexdigest()):
            return False
    if not same_fields(paper, {"schema_version": INTEGRITY_SCHEMA, "status": "VERIFIED",
            "verifier_receipt_schema_version": PAPER_INTEGRITY_VERIFIER_RECEIPT_SCHEMA}):
        return False
    if not all(digest(paper.get(k)) for k in ("file_sha256", "files_sha256", "snapshot_hash",
            "genesis_identity_sha256", "verifier_receipt_sha256", "immutable_head_selection_sha256",
            "immutable_root_snapshot_hash", "immutable_terminal_snapshot_hash")):
        return False
    if not all(integer(paper.get(k), 1) for k in ("file_bytes", "file_count", "verifier_receipt_bytes", "immutable_head_count")):
        return False
    chain = paper.get("immutable_chain_snapshot_hashes")
    try:
        valid_date = date.fromisoformat(paper["as_of_date"]).isoformat() == paper["as_of_date"]
    except (KeyError, TypeError, ValueError):
        return False
    return (isinstance(chain, list) and all(digest(x) for x in chain) and len(set(chain)) == len(chain)
            and len(chain) == paper["immutable_head_count"]
            and integer(paper.get("ancestor_snapshot_count")) and paper["ancestor_snapshot_count"] == len(chain) - 1
            and chain[0] == paper["immutable_root_snapshot_hash"]
            and chain[-1] == paper["immutable_terminal_snapshot_hash"] == paper["snapshot_hash"]
            and paper.get("previous_snapshot_hash") == (chain[-2] if len(chain) > 1 else "")
            and valid_date
            and paper["as_of_date"] <= receipt["source"]["session_date"])


def read_upstream_prerequisite(path, upstream, run, artifact, session, contract):
    """Verify ready producer structure, exact dynamic bytes, and stage lineage."""
    require(upstream.get("schema_version") == "run287-exact-packet-upstream-orchestrator-v3"
            and upstream.get("status") in (READY, REUSED) and upstream.get("upstream_ready") is True
            and upstream.get("valuation_price_cutoff_date") == session
            and upstream.get("research_only") is True
            and all(upstream.get(k) is False for k in SAFE_FALSE + ("historical_cagr_mdd_evidence_changed",)),
            "upstream_producer_contract_invalid")
    require(not any(upstream.get(k) for k in ("failures", "contract_failures", "skip_reasons", "failed_stage")),
            "upstream_producer_audit_failed")
    preflight = upstream.get("preflight")
    require(isinstance(preflight, dict), "upstream_preflight_missing")
    identity = preflight.get("code_identity")
    require(not code_identity_failures(identity) and identity["source_commit_sha"] == run["head_sha"],
            "upstream_code_identity_invalid")
    require(all(isinstance(record, dict) and digest(record.get("sha256"))
                for record in identity["files"].values()), "upstream_code_files_invalid")
    decision = preflight.get("decision_time_utc")
    completed = upstream.get("completed_at_utc")
    require(utc(run.get("run_started_at") or run["created_at"]) <= utc(decision) <= utc(completed) <= utc(artifact["created_at"]),
            "upstream_preflight_time_invalid")
    require(integer(upstream.get("network_requests_executed"))
            and type(upstream.get("elapsed_seconds")) in (int, float)
            and math.isfinite(upstream["elapsed_seconds"]) and upstream["elapsed_seconds"] >= 0,
            "upstream_counters_invalid")
    policy = decode_evidence_json((ROOT / "docs/run287_exact_packet_producer_contract.json").read_text())
    evidence = {}
    with zipfile.ZipFile(path) as archive:
        names, total = archive.namelist(), 0
        def read(label, record, json_object=True):
            nonlocal total
            name, expected = reference(record, contract["repository"])
            require(names.count(name) == 1, "upstream_member_missing_or_duplicate")
            info = archive.getinfo(name)
            require(not info.is_dir() and info.file_size <= contract["max_member_bytes"], "upstream_member_size_invalid")
            total += info.file_size
            require(total <= contract["max_artifact_bytes"], "upstream_graph_size_invalid")
            raw = archive.read(info)
            require(hashlib.sha256(raw).hexdigest() == expected, "upstream_member_hash_mismatch")
            if "bytes" in record:
                require(type(record["bytes"]) is int and record["bytes"] == len(raw), "upstream_member_bytes_invalid")
            if "exists" in record:
                require(record["exists"] is True, "upstream_member_not_present")
            evidence["theme_upstream_" + label] = {"member": name, "sha256": expected, "bytes": len(raw)}
            if not json_object:
                return raw
            require(name.endswith(".json"), "upstream_manifest_type_invalid")
            obj = decode_evidence_json(raw.decode("utf-8-sig"))
            require(isinstance(obj, dict), "upstream_manifest_not_object")
            return obj
        attempt = f"outputs/run287_exact_packet_upstream/attempts/{run['id']}-{run['run_attempt']}"
        plan_ref = preflight.get("archived_plan")
        require(reference(plan_ref, contract["repository"])[0] == attempt + "/plan.json", "upstream_plan_attempt_mismatch")
        plan = read("plan", plan_ref)
        plan_path = "docs/run287_exact_packet_upstream_plan.json"
        trusted_plan_raw = (ROOT / plan_path).read_bytes()
        expected_plan_hash = hashlib.sha256(trusted_plan_raw).hexdigest()
        original_plan = preflight.get("plan")
        runner_root = "/home/runner/work/" + "/".join([contract["repository"].split("/")[-1]] * 2) + "/"
        require(same_fields(original_plan, {"sha256": expected_plan_hash, "bytes": len(trusted_plan_raw), "exists": True})
                and original_plan.get("path") in (plan_path, runner_root + plan_path)
                and plan_ref["sha256"] == expected_plan_hash, "upstream_plan_identity_mismatch")
        budgets = plan["network_budgets"]
        require(integer(budgets.get("maximum_total_recorded_requests"))
                and upstream["network_requests_executed"] <= budgets["maximum_total_recorded_requests"],
                "upstream_request_budget_exceeded")
        bundle = read("bundle", upstream.get("source_bundle"))
        require(bundle.get("schema_version") == BUNDLE_SCHEMA and bundle.get("status") == BUNDLE_STATUS
                and bundle.get("valuation_price_cutoff_date") == session and bundle.get("research_only") is True
                and all(bundle.get(k) is False for k in SAFE_FALSE)
                and type(bundle.get("network_requests_executed")) is int and bundle["network_requests_executed"] == 0
                and bundle.get("code_identity") == identity, "upstream_bundle_contract_invalid")
        inputs = bundle.get("inputs")
        dynamic, fixed = policy["required_dynamic_inputs"], policy["required_fixed_inputs"]
        require(isinstance(inputs, dict) and set(inputs) == set(dynamic) | set(fixed), "upstream_bundle_inputs_invalid")
        for label, pin in fixed.items():
            record = inputs[label]
            require(isinstance(record, dict) and record.get("sha256") == pin
                    and isinstance(record.get("path"), str) and bool(record["path"].strip()), "upstream_fixed_pin_invalid")
        manifests = {}
        for label, requirement in dynamic.items():
            obj = manifests[label] = read(label, inputs[label])
            require(obj.get("status") == requirement["status"] and obj.get(requirement["date_field"]) == session,
                    "upstream_dynamic_not_ready")
            require(all(k not in obj or obj[k] is False for k in SAFE_FALSE + ("source_inputs_mutated",)),
                    "upstream_dynamic_unsafe")
            for output in OUTPUTS[label]:
                read(label + "_" + output, (obj.get("outputs") or {}).get(output), False)
        for owner, key, source in EDGES:
            require(reference((manifests[owner].get("source_inputs") or {}).get(key), contract["repository"])
                    == reference(inputs[source], contract["repository"]), "upstream_lineage_mismatch")
        stage_refs = {name: inputs[label] for name, _, _, _, label in STAGES if label}
        for name, owner, key in (("benchmark_event", "decision_manifest", "benchmark_manifest"),
                                 ("recent_sec", "decision_manifest", "sec_delta_manifest"),
                                 ("recent_companyfacts", "decision_manifest", "companyfacts_manifest"),
                                 ("score_only", "score_stack_manifest", "score_only_manifest")):
            stage_refs[name] = (manifests[owner].get("source_inputs") or {}).get(key)
        stage_objects = {}
        for name, _, status, date_field, label in STAGES:
            obj = stage_objects[name] = manifests[label] if label else read("stage_" + name, stage_refs[name])
            require(obj.get("status") == status and (not date_field or obj.get(date_field) == session)
                    and all(k not in obj or obj[k] is False for k in SAFE_FALSE + ("source_inputs_mutated",)),
                    "upstream_stage_manifest_invalid")
            require(all(k not in obj or type(obj[k]) is list and obj[k] == []
                        for k in ("blockers", "failures", "contract_failures", "skip_reasons")), "upstream_stage_blocked")
            for key in ("executed_at_utc", "generated_at_utc", "completed_at_utc"):
                if key in obj:
                    require(utc(obj[key]) <= utc(completed), "upstream_completion_predates_stage")
        for owner, key, source in STAGE_EDGES:
            require(reference((stage_objects[owner].get("source_inputs") or {}).get(key), contract["repository"])
                    == reference(stage_refs[source], contract["repository"]), "upstream_stage_lineage_mismatch")
        audits = upstream.get("stage_audit")
        require(isinstance(audits, list) and all(isinstance(a, dict) for a in audits), "upstream_stage_audit_missing")
        if upstream["status"] == REUSED:
            require(len(audits) == 1 and same_fields(audits[0], {"name": "existing_source_bundle",
                    "status": "READY_EXISTING_EXACT_PACKET_INPUT_SOURCE_BUNDLE_REVIEW_ONLY",
                    "network_requests_executed": 0, "failures": []})
                    and upstream["network_requests_executed"] == 0
                    and upstream.get("network_execution_authorized") is False, "upstream_reuse_invalid")
            require(read("reused_bundle", audits[0].get("manifest")) == bundle
                    and audits[0]["manifest"]["sha256"] == upstream["source_bundle"]["sha256"], "upstream_reuse_mismatch")
            require(utc(decision) <= utc(audits[0].get("completed_at_utc")) <= utc(completed), "upstream_completion_order_invalid")
        else:
            require([a.get("name") for a in audits] == [s[0] for s in STAGES], "upstream_stages_incomplete")
            prior_completion = utc(decision)
            for audit, (name, tool, status, date_field, label) in zip(audits, STAGES):
                require(same_fields(audit, {"tool": "tools/" + tool + ".py", "status": status,
                        "return_code": 0, "failures": []}) and integer(audit.get("network_requests_executed")),
                        "upstream_stage_failed")
                require(reference(audit.get("manifest"), contract["repository"])[0] == attempt + "/" + name + "/manifest.json"
                        and reference(audit.get("log"), contract["repository"])[0] == attempt + "/logs/" + name + ".log",
                        "upstream_stage_attempt_mismatch")
                require(reference(audit["manifest"], contract["repository"]) == reference(stage_refs[name], contract["repository"]),
                        "upstream_stage_graph_mismatch")
                cap = budgets[STAGE_BUDGETS[name]] if name in STAGE_BUDGETS else 0
                require(integer(cap) and audit["network_requests_executed"] <= cap, "upstream_stage_budget_exceeded")
                require(audit["network_requests_executed"] == declared_requests(stage_objects[name]),
                        "upstream_stage_request_count_mismatch")
                stage_completed = utc(audit.get("completed_at_utc"))
                require(prior_completion <= stage_completed <= utc(completed), "upstream_completion_order_invalid")
                prior_completion = stage_completed
                obj = read("stage_" + name, audit.get("manifest"))
                read("log_" + name, audit.get("log"), False)
                require(obj.get("status") == status and (not date_field or obj.get(date_field) == session)
                        and all(k not in obj or obj[k] is False for k in SAFE_FALSE), "upstream_stage_manifest_invalid")
                for key in ("executed_at_utc", "generated_at_utc", "completed_at_utc"):
                    if key in obj:
                        require(utc(obj[key]) <= stage_completed, "upstream_completion_predates_stage")
                if label:
                    require(reference(audit["manifest"], contract["repository"]) == reference(inputs[label], contract["repository"]),
                            "upstream_stage_bundle_mismatch")
            require(upstream["network_requests_executed"] == sum(a["network_requests_executed"] for a in audits),
                    "upstream_network_count_mismatch")
    return completed, evidence
