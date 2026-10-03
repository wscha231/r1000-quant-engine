"""P0-3 SEC/price producer adapters. Assembly is NOT input approval.

Reads captured SEC columnar JSON and explicit price CSV exports. Retains
8-K/6-K/amendments and missing history in the review denominator. Never infers
contract amounts, positive sentiment, historical listing, or publication time.
An external human/source review supplies those facts before bundle assembly.
No network, training, selector, broker, Drive commit or model promotion here.
"""
from __future__ import annotations

from bisect import bisect_left
import csv
from datetime import date
import io
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from .admission import (HEX40, HEX64, MAX_BUNDLE_BYTES, MAX_FILE_BYTES, checked_file,
                        json_load, read_bounded, reparse_point, rows, safe_rel, sha256,
                        verify_bundle, CONSUMER)
from .execution import ExecutionBook, number, require, validate_policy
from .runtime import (CHECKPOINTS, ContractError, canonical_bytes, normalize_event,
                      strict_bool, utc, validate_sessions)

FORMS = {"8-K", "8-K/A", "6-K", "6-K/A"}
ITEMS = {
    "1.01": "MATERIAL_AGREEMENT_UNCLASSIFIED",
    "1.02": "AGREEMENT_TERMINATION",
    "1.03": "BANKRUPTCY_OR_RECEIVERSHIP",
    "2.01": "ASSET_TRANSACTION",
    "2.02": "EARNINGS_DISCLOSURE",
    "2.03": "FINANCIAL_OBLIGATION",
    "2.04": "OBLIGATION_TRIGGER",
    "2.05": "EXIT_OR_DISPOSAL_COST",
    "2.06": "MATERIAL_IMPAIRMENT",
    "3.01": "LISTING_NOTICE",
    "3.02": "UNREGISTERED_EQUITY_SALE",
    "4.02": "FINANCIAL_STATEMENT_NONRELIANCE",
}
ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
MAX_INPUT_FILES = 1200


def cik10(value: Any) -> str:
    require(type(value) in (str, int) and type(value) is not bool, "INVALID_CIK")
    text = str(value)
    require(bool(re.fullmatch(r"[0-9]{1,10}", text)) and int(text) > 0, "INVALID_CIK")
    return text.zfill(10)


def day(value: Any) -> date:
    require(type(value) is str and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), "INVALID_DATE")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError("INVALID_DATE") from exc


def sec_url(value: Any) -> str:
    """Only exact SEC submission or accession paths; no query/redirect targets."""
    require(type(value) is str and value.isascii() and not any(ord(c) < 33 for c in value), "SEC_URL")
    u = urlsplit(value)
    require(u.scheme == "https" and u.netloc in {"data.sec.gov", "www.sec.gov"}
            and not u.query and not u.fragment and not u.username and not u.password, "SEC_URL")
    if u.netloc == "data.sec.gov":
        require(bool(re.fullmatch(r"/submissions/CIK[0-9]{10}(?:-submissions-[0-9]{3})?\.json", u.path)), "SEC_URL")
    else:
        require(bool(re.fullmatch(r"/Archives/edgar/data/[1-9][0-9]{0,9}/[0-9]{18}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}", u.path)), "SEC_URL")
        require(".." not in u.path.split("/")[-1], "SEC_URL")
    return value


def filing_url(cik: str, accession: str, filename: str) -> str:
    require(type(accession) is str and ACCESSION.fullmatch(accession), "ACCESSION_FORMAT")
    return sec_url(f"https://www.sec.gov/Archives/edgar/data/{int(cik10(cik))}/{accession.replace('-', '')}/{filename}")


def _items(value: Any) -> list[str]:
    require(type(value) is str, "ITEMS_TYPE")
    if not value.strip():
        return []
    out = re.split(r"[\s,;]+", value.strip())
    require(all(re.fullmatch(r"[1-9]\.[0-9]{2}", t) for t in out), "ITEMS_FORMAT")
    return sorted(set(out))


