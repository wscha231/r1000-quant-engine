#!/usr/bin/env python3
"""Cloud-only bounded SEC capture -> Drive copy/readback -> pinned shared view.

No runtime downloads of code, training, model approval, target or order writes.
Inspect only lists this exact research folder. Capture needs exact source SHA,
explicit confirmation and the existing Drive secret. No scheduled execution.
"""
from __future__ import annotations
import argparse
import configparser
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.news_event_alpha_v1.runtime import ContractError, canonical_bytes, utc
from research.news_event_alpha_v1.admission import json_load, read_bounded, sha256
from research.news_event_alpha_v1.execution import require
from research.news_event_alpha_v1.source_capture import capture, exclusive_bytes
from research.news_event_alpha_v1.source_bridge import cik10, day
from research.news_event_alpha_v1.source_checkpoint import (
    code_fingerprint, freeze_cache, restore_cache, validate_checkpoint_manifest, check_pin,
)
from research.news_event_alpha_v1.shared_reader import build_shared_capture, read_shared_capture
from research.news_event_alpha_v1.review_guards import DriveReferences, checkpoint_lifetime, enforce_retry

FOLDER_ID = "1GdikTcHjAnhWLFXLiaVO4zcpUgetVFdH"
REGISTRY_ID = "1i0f0cQ4BfreWiFJdMl7okO9kJkChOn08"


def now():
    return datetime.now(timezone.utc).isoformat()


def make_plan(ciks, start, end, source_sha, *, cutoff):
    ids = [cik10(c.strip()) for c in ciks.split(",") if c.strip()]
    require(0 < len(ids) <= 10 and len(ids) == len(set(ids)), "CLOUD_CIK_LIST")
    a, b = day(start), day(end)
    require(0 <= (b-a).days <= 732, "CLOUD_WINDOW")
    require(re.fullmatch(r"[0-9a-f]{40}", source_sha) is not None, "CLOUD_SHA")
    return {"schema": "news-sec-capture-plan-p0.3", "ciks": ids,
            "window_start": start, "window_end": end, "data_cutoff": cutoff,
            "source_commit": source_sha, "max_filings": 100, "max_requests": 150,
            "selection_rule": "EARLIEST_BY_FILED_DATE_THEN_CIK_ACCESSION_NO_RETURNS",
            "document_progression": "REMAINING_UNCAPTURED"}


class Drive:
    def __init__(self, binary: str, config: Path):
        self.binary, self.config = binary, config

    def call(self, *args):
        # Explicit argv, bounded timeout/retry, captured secret-bearing error text.
        result = subprocess.run([self.binary, "--config", str(self.config),
                                 "--retries", "1", "--low-level-retries", "1",
                                 "--contimeout", "20s", "--timeout", "60s", *args],
                                capture_output=True, timeout=240)
        require(result.returncode == 0, "DRIVE_OPERATION_FAILED")
        return result.stdout

    def parity(self):
        registry = json_load(DriveReferences(self.call, FOLDER_ID).read_path(
            "gdrive:news_research_access.json", expected_id=REGISTRY_ID))
        require(registry.get("repository") == "wscha231/r1000-quant-engine" and
                registry.get("access", {}).get("drive_folder_id") == FOLDER_ID,
                "DRIVE_ROOT_REGISTRY_MISMATCH")


@contextmanager
def transport(workspace: Path):
    from tools.configure_macro_research_drive import validate_drive_config
    supplied = configparser.ConfigParser(interpolation=None)
    try:
        supplied.read_string(os.environ.get("NEWS_DRIVE_CONFIG", ""))
        require(supplied.has_section("gdrive") and supplied["gdrive"].get("type") == "drive", "DRIVE_CONFIG_REQUIRED")
        source = supplied["gdrive"]
        # Do not carry external credential paths, injected flags or other remotes.
        require(not source.get("service_account_file") and not source.get("service_account_credentials"), "OAUTH_CONFIG_REQUIRED")
        validate_drive_config(source)
        allowed = ("type", "client_id", "client_secret", "token", "scope", "team_drive")
        config = configparser.ConfigParser(interpolation=None)
        config["gdrive"] = {k: source[k] for k in allowed if source.get(k)}
        config["gdrive"]["root_folder_id"] = FOLDER_ID
        path = workspace / "news-rclone.conf"
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f: config.write(f)
    except Exception:
        raise ContractError("DRIVE_CONFIGURATION_BLOCKED") from None
    try:
        yield Drive(os.environ.get("NEWS_RCLONE_BIN", "rclone"), path)
    finally:
        path.unlink(missing_ok=True)  # only this execution's temporary credential file


