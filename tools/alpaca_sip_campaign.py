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
CONTINUED_LIMITS = dict(LIMITS, drive_bytes=9 * 1024**3)
# One human-approved continuation of the measured128-name stop, not a reset
# or a general budget/account migration facility. All identifiers are public
# run IDs or evidence hashes; private objects and credentials stay external.
CONTINUATION = dict(
    auth="b5f25d1bac9b393bc5101fa3562b95e7a54ed3c6f79768b4651b541e454bdf9e",
    master="5a762256a17851b864595265c6e83c01f22f9a0a",
    checkpoint="032dac3437c379f6cebc00f3b1e2f0315304974a8f16b39787086c2614048605",
    event="e4bbd55f825e17745270ea9a8c7893253728cc1c9e15938adc5e5695b64408bb",
    progress="af888fc6e3b72c451269f06f61ec673597db7159ef4fc822d38bcafeea4e7630",
    request="e602411e37b3e6e544a46e7fc78b1a320acfbde891ead7b7268efe79ebca8eec",
    runs=[38993769026, 38994018637, 38994265036, 38994543208, 38994825057],
    receipts=["9337aa3aac842a7c128488e3a4a221a40697243396613834b299acd8269af120",
              "b16472531ef68c90756683abaaa447c2a596c7e66f76ccbc23062b6438ddeeb3",
              "a1aa85c89c2508a6a75ad3daf35372bdf03c1ede036586938e29b151b4499c14",
              "1a26ad29e6c6dfec2293d1be697cb78c52cd17f172693649bdceb4e06d9f95a2",
              "93e1ce073ae2c4bfccd70bebf40a4e834cd1ea03608e757c039be49214a6604f"],
    used=dict(provider_gets=88, drive_requests=1428, drive_bytes=235895806, storage_bytes=28012817),
    bindings=dict(credential_binding="0c71faf943d489e215c81bcd31affe6b8f6600b646a3462ed02c97fab1637ad2",
                  owner_sha256="08e29aa6cca772e9319b2aab20ad9fdba5dd0d8fce08a90b9fdbf3253fe9a94e"),
    permission_record="f6bcb213cacc09e41288375da7ad983607da99614a41b6cb9ab7e4e23fd27e0e",
    active_seconds=872, examined=144, events=17, first="2026-10-17T02:08:51Z")
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
    continued = isinstance(auth, dict) and "continuation" in auth
    external = isinstance(auth, dict) and "external_cohort" in auth
    require(not (continued and external), "CAMPAIGN_AUTHORIZATION")
    require(isinstance(auth, dict) and set(auth) == AUTH_FIELDS | (
            {"external_cohort"} if external else {"continuation"} if continued else set())
            and auth.get("schema") == ("r1000-sip-external-cohort-authorization-v1" if external else
                                       "r1000-sip-campaign-authorization-v2" if continued else
                                       "r1000-sip-campaign-authorization-v1") and auth.get("task_key") == TASK
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
    require(auth.get("limits") == (CONTINUED_LIMITS if continued or external else LIMITS)
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
    if continued:
        continuation = auth["continuation"]
        require(isinstance(continuation, dict) and set(continuation) == {"prior_authorization", "proof_reference"},
                "CAMPAIGN_CONTINUATION_AUTH")
        prior = continuation["prior_authorization"]
        require(isinstance(prior, dict) and "continuation" not in prior,
                "CAMPAIGN_CONTINUATION_AUTH")
        require(validate_authorization(prior) == CONTINUATION["auth"]
                and prior["expected_master"] == CONTINUATION["master"]
                and auth["expected_master"] != prior["expected_master"]
                and all(auth[k] == prior[k] for k in AUTH_FIELDS - {"schema", "limits", "expected_master", "code_pins"}),
                "CAMPAIGN_CONTINUATION_SCOPE")
        require(isinstance(continuation["proof_reference"], str) and re.fullmatch(
            r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",
            continuation["proof_reference"]), "CAMPAIGN_CONTINUATION_PROOF")
    if external:
        validate_external_authorization(auth)
    return digest(encoded(auth))


def active_limit(auth):
    return 43200 if "continuation" in auth or "external_cohort" in auth else 28800


def continuation_proof(auth):
    """Bind the real OWNER record to exactly this one finite, spent prefix."""
    if "continuation" not in auth:
        return None
    auth_hash = validate_authorization(auth)
    reference = auth["continuation"]["proof_reference"]
    comment_id = int(reference.rsplit("-", 1)[1])
    comment = gh_json(f"repos/{REPO}/issues/comments/{comment_id}")
    author = comment.get("user", {})
    require(comment.get("id") == comment_id and type(comment.get("id")) is int
            and comment.get("issue_url") == f"https://api.github.com/repos/{REPO}/issues/448"
            and comment.get("author_association") == "OWNER" and author.get("type") == "User"
            and type(author.get("id")) is int and author["id"] > 0
            and isinstance(comment.get("body"), str), "CAMPAIGN_CONTINUATION_ATTESTOR")
    tag = "A1_SIP_BOUNDED_CONTINUATION "
    lines = [line[len(tag):] for line in comment["body"].splitlines() if line.startswith(tag)]
    require(len(lines) == 1 and len(lines[0]) <= 4096, "CAMPAIGN_CONTINUATION_PROOF")
    record = decode(lines[0])
    expected = dict(schema="a1-sip-bounded-continuation-v1", task_key=TASK,
                    prior_auth_sha256=CONTINUATION["auth"], auth_sha256=auth_hash,
                    prior_journal_event_sha256=CONTINUATION["event"],
                    prior_progress_sha256=CONTINUATION["progress"],
                    checkpoint_sha256=CONTINUATION["checkpoint"],
                    prior_run_ids=CONTINUATION["runs"], prior_usage=CONTINUATION["used"],
                    prior_active_seconds=CONTINUATION["active_seconds"], prior_examined=CONTINUATION["examined"],
                    first_canonical_utc=CONTINUATION["first"],
                    expires_at_utc=(utc(CONTINUATION["first"])+timedelta(hours=48)).isoformat(),
                    request_sha256=CONTINUATION["request"], limits=CONTINUED_LIMITS,
                    active_seconds_limit=43200, dispatch_limit=40, preserve_seed_order=True,
                    account_rotation=False, expected_master=auth["expected_master"],
                    code_pins_sha256=digest(encoded(auth["code_pins"])))
    require(isinstance(record, dict) and set(record) == set(expected)
            and all(record[k] == v and type(record[k]) is type(v) for k,v in expected.items())
            and all(type(record["prior_usage"][k]) is int and type(record["limits"][k]) is int for k in LIMITS)
            and all(type(v) is int for v in record["prior_run_ids"]), "CAMPAIGN_CONTINUATION_PROOF")
    require(isinstance(comment.get("created_at"), str) and isinstance(comment.get("updated_at"), str),
            "CAMPAIGN_CONTINUATION_CLOCK")
    created, updated = utc(comment["created_at"]), utc(comment["updated_at"])
    require(utc(CONTINUATION["first"]) <= created <= updated <= utc()
            and updated < utc(expected["expires_at_utc"]), "CAMPAIGN_CONTINUATION_CLOCK")
    permission = account_permission_evidence(reference, auth_hash, CONTINUATION["bindings"])
    require(permission["body_sha256"] == digest(comment["body"].encode())
            and permission["record"]["expires_at_utc"] == expected["expires_at_utc"],
            "CAMPAIGN_CONTINUATION_PERMISSION")
    return dict(prior_auth_sha256=CONTINUATION["auth"],
                prior_journal_event_sha256=CONTINUATION["event"],
                checkpoint_sha256=CONTINUATION["checkpoint"], prior_usage=CONTINUATION["used"],
                prior_active_seconds=CONTINUATION["active_seconds"], prior_examined=CONTINUATION["examined"],
                first_canonical_utc=CONTINUATION["first"], expires_at_utc=expected["expires_at_utc"],
                proof_reference=reference, proof_created_utc=created.isoformat(), proof_updated_utc=updated.isoformat(),
                proof_sha256=digest(encoded(dict(author_id=author["id"], body_sha256=digest(comment["body"].encode()),
                                               created_at=created.isoformat(), updated_at=updated.isoformat(), record=record))),
                prior_permission_record_sha256=CONTINUATION["permission_record"],
                permission_reference_sha256=digest(reference.encode()),
                permission_record_sha256=digest(encoded(permission)),
                limits=CONTINUED_LIMITS, active_seconds_limit=43200,
                expected_master=auth["expected_master"], code_pins_sha256=expected["code_pins_sha256"])


class RuntimeMeter:
    """Write conservative debit before I/O; settle only a complete response.

    Transfer means HTTP bodies (including multipart) plus a fixed conservative
    overhead allowance. It is not an encrypted socket/TLS byte measurement.
    This explicit metric must be accepted in the immutable authorization.
    """
    def __init__(self, allowance, journal, deadline, identity, clock=utc,
                 opener=None, limits=None, asset_symbols=()):
        caps = LIMITS if limits is None else limits
        require(caps in (LIMITS, CONTINUED_LIMITS), "CAMPAIGN_LIMITS")
        require(set(allowance) == set(LIMITS), "CAMPAIGN_COUNTER")
        self.allowance = {k: integer(allowance[k], caps[k]) for k in LIMITS}
        self.used = {k: 0 for k in LIMITS}
        self.journal, self.deadline = Path(journal), utc(deadline)
        self.identity, self.clock = dict(identity), clock
        require(isinstance(asset_symbols, (list, tuple)) and len(asset_symbols) <= 32
                and len(set(asset_symbols)) == len(asset_symbols)
                and all(isinstance(s, str) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,13}", s)
                        for s in asset_symbols), "CAMPAIGN_ASSET_SCOPE")
        self.asset_symbols = tuple(asset_symbols)
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
        asset = (endpoint.netloc == "paper-api.alpaca.markets" and not endpoint.query
                 and endpoint.path in {"/v2/assets/" + s for s in self.asset_symbols})
        provider = provider or asset
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
            code = ("ASSET_NOT_FOUND" if asset and exc.code == 404 else
                    {401: "AUTH", 402: "ENTITLEMENT", 403: "PERMISSION", 429: "RATE_LIMIT"}.get(exc.code, "HTTP_ERROR"))
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


def receipt_for_run(run, auth_hash, expected_master, limits=None):
    caps = LIMITS if limits is None else limits
    require(caps in (LIMITS, CONTINUED_LIMITS), "CAMPAIGN_LIMITS")
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
            and (value.get("auth_sha256") in auth_hash if isinstance(auth_hash, tuple)
                 else value.get("auth_sha256") == auth_hash)
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
        integer(value["usage"][name], caps[name])
        integer(value["allowance"][name], caps[name])
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
            and integer(value.get("observed_google_body_bytes"), caps["drive_bytes"]) <= value["usage"]["drive_bytes"],
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
    if isinstance(auth, dict) and "external_cohort" in auth:
        return external_history(auth, current_run, nonce, recovery_run, enforce_expiry)
    auth_hash = validate_authorization(auth)
    continuation = continuation_proof(auth)
    prior = auth["continuation"]["prior_authorization"] if continuation else None
    runs = campaign_runs(auth["workflow_run_floor"])
    if continuation:
        require([r["id"] for r in runs[:len(CONTINUATION["runs"])]] == CONTINUATION["runs"],
                "CAMPAIGN_CONTINUATION_PREFIX")
        require(all(utc(r["created_at"]) >= utc(continuation["proof_updated_utc"])
                    for r in runs[len(CONTINUATION["runs"]):]), "CAMPAIGN_CONTINUATION_CLOCK")
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
    values = []
    for index, run in enumerate(previous):
        if continuation and index < len(CONTINUATION["runs"]):
            value = receipt_for_run(run, CONTINUATION["auth"], prior["expected_master"])
            require(digest(encoded(value)) == CONTINUATION["receipts"][index], "CAMPAIGN_CONTINUATION_PREFIX")
        elif continuation:
            value = receipt_for_run(run, auth_hash, auth["expected_master"], auth["limits"])
            require(value.get("continuation_proof_sha256") == continuation["proof_sha256"],
                    "CAMPAIGN_CONTINUATION_DRIFT")
        else:
            value = receipt_for_run(run, auth_hash, auth["expected_master"])
        values.append(value)
    for index, (run, value) in enumerate(zip(previous, values)):
        if continuation and index == len(CONTINUATION["runs"]):
            # The only allowed permission transition is hash-bound in the
            # typed bridge; arbitrary same-URL/body/account drift still fails.
            permission_hash = continuation["permission_reference_sha256"]
            permission_record_hash = continuation["permission_record_sha256"]
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
            caps = prior["limits"] if continuation and index < len(CONTINUATION["runs"]) else auth["limits"]
            require(value["allowance"][name] == caps[name] - used[name], "CAMPAIGN_ALLOWANCE_RESET")
            used[name] += value["usage"][name]
            require(used[name] <= caps[name], "CAMPAIGN_LEDGER_BUDGET")
        duration = job_seconds(run)
        active += duration
        durations.append(duration)
        parent, examined = value["checkpoint_sha256"], after
        receipts.append(value)
        if continuation and index + 1 == len(CONTINUATION["runs"]):
            require(used == CONTINUATION["used"] and active == CONTINUATION["active_seconds"]
                    and examined == CONTINUATION["examined"] and parent == CONTINUATION["checkpoint"]
                    and bindings == CONTINUATION["bindings"]
                    and permission_record_hash == CONTINUATION["permission_record"], "CAMPAIGN_CONTINUATION_PREFIX")
        require((value["status"] == "COMPLETE" and run.get("conclusion") == "success") or
                (value.get("reason") in ("NETWORK", "HTTP_ERROR") and
                 ((run["id"] == recovery_run and run == previous[-1]) or
                  (index + 1 < len(values) and values[index + 1].get("recovery_run") == run["id"]))),
                "CAMPAIGN_FAILED_RUN_REQUIRES_RECOVERY")
    require(active <= active_limit(auth), "CAMPAIGN_ACTIVE_TIME")
    first = utc(runs[0]["created_at"]) if runs else None
    if continuation:
        require(first == utc(CONTINUATION["first"]), "CAMPAIGN_CONTINUATION_CLOCK")
        if len(previous) == len(CONTINUATION["runs"]):
            permission_hash = continuation["permission_reference_sha256"]
            permission_record_hash = continuation["permission_record_sha256"]
    if first is not None and enforce_expiry:
        require(utc() < first + timedelta(hours=48), "CAMPAIGN_EXPIRED")
    return dict(runs=runs, receipts=receipts, used=used, active_seconds=active, bindings=bindings,
                permission_hash=permission_hash, permission_record_hash=permission_record_hash,
                durations=durations, active_limit=active_limit(auth), continuation=continuation,
                parent_sha=parent, examined=examined, first=first,
                remaining={k: auth["limits"][k] - used[k] for k in LIMITS})


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
    fits = fits and seconds <= observed.get("active_limit", 28800) - observed["active_seconds"]
    return dict(new_processed=processed, remaining_candidates=remaining_names,
                estimated_remaining=estimates, estimated_remaining_active_seconds=seconds,
                margin=1.25, estimate_only=True, fits_current_budgets=fits)


def next_batch(examined):
    require(type(examined) is int and 16 <= examined < 1009, "CAMPAIGN_PROGRESS")
    # Normal campaign is31x32+1. After a partial failed batch, align with the
    # next128-new-symbol checkpoint instead of silently skipping calibration.
    return min(32, 1009 - examined, 128 - (examined - 16) % 128)


# One named, independently reproduced local CLI rejection; not a general refund.
LOCAL_REJECT = dict(
    auth="f67185f7cec535c3f9bce5b1585407ee47543aab9768a6c82fe66152f1b9aecd",
    reservation="91f8f12d1f1687e7f7d448e35abc92fb1cf389736a7900c9c137f3c79363ecb1",
    progress="af97dd8256eabeb0b5ee000f03881c4a12d8b581eaad6ff556eaad46e8afbec6",
    cli_binary="619787d8ee760105ccf8a554d164c6e67196d1ec77a5fd31c39afe32cff640a9",
    cli_evidence="8d5fedba10336bb5d4796c9196d8b5197f5a9ff04d79721031dabfc93520ec50",
    independent_qa="d1651c00253e7164bfac49a5e82b4ff8d8df2bde753ce6e78976e81955306a9d")


def local_reject_recovery(bundle_path, auth, directory):
    """Read-only proof for the single pre-first-dispatch rejection. No I/O refund."""
    bundle = bounded_json(bundle_path)
    require(isinstance(bundle, dict) and set(bundle) ==
            {"prior_authorization", "prior_progress_snapshot", "proof_reference", "receipt_path"}
            and all(isinstance(v, str) and 0 < len(v) <= 4096 for v in bundle.values()),
            "CAMPAIGN_LOCAL_REJECT_BUNDLE")
    snapshot = Path(bundle["prior_progress_snapshot"])
    resolved_snapshot, resolved_state = snapshot.resolve(), Path(directory).resolve()
    require(not snapshot.is_symlink() and resolved_snapshot != resolved_state
            and resolved_state not in resolved_snapshot.parents, "CAMPAIGN_LOCAL_REJECT_SNAPSHOT_PATH")
    receipt = Path(bundle["receipt_path"])
    resolved_receipt, resolved_directory = receipt.resolve(), Path(directory).resolve()
    inputs = {Path(v).resolve() for v in (bundle_path, bundle["prior_authorization"],
                                         bundle["prior_progress_snapshot"])}
    require(not receipt.is_symlink() and resolved_receipt != resolved_directory
            and resolved_directory not in resolved_receipt.parents
            and resolved_receipt not in inputs, "CAMPAIGN_LOCAL_REJECT_RECEIPT_PATH")
    prior_raw = bounded_bytes(bundle["prior_authorization"])
    require(digest(prior_raw) == LOCAL_REJECT["auth"], "CAMPAIGN_LOCAL_REJECT_AUTH")
    prior = decode(prior_raw)
    old_hash, new_hash = validate_authorization(prior), validate_authorization(auth)
    require(old_hash == LOCAL_REJECT["auth"] and new_hash != old_hash,
            "CAMPAIGN_LOCAL_REJECT_AUTH")
    mutable = {"expected_master", "code_pins", "workflow_run_floor"}
    scope = {k: v for k, v in prior.items() if k not in mutable}
    require(scope == {k: v for k, v in auth.items() if k not in mutable}
            and auth["expected_master"] != prior["expected_master"]
            and auth["workflow_run_floor"] >= prior["workflow_run_floor"],
            "CAMPAIGN_LOCAL_REJECT_SCOPE")
    reserved_raw = bounded_bytes(Path(directory) / "000001.json")
    require(digest(reserved_raw) == LOCAL_REJECT["reservation"]
            and digest(bounded_bytes(bundle["prior_progress_snapshot"])) == LOCAL_REJECT["progress"],
            "CAMPAIGN_LOCAL_REJECT_PREFIX")
    reserved = decode(reserved_raw)
    require(reserved.get("kind") == "RESERVED" and reserved.get("sequence") == 1
            and reserved.get("previous_sha256") is None and reserved.get("auth_sha256") == old_hash
            and reserved.get("remaining") == LIMITS and reserved.get("active_seconds_remaining") == 28800
            and reserved.get("parent_checkpoint_sha256") == INITIAL_SHA,
            "CAMPAIGN_LOCAL_REJECT_PREFIX")
    reference = bundle["proof_reference"]
    match = re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-([0-9]+)", reference)
    require(match is not None, "CAMPAIGN_LOCAL_REJECT_PROOF")
    comment = gh_json(f"repos/{REPO}/issues/comments/{match[1]}")
    author = comment.get("user", {})
    require(comment.get("issue_url") == f"https://api.github.com/repos/{REPO}/issues/448"
            and comment.get("author_association") == "OWNER" and author.get("type") == "User"
            and type(author.get("id")) is int and author["id"] > 0
            and type(comment.get("id")) is int and comment["id"] == int(match[1])
            and comment["id"] > 0 and isinstance(comment.get("body"), str),
            "CAMPAIGN_LOCAL_REJECT_ATTESTOR")
    tag = "A1_SIP_LOCAL_REJECT_RECOVERY "
    lines = [v[len(tag):] for v in comment["body"].splitlines() if v.startswith(tag)]
    require(len(lines) == 1 and len(lines[0]) <= 4096, "CAMPAIGN_LOCAL_REJECT_PROOF")
    record = decode(lines[0])
    expected = dict(schema="a1-sip-local-reject-recovery-v1", task_key=TASK,
                    prior_auth_sha256=old_hash, auth_sha256=new_hash,
                    prior_reservation_sha256=LOCAL_REJECT["reservation"],
                    prior_progress_sha256=LOCAL_REJECT["progress"], prior_nonce=reserved["nonce"],
                    expected_master=auth["expected_master"], scope_sha256=digest(encoded(scope)),
                    code_pins_sha256=digest(encoded(auth["code_pins"])),
                    cli_version="2.91.0", cli_binary_sha256=LOCAL_REJECT["cli_binary"],
                    local_reject_evidence_sha256=LOCAL_REJECT["cli_evidence"],
                    independent_qa_sha256=LOCAL_REJECT["independent_qa"],
                    dispatch_post_sent=False, canonical_runs_before_recovery=0,
                    actual_usage={k: 0 for k in LIMITS})
    require(isinstance(record, dict) and set(record) == set(expected) | {"expires_at_utc"}
            and all(record[k] == v and type(record[k]) is type(v) for k, v in expected.items())
            and all(type(record["actual_usage"][k]) is int for k in LIMITS),
            "CAMPAIGN_LOCAL_REJECT_PROOF")
    require(isinstance(comment.get("created_at"), str) and isinstance(comment.get("updated_at"), str)
            and isinstance(record.get("expires_at_utc"), str), "CAMPAIGN_LOCAL_REJECT_CLOCK")
    created, updated, now = utc(comment["created_at"]), utc(comment["updated_at"]), utc()
    require(utc(reserved["recorded_utc"]) <= created <= updated <= now
            and updated < utc(record["expires_at_utc"]),
            "CAMPAIGN_LOCAL_REJECT_CLOCK")
    proof_hash = digest(encoded(dict(reference=reference, comment_id=comment["id"],
                                    author_id=author["id"], created_at=created.isoformat(),
                                    updated_at=updated.isoformat(), body_sha256=digest(comment["body"].encode()),
                                    record=record)))
    binding = dict(prior_nonce=reserved["nonce"], prior_auth_sha256=old_hash,
                   prior_reservation_sha256=LOCAL_REJECT["reservation"],
                   prior_progress_sha256=LOCAL_REJECT["progress"],
                   proof_reference=reference, proof_sha256=proof_hash,
                   scope_sha256=expected["scope_sha256"], actual_usage=expected["actual_usage"],
                   prior_expected_master=prior["expected_master"],
                   prior_code_pins_sha256=digest(encoded(prior["code_pins"])),
                   code_pins_sha256=expected["code_pins_sha256"],
                   proof_created_utc=created.isoformat(),
                   proof_expires_utc=utc(record["expires_at_utc"]).isoformat(),
                   expected_master=auth["expected_master"],
                   prior_workflow_run_floor=prior["workflow_run_floor"],
                   workflow_run_floor=auth["workflow_run_floor"])
    return dict(binding=binding, receipt_path=bundle["receipt_path"])


def apply_local_reject_recovery(journal, auth, recovery):
    """Append a typed zero-use closure and immutable receipt, preserving entry1."""
    binding = recovery["binding"]
    if len(journal.entries) == 1:
        require(utc() < utc(binding["proof_expires_utc"]), "CAMPAIGN_LOCAL_REJECT_CLOCK")
        require(not Path(recovery["receipt_path"]).exists(), "CAMPAIGN_LOCAL_REJECT_RECEIPT_PATH")
        require(digest(bounded_bytes(journal.directory / "progress")) == LOCAL_REJECT["progress"],
                "CAMPAIGN_LOCAL_REJECT_PREFIX")
        require(not campaign_runs(auth["workflow_run_floor"]), "CAMPAIGN_LOCAL_REJECT_REMOTE")
        require(gh_json(f"repos/{REPO}/branches/master")["commit"]["sha"] == auth["expected_master"],
                "CAMPAIGN_MASTER_DRIFT")
        for path in PINS:
            deployed = gh_json(f"repos/{REPO}/contents/{path}?ref={auth['expected_master']}")
            require(deployed.get("encoding") == "base64"
                    and digest(base64.b64decode(deployed["content"])) == auth["code_pins"][path]
                    and digest(bounded_bytes(ROOT / path, 262144).replace(b"\r\n", b"\n")) == auth["code_pins"][path],
                    "CAMPAIGN_DEPLOYED_CODE")
        require(not campaign_runs(auth["workflow_run_floor"]), "CAMPAIGN_LOCAL_REJECT_REMOTE")
        journal.append("LOCAL_REJECT_RECOVERED", **binding)
    event = journal.entries[1]
    event_raw = bounded_bytes(journal.directory / "000002.json")
    require(event_raw == encoded(event), "CAMPAIGN_LOCAL_REJECT_EVENT_BYTES")
    receipt = dict(schema="a1-sip-local-reject-recovery-receipt-v1",
                   auth_sha256=event["auth_sha256"], journal_event_sha256=digest(event_raw),
                   recorded_utc=event["recorded_utc"], **binding)
    raw, path = encoded(receipt), Path(recovery["receipt_path"])
    if path.exists():
        require(bounded_bytes(path) == raw, "CAMPAIGN_LOCAL_REJECT_RECEIPT")
    else:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())


