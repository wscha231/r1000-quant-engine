"""Standing, finite A1 refresh adapter for the existing private SIP primitives.

No new bar downloader, cron, financial ledger, or Source/PIT admission. A real
post-deployment OWNER contract and reviewed account evidence are mandatory.
Absent evidence returns WAIT_OWNER_EVIDENCE before credentials or remote I/O.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import gzip
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlencode
import zipfile

from tools import alpaca_sip_campaign as campaign
from tools import alpaca_sip_private_backfill_v1 as capture
from tools import prepare_a1_managed_ohlcv as managed
from tools.twelve_private_capture import OwnerDrive, Refused, decode, digest, encoded, require

REPO = "wscha231/r1000-quant-engine"
WORKFLOW = "free_data_daily_update.yml"
TAG = "A1_MANAGED_SIP_EXECUTION_V1 "
SCHEMA = "a1-managed-sip-maintenance-v1"
KEYS = tuple(campaign.LIMITS)
TOTAL_KEYS = KEYS + ("active_seconds", "dispatches")
PIN_PATHS = ("tools/alpaca_sip_managed_refresh.py", "tools/prepare_a1_managed_ohlcv.py",
             "tools/alpaca_sip_campaign.py", "tools/alpaca_sip_private_backfill_v1.py",
             "tools/twelve_private_capture.py", "tools/configure_macro_research_drive.py",
             "tools/macro_history_sources.py", "tools/run_daily_market_session_gate.py",
             ".github/workflows/free_data_daily_update.yml", "requirements_github.txt")
ROOT = Path(__file__).resolve().parents[1]
MAX_STATE = 2_000_000
JOB = "Managed A1 private OHLCV refresh"
JOB_RESERVATION_SECONDS = 5400  # job timeout, including setup/final artifact
PROVIDER_END_DELAY_MINUTES = 15  # conservative historical SIP, no real-time assumption


class MetadataReader:
    """Bound every GitHub metadata read to this run's original wall deadline."""

    def __init__(self, reader, deadline, clock):
        self.reader, self.deadline, self.clock, self.calls = reader, deadline, clock, 0

    def __call__(self, path):
        require(self.clock() + timedelta(seconds=45) < self.deadline
                and self.calls < 170, "MANAGED_METADATA_BUDGET")
        self.calls += 1
        value = self.reader(path)
        require(self.clock() < self.deadline, "MANAGED_METADATA_BUDGET")
        return value


def sha(value):
    return digest(encoded(value))


def integer(value, lower, upper, reason):
    require(type(value) is int and lower <= value <= upper, reason)
    return value


def reference(value, maximum=16_000_000):
    require(isinstance(value, dict) and set(value) == {"file_id", "sha256", "bytes"}
            and isinstance(value["file_id"], str)
            and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", value["file_id"])
            and isinstance(value["sha256"], str) and managed.SHA.fullmatch(value["sha256"]),
            "MANAGED_REFERENCE")
    integer(value["bytes"], 1, maximum, "MANAGED_REFERENCE_SIZE")
    return value


def private_bytes(drive, folder, ref, maximum=16_000_000):
    reference(ref, maximum)
    drive.check(ref["file_id"], folder, folder=False)
    raw = drive.read(ref["file_id"], ref["bytes"])
    require(len(raw) == ref["bytes"] and digest(raw) == ref["sha256"], "MANAGED_OBJECT_HASH")
    return raw


def execution_scope(control):
    """An absent subset preserves the full policy; a present subset is exact."""
    if "execution_tickers" not in control:
        return None
    value = control["execution_tickers"]
    require(isinstance(value, list) and value
            and len(value) <= control["max_symbols_per_run"], "MANAGED_EXECUTION_SCOPE")
    names = managed.symbols(value)
    require(names <= set(control["authorized_tickers"]), "MANAGED_EXECUTION_SCOPE")
    return names


