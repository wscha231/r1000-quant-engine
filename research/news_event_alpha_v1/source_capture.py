"""Manual bounded SEC source capture with content-addressed local receipts.

Not a scheduler, market model, Drive writer, or data-approval service. Reuses
frozen successful receipts on resume; HTTP restrictions stop instead of being
bypassed. SEC User-Agent is read from an environment variable, never printed.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener
import uuid

from .admission import (HEX40, checked_file, json_load, read_bounded, reparse_point, sha256)
from .execution import require
from .runtime import canonical_bytes, ContractError, utc
from .source_bridge import cik10, day, sec_url, parse_submissions, merge_indexes

MAX_BODY = 16 * 1024 * 1024
MAX_STORED = 128 * 1024 * 1024


class CaptureBlocked(ContractError):
    def __init__(self, code: str, retry_after: str | None = None):
        self.code = code
        self.retry_after = retry_after if retry_after and re.fullmatch(r"\d{1,8}",retry_after) else None
        super().__init__(code)


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_sec(url: str, user_agent: str) -> bytes:
    url = sec_url(url)
    require(type(user_agent) is str and 8 <= len(user_agent) <= 240 and "@" in user_agent
            and not any(ord(c) < 32 or ord(c)>126 for c in user_agent), "SEC_USER_AGENT_REQUIRED")
    opener = build_opener(_NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    req = Request(url,headers={"User-Agent":user_agent,"Accept-Encoding":"identity"})
    try:
        with opener.open(req,timeout=30) as response:
            if response.status != 200:
                raise CaptureBlocked("HTTP_"+str(response.status))
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            if encoding not in {"", "identity"}:
                raise CaptureBlocked("UNSUPPORTED_HTTP_ENCODING")
            length = response.headers.get("Content-Length")
            if length and length.isdigit() and int(length)>MAX_BODY:
                raise CaptureBlocked("RESPONSE_TOO_LARGE")
            content = response.read(MAX_BODY+1)
            if len(content)>MAX_BODY:
                raise CaptureBlocked("RESPONSE_TOO_LARGE")
            if not content:
                raise CaptureBlocked("EMPTY_RESPONSE")
            lower=content[:16000].lower()
            if b"your request originates from an undeclared automated tool" in lower or b"request rate threshold exceeded" in lower:
                raise CaptureBlocked("SEC_ACCESS_RESTRICTION")
            return content
    except HTTPError as exc:
        raise CaptureBlocked("HTTP_"+str(exc.code),exc.headers.get("Retry-After")) from None
    except (URLError, TimeoutError, OSError):
        raise CaptureBlocked("NETWORK_UNAVAILABLE_OR_TIMEOUT") from None


def _outside_git(path: Path):
    require(not any(reparse_point(p) for p in (path,*path.parents)), "CAPTURE_REPARSE_POINT")
    require(not any((p/".git").exists() for p in (path,*path.parents)), "CAPTURE_INSIDE_WORKTREE")


def exclusive_bytes(path: Path, raw: bytes):
    """Idempotent immutable object. Never follows symlinks or replaces user data."""
    require(not reparse_point(path) and not any(reparse_point(p) for p in path.parents), "CAPTURE_REPARSE_POINT")
    if path.exists():
        require(path.is_file() and read_bounded(path)==raw, "IMMUTABLE_CAPTURE_CONFLICT")
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    # On interruption a partial new file remains invalid and must not be accepted.
    with path.open("xb") as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    require(read_bounded(path)==raw, "CAPTURE_READBACK")


@contextmanager
def writer_lock(path: Path):
    _outside_git(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    token=uuid.uuid4().hex.encode("ascii")
    try:
        with path.open("xb") as f: f.write(token)
    except FileExistsError:
        raise CaptureBlocked("WRITER_LOCK_EXISTS_INSPECT_BEFORE_RESUMING") from None
    try:
        yield
    finally:
        if path.is_file() and not reparse_point(path) and path.read_bytes()==token:
            path.unlink()  # only our ephemeral lock, never research data


class CaptureStore:
    def __init__(self, root: Path, *, user_agent: str, request_budget: int,
                 clock=None, fetcher=None, monotonic=None, sleeper=None):
        self.root=Path(root); _outside_git(self.root)
        require(type(request_budget) is int and 1<=request_budget<=150, "REQUEST_BUDGET")
        self.request_budget=request_budget
        self.user_agent=user_agent
        self.clock=clock or (lambda:datetime.now(timezone.utc).isoformat())
        self.fetcher=fetcher or fetch_sec
        self.monotonic=monotonic or time.monotonic; self.sleeper=sleeper or time.sleep
        self.calls=0; self.reused=0; self.last=None
        self.root.mkdir(parents=True,exist_ok=True)

    def get(self, url: str) -> tuple[bytes,dict]:
        url=sec_url(url)
        rid=sha256(url.encode("ascii"))
        receipt_path=self.root/"receipts"/(rid+".json")
        require(not reparse_point(receipt_path), "CAPTURE_REPARSE_POINT")
        if receipt_path.exists():
            r=json_load(read_bounded(receipt_path))
            require(r.get("schema")=="sec-capture-receipt-p0.3" and r.get("source_url")==url,
                    "CAPTURE_RECEIPT_IDENTITY")
            require(re.fullmatch(r"[0-9a-f]{64}",str(r.get("raw_sha256",""))) is not None,"CAPTURE_RECEIPT_HASH")
            data=read_bounded(checked_file(self.root,"objects/"+r["raw_sha256"]))
            require(len(data)==r.get("bytes") and sha256(data)==r["raw_sha256"],"CAPTURE_RECEIPT_BYTES")
            require(utc(r["ingested_at"])<=utc(self.clock()), "CAPTURE_FUTURE_RECEIPT")
            self.reused+=1
            return data,r
        if self.calls>=self.request_budget:
            raise CaptureBlocked("REQUEST_BUDGET_EXHAUSTED")
        if self.last is not None:
            wait=0.5-(self.monotonic()-self.last)
            if wait>0: self.sleeper(wait)
        self.last=self.monotonic(); self.calls+=1
        data=self.fetcher(url,self.user_agent)
        require(type(data) is bytes and 0<len(data)<=MAX_BODY,"CAPTURE_BODY_BUDGET")
        if url.startswith("https://data.sec.gov/"):
            require(type(json_load(data)) is dict, "CAPTURE_EXPECTED_JSON")
        if (self.root/"objects").exists():
            require(all(not reparse_point(p) and p.is_file() for p in (self.root/"objects").iterdir()), "CAPTURE_OBJECT_TYPE")
            total=sum(p.stat().st_size for p in (self.root/"objects").iterdir())
        else: total=0
        require(total+len(data)<=MAX_STORED,"CAPTURE_STORAGE_BUDGET")
        r={"schema":"sec-capture-receipt-p0.3","source_url":url,"raw_sha256":sha256(data),
           "bytes":len(data),"ingested_at":utc(self.clock()).isoformat(),
           "source_public_at":None,"source_id":"SEC_EDGAR",
           "readback_verified":True,"rights_granted_by_this_receipt":False,
           "historical_pit_certified":False}
        exclusive_bytes(self.root/"objects"/r["raw_sha256"],data)
        exclusive_bytes(receipt_path,canonical_bytes(r))
        return data,r


def capture(plan: dict, output: Path, *, user_agent: str, lock_path: Path,
            resume: bool = False, clock=None, fetcher=None, monotonic=None, sleeper=None) -> dict:
    require(plan.get("schema")=="news-sec-capture-plan-p0.3", "CAPTURE_PLAN_SCHEMA")
    ids=plan.get("ciks")
    require(type(ids) is list and 0<len(ids)<=10, "CAPTURE_CIK_BUDGET")
    ids=[cik10(c) for c in ids]; require(len(set(ids))==len(ids),"CAPTURE_DUPLICATE_CIK")
    start,end=day(plan["window_start"]),day(plan["window_end"])
    require(0<=(end-start).days<=732,"CAPTURE_WINDOW_BUDGET")
    require(HEX40.fullmatch(str(plan.get("source_commit",""))) is not None,"CAPTURE_SOURCE_COMMIT")
    limit=plan.get("max_filings"); request_limit=plan.get("max_requests")
    require(type(limit) is int and 1<=limit<=100,"CAPTURE_FILING_BUDGET")
    require(type(request_limit) is int and 1<=request_limit<=150,"REQUEST_BUDGET")
    require(plan.get("selection_rule")=="EARLIEST_BY_FILED_DATE_THEN_CIK_ACCESSION_NO_RETURNS", "CAPTURE_SELECTION_RULE")
    cutoff=utc(plan["data_cutoff"])
    clock=clock or (lambda:datetime.now(timezone.utc).isoformat())
    require(cutoff<=utc(clock()),"CAPTURE_CUTOFF")
    require(end<=cutoff.date(),"CAPTURE_END_AFTER_CUTOFF")
    output=Path(output); _outside_git(output)
    require(not output.exists() or resume,"CAPTURE_EXISTS_USE_EXPLICIT_RESUME")
    require(not resume or (output/"CAPTURE_PLAN.json").is_file(), "CAPTURE_RESUME_PLAN_MISSING")
    # All callers must share this lock with other collectors; not a distributed/IP lock.
    with writer_lock(Path(lock_path)):
        output.mkdir(parents=True,exist_ok=True)
        exclusive_bytes(output/"CAPTURE_PLAN.json",canonical_bytes(plan))
        store=CaptureStore(output,user_agent=user_agent,request_budget=request_limit,
                           clock=clock,fetcher=fetcher,monotonic=monotonic,sleeper=sleeper)
        queue=[{"cik":c,"url":f"https://data.sec.gov/submissions/CIK{c}.json"} for c in ids]
        indexes, captured, blockers, attempted = [], {}, [], set()
        while queue:
            task=queue.pop(0)
            if task["url"] in attempted: continue
            attempted.add(task["url"])
            try:
                raw,r=store.get(task["url"])
                ix=parse_submissions(raw,cik=task["cik"],source_url=task["url"],ingested_at=r["ingested_at"],
                                     window_start=plan["window_start"],window_end=plan["window_end"])
                indexes.append(ix); captured[task["url"]]=(raw,r,task["cik"],"sec_submissions")
                queue.extend({"url":h["source_url"],"cik":h["cik"]} for h in ix["history_requests"])
            except ContractError as exc:
                blockers.append({"stage":"SUBMISSIONS","source_url":task["url"],"reason":str(exc),
                                 "retry_after_seconds":getattr(exc,"retry_after",None)})
                break   # no bypass/retry storms, preserve unfinished queue below
        merged=merge_indexes(indexes,set(captured))
        selected=merged["candidates"][:limit]
        documents=[]
        if not blockers:
            for c in selected:
                if not c["primary_document_url"]:
                    documents.append({"candidate_id":c["candidate_id"],"status":"PRIMARY_PATH_MISSING"}); continue
                try:
                    raw,r=store.get(c["primary_document_url"])
                    captured[r["source_url"]]=(raw,r,c["cik"],"raw_object")
                    documents.append({"candidate_id":c["candidate_id"],"status":"CAPTURED_NOT_REVIEWED",**r})
                except ContractError as exc:
                    blockers.append({"stage":"PRIMARY_DOCUMENT","candidate_id":c["candidate_id"],"reason":str(exc),
                                     "retry_after_seconds":getattr(exc,"retry_after",None)})
                    break
        attempt=uuid.uuid4().hex
        export=output/"exports"/attempt; export.mkdir(parents=True,exist_ok=False)
        files=[]
        for url,(raw,r,cik,role) in sorted(captured.items()):
            path="raw/"+sha256(url.encode("ascii"))+".bin"
            exclusive_bytes(export/path,raw)
            files.append({"path":path,"sha256":sha256(raw),"bytes":len(raw),"source_id":"SEC_EDGAR",
                          "role":role,"cik":cik,"source_url":url,"ingested_at":r["ingested_at"]})
        generated=clock()
        manifest={"schema":"news-source-export-p0.3","origin":"HISTORICAL_RECONSTRUCTION",
                  "source_commit":plan["source_commit"],"data_cutoff":plan["data_cutoff"],
                  "generated_at":generated,"window_start":plan["window_start"],"window_end":plan["window_end"],
                  "selection_rule":plan["selection_rule"],"files":files,"stage":"RAW_INDEX_EXPORT_REVIEW_NOT_READY"}
        exclusive_bytes(export/"export_manifest.json",canonical_bytes(manifest))
        report={"schema":"sec-capture-report-p0.3","status":"PARTIAL_BLOCKED" if blockers else "CAPTURED_REVIEW_REQUIRED",
                "attempt_id":attempt,"new_requests":store.calls,"reused_verified_receipts":store.reused,
                "indexed_filing_candidates":len(merged["candidates"]),"selected_document_budget":len(selected),
                "captured_documents":len([d for d in documents if d["status"]=="CAPTURED_NOT_REVIEWED"]),
                "deferred_document_candidates":max(0,len(merged["candidates"])-limit),
                "history_pages_complete":not queue and not blockers and merged["declared_history_pages_complete"],
                "unfinished_submissions_queue":queue,"missing_history_urls":merged["unresolved_history_urls"],
                "blockers":blockers,"export_manifest_sha256":sha256(canonical_bytes(manifest)),
                "export_dir":str(export),"generated_at":generated,
                "has_price_or_security_approval":False,"whole_market_coverage_certified":False,
                "historical_training_run":False,"selector_weight":0.0,"drive_written":False,
                "global_sec_ip_limit_enforced":False,
                "capture_source_sha256":sha256(Path(__file__).read_bytes())}
        audit=output/"attempts"/attempt; audit.mkdir(parents=True,exist_ok=False)
        exclusive_bytes(audit/"CAPTURE_REPORT.json",canonical_bytes(report))
        exclusive_bytes(audit/"review_queue.jsonl",b"".join(canonical_bytes(c) for c in merged["candidates"]))
        exclusive_bytes(audit/"documents.jsonl",b"".join(canonical_bytes(d) for d in documents))
        exclusive_bytes(audit/"excluded_records.jsonl",b"".join(canonical_bytes(d) for d in merged["excluded_records"]))
        return report