def apply_continuation(journal, auth, receipt_path, inputs):
    """Append one bridge to the SAME spent ledger; no old byte or clock reset."""
    binding = journal.continuation
    require(binding is not None and receipt_path is not None, "CAMPAIGN_CONTINUATION_RECEIPT_PATH")
    path, state = Path(receipt_path), journal.directory.resolve()
    resolved = path.resolve()
    require(not path.is_symlink() and resolved != state and state not in resolved.parents
            and resolved not in {Path(p).resolve() for p in inputs}, "CAMPAIGN_CONTINUATION_RECEIPT_PATH")
    if len(journal.entries) == CONTINUATION["events"]:
        require(not path.exists(), "CAMPAIGN_CONTINUATION_RECEIPT_PATH")
        require(digest(bounded_bytes(journal.directory / "progress")) == CONTINUATION["progress"],
                "CAMPAIGN_CONTINUATION_PREFIX")
        # Recheck the canonical5 after all deployed code/pin reads too. A late
        # run or modified OWNER proof cannot be hidden by a valid local prefix.
        require(gh_json(f"repos/{REPO}/branches/master")["commit"]["sha"] == auth["expected_master"],
                "CAMPAIGN_MASTER_DRIFT")
        for name in PINS:
            deployed = gh_json(f"repos/{REPO}/contents/{name}?ref={auth['expected_master']}")
            require(deployed.get("encoding") == "base64"
                    and digest(base64.b64decode(deployed["content"])) == auth["code_pins"][name]
                    and digest(bounded_bytes(ROOT/name, 262144).replace(b"\r\n", b"\n")) == auth["code_pins"][name],
                    "CAMPAIGN_DEPLOYED_CODE")
        observed = history(auth)
        require(observed["continuation"] == binding
                and [r["id"] for r in observed["runs"]] == CONTINUATION["runs"],
                "CAMPAIGN_CONTINUATION_PREFIX")
        fresh_runs = campaign_runs(auth["workflow_run_floor"])
        require([r["id"] for r in fresh_runs] == CONTINUATION["runs"], "CAMPAIGN_CONTINUATION_PREFIX")
        journal.reconcile(fresh_runs)
        journal.append("BUDGET_CONTINUED", **binding)
    event = journal.entries[CONTINUATION["events"]]
    raw_event = bounded_bytes(journal.directory / f"{CONTINUATION['events']+1:06d}.json")
    require(raw_event == encoded(event), "CAMPAIGN_CONTINUATION_EVENT_BYTES")
    receipt = encoded(dict(schema="a1-sip-bounded-continuation-receipt-v1",
                           auth_sha256=journal.auth_hash, journal_event_sha256=digest(raw_event),
                           recorded_utc=event["recorded_utc"], **binding))
    if path.exists():
        require(bounded_bytes(path) == receipt, "CAMPAIGN_CONTINUATION_RECEIPT")
    else:
        with path.open("xb") as handle:
            handle.write(receipt)
            handle.flush()
            os.fsync(handle.fileno())


