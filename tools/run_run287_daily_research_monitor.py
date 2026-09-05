#!/usr/bin/env python3
"""Join immutable GitHub evidence into a read-only daily research handoff.

No provider calls, model runs, portfolio reads/writes, arbitrary artifact
extraction, workflow dispatches, or fallback to an earlier successful run.
Downloaded JSON/CSV is data only. This report is not accepted paper state.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "docs/run287_daily_research_monitor_contract.json"
SCHEMA = "run287-daily-research-monitor-v1"
READY_UPSTREAM = {
    "READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
    "READY_EXISTING_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
}


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result.astimezone(timezone.utc)


def number(value: Any) -> float | None:
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def date_state(value: Any, expected: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return "MISSING_OR_INVALID_DATE"
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return "MISSING_OR_INVALID_DATE"
    return "CURRENT" if value == expected else "STALE" if value < expected else "FUTURE_DATE"


def collection_current(value: Any, session: str, now: datetime) -> bool:
    return (date_state(value, session) in {"CURRENT", "FUTURE_DATE"}
            and value <= now.date().isoformat())


def latest_run(runs: list[dict], workflow: str, repository: str) -> dict | None:
    eligible = [r for r in runs if r.get("head_branch") == "master"
                and r.get("path") == f".github/workflows/{workflow}"
                and (r.get("head_repository") or {}).get("full_name") == repository
                and r.get("event") in {"schedule", "workflow_dispatch"}]
    # Include failed and running runs. Never hide a failure behind old success.
    return max(eligible, key=lambda r: (r["created_at"], r["id"]), default=None)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not token:
            raise ValueError("repository_or_token_missing")
        self.root = f"https://api.github.com/repos/{repository}"
        self.headers = {"Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "run287-readonly-research-monitor"}

    def json(self, path: str) -> Any:
        req = urllib.request.Request(self.root + path, headers=self.headers)
        with urllib.request.build_opener(NoRedirect).open(req, timeout=45) as response:
            return json.load(response)

    def archive(self, artifact_id: int, destination: Path, limit: int) -> str:
        req = urllib.request.Request(f"{self.root}/actions/artifacts/{artifact_id}/zip",
                                     headers=self.headers)
        try:
            response = urllib.request.build_opener(NoRedirect).open(req, timeout=45)
        except urllib.error.HTTPError as exc:
            if exc.code != 302:
                raise
            location = exc.headers.get("Location", "")
            parsed = urllib.parse.urlsplit(location)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("unsafe_artifact_redirect") from None
            # The temporary storage URL never receives the GitHub token.
            response = urllib.request.urlopen(location, timeout=90)
        digest = hashlib.sha256()
        size = 0
        with response, destination.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValueError("artifact_size_limit")
                digest.update(chunk)
                out.write(chunk)
        return "sha256:" + digest.hexdigest()


def read_members(path: Path, members: dict[str, str], limit: int) -> tuple[dict, dict]:
    data, evidence = {}, {}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for label, name in members.items():
            if names.count(name) > 1:
                raise ValueError("duplicate_artifact_member")
            if name not in names:
                continue
            info = archive.getinfo(name)
            if info.file_size > limit or info.is_dir():
                raise ValueError("artifact_member_size_or_type")
            # Read by exact contract path, never extract or execute artifact files.
            raw = archive.read(info)
            evidence[label] = {"member": name, "sha256": hashlib.sha256(raw).hexdigest(),
                               "bytes": len(raw)}
            value = raw.decode("utf-8-sig")
            parsed = json.loads(value) if name.endswith(".json") else list(csv.DictReader(io.StringIO(value)))
            if name.endswith(".json") and not isinstance(parsed, dict):
                raise ValueError("manifest_must_be_object")
            data[label] = parsed
    return data, evidence


def collect_source(client: GitHub, key: str, spec: dict, contract: dict) -> dict:
    result: dict[str, Any] = {"source": key, "status": "MISSING_RUN", "data": {}}
    try:
        runs = client.json(f"/actions/workflows/{spec['workflow']}/runs?branch=master&per_page=30")
        run = latest_run(runs.get("workflow_runs", []), spec["workflow"], contract["repository"])
        if run is None:
            return result
        result["run"] = {k: run.get(k) for k in
                         ("id", "run_attempt", "head_sha", "created_at", "status", "conclusion", "html_url")}
        if run.get("status") != "completed":
            result["status"] = "UPSTREAM_IN_PROGRESS"
            return result
        result["status"] = "UPSTREAM_FAILED" if run.get("conclusion") != "success" else "MISSING_ARTIFACT"
        artifacts = client.json(f"/actions/runs/{run['id']}/artifacts?per_page=100").get("artifacts", [])
        matches = [a for a in artifacts if a.get("name") == spec["artifact_prefix"] + str(run["id"])]
        if len(matches) != 1:
            return result
        artifact = matches[0]
        result["artifact"] = {k: artifact.get(k) for k in ("id", "name", "digest", "expired", "size_in_bytes")}
        identity = artifact.get("workflow_run") or {}
        if identity.get("id") != run["id"] or identity.get("head_sha") != run["head_sha"]:
            raise ValueError("artifact_run_identity_mismatch")
        if artifact.get("expired") or artifact.get("size_in_bytes", 0) > contract["max_artifact_bytes"]:
            raise ValueError("artifact_expired_or_oversize")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", artifact.get("digest") or ""):
            raise ValueError("artifact_digest_missing")
        with tempfile.TemporaryDirectory(prefix="run287-monitor-") as folder:
            path = Path(folder) / "evidence.zip"
            actual = client.archive(artifact["id"], path, contract["max_artifact_bytes"])
            if actual != artifact["digest"]:
                raise ValueError("artifact_digest_mismatch")
            members = {k: v.format(run_id=run["id"], run_attempt=run.get("run_attempt", 1))
                       for k, v in spec["members"].items()}
            result["data"], result["files"] = read_members(path, members, contract["max_member_bytes"])
        result["artifact_hash_verified"] = True
        if run.get("conclusion") == "success":
            result["status"] = "VERIFIED_ARTIFACT"
    except Exception as exc:
        result["status"] = "BLOCKED_SOURCE"
        # Never echo exception text: urllib errors may contain signed URLs.
        result["error_type"] = type(exc).__name__
        if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]+", str(exc)):
            result["reason"] = str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            result["http_status"] = exc.code
        result["data"] = {}
    return result


def completed_session(now: datetime) -> str:
    import pandas_market_calendars as mcal
    schedule = mcal.get_calendar("NYSE").schedule(start_date=(now - timedelta(days=14)).date(),
                                                end_date=now.date())
    completed = schedule[schedule["market_close"] <= now - timedelta(minutes=90)]
    if completed.empty:
        raise ValueError("no_settled_us_session")
    return str(completed.index[-1].date())


def evaluate(sources: dict, session: str, now: datetime, contract: dict) -> dict:
    alerts, observations = [], {}
    for key in contract["sources"]:
        source = sources.get(key, {})
        if source.get("status") != "VERIFIED_ARTIFACT":
            alerts.append(f"{key}:{source.get('status', 'MISSING_SOURCE')}")
        created = (source.get("run") or {}).get("created_at")
        if created:
            try:
                if timestamp(created) > now:
                    alerts.append(f"{key}:FUTURE_RUN")
            except ValueError:
                alerts.append(f"{key}:INVALID_RUN_TIME")
    data = lambda key: sources.get(key, {}).get("data", {})
    recovery = data("operating").get("recovery", {})
    observations["operating_recovery"] = {k: recovery.get(k) for k in ("status", "next_action")}
    if str(recovery.get("status", "")).startswith("BLOCKED"):
        alerts.append("operating:" + str(recovery["status"]))
    tactical = data("tactical").get("summary", {})
    for key in ("data_as_of", "latest_scored_rebalance_date"):
        state = date_state(tactical.get(key), session)
        observations[f"tactical_{key}"] = {"date": tactical.get(key), "state": state}
        if state != "CURRENT":
            alerts.append(f"tactical:{key}:{state}")
    upstream = data("operating").get("upstream", {})
    upstream_date = upstream.get("valuation_price_cutoff_date")
    observations["current_decision_inputs"] = {"status": upstream.get("status"), "date": upstream_date}
    if upstream.get("status") not in READY_UPSTREAM or date_state(upstream_date, session) != "CURRENT":
        alerts.append("operating:CURRENT_DECISION_INPUTS_UNAVAILABLE")
    estimates = data("estimates").get("summary", {})
    coverage = number(estimates.get("request_estimate_coverage_ratio"))
    fetch_date = estimates.get("fetch_date")
    observations["estimates"] = {"request_coverage": coverage,
                                "collector_status": estimates.get("collector_status"),
                                "fetch_date": fetch_date,
                                "archive_coverage": number(estimates.get("coverage_ratio"))}
    # Collection date is not an earnings period or exact market-close date.
    if not collection_current(fetch_date, session, now):
        alerts.append("estimates:MISSING_STALE_OR_FUTURE_FETCH_DATE")
    if coverage is None or not 0 <= coverage <= 1 or coverage < 1:
        alerts.append("estimates:PARTIAL_OR_UNKNOWN_FORWARD_ESTIMATE_COVERAGE")
    if str(estimates.get("collector_status", "")).startswith("blocked"):
        alerts.append("estimates:COLLECTOR_BLOCKED")
    price_archive = data("estimates").get("prices", {})
    observations["independent_price_archive"] = {k: price_archive.get(k) for k in
                                                ("start", "end", "common_coverage_end", "actual_cached_ticker_count")}
    observations["independent_price_archive"]["meaning"] = "Coverage metadata only; archived price bytes are not included in this source artifact."
    if date_state(price_archive.get("common_coverage_end"), session) != "CURRENT":
        alerts.append("estimates:INDEPENDENT_PRICE_COVERAGE_NOT_CURRENT")
    ownership = data("ownership").get("summary", {}).get("13f_freshness", {})
    observations["ownership"] = {k: ownership.get(k) for k in
                                 ("as_of_date", "required_due_period_end", "latest_accepted_at", "selected_manager_coverage")}
    observations["ownership"]["meaning"] = "Disclosed quarterly holdings, not current institutional buying."
    observations["ownership"]["existing_weights"] = data("ownership").get("summary", {}).get("weights")
    observations["ownership"]["weights_validated_by_monitor"] = False
    ownership_usable = (sources.get("ownership", {}).get("status") == "VERIFIED_ARTIFACT"
                        and ownership.get("freshness_ready") is True
                        and collection_current(ownership.get("as_of_date"), session, now))
    if not ownership_usable:
        alerts.append("ownership:MISSING_STALE_OR_BLOCKED_DISCLOSURE_SNAPSHOT")
    indexed = {}
    for row in data("ownership").get("ranked", []):
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker in indexed:
            alerts.append("ownership:DUPLICATE_TICKER")
            ownership_usable = False
        indexed[ticker] = row
    price_rows = data("operating").get("prices", [])
    prices, duplicates = {}, set()
    for row in price_rows:
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker in prices:
            duplicates.add(ticker)
        prices[ticker] = row
    market = data("operating").get("market", {})
    observations["market_snapshot"] = {k: market.get(k) for k in
                                        ("asof_date", "latest_price_date_min", "latest_price_date_max",
                                         "ticker_count", "exact_asof_close_count")}
    price_source_verified = sources.get("operating", {}).get("artifact_hash_verified") is True
    if duplicates:
        alerts.append("operating:DUPLICATE_PRICE_TICKERS")
    watchlist = []
    for market, tickers in contract["watchlist"].items():
        for ticker in tickers:
            row = indexed.get(ticker, {}) if market == "US" and ownership_usable else {}
            available = row.get("latest_available_from")
            try:
                usable_row = bool(available and timestamp(available) <= now)
            except ValueError:
                usable_row = False
            price = prices.get(ticker, {}) if market == "US" and price_source_verified else {}
            price_state = date_state(price.get("latest_price_date"), session)
            close = number(price.get("previous_close"))
            if ticker in duplicates:
                price_state = "DUPLICATE_TICKER"
            if close is None or close <= 0:
                price_state = "MISSING_OR_INVALID_PRICE"
            watchlist.append({"market": market, "ticker": ticker,
                              "price_as_of": price.get("latest_price_date"),
                              "price_status": price_state,
                              "close": close if price_state == "CURRENT" else None,
                              "currency": price.get("currency") if price_state == "CURRENT" else None,
                              "ownership_score": number(row.get("smart_money_score")) if usable_row else None,
                              "ownership_available_from": available,
                              "current_engine_score": None,
                              "current_engine_status": "NO_VALIDATED_RANKING_HANDOFF",
                              "research_status": "PRIMARY_SOURCE_REVIEW_REQUIRED",
                              "data_gap": "KR_ADAPTER_REQUIRED" if market == "KR" else
                              "PRICE_FINANCIAL_MOAT_AND_SCORE_HANDOFF_REQUIRED"})
    return {"schema_version": SCHEMA, "generated_at_utc": now.isoformat(),
            "expected_us_session": session, "repository": contract["repository"],
            "status": "ATTENTION_REQUIRED" if alerts else "OBSERVATIONS_COLLECTED",
            "current_investment_ranking_ready": False,
            "alerts": sorted(set(alerts)), "observations": observations,
            "sources": {k: {a: b for a, b in v.items() if a != "data"} for k, v in sources.items()},
            "watchlist": watchlist, "research_questions": contract["research_questions"],
            "score_policy": contract["score_policy"], "safety": contract["safety"]}


def render(report: dict) -> str:
    rows = ["# Run287 Daily Research Handoff", "",
            f"Expected US close: {report['expected_us_session']} · {report['status']}", "",
            "Current investment ranking: **withheld**. This is source monitoring and research input, not an accepted portfolio publication.",
            "", "| Source | Collection | Run |", "|---|---|---|"]
    for key, source in report["sources"].items():
        run = source.get("run", {})
        link = f"https://github.com/{report['repository']}/actions/runs/{run.get('id', '')}"
        rows.append(f"| {key} | {source.get('status')} | [{run.get('id', 'missing')}]({link}) |")
    rows.extend(["", "## Data dates and coverage", "", "```json",
                 json.dumps(report["observations"], ensure_ascii=False, indent=2), "```",
                 "", "## Items to resolve", ""])
    rows.extend(f"- {item}" for item in report["alerts"])
    rows.extend(["", "## Research queue", "",
                 "| Market | Ticker | Close / date | Disclosed ownership score | Data gap |", "|---|---|---|---|---|"])
    for row in report["watchlist"]:
        score = row["ownership_score"]
        price = f"{row['close']} / {row['price_as_of']}" if row['close'] is not None else row['price_status']
        rows.append(f"| {row['market']} | {row['ticker']} | {price} | {score if score is not None else 'unavailable'} | {row['data_gap']} |")
    rows.extend(["", report["score_policy"], "",
                 "KR exchange calendar, long price history, financial estimates and source-cited moat research remain separate inputs. No US-relative score is imputed for KR tickers.", ""])
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    if contract.get("schema_version") != SCHEMA or contract.get("branch") != "master":
        raise ValueError("monitor_contract_invalid")
    # New report directory only; never overwrite an existing evidence set.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    now = datetime.now(timezone.utc)
    client = GitHub(contract["repository"], os.environ.get("GH_TOKEN", ""))
    sources = {k: collect_source(client, k, spec, contract) for k, spec in contract["sources"].items()}
    report = evaluate(sources, completed_session(now), now, contract)
    report["code_sha"] = os.environ.get("GITHUB_SHA", "local-unpublished")
    report["contract_sha256"] = hashlib.sha256(args.contract.read_bytes()).hexdigest()
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "report.md").write_text(render(report), encoding="utf-8")
    with (args.output_dir / "research_queue.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report["watchlist"][0]))
        writer.writeheader()
        writer.writerows(report["watchlist"])
    print(json.dumps({"status": report["status"], "expected_us_session": report["expected_us_session"],
                      "alerts": report["alerts"], "current_investment_ranking_ready": False}))
    return 0  # Report generation success is intentionally separate from data readiness.


if __name__ == "__main__":
    sys.exit(main())