def parse_submissions(raw: bytes, *, cik: str, source_url: str,
                      ingested_at: str, window_start: str, window_end: str) -> dict:
    """SEC current (filings.recent) AND older flat columnar JSON.

    Uses filing date only for coarse collection windows, never intraday timing.
    Date-only accepted fields remain unavailable, not midnight-UTC inventions.
    Additional history descriptors remain explicit requests until supplied.
    """
    cik = cik10(cik)
    u = sec_url(source_url)
    require(u.startswith(f"https://data.sec.gov/submissions/CIK{cik}"), "SOURCE_CIK_MISMATCH")
    ingest = utc(ingested_at)
    start, end = day(window_start), day(window_end)
    require(start <= end, "WINDOW_ORDER")
    p = json_load(raw)
    require(type(p) is dict, "SEC_PAYLOAD")
    current = "filings" in p
    if current:
        require(cik10(p.get("cik")) == cik, "PAYLOAD_CIK_MISMATCH")
        require(type(p["filings"]) is dict and type(p["filings"].get("recent")) is dict, "SEC_RECENT_SHAPE")
        cols = p["filings"]["recent"]
        history = p["filings"].get("files", [])
    else:
        cols, history = p, []
        require("-submissions-" in u, "FLAT_JSON_REQUIRES_ARCHIVE_URL")
    require(type(history) is list, "HISTORY_DESCRIPTORS")
    required = ("accessionNumber", "form", "filingDate", "primaryDocument")
    require(all(type(cols.get(k)) is list for k in required), "SEC_REQUIRED_COLUMNS")
    n = len(cols["accessionNumber"])
    require(n <= 100000, "SEC_ROW_BUDGET")
    for k, v in cols.items():
        require(type(v) is list and len(v) == n, "SEC_COLUMN_LENGTH:" + str(k))
    candidates, excluded = [], []
    for i in range(n):
        acc, form, filed, primary = (cols[k][i] for k in required)
        require(type(acc) is str and bool(ACCESSION.fullmatch(acc)), "ACCESSION_FORMAT")
        require(type(form) is str and type(primary) is str, "SEC_ROW_TYPES")
        form = form.strip().upper()
        fd = day(filed)
        ident = f"sec:{cik}:{acc}"
        if not start <= fd <= end or form not in FORMS:
            excluded.append({"candidate_id": ident, "form": form,
                             "reason": "OUTSIDE_COLLECTION_WINDOW" if not start <= fd <= end else "UNSUPPORTED_FORM"})
            continue
        accepted = cols.get("acceptanceDateTime", [None] * n)[i]
        accepted_at = None
        blockers = ["PUBLICATION_TIME_REVIEW_REQUIRED", "HISTORICAL_SECURITY_REVIEW_REQUIRED",
                    "ECONOMIC_MEANING_REVIEW_REQUIRED"]
        if type(accepted) is str and len(accepted) > 10:
            # UTC offset must actually exist in source. Do not repair naive time.
            try:
                dt = utc(accepted)
                require(dt <= ingest, "ACCEPTANCE_AFTER_INGEST")
                accepted_at = dt.isoformat()
            except (ValueError, TypeError):
                blockers.append("ACCEPTANCE_TIME_INVALID_OR_UNZONED")
        else:
            blockers.append("ACCEPTANCE_TIME_MISSING")
        item_value = cols.get("items", [""] * n)[i]
        item_codes = _items("" if item_value is None else item_value)
        # 6-K doesn't share 8-K's item taxonomy even if a bad producer supplies it.
        tags = [ITEMS[t] for t in item_codes if t in ITEMS] if form.startswith("8-K") else ["FPI_DISCLOSURE_UNCLASSIFIED"]
        if not tags:
            tags = ["CURRENT_REPORT_UNCLASSIFIED"]
        primary_url = None
        if primary:
            primary_url = filing_url(cik, acc, primary)
        else:
            blockers.append("PRIMARY_DOCUMENT_MISSING")
        candidates.append({
            "candidate_id": ident, "cik": cik, "accession_number": acc,
            "form_type": form, "is_amendment": form.endswith("/A"),
            "amends_event_id": None, "filing_date": filed,
            "accepted_at": accepted_at, "source_public_at": None,
            "available_at": None, "first_seen_in_capture_at": ingest.isoformat(),
            "primary_document": primary, "primary_document_url": primary_url,
            "sec_items": item_codes, "descriptive_event_tags": tags,
            "economic_amount_usd": None, "business_relation_new": None,
            "official_document": True, "role": None, "sentiment": None,
            "listing_verified": False, "candidate_state": "REVIEW_REQUIRED",
            "blockers": sorted(set(blockers)),
            "source_refs": [{"url": u, "raw_sha256": sha256(raw), "row_index": i,
                             "ingested_at": ingest.isoformat()}],
        })
    requests = []
    for h in history:
        require(type(h) is dict, "HISTORY_DESCRIPTOR")
        name = h.get("name")
        require(type(name) is str and re.fullmatch(r"CIK" + cik + r"-submissions-[0-9]{3}\.json", name), "HISTORY_FILENAME")
        a, z = day(h.get("filingFrom")), day(h.get("filingTo"))
        require(a <= z, "HISTORY_RANGE")
        if a <= end and z >= start:
            requests.append({"source_url": sec_url("https://data.sec.gov/submissions/"+name),
                             "cik": cik, "filing_from": a.isoformat(), "filing_to": z.isoformat()})
    require(len({r["source_url"] for r in requests}) == len(requests), "DUPLICATE_HISTORY_DESCRIPTOR")
    return {"schema": "news-sec-index-p0.3", "candidates": candidates,
            "excluded_records": excluded, "history_requests": requests,
            "source_rows": n, "selection_rule": "FORM_AND_FILING_DATE_ONLY_NO_RETURN_FILTER"}


