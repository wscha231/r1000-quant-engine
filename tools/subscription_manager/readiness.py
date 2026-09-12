#!/usr/bin/env python3
"""Offline subscription-manager data readiness, not selection or publication.

Reuse hash-pinned PR415 current observations and its exact broad price cohort.
Keep historical SEC raw bodies/PIT evidence distinct from this derived snapshot.
Only new local output directories are written. No network, broker, LLM calls,
customer data, authenticated Drive writes, portfolio weights or live returns.
"""
from __future__ import annotations

import argparse
import csv
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import html
import io
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
from typing import Any, Iterator

VERSION = "subscription-manager-readiness-v1"
MAX_INPUT_BYTES = 64 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}\Z")
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,19}\Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def date_value(value: Any) -> str:
    """Parse actual YYYYMMDD dates, never Unix nanoseconds. Floats are rejected."""
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str):
        raise ValueError("date_type")
    if re.fullmatch(r"\d{8}", value):
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date_format")
    return date.fromisoformat(value).isoformat()


def timestamp(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("timestamp_type")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp_timezone_required")
    return result.astimezone(timezone.utc).isoformat()


def number(value: Any) -> str:
    if isinstance(value, bool) or value is None or not isinstance(value, (int, float)):
        raise ValueError("numeric_value_required")
    try:
        out = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("numeric_value_required") from None
    if not out.is_finite():
        raise ValueError("nonfinite_value")
    return str(out.normalize())


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def read_pinned(path: Path, expected: str) -> tuple[dict, bytes]:
    if not HASH.fullmatch(expected):
        raise ValueError("invalid_expected_hash")
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("input_file_or_size")
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError("input_hash_mismatch")
    def reject_constant(_: str) -> None:
        raise ValueError("nonfinite_json_constant")
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("input_object_required")
    return value, raw


def identity_rows(rows: Any) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise ValueError("rows_required")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not SYMBOL.fullmatch(str(row.get("ticker", ""))):
            raise ValueError("invalid_security_identity")
        symbol = row["ticker"]
        if symbol in result:
            raise ValueError("duplicate_security_identity")
        result[symbol] = row
    return result


def validate_inputs(cohort: dict, financials: dict, cohort_hash: str,
                    decision_at: str) -> tuple[dict, dict]:
    decision = timestamp(decision_at)
    if financials.get("schema_version") != "whole-cohort-financial-coverage-v1":
        raise ValueError("unsupported_financial_schema")
    if financials.get("data_kind") != "REAL_CURRENT_OBSERVATIONS" or cohort.get("data_kind") != "REAL":
        raise ValueError("real_data_required")
    if financials.get("cohort_sha256") != cohort_hash:
        raise ValueError("cohort_lineage_mismatch")
    prices = identity_rows(cohort.get("rows"))
    facts = identity_rows(financials.get("rows"))
    if len(prices) < 1000:
        raise ValueError("broad_universe_floor")
    if set(prices) != set(facts):
        raise ValueError("universe_identity_mismatch")
    for container, key in ((cohort, "candidate_count"), (financials, "requested_securities")):
        if type(container.get(key)) is not int or container[key] != len(prices):
            raise ValueError("universe_count_mismatch")
    cutoff = date_value(financials["filing_cutoff_date"])
    price_date = date_value(cohort["as_of"])
    if date_value(financials["cohort_price_as_of"]) != price_date:
        raise ValueError("price_lineage_date_mismatch")
    observed = timestamp(financials["analysis_at"])
    if observed > decision or max(price_date, cutoff) > decision[:10] or cutoff > observed[:10]:
        raise ValueError("future_input")
    if financials.get("orders_allowed") is not False or financials.get("portfolio_weights") is not None:
        raise ValueError("upstream_authority_mismatch")
    for row in facts.values():
        if row.get("status") not in {"COLLECTED", "UNAVAILABLE", "MISSING_IDENTITY"}:
            raise ValueError("unknown_collection_status")
        if row.get("cik") is not None and not re.fullmatch(r"\d{10}", str(row["cik"])):
            raise ValueError("invalid_cik")
        if row["status"] == "COLLECTED":
            if not row.get("cik") or not HASH.fullmatch(str(row.get("raw_sha256", ""))):
                raise ValueError("missing_issuer_provenance")
            data = row.get("financials")
            if not isinstance(data, dict) or type(data.get("current_quarter_usable")) is not bool:
                raise ValueError("financial_packet_required")
            for name in ("revenue_yoy", "revenue_growth_acceleration_pp", "fcf_ttm"):
                if data.get(name) is not None:
                    number(data[name])
            if data.get("quarter_end") is not None and date_value(data["quarter_end"]) > cutoff:
                raise ValueError("future_fiscal_period")
    return prices, facts


def embedded_facts(node: Any) -> Iterator[dict]:
    """Yield retained source excerpts, not the producer's computed TTM values."""
    if isinstance(node, dict):
        if {"accn", "namespace", "tag", "currency", "end", "filed", "val"} <= node.keys():
            yield node
        else:
            for value in node.values():
                yield from embedded_facts(value)
    elif isinstance(node, list):
        for value in node:
            yield from embedded_facts(value)


def normalized_fact(cik: str, raw: dict, observed_at: str, cutoff: str) -> dict:
    start = date_value(raw["start"]) if raw.get("start") is not None else None
    end, filed = date_value(raw["end"]), date_value(raw["filed"])
    if filed > cutoff or end > cutoff or filed < end or (start is not None and start > end):
        raise ValueError("fact_period_or_availability")
    if raw["namespace"] not in {"us-gaap", "ifrs-full"} or not re.fullmatch(r"[A-Z]{3}", raw["currency"]):
        raise ValueError("fact_reporting_basis")
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(raw["accn"])):
        raise ValueError("fact_accession")
    if not isinstance(raw["tag"], str) or not raw["tag"]:
        raise ValueError("fact_tag")
    return {"cik": cik, "namespace": raw["namespace"], "tag": raw["tag"],
            "unit": raw["currency"], "period_start": start, "period_end": end,
            "filed_date": filed, "accession": raw["accn"], "value": number(raw["val"]),
            "accepted_at": None, "observed_at": timestamp(observed_at),
            "source_kind": "RETAINED_DERIVED_EXCERPT_NOT_RAW_SEC_BODY",
            "historical_pit_verified": False}


