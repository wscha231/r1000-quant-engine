"""Finite private SIP campaign control; no source or economic admission.

The Work host reserves all remaining allowance before dispatch. A worker derives
remaining allowance independently from canonical same-campaign Actions receipts.
An unknown outcome cannot release a reservation or start another worker.
"""
from __future__ import annotations

import argparse
import base64
import configparser
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from tools.twelve_private_capture import (
    Refused, NoRedirect, credential_safe_json, decode, digest, encoded, require,
)

TASK = "R1000-A1-993-SIP-BOUNDED-CAMPAIGN-20261015"
REPO = "wscha231/r1000-quant-engine"
WORKFLOW = "alpaca_sip_private_backfill_v1.yml"
PREFIX = "r1000-993-20261015-"
INITIAL_SHA = "9a8e0d12d0acb065ce0b5a44963b6b152646127c521bf0e592119526d889fd6a"
SEED_SHA = "333668b35a6264ad9c3bbe635212a5b95db21ba57855666dca2ee5311ea160cc"
LIMITS = dict(provider_gets=2000, drive_requests=50000,
              drive_bytes=8 * 1024**3, storage_bytes=1024**3)
METRIC = "HTTP_BODIES_PLUS_65536_RESERVED_OVERHEAD_PER_GOOGLE_REQUEST"
PINS = ("tools/alpaca_sip_campaign.py", "tools/alpaca_sip_private_backfill_v1.py",
        "tools/twelve_private_capture.py", "tools/configure_macro_research_drive.py",
        "tools/macro_history_sources.py", ".github/workflows/" + WORKFLOW)
ROOT = Path(__file__).resolve().parents[1]
AUTH_FIELDS = {"schema", "task_key", "scope_approved", "private_noncommercial", "approval_reference",
               "start", "end", "seed_sha256", "initial_checkpoint_sha256", "transfer_definition",
               "limits", "workflow_run_floor", "expected_master", "code_pins", "private_root_folder_id",
               "private_data_folder_id", "initial_checkpoint_file_id", "account_permission_reference",
               "owner_permission_id", "credential_binding"}


def utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    require(isinstance(value, str), "CAMPAIGN_CLOCK")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.utcoffset() == timedelta(0), "CAMPAIGN_CLOCK")
        return result
    except (ValueError, TypeError, OverflowError):
        raise Refused("CAMPAIGN_CLOCK") from None


def integer(value, maximum, code="CAMPAIGN_COUNTER"):
    require(type(value) is int and 0 <= value <= maximum, code)
    return value


def bounded_bytes(path, limit=65536):
    path = Path(path)
    require(not path.is_symlink(), "CAMPAIGN_INPUT_FILE")
    if os.name == "nt":
        require(":" not in path.name and path.stem.upper() not in
                {"CON", "PRN", "AUX", "NUL", *("COM" + str(i) for i in range(1, 10)),
                 *("LPT" + str(i) for i in range(1, 10))}, "CAMPAIGN_INPUT_FILE")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        initial = os.fstat(descriptor)
        require(stat.S_ISREG(initial.st_mode) and 0 <= initial.st_size <= limit, "CAMPAIGN_INPUT_SIZE")
        handle = os.fdopen(descriptor, "rb")
        descriptor = None
        with handle:
            raw = handle.read(limit + 1)
            final = os.fstat(handle.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)
    current = path.lstat()
    signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    require(signature(initial) == signature(final) == signature(current)
            and len(raw) == initial.st_size <= limit, "CAMPAIGN_INPUT_CHANGED")
    return raw


def bounded_json(path, limit=65536):
    return decode(bounded_bytes(path, limit))