class WorkJournal:
    """One existing Work directory; append and fsync before dispatch.

    Canonical Actions reconciliation, not the local hash chain alone, detects
    a complete rollback to an older valid prefix.
    """
    def __init__(self, directory, auth_hash, recovery=None, continuation=None):
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
        self.recovery = recovery
        self.continuation = continuation
        try:
            for index, path in enumerate(sorted(self.directory.glob("*.json")), 1):
                require(path.name == f"{index:06d}.json" and not path.is_symlink(),
                        "CAMPAIGN_JOURNAL_CHAIN")
                raw = bounded_bytes(path)
                entry = decode(raw)
                require(entry.get("previous_sha256") == self.parent
                        and entry.get("auth_sha256") == (recovery["binding"]["prior_auth_sha256"]
                            if recovery is not None and index == 1 else
                            CONTINUATION["auth"] if continuation and index <= CONTINUATION["events"] else auth_hash)
                        and entry.get("sequence") == index, "CAMPAIGN_JOURNAL_CHAIN")
                if recovery is not None and index == 1:
                    require(digest(raw) == recovery["binding"]["prior_reservation_sha256"],
                            "CAMPAIGN_LOCAL_REJECT_PREFIX")
                if recovery is not None and index == 2:
                    require(raw == encoded(entry), "CAMPAIGN_LOCAL_REJECT_EVENT_BYTES")
                self.parent = digest(raw)
                self.entries.append(entry)
                if continuation and index == CONTINUATION["events"]:
                    require(self.parent == CONTINUATION["event"] and entry.get("kind") == "SETTLED",
                            "CAMPAIGN_CONTINUATION_PREFIX")
                if continuation and index == CONTINUATION["events"]+1:
                    common = {"sequence", "kind", "auth_sha256", "previous_sha256", "recorded_utc"}
                    require(raw == encoded(entry) and entry.get("kind") == "BUDGET_CONTINUED"
                            and set(entry) == common | set(continuation)
                            and all(entry.get(k) == v for k,v in continuation.items())
                            and utc(continuation["proof_updated_utc"]) <= utc(entry["recorded_utc"])
                                < utc(continuation["expires_at_utc"])
                            and utc(entry["recorded_utc"]) <= utc(), "CAMPAIGN_CONTINUATION_DRIFT")
            if continuation:
                require(recovery is not None and len(self.entries) >= CONTINUATION["events"],
                        "CAMPAIGN_CONTINUATION_PREFIX")
            if recovery is not None:
                require(self.entries, "CAMPAIGN_LOCAL_REJECT_PREFIX")
                if len(self.entries) > 1:
                    event = self.entries[1]
                    require(event.get("kind") == "LOCAL_REJECT_RECOVERED"
                            and set(event) == {"sequence", "kind", "auth_sha256", "previous_sha256", "recorded_utc"}
                                             | set(recovery["binding"])
                            and all(event.get(k) == v for k, v in recovery["binding"].items())
                            and isinstance(event.get("recorded_utc"), str)
                            and utc(recovery["binding"]["proof_created_utc"]) <= utc(event["recorded_utc"])
                                < utc(recovery["binding"]["proof_expires_utc"])
                            and utc(event["recorded_utc"]) <= utc(),
                            "CAMPAIGN_LOCAL_REJECT_DRIFT")
        except BaseException:
            self.close()
            raise

    def append(self, kind, **data):
        entry = dict(sequence=len(self.entries) + 1, kind=kind,
                     auth_sha256=self.auth_hash, previous_sha256=self.parent,
                     recorded_utc=utc().isoformat(), **data)
        if kind == "LOCAL_REJECT_RECOVERED":
            require(self.recovery is not None and data == self.recovery["binding"]
                    and utc(data["proof_created_utc"]) <= utc(entry["recorded_utc"])
                        < utc(data["proof_expires_utc"]), "CAMPAIGN_LOCAL_REJECT_CLOCK")
        if kind == "BUDGET_CONTINUED":
            require(self.continuation is not None and data == self.continuation
                    and len(self.entries) == CONTINUATION["events"] and self.parent == CONTINUATION["event"]
                    and utc(data["proof_updated_utc"]) <= utc(entry["recorded_utc"]) < utc(data["expires_at_utc"]),
                    "CAMPAIGN_CONTINUATION_CLOCK")
        if kind in ("EXTERNAL_COHORT_BOUND", "EXTERNAL_FAMILY_BOUND"):
            require(not self.entries and utc(data["proof_updated_utc"]) <= utc(entry["recorded_utc"])
                    < utc(data["expires_at_utc"]), "EXTERNAL_BINDING_CLOCK")
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
        closed = ({self.recovery["binding"]["prior_nonce"]}
                  if getattr(self, "recovery", None) and len(self.entries) > 1 else set())
        require(not (closed & remote), "CAMPAIGN_LOCAL_REJECT_REMOTE")
        require(reserved - closed == remote, "CAMPAIGN_JOURNAL_REMOTE_CONFLICT")

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
    scope = meter.identity.get("cohort_scope")
    previous = state.get("previous_checkpoint")
    first_external = scope is not None and meter.examined == 0
    require(decode(stored) == state and state.get("cohort_scope") == scope
            and ((previous is None and meter.checkpoint_sha == external_genesis(scope)) if first_external
                 else isinstance(previous, dict) and previous.get("sha256") == meter.checkpoint_sha),
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
                and receipt.get("seed_sha256") == (scope["input_sha256"] if scope else SEED_SHA)
                and receipt.get("cohort_scope") == scope
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
        require(state["last_status"] in (("HELD_BAR_VALUE", "HELD_PROVIDER_ASSET") if scope else ("HELD_BAR_VALUE",))
                and len(objects) == 1,
                "CAMPAIGN_GROUP_STATUS")
        marker = decode(cap._private_object(drive, folder, objects[0]))
        asset_hold = state["last_status"] == "HELD_PROVIDER_ASSET"
        require(marker.get("status") == state["last_status"]
                and marker.get("reason") == ("PROVIDER_ASSET_UNAVAILABLE" if asset_hold else "BAR_VALUE")
                and marker.get("symbols") == state["last_held"]
                and marker.get("source_sha") == os.environ["GITHUB_SHA"]
                and marker.get("seed_sha256") == (scope["input_sha256"] if scope else SEED_SHA)
                and marker.get("cohort_scope") == scope
                and marker.get("start") == "2016-01-04" and marker.get("end") == "2026-10-14"
                and marker.get("original_price_bytes_retained") is False,
                "CAMPAIGN_HELD_MARKER")
        if asset_hold:
            cap.verify_asset_evidence(marker.get("asset_precheck"), state["last_held"])
            require(all(not cap.asset_supported(row) for row in marker["asset_precheck"]),
                    "EXTERNAL_ASSET_EVIDENCE")
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


def account_permission_evidence(reference, auth_hash, bindings):
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
    created = utc(comment.get("created_at"))
    # URL identity alone cannot bind a mutable comment. Record the verified
    # assertions and immutable issue/comment/author identity, never raw rights
    # text in the public meter. A later edit must stop the next worker.
    verified = dict(reference=reference, comment_id=comment["id"],
                    issue_url=comment["issue_url"], author_id=author["id"],
                    created_at_utc=created.isoformat(),
                    body_sha256=digest(comment["body"].encode()), record=record)
    if approval_binding is not None:
        verified["capture_approval"] = approval_binding
    return verified


def verify_account_permission(reference, auth_hash, bindings, *, valid_through):
    verified = account_permission_evidence(reference, auth_hash, bindings)
    now = utc()
    created, expiry = utc(verified["created_at_utc"]), utc(verified["record"]["expires_at_utc"])
    require(isinstance(valid_through, datetime) and valid_through.utcoffset() == timedelta(0),
            "CAMPAIGN_CLOCK")
    require(created <= now < valid_through <= expiry, "CAMPAIGN_ACCOUNT_EXPIRED")
    return digest(encoded(verified))


def worker(args, control, journal):
    from tools import alpaca_sip_private_backfill_v1 as cap
    from tools.twelve_private_capture import OwnerDrive
    require(os.getenv("A1_PRIVATE_RESEARCH_AUTHORIZED") == "true"
            and os.getenv("ALPACA_NONCOMMERCIAL_ACKNOWLEDGED") == "true",
            "USER_AUTHORIZATION_MISSING")
    if isinstance(control, dict) and isinstance(control.get("authorization"), dict) and "external_cohort" in control["authorization"]:
        return external_worker(args, control, journal)
    require(isinstance(control, dict) and {"authorization", "nonce"} <= set(control)
            and set(control) <= {"authorization", "nonce", "recovery_run", "preflight_only",
                                 "account_permission_reference", "continuation_binding"}, "CAMPAIGN_CONTROL_REQUIRED")
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
    if "continuation" in auth:
        require(control.get("continuation_binding") == observed["continuation"], "CAMPAIGN_CONTINUATION_DRIFT")
    else:
        require("continuation_binding" not in control, "CAMPAIGN_CONTINUATION_AUTH")
    preflight = control.get("preflight_only") is True
    require(type(control.get("preflight_only", False)) is bool, "CAMPAIGN_PREFLIGHT")
    permission = auth.get("account_permission_reference") or control.get("account_permission_reference")
    if "continuation" in auth:
        require(permission == auth["continuation"]["proof_reference"] and not preflight,
                "CAMPAIGN_CONTINUATION_PERMISSION")
    require(preflight or (isinstance(permission, str) and 0 < len(permission) <= 512),
            "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
    require(preflight or observed.get("permission_hash") is None or
            (permission is not None and digest(permission.encode()) == observed["permission_hash"]),
            "CAMPAIGN_RIGHTS_DRIFT")
    if observed["examined"] > 16 and (observed["examined"] - 16) % 128 == 0:
        require(forecast_remaining(observed)["fits_current_budgets"], "CAMPAIGN_CALIBRATION_BUDGET")
    require(len(observed["runs"]) <= 40
            and observed["active_seconds"] + 7800 <= active_limit(auth), "CAMPAIGN_ACTIVE_RESERVATION")
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
    if "continuation" in auth:
        identity["continuation_proof_sha256"] = observed["continuation"]["proof_sha256"]
    meter = RuntimeMeter(observed["remaining"], journal, deadline.isoformat(), identity, limits=auth["limits"])
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
    if "external_cohort" in auth:
        return dict(file_id="", sha256=external_genesis(auth["external_cohort"]["scope"]), bytes=0)
    return dict(file_id=auth["initial_checkpoint_file_id"], sha256=INITIAL_SHA, bytes=1375)


def settle_run(journal, auth, run, receipt):
    parent = settled_parent(journal, auth)
    require(receipt["parent_checkpoint_sha256"] == parent["sha256"], "CAMPAIGN_LOCAL_PARENT")
    ref = checkpoint_from_log(run, receipt, parent)
    if "external_cohort" in auth:
        frozen = {k: journal.entries[0][k] for k in ("proof_sha256", "proof_updated_utc", "expires_at_utc")}
        observed = external_history(auth, enforce_expiry=False, allow_stopped=True)
        require(observed["external_proof"] == frozen
                and any(r["id"] == run["id"] and v == receipt for r,v in
                        zip(observed["cohort_runs"], observed["cohort_receipts"]))
                and external_proof(auth) == frozen, "EXTERNAL_PROOF_DRIFT")
        require(campaign_runs(auth["workflow_run_floor"]) == observed["runs"], "EXTERNAL_CANONICAL_DRIFT")
        journal.reconcile(observed["cohort_runs"])
    if getattr(journal, "continuation", None) is not None:
        require(continuation_proof(auth) == journal.continuation
                and receipt.get("continuation_proof_sha256") == journal.continuation["proof_sha256"],
                "CAMPAIGN_CONTINUATION_DRIFT")
    if getattr(journal, "recovery", None) is not None:
        journal.reconcile(campaign_runs(auth["workflow_run_floor"]))
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


def host(auth_path, state_dir, recovery_run=None, permission_reference=None, predispatch_recovery=None,
         continuation_receipt=None, cohort_input=None, budget_state_dir=None, max_batches=None):
    """One finite, serial Work process; never invoked by PR checks."""
    auth = bounded_json(auth_path)
    auth_hash = validate_authorization(auth)
    if "external_cohort" in auth:
        require(permission_reference is None and continuation_receipt is None, "EXTERNAL_CONTROL")
        return external_host(auth, state_dir, cohort_input, budget_state_dir, predispatch_recovery,
                             recovery_run, max_batches)
    require(cohort_input is None and budget_state_dir is None and max_batches is None, "EXTERNAL_CONTROL")
    continuation = continuation_proof(auth)
    prior = auth["continuation"]["prior_authorization"] if continuation else auth
    if continuation is not None:
        reference = auth["continuation"]["proof_reference"]
        require(permission_reference is None or permission_reference == reference,
                "CAMPAIGN_CONTINUATION_PERMISSION")
        permission_reference = reference
    require(not continuation or (predispatch_recovery is not None and continuation_receipt is not None),
            "CAMPAIGN_CONTINUATION_PREFIX")
    require(continuation or continuation_receipt is None, "CAMPAIGN_CONTINUATION_AUTH")
    recovery = local_reject_recovery(predispatch_recovery, prior, state_dir) if predispatch_recovery else None
    journal = WorkJournal(state_dir, auth_hash, recovery=recovery, continuation=continuation)
    last_observed = None
    try:
        if recovery is not None:
            apply_local_reject_recovery(journal, auth, recovery)
        if continuation is not None:
            bundle = bounded_json(predispatch_recovery)
            apply_continuation(journal, auth, continuation_receipt,
                               [auth_path, predispatch_recovery, *(bundle[k] for k in
                                ("prior_authorization", "prior_progress_snapshot", "receipt_path"))])
        while True:
            observed = history(auth, recovery_run=recovery_run, enforce_expiry=False)
            last_observed = observed
            if continuation is not None:
                require(observed["continuation"] == continuation, "CAMPAIGN_CONTINUATION_DRIFT")
            if recovery is not None and recovery_run is not None:
                require(observed["runs"] and observed["runs"][-1]["id"] == recovery_run
                        and observed["receipts"][-1]["status"] == "BLOCKED"
                        and observed["receipts"][-1].get("reason") in ("NETWORK", "HTTP_ERROR"),
                        "CAMPAIGN_RECOVERY")
            journal.reconcile(observed["runs"])
            if journal.entries and journal.entries[-1]["kind"] in ("RESERVED", "RUN_ASSIGNED"):
                nonce = journal.entries[-1]["nonce"]
                pending = [r for r in observed["runs"] if r["display_title"] == "a1-sip " + nonce]
                require(len(pending) == 1 and pending[0]["status"] == "completed", "CAMPAIGN_ACTIVE_RESERVATION")
                receipt = (receipt_for_run(pending[0], auth_hash, auth["expected_master"], auth["limits"]) if continuation
                           else receipt_for_run(pending[0], auth_hash, auth["expected_master"]))
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
            require(len(observed["runs"]) < 40 and observed["active_seconds"] + 7800 <= active_limit(auth),
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
            require(not journal.entries or journal.entries[-1]["kind"] == "SETTLED"
                    or (recovery is not None and journal.entries[-1]["kind"] == "LOCAL_REJECT_RECOVERED")
                    or (continuation is not None and journal.entries[-1]["kind"] == "BUDGET_CONTINUED"),
                    "CAMPAIGN_ACTIVE_RESERVATION")
            if continuation is not None:
                require(continuation_proof(auth) == continuation, "CAMPAIGN_CONTINUATION_DRIFT")
            if recovery is not None:
                journal.reconcile(campaign_runs(auth["workflow_run_floor"]))
            nonce = PREFIX + os.urandom(12).hex()
            bindings_missing = (observed.get("bindings") is None and
                                (auth.get("owner_permission_id") is None or auth.get("credential_binding") is None))
            preflight = bool(bindings_missing)
            permission = auth.get("account_permission_reference") or permission_reference
            if continuation is not None:
                require(permission == auth["continuation"]["proof_reference"] and not preflight,
                        "CAMPAIGN_CONTINUATION_PERMISSION")
            require(preflight or (isinstance(permission, str) and 0 < len(permission) <= 512),
                    "CAMPAIGN_ACCOUNT_PROOF_REQUIRED")
            require(observed["first"] is None or utc() < observed["first"] + timedelta(hours=48),
                    "CAMPAIGN_EXPIRED")
            control = dict(authorization=auth, nonce=nonce, recovery_run=recovery_run,
                           preflight_only=preflight, account_permission_reference=permission)
            if continuation is not None:
                control["continuation_binding"] = continuation
            control_raw = encoded(control).decode()
            require(len(control_raw) <= 16384, "CAMPAIGN_CONTROL_SIZE")
            journal.append("RESERVED", nonce=nonce, remaining=observed["remaining"],
                           active_seconds_remaining=active_limit(auth) - observed["active_seconds"],
                           parent_checkpoint_sha256=observed["parent_sha"])
            inputs = dict(private_root_folder_id=auth["private_root_folder_id"],
                          private_data_folder_id=auth["private_data_folder_id"],
                          private_research_authorized="true", noncommercial_terms_acknowledged="true",
                          end_date=auth["end"], max_new_symbols=str(next_batch(observed["examined"])),
                          resume_file_id=current_ref["file_id"], resume_sha256=current_ref["sha256"],
                          campaign_control=control_raw, campaign_nonce=nonce)
            result = subprocess.run(["gh", "workflow", "run", WORKFLOW, "--repo", REPO,
                                     "--ref", "master", "--json"], input=json.dumps(inputs).encode(),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
            require(result.returncode == 0, "CAMPAIGN_DISPATCH_UNCERTAIN")
            run = None
            for _ in range(30):
                polled = campaign_runs(auth["workflow_run_floor"]) if recovery is not None else campaign_runs()
                if recovery is not None:
                    require(all(r["display_title"] != "a1-sip " + recovery["binding"]["prior_nonce"]
                                for r in polled), "CAMPAIGN_LOCAL_REJECT_REMOTE")
                matches = [r for r in polled if r["display_title"] == "a1-sip " + nonce]
                require(len(matches) <= 1, "CAMPAIGN_NONCE_REPLAY")
                if matches:
                    if recovery is not None:
                        journal.reconcile(polled)
                    run = matches[0]
                    break
                time.sleep(2)
            require(run is not None, "CAMPAIGN_DISPATCH_UNCERTAIN")
            journal.append("RUN_ASSIGNED", nonce=nonce, run_id=run["id"])
            # The local reservation survives interruption/unknown remote status.
            result = subprocess.run(["gh", "run", "watch", str(run["id"]), "--repo", REPO,
                                     "--exit-status", "--interval", "30"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=9000)
            if recovery is not None:
                journal.reconcile(campaign_runs(auth["workflow_run_floor"]))
            fresh = gh_json(f"repos/{REPO}/actions/runs/{run['id']}")
            receipt = (receipt_for_run(fresh, auth_hash, auth["expected_master"], auth["limits"]) if continuation
                       else receipt_for_run(fresh, auth_hash, auth["expected_master"]))
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
            closed = ({recovery["binding"]["prior_nonce"]}
                      if recovery is not None and len(journal.entries) > 1 else set())
            pending = [e for e in journal.entries if e["kind"] == "RESERVED" and e["nonce"] not in closed]
            unsettled = bool(journal.entries and journal.entries[-1]["kind"] in ("RESERVED", "RUN_ASSIGNED"))
            summary["unsettled_reservation"] = pending[-1]["remaining"] if unsettled and pending else None
            try:
                atomic_json(journal.directory / "progress", summary)
            except OSError:
                pass  # The append-only reservation and canonical evidence remain.
        raise
    finally:
        journal.close()


def external_genesis(scope):
    from tools.alpaca_sip_private_backfill_v1 import external_scope
    return digest(encoded(dict(schema="a1-external-logical-genesis-v1", scope=external_scope(scope),
                               start="2016-01-04", end="2026-10-14", feed="sip", adjustments=["raw", "split"])))


def validate_external_authorization(auth):
    from tools import alpaca_sip_private_backfill_v1 as cap
    ex = auth["external_cohort"]
    require(isinstance(ex, dict) and set(ex) == {"scope", "input_csv", "intake_manifest_sha256",
            "receipt_dedupe_sha256", "prior_authorization", "prior_epochs", "proof_reference"}, "EXTERNAL_AUTHORIZATION")
    scope = cap.external_scope(ex["scope"])
    require(isinstance(ex["input_csv"], str), "EXTERNAL_COHORT_SCHEMA")
    raw = ex["input_csv"].encode("utf-8")
    names = cap.external_cohort(raw)
    require(digest(raw) == scope["input_sha256"], "EXTERNAL_COHORT_HASH")
    for key in ("intake_manifest_sha256", "receipt_dedupe_sha256"):
        require(isinstance(ex[key], str) and re.fullmatch(r"[0-9a-f]{64}", ex[key]), "EXTERNAL_INPUT_PROOF")
    prior = ex["prior_authorization"]
    require(isinstance(prior, dict) and set(prior) == AUTH_FIELDS
            and validate_authorization(prior) == CONTINUATION["auth"], "EXTERNAL_BUDGET_ORIGIN")
    fixed = AUTH_FIELDS - {"schema", "limits", "expected_master", "code_pins", "account_permission_reference",
                           "owner_permission_id", "credential_binding"}
    require(all(auth[k] == prior[k] for k in fixed)
            and auth["expected_master"] != prior["expected_master"]
            and (auth["owner_permission_id"] is None or
                 digest(auth["owner_permission_id"].encode()) == CONTINUATION["bindings"]["owner_sha256"])
            and auth["credential_binding"] == CONTINUATION["bindings"]["credential_binding"]
            and prior["owner_permission_id"] in (None, auth["owner_permission_id"])
            and prior["credential_binding"] in (None, auth["credential_binding"]), "EXTERNAL_BUDGET_ORIGIN")
    require(isinstance(ex["proof_reference"], str) and re.fullmatch(
        r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+", ex["proof_reference"])
        and auth["account_permission_reference"] == ex["proof_reference"], "EXTERNAL_PROOF_REFERENCE")
    # Two bounded epochs: the explicit discovery input, then the deduplicated
    # market-cap input. Refuse recursive cycles/extra epochs before recursing.
    epochs = ex["prior_epochs"]
    require(isinstance(epochs, list) and len(epochs) <= 1, "EXTERNAL_EPOCH_LIMIT")
    for previous in epochs:
        require(isinstance(previous, dict) and isinstance(previous.get("external_cohort"), dict)
                and previous["external_cohort"].get("prior_epochs") == [], "EXTERNAL_EPOCH_LIMIT")
        validate_authorization(previous)
        old = previous["external_cohort"]
        require(old["prior_authorization"] == prior and old["scope"]["namespace"] != scope["namespace"]
                and all(auth[k] == previous[k] for k in fixed)
                and set(names).isdisjoint(cap.external_cohort(old["input_csv"].encode())), "EXTERNAL_RECOLLECTION")
    # These144 names have already been examined in the original immutable chain.
    # Existing no-data observations remain retained rather than being retried.
    require(digest(cap.SEED.read_bytes().replace(b"\r\n", b"\n")) == SEED_SHA, "CAMPAIGN_SEED")
    require(set(names).isdisjoint(cap.cohort(cap.SEED.read_bytes())[:CONTINUATION["examined"]]),
            "EXTERNAL_RECOLLECTION")
    require(len(encoded(auth)) <= 15000, "CAMPAIGN_CONTROL_SIZE")


def external_proof_record(auth):
    ex = auth["external_cohort"]
    return dict(schema="a1-sip-external-cohort-consent-v1", budget_task_key=TASK,
                scope=ex["scope"], auth_sha256=validate_authorization(auth),
                prior_auth_sha256=CONTINUATION["auth"],
                prior_epoch_auth_sha256=[validate_authorization(a) for a in ex["prior_epochs"]],
                intake_manifest_sha256=ex["intake_manifest_sha256"], receipt_dedupe_sha256=ex["receipt_dedupe_sha256"],
                initial_checkpoint_sha256=external_genesis(ex["scope"]),
                original_checkpoint_sha256=CONTINUATION["checkpoint"],
                original_journal_event_sha256=CONTINUATION["event"], original_usage=CONTINUATION["used"],
                first_canonical_utc=CONTINUATION["first"],
                expires_at_utc=(utc(CONTINUATION["first"])+timedelta(hours=48)).isoformat(),
                limits=CONTINUED_LIMITS, active_seconds_limit=43200, dispatch_limit=40,
                expected_master=auth["expected_master"], code_pins_sha256=digest(encoded(auth["code_pins"])),
                bindings=CONTINUATION["bindings"], personal_historical_capture_requested=True,
                private_noncommercial=True, supplier_rights_verified=False, account_rotation=False,
                original_seed_unchanged=True, budget_reset=False)


def external_proof(auth):
    """Execution consent for THIS input, explicitly no fabricated supplier rights."""
    expected = external_proof_record(auth)
    reference = auth["external_cohort"]["proof_reference"]
    comment_id = int(reference.rsplit("-", 1)[1])
    comment = gh_json(f"repos/{REPO}/issues/comments/{comment_id}")
    author = comment.get("user", {})
    require(comment.get("id") == comment_id and type(comment.get("id")) is int
            and comment.get("issue_url") == f"https://api.github.com/repos/{REPO}/issues/448"
            and comment.get("author_association") == "OWNER" and author.get("type") == "User"
            and type(author.get("id")) is int and author["id"] > 0
            and isinstance(comment.get("body"), str), "EXTERNAL_ATTESTOR")
    tag = "A1_SIP_EXTERNAL_COHORT_CONSENT "
    lines = [line[len(tag):] for line in comment["body"].splitlines() if line.startswith(tag)]
    require(len(lines) == 1 and len(lines[0]) <= 4096, "EXTERNAL_PROOF")
    record = decode(lines[0])
    require(isinstance(record, dict) and encoded(record) == encoded(expected), "EXTERNAL_PROOF")
    created, updated = utc(comment.get("created_at")), utc(comment.get("updated_at"))
    require(utc(CONTINUATION["first"]) <= created <= updated <= utc()
            and updated < utc(expected["expires_at_utc"]), "EXTERNAL_PROOF_CLOCK")
    proof = dict(reference=reference, comment_id=comment_id, author_id=author["id"],
                 created_at=created.isoformat(), updated_at=updated.isoformat(),
                 body_sha256=digest(comment["body"].encode()), record=record)
    return dict(proof_sha256=digest(encoded(proof)), proof_updated_utc=updated.isoformat(),
                expires_at_utc=expected["expires_at_utc"])


def external_batch(examined, count):
    integer(examined, count)
    require(examined < count <= 500, "EXTERNAL_COHORT_COMPLETE")
    return min(32, count-examined, 128-(examined % 128))


def external_history(auth, current_run=None, nonce=None, recovery_run=None, enforce_expiry=True, *, allow_stopped=False):
    """All family costs, per-cohort progress, same first clock/dispatch budget."""
    from tools import alpaca_sip_private_backfill_v1 as cap
    auth_hash = validate_authorization(auth)
    ex = auth["external_cohort"]
    require(recovery_run is None, "EXTERNAL_RECOVERY_NOT_AUTHORIZED")
    epochs = ex["prior_epochs"] + [auth]
    hashes = [validate_authorization(a) for a in epochs]
    require(len(set(hashes)) == len(hashes), "EXTERNAL_EPOCH_LIMIT")
    proofs = [external_proof(a) for a in epochs]
    runs = campaign_runs(auth["workflow_run_floor"])
    require([r["id"] for r in runs[:5]] == CONTINUATION["runs"], "EXTERNAL_BUDGET_PREFIX")
    if current_run is not None:
        require(len(runs) > 5 and runs[-1]["id"] == current_run
                and runs[-1]["display_title"] == "a1-sip " + nonce and runs[-1].get("run_attempt") == 1
                and runs[-1].get("head_sha") == auth["expected_master"], "CAMPAIGN_SINGLE_USE")
    previous = runs[:-1] if current_run is not None else runs
    used, active = {k: 0 for k in LIMITS}, 0
    local = {h: dict(parent=external_genesis(a["external_cohort"]["scope"]), examined=0,
                    receipts=[], runs=[], durations=[]) for h,a in zip(hashes,epochs)}
    old_parent, old_examined = INITIAL_SHA, 16
    receipts, durations, epoch_index = [], [], 0
    for index, run in enumerate(previous):
        if index < 5:
            value = receipt_for_run(run, CONTINUATION["auth"], CONTINUATION["master"])
            require(digest(encoded(value)) == CONTINUATION["receipts"][index]
                    and value["parent_checkpoint_sha256"] == old_parent
                    and value["examined_before"] == old_examined, "EXTERNAL_BUDGET_PREFIX")
            old_parent, old_examined = value["checkpoint_sha256"], value["examined_after"]
            caps = LIMITS
        else:
            require(run.get("head_sha") in {a["expected_master"] for a in epochs}, "CAMPAIGN_SOURCE")
            value = receipt_for_run(run, tuple(hashes), run["head_sha"], CONTINUED_LIMITS)
            h = value["auth_sha256"]
            require(h in hashes, "EXTERNAL_RECEIPT_BINDING")
            position = hashes.index(h)
            require(position >= epoch_index, "EXTERNAL_EPOCH_ORDER")
            if position > epoch_index:
                require(all(local[hashes[j]]["examined"] == len(cap.external_cohort(
                    epochs[j]["external_cohort"]["input_csv"].encode())) for j in range(position)),
                    "EXTERNAL_EPOCH_INCOMPLETE")
            epoch_index = position
            a, proof, state = epochs[position], proofs[position], local[h]
            scope = a["external_cohort"]["scope"]
            require(value.get("source_sha") == a["expected_master"] and value.get("cohort_scope") == scope
                    and value.get("recovery_run") is None
                    and value.get("external_proof_sha256") == proof["proof_sha256"]
                    and value.get("preflight_only") is False
                    and value.get("bindings") == CONTINUATION["bindings"]
                    and value.get("account_permission_reference_sha256") == digest(a["external_cohort"]["proof_reference"].encode())
                    and value.get("account_permission_record_sha256") == proof["proof_sha256"]
                    and utc(run["created_at"]) >= utc(proof["proof_updated_utc"]), "EXTERNAL_RECEIPT_BINDING")
            count = len(cap.external_cohort(a["external_cohort"]["input_csv"].encode()))
            require(value["examined_before"] == state["examined"]
                    and value["parent_checkpoint_sha256"] == state["parent"]
                    and state["examined"] <= value["examined_after"] <= state["examined"] + external_batch(state["examined"], count)
                    and isinstance(value.get("checkpoint_sha256"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", value["checkpoint_sha256"]), "EXTERNAL_CHECKPOINT_CHAIN")
            require((value["examined_after"] > state["examined"]) == (value["checkpoint_sha256"] != state["parent"]),
                    "EXTERNAL_CHECKPOINT_CHAIN")
            state.update(parent=value["checkpoint_sha256"], examined=value["examined_after"])
            state["runs"].append(run); state["receipts"].append(value)
            caps = CONTINUED_LIMITS
        for k in LIMITS:
            require(value["allowance"][k] == caps[k]-used[k], "CAMPAIGN_ALLOWANCE_RESET")
            used[k] += value["usage"][k]
            require(used[k] <= caps[k], "CAMPAIGN_LEDGER_BUDGET")
        seconds = job_seconds(run)
        active += seconds
        if index < 5 and index == 4:
            require(used == CONTINUATION["used"] and active == CONTINUATION["active_seconds"]
                    and old_parent == CONTINUATION["checkpoint"] and old_examined == CONTINUATION["examined"],
                    "EXTERNAL_BUDGET_PREFIX")
        if index >= 5:
            local[value["auth_sha256"]]["durations"].append(seconds)
        receipts.append(value); durations.append(seconds)
        failed = value["status"] != "COMPLETE" or run.get("conclusion") != "success"
        if failed:
            if allow_stopped and current_run is None and run == previous[-1] and value["status"] == "BLOCKED":
                # Import/account a closed failure only. Host separately refuses
                # another dispatch; this flag is never accepted by workers.
                require(isinstance(value.get("reason"), str) and re.fullmatch(r"[A-Z_]{1,80}", value["reason"]),
                        "CAMPAIGN_REASON")
                continue
            raise Refused("CAMPAIGN_EXTERNAL_FAILURE_STOP")
    require(active <= active_limit(auth) and utc(runs[0]["created_at"]) == utc(CONTINUATION["first"]),
            "CAMPAIGN_ACTIVE_TIME")
    first = utc(CONTINUATION["first"])
    if enforce_expiry:
        require(utc() < first+timedelta(hours=48), "CAMPAIGN_EXPIRED")
    state = local[auth_hash]
    if len(epochs) > 1:
        require(local[hashes[0]]["examined"] == len(cap.external_cohort(epochs[0]["external_cohort"]["input_csv"].encode())),
                "EXTERNAL_EPOCH_INCOMPLETE")
    return dict(runs=runs, receipts=receipts, used=used, active_seconds=active, first=first,
                durations=durations, bindings=CONTINUATION["bindings"], external_proof=proofs[-1],
                parent_sha=state["parent"], examined=state["examined"], cohort_runs=state["runs"],
                cohort_receipts=state["receipts"], cohort_durations=state["durations"],
                remaining={k: CONTINUED_LIMITS[k]-used[k] for k in LIMITS})


def external_worker(args, control, journal):
    from tools import alpaca_sip_private_backfill_v1 as cap
    from tools.twelve_private_capture import OwnerDrive
    require(set(control) == {"authorization", "nonce", "recovery_run", "preflight_only", "external_binding"}
            and control["preflight_only"] is False, "EXTERNAL_CONTROL")
    auth = control["authorization"]
    h = validate_authorization(auth)
    verify_worker_source(auth)
    nonce, recovered = control["nonce"], control["recovery_run"]
    require(isinstance(nonce, str) and re.fullmatch(PREFIX+r"[0-9a-f]{24}", nonce)
            and nonce == os.getenv("INPUT_CAMPAIGN_NONCE")
            and recovered is None, "EXTERNAL_RECOVERY_NOT_AUTHORIZED")
    run_id = int(os.environ["GITHUB_RUN_ID"])
    observed = external_history(auth, run_id, nonce, recovered)
    proof, ex = observed["external_proof"], auth["external_cohort"]
    scope = ex["scope"]
    names = cap.external_cohort(ex["input_csv"].encode())
    n = observed["examined"]
    require(control["external_binding"] == proof and len(observed["runs"]) <= 40
            and observed["active_seconds"] + 7800 <= active_limit(auth), "EXTERNAL_PROOF_DRIFT")
    require(args.private_root_folder_id == auth["private_root_folder_id"]
            and args.private_data_folder_id == auth["private_data_folder_id"]
            and args.start == auth["start"] and args.end == auth["end"]
            and args.max_new_symbols == external_batch(n, len(names))
            and (args.resume_sha256 == observed["parent_sha"] if n else
                 args.resume_file_id == args.resume_sha256 == ""), "EXTERNAL_PARENT")
    key, secret = os.getenv("ALPACA_API_KEY", "").strip(), os.getenv("ALPACA_API_SECRET", "").strip()
    require(key and secret and digest((key+"\0"+secret).encode()) == auth["credential_binding"],
            "CAMPAIGN_CREDENTIAL_BINDING")
    deadline = worker_deadline(run_id, observed["first"])
    require(deadline <= utc(proof["expires_at_utc"]), "CAMPAIGN_ACCOUNT_EXPIRED")
    require(external_proof(auth) == proof, "EXTERNAL_PROOF_DRIFT")
    require([(r["id"], r.get("run_attempt"), r.get("head_sha"), r.get("display_title"))
             for r in campaign_runs(auth["workflow_run_floor"])] ==
            [(r["id"], r.get("run_attempt"), r.get("head_sha"), r.get("display_title")) for r in observed["runs"]],
            "EXTERNAL_CANONICAL_DRIFT")
    identity = dict(task_key=TASK, auth_sha256=h, source_sha=auth["expected_master"], nonce=nonce,
                    run_id=run_id, run_attempt=1, recovery_run=recovered, preflight_only=False,
                    cohort_scope=scope, external_proof_sha256=proof["proof_sha256"],
                    bindings=CONTINUATION["bindings"], parent_checkpoint_sha256=observed["parent_sha"],
                    examined_before=n, account_permission_reference_sha256=digest(ex["proof_reference"].encode()),
                    account_permission_record_sha256=proof["proof_sha256"])
    meter = RuntimeMeter(observed["remaining"], journal, deadline.isoformat(), identity, limits=auth["limits"],
                         asset_symbols=names[n:n+args.max_new_symbols])
    def factory(root, temp):
        drive = OwnerDrive(root, temp, meter=meter)
        require((auth["owner_permission_id"] is None or drive.owner == auth["owner_permission_id"])
                and digest(drive.owner.encode()) == CONTINUATION["bindings"]["owner_sha256"]
                and drive.free >= 2*1024**3,
                "CAMPAIGN_OWNER_OR_SPACE")
        meter.identity["free_bytes_at_start"] = drive.free
        meter.save()
        return drive
    try:
        with meter.process_deadline():
            result = cap._collect(args, drive_factory=factory, get=meter.perform,
                on_group=lambda drive,state,ref: verify_new_group(drive, args.private_data_folder_id, state, ref, meter),
                expected_examined=n, external=dict(input_csv=ex["input_csv"], scope=scope))
        require(meter.examined == n+args.max_new_symbols and meter.checkpoint_sha == result["checkpoint"]["sha256"],
                "CAMPAIGN_BATCH_CLOSURE")
        meter.finish("COMPLETE")
        return result
    except Refused as exc:
        meter.finish("BLOCKED", str(exc)); raise
    except Exception:
        meter.finish("BLOCKED", "CAMPAIGN_INTERNAL")
        raise Refused("CAMPAIGN_INTERNAL") from None


def external_progress(auth, observed, status):
    from tools.alpaca_sip_private_backfill_v1 import external_cohort
    receipts = observed["cohort_receipts"]
    return dict(task_key=auth["external_cohort"]["scope"]["task_key"], budget_task_key=TASK, status=status,
                cohort_scope=auth["external_cohort"]["scope"], examined=observed["examined"],
                cohort_count=len(external_cohort(auth["external_cohort"]["input_csv"].encode())),
                states={k: sum(r["new_states"][k] for r in receipts) for k in
                        ("VALID_COLLECTED", "VERIFIED_NO_DATA", "QUARANTINED")},
                rows_verified=sum(r["rows_verified"] for r in receipts), charged_usage=observed["used"],
                remaining=observed["remaining"], active_seconds=observed["active_seconds"],
                workflow_dispatches=len(observed["runs"]), checkpoint_sha256=observed["parent_sha"],
                first_canonical_utc=observed["first"].isoformat(), source_admission=False,
                pit_verified=False, economic_authority=False)


def verify_external_budget_journal(journal, auth, recovery):
    """Read only: a missing old receipt is a refusal, never regenerated here."""
    require(len(journal.entries) == 17 and journal.parent == CONTINUATION["event"]
            and digest(bounded_bytes(journal.directory/"progress")) == CONTINUATION["progress"],
            "EXTERNAL_BUDGET_PREFIX")
    event = journal.entries[1]
    raw = bounded_bytes(journal.directory/"000002.json")
    require(raw == encoded(event), "CAMPAIGN_LOCAL_REJECT_EVENT_BYTES")
    receipt = encoded(dict(schema="a1-sip-local-reject-recovery-receipt-v1", auth_sha256=event["auth_sha256"],
        journal_event_sha256=digest(raw), recorded_utc=event["recorded_utc"], **recovery["binding"]))
    require(Path(recovery["receipt_path"]).is_file() and bounded_bytes(recovery["receipt_path"]) == receipt,
            "CAMPAIGN_LOCAL_REJECT_RECEIPT")


def external_deployed(auth):
    require(gh_json(f"repos/{REPO}/branches/master")["commit"]["sha"] == auth["expected_master"],
            "CAMPAIGN_MASTER_DRIFT")
    for path in PINS:
        value = gh_json(f"repos/{REPO}/contents/{path}?ref={auth['expected_master']}")
        require(value.get("encoding") == "base64" and
                digest(base64.b64decode(value["content"])) == auth["code_pins"][path]
                and digest(bounded_bytes(ROOT/path, 262144).replace(b"\r\n", b"\n")) == auth["code_pins"][path],
                "CAMPAIGN_DEPLOYED_CODE")


def external_forecast(auth, observed):
    # Includes assets, full-prefix readback, failed attempts and all global
    # usage. A linear average would hide the growing restore/check cost.
    from tools.alpaca_sip_private_backfill_v1 import external_cohort
    count = len(external_cohort(auth["external_cohort"]["input_csv"].encode()))
    if not observed["examined"] or observed["examined"] % 128:
        return None
    proxy = dict(observed, examined=observed["examined"]+16,
                 receipts=observed["cohort_receipts"], durations=observed["cohort_durations"])
    # The existing predictor assumes1009 names; project its conservative
    # envelope to the smaller cohort without changing hard meter limits.
    forecast = forecast_remaining(proxy)
    scale = (count-observed["examined"])/(1009-proxy["examined"])
    projected = {k: math.ceil(v*scale) for k,v in forecast["estimated_remaining"].items()}
    seconds = math.ceil(forecast["estimated_remaining_active_seconds"]*scale)
    jobs = math.ceil((count-observed["examined"])/32)
    return dict(projected=projected, active_seconds=seconds, dispatches=jobs, estimate_only=True,
                fits=all(projected[k] <= observed["remaining"][k] for k in LIMITS)
                     and seconds <= active_limit(auth)-observed["active_seconds"]
                     and len(observed["runs"])+jobs <= 40)


def external_family_registry(budget_path, auth, state_path):
    """One deterministic shared reservation authority, outside the frozen17."""
    first_auth = (auth["external_cohort"]["prior_epochs"] or [auth])[0]
    first_hash = validate_authorization(first_auth)
    proof = external_proof(first_auth)
    genesis = digest(encoded(dict(schema="a1-external-budget-genesis-v1", task_key=TASK,
        prior_auth_sha256=CONTINUATION["auth"], prior_event_sha256=CONTINUATION["event"],
        first=CONTINUATION["first"], limits=CONTINUED_LIMITS, active_seconds_limit=43200, dispatch_limit=40)))
    directory = budget_path.parent / ("external-budget-"+CONTINUATION["auth"][:16])
    existed = directory.exists()
    registry = WorkJournal(directory, genesis)
    try:
        binding = dict(genesis_sha256=genesis, capture_auth_sha256=first_hash,
                       scope=first_auth["external_cohort"]["scope"], **proof)
        if registry.entries:
            first = registry.entries[0]
            require(first.get("kind") == "EXTERNAL_FAMILY_BOUND"
                    and {k:first.get(k) for k in binding} == binding
                    and utc(proof["proof_updated_utc"]) <= utc(first.get("recorded_utc"))
                        < utc(proof["expires_at_utc"]), "EXTERNAL_FAMILY_DRIFT")
        else:
            # Absence of local registration is not evidence of zero POSTs.
            require(not existed and not auth["external_cohort"]["prior_epochs"]
                    and not list(state_path.glob("*.json"))
                    and [r["id"] for r in campaign_runs(auth["workflow_run_floor"])] == CONTINUATION["runs"],
                    "EXTERNAL_FAMILY_MISSING")
            registry.append("EXTERNAL_FAMILY_BOUND", **binding)
        return registry
    except BaseException:
        registry.close()
        raise


def reconcile_external_family(registry, journal, auth, observed):
    """No later namespace can ignore an unobserved or partially logged POST."""
    h, scope = validate_authorization(auth), auth["external_cohort"]["scope"]
    suffix = list(zip(observed["runs"][5:], observed["receipts"][5:]))
    remote = {v["nonce"]:(r,v) for r,v in suffix}
    registry.reconcile(observed["runs"][5:])
    pending, settled, reserved = None, {}, {}
    for entry in registry.entries[1:]:
        kind, nonce = entry.get("kind"), entry.get("nonce")
        require(kind in ("RESERVED", "RUN_ASSIGNED", "SETTLED") and nonce in remote, "EXTERNAL_FAMILY_CONFLICT")
        run, value = remote[nonce]
        require(entry.get("capture_auth_sha256") == value["auth_sha256"]
                and entry.get("scope") == value.get("cohort_scope"), "EXTERNAL_FAMILY_CONFLICT")
        if kind == "RESERVED":
            require(pending is None and nonce not in reserved
                    and entry.get("remaining") == value["allowance"]
                    and entry.get("parent_checkpoint_sha256") == value["parent_checkpoint_sha256"],
                    "EXTERNAL_FAMILY_RESERVATION")
            reserved[nonce] = entry
            pending = nonce
        else:
            require(pending == nonce and entry.get("run_id") == run["id"], "EXTERNAL_FAMILY_RESERVATION")
            if kind == "SETTLED":
                require(entry.get("receipt_sha256") == digest(encoded(value))
                        and entry.get("usage") == value["usage"]
                        and entry.get("checkpoint_sha256") == value["checkpoint_sha256"], "EXTERNAL_FAMILY_SETTLEMENT")
                settled[nonce] = entry
                pending = None
    own_reserved = {e["nonce"] for e in journal.entries if e["kind"] == "RESERVED"}
    own_global = {nonce for nonce,e in reserved.items() if e["capture_auth_sha256"] == h}
    require(own_reserved == own_global, "EXTERNAL_FAMILY_ORPHAN")
    own_settled = {e["nonce"]:e for e in journal.entries if e["kind"] == "SETTLED"}
    for nonce in own_global:
        run, value = remote[nonce]
        if nonce in settled:
            require(nonce in own_settled, "EXTERNAL_FAMILY_ORPHAN")
        if nonce in own_settled:
            entry = own_settled[nonce]
            require(entry.get("run_id") == run["id"] and entry.get("receipt") == value
                    and entry.get("receipt_sha256") == digest(encoded(value))
                    and entry.get("usage") == value["usage"]
                    and entry.get("checkpoint", {}).get("sha256") == value["checkpoint_sha256"],
                    "EXTERNAL_FAMILY_SETTLEMENT")
            if nonce not in settled:
                require(pending == nonce and registry.entries[-1]["nonce"] == nonce,
                        "EXTERNAL_FAMILY_ORPHAN")
                # Cohort SETTLED first; a crash here resumes only with this
                # exact canonical receipt, never a refund or another nonce.
                registry.append("SETTLED", nonce=nonce, run_id=run["id"], capture_auth_sha256=h, scope=scope,
                    receipt_sha256=digest(encoded(value)), usage=value["usage"], checkpoint_sha256=value["checkpoint_sha256"])
                pending = None
    require(pending is None or reserved[pending]["capture_auth_sha256"] == h, "EXTERNAL_FAMILY_PENDING")
    return pending


def external_host(auth, state_dir, cohort_input, budget_state_dir, predispatch_recovery, recovery_run, max_batches):
    from tools.alpaca_sip_private_backfill_v1 import external_cohort
    ex, h = auth["external_cohort"], validate_authorization(auth)
    require(recovery_run is None, "EXTERNAL_RECOVERY_NOT_AUTHORIZED")
    require(cohort_input is not None and budget_state_dir is not None and predispatch_recovery is not None,
            "EXTERNAL_HOST_INPUTS")
    require(max_batches is None or type(max_batches) is int and 1 <= max_batches <= 16, "EXTERNAL_BATCH_LIMIT")
    require(bounded_bytes(cohort_input, 8192) == ex["input_csv"].encode(), "EXTERNAL_COHORT_HASH")
    budget_path, state_path = Path(budget_state_dir).resolve(), Path(state_dir).resolve()
    require(budget_path.is_dir() and state_path != budget_path and budget_path not in state_path.parents
            and state_path not in budget_path.parents
            and state_path == budget_path.parent / ("external-cohort-"+ex["scope"]["namespace"]),
            "EXTERNAL_NAMESPACE")
    base = ex["prior_authorization"]
    recovery = local_reject_recovery(predispatch_recovery, base, budget_path)
    global_journal = WorkJournal(budget_path, CONTINUATION["auth"], recovery=recovery)
    journal = family = None
    last_observed = None
    try:
        verify_external_budget_journal(global_journal, auth, recovery)
        family = external_family_registry(budget_path, auth, state_path)
        journal = WorkJournal(state_path, h)
        frozen = external_proof(auth)
        binding = dict(scope=ex["scope"], genesis_sha256=external_genesis(ex["scope"]), **frozen)
        if journal.entries:
            first = journal.entries[0]
            require(first.get("kind") == "EXTERNAL_COHORT_BOUND"
                    and {k: first.get(k) for k in binding} == binding
                    and utc(frozen["proof_updated_utc"]) <= utc(first.get("recorded_utc"))
                        < utc(frozen["expires_at_utc"]), "EXTERNAL_PROOF_DRIFT")
        else:
            # No provider/Drive I/O or dispatch; binding is this new namespace only.
            journal.append("EXTERNAL_COHORT_BOUND", **binding)
        completed = 0
        while True:
            observed = external_history(auth, recovery_run=recovery_run, enforce_expiry=False, allow_stopped=True)
            last_observed = observed
            require(observed["external_proof"] == frozen, "EXTERNAL_PROOF_DRIFT")
            global_journal.reconcile(observed["runs"][:5])
            journal.reconcile(observed["cohort_runs"])
            reconcile_external_family(family, journal, auth, observed)
            if journal.entries[-1]["kind"] in ("RESERVED", "RUN_ASSIGNED"):
                matches = [(r,v) for r,v in zip(observed["cohort_runs"], observed["cohort_receipts"])
                           if v["nonce"] == journal.entries[-1]["nonce"]]
                require(len(matches) == 1, "CAMPAIGN_ACTIVE_RESERVATION")
                run, value = matches[0]
                require(external_proof(auth) == frozen, "EXTERNAL_PROOF_DRIFT")
                settle_run(journal, auth, run, value)
                reconcile_external_family(family, journal, auth, observed)
            atomic_json(journal.directory/"progress", external_progress(auth, observed, "VERIFIED"))
            latest = observed["cohort_receipts"][-1] if observed["cohort_receipts"] else None
            if latest is not None and latest["status"] == "BLOCKED":
                atomic_json(journal.directory/"progress", external_progress(auth, observed, "BLOCKED"))
                raise Refused("CAMPAIGN_WORKER_BLOCKED")
            count = len(external_cohort(ex["input_csv"].encode()))
            if observed["examined"] == count or max_batches is not None and completed >= max_batches:
                return external_progress(auth, observed, "COHORT_PROCESSED" if observed["examined"] == count else "BATCH_BOUNDARY")
            forecast = external_forecast(auth, observed)
            if forecast is not None:
                print(json.dumps(dict(status="EXTERNAL_128_REVIEW", **forecast)), flush=True)
                require(forecast["fits"], "CAMPAIGN_CALIBRATION_BUDGET")
            require(len(observed["runs"]) < 40 and observed["active_seconds"]+7800 <= active_limit(auth),
                    "CAMPAIGN_DISPATCH_BUDGET")
            external_deployed(auth)
            fresh = external_history(auth, recovery_run=recovery_run)
            require(fresh == observed and fresh["external_proof"] == frozen, "EXTERNAL_CANONICAL_DRIFT")
            require(external_proof(auth) == frozen, "EXTERNAL_PROOF_DRIFT")
            require(campaign_runs(auth["workflow_run_floor"]) == observed["runs"], "EXTERNAL_CANONICAL_DRIFT")
            require(reconcile_external_family(family, journal, auth, observed) is None,
                    "EXTERNAL_FAMILY_PENDING")
            parent = settled_parent(journal, auth)
            require(parent["sha256"] == observed["parent_sha"]
                    and journal.entries[-1]["kind"] in ("EXTERNAL_COHORT_BOUND", "SETTLED"), "CAMPAIGN_LOCAL_PARENT")
            nonce = PREFIX+os.urandom(12).hex()
            control = dict(authorization=auth, nonce=nonce, recovery_run=recovery_run,
                           preflight_only=False, external_binding=frozen)
            raw = encoded(control)
            require(len(raw) <= 16384, "CAMPAIGN_CONTROL_SIZE")
            family.append("RESERVED", nonce=nonce, remaining=observed["remaining"], capture_auth_sha256=h, scope=ex["scope"],
                          active_seconds_remaining=active_limit(auth)-observed["active_seconds"],
                          parent_checkpoint_sha256=parent["sha256"])
            journal.append("RESERVED", nonce=nonce, remaining=observed["remaining"],
                           active_seconds_remaining=active_limit(auth)-observed["active_seconds"],
                           parent_checkpoint_sha256=parent["sha256"], external_proof_sha256=frozen["proof_sha256"])
            inputs = dict(private_root_folder_id=auth["private_root_folder_id"],
                          private_data_folder_id=auth["private_data_folder_id"], private_research_authorized="true",
                          noncommercial_terms_acknowledged="true", end_date=auth["end"],
                          max_new_symbols=str(external_batch(observed["examined"], count)),
                          resume_file_id=parent["file_id"], resume_sha256=parent["sha256"] if parent["file_id"] else "",
                          campaign_control=raw.decode(), campaign_nonce=nonce)
            result = subprocess.run(["gh", "workflow", "run", WORKFLOW, "--repo", REPO, "--ref", "master", "--json"],
                input=json.dumps(inputs).encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
            require(result.returncode == 0, "CAMPAIGN_DISPATCH_UNCERTAIN")
            run = None
            for _ in range(30):
                matches = [r for r in campaign_runs(auth["workflow_run_floor"]) if r["display_title"] == "a1-sip "+nonce]
                require(len(matches) <= 1, "CAMPAIGN_NONCE_REPLAY")
                if matches:
                    run = matches[0]; break
                time.sleep(2)
            require(run is not None, "CAMPAIGN_DISPATCH_UNCERTAIN")
            family.append("RUN_ASSIGNED", nonce=nonce, run_id=run["id"], capture_auth_sha256=h, scope=ex["scope"])
            journal.append("RUN_ASSIGNED", nonce=nonce, run_id=run["id"])
            subprocess.run(["gh", "run", "watch", str(run["id"]), "--repo", REPO, "--exit-status", "--interval", "30"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=9000)
            # Loop revalidates all family meters/proof before importing or
            # settling. Unknown outcomes leave the reservation intact.
            completed += 1
            recovery_run = None
    except BaseException:
        if journal is not None and last_observed is not None:
            report = external_progress(auth, last_observed, "BLOCKED")
            pending = journal.entries and journal.entries[-1]["kind"] in ("RESERVED", "RUN_ASSIGNED")
            reservations = [e for e in journal.entries if e["kind"] == "RESERVED"]
            report["unsettled_reservation"] = reservations[-1]["remaining"] if pending and reservations else None
            try:
                atomic_json(journal.directory/"progress", report)
            except OSError:
                pass  # Durable append-only reservation is still authoritative.
        raise
    finally:
        try:
            if journal is not None:
                journal.close()
        finally:
            try:
                if family is not None:
                    family.close()
            finally:
                global_journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--recovery-run", type=int)
    parser.add_argument("--account-permission-reference")
    parser.add_argument("--predispatch-recovery", help="Bounded proof bundle for the named local CLI rejection only")
    parser.add_argument("--continuation-receipt", help="External immutable receipt for the approved128-stop continuation")
    parser.add_argument("--cohort-input", help="Exact SHA-bound ticker CSV for a distinct discovery cohort")
    parser.add_argument("--budget-state-dir", help="Existing spent campaign journal; shared lock, read-only prefix")
    parser.add_argument("--max-batches", type=int, help="Stop after this many newly verified external batches")
    args = parser.parse_args()
    try:
        host(args.authorization, args.state_dir, args.recovery_run, args.account_permission_reference,
             args.predispatch_recovery, args.continuation_receipt, args.cohort_input,
             args.budget_state_dir, args.max_batches)
        return 0
    except Refused as exc:
        print(json.dumps(dict(status="BLOCKED", code=str(exc), source_admission=False)))
        return 2
    except Exception:
        print(json.dumps(dict(status="BLOCKED", code="CAMPAIGN_INTERNAL", source_admission=False)))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