def merge_indexes(indexes: list[dict], supplied_urls: set[str]) -> dict:
    """Same source event twice is one candidate. Disagreement never best-wins."""
    out, excluded, required = {}, [], {}
    for ix in indexes:
        excluded.extend(ix["excluded_records"])
        for h in ix["history_requests"]:
            required[h["source_url"]] = h
        for c in ix["candidates"]:
            key = c["candidate_id"]
            if key in out:
                prior = out[key]
                ignored = {"source_refs", "first_seen_in_capture_at"}
                require({k:v for k,v in prior.items() if k not in ignored} ==
                        {k:v for k,v in c.items() if k not in ignored}, "CONFLICTING_SEC_EVENT:"+key)
                prior["source_refs"] = sorted({canonical_bytes(r):r for r in prior["source_refs"]+c["source_refs"]}.values(), key=lambda r:(r["url"],r["row_index"]))
                prior["first_seen_in_capture_at"] = min(prior["first_seen_in_capture_at"],c["first_seen_in_capture_at"])
            else:
                out[key] = dict(c)
    missing = sorted(set(required) - supplied_urls)
    return {"schema": "news-sec-index-set-p0.3",
            "candidates": sorted(out.values(),key=lambda c:(c["filing_date"],c["candidate_id"])),
            "excluded_records": excluded, "unresolved_history_urls": missing,
            "declared_history_pages_complete": not missing,
            "whole_us_market_coverage": False,
            "source_rows": sum(ix["source_rows"] for ix in indexes)}


def parse_price_csv(raw: bytes) -> list[dict]:
    """Adapter for an explicitly documented USD total-return export, NOT OHLC.

    Refuses AdjClose/raw-close fallback, invented listing, or availability. A
    provider exporter must supply all fields and its own provenance/rights.
    """
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    except UnicodeError as exc:
        raise ContractError("PRICE_CSV_ENCODING") from exc
    required = {"stable_security_id", "session", "total_return_index", "available_at",
                "currency", "feed", "return_convention", "status", "tradable"}
    fields = reader.fieldnames or []
    require(len(set(fields)) == len(fields) and required.issubset(fields), "PRICE_CSV_COLUMNS")
    allowed = required | {"volume", "terminal_evidence_id"}
    require(set(fields).issubset(allowed), "PRICE_CSV_UNKNOWN_COLUMNS")
    result = []
    for r in reader:
        require(None not in r and None not in r.values(), "PRICE_CSV_ROW_LENGTH")
        t = r["tradable"].strip().lower()
        require(t in {"true", "false"}, "PRICE_BOOLEAN")
        r["tradable"] = t == "true"
        for k in ("total_return_index", "volume"):
            text = r.get(k, "").strip()
            if not text:
                r[k] = None
            else:
                try:
                    value = float(text)
                except ValueError as exc:
                    raise ContractError("PRICE_NUMBER") from exc
                require(math.isfinite(value) and value >= 0, "PRICE_NUMBER")
                r[k] = value
        day(r["session"])
        utc(r["available_at"])
        result.append(r)
        require(len(result) <= 100000, "PRICE_ROW_BUDGET")
    require(bool(result), "EMPTY_PRICE_EXPORT")
    return result


EXPORT_SINGLE = {"reviews", "prices_csv", "sessions", "securities", "documents", "rights", "policy", "config"}
EXPORT_EXTRA = {"sec_submissions", "raw_object", "rights_evidence", "calendar_evidence", "policy_source"}