def run_id(value):
    require(type(value) is str and re.fullmatch(r"[0-9]{1,24}-[0-9]{1,8}", value) is not None, "CLOUD_RUN_ID")
    return value


def parent_unused(drive, parent):
    # A duplicate name/ID anywhere in the parent set is ambiguous, never pick first.
    refs = DriveReferences(drive.call, FOLDER_ID)
    root = refs.directory("source_captures")
    children = refs.children(root)
    require(len(children) <= 2001, "RESUME_ATTEMPT_LIST_BUDGET")
    for key, entry in children.items():
        if key == "_objects":
            require(entry["IsDir"], "RESUME_OBJECT_POOL_TYPE")
            continue
        run_id(key)
        require(entry["IsDir"], "RESUME_ATTEMPT_FOLDER_TYPE")
        prior = json_load(refs.read_child(entry["ID"], "STARTED.json"))
        require(prior.get("run_key") == key, "RESUME_ATTEMPT_IDENTITY")
        require(prior.get("resume_from") != parent, "RESUME_PARENT_ALREADY_CONTINUED_USE_CHILD")
    require(refs.children(root) == children, "RESUME_ATTEMPT_SET_CHANGED")


def load_resume(drive, workspace, *, parent, pin, code_hash):
    run_id(parent); check_pin(pin)
    refs = DriveReferences(drive.call, FOLDER_ID)
    parent_id = refs.directory("source_captures/" + parent)
    start_raw = refs.read_child(parent_id, "STARTED.json")
    start = json_load(start_raw)
    terminal = json_load(refs.read_child(parent_id, "TERMINAL.json"))
    require(start.get("schema") == "news-capture-attempt-v1" and
            terminal.get("schema") == "news-capture-terminal-v1", "RESUME_ATTEMPT_SCHEMA")
    require(start.get("run_key") == terminal.get("run_key") == parent and
            sha256(start_raw) == terminal.get("started_sha256"), "RESUME_ATTEMPT_LINK")
    require(start.get("source_commit") == terminal.get("source_commit") and
            start.get("selector_eligible") is False, "RESUME_SOURCE_AUTHORITY")
    enforce_retry(terminal, as_of=now())
    require(terminal.get("resume_checkpoint_verified") is True
            and terminal.get("checkpoint_sha256") == pin, "RESUME_CHECKPOINT_NOT_VERIFIED")
    require(terminal.get("status") in {"BLOCKED", "PARTIAL_SOURCE_CAPTURE", "SOURCE_CAPTURE_REVIEW_REQUIRED"}
            and terminal.get("selector_eligible") is False and terminal.get("model_training_eligible") is False,
            "RESUME_TERMINAL_AUTHORITY")
    require(utc(start["started_at"]) <= utc(terminal["finished_at"]) <= utc(now()), "RESUME_ATTEMPT_CLOCK")
    raw = refs.read_child(parent_id, "CHECKPOINT.json")
    manifest = validate_checkpoint_manifest(raw, expected_hash=pin, code_hash=code_hash, as_of=now())
    checkpoint_lifetime(start, manifest, terminal)
    require(refs.directory("source_captures/" + parent) == parent_id, "RESUME_PARENT_ID_CHANGED")
    require(manifest["plan_sha256"] == start["plan_sha256"] == terminal["plan_sha256"], "RESUME_PLAN_LINK")
    require(manifest.get("parent_checkpoint_sha256") == start.get("parent_checkpoint_sha256"), "RESUME_PARENT_LINK")
    snapshot = workspace / "previous-checkpoint"
    exclusive_bytes(snapshot / "CHECKPOINT.json", raw)
    wanted = workspace / "resume-object-list.txt"
    wanted.write_text("".join(h + "\n" for h in sorted({e["sha256"] for e in manifest["files"]})), encoding="ascii")
    # Restore only referenced hashes. Never download the whole shared object pool.
    drive.call("copy", "gdrive:source_captures/_objects", str(snapshot / "objects"),
               "--files-from-raw", str(wanted), "--immutable", "--checksum", "--max-transfer", "144M")
    return restore_cache(snapshot, workspace / "capture", expected_hash=pin,
                         code_hash=code_hash, as_of=now())


