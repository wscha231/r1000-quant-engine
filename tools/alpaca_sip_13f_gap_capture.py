"""One finite historical-gap request through the existing private SIP worker."""

import csv
import gzip
import io
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from tools import alpaca_sip_private_backfill_v1 as cap
from tools.twelve_private_capture import OwnerDrive, Refused, decode, digest, encoded, require


PROFILE = "owner-13f154-gap-20261126-v1"
TASK = "R1000-13F-154-SOURCE-CAPTURE-20261126"
PLAN_SHA = "191442b6aaaea38a8c34d116ac2ebd6e21f22a4e11687e4ed5be9dfd3bd8525e"
SCOPE_SHA = "480ce70fb20a5f165e18072758c73aa38b3e553ab9d2733a7024ecd8002b2c80"
RIGHTS_SHA = "4d2d6d300665ab39da1e02b056936e66b2272d102138614f261fdd2dcde6f3ac"
MODULE = "tools/alpaca_sip_13f_gap_capture.py"
CALENDAR = "tools/run_daily_market_session_gate.py"
END = "2026-11-16"
START = "2026-08-07"
PAGE_LIMIT = 2
TAG = "A1_SIP_13F154_EXECUTION "
SOURCE_FIELDS = ("id", "run_number", "run_attempt", "head_sha", "head_branch", "event", "status",
                 "conclusion", "display_title", "created_at", "updated_at")
PLAN_FIELDS = ("plan_group", "start", "end_exclusive", "symbols", "sym_count", "requested_per_basis",
               "provider_feed", "currency", "bases", "execution_status")
AUTH_FIELDS = {"schema", "task_key", "allocation_profile", "allocation_reference", "expected_master", "code_pins",
               "deployment", "not_before_utc", "expires_at_utc", "wall_seconds", "limits", "opening",
               "private_root_folder_id", "private_data_folder_id", "evidence_folder_id", "owner_sha256",
               "plan_ref", "identity_ref", "rights_ref"}


@dataclass(frozen=True)
class Window:
    number: int
    start: str
    end: str
    symbols: tuple[str, ...]
    sessions: tuple[str, ...]


def valid_sha(value, size=64):
    return isinstance(value, str) and re.fullmatch(rf"[a-f0-9]{{{size}}}", value) is not None


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", value) is not None


def check_ref(ref, maximum):
    require(type(ref) is dict and set(ref) == {"file_id", "sha256", "bytes"}
            and valid_id(ref["file_id"]) and valid_sha(ref["sha256"])
            and type(ref["bytes"]) is int and 0 < ref["bytes"] <= maximum, "13F_GAP_PRIVATE_REF")


def control_digest(auth):
    return digest(encoded({k: v for k, v in auth.items() if k != "allocation_reference"}))


def nonce(c):
    return c.PREFIX + digest(f"{TASK}:{SCOPE_SHA}".encode())[:24]


def accounting_keys(c):
    return {*c.LIMITS, "active_seconds", "dispatches"}