def load_export(root: Path, *, now: str, index_only: bool = False) -> tuple[dict, dict[str,bytes], dict]:
    root = Path(root)
    require(root.is_dir() and not reparse_point(root), "EXPORT_ROOT")
    raw = read_bounded(checked_file(root, "export_manifest.json"))
    manifest = json_load(raw)
    require(type(manifest) is dict, "EXPORT_MANIFEST_OBJECT")
    entries = manifest.get("files")
    require(type(entries) is list and 0 < len(entries) <= MAX_INPUT_FILES, "EXPORT_FILE_COUNT")
    members, total = {}, 0
    for entry in entries:
        require(type(entry) is dict, "EXPORT_ROLE")
        name = safe_rel(entry.get("path"))
        require(name != "export_manifest.json" and name not in members, "EXPORT_DUPLICATE_PATH")
        data = read_bounded(checked_file(root, name))
        total += len(data)
        require(total <= MAX_BUNDLE_BYTES, "EXPORT_BYTES_BUDGET")
        members[name] = data
    actual = set()
    for path in root.rglob("*"):
        require(not reparse_point(path), "EXPORT_REPARSE_POINT")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    require(actual == set(members) | {"export_manifest.json"}, "EXPORT_UNDECLARED_FILE")
    return load_export_snapshot(raw, members, now=now, index_only=index_only)


def load_export_snapshot(raw: bytes, members: dict[str, bytes], *, now: str,
                         index_only: bool = False) -> tuple[dict, dict[str,bytes], dict]:
    """Validate already frozen bytes; semantic consumers must not reread disk.

    This is the same export contract as load_export, not a weaker admission path.
    Byte snapshots prevent filesystem updates between hashing and interpretation.
    """
    require(type(raw) is bytes and len(raw) <= MAX_FILE_BYTES, "EXPORT_MANIFEST_BYTES")
    require(type(members) is dict and len(members) <= MAX_INPUT_FILES, "EXPORT_MEMBER_COUNT")
    members = dict(members)
    m = json_load(raw)
    require(type(m) is dict, "EXPORT_MANIFEST_OBJECT")
    require(m.get("schema") == "news-source-export-p0.3", "EXPORT_SCHEMA")
    require(m.get("origin") in {"SYNTHETIC_TEST", "HISTORICAL_RECONSTRUCTION", "FORWARD_OBSERVED"}, "EXPORT_ORIGIN")
    require(HEX40.fullmatch(str(m.get("source_commit",""))) is not None,"EXPORT_SOURCE_COMMIT")
    require(utc(m["data_cutoff"]) <= utc(m["generated_at"]) <= utc(now), "EXPORT_CLOCK")
    require(day(m["window_start"]) <= day(m["window_end"]), "EXPORT_WINDOW")
    require(type(m.get("selection_rule")) is str and bool(m["selection_rule"].strip()), "EXPORT_SELECTION_RULE")
    entries = m.get("files")
    require(type(entries) is list and 0 < len(entries) <= MAX_INPUT_FILES, "EXPORT_FILE_COUNT")
    files, roles, casenames, total = {}, {}, set(), 0
    for e in entries:
        require(type(e) is dict and e.get("role") in EXPORT_SINGLE | EXPORT_EXTRA, "EXPORT_ROLE")
        path = safe_rel(e.get("path"))
        require(path != "export_manifest.json" and not path.startswith("_adapter/") and path.casefold() not in casenames, "EXPORT_DUPLICATE_PATH")
        casenames.add(path.casefold())
        require(type(e.get("bytes")) is int and 0 <= e["bytes"] <= MAX_FILE_BYTES, "EXPORT_FILE_BYTES")
        total += e["bytes"]
        require(total <= MAX_BUNDLE_BYTES, "EXPORT_BYTES_BUDGET")
        data = members.get(path)
        require(type(data) is bytes and len(data) <= MAX_FILE_BYTES, "EXPORT_MEMBER_BYTES")
        require(len(data) == e["bytes"] and sha256(data) == e.get("sha256"), "EXPORT_HASH_MISMATCH:"+path)
        require(type(e.get("source_id")) is str and bool(e["source_id"]), "EXPORT_SOURCE_ID")
        files[path] = data
        if e["role"] in EXPORT_SINGLE:
            require(e["role"] not in roles, "EXPORT_DUPLICATE_ROLE")
            roles[e["role"]] = path
        if e["role"] == "sec_submissions":
            require(utc(e["ingested_at"]) <= utc(m["generated_at"]), "CAPTURE_CLOCK")
    require(set(members) == set(files), "EXPORT_UNDECLARED_FILE")
    require(any(e["role"] == "sec_submissions" for e in entries), "SEC_SOURCE_MISSING")
    require(index_only or set(roles) == EXPORT_SINGLE, "EXPORT_MISSING_ROLES")
    m["_export_sha256"] = sha256(raw)
    return m, files, roles


