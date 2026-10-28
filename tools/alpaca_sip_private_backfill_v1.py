#!/usr/bin/env python3
"""Bounded, resumable Alpaca SIP 1Day research backfill.

No trading, fullrun, research admission, public original upload, or automatic
portfolio change. Original vendor bytes are private and gated by owner consent.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import gzip
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlencode
import zipfile

from tools.twelve_private_capture import (
    OwnerDrive, Refused, credential_safe_json, decode, digest, encoded, http, require,
)

REPOSITORY = "wscha231/r1000-quant-engine"
SCHEMA = "alpaca-private-sip-history-v1"
SOURCE = "ALPACA_STOCK_BARS_V2_HISTORICAL_SIP"
URL = "https://data.alpaca.markets/v2/stocks/bars"
SEED = Path("data_static/iwb_holdings_seed.csv")
MIN_START = "2016-01-04"
ALLOWED_SUFFIXES = (".json", ".zip", ".jsonl.gz")
MAX_CHECKPOINT_CHAIN = 1500
MAX_PAGE_BYTES = 8_000_000
MAX_PAGES = 25
GROUP_SIZE = 4
SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,13}")

# One reviewed research window, independent of the frozen IWB/174 lineage.
FIXED_SPY_PROFILE = "spy-665-20261023-v1"
FIXED_SPY_START = "2024-03-01"
FIXED_SPY_END = "2026-10-24"
FIXED_SPY_INPUT = b"ticker\nSPY\n"


def _fixed_spy_scope():
    return dict(task_key="R1000-A1-SPY-665-20261025", namespace="spy-665-20261023",
                input_sha256=digest(FIXED_SPY_INPUT))


def _fixed_spy_genesis():
    return digest(encoded(dict(schema="a1-fixed-spy-data-genesis-v1",
        cohort_scope=_fixed_spy_scope(), start=FIXED_SPY_START, end=FIXED_SPY_END)))


def cohort(raw: bytes) -> list[str]:
    text = raw.decode("utf-8-sig")
    rows = csv.DictReader(io.StringIO(text, newline=""))
    require(rows.fieldnames is not None and "ticker" in rows.fieldnames, "COHORT_SCHEMA")
    values = []
    seen = set()
    for row in rows:
        name = str(row.get("ticker") or "").strip().upper()
        # IWB proxy includes occasional non-equity rows; mark and exclude.
        if not SYMBOL.fullmatch(name):
            continue
        require(name not in seen, "COHORT_DUPLICATE")
        seen.add(name)
        values.append(name)
    require(900 <= len(values) <= 1500, "COHORT_SCOPE")
    return sorted(values)


def external_cohort(raw: bytes) -> list[str]:
    """Explicit bounded discovery input; never changes the legacy IWB seed."""
    require(isinstance(raw, bytes) and 0 < len(raw) <= 8192, "EXTERNAL_COHORT_SIZE")
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    except (UnicodeError, csv.Error):
        raise Refused("EXTERNAL_COHORT_SCHEMA") from None
    require(rows and rows[0] == ["ticker"] and 1 <= len(rows)-1 <= 500
            and all(len(row) == 1 and SYMBOL.fullmatch(row[0]) for row in rows[1:]),
            "EXTERNAL_COHORT_SCHEMA")
    names = [row[0] for row in rows[1:]]
    require(len(set(names)) == len(names), "EXTERNAL_COHORT_DUPLICATE")
    return names


def external_scope(value):
    require(isinstance(value, dict) and set(value) ==
            {"task_key", "namespace", "input_sha256"}
            and isinstance(value["task_key"], str)
            and re.fullmatch(r"R1000-[A-Z0-9-]{8,100}", value["task_key"])
            and isinstance(value["namespace"], str)
            and re.fullmatch(r"[a-z][a-z0-9-]{7,79}", value["namespace"])
            and isinstance(value["input_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", value["input_sha256"]), "EXTERNAL_COHORT_SCOPE")
    return dict(value)


def asset_record(raw, symbol):
    """Current asset reference only, never historical identity/entitlement."""
    value = decode(raw)
    require(isinstance(value, dict) and value.get("symbol") == symbol
            and value.get("class") == "us_equity"
            and isinstance(value.get("id"), str)
            and re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value["id"])
            and isinstance(value.get("exchange"), str) and 1 <= len(value["exchange"]) <= 32
            and value.get("status") in ("active", "inactive"), "EXTERNAL_ASSET_IDENTITY")
    return value


def verify_asset_evidence(evidence, names):
    require(isinstance(evidence, list) and len(evidence) == len(names), "EXTERNAL_ASSET_EVIDENCE")
    for row, symbol in zip(evidence, names):
        require(isinstance(row, dict) and set(row) ==
                {"symbol", "url", "collected_at_utc", "http_status", "response_utf8", "sha256"}
                and row["symbol"] == symbol
                and row["url"] == "https://paper-api.alpaca.markets/v2/assets/" + symbol
                and valid_clock(row["collected_at_utc"]), "EXTERNAL_ASSET_EVIDENCE")
        if row["http_status"] == 404:
            require(type(row["http_status"]) is int and row["response_utf8"] is None
                    and row["sha256"] is None, "EXTERNAL_ASSET_EVIDENCE")
        else:
            require(type(row["http_status"]) is int and row["http_status"] == 200
                    and isinstance(row["response_utf8"], str)
                    and 0 < len(row["response_utf8"].encode()) <= 65536
                    and digest(row["response_utf8"].encode()) == row["sha256"], "EXTERNAL_ASSET_EVIDENCE")
            asset_record(row["response_utf8"].encode(), symbol)


def precheck_assets(names, key, secret, get):
    evidence = []
    for symbol in names:
        url = "https://paper-api.alpaca.markets/v2/assets/" + symbol
        row = dict(symbol=symbol, url=url, collected_at_utc=datetime.now(timezone.utc).isoformat(),
                   http_status=200, response_utf8=None, sha256=None)
        try:
            raw = get(url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                      limit=65536, credentials=(key, secret))
            credential_safe_json(raw, (key, secret))
            asset_record(raw, symbol)
            row.update(response_utf8=raw.decode("utf-8"), sha256=digest(raw))
        except Refused as exc:
            if str(exc) != "ASSET_NOT_FOUND":
                raise
            row["http_status"] = 404  # No response bytes/hash are invented.
        evidence.append(row)
    verify_asset_evidence(evidence, names)
    return evidence


def asset_supported(row):
    return row["http_status"] == 200 and asset_record(
        row["response_utf8"].encode(), row["symbol"])["status"] == "active"


def mapping_asof(end: str) -> str:
    """Stable symbol-identity mapping date derived only from frozen cohort end."""
    require(isinstance(end, str) and
            re.fullmatch(r"\d{4}-\d{2}-\d{2}", end), "ASOF_DATE")
    try:
        return (date.fromisoformat(end) - timedelta(days=1)).isoformat()
    except (ValueError, OverflowError):
        raise Refused("ASOF_DATE") from None


def valid_clock(value: str) -> bool:
    try:
        clock = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return clock.utcoffset() == timezone.utc.utcoffset(clock)
    except (ValueError, AttributeError, TypeError, OverflowError):
        return False


def normalize(bars: list[dict], symbol: str, adjustment: str,
              start: str, end: str) -> list[dict]:
    out, seen = [], set()
    require(isinstance(bars, list), "BARS_SCHEMA")
    for bar in bars:
        require(isinstance(bar, dict), "BARS_SCHEMA")
        timestamp = bar.get("t")
        require(isinstance(timestamp, str) and valid_clock(timestamp), "BAR_TIMESTAMP")
        session = timestamp[:10]
        try:
            day = date.fromisoformat(session)
        except ValueError:
            raise Refused("BAR_TIMESTAMP") from None
        require(start <= session < end and day.weekday() < 5, "BAR_RANGE")
        require(session not in seen, "DUPLICATE_SESSION")
        seen.add(session)
        fields = []
        for key in ("o", "h", "l", "c", "v"):
            x = bar.get(key)
            require(type(x) in (int, float), "BAR_VALUE")
            try:
                y = Decimal(str(x))
            except (InvalidOperation, ValueError, OverflowError):
                raise Refused("BAR_VALUE") from None
            require(y.is_finite(), "BAR_VALUE")
            fields.append(y)
        o, h, l, c, v = fields
        require(min(o, h, l, c) > 0 and l <= min(o, c) <= max(o, c) <= h
                and v >= 0 and v == v.to_integral_value(), "BAR_VALUE")
        out.append({
            "ticker": symbol, "date": session, "adjustment": adjustment,
            "open": str(o), "high": str(h), "low": str(l),
            "close": str(c), "volume": str(v), "currency": "USD",
        })
    return sorted(out, key=lambda x: x["date"])


def request_pages(symbols: list[str], adjustment: str, start: str, end: str,
                  key: str, secret: str, get=http, pause=time.sleep):
    require(1 <= len(symbols) <= GROUP_SIZE and adjustment in ("raw", "split"),
            "REQUEST_SCOPE")
    # Alpaca bars "end" is inclusive. The caller's contract is exclusive.
    # Use the entire last requested civil day without spilling into end_date.
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", end or ""), "DATE_SCOPE")
    try:
        last_day = (date.fromisoformat(end) - timedelta(days=1)).isoformat()
    except (ValueError, OverflowError):
        raise Refused("DATE_SCOPE") from None
    query = {
        "symbols": ",".join(symbols), "timeframe": "1Day",
        "start": start + "T00:00:00Z",
        "end": last_day + "T23:59:59Z", "adjustment": adjustment,
        "feed": "sip", "limit": 10000, "sort": "asc",
        "asof": mapping_asof(end),
    }
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }
    members, grouped, pages, tokens = {}, {s: [] for s in symbols}, [], set()
    token = None
    for index in range(MAX_PAGES):
        params = dict(query)
        if token is not None:
            params["page_token"] = token
        pause(0.4)  # below free historical RPM; no parallel consumers
        raw = get(
            URL + "?" + urlencode(params), headers=headers,
            limit=MAX_PAGE_BYTES, credentials=(key, secret),
        )
        payload = credential_safe_json(raw, (key, secret))  # also reject escaped credential echoes
        require(isinstance(payload, dict) and isinstance(payload.get("bars"), dict),
                "BARS_SCHEMA")
        require(set(payload["bars"]) <= set(symbols), "UNKNOWN_SYMBOL")
        for symbol, bars in payload["bars"].items():
            require(isinstance(bars, list), "BARS_SCHEMA")
            grouped[symbol].extend(bars)
        member = digest(raw) + ".json"
        members[member] = raw
        pages.append({"sha256": digest(raw), "bytes": len(raw),
                      "member": member, "page": index,
                      "symbols": list(symbols), "adjustment": adjustment})
        token = payload.get("next_page_token")
        if token is None:
            return members, grouped, pages
        require(isinstance(token, str) and bool(token) and len(token) <= 4096
                and token not in tokens, "PAGE_TOKEN")
        tokens.add(token)
    raise Refused("PAGE_BUDGET")


def zip_bytes(members: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as dest:
        for name in sorted(members):
            require(re.fullmatch(r"[a-f0-9]{64}\.json|capture\.json", name),
                    "PACK_MEMBER")
            # ZipInfo default mtime follows wall clock; fix it for exact retry.
            item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o600 << 16
            dest.writestr(item, members[name])
    return stream.getvalue()


def persist_object(drive: OwnerDrive, folder: str, raw: bytes, extension: str):
    """Content-addressed owner-only reuse before an external Drive POST.

    With one writer and deterministic raw bytes, resuming after interrupted
    uploads reuses exact originals. A missing/ambiguous listing fails closed.
    """
    require(isinstance(raw, bytes) and 0 < len(raw) <= 16_000_000
            and extension in ALLOWED_SUFFIXES, "PACK_BUDGET")
    require(isinstance(folder, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", folder), "PRIVATE_FOLDER")
    name = digest(raw) + extension
    q = "name = '" + name + "' and '" + folder + "' in parents and trashed = false"
    result = credential_safe_json(
        drive.request("https://www.googleapis.com/drive/v3/files?" + urlencode({
            "q": q, "fields": "nextPageToken,files(id,name,parents)",
            "pageSize": 100,
        }), limit=MAX_PAGE_BYTES),
        (drive.token,),
    )
    require(isinstance(result, dict) and result.get("nextPageToken") is None
            and isinstance(result.get("files"), list), "STORAGE_LOOKUP")
    matches = result["files"]
    require(len(matches) <= 1, "STORAGE_DUPLICATE")
    if matches:
        item = matches[0]
        require(isinstance(item, dict) and item.get("name") == name
                and isinstance(item.get("id"), str), "STORAGE_LOOKUP")
        drive.check(item["id"], folder, folder=False)
        stored = drive.read(item["id"], 16_000_000)
        require(stored == raw and digest(stored) == name[:64],
                "STORAGE_CONTENT_CONFLICT")
        return {"file_id": item["id"], "sha256": digest(raw),
                "bytes": len(raw)}
    written = drive.write(folder, raw, extension)
    require(isinstance(written, dict)
            and written.get("sha256") == digest(raw)
            and written.get("bytes") == len(raw), "STORAGE_WRITE")
    return written


def _private_object(drive: OwnerDrive, folder: str, ref: dict,
                    max_bytes: int = 16_000_000) -> bytes:
    require(isinstance(ref, dict)
            and isinstance(ref.get("file_id"), str)
            and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", ref["file_id"])
            and isinstance(ref.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])
            and type(ref.get("bytes")) is int
            and 0 < ref["bytes"] <= max_bytes, "RESUME_REFERENCE")
    drive.check(ref["file_id"], folder, folder=False)
    raw = drive.read(ref["file_id"], max_bytes)
    require(len(raw) == ref["bytes"] and digest(raw) == ref["sha256"],
            "RESUME_OBJECT_HASH")
    return raw


def verify_archived_group(raw_pack: bytes, normalized_pack: bytes,
                          receipt: dict) -> None:
    """Rebuild every retained bar from bounded original response members.

    Hashes and file magic alone cannot prove symbol, date, adjustment, or
    normalized-row membership. A restored checkpoint never skips unverifiable
    inputs, even when its own bytes were preserved without modification.
    """
    require(isinstance(receipt, dict), "RESUME_RECEIPT_CONTENT")
    names = receipt.get("symbols")
    require(isinstance(names, list) and 1 <= len(names) <= GROUP_SIZE
            and len(names) == len(set(names))
            and all(isinstance(t, str) and SYMBOL.fullmatch(t) for t in names),
            "RESUME_RECEIPT_CONTENT")
    require(isinstance(raw_pack, bytes) and 0 < len(raw_pack) < 16_000_000
            and isinstance(normalized_pack, bytes)
            and 0 < len(normalized_pack) < 16_000_000,
            "RESUME_ARCHIVE_LIMIT")
    grids = {basis: {name: [] for name in names} for basis in ("raw", "split")}
    try:
        with zipfile.ZipFile(io.BytesIO(raw_pack)) as archive:
            infos = archive.infolist()
            members = [item.filename for item in infos]
            require(len(infos) <= 2 * MAX_PAGES + 1
                    and len(infos) == len(set(members))
                    and "capture.json" in members
                    and all(re.fullmatch(r"[0-9a-f]{64}\.json|capture\.json", n)
                            for n in members)
                    and sum(info.file_size for info in infos) <= 128_000_000
                    and all(info.file_size <= MAX_PAGE_BYTES
                            for info in infos if info.filename != "capture.json")
                    and archive.testzip() is None, "RESUME_ARCHIVE")
            manifest = decode(archive.read("capture.json"))
            require(isinstance(manifest, dict)
                    and manifest.get("schema") == SCHEMA
                    and manifest.get("source") == SOURCE
                    and manifest.get("symbols") == names
                    and manifest.get("collected") == receipt.get("collected")
                    and manifest.get("no_bars") == receipt.get("no_bars")
                    and manifest.get("seed_sha256") == receipt.get("seed_sha256")
                    and manifest.get("source_sha") == receipt.get("source_sha")
                    and manifest.get("start") == receipt.get("start")
                    and manifest.get("end") == receipt.get("end")
                    and manifest.get("asof") == receipt.get("asof")
                    and manifest.get("cohort_scope") == receipt.get("cohort_scope")
                    and manifest.get("asset_precheck") == receipt.get("asset_precheck")
                    and manifest.get("asof") == mapping_asof(receipt.get("end"))
                    and manifest.get("raw_adjustments") == ["raw", "split"]
                    and manifest.get("pit_verified") is False
                    and manifest.get("historical_identity_verified") is False
                    and manifest.get("commercial_use_authorized") is False
                    and manifest.get("source_admission") is False,
                    "RESUME_MANIFEST")
            if receipt.get("cohort_scope") is not None:
                external_scope(receipt["cohort_scope"])
                verify_asset_evidence(receipt.get("asset_precheck"), names)
                require(all(asset_supported(row) for row in receipt["asset_precheck"]),
                        "EXTERNAL_ASSET_EVIDENCE")
            evidence = manifest.get("pages")
            require(isinstance(evidence, list)
                    and 2 <= len(evidence) <= 2 * MAX_PAGES
                    and len(evidence) == receipt.get("pages"),
                    "RESUME_EVIDENCE")
            visited = {"raw": [], "split": []}
            expected_members = {"capture.json"}
            for row in evidence:
                require(isinstance(row, dict)
                        and row.get("adjustment") in grids
                        and row.get("symbols") == names
                        and type(row.get("page")) is int
                        and row["page"] == len(visited[row["adjustment"]])
                        and type(row.get("bytes")) is int
                        and 0 < row["bytes"] <= MAX_PAGE_BYTES
                        and isinstance(row.get("sha256"), str)
                        and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                        and row.get("member") == row["sha256"] + ".json",
                        "RESUME_EVIDENCE")
                member = row["member"]
                require(member in members, "RESUME_MEMBER_MISSING")
                raw = archive.read(member)
                require(len(raw) == row["bytes"]
                        and digest(raw) == row["sha256"], "RESUME_MEMBER_HASH")
                payload = decode(raw)
                require(isinstance(payload, dict)
                        and isinstance(payload.get("bars"), dict)
                        and set(payload["bars"]) <= set(names),
                        "RESUME_BARS_SCHEMA")
                for name, bars in payload["bars"].items():
                    require(isinstance(bars, list), "RESUME_BARS_SCHEMA")
                    grids[row["adjustment"]][name].extend(bars)
                token = payload.get("next_page_token")
                require(token is None or
                        (isinstance(token, str) and 0 < len(token) <= 4096),
                        "RESUME_PAGE_TOKEN")
                visited[row["adjustment"]].append(token)
                expected_members.add(member)
            require(set(members) == expected_members, "RESUME_MEMBER_SET")
            for tokens in visited.values():
                require(tokens and len(tokens) <= MAX_PAGES and tokens[-1] is None
                        and all(token is not None for token in tokens[:-1])
                        and len(tokens[:-1]) == len(set(tokens[:-1])),
                        "RESUME_PAGINATION")
    except (zipfile.BadZipFile, OSError, EOFError, RuntimeError,
            ValueError, OverflowError):
        raise Refused("RESUME_ARCHIVE") from None
    restored_rows, collected, missing = [], [], []
    for name in names:
        raw_rows = normalize(grids["raw"][name], name, "raw",
                             receipt["start"], receipt["end"])
        split_rows = normalize(grids["split"][name], name, "split",
                               receipt["start"], receipt["end"])
        require([x["date"] for x in raw_rows] ==
                [x["date"] for x in split_rows],
                "RESUME_BASIS_GRID")
        if raw_rows:
            collected.append(name)
        else:
            missing.append(name)
        restored_rows.extend(raw_rows)
        restored_rows.extend(split_rows)
    require(collected == receipt.get("collected")
            and missing == receipt.get("no_bars")
            and len(restored_rows) == receipt.get("rows"),
            "RESUME_ROWS")
    expected = b"".join(encoded(row) for row in restored_rows)
    require(len(expected) <= 32_000_000, "RESUME_NORMALIZED_LIMIT")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(normalized_pack), mode="rb") as gz:
            recovered = gz.read(32_000_001)
    except (OSError, EOFError, ValueError, OverflowError):
        raise Refused("RESUME_NORMALIZED_FORMAT") from None
    require(len(recovered) <= 32_000_000 and recovered == expected,
            "RESUME_NORMALIZED_MISMATCH")


STORAGE_QUARANTINE = dict(
    schema="a1-uncertain-storage-quarantine-v1", failed_run_id=39085031884,
    failed_meter_sha256="231d256890c209ef5dace024a25cfafc5d6a8714abded3a8cca76f2752818814",
    native_run_id=39103855450,
    native_meter_sha256="5ee2027eb33a6f271aa8cf96c35763e71b49e23ac9eb8517541ecf6a8556c18e",
    native_source_sha="a549c27b1cdd002bdaaa7dd6ab5dfc44fef0aaad",
    checkpoint_sha256="efcea3356688118392fa71612ee2702c4b9ea436ad88bdfdab917ef60e373cfd",
    input_sha256="1f04634e055a1b92fc8e1c167d92b54b8ada71032cb633afe02235dfef36c57e",
    owner_sha256="08e29aa6cca772e9319b2aab20ad9fdba5dd0d8fce08a90b9fdbf3253fe9a94e",
    examined_before=76, symbols=["VLO", "MFG", "BP", "BTI"],
    unknown_storage_bytes_still_charged=302101,
    absence_proven=False, failed_request_body_hash_known=False,
)


def verify_storage_quarantine(evidence, scope):
    """One sealed non-price hold, never permission to retry unknown bytes."""
    require(isinstance(evidence, dict) and set(evidence) == set(STORAGE_QUARANTINE) |
            {"authorization_sha256", "external_proof_sha256", "native_settlement_sha256", "recovery_run_id"}
            and all(type(evidence[k]) is type(v) and evidence[k] == v
                    for k, v in STORAGE_QUARANTINE.items())
            and scope == dict(task_key="R1000-DISCOVERY-EXPANSION-INTAKE-20261017",
                             namespace="top500-20261017",
                             input_sha256=STORAGE_QUARANTINE["input_sha256"])
            and all(isinstance(evidence[k], str) and re.fullmatch(r"[0-9a-f]{64}", evidence[k])
                    for k in ("authorization_sha256", "external_proof_sha256", "native_settlement_sha256"))
            and type(evidence["recovery_run_id"]) is int
            and evidence["recovery_run_id"] > STORAGE_QUARANTINE["native_run_id"],
            "STORAGE_QUARANTINE_PROOF")


def verify_storage_hold(marker, state):
    require(isinstance(marker, dict) and set(marker) == {
        "schema", "scope", "source", "status", "reason", "symbols", "seed_sha256", "source_sha",
        "start", "end", "asof", "original_price_bytes_retained", "source_admission", "pit_verified",
        "historical_identity_verified", "commercial_use_authorized", "cohort_scope", "uncertain_storage"}
        and marker.get("status") == "HELD_UNCERTAIN_STORAGE", "STORAGE_QUARANTINE_PROOF")
    verify_storage_quarantine(marker.get("uncertain_storage"), state.get("cohort_scope"))
    require(marker.get("symbols") == STORAGE_QUARANTINE["symbols"]
            and marker.get("reason") == "DRIVE_CREATE_OUTCOME_UNKNOWN"
            and len(state.get("examined", [])) == 80
            and state["examined"][76:] == STORAGE_QUARANTINE["symbols"]
            and state.get("held") == STORAGE_QUARANTINE["symbols"]
            and len(state.get("completed", [])) == 76
            and isinstance(state.get("previous_checkpoint"), dict)
            and state["previous_checkpoint"].get("sha256") == STORAGE_QUARANTINE["checkpoint_sha256"]
            and state.get("last_collected") == state.get("last_no_bars") == []
            and state.get("last_held") == STORAGE_QUARANTINE["symbols"],
            "STORAGE_QUARANTINE_PREFIX")


def resume_state(drive: OwnerDrive, folder: str, file_id: str, sha: str,
                 seed_sha: str, start: str, end: str, *, scope=None):
    """Restore verified groups and separately quarantined invalid observations.

    examined is a contiguous discovery-queue prefix. completed contains only
    groups with verified original raw/split evidence (including genuine no-bar
    responses). held contains only invalid-data group members, never admitted.
    """
    if not file_id and not sha:
        return [], [], [], None
    require(isinstance(file_id, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", file_id)
            and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha),
            "RESUME_PAIR")
    asof = mapping_asof(end)
    original_ref = {"file_id": file_id, "sha256": sha}
    pointer = original_ref
    seen = set()
    expected = None
    finals = None
    for _ in range(MAX_CHECKPOINT_CHAIN):
        require(pointer["file_id"] not in seen, "RESUME_CYCLE")
        seen.add(pointer["file_id"])
        drive.check(pointer["file_id"], folder, folder=False)
        original = drive.read(pointer["file_id"], 2_000_000)
        require(digest(original) == pointer["sha256"], "RESUME_HASH")
        if "bytes" in pointer:
            require(len(original) == pointer["bytes"], "RESUME_HASH")
        if finals is None:
            original_ref = {"file_id": file_id, "sha256": sha,
                            "bytes": len(original)}
        state = decode(original)
        require(isinstance(state, dict) and state.get("schema") == SCHEMA
                and state.get("seed_sha256") == seed_sha
                and state.get("cohort_scope") == scope
                and state.get("start") == start and state.get("end") == end
                and state.get("asof") == asof
                and state.get("source") == SOURCE
                and state.get("state") == "PRIVATE_RESEARCH_ONLY"
                and isinstance(state.get("source_sha"), str)
                and re.fullmatch(r"[0-9a-f]{40}", state["source_sha"])
                and state.get("source_admission") is False
                and state.get("commercial_use_authorized") is False
                and state.get("historical_identity_verified") is False
                and state.get("pit_verified") is False,
                "RESUME_CONTEXT")
        examined = state.get("examined")
        done = state.get("completed")
        held = state.get("held")
        require(all(isinstance(x, list) for x in (examined, done, held))
                and examined and len(examined) <= 1500
                and len(set(examined)) == len(examined)
                and len(set(done)) == len(done)
                and len(set(held)) == len(held)
                and all(isinstance(x, str) and SYMBOL.fullmatch(x)
                        for x in examined + done + held)
                and set(done).isdisjoint(set(held))
                and set(examined) == set(done) | set(held),
                "RESUME_MEMBERSHIP")
        if finals is None:
            finals = (examined, done, held)
        elif (examined, done, held) != expected:
            raise Refused("RESUME_CHAIN_MEMBERSHIP")
        refs = state.get("last_objects")
        status = state.get("last_status")
        require(status in (("VERIFIED_RAW_SPLIT", "HELD_BAR_VALUE", "HELD_PROVIDER_ASSET", "HELD_UNCERTAIN_STORAGE")
                           if scope else ("VERIFIED_RAW_SPLIT", "HELD_BAR_VALUE"))
                and isinstance(refs, list)
                and len(refs) == (3 if status == "VERIFIED_RAW_SPLIT" else 1),
                "RESUME_OBJECTS")
        if status == "VERIFIED_RAW_SPLIT":
            raw_pack = _private_object(drive, folder, refs[0])
            normalized_pack = _private_object(drive, folder, refs[1])
            receipt_bytes = _private_object(drive, folder, refs[2], 2_000_000)
            receipt = decode(receipt_bytes)
            require(isinstance(receipt, dict)
                    and receipt.get("schema") == SCHEMA
                    and receipt.get("scope") == "PRIVATE_RESEARCH_ONLY"
                    and receipt.get("source") == SOURCE
                    and receipt.get("seed_sha256") == seed_sha
                    and receipt.get("cohort_scope") == scope
                    and receipt.get("start") == start
                    and receipt.get("end") == end
                    and receipt.get("asof") == asof
                    and receipt.get("source_sha") == state["source_sha"]
                    and receipt.get("pit_verified") is False
                    and receipt.get("historical_identity_verified") is False
                    and receipt.get("commercial_use_authorized") is False
                    and receipt.get("source_admission") is False
                    and receipt.get("readback_verified") is True
                    and receipt.get("raw_object") == refs[0]
                    and receipt.get("normalized_object") == refs[1],
                    "RESUME_RECEIPT_BINDING")
            verify_archived_group(raw_pack, normalized_pack, receipt)
            group = receipt.get("symbols")
            collected = receipt.get("collected")
            absent = receipt.get("no_bars")
            require(isinstance(group, list)
                    and 1 <= len(group) <= GROUP_SIZE
                    and len(group) == len(set(group))
                    and all(isinstance(s, str) and SYMBOL.fullmatch(s)
                            for s in group)
                    and isinstance(collected, list)
                    and isinstance(absent, list)
                    and set(collected).isdisjoint(set(absent))
                    and set(collected) | set(absent) == set(group)
                    and state.get("last_collected") == collected
                    and state.get("last_no_bars") == absent
                    and state.get("last_held") == []
                    and done[-len(group):] == group,
                    "RESUME_CHAIN_MEMBERSHIP")
            prefix_done = done[:-len(group)]
            prefix_held = held
        else:
            marker = decode(_private_object(drive, folder, refs[0],
                                            2_000_000))
            require(isinstance(marker, dict)
                    and marker.get("schema") == SCHEMA
                    and marker.get("scope") == "PRIVATE_RESEARCH_ONLY"
                    and marker.get("status") == status
                    and marker.get("reason") == ("DRIVE_CREATE_OUTCOME_UNKNOWN" if status == "HELD_UNCERTAIN_STORAGE" else
                        "PROVIDER_ASSET_UNAVAILABLE" if status == "HELD_PROVIDER_ASSET" else "BAR_VALUE")
                    and marker.get("source") == SOURCE
                    and marker.get("seed_sha256") == seed_sha
                    and marker.get("cohort_scope") == scope
                    and marker.get("start") == start
                    and marker.get("end") == end
                    and marker.get("asof") == asof
                    and marker.get("source_sha") == state["source_sha"]
                    and marker.get("source_admission") is False
                    and marker.get("commercial_use_authorized") is False
                    and marker.get("pit_verified") is False
                    and marker.get("historical_identity_verified") is False
                    and marker.get("original_price_bytes_retained") is False,
                    "RESUME_HELD_RECEIPT")
            group = marker.get("symbols")
            if status == "HELD_UNCERTAIN_STORAGE":
                verify_storage_hold(marker, state)
            if status == "HELD_PROVIDER_ASSET":
                verify_asset_evidence(marker.get("asset_precheck"), group)
                require(all(not asset_supported(row) for row in marker["asset_precheck"]),
                        "EXTERNAL_ASSET_EVIDENCE")
            require(isinstance(group, list)
                    and 1 <= len(group) <= GROUP_SIZE
                    and len(group) == len(set(group))
                    and all(isinstance(s, str) and SYMBOL.fullmatch(s)
                            for s in group)
                    and state.get("last_held") == group
                    and state.get("last_collected") == []
                    and state.get("last_no_bars") == []
                    and held[-len(group):] == group,
                    "RESUME_HELD_MEMBERSHIP")
            prefix_done = done
            prefix_held = held[:-len(group)]
        require(examined[-len(group):] == group,
                "RESUME_CHAIN_MEMBERSHIP")
        prefix_examined = examined[:-len(group)]
        previous = state.get("previous_checkpoint")
        if previous is None:
            require(not prefix_examined and not prefix_done and not prefix_held,
                    "RESUME_CHAIN_TRUNCATED")
            return (*finals, original_ref)
        require(isinstance(previous, dict)
                and isinstance(previous.get("file_id"), str)
                and re.fullmatch(r"[A-Za-z0-9_-]{10,100}",
                                 previous["file_id"])
                and isinstance(previous.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", previous["sha256"])
                and type(previous.get("bytes")) is int
                and previous["bytes"] > 0 and prefix_examined,
                "RESUME_CHAIN")
        expected = (prefix_examined, prefix_done, prefix_held)
        pointer = previous
    raise Refused("RESUME_CHAIN_LIMIT")



def capture_one_group(drive: OwnerDrive, folder: str, symbols: list[str],
                      start: str, end: str, key: str, secret: str,
                      seed_sha: str, source_sha: str, *, get=None, scope=None, asset_evidence=None):
    raw_members, evidence, results = {}, [], {}
    for adjustment in ("raw", "split"):
        members, grouped, pages = request_pages(
            symbols, adjustment, start, end, key, secret,
            **({"get": get} if get is not None else {}),
        )
        for member, raw in members.items():
            # Different response bodies must not share the same hash.
            require(member not in raw_members or raw_members[member] == raw,
                    "PACK_HASH_COLLISION")
            raw_members[member] = raw
        evidence.extend(pages)
        results[adjustment] = {
            symbol: normalize(grouped[symbol], symbol, adjustment, start, end)
            for symbol in symbols
        }
    collected, missing, normalized = [], [], []
    for symbol in symbols:
        raw = results["raw"][symbol]
        split = results["split"][symbol]
        require([r["date"] for r in raw] == [r["date"] for r in split],
                "RAW_SPLIT_GRID_MISMATCH")
        if not raw:
            missing.append(symbol)
            continue
        collected.append(symbol)
        normalized.extend(raw)
        normalized.extend(split)
    # A verified all-missing group is an examined research result, not a
    # source-admitted price series; persist its evidence so later names advance.
    meta = {
        "schema": SCHEMA, "source": SOURCE, "symbols": list(symbols),
        "collected": collected, "no_bars": missing, "start": start, "end": end,
        "asof": mapping_asof(end),
        "seed_sha256": seed_sha, "source_sha": source_sha,
        "pages": evidence, "raw_adjustments": ["raw", "split"],
        "historical_identity_verified": False, "pit_verified": False,
        "source_admission": False, "commercial_use_authorized": False,
    }
    if scope is not None:
        meta.update(cohort_scope=scope, asset_precheck=asset_evidence)
    raw_members["capture.json"] = encoded(meta)
    zipped = zip_bytes(raw_members)
    require(0 < len(zipped) < 16_000_000, "PACK_BUDGET")
    require(sum(len(v) for v in raw_members.values()) <= 128_000_000, "PACK_BUDGET")
    raw_obj = persist_object(drive, folder, zipped, ".zip")
    normalized_bytes = gzip.compress(
        b"".join(encoded(r) for r in normalized), mtime=0,
    )
    require(len(normalized_bytes) < 16_000_000, "PACK_BUDGET")
    norm_obj = persist_object(drive, folder, normalized_bytes, ".jsonl.gz")
    receipt = {
        "schema": SCHEMA, "scope": "PRIVATE_RESEARCH_ONLY",
        "source": SOURCE,
        "source_sha": source_sha, "seed_sha256": seed_sha,
        "start": start, "end": end, "asof": mapping_asof(end),
        "symbols": symbols, "collected": collected, "no_bars": missing,
        "pages": len(evidence), "rows": len(normalized),
        "raw_object": raw_obj, "normalized_object": norm_obj,
        "readback_verified": True, "source_admission": False,
        "pit_verified": False, "historical_identity_verified": False,
        "commercial_use_authorized": False,
    }
    if scope is not None:
        receipt.update(cohort_scope=scope, asset_precheck=asset_evidence)
    rec_obj = persist_object(drive, folder, encoded(receipt), ".json")
    return [raw_obj, norm_obj, rec_obj], collected, missing, len(normalized)


def _collect(args, *, drive_factory, get=None, on_group=None, expected_examined=None, external=None,
             fixed_profile=None):
    require(os.getenv("A1_PRIVATE_RESEARCH_AUTHORIZED") == "true",
            "USER_AUTHORIZATION_MISSING")
    require(os.getenv("ALPACA_NONCOMMERCIAL_ACKNOWLEDGED") == "true",
            "PROVIDER_TERMS_NOT_ACKNOWLEDGED")
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and os.environ.get("GITHUB_REF") == "refs/heads/master",
            "REPOSITORY_SCOPE")
    source_sha = os.environ.get("GITHUB_SHA", "")
    require(re.fullmatch(r"[0-9a-f]{40}", source_sha), "SOURCE_SHA")
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_API_SECRET", "").strip()
    require(key and secret, "CREDENTIALS_MISSING")
    if fixed_profile is None:
        require(args.start == MIN_START and MIN_START < args.end <= date.today().isoformat(),
                "DATE_SCOPE")
    else:
        require(fixed_profile == FIXED_SPY_PROFILE and args.start == FIXED_SPY_START
                and args.end == FIXED_SPY_END and args.end <= date.today().isoformat()
                and args.max_new_symbols == 1 and args.resume_file_id == args.resume_sha256 == ""
                and external == dict(input_csv=FIXED_SPY_INPUT.decode(), scope=_fixed_spy_scope()),
                "SPY665_SCOPE")
    require(1 <= args.max_new_symbols <= 32, "BATCH_SCOPE")
    scope, quarantine = None, None
    if external is None:
        seed = SEED.read_bytes()
        names = cohort(seed)
    else:
        require(isinstance(external, dict) and set(external) in (
                    {"input_csv", "scope"}, {"input_csv", "scope", "storage_quarantine"})
                and callable(get), "EXTERNAL_COHORT_SCOPE")
        scope = external_scope(external["scope"])
        seed = external["input_csv"].encode("utf-8")
        names = external_cohort(seed)
        require(digest(seed) == scope["input_sha256"], "EXTERNAL_COHORT_HASH")
        if "storage_quarantine" in external:
            quarantine = external["storage_quarantine"]
            verify_storage_quarantine(quarantine, scope)
    seed_sha = digest(seed)
    with tempfile.TemporaryDirectory(prefix="a1-alpaca-private-") as tmp:
        drive = drive_factory(args.private_root_folder_id, tmp)
        drive.check(args.private_data_folder_id, drive.root_id)
        examined, completed, held_invalid, prior = resume_state(
            drive, args.private_data_folder_id,
            args.resume_file_id, args.resume_sha256,
            seed_sha, args.start, args.end, **({"scope": scope} if scope is not None else {}),
        )
        # The discovery queue is immutable; held groups do not become
        # completed data and cannot silently create holes in the worklist.
        require(examined == names[:len(examined)], "RESUME_UNIVERSE")
        require(expected_examined is None or len(examined) == expected_examined,
                "CAMPAIGN_EXAMINED_PARENT")
        require(set(completed).isdisjoint(set(held_invalid))
                and set(examined) == set(completed) | set(held_invalid),
                "RESUME_UNIVERSE")
        selected = names[len(examined):len(examined) + args.max_new_symbols]
        require(bool(selected), "COHORT_COMPLETE")
        if quarantine is not None:
            require(len(examined) == len(completed) == 76 and held_invalid == []
                    and selected == STORAGE_QUARANTINE["symbols"] and args.max_new_symbols == 4
                    and isinstance(prior, dict)
                    and prior["sha256"] == STORAGE_QUARANTINE["checkpoint_sha256"]
                    and quarantine["recovery_run_id"] == int(os.environ.get("GITHUB_RUN_ID", "0")),
                    "STORAGE_QUARANTINE_PREFIX")
        checkpoint, row_count = prior, 0
        held_this_batch = []
        no_data_this_batch = []
        asset_rows = precheck_assets(selected, key, secret, get) if scope is not None and quarantine is None else None
        offset = 0
        while offset < len(selected):
            size = GROUP_SIZE
            unavailable = asset_rows is not None and not asset_supported(asset_rows[offset])
            if asset_rows is not None:
                size = 1
                while size < GROUP_SIZE and offset+size < len(selected) and (
                        not asset_supported(asset_rows[offset+size])) == unavailable:
                    size += 1
            group = selected[offset:offset + size]
            assets = asset_rows[offset:offset+len(group)] if asset_rows is not None else None
            offset += len(group)
            try:
                if quarantine is not None:
                    marker = dict(schema=SCHEMA, scope="PRIVATE_RESEARCH_ONLY", source=SOURCE,
                        status="HELD_UNCERTAIN_STORAGE", reason="DRIVE_CREATE_OUTCOME_UNKNOWN",
                        symbols=group, seed_sha256=seed_sha, source_sha=source_sha,
                        start=args.start, end=args.end, asof=mapping_asof(args.end),
                        original_price_bytes_retained=False, source_admission=False, pit_verified=False,
                        historical_identity_verified=False, commercial_use_authorized=False,
                        cohort_scope=scope, uncertain_storage=quarantine)
                    # This new typed marker cannot equal any old price pack/body.
                    # No old raw/normalized/receipt bytes are generated or posted.
                    objs = [persist_object(drive, args.private_data_folder_id, encoded(marker), ".json")]
                    accepted, missing, rows = [], [], 0
                    held_invalid.extend(group)
                    held_this_batch.extend(group)
                    status, last_held = "HELD_UNCERTAIN_STORAGE", group
                elif unavailable:
                    raise Refused("PROVIDER_ASSET_UNAVAILABLE")
                else:
                    objs, accepted, missing, rows = capture_one_group(
                        drive, args.private_data_folder_id, group,
                        args.start, args.end, key, secret, seed_sha,
                        source_sha,
                        **({"get": get} if get is not None else {}),
                        **({"scope": scope, "asset_evidence": assets} if scope is not None else {}),
                    )
            except Refused as exc:
                # A single invalid numerical bar gives no eligible data
                # for any group member; retain a bounded, sanitized hold
                # without original vendor responses. Only this exact
                # deterministic error is recoverable. Auth, quota,
                # incomplete pagination, identity and storage failures
                # remain terminal.
                if str(exc) != "BAR_VALUE" and not (scope is not None and unavailable
                                                  and str(exc) == "PROVIDER_ASSET_UNAVAILABLE"):
                    raise
                held_status = "HELD_PROVIDER_ASSET" if unavailable else "HELD_BAR_VALUE"
                marker = {
                    "schema": SCHEMA, "scope": "PRIVATE_RESEARCH_ONLY",
                    "status": held_status, "reason": str(exc),
                    "symbols": group, "source": SOURCE,
                    "seed_sha256": seed_sha,
                    "source_sha": source_sha,
                    "start": args.start, "end": args.end,
                    "asof": mapping_asof(args.end),
                    "original_price_bytes_retained": False,
                    "source_admission": False, "pit_verified": False,
                    "historical_identity_verified": False,
                    "commercial_use_authorized": False,
                }
                if scope is not None:
                    marker.update(cohort_scope=scope, asset_precheck=assets)
                objs = [persist_object(
                    drive, args.private_data_folder_id,
                    encoded(marker), ".json",
                )]
                accepted, missing, rows = [], [], 0
                held_invalid.extend(group)
                held_this_batch.extend(group)
                status = held_status
                last_held = group
            else:
                if quarantine is None:
                    completed.extend(group)
                    no_data_this_batch.extend(missing)
                    status = "VERIFIED_RAW_SPLIT"
                    last_held = []
            examined.extend(group)
            row_count += rows
            state = {
                "schema": SCHEMA, "state": "PRIVATE_RESEARCH_ONLY",
                "source": SOURCE, "seed_sha256": seed_sha,
                "source_sha": source_sha,
                "start": args.start, "end": args.end,
                "asof": mapping_asof(args.end),
                "examined": examined, "completed": completed,
                "held": held_invalid,
                "last_status": status,
                "last_objects": objs, "previous_checkpoint": checkpoint,
                "last_collected": accepted, "last_no_bars": missing,
                "last_held": last_held,
                "historical_identity_verified": False, "pit_verified": False,
                "source_admission": False, "commercial_use_authorized": False,
            }
            if scope is not None:
                state["cohort_scope"] = scope
            checkpoint = persist_object(
                drive, args.private_data_folder_id, encoded(state), ".json",
            )
            if on_group is not None:
                on_group(drive, state, checkpoint)
            print(json.dumps({
                "status": "PRIVATE_CHECKPOINT_SAVED",
                "last_group_status": status,
                "total_examined": len(examined),
                "verified_or_no_bar": len(completed),
                "held_invalid_count": len(held_invalid),
                "checkpoint": checkpoint,
                "source_admission": False,
            }, sort_keys=True))
        result = {
            "status": ("PRIVATE_HISTORY_PARTIAL_HELD" if held_this_batch
                       else "PRIVATE_HISTORY_BATCH_RESTORED"),
            "seed_count": len(names), "attempted_new": len(selected),
            "total_examined": len(examined),
            "verified_or_no_bar": len(completed),
            "total_held_invalid": len(held_invalid),
            "held_this_batch": len(held_this_batch),
            "no_data_this_batch": len(no_data_this_batch),
            "rows_new": row_count, "checkpoint": checkpoint,
            "public_provider_bytes_uploaded": False,
            "source_admission": False, "economic_authority": False,
        }
        print(json.dumps(result, sort_keys=True))
        return result


def _verify_campaign_group(c, drive, folder, state, checkpoint, meter, *, reused_source=False, fixed_spy=False, new3=False):
    from tools import alpaca_sip_private_backfill_v1 as cap
    start, end, genesis = "2016-01-04", "2026-10-14", None
    if new3:
        c.require(not reused_source and not fixed_spy
            and meter.identity.get("allocation_profile") == NEW3_PROFILE
            and meter.identity.get("allocation_comment_id") == 6474160005
            and meter.identity.get("cohort_scope") == _new3_scope()
            and state.get("start") == MIN_START and state.get("end") == NEW3_END
            and state.get("seed_sha256") == digest(NEW3_INPUT)
            and state.get("source_sha") == c.os.environ.get("GITHUB_SHA"), "NEW3_GROUP_SCOPE")
        start, end, genesis = MIN_START, NEW3_END, c.external_genesis(_new3_scope())
    if fixed_spy:
        c.require(not reused_source and meter.identity.get("fixed_profile") == cap.FIXED_SPY_PROFILE
                and meter.identity.get("cohort_scope") == cap._fixed_spy_scope()
                and state.get("start") == cap.FIXED_SPY_START and state.get("end") == cap.FIXED_SPY_END
                and state.get("seed_sha256") == cap.digest(cap.FIXED_SPY_INPUT)
                and state.get("source_sha") == c.os.environ.get("GITHUB_SHA"), "SPY665_GROUP_SCOPE")
        start, end, genesis = cap.FIXED_SPY_START, cap.FIXED_SPY_END, cap._fixed_spy_genesis()
    stored = cap._private_object(drive, folder, checkpoint)
    scope = meter.identity.get("cohort_scope")
    previous = state.get("previous_checkpoint")
    first_external = scope is not None and meter.examined == 0
    c.require(c.decode(stored) == state and state.get("cohort_scope") == scope
            and ((previous is None and meter.checkpoint_sha == (genesis or c.external_genesis(scope))) if first_external
                 else isinstance(previous, dict) and previous.get("sha256") == meter.checkpoint_sha),
            "CAMPAIGN_CHECKPOINT_CHAIN")
    objects = state["last_objects"]
    if state["last_status"] == "VERIFIED_RAW_SPLIT":
        c.require(len(objects) == 3, "CAMPAIGN_GROUP_OBJECTS")
        receipt = c.decode(cap._private_object(drive, folder, objects[2]))
        raw = cap._private_object(drive, folder, objects[0])
        normalized = cap._private_object(drive, folder, objects[1])
        expected_source = c.os.environ["GITHUB_SHA"]
        if reused_source and "price174_reuse" in meter.identity:
            expected_source = c._revision_module().price174_reuse_source(c._module(),state,objects,receipt,meter,raw,normalized)
        elif reused_source:
            reuse = meter.identity.get("drive_orphan_reuse")
            c.verify_drive_reuse(reuse, meter.identity)
            recovery_spec = c.MATERIALIZATION_RECOVERY if "materialization" in reuse else c.DRIVE_RECOVERY
            c.require(isinstance(reuse, dict) and receipt.get("recovered_from") == reuse
                    and meter.identity.get("recovery_run") == recovery_spec["run_id"]
                    and meter.identity.get("examined_before") == meter.examined == c.DRIVE_RECOVERY["examined"]
                    and meter.checkpoint_sha == c.DRIVE_RECOVERY["checkpoint_sha256"]
                    and receipt.get("symbols") == ["TWST", "UBS", "UL", "UPST"]
                    and objects[0]["sha256"] == reuse.get("raw_sha256")
                    and objects[1]["sha256"] == reuse.get("normalized_sha256")
                    and reuse.get("failed_run_id") == recovery_spec["run_id"]
                    and reuse.get("capture_source_sha") == c.DRIVE_RECOVERY["master"]
                    and reuse.get("derivation_source_sha") == expected_source
                    and reuse.get("derivation_run_id") == meter.identity["run_id"]
                    and reuse.get("derivation_auth_sha256") == meter.identity["auth_sha256"]
                    and reuse.get("parent_checkpoint_sha256") == c.DRIVE_RECOVERY["checkpoint_sha256"]
                    and state.get("recovered_from") == reuse
                    and state.get("source_sha") == c.DRIVE_RECOVERY["master"]
                    and reuse.get("external_proof_sha256") == meter.identity["external_proof_sha256"],
                    "EXTERNAL_ORPHAN_SOURCE")
            expected_source = c.DRIVE_RECOVERY["master"]
        c.require(receipt.get("raw_object") == objects[0]
                and receipt.get("normalized_object") == objects[1]
                and receipt.get("source_sha") == expected_source
                and receipt.get("seed_sha256") == (scope["input_sha256"] if scope else c.SEED_SHA)
                and receipt.get("cohort_scope") == scope
                and receipt.get("start") == start
                and receipt.get("end") == end
                and receipt.get("collected") == state["last_collected"]
                and receipt.get("no_bars") == state["last_no_bars"], "CAMPAIGN_GROUP_RECEIPT")
        c.require(all(receipt.get(k) is False for k in
                    ("source_admission", "pit_verified", "historical_identity_verified",
                     "commercial_use_authorized")), "CAMPAIGN_GROUP_AUTHORITY")
        cap.verify_archived_group(raw, normalized, receipt)
        if reused_source and "materialization" in locals().get("reuse",{}):
            c.require(c.digest(cap.gzip.decompress(normalized)) == reuse["materialization"]["rows_sha256"],
                    "EXTERNAL_MATERIAL_ROWS")
        meter.rows += receipt["rows"]
        meter.states["VALID_COLLECTED"] += len(receipt["collected"])
        meter.states["VERIFIED_NO_DATA"] += len(receipt["no_bars"])
    else:
        c.require(state["last_status"] in (("HELD_BAR_VALUE", "HELD_PROVIDER_ASSET", "HELD_UNCERTAIN_STORAGE") if scope else ("HELD_BAR_VALUE",))
                and len(objects) == 1,
                "CAMPAIGN_GROUP_STATUS")
        marker = c.decode(cap._private_object(drive, folder, objects[0]))
        asset_hold = state["last_status"] == "HELD_PROVIDER_ASSET"
        storage_hold = state["last_status"] == "HELD_UNCERTAIN_STORAGE"
        c.require(marker.get("status") == state["last_status"]
                and marker.get("reason") == ("DRIVE_CREATE_OUTCOME_UNKNOWN" if storage_hold else "PROVIDER_ASSET_UNAVAILABLE" if asset_hold else "BAR_VALUE")
                and marker.get("symbols") == state["last_held"]
                and marker.get("source_sha") == c.os.environ["GITHUB_SHA"]
                and marker.get("seed_sha256") == (scope["input_sha256"] if scope else c.SEED_SHA)
                and marker.get("cohort_scope") == scope
                and marker.get("start") == start and marker.get("end") == end
                and marker.get("original_price_bytes_retained") is False,
                "CAMPAIGN_HELD_MARKER")
        if storage_hold:
            cap.verify_storage_hold(marker,state)
            evidence = marker["uncertain_storage"]
            c.require(meter.examined == c.NATIVE18_RECOVERY["examined"]
                    and meter.identity.get("recovery_run") == c.NATIVE18_RECOVERY["run_id"]
                    and evidence["authorization_sha256"] == meter.identity.get("auth_sha256")
                    and evidence["external_proof_sha256"] == meter.identity.get("external_proof_sha256")
                    and evidence["native_settlement_sha256"] == meter.identity.get("native18_settlement_sha256")
                    and evidence["recovery_run_id"] == meter.identity.get("run_id"),
                    "EXTERNAL_NATIVE18_HELD")
            meter.identity["uncertain_storage_hold"] = dict(evidence=evidence,
                marker_sha256=objects[0]["sha256"],checkpoint_sha256=checkpoint["sha256"])
        if asset_hold:
            cap.verify_asset_evidence(marker.get("asset_precheck"), state["last_held"])
            c.require(all(not cap.asset_supported(row) for row in marker["asset_precheck"]),
                    "EXTERNAL_ASSET_EVIDENCE")
        c.require(all(marker.get(k) is False for k in
                    ("source_admission", "pit_verified", "historical_identity_verified",
                     "commercial_use_authorized")), "CAMPAIGN_GROUP_AUTHORITY")
        meter.states["QUARANTINED"] += len(state["last_held"])
    meter.examined = len(state["examined"])
    meter.checkpoint_sha = checkpoint["sha256"]
    # Flush the private reference before publishing its SHA in the public
    # meter. No provider bytes enter this existing Actions log surface.
    print("CAMPAIGN_VERIFIED_CHECKPOINT " + c.json.dumps(checkpoint, sort_keys=True), flush=True)
    meter.save()  # Advances only after a separate, semantic readback.


def _fixed_spy_authorization(c, auth):
    """Structural validation only; neither a local dict nor tests grant I/O."""
    extra = {"fixed_profile", "parent_manifest_reference", "parent_manifest_sha256",
             "subcaps", "wall_seconds", "phases", "not_before_utc", "expires_at_utc"}
    require(isinstance(auth, dict) and set(auth) == c.AUTH_FIELDS | extra
            and auth.get("schema") == "a1-fixed-spy-authorization-v1"
            and auth.get("task_key") == c.TASK
            and auth.get("fixed_profile") == FIXED_SPY_PROFILE
            and auth.get("scope_approved") is True
            and auth.get("private_noncommercial") is True, "SPY665_AUTHORIZATION")
    require(auth.get("start") == FIXED_SPY_START and auth.get("end") == FIXED_SPY_END
            and auth.get("seed_sha256") == digest(FIXED_SPY_INPUT)
            and auth.get("initial_checkpoint_sha256") == _fixed_spy_genesis()
            and auth.get("initial_checkpoint_file_id") == ""
            and auth.get("transfer_definition") == c.METRIC, "SPY665_SCOPE")
    require(auth.get("limits") == c.CONTINUED_LIMITS
            and all(type(auth["limits"][k]) is int for k in c.LIMITS), "SPY665_LIMITS")
    caps = dict(provider_gets=3, drive_requests=64, drive_bytes=64*1024**2,
                storage_bytes=4*1024**2)
    require(isinstance(auth.get("subcaps"), dict) and set(auth["subcaps"]) == set(caps),
            "SPY665_SUBCAP")
    for key in caps:
        c.integer(auth["subcaps"][key], caps[key], "SPY665_SUBCAP")
    require(type(auth.get("wall_seconds")) is int and 1 <= auth["wall_seconds"] <= 900
            and auth.get("phases") in (["capture"], ["preflight", "capture"]),
            "SPY665_PHASES")
    require(c.utc(auth["not_before_utc"]) < c.utc(auth["expires_at_utc"])
            <= c.utc(auth["not_before_utc"]) + timedelta(hours=48), "SPY665_CLOCK")
    require(type(auth.get("workflow_run_floor")) is int
            and 1 <= auth["workflow_run_floor"] <= 1_000_000_000
            and isinstance(auth.get("expected_master"), str)
            and re.fullmatch(r"[0-9a-f]{40}", auth["expected_master"]), "SPY665_SOURCE")
    require(isinstance(auth.get("code_pins"), dict)
            and set(auth["code_pins"]) == set(c.PINS + (c.REVISION_MODULE,))
            and all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
                    for v in auth["code_pins"].values()), "SPY665_CODE_PINS")
    for key in ("private_root_folder_id", "private_data_folder_id"):
        require(isinstance(auth.get(key), str)
                and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", auth[key]), "SPY665_PRIVATE_REF")
    for key in ("approval_reference", "account_permission_reference"):
        require(isinstance(auth.get(key), str) and 0 < len(auth[key]) <= 512,
                "SPY665_ACCOUNT_REFERENCE")
    require(isinstance(auth.get("owner_permission_id"), str)
            and 0 < len(auth["owner_permission_id"]) <= 128
            and isinstance(auth.get("credential_binding"), str)
            and re.fullmatch(r"[0-9a-f]{64}", auth["credential_binding"])
            and isinstance(auth.get("parent_manifest_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", auth["parent_manifest_sha256"])
            and isinstance(auth.get("parent_manifest_reference"), str)
            and re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",
                             auth["parent_manifest_reference"]), "SPY665_PARENT_BINDING")
    require(len(encoded(auth)) <= 12000, "CAMPAIGN_CONTROL_SIZE")
    return digest(encoded(auth))


def _fixed_spy_owner_record(c, reference, tag, *, window=None):
    """Canonical immutable OWNER record, never caller-supplied approved=true."""
    match = re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-([0-9]+)",
                         reference or "")
    require(match is not None, "SPY665_OWNER_RECORD")
    comment = c.gh_json(f"repos/{c.REPO}/issues/comments/{match[1]}")
    require(isinstance(comment, dict) and type(comment.get("id")) is int
            and comment["id"] == int(match[1])
            and comment.get("issue_url") == f"https://api.github.com/repos/{c.REPO}/issues/448"
            and comment.get("author_association") == "OWNER"
            and comment.get("user", {}).get("type") == "User"
            and type(comment["user"].get("id")) is int and comment["user"]["id"] > 0
            and comment.get("created_at") == comment.get("updated_at")
            and c.utc(comment.get("created_at")) <= c.utc()
            and isinstance(comment.get("body"), str)
            and len(comment["body"].encode()) <= 60000, "SPY665_OWNER_RECORD")
    if window is not None:
        require(c.utc(window[0]) <= c.utc(comment["created_at"]) < c.utc(window[1]),
                "SPY665_OWNER_CLOCK")
    lines = [line[len(tag):] for line in comment["body"].splitlines() if line.startswith(tag)]
    require(len(lines) == 1, "SPY665_OWNER_RECORD")
    return decode(lines[0])


def _fixed_spy_parent(c, auth):
    parent = _fixed_spy_owner_record(c, auth["parent_manifest_reference"],
                                     "A1_SIP_CLOSED_PARENT_MANIFEST ")
    fields = {"schema", "family_genesis_sha256", "family_prefix_count",
              "family_prefix_first_sha256", "family_prefix_head_sha256", "runs", "used",
              "active_seconds", "event_count", "closed", "accepted_evidence_manifest_sha256",
              "independent_review_sha256", "bindings", "workflow_run_floor"}
    require(isinstance(parent, dict) and set(parent) == fields
            and digest(encoded(parent)) == auth["parent_manifest_sha256"]
            and parent.get("schema") == "a1-sip-closed-parent-manifest-v1"
            and parent.get("closed") is True
            and parent.get("family_genesis_sha256") == c.external_family_genesis()
            and parent.get("workflow_run_floor") == auth["workflow_run_floor"], "SPY665_PARENT")
    for key in ("family_prefix_first_sha256", "family_prefix_head_sha256",
                "accepted_evidence_manifest_sha256", "independent_review_sha256"):
        require(isinstance(parent.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", parent[key]),
                "SPY665_PARENT")
    require(type(parent.get("family_prefix_count")) is int
            and 1 <= parent["family_prefix_count"] <= 1000
            and isinstance(parent.get("runs"), list) and 1 <= len(parent["runs"]) <= 40
            and parent.get("event_count") == len(parent["runs"])
            and type(parent["event_count"]) is int
            and isinstance(parent.get("used"), dict) and set(parent["used"]) == set(c.LIMITS),
            "SPY665_PARENT")
    used = dict.fromkeys(c.LIMITS, 0)
    active, ids, nonces, numbers = 0, [], [], []
    for row in parent["runs"]:
        require(isinstance(row, dict) and set(row) == {"id", "run_number", "nonce", "display_title", "head_sha",
                    "auth_sha256", "meter_or_closure_sha256", "usage", "active_seconds"}
                and type(row.get("id")) is int and row["id"] > 0
                and type(row.get("run_number")) is int and row["run_number"] > 0
                and isinstance(row.get("nonce"), str)
                and re.fullmatch(c.PREFIX+r"[0-9a-f]{24}", row["nonce"])
                and isinstance(row.get("head_sha"), str) and re.fullmatch(r"[0-9a-f]{40}", row["head_sha"])
                and isinstance(row.get("usage"), dict) and set(row["usage"]) == set(c.LIMITS),
                "SPY665_PARENT_VECTOR")
        require(isinstance(row.get("display_title"), str)
                and re.fullmatch("a1-sip " + re.escape(row["nonce"])
                    + r"(?: native-read(?:39085031884|39235028468))?", row["display_title"]),
                "SPY665_PARENT_TITLE")
        for key in ("auth_sha256", "meter_or_closure_sha256"):
            require(isinstance(row.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", row[key]),
                    "SPY665_PARENT_VECTOR")
        for key in used:
            used[key] += c.integer(row["usage"][key], c.CONTINUED_LIMITS[key])
        active += c.integer(row["active_seconds"], 43200)
        ids.append(row["id"]); nonces.append(row["nonce"]); numbers.append(row["run_number"])
    require(ids == sorted(set(ids)) and numbers == sorted(set(numbers))
            and len(set(nonces)) == len(nonces)
            and used == parent["used"] and any(used.values())
            and type(parent.get("active_seconds")) is int and active == parent["active_seconds"]
            and active <= 43200, "SPY665_PARENT_ACCOUNTING")
    for key in used:
        c.integer(used[key], c.CONTINUED_LIMITS[key])
    require(parent.get("bindings") == dict(owner_sha256=digest(auth["owner_permission_id"].encode()),
                                            credential_binding=auth["credential_binding"]),
            "SPY665_ACCOUNT_BINDING")
    return parent


def _fixed_spy_grant(c, auth, reference):
    h = _fixed_spy_authorization(c, auth)
    grant = _fixed_spy_owner_record(c, reference, "A1_SIP_FIXED_SPY_EXECUTION ",
                    window=(auth["not_before_utc"], auth["expires_at_utc"]))
    expected = dict(schema="a1-fixed-spy-execution-v1", auth_sha256=h,
        parent_manifest_sha256=auth["parent_manifest_sha256"], profile=FIXED_SPY_PROFILE,
        start=FIXED_SPY_START, end=FIXED_SPY_END, input_sha256=digest(FIXED_SPY_INPUT),
        eligible_purpose="PRIVATE_NONCOMMERCIAL_RESEARCH", current_account_reviewed=True,
        supplier_rights_verified=False, source_admission=False, economic_authority=False,
        not_before_utc=auth["not_before_utc"], expires_at_utc=auth["expires_at_utc"],
        account_permission_reference_sha256=digest(auth["account_permission_reference"].encode()))
    require(grant == expected and c.utc(auth["not_before_utc"]) <= c.utc()
            < c.utc(auth["expires_at_utc"]), "SPY665_EXECUTION_GRANT")
    return digest(encoded(grant))


def _fixed_spy_noncollection_run(c, run):
    """Recognize one failed historical workflow-validation stub, never a push class.

    Its immutable workflow blob 93a38491a0180e0ba2b99e3a6086fc79c741c76e
    has invalid YAML and permits capture only for workflow_dispatch on master.
    Canonical runnerless review checks must still match on every observation.
    This classification refunds no provider, storage or platform expenditure.
    """
    if run.get("id") != 39388523155:
        return False
    expected = dict(id=39388523155, run_number=98, event="push", run_attempt=1,
        name=".github/workflows/alpaca_sip_private_backfill_v1.yml",
        path=".github/workflows/alpaca_sip_private_backfill_v1.yml", workflow_id=382519204,
        head_sha="284abcb6a90549d9fe047fce679c8695020fdefd",
        head_branch="task/a1-named-read39235028468-20261019",
        display_title="fix(source): bind renewed read392 window to protected deployment",
        status="completed", conclusion="failure", check_suite_id=106734505787,
        created_at="2026-10-20T07:44:30Z", updated_at="2026-10-20T07:44:30Z",
        run_started_at="2026-10-20T07:44:30Z")
    require(all(type(run.get(key)) is type(value) and run[key] == value
                for key, value in expected.items()),
            "SPY665_NONCOLLECTION_RUN")
    jobs = c.gh_json(f"repos/{c.REPO}/actions/runs/39388523155/jobs?per_page=100")
    require(isinstance(jobs, dict) and type(jobs.get("total_count")) is int
            and jobs["total_count"] == 2 and isinstance(jobs.get("jobs"), list)
            and len(jobs["jobs"]) == 2, "SPY665_NONCOLLECTION_JOBS")
    identities = ((118514193309, "review_head_observed", "success", "2026-10-20T07:44:41Z"),
                  (118514203527, "review_complete", "failure", "2026-10-20T07:44:42Z"))
    require(all(isinstance(job, dict) and type(job.get("id")) is int for job in jobs["jobs"])
            and {job["id"] for job in jobs["jobs"]} == {row[0] for row in identities},
            "SPY665_NONCOLLECTION_JOBS")
    for job_id, name, conclusion, clock in identities:
        job = next(job for job in jobs["jobs"] if job["id"] == job_id)
        pinned = dict(id=job_id, run_id=39388523155, run_attempt=1, name=name,
            head_sha=expected["head_sha"], head_branch=expected["head_branch"],
            workflow_name=expected["name"], status="completed", conclusion=conclusion,
            created_at=clock, started_at=clock, completed_at=clock,
            steps=[], labels=[], runner_id=None, runner_name=None,
            runner_group_id=None, runner_group_name=None)
        require(set(pinned) <= set(job)
                and all(type(job[key]) is type(value) and job[key] == value
                        for key, value in pinned.items()),
                "SPY665_NONCOLLECTION_JOBS")
    return True


def _fixed_spy_history(c, auth, parent, grant_sha, *, current_run=None, nonce=None):
    """Every canonical dispatch belongs to the closed prefix or this exact tail."""
    runs = c.campaign_runs(auth["workflow_run_floor"])
    all_runs = c.campaign_run_pages(c)
    require(all(type(r.get("run_number")) is int and r["run_number"] > 0
                and type(r.get("id")) is int and r["id"] > 0 for r in all_runs)
            and len({r["id"] for r in all_runs}) == len(all_runs),
            "SPY665_CENSUS")
    noncollection = {r["id"] for r in all_runs if _fixed_spy_noncollection_run(c, r)}
    dispatches = [r for r in all_runs if r["run_number"] >= auth["workflow_run_floor"]
                  and r.get("event") != "pull_request" and r["id"] not in noncollection]
    require(all(r.get("event") == "workflow_dispatch" for r in dispatches)
            and {r["id"] for r in dispatches} == {r["id"] for r in runs},
            "SPY665_UNKNOWN_DISPATCH")
    fields = ("id", "run_number", "display_title", "head_sha", "head_branch",
              "run_attempt", "status", "conclusion")
    require({tuple(r.get(k) for k in fields) for r in dispatches}
            == {tuple(r.get(k) for k in fields) for r in runs}, "SPY665_CENSUS_DRIFT")
    require(len(runs) <= 40 and len({r.get("id") for r in runs}) == len(runs)
            and len({r.get("display_title") for r in runs}) == len(runs), "SPY665_CENSUS")
    if current_run is not None:
        require(runs and runs[-1].get("id") == current_run
                and runs[-1].get("display_title") == "a1-sip " + nonce
                and runs[-1].get("run_attempt") == 1
                and runs[-1].get("head_sha") == auth["expected_master"]
                and runs[-1].get("head_branch") == "master", "SPY665_CURRENT_RUN")
        previous = runs[:-1]
    else:
        previous = runs
    old = parent["runs"]
    require(len(previous) >= len(old)
            and len(old) + len(auth["phases"]) <= 40
            and parent["active_seconds"] + auth["wall_seconds"] <= 43200,
            "SPY665_PARENT_REMAINING")
    for actual, pinned in zip(previous, old):
        require(actual.get("id") == pinned["id"] and actual.get("run_number") == pinned["run_number"]
                and actual.get("run_attempt") == 1 and actual.get("status") == "completed"
                and actual.get("head_sha") == pinned["head_sha"]
                and actual.get("head_branch") == "master"
                and actual.get("display_title") == pinned["display_title"],
                "SPY665_PARENT_CENSUS_DRIFT")
    tail = previous[len(old):]
    require(len(tail) <= len(auth["phases"]), "SPY665_PHASE_LIMIT")
    used, spent, active, receipts, blocked = dict(parent["used"]), dict.fromkeys(c.LIMITS, 0), 0, [], False
    h = digest(encoded(auth))
    for phase, run in zip(auth["phases"], tail):
        allowance = {k: min(auth["limits"][k]-used[k], auth["subcaps"][k]-spent[k]) for k in used}
        value = c.receipt_for_run(run, h, auth["expected_master"], auth["limits"])
        require(value.get("fixed_profile") == FIXED_SPY_PROFILE
                and value.get("parent_manifest_sha256") == auth["parent_manifest_sha256"]
                and value.get("scope_grant_sha256") == grant_sha
                and value.get("cohort_scope") == _fixed_spy_scope()
                and value.get("parent_checkpoint_sha256") == _fixed_spy_genesis()
                and value.get("shared_family_prefix_sha256") == parent["family_prefix_head_sha256"]
                and value.get("bindings") == parent["bindings"]
                and value.get("account_permission_reference_sha256") == digest(auth["account_permission_reference"].encode())
                and value.get("account_permission_record_sha256") == grant_sha
                and value.get("preflight_only") is (phase == "preflight")
                and value.get("allowance") == allowance
                and value.get("examined_before") == 0
                and value.get("examined_after") in (0, 1), "SPY665_RECEIPT")
        for key in used:
            used[key] += value["usage"][key]
            spent[key] += value["usage"][key]
        active += c.job_seconds(run)
        blocked |= value["status"] != "COMPLETE" or run.get("conclusion") != "success"
        receipts.append(value)
    require(active <= auth["wall_seconds"]
            and parent["active_seconds"] + active <= 43200, "SPY665_ACTIVE_TIME")
    allowance = {k: min(auth["limits"][k]-used[k], auth["subcaps"][k]-spent[k]) for k in used}
    for key in allowance:
        c.integer(allowance[key], auth["limits"][key], "SPY665_REMAINING")
    require(current_run is None or len(tail) < len(auth["phases"]), "SPY665_PHASE_LIMIT")
    return dict(runs=runs, tail_runs=tail, tail_receipts=receipts, allowance=allowance,
                used=used, scope_used=spent, scope_active_seconds=active, blocked=blocked,
                phase=auth["phases"][len(tail)] if len(tail) < len(auth["phases"]) else None)


def _fixed_spy_worker(c, args, control, journal):
    require(isinstance(control, dict) and set(control) ==
            {"authorization", "nonce", "fixed_spy_grant_reference", "preflight_only"}, "SPY665_CONTROL")
    auth, nonce = control["authorization"], control["nonce"]
    h = _fixed_spy_authorization(c, auth)
    c.verify_worker_source(auth)
    require(isinstance(nonce, str) and re.fullmatch(c.PREFIX+r"[0-9a-f]{24}", nonce)
            and nonce == os.getenv("INPUT_CAMPAIGN_NONCE")
            and args.start == MIN_START and args.end == FIXED_SPY_END
            and args.max_new_symbols == 1
            and args.private_root_folder_id == auth["private_root_folder_id"]
            and args.private_data_folder_id == auth["private_data_folder_id"]
            and args.resume_file_id == args.resume_sha256 == ""
            and type(control["preflight_only"]) is bool, "SPY665_DELIVERY")
    parent = _fixed_spy_parent(c, auth)
    grant_sha = _fixed_spy_grant(c, auth, control["fixed_spy_grant_reference"])
    run_id = int(os.environ["GITHUB_RUN_ID"])
    observed = _fixed_spy_history(c, auth, parent, grant_sha, current_run=run_id, nonce=nonce)
    preflight = control["preflight_only"]
    require(not observed["blocked"] and preflight is (observed["phase"] == "preflight"), "SPY665_PHASE")
    key, secret = os.getenv("ALPACA_API_KEY", "").strip(), os.getenv("ALPACA_API_SECRET", "").strip()
    require(key and secret and digest((key+"\0"+secret).encode()) == auth["credential_binding"],
            "CAMPAIGN_CREDENTIAL_BINDING")
    jobs = c.gh_json(f"repos/{c.REPO}/actions/runs/{run_id}/jobs?per_page=100")
    require(isinstance(jobs.get("jobs"), list) and jobs.get("total_count") == len(jobs["jobs"]) == 2,
            "CAMPAIGN_JOB_TIME")
    live = [j for j in jobs["jobs"] if j.get("name") == "capture" and j.get("status") == "in_progress"]
    require(len(live) == 1, "CAMPAIGN_JOB_TIME")
    started = c.utc(live[0].get("started_at"))
    require(started <= c.utc() + timedelta(seconds=5), "CAMPAIGN_JOB_TIME")
    offline = [j for j in jobs["jobs"] if j.get("name") == "offline"]
    require(len(offline) == 1 and offline[0].get("status") == "completed"
            and offline[0].get("conclusion") == "success", "SPY665_OFFLINE_JOB")
    offline_started, offline_end = c.utc(offline[0].get("started_at")), c.utc(offline[0].get("completed_at"))
    offline_seconds = (offline_end-offline_started).total_seconds()
    require(offline_started <= offline_end <= started and 0 <= offline_seconds <= 7800,
            "CAMPAIGN_JOB_TIME")
    deadline = min(c.utc(auth["expires_at_utc"]), started + timedelta(
        seconds=auth["wall_seconds"]-observed["scope_active_seconds"]-offline_seconds))
    require(c.utc() < deadline, "CAMPAIGN_DEADLINE")
    identity = dict(task_key=c.TASK, auth_sha256=h, source_sha=auth["expected_master"],
        nonce=nonce, run_id=run_id, run_attempt=1, recovery_run=None, preflight_only=preflight,
        fixed_profile=FIXED_SPY_PROFILE, cohort_scope=_fixed_spy_scope(),
        parent_manifest_sha256=auth["parent_manifest_sha256"], scope_grant_sha256=grant_sha,
        shared_family_prefix_sha256=parent["family_prefix_head_sha256"],
        bindings=parent["bindings"], parent_checkpoint_sha256=_fixed_spy_genesis(), examined_before=0,
        account_permission_reference_sha256=digest(auth["account_permission_reference"].encode()),
        account_permission_record_sha256=grant_sha)
    meter = c.RuntimeMeter(observed["allowance"], journal, deadline.isoformat(), identity,
                           limits=auth["limits"], asset_symbols=("SPY",))
    def factory(root, temp):
        drive = OwnerDrive(root, temp, meter=meter)
        require(drive.owner == auth["owner_permission_id"]
                and drive.free >= observed["allowance"]["storage_bytes"], "CAMPAIGN_OWNER_OR_SPACE")
        meter.identity["free_bytes_at_start"] = drive.free
        meter.save()
        return drive
    private_args = argparse.Namespace(**dict(vars(args), start=FIXED_SPY_START))
    try:
        with meter.process_deadline():
            if preflight:
                with tempfile.TemporaryDirectory(prefix="a1-spy-preflight-") as temp:
                    drive = factory(args.private_root_folder_id, temp)
                    drive.check(args.private_data_folder_id, drive.root_id)
                result = None
            else:
                result = _collect(private_args, drive_factory=factory, get=meter.perform,
                    expected_examined=0, external=dict(input_csv=FIXED_SPY_INPUT.decode(),
                        scope=_fixed_spy_scope()), fixed_profile=FIXED_SPY_PROFILE,
                    on_group=lambda drive, state, ref: c.verify_new_group(drive,
                        args.private_data_folder_id, state, ref, meter, fixed_spy=True))
                require(meter.examined == 1 and meter.checkpoint_sha == result["checkpoint"]["sha256"],
                        "CAMPAIGN_BATCH_CLOSURE")
        meter.finish("COMPLETE")
        return result
    except Refused as exc:
        meter.finish("BLOCKED", str(exc)); raise
    except Exception:
        meter.finish("BLOCKED", "CAMPAIGN_INTERNAL")
        raise Refused("CAMPAIGN_INTERNAL") from None


def _fixed_spy_family(c, auth, parent, grant_sha, budget_state_dir):
    require(budget_state_dir is not None, "SPY665_SHARED_JOURNAL_REQUIRED")
    supplied = Path(budget_state_dir)
    require(supplied.is_dir() and not supplied.is_symlink(), "SPY665_SHARED_JOURNAL_REQUIRED")
    budget = supplied.resolve()
    directory = budget.parent / ("external-budget-" + c.CONTINUATION["auth"][:16])
    require(budget.is_dir() and not budget.is_symlink()
            and directory.is_dir() and not directory.is_symlink(), "SPY665_SHARED_JOURNAL_REQUIRED")
    family = c.WorkJournal(directory, c.external_family_genesis())
    try:
        count = parent["family_prefix_count"]
        require(len(family.entries) >= count
                and family.entries[0].get("kind") == "EXTERNAL_FAMILY_BOUND"
                and family.entries[0].get("budget_state_root") == os.path.normcase(str(budget))
                and digest(c.bounded_bytes(directory / "000001.json")) == parent["family_prefix_first_sha256"]
                and digest(c.bounded_bytes(directory / f"{count:06d}.json")) == parent["family_prefix_head_sha256"],
                "SPY665_SHARED_PREFIX_DRIFT")
        binding = dict(profile=FIXED_SPY_PROFILE, capture_auth_sha256=digest(encoded(auth)),
            scope_grant_sha256=grant_sha, parent_manifest_sha256=auth["parent_manifest_sha256"],
            shared_parent_sha256=parent["family_prefix_head_sha256"],
            data_genesis_sha256=_fixed_spy_genesis(), cohort_scope=_fixed_spy_scope())
        if len(family.entries) == count:
            family.append("SPY665_PROFILE_BOUND", **binding)
        first = family.entries[count]
        require(first.get("kind") == "SPY665_PROFILE_BOUND"
                and {k: first.get(k) for k in binding} == binding, "SPY665_SHARED_BINDING")
        return family
    except BaseException:
        family.close(); raise


def _fixed_spy_reconcile(c, family, auth, parent, observed):
    """Only this bounded typed tail is new; historical bytes remain untouched."""
    tail = family.entries[parent["family_prefix_count"] + 1:]
    pending, phase_index, settled = None, 0, []
    for entry in tail:
        kind = entry.get("kind")
        require(entry.get("capture_auth_sha256") == digest(encoded(auth)), "SPY665_SHARED_TAIL")
        if kind == "SPY665_RESERVED":
            require(pending is None and phase_index < len(auth["phases"])
                    and entry.get("phase") == auth["phases"][phase_index]
                    and isinstance(entry.get("nonce"), str)
                    and re.fullmatch(c.PREFIX+r"[0-9a-f]{24}", entry["nonce"]), "SPY665_SHARED_TAIL")
            pending = dict(entry)
        elif kind == "SPY665_RUN_ASSIGNED":
            require(pending is not None and "assigned_run_id" not in pending
                    and entry.get("nonce") == pending["nonce"]
                    and type(entry.get("run_id")) is int, "SPY665_SHARED_TAIL")
            pending["assigned_run_id"] = entry["run_id"]
        elif kind == "SPY665_SETTLED":
            require(pending is not None and phase_index < len(observed["tail_runs"]),
                    "SPY665_SHARED_TAIL")
            run, value = observed["tail_runs"][phase_index], observed["tail_receipts"][phase_index]
            require(entry.get("nonce") == pending["nonce"] == value["nonce"]
                    and entry.get("run_id") == pending.get("assigned_run_id") == run["id"]
                    and entry.get("receipt_sha256") == digest(encoded(value))
                    and entry.get("usage") == value["usage"]
                    and entry.get("status") == value["status"]
                    and entry.get("phase") == pending["phase"]
                    and pending.get("allowance") == value["allowance"]
                    and entry.get("checkpoint") == c.checkpoint_from_log(run, value,
                        dict(file_id="", sha256=_fixed_spy_genesis())), "SPY665_SETTLEMENT_DRIFT")
            settled.append(run["id"]); phase_index += 1; pending = None
        else:
            raise Refused("SPY665_SHARED_TAIL")
    require(phase_index <= len(observed["tail_runs"]) <= phase_index + (pending is not None),
            "SPY665_JOURNAL_ROLLBACK_OR_UNKNOWN_RUN")
    return pending, phase_index


def _fixed_spy_host(c, auth, state_dir, budget_state_dir, grant_reference, max_batches):
    """One fixed finite tail in the existing shared journal, never a new family."""
    h = _fixed_spy_authorization(c, auth)
    require(type(max_batches) is int and 1 <= max_batches <= len(auth["phases"]), "SPY665_PHASE_LIMIT")
    parent = _fixed_spy_parent(c, auth)
    grant_sha = _fixed_spy_grant(c, auth, grant_reference)
    require(budget_state_dir is not None and Path(state_dir).resolve() == Path(budget_state_dir).resolve().parent
            / ("fixed-" + FIXED_SPY_PROFILE) and not Path(state_dir).is_symlink(), "SPY665_STATE_PATH")
    family = _fixed_spy_family(c, auth, parent, grant_sha, budget_state_dir)
    closed_now = 0
    try:
        Path(state_dir).mkdir(exist_ok=True)
        while True:
            observed = _fixed_spy_history(c, auth, parent, grant_sha)
            pending, done = _fixed_spy_reconcile(c, family, auth, parent, observed)
            if pending is not None:
                matches = [(r, v) for r, v in zip(observed["tail_runs"], observed["tail_receipts"])
                           if v["nonce"] == pending["nonce"]]
                require(len(matches) == 1, "CAMPAIGN_ACTIVE_RESERVATION")
                run, value = matches[0]
                if "assigned_run_id" not in pending:
                    family.append("SPY665_RUN_ASSIGNED", capture_auth_sha256=h,
                                  nonce=pending["nonce"], run_id=run["id"])
                else:
                    require(pending["assigned_run_id"] == run["id"], "SPY665_SHARED_TAIL")
                require(pending["allowance"] == value["allowance"], "SPY665_SETTLEMENT_DRIFT")
                # A verified checkpoint reference is an output, never admission.
                ref = c.checkpoint_from_log(run, value, dict(file_id="", sha256=_fixed_spy_genesis()))
                family.append("SPY665_SETTLED", capture_auth_sha256=h, nonce=value["nonce"],
                    run_id=run["id"], phase=pending["phase"], receipt_sha256=digest(encoded(value)),
                    usage=value["usage"], status=value["status"], checkpoint=ref)
                closed_now += 1
                continue
            require(not observed["blocked"], "CAMPAIGN_WORKER_BLOCKED")
            if observed["phase"] is None or closed_now >= max_batches:
                result = dict(status="SPY665_PHASE_BOUNDARY", profile=FIXED_SPY_PROFILE,
                    phases_closed=done, shared_used=observed["used"], scope_used=observed["scope_used"],
                    source_admission=False, pit_verified=False, economic_authority=False)
                c.atomic_json(Path(state_dir) / "progress", result)
                return result
            require(len(observed["runs"]) < 40
                    and observed["scope_active_seconds"] < auth["wall_seconds"], "SPY665_DISPATCH_BUDGET")
            require(c.gh_json(f"repos/{c.REPO}/branches/master")["commit"]["sha"] == auth["expected_master"],
                    "CAMPAIGN_MASTER_DRIFT")
            for path in c.PINS + (c.REVISION_MODULE,):
                value = c.gh_json(f"repos/{c.REPO}/contents/{path}?ref={auth['expected_master']}")
                require(value.get("encoding") == "base64"
                        and digest(c.base64.b64decode(value["content"], validate=False)) == auth["code_pins"][path],
                        "CAMPAIGN_DEPLOYED_CODE")
            require(_fixed_spy_grant(c, auth, grant_reference) == grant_sha
                    and _fixed_spy_history(c, auth, parent, grant_sha) == observed, "SPY665_CANONICAL_DRIFT")
            nonce = c.PREFIX + os.urandom(12).hex()
            phase = observed["phase"]
            control = dict(authorization=auth, nonce=nonce, fixed_spy_grant_reference=grant_reference,
                           preflight_only=phase == "preflight")
            raw = encoded(control)
            require(len(raw) <= 16384, "CAMPAIGN_CONTROL_SIZE")
            family.append("SPY665_RESERVED", capture_auth_sha256=h, nonce=nonce, phase=phase,
                allowance=observed["allowance"], remaining_active_seconds=auth["wall_seconds"]-observed["scope_active_seconds"],
                remaining_event_slots=40-len(observed["runs"]))
            inputs = dict(private_root_folder_id=auth["private_root_folder_id"],
                private_data_folder_id=auth["private_data_folder_id"], private_research_authorized="true",
                noncommercial_terms_acknowledged="true", end_date=FIXED_SPY_END, max_new_symbols="1",
                resume_file_id="", resume_sha256="", campaign_control=raw.decode(), campaign_nonce=nonce)
            result = c.subprocess.run(["gh", "workflow", "run", c.WORKFLOW, "--repo", c.REPO,
                "--ref", "master", "--json"], input=c.json.dumps(inputs).encode(),
                stdout=c.subprocess.DEVNULL, stderr=c.subprocess.DEVNULL, timeout=45)
            require(result.returncode == 0, "CAMPAIGN_DISPATCH_UNCERTAIN")
            found = None
            for _ in range(30):
                matches = [r for r in c.campaign_runs(auth["workflow_run_floor"])
                           if r.get("display_title") == "a1-sip " + nonce]
                require(len(matches) <= 1, "CAMPAIGN_NONCE_REPLAY")
                if matches:
                    found = matches[0]; break
                time.sleep(2)
            require(found is not None, "CAMPAIGN_DISPATCH_UNCERTAIN")
            family.append("SPY665_RUN_ASSIGNED", capture_auth_sha256=h, nonce=nonce, run_id=found["id"])
            c.subprocess.run(["gh", "run", "watch", str(found["id"]), "--repo", c.REPO,
                "--exit-status", "--interval", "30"], stdout=c.subprocess.DEVNULL,
                stderr=c.subprocess.DEVNULL, timeout=auth["wall_seconds"]+120)
            # Re-read finalized actual evidence before accounting; never retry.
    finally:
        family.close()


# One separately allocated attempt; never a renewal of the legacy40-run family.
NEW3_PROFILE = "owner-new3-20261029-r2"
NEW3_TASK = "R1000-A0-NEW3-OHLCV-20261029-ONE-R2"
NEW3_INPUT = b"ticker\nSYM\nCGNX\nNOVT\n"
NEW3_END = "2026-10-28"
NEW3_EXPIRY = "2026-10-28T22:00:00Z"
NEW3_ALLOCATION = "https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-6474160005"
NEW3_ALLOCATION_BODY = "46830e6265226868f33f3412c9dddbc255adb76c745a12cac4f146a8d8515069"
NEW3_CAPS = dict(provider_gets=8, drive_requests=256, drive_bytes=128*1024**2,
                 storage_bytes=16*1024**2)
NEW3_CALENDAR_PATH = "tools/run_daily_market_session_gate.py"
NEW3_ARCHIVAL_POLICY = 6474415974
NEW3_ARCHIVAL_POLICY_SHA = "a001000deb232f52615355151da1cc88c5af46e4e43cff5d0ff4cde9bd11f4b1"
NEW3_SUPERSEDED_TASK = "R1000-A0-NEW3-OHLCV-20261028-ONE"
NEW3_SUPERSEDED_ALLOCATION = "https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-6471394173"


def _new3_scope():
    return dict(task_key=NEW3_TASK, namespace="owner-new3-20261029-r2", input_sha256=digest(NEW3_INPUT))


def _new3_hash(auth):
    return digest(encoded({k: v for k, v in auth.items() if k != "working_copy_reference"}))


def _new3_nonce(c):
    # Grant identity, not mutable control/nonce bytes, fixes the one remote slot.
    return c.PREFIX + digest((NEW3_TASK + NEW3_ALLOCATION).encode())[:24]


def _new3_authorization(c, auth):
    fields = {"schema", "task_key", "allocation_profile", "allocation_reference", "start", "end",
        "input_csv", "scope", "limits", "wall_seconds", "start_before_utc", "expected_master",
        "code_pins", "deployment", "private_root_folder_id", "private_data_folder_id",
        "owner_permission_id", "credential_binding", "working_copy_reference", "rights_documents",
        "opening", "market_gate", "asset_ids"}
    require(isinstance(auth, dict) and set(auth) == fields
        and auth.get("schema") == "a1-new3-one-capture-authorization-v1"
        and auth.get("allocation_profile") == NEW3_PROFILE and auth.get("task_key") == NEW3_TASK
        and auth.get("allocation_reference") == NEW3_ALLOCATION, "NEW_THREE_AUTHORIZATION")
    require(auth["start"] == MIN_START and auth["end"] == NEW3_END
        and auth["input_csv"] == NEW3_INPUT.decode() and auth["scope"] == _new3_scope()
        and external_cohort(NEW3_INPUT) == ["SYM", "CGNX", "NOVT"], "NEW_THREE_SCOPE")
    require(auth["limits"] == NEW3_CAPS and all(type(auth["limits"][k]) is int for k in NEW3_CAPS)
        and type(auth["wall_seconds"]) is int and auth["wall_seconds"] == 900
        and auth["start_before_utc"] == NEW3_EXPIRY, "NEW_THREE_LIMITS")
    require(isinstance(auth["expected_master"], str) and c.re.fullmatch("[0-9a-f]{40}", auth["expected_master"])
        and isinstance(auth["code_pins"], dict) and set(auth["code_pins"]) == set(c.PINS + (c.REVISION_MODULE, NEW3_CALENDAR_PATH))
        and all(isinstance(x, str) and c.re.fullmatch("[0-9a-f]{64}", x) for x in auth["code_pins"].values()),
        "NEW_THREE_CODE_PINS")
    d = auth["deployment"]
    require(isinstance(d, dict) and set(d) == {"pull_request", "reviewed_head"}
        and type(d["pull_request"]) is int and d["pull_request"] > 0
        and isinstance(d["reviewed_head"], str) and c.re.fullmatch("[0-9a-f]{40}", d["reviewed_head"]),
        "NEW_THREE_DEPLOYMENT")
    for key in ("private_root_folder_id", "private_data_folder_id"):
        require(isinstance(auth[key], str) and c.re.fullmatch("[A-Za-z0-9_-]{10,100}", auth[key]), "NEW_THREE_PRIVATE_REF")
    require(auth["private_root_folder_id"] != auth["private_data_folder_id"]
        and isinstance(auth["owner_permission_id"], str)
        and digest(auth["owner_permission_id"].encode()) == c.CONTINUATION["bindings"]["owner_sha256"]
        and auth["credential_binding"] == c.CONTINUATION["bindings"]["credential_binding"], "NEW_THREE_ACCOUNT_BINDING")
    docs = auth["rights_documents"]
    require(isinstance(docs, list) and 1 <= len(docs) <= 8, "NEW_THREE_RIGHTS_REFERENCES")
    for ref in docs:
        require(isinstance(ref, dict) and set(ref) == {"folder_id", "file_id", "sha256", "bytes"}
            and all(isinstance(ref[k], str) and c.re.fullmatch("[A-Za-z0-9_-]{10,100}", ref[k])
                    for k in ("folder_id", "file_id"))
            and isinstance(ref["sha256"], str) and c.re.fullmatch("[0-9a-f]{64}", ref["sha256"])
            and type(ref["bytes"]) is int and 1 <= ref["bytes"] <= 262144, "NEW_THREE_RIGHTS_REFERENCES")
    require(len({r["file_id"] for r in docs}) == len(docs), "NEW_THREE_RIGHTS_REFERENCES")
    opening = auth["opening"]
    require(isinstance(opening, dict) and set(opening) == {"family_prefix_first_sha256", "family_prefix_sha256",
        "event_count", "dispatches", "usage", "source_history_sha256", "unresolved_costs_reserved"}
        and type(opening["event_count"]) is int and 108 <= opening["event_count"] <= 1000
        and type(opening["dispatches"]) is int and opening["dispatches"] == 40
        and opening["unresolved_costs_reserved"] is True, "NEW_THREE_OPENING_ACCOUNTING")
    for key in ("family_prefix_first_sha256", "family_prefix_sha256", "source_history_sha256"):
        require(isinstance(opening[key], str) and c.re.fullmatch("[0-9a-f]{64}", opening[key]), "NEW_THREE_OPENING_ACCOUNTING")
    floor = dict(provider_gets=1333, drive_requests=12651, drive_bytes=2146683011, storage_bytes=172244405)
    require(isinstance(opening["usage"], dict) and set(opening["usage"]) == set(floor), "NEW_THREE_OPENING_ACCOUNTING")
    for key, minimum in floor.items():
        require(c.integer(opening["usage"][key], c.CONTINUED_LIMITS[key], "NEW_THREE_OPENING_ACCOUNTING") >= minimum,
                "NEW_THREE_OPENING_ACCOUNTING")
    gate = auth["market_gate"]
    require(isinstance(gate, dict) and gate.get("schema_version") == "daily-market-session-gate-v1"
        and gate.get("calendar") == "NYSE" and type(gate.get("ready")) is bool
        and isinstance(gate.get("session_date"), str)
        and isinstance(gate.get("market_close_utc"), str) and isinstance(gate.get("checked_at_utc"), str)
        and c.utc(gate.get("market_close_utc")) <= c.utc(gate.get("checked_at_utc"))
        and c.utc(gate.get("checked_at_utc")) >= c.utc("2026-10-28T00:15:00Z"), "NEW_THREE_MARKET_GATE")
    require(isinstance(auth["asset_ids"], dict) and set(auth["asset_ids"]) == set(external_cohort(NEW3_INPUT))
        and all(isinstance(v, str) and c.re.fullmatch("[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", v)
                for v in auth["asset_ids"].values())
        and len(set(auth["asset_ids"].values())) == 3, "NEW_THREE_ASSET_IDS")
    require(isinstance(auth["working_copy_reference"], str)
        and c.re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",
                          auth["working_copy_reference"]) and len(encoded(auth)) <= 12000, "NEW_THREE_ACCOUNT_REVIEW")
    return _new3_hash(auth)


def _new3_authority(c, auth, *, accounting=False):
    allocation = c.gh_json(f"repos/{c.REPO}/issues/comments/6474160005")
    require(allocation.get("id") == 6474160005 and allocation.get("author_association") == "OWNER"
        and allocation.get("user", {}).get("type") == "User"
        and isinstance(allocation.get("created_at"), str)
        and allocation.get("issue_url") == f"https://api.github.com/repos/{c.REPO}/issues/448"
        and allocation.get("created_at") == allocation.get("updated_at")
        and isinstance(allocation.get("body"), str)
        and digest(allocation["body"].encode()) == NEW3_ALLOCATION_BODY
        and c.utc(allocation.get("created_at")) <= c.utc()
        and (accounting or c.utc() < c.utc(NEW3_EXPIRY)), "NEW_THREE_ALLOCATION")
    policy = c.gh_json(f"repos/{c.REPO}/issues/comments/{NEW3_ARCHIVAL_POLICY}")
    require(policy.get("id") == NEW3_ARCHIVAL_POLICY and policy.get("author_association") == "OWNER"
        and policy.get("user", {}).get("type") == "User"
        and policy.get("issue_url") == f"https://api.github.com/repos/{c.REPO}/issues/448"
        and isinstance(policy.get("created_at"), str)
        and policy.get("created_at") == policy.get("updated_at")
        and isinstance(policy.get("body"), str) and digest(policy["body"].encode()) == NEW3_ARCHIVAL_POLICY_SHA
        and c.utc(allocation["created_at"]) <= c.utc(policy["created_at"]) <= c.utc(), "NEW_THREE_ARCHIVAL_POLICY")
    record = _fixed_spy_owner_record(c, auth["working_copy_reference"], "A1_NEW3_PRIVATE_WORKING_COPY_REVIEW ",
        window=(allocation["created_at"], NEW3_EXPIRY))
    review_id = auth["working_copy_reference"].rsplit("-", 1)[-1]
    reviewed_at = c.gh_json(f"repos/{c.REPO}/issues/comments/{review_id}").get("created_at")
    deployed_at = c.gh_json(f"repos/{c.REPO}/pulls/{auth['deployment']['pull_request']}").get("merged_at")
    require(isinstance(reviewed_at, str) and isinstance(deployed_at, str)
        and c.utc(deployed_at) <= c.utc(reviewed_at), "NEW_THREE_REVIEW_BEFORE_DEPLOYMENT")
    expected = dict(schema="a1-new3-private-working-copy-review-v1", control_sha256=_new3_hash(auth),
        allocation_comment_id=6474160005, credential_binding=auth["credential_binding"],
        owner_sha256=digest(auth["owner_permission_id"].encode()),
        opening_sha256=digest(encoded(auth["opening"])), rights_manifest_sha256=digest(encoded(auth["rights_documents"])),
        purpose="PRIVATE_NONCOMMERCIAL_RESEARCH_WORKING_COPY", historical_sip_reviewed=True,
        current_account_reviewed=True, supplier_rights_verified=False, supplier_expiry=None,
        permanent_retention_verified=False, redistribution_authorized=False, source_admission=False,
        economic_authority=False)
    require(record == expected and (accounting or
        0 <= (c.utc() - c.utc(auth["market_gate"]["checked_at_utc"])).total_seconds() <= 900),
        "NEW_THREE_ACCOUNT_REVIEW")
    return digest(encoded(record))


def _new3_source(c, auth, *, accounting=False):
    if not accounting:
        master = c.gh_json(f"repos/{c.REPO}/branches/master")
        require(master.get("protected") is True and master.get("commit", {}).get("sha") == auth["expected_master"],
            "NEW_THREE_MASTER_DRIFT")
    pr = c.gh_json(f"repos/{c.REPO}/pulls/{auth['deployment']['pull_request']}")
    require(pr.get("merged") is True and pr.get("draft") is False
        and pr.get("number") == auth["deployment"]["pull_request"]
        and pr.get("base", {}).get("ref") == "master"
        and pr.get("head", {}).get("repo", {}).get("full_name") == c.REPO
        and pr.get("base", {}).get("repo", {}).get("full_name") == c.REPO
        and pr.get("head", {}).get("sha") == auth["deployment"]["reviewed_head"]
        and pr.get("merge_commit_sha") == auth["expected_master"], "NEW_THREE_DEPLOYMENT")
    c._revision_module().named_read_checks(c, auth)
    for path, sha in auth["code_pins"].items():
        value = c.gh_json(f"repos/{c.REPO}/contents/{path}?ref={auth['expected_master']}")
        require(value.get("encoding") == "base64" and digest(c.base64.b64decode(value["content"])) == sha
            and (accounting or digest(c.bounded_bytes(c.ROOT/path, 262144).replace(b"\r\n", b"\n")) == sha),
            "NEW_THREE_CODE_DRIFT")


def _new3_history(c, auth, current=None):
    rows = c.campaign_run_pages(c)
    old_nonce = c.PREFIX + digest((NEW3_SUPERSEDED_TASK + NEW3_SUPERSEDED_ALLOCATION).encode())[:24]
    require(not any(r.get("display_title") == "a1-sip " + old_nonce for r in rows),
            "NEW_THREE_SUPERSEDED_ATTEMPT")
    fields = ("id", "run_number", "run_attempt", "head_sha", "head_branch", "event", "status",
              "conclusion", "display_title", "created_at", "updated_at")
    matches = [r for r in rows if r.get("display_title") == "a1-sip " + _new3_nonce(c)]
    require(len(matches) == (0 if current is None else 1), "NEW_THREE_ALREADY_ATTEMPTED_OR_UNKNOWN")
    require(current is None or matches[0].get("id") == current and matches[0].get("run_attempt") == 1
        and matches[0].get("event") == "workflow_dispatch" and matches[0].get("head_branch") == "master"
        and matches[0].get("head_sha") == auth["expected_master"] and matches[0].get("status") == "in_progress",
        "NEW_THREE_CURRENT_RUN")
    previous = [r for r in rows if r.get("id") != current]
    require(all(r.get("status") == "completed" for r in previous), "NEW_THREE_FOREIGN_ACTIVE_RUN")
    snapshot = [{k: r.get(k) for k in fields} for r in sorted(previous, key=lambda x: x["id"])]
    require(digest(encoded(snapshot)) == auth["opening"]["source_history_sha256"], "NEW_THREE_HISTORY_DRIFT")
    return matches[0] if current is not None else None



def _new3_archival_gate(c, auth, *, observed=None):
    """Existing calendar truth; archival eligibility never changes daily readiness."""
    try:
        from tools.run_daily_market_session_gate import evaluate_market_session, mcal
        from importlib.metadata import version
    except ImportError:
        raise c.Refused("NEW_THREE_CALENDAR_DEPENDENCY") from None
    now = c.utc() if observed is None else observed
    require(now < c.utc(NEW3_EXPIRY), "NEW_THREE_ARCHIVAL_EXPIRY")
    require(auth.get("start") == MIN_START and auth.get("end") == NEW3_END, "NEW_THREE_ARCHIVAL_WINDOW")
    checked = c.utc(auth["market_gate"]["checked_at_utc"])
    require(0 <= (now-checked).total_seconds() <= 900, "NEW_THREE_CALENDAR_RECEIPT_AGE")
    # No force, max-age override or caller READY flag can replace this result.
    original = evaluate_market_session(now_utc=checked, min_close_age_minutes=120)
    require(auth["market_gate"] == original, "NEW_THREE_CALENDAR_RECEIPT_CONFLICT")
    daily = evaluate_market_session(now_utc=now, min_close_age_minutes=120)
    target = (date.fromisoformat(NEW3_END)-timedelta(days=1)).isoformat()
    schedule = mcal.get_calendar("NYSE").schedule(start_date=target,
        end_date=(now.date()+timedelta(days=1)).isoformat())
    selected = [(label, row) for label, row in schedule.iterrows() if label.date().isoformat() == target]
    require(len(selected) == 1, "NEW_THREE_ARCHIVAL_NOT_SESSION")
    close = c.utc(selected[0][1]["market_close"].isoformat())
    earliest_close = close+timedelta(minutes=120)
    # Preserve the collector's inclusive UTC end and existing delayed-SIP boundary.
    endpoint = c.utc(target+"T23:59:59Z")
    earliest_endpoint = endpoint+timedelta(minutes=15)
    require(close <= now and earliest_close <= now and earliest_endpoint <= now,
        "NEW_THREE_ARCHIVAL_UNSETTLED")
    eligible = [label.date().isoformat() for label, row in schedule.iterrows()
        if c.utc(row["market_close"].isoformat())+timedelta(minutes=120) <= now
        and c.utc(label.date().isoformat()+"T23:59:59Z")+timedelta(minutes=15) <= now]
    require(eligible and eligible[-1] == target, "NEW_THREE_NEWER_ELIGIBLE_SESSION")
    return dict(schema="a1-new3-archival-time-gate-v1", status="ARCHIVAL_COLLECTION_ONLY",
        observed_at_utc=now.isoformat(), target_session=target, latest_settlement_eligible_session=eligible[-1],
        actual_market_close_utc=close.isoformat(), earliest_close_ready_utc=earliest_close.isoformat(),
        requested_inclusive_end_utc=endpoint.isoformat(), earliest_endpoint_ready_utc=earliest_endpoint.isoformat(),
        min_close_age_minutes=120, provider_end_delay_minutes=15,
        owner_gate_sha256=digest(encoded(original)), daily_market_gate=daily,
        calendar_versions=dict(pandas=version("pandas"), pandas_market_calendars=version("pandas_market_calendars")),
        source_admission=False, pit_verified=False, current_price_verified=False,
        er_authority=False, a5_authority=False, economic_authority=False)


def _new3_event_control(c, expected=None):
    """Read R2 private references only from the runner event, never job env/CLI."""
    require(os.getenv("INPUT_PRIVATE_NEW3_R2") == "true"
        and not any(os.getenv(k) for k in ("INPUT_CAMPAIGN_CONTROL", "INPUT_PRIVATE_ROOT_FOLDER_ID",
            "INPUT_PRIVATE_DATA_FOLDER_ID", "INPUT_RESUME_FILE_ID")), "NEW_THREE_PRIVATE_ENV")
    path = os.getenv("GITHUB_EVENT_PATH")
    require(isinstance(path, str) and path, "NEW_THREE_PRIVATE_EVENT")
    event = c.bounded_json(path, 65536)
    if os.name != "nt":
        os.chmod(path, 0o600)
        require(Path(path).stat().st_mode & 0o077 == 0, "NEW_THREE_PRIVATE_EVENT_MODE")
    inputs = event.get("inputs") if isinstance(event, dict) else None
    require(isinstance(inputs, dict) and isinstance(inputs.get("campaign_control"), str)
        and 0 < len(inputs["campaign_control"].encode()) <= 16384, "NEW_THREE_PRIVATE_EVENT")
    control = c.decode(inputs["campaign_control"])
    require(isinstance(control, dict) and set(control) == {"authorization", "nonce"}, "NEW_THREE_PRIVATE_EVENT")
    auth = control["authorization"]
    _new3_authorization(c, auth)
    require(control["nonce"] == inputs.get("campaign_nonce") == _new3_nonce(c)
        and inputs.get("private_root_folder_id") == auth["private_root_folder_id"]
        and inputs.get("private_data_folder_id") == auth["private_data_folder_id"]
        and inputs.get("resume_file_id", "") == inputs.get("resume_sha256", "") == ""
        and inputs.get("end_date") == NEW3_END
        and (type(inputs.get("max_new_symbols")) is int and inputs["max_new_symbols"] == 3
             or inputs.get("max_new_symbols") == "3")
        and all(inputs.get(k) is True or inputs.get(k) == "true" for k in
            ("private_research_authorized", "noncommercial_terms_acknowledged"))
        and (expected is None or encoded(expected) == encoded(control)), "NEW_THREE_PRIVATE_EVENT")
    return control


def _new3_worker(c, args, control, journal):
    require(isinstance(control, dict) and set(control) == {"authorization", "nonce"}, "NEW_THREE_CONTROL")
    auth = control["authorization"]
    h = _new3_authorization(c, auth)
    require(os.getenv("A1_PRIVATE_RESEARCH_AUTHORIZED") == "true"
        and os.getenv("ALPACA_NONCOMMERCIAL_ACKNOWLEDGED") == "true"
        and os.getenv("GITHUB_REPOSITORY") == c.REPO and os.getenv("GITHUB_REF") == "refs/heads/master"
        and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch" and os.getenv("GITHUB_RUN_ATTEMPT") == "1"
        and os.getenv("GITHUB_SHA") == auth["expected_master"]
        and control["nonce"] == os.getenv("INPUT_CAMPAIGN_NONCE") == _new3_nonce(c), "NEW_THREE_CONTEXT")
    _new3_event_control(c, control)
    require(args.private_root_folder_id == args.private_data_folder_id == "", "NEW_THREE_PRIVATE_CLI")
    args = argparse.Namespace(**vars(args))
    args.private_root_folder_id = auth["private_root_folder_id"]
    args.private_data_folder_id = auth["private_data_folder_id"]
    require(args.start == MIN_START and args.end == NEW3_END and args.max_new_symbols == 3
        and args.resume_file_id == args.resume_sha256 == ""
        and args.private_root_folder_id == auth["private_root_folder_id"]
        and args.private_data_folder_id == auth["private_data_folder_id"], "NEW_THREE_ARGUMENTS")
    _new3_source(c, auth)
    reviewed = _new3_authority(c, auth)
    archival = _new3_archival_gate(c, auth)
    run_id = int(os.environ["GITHUB_RUN_ID"])
    current = _new3_history(c, auth, run_id)
    require(isinstance(current.get("run_started_at"), str) and isinstance(current.get("created_at"), str),
        "NEW_THREE_RUN_START_CLOCK")
    start = c.utc(current["created_at"])
    require(start <= c.utc(current["run_started_at"]) <= c.utc() < c.utc(NEW3_EXPIRY)
        and c.utc() < start + timedelta(seconds=840), "NEW_THREE_START_OR_DEADLINE")
    require(c.gh_json(f"repos/{c.REPO}/branches/master").get("commit", {}).get("sha") == auth["expected_master"],
        "NEW_THREE_MASTER_DRIFT")
    key, secret = os.getenv("ALPACA_API_KEY", "").strip(), os.getenv("ALPACA_API_SECRET", "").strip()
    require(key and secret and digest((key + "\0" + secret).encode()) == auth["credential_binding"], "NEW_THREE_CREDENTIAL_BINDING")
    identity = dict(task_key=NEW3_TASK, auth_sha256=h, source_sha=auth["expected_master"], nonce=_new3_nonce(c),
        run_id=run_id, run_attempt=1, preflight_only=False, allocation_profile=NEW3_PROFILE,
        allocation_comment_id=6474160005, cohort_scope=_new3_scope(), parent_checkpoint_sha256=c.external_genesis(_new3_scope()),
        examined_before=0, bindings=dict(c.CONTINUATION["bindings"]),
        opening_accounting_sha256=digest(encoded(auth["opening"])),
        account_permission_reference_sha256=digest(auth["working_copy_reference"].encode()),
        account_permission_record_sha256=reviewed, archival_time_gate=archival,
        archival_time_policy_sha256=NEW3_ARCHIVAL_POLICY_SHA, current_price_verified=False)
    meter = c.RuntimeMeter(dict(NEW3_CAPS), journal, (start + timedelta(seconds=840)).isoformat(), identity,
        asset_symbols=tuple(external_cohort(NEW3_INPUT)))
    def factory(root, temp):
        drive = OwnerDrive(root, temp, meter=meter)
        require(drive.owner == auth["owner_permission_id"] and drive.free >= 2*1024**3, "NEW_THREE_OWNER_OR_SPACE")
        for ref in auth["rights_documents"]:
            drive.check(ref["folder_id"])
            _private_object(drive, ref["folder_id"], ref, 262144)
        return drive
    def get(url, **kwargs):
        raw = meter.perform(url, **kwargs)
        if "/v2/assets/" in url:
            symbol = url.rsplit("/", 1)[-1]
            require(symbol in auth["asset_ids"] and asset_record(raw, symbol)["id"] == auth["asset_ids"][symbol],
                "NEW_THREE_ASSET_IDENTITY_CHANGED")
        return raw
    try:
        # Existing collector logging includes private object refs; keep that text
        # off the public Actions log for this new route only.
        from contextlib import redirect_stdout
        with meter.process_deadline(), redirect_stdout(io.StringIO()):
            result = _collect(args, drive_factory=factory, get=get, expected_examined=0,
                external=dict(input_csv=NEW3_INPUT.decode(), scope=_new3_scope()),
                on_group=lambda drive, state, ref: c.verify_new_group(drive, args.private_data_folder_id,
                    state, ref, meter, new3=True))
        require(meter.examined == 3 and meter.checkpoint_sha == result["checkpoint"]["sha256"], "NEW_THREE_BATCH_CLOSURE")
        meter.finish("COMPLETE")
        public = dict(status=result["status"], allocation_profile=NEW3_PROFILE, checkpoint_sha256=meter.checkpoint_sha,
            examined=3, rows_verified=meter.rows, states=meter.states, price_coverage_certified=False,
            time_gate_status=archival["status"], daily_market_status=archival["daily_market_gate"]["status"],
            daily_market_ready=archival["daily_market_gate"]["ready"], current_price_verified=False,
            source_admission=False, economic_authority=False)
        print(c.json.dumps(public, sort_keys=True))
        return public
    except BaseException as exc:
        meter.finish("BLOCKED", str(exc) if isinstance(exc, c.Refused) else "NEW_THREE_INTERNAL")
        if isinstance(exc, (c.Refused, KeyboardInterrupt, SystemExit)):
            raise
        raise c.Refused("NEW_THREE_INTERNAL") from None


def _new3_host(c, auth, state_dir, budget_state_dir, *, forbidden=False):
    _new3_authorization(c, auth)
    require(not forbidden and budget_state_dir is not None, "NEW_THREE_HOST_SCOPE")
    budget = Path(budget_state_dir)
    family_dir = budget.resolve().parent / ("external-budget-" + c.CONTINUATION["auth"][:16])
    require(budget.is_dir() and not budget.is_symlink() and family_dir.is_dir() and not family_dir.is_symlink()
        and not Path(state_dir).is_symlink() and Path(state_dir).resolve() == budget.resolve().parent / "new3-6474160005",
        "NEW_THREE_JOURNAL_PATH")
    family = c.WorkJournal(family_dir, c.external_family_genesis())
    slot = None
    try:
        opening = auth["opening"]
        require(len(family.entries) == opening["event_count"] and family.parent == opening["family_prefix_sha256"]
            and digest(c.bounded_bytes(family_dir / "000001.json")) == opening["family_prefix_first_sha256"]
            and family.entries[0].get("kind") == "EXTERNAL_FAMILY_BOUND"
            and family.entries[0].get("budget_state_root") == os.path.normcase(str(budget.resolve())), "NEW_THREE_LEGACY_PREFIX_DRIFT")
        # The predecessor is unused, not reset or retried under a new name.
        prior_dir = budget.resolve().parent / "new3-6471394173"
        require(not prior_dir.is_symlink(), "NEW_THREE_SUPERSEDED_STATE")
        if prior_dir.exists():
            prior = c.WorkJournal(prior_dir, digest(NEW3_SUPERSEDED_ALLOCATION.encode()))
            try:
                require(not prior.entries, "NEW_THREE_SUPERSEDED_RESERVATION")
            finally:
                prior.close()
        slot = c.WorkJournal(state_dir, digest(NEW3_ALLOCATION.encode()))
        if slot.entries:
            return _new3_settle(c, auth, slot)
        _new3_source(c, auth)
        _new3_authority(c, auth)
        _new3_history(c, auth)
        # Source/authority/census are re-read directly before the single POST.
        _new3_source(c, auth)
        _new3_authority(c, auth)
        _new3_archival_gate(c, auth)
        control = dict(authorization=auth, nonce=_new3_nonce(c))
        require(len(encoded(control)) <= 16384, "NEW_THREE_CONTROL_SIZE")
        slot.append("NEW_THREE_RESERVED", nonce=_new3_nonce(c), control_sha256=_new3_hash(auth),
            allowance=dict(NEW3_CAPS), elapsed_reservation=900, old_family_prefix_sha256=family.parent)
        inputs = dict(private_root_folder_id=auth["private_root_folder_id"], private_data_folder_id=auth["private_data_folder_id"],
            private_research_authorized="true", noncommercial_terms_acknowledged="true", end_date=NEW3_END,
            max_new_symbols="3", resume_file_id="", resume_sha256="", campaign_control=encoded(control).decode(), campaign_nonce=_new3_nonce(c))
        try:
            sent = c.subprocess.run(["gh", "workflow", "run", c.WORKFLOW, "--repo", c.REPO, "--ref", "master", "--json"],
                input=c.json.dumps(inputs).encode(), stdout=c.subprocess.DEVNULL, stderr=c.subprocess.DEVNULL, timeout=45)
            require(sent.returncode == 0, "NEW_THREE_DISPATCH_UNCERTAIN")
        except Exception:
            raise c.Refused("NEW_THREE_DISPATCH_UNCERTAIN") from None
        return dict(status="NEW_THREE_POST_ACCEPTED_OUTCOME_PENDING", nonce=_new3_nonce(c),
            allocation_comment_id=6474160005, automatic_retry=False, source_admission=False)
    finally:
        try:
            if slot is not None:
                slot.close()
        finally:
            family.close()


def _new3_settle(c, auth, slot):
    """Read/account an existing attempt, including failure; never another POST."""
    first = slot.entries[0]
    require(first.get("kind") == "NEW_THREE_RESERVED" and first.get("nonce") == _new3_nonce(c)
        and first.get("control_sha256") == _new3_hash(auth) and first.get("allowance") == NEW3_CAPS
        and first.get("elapsed_reservation") == 900
        and first.get("old_family_prefix_sha256") == auth["opening"]["family_prefix_sha256"], "NEW_THREE_RESERVATION_DRIFT")
    require(len(slot.entries) <= 2, "NEW_THREE_RESERVATION_DRIFT")
    _new3_source(c, auth, accounting=True)
    _new3_authority(c, auth, accounting=True)
    rows = [r for r in c.campaign_run_pages(c) if r.get("display_title") == "a1-sip " + _new3_nonce(c)]
    require(len(rows) == 1, "NEW_THREE_DISPATCH_OUTCOME_UNKNOWN")
    run = rows[0]
    require(run.get("event") == "workflow_dispatch" and run.get("head_branch") == "master"
        and run.get("head_sha") == auth["expected_master"] and run.get("run_attempt") == 1, "NEW_THREE_SETTLEMENT_IDENTITY")
    if run.get("status") != "completed":
        require(len(slot.entries) == 1, "NEW_THREE_SETTLEMENT_DRIFT")
        return dict(status="NEW_THREE_OUTCOME_PENDING", run_id=run["id"], automatic_retry=False, source_admission=False)
    receipt = c.receipt_for_run(run, _new3_hash(auth), auth["expected_master"], NEW3_CAPS,
        allocation_profile=NEW3_PROFILE)
    require(receipt.get("allocation_profile") == NEW3_PROFILE and receipt.get("allocation_comment_id") == 6474160005
        and receipt.get("cohort_scope") == _new3_scope() and receipt.get("allowance") == NEW3_CAPS
        and receipt.get("opening_accounting_sha256") == digest(encoded(auth["opening"]))
        and receipt.get("parent_checkpoint_sha256") == c.external_genesis(_new3_scope())
        and receipt.get("examined_before") == 0 and 0 <= receipt.get("examined_after", -1) <= 3,
        "NEW_THREE_SETTLEMENT_IDENTITY")
    gate = receipt.get("archival_time_gate")
    require(isinstance(gate, dict) and isinstance(gate.get("observed_at_utc"), str)
        and receipt.get("archival_time_policy_sha256") == NEW3_ARCHIVAL_POLICY_SHA
        and receipt.get("current_price_verified") is False
        and gate == _new3_archival_gate(c, auth, observed=c.utc(gate["observed_at_utc"])),
        "NEW_THREE_ARCHIVAL_RECEIPT_CONFLICT")
    seconds = c.job_seconds(run)
    require(isinstance(run.get("created_at"), str) and isinstance(run.get("updated_at"), str),
        "NEW_THREE_SETTLEMENT_CLOCK")
    require(c.utc(run["created_at"]) <= c.utc(gate["observed_at_utc"]) <= c.utc(run["updated_at"]) <= c.utc(),
        "NEW_THREE_SETTLEMENT_CLOCK")
    elapsed = (c.utc(run["updated_at"])-c.utc(run["created_at"])).total_seconds()
    status = "COMPLETE" if receipt["status"] == "COMPLETE" and run.get("conclusion") == "success" and seconds <= 900 and elapsed <= 900 else "BLOCKED"
    record = dict(run_id=run["id"], receipt_sha256=digest(encoded(receipt)), usage=receipt["usage"],
        measured_job_seconds=seconds, canonical_elapsed_seconds=elapsed,
        status=status, checkpoint_sha256=receipt["checkpoint_sha256"])
    if len(slot.entries) == 1:
        slot.append("NEW_THREE_SETTLED", **record)
    else:
        last = slot.entries[1]
        require(last.get("kind") == "NEW_THREE_SETTLED" and all(last.get(k) == v for k, v in record.items()), "NEW_THREE_SETTLEMENT_DRIFT")
    return dict(record, status="NEW_THREE_" + status, source_admission=False, economic_authority=False)


def run(args):
    # The public API/CLI cannot silently fall back to unbudgeted collection.
    from tools.alpaca_sip_campaign import bounded_json, worker
    path = getattr(args, "campaign_control_file", None)
    require(path, "CAMPAIGN_CONTROL_REQUIRED")
    temp = os.environ.get("RUNNER_TEMP")
    require(temp and Path(temp).is_dir(), "CAMPAIGN_JOURNAL_PATH")
    return worker(args, bounded_json(path, 16384), Path(temp) / "campaign_meter.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root-folder-id", required=True)
    parser.add_argument("--private-data-folder-id", required=True)
    parser.add_argument("--resume-file-id", default="")
    parser.add_argument("--resume-sha256", default="")
    parser.add_argument("--start", default=MIN_START)
    parser.add_argument("--end", required=True)
    parser.add_argument("--max-new-symbols", type=int, default=16)
    parser.add_argument("--campaign-control-file")
    args = parser.parse_args()
    try:
        run(args)
        return 0
    except Refused as exc:
        print(json.dumps({"status": "BLOCKED", "code": str(exc),
                          "source_admission": False}))
        return 2
    except Exception:
        print(json.dumps({"status": "BLOCKED_INTERNAL",
                          "source_admission": False}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