def publish_checkpoint(drive, cap, workspace, remote, *, code_hash, parent_pin):
    snapshot = workspace / "checkpoint"
    cp = freeze_cache(cap, snapshot, as_of=now(), code_hash=code_hash, parent_checkpoint=parent_pin)
    # Hash filenames allow identical source objects to be reused across runs.
    drive.call("copy", str(snapshot / "objects"), "gdrive:source_captures/_objects",
               "--immutable", "--checksum", "--max-transfer", "144M")
    drive.call("check", str(snapshot / "objects"), "gdrive:source_captures/_objects", "--download", "--one-way")
    drive.call("copyto", str(snapshot / "CHECKPOINT.json"), remote + "/CHECKPOINT.json", "--immutable", "--checksum")
    require(DriveReferences(drive.call, FOLDER_ID).read_path(remote + "/CHECKPOINT.json") == (snapshot / "CHECKPOINT.json").read_bytes(),
            "CHECKPOINT_MANIFEST_READBACK")
    return cp


def run_capture_to_drive(drive, plan, workspace, *, run_key, user_agent,
                         resume_from=None, resume_pin=None, source_commit=None):
    run_id(run_key)
    require(bool(resume_from) == bool(resume_pin), "RESUME_PARENT_AND_HASH_REQUIRED")
    if resume_from:
        run_id(resume_from); check_pin(resume_pin)
        require(resume_from != run_key and plan is None, "RESUME_CANNOT_OVERRIDE_PLAN_OR_SELF")
    else:
        require(type(plan) is dict, "CAPTURE_PLAN_REQUIRED")
    drive.parity()
    fingerprint = sha256(canonical_bytes({"base": code_fingerprint(ROOT),
        "review_guards": sha256(read_bounded(ROOT / "research/news_event_alpha_v1/review_guards.py"))}))
    if resume_from:
        parent_unused(drive, resume_from)
        plan = load_resume(drive, workspace, parent=resume_from, pin=resume_pin, code_hash=fingerprint)
    executing_sha = source_commit or plan["source_commit"]
    require(re.fullmatch(r"[0-9a-f]{40}", executing_sha) is not None, "CLOUD_SHA")
    progressive = plan.get("document_progression") == "REMAINING_UNCAPTURED"
    remote = "gdrive:source_captures/" + run_key
    started = {"schema": "news-capture-attempt-v1", "run_key": run_key,
               "started_at": now(), "source_commit": executing_sha,
               "plan_sha256": sha256(canonical_bytes(plan)), "selector_eligible": False,
               "resume_from": resume_from, "parent_checkpoint_sha256": resume_pin,
               "code_fingerprint": fingerprint}
    marker = workspace / "STARTED.json"; exclusive_bytes(marker, canonical_bytes(started))
    drive.call("copyto", str(marker), remote + "/STARTED.json", "--immutable", "--checksum")
    require(DriveReferences(drive.call, FOLDER_ID).read_path(remote + "/STARTED.json") == marker.read_bytes(),
            "STARTED_ID_READBACK_FAILED")
    terminal = {"schema": "news-capture-terminal-v1", "run_key": run_key,
                "started_sha256": sha256(canonical_bytes(started)), "plan_sha256": started["plan_sha256"],
                "source_commit": executing_sha, "status": "BLOCKED", "consumer_readback_verified": False,
                "model_training_eligible": False, "selector_eligible": False,
                "resume_checkpoint_verified": False, "checkpoint_sha256": None,
                "whole_market_coverage_certified": False}
    try:
        cap = workspace / "capture"
        result = capture(plan, cap, user_agent=user_agent, lock_path=workspace / "sec.lock",
                         resume=bool(resume_from), execution_source_commit=executing_sha)
        directives = result.get("blockers", [])
        terminal["retry_manual_review_required"] = any(
            b.get("retry_manual_review_required", False) is not False for b in directives)
        deadlines = [utc(b["retry_not_before"]) for b in directives if b.get("retry_not_before")]
        if deadlines:
            terminal["retry_not_before"] = max(deadlines).isoformat()
        if progressive:
            cp = publish_checkpoint(drive, cap, workspace, remote, code_hash=fingerprint, parent_pin=resume_pin)
            terminal.update(resume_checkpoint_verified=True, checkpoint_sha256=cp["checkpoint_sha256"],
                            coverage_counts=result["coverage_counts"], new_requests=result["new_requests"],
                            new_documents_captured=result["new_documents_captured"],
                            source_complete_for_declared_selection=result["source_complete_for_declared_selection"])
        bundle = workspace / "shared"
        shared = build_shared_capture(cap, result["attempt_id"], bundle, as_of=now())
        drive.call("copy", str(bundle), remote + "/bundle", "--immutable", "--checksum")
        drive.call("check", str(bundle), remote + "/bundle", "--download", "--one-way")
        restored = workspace / "restored"
        drive.call("copy", remote + "/bundle", str(restored), "--immutable", "--checksum", "--max-transfer", "160M")
        view = read_shared_capture(restored, expected_manifest_sha256=shared["manifest_sha256"], as_of=now())
        terminal.update(status=view["status"], manifest_sha256=shared["manifest_sha256"],
                        consumer_readback_verified=True, captured_primary_count=view["captured_primary_count"])
    except Exception:
        # A verified checkpoint may survive a blocked source/consumer stage. Not a successful analysis.
        terminal.update(status="BLOCKED", reason="CAPTURE_OR_PUBLICATION_FAILED", consumer_readback_verified=False)
    terminal["finished_at"] = now()
    final = workspace / "TERMINAL.json"; exclusive_bytes(final, canonical_bytes(terminal))
    drive.call("copyto", str(final), remote + "/TERMINAL.json", "--immutable", "--checksum")
    require(DriveReferences(drive.call, FOLDER_ID).read_path(remote + "/TERMINAL.json") == final.read_bytes(), "TERMINAL_READBACK_FAILED")
    return terminal


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["inspect", "capture"], required=True)
    p.add_argument("--expected-sha", required=True)
    p.add_argument("--ciks", default="")
    p.add_argument("--start", default=""); p.add_argument("--end", default="")
    p.add_argument("--confirm", default="")
    p.add_argument("--resume-from", default="")
    p.add_argument("--resume-checkpoint", default="")
    args = p.parse_args(argv)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(args.expected_sha == head and re.fullmatch(r"[0-9a-f]{40}", head), "EXACT_SOURCE_SHA_REQUIRED")
    require(os.environ.get("GITHUB_REF") == "refs/heads/master" and
            os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "MANUAL_MASTER_ONLY")
    plan = None
    if args.mode == "capture":
        require(args.confirm == "capture-source-only", "CAPTURE_CONFIRMATION_REQUIRED")
        require(bool(args.resume_from) == bool(args.resume_checkpoint), "RESUME_PARENT_AND_HASH_REQUIRED")
        if args.resume_from:
            require(not args.ciks and not args.start and not args.end, "RESUME_SCOPE_OVERRIDE_BLOCKED")
        else:
            plan = make_plan(args.ciks, args.start, args.end, head, cutoff=now())
    else:
        require(not args.resume_from and not args.resume_checkpoint, "INSPECT_CANNOT_RESUME")
    with tempfile.TemporaryDirectory(prefix="news-cloud-", dir=os.environ.get("RUNNER_TEMP")) as temp:
        work = Path(temp)
        with transport(work) as drive:
            if args.mode == "inspect":
                drive.parity()
                result = {"status": "ROOT_READ_PARITY_ONLY", "source_commit": head,
                          "capture_run": False, "model_training_eligible": False, "selector_eligible": False}
            else:
                result = run_capture_to_drive(drive, plan, work,
                    run_key=os.environ.get("GITHUB_RUN_ID", "") + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", ""),
                    user_agent=os.environ.get("SEC_USER_AGENT", ""),
                    resume_from=args.resume_from or None, resume_pin=args.resume_checkpoint or None,
                    source_commit=head)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"ROOT_READ_PARITY_ONLY", "SOURCE_CAPTURE_REVIEW_REQUIRED"} else 2

if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception:
        print("NEWS_CLOUD_BLOCKED: inspect approved inputs and run receipt; no secrets logged", file=sys.stderr)
        raise SystemExit(2)