def atomic_json(path, value):
    path = Path(path)
    raw = encoded(value)
    require(len(raw) <= 65536, "CAMPAIGN_JOURNAL_SIZE")
    temporary = path.with_name(path.name + ".new")
    with temporary.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def validate_authorization(auth):
    require(isinstance(auth, dict) and set(auth) == AUTH_FIELDS
            and auth.get("schema") == "r1000-sip-campaign-authorization-v1" and auth.get("task_key") == TASK
            and auth.get("scope_approved") is True
            and auth.get("private_noncommercial") is True
            and isinstance(auth.get("approval_reference"), str)
            and 0 < len(auth["approval_reference"]) <= 512,
            "CAMPAIGN_AUTHORIZATION")
    require(auth.get("start") == "2016-01-04" and auth.get("end") == "2026-10-14"
            and auth.get("seed_sha256") == SEED_SHA
            and auth.get("initial_checkpoint_sha256") == INITIAL_SHA
            and auth.get("transfer_definition") == METRIC,
            "CAMPAIGN_SCOPE")
    require(auth.get("limits") == LIMITS
            and all(type(auth["limits"][name]) is int for name in LIMITS),
            "CAMPAIGN_LIMITS")
    require(type(auth.get("workflow_run_floor")) is int
            and 1 <= auth["workflow_run_floor"] <= 1_000_000_000,
            "CAMPAIGN_HISTORY_FLOOR")
    require(isinstance(auth.get("expected_master"), str)
            and re.fullmatch(r"[0-9a-f]{40}", auth["expected_master"]),
            "CAMPAIGN_SOURCE")
    require(isinstance(auth.get("code_pins"), dict)
            and set(auth["code_pins"]) == set(PINS)
            and all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
                    for v in auth["code_pins"].values()), "CAMPAIGN_CODE_PINS")
    for key in ("private_root_folder_id", "private_data_folder_id", "initial_checkpoint_file_id"):
        require(isinstance(auth.get(key), str)
                and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", auth[key]), "CAMPAIGN_PRIVATE_REF")
    # A caller cannot replace unknown account rights with a successful bars GET.
    # Null bindings allow metered metadata preflight, never price capture.
    permission, owner, key = (auth.get(k) for k in
                              ("account_permission_reference", "owner_permission_id", "credential_binding"))
    require(permission is None or (isinstance(permission, str) and 0 < len(permission) <= 512),
            "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
    require(owner is None or (isinstance(owner, str) and 0 < len(owner) <= 128),
            "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
    require(key is None or (isinstance(key, str) and re.fullmatch(r"[0-9a-f]{64}", key)),
            "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
    return digest(encoded(auth))


class RuntimeMeter:
    """Write conservative debit before I/O; settle only a complete response.

    Transfer means HTTP bodies (including multipart) plus a fixed conservative
    overhead allowance. It is not an encrypted socket/TLS byte measurement.
    This explicit metric must be accepted in the immutable authorization.
    """
    def __init__(self, allowance, journal, deadline, identity, clock=utc,
                 opener=None):
        require(set(allowance) == set(LIMITS), "CAMPAIGN_COUNTER")
        self.allowance = {k: integer(allowance[k], LIMITS[k]) for k in LIMITS}
        self.used = {k: 0 for k in LIMITS}
        self.journal, self.deadline = Path(journal), utc(deadline)
        self.identity, self.clock = dict(identity), clock
        self.opener = opener or build_opener(NoRedirect())
        self.live_transport = opener is None
        self.alarm_active = False
        self.observed_google_body_bytes = 0
        self.confirmed_storage_bytes = 0
        self.finalized, self.status, self.reason = False, "RUNNING", None
        self.checkpoint_sha = identity["parent_checkpoint_sha256"]
        self.examined, self.rows = identity["examined_before"], 0
        self.states = dict(VALID_COLLECTED=0, VERIFIED_NO_DATA=0, QUARANTINED=0)
        self.save()

    def remaining_seconds(self):
        value = (self.deadline - self.clock()).total_seconds()
        require(value > 0, "CAMPAIGN_DEADLINE")
        return value

    def save(self):
        atomic_json(self.journal, dict(schema="a1-sip-campaign-meter-v1",
                    **self.identity, usage=self.used, allowance=self.allowance,
                    status=self.status, reason=self.reason, finalized=self.finalized,
                    checkpoint_sha256=self.checkpoint_sha,
                    examined_after=self.examined, rows_verified=self.rows,
                    new_states=self.states, transfer_definition=METRIC,
                    observed_google_body_bytes=self.observed_google_body_bytes,
                    confirmed_storage_bytes=self.confirmed_storage_bytes,
                    source_admission=False, pit_verified=False,
                    economic_authority=False))

    def debit(self, changes):
        self.remaining_seconds()
        next_used = dict(self.used)
        for key, amount in changes.items():
            integer(amount, LIMITS[key])
            require(next_used[key] + amount <= self.allowance[key],
                    "CAMPAIGN_BUDGET_" + key.upper())
            next_used[key] += amount
        self.used = next_used
        self.save()  # Failure here occurs before the external side effect.

    def reserve_storage(self, size):
        self.debit(dict(storage_bytes=integer(size, 16_000_000)))

    @contextmanager
    def process_deadline(self):
        # Live workers are Linux Actions processes. SIGALRM interrupts header
        # parsing, TLS, uploads and CPU work as well as body reads. Windows is
        # supported for the Work host and offline proofs, not live worker I/O.
        supported = hasattr(signal, "setitimer") and threading.current_thread() is threading.main_thread()
        require(supported or not self.live_transport, "CAMPAIGN_DEADLINE_PLATFORM")
        if not supported:
            yield
            return
        require(signal.getitimer(signal.ITIMER_REAL)[0] == 0, "CAMPAIGN_EXISTING_ALARM")
        old = signal.getsignal(signal.SIGALRM)
        def expired(*_):
            raise Refused("CAMPAIGN_DEADLINE")
        try:
            signal.signal(signal.SIGALRM, expired)
            signal.setitimer(signal.ITIMER_REAL, self.remaining_seconds())
            self.alarm_active = True
            yield
        finally:
            # A failed disarm may leave SIGALRM pending: retain its safe handler
            # and active state until the timer is confirmed cleared.
            signal.setitimer(signal.ITIMER_REAL, 0)
            self.alarm_active = False
            signal.signal(signal.SIGALRM, old)

    def perform(self, url, *, method="GET", headers=None, body=None,
                limit=2_000_000, credentials=()):
        endpoint = urlsplit(url)
        require(endpoint.scheme == "https" and endpoint.username is None
                and endpoint.password is None and endpoint.port in (None, 443),
                "CAMPAIGN_ENDPOINT")
        provider = endpoint.netloc == "data.alpaca.markets" and endpoint.path == "/v2/stocks/bars"
        google = ((endpoint.netloc == "www.googleapis.com" and
                   (endpoint.path == "/drive/v3/about" or
                    endpoint.path == "/drive/v3/files" or
                    re.fullmatch(r"/drive/v3/files/[A-Za-z0-9_-]+", endpoint.path) or
                    endpoint.path == "/upload/drive/v3/files")) or
                  (endpoint.netloc == "oauth2.googleapis.com" and endpoint.path == "/token"))
        require((provider and method == "GET") or
                (google and method in ("GET", "POST")), "CAMPAIGN_ENDPOINT")
        integer(limit, 16_000_000)
        require(limit > 0 and (body is None or isinstance(body, bytes)), "CAMPAIGN_IO_SIZE")
        require(not self.live_transport or self.alarm_active, "CAMPAIGN_DEADLINE_REQUIRED")
        reserved = limit + 1 + len(body or b"") + 65536
        self.debit(dict(provider_gets=1) if provider else
                   dict(drive_requests=1, drive_bytes=reserved))
        try:
            with self.opener.open(Request(url, data=body, method=method,
                                         headers=headers or {}),
                                  timeout=min(25, self.remaining_seconds())) as reply:
                require(reply.status == 200, "HTTP_ERROR")
                # read1 bounds each underlying socket read; read(n) can wait
                # indefinitely for n bytes from a trickling peer.
                sock = reply.fp.raw._sock
                chunks, size = [], 0
                while True:
                    # HTTPResponse closes its file as soon as Content-Length
                    # is satisfied. Do not touch that socket again. Conversely,
                    # read1 returns EOF without raising on a truncated length.
                    self.remaining_seconds()
                    if getattr(reply, "length", None) == 0:
                        break
                    sock.settimeout(min(25, self.remaining_seconds()))
                    chunk = reply.read1(min(65536, limit + 1 - size))
                    if not chunk:
                        require(getattr(reply, "length", None) is None, "NETWORK")
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    require(size <= limit, "RESPONSE_SIZE")
                raw = b"".join(chunks)
                require(raw, "RESPONSE_SIZE")
                self.remaining_seconds()
        except HTTPError as exc:
            code = {401: "AUTH", 402: "ENTITLEMENT", 403: "PERMISSION", 429: "RATE_LIMIT"}.get(exc.code, "HTTP_ERROR")
            exc.close()
            raise Refused(code) from None
        except Refused:
            raise
        except Exception:
            raise Refused("NETWORK") from None
        require(all(not value or value.encode() not in raw for value in credentials), "CREDENTIAL_ECHO")
        if google:
            # Unknown/failed/partial replies retain their entire reservation.
            self.used["drive_bytes"] -= limit + 1 - len(raw)
            self.observed_google_body_bytes += len(body or b"") + len(raw)
            self.save()
        return raw

    def finish(self, status, reason=None):
        require(status in ("COMPLETE", "BLOCKED"), "CAMPAIGN_STATUS")
        require(reason is None or (isinstance(reason, str)
                and re.fullmatch(r"[A-Z_]{1,80}", reason)), "CAMPAIGN_REASON")
        self.status, self.finalized, self.reason = status, True, reason
        self.save()


def gh_json(path):
    """Fixed-repository, bounded metadata; never print CLI errors/credentials."""
    require(path.startswith("repos/" + REPO + "/"), "CAMPAIGN_GITHUB_SCOPE")
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(["gh", "api", path], stdout=output,
                                    stderr=subprocess.DEVNULL, timeout=45)
        except Exception:
            raise Refused("CAMPAIGN_GITHUB_READ") from None
        require(result.returncode == 0, "CAMPAIGN_GITHUB_READ")
        output.seek(0)
        raw = output.read(4_000_001)
    require(len(raw) <= 4_000_000, "CAMPAIGN_GITHUB_SIZE")
    return decode(raw)


def campaign_runs(floor=None):
    path = "repos/" + REPO + "/actions/workflows/" + WORKFLOW + "/runs?" + urlencode(
        dict(created=">=2026-10-14", per_page=100))
    payload = gh_json(path)
    require(type(payload.get("total_count")) is int and payload["total_count"] <= 100
            and isinstance(payload.get("workflow_runs"), list)
            and len(payload["workflow_runs"]) == payload["total_count"], "CAMPAIGN_HISTORY_INCOMPLETE")
    runs = [r for r in payload["workflow_runs"] if
            isinstance(r.get("display_title"), str) and r["display_title"].startswith("a1-sip " + PREFIX)]
    if floor is not None:
        require(type(floor) is int and floor > 0
                and all(type(r.get("run_number")) is int and r["run_number"] > 0
                        for r in payload["workflow_runs"]), "CAMPAIGN_HISTORY_FLOOR")
        all_numbers = {r["run_number"] for r in payload["workflow_runs"]}
        numbers = {number for number in all_numbers if number >= floor}
        require(not numbers or (max(numbers) - floor < 100
                and numbers == set(range(floor, max(numbers) + 1))),
                "CAMPAIGN_HISTORY_GAP")
        if runs:
            # A future floor must never hide an already observed dispatch.
            require(min(r["run_number"] for r in runs) == floor,
                    "CAMPAIGN_HISTORY_FLOOR")
        else:
            require(floor == max(all_numbers, default=0) + 1,
                    "CAMPAIGN_HISTORY_FLOOR")
    require(len(runs) <= 40 and len({r["display_title"] for r in runs}) == len(runs),
            "CAMPAIGN_NONCE_REPLAY")
    return sorted(runs, key=lambda r: (r["created_at"], r["id"]))


def receipt_for_run(run, auth_hash, expected_master):
    require(run.get("status") == "completed" and run.get("run_attempt") == 1
            and run.get("head_sha") == expected_master and run.get("head_branch") == "master",
            "CAMPAIGN_RUN_UNRESOLVED")
    artifacts = gh_json(f"repos/{REPO}/actions/runs/{run['id']}/artifacts?per_page=100")
    require(artifacts.get("total_count") == len(artifacts.get("artifacts", [])) <= 100,
            "CAMPAIGN_ARTIFACTS")
    found = [a for a in artifacts["artifacts"] if a.get("name") == "a1-campaign-meter"]
    require(len(found) == 1 and found[0].get("expired") is False
            and type(found[0].get("size_in_bytes")) is int
            and 0 < found[0]["size_in_bytes"] <= 65536, "CAMPAIGN_RECEIPT_MISSING")
    with tempfile.TemporaryDirectory(prefix="a1-meter-read-") as temp:
        result = subprocess.run(["gh", "run", "download", str(run["id"]),
                                 "--repo", REPO, "--name", "a1-campaign-meter", "--dir", temp],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        require(result.returncode == 0, "CAMPAIGN_RECEIPT_DOWNLOAD")
        files = list(Path(temp).iterdir())
        require(len(files) == 1 and files[0].name == "campaign_meter.json"
                and not files[0].is_symlink(), "CAMPAIGN_RECEIPT_FILES")
        value = bounded_json(files[0])
    require(value.get("schema") == "a1-sip-campaign-meter-v1"
            and value.get("auth_sha256") == auth_hash
            and value.get("run_id") == run["id"] and value.get("run_attempt") == 1
            and value.get("nonce") == run["display_title"][7:]
            and value.get("source_sha") == expected_master
            and value.get("finalized") is True and value.get("status") in ("COMPLETE", "BLOCKED")
            and value.get("transfer_definition") == METRIC
            and value.get("source_admission") is False and value.get("pit_verified") is False
            and value.get("economic_authority") is False, "CAMPAIGN_RECEIPT_BINDING")
    require(set(value.get("usage", {})) == set(LIMITS)
            and set(value.get("allowance", {})) == set(LIMITS), "CAMPAIGN_RECEIPT_COUNTERS")
    for name in LIMITS:
        integer(value["usage"][name], LIMITS[name])
        integer(value["allowance"][name], LIMITS[name])
        require(value["usage"][name] <= value["allowance"][name], "CAMPAIGN_RECEIPT_COUNTERS")
    integer(value.get("examined_before"), 1009)
    integer(value.get("examined_after"), 1009)
    integer(value.get("rows_verified"), 4_000_000)
    require(set(value.get("new_states", {})) ==
            {"VALID_COLLECTED", "VERIFIED_NO_DATA", "QUARANTINED"}, "CAMPAIGN_RECEIPT_STATES")
    for count in value["new_states"].values():
        integer(count, 32)
    require(sum(value["new_states"].values()) == value["examined_after"] - value["examined_before"],
            "CAMPAIGN_RECEIPT_STATES")
    require(integer(value.get("confirmed_storage_bytes"), LIMITS["storage_bytes"]) <= value["usage"]["storage_bytes"]
            and integer(value.get("observed_google_body_bytes"), LIMITS["drive_bytes"]) <= value["usage"]["drive_bytes"],
            "CAMPAIGN_RECEIPT_OBSERVED")
    require(type(value.get("preflight_only")) is bool, "CAMPAIGN_RECEIPT_PREFLIGHT")
    if value["preflight_only"]:
        require(value["examined_after"] == value["examined_before"]
                and value["rows_verified"] == value["usage"]["provider_gets"] == value["usage"]["storage_bytes"] == 0,
                "CAMPAIGN_RECEIPT_PREFLIGHT")
    elif value["examined_after"] > value["examined_before"] or value["usage"]["provider_gets"]:
        require(isinstance(value.get("account_permission_reference_sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", value["account_permission_reference_sha256"])
                and isinstance(value.get("account_permission_record_sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", value["account_permission_record_sha256"])
                and value.get("bindings") is not None, "CAMPAIGN_RECEIPT_ACCOUNT")
    return value


def job_seconds(run):
    payload = gh_json(f"repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=100")
    jobs = payload.get("jobs")
    require(isinstance(jobs, list) and payload.get("total_count") == len(jobs)
            and 1 <= len(jobs) <= 2, "CAMPAIGN_JOB_TIME")
    total = 0
    for job in jobs:
        require(job.get("status") == "completed", "CAMPAIGN_JOB_TIME")
        seconds = (utc(job.get("completed_at")) - utc(job.get("started_at"))).total_seconds()
        require(0 <= seconds <= 7800, "CAMPAIGN_JOB_TIME")
        total += seconds
    require(total <= 7800, "CAMPAIGN_JOB_TIME")
    return total


def history(auth, current_run=None, nonce=None, recovery_run=None, enforce_expiry=True):
    """Canonical Actions history prevents a valid old local ledger rollback."""
    auth_hash = validate_authorization(auth)
    runs = campaign_runs(auth["workflow_run_floor"])
    if current_run is not None:
        require(runs and runs[-1]["id"] == current_run
                and runs[-1]["display_title"] == "a1-sip " + nonce
                and runs[-1].get("run_attempt") == 1
                and runs[-1].get("head_sha") == auth["expected_master"], "CAMPAIGN_SINGLE_USE")
        previous = runs[:-1]
    else:
        previous = runs
    used = {k: 0 for k in LIMITS}
    parent, examined, active, bindings, permission_hash = INITIAL_SHA, 16, 0, None, None
    permission_record_hash = None
    receipts = []
    durations = []
    values = [receipt_for_run(run, auth_hash, auth["expected_master"]) for run in previous]
    for index, (run, value) in enumerate(zip(previous, values)):
        current_bindings = value.get("bindings")
        if current_bindings is not None:
            require(isinstance(current_bindings, dict) and set(current_bindings) ==
                    {"owner_sha256", "credential_binding"}
                    and all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
                            for v in current_bindings.values()), "CAMPAIGN_ACCOUNT_BINDING")
            require(bindings is None or bindings == current_bindings, "CAMPAIGN_ACCOUNT_DRIFT")
            bindings = current_bindings
        current_permission = value.get("account_permission_reference_sha256")
        current_record = value.get("account_permission_record_sha256")
        if current_permission is not None:
            require(isinstance(current_permission, str) and re.fullmatch(r"[0-9a-f]{64}", current_permission),
                    "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
            require(isinstance(current_record, str) and re.fullmatch(r"[0-9a-f]{64}", current_record),
                    "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
            require(permission_hash is None or permission_hash == current_permission, "CAMPAIGN_RIGHTS_DRIFT")
            require(permission_record_hash is None or permission_record_hash == current_record,
                    "CAMPAIGN_RIGHTS_DRIFT")
            permission_hash = current_permission
            permission_record_hash = current_record
        else:
            require(current_record is None, "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
        require(value.get("parent_checkpoint_sha256") == parent
                and value.get("examined_before") == examined, "CAMPAIGN_LEDGER_CHAIN")
        after = integer(value.get("examined_after"), 1009)
        require(examined <= after <= examined + min(32, 1009 - examined), "CAMPAIGN_PROGRESS")
        require(isinstance(value.get("checkpoint_sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", value["checkpoint_sha256"]), "CAMPAIGN_CHECKPOINT")
        for name in LIMITS:
            require(value["allowance"][name] == LIMITS[name] - used[name], "CAMPAIGN_ALLOWANCE_RESET")
            used[name] += value["usage"][name]
            require(used[name] <= LIMITS[name], "CAMPAIGN_LEDGER_BUDGET")
        duration = job_seconds(run)
        active += duration
        durations.append(duration)
        parent, examined = value["checkpoint_sha256"], after
        receipts.append(value)
        require((value["status"] == "COMPLETE" and run.get("conclusion") == "success") or
                (value.get("reason") in ("NETWORK", "HTTP_ERROR") and
                 ((run["id"] == recovery_run and run == previous[-1]) or
                  (index + 1 < len(values) and values[index + 1].get("recovery_run") == run["id"]))),
                "CAMPAIGN_FAILED_RUN_REQUIRES_RECOVERY")
    require(active <= 28800, "CAMPAIGN_ACTIVE_TIME")
    first = utc(runs[0]["created_at"]) if runs else None
    if first is not None and enforce_expiry:
        require(utc() < first + timedelta(hours=48), "CAMPAIGN_EXPIRED")
    return dict(runs=runs, receipts=receipts, used=used, active_seconds=active, bindings=bindings,
                permission_hash=permission_hash, permission_record_hash=permission_record_hash,
                durations=durations,
                parent_sha=parent, examined=examined, first=first,
                remaining={k: LIMITS[k] - used[k] for k in LIMITS})


def forecast_remaining(observed):
    """Measured conservative forecast, separate from hard runtime caps."""
    processed = observed["examined"] - 16
    require(processed >= 128 and observed["receipts"], "CAMPAIGN_CALIBRATION_INPUT")
    remaining_names = 1009 - observed["examined"]
    jobs = math.ceil(remaining_names / 32)
    pairs = [(r, seconds) for r, seconds in zip(observed["receipts"], observed["durations"])
             if r["examined_after"] > r["examined_before"]]
    require(pairs, "CAMPAIGN_CALIBRATION_INPUT")
    captures = [r for r, _ in pairs]
    # A recovery batch may process only1-4 names. Its total bytes/time cannot
    # stand in for a future32-name batch. Retain the largest full-batch
    # equivalent, and measure positive growth per32 names of prefix advance.
    def full_batch_forecast(values):
        normalized = [value * 32 / (r["examined_after"] - r["examined_before"])
                      for r, value in zip(captures, values)]
        slope = max([0] + [max(0, b - a) * 32 /
                          (right["examined_before"] - left["examined_before"])
                          for a, b, left, right in zip(normalized, normalized[1:],
                                                       captures, captures[1:])])
        return jobs * max(normalized) + slope * jobs * (jobs + 1) / 2
    estimates = {}
    for key in LIMITS:
        deltas = [r["usage"][key] for r in captures]
        if key in ("provider_gets", "storage_bytes"):
            estimate = sum(deltas) / processed * remaining_names
        elif key == "drive_requests":
            # Preserve the known full-prefix restore, including a partial
            # recovery/calibration batch. Preflight is not a price-job slope.
            overhead = max([4] + [r["usage"][key] - 8 * math.ceil(r["examined_before"] / 4)
                                   - 28 * math.ceil((r["examined_after"] - r["examined_before"]) / 4)
                                   for r in captures])
            estimate, prefix = 0, observed["examined"]
            while prefix < 1009:
                size = next_batch(prefix)
                estimate += 8 * math.ceil(prefix / 4) + 28 * math.ceil(size / 4) + overhead
                prefix += size
        else:
            estimate = full_batch_forecast(deltas)
        estimates[key] = math.ceil(estimate * 1.25)
    durations = [seconds for _, seconds in pairs]
    seconds = math.ceil(full_batch_forecast(durations) * 1.25)
    fits = all(estimates[k] <= observed["remaining"][k] for k in LIMITS)
    fits = fits and seconds <= 28800 - observed["active_seconds"]
    return dict(new_processed=processed, remaining_candidates=remaining_names,
                estimated_remaining=estimates, estimated_remaining_active_seconds=seconds,
                margin=1.25, estimate_only=True, fits_current_budgets=fits)


def next_batch(examined):
    require(type(examined) is int and 16 <= examined < 1009, "CAMPAIGN_PROGRESS")
    # Normal campaign is31x32+1. After a partial failed batch, align with the
    # next128-new-symbol checkpoint instead of silently skipping calibration.
    return min(32, 1009 - examined, 128 - (examined - 16) % 128)


class WorkJournal:
    """One existing Work directory; append and fsync before dispatch.

    Canonical Actions reconciliation, not the local hash chain alone, detects
    a complete rollback to an older valid prefix.
    """
    def __init__(self, directory, auth_hash):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        require(not self.directory.is_symlink(), "CAMPAIGN_JOURNAL_PATH")
        require(all(re.fullmatch(r"[0-9]{6}\.json|writer\.lock|progress(?:\.new)?", p.name)
                    for p in self.directory.iterdir()), "CAMPAIGN_JOURNAL_PATH")
        self.lock = self.directory / "writer.lock"
        try:
            with self.lock.open("x") as handle:
                self.lock_value = str(os.getpid()) + ":" + os.urandom(16).hex()
                handle.write(self.lock_value)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            raise Refused("CAMPAIGN_WRITER_LOCK") from None
        self.lock_owned = True
        self.auth_hash, self.entries, self.parent = auth_hash, [], None
        try:
            for index, path in enumerate(sorted(self.directory.glob("*.json")), 1):
                require(path.name == f"{index:06d}.json" and not path.is_symlink(),
                        "CAMPAIGN_JOURNAL_CHAIN")
                raw = bounded_bytes(path)
                entry = decode(raw)
                require(entry.get("previous_sha256") == self.parent
                        and entry.get("auth_sha256") == auth_hash
                        and entry.get("sequence") == index, "CAMPAIGN_JOURNAL_CHAIN")
                self.parent = digest(raw)
                self.entries.append(entry)
        except BaseException:
            self.close()
            raise

    def append(self, kind, **data):
        entry = dict(sequence=len(self.entries) + 1, kind=kind,
                     auth_sha256=self.auth_hash, previous_sha256=self.parent,
                     recorded_utc=utc().isoformat(), **data)
        raw = encoded(entry)
        require(len(raw) <= 65536, "CAMPAIGN_JOURNAL_SIZE")
        path = self.directory / f"{entry['sequence']:06d}.json"
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        self.entries.append(entry)
        self.parent = digest(raw)

    def reconcile(self, runs):
        reserved = {e["nonce"] for e in self.entries if e["kind"] == "RESERVED"}
        remote = {r["display_title"][7:] for r in runs}
        require(reserved == remote, "CAMPAIGN_JOURNAL_REMOTE_CONFLICT")

    def close(self):
        if getattr(self, "lock_owned", False) and self.lock.exists():
            require(bounded_bytes(self.lock, 128).decode() == self.lock_value,
                    "CAMPAIGN_WRITER_LOCK_CHANGED")
            self.lock.unlink()
        self.lock_owned = False


def verify_worker_source(auth):
    require(os.getenv("GITHUB_REPOSITORY") == REPO
            and os.getenv("GITHUB_REF") == "refs/heads/master"
            and os.getenv("GITHUB_SHA") == auth["expected_master"]
            and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and os.getenv("GITHUB_RUN_ATTEMPT") == "1", "CAMPAIGN_WORKER_CONTEXT")
    for path in PINS:
        require(digest(bounded_bytes(ROOT / path, 262144)) == auth["code_pins"][path],
                "CAMPAIGN_CODE_DRIFT")


def verify_new_group(drive, folder, state, checkpoint, meter):
    from tools import alpaca_sip_private_backfill_v1 as cap
    stored = cap._private_object(drive, folder, checkpoint)
    require(decode(stored) == state and state["previous_checkpoint"]["sha256"] == meter.checkpoint_sha,
            "CAMPAIGN_CHECKPOINT_CHAIN")
    objects = state["last_objects"]
    if state["last_status"] == "VERIFIED_RAW_SPLIT":
        require(len(objects) == 3, "CAMPAIGN_GROUP_OBJECTS")
        receipt = decode(cap._private_object(drive, folder, objects[2]))
        raw = cap._private_object(drive, folder, objects[0])
        normalized = cap._private_object(drive, folder, objects[1])
        require(receipt.get("raw_object") == objects[0]
                and receipt.get("normalized_object") == objects[1]
                and receipt.get("source_sha") == os.environ["GITHUB_SHA"]
                and receipt.get("seed_sha256") == SEED_SHA
                and receipt.get("start") == "2016-01-04"
                and receipt.get("end") == "2026-10-14"
                and receipt.get("collected") == state["last_collected"]
                and receipt.get("no_bars") == state["last_no_bars"], "CAMPAIGN_GROUP_RECEIPT")
        require(all(receipt.get(k) is False for k in
                    ("source_admission", "pit_verified", "historical_identity_verified",
                     "commercial_use_authorized")), "CAMPAIGN_GROUP_AUTHORITY")
        cap.verify_archived_group(raw, normalized, receipt)
        meter.rows += receipt["rows"]
        meter.states["VALID_COLLECTED"] += len(receipt["collected"])
        meter.states["VERIFIED_NO_DATA"] += len(receipt["no_bars"])
    else:
        require(state["last_status"] == "HELD_BAR_VALUE" and len(objects) == 1,
                "CAMPAIGN_GROUP_STATUS")
        marker = decode(cap._private_object(drive, folder, objects[0]))
        require(marker.get("status") == "HELD_BAR_VALUE" and marker.get("reason") == "BAR_VALUE"
                and marker.get("symbols") == state["last_held"]
                and marker.get("source_sha") == os.environ["GITHUB_SHA"]
                and marker.get("seed_sha256") == SEED_SHA
                and marker.get("start") == "2016-01-04" and marker.get("end") == "2026-10-14"
                and marker.get("original_price_bytes_retained") is False,
                "CAMPAIGN_HELD_MARKER")
        require(all(marker.get(k) is False for k in
                    ("source_admission", "pit_verified", "historical_identity_verified",
                     "commercial_use_authorized")), "CAMPAIGN_GROUP_AUTHORITY")
        meter.states["QUARANTINED"] += len(state["last_held"])
    meter.examined = len(state["examined"])
    meter.checkpoint_sha = checkpoint["sha256"]
    # Flush the private reference before publishing its SHA in the public
    # meter. No provider bytes enter this existing Actions log surface.
    print("CAMPAIGN_VERIFIED_CHECKPOINT " + json.dumps(checkpoint, sort_keys=True), flush=True)
    meter.save()  # Advances only after a separate, semantic readback.


def worker_deadline(run_id, first):
    payload = gh_json(f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100")
    jobs = payload.get("jobs")
    require(isinstance(jobs, list) and payload.get("total_count") == len(jobs) <= 2,
            "CAMPAIGN_JOB_TIME")
    captures = [j for j in jobs if j.get("name") == "capture" and j.get("status") == "in_progress"]
    require(len(captures) == 1, "CAMPAIGN_JOB_TIME")
    start = utc(captures[0].get("started_at"))
    require(start <= utc() + timedelta(seconds=5), "CAMPAIGN_JOB_TIME")
    # Includes initialization/history downloads, not a fresh clock after them.
    return min(start + timedelta(seconds=7100), first + timedelta(hours=48))


def verify_account_permission(reference, auth_hash, bindings, *, valid_through):
    # Preserve actual account attestations. A separate direct human capture
    # request is execution consent, explicitly not supplier-rights certification.
    match = re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-([0-9]+)", reference or "")
    require(match is not None, "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
    comment = gh_json(f"repos/{REPO}/issues/comments/{match[1]}")
    author = comment.get("user", {})
    require(comment.get("issue_url") == f"https://api.github.com/repos/{REPO}/issues/448"
            and comment.get("author_association") in ("OWNER", "MEMBER", "COLLABORATOR")
            and author.get("type") == "User"
            and type(comment.get("id")) is int and comment["id"] == int(match[1])
            and type(author.get("id")) is int and author["id"] > 0,
            "CAMPAIGN_ACCOUNT_ATTESTOR")
    tags = ("A1_SIP_ACCOUNT_PERMISSION ", "A1_SIP_CAPTURE_DIRECTIVE ")
    lines = [(tag, line[len(tag):]) for line in comment.get("body", "").splitlines()
             for tag in tags if line.startswith(tag)]
    require(len(lines) == 1 and len(lines[0][1]) <= 4096, "CAMPAIGN_ACCOUNT_RECORD")
    tag, raw = lines[0]
    record = decode(raw)
    require(isinstance(record, dict) and record.get("task_key") == TASK
            and record.get("auth_sha256") == auth_hash
            and record.get("bindings") == bindings, "CAMPAIGN_ACCOUNT_RECORD")
    approval_binding = None
    if tag == tags[0]:
        required = {"task_key", "auth_sha256", "bindings", "agreement_reviewed", "account_eligible",
                    "historical_sip_allowed", "private_retention_allowed", "private_noncommercial",
                    "evidence_reference", "expires_at_utc"}
        require(set(record) == required
                and all(record[k] is True for k in ("agreement_reviewed", "account_eligible",
                        "historical_sip_allowed", "private_retention_allowed", "private_noncommercial"))
                and isinstance(record["evidence_reference"], str)
                and 0 < len(record["evidence_reference"]) <= 512, "CAMPAIGN_ACCOUNT_RECORD")
    else:
        required = {"task_key", "auth_sha256", "bindings", "mode", "plan",
                    "personal_historical_capture_requested", "private_noncommercial",
                    "evidence_procedure_waived", "supplier_rights_verified",
                    "approval_reference", "expires_at_utc"}
        require(set(record) == required
                and record["mode"] == "DIRECT_HUMAN_CAPTURE_REQUEST"
                and record["plan"] == "Trading Basic"
                and record["supplier_rights_verified"] is False
                and all(record[k] is True for k in ("personal_historical_capture_requested",
                        "private_noncommercial", "evidence_procedure_waived"))
                and isinstance(record["approval_reference"], str)
                and re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",
                                 record["approval_reference"]) is not None,
                "CAMPAIGN_CAPTURE_DIRECTIVE")
        approval_reference = record["approval_reference"]
        approval_id = int(approval_reference.rsplit("-", 1)[1])
        approval = comment if approval_reference == reference else gh_json(
            f"repos/{REPO}/issues/comments/{approval_id}")
        approval_author = approval.get("user", {})
        require(approval.get("issue_url") == f"https://api.github.com/repos/{REPO}/issues/448"
                and approval.get("author_association") == "OWNER"
                and approval_author.get("type") == "User"
                and type(approval.get("id")) is int and approval["id"] == approval_id
                and type(approval_author.get("id")) is int and approval_author["id"] > 0
                and isinstance(approval.get("body"), str), "CAMPAIGN_CAPTURE_APPROVER")
        approval_lines = [line[len("A1_SIP_CAPTURE_APPROVAL "):]
                          for line in approval["body"].splitlines()
                          if line.startswith("A1_SIP_CAPTURE_APPROVAL ")]
        require(len(approval_lines) == 1 and len(approval_lines[0]) <= 4096,
                "CAMPAIGN_CAPTURE_APPROVAL")
        scope = decode(approval_lines[0])
        approval_fields = {"task_key", "plan", "personal_historical_capture_requested",
                           "private_noncommercial", "evidence_procedure_waived",
                           "supplier_rights_verified", "start", "end", "seed_sha256",
                           "initial_checkpoint_sha256"}
        require(isinstance(scope, dict) and set(scope) == approval_fields
                and scope["task_key"] == TASK and scope["plan"] == "Trading Basic"
                and scope["start"] == "2016-01-04" and scope["end"] == "2026-10-14"
                and scope["seed_sha256"] == SEED_SHA and scope["initial_checkpoint_sha256"] == INITIAL_SHA
                and scope["supplier_rights_verified"] is False
                and all(scope[k] is True for k in ("personal_historical_capture_requested",
                        "private_noncommercial", "evidence_procedure_waived")),
                "CAMPAIGN_CAPTURE_APPROVAL")
        require(isinstance(approval.get("created_at"), str)
                and isinstance(approval.get("updated_at"), str), "CAMPAIGN_CAPTURE_APPROVAL_CLOCK")
        approval_created = utc(approval["created_at"])
        approval_updated = utc(approval["updated_at"])
        require(approval_created <= approval_updated <= utc(comment.get("created_at")),
                "CAMPAIGN_CAPTURE_APPROVAL_CLOCK")
        approval_binding = dict(reference=approval_reference, comment_id=approval["id"],
                                author_id=approval_author["id"], created_at_utc=approval_created.isoformat(),
                                updated_at_utc=approval_updated.isoformat(),
                                body_sha256=digest(approval["body"].encode()), scope=scope)
    now = utc()
    created, expiry = utc(comment.get("created_at")), utc(record["expires_at_utc"])
    require(isinstance(valid_through, datetime) and valid_through.utcoffset() == timedelta(0),
            "CAMPAIGN_CLOCK")
    require(created <= now < valid_through <= expiry,
            "CAMPAIGN_ACCOUNT_EXPIRED")
    # URL identity alone cannot bind a mutable comment. Record the verified
    # assertions and immutable issue/comment/author identity, never raw rights
    # text in the public meter. A later edit must stop the next worker.
    verified = dict(reference=reference, comment_id=comment["id"],
                    issue_url=comment["issue_url"], author_id=author["id"],
                    created_at_utc=created.isoformat(),
                    body_sha256=digest(comment["body"].encode()), record=record)
    if approval_binding is not None:
        verified["capture_approval"] = approval_binding
    return digest(encoded(verified))


def worker(args, control, journal):
    from tools import alpaca_sip_private_backfill_v1 as cap
    from tools.twelve_private_capture import OwnerDrive
    require(os.getenv("A1_PRIVATE_RESEARCH_AUTHORIZED") == "true"
            and os.getenv("ALPACA_NONCOMMERCIAL_ACKNOWLEDGED") == "true",
            "USER_AUTHORIZATION_MISSING")
    require(isinstance(control, dict) and {"authorization", "nonce"} <= set(control)
            and set(control) <= {"authorization", "nonce", "recovery_run", "preflight_only",
                                 "account_permission_reference"}, "CAMPAIGN_CONTROL_REQUIRED")
    auth = control.get("authorization")
    auth_hash = validate_authorization(auth)
    verify_worker_source(auth)
    nonce = control.get("nonce")
    require(isinstance(nonce, str) and re.fullmatch(PREFIX + r"[0-9a-f]{24}", nonce)
            and nonce == os.getenv("INPUT_CAMPAIGN_NONCE"), "CAMPAIGN_NONCE")
    current_id = int(os.environ["GITHUB_RUN_ID"])
    recovered = control.get("recovery_run")
    require(recovered is None or type(recovered) is int, "CAMPAIGN_RECOVERY")
    observed = history(auth, current_id, nonce, recovered)
    preflight = control.get("preflight_only") is True
    require(type(control.get("preflight_only", False)) is bool, "CAMPAIGN_PREFLIGHT")
    permission = auth.get("account_permission_reference") or control.get("account_permission_reference")
    require(preflight or (isinstance(permission, str) and 0 < len(permission) <= 512),
            "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
    require(preflight or observed.get("permission_hash") is None or
            (permission is not None and digest(permission.encode()) == observed["permission_hash"]),
            "CAMPAIGN_RIGHTS_DRIFT")
    if observed["examined"] > 16 and (observed["examined"] - 16) % 128 == 0:
        require(forecast_remaining(observed)["fits_current_budgets"], "CAMPAIGN_CALIBRATION_BUDGET")
    require(len(observed["runs"]) <= 40
            and observed["active_seconds"] + 7800 <= 28800, "CAMPAIGN_ACTIVE_RESERVATION")
    require(args.resume_sha256 == observed["parent_sha"]
            and args.private_root_folder_id == auth["private_root_folder_id"]
            and args.private_data_folder_id == auth["private_data_folder_id"]
            and args.start == auth["start"] and args.end == auth["end"]
            and args.max_new_symbols == next_batch(observed["examined"]), "CAMPAIGN_PARENT")
    if observed["examined"] == 16:
        require(args.resume_file_id == auth["initial_checkpoint_file_id"], "CAMPAIGN_INITIAL_REF")
    require(digest(cap.SEED.read_bytes()) == SEED_SHA, "CAMPAIGN_SEED")
    key, secret = os.getenv("ALPACA_API_KEY", "").strip(), os.getenv("ALPACA_API_SECRET", "").strip()
    actual_key = digest((key + "\0" + secret).encode())
    prior_bindings = observed.get("bindings")
    expected_key = auth.get("credential_binding") or (prior_bindings or {}).get("credential_binding")
    require(key and secret and (expected_key == actual_key or (preflight and expected_key is None)),
            "CAMPAIGN_CREDENTIAL_BINDING")
    first = observed["first"] or utc()
    deadline = worker_deadline(current_id, first)
    record_hash = None
    if not preflight:
        expected_bindings = prior_bindings or (dict(owner_sha256=digest(auth["owner_permission_id"].encode()),
                                                   credential_binding=actual_key) if auth.get("owner_permission_id") else None)
        require(expected_bindings is not None, "CAMPAIGN_OWNER_BINDING")
        record_hash = verify_account_permission(permission, auth_hash, expected_bindings,
                                                valid_through=deadline)
        require(observed.get("permission_record_hash") is None or
                record_hash == observed["permission_record_hash"], "CAMPAIGN_RIGHTS_DRIFT")
    identity = dict(task_key=TASK, auth_sha256=auth_hash, source_sha=auth["expected_master"],
                    nonce=nonce, run_id=current_id, run_attempt=1,
                    recovery_run=recovered,
                    preflight_only=preflight, bindings=prior_bindings,
                    account_permission_reference_sha256=digest(permission.encode()) if not preflight else None,
                    account_permission_record_sha256=record_hash,
                    parent_checkpoint_sha256=args.resume_sha256,
                    examined_before=observed["examined"])
    meter = RuntimeMeter(observed["remaining"], journal, deadline.isoformat(), identity)
    def factory(root, temp):
        drive = OwnerDrive(root, temp, meter=meter)
        owner = auth.get("owner_permission_id")
        require(owner is None or drive.owner == owner, "CAMPAIGN_OWNER_BINDING")
        actual_bindings = dict(owner_sha256=digest(drive.owner.encode()), credential_binding=actual_key)
        require(prior_bindings is None or prior_bindings == actual_bindings, "CAMPAIGN_ACCOUNT_DRIFT")
        meter.identity["bindings"] = actual_bindings
        minimum = 2 * 1024**3 if observed["examined"] == 16 else observed["remaining"]["storage_bytes"]
        require(drive.free >= minimum, "CAMPAIGN_DRIVE_SPACE")
        meter.identity["free_bytes_at_start"] = drive.free
        meter.save()
        return drive
    try:
        with meter.process_deadline():
            if preflight:
                with tempfile.TemporaryDirectory(prefix="a1-meter-preflight-") as temp:
                    drive = factory(args.private_root_folder_id, temp)
                    drive.check(args.private_data_folder_id, drive.root_id)
                meter.finish("COMPLETE")
                print(json.dumps(dict(status="CAMPAIGN_PREFLIGHT_COMPLETE", provider_entitlement="NOT_PROBED",
                                      price_collection=0, source_admission=False)), flush=True)
                return None
            result = cap._collect(args, drive_factory=factory, get=meter.perform,
                                  on_group=lambda drive, state, ref: verify_new_group(
                                      drive, args.private_data_folder_id, state, ref, meter),
                                  expected_examined=observed["examined"])
        require(meter.examined == observed["examined"] + args.max_new_symbols
                and meter.checkpoint_sha == result["checkpoint"]["sha256"], "CAMPAIGN_BATCH_CLOSURE")
        meter.finish("COMPLETE")
        return result
    except Refused as exc:
        meter.finish("BLOCKED", str(exc))
        raise
    except Exception:
        meter.finish("BLOCKED", "CAMPAIGN_INTERNAL")
        raise Refused("CAMPAIGN_INTERNAL") from None


def checkpoint_from_log(run, receipt, parent_ref):
    if receipt["checkpoint_sha256"] == receipt["parent_checkpoint_sha256"]:
        require(parent_ref["sha256"] == receipt["checkpoint_sha256"], "CAMPAIGN_LOCAL_PARENT")
        return parent_ref
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(["gh", "run", "view", str(run["id"]), "--repo", REPO, "--log"],
                                stdout=output, stderr=subprocess.DEVNULL, timeout=45)
        require(result.returncode == 0, "CAMPAIGN_PRIVATE_REF_LOG")
        output.seek(0)
        raw = output.read(8_000_001)
    require(len(raw) <= 8_000_000, "CAMPAIGN_LOG_SIZE")
    refs = []
    marker = "CAMPAIGN_VERIFIED_CHECKPOINT "
    for line in raw.decode("utf-8", errors="strict").splitlines():
        if marker in line:
            ref = decode(line.split(marker, 1)[1])
            if ref.get("sha256") == receipt["checkpoint_sha256"]:
                require(set(ref) == {"file_id", "sha256", "bytes"}
                        and isinstance(ref["file_id"], str)
                        and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", ref["file_id"])
                        and type(ref["bytes"]) is int and 0 < ref["bytes"] <= 16_000_000,
                        "CAMPAIGN_PRIVATE_REF_LOG")
                refs.append(ref)
    require(len(refs) == 1, "CAMPAIGN_PRIVATE_REF_LOG")
    return refs[0]


def settled_parent(journal, auth):
    for entry in reversed(journal.entries):
        if entry["kind"] == "SETTLED":
            return entry["checkpoint"]
    return dict(file_id=auth["initial_checkpoint_file_id"], sha256=INITIAL_SHA, bytes=1375)


def settle_run(journal, auth, run, receipt):
    parent = settled_parent(journal, auth)
    require(receipt["parent_checkpoint_sha256"] == parent["sha256"], "CAMPAIGN_LOCAL_PARENT")
    ref = checkpoint_from_log(run, receipt, parent)
    journal.append("SETTLED", nonce=receipt["nonce"], run_id=run["id"],
                   usage=receipt["usage"], checkpoint=ref,
                   receipt=receipt,
                   examined_after=receipt["examined_after"],
                   receipt_sha256=digest(encoded(receipt)))


def progress_summary(observed, status):
    states = dict(VALID_COLLECTED=16, VERIFIED_NO_DATA=0, QUARANTINED=0,
                  IDENTITY_UNRESOLVED=0, PENDING=1009 - observed["examined"])
    for receipt in observed["receipts"]:
        for key, count in receipt["new_states"].items():
            states[key] += count
    require(sum(states.values()) == 1009, "CAMPAIGN_SUMMARY_PARTITION")
    return dict(task_key=TASK, status=status, states=states,
                new_processed=observed["examined"] - 16, total_processed=observed["examined"],
                processing_rate=observed["examined"] / 1009,
                OHLCV_raw_split_symbol_coverage=states["VALID_COLLECTED"] / 1009,
                session_grid_coverage="NOT_ESTABLISHED", research_eligibility="NOT_ESTABLISHED",
                original16_rows=81592,
                new_verified_rows=sum(r["rows_verified"] for r in observed["receipts"]),
                charged_usage=observed["used"],
                confirmed_successful_upload_bytes=sum(r["confirmed_storage_bytes"] for r in observed["receipts"]),
                observed_successful_google_body_bytes=sum(r["observed_google_body_bytes"] for r in observed["receipts"]),
                transfer_definition=METRIC, active_seconds=observed["active_seconds"],
                workflow_dispatches=len(observed["runs"]), last_checkpoint_sha256=observed["parent_sha"],
                first_workflow_created_utc=observed["first"].isoformat() if observed["first"] else None,
                source_admission=False, pit_verified=False, economic_authority=False)


def host(auth_path, state_dir, recovery_run=None, permission_reference=None):
    """One finite, serial Work process; never invoked by PR checks."""
    auth = bounded_json(auth_path)
    auth_hash = validate_authorization(auth)
    journal = WorkJournal(state_dir, auth_hash)
    last_observed = None
    try:
        while True:
            observed = history(auth, recovery_run=recovery_run, enforce_expiry=False)
            last_observed = observed
            journal.reconcile(observed["runs"])
            if journal.entries and journal.entries[-1]["kind"] in ("RESERVED", "RUN_ASSIGNED"):
                nonce = journal.entries[-1]["nonce"]
                pending = [r for r in observed["runs"] if r["display_title"] == "a1-sip " + nonce]
                require(len(pending) == 1 and pending[0]["status"] == "completed", "CAMPAIGN_ACTIVE_RESERVATION")
                receipt = receipt_for_run(pending[0], auth_hash, auth["expected_master"])
                settle_run(journal, auth, pending[0], receipt)
            if observed["examined"] > 16 and (observed["examined"] - 16) % 128 == 0:
                forecast = forecast_remaining(observed)
                print(json.dumps(dict(status="128_REVIEW", **forecast)), flush=True)
                require(forecast["fits_current_budgets"], "CAMPAIGN_CALIBRATION_BUDGET")
            if observed["examined"] == 1009:
                summary = progress_summary(observed, "RAW_CAMPAIGN_PROCESSED")
                atomic_json(journal.directory / "progress", summary)
                print(json.dumps(summary))
                return
            require(len(observed["runs"]) < 40 and observed["active_seconds"] + 7800 <= 28800,
                    "CAMPAIGN_DISPATCH_BUDGET")
            require(gh_json("repos/" + REPO + "/branches/master")["commit"]["sha"] == auth["expected_master"],
                    "CAMPAIGN_MASTER_DRIFT")
            # Compare canonical deployed bytes; no current-branch substitution.
            for path in PINS:
                file = gh_json(f"repos/{REPO}/contents/{path}?ref={auth['expected_master']}")
                require(file.get("encoding") == "base64"
                        and digest(base64.b64decode(file["content"], validate=False)) == auth["code_pins"][path],
                        "CAMPAIGN_DEPLOYED_CODE")
            current_ref = settled_parent(journal, auth)
            require(current_ref and current_ref["sha256"] == observed["parent_sha"], "CAMPAIGN_LOCAL_PARENT")
            require(not journal.entries or journal.entries[-1]["kind"] == "SETTLED",
                    "CAMPAIGN_ACTIVE_RESERVATION")
            nonce = PREFIX + os.urandom(12).hex()
            bindings_missing = (observed.get("bindings") is None and
                                (auth.get("owner_permission_id") is None or auth.get("credential_binding") is None))
            preflight = bool(bindings_missing)
            permission = auth.get("account_permission_reference") or permission_reference
            require(preflight or (isinstance(permission, str) and 0 < len(permission) <= 512),
                    "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
            require(observed["first"] is None or utc() < observed["first"] + timedelta(hours=48),
                    "CAMPAIGN_EXPIRED")
            control = dict(authorization=auth, nonce=nonce, recovery_run=recovery_run,
                           preflight_only=preflight, account_permission_reference=permission)
            control_raw = encoded(control).decode()
            require(len(control_raw) <= 16384, "CAMPAIGN_CONTROL_SIZE")
            journal.append("RESERVED", nonce=nonce, remaining=observed["remaining"],
                           active_seconds_remaining=28800 - observed["active_seconds"],
                           parent_checkpoint_sha256=observed["parent_sha"])
            inputs = dict(private_root_folder_id=auth["private_root_folder_id"],
                          private_data_folder_id=auth["private_data_folder_id"],
                          private_research_authorized=True, noncommercial_terms_acknowledged=True,
                          end_date=auth["end"], max_new_symbols=next_batch(observed["examined"]),
                          resume_file_id=current_ref["file_id"], resume_sha256=current_ref["sha256"],
                          campaign_control=control_raw, campaign_nonce=nonce)
            result = subprocess.run(["gh", "workflow", "run", WORKFLOW, "--repo", REPO,
                                     "--ref", "master", "--json"], input=json.dumps(inputs).encode(),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
            require(result.returncode == 0, "CAMPAIGN_DISPATCH_UNCERTAIN")
            run = None
            for _ in range(30):
                matches = [r for r in campaign_runs() if r["display_title"] == "a1-sip " + nonce]
                require(len(matches) <= 1, "CAMPAIGN_NONCE_REPLAY")
                if matches:
                    run = matches[0]
                    break
                time.sleep(2)
            require(run is not None, "CAMPAIGN_DISPATCH_UNCERTAIN")
            journal.append("RUN_ASSIGNED", nonce=nonce, run_id=run["id"])
            # The local reservation survives interruption/unknown remote status.
            result = subprocess.run(["gh", "run", "watch", str(run["id"]), "--repo", REPO,
                                     "--exit-status", "--interval", "30"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=9000)
            fresh = gh_json(f"repos/{REPO}/actions/runs/{run['id']}")
            receipt = receipt_for_run(fresh, auth_hash, auth["expected_master"])
            settle_run(journal, auth, fresh, receipt)
            # Known closed outcomes can be handed off even if the run failed;
            # an unknown/missing meter never reaches this point.
            updated = dict(observed)
            updated["receipts"] = observed["receipts"] + [receipt]
            updated["runs"] = observed["runs"] + [fresh]
            updated["used"] = {k: observed["used"][k] + receipt["usage"][k] for k in LIMITS}
            updated["active_seconds"] = observed["active_seconds"] + job_seconds(fresh)
            updated["examined"], updated["parent_sha"] = receipt["examined_after"], receipt["checkpoint_sha256"]
            updated["first"] = observed["first"] or utc(fresh["created_at"])
            last_observed = updated
            atomic_json(journal.directory / "progress", progress_summary(updated, receipt["status"]))
            require(result.returncode == 0 and receipt["status"] == "COMPLETE", "CAMPAIGN_WORKER_BLOCKED")
            recovery_run = None
            examined = receipt["examined_after"]
            print(json.dumps(dict(status="BATCH_VERIFIED", new_processed=examined - 16,
                                  total_examined=examined, rows_new=receipt["rows_verified"],
                                  usage_delta=receipt["usage"], checkpoint_sha256=receipt["checkpoint_sha256"])), flush=True)
    except BaseException:
        if last_observed is not None:
            summary = progress_summary(last_observed, "BLOCKED")
            pending = [e for e in journal.entries if e["kind"] == "RESERVED"]
            unsettled = bool(journal.entries and journal.entries[-1]["kind"] != "SETTLED")
            summary["unsettled_reservation"] = pending[-1]["remaining"] if unsettled and pending else None
            try:
                atomic_json(journal.directory / "progress", summary)
            except OSError:
                pass  # The append-only reservation and canonical evidence remain.
        raise
    finally:
        journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--recovery-run", type=int)
    parser.add_argument("--account-permission-reference")
    args = parser.parse_args()
    try:
        host(args.authorization, args.state_dir, args.recovery_run, args.account_permission_reference)
        return 0
    except Refused as exc:
        print(json.dumps(dict(status="BLOCKED", code=str(exc), source_admission=False)))
        return 2
    except Exception:
        print(json.dumps(dict(status="BLOCKED", code="CAMPAIGN_INTERNAL", source_admission=False)))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
