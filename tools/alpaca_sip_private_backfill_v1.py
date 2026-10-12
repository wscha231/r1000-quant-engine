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
MAX_CHECKPOINT_CHAIN = 1200
MAX_PAGE_BYTES = 8_000_000
MAX_PAGES = 25
GROUP_SIZE = 4
SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,13}")


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


def resume_state(drive: OwnerDrive, folder: str, file_id: str, sha: str,
                 seed_sha: str, start: str, end: str) -> tuple[list[str], dict | None]:
    if not file_id and not sha:
        return [], None
    require(isinstance(file_id, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", file_id)
            and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha),
            "RESUME_PAIR")
    original_ref = {"file_id": file_id, "sha256": sha}
    pointer = original_ref
    seen = set()
    expected = None
    final_completed = None
    for _ in range(MAX_CHECKPOINT_CHAIN):
        require(pointer["file_id"] not in seen, "RESUME_CYCLE")
        seen.add(pointer["file_id"])
        # Older checkpoint references historically use id/hash, not byte count.
        drive.check(pointer["file_id"], folder, folder=False)
        original = drive.read(pointer["file_id"], 2_000_000)
        require(digest(original) == pointer["sha256"], "RESUME_HASH")
        state = decode(original)
        require(isinstance(state, dict) and state.get("schema") == SCHEMA
                and state.get("seed_sha256") == seed_sha
                and state.get("start") == start and state.get("end") == end
                and state.get("source") == SOURCE
                and state.get("state") == "PRIVATE_RESEARCH_ONLY"
                and state.get("source_admission") is False
                and state.get("historical_identity_verified") is False
                and state.get("pit_verified") is False,
                "RESUME_CONTEXT")
        done = state.get("completed")
        require(isinstance(done, list) and done and len(done) <= 1500
                and len(done) == len(set(done))
                and all(isinstance(s, str) and SYMBOL.fullmatch(s) for s in done),
                "RESUME_MEMBERSHIP")
        if expected is None:
            final_completed = done
        else:
            require(done == expected, "RESUME_CHAIN_MEMBERSHIP")
        refs = state.get("last_objects")
        require(isinstance(refs, list) and len(refs) == 3, "RESUME_OBJECTS")
        raw_pack = _private_object(drive, folder, refs[0])
        normalized_pack = _private_object(drive, folder, refs[1])
        receipt_bytes = _private_object(drive, folder, refs[2], 2_000_000)
        receipt = decode(receipt_bytes)
        require(isinstance(receipt, dict) and receipt.get("schema") == SCHEMA
                and receipt.get("scope") == "PRIVATE_RESEARCH_ONLY"
                and receipt.get("source") == SOURCE
                and receipt.get("seed_sha256") == seed_sha
                and receipt.get("start") == start
                and receipt.get("end") == end
                and receipt.get("source_admission") is False
                and receipt.get("readback_verified") is True
                and receipt.get("raw_object") == refs[0]
                and receipt.get("normalized_object") == refs[1],
                "RESUME_RECEIPT_BINDING")
        # A matching compressed byte hash alone is sufficient for preservation;
        # no provider body is printed or sent to an untrusted consumer.
        require(raw_pack[:2] == b"PK" and normalized_pack[:2] == b"\x1f\x8b",
                "RESUME_FORMAT")
        current_symbols = receipt.get("symbols")
        collected = receipt.get("collected")
        absent = receipt.get("no_bars")
        require(isinstance(current_symbols, list)
                and 1 <= len(current_symbols) <= GROUP_SIZE
                and len(current_symbols) == len(set(current_symbols))
                and all(isinstance(s, str) and SYMBOL.fullmatch(s)
                        for s in current_symbols)
                and isinstance(collected, list) and isinstance(absent, list)
                and set(collected).isdisjoint(set(absent))
                and set(collected) | set(absent) == set(current_symbols)
                and state.get("last_collected") == collected
                and state.get("last_no_bars") == absent
                and done[-len(current_symbols):] == current_symbols,
                "RESUME_CHAIN_MEMBERSHIP")
        prefix = done[:-len(current_symbols)]
        previous = state.get("previous_checkpoint")
        if previous is None:
            require(prefix == [], "RESUME_CHAIN_TRUNCATED")
            return final_completed, original_ref
        require(isinstance(previous, dict)
                and isinstance(previous.get("file_id"), str)
                and re.fullmatch(r"[A-Za-z0-9_-]{10,100}", previous["file_id"])
                and isinstance(previous.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", previous["sha256"])
                and prefix, "RESUME_CHAIN")
        expected = prefix
        pointer = previous
    raise Refused("RESUME_CHAIN_LIMIT")


def capture_one_group(drive: OwnerDrive, folder: str, symbols: list[str],
                      start: str, end: str, key: str, secret: str,
                      seed_sha: str, source_sha: str):
    raw_members, evidence, results = {}, [], {}
    for adjustment in ("raw", "split"):
        members, grouped, pages = request_pages(
            symbols, adjustment, start, end, key, secret,
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
    require(bool(collected), "GROUP_EMPTY")
    meta = {
        "schema": SCHEMA, "source": SOURCE, "symbols": list(symbols),
        "collected": collected, "no_bars": missing, "start": start, "end": end,
        "seed_sha256": seed_sha, "source_sha": source_sha,
        "pages": evidence, "raw_adjustments": ["raw", "split"],
        "historical_identity_verified": False, "pit_verified": False,
        "source_admission": False, "commercial_use_authorized": False,
    }
    raw_members["capture.json"] = encoded(meta)
    zipped = zip_bytes(raw_members)
    require(0 < len(zipped) < 16_000_000, "PACK_BUDGET")
    raw_obj = persist_object(drive, folder, zipped, ".zip")
    normalized_bytes = gzip.compress(
        b"".join(encoded(r) for r in normalized), mtime=0,
    )
    norm_obj = persist_object(drive, folder, normalized_bytes, ".jsonl.gz")
    receipt = {
        "schema": SCHEMA, "scope": "PRIVATE_RESEARCH_ONLY",
        "source": SOURCE, "run_id": os.environ.get("GITHUB_RUN_ID"),
        "source_sha": source_sha, "seed_sha256": seed_sha,
        "start": start, "end": end,
        "symbols": symbols, "collected": collected, "no_bars": missing,
        "pages": len(evidence), "rows": len(normalized),
        "raw_object": raw_obj, "normalized_object": norm_obj,
        "readback_verified": True, "source_admission": False,
        "pit_verified": False, "historical_identity_verified": False,
        "commercial_use_authorized": False,
    }
    rec_obj = persist_object(drive, folder, encoded(receipt), ".json")
    return [raw_obj, norm_obj, rec_obj], collected, missing, len(normalized)


def run(args):
    require(os.getenv("A1_PRIVATE_RESEARCH_AUTHORIZED") == "true",
            "USER_AUTHORIZATION_MISSING")
    require(os.getenv("ALPACA_NONCOMMERCIAL_ACKNOWLEDGED") == "true",
            "PROVIDER_TERMS_NOT_ACKNOWLEDGED")
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and os.environ.get("GITHUB_REF") == "refs/heads/master",
            "REPOSITORY_SCOPE")
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_API_SECRET", "").strip()
    require(key and secret, "CREDENTIALS_MISSING")
    require(args.start == MIN_START and MIN_START < args.end <= date.today().isoformat(),
            "DATE_SCOPE")
    require(1 <= args.max_new_symbols <= 32, "BATCH_SCOPE")
    seed = SEED.read_bytes()
    names = cohort(seed)
    seed_sha = digest(seed)
    with tempfile.TemporaryDirectory(prefix="a1-alpaca-private-") as tmp:
        drive = OwnerDrive(args.private_root_folder_id, tmp)
        drive.check(args.private_data_folder_id, drive.root_id)
        done, prior = resume_state(
            drive, args.private_data_folder_id,
            args.resume_file_id, args.resume_sha256,
            seed_sha, args.start, args.end,
        )
        require(done == names[:len(done)], "RESUME_UNIVERSE")
        selected = [s for s in names if s not in set(done)][:args.max_new_symbols]
        require(bool(selected), "COHORT_COMPLETE")
        completed, held, checkpoint, row_count = done[:], [], prior, 0
        for offset in range(0, len(selected), GROUP_SIZE):
            group = selected[offset:offset + GROUP_SIZE]
            objs, accepted, missing, rows = capture_one_group(
                drive, args.private_data_folder_id, group, args.start, args.end,
                key, secret, seed_sha, os.environ.get("GITHUB_SHA", ""),
            )
            completed.extend(group)
            held.extend(missing)
            row_count += rows
            state = {
                "schema": SCHEMA, "state": "PRIVATE_RESEARCH_ONLY",
                "source": SOURCE, "seed_sha256": seed_sha,
                "start": args.start, "end": args.end, "completed": completed,
                "last_objects": objs, "previous_checkpoint": checkpoint,
                "last_collected": accepted, "last_no_bars": missing,
                "historical_identity_verified": False, "pit_verified": False,
                "source_admission": False, "commercial_use_authorized": False,
            }
            checkpoint = persist_object(
                drive, args.private_data_folder_id, encoded(state), ".json",
            )
            print(json.dumps({
                "status": "PRIVATE_CHECKPOINT_SAVED",
                "completed_or_examined": len(completed),
                "checkpoint": checkpoint,
                "last_no_bars": len(missing),
                "source_admission": False,
            }, sort_keys=True))
        print(json.dumps({
            "status": "PRIVATE_HISTORY_BATCH_RESTORED",
            "seed_count": len(names), "attempted_new": len(selected),
            "total_completed_or_examined": len(completed),
            "held_no_data": len(held), "rows_new": row_count,
            "checkpoint": checkpoint,
            "public_provider_bytes_uploaded": False,
            "source_admission": False, "economic_authority": False,
        }, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root-folder-id", required=True)
    parser.add_argument("--private-data-folder-id", required=True)
    parser.add_argument("--resume-file-id", default="")
    parser.add_argument("--resume-sha256", default="")
    parser.add_argument("--start", default=MIN_START)
    parser.add_argument("--end", required=True)
    parser.add_argument("--max-new-symbols", type=int, default=16)
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