def validate_authorization(c, auth):
    require(type(auth) is dict and set(auth) == AUTH_FIELDS and auth["allocation_profile"] == PROFILE
            and auth["schema"] == "a1-13f154-gap-authorization-v1" and auth["task_key"] == TASK,
            "13F_GAP_AUTHORIZATION")
    start, end = c.utc(auth["not_before_utc"]), c.utc(auth["expires_at_utc"])
    require(type(auth["wall_seconds"]) is int and 120 <= auth["wall_seconds"] <= 1800
            and timedelta(seconds=auth["wall_seconds"]) <= end - start <= timedelta(hours=24),
            "13F_GAP_OPERATING_WINDOW")
    deployment = auth["deployment"]
    require(valid_sha(auth["expected_master"], 40) and type(deployment) is dict
            and set(deployment) == {"pull_request", "reviewed_head"}
            and type(deployment["pull_request"]) is int and deployment["pull_request"] > 0
            and valid_sha(deployment["reviewed_head"], 40), "13F_GAP_DEPLOYMENT")
    pins = auth["code_pins"]
    require(type(pins) is dict and set(pins) == {*c.PINS, c.REVISION_MODULE, MODULE, CALENDAR}
            and all(valid_sha(s) for s in pins.values()), "13F_GAP_CODE_PINS")
    require(isinstance(auth["allocation_reference"], str) and re.fullmatch(
        r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[1-9][0-9]*",
        auth["allocation_reference"]), "13F_GAP_ALLOCATION_REFERENCE")
    folders = [auth[k] for k in ("private_root_folder_id", "private_data_folder_id", "evidence_folder_id")]
    require(all(valid_id(folder) for folder in folders) and len(set(folders)) == 3
            and auth["owner_sha256"] == c.CONTINUATION["bindings"]["owner_sha256"], "13F_GAP_PRIVATE_FOLDERS")
    for field in ("plan_ref", "identity_ref", "rights_ref"):
        check_ref(auth[field], 262144)
    require(auth["plan_ref"]["sha256"] == PLAN_SHA and auth["rights_ref"]["sha256"] == RIGHTS_SHA,
            "13F_GAP_INPUT_HASH")
    limits = auth["limits"]
    require(type(limits) is dict and set(limits) == set(c.LIMITS), "13F_GAP_LIMITS")
    for k in limits:
        c.integer(limits[k], c.LIMITS[k], "13F_GAP_LIMITS")
    require(241 <= limits["provider_gets"] <= 155 + 86 * PAGE_LIMIT
            and all(limits[k] > 0 for k in ("drive_requests", "drive_bytes", "storage_bytes")),
            "13F_GAP_LIMITS")
    opening = auth["opening"]
    require(type(opening) is dict and set(opening) ==
            {"source_history_sha256", "family_prefix_sha256", "family_first_sha256",
             "usage", "ceiling", "unresolved_costs_reserved"}
            and opening["unresolved_costs_reserved"] is True
            and all(valid_sha(opening[k]) for k in ("source_history_sha256", "family_prefix_sha256",
                                                   "family_first_sha256")), "13F_GAP_OPENING")
    reservation = dict(limits, active_seconds=auth["wall_seconds"], dispatches=1)
    for key in ("usage", "ceiling"):
        require(type(opening[key]) is dict and set(opening[key]) == accounting_keys(c), "13F_GAP_OPENING")
        for amount in opening[key].values():
            c.integer(amount, 2**53 - 1, "13F_GAP_OPENING")
    floor = dict(c.CONTINUATION["used"], active_seconds=c.CONTINUATION["active_seconds"],
                 dispatches=len(c.CONTINUATION["runs"]))
    require(all(floor[k] <= opening["usage"][k]
                and opening["usage"][k] + reservation[k] <= opening["ceiling"][k] for k in reservation),
            "13F_GAP_CUMULATIVE_LIMIT")
    return control_digest(auth)


def read_plan(raw, schedule):
    require(digest(raw) == PLAN_SHA, "13F_GAP_PLAN_HASH")
    reader = csv.DictReader(io.StringIO(raw.decode("ascii"), newline=""))
    require(tuple(reader.fieldnames or ()) == PLAN_FIELDS, "13F_GAP_PLAN_SCHEMA")
    windows, seen = [], set()
    for i, row in enumerate(reader, 1):
        start, end = row["start"], row["end_exclusive"]
        symbols = tuple(row["symbols"].split(";"))
        require(set(row) == set(PLAN_FIELDS) and START <= start < end <= END and row["plan_group"] == str(i)
                and symbols == tuple(sorted(set(symbols))) and 1 <= len(symbols) <= cap.GROUP_SIZE
                and all(cap.SYMBOL.fullmatch(t) for t in symbols)
                and row["sym_count"] == str(len(symbols)) and row["provider_feed"] == "sip"
                and row["currency"] == "USD" and row["bases"] == "raw;split"
                and row["execution_status"] == "NOT_ACTIVATED", "13F_GAP_PLAN_GROUP")
        sessions = tuple(day for day in schedule if start <= day < end)
        keys = {(t, day) for t in symbols for day in sessions}
        require(sessions and sessions[0] == start and start == date.fromisoformat(start).isoformat()
                and end == date.fromisoformat(end).isoformat()
                and row["requested_per_basis"] == str(len(keys)) and not keys.intersection(seen),
                "13F_GAP_PLAN_SESSIONS")
        seen.update(keys)
        windows.append(Window(i, start, end, symbols, sessions))
    require(len(windows) == 43 and len(seen) == 4980 and len({t for t, _ in seen}) == 154
            and sum(len(w.symbols) for w in windows) == 155, "13F_GAP_PLAN_COVERAGE")
    return windows