def build(cohort: dict, financials: dict, cohort_hash: str, financial_hash: str,
          decision_at: str, history_start_year: int = 2016, source_commit: str | None = None) -> dict:
    prices, data = validate_inputs(cohort, financials, cohort_hash, decision_at)
    if source_commit is not None and not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit")
    if not HASH.fullmatch(financial_hash):
        raise ValueError("financial_hash")
    if type(history_start_year) is not int or not 1993 <= history_start_year <= int(decision_at[:4]):
        raise ValueError("history_start_year")
    observations, versions, groups, rows = {}, {}, {}, []
    for ticker in sorted(prices):
        row = data[ticker]
        f = row.get("financials", {})
        reasons = []
        if row["status"] != "COLLECTED":
            reasons.append(row.get("reason") or row["status"])
        elif not f["current_quarter_usable"]:
            reasons.append(f.get("reason") or "CURRENT_QUARTER_UNRESOLVED")
        if f.get("fcf_ttm") is None:
            reasons.append("FCF_DEFINITION_OR_VALUE_UNRESOLVED")
        # Sparse retained excerpts cannot certify issuer-year-quarter-field history.
        reasons += ["HISTORY_INVENTORY_REQUIRED", "ACCEPTED_AT_REQUIRED"]
        group = "CIK:" + row["cik"] if row.get("cik") else "SECURITY:" + ticker
        item = groups.setdefault(group, {"issuer_key": group, "tickers": [],
            "first_action": "RESTORE_VERIFY_EXISTING_RAW_ARCHIVE" if row.get("cik") else "RESOLVE_IDENTITY",
            "history_start_year": history_start_year, "history_end": financials["filing_cutoff_date"],
            "warmup": "EARLIER_WHERE_FEATURE_LOOKBACK_REQUIRES",
            "history_status": "UNKNOWN_NOT_ZERO", "missing_intervals": None,
            "requests_sent": 0, "blockers": []})
        item["tickers"].append(ticker)
        item["blockers"] = sorted(set(item["blockers"] + reasons))
        rs_coverage = {}
        for horizon in (20, 60, 120, 240):
            h = prices[ticker].get("horizons", {}).get(str(horizon), {})
            valid = h.get("status") == "available"
            if valid:
                if date_value(h["end"]) != cohort["as_of"]:
                    raise ValueError("rs_end_mismatch")
                for key in ("stock_return", "benchmark_return"):
                    if float(number(h[key])) <= -1:
                        raise ValueError("invalid_log_return")
            rs_coverage[str(horizon)] = valid
        rows.append({"ticker": ticker, "cik": row.get("cik"), "sector": prices[ticker].get("sector"),
                     "collection_status": row["status"], "current_quarter_usable_at_source": f.get("current_quarter_usable", False),
                     "quarter_end": f.get("quarter_end"), "fcf_ttm_observed": f.get("fcf_ttm") is not None,
                     "rs_coverage": rs_coverage, "history_coverage": None, "review_state": "NOT_ASSESSED",
                     "blockers": reasons})
        for raw in embedded_facts(f):
            fact = normalized_fact(row["cik"], raw, financials["analysis_at"], financials["filing_cutoff_date"])
            key = tuple(fact[k] for k in ("cik", "namespace", "tag", "unit", "period_start", "period_end", "accession"))
            if key in versions and versions[key] != (fact["value"], fact["filed_date"]):
                raise ValueError("conflicting_fact_version")
            versions[key] = (fact["value"], fact["filed_date"])
            fact_id = digest(canonical(fact))
            obs = observations.setdefault(fact_id, {**fact, "fact_id": fact_id, "source_hashes": []})
            obs["source_hashes"] = sorted(set(obs["source_hashes"] + [row["raw_sha256"]]))
    coverage = {
        "requested_securities": len(rows),
        "mapped_unique_issuers": sum(k.startswith("CIK:") for k in groups),
        "collected_securities": sum(r["collection_status"] == "COLLECTED" for r in rows),
        "current_quarter_usable_at_source": sum(r["current_quarter_usable_at_source"] for r in rows),
        "fcf_ttm_observed": sum(r["fcf_ttm_observed"] for r in rows),
        "revenue_yoy_observed_including_stale": sum(r.get("financials", {}).get("revenue_yoy") is not None for r in data.values()),
        "growth_acceleration_observed_including_stale": sum(r.get("financials", {}).get("revenue_growth_acceleration_pp") is not None for r in data.values()),
        "retained_unique_fact_versions": len(observations),
        "exact_accepted_at_verified": 0,
        "historical_cell_coverage": None,
        "rs_coverage": {str(h): sum(r["rs_coverage"][str(h)] for r in rows) for h in (20, 60, 120, 240)},
    }
    manifest = {
        "schema_version": VERSION, "product": "AI_MANAGER_MODEL_PORTFOLIO_SUBSCRIPTION",
        "source_commit": source_commit, "implementation_sha256": digest(Path(__file__).read_bytes()),
        "config_sha256": digest(canonical({"version": VERSION, "history_start_year": history_start_year, "minimum_securities": 1000})),
        "upstream_price_basis": cohort.get("price_basis"),
        "upstream_ranking_use": cohort.get("ranking_use"),
        "status": "INTERNAL_READINESS_ONLY", "decision_at": timestamp(decision_at),
        "source_observed_at": timestamp(financials["analysis_at"]),
        "price_as_of": cohort["as_of"], "financial_filed_cutoff": financials["filing_cutoff_date"],
        "source_hashes": {"cohort": cohort_hash, "financials": financial_hash},
        "coverage": coverage, "security_rows": rows, "issuer_queue": list(groups.values()),
        "retained_facts": [observations[k] for k in sorted(observations)],
        "historical_universe_verified": False, "sec_raw_bodies_restored": False,
        "subscription_release_allowed": False, "orders_allowed": False,
        "customer_asset_management": False, "portfolio_weights": None, "performance": None,
        "release_blockers": ["CURRENT_PRICE_AND_ACTIONS", "COMMON_UNIVERSE_ESTIMATES", "REVIEWED_BUSINESS_AND_VALUATION",
            "MODEL_RISK_REVIEW", "PUBLICATION_FIRST_MODEL_LEDGER", "DURABLE_SOURCE_RESTORE",
            "DATA_DISTRIBUTION_RIGHTS", "SERVICE_LEGAL_REVIEW", "AUTHENTICATED_MEMBER_DELIVERY"],
        "historical_research_blockers": ["FULL_HISTORY_INVENTORY", "EXACT_ACCEPTED_AT", "LEGACY_PIT_FIXES", "HISTORICAL_MEMBERSHIP"],
        "provenance_note": "Source hash claims bind the supplied derived snapshots; they do not authenticate the unavailable SEC raw bodies.",
    }
    return manifest


