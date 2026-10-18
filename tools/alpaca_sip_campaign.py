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
# A single inspected partial failure, not a generic retry facility. Activation
# still needs a new immutable OWNER record and protected deployed source pins.
NAMED_RECOVERY = dict(
    prior_auth="ca08ac2f7da1d6483a98c2db260f5d7b0beff047980162cb63c9906acc7af8c3",
    run_id=39023083535,
    receipt_sha256="e189da57517ea833e31ed348cdc5930984d0938c79a52b9de43401d4536ace2b",
    checkpoint_sha256="a9459d00316fe60bd1a3638571b484878aa78897d94b0fc8ecdc3c7e323d3e12",
    examined=120, events=13,
    cohort_event_sha256="285fe76aa02e19bdbfaada9891dbd672042b1b6a48d66d59f1547ec6b3ba560d",
    family_event_sha256="a2a0ed1a1709f92cae4a3fbb11ee3f1e96263a0528d7ac69790c015d7b6d37df",
    request_sha256="4a127c70320f7bb44d96d3e180304f0c21cbbbb6d4a5a71110c3356020830397")
# This later, separately authorized failure retains the complete v2 revision.
# A 502 before a CREATE response does not prove that its object is absent.
DRIVE_RECOVERY = dict(
    prior_auth="78bc78ae17352608f963997d4a79c1a75d72f50f0e539b313cf9c9307c53aedd",
    master="ff85c8234088898a57bbe24422d9ecc47a5ced71", run_id=39032304843,
    receipt_sha256="36fb77e3dbc24b379b4b601bf692babe5e996251b92e2424220dfb74265baeeb",
    checkpoint_sha256="f07693bdb23abeabf9540413c3db5ac4c474a13d443d3f5c5dae0fd49d87b89b",
    examined=160, events=23, family_events=22, batch=9,
    cohort_event_sha256="56d10ce5ed74ceb10043d3d7b3374bc0047218910930adb08139cee7c8dcd597",
    family_event_sha256="695dc4445044e0e17a17747a21cdcc8e4c5f51fd0033566c6c2d85dbb67d0a8a",
    request_sha256="9e7391293df9fca33e799f7e2ac893bd6c125fbb03d1f15a93651f240831c7da",
    window_start="2026-10-17T12:23:43Z", window_end="2026-10-17T12:26:22Z",
    raw_bytes=505475)
# The v3 diagnostic failure spent its allowance but admitted no new symbols.
# This successor can derive one normalized object from independently verified
# original ZIP bytes; it cannot repeat the uncertain original CREATE.
MATERIALIZATION_RECOVERY = dict(
    prior_auth="83da6be13d5b8fde8111a12b0b2995870e994867380fb986da637cedcb7700e9",
    master="35b36d289dbae9104042c2158532466076844f9b", run_id=39058081878,
    receipt_sha256="7a2eff65c06d3591072b0440b8c59d2228325653840d8ed4d97d5d62cd4534ad",
    checkpoint_sha256="f07693bdb23abeabf9540413c3db5ac4c474a13d443d3f5c5dae0fd49d87b89b",
    reason="EXTERNAL_ORPHAN_MISSING_OR_AMBIGUOUS", examined=160, events=27, family_events=25, batch=9,
    cohort_event_sha256="50c4ee61a7ef784365c1b5a83cf2b4376bc13482908e7f19f4a8b1c61f057789",
    family_event_sha256="ae439338e83618cd9f0a2f267c55cb8d7a5270561c60b71db024e7dcade325f2",
    request_sha256="b42f7e70e974918e2aefabec5543f4cced79f365be81e207fbdb2e6519ba23dd")
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
    revised = external and isinstance(auth["external_cohort"], dict) and "named_recovery" in auth["external_cohort"]
    drive_revised = revised and "drive_recovery" in auth["external_cohort"]
    material_revised = drive_revised and "materialization_recovery" in auth["external_cohort"]
    require(not (continued and external), "CAMPAIGN_AUTHORIZATION")
    require(isinstance(auth, dict) and set(auth) == AUTH_FIELDS | (
            {"external_cohort"} if external else {"continuation"} if continued else set())
            and auth.get("schema") == ("r1000-sip-external-cohort-authorization-v4" if material_revised else
                                       "r1000-sip-external-cohort-authorization-v3" if drive_revised else
                                       "r1000-sip-external-cohort-authorization-v2" if revised else
                                       "r1000-sip-external-cohort-authorization-v1" if external else
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
        self.last_transport_failure = None
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
                    economic_authority=False,
                    **({"last_transport_failure": self.last_transport_failure}
                       if self.last_transport_failure is not None else {})))

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
        category = ("ALPACA_ASSET" if asset else "ALPACA_BARS" if provider else
                    "OAUTH_TOKEN" if endpoint.netloc == "oauth2.googleapis.com" else
                    "DRIVE_CREATE" if method == "POST" else
                    "DRIVE_MEDIA" if "alt=media" in endpoint.query else "DRIVE_METADATA")
        phase, status = "HEADER_OPEN", None
        def record_failure(http_status=None):
            self.last_transport_failure = dict(
                http_status=http_status if type(http_status) is int and 100 <= http_status <= 599 else None,
                request_category=category, phase=phase, method=method,
                request_ordinal=self.used["provider_gets"]+self.used["drive_requests"])
            try:
                self.save()
            except Exception:
                # Suppress the active HTTP/transport exception context too.
                # Its URL, reason or body may contain sensitive provider data.
                raise Refused("CAMPAIGN_DIAGNOSTIC_JOURNAL") from None
        try:
            with self.opener.open(Request(url, data=body, method=method,
                                         headers=headers or {}),
                                  timeout=min(25, self.remaining_seconds())) as reply:
                phase, status = "HEADERS", reply.status
                require(status == 200, "HTTP_ERROR")
                # read1 bounds each underlying socket read; read(n) can wait
                # indefinitely for n bytes from a trickling peer.
                sock = reply.fp.raw._sock
                chunks, size = [], 0
                phase = "BODY_READ"
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
            record_failure(exc.code)
            raise Refused(code) from None
        except Refused:
            record_failure(status)
            raise
        except Exception:
            record_failure(status)
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
    if "last_transport_failure" in value:
        failure = value["last_transport_failure"]
        require(isinstance(failure, dict) and set(failure) ==
                {"http_status", "request_category", "phase", "method", "request_ordinal"}
                and (failure["http_status"] is None or type(failure["http_status"]) is int
                     and 100 <= failure["http_status"] <= 599)
                and failure["request_category"] in {"ALPACA_ASSET", "ALPACA_BARS", "OAUTH_TOKEN",
                                                    "DRIVE_CREATE", "DRIVE_MEDIA", "DRIVE_METADATA"}
                and failure["phase"] in {"HEADER_OPEN", "HEADERS", "BODY_READ"}
                and failure["method"] in {"GET", "POST"}
                and type(failure["request_ordinal"]) is int
                and 1 <= failure["request_ordinal"] <= value["usage"]["provider_gets"]+value["usage"]["drive_requests"],
                "CAMPAIGN_TRANSPORT_DIAGNOSTIC")
    if "orphan_inventory" in value:
        verify_orphan_inventory(value["orphan_inventory"])
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
    def __init__(self, directory, auth_hash, recovery=None, continuation=None, revision=None, drive_revision=None,
                 material_revision=None):
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
        self.revision = revision
        self.drive_revision = drive_revision
        self.material_revision = material_revision
        try:
            for index, path in enumerate(sorted(self.directory.glob("*.json")), 1):
                require(path.name == f"{index:06d}.json" and not path.is_symlink(),
                        "CAMPAIGN_JOURNAL_CHAIN")
                raw = bounded_bytes(path)
                entry = decode(raw)
                require(entry.get("previous_sha256") == self.parent
                        and entry.get("auth_sha256") == (recovery["binding"]["prior_auth_sha256"]
                            if recovery is not None and index == 1 else
                            CONTINUATION["auth"] if continuation and index <= CONTINUATION["events"] else
                            NAMED_RECOVERY["prior_auth"] if revision and index <= NAMED_RECOVERY["events"] else
                            DRIVE_RECOVERY["prior_auth"] if drive_revision and index <= DRIVE_RECOVERY["events"] else
                            MATERIALIZATION_RECOVERY["prior_auth"] if material_revision
                                and index <= MATERIALIZATION_RECOVERY["events"] else auth_hash)
                        and entry.get("sequence") == index, "CAMPAIGN_JOURNAL_CHAIN")
                if recovery is not None and index == 1:
                    require(digest(raw) == recovery["binding"]["prior_reservation_sha256"],
                            "CAMPAIGN_LOCAL_REJECT_PREFIX")
                if recovery is not None and index == 2:
                    require(raw == encoded(entry), "CAMPAIGN_LOCAL_REJECT_EVENT_BYTES")
                self.parent = digest(raw)
                self.entries.append(entry)
                if revision and index == NAMED_RECOVERY["events"]:
                    require(self.parent == NAMED_RECOVERY["cohort_event_sha256"]
                            and entry.get("kind") == "SETTLED"
                            and entry.get("run_id") == NAMED_RECOVERY["run_id"]
                            and entry.get("receipt_sha256") == NAMED_RECOVERY["receipt_sha256"],
                            "EXTERNAL_RECOVERY_PREFIX")
                if revision and index == NAMED_RECOVERY["events"]+1:
                    require(entry.get("kind") == "EXTERNAL_RECOVERY_BOUND"
                            and {k:entry.get(k) for k in revision} == revision
                            and set(entry) == {"sequence", "kind", "auth_sha256", "previous_sha256", "recorded_utc"} | set(revision)
                            and utc(revision["proof_updated_utc"]) <= utc(entry["recorded_utc"])
                                < utc(revision["expires_at_utc"])
                            and utc(entry["recorded_utc"]) <= utc(), "EXTERNAL_RECOVERY_BINDING")
                if drive_revision and index == DRIVE_RECOVERY["events"]:
                    require(self.parent == DRIVE_RECOVERY["cohort_event_sha256"]
                            and entry.get("kind") == "SETTLED"
                            and entry.get("run_id") == DRIVE_RECOVERY["run_id"]
                            and entry.get("receipt_sha256") == DRIVE_RECOVERY["receipt_sha256"],
                            "EXTERNAL_DRIVE_PREFIX")
                if drive_revision and index == DRIVE_RECOVERY["events"]+1:
                    require(entry.get("kind") == "EXTERNAL_DRIVE_RECOVERY_BOUND"
                            and {k:entry.get(k) for k in drive_revision} == drive_revision
                            and set(entry) == {"sequence", "kind", "auth_sha256", "previous_sha256", "recorded_utc"} | set(drive_revision)
                            and utc(drive_revision["proof_updated_utc"]) <= utc(entry["recorded_utc"])
                                < utc(drive_revision["expires_at_utc"])
                            and utc(entry["recorded_utc"]) <= utc(), "EXTERNAL_DRIVE_BINDING")
                if material_revision and index == MATERIALIZATION_RECOVERY["events"]:
                    require(self.parent == MATERIALIZATION_RECOVERY["cohort_event_sha256"]
                            and entry.get("kind") == "SETTLED"
                            and entry.get("run_id") == MATERIALIZATION_RECOVERY["run_id"]
                            and entry.get("receipt_sha256") == MATERIALIZATION_RECOVERY["receipt_sha256"],
                            "EXTERNAL_MATERIAL_PREFIX")
                if material_revision and index == MATERIALIZATION_RECOVERY["events"]+1:
                    require(entry.get("kind") == "EXTERNAL_MATERIALIZATION_BOUND"
                            and {k:entry.get(k) for k in material_revision} == material_revision
                            and set(entry) == {"sequence", "kind", "auth_sha256", "previous_sha256", "recorded_utc"}
                                | set(material_revision)
                            and utc(material_revision["proof_updated_utc"]) <= utc(entry["recorded_utc"])
                                < utc(material_revision["expires_at_utc"])
                            and utc(entry["recorded_utc"]) <= utc(), "EXTERNAL_MATERIAL_BINDING")
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
            if revision:
                require(len(self.entries) >= NAMED_RECOVERY["events"], "EXTERNAL_RECOVERY_PREFIX")
            if drive_revision:
                require(revision is not None and len(self.entries) >= DRIVE_RECOVERY["events"], "EXTERNAL_DRIVE_PREFIX")
            if material_revision:
                require(drive_revision is not None and len(self.entries) >= MATERIALIZATION_RECOVERY["events"],
                        "EXTERNAL_MATERIAL_PREFIX")
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
        if kind == "EXTERNAL_RECOVERY_BOUND":
            require(self.revision is not None and data == self.revision
                    and len(self.entries) == NAMED_RECOVERY["events"]
                    and self.parent == NAMED_RECOVERY["cohort_event_sha256"]
                    and utc(data["proof_updated_utc"]) <= utc(entry["recorded_utc"])
                        < utc(data["expires_at_utc"]), "EXTERNAL_RECOVERY_BINDING")
        if kind == "EXTERNAL_DRIVE_RECOVERY_BOUND":
            require(self.drive_revision is not None and data == self.drive_revision
                    and len(self.entries) == DRIVE_RECOVERY["events"]
                    and self.parent == DRIVE_RECOVERY["cohort_event_sha256"]
                    and utc(data["proof_updated_utc"]) <= utc(entry["recorded_utc"])
                        < utc(data["expires_at_utc"]), "EXTERNAL_DRIVE_BINDING")
        if kind == "EXTERNAL_MATERIALIZATION_BOUND":
            require(self.material_revision is not None and data == self.material_revision
                    and len(self.entries) == MATERIALIZATION_RECOVERY["events"]
                    and self.parent == MATERIALIZATION_RECOVERY["cohort_event_sha256"]
                    and utc(data["proof_updated_utc"]) <= utc(entry["recorded_utc"])
                        < utc(data["expires_at_utc"]), "EXTERNAL_MATERIAL_BINDING")
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


