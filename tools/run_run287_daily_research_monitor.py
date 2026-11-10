#!/usr/bin/env python3
"""Join immutable GitHub evidence into a read-only daily research handoff.

No provider calls, model runs, portfolio reads/writes, arbitrary artifact
extraction, workflow dispatches, or fallback to an earlier successful run.
Downloaded JSON/CSV is data only. This report is not accepted paper state.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.run287_research_score_handoff import read_score_handoff, evaluate_score_handoff
from tools.run287_research_report_html import render_html
from tools import run287_etf_rotation, theme_etf_source_bridge
from tools import candidate_reassessment_bridge as reassessment
from tools.theme_etf_upstream_admission import read_upstream_prerequisite, recovery_observed_ready

CONTRACT = ROOT / "docs/run287_daily_research_monitor_contract.json"
SCHEMA = "run287-daily-research-monitor-v1"
READY_UPSTREAM = {
    "READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
    "READY_EXISTING_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
}


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result.astimezone(timezone.utc)


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def date_state(value: Any, expected: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return "MISSING_OR_INVALID_DATE"
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return "MISSING_OR_INVALID_DATE"
    return "CURRENT" if value == expected else "STALE" if value < expected else "FUTURE_DATE"


def collection_current(value: Any, session: str, now: datetime) -> bool:
    return (date_state(value, session) in {"CURRENT", "FUTURE_DATE"}
            and value <= now.date().isoformat())


def latest_run(runs: list[dict], workflow: str, repository: str, allowed_events: list[str]) -> dict | None:
    eligible = [r for r in runs if r.get("head_branch") == "master"
                and r.get("path") == f".github/workflows/{workflow}"
                and (r.get("head_repository") or {}).get("full_name") == repository
                and r.get("event") in allowed_events]
    # Include failed and running runs. Never hide a failure behind old success.
    return max(eligible, key=lambda r: (r["created_at"], r["id"]), default=None)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not token:
            raise ValueError("repository_or_token_missing")
        self.root = f"https://api.github.com/repos/{repository}"
        self.headers = {"Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "run287-readonly-research-monitor"}

    def json(self, path: str) -> Any:
        req = urllib.request.Request(self.root + path, headers=self.headers)
        with urllib.request.build_opener(NoRedirect).open(req, timeout=45) as response:
            return json.load(response)

    def archive(self, artifact_id: int, destination: Path, limit: int) -> str:
        req = urllib.request.Request(f"{self.root}/actions/artifacts/{artifact_id}/zip",
                                     headers=self.headers)
        try:
            response = urllib.request.build_opener(NoRedirect).open(req, timeout=45)
        except urllib.error.HTTPError as exc:
            if exc.code != 302:
                raise
            location = exc.headers.get("Location", "")
            parsed = urllib.parse.urlsplit(location)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("unsafe_artifact_redirect") from None
            # The temporary storage URL never receives the GitHub token.
            response = urllib.request.urlopen(location, timeout=90)
        digest = hashlib.sha256()
        size = 0
        with response, destination.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValueError("artifact_size_limit")
                digest.update(chunk)
                out.write(chunk)
        return "sha256:" + digest.hexdigest()


def read_members(path: Path, members: dict[str, str], limit: int) -> tuple[dict, dict]:
    data, evidence = {}, {}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for label, name in members.items():
            if names.count(name) > 1:
                raise ValueError("duplicate_artifact_member")
            if name not in names:
                continue
            info = archive.getinfo(name)
            if info.file_size > limit or info.is_dir():
                raise ValueError("artifact_member_size_or_type")
            # Read by exact contract path, never extract or execute artifact files.
            raw = archive.read(info)
            evidence[label] = {"member": name, "sha256": hashlib.sha256(raw).hexdigest(),
                               "bytes": len(raw)}
            value = raw.decode("utf-8-sig")
            parsed = (theme_etf_source_bridge.decode_evidence_json(value) if name.endswith(".json")
                      else list(csv.DictReader(io.StringIO(value))))
            if name.endswith(".json") and not isinstance(parsed, dict):
                raise ValueError("manifest_must_be_object")
            data[label] = parsed
    return data, evidence


def recovery_receipt_ready(receipt: dict, run: dict, artifact: dict, session: str) -> bool:
    """Consume the existing preflight's exact producer identity and approval."""
    status = receipt.get("status")
    modes = {"READY_ONE_TIME_LEGACY_QUARANTINE": ("legacy_quarantine", "allow_quarantined_legacy_outcome_parent"),
             "READY_ONE_TIME_GENESIS": ("genesis", "allow_risk_outcome_genesis_bootstrap")}
    if not isinstance(status, str) or status not in modes:
        return False
    mode, required_input = modes[status]
    expected_source = {"event_name": "workflow_dispatch", "source_commit_sha": run.get("head_sha"),
                       "source_run_id": str(run.get("id")), "source_run_attempt": str(run.get("run_attempt")),
                       "source_job_key": "refresh", "session_date": session}
    expected_authorization = {"mode": mode, "required_event_name": "workflow_dispatch",
                              "required_input": required_input, "requested": True,
                              "conflicting_authorization_requested": False, "satisfied": True,
                              "one_time_only": True, "separate_user_approval_required": True}
    authorization = receipt.get("authorization")
    inactive_flags = ("accepted_head_created", "parent_anchor_created", "target_books_mutated",
                      "orders_generated", "ledger_mutated", "historical_cagr_mdd_evidence_changed",
                      "fullrun_executed", "production_activation_allowed", "live_trading_enabled",
                      "automatic_promotion_allowed")
    ready = (receipt.get("schema_version") == "run287-risk-outcome-parent-preflight-v1"
            and run.get("event") == "workflow_dispatch" and receipt.get("source") == expected_source
            and isinstance(authorization, dict)
            and all(type(authorization.get(k)) is type(v) and authorization.get(k) == v
                    for k, v in expected_authorization.items())
            and receipt.get("review_only") is True and receipt.get("blockers") == []
            and all(receipt.get(k) is False for k in inactive_flags)
            and type(receipt.get("exit_code")) is int and receipt["exit_code"] == 0
            and recovery_observed_ready(receipt))
    if not ready:
        return False
    try:
        return (timestamp(run.get("run_started_at") or run["created_at"])
                <= timestamp(receipt["generated_at_utc"]) <= timestamp(artifact["created_at"]))
    except (KeyError, AttributeError, TypeError, ValueError):
        return False


def forward_a1_jobs(client: GitHub, run: dict, names: dict) -> dict:
    """Bind the proxy and managed jobs to one run attempt."""
    path = f"/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"
    listing = client.json(path)
    jobs = listing.get("jobs")
    count = listing.get("total_count")
    if not isinstance(jobs, list) or type(count) is not int or count != len(jobs) or count > 100:
        raise ValueError("forward_job_list_incomplete")
    result = {}
    for label, name in names.items():
        matches = [job for job in jobs if job.get("name") == name]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError("forward_job_ambiguous")
        job = matches[0]
        if (type(job.get("id")) is not int or job["id"] <= 0
                or type(job.get("run_id")) is not int or job["run_id"] != run["id"]
                or type(job.get("run_attempt")) is not int or job["run_attempt"] != run["run_attempt"]
                or job.get("head_sha") != run["head_sha"] or job.get("status") != "completed"):
            raise ValueError("forward_job_identity_mismatch")
        result[label] = {k: job.get(k) for k in ("id", "status", "conclusion")}
    return result