def _safe_root(root: Path) -> None:
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("symlink_output")


def export(result: dict, root: Path, source_bytes: dict[str, bytes]) -> dict:
    """Snapshot-only SQLite copy and content manifests; never overwrite accepted state."""
    _safe_root(root)
    if root.exists():
        raise ValueError("new_output_directory_required")
    if set(source_bytes) != {"cohort", "financials"}:
        raise ValueError("unexpected_source_bytes")
    for name in ("cohort", "financials"):
        if digest(source_bytes[name]) != result["source_hashes"][name]:
            raise ValueError("export_source_hash_mismatch")
    root.mkdir(parents=True)
    private = root / "private"
    private.mkdir(mode=0o700)
    for name, raw in source_bytes.items():
        path = private / (digest(raw) + ".json")
        path.write_bytes(raw)
        path.chmod(0o600)
    index = private / "observations.sqlite"
    with closing(sqlite3.connect(index)) as db, db:
        db.execute("CREATE TABLE securities(ticker TEXT PRIMARY KEY, cik TEXT, packet TEXT NOT NULL)")
        db.execute("CREATE TABLE fact_versions(fact_id TEXT PRIMARY KEY, cik TEXT NOT NULL, accession TEXT NOT NULL, tag TEXT NOT NULL, unit TEXT NOT NULL, period_start TEXT, period_end TEXT NOT NULL, filed_date TEXT NOT NULL, accepted_at TEXT, observed_at TEXT NOT NULL, payload TEXT NOT NULL)")
        db.executemany("INSERT INTO securities VALUES(?,?,?)", [(r["ticker"], r["cik"], canonical(r).decode()) for r in result["security_rows"]])
        db.executemany("INSERT INTO fact_versions VALUES(?,?,?,?,?,?,?,?,?,?,?)", [(
            r["fact_id"], r["cik"], r["accession"], r["tag"], r["unit"], r["period_start"], r["period_end"],
            r["filed_date"], r["accepted_at"], r["observed_at"], canonical(r).decode()) for r in result["retained_facts"]])
        db.execute("CREATE INDEX issuer_period ON fact_versions(cik,period_end)")
        db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT)")
        db.executemany("INSERT INTO metadata VALUES(?,?)", [("schema_version", VERSION), ("historical_pit_verified", "false"), ("sec_raw_bodies_restored", "false")])
    index.chmod(0o600)
    summary = {k: v for k, v in result.items() if k not in {"security_rows", "retained_facts", "issuer_queue"}}
    (root / "readiness.json").write_bytes(canonical(summary))
    (private / "issuer_reuse_queue.json").write_bytes(canonical(result["issuer_queue"]))
    (private / "security_coverage.json").write_bytes(canonical(result["security_rows"]))
    stream = io.StringIO(newline="")
    fields = ["ticker", "cik", "collection_status", "quarter_end", "current_quarter_usable_at_source", "fcf_ttm_observed", "history_coverage", "review_state"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows({k: row[k] for k in fields} for row in result["security_rows"])
    (private / "security_coverage.csv").write_text(stream.getvalue(), encoding="utf-8")
    counts = result["coverage"]
    cells = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in counts.items())
    blockers = "".join(f"<li>{html.escape(v)}</li>" for v in result["release_blockers"])
    page = ("<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>AI Manager · 내부 준비현황</title><style>body{max-width:1000px;margin:40px auto;padding:24px;font:16px/1.65 system-ui;background:#f5f7fa;color:#16253c}"
            "table{background:white;width:100%;border-collapse:collapse}th,td{padding:10px;text-align:left;border-bottom:1px solid #dee4ed}h1{font-size:30px}aside{padding:18px;background:#fff1d5}</style>"
            "<h1>AI Manager · 구독서비스 준비현황</h1><aside>내부 개발 미리보기 · 구독자에게 발행되지 않음 · 추천·비중·성과 없음</aside>"
            f"<p>재사용 가격 기준: {html.escape(result['price_as_of'])} / 재무 공시일 기준: {html.escape(result['financial_filed_cutoff'])}</p>"
            "<p>아래 수치는 자료 확보 현황입니다. 투자 심사 완료나 과거 재무 전체 확보율이 아닙니다.</p>"
            f"<table>{cells}</table><h2>서비스 발행 전에 남은 연결</h2><ul>{blockers}</ul>"
            "<p>기존 데이터 원본·품질 검토·가치평가·모델 장부를 연결합니다. 자동주문과 고객 자산관리는 포함하지 않습니다.</p></html>")
    (root / "internal_preview.html").write_text(page, encoding="utf-8")
    files = {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}
    receipt = {"schema_version": VERSION + "-export", "files": files,
               "contains_private_licensed_inputs": True, "publish_to_public_repository": False,
               "subscription_release_allowed": False, "sec_raw_bodies_restored": False}
    (root / "export_manifest.json").write_bytes(canonical(receipt))
    return receipt