def archival_schedule(c, now):
    from tools.run_daily_market_session_gate import mcal

    last = (date.fromisoformat(END) - timedelta(days=1)).isoformat()
    schedule = mcal.get_calendar("NYSE").schedule(start_date=START, end_date=last)
    require(len(schedule) and all(c.utc(row["market_close"].isoformat()) + timedelta(minutes=120) <= now
                                  for _, row in schedule.iterrows())
            and c.utc(last + "T23:59:59Z") + timedelta(minutes=15) <= now, "13F_GAP_UNSETTLED")
    return tuple(label.date().isoformat() for label in schedule.index)


def event_control(c, inputs, control, expected=None):
    require(type(control) is dict and set(control) == {"authorization", "nonce"}, "13F_GAP_CONTROL")
    auth = control["authorization"]
    validate_authorization(c, auth)
    require(control["nonce"] == inputs.get("campaign_nonce") == nonce(c)
            and inputs.get("private_root_folder_id") == auth["private_root_folder_id"]
            and inputs.get("private_data_folder_id") == auth["private_data_folder_id"]
            and inputs.get("resume_file_id", "") == inputs.get("resume_sha256", "") == ""
            and inputs.get("end_date") == END and inputs.get("max_new_symbols") in (4, "4")
            and all(inputs.get(k) is True or inputs.get(k) == "true" for k in
                    ("private_research_authorized", "noncommercial_terms_acknowledged"))
            and (expected is None or encoded(expected) == encoded(control)), "13F_GAP_EVENT")
    return control


def verify_source(c, auth, *, accounting=False):
    cap._new3_source(c, auth, accounting=accounting,
                     gate_profile=c._revision_module().BRIDGE_CURRENT_GATE_PROFILE)


def authority(c, auth):
    now, start, expiry = c.utc(), c.utc(auth["not_before_utc"]), c.utc(auth["expires_at_utc"])
    require(start <= now < expiry, "13F_GAP_OPERATING_WINDOW")
    approved = cap._fixed_spy_owner_record(c, auth["allocation_reference"], TAG,
                                           window=(auth["not_before_utc"], auth["expires_at_utc"]))
    require(approved == dict(schema="a1-13f154-gap-execution-v1", task_key=TASK, control_sha256=control_digest(auth),
                            scope_sha256=SCOPE_SHA, dispatches=1, expires_at_utc=auth["expires_at_utc"],
                            rights_sha256=RIGHTS_SHA, private_noncommercial=True,
                            source_admission=False, economic_authority=False), "13F_GAP_OWNER_GRANT")
    pr = c.gh_json(f"repos/{c.REPO}/pulls/{auth['deployment']['pull_request']}")
    require(c.utc(pr.get("merged_at")) <= start, "13F_GAP_DEPLOYMENT_CLOCK")