def collect_source(client: GitHub, key: str, spec: dict, contract: dict, *, now=None, session=None) -> dict:
    result: dict[str, Any] = {"source": key, "status": "MISSING_RUN", "data": {}}
    forward = key in contract.get("forward_context_sources", {})
    archive_limit = min(contract["max_artifact_bytes"], spec.get("max_artifact_bytes", contract["max_artifact_bytes"]))
    member_limit = min(contract["max_member_bytes"], spec.get("max_member_bytes", contract["max_member_bytes"]))
    try:
        runs = client.json(f"/actions/workflows/{spec['workflow']}/runs?branch=master&per_page=30")
        if key == "previous_monitor":
            current_id = os.environ.get("GITHUB_RUN_ID", "")
            runs = dict(runs, workflow_runs=[r for r in runs.get("workflow_runs", [])
                        if str(r.get("id")) != current_id])
        run = latest_run(runs.get("workflow_runs", []), spec["workflow"], contract["repository"], spec["allowed_events"])
        if run is None:
            return result
        result["run"] = {k: run.get(k) for k in
                         ("id", "run_attempt", "head_sha", "created_at", "updated_at", "status", "conclusion", "html_url")}
        result["metadata_collected_at"] = (now or datetime.now(timezone.utc)).isoformat()
        if run.get("status") != "completed":
            result["status"] = "UPSTREAM_IN_PROGRESS"
            return result
        result["status"] = "UPSTREAM_FAILED" if run.get("conclusion") != "success" else "MISSING_ARTIFACT"
        if forward:
            observed = now if now is not None else datetime.now(timezone.utc)
            if (type(run.get("id")) is not int or run["id"] <= 0
                    or type(run.get("run_attempt")) is not int or run["run_attempt"] <= 0
                    or not re.fullmatch(r"[a-f0-9]{40}", run.get("head_sha") or "")):
                raise ValueError("forward_run_identity_invalid")
            if not (timestamp(run["created_at"]) <= timestamp(run["updated_at"]) <= observed):
                raise ValueError("forward_run_clock_invalid")
            if not isinstance(run.get("conclusion"), str) or not run["conclusion"]:
                raise ValueError("forward_run_conclusion_invalid")
            if spec.get("metadata_only") is True:
                result["status"] = "RUN_METADATA_ONLY"
                return result
            if spec.get("job_names"):
                result["jobs"] = forward_a1_jobs(client, run, spec["job_names"])
            # These artifact names contain a run ID, with no attempt field.
            if run["run_attempt"] != 1:
                result["status"] = "UNVERIFIED_RUN_ATTEMPT"
                return result
        listing = client.json(f"/actions/runs/{run['id']}/artifacts?per_page=100")
        artifacts = listing.get("artifacts", [])
        if forward:
            count = listing.get("total_count")
            if (not isinstance(artifacts, list) or type(count) is not int
                    or count != len(artifacts) or count > 100):
                raise ValueError("forward_artifact_list_incomplete")
        artifact_name = spec.get("artifact_name", spec["artifact_prefix"] + "{run_id}").format(
            run_id=run["id"], run_attempt=run.get("run_attempt", 1))
        matches = [a for a in artifacts if a.get("name") == artifact_name]
        if len(matches) != 1:
            return result
        artifact = matches[0]
        result["artifact"] = {k: artifact.get(k) for k in ("id", "name", "digest", "expired", "size_in_bytes", "created_at")}
        identity = artifact.get("workflow_run") or {}
        if identity.get("id") != run["id"] or identity.get("head_sha") != run["head_sha"]:
            raise ValueError("artifact_run_identity_mismatch")
        if forward:
            repo_id = (run.get("head_repository") or {}).get("id")
            if (type(identity.get("id")) is not int or identity.get("head_branch") != "master"
                    or artifact.get("expired") is not False
                    or type(repo_id) is not int or repo_id <= 0
                    or identity.get("repository_id") != repo_id or identity.get("head_repository_id") != repo_id
                    or type(artifact.get("id")) is not int or artifact["id"] <= 0
                    or type(artifact.get("size_in_bytes")) is not int
                    or not 0 < artifact["size_in_bytes"] <= archive_limit):
                raise ValueError("forward_artifact_identity_or_size_invalid")
            if not (timestamp(run["created_at"]) <= timestamp(artifact["created_at"])
                    <= timestamp(run["updated_at"]) <= observed):
                raise ValueError("forward_artifact_clock_invalid")
            result["artifact"]["created_at"] = artifact["created_at"]
        if artifact.get("expired") or artifact.get("size_in_bytes", 0) > archive_limit:
            raise ValueError("artifact_expired_or_oversize")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", artifact.get("digest") or ""):
            raise ValueError("artifact_digest_missing")
        with tempfile.TemporaryDirectory(prefix="run287-monitor-") as folder:
            path = Path(folder) / "evidence.zip"
            actual = client.archive(artifact["id"], path, archive_limit)
            if actual != artifact["digest"]:
                raise ValueError("artifact_digest_mismatch")
            members = {k: v.format(run_id=run["id"], run_attempt=run.get("run_attempt", 1))
                       for k, v in spec["members"].items()}
            rotation_member = members.get("etf_rotation") if key == "tactical" else None
            ordinary_members = {k: v for k, v in members.items() if not rotation_member or k != "etf_rotation"}
            result["data"], result["files"] = read_members(path, ordinary_members, member_limit)
            if rotation_member:
                # A bad optional receipt must not discard existing tactical diagnostics.
                try:
                    rotation, hashes = read_members(path, {"etf_rotation": rotation_member}, min(member_limit, 131_072))
                    rotation_now = now if now is not None else datetime.now(timezone.utc)
                    raw_receipt = rotation.get("etf_rotation")
                    result["data"]["etf_rotation"] = run287_etf_rotation.receipt_observation(
                        raw_receipt, run, artifact, session or completed_session(rotation_now),
                        rotation_now, contract)
                    capsule = raw_receipt.get("safe_review_handoff") if isinstance(raw_receipt, dict) else None
                    if capsule is not None:
                        result["data"]["etf_safe_review"] = capsule
                    result["files"].update(hashes)
                except (ValueError, OSError, RuntimeError, zipfile.BadZipFile):
                    result["data"]["etf_rotation"] = {"status": "UNVERIFIED_RECEIPT"}
            if key == "operating" and contract.get("theme_etf_bridge"):
                bridge_now = now if now is not None else datetime.now(timezone.utc)
                bridge_session = session if session is not None else completed_session(bridge_now)
                prerequisites = set(members) - set(spec.get("optional_members", []))
                upstream = result["data"].get("upstream", {})
                recovery = result["data"].get("recovery", {})
                recovery_ready = "recovery" not in result["data"] or recovery_receipt_ready(
                    recovery, run, artifact, bridge_session)
                upstream_ready, prerequisite_at = False, recovery.get("generated_at_utc")
                if recovery_ready:
                    try:
                        upstream_at, upstream_evidence = read_upstream_prerequisite(
                            path, upstream, run, artifact, bridge_session, contract)
                        handoff, hashes = read_score_handoff(path, upstream,
                            contract["repository"], contract["max_member_bytes"])
                        result["data"]["score_handoff"] = handoff
                        result["files"].update(hashes)
                        result["files"].update(upstream_evidence)
                        prerequisite_at = max((x for x in (prerequisite_at, upstream_at) if x), key=timestamp)
                        upstream_ready = True
                    except Exception as exc:
                        # Optional admission cannot erase the primary monitor evidence.
                        result["theme_upstream_error"] = (str(exc) if isinstance(exc, ValueError)
                            and re.fullmatch(r"[a-z_]+", str(exc)) else "upstream_evidence_invalid")
                if (run.get("conclusion") == "success" and prerequisites.issubset(result["data"])
                        and upstream_ready):
                    bridge = theme_etf_source_bridge.read_bundle(
                        path, run, artifact, contract["theme_etf_bridge"], bridge_session, bridge_now,
                        prerequisite_at=prerequisite_at)
                else:
                    bridge = theme_etf_source_bridge.blocked("upstream_contract_not_ready", bridge_session)
                result["data"]["theme_etf_bridge"] = bridge
            if (key == "operating" and result["data"].get("upstream", {}).get("status") in READY_UPSTREAM
                    and "score_handoff" not in result["data"]):
                try:
                    handoff, hashes = read_score_handoff(path, result["data"]["upstream"],
                                                       contract["repository"], contract["max_member_bytes"])
                    result["data"]["score_handoff"] = handoff
                    result["files"].update(hashes)
                except Exception as exc:
                    # Preserve price/recovery evidence when the score graph fails.
                    result["score_handoff_error"] = (str(exc) if isinstance(exc, ValueError)
                        and re.fullmatch(r"[a-z_]+", str(exc)) else "score_handoff_invalid")
        result["artifact_hash_verified"] = True
        optional = set(spec.get("optional_members", []))
        if not optional.issubset(members):
            raise ValueError("unknown_optional_member")
        result["missing_members"] = sorted(set(members) - set(result["data"]) - optional)
        if run.get("conclusion") == "success":
            result["status"] = "MISSING_CONTRACT_MEMBERS" if result["missing_members"] else "VERIFIED_ARTIFACT"
    except Exception as exc:
        result["status"] = "BLOCKED_SOURCE"
        # Never echo exception text: urllib errors may contain signed URLs.
        result["error_type"] = type(exc).__name__
        if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]+", str(exc)):
            result["reason"] = str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            result["http_status"] = exc.code
        result["data"] = {}
    return result