def index_export(m: dict, files: dict[str,bytes]) -> dict:
    entries = [e for e in m["files"] if e["role"] == "sec_submissions"]
    indexes = [parse_submissions(files[e["path"]], cik=e["cik"], source_url=e["source_url"],
                                ingested_at=e["ingested_at"], window_start=m["window_start"],
                                window_end=m["window_end"]) for e in entries]
    return merge_indexes(indexes, {e["source_url"] for e in entries})


def _security(securities: list[dict], sid: str, session: str, decision: str, cik: str) -> dict:
    found = [s for s in securities if s.get("stable_security_id") == sid
             and s["valid_from"] <= session <= s["valid_to"]]
    require(len(found) == 1, "SECURITY_MAPPING_MISSING_OR_AMBIGUOUS")
    s = found[0]
    require(s.get("instrument") in {"COMMON","ADR"} and s.get("listing_country") == "US"
            and s.get("exchange") in {"XNYS","XNAS","XASE"}, "CANDIDATE_LISTING_INELIGIBLE")
    require(cik10(s.get("cik")) == cik, "REVIEW_ISSUER_CIK_MISMATCH")
    require(utc(s["known_at"]) <= utc(decision), "SECURITY_NOT_KNOWN")
    return s


def build_snapshots(candidates: list[dict], reviews: list[dict], securities: list[dict],
                    documents: list[dict], prices: list[dict], sessions: list[dict],
                    *, origin: str, cutoff: str, generated_at: str, benchmark: str) -> tuple[list, list, list]:
    """Review-gated bridge. Empty reviews yield explicit exclusions, not guesses.

    P0-3 supports new accessions (including /A) as separate episodes. Linking an
    amendment to a previous economic event is preserved for review but not
    guessed. In-place event-history revision is intentionally not attempted.
    """
    book = ExecutionBook(prices, sessions, as_of=cutoff)
    docs = {d["document_id"]:d for d in documents}
    require(len(docs)==len(documents), "DUPLICATE_REVIEW_DOCUMENT")
    candidate_map = {c["candidate_id"]:c for c in candidates}
    review_map, seen = {}, set()
    for r in reviews:
        require(type(r) is dict and r.get("candidate_id") in candidate_map, "UNKNOWN_REVIEW_CANDIDATE")
        k = (r["candidate_id"], r.get("stable_security_id"))
        require(type(k[1]) is str and bool(k[1]) and k not in seen, "DUPLICATE_OR_INVALID_REVIEW")
        seen.add(k); review_map.setdefault(k[0], []).append(r)
    snapshots, rejected, checkpoint_notes = [], [], []
    for c in candidates:
        rs = review_map.get(c["candidate_id"], [])
        if not rs:
            rejected.append({"event_id": c["candidate_id"], "reason": "NO_REVIEW"})
            continue
        for r in rs:
            ident = c["candidate_id"] + "|" + r["stable_security_id"]
            # Row-level known incompleteness is auditable; malformed contracts block.
            if r.get("state") == "REJECTED":
                require(type(r.get("reason")) is str and bool(r["reason"]), "REJECTION_REASON")
                rejected.append({"event_id": ident, "reason": r["reason"]})
                continue
            require(r.get("state") == "REVIEWED_FOR_ASSEMBLY_NOT_APPROVAL", "REVIEW_STATE")
            require(type(r.get("reviewer_id")) is str and bool(r["reviewer_id"]), "REVIEWER_ID")
            require(utc(r["reviewed_at"]) <= utc(generated_at), "REVIEW_CLOCK")
            if c["accepted_at"] is None:
                rejected.append({"event_id": ident, "reason": "ACCEPTANCE_TIME_REVIEW_REQUIRED"})
                continue
            available = utc(r["available_at"])
            require(utc(c["accepted_at"]) <= available <= utc(cutoff), "REVIEW_EVENT_AVAILABILITY")
            require(r.get("publication_time_basis") == "DOCUMENTED_PUBLIC_TIME_WITH_EVIDENCE", "PUBLIC_TIME_NOT_VERIFIED")
            evidence_id = r.get("publication_evidence_document_id")
            require(evidence_id in docs, "PUBLIC_TIME_EVIDENCE_MISSING")
            refs = r.get("source_document_ids")
            require(type(refs) is list and bool(refs) and evidence_id in refs and len(refs)==len(set(refs)), "REVIEW_SOURCE_REFS")
            require(all(d in docs for d in refs), "REVIEW_DOCUMENT_MISSING")
            require(any(docs[d]["source_url"] == c["primary_document_url"] for d in refs), "PRIMARY_DOCUMENT_NOT_BOUND")
            for did in refs:
                require(utc(docs[did]["source_public_at"]) <= available, "LATE_EVIDENCE_AT_EVENT")
            if origin == "FORWARD_OBSERVED":
                require(utc(r["reviewed_at"]) <= available and all(utc(docs[d]["ingested_at"]) <= available for d in refs), "RECONSTRUCTION_NOT_FORWARD")
            require(r.get("event_version",1) == 1 and type(r.get("event_version",1)) is int, "NEW_ACCESSION_VERSION_MUST_BE_ONE")
            for name in ("economic_value_confirmed", "business_relation_new"):
                strict_bool(r.get(name,False), name)
            # No amount/relationship assertion without a reviewed field-specific citation.
            for flag, fact in (("economic_value_confirmed", "economic_amount_usd"), ("business_relation_new", "business_relation_new")):
                if r.get(flag,False):
                    citation = r.get("fact_evidence",{}).get(fact)
                    require(type(citation) is dict and citation.get("document_id") in refs
                            and type(citation.get("locator")) is str and bool(citation["locator"]), "FACT_EVIDENCE_MISSING:"+fact)
            if r.get("economic_value_confirmed",False):
                number(r.get("economic_amount_usd"), "economic_amount_usd")
                require(r.get("economic_currency") == "USD", "REVIEW_AMOUNT_CURRENCY")
                require(r.get("economic_amount_kind") in {"GUARANTEED","EXPECTED_DELIVERIES","CEILING","RECOGNIZED_REVENUE"}, "AMOUNT_KIND")
            else:
                require(r.get("economic_amount_usd") is None, "UNCONFIRMED_AMOUNT")
            event_pos = bisect_left(book.closes, available)
            made = 0
            for cp in CHECKPOINTS:
                p = event_pos + cp
                if p >= len(book.dates) or book.closes[p] > utc(cutoff):
                    checkpoint_notes.append({"event_id":ident, "checkpoint":cp, "reason":"CHECKPOINT_NOT_MATURE"})
                    continue
                session = book.dates[p]
                quotes = [book.row(sid,session) for sid in (r["stable_security_id"],benchmark)]
                if any(q is None or q["status"] != "ACTIVE" for q in quotes):
                    checkpoint_notes.append({"event_id":ident, "checkpoint":cp, "reason":"CHECKPOINT_PRICE_MISSING_OR_INACTIVE"})
                    continue
                price_at = max(utc(q["available_at"]) for q in quotes)
                decision = max(available, book.closes[p], price_at)
                if decision > utc(cutoff):
                    continue
                try:
                    s = _security(securities,r["stable_security_id"],session,decision.isoformat(),c["cik"])
                except ContractError as exc:
                    checkpoint_notes.append({"event_id":ident,"checkpoint":cp,"reason":str(exc)})
                    continue
                raw = {
                    "event_id":ident, "economic_event_id":c["candidate_id"],
                    "stable_security_id":r["stable_security_id"], "security_id":s["ticker"],
                    "issuer_id":s["issuer_id"], "instrument":s["instrument"], "exchange":s["exchange"],
                    "listing_country":"US", "eligibility_verified_asof":True,
                    "event_version":1, "available_at":available.isoformat(),
                    "first_available_at":available.isoformat(),
                    "event_type":r.get("event_type", c["descriptive_event_tags"][0]),
                    "role":r.get("role"), "source_tier":"OFFICIAL", "official_evidence":True,
                    "business_relation_new":r.get("business_relation_new",False),
                    "economic_value_confirmed":r.get("economic_value_confirmed",False),
                    "economic_amount_usd":r.get("economic_amount_usd"),
                    "economic_amount_kind":r.get("economic_amount_kind","UNKNOWN"),
                    "material_agreement_confirmed":"1.01" in c["sec_items"] and c["form_type"].startswith("8-K"),
                    "theme_peer_ids":[], "theme_id":"UNASSIGNED",
                    "sample_origin":"FORWARD_SHADOW" if origin=="FORWARD_OBSERVED" else "HISTORICAL_BACKFILL",
                    "independent_source_groups":["SEC_EDGAR"], "source_family":"SEC_EDGAR",
                    "source_url":c["primary_document_url"], "event_tags":c["descriptive_event_tags"],
                    "dilution_risk":r.get("dilution_risk"), "cashflow_risk":r.get("cashflow_risk"),
                    "balance_sheet_risk":r.get("balance_sheet_risk"),
                }
                event = normalize_event(raw)
                event.update(checkpoint=cp, checkpoint_session=session, decision_at=decision.isoformat(),
                             event_session=book.dates[event_pos], source_document_ids=refs,
                             first_available_at=available.isoformat(),
                             price_features_available_at=price_at.isoformat(), feature_available_at={},
                             contract_version="reviewed-sec-export-snapshot-p0.3",
                             sec_form_type=c["form_type"], accession_number=c["accession_number"],
                             amends_event_id=r.get("amends_event_id"),
                             review_supplied_not_independently_certified=True,
                             review_record_sha256=sha256(canonical_bytes(r)),
                             theme_breadth_checkpoint=None, theme_breadth_peer_count=0,
                             confirmed_combo=False)
                # Exact-session pre-event RS uses only prior available prices, not future labels.
                for h in (20,60):
                    left, right = event_pos-1-h, event_pos-1
                    qs = [book.row(sid, book.dates[i]) if i>=0 else None
                          for sid in (r["stable_security_id"],benchmark) for i in (left,right)]
                    ok = all(q is not None and q["status"]=="ACTIVE" and utc(q["available_at"])<=decision for q in qs)
                    event[f"pre_rs{h}"] = ((qs[1]["total_return_index"]/qs[0]["total_return_index"] -
                                             qs[3]["total_return_index"]/qs[2]["total_return_index"]) if ok else None)
                    if ok: event["feature_available_at"][f"pre_rs{h}"] = max((q["available_at"] for q in qs), key=utc)
                event["snapshot_sha256"] = sha256(canonical_bytes(event))
                snapshots.append(event); made += 1
            if made == 0:
                rejected.append({"event_id":ident,"reason":"NO_MATURE_ELIGIBLE_CHECKPOINT"})
    return snapshots, rejected, checkpoint_notes