def verify_orphan_inventory(evidence):
    require(isinstance(evidence, dict) and set(evidence) ==
            {"schema", "observed_at_utc", "window", "files_count", "has_more", "entries"}
            and evidence["schema"] == "a1-bounded-orphan-inventory-v1"
            and evidence["window"] == [DRIVE_RECOVERY["window_start"], DRIVE_RECOVERY["window_end"]]
            and (evidence["files_count"] is None or type(evidence["files_count"]) is int
                 and 0 <= evidence["files_count"] <= 1_000_000)
            and type(evidence["has_more"]) is bool and isinstance(evidence["entries"], list)
            and len(evidence["entries"]) <= 8
            and isinstance(evidence["observed_at_utc"], str)
            and utc(DRIVE_RECOVERY["window_end"]) <= utc(evidence["observed_at_utc"]) <= utc(),
            "EXTERNAL_ORPHAN_DIAGNOSTIC")
    for row in evidence["entries"]:
        require(isinstance(row, dict) and set(row) == {"kind", "sha256", "bytes", "created_at_utc"}
                and row["kind"] in {"RAW", "NORMALIZED", "JSON", "OTHER"}
                and (row["sha256"] is None or isinstance(row["sha256"], str)
                     and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]))
                and (row["bytes"] is None or type(row["bytes"]) is int and 0 <= row["bytes"] <= 16_000_000)
                and (row["created_at_utc"] is None or
                     utc(DRIVE_RECOVERY["window_start"]) <= utc(row["created_at_utc"]) <= utc()),
                "EXTERNAL_ORPHAN_DIAGNOSTIC")