def completed_session(now: datetime) -> str:
    import pandas_market_calendars as mcal
    schedule = mcal.get_calendar("NYSE").schedule(start_date=(now - timedelta(days=14)).date(),
                                                end_date=now.date())
    completed = schedule[schedule["market_close"] <= now - timedelta(minutes=90)]
    if completed.empty:
        raise ValueError("no_settled_us_session")
    return str(completed.index[-1].date())


def forward_a1_context(source: dict, session: str) -> dict:
    jobs = source.get("jobs", {})
    proxy = jobs.get("proxy_validation")
    managed_job = jobs.get("managed_refresh")
    proxy_view = {"status": "JOB_METADATA_ONLY" if proxy else "JOB_UNAVAILABLE",
                  "job": proxy, "session": None}
    managed = {"status": source.get("status", "MISSING_SOURCE"), "job": managed_job,
               "session": None, "checkpoint_sha256": None, "reason": None}
    report = source.get("data", {}).get("result", {})
    meter = source.get("data", {}).get("meter", {})
    run = source.get("run", {})
    if not (source.get("artifact_hash_verified") is True and managed_job
            and type(run.get("run_attempt")) is int and run["run_attempt"] == 1
            and meter.get("schema") == "a1-sip-campaign-meter-v1"
            and type(meter.get("run_id")) is int and meter["run_id"] == run.get("id")
            and type(meter.get("run_attempt")) is int and meter["run_attempt"] == 1
            and meter.get("source_sha") == run.get("head_sha")
            and meter.get("finalized") is True
            and all(item.get(k) is False for item in (report, meter)
                    for k in ("source_admission", "pit_verified", "economic_authority"))):
        if source.get("artifact_hash_verified") is True:
            managed["status"] = "MANAGED_EVIDENCE_UNVERIFIED"
        return {"proxy_validation": proxy_view, "managed_generation": managed}
    if (managed_job.get("conclusion") == "failure" and meter.get("status") == "BLOCKED"
            and report.get("status") == "BLOCKED"):
        reason = report.get("reason")
        managed.update(status="MANAGED_REFRESH_BLOCKED",
                       reason=reason if isinstance(reason, str) and re.fullmatch(r"[A-Z_]{1,100}", reason) else None)
    elif (managed_job.get("conclusion") == "success" and meter.get("status") == "COMPLETE"
          and report.get("status") == "REFRESH_CHECKPOINT_VERIFIED"
          and isinstance(report.get("checkpoint_sha256"), str)
          and re.fullmatch(r"[a-f0-9]{64}", report["checkpoint_sha256"])
          and meter.get("managed_checkpoint_sha256") == report["checkpoint_sha256"]):
        state = date_state(report.get("session"), session)
        managed["status"] = "MANAGED_CHECKPOINT_REPORTED_FOR_SESSION" if state == "CURRENT" else state
        if state == "CURRENT":
            managed.update(session=session, checkpoint_sha256=report["checkpoint_sha256"])
    else:
        managed["status"] = "MANAGED_EVIDENCE_UNVERIFIED"
    return {"proxy_validation": proxy_view, "managed_generation": managed}


def forward_a4_context(source: dict, session: str, now: datetime) -> dict:
    result = {"status": source.get("status", "MISSING_SOURCE"), "report_session": None,
              "source_session": None, "source_receipts": None, "risk_score": None,
              "reason_codes": []}
    if source.get("artifact_hash_verified") is not True:
        return result
    result["status"] = "A4_REPORT_UNVERIFIED"
    run, artifact = source.get("run", {}), source.get("artifact", {})
    report = source.get("data", {}).get("summary", {})
    market = report.get("market_analysis")
    if (type(run.get("run_attempt")) is not int or run["run_attempt"] != 1
            or run.get("conclusion") not in ("success", "failure")
            or report.get("schema_version") != "daily-crisis-monitor-v2"
            or report.get("research_only") is not True or report.get("auto_trade_allowed") is not False
            or not isinstance(market, dict) or market.get("schema") != "market-analysis-report-v1"
            or market.get("market") != "US"):
        return result
    if report.get("expected_session") != session or market.get("session") not in (None, session):
        result["status"] = "A4_SESSION_MISMATCH"
        return result
    try:
        generated = timestamp(report["generated_at_utc"])
        if not (timestamp(run["created_at"]) <= generated <= timestamp(artifact["created_at"]) <= now):
            raise ValueError("a4_report_clock")
        if market.get("cutoff") is not None and timestamp(market["cutoff"]) > generated:
            raise ValueError("a4_report_clock")
    except (KeyError, TypeError, ValueError, AttributeError):
        result["status"] = "A4_REPORT_CLOCK_UNVERIFIED"
        return result
    if market.get("status") == "DATA_BLOCKED":
        reasons = market.get("blockers", [])
        result.update(status="DATA_BLOCKED", report_session=session,
                      reason_codes=[r for r in reasons[:20] if isinstance(r, str)
                                    and re.fullmatch(r"[A-Z0-9_]{1,100}", r)]
                      if isinstance(reasons, list) else [])
    elif (run.get("conclusion") == "success" and market.get("status") == "READY_RESEARCH_ONLY"
          and market.get("session") == session and market.get("cutoff") is not None):
        result.update(status="RESEARCH_REPORT_AVAILABLE", report_session=session)
    return result


def forward_source_context(sources: dict, session: str, now: datetime) -> dict:
    form4 = sources.get("sec_form4", {})
    return {"a1": forward_a1_context(sources.get("a1_forward", {}), session),
            "a4": forward_a4_context(sources.get("a4_forward", {}), session, now),
            "sec_form4": {"status": form4.get("status", "MISSING_SOURCE"),
                          "run_conclusion": form4.get("run", {}).get("conclusion")
                          if form4.get("status") == "RUN_METADATA_ONLY" else None,
                          "filing_available_at": None, "source_session": None,
                          "source_receipt_sha256": None},
            "sec_13f": {"observation_key": "ownership", "scope": "QUARTERLY_DISCLOSURES"}}


def completion_trigger(client: GitHub, contract: dict, now: datetime, event: dict | None = None) -> dict:
    """Authenticate completion metadata; never dispatch or rerun its workflow."""
    if event is None:
        if os.environ.get("GITHUB_EVENT_NAME") != "workflow_run":
            return {"status": "NORMAL_MONITOR_ENTRY"}
        path = Path(os.environ["GITHUB_EVENT_PATH"])
        if path.stat().st_size > contract["reassessment"]["max_bytes"]:
            raise ValueError("completion_event_budget")
        event = theme_etf_source_bridge.decode_evidence_json(path.read_text(encoding="utf-8"))
    candidate = event.get("workflow_run", {})
    run_id = candidate.get("id")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("completion_run_identity")
    run = client.json(f"/actions/runs/{run_id}")
    workflows = contract["reassessment"]["completion_workflows"]
    if (run.get("name") not in workflows or run.get("path") != ".github/workflows/" + workflows[run["name"]]
            or run.get("head_branch") != contract["branch"]
            or any((run.get(k) or {}).get("full_name") != contract["repository"] for k in ("repository", "head_repository"))
            or run.get("event") not in ("schedule", "workflow_dispatch")
            or run.get("status") != "completed" or type(run.get("run_attempt")) is not int
            or run["run_attempt"] <= 0 or not isinstance(run.get("conclusion"), str)
            or not re.fullmatch(r"[a-f0-9]{40}", run.get("head_sha") or "")
            or any(candidate.get(k) != run.get(k) for k in ("id", "run_attempt", "head_sha", "head_branch", "event", "name"))
            or (candidate.get("head_repository") or {}).get("full_name") != contract["repository"]
            or not timestamp(run["created_at"]) <= timestamp(run["updated_at"]) <= now):
        raise ValueError("untrusted_completion_trigger")
    return {"status": "VERIFIED_COMPLETION_METADATA_ONLY", "run_id": run_id,
            "attempt": run["run_attempt"], "head_sha": run["head_sha"], "workflow": run["name"],
            "conclusion": run["conclusion"], "source_admission": False, "dispatch": False}