def verify_fact_citations(reviews: list[dict], documents: list[dict], files: dict[str,bytes]) -> None:
    """Bind asserted amount/new-relation citations to exact raw byte spans.

    This verifies the excerpt exists, not that a human interpreted it correctly.
    A quotation/locator never authorizes trading, historical training or rights.
    """
    docs = {d["document_id"]:d for d in documents}
    for review in reviews:
        if review.get("state") != "REVIEWED_FOR_ASSEMBLY_NOT_APPROVAL":
            continue
        for flag, fact in (("economic_value_confirmed", "economic_amount_usd"),
                           ("business_relation_new", "business_relation_new")):
            strict_bool(review.get(flag,False),flag)
            if not review.get(flag,False): continue
            e = review.get("fact_evidence",{}).get(fact)
            require(type(e) is dict and e.get("document_id") in docs, "FACT_EVIDENCE_MISSING:"+fact)
            doc = docs[e["document_id"]]
            raw = files.get(doc["raw_path"])
            require(type(raw) is bytes and sha256(raw) == e.get("raw_sha256") == doc["raw_sha256"], "FACT_CITATION_HASH")
            lo,hi = e.get("byte_start"),e.get("byte_end")
            require(type(lo) is int and type(hi) is int and 0<=lo<hi<=len(raw), "FACT_CITATION_RANGE")
            quote=e.get("quote_utf8")
            require(type(quote) is str and bool(quote) and quote.encode("utf-8")==raw[lo:hi], "FACT_CITATION_QUOTE")


