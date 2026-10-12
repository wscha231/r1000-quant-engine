#!/usr/bin/env python3
"""Bounded, resumable Alpaca SIP 1Day research backfill.

No trading, fullrun, research admission, public original upload, or automatic
portfolio change. Original vendor bytes are private and gated by owner consent.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
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
    query = {
        "symbols": ",".join(symbols), "timeframe": "1Day",
        "start": start, "end": end, "adjustment": adjustment,
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
            dest.writestr(name, members[name])
    return stream.getvalue()


def resume_state(drive: OwnerDrive, folder: str, file_id: str, sha: str,
                 seed_sha: str, start: str, end: str) -> tuple[list[str], dict | None]:
    if not file_id and not sha:
        return [], None
    require(bool(file_id and re.fullmatch(r"[a-f0-9]{64}", sha)), "RESUME_PAIR")
    drive.check(file_id, folder, folder=False)
    original = drive.read(file_id, 2_000_000)
    require(digest(original) == sha, "RESUME_HASH")
    receipt = decode(original)
    require(isinstance(receipt, dict) and receipt.get("schema") == SCHEMA
            and receipt.get("seed_sha256") == seed_sha
            and receipt.get("start") == start and receipt.get("end") == end
            and receipt.get("source") == SOURCE
            and receipt.get("state") == "PRIVATE_RESEARCH_ONLY"
            and receipt.get("source_admission") is False,
            "RESUME_CONTEXT")
    done = receipt.get("completed")
    require(isinstance(done, list) and len(done) == len(set(done))
            and all(isinstance(s, str) and SYMBOL.fullmatch(s) for s in done),
            "RESUME_MEMBERSHIP")
    objects = receipt.get("last_objects")
    if objects is not None:
        require(isinstance(objects, list) and len(objects) == 3, "RESUME_OBJECTS")
        for obj in objects:
            require(isinstance(obj, dict) and "file_id" in obj
                    and re.fullmatch(r"[a-f0-9]{64}", str(obj.get("sha256"))),
                    "RESUME_OBJECTS")
            drive.check(obj["file_id"], folder, folder=False)
            require(digest(drive.read(obj["file_id"])) == obj["sha256"],
                    "RESUME_OBJECT_HASH")
    return done, {"file_id": file_id, "sha256": sha}


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
    raw_obj = drive.write(folder, zipped, ".zip")
    normalized_bytes = gzip.compress(
        b"".join(encoded(r) for r in normalized), mtime=0,
    )
    norm_obj = drive.write(folder, normalized_bytes, ".jsonl.gz")
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
    rec_obj = drive.write(folder, encoded(receipt), ".json")
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
        require(set(done) <= set(names), "RESUME_UNIVERSE")
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
            checkpoint = drive.write(
                args.private_data_folder_id, encoded(state), ".json",
            )
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