def cadence_observation(source: dict, session: str) -> dict:
    """Tier progress is a Source diagnostic, never holdings or price admission."""
    blocked = {"status": "CADENCE_UNVERIFIED", "daily_current": False,
               "whole_universe_current": False, "holdings_completeness": "UNKNOWN", "source_admission": False}
    result = source.get("data", {}).get("result", {})
    progress, binding = result.get("tier_progress"), result.get("cadence_binding_sha256")
    if (source.get("artifact_hash_verified") is not True or result.get("session") != session
            or not isinstance(binding, str) or not re.fullmatch(r"[a-f0-9]{64}", binding)
            or not isinstance(progress, dict)):
        return blocked
    counts = progress.get("by_tier", {})
    if set(counts) != {"DAILY", "WEEKLY"}:
        return blocked
    for row in counts.values():
        if (not isinstance(row, dict) or set(row) != {"CURRENT", "PENDING", "HELD"}
                or any(type(v) is not int or not 0 <= v <= 10000 for v in row.values())):
            return blocked
    outside, stale = progress.get("outside_scope", []), progress.get("stale_role_counts", {})
    if (not isinstance(outside, list) or len(outside) > 10000 or type(progress.get("weekly_due")) is not bool
            or date_state(progress.get("weekly_target_session"), session) not in {"CURRENT", "STALE"}
            or not isinstance(stale, dict) or len(stale) > 100
            or any(not isinstance(k, str) or not re.fullmatch(r"[A-Z_]{1,100}", k)
                   or type(v) is not int or not 0 <= v <= 10000 for k, v in stale.items())):
        return blocked
    daily = counts["DAILY"]
    return {"status": "SOURCE_CADENCE_REPORTED_ONLY", "cadence_binding_sha256": binding,
            "daily_current": sum(daily.values()) > 0 and daily["PENDING"] == daily["HELD"] == 0,
            "whole_universe_current": (sum(sum(r.values()) for r in counts.values()) > 0
                and all(r["PENDING"] == r["HELD"] == 0 for r in counts.values()) and not outside
                and (sum(counts["WEEKLY"].values()) == 0 or progress["weekly_target_session"] == session)),
            "by_tier": counts, "weekly_due": progress.get("weekly_due"),
            "weekly_target_session": progress.get("weekly_target_session"),
            "outside_scope_count": len(outside),
            "holdings_completeness": progress.get("holdings_completeness", "UNKNOWN"),
            "stale_role_counts": stale, "source_admission": False}


def _review_source_row(key: str, source: dict, session: str, now: datetime) -> tuple[dict | None, dict]:
    run = source.get("run", {})
    if (type(run.get("id")) is not int or run["id"] <= 0
            or type(run.get("run_attempt")) is not int or run["run_attempt"] <= 0
            or not re.fullmatch(r"[a-f0-9]{40}", run.get("head_sha") or "")):
        raise ValueError("source_review_identity_missing")
    collected, available = timestamp(source["metadata_collected_at"]), timestamp(run["updated_at"])
    if not timestamp(run["created_at"]) <= available <= collected <= now:
        raise ValueError("source_review_clock")
    reference = {"source": key, "run": {k: run.get(k) for k in
        ("id", "run_attempt", "head_sha", "created_at", "updated_at", "status", "conclusion")},
        "artifact_sha256": source.get("artifact", {}).get("digest"),
        "members": {k: {"sha256": v.get("sha256"), "bytes": v.get("bytes")}
                    for k, v in source.get("files", {}).items()}, "observed_at": collected.isoformat()}
    # These clocks concern the observed workflow status, not publication or
    # collection of underlying prices. No private values enter public snapshots.
    status = "FAILED" if source.get("status") in {"UPSTREAM_FAILED", "BLOCKED_SOURCE"} else "MISSING"
    values, period = {"source_status": source.get("status", "MISSING_SOURCE")}, available.date().isoformat()
    if key == "a1_forward":
        managed = forward_a1_context(source, session)["managed_generation"]
        values["source_status"] = managed["status"]
        if managed["status"] == "MANAGED_CHECKPOINT_REPORTED_FOR_SESSION":
            # A checked producer checkpoint is neither missing nor a changed
            # economic REGIME. Preserve its proof without scheduling A5 risk.
            reference.update(reason=managed["status"],
                classification="PRODUCER_COMPLETION_ONLY_NOT_ECONOMIC_OBSERVATION",
                producer_evidence={k: managed[k] for k in ("status", "session", "checkpoint_sha256")},
                source_admission=False, pit_verified=False, economic_authority=False)
            return None, reference
        if managed["status"] == "STALE":
            status = "STALE"
        elif managed["status"] in {"MANAGED_REFRESH_BLOCKED", "MANAGED_EVIDENCE_UNVERIFIED", "FUTURE"}:
            status = "FAILED"
    if key == "a4_forward":
        view = forward_a4_context(source, session, now)
        values = {"source_status": view["status"], "reason_codes": view["reason_codes"]}
        period = view["report_session"] or period
        model = source.get("data", {}).get("summary", {}).get("market_analysis", {}).get("market_assessment", {})
        if (view["status"] == "RESEARCH_REPORT_AVAILABLE" and isinstance(model, dict)
                and model.get("status") == "READY_RESEARCH_ONLY"
                and isinstance(model.get("state"), str) and model["state"]
                and number(model.get("risk_score")) is not None and isinstance(model.get("axes"), list)):
            # Digest actual incumbent state/risk/axes, not a READY label. Never
            # publish price-derived numbers from those private originals.
            values["market_assessment"] = {k: model.get(k) for k in
                ("state", "observed_state", "risk_score", "axes", "ready_axis_count", "required_axes_ready",
                 "fear_recovery_stage", "contract_sha256")}
            status = "OBSERVED"
        else:
            status = "FAILED"
    row = dict(family="REGIME", provider="GITHUB_ACTIONS_METADATA", entity_kind="MARKET",
        entity_id="monitor:" + key, metric="report_status", fiscal_period=None, observation_period=period,
        identity={"scope": "REPORT_STATUS_ONLY"}, values={"semantic_sha256": reassessment.digest(values)},
        status=status, available_at=available.isoformat(), collected_at=collected.isoformat(),
        revision_id="report-status-v1", source_sha256=reassessment.digest(reference), causal_event_id=None)
    reference["reason"] = values["source_status"]
    return row, reference