def assemble_export(export_root: Path, output_root: Path, *, now: str) -> dict:
    """Hash frozen producer files -> P0-2 bundle -> existing byte/graph verifier.

    Does not add anything to REVIEWED_REGISTRY. Real training and computation
    remain blocked until the existing independent review gate is satisfied.
    """
    m, files, roles = load_export(export_root,now=now)
    ix = index_export(m,files)
    sessions = validate_sessions(rows(files[roles["sessions"]]))
    prices = parse_price_csv(files[roles["prices_csv"]])
    documents = rows(files[roles["documents"]])
    securities = rows(files[roles["securities"]])
    policy = validate_policy(json_load(files[roles["policy"]]))
    reviews = rows(files[roles["reviews"]])
    verify_fact_citations(reviews,documents,files)
    snaps, rejected, cp_notes = build_snapshots(ix["candidates"], reviews,
                          securities, documents, prices, sessions, origin=m["origin"],
                          cutoff=m["data_cutoff"], generated_at=m["generated_at"],
                          benchmark=policy["benchmark_security_id"])
    output_root = Path(output_root)
    require(not output_root.exists() and not reparse_point(output_root), "OUTPUT_EXISTS")
    require(not any(reparse_point(p) for p in output_root.parents), "OUTPUT_REPARSE_POINT")
    require(not output_root.resolve().is_relative_to(Path(export_root).resolve()), "OUTPUT_INSIDE_INPUT")
    require(not any((p/".git").exists() for p in (output_root,*output_root.parents)), "OUTPUT_INSIDE_WORKTREE")
    entries = []
    assembled = dict(files)
    for e in m["files"]:
        entry = {k:e[k] for k in ("path","sha256","bytes","role","source_id")}
        if entry["role"] in {"sec_submissions","reviews","prices_csv"}: entry["role"]="raw_object"
        entries.append(entry)
    source_id = m.get("adapter_source_id")
    require(type(source_id) is str and bool(source_id), "ADAPTER_SOURCE_ID")
    def add(role, value, is_rows=False):
        path = "_adapter/"+role+(".jsonl" if is_rows else ".json")
        data = b"".join(canonical_bytes(r) for r in value) if is_rows else canonical_bytes(value)
        assembled[path]=data
        entries.append({"path":path,"bytes":len(data),"sha256":sha256(data),"role":role,"source_id":source_id})
    add("snapshots",snaps,True); add("prices",prices,True)
    cal_evidence = [e["path"] for e in entries if e["role"]=="calendar_evidence"]
    require(len(cal_evidence)==1, "CALENDAR_EVIDENCE_COUNT")
    included = len({(s["economic_event_id"],s["stable_security_id"],s["event_version"]) for s in snaps})
    coverage = {"schema":"news-event-coverage-p0.2","scope":"DECLARED_INPUT_ONLY_NOT_ENTIRE_US_MARKET",
                "calendar_start":sessions[0]["session"],"calendar_end":sessions[-1]["session"],
                "calendar_evidence_path":cal_evidence[0],"historical_universe_complete":False,
                "selection_rule":m["selection_rule"],"candidate_count":included+len(rejected),
                "included_event_security_revisions":included,"rejected_events":rejected,
                "price_row_count":len(prices),"document_count":len(documents),
                "raw_filing_candidate_count":len(ix["candidates"]),
                "unresolved_history_urls":ix["unresolved_history_urls"],
                "history_pages_complete":ix["declared_history_pages_complete"],
                "checkpoint_rejections":cp_notes}
    add("coverage",coverage)
    manifest = {"schema":"news-event-input-bundle-p0.2","consumer":CONSUMER,
                "origin":m["origin"],"source_commit":m["source_commit"],
                "data_cutoff":m["data_cutoff"],"generated_at":m["generated_at"],
                "generation":1,"parent_receipt_sha256":None,"files":entries,
                "producer_export_sha256":m["_export_sha256"],"adapter_contract":"source-bridge-p0.3",
                "standalone_input_not_drive_generation":True}
    # Exclusive local outputs. Failure leaves an explicitly non-accepted directory.
    output_root.mkdir(parents=True,exist_ok=False)
    bundle_root = output_root/"bundle"; bundle_root.mkdir()
    for path,data in assembled.items():
        dst=bundle_root/path; dst.parent.mkdir(parents=True,exist_ok=True)
        with dst.open("xb") as f: f.write(data)
    with (bundle_root/"manifest.json").open("xb") as f: f.write(canonical_bytes(manifest))
    b = verify_bundle(bundle_root,now=now)
    report = {"schema":"news-source-bridge-report-p0.3", "status":"ASSEMBLED_BYTE_GRAPH_CHECKED_NOT_APPROVED",
              "producer_export_sha256":m["_export_sha256"],"bundle_manifest_sha256":b.manifest_sha256,
              "raw_sec_candidates":len(ix["candidates"]),"snapshots":len(snaps),
              "included_event_security_revisions":included,"rejected_events":len(rejected),
              "checkpoint_notes":len(cp_notes),"history_pages_complete":ix["declared_history_pages_complete"],
              "missing_history_pages":len(ix["unresolved_history_urls"]),
              "origin":m["origin"],"real_input_approval_granted":False,
              "historical_training_run":False,"selector_weight":0.0,"drive_published":False,
              "outcomes_computed":False,"source_hashes":{p:sha256(v) for p,v in files.items()}}
    with (output_root/"ASSEMBLY_REPORT.json").open("xb") as f: f.write(canonical_bytes(report))
    return report