def history(c, auth, current=None):
    rows = c.campaign_run_pages(c)
    matches = [r for r in rows if r.get("display_title") == "a1-sip " + nonce(c)]
    require(len(matches) == (0 if current is None else 1), "13F_GAP_SLOT_ALREADY_USED_OR_UNKNOWN")
    if current is not None:
        run = matches[0]
        require(run.get("id") == current and run.get("run_attempt") == 1 and run.get("head_sha") == auth["expected_master"]
                and run.get("event") == "workflow_dispatch" and run.get("head_branch") == "master"
                and run.get("status") == "in_progress", "13F_GAP_CURRENT_RUN")
    others = [r for r in rows if r.get("id") != current]
    require(all(r.get("status") == "completed" for r in others), "13F_GAP_OTHER_SOURCE_RUN")
    prefix = [{k: r.get(k) for k in SOURCE_FIELDS} for r in sorted(others, key=lambda x: x["id"])]
    require(digest(encoded(prefix)) == auth["opening"]["source_history_sha256"], "13F_GAP_SOURCE_HISTORY")
    return matches[0] if matches else None


def read_assets(drive, auth, windows):
    folder = auth["evidence_folder_id"]
    document = decode(cap._private_object(drive, folder, auth["identity_ref"], 262144))
    require(type(document) is dict and set(document) == {"schema", "plan_sha256", "assets"}
            and document["schema"] == "a1-13f154-gap-asset-bindings-v1"
            and document["plan_sha256"] == PLAN_SHA and type(document["assets"]) is dict
            and set(document["assets"]) <= {t for w in windows for t in w.symbols}, "13F_GAP_ASSET_BINDINGS")
    results = {}
    for ticker, row in document["assets"].items():
        require(type(row) is dict and set(row) == {"verified_from", "verified_through", "asset_ref"}
                and START <= row["verified_from"] <= row["verified_through"] < END,
                "13F_GAP_ASSET_BOUNDARY")
        for key in ("verified_from", "verified_through"):
            require(row[key] == date.fromisoformat(row[key]).isoformat(), "13F_GAP_ASSET_BOUNDARY")
        check_ref(row["asset_ref"], 65536)
        raw = cap._private_object(drive, folder, row["asset_ref"], 65536)
        asset = cap.asset_record(raw, ticker)
        require(asset["status"] == "active", "13F_GAP_ASSET_BINDINGS")
        results[ticker] = (row["verified_from"], row["verified_through"], asset["id"], asset["exchange"])
    return results


def guard_requests(c, window, meter, key, secret):
    first, last = window.sessions[0], (date.fromisoformat(window.end) - timedelta(days=1)).isoformat()
    expected = {"symbols": [",".join(window.symbols)], "timeframe": ["1Day"], "start": [first+"T00:00:00Z"],
                "end": [last+"T23:59:59Z"], "feed": ["sip"], "limit": ["10000"], "sort": ["asc"],
                "asof": [cap.mapping_asof(window.end)]}
    page_counts, next_tokens = Counter(), {}
    asset_paths = {"/v2/assets/" + t for t in window.symbols}

    def get(url, **kwargs):
        endpoint = urlsplit(url)
        if (endpoint.netloc == "paper-api.alpaca.markets" and endpoint.path in asset_paths
                and not endpoint.query and not endpoint.fragment):
            asset_paths.remove(endpoint.path)
            return meter.perform(url, **kwargs)
        query = parse_qs(endpoint.query, keep_blank_values=True, strict_parsing=True)
        basis = query.pop("adjustment", [])
        token = query.pop("page_token", None)
        require(endpoint.netloc == "data.alpaca.markets" and endpoint.path == "/v2/stocks/bars"
                and not endpoint.fragment and not asset_paths and query == expected and basis in (["raw"], ["split"]),
                "13F_GAP_REQUEST_SCOPE")
        name = basis[0]
        require(page_counts[name] < PAGE_LIMIT
                and (token is None if not page_counts[name] else token == next_tokens.get(name) and token is not None),
                "13F_GAP_PAGE_SCOPE")
        page_counts[name] += 1
        raw = meter.perform(url, **kwargs)
        payload = cap.credential_safe_json(raw, (key, secret))
        require(type(payload) is dict and type(payload.get("bars")) is dict, "13F_GAP_BARS_SCHEMA")
        next_token = payload.get("next_page_token")
        next_tokens[name] = [next_token] if next_token is not None else None
        require(next_token is None or page_counts[name] < PAGE_LIMIT, "13F_GAP_PAGE_SCOPE")
        return raw

    return get