def published_etf_reviews(source: dict, contract: dict, now: datetime) -> list[dict]:
    """Read the producer's decoder/readback capsule from the same hashed member.

    This observes reviewed producer code and immutable publication provenance;
    it grants no Source/ER/PIT admission. A3 still rereads private originals.
    """
    helper = run287_etf_rotation
    obs, capsule = (source.get("data", {}).get(k, {}) for k in ("etf_rotation", "etf_safe_review"))
    run, artifact = source.get("run", {}), source.get("artifact", {})
    if (source.get("artifact_hash_verified") is not True or obs.get("a3_handoff_status") != "REVIEW_REQUESTS_READY"
            or not re.fullmatch(r"[a-f0-9]{64}", source.get("files", {}).get("etf_rotation", {}).get("sha256", ""))
            or len(helper.canonical(capsule)) > 131072 or capsule.get("schema") != "etf-published-review-handoff-v1"):
        raise ValueError("published_etf_original_missing")
    unsigned = {k: v for k, v in capsule.items() if k != "binding_sha256"}
    _, watch, policy_sha = helper.policy(contract)
    if (capsule.get("binding_sha256") != helper.sha256(helper.canonical(unsigned))
            or capsule.get("private_payload_sha256") != obs.get("private_payload_sha256")
            or capsule.get("readback_sha256") != obs.get("private_payload_sha256")
            or not re.fullmatch(r"[a-f0-9]{64}", capsule.get("readback_sha256") or "")
            or capsule.get("producer") != obs.get("producer")
            or capsule.get("producer") != {"run_id": run.get("id"), "run_attempt": run.get("run_attempt"), "head_sha": run.get("head_sha")}
            or capsule.get("observed_at_utc") != obs.get("observed_at_utc") or capsule.get("session") != obs.get("session")
            or capsule.get("policy_sha256") != policy_sha or capsule.get("safety") != helper.SAFETY
            or capsule.get("decoder") != "tools.run287_etf_rotation.decode_a3_review_requests"
            or capsule.get("decoder_git_lf_sha256") != hashlib.sha256(Path(helper.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            or capsule.get("producer_git_lf_sha256") != hashlib.sha256((ROOT / "tools/etf_leadership_snapshot.py").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            or not timestamp(run["created_at"]) <= timestamp(capsule["observed_at_utc"])
                <= timestamp(artifact["created_at"]) <= timestamp(source["metadata_collected_at"]) <= now):
        raise ValueError("published_etf_provenance_refused")
    requests = capsule.get("requests")
    if not isinstance(requests, list) or len(requests) != obs["counts"]["a3_review_requests"]:
        raise ValueError("published_etf_count")
    seen = set()
    fields = {"request_id", "agent", "subject", "status", "event_family", "requested_slices", "requires", "execute"}
    for request in requests:
        ticker = request.get("subject", {}).get("ticker")
        if (set(request) != fields or request["subject"] != {"market": "US", "ticker": ticker}
                or ticker not in watch or ticker in seen or request["agent"] != "A3"
                or request["request_id"] != helper.a3_request_id(obs["session"], request["subject"])
                or request["status"] != "REVIEW_REQUIRED" or request["event_family"] != "LEADERSHIP"
                or request["requested_slices"] != list(helper.A3_SLICES)
                or request["requires"] != list(helper.A3_REQUIREMENTS) or request["execute"] is not False):
            raise ValueError("published_etf_request")
        seen.add(ticker)
    return copy.deepcopy(requests)


def _review_parameter_proposals(plan: dict, *, new_event_ids: list[str],
                                contract_identity: dict, previous_contract_identity: dict | None) -> dict:
    # Recollection alone is suppressed; a changed contract still needs its
    # original review proposals even when persistent failure event IDs repeat.
    if not new_event_ids and previous_contract_identity == contract_identity:
        return {}
    return reassessment.a0_parameter_proposals(plan)


def reassessment_handoff(sources: dict, session: str, now: datetime, contract: dict, *,
                         previous: dict | None = None, private_etf_payload: bytes | None = None,
                         code_sha: str | None = None) -> dict:
    """Reuse existing semantic planning; isolated missing scopes stay visible."""
    spec = contract["reassessment"]
    blocked, rows, refs, original_expiries = [], [], [], []
    for key, source in sorted(sources.items()):
        try:
            row, ref = _review_source_row(key, source, session, now)
            if row is None:
                refs.append(ref)
                continue
            extra = []
            if key == "a4_forward" and row["status"] == "OBSERVED":
                original = source["data"]["summary"]["market_analysis"].get("candidate_reassessment_snapshot")
                if original is not None:
                    reassessment.verify(original, "review-observation-snapshot-v1")
                    if original != reassessment.snapshot(original["rows"], scope_id=original["scope_id"],
                            cutoff=original["cutoff"], expires_at=original["expires_at"]):
                        raise ValueError("a4_original_snapshot_refused")
                    market_cutoff = source["data"]["summary"]["market_analysis"]["cutoff"]
                    if (timestamp(original["cutoff"]) != timestamp(market_cutoff)
                            or not timestamp(original["cutoff"]) <= now < timestamp(original["expires_at"])):
                        row["status"] = "FAILED"
                        ref["reason"] = "A4_ORIGINAL_SNAPSHOT_EXPIRED_OR_CUTOFF_MISMATCH"
                        original = None
                    else:
                        original_expiries.append(timestamp(original["expires_at"]))
                        ref["child_snapshot"] = {k: original[k] for k in ("content_sha256", "cutoff", "expires_at")}
                    for item in original["rows"] if original else []:
                        # Keep original identity/clocks/receipt SHA; expose only
                        # its existing semantic digest, never the source value.
                        extra.append({**item, "values": {"semantic_sha256":
                            reassessment.digest(reassessment.semantic(item))}})
            rows.extend([row, *extra]); refs.append(ref)
        except (ValueError, TypeError, KeyError, AttributeError):
            blocked.append({"scope": key, "reason": "ORIGINAL_SOURCE_IDENTITY_OR_CLOCK_MISSING"})
    if len(rows) > spec["max_rows"]:
        raise ValueError("review_row_budget")
    etf_source = sources.get("tactical", {})
    rotation = etf_source.get("data", {}).get("etf_rotation", {})
    etf_requests = []
    try:
        etf_requests = (run287_etf_rotation.decode_a3_review_requests(rotation, private_etf_payload, contract)
                        if private_etf_payload is not None else published_etf_reviews(etf_source, contract, now))
        # ETF leadership is a verified market review catalyst, not an invented
        # company/issuer exposure. The incumbent bridge supplies A5's requires.
        available = timestamp(rotation["observed_at_utc"])
        collected = timestamp(etf_source["metadata_collected_at"])
        if not available <= collected <= now:
            raise ValueError("etf_review_clock")
        if etf_requests:
            ids = sorted(r["request_id"] for r in etf_requests)
            rows.append(dict(family="REGIME", provider="EXISTING_ETF_ROTATION", entity_kind="MARKET",
                entity_id="ETF_ROTATION", metric="verified_review_batch", fiscal_period=None,
                observation_period=rotation["session"], identity={"policy_sha256": rotation["policy_sha256"]},
                values={"semantic_sha256": reassessment.digest(ids)}, status="OBSERVED",
                available_at=available.isoformat(), collected_at=collected.isoformat(),
                revision_id="etf-review-v1", source_sha256=rotation["private_payload_sha256"],
                causal_event_id=reassessment.digest(ids)))
    except (ValueError, TypeError, KeyError, AttributeError):
        etf_requests = []
        blocked.append({"scope": "etf", "reason": "PRIVATE_ETF_PAYLOAD_OR_CHECKED_PUBLICATION_MISSING_NO_RECONSTRUCTION",
                        "expected_sha256": rotation.get("private_payload_sha256")})
    result = {"schema": spec["schema"], "status": "PARTIAL_REVIEW_ONLY", "session": session,
        "source_refs": refs, "blocked_scopes": blocked, "global_scope_complete": False,
        "holdings_status": "ACCEPTED_HOLDINGS_NOT_CONNECTED", "consumption_ack": False,
        "execution_completed": False, "parameter_proposals": {}, "review_requests": [],
        "intake_export": {"status": "BLOCKED_CANONICAL_INTAKE_MISSING", "next_packet": {
            "required": ["fresh full source_intake", "original evidence_root", "original request roles/model/hash/clock",
                         "current A3/ER/A4/A6 evidence"], "synthesize_missing_roles": False}},
        "safety": dict(reassessment.CLOSED)}
    if not spec.get("exposure_index"):
        blocked.append({"scope": "company_exposures", "reason": "VERIFIED_EXPOSURE_INDEX_MISSING_UNMAPPED_RETAINED"})
    previous = previous if isinstance(previous, dict) and previous.get("schema") == spec["schema"] else None
    code_sha = code_sha or os.environ.get("GITHUB_SHA", "")
    if re.fullmatch(r"[a-f0-9]{40}", code_sha or ""):
        cutoff = now.isoformat()
        expiry = min([now + timedelta(hours=spec["expiry_hours"]), *original_expiries]).isoformat()
        index = spec.get("exposure_index") or reassessment.exposure_index(
            candidates=[], edges=[], available_at=cutoff, expires_at=expiry)
        scope = "monitor:" + reassessment.digest(sorted(reassessment.row_key(r) for r in rows))[:24]
        current = reassessment.snapshot(rows, scope_id=scope, cutoff=cutoff, expires_at=expiry)
        identity = dict(code_sha=code_sha, config_sha256=reassessment.digest(spec), model_version=spec["profile"],
            parameters_sha256=reassessment.digest({"scope": scope}),
            dependency_sha256=hashlib.sha256(Path(reassessment.__file__).read_bytes()).hexdigest())
        prior = previous.get("current_snapshot") if previous else None
        if prior and prior.get("scope_id") != scope:
            prior = None; blocked.append({"scope": "comparison", "reason": "SCOPE_CHANGED_REAUDIT"})
        try:
            plan = reassessment.plan_reassessment(prior, current, index, now=cutoff, contract_identity=identity,
                previous_contract_identity=previous.get("contract_identity") if prior else None,
                previous_index_sha256=previous.get("exposure_index", {}).get("content_sha256") if prior else None)
            result.update(plan=plan, proposal_plan=plan, current_snapshot=current, exposure_index=index,
                          contract_identity=identity,
                          comparison_snapshot=prior,
                          comparison_contract_identity=previous.get("contract_identity") if prior else None,
                          comparison_index_sha256=previous.get("exposure_index", {}).get("content_sha256") if prior else None)
            old_ids = {e["event_id"] for e in previous.get("plan", {}).get("events", [])} if previous else set()
            result["new_event_ids"] = sorted(e["event_id"] for e in plan["events"] if e["event_id"] not in old_ids)
            result["parameter_proposals"] = _review_parameter_proposals(plan,
                new_event_ids=result["new_event_ids"], contract_identity=identity,
                previous_contract_identity=result["comparison_contract_identity"])
            for intent in plan["review_intents"]:
                result["review_requests"].append({**intent, "request_id": reassessment.digest(intent),
                                                 "source_refs": refs, "authority": "REVIEW_ONLY"})
        except (ValueError, TypeError, KeyError):
            blocked.append({"scope": "bridge", "reason": "BRIDGE_OR_PREVIOUS_ORIGINAL_REFUSED"})
    else:
        blocked.append({"scope": "bridge", "reason": "CURRENT_CODE_IDENTITY_MISSING"})
    if previous and previous.get("contract_identity") == result.get("contract_identity"):
        current_ids = {r["request_id"] for r in result["review_requests"]}
        for old in previous.get("review_requests", []):
            # Keep open bridge requests visible; a prior monitor is not an A0
            # ACK or current evidence. ETF metadata is never a substitute for
            # replaying its private original payload below.
            if "event_ids" in old and old["request_id"] not in current_ids:
                result["review_requests"].append({**copy.deepcopy(old),
                    "pending_scope": "PRIOR_REVIEW_NOT_CURRENT_EVIDENCE"})
    if len(result["review_requests"]) > spec["max_rows"]:
        raise ValueError("pending_review_budget")
    if etf_requests:
            cause = [e["event_id"] for e in result.get("plan", {}).get("events", []) if e.get("entity_id") == "ETF_ROTATION"]
            for request in etf_requests:
                safe = {k: request[k] for k in ("request_id", "agent", "subject", "status", "event_family",
                                                "requested_slices", "requires", "execute")}
                result["review_requests"].append({**safe, "authority": "REVIEW_ONLY", "causal_event_ids": cause,
                    "source_refs": [{"private_payload_sha256": rotation["private_payload_sha256"]}]})
            result["etf_parameter_proposals"] = {"A3": {"etf_rotation_review": {
                "requests": [r for r in result["review_requests"] if "subject" in r],
                "private_payload_sha256": rotation["private_payload_sha256"]}}}
            result["etf_observation"] = copy.deepcopy(rotation)
            if private_etf_payload is None:
                # Retain public-safe original proof needed for export replay,
                # never raw payloads, tactical price rows or private holdings.
                result["etf_publication_source"] = {
                    "artifact_hash_verified": etf_source.get("artifact_hash_verified"),
                    "metadata_collected_at": etf_source.get("metadata_collected_at"),
                    "run": {k: etf_source.get("run", {}).get(k) for k in
                        ("id", "run_attempt", "head_sha", "created_at", "updated_at", "status", "conclusion")},
                    "artifact": {k: etf_source.get("artifact", {}).get(k) for k in ("id", "digest", "created_at")},
                    "files": {"etf_rotation": etf_source.get("files", {}).get("etf_rotation")},
                    "data": {"etf_rotation": copy.deepcopy(rotation),
                             "etf_safe_review": copy.deepcopy(etf_source.get("data", {}).get("etf_safe_review"))}}
    result["review_intake_id"] = reassessment.digest({"requests": sorted(r["request_id"] for r in result["review_requests"]),
                                                    "profile": spec["profile"]})
    return result


def export_review_intake(intake: dict, handoff: dict, evidence_root: Path, now: datetime, code_sha: str,
                        *, private_etf_payload: bytes | None = None, contract: dict | None = None) -> tuple[dict, dict]:
    """Return a private full intake changing parameters only, never a state."""
    from tools import materialize_system_state as materializer
    if len(json.dumps(intake, allow_nan=False).encode()) > 2_000_000:
        raise ValueError("intake_budget")
    if (handoff.get("contract_identity", {}).get("code_sha") != code_sha
            or handoff["contract_identity"]["dependency_sha256"] !=
            hashlib.sha256(Path(reassessment.__file__).read_bytes()).hexdigest()):
        raise ValueError("intake_review_code_changed")
    materializer.intake_validate(intake, now)
    replay = reassessment.plan_reassessment(handoff.get("comparison_snapshot"), handoff["current_snapshot"],
        handoff["exposure_index"], now=handoff["current_snapshot"]["cutoff"],
        contract_identity=handoff["contract_identity"], previous_contract_identity=handoff.get("comparison_contract_identity"),
        previous_index_sha256=handoff.get("comparison_index_sha256"))
    expected = _review_parameter_proposals(replay, new_event_ids=handoff.get("new_event_ids"),
        contract_identity=handoff["contract_identity"],
        previous_contract_identity=handoff.get("comparison_contract_identity"))
    if replay != handoff["plan"] or expected != handoff["parameter_proposals"]:
        raise ValueError("intake_proposal_original_required")
    merged, missing = copy.deepcopy(intake), []
    requests = {r["agent"]: r for r in merged.get("requests", [])}
    if len(requests) != len(merged.get("requests", [])):
        raise ValueError("intake_duplicate_agents")
    proposals = copy.deepcopy(handoff["parameter_proposals"])
    if handoff.get("etf_parameter_proposals"):
        if contract is None:
            contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        if private_etf_payload is not None:
            decoded = run287_etf_rotation.decode_a3_review_requests(handoff["etf_observation"], private_etf_payload, contract)
        elif handoff.get("etf_publication_source"):
            decoded = published_etf_reviews(handoff["etf_publication_source"], contract, now)
        else:
            raise ValueError("intake_etf_original_required")
        causes = [e["event_id"] for e in replay["events"] if e.get("entity_id") == "ETF_ROTATION"]
        fields = ("request_id", "agent", "subject", "status", "event_family", "requested_slices", "requires", "execute")
        checked = [{**{k: r[k] for k in fields}, "authority": "REVIEW_ONLY", "causal_event_ids": causes,
            "source_refs": [{"private_payload_sha256": handoff["etf_observation"]["private_payload_sha256"]}]} for r in decoded]
        exact = {"A3": {"etf_rotation_review": {"requests": checked,
                 "private_payload_sha256": handoff["etf_observation"]["private_payload_sha256"]}}}
        if handoff["etf_parameter_proposals"] != exact:
            raise ValueError("intake_etf_proposal_injection")
        proposals.setdefault("A3", {}).update(exact["A3"])
    for agent, proposal in proposals.items():
        if agent not in requests:
            missing.append(agent); continue
        request = requests[agent]
        if set(request["inputs"]) != set(materializer.board.contracts()["agents"][agent]["inputs"]):
            raise ValueError("intake_existing_role_mismatch")
        for key, value in proposal.items():
            if key in request["parameters"] and request["parameters"][key] != value:
                raise ValueError("intake_existing_parameter_conflict")
            request["parameters"][key] = copy.deepcopy(value)
    state = materializer.materialize(merged, evidence_root, now, code_sha)
    materializer.verify_state(state, merged, evidence_root, now, code_sha)
    return merged, {"status": "MATERIALIZER_CONSUMABLE_REVIEW_ONLY", "missing_request_templates": missing,
        "state_sha256": state["state_sha256"], "g0_status": state["g0"]["status"],
        "unresolved_blocker_count": len(state["blockers"]), "consumption_ack": False,
        "execute": False, "A5_decision_completed": False}


def evaluate(sources: dict, session: str, now: datetime, contract: dict, *, previous=None,
             private_etf_payload=None) -> dict:
    alerts, observations = [], {}
    observations["theme_etf_bridge"] = theme_etf_source_bridge.observation(sources.get("operating", {}), session)
    if contract.get("forward_context_sources"):
        observations["forward_source_context"] = forward_source_context(sources, session, now)
    bridge_observation = observations["theme_etf_bridge"]
    if not bridge_observation["runtime_executed"]:
        alerts.append("theme_etf:" + str(bridge_observation["reason"]))
    for key in contract["sources"]:
        source = sources.get(key, {})
        if source.get("status") != "VERIFIED_ARTIFACT":
            alerts.append(f"{key}:{source.get('status', 'MISSING_SOURCE')}")
        for member in source.get("missing_members", []):
            alerts.append(f"{key}:MISSING_CONTRACT_MEMBER:{member}")
        created = (source.get("run") or {}).get("created_at")
        if created:
            try:
                if timestamp(created) > now:
                    alerts.append(f"{key}:FUTURE_RUN")
            except ValueError:
                alerts.append(f"{key}:INVALID_RUN_TIME")
    data = lambda key: sources.get(key, {}).get("data", {})
    recovery = data("operating").get("recovery", {})
    observations["operating_recovery"] = {k: recovery.get(k) for k in ("status", "next_action")}
    if str(recovery.get("status", "")).startswith("BLOCKED"):
        alerts.append("operating:" + str(recovery["status"]))
    tactical = data("tactical").get("summary", {})
    if contract.get("etf_rotation"):
        rotation = data("tactical").get("etf_rotation", {"status": "MISSING_RECEIPT"})
        observations["etf_rotation"] = rotation
        if rotation["status"] != "CURRENT":
            alerts.append("etf_rotation:" + rotation["status"])
        if rotation.get("a3_handoff_status") == "PRIVATE_HANDOFF_BLOCKED":
            alerts.append("etf_rotation:PRIVATE_HANDOFF_BLOCKED")
    for key in ("data_as_of", "latest_scored_rebalance_date"):
        state = date_state(tactical.get(key), session)
        observations[f"tactical_{key}"] = {"date": tactical.get(key), "state": state}
        if state != "CURRENT":
            alerts.append(f"tactical:{key}:{state}")
    upstream = data("operating").get("upstream", {})
    upstream_date = upstream.get("valuation_price_cutoff_date")
    observations["current_decision_inputs"] = {"status": upstream.get("status"), "date": upstream_date}
    if upstream.get("status") not in READY_UPSTREAM or date_state(upstream_date, session) != "CURRENT":
        alerts.append("operating:CURRENT_DECISION_INPUTS_UNAVAILABLE")
    estimates = data("estimates").get("summary", {})
    coverage = number(estimates.get("request_estimate_coverage_ratio"))
    fetch_date = estimates.get("fetch_date")
    observations["estimates"] = {"request_coverage": coverage,
                                "collector_status": estimates.get("collector_status"),
                                "fetch_date": fetch_date,
                                "archive_coverage": number(estimates.get("coverage_ratio"))}
    # Collection date is not an earnings period or exact market-close date.
    if not collection_current(fetch_date, session, now):
        alerts.append("estimates:MISSING_STALE_OR_FUTURE_FETCH_DATE")
    if coverage is None or not 0 <= coverage <= 1 or coverage < 1:
        alerts.append("estimates:PARTIAL_OR_UNKNOWN_FORWARD_ESTIMATE_COVERAGE")
    if str(estimates.get("collector_status", "")).startswith("blocked"):
        alerts.append("estimates:COLLECTOR_BLOCKED")
    price_archive = data("estimates").get("prices", {})
    observations["independent_price_archive"] = {k: price_archive.get(k) for k in
                                                ("start", "end", "common_coverage_end", "actual_cached_ticker_count")}
    observations["independent_price_archive"]["meaning"] = "Coverage metadata only; archived price bytes are not included in this source artifact."
    if date_state(price_archive.get("common_coverage_end"), session) != "CURRENT":
        alerts.append("estimates:INDEPENDENT_PRICE_COVERAGE_NOT_CURRENT")
    ownership = data("ownership").get("summary", {}).get("13f_freshness", {})
    observations["ownership"] = {k: ownership.get(k) for k in
                                 ("as_of_date", "required_due_period_end", "latest_accepted_at", "selected_manager_coverage")}
    observations["ownership"]["meaning"] = "Disclosed quarterly holdings, not current institutional buying."
    observations["ownership"]["existing_weights"] = data("ownership").get("summary", {}).get("weights")
    observations["ownership"]["weights_validated_by_monitor"] = False
    ownership_usable = (sources.get("ownership", {}).get("status") == "VERIFIED_ARTIFACT"
                        and ownership.get("freshness_ready") is True
                        and collection_current(ownership.get("as_of_date"), session, now))
    if not ownership_usable:
        alerts.append("ownership:MISSING_STALE_OR_BLOCKED_DISCLOSURE_SNAPSHOT")
    indexed = {}
    for row in data("ownership").get("ranked", []):
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker in indexed:
            alerts.append("ownership:DUPLICATE_TICKER")
            ownership_usable = False
        indexed[ticker] = row
    price_rows = data("operating").get("prices", [])
    prices, duplicates = {}, set()
    for row in price_rows:
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker in prices:
            duplicates.add(ticker)
        prices[ticker] = row
    market = data("operating").get("market", {})
    observations["market_snapshot"] = {k: market.get(k) for k in
                                        ("asof_date", "latest_price_date_min", "latest_price_date_max",
                                         "ticker_count", "exact_asof_close_count")}
    price_source_verified = sources.get("operating", {}).get("artifact_hash_verified") is True
    if duplicates:
        alerts.append("operating:DUPLICATE_PRICE_TICKERS")
    score_handoff, score_rows = evaluate_score_handoff(sources.get("operating", {}), session, now)
    observations["engine_score_handoff"] = score_handoff
    if not score_handoff["ready"]:
        alerts.append("operating:" + score_handoff["status"])
    # The source artifact is diagnostic. Accepted Drive-backed account state
    # requires a separate receipt; this collector never substitutes a replay.
    observations["accepted_portfolio"] = {
        "status": "ACCEPTED_ACCOUNT_SOURCE_NOT_CONNECTED", "current_weights_ready": False,
        "trade_history_ready": False, "performance_ready": False,
        "meaning": "Current weights, trades and CAGR/MDD require a verified accepted-account handoff."}
    watchlist = []
    for market, tickers in contract["watchlist"].items():
        for ticker in tickers:
            row = indexed.get(ticker, {}) if market == "US" and ownership_usable else {}
            available = row.get("latest_available_from")
            try:
                usable_row = bool(available and timestamp(available) <= now)
            except ValueError:
                usable_row = False
            price = prices.get(ticker, {}) if market == "US" and price_source_verified else {}
            price_state = date_state(price.get("latest_price_date"), session)
            close = number(price.get("previous_close"))
            if ticker in duplicates:
                price_state = "DUPLICATE_TICKER"
            if close is None or close <= 0:
                price_state = "MISSING_OR_INVALID_PRICE"
            engine = score_rows.get(ticker) if market == "US" else None
            engine_status = ("KR_ADAPTER_REQUIRED" if market == "KR" else
                             score_handoff["status"] if not score_handoff["ready"] else
                             "TICKER_NOT_IN_SCORE_EXPORT" if engine is None else
                             "CURRENT_NONRANKING_DIAGNOSTIC")
            if market == "US" and score_handoff["ready"] and engine is None:
                alerts.append(f"operating:SCORE_TICKER_MISSING:{ticker}")
            watchlist.append({"market": market, "ticker": ticker,
                              "price_as_of": price.get("latest_price_date"),
                              "price_status": price_state,
                              "close": close if price_state == "CURRENT" else None,
                              "currency": price.get("currency") if price_state == "CURRENT" else None,
                              "ownership_score": number(row.get("smart_money_score")) if usable_row else None,
                              "ownership_available_from": available,
                              "current_engine_score": engine["score"] if engine is not None else None,
                              "current_engine_status": engine_status,
                              "engine_score_as_of": score_handoff["score_as_of"] if market == "US" else None,
                              "engine_code_sha": score_handoff.get("engine_code_sha") if engine is not None else None,
                              "engine_research_eligible": engine["research_eligible_after_quarantine"] if engine is not None else None,
                              "engine_critical_data_complete": engine["critical_data_complete"] if engine is not None else None,
                              "engine_critical_missing_fields": engine["critical_missing_fields"] if engine is not None else None,
                              "engine_corporate_action_quarantine": engine["corporate_action_quarantine"] if engine is not None else None,
                              "engine_missing_neutral_applied": engine["missing_neutral_applied"] if engine is not None else None,
                              "research_status": "PRIMARY_SOURCE_REVIEW_REQUIRED",
                              "a3_rotation_batch_status": (observations.get("etf_rotation", {}).get(
                                  "a3_handoff_status", "UNAVAILABLE") if market == "US" else "OUTSIDE_US_SCOPE"),
                              "a3_rotation_batch_sha256": (observations.get("etf_rotation", {}).get(
                                  "private_payload_sha256") if market == "US" else None),
                              "data_gap": "KR_ADAPTER_REQUIRED" if market == "KR" else
                              "PRICE_FINANCIAL_MOAT_AND_SELECTOR_REVIEW_REQUIRED" if engine is not None else
                              "PRICE_FINANCIAL_MOAT_AND_SCORE_HANDOFF_REQUIRED"})
    report = {"schema_version": SCHEMA, "generated_at_utc": now.isoformat(),
            "expected_us_session": session, "repository": contract["repository"],
            "status": "ATTENTION_REQUIRED" if alerts else "OBSERVATIONS_COLLECTED",
            "current_investment_ranking_ready": False,
            "current_engine_scores_ready": score_handoff["ready"],
            "current_portfolio_ready": False,
            "alerts": sorted(set(alerts)), "observations": observations,
            "sources": {k: {a: b for a, b in v.items() if a != "data"} for k, v in sources.items()},
            "watchlist": watchlist, "research_questions": contract["research_questions"],
            "score_policy": contract["score_policy"], "safety": contract["safety"]}
    report["observations"]["cadence"] = cadence_observation(sources.get("a1_forward", {}), session)
    # This path is independent of legacy accepted-account/frontier health.
    report["reassessment"] = reassessment_handoff(sources, session, now, contract,
        previous=previous, private_etf_payload=private_etf_payload)
    return report


def render(report: dict) -> str:
    rows = ["# Run287 Daily Research Handoff", "",
            f"Expected US close: {report['expected_us_session']} · {report['status']}", "",
            "Current investment ranking: **withheld**. This is source monitoring and research input, not an accepted portfolio publication.",
            "", "| Source | Collection | Run |", "|---|---|---|"]
    for key, source in report["sources"].items():
        run = source.get("run", {})
        link = f"https://github.com/{report['repository']}/actions/runs/{run.get('id', '')}"
        rows.append(f"| {key} | {source.get('status')} | [{run.get('id', 'missing')}]({link}) |")
    rows.extend(["", "## Data dates and coverage", "", "```json",
                 json.dumps(report["observations"], ensure_ascii=False, indent=2), "```",
                 "", "## Items to resolve", ""])
    rows.extend(f"- {item}" for item in report["alerts"])
    rows.extend(["", "## Research queue", "",
                 "| Market | Ticker | Close / date | Engine score / status | Disclosed ownership score | Data gap |", "|---|---|---|---|---|---|"])
    for row in report["watchlist"]:
        score = row["ownership_score"]
        price = f"{row['close']} / {row['price_as_of']}" if row['close'] is not None else row['price_status']
        engine = row["current_engine_score"]
        engine_text = f"{engine:.6f} / {row['engine_score_as_of']} (nonranking)" if engine is not None else row["current_engine_status"]
        rows.append(f"| {row['market']} | {row['ticker']} | {price} | {engine_text} | {score if score is not None else 'unavailable'} | {row['data_gap']} |")
    rows.extend(["", report["score_policy"], "",
                 "KR exchange calendar, long price history, financial estimates and source-cited moat research remain separate inputs. No US-relative score is imputed for KR tickers.", ""])
    review = report.get("reassessment", {})
    rows.extend(["## A3 / A5 review handoff", "",
                 "Review requests are not consumption ACKs, completed analysis, weights or orders.",
                 f"Scope: {review.get('status')} / intake: {review.get('intake_export', {}).get('status')}", "",
                 "| Agent | Stable request | Reason / slices | Requires |", "|---|---|---|---|"])
    for request in review.get("review_requests", []):
        rows.append("| " + " | ".join((request["agent"], request["request_id"],
            ", ".join(request.get("slices", request.get("requested_slices", []))),
            ", ".join(request["requires"]))) + " |")
    rows.extend("- " + item["scope"] + ": " + item["reason"] for item in review.get("blocked_scopes", []))
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--canonical-inputs", type=Path)
    parser.add_argument("--expected-intake-sha256")
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--private-intake-output", type=Path)
    parser.add_argument("--private-etf-payload", type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    if contract.get("schema_version") != SCHEMA or contract.get("branch") != "master":
        raise ValueError("monitor_contract_invalid")
    # New report directory only; never overwrite an existing evidence set.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    now = datetime.now(timezone.utc)
    client = GitHub(contract["repository"], os.environ.get("GH_TOKEN", ""))
    trigger = completion_trigger(client, contract, now)
    session = completed_session(now)
    forward_specs = contract.get("forward_context_sources", {})
    if set(contract["sources"]).intersection(forward_specs):
        raise ValueError("forward_source_key_conflict")
    sources = {k: collect_source(client, k, spec, contract, now=now, session=session)
               for k, spec in {**contract["sources"], **forward_specs}.items()}
    prior_source = collect_source(client, "previous_monitor", contract["reassessment"]["previous_monitor"],
                                 contract, now=now, session=session)
    prior_report = prior_source.get("data", {}).get("report", {})
    previous = (prior_report.get("reassessment") if prior_source.get("artifact_hash_verified") is True
                and prior_source.get("status") == "VERIFIED_ARTIFACT"
                and prior_report.get("repository") == contract["repository"] else None)
    private_etf = None
    if args.private_etf_payload:
        if args.private_etf_payload.stat().st_size > 1_000_000:
            raise ValueError("private_etf_payload_budget")
        private_etf = args.private_etf_payload.read_bytes()
    report = evaluate(sources, session, now, contract, previous=previous, private_etf_payload=private_etf)
    report["completion_trigger"] = trigger
    report["review_comparison"] = {"status": prior_source.get("status"),
                                    "run": prior_source.get("run"), "consumption_ack": False}
    report["code_sha"] = os.environ.get("GITHUB_SHA", "local-unpublished")
    report["contract_sha256"] = hashlib.sha256(args.contract.read_bytes()).hexdigest()
    if args.canonical_inputs:
        try:
            if (args.canonical_inputs.stat().st_size > contract["reassessment"]["max_bytes"]
                    or not args.evidence_root or not args.private_intake_output
                    or not re.fullmatch(r"[a-f0-9]{64}", args.expected_intake_sha256 or "")):
                raise ValueError("intake_binding_or_private_destination_missing")
            raw = args.canonical_inputs.read_bytes()
            if hashlib.sha256(raw).hexdigest() != args.expected_intake_sha256:
                raise ValueError("intake_original_hash_mismatch")
            destination = args.private_intake_output.resolve()
            if (destination.is_relative_to(args.output_dir.resolve())
                    or destination.is_relative_to(ROOT.resolve())
                    or destination.is_relative_to(args.evidence_root.resolve())
                    or destination == args.canonical_inputs.resolve()
                    or args.private_intake_output.is_symlink() or destination.exists()):
                raise ValueError("private_intake_destination_overlap")
            intake, result = export_review_intake(theme_etf_source_bridge.decode_evidence_json(raw.decode("utf-8")),
                report["reassessment"], args.evidence_root, now, report["code_sha"],
                private_etf_payload=private_etf, contract=contract)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as handle:
                json.dump(intake, handle, sort_keys=True, allow_nan=False)
            report["reassessment"]["intake_export"] = result
        except (OSError, ValueError, TypeError, KeyError):
            report["reassessment"]["intake_export"] = {"status": "BLOCKED_ORIGINAL_INTAKE_OR_PRIVATE_EXPORT",
                                                         "consumption_ack": False, "execute": False}
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "report.md").write_text(render(report), encoding="utf-8")
    (args.output_dir / "report.html").write_text(render_html(report), encoding="utf-8")
    bridge = sources.get("operating", {}).get("data", {}).get("theme_etf_bridge")
    if bridge is None:
        bridge = report["observations"]["theme_etf_bridge"]
    bridge = theme_etf_source_bridge.publication(
        bridge, code_sha=report["code_sha"], contract_hash=report["contract_sha256"])
    (args.output_dir / "theme_etf_bridge.json").write_text(
        json.dumps(bridge, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    with (args.output_dir / "research_queue.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report["watchlist"][0]))
        writer.writeheader()
        writer.writerows(report["watchlist"])
    for name, value in (("candidate_reassessment.json", report["reassessment"]),
                        ("a0_parameter_proposals.json", report["reassessment"]["parameter_proposals"])):
        (args.output_dir / name).write_text(json.dumps(value, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    with (args.output_dir / "review_queue.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["agent", "request_id", "reason", "requires", "execute"])
        writer.writeheader()
        for request in report["reassessment"]["review_requests"]:
            writer.writerow({"agent": request["agent"], "request_id": request["request_id"],
                "reason": ";".join(request.get("slices", request.get("requested_slices", []))),
                "requires": ";".join(request["requires"]), "execute": False})
    print(json.dumps({"status": report["status"], "expected_us_session": report["expected_us_session"],
                      "alerts": report["alerts"], "current_investment_ranking_ready": False,
                      "current_engine_scores_ready": report["current_engine_scores_ready"]}))
    return 0  # Report generation success is intentionally separate from data readiness.


if __name__ == "__main__":
    sys.exit(main())