def verify_drive_reuse(reuse, identity):
    material = isinstance(reuse, dict) and "materialization" in reuse
    spec = MATERIALIZATION_RECOVERY if material else DRIVE_RECOVERY
    require(isinstance(reuse, dict) and set(reuse) == {
        "failed_run_id", "capture_source_sha", "derivation_source_sha", "raw_sha256", "normalized_sha256",
        "external_proof_sha256", "derivation_run_id", "derivation_auth_sha256", "parent_checkpoint_sha256",
        "derived_at_utc", "failed_run_observation_window"} | ({"materialization"} if material else set())
        and reuse["failed_run_id"] == spec["run_id"]
        and type(reuse["failed_run_id"]) is int
        and reuse["capture_source_sha"] == DRIVE_RECOVERY["master"]
        and reuse["derivation_source_sha"] == identity["source_sha"]
        and type(reuse["derivation_run_id"]) is int and reuse["derivation_run_id"] == identity["run_id"]
        and reuse["derivation_auth_sha256"] == identity["auth_sha256"]
        and reuse["external_proof_sha256"] == identity["external_proof_sha256"]
        and reuse["parent_checkpoint_sha256"] == DRIVE_RECOVERY["checkpoint_sha256"]
        and reuse["failed_run_observation_window"] == [DRIVE_RECOVERY["window_start"], DRIVE_RECOVERY["window_end"]]
        and all(isinstance(reuse[k], str) and re.fullmatch(r"[0-9a-f]{64}", reuse[k])
                for k in ("raw_sha256", "normalized_sha256"))
        and isinstance(reuse["derived_at_utc"], str)
        and utc(DRIVE_RECOVERY["window_end"]) <= utc(reuse["derived_at_utc"]) <= utc(), "EXTERNAL_ORPHAN_PROVENANCE")
    if material:
        data = reuse["materialization"]
        evidence = identity.get("orphan_inventory")
        verify_orphan_inventory(evidence)
        entries = evidence["entries"]
        originals = [row for row in entries if row["kind"] == "RAW"]
        normalized = [row for row in entries if row["kind"] == "NORMALIZED"]
        require(evidence["has_more"] is False and evidence["files_count"] == len(entries)
                and 1 <= len(entries) <= 8 and len(originals) == 1 and len(normalized) <= 1
                and all(row["kind"] != "OTHER" and row["sha256"] is not None
                        and row["bytes"] is not None and 0 < row["bytes"] < 16_000_000
                        and row["created_at_utc"] is not None
                        and utc(DRIVE_RECOVERY["window_start"]) <= utc(row["created_at_utc"])
                            <= utc(DRIVE_RECOVERY["window_end"]) for row in entries)
                and originals[0]["sha256"] == reuse["raw_sha256"]
                and originals[0]["bytes"] == DRIVE_RECOVERY["raw_bytes"]
                and (not normalized or normalized[0]["sha256"] == reuse["normalized_sha256"]),
                "EXTERNAL_ORPHAN_INVENTORY_CLOSURE")
        require(isinstance(data, dict) and set(data) == {"capture_failed_run_id", "rows_sha256", "codec", "mode",
                "created_at_utc", "lookup_observed_at_utc", "inventory_sha256", "original_create_outcome"}
                and data["capture_failed_run_id"] == DRIVE_RECOVERY["run_id"]
                and type(data["capture_failed_run_id"]) is int
                and isinstance(data["rows_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", data["rows_sha256"])
                and data["mode"] in {"EXISTING_VERIFIED", "DERIVED_NEW"}
                and data["codec"] in {"EXISTING_GZIP_VERIFIED", "GZIP_FILENAME_EMPTY_MTIME0_LEVEL9"}
                and data["codec"] == {"DERIVED_NEW":"GZIP_FILENAME_EMPTY_MTIME0_LEVEL9",
                                      "EXISTING_VERIFIED":"EXISTING_GZIP_VERIFIED"}[data["mode"]]
                and data["original_create_outcome"] == "UNKNOWN"
                and data["inventory_sha256"] == digest(encoded(evidence))
                and isinstance(data["created_at_utc"], str) and isinstance(data["lookup_observed_at_utc"], str)
                and utc(evidence["observed_at_utc"]) <= utc(data["lookup_observed_at_utc"])
                and utc(data["created_at_utc"]) <= utc(data["lookup_observed_at_utc"])
                    <= utc(reuse["derived_at_utc"])
                and (not normalized or data["mode"] == "EXISTING_VERIFIED"
                     and utc(data["created_at_utc"]) == utc(normalized[0]["created_at_utc"]))
                and (normalized or data["mode"] != "EXISTING_VERIFIED" or not
                     utc(DRIVE_RECOVERY["window_start"]) <= utc(data["created_at_utc"]) <= utc(DRIVE_RECOVERY["window_end"]))
                and (data["mode"] != "DERIVED_NEW" or utc(evidence["observed_at_utc"]) <= utc(data["created_at_utc"])),
                "EXTERNAL_MATERIAL_PROVENANCE")


def verify_new_group(drive, folder, state, checkpoint, meter, *, reused_source=False):
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
        expected_source = os.environ["GITHUB_SHA"]
        if reused_source:
            reuse = meter.identity.get("drive_orphan_reuse")
            verify_drive_reuse(reuse, meter.identity)
            recovery_spec = MATERIALIZATION_RECOVERY if "materialization" in reuse else DRIVE_RECOVERY
            require(isinstance(reuse, dict) and receipt.get("recovered_from") == reuse
                    and meter.identity.get("recovery_run") == recovery_spec["run_id"]
                    and meter.identity.get("examined_before") == meter.examined == DRIVE_RECOVERY["examined"]
                    and meter.checkpoint_sha == DRIVE_RECOVERY["checkpoint_sha256"]
                    and receipt.get("symbols") == ["TWST", "UBS", "UL", "UPST"]
                    and objects[0]["sha256"] == reuse.get("raw_sha256")
                    and objects[1]["sha256"] == reuse.get("normalized_sha256")
                    and reuse.get("failed_run_id") == recovery_spec["run_id"]
                    and reuse.get("capture_source_sha") == DRIVE_RECOVERY["master"]
                    and reuse.get("derivation_source_sha") == expected_source
                    and reuse.get("derivation_run_id") == meter.identity["run_id"]
                    and reuse.get("derivation_auth_sha256") == meter.identity["auth_sha256"]
                    and reuse.get("parent_checkpoint_sha256") == DRIVE_RECOVERY["checkpoint_sha256"]
                    and state.get("recovered_from") == reuse
                    and state.get("source_sha") == DRIVE_RECOVERY["master"]
                    and reuse.get("external_proof_sha256") == meter.identity["external_proof_sha256"],
                    "EXTERNAL_ORPHAN_SOURCE")
            expected_source = DRIVE_RECOVERY["master"]
        require(receipt.get("raw_object") == objects[0]
                and receipt.get("normalized_object") == objects[1]
                and receipt.get("source_sha") == expected_source
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
        if reused_source and "materialization" in reuse:
            require(digest(cap.gzip.decompress(normalized)) == reuse["materialization"]["rows_sha256"],
                    "EXTERNAL_MATERIAL_ROWS")
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
        binding = active_external_revision(journal)[0] or journal.entries[0]
        frozen = {k: binding[k] for k in ("proof_sha256", "proof_updated_utc", "expires_at_utc")}
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
    revised = isinstance(ex, dict) and "named_recovery" in ex
    drive_revised = isinstance(ex, dict) and "drive_recovery" in ex
    material_revised = isinstance(ex, dict) and "materialization_recovery" in ex
    require(isinstance(ex, dict) and set(ex) == {"scope", "input_csv", "intake_manifest_sha256",
            "receipt_dedupe_sha256", "prior_authorization", "prior_epochs", "proof_reference"}
            | ({"named_recovery"} if revised else set())
            | ({"drive_recovery"} if drive_revised else set())
            | ({"materialization_recovery"} if material_revised else set()), "EXTERNAL_AUTHORIZATION")
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
    if material_revised:
        recovery = ex["materialization_recovery"]
        require(drive_revised and revised and isinstance(recovery, dict) and set(recovery) ==
                {"prior_capture_source", "failed_run_id", "failed_receipt_sha256", "checkpoint_sha256", "examined"},
                "EXTERNAL_MATERIAL_RECOVERY")
        source = recovery["prior_capture_source"]
        require(isinstance(source, dict) and set(source) == {"expected_master", "code_pins", "proof_reference"}
                and ex["prior_epochs"] == [], "EXTERNAL_MATERIAL_RECOVERY")
        previous = external_previous(auth)
        require(validate_authorization(previous) == MATERIALIZATION_RECOVERY["prior_auth"]
                and previous["expected_master"] == MATERIALIZATION_RECOVERY["master"]
                and all(recovery[k] == MATERIALIZATION_RECOVERY[v] and type(recovery[k]) is type(MATERIALIZATION_RECOVERY[v])
                        for k,v in (("failed_run_id","run_id"),("failed_receipt_sha256","receipt_sha256"),
                                    ("checkpoint_sha256","checkpoint_sha256"),("examined","examined")))
                and all(ex[k] == previous["external_cohort"][k] for k in ex
                        if k not in ("materialization_recovery", "proof_reference"))
                and all(auth[k] == previous[k] for k in AUTH_FIELDS
                        - {"schema", "expected_master", "code_pins", "account_permission_reference"})
                and auth["expected_master"] != previous["expected_master"]
                and ex["proof_reference"] != previous["external_cohort"]["proof_reference"],
                "EXTERNAL_MATERIAL_RECOVERY")
    elif drive_revised:
        recovery = ex["drive_recovery"]
        require(revised and isinstance(recovery, dict) and set(recovery) ==
                {"prior_capture_source", "failed_run_id", "failed_receipt_sha256", "checkpoint_sha256", "examined"},
                "EXTERNAL_DRIVE_RECOVERY")
        source = recovery["prior_capture_source"]
        require(isinstance(source, dict) and set(source) == {"expected_master", "code_pins", "proof_reference"}
                and ex["prior_epochs"] == [], "EXTERNAL_DRIVE_RECOVERY")
        previous = external_previous(auth)
        require(validate_authorization(previous) == DRIVE_RECOVERY["prior_auth"]
                and previous["expected_master"] == DRIVE_RECOVERY["master"]
                and all(recovery[k] == DRIVE_RECOVERY[v] and type(recovery[k]) is type(DRIVE_RECOVERY[v])
                        for k,v in (("failed_run_id","run_id"),("failed_receipt_sha256","receipt_sha256"),
                                    ("checkpoint_sha256","checkpoint_sha256"),("examined","examined")))
                and all(ex[k] == previous["external_cohort"][k] for k in ex
                        if k not in ("drive_recovery", "proof_reference"))
                and all(auth[k] == previous[k] for k in AUTH_FIELDS
                        - {"schema", "expected_master", "code_pins", "account_permission_reference"})
                and auth["expected_master"] != previous["expected_master"]
                and ex["proof_reference"] != previous["external_cohort"]["proof_reference"],
                "EXTERNAL_DRIVE_RECOVERY")
    elif revised:
        recovery = ex["named_recovery"]
        require(isinstance(recovery, dict) and set(recovery) ==
                {"prior_capture_source", "failed_run_id", "failed_receipt_sha256", "checkpoint_sha256", "examined"},
                "EXTERNAL_NAMED_RECOVERY")
        source = recovery["prior_capture_source"]
        require(isinstance(source, dict) and set(source) == {"expected_master", "code_pins", "proof_reference"}
                and ex["prior_epochs"] == [], "EXTERNAL_NAMED_RECOVERY")
        previous = external_previous(auth)
        require(validate_authorization(previous) == NAMED_RECOVERY["prior_auth"]
                and all(recovery[k] == NAMED_RECOVERY[v] and type(recovery[k]) is type(NAMED_RECOVERY[v])
                        for k,v in (("failed_run_id","run_id"),("failed_receipt_sha256","receipt_sha256"),
                                    ("checkpoint_sha256","checkpoint_sha256"),("examined","examined")))
                and all(ex[k] == previous["external_cohort"][k] for k in ex
                        if k not in ("named_recovery", "proof_reference"))
                and all(auth[k] == previous[k] for k in AUTH_FIELDS
                        - {"schema", "expected_master", "code_pins", "account_permission_reference"})
                and auth["expected_master"] != previous["expected_master"]
                and ex["proof_reference"] != previous["external_cohort"]["proof_reference"],
                "EXTERNAL_NAMED_RECOVERY")


def external_previous(auth):
    """Reconstruct exact old bytes from immutable shared fields + typed source delta.

    Its complete canonical hash must equal the named original authorization;
    deduplication keeps a later top500 wrapper below the unchanged control cap.
    """
    ex = auth["external_cohort"]
    material_revised = "materialization_recovery" in ex
    drive_revised = "drive_recovery" in ex
    field = "materialization_recovery" if material_revised else "drive_recovery" if drive_revised else "named_recovery"
    source = ex[field]["prior_capture_source"]
    old_ex = {k:v for k,v in ex.items() if k != field}
    old_ex["proof_reference"] = source["proof_reference"]
    return dict(auth, schema=("r1000-sip-external-cohort-authorization-v3" if material_revised else
                             "r1000-sip-external-cohort-authorization-v2" if drive_revised else
                             "r1000-sip-external-cohort-authorization-v1"),
                expected_master=source["expected_master"], code_pins=source["code_pins"],
                account_permission_reference=source["proof_reference"], external_cohort=old_ex)


def external_variants(auth):
    named = auth["external_cohort"].get("named_recovery")
    return external_variants(external_previous(auth)) + [auth] if named else [auth]


def external_recoveries(auth):
    """Sealed inspected transitions only; never arbitrary retry authority."""
    ex = auth["external_cohort"]
    result = [dict(NAMED_RECOVERY, batch=8)] if "named_recovery" in ex else []
    if "drive_recovery" in ex:
        result.append(DRIVE_RECOVERY)
    if "materialization_recovery" in ex:
        result.append(MATERIALIZATION_RECOVERY)
    return result


def external_revision(auth, proof):
    if "named_recovery" not in auth["external_cohort"]:
        return None
    return dict(prior_auth_sha256=NAMED_RECOVERY["prior_auth"],
                failed_run_id=NAMED_RECOVERY["run_id"], failed_receipt_sha256=NAMED_RECOVERY["receipt_sha256"],
                checkpoint_sha256=NAMED_RECOVERY["checkpoint_sha256"], examined=NAMED_RECOVERY["examined"], **proof)


def external_journal(directory, auth, proof, *, epoch_proofs=None):
    revisions = []
    versions = external_variants(auth)
    for version, spec in zip(versions[1:], external_recoveries(auth)):
        if version is auth:
            version_proof = proof
        elif epoch_proofs is None:
            version_proof = external_proof(version)  # Initial open, before canonical reconciliation.
        else:
            require(isinstance(epoch_proofs, dict), "EXTERNAL_PRIOR_JOURNAL_DRIFT")
            version_proof = epoch_proofs.get(validate_authorization(version))
            require(isinstance(version_proof, dict), "EXTERNAL_PRIOR_JOURNAL_DRIFT")
        revisions.append(dict(prior_auth_sha256=spec["prior_auth"], failed_run_id=spec["run_id"],
            failed_receipt_sha256=spec["receipt_sha256"], checkpoint_sha256=spec["checkpoint_sha256"],
            examined=spec["examined"], **version_proof))
    revision, drive_revision, material_revision = (revisions+[None]*3)[:3]
    if revision:
        require(Path(directory).is_dir() and not Path(directory).is_symlink()
                and (Path(directory)/f"{NAMED_RECOVERY['events']:06d}.json").is_file(), "EXTERNAL_RECOVERY_PREFIX")
    return WorkJournal(directory, validate_authorization(auth), revision=revision,
                       drive_revision=drive_revision, material_revision=material_revision)


def active_external_revision(journal):
    for field, spec, kind in (("material_revision", MATERIALIZATION_RECOVERY, "EXTERNAL_MATERIALIZATION_BOUND"),
                             ("drive_revision", DRIVE_RECOVERY, "EXTERNAL_DRIVE_RECOVERY_BOUND"),
                             ("revision", NAMED_RECOVERY, "EXTERNAL_RECOVERY_BOUND")):
        value = getattr(journal, field, None)
        if value:
            return value, spec, kind
    return None, None, None


def named_failed_receipt(run, value, auth):
    for spec in external_recoveries(auth):
        matched = (run.get("id") == spec["run_id"] and run.get("run_attempt") == 1
            and run.get("conclusion") == "failure" and value.get("status") == "BLOCKED"
            and value.get("reason") == spec.get("reason", "HTTP_ERROR") and value.get("auth_sha256") == spec["prior_auth"]
            and digest(encoded(value)) == spec["receipt_sha256"]
            and value.get("checkpoint_sha256") == spec["checkpoint_sha256"]
            and value.get("examined_after") == spec["examined"])
        if matched and spec is DRIVE_RECOVERY:
            require(value.get("last_transport_failure") == dict(http_status=502, method="POST",
                phase="HEADER_OPEN", request_category="DRIVE_CREATE", request_ordinal=343),
                "EXTERNAL_DRIVE_FAILURE_DIAGNOSTIC")
        if matched:
            return True
    return False


def external_proof_record(auth):
    ex = auth["external_cohort"]
    result = dict(schema="a1-sip-external-cohort-consent-v1", budget_task_key=TASK,
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
    if "named_recovery" in ex:
        result.update(named_recovery=dict(prior_capture_auth_sha256=NAMED_RECOVERY["prior_auth"],
            failed_run_id=NAMED_RECOVERY["run_id"], failed_receipt_sha256=NAMED_RECOVERY["receipt_sha256"],
            checkpoint_sha256=NAMED_RECOVERY["checkpoint_sha256"], examined=NAMED_RECOVERY["examined"],
            recovery_dispatch_limit=1, first_recovery_batch_limit=8,
            unknown_http_status_acknowledged=True, request_sha256=NAMED_RECOVERY["request_sha256"]))
    if "drive_recovery" in ex:
        result.update(drive_recovery=dict(prior_capture_auth_sha256=DRIVE_RECOVERY["prior_auth"],
            failed_run_id=DRIVE_RECOVERY["run_id"], failed_receipt_sha256=DRIVE_RECOVERY["receipt_sha256"],
            checkpoint_sha256=DRIVE_RECOVERY["checkpoint_sha256"], examined=DRIVE_RECOVERY["examined"],
            recovery_dispatch_limit=1, first_recovery_batch_limit=9,
            uncertain_create_outcome_acknowledged=True, request_sha256=DRIVE_RECOVERY["request_sha256"]))
    if "materialization_recovery" in ex:
        spec = MATERIALIZATION_RECOVERY
        result.update(materialization_recovery=dict(prior_capture_auth_sha256=spec["prior_auth"],
            failed_run_id=spec["run_id"], failed_receipt_sha256=spec["receipt_sha256"],
            checkpoint_sha256=spec["checkpoint_sha256"], examined=spec["examined"],
            recovery_dispatch_limit=1, first_recovery_batch_limit=9,
            normalized_only_derivation=True, original_create_outcome_unknown=True,
            request_sha256=spec["request_sha256"]))
    return result


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


def external_history(auth, current_run=None, nonce=None, recovery_run=None, enforce_expiry=True, *, allow_stopped=False,
                     native_read_run=None):
    """All costs; a named auth revision stays inside the same logical cohort."""
    from tools import alpaca_sip_private_backfill_v1 as cap
    auth_hash = validate_authorization(auth)
    ex = auth["external_cohort"]
    named = "named_recovery" in ex
    recoveries = external_recoveries(auth)
    require(recovery_run is None or named and type(recovery_run) is int
            and recovery_run == recoveries[-1]["run_id"], "EXTERNAL_RECOVERY_NOT_AUTHORIZED")
    epochs = ex["prior_epochs"] + [auth]
    variants = [(position, a) for position, epoch in enumerate(epochs) for a in external_variants(epoch)]
    hashes = [validate_authorization(a) for position,a in variants]
    require(len(set(hashes)) == len(hashes), "EXTERNAL_EPOCH_LIMIT")
    proofs = {h: external_proof(a) for h,(position,a) in zip(hashes,variants)}
    by_hash = dict(zip(hashes, variants))
    runs = campaign_runs(auth["workflow_run_floor"])
    if native_read_run is not None:
        require(current_run is None and allow_stopped, "NATIVE_READ_HISTORY_MODE")
        runs = native_read_prefix(runs, native_read_run)
    require([r["id"] for r in runs[:5]] == CONTINUATION["runs"], "EXTERNAL_BUDGET_PREFIX")
    if current_run is not None:
        require(len(runs) > 5 and runs[-1]["id"] == current_run
                and runs[-1]["display_title"] == "a1-sip " + nonce and runs[-1].get("run_attempt") == 1
                and runs[-1].get("head_sha") == auth["expected_master"], "CAMPAIGN_SINGLE_USE")
    previous = runs[:-1] if current_run is not None else runs
    used, active = {k: 0 for k in LIMITS}, 0
    local = [dict(parent=external_genesis(a["external_cohort"]["scope"]), examined=0,
                  receipts=[], runs=[], durations=[], version=0, named_failures=set()) for a in epochs]
    old_parent, old_examined = INITIAL_SHA, 16
    receipts, durations, epoch_index = [], [], 0
    for index, run in enumerate(previous):
        named_failure = False
        if index < 5:
            value = receipt_for_run(run, CONTINUATION["auth"], CONTINUATION["master"])
            require(digest(encoded(value)) == CONTINUATION["receipts"][index]
                    and value["parent_checkpoint_sha256"] == old_parent
                    and value["examined_before"] == old_examined, "EXTERNAL_BUDGET_PREFIX")
            old_parent, old_examined = value["checkpoint_sha256"], value["examined_after"]
            caps = LIMITS
        else:
            require(run.get("head_sha") in {a["expected_master"] for position,a in variants}, "CAMPAIGN_SOURCE")
            value = receipt_for_run(run, tuple(hashes), run["head_sha"], CONTINUED_LIMITS)
            h = value["auth_sha256"]
            require(h in by_hash, "EXTERNAL_RECEIPT_BINDING")
            position, a = by_hash[h]
            require(position >= epoch_index, "EXTERNAL_EPOCH_ORDER")
            if position > epoch_index:
                require(all(local[j]["examined"] == len(cap.external_cohort(
                    epochs[j]["external_cohort"]["input_csv"].encode())) for j in range(position)), "EXTERNAL_EPOCH_INCOMPLETE")
            epoch_index = position
            proof, state, epoch = proofs[h], local[position], epochs[position]
            epoch_variants = external_variants(epoch)
            transitions = external_recoveries(epoch)
            version = [validate_authorization(v) for v in epoch_variants].index(h)
            require(state["version"] <= version <= state["version"]+1, "EXTERNAL_AUTH_REVISION_ORDER")
            expected_recovery = None
            if version > state["version"]:
                transition = transitions[version-1]
                require(transition["run_id"] in state["named_failures"]
                        and state["examined"] == transition["examined"]
                        and state["parent"] == transition["checkpoint_sha256"], "EXTERNAL_RECOVERY_PARENT")
                expected_recovery = transition["run_id"]
            elif version < len(transitions):
                require(transitions[version]["run_id"] not in state["named_failures"], "EXTERNAL_AUTH_REVISION_ORDER")
            state["version"] = version
            scope = a["external_cohort"]["scope"]
            require(value.get("source_sha") == a["expected_master"] and value.get("cohort_scope") == scope
                    and value.get("recovery_run") == expected_recovery
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
            require((value["examined_after"] > state["examined"]) == (value["checkpoint_sha256"] != state["parent"]), "EXTERNAL_CHECKPOINT_CHAIN")
            if expected_recovery is not None and value["status"] == "COMPLETE":
                require(value["examined_after"] == transition["examined"]+transition["batch"],
                        "EXTERNAL_RECOVERY_CLOSURE")
            if "drive_recovery" in a["external_cohort"]:
                require(value["examined_after"] == DRIVE_RECOVERY["examined"]
                        or value["examined_after"] >= DRIVE_RECOVERY["examined"]+4, "EXTERNAL_ORPHAN_CLOSURE")
                if value["examined_after"] > DRIVE_RECOVERY["examined"] or "drive_orphan_reuse" in value:
                    verify_drive_reuse(value.get("drive_orphan_reuse"), value)
                    require(("materialization" in value["drive_orphan_reuse"]) ==
                            ("materialization_recovery" in a["external_cohort"]), "EXTERNAL_ORPHAN_PROVENANCE")
                    if "materialization_recovery" in a["external_cohort"]:
                        require(isinstance(run["created_at"], str)
                                and utc(run["created_at"]) <= utc(value["orphan_inventory"]["observed_at_utc"]),
                                "EXTERNAL_MATERIAL_RUN_CLOCK")
            state.update(parent=value["checkpoint_sha256"], examined=value["examined_after"])
            state["runs"].append(run); state["receipts"].append(value)
            named_failure = named_failed_receipt(run, value, epoch)
            if named_failure:
                state["named_failures"].add(run["id"])
            caps = CONTINUED_LIMITS
        for k in LIMITS:
            require(value["allowance"][k] == caps[k]-used[k], "CAMPAIGN_ALLOWANCE_RESET")
            used[k] += value["usage"][k]
            require(used[k] <= caps[k], "CAMPAIGN_LEDGER_BUDGET")
        seconds = job_seconds(run)
        active += seconds
        if index < 5 and index == 4:
            require(used == CONTINUATION["used"] and active == CONTINUATION["active_seconds"]
                    and old_parent == CONTINUATION["checkpoint"] and old_examined == CONTINUATION["examined"], "EXTERNAL_BUDGET_PREFIX")
        if index >= 5:
            state["durations"].append(seconds)
        receipts.append(value); durations.append(seconds)
        failed = value["status"] != "COMPLETE" or run.get("conclusion") != "success"
        if failed and not named_failure:
            if allow_stopped and current_run is None and run == previous[-1] and value["status"] == "BLOCKED":
                require(isinstance(value.get("reason"), str) and re.fullmatch(r"[A-Z_]{1,80}", value["reason"]), "CAMPAIGN_REASON")
                continue
            raise Refused("CAMPAIGN_EXTERNAL_FAILURE_STOP")
    require(all(spec["run_id"] in state["named_failures"] for state,epoch in zip(local,epochs)
                for spec in external_recoveries(epoch)), "EXTERNAL_RECOVERY_PARENT")
    require(active <= active_limit(auth) and utc(runs[0]["created_at"]) == utc(CONTINUATION["first"]), "CAMPAIGN_ACTIVE_TIME")
    first = utc(CONTINUATION["first"])
    if enforce_expiry:
        require(utc() < first+timedelta(hours=48), "CAMPAIGN_EXPIRED")
    state = local[-1]
    expected_recovery = recoveries[-1]["run_id"] if named and state["version"] < len(recoveries) else None
    if current_run is not None or not allow_stopped:
        require(recovery_run == expected_recovery, "EXTERNAL_RECOVERY_NOT_AUTHORIZED")
    if len(epochs) > 1:
        require(local[0]["examined"] == len(cap.external_cohort(epochs[0]["external_cohort"]["input_csv"].encode())), "EXTERNAL_EPOCH_INCOMPLETE")
    return dict(runs=runs, receipts=receipts, used=used, active_seconds=active, first=first,
                durations=durations, bindings=CONTINUATION["bindings"], external_proof=proofs[auth_hash],
                epoch_proofs=proofs, parent_sha=state["parent"], examined=state["examined"],
                cohort_runs=state["runs"], cohort_receipts=state["receipts"], cohort_durations=state["durations"],
                recovery_required=expected_recovery,
                remaining={k: CONTINUED_LIMITS[k]-used[k] for k in LIMITS})


def orphan_inventory(drive, folder, meter):
    """One bounded original-time query. Persist only allowlisted diagnostics."""
    spec = DRIVE_RECOVERY
    query = ("'"+folder+"' in parents and trashed = false and createdTime >= '"+spec["window_start"]
             +"' and createdTime <= '"+spec["window_end"]+"'")
    listed = credential_safe_json(drive.request("https://www.googleapis.com/drive/v3/files?"+urlencode(dict(
        q=query, pageSize=8, fields="nextPageToken,files(id,name,size,parents,createdTime)"))), (drive.token,))
    files = listed.get("files") if isinstance(listed, dict) else None
    evidence = dict(schema="a1-bounded-orphan-inventory-v1", observed_at_utc=utc().isoformat(),
        window=[spec["window_start"], spec["window_end"]], files_count=len(files) if isinstance(files, list) else None,
        has_more=not isinstance(listed, dict) or listed.get("nextPageToken") is not None, entries=[])
    for item in files[:8] if isinstance(files, list) else []:
        item = item if isinstance(item, dict) else {}
        name = item.get("name")
        match = re.fullmatch(r"([0-9a-f]{64})(\.zip|\.jsonl\.gz|\.json)", name) if isinstance(name, str) else None
        size = item.get("size")
        size = int(size) if isinstance(size, str) and size.isascii() and size.isdigit() and len(size) <= 8 else None
        created = item.get("createdTime")
        try:
            if not (utc(spec["window_start"]) <= utc(created) <= utc()):
                created = None
        except Refused:
            created = None
        evidence["entries"].append(dict(kind={".zip":"RAW", ".jsonl.gz":"NORMALIZED", ".json":"JSON"}.get(
            match[2] if match else None, "OTHER"), sha256=match[1] if match else None,
            bytes=size if size is not None and size <= 16_000_000 else None, created_at_utc=created))
    verify_orphan_inventory(evidence)
    meter.identity["orphan_inventory"] = evidence
    meter.save()  # Survives a count/role/metadata refusal without leaking IDs or raw names.
    require(isinstance(files, list) and len(files) <= 8 and not evidence["has_more"], "EXTERNAL_ORPHAN_INVENTORY")
    kinds, ids = {"raw":[], "normalized":[]}, set()
    for item, safe in zip(files, evidence["entries"]):
        validate_orphan_item(item, folder)
        require(item["id"] not in ids and safe["kind"] != "OTHER"
                and utc(spec["window_start"]) <= utc(item["createdTime"]) <= utc(spec["window_end"]),
                "EXTERNAL_ORPHAN_LISTING")
        ids.add(item["id"])
        if safe["kind"] != "JSON":
            kinds["raw" if safe["kind"] == "RAW" else "normalized"].append(item)
    require(len(kinds["raw"]) == 1 and len(kinds["normalized"]) <= 1, "EXTERNAL_ORPHAN_ROLES")
    return kinds


def validate_orphan_item(item, folder):
    require(isinstance(item, dict) and isinstance(item.get("name"), str)
            and re.fullmatch(r"[0-9a-f]{64}\.(zip|jsonl\.gz|json)", item["name"])
            and isinstance(item.get("id"), str) and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", item["id"])
            and item.get("parents") == [folder] and isinstance(item.get("size"), str)
            and item["size"].isascii() and item["size"].isdigit() and len(item["size"]) <= 8
            and 0 < int(item["size"]) < 16_000_000
            and isinstance(item.get("createdTime"), str)
            and utc(item["createdTime"]) <= utc(),
            "EXTERNAL_ORPHAN_LISTING")


def read_orphan_item(drive, folder, item):
    validate_orphan_item(item, folder)
    drive.check(item["id"], folder, folder=False)
    raw = drive.read(item["id"], 16_000_000)
    require(len(raw) == int(item["size"]) and digest(raw) == item["name"][:64], "EXTERNAL_ORPHAN_HASH")
    return dict(file_id=item["id"], sha256=digest(raw), bytes=len(raw)), raw


def lookup_orphan_normalized(drive, folder, name):
    require(re.fullmatch(r"[0-9a-f]{64}\.jsonl\.gz", name), "EXTERNAL_ORPHAN_LISTING")
    query = "name = '"+name+"' and '"+folder+"' in parents and trashed = false"
    result = credential_safe_json(drive.request("https://www.googleapis.com/drive/v3/files?"+urlencode(dict(
        q=query, pageSize=2, fields="nextPageToken,files(id,name,size,parents,createdTime)"))), (drive.token,))
    require(isinstance(result, dict) and result.get("nextPageToken") is None
            and isinstance(result.get("files"), list) and len(result["files"]) <= 1, "EXTERNAL_ORPHAN_NORMALIZED_LOOKUP")
    for item in result["files"]:
        validate_orphan_item(item, folder)
        require(item["name"] == name, "EXTERNAL_ORPHAN_NORMALIZED_LOOKUP")
    return result["files"]


def recover_drive_orphan(drive, args, auth, meter, *, materialize=False):
    """Only exact existing bytes from the sealed failed POST window; no GETs
    to providers and no raw/normalized uploads, even when an object is absent.
    The old capture source and original asset clocks remain unchanged.
    """
    from tools import alpaca_sip_private_backfill_v1 as cap
    spec, ex = DRIVE_RECOVERY, auth["external_cohort"]
    names = cap.external_cohort(ex["input_csv"].encode())
    group = names[160:164]
    require(group == ["TWST", "UBS", "UL", "UPST"]
            and meter.identity.get("recovery_run") == (MATERIALIZATION_RECOVERY if materialize else spec)["run_id"]
            and meter.examined == spec["examined"] and meter.checkpoint_sha == spec["checkpoint_sha256"],
            "EXTERNAL_ORPHAN_PARENT")
    folder = args.private_data_folder_id
    require(isinstance(folder, str) and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", folder), "PRIVATE_FOLDER")
    if materialize:
        require("materialization_recovery" in ex, "EXTERNAL_MATERIAL_RECOVERY")
        kinds = orphan_inventory(drive, folder, meter)
        ref, raw = read_orphan_item(drive, folder, kinds["raw"][0])
        require(ref["bytes"] == spec["raw_bytes"], "EXTERNAL_ORPHAN_RAW_SIZE")
        refs, contents = {"raw":ref}, {"raw":raw}
    else:
        refs, contents = legacy_orphan_objects(drive, folder)
    return finish_drive_orphan(drive, args, auth, meter, refs, contents, kinds if materialize else None)


def legacy_orphan_objects(drive, folder):
    spec = DRIVE_RECOVERY
    query = ("'"+folder+"' in parents and trashed = false and createdTime >= '"+spec["window_start"]
             +"' and createdTime <= '"+spec["window_end"]+"'")
    listed = credential_safe_json(drive.request("https://www.googleapis.com/drive/v3/files?"+urlencode(dict(
        q=query, pageSize=8, fields="nextPageToken,files(id,name,size,parents,createdTime)"))), (drive.token,))
    require(isinstance(listed, dict) and listed.get("nextPageToken") is None
            and isinstance(listed.get("files"), list) and len(listed["files"]) == 2,
            "EXTERNAL_ORPHAN_MISSING_OR_AMBIGUOUS")
    refs, contents, ids = {}, {}, set()
    for item in listed["files"]:
        require(isinstance(item, dict) and isinstance(item.get("name"), str)
                and re.fullmatch(r"[0-9a-f]{64}\.(zip|jsonl\.gz)", item["name"])
                and isinstance(item.get("id"), str) and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", item["id"])
                and item["id"] not in ids and item.get("parents") == [folder]
                and isinstance(item.get("size"), str) and item["size"].isdigit()
                and 0 < int(item["size"]) < 16_000_000
                and utc(spec["window_start"]) <= utc(item.get("createdTime")) <= utc(spec["window_end"]),
                "EXTERNAL_ORPHAN_LISTING")
        kind = "raw" if item["name"].endswith(".zip") else "normalized"
        require(kind not in refs, "EXTERNAL_ORPHAN_MISSING_OR_AMBIGUOUS")
        ids.add(item["id"])
        drive.check(item["id"], folder, folder=False)
        raw = drive.read(item["id"], 16_000_000)
        require(len(raw) == int(item["size"]) and digest(raw) == item["name"][:64], "EXTERNAL_ORPHAN_HASH")
        refs[kind] = dict(file_id=item["id"], sha256=digest(raw), bytes=len(raw))
        contents[kind] = raw
    require(set(refs) == {"raw", "normalized"} and refs["raw"]["bytes"] == spec["raw_bytes"],
            "EXTERNAL_ORPHAN_MISSING_OR_AMBIGUOUS")
    return refs, contents


def finish_drive_orphan(drive, args, auth, meter, refs, contents, kinds):
    from tools import alpaca_sip_private_backfill_v1 as cap
    spec, ex, folder = DRIVE_RECOVERY, auth["external_cohort"], args.private_data_folder_id
    names = cap.external_cohort(ex["input_csv"].encode())
    group = names[160:164]
    try:
        with cap.zipfile.ZipFile(cap.io.BytesIO(contents["raw"])) as archive:
            infos = archive.infolist()
            require(len(infos) <= 2*cap.MAX_PAGES+1 and len({i.filename for i in infos}) == len(infos)
                    and sum(i.file_size for i in infos) <= 128_000_000
                    and all(i.file_size <= cap.MAX_PAGE_BYTES for i in infos), "EXTERNAL_ORPHAN_ARCHIVE")
            manifest = decode(archive.read("capture.json"))
            require(manifest.get("symbols") == group and manifest.get("source_sha") == spec["master"]
                    and manifest.get("cohort_scope") == ex["scope"] and manifest.get("seed_sha256") == ex["scope"]["input_sha256"]
                    and manifest.get("start") == auth["start"] and manifest.get("end") == auth["end"],
                    "EXTERNAL_ORPHAN_SCOPE")
            grids = {basis:{name:[] for name in group} for basis in ("raw", "split")}
            require(isinstance(manifest.get("pages"), list) and 2 <= len(manifest["pages"]) <= 2*cap.MAX_PAGES,
                    "EXTERNAL_ORPHAN_ARCHIVE")
            for page in manifest["pages"]:
                require(isinstance(page, dict) and page.get("adjustment") in grids
                        and isinstance(page.get("member"), str), "EXTERNAL_ORPHAN_ARCHIVE")
                payload = decode(archive.read(page["member"]))
                require(isinstance(payload, dict) and isinstance(payload.get("bars"), dict)
                        and set(payload["bars"]) <= set(group), "EXTERNAL_ORPHAN_ARCHIVE")
                for symbol, bars in payload["bars"].items():
                    require(isinstance(bars, list), "EXTERNAL_ORPHAN_ARCHIVE")
                    grids[page["adjustment"]][symbol].extend(bars)
    except (KeyError, ValueError, OSError, cap.zipfile.BadZipFile):
        raise Refused("EXTERNAL_ORPHAN_ARCHIVE") from None
    rows = []
    for symbol in group:
        for basis in ("raw", "split"):
            rows.extend(cap.normalize(grids[basis][symbol], symbol, basis, auth["start"], auth["end"]))
    row_bytes = b"".join(encoded(row) for row in rows)
    norm_item = None
    if kinds is not None:
        # Gzip wrapper bytes differ across Python versions. Compare rebuilt row
        # bytes separately and use an explicit encoder for this new derivation.
        buffer = cap.io.BytesIO()
        with cap.gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0) as handle:
            handle.write(row_bytes)
        canonical = buffer.getvalue()
        candidates = kinds["normalized"]
        if candidates:
            indexed = lookup_orphan_normalized(drive, folder, candidates[0]["name"])
            require(indexed == candidates, "EXTERNAL_ORPHAN_NORMALIZED_LOOKUP")
        else:
            # Python3.12's fast gzip path may retain zlib's OS=3 header;
            # later Python versions use255. These are candidate content names,
            # never evidence that any prior object was actually created.
            for hashed in sorted({digest(canonical), digest(cap.gzip.compress(row_bytes, mtime=0)),
                                  digest(canonical[:9]+b"\x03"+canonical[10:])}):
                candidates += lookup_orphan_normalized(drive, folder, hashed+".jsonl.gz")
        require(len(candidates) <= 1, "EXTERNAL_ORPHAN_ROLES")
        if candidates:
            norm_item = candidates[0]
            refs["normalized"], contents["normalized"] = read_orphan_item(drive, folder, norm_item)
        else:
            contents["normalized"] = canonical
            refs["normalized"] = dict(sha256=digest(canonical), bytes=len(canonical))  # Not a stored object yet.
    receipt = dict(schema=cap.SCHEMA, scope="PRIVATE_RESEARCH_ONLY", source=cap.SOURCE,
        source_sha=spec["master"], seed_sha256=ex["scope"]["input_sha256"],
        start=auth["start"], end=auth["end"], asof=cap.mapping_asof(auth["end"]), symbols=group,
        collected=manifest.get("collected"), no_bars=manifest.get("no_bars"), pages=len(manifest["pages"]),
        rows=len(rows), raw_object=refs["raw"], normalized_object=refs["normalized"],
        readback_verified=True, source_admission=False, pit_verified=False,
        historical_identity_verified=False, commercial_use_authorized=False,
        cohort_scope=ex["scope"], asset_precheck=manifest.get("asset_precheck"))
    cap.verify_archived_group(contents["raw"], contents["normalized"], receipt)
    require(all(utc(spec["window_start"]) <= utc(row["collected_at_utc"]) <= utc(spec["window_end"])
                for row in receipt["asset_precheck"]), "EXTERNAL_ORPHAN_CLOCK")
    examined, completed, held, parent = cap.resume_state(drive, folder, args.resume_file_id, args.resume_sha256,
        ex["scope"]["input_sha256"], auth["start"], auth["end"], scope=ex["scope"])
    require(examined == names[:160] and parent["sha256"] == spec["checkpoint_sha256"], "EXTERNAL_ORPHAN_PARENT")
    materialization = None
    if kinds is not None:
        created = False
        if norm_item is None:
            class DerivationDrive:
                def __getattr__(self, name):
                    return getattr(drive, name)
                def write(self, *a, **kw):
                    nonlocal created
                    created = True
                    return drive.write(*a, **kw)  # One CREATE only; an unknown result is terminal.
            refs["normalized"] = cap.persist_object(DerivationDrive(), folder, canonical, ".jsonl.gz")
            indexed = lookup_orphan_normalized(drive, folder, refs["normalized"]["sha256"]+".jsonl.gz")
            require(len(indexed) == 1 and indexed[0]["id"] == refs["normalized"]["file_id"],
                    "EXTERNAL_ORPHAN_NORMALIZED_LOOKUP")
            norm_item = indexed[0]
            actual_ref, actual = read_orphan_item(drive, folder, norm_item)
            require(actual_ref == refs["normalized"] and actual == canonical, "EXTERNAL_MATERIAL_READBACK")
        materialization = dict(capture_failed_run_id=spec["run_id"], rows_sha256=digest(row_bytes),
            codec="GZIP_FILENAME_EMPTY_MTIME0_LEVEL9" if created else "EXISTING_GZIP_VERIFIED",
            mode="DERIVED_NEW" if created else "EXISTING_VERIFIED", created_at_utc=norm_item["createdTime"],
            lookup_observed_at_utc=utc().isoformat(), inventory_sha256=digest(encoded(meter.identity["orphan_inventory"])),
            original_create_outcome="UNKNOWN")
        receipt["normalized_object"] = refs["normalized"]
    # All raw semantics and the entire old checkpoint were verified before any
    # new storage. No original ZIP upload or provider request occurs here.
    reuse = dict(failed_run_id=(MATERIALIZATION_RECOVERY if kinds is not None else spec)["run_id"], capture_source_sha=spec["master"],
        derivation_source_sha=auth["expected_master"], raw_sha256=refs["raw"]["sha256"],
        normalized_sha256=refs["normalized"]["sha256"], external_proof_sha256=meter.identity["external_proof_sha256"],
        derivation_run_id=meter.identity["run_id"], derivation_auth_sha256=meter.identity["auth_sha256"],
        parent_checkpoint_sha256=spec["checkpoint_sha256"],
        derived_at_utc=utc().isoformat(), failed_run_observation_window=[spec["window_start"],spec["window_end"]])
    if materialization is not None:
        reuse["materialization"] = materialization
    verify_drive_reuse(reuse, meter.identity)
    meter.identity["drive_orphan_reuse"] = reuse
    meter.save()
    receipt["recovered_from"] = reuse
    rec = cap.persist_object(drive, folder, encoded(receipt), ".json")
    state = dict(schema=cap.SCHEMA, state="PRIVATE_RESEARCH_ONLY", source=cap.SOURCE,
        seed_sha256=ex["scope"]["input_sha256"], source_sha=spec["master"],
        start=auth["start"], end=auth["end"], asof=cap.mapping_asof(auth["end"]),
        examined=examined+group, completed=completed+group, held=held,
        last_status="VERIFIED_RAW_SPLIT", last_objects=[refs["raw"], refs["normalized"], rec],
        previous_checkpoint=parent, last_collected=receipt["collected"], last_no_bars=receipt["no_bars"], last_held=[],
        historical_identity_verified=False, pit_verified=False, source_admission=False,
        commercial_use_authorized=False, cohort_scope=ex["scope"])
    state["recovered_from"] = reuse
    checkpoint = cap.persist_object(drive, folder, encoded(state), ".json")
    verify_new_group(drive, folder, state, checkpoint, meter, reused_source=True)
    return checkpoint


def external_worker(args, control, journal):
    from tools import alpaca_sip_private_backfill_v1 as cap
    from tools.twelve_private_capture import OwnerDrive
    require(set(control) == {"authorization", "nonce", "recovery_run", "preflight_only", "external_binding"}
            and control["preflight_only"] is False, "EXTERNAL_CONTROL")
    auth = control["authorization"]
    specs = external_recoveries(auth)
    drive_recovery = "drive_recovery" in auth["external_cohort"]
    h = validate_authorization(auth)
    verify_worker_source(auth)
    nonce, recovered = control["nonce"], control["recovery_run"]
    require(isinstance(nonce, str) and re.fullmatch(PREFIX+r"[0-9a-f]{24}", nonce)
            and nonce == os.getenv("INPUT_CAMPAIGN_NONCE")
            and (recovered is None or "named_recovery" in auth["external_cohort"]
                 and type(recovered) is int and recovered == specs[-1]["run_id"]), "EXTERNAL_RECOVERY_NOT_AUTHORIZED")
    run_id = int(os.environ["GITHUB_RUN_ID"])
    observed = external_history(auth, run_id, nonce, recovered)
    proof, ex = observed["external_proof"], auth["external_cohort"]
    scope = ex["scope"]
    names = cap.external_cohort(ex["input_csv"].encode())
    n = observed["examined"]
    if recovered is not None:
        require(n == specs[-1]["examined"]
                and observed["parent_sha"] == specs[-1]["checkpoint_sha256"]
                and args.max_new_symbols == specs[-1]["batch"], "EXTERNAL_RECOVERY_PARENT")
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
    original_batch = args.max_new_symbols
    args = argparse.Namespace(**vars(args))
    def factory(root, temp):
        drive = OwnerDrive(root, temp, meter=meter)
        require((auth["owner_permission_id"] is None or drive.owner == auth["owner_permission_id"])
                and digest(drive.owner.encode()) == CONTINUATION["bindings"]["owner_sha256"]
                and drive.free >= 2*1024**3,
                "CAMPAIGN_OWNER_OR_SPACE")
        meter.identity["free_bytes_at_start"] = drive.free
        meter.save()
        if drive_recovery:
            ref = recover_drive_orphan(drive, args, auth, meter,
                **({"materialize":True} if "materialization_recovery" in ex else {}))
            args.resume_file_id, args.resume_sha256 = ref["file_id"], ref["sha256"]
            args.max_new_symbols = original_batch-4
        return drive
    try:
        with meter.process_deadline():
            result = cap._collect(args, drive_factory=factory, get=meter.perform,
                on_group=lambda drive,state,ref: verify_new_group(drive, args.private_data_folder_id, state, ref, meter),
                expected_examined=n+(4 if drive_recovery else 0), external=dict(input_csv=ex["input_csv"], scope=scope))
        require(meter.examined == n+original_batch and meter.checkpoint_sha == result["checkpoint"]["sha256"],
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


def external_family_registry(budget_path, auth, state_path, *, first_proof=None):
    """One deterministic shared reservation authority, outside the frozen17."""
    budget_path, state_path = Path(budget_path).resolve(), Path(state_path).resolve()
    require(state_path == budget_path.parent / (
        "external-cohort-"+auth["external_cohort"]["scope"]["namespace"]), "EXTERNAL_NAMESPACE")
    first_auth = external_variants((auth["external_cohort"]["prior_epochs"] or [auth])[0])[0]
    first_hash = validate_authorization(first_auth)
    proof = external_proof(first_auth) if first_proof is None else first_proof
    genesis = digest(encoded(dict(schema="a1-external-budget-genesis-v1", task_key=TASK,
        prior_auth_sha256=CONTINUATION["auth"], prior_event_sha256=CONTINUATION["event"],
        first=CONTINUATION["first"], limits=CONTINUED_LIMITS, active_seconds_limit=43200, dispatch_limit=40)))
    directory = budget_path.parent / ("external-budget-"+CONTINUATION["auth"][:16])
    if any("drive_recovery" in a["external_cohort"] for a in auth["external_cohort"]["prior_epochs"]+[auth]):
        require(directory.is_dir() and not directory.is_symlink()
                and (directory/f"{DRIVE_RECOVERY['family_events']:06d}.json").is_file()
                and digest(bounded_bytes(directory/f"{DRIVE_RECOVERY['family_events']:06d}.json"))
                    == DRIVE_RECOVERY["family_event_sha256"], "EXTERNAL_DRIVE_FAMILY_PREFIX")
    if any("materialization_recovery" in a["external_cohort"] for a in auth["external_cohort"]["prior_epochs"]+[auth]):
        require(directory.is_dir() and not directory.is_symlink()
                and (directory/f"{MATERIALIZATION_RECOVERY['family_events']:06d}.json").is_file()
                and digest(bounded_bytes(directory/f"{MATERIALIZATION_RECOVERY['family_events']:06d}.json"))
                    == MATERIALIZATION_RECOVERY["family_event_sha256"], "EXTERNAL_MATERIAL_FAMILY_PREFIX")
    if any("named_recovery" in a["external_cohort"] for a in auth["external_cohort"]["prior_epochs"]+[auth]):
        require(directory.is_dir() and not directory.is_symlink()
                and (directory/f"{NAMED_RECOVERY['events']:06d}.json").is_file()
                and digest(bounded_bytes(directory/f"{NAMED_RECOVERY['events']:06d}.json"))
                    == NAMED_RECOVERY["family_event_sha256"], "EXTERNAL_RECOVERY_FAMILY_PREFIX")
    existed = directory.exists()
    registry = WorkJournal(directory, genesis)
    try:
        binding = dict(genesis_sha256=genesis, capture_auth_sha256=first_hash,
                       scope=first_auth["external_cohort"]["scope"],
                       budget_state_root=os.path.normcase(str(budget_path)),
                       first_cohort_state_root=os.path.normcase(str(budget_path.parent / (
                           "external-cohort-"+first_auth["external_cohort"]["scope"]["namespace"]))), **proof)
        if registry.entries:
            first = registry.entries[0]
            require(first.get("kind") == "EXTERNAL_FAMILY_BOUND"
                    and {k:first.get(k) for k in binding} == binding
                    and utc(proof["proof_updated_utc"]) <= utc(first.get("recorded_utc"))
                        < utc(proof["expires_at_utc"]), "EXTERNAL_FAMILY_DRIFT")
        else:
            # Absence of local registration is not evidence of zero POSTs.
            require(not existed and not auth["external_cohort"]["prior_epochs"]
                    and not list(budget_path.parent.glob("external-cohort-*"))
                    and [r["id"] for r in campaign_runs(auth["workflow_run_floor"])] == CONTINUATION["runs"],
                    "EXTERNAL_FAMILY_MISSING")
            registry.append("EXTERNAL_FAMILY_BOUND", **binding)
        return registry
    except BaseException:
        registry.close()
        raise


def verify_external_prior_journals(registry, auth, observed):
    """Read existing prior epochs only; canonical meters do not replace their journals."""
    from tools.alpaca_sip_private_backfill_v1 import external_cohort
    for previous in auth["external_cohort"]["prior_epochs"]:
        h, scope = validate_authorization(previous), previous["external_cohort"]["scope"]
        directory = registry.directory.parent / ("external-cohort-"+scope["namespace"])
        require(directory.is_dir() and not directory.is_symlink()
                and (directory/"000001.json").is_file(), "EXTERNAL_PRIOR_JOURNAL_MISSING")
        proof = observed.get("epoch_proofs", {}).get(h)
        require(isinstance(proof, dict), "EXTERNAL_PRIOR_JOURNAL_DRIFT")
        # This final reservation guard must remain local after canonical history
        # was fetched. A fresh remote proof read here would reopen a run race.
        prior = external_journal(directory, previous, proof, epoch_proofs=observed.get("epoch_proofs"))
        try:
            versions = {validate_authorization(a) for a in external_variants(previous)}
            known = [(r,v) for r,v in zip(observed["runs"], observed["receipts"]) if v["auth_sha256"] in versions]
            prior.reconcile([r for r,v in known])
            first_proof = observed.get("epoch_proofs", {}).get(validate_authorization(external_variants(previous)[0]))
            require(isinstance(first_proof, dict), "EXTERNAL_PRIOR_JOURNAL_DRIFT")
            binding = dict(scope=scope, genesis_sha256=external_genesis(scope), **first_proof)
            first = prior.entries[0]
            require(first.get("kind") == "EXTERNAL_COHORT_BOUND"
                    and {k:first.get(k) for k in binding} == binding
                    and utc(first_proof["proof_updated_utc"]) <= utc(first.get("recorded_utc"))
                        < utc(first_proof["expires_at_utc"]), "EXTERNAL_PRIOR_JOURNAL_DRIFT")
            cursor = 1
            for run, value in known:
                if prior.revision and cursor == NAMED_RECOVERY["events"]:
                    require(cursor < len(prior.entries) and prior.entries[cursor]["kind"] == "EXTERNAL_RECOVERY_BOUND",
                            "EXTERNAL_PRIOR_JOURNAL_DRIFT")
                    cursor += 1
                if prior.drive_revision and cursor == DRIVE_RECOVERY["events"]:
                    require(cursor < len(prior.entries) and prior.entries[cursor]["kind"] == "EXTERNAL_DRIVE_RECOVERY_BOUND",
                            "EXTERNAL_PRIOR_JOURNAL_DRIFT")
                    cursor += 1
                if prior.material_revision and cursor == MATERIALIZATION_RECOVERY["events"]:
                    require(cursor < len(prior.entries) and prior.entries[cursor]["kind"] == "EXTERNAL_MATERIALIZATION_BOUND",
                            "EXTERNAL_PRIOR_JOURNAL_DRIFT")
                    cursor += 1
                require(cursor < len(prior.entries), "EXTERNAL_PRIOR_JOURNAL_DRIFT")
                reserved = prior.entries[cursor]; cursor += 1
                require(reserved.get("kind") == "RESERVED" and reserved.get("nonce") == value["nonce"]
                        and reserved.get("remaining") == value["allowance"]
                        and reserved.get("parent_checkpoint_sha256") == value["parent_checkpoint_sha256"]
                        and reserved.get("external_proof_sha256") == observed["epoch_proofs"][value["auth_sha256"]]["proof_sha256"],
                        "EXTERNAL_PRIOR_JOURNAL_DRIFT")
                if cursor < len(prior.entries) and prior.entries[cursor].get("kind") == "RUN_ASSIGNED":
                    assigned = prior.entries[cursor]; cursor += 1
                    require(assigned.get("nonce") == value["nonce"] and assigned.get("run_id") == run["id"],
                            "EXTERNAL_PRIOR_JOURNAL_DRIFT")
                require(cursor < len(prior.entries), "EXTERNAL_PRIOR_JOURNAL_DRIFT")
                settled = prior.entries[cursor]; cursor += 1
                require(settled.get("kind") == "SETTLED" and settled.get("nonce") == value["nonce"]
                        and settled.get("run_id") == run["id"] and settled.get("receipt") == value
                        and settled.get("receipt_sha256") == digest(encoded(value))
                        and settled.get("usage") == value["usage"]
                        and settled.get("checkpoint", {}).get("sha256") == value["checkpoint_sha256"]
                        and settled.get("examined_after") == value["examined_after"], "EXTERNAL_PRIOR_JOURNAL_DRIFT")
            require(cursor == len(prior.entries) and known and known[-1][1]["status"] == "COMPLETE"
                    and known[-1][1]["examined_after"] == len(external_cohort(
                        previous["external_cohort"]["input_csv"].encode())), "EXTERNAL_PRIOR_JOURNAL_DRIFT")
        finally:
            prior.close()


def reconcile_external_family(registry, journal, auth, observed):
    """No later namespace can ignore an unobserved or partially logged POST."""
    h, scope = validate_authorization(auth), auth["external_cohort"]["scope"]
    versions = {validate_authorization(a) for a in external_variants(auth)}
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
    own_global = {nonce for nonce,e in reserved.items() if e["capture_auth_sha256"] in versions}
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
                registry.append("SETTLED", nonce=nonce, run_id=run["id"], capture_auth_sha256=value["auth_sha256"], scope=scope,
                    receipt_sha256=digest(encoded(value)), usage=value["usage"], checkpoint_sha256=value["checkpoint_sha256"])
                pending = None
    verify_external_prior_journals(registry, auth, observed)
    require(pending is None or reserved[pending]["capture_auth_sha256"] == h, "EXTERNAL_FAMILY_PENDING")
    return pending


def external_host(auth, state_dir, cohort_input, budget_state_dir, predispatch_recovery, recovery_run, max_batches):
    from tools.alpaca_sip_private_backfill_v1 import external_cohort
    ex, h = auth["external_cohort"], validate_authorization(auth)
    specs = external_recoveries(auth)
    require(recovery_run is None or "named_recovery" in ex and type(recovery_run) is int
            and recovery_run == specs[-1]["run_id"], "EXTERNAL_RECOVERY_NOT_AUTHORIZED")
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
        frozen = external_proof(auth)
        family = external_family_registry(budget_path, auth, state_path,
            first_proof=frozen if not ex["prior_epochs"] and "named_recovery" not in ex else None)
        journal = external_journal(state_path, auth, frozen)
        initial_proof = external_proof(external_variants(auth)[0]) if "named_recovery" in ex else frozen
        binding = dict(scope=ex["scope"], genesis_sha256=external_genesis(ex["scope"]), **initial_proof)
        if journal.entries:
            first = journal.entries[0]
            require(first.get("kind") == "EXTERNAL_COHORT_BOUND"
                    and {k: first.get(k) for k in binding} == binding
                    and utc(initial_proof["proof_updated_utc"]) <= utc(first.get("recorded_utc"))
                        < utc(initial_proof["expires_at_utc"]), "EXTERNAL_PROOF_DRIFT")
        else:
            # No provider/Drive I/O or dispatch; binding is this new namespace only.
            journal.append("EXTERNAL_COHORT_BOUND", **binding)
        settled_before = sum(e["kind"] == "SETTLED" and e.get("capture_auth_sha256") == h for e in family.entries)
        if journal.revision and settled_before == 0:
            # Importing or repairing the first recovery still consumes its one
            # allowed batch. A crash must not turn that closure into a free slot.
            require(max_batches == 1, "EXTERNAL_RECOVERY_BOUNDARY")
        active_revision, active_spec, active_kind = active_external_revision(journal)
        while True:
            observed = external_history(auth, recovery_run=recovery_run, enforce_expiry=False, allow_stopped=True)
            last_observed = observed
            require(observed["external_proof"] == frozen, "EXTERNAL_PROOF_DRIFT")
            global_journal.reconcile(observed["runs"][:5])
            journal.reconcile(observed["cohort_runs"])
            reconcile_external_family(family, journal, auth, observed)
            if active_revision and len(journal.entries) == active_spec["events"]:
                require(observed.get("recovery_required") == active_spec["run_id"]
                        and recovery_run == active_spec["run_id"] and max_batches == 1,
                        "EXTERNAL_RECOVERY_BOUNDARY")
                journal.append(active_kind, **active_revision)
            if journal.entries[-1]["kind"] in ("RESERVED", "RUN_ASSIGNED"):
                matches = [(r,v) for r,v in zip(observed["cohort_runs"], observed["cohort_receipts"])
                           if v["nonce"] == journal.entries[-1]["nonce"]]
                require(len(matches) == 1, "CAMPAIGN_ACTIVE_RESERVATION")
                run, value = matches[0]
                require(external_proof(auth) == frozen, "EXTERNAL_PROOF_DRIFT")
                settle_run(journal, auth, run, value)
                reconcile_external_family(family, journal, auth, observed)
            # Count newly closed shared settlements, including an imported run
            # or interrupted cohort-to-family settlement; never count a watch twice.
            completed = sum(e["kind"] == "SETTLED" and e.get("capture_auth_sha256") == h
                            for e in family.entries) - settled_before
            atomic_json(journal.directory/"progress", external_progress(auth, observed, "VERIFIED"))
            latest = observed["cohort_receipts"][-1] if observed["cohort_receipts"] else None
            if latest is not None and latest["status"] == "BLOCKED" and not named_failed_receipt(
                    observed["cohort_runs"][-1], latest, auth):
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
                    and journal.entries[-1]["kind"] in ("EXTERNAL_COHORT_BOUND", "EXTERNAL_RECOVERY_BOUND",
                        "EXTERNAL_DRIVE_RECOVERY_BOUND", "EXTERNAL_MATERIALIZATION_BOUND", "SETTLED"), "CAMPAIGN_LOCAL_PARENT")
            if observed.get("recovery_required") is not None:
                require(max_batches == 1 and recovery_run == active_spec["run_id"]
                        and observed["examined"] == active_spec["examined"]
                        and external_batch(observed["examined"], count) == active_spec.get("batch", 8),
                        "EXTERNAL_RECOVERY_BOUNDARY")
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


NATIVE_READ_TASK = "R1000-SOURCE39085031884-NATIVE-METERED-READ-PATH-20261018"
NATIVE_READ_CP = "efcea3356688118392fa71612ee2702c4b9ea436ad88bdfdab917ef60e373cfd"
NATIVE_READ_AUTH = "141bcf8526425244821b2e940d01fced58ff3e64e9237dffd69e9d558131c7cb"
NATIVE_READ_METER = "231d256890c209ef5dace024a25cfafc5d6a8714abded3a8cca76f2752818814"
NATIVE_READ_CP_ID = "1mkt2HTzWWObV_60BSv1Iqdj9myQ4BlQZ"
NATIVE_READ_WINDOW = ("2026-10-18T01:07:04.874Z", "2026-10-18T01:07:37Z")
# A suballocation of the existing remaining caps, never a new campaign budget.
NATIVE_READ_ALLOWANCE = dict(provider_gets=0, drive_requests=16, drive_bytes=16_000_000, storage_bytes=0)


def native_read_control(value):
    require(isinstance(value, dict) and set(value) == {"schema", "task_key", "expected_master", "nonce",
            "authorization", "pending_external_read_accounting"}
            and value["schema"] == "a1-native-drive-read-39085031884-v1"
            and value["task_key"] == NATIVE_READ_TASK, "NATIVE_READ_CONTROL")
    auth = value["authorization"]
    require(validate_authorization(auth) == NATIVE_READ_AUTH, "NATIVE_READ_AUTH")
    require(isinstance(value["expected_master"], str) and re.fullmatch(r"[0-9a-f]{40}", value["expected_master"])
            and isinstance(value["nonce"], str) and re.fullmatch(PREFIX+r"[0-9a-f]{24}", value["nonce"]),
            "NATIVE_READ_SOURCE_NONCE")
    # Connector calls are NOT wire bytes. Unknown costs remain pending and
    # cannot silently become zero or be omitted from the shared remaining cap.
    pending = value["pending_external_read_accounting"]
    require(isinstance(pending, dict) and set(pending) == {"basis", "receipt_sha256", "usage", "reference"}
            and pending["basis"] == "VERIFIED_TRANSPORT_ACCOUNTING"
            and isinstance(pending["receipt_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", pending["receipt_sha256"])
            and isinstance(pending["reference"], str) and re.fullmatch(
                r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",pending["reference"])
            and isinstance(pending["usage"], dict) and set(pending["usage"]) == set(LIMITS),
            "NATIVE_READ_PENDING_COST_UNSETTLED")
    for key in LIMITS:
        integer(pending["usage"][key], CONTINUED_LIMITS[key])
    require(pending["usage"]["provider_gets"] == pending["usage"]["storage_bytes"] == 0
            and pending["usage"]["drive_requests"] > 0 and pending["usage"]["drive_bytes"] > 0,
            "NATIVE_READ_PENDING_COST_UNSETTLED")
    require(utc() < utc(CONTINUATION["first"])+timedelta(hours=48), "CAMPAIGN_EXPIRED")
    return auth


def native_read_pending_proof(pending):
    """Counter input is not evidence: require an immutable OWNER accounting record."""
    comment_id = int(pending["reference"].rsplit("-",1)[1])
    comment = gh_json(f"repos/{REPO}/issues/comments/{comment_id}")
    require(comment.get("id") == comment_id and comment.get("author_association") == "OWNER"
            and comment.get("issue_url") == f"https://api.github.com/repos/{REPO}/issues/448"
            and comment.get("user",{}).get("type") == "User", "NATIVE_READ_ACCOUNTING_OWNER")
    tag = "A1_SIP_NATIVE_READ_ACCOUNTING "
    lines = [line[len(tag):] for line in comment.get("body","").splitlines() if line.startswith(tag)]
    expected = dict(schema="a1-native-read-pending-accounting-v1",failed_run_id=39085031884,
        failed_meter_sha256=NATIVE_READ_METER,prior_auth_sha256=NATIVE_READ_AUTH,
        pending_observation_sha256="c0c9de188852ac7cea996ab506f27e514cfe976f4c467ec4e782303ed5ca7e2f",
        basis=pending["basis"],receipt_sha256=pending["receipt_sha256"],usage=pending["usage"])
    require(len(lines) == 1 and len(lines[0]) <= 2048 and encoded(decode(lines[0])) == encoded(expected)
            and utc("2026-10-18T01:07:37Z") <= utc(comment.get("created_at")) <= utc(comment.get("updated_at")) <= utc(),
            "NATIVE_READ_ACCOUNTING_PROOF")
    return digest(encoded(dict(id=comment_id,updated_at=comment["updated_at"],body=comment["body"])))


def native_read_prefix(runs, current):
    require(os.getenv("INPUT_NATIVE_READ_ONLY") == "true"
            and current.get("id") == int(os.environ.get("GITHUB_RUN_ID", "0"))
            and current.get("run_attempt") == 1 and type(current.get("run_attempt")) is int
            and current.get("head_sha") == os.getenv("GITHUB_SHA")
            and current.get("head_branch") == "master" and current.get("event") == "workflow_dispatch"
            and current.get("display_title") == "a1-sip "+os.getenv("INPUT_CAMPAIGN_NONCE", "")+" native-read39085031884"
            and len(runs) == 18 and runs[-1] == current and runs[-2].get("id") == 39085031884,
            "NATIVE_READ_SINGLE_USE")
    require(all(r.get("display_title") != "a1-sip "+os.getenv("INPUT_CAMPAIGN_NONCE", "") for r in runs[:-1]),
            "NATIVE_READ_NONCE_REUSE")
    # This one marked in-progress read is removed ONLY for its own read-only
    # precheck. Default capture still sees it and fails closed until a future
    # explicit recovery accounts its separate meter/dispatch/job duration.
    return runs[:-1]


def native_read_budget(observed, pending):
    require(len(observed["runs"]) == 17 and observed["runs"][-1]["id"] == 39085031884
            and observed["examined"] == 76 and observed["parent_sha"] == NATIVE_READ_CP
            and digest(encoded(observed["receipts"][-1])) == NATIVE_READ_METER
            and observed["first"] == utc(CONTINUATION["first"])
            and observed["used"] == dict(provider_gets=542,drive_requests=5269,drive_bytes=842810550,storage_bytes=79426031)
            and observed["active_seconds"] == 3769, "NATIVE_READ_CAPTURE_PREFIX")
    require(all(observed["used"][k]+pending["usage"][k]+NATIVE_READ_ALLOWANCE[k] <= CONTINUED_LIMITS[k] for k in LIMITS)
            and len(observed["runs"])+1 <= 40 and observed["active_seconds"]+900 <= 43200,
            "NATIVE_READ_SHARED_BUDGET")


def native_read_source(expected_master):
    branch = gh_json(f"repos/{REPO}/branches/master")
    require(branch.get("protected") is True and branch.get("commit", {}).get("sha") == expected_master,
            "CAMPAIGN_MASTER_DRIFT")
    pins = {}
    for path in PINS:
        remote = gh_json(f"repos/{REPO}/contents/{path}?ref={expected_master}")
        local = digest(bounded_bytes(ROOT/path,262144).replace(b"\r\n",b"\n"))
        require(remote.get("encoding") == "base64" and digest(base64.b64decode(remote["content"])) == local,
                "NATIVE_READ_CODE_DRIFT")
        pins[path] = local
    return pins


class NativeReadMeter(RuntimeMeter):
    """Existing conservative transport with no provider or Drive write door."""
    def __init__(self, *args, root_id, folder_id, **kwargs):
        self.native_ids = {root_id, folder_id, NATIVE_READ_CP_ID}
        self.native_media_sizes = {NATIVE_READ_CP_ID:2304}
        self.native_queries = {
            "name = '"+NATIVE_READ_CP+".json' and '"+folder_id+"' in parents and trashed = false": "2",
            "'"+folder_id+"' in parents and trashed = false and createdTime >= '"+NATIVE_READ_WINDOW[0]
            +"' and createdTime <= '"+NATIVE_READ_WINDOW[1]+"'": "8"}
        self.native_result = {}
        super().__init__(*args, **kwargs)

    def save(self):
        atomic_json(self.journal, dict(schema="a1-native-drive-read-meter-v1", **self.identity,
            usage=self.used, allowance=self.allowance, status=self.status, reason=self.reason,
            finalized=self.finalized, transfer_definition=METRIC,
            observed_google_body_bytes=self.observed_google_body_bytes,
            result=self.native_result, capture_allowed=False, source_admission=False,
            pit_verified=False, economic_authority=False,
            **({"last_transport_failure":self.last_transport_failure} if self.last_transport_failure else {})))

    def reserve_storage(self, size):
        raise Refused("NATIVE_READ_WRITE_BLOCKED")

    def perform(self, url, *, method="GET", body=None, **kwargs):
        from urllib.parse import parse_qs, urlsplit
        endpoint = urlsplit(url)
        refresh = url == "https://oauth2.googleapis.com/token" and method == "POST"
        allowed = False
        if endpoint.scheme == "https" and endpoint.netloc == "www.googleapis.com" and method == "GET" and body is None:
            if endpoint.path == "/drive/v3/about":
                allowed = parse_qs(endpoint.query) == {"fields":["user(permissionId),storageQuota"]}
            elif endpoint.path == "/drive/v3/files":
                query = parse_qs(endpoint.query)
                allowed = (set(query) == {"q", "pageSize", "fields"} and len(query["q"]) == 1
                    and self.native_queries.get(query["q"][0]) == query["pageSize"][0]
                    and query["fields"] == ["nextPageToken,files(id,name,size,parents,createdTime)"])
            elif endpoint.path.startswith("/drive/v3/files/"):
                file_id = endpoint.path.removeprefix("/drive/v3/files/")
                allowed = file_id in self.native_ids
                if parse_qs(endpoint.query) == {"alt":["media"]}:
                    allowed = file_id in self.native_media_sizes
                    if allowed:
                        kwargs["limit"] = min(kwargs.get("limit",16_000_000),self.native_media_sizes[file_id])
        require(refresh or allowed, "NATIVE_READ_ENDPOINT")
        return super().perform(url, method=method, body=body, **kwargs)


def native_read_objects(drive, auth, meter):
    from tools import alpaca_sip_private_backfill_v1 as cap
    folder = auth["private_data_folder_id"]
    require(digest(drive.owner.encode()) == CONTINUATION["bindings"]["owner_sha256"], "NATIVE_READ_OWNER")
    drive.check(folder, auth["private_root_folder_id"])
    control = cap._private_object(drive, folder,
        dict(file_id=NATIVE_READ_CP_ID, sha256=NATIVE_READ_CP, bytes=2304), 2304)
    cp = decode(control)
    names = cap.external_cohort(auth["external_cohort"]["input_csv"].encode())
    require(cp.get("examined") == names[:76] and cp.get("cohort_scope") == auth["external_cohort"]["scope"],
            "NATIVE_READ_CP_CONTENT")
    def listed(query):
        value = credential_safe_json(drive.request("https://www.googleapis.com/drive/v3/files?"+urlencode(dict(
            q=query, pageSize=meter.native_queries[query], fields="nextPageToken,files(id,name,size,parents,createdTime)"))),
            (drive.token,))
        require(isinstance(value, dict) and value.get("nextPageToken") is None
                and isinstance(value.get("files"), list), "NATIVE_READ_LIST_INCOMPLETE")
        return value["files"]
    positive, window = meter.native_queries
    matches = listed(positive)
    require(len(matches) == 1 and matches[0].get("id") == NATIVE_READ_CP_ID
            and matches[0].get("name") == NATIVE_READ_CP+".json"
            and matches[0].get("parents") == [folder] and matches[0].get("size") == "2304"
            and matches[0].get("createdTime") == NATIVE_READ_WINDOW[0], "NATIVE_READ_POSITIVE_CONTROL")
    items = listed(window)
    require(len(items) <= 8, "NATIVE_READ_LIST_INCOMPLETE")
    seen, candidates = set(), []
    for item in items:
        validate_orphan_item(item, folder)
        require(item["id"] not in seen and utc(NATIVE_READ_WINDOW[0]) <= utc(item["createdTime"]) <= utc(NATIVE_READ_WINDOW[1]),
                "NATIVE_READ_LIST_IDENTITY")
        seen.add(item["id"])
        if item["name"].endswith(".zip") and item["size"] == "302101":
            candidates.append(item)
    require(len(candidates) <= 1, "NATIVE_READ_DUPLICATE")
    result = dict(positive_control_verified=True, files_count=len(items), candidate_count=len(candidates),
                  owner_sha256=digest(drive.owner.encode()), absence_proven=False, failed_request_body_hash_known=False)
    if candidates:
        item = candidates[0]
        meter.native_ids.add(item["id"])
        meter.native_media_sizes[item["id"]] = 302101
        ref, raw = read_orphan_item(drive, folder, item)
        result.update(candidate_sha256=ref["sha256"], candidate_bytes=len(raw))
    meter.native_result = result
    meter.save()
    return result


def native_read_worker(control_path, state_dir):
    """Isolated reviewed-master diagnostic. Never invokes a collector/host."""
    from tools.twelve_private_capture import OwnerDrive
    control = bounded_json(control_path, 16384)
    auth = native_read_control(control)  # Pending unknown accounting fails before any credentials.
    require(os.getenv("GITHUB_REPOSITORY") == REPO and os.getenv("GITHUB_REF") == "refs/heads/master"
            and os.getenv("INPUT_NATIVE_READ_ONLY") == "true"
            and os.getenv("A1_PRIVATE_RESEARCH_AUTHORIZED") == "true"
            and os.getenv("ALPACA_NONCOMMERCIAL_ACKNOWLEDGED") == "true"
            and os.getenv("INPUT_CAMPAIGN_NONCE") == control["nonce"]
            and os.getenv("GITHUB_SHA") == control["expected_master"], "NATIVE_READ_CONTEXT")
    source_pins = native_read_source(control["expected_master"])
    pending_proof_sha = native_read_pending_proof(control["pending_external_read_accounting"])
    current = gh_json(f"repos/{REPO}/actions/runs/{int(os.environ['GITHUB_RUN_ID'])}")
    observed = external_history(auth, allow_stopped=True, native_read_run=current)
    pending = control["pending_external_read_accounting"]
    native_read_budget(observed,pending)
    jobs = gh_json(f"repos/{REPO}/actions/runs/{current['id']}/jobs?per_page=100")
    require(jobs.get("total_count") == len(jobs.get("jobs", [])) == 2, "NATIVE_READ_JOB")
    active = [j for j in jobs["jobs"] if j.get("name") == "reconcile" and j.get("status") == "in_progress"]
    require(len(active) == 1, "NATIVE_READ_JOB")
    deadline = min(utc(active[0]["started_at"])+timedelta(seconds=300), observed["first"]+timedelta(hours=48))
    directory = Path(state_dir)
    directory.mkdir(exist_ok=False)
    identity = dict(task_key=NATIVE_READ_TASK,run_id=current["id"],run_attempt=1,nonce=control["nonce"],
        source_sha=control["expected_master"],source_pins=source_pins,
        parent_checkpoint_sha256=NATIVE_READ_CP,examined_before=76,failed_run_id=39085031884,
        failed_meter_sha256=NATIVE_READ_METER,pending_external_read_accounting=pending,
        pending_external_read_proof_sha256=pending_proof_sha,
        capture_usage_before=observed["used"],active_seconds_reservation=900,dispatch_reservation=1,
        subsequent_capture_requires_separate_native_meter_settlement=True)
    meter = NativeReadMeter(NATIVE_READ_ALLOWANCE,directory/"native_read_meter.json",deadline.isoformat(),identity,
        limits=CONTINUED_LIMITS,root_id=auth["private_root_folder_id"],folder_id=auth["private_data_folder_id"])
    try:
        with meter.process_deadline(), tempfile.TemporaryDirectory(prefix="a1-native-read-") as temp:
            drive = OwnerDrive(auth["private_root_folder_id"],temp,meter=meter)
            native_read_objects(drive,auth,meter)
        meter.finish("COMPLETE")
    except Refused as exc:
        meter.finish("BLOCKED",str(exc))
        raise
    except Exception:
        meter.finish("BLOCKED","NATIVE_READ_INTERNAL")
        raise Refused("NATIVE_READ_INTERNAL") from None
    print(json.dumps(dict(status="NATIVE_READ_COMPLETE",capture_allowed=False,source_admission=False)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--authorization")
    mode.add_argument("--native-read-control", help="Exact39085031884 read-only control; no collector execution")
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
        if args.native_read_control:
            require(not any((args.recovery_run,args.account_permission_reference,args.predispatch_recovery,
                args.continuation_receipt,args.cohort_input,args.budget_state_dir,args.max_batches)), "NATIVE_READ_MODE")
            native_read_worker(args.native_read_control,args.state_dir)
            return 0
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