def record_checkpoint(drive, auth, meter, receipts, last, totals):
    state = dict(schema="a1-13f154-gap-checkpoint-v1", task_key=TASK, plan_sha256=PLAN_SHA, scope_sha256=SCOPE_SHA,
                 source_sha=auth["expected_master"], run_id=meter.identity["run_id"], run_attempt=1,
                 previous_checkpoint=last, groups=receipts, totals=dict(totals), source_admission=False,
                 pit_verified=False, economic_authority=False)
    folder = auth["private_data_folder_id"]
    checkpoint = cap.persist_object(drive, folder, encoded(state), ".json")
    require(decode(cap._private_object(drive, folder, checkpoint, 262144)) == state, "13F_GAP_CHECKPOINT_READBACK")
    meter.checkpoint_sha, meter.examined, meter.rows = checkpoint["sha256"], len(receipts), totals["rows"]
    meter.states["VALID_COLLECTED"] = totals["complete_groups"]
    meter.states["QUARANTINED"] = totals["held_groups"]
    meter.save()
    return checkpoint


def capture(c, auth, drive, meter, windows, assets, key, secret):
    folder = auth["private_data_folder_id"]
    scope = dict(task_key=TASK, namespace=PROFILE, input_sha256=PLAN_SHA)
    receipts, totals, last = [], Counter(rows=0, complete_groups=0, held_groups=0), None
    for window in windows:
        meter.remaining_seconds()
        group = dict(group=window.number, start=window.start, end_exclusive=window.end, symbols=list(window.symbols))
        if any(t not in assets or not assets[t][0] <= window.sessions[0] <= window.sessions[-1] <= assets[t][1]
               for t in window.symbols):
            group["status"] = "HELD_IDENTITY_WINDOW"
        else:
            meter.asset_symbols = window.symbols
            get = guard_requests(c, window, meter, key, secret)
            evidence = cap.precheck_assets(list(window.symbols), key, secret, get)
            same = all(cap.asset_supported(row)
                       and tuple(cap.asset_record(row["response_utf8"].encode(), row["symbol"])[k]
                                 for k in ("id", "exchange")) == assets[row["symbol"]][2:] for row in evidence)
            if not same:
                group.update(status="HELD_ASSET_RECHECK",
                             asset_evidence=cap.persist_object(drive, folder, encoded(evidence), ".json"))
            else:
                objects, _, _, count = cap.capture_one_group(drive, folder, list(window.symbols), window.start, window.end,
                    key, secret, PLAN_SHA, auth["expected_master"], get=get, scope=scope, asset_evidence=evidence)
                raw, norm, receipt = [cap._private_object(drive, folder, ref, 16_000_000) for ref in objects]
                cap.verify_archived_group(raw, norm, decode(receipt))
                expected = {(t, day, basis) for t in window.symbols for day in window.sessions for basis in ("raw", "split")}
                received = {(r["ticker"], r["date"], r["adjustment"])
                            for r in map(decode, gzip.decompress(norm).splitlines())}
                require(received <= expected and len(received) == count, "13F_GAP_NORMALIZED_SCOPE")
                group.update(status="VERIFIED_RAW_SPLIT" if expected == received else "PARTIAL_RAW_SPLIT",
                             objects=objects, rows=count, missing_cells=len(expected - received))
                totals["rows"] += count
        totals["complete_groups" if group["status"] == "VERIFIED_RAW_SPLIT" else "held_groups"] += 1
        receipts.append(group)
        last = record_checkpoint(drive, auth, meter, receipts[:], last, totals)
    return totals