def verify_export(root: Path, expected_manifest_sha256: str) -> dict:
    _safe_root(root)
    manifest, _ = read_pinned(root / "export_manifest.json", expected_manifest_sha256)
    if manifest.get("schema_version") != VERSION + "-export" or not isinstance(manifest.get("files"), dict) or not manifest["files"]:
        raise ValueError("export_manifest_schema")
    listed = set()
    for name, expected in manifest["files"].items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError("unsafe_manifest_path")
        dest = root.joinpath(*path.parts)
        if any(p.is_symlink() for p in (dest, *dest.parents)) or not dest.is_file():
            raise ValueError("missing_or_unsafe_export_member")
        if not HASH.fullmatch(str(expected)) or digest(dest.read_bytes()) != expected:
            raise ValueError("export_member_hash_mismatch")
        listed.add(name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.relative_to(root).as_posix() != "export_manifest.json"}
    if actual != listed:
        raise ValueError("unlisted_export_members")
    return {"verified_files": len(listed), "verified_manifest_sha256": expected_manifest_sha256,
            "historical_pit_verified": False, "subscription_release_allowed": False}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cohort", type=Path, required=True)
    p.add_argument("--cohort-sha256", required=True)
    p.add_argument("--financials", type=Path, required=True)
    p.add_argument("--financials-sha256", required=True)
    p.add_argument("--decision-at", required=True)
    p.add_argument("--history-start-year", type=int, default=2016)
    p.add_argument("--source-commit", required=True, help="Exact implementation commit, local or published; not upstream data commit")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    cohort, c_raw = read_pinned(args.cohort, args.cohort_sha256)
    financials, f_raw = read_pinned(args.financials, args.financials_sha256)
    result = build(cohort, financials, args.cohort_sha256, args.financials_sha256, args.decision_at, args.history_start_year, args.source_commit)
    export(result, args.output, {"cohort": c_raw, "financials": f_raw})
    print(json.dumps({"status": result["status"], "coverage": result["coverage"], "subscription_release_allowed": False}, indent=2))
    return 0  # Successful offline audit is explicitly NOT a successful subscription release.


if __name__ == "__main__":
    raise SystemExit(main())
