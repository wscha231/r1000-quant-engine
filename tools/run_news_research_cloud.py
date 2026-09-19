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
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.news_event_alpha_v1.runtime import ContractError, canonical_bytes
from research.news_event_alpha_v1.admission import json_load, read_bounded, sha256
from research.news_event_alpha_v1.execution import require
from research.news_event_alpha_v1.source_capture import capture, exclusive_bytes
from research.news_event_alpha_v1.source_bridge import cik10, day
from research.news_event_alpha_v1.shared_reader import build_shared_capture, read_shared_capture

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
            "selection_rule": "EARLIEST_BY_FILED_DATE_THEN_CIK_ACCESSION_NO_RETURNS"}


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
        registry = json_load(self.call("cat", "gdrive:news_research_access.json"))
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


def run_capture_to_drive(drive, plan, workspace, *, run_key, user_agent):
    require(re.fullmatch(r"[0-9]+-[0-9]+", run_key) is not None, "CLOUD_RUN_ID")
    remote = "gdrive:source_captures/" + run_key
    started = {"schema": "news-capture-attempt-v1", "run_key": run_key,
               "started_at": now(), "source_commit": plan["source_commit"],
               "plan_sha256": sha256(canonical_bytes(plan)), "selector_eligible": False}
    marker = workspace / "STARTED.json"; exclusive_bytes(marker, canonical_bytes(started))
    drive.parity()
    drive.call("copyto", str(marker), remote + "/STARTED.json", "--immutable")
    try:
        cap = workspace / "capture"
        result = capture(plan, cap, user_agent=user_agent, lock_path=workspace / "sec.lock")
        bundle = workspace / "shared"
        shared = build_shared_capture(cap, result["attempt_id"], bundle, as_of=now())
        drive.call("copy", str(bundle), remote + "/bundle", "--immutable")
        drive.call("check", str(bundle), remote + "/bundle", "--download", "--one-way")
        # Restore separately and run the exact consumer, not just an upload exit code.
        restored = workspace / "restored"
        drive.call("copy", remote + "/bundle", str(restored), "--immutable")
        view = read_shared_capture(restored, expected_manifest_sha256=shared["manifest_sha256"], as_of=now())
        terminal = {"schema": "news-capture-terminal-v1", "run_key": run_key,
                    "started_sha256": sha256(canonical_bytes(started)),
                    "status": view["status"], "finished_at": now(),
                    "manifest_sha256": shared["manifest_sha256"],
                    "source_commit": plan["source_commit"], "consumer_readback_verified": True,
                    "captured_primary_count": view["captured_primary_count"],
                    "model_training_eligible": False, "selector_eligible": False,
                    "whole_market_coverage_certified": False}
    except Exception:
        terminal = {"schema": "news-capture-terminal-v1", "run_key": run_key,
                    "started_sha256": sha256(canonical_bytes(started)), "finished_at": now(),
                    "status": "BLOCKED", "reason": "CAPTURE_OR_PUBLICATION_FAILED",
                    "consumer_readback_verified": False, "model_training_eligible": False,
                    "selector_eligible": False}
    final = workspace / "TERMINAL.json"; exclusive_bytes(final, canonical_bytes(terminal))
    drive.call("copyto", str(final), remote + "/TERMINAL.json", "--immutable")
    require(drive.call("cat", remote + "/TERMINAL.json") == final.read_bytes(), "TERMINAL_READBACK_FAILED")
    return terminal


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["inspect", "capture"], required=True)
    p.add_argument("--expected-sha", required=True)
    p.add_argument("--ciks", default="")
    p.add_argument("--start", default=""); p.add_argument("--end", default="")
    p.add_argument("--confirm", default="")
    args = p.parse_args(argv)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(args.expected_sha == head and re.fullmatch(r"[0-9a-f]{40}", head), "EXACT_SOURCE_SHA_REQUIRED")
    require(os.environ.get("GITHUB_REF") == "refs/heads/master" and
            os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "MANUAL_MASTER_ONLY")
    plan = None
    if args.mode == "capture":
        require(args.confirm == "capture-source-only", "CAPTURE_CONFIRMATION_REQUIRED")
        plan = make_plan(args.ciks, args.start, args.end, head, cutoff=now())
    with tempfile.TemporaryDirectory(prefix="news-cloud-", dir=os.environ.get("RUNNER_TEMP")) as temp:
        work = Path(temp)
        with transport(work) as drive:
            if plan is None:
                drive.parity()
                result = {"status": "ROOT_READ_PARITY_ONLY", "source_commit": head,
                          "capture_run": False, "model_training_eligible": False, "selector_eligible": False}
            else:
                result = run_capture_to_drive(drive, plan, work,
                    run_key=os.environ.get("GITHUB_RUN_ID", "") + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", ""),
                    user_agent=os.environ.get("SEC_USER_AGENT", ""))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"ROOT_READ_PARITY_ONLY", "SOURCE_CAPTURE_REVIEW_REQUIRED"} else 2

if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception:
        print("NEWS_CLOUD_BLOCKED: inspect approved inputs and run receipt; no secrets logged", file=sys.stderr)
        raise SystemExit(2)