def worker(c, args, control, journal):
    require(type(control) is dict and set(control) == {"authorization", "nonce"}, "13F_GAP_CONTROL")
    auth = control["authorization"]
    auth_hash = validate_authorization(c, auth)
    require(os.getenv("GITHUB_REPOSITORY") == c.REPO and os.getenv("GITHUB_REF") == "refs/heads/master"
            and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch" and os.getenv("GITHUB_RUN_ATTEMPT") == "1"
            and os.getenv("GITHUB_SHA") == auth["expected_master"]
            and control["nonce"] == os.getenv("INPUT_CAMPAIGN_NONCE") == nonce(c), "13F_GAP_CONTEXT")
    cap._new3_event_control(c, control)
    require(args.private_root_folder_id == args.private_data_folder_id == args.resume_file_id == args.resume_sha256 == ""
            and args.start == cap.MIN_START and args.end == END and args.max_new_symbols == cap.GROUP_SIZE,
            "13F_GAP_ARGUMENTS")
    verify_source(c, auth)
    authority(c, auth)
    run_id = int(os.environ["GITHUB_RUN_ID"])
    run = history(c, auth, run_id)
    start, now = c.utc(run["created_at"]), c.utc()
    deadline = min(c.utc(auth["expires_at_utc"]), start + timedelta(seconds=auth["wall_seconds"] - 60))
    require(c.utc(auth["not_before_utc"]) <= start <= c.utc(run["run_started_at"]) <= now < deadline,
            "13F_GAP_START_OR_DEADLINE")
    schedule = archival_schedule(c, now)
    verify_source(c, auth)
    key, secret = os.getenv("ALPACA_API_KEY", "").strip(), os.getenv("ALPACA_API_SECRET", "").strip()
    require(key and secret, "13F_GAP_CREDENTIALS")
    meter = c.RuntimeMeter(auth["limits"], journal, deadline.isoformat(),
        dict(task_key=TASK, allocation_profile=PROFILE, auth_sha256=auth_hash, source_sha=auth["expected_master"],
             nonce=nonce(c), run_id=run_id, run_attempt=1, preflight_only=False, examined_before=0,
             parent_checkpoint_sha256=None, opening_accounting_sha256=digest(encoded(auth["opening"]))))
    try:
        with meter.process_deadline(), tempfile.TemporaryDirectory(prefix="a1-13f-gap-") as temp:
            drive = OwnerDrive(auth["private_root_folder_id"], temp, meter=meter)
            require(digest(drive.owner.encode()) == auth["owner_sha256"] and drive.free >= 2*1024**3, "13F_GAP_OWNER")
            drive.check(auth["private_data_folder_id"], drive.root_id)
            folder = auth["evidence_folder_id"]
            drive.check(folder, drive.root_id)
            rights = decode(cap._private_object(drive, folder, auth["rights_ref"], 262144))
            require(rights.get("schema") == "a1-reviewed-account-rights-v1" and rights.get("provider") == "alpaca"
                    and rights.get("purpose") == "PRIVATE_NONCOMMERCIAL_RESEARCH"
                    and rights.get("historical_sip_allowed") is True and rights.get("private_retention_allowed") is True
                    and rights.get("credential_binding") == digest((key+"\0"+secret).encode()),
                    "13F_GAP_RIGHTS_OR_CREDENTIAL_BINDING")
            expiry = rights.get("supplier_expiry")
            require(expiry is None or c.utc(expiry) >= c.utc(auth["expires_at_utc"]), "13F_GAP_SUPPLIER_EXPIRY")
            docs = rights.get("source_documents")
            require(isinstance(docs, list) and 1 <= len(docs) <= 8, "13F_GAP_RIGHTS_DOCUMENTS")
            for ref in docs:
                check_ref(ref, 262144)
                cap._private_object(drive, folder, ref, 262144)
            windows = read_plan(cap._private_object(drive, folder, auth["plan_ref"], 262144), schedule)
            assets = read_assets(drive, auth, windows)
            require(any(all(t in assets and assets[t][0] <= w.sessions[0] <= w.sessions[-1] <= assets[t][1]
                            for t in w.symbols) for w in windows), "13F_GAP_NO_ELIGIBLE_GROUP")
            totals = capture(c, auth, drive, meter, windows, assets, key, secret)
    except BaseException:
        meter.finish("BLOCKED", "13F_GAP_CAPTURE_FAILED")
        raise
    status = "COMPLETE" if not totals["held_groups"] else "PARTIAL"
    meter.finish("COMPLETE" if status == "COMPLETE" else "BLOCKED",
                 None if status == "COMPLETE" else "13F_GAP_PARTIAL")
    result = dict(status=status, allocation_profile=PROFILE, checkpoint_sha256=meter.checkpoint_sha,
                  rows_verified=meter.rows, group_counts=dict(totals), source_admission=False,
                  pit_verified=False, economic_authority=False)
    print(c.json.dumps(result, sort_keys=True))
    require(status == "COMPLETE", "13F_GAP_PARTIAL")
    return result