def validate_control(control, inventory_sha, policy_sha, now):
    require(isinstance(control, dict) and control.get("schema") == SCHEMA, "MANAGED_CONTROL")
    require(control.get("repository") == REPO
            and control.get("inventory_sha256") == inventory_sha
            and control.get("policy_sha256") == policy_sha, "MANAGED_SCOPE")
    require(isinstance(control.get("task_key"), str)
            and re.fullmatch(r"R1000-[A-Z0-9-]{8,100}", control["task_key"]), "MANAGED_TASK")
    start, expiry = campaign.utc(control.get("not_before")), campaign.utc(control.get("expires_at"))
    require(start <= now < expiry and timedelta(0) < expiry - start <= timedelta(days=31),
            "MANAGED_WINDOW")
    runs = integer(control.get("max_runs"), 1, 40, "MANAGED_RUN_LIMIT")
    integer(control.get("max_symbols_per_run"), 1, managed.MAX_SYMBOLS, "MANAGED_SYMBOL_LIMIT")
    integer(control.get("max_active_seconds_per_run"), 1, 4800, "MANAGED_ACTIVE_LIMIT")
    require(type(control.get("include_previous_close", False)) is bool,
            "MANAGED_ANCHOR_SCOPE")
    require(control.get("private_noncommercial") is True
            and control.get("supplier_rights_verified") is True
            and control.get("source_admission") is False, "WAIT_OWNER_EVIDENCE")
    for key in ("rights_ref", "bootstrap_ref", "opening_evidence_ref"):
        reference(control.get(key), MAX_STATE)
    require(control["opening_evidence_ref"]["sha256"] == control.get("opening_evidence_sha256"),
            "MANAGED_OPENING_EVIDENCE")
    for key in ("owner_sha256", "credential_binding", "opening_evidence_sha256", "source_history_sha256"):
        require(isinstance(control.get(key), str) and managed.SHA.fullmatch(control[key]),
                "MANAGED_IDENTITY_OR_OPENING_PROOF")
    for key in ("private_root_folder_id", "private_data_folder_id", "journal_folder_id", "evidence_folder_id"):
        require(isinstance(control.get(key), str)
                and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", control[key]), "MANAGED_FOLDER")
    require(len({control[k] for k in ("private_root_folder_id", "private_data_folder_id",
                                     "journal_folder_id", "evidence_folder_id")}) == 4, "MANAGED_FOLDER_ALIAS")
    for field in ("opening_usage", "per_run_allowance", "cumulative_ceiling"):
        keys = KEYS if field == "per_run_allowance" else TOTAL_KEYS
        require(isinstance(control.get(field), dict) and set(control[field]) == set(keys), "MANAGED_BUDGET")
        for key in keys:
            integer(control[field][key], 0, 2**53 - 1, "MANAGED_BUDGET")
    for key in KEYS:
        # Fully reserve every slot, including failed bootstrap/final publication.
        # These are explicit caller numbers, never a new inferred grant/refund.
        require(control["per_run_allowance"][key] <= campaign.LIMITS[key]
                and control["opening_usage"][key] + runs * control["per_run_allowance"][key]
                <= control["cumulative_ceiling"][key], "MANAGED_CUMULATIVE_RESERVATION")
    require(control["opening_usage"]["active_seconds"] + runs * JOB_RESERVATION_SECONDS
            <= control["cumulative_ceiling"]["active_seconds"]
            and control["opening_usage"]["dispatches"] + runs
            <= control["cumulative_ceiling"]["dispatches"], "MANAGED_CUMULATIVE_RESERVATION")
    require(isinstance(control.get("backfill_tickers"), list)
            and managed.symbols(control["backfill_tickers"]) <= set(control.get("authorized_tickers", []))
            and managed.symbols(control.get("authorized_tickers")), "MANAGED_TICKER_SCOPE")
    execution_scope(control)
    require(isinstance(control.get("deployment"), dict)
            and set(control.get("code_pins", {})) == set(PIN_PATHS)
            and all(isinstance(h, str) and managed.SHA.fullmatch(h)
                    for h in control["code_pins"].values()), "MANAGED_DEPLOYMENT")
    # The actual comment ID is returned by GitHub after posting. Excluding only
    # that locator avoids predicting an ID or editing an immutable approval.
    return sha({k: v for k, v in control.items() if k != "approval_reference"})


def owner_grant(control, control_sha, gh, now):
    match = re.fullmatch(re.escape(managed.A0) + r"#issuecomment-([0-9]+)",
                         control.get("approval_reference", ""))
    require(match is not None, "MANAGED_OWNER_GRANT")
    c = gh(f"repos/{REPO}/issues/comments/{match[1]}")
    require(c.get("id") == int(match[1]) and c.get("author_association") == "OWNER"
            and c.get("user", {}).get("type") == "User"
            and c.get("issue_url") == f"https://api.github.com/repos/{REPO}/issues/448"
            and c.get("created_at") == c.get("updated_at"), "MANAGED_IMMUTABLE_OWNER_GRANT")
    created = campaign.utc(c.get("created_at"))
    require(campaign.utc(control["not_before"]) <= created <= now, "MANAGED_OWNER_CLOCK")
    lines = [line[len(TAG):] for line in c.get("body", "").splitlines() if line.startswith(TAG)]
    require(len(lines) == 1 and len(lines[0]) <= 4096, "MANAGED_OWNER_GRANT")
    record = decode(lines[0].encode())
    require(record == dict(control_sha256=control_sha,
                           rights_sha256=control["rights_ref"]["sha256"],
                           opening_evidence_sha256=control["opening_evidence_sha256"],
                           expires_at=control["expires_at"],
                           private_retention_reviewed=True, historical_sip_reviewed=True,
                           standing_budget_approved=True), "MANAGED_OWNER_SCOPE")
    return created


def deployed_source(control, gh, context, root=ROOT):
    require(context.get("repository") == REPO and context.get("ref") == "refs/heads/master"
            and context.get("event") in {"schedule", "workflow_dispatch"}
            and context.get("attempt") == 1, "MANAGED_WORKER_CONTEXT")
    head = context.get("head")
    require(isinstance(head, str) and re.fullmatch(r"[0-9a-f]{40}", head), "MANAGED_WORKER_HEAD")
    for path in PIN_PATHS:
        require(digest(campaign.bounded_bytes(root / path, 600_000).replace(b"\r\n", b"\n"))
                == control["code_pins"][path], "MANAGED_CODE_DRIFT")
    d = control["deployment"]
    integer(d.get("pull_request"), 1, 10**9, "MANAGED_DEPLOYMENT")
    require(all(isinstance(d.get(k), str) and re.fullmatch(r"[0-9a-f]{40}", d[k])
                for k in ("reviewed_head", "merge_sha")), "MANAGED_DEPLOYMENT")
    pr = gh(f"repos/{REPO}/pulls/{d['pull_request']}")
    require(pr.get("merged") is True and pr.get("base", {}).get("ref") == "master"
            and pr.get("head", {}).get("sha") == d.get("reviewed_head")
            and pr.get("merge_commit_sha") == d.get("merge_sha"), "MANAGED_DEPLOYMENT")
    branch = gh(f"repos/{REPO}/branches/master")
    require(branch.get("protected") is True and branch.get("commit", {}).get("sha") == head,
            "MANAGED_PROTECTED_MASTER")
    compare = gh(f"repos/{REPO}/compare/{d['merge_sha']}...{head}")
    require(compare.get("status") in {"identical", "ahead"}
            and compare.get("merge_base_commit", {}).get("sha") == d["merge_sha"], "MANAGED_SOURCE_ANCESTRY")
    return campaign.utc(pr.get("merged_at"))


def run_history(control, gh, context):
    query = urlencode(dict(created=">=" + control["not_before"], per_page=100))
    payload = gh(f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?" + query)
    rows = payload.get("workflow_runs")
    require(isinstance(rows, list) and payload.get("total_count") == len(rows) <= control["max_runs"],
            "MANAGED_HISTORY_INCOMPLETE_OR_BUDGET")
    require(all(isinstance(r, dict) and type(r.get("id")) is int and r["id"] > 0
                and r.get("run_attempt") == 1 and r.get("head_branch") == "master"
                and r.get("event") in {"schedule", "workflow_dispatch"}
                and campaign.utc(control["not_before"]) <= campaign.utc(r.get("created_at"))
                    < campaign.utc(control["expires_at"]) for r in rows)
            and len({r["id"] for r in rows}) == len(rows), "MANAGED_HISTORY")
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    require(rows and rows[-1]["id"] == context["run_id"], "MANAGED_RUN_ORDER")
    require(all(r.get("status") == "completed" for r in rows[:-1]), "MANAGED_PRIOR_RUN_ACTIVE")
    for run in rows[:-1]:
        jobs = gh(f"repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=100")
        require(isinstance(jobs.get("jobs"), list)
                and jobs.get("total_count") == len(jobs["jobs"]) <= 100, "MANAGED_JOBS_INCOMPLETE")
        found = [j for j in jobs["jobs"] if j.get("name") == JOB]
        require(len(found) == 1 and found[0].get("status") == "completed", "MANAGED_JOB_UNCONFIRMED")
        run["managed_skipped"] = found[0].get("conclusion") == "skipped"
    return rows


def provider_endpoint_gate(session, now):
    """Gate the collector's actual inclusive UTC-day end, not the NYSE close.

    request_pages preserves the entire requested day through 23:59:59Z. A
    completed exchange session alone does not make that endpoint historical.
    Keep the conservative delayed-feed boundary even for a real-time account.
    """
    endpoint = campaign.utc(session + "T23:59:59Z")
    earliest = endpoint + timedelta(minutes=PROVIDER_END_DELAY_MINUTES)
    return dict(schema="a1-managed-provider-endpoint-gate-v1",
                ready=now >= earliest, session_date=session,
                requested_inclusive_end_utc=endpoint.isoformat(),
                earliest_request_at_utc=earliest.isoformat(),
                delay_minutes=PROVIDER_END_DELAY_MINUTES,
                checked_at_utc=now.isoformat())


def verify_final_meter(value, run, checkpoint_sha, control_sha, allowance):
    if checkpoint_sha is None:
        require(isinstance(value, dict) and value.get("schema") == "a1-managed-no-capture-v1"
                and value.get("status") in {"SKIP_MARKET_WINDOW", "SKIP_PROVIDER_ENDPOINT_WINDOW"}
                and value.get("managed_control_sha256") == control_sha
                and value.get("run_id") == run["id"] and value.get("run_attempt") == 1
                and value.get("source_sha") == run["head_sha"]
                and value.get("phase") == "BEFORE_CREDENTIALS"
                and value.get("provider_requests") == value.get("drive_requests") == 0
                and value.get("collection_enabled") is False, "MANAGED_NO_CAPTURE_PROOF")
        observed = campaign.utc(value.get("observed_at_utc"))
        require(campaign.utc(run.get("created_at")) <= observed <= campaign.utc(run.get("updated_at")),
                "MANAGED_NO_CAPTURE_CLOCK")
        gate = managed.evaluate_market_session(now_utc=observed, min_close_age_minutes=120)
        require(value.get("market_gate") == gate, "MANAGED_NO_CAPTURE_CALENDAR")
        if value["status"] == "SKIP_MARKET_WINDOW":
            require(gate["ready"] is False, "MANAGED_NO_CAPTURE_CALENDAR")
        else:
            endpoint = provider_endpoint_gate(gate["session_date"], observed)
            require(gate["ready"] is True and endpoint["ready"] is False
                    and value.get("provider_endpoint_gate") == endpoint,
                    "MANAGED_NO_CAPTURE_PROVIDER_CLOCK")
        return dict(no_capture_verified=True)
    require(isinstance(value, dict) and value.get("schema") == "a1-sip-campaign-meter-v1"
            and value.get("run_id") == run["id"] and value.get("run_attempt") == 1
            and value.get("source_sha") == run["head_sha"]
            and value.get("managed_control_sha256") == control_sha
            and value.get("managed_checkpoint_sha256") == checkpoint_sha
            and value.get("finalized") is True and value.get("status") == "COMPLETE"
            and value.get("allowance") == allowance
            and value.get("transfer_definition") == campaign.METRIC
            and all(value.get(k) is False for k in
                    ("source_admission", "pit_verified", "economic_authority")), "MANAGED_FINAL_METER")
    require(isinstance(value.get("usage"), dict) and set(value["usage"]) == set(KEYS),
            "MANAGED_FINAL_METER")
    for key in KEYS:
        integer(value["usage"][key], 0, allowance[key], "MANAGED_FINAL_METER")
    return dict(value["usage"])


def source_history_fence(control, gh):
    """Freeze the full bounded original-Source prefix, including old reruns.

    A latest-created ID alone misses an older run's changed attempt/cost. Any
    added/removed/changed run blocks maintenance until explicit reconciliation.
    """
    rows, total = [], None
    for page in range(1, 5):
        payload = gh(f"repos/{REPO}/actions/workflows/{campaign.WORKFLOW}/runs?per_page=100&page={page}")
        if total is None:
            total = integer(payload.get("total_count"), 0, 400, "MANAGED_SOURCE_HISTORY_BOUND")
        batch = payload.get("workflow_runs")
        require(payload.get("total_count") == total and isinstance(batch, list)
                and len(batch) == min(100, total-len(rows)), "MANAGED_SOURCE_HISTORY_INCOMPLETE")
        rows.extend(batch)
        if len(rows) == total:
            break
    require(len(rows) == total and len({r.get("id") for r in rows}) == total
            and all(type(r.get("id")) is int and r["id"] > 0
                    and type(r.get("run_attempt")) is int and r["run_attempt"] > 0
                    and r.get("status") == "completed" for r in rows), "MANAGED_SOURCE_HISTORY_UNRESOLVED")
    fields = ("id", "run_attempt", "head_sha", "status", "conclusion", "created_at", "updated_at")
    proof = [{k: r.get(k) for k in fields} for r in sorted(rows,key=lambda r:r["id"])]
    require(sha(proof) == control["source_history_sha256"], "MANAGED_INTERVENING_SOURCE_ACTIVITY")
    return proof


def final_meter_reader(gh, control, control_sha, deadline, clock):
    def verify(run, checkpoint_sha):
        payload = gh(f"repos/{REPO}/actions/runs/{run['id']}/artifacts?per_page=100")
        items = payload.get("artifacts")
        require(isinstance(items, list) and payload.get("total_count") == len(items) <= 100,
                "MANAGED_ARTIFACT_LIST")
        name = "a1-managed-ohlcv-" + str(run["id"])
        found = [a for a in items if a.get("name") == name]
        require(len(found) == 1 and found[0].get("expired") is False
                and type(found[0].get("size_in_bytes")) is int
                and 0 < found[0]["size_in_bytes"] <= 150_000, "MANAGED_ARTIFACT_MISSING")
        require(clock() + timedelta(seconds=45) < deadline, "MANAGED_METADATA_BUDGET")
        with tempfile.TemporaryFile() as archive:
            # Same fixed-repository download primitive as the existing Source
            # controller. Only small final meter/result files are published.
            artifact_id = integer(found[0].get("id"), 1, 2**53-1, "MANAGED_ARTIFACT_ID")
            result = subprocess.run(["gh", "api", f"repos/{REPO}/actions/artifacts/{artifact_id}/zip"],
                                    stdout=archive,
                                    stderr=subprocess.DEVNULL, timeout=45)
            require(result.returncode == 0 and clock() < deadline, "MANAGED_ARTIFACT_DOWNLOAD")
            archive.seek(0)
            raw = archive.read(150_001)
            require(0 < len(raw) <= 150_000, "MANAGED_ARTIFACT_SIZE")
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                files = z.infolist()
                require(len(files) == 2 and {f.filename for f in files}
                        == {"managed_meter.json", "managed_result.json"}
                        and all(0 < f.file_size <= 65536 for f in files), "MANAGED_ARTIFACT_FILES")
                meter = decode(z.read("managed_meter.json"))
        return verify_final_meter(meter, run, checkpoint_sha, control_sha, control["per_run_allowance"])
    return verify


def rights_and_bootstrap(control, drive):
    folder = control["evidence_folder_id"]
    rights = decode(private_bytes(drive, folder, control["rights_ref"], MAX_STATE))
    require(isinstance(rights, dict) and rights.get("schema") == "a1-reviewed-account-rights-v1"
            and rights.get("credential_binding") == control["credential_binding"]
            and rights.get("purpose") == "PRIVATE_NONCOMMERCIAL_RESEARCH"
            and rights.get("provider") == "alpaca"
            and rights.get("historical_sip_allowed") is True
            and rights.get("private_retention_allowed") is True, "WAIT_OWNER_EVIDENCE")
    docs = rights.get("source_documents")
    require(isinstance(docs, list) and 1 <= len(docs) <= 8, "MANAGED_RIGHTS_DOCUMENTS")
    for ref in docs:
        private_bytes(drive, folder, ref)
    opening = decode(private_bytes(drive, folder, control["opening_evidence_ref"], MAX_STATE))
    require(isinstance(opening, dict) and opening.get("schema") == "a1-managed-opening-accounting-v1"
            and opening.get("opening_usage") == control["opening_usage"]
            and opening.get("credential_binding") == control["credential_binding"]
            and opening.get("source_history_sha256") == control["source_history_sha256"]
            and opening.get("original_campaigns_unchanged") is True
            and opening.get("unresolved_costs_reserved") is True
            and isinstance(opening.get("source_documents"), list)
            and 1 <= len(opening["source_documents"]) <= 40, "MANAGED_OPENING_EVIDENCE")
    for ref in opening["source_documents"]:
        private_bytes(drive, folder, ref)
    # Supplier expiry may be absent; do not invent it from execution expiry.
    if rights.get("supplier_expiry") is not None:
        require(campaign.utc(rights["supplier_expiry"]) >= campaign.utc(control["expires_at"]),
                "MANAGED_SUPPLIER_EXPIRY")
    bootstrap_raw = private_bytes(drive, folder, control["bootstrap_ref"], MAX_STATE)
    bootstrap = decode(bootstrap_raw)
    require(bootstrap.get("schema") == "a1-managed-reuse-bootstrap-v1"
            and bootstrap.get("inventory_sha256") == control["inventory_sha256"]
            and bootstrap.get("opening_usage") == control["opening_usage"]
            and bootstrap.get("opening_evidence_sha256") == control["opening_evidence_sha256"]
            and isinstance(bootstrap.get("groups"), list) and len(bootstrap["groups"]) <= 1500,
            "MANAGED_BOOTSTRAP")
    return bootstrap


def journal_rows(drive, control):
    folder = control["journal_folder_id"]
    query = urlencode(dict(q=f"'{folder}' in parents and trashed=false",
                           fields="nextPageToken,files(id,name,size)", pageSize=100))
    payload = decode(drive.request("https://www.googleapis.com/drive/v3/files?" + query,
                                   limit=MAX_STATE))
    files = payload.get("files")
    require(isinstance(files, list) and payload.get("nextPageToken") is None
            and len(files) <= 2 * control["max_runs"], "MANAGED_JOURNAL_PAGE")
    rows = []
    for f in files:
        require(isinstance(f, dict) and isinstance(f.get("name"), str)
                and re.fullmatch(r"[0-9a-f]{64}\.json", f["name"])
                and isinstance(f.get("size"), str) and f["size"].isdigit(), "MANAGED_JOURNAL_OBJECT")
        ref = dict(file_id=f["id"], sha256=f["name"][:64], bytes=int(f["size"]))
        value = decode(private_bytes(drive, folder, ref, MAX_STATE))
        require(value.get("schema") == "a1-managed-run-checkpoint-v1", "MANAGED_JOURNAL_OBJECT")
        rows.append((ref["sha256"], value))
    require(len({h for h, _ in rows}) == len(rows), "MANAGED_DUPLICATE_STATE")
    return rows


def restore_journal(rows, history, control_sha, meter_verifier=None):
    parent = None
    coverage, held = {}, {}
    expected_states = 0
    for ordinal, run in enumerate(history[:-1], 1):
        if run.get("managed_skipped") is True:
            require(not any(r.get("slot") == ordinal for _, r in rows), "MANAGED_SKIPPED_STATE_CONFLICT")
            continue
        pair = [(h, r) for h, r in rows if r.get("slot") == ordinal]
        if not pair:
            require(meter_verifier is not None, "MANAGED_UNCONFIRMED_PRIOR_RUN")
            require(meter_verifier(run, None) == dict(no_capture_verified=True),
                    "MANAGED_UNCONFIRMED_PRIOR_RUN")
            continue
        require(len(pair) == 2, "MANAGED_UNCONFIRMED_PRIOR_RUN")
        expected_states += 2
        reserved = [(h, r) for h, r in pair if r.get("state") == "RESERVED"]
        terminal = [(h, r) for h, r in pair if r.get("state") in {"COMPLETE", "BLOCKED"}]
        require(len(reserved) == len(terminal) == 1, "MANAGED_UNCONFIRMED_PRIOR_RUN")
        h0, r0 = reserved[0]
        h1, r1 = terminal[0]
        require(all(r.get("run_id") == run["id"] and r.get("control_sha256") == control_sha
                    and r.get("source_sha") == run.get("head_sha")
                    for r in (r0, r1)) and r0.get("parent_sha256") == parent
                and r1.get("parent_sha256") == h0, "MANAGED_STATE_CHAIN")
        require(r1["state"] == "COMPLETE", "MANAGED_PRIOR_FAILURE_REQUIRES_RECONCILIATION")
        require(meter_verifier is not None, "MANAGED_FINAL_METER_REQUIRED")
        meter_verifier(run, h1)
        require(isinstance(r1.get("coverage_updates"), dict) and isinstance(r1.get("held"), dict),
                "MANAGED_STATE_CONTENT")
        coverage.update(r1["coverage_updates"])
        held.update(r1["held"])
        parent = h1
    require(len(rows) == expected_states,
            "MANAGED_REPLAY_OR_FOREIGN_STATE")
    return parent, coverage, held


def bootstrap_coverage(drive, control, bootstrap, targets):
    """Validate only retained groups needed by this run; never recensus the Lake."""
    found = {}
    seen = set()
    for group in bootstrap["groups"]:
        names = group.get("symbols") if isinstance(group, dict) else None
        require(isinstance(names, list) and 1 <= len(names) <= capture.GROUP_SIZE
                and len(set(names)) == len(names)
                and all(isinstance(t, str) and capture.SYMBOL.fullmatch(t) for t in names),
                "MANAGED_BOOTSTRAP_GROUP")
        require(not (seen & set(names)), "MANAGED_BOOTSTRAP_DUPLICATE")
        seen.update(names)
        if not (set(names) & targets):
            continue
        if group.get("provider") != "alpaca_sip":
            continue  # Twelve-only bytes remain preserved; no silent provider conversion.
        receipt = decode(private_bytes(drive, control["private_data_folder_id"], group["receipt"], MAX_STATE))
        require(receipt.get("symbols") == names, "MANAGED_BOOTSTRAP_RECEIPT")
        raw = private_bytes(drive, control["private_data_folder_id"], receipt["raw_object"])
        norm = private_bytes(drive, control["private_data_folder_id"], receipt["normalized_object"])
        capture.verify_archived_group(raw, norm, receipt)
        with gzip.GzipFile(fileobj=io.BytesIO(norm)) as gz:
            body = gz.read(32_000_001)
        require(len(body) <= 32_000_000, "MANAGED_NORMALIZED_LIMIT")
        dates = {t: {"raw": set(), "split": set()} for t in names}
        for line in body.splitlines():
            row = decode(line)
            dates[row["ticker"]][row["adjustment"]].add(row["date"])
        complete = complete_grid(norm, names, receipt["start"], receipt["end"])
        for t in names:
            require(dates[t]["raw"] == dates[t]["split"], "MANAGED_GRID")
            if t in targets:
                require(t in complete, "MANAGED_BOOTSTRAP_INCOMPLETE_GRID")
                found[t] = max(dates[t]["raw"])
    return found


def missing_windows(targets, coverage, target_session, backfill, *, include_previous_close=False):
    require(type(include_previous_close) is bool, "MANAGED_ANCHOR_SCOPE")
    windows, reused, held = {}, [], {}
    end = (date.fromisoformat(target_session) + timedelta(days=1)).isoformat()
    for ticker in sorted(targets):
        last = coverage.get(ticker)
        if last is not None:
            require(isinstance(last, str) and date.fromisoformat(last).isoformat() == last
                    and last <= target_session, "MANAGED_COVERAGE_CLOCK")
            if last == target_session:
                reused.append(ticker)
                continue
            start = last if include_previous_close else (date.fromisoformat(last) + timedelta(days=1)).isoformat()
        elif ticker in backfill:
            start = capture.MIN_START
        else:
            held[ticker] = "MISSING_VERIFIED_ALPACA_COVERAGE"
            continue
        windows.setdefault((start, end), []).append(ticker)
    return windows, reused, held


def complete_grid(normalized, valid, start, end):
    from tools.run_daily_market_session_gate import mcal
    expected = set(mcal.get_calendar("NYSE").schedule(
        start_date=start, end_date=(date.fromisoformat(end) - timedelta(days=1)).isoformat()
    ).index.strftime("%Y-%m-%d"))
    with gzip.GzipFile(fileobj=io.BytesIO(normalized)) as gz:
        body = gz.read(32_000_001)
    require(len(body) <= 32_000_000, "MANAGED_NORMALIZED_LIMIT")
    dates = {t: {"raw": set(), "split": set()} for t in valid}
    for line in body.splitlines():
        row = decode(line)
        require(row.get("ticker") in dates and row.get("adjustment") in {"raw", "split"}, "MANAGED_GRID")
        dates[row["ticker"]][row["adjustment"]].add(row["date"])
    return {t for t, grids in dates.items() if expected and grids["raw"] == grids["split"] == expected}


def collect_groups(drive, meter, control, bootstrap, tracked, prior_coverage,
                   prior_held, session, key, secret, clock=campaign.utc):
    # Oldest covered names first avoids starving the tail after a bounded run.
    candidates = sorted(set(tracked) - set(prior_held), key=lambda t: (prior_coverage.get(t, ""), t))
    candidates = candidates[:control["max_symbols_per_run"]]
    needs = set(candidates) - set(prior_coverage)
    coverage = bootstrap_coverage(drive, control, bootstrap, needs)
    coverage.update(prior_coverage)
    windows, reused, held = missing_windows(candidates, coverage, session, set(control["backfill_tickers"]),
        include_previous_close=control.get("include_previous_close", False))
    identity_refs = bootstrap.get("asset_identity_refs", {})
    require(isinstance(identity_refs, dict), "MANAGED_IDENTITY_MAP")
    identities = {}
    for t in candidates:
        ref = identity_refs.get(t)
        if ref is None:
            held[t] = "MISSING_STABLE_PROVIDER_IDENTITY_PROOF"
            continue
        original = private_bytes(drive, control["evidence_folder_id"], ref, 65536)
        identities[t] = capture.asset_record(original, t)["id"]
    reused = [t for t in reused if t not in held]
    updates, receipts, rows = {}, [], 0
    for (start, end), names in sorted(windows.items()):
        names = [t for t in names if t not in held]
        for offset in range(0, len(names), capture.GROUP_SIZE):
            group = names[offset:offset + capture.GROUP_SIZE]
            meter.asset_symbols = tuple(group)  # each existing metered asset scope stays <=4
            evidence = capture.precheck_assets(group, key, secret, meter.perform)
            eligible = []
            for row in evidence:
                t = row["symbol"]
                if not capture.asset_supported(row):
                    held[t] = "INACTIVE_OR_UNSUPPORTED_ASSET"
                elif capture.asset_record(row["response_utf8"].encode(), t)["id"] != identities[t]:
                    held[t] = "PROVIDER_SECURITY_ID_CHANGED"
                else:
                    eligible.append(t)
            if not eligible:
                continue
            observed = clock().isoformat()
            objects, valid, no_data, count = capture.capture_one_group(
                drive, control["private_data_folder_id"], eligible, start, end, key, secret,
                control["inventory_sha256"], os.environ.get("GITHUB_SHA", ""),
                get=meter.perform, scope=dict(task_key=control["task_key"],
                    namespace="managed-refresh-v1", input_sha256=control["inventory_sha256"]),
                asset_evidence=[r for r in evidence if r["symbol"] in eligible])
            receipt = decode(private_bytes(drive, control["private_data_folder_id"], objects[-1], MAX_STATE))
            raw = private_bytes(drive, control["private_data_folder_id"], objects[0])
            normalized = private_bytes(drive, control["private_data_folder_id"], objects[1])
            capture.verify_archived_group(raw, normalized, receipt)
            complete = complete_grid(normalized, valid, start, end)
            for t in valid:
                if t in complete:
                    updates[t] = session
                else:
                    held[t] = "INCOMPLETE_REQUESTED_SESSION"
            held.update({t: "VERIFIED_NO_DATA_FOR_REQUESTED_WINDOW" for t in no_data})
            receipts.append(dict(objects=objects, collection_started_at=observed,
                                 collection_finished_at=clock().isoformat(), public_available_at=None,
                                 historical_identity_verified=False, corporate_action_chain_verified=False,
                                 source_admission=False, pit_verified=False))
            rows += count
    updates.update({t: coverage[t] for t in reused})
    return updates, held, reused, receipts, rows


def execute(control, control_sha, policy, bootstrap, history, drive, meter, context,
            key, secret, clock=campaign.utc, meter_verifier=None, *, market_preflight):
    tracked = set(policy["active_tickers"]) | set(policy["watch_tickers"])
    require(tracked <= set(control["authorized_tickers"]), "MANAGED_POLICY_SCOPE_CHANGED")
    subset = execution_scope(control)
    if subset is not None:
        require(subset <= tracked, "MANAGED_EXECUTION_SCOPE")
        tracked = subset
    prior = journal_rows(drive, control)
    parent, coverage, old_held = restore_journal(prior, history, control_sha, meter_verifier)
    if subset is not None:
        require(set(coverage) | set(old_held) <= tracked, "MANAGED_EXECUTION_STATE_SCOPE")
    slot = len(history)
    base = dict(schema="a1-managed-run-checkpoint-v1", control_sha256=control_sha,
                run_id=context["run_id"], slot=slot, source_sha=context["head"])
    reserve = dict(base, state="RESERVED", parent_sha256=parent,
                   reserved_allowance=control["per_run_allowance"],
                   created_at=clock().isoformat())
    reserved = capture.persist_object(drive, control["journal_folder_id"], encoded(reserve), ".json")
    # No provider request occurs until this durable reservation has read back.
    terminal = dict(base, parent_sha256=reserved["sha256"], state="BLOCKED",
                    coverage_updates={}, held={}, receipts=[], reason="MANAGED_INTERRUPTED")
    try:
        observed = clock()
        require(observed >= campaign.utc(market_preflight["checked_at_utc"]),
                "MANAGED_MARKET_CLOCK_REGRESSION")
        gate = managed.evaluate_market_session(now_utc=observed, min_close_age_minutes=120)
        require(gate["ready"], "MANAGED_MARKET_WINDOW")
        require(market_preflight["ready"] is True
                and gate["session_date"] == market_preflight["session_date"],
                "MANAGED_MARKET_SESSION_CHANGED")
        require(provider_endpoint_gate(gate["session_date"], observed)["ready"],
                "MANAGED_PROVIDER_ENDPOINT_WINDOW")
        values = collect_groups(drive, meter, control, bootstrap, tracked, coverage, old_held,
                                gate["session_date"], key, secret, clock)
        updates, held, reused, receipts, rows = values
        terminal.update(state="COMPLETE", reason=None, coverage_updates=updates, held=held,
                        reused=reused, receipts=receipts, rows=rows,
                        session=gate["session_date"], completed_at=clock().isoformat())
    except BaseException:
        terminal.update(completed_at=clock().isoformat())
        capture.persist_object(drive, control["journal_folder_id"], encoded(terminal), ".json")
        raise
    terminal["meter_usage_before_checkpoint_publication"] = dict(meter.used)
    stored = capture.persist_object(drive, control["journal_folder_id"], encoded(terminal), ".json")
    meter.identity["managed_checkpoint_sha256"] = stored["sha256"]
    meter.save()
    return dict(status="REFRESH_CHECKPOINT_VERIFIED", session=terminal["session"],
                valid_updated=len(terminal["coverage_updates"])-len(terminal["reused"]), held=len(terminal["held"]),
                reused=len(terminal["reused"]), rows=terminal["rows"], checkpoint_sha256=stored["sha256"],
                slot=slot, remaining_slots=control["max_runs"] - slot,
                budget_basis="all slots fully reserved; no automatic refund",
                supplier_expiry_inferred=False, source_admission=False, pit_verified=False,
                economic_authority=False)


def context_from_env():
    return dict(repository=os.getenv("GITHUB_REPOSITORY"), ref=os.getenv("GITHUB_REF"),
                head=os.getenv("GITHUB_SHA"), event=os.getenv("GITHUB_EVENT_NAME"),
                attempt=int(os.getenv("GITHUB_RUN_ATTEMPT", "0")),
                run_id=int(os.getenv("GITHUB_RUN_ID", "0")))


def run(args, *, gh=campaign.gh_json, drive_factory=OwnerDrive, clock=campaign.utc):
    for path, other in ((args.meter, args.output), (args.output, args.meter)):
        managed.protect_output(path, [args.policy, args.inventory, other])
    policy, policy_sha = managed.load(args.policy)
    inventory, inventory_sha = managed.load(args.inventory)
    retained = managed.inventory_rows(inventory)
    active = managed.policy_rows(policy, inventory_sha)
    previous = previous_sha = None
    if policy.get("previous_policy_sha256") is not None:
        h = policy["previous_policy_sha256"]
        require(isinstance(h, str) and managed.SHA.fullmatch(h), "MANAGED_PREVIOUS_POLICY")
        previous, previous_sha = managed.load(Path(args.policy).parent / "a1_ohlcv_managed_history" / (h + ".json"))
    managed.transition(policy, previous, previous_sha, retained, active, inventory_sha)
    if policy.get("automatic_capture_enabled") is not True:
        return dict(status="WAIT_OWNER_EVIDENCE", provider_requests=0, dispatches=0,
                    collection_enabled=False, source_admission=False, pit_verified=False)
    raw = os.environ.get("A1_MANAGED_OHLCV_CONTROL", "")
    require(0 < len(raw.encode()) <= 16384, "MANAGED_CONTROL_REQUIRED")
    control = decode(raw.encode())
    now = clock()
    control_sha = validate_control(control, inventory_sha, policy_sha, now)
    deadline = min(campaign.utc(control["expires_at"]),
                   now + timedelta(seconds=control["max_active_seconds_per_run"]))
    gh = MetadataReader(gh, deadline, clock)
    ctx = context_from_env()
    deployed_at = deployed_source(control, gh, ctx)
    require(owner_grant(control, control_sha, gh, now) >= deployed_at, "MANAGED_GRANT_PREDATES_DEPLOYMENT")
    history = run_history(control, gh, ctx)
    source_history_fence(control, gh)
    observed = clock()  # metadata validation must not freeze the provider clock
    require(observed >= now, "MANAGED_MARKET_CLOCK_REGRESSION")
    gate = managed.evaluate_market_session(now_utc=observed, min_close_age_minutes=120)
    endpoint = provider_endpoint_gate(gate["session_date"], observed) if gate["ready"] else None
    if not gate["ready"] or not endpoint["ready"]:
        marker = dict(schema="a1-managed-no-capture-v1",
                      status="SKIP_MARKET_WINDOW" if not gate["ready"] else "SKIP_PROVIDER_ENDPOINT_WINDOW",
                      managed_control_sha256=control_sha,run_id=ctx["run_id"],run_attempt=ctx["attempt"],
                      source_sha=ctx["head"],observed_at_utc=observed.isoformat(),market_gate=gate,
                      phase="BEFORE_CREDENTIALS",provider_requests=0,drive_requests=0,dispatches=0,
                      collection_enabled=False,source_admission=False,pit_verified=False,
                      economic_authority=False)
        if endpoint is not None:
            marker["provider_endpoint_gate"] = endpoint
        managed.write_report(args.meter, marker, [args.policy,args.inventory,args.output])
        return marker
    key, secret = os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_API_SECRET", "")
    require(key and secret and digest((key + "\0" + secret).encode()) == control["credential_binding"],
            "MANAGED_CREDENTIAL_BINDING")
    identity = dict(managed_control_sha256=control_sha, run_id=ctx["run_id"],
                    run_attempt=ctx["attempt"], source_sha=ctx["head"],
                    parent_checkpoint_sha256=None, examined_before=0,
                    managed_worker_started_at=now.isoformat(),
                    managed_worker_deadline=deadline.isoformat())
    journal = Path(args.meter)
    journal.parent.mkdir(parents=True, exist_ok=True)
    meter = campaign.RuntimeMeter(control["per_run_allowance"], journal,
                                   deadline.isoformat(), identity, clock=clock)
    try:
        with meter.process_deadline(), tempfile.TemporaryDirectory(prefix="a1-managed-") as temp:
            drive = drive_factory(control["private_root_folder_id"], temp, meter=meter)
            require(digest(drive.owner.encode()) == control["owner_sha256"] and drive.free >= 2 * 1024**3,
                    "MANAGED_OWNER_OR_SPACE")
            for field in ("private_data_folder_id", "journal_folder_id", "evidence_folder_id"):
                drive.check(control[field], drive.root_id)
            bootstrap = rights_and_bootstrap(control, drive)
            result = execute(control, control_sha, policy, bootstrap, history, drive, meter, ctx,
                             key, secret, clock, final_meter_reader(gh, control, control_sha, deadline, clock),
                             market_preflight=gate)
        meter.finish("COMPLETE")
        result.update(provider_requests=meter.used["provider_gets"],
                      measured_usage=dict(meter.used), reserved_usage=control["per_run_allowance"],
                      github_metadata_requests=gh.calls, platform_total_cost_verified=False,
                      collection_enabled=True, dispatches=0)
        return result
    except BaseException:
        meter.finish("BLOCKED", "MANAGED_RUN_BLOCKED")
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy", required=True)
    p.add_argument("--inventory", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--meter", required=True)
    args = p.parse_args()
    result, code = {}, 0
    try:
        result = run(args)
    except Exception as exc:
        reason = str(exc)
        result = dict(status="BLOCKED", reason=reason if re.fullmatch(r"[A-Z_]{1,100}", reason)
                      else "MANAGED_INTERNAL", collection_enabled=False, source_admission=False,
                      pit_verified=False, economic_authority=False)
        code = 2
    managed.write_report(args.output, result, [args.policy, args.inventory, args.meter])
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
