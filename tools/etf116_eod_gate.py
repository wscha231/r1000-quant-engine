#!/usr/bin/env python3
"""ETF116 research-only EOD intake preflight. Pure input validation, no remote calls/writes.

This is a T2 PREPARED candidate, NOT installed in the R1000 repository, not a data
collector, not a calculation engine and not an authorized publisher. Integrate via
single A1 writer and independent A6 after exact-head review.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = "etf116-eod-tr-packet-v1"
EXPECTED_UNIVERSE_SHA256 = "7ae2a5f1a679423ace1602dd2628f2853ea85b0496a4ecfea0df720dfe0530cc"
STATUS = {"VERIFIED", "BLOCKED", "STALE", "INELIGIBLE"}
BASIS = {"NAV_TR_INDEX", "MARKET_TR_INDEX"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,11}$")

class GateError(ValueError):
    pass

def require(ok, reason):
    if not ok:
        raise GateError(reason)

def timestamp(s, name):
    require(isinstance(s, str), name + "_missing")
    try:
        value = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError(name + "_invalid") from exc
    require(value.tzinfo is not None, name + "_missing_offset")
    return value.astimezone(timezone.utc)

def date(s, name):
    require(isinstance(s, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s), name + "_invalid")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as exc:
        raise GateError(name + "_invalid") from exc

def canonical_bytes(obj):
    return json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def sha(obj):
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()

def validate_universe(lines):
    tickers = [line.strip() for line in lines if line.strip()]
    require(len(tickers) == 116, "UNIVERSE_COUNT_NOT_116")
    require(len(set(tickers)) == 116, "DUPLICATE_TICKER")
    require(tickers == sorted(tickers) and all(TICKER_RE.fullmatch(t) for t in tickers), "UNIVERSE_ORDER_OR_IDENTITY")
    digest = hashlib.sha256("\n".join(tickers).encode()).hexdigest()
    require(digest == EXPECTED_UNIVERSE_SHA256, "UNIVERSE_SHA_MISMATCH")
    return tickers

def prepare(packet, frozen_tickers, prior_receipt=None):
    """Validate one licensed-provider upstream packet and return a read-only proposal.

    All input is untrusted. This method deliberately makes NO service-account,
    market-data, GitHub, Drive, or Sheets calls and never writes a current pointer.
    """
    require(isinstance(packet, dict) and packet.get("schema") == SCHEMA, "PACKET_SCHEMA")
    require(packet.get("scope_sha256") == EXPECTED_UNIVERSE_SHA256, "PACKET_SCOPE_SHA")
    session = packet.get("session")
    date(session, "session")
    close = timestamp(packet.get("official_nyse_close_utc"), "official_close")
    run_at = timestamp(packet.get("run_at_utc"), "run_at")
    require(run_at >= close + timedelta(minutes=30), "SESSION_NOT_READY_30MIN_DELAY")
    require(close.date().isoformat() == session, "SESSION_CLOSE_DATE_MISMATCH")
    close_identity = close.isoformat()
    require(close <= run_at, "FUTURE_SESSION")
    require(packet.get("nyse_session_verified") is True, "NYSE_CALENDAR_NOT_VERIFIED")
    require(packet.get("source_rights_verified") is True, "PROVIDER_RIGHTS_NOT_VERIFIED")
    require(packet.get("private_sheet_write_tested") is True, "SHEET_AUTH_NOT_VERIFIED")
    require(packet.get("a6_independent_pass") is True, "INDEPENDENT_A6_NOT_VERIFIED")
    receipt = packet.get("rights_receipt_sha256")
    require(isinstance(receipt, str) and SHA_RE.fullmatch(receipt), "RIGHTS_RECEIPT_MISSING")
    source = packet.get("source_id")
    require(isinstance(source, str) and 2 <= len(source) <= 128, "SOURCE_ID_MISSING")
    basis = packet.get("tr_basis")
    require(basis in BASIS, "TR_BASIS_INVALID")
    rows = packet.get("rows")
    require(isinstance(rows, list) and len(rows) == 116, "ROW_COUNT_NOT_116")
    ids = [r.get("ticker") for r in rows if isinstance(r, dict)]
    require(len(ids) == 116 and ids == frozen_tickers, "ROWS_NOT_EXACT_PINNED_TICKER_ORDER")
    bad, good = [], []
    for r in rows:
        t = r["ticker"]
        status = r.get("status")
        require(status in STATUS, t + "_BAD_STATUS")
        if status != "VERIFIED":
            require(isinstance(r.get("reason"), str) and len(r["reason"].strip()) >= 4, t + "_BLOCK_REASON_MISSING")
            require(r.get("tr_index") is None, t + "_BLOCKED_MUST_NOT_HAVE_TR")
            bad.append({"ticker":t,"status":status,"reason":r["reason"]})
            continue
        require(r.get("asof") == session, t + "_DATE_MISMATCH")
        value = r.get("tr_index")
        require(type(value) in (float, int) and math.isfinite(value) and value > 0, t + "_BAD_TOTAL_RETURN_INDEX")
        require(r.get("basis") == basis, t + "_MIXED_NAV_MARKET_BASIS")
        require(r.get("corporate_action_verified") is True, t + "_CA_NOT_VERIFIED")
        observed = timestamp(r.get("available_at_utc"), t + "_available_at")
        require(close <= observed <= run_at, t + "_FUTURE_OR_PREMATURE_SOURCE")
        evidence = r.get("source_sha256")
        require(isinstance(evidence, str) and SHA_RE.fullmatch(evidence), t + "_SOURCE_DIGEST_MISSING")
        good.append({"ticker":t,"asof":session,"tr_index":value,"basis":basis,"source_sha256":evidence})
    digest = sha({"schema":SCHEMA,"session":session,"rows":rows,"source_id":source,"basis":basis,"scope_sha256":EXPECTED_UNIVERSE_SHA256,"rights_receipt_sha256":receipt,"official_nyse_close_utc":close_identity})
    if prior_receipt is not None:
        require(isinstance(prior_receipt, dict), "PRIOR_RECEIPT_INVALID")
        prev_s = prior_receipt.get("session")
        date(prev_s, "prior_session")
        require(prev_s <= session, "SESSION_ROLLBACK_BLOCKED")
        if prev_s == session:
            if prior_receipt.get("input_digest") == digest:
                return {"state":"SKIP_UNCHANGED","session":session,"input_digest":digest,"rights_receipt_sha256":receipt,"official_nyse_close_utc":close_identity,"publish_enabled":False}
            raise GateError("SAME_SESSION_CONFLICT_BLOCKED")
    return {"state":"PREPARED_ONLY","session":session,"scope_sha256":EXPECTED_UNIVERSE_SHA256,
            "input_digest":digest,"rights_receipt_sha256":receipt,"official_nyse_close_utc":close_identity,"verified_count":len(good),"blocked_count":len(bad),
            "verified_rows":good,"non_publishable_rows":bad,
            "publish_enabled":False,"source_id":source,
            "next_gate":"INTEGRATE_IN_APPROVED_REPO_LANE_AND_VERIFY_GOOGLE_SHEETS_WRITE"}

def main():
    p = argparse.ArgumentParser(description="ETF116 fail-closed EOD research preflight (no writes outside --output)")
    p.add_argument("--frozen",required=True)
    p.add_argument("--packet",required=True)
    p.add_argument("--prior-receipt")
    p.add_argument("--output",required=True)
    args=p.parse_args()
    tickers=validate_universe(Path(args.frozen).read_text().splitlines())
    packet=json.loads(Path(args.packet).read_text())
    prior=json.loads(Path(args.prior_receipt).read_text()) if args.prior_receipt else None
    result=prepare(packet,tickers,prior)
    with Path(args.output).open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:result[k] for k in ("state","session","input_digest","publish_enabled")},sort_keys=True))

if __name__=="__main__":main()