def dispatch(c, auth, state_dir, budget_state_dir, *, forbidden=False):
    require(not forbidden and budget_state_dir is not None, "13F_GAP_HOST_SCOPE")
    budget = Path(budget_state_dir)
    state = Path(state_dir)
    family_path = budget.resolve().parent / ("external-budget-" + c.CONTINUATION["auth"][:16])
    require(budget.is_dir() and not budget.is_symlink() and family_path.is_dir() and not family_path.is_symlink()
            and not state.is_symlink() and state.resolve() == budget.resolve().parent / PROFILE, "13F_GAP_JOURNAL_PATH")
    family = c.WorkJournal(family_path, c.external_family_genesis())
    slot = None
    try:
        opening = auth["opening"]
        require(bool(family.entries) and family.entries[0].get("kind") == "EXTERNAL_FAMILY_BOUND"
                and family.entries[0].get("budget_state_root") == os.path.normcase(str(budget.resolve()))
                and family.parent == opening["family_prefix_sha256"]
                and digest(c.bounded_bytes(family_path/"000001.json")) == opening["family_first_sha256"],
                "13F_GAP_FAMILY_PREFIX")
        slot = c.WorkJournal(state, digest(TASK.encode()))
        if slot.entries:
            return dict(status="13F_GAP_RESERVED_READBACK_ONLY", nonce=nonce(c), automatic_retry=False)
        verify_source(c, auth)
        authority(c, auth)
        history(c, auth)
        archival_schedule(c, c.utc())
        slot.append("13F_GAP_RESERVED", nonce=nonce(c), control_sha256=control_digest(auth),
                    allowance=auth["limits"], elapsed_reservation=auth["wall_seconds"],
                    opening_sha256=digest(encoded(opening)))
        verify_source(c, auth)
        authority(c, auth)
        history(c, auth)
        control = dict(authorization=auth, nonce=nonce(c))
        inputs = dict(private_root_folder_id=auth["private_root_folder_id"],
                      private_data_folder_id=auth["private_data_folder_id"], private_research_authorized="true",
                      noncommercial_terms_acknowledged="true", end_date=END, max_new_symbols=str(cap.GROUP_SIZE),
                      resume_file_id="", resume_sha256="", campaign_control=encoded(control).decode(),
                      campaign_nonce=nonce(c))
        try:
            sent = c.subprocess.run(["gh","workflow","run",c.WORKFLOW,"--repo",c.REPO,"--ref","master","--json"],
                input=c.json.dumps(inputs).encode(), stdout=c.subprocess.DEVNULL, stderr=c.subprocess.DEVNULL, timeout=45)
            require(sent.returncode == 0, "13F_GAP_DISPATCH_UNCERTAIN")
        except Exception:
            raise Refused("13F_GAP_DISPATCH_UNCERTAIN") from None
        return dict(status="13F_GAP_POST_ACCEPTED_OUTCOME_PENDING", nonce=nonce(c),
                    automatic_retry=False, source_admission=False)
    finally:
        try:
            if slot is not None:
                slot.close()
        finally:
            family.close()
