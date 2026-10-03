"""Bounded source-only access to registered FMP/EODHD credentials.

Reuse the accepted H1 parser and provider fetch functions. Never run the
transactional collector, Drive publication, selection overlay, or paper ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import collect_earnings_estimates_finnhub as collector
from tools.earnings_consensus_h1 import build_snapshot, identity_complete, optional_float

MAX_HTTP = 24
MAX_BYTES = 4_000_000
KEY_NAMES = {"fmp": "FMP_API_KEY", "fmp2": "FMP_API_KEY2", "eodhd": "EODHD_API_KEY"}


class ProbeBlocked(ValueError):
    pass


class BoundedSession:
    """One shared reservation counter for every source request in this probe."""
    def __init__(self, max_http, api_units, transport=None):
        if type(max_http) is not int or not 1 <= max_http <= MAX_HTTP:
            raise ProbeBlocked("INVALID_HTTP_BUDGET")
        if type(api_units) is not int or not 0 <= api_units <= 100_000:
            raise ProbeBlocked("INVALID_API_UNIT_BUDGET")
        self.max_http, self.api_units = max_http, api_units
        self.http_attempts, self.api_units_reserved = 0, 0
        self.transport = transport or requests.Session()
        self.transport.trust_env = False

    def get(self, url, *, params, timeout):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.query or parsed.fragment:
            raise ProbeBlocked("UNAPPROVED_ENDPOINT")
        if parsed.netloc == "financialmodelingprep.com" and parsed.path == "/stable/analyst-estimates":
            cost = 1
        elif parsed.netloc == "eodhd.com" and parsed.path == "/api/user":
            cost = 0
        elif parsed.netloc == "eodhd.com" and re.fullmatch(r"/api/v1\.1/fundamentals/[A-Z]{1,8}\.US", parsed.path):
            cost = 10
        else:
            raise ProbeBlocked("UNAPPROVED_ENDPOINT")
        if self.http_attempts >= self.max_http or self.api_units_reserved + cost > self.api_units:
            raise ProbeBlocked("REQUEST_BUDGET_EXHAUSTED")
        # Reserve before sending, including failed/time-out requests. No retries.
        self.http_attempts += 1
        self.api_units_reserved += cost
        response = self.transport.get(url, params=params, timeout=timeout,
                                      allow_redirects=False, stream=True)
        try:
            if 300 <= response.status_code < 400:
                raise ProbeBlocked("REDIRECT_REFUSED")
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65_536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ProbeBlocked("RESPONSE_TOO_LARGE")
                chunks.append(chunk)
            data = json.loads(b"".join(chunks))
            if parsed.netloc == "financialmodelingprep.com":
                rows = data.get("data") if isinstance(data, dict) else data
                if not isinstance(rows, list):
                    raise ProbeBlocked("INVALID_PROVIDER_SCHEMA")
                if any(not isinstance(row, dict) or row.get("symbol") != params.get("symbol") for row in rows):
                    raise ProbeBlocked("PROVIDER_SECURITY_MISMATCH")
        finally:
            response.close()
        # Adapt to the accepted collector's response interface without a second GET.
        class CapturedResponse:
            def raise_for_status(self): return None
            def json(self): return data
        return CapturedResponse()


def ticker_list(value):
    tickers = [item.strip().upper() for item in value.split(",")]
    if not tickers or any(not re.fullmatch(r"[A-Z]{1,8}", item) for item in tickers):
        raise ProbeBlocked("EXPLICIT_US_SYMBOL_MAPPING_REQUIRED")
    if len(tickers) != len(set(tickers)) or len(tickers) > MAX_HTTP:
        raise ProbeBlocked("INVALID_OR_DUPLICATE_SAMPLE")
    return tickers


def eodhd_payloads(payload, ticker):
    """Only v1.1 analyst Trend sections; never History or Annual actual earnings."""
    if not isinstance(payload, dict):
        raise ProbeBlocked("INVALID_PROVIDER_SCHEMA")
    general = payload.get("General")
    if not isinstance(general, dict) or general.get("Code") != ticker:
        raise ProbeBlocked("PROVIDER_SECURITY_MISMATCH")
    earnings = payload.get("Earnings")
    trend = earnings.get("Trend") if isinstance(earnings, dict) else None
    if not isinstance(trend, dict):
        return {"data": []}, {"data": []}
    if trend and not set(trend).issubset({"Annual", "Quarterly"}):
        raise ProbeBlocked("UNSUPPORTED_EARNINGS_TREND_VERSION")
    result = {"eps": [], "rev": []}
    for section, period_type in (("Annual", "ANNUAL"), ("Quarterly", "QUARTERLY")):
        rows = trend.get(section, {})
        if not isinstance(rows, dict):
            raise ProbeBlocked("INVALID_PROVIDER_SCHEMA")
        for period, item in sorted(rows.items()):
            if not isinstance(item, dict):
                raise ProbeBlocked("INVALID_PROVIDER_SCHEMA")
            try:
                if date.fromisoformat(period).isoformat() != period or item.get("date", period) != period:
                    raise ValueError
            except (ValueError, TypeError):
                raise ProbeBlocked("CONFLICTING_FISCAL_PERIOD") from None
            for metric, name in (("eps", "earnings"), ("rev", "revenue")):
                result[metric].append({"period": period, "period_type": period_type,
                    "avg": optional_float(item.get(name + "EstimateAvg")),
                    "high": optional_float(item.get(name + "EstimateHigh")),
                    "low": optional_float(item.get(name + "EstimateLow")),
                    "numberAnalysts": optional_float(item.get(name + "EstimateNumberOfAnalysts")),
                    # Missing economic identity is preserved; do not infer basis/ADR units.
                    "issuer_id": item.get("issuer_id"), "security_id": "EODHD:" + ticker + ".US",
                    "accounting_basis": item.get("accounting_basis"),
                    "currency": item.get("currency"), "share_or_ADR_unit": item.get("share_or_ADR_unit")})
    return {"data": result["eps"]}, {"data": result["rev"]}


def fresh_quota_stamp(value, now):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        age = (now - stamp).total_seconds() if stamp.tzinfo else -1
        return 0 <= age <= 900
    except (ValueError, AttributeError, OverflowError):
        return False


def eodhd_daily_lower_bound(payload, started, ended):
    if not isinstance(payload, dict) or started.date() != ended.date():
        raise ProbeBlocked("UNVERIFIED_EODHD_QUOTA")
    used, limit = payload.get("apiRequests"), payload.get("dailyRateLimit")
    if type(used) is not int or type(limit) is not int or not 0 <= used <= 100_000_000 or not 0 < limit <= 100_000_000:
        raise ProbeBlocked("UNVERIFIED_EODHD_QUOTA")
    activity = payload.get("apiRequestsDate")
    if activity is None and used == 0:
        # Never-used accounts: subtract the entire reported counter, without reset.
        return limit
    try:
        if not isinstance(activity, str) or date.fromisoformat(activity).isoformat() != activity or date.fromisoformat(activity) > ended.date():
            raise ValueError
    except (TypeError, ValueError):
        raise ProbeBlocked("UNVERIFIED_EODHD_QUOTA") from None
    # A previous active-day counter is a conservative subtraction, not today's counter.
    # extraLimit is intentionally excluded from this probe's data-request budget.
    return max(0, limit - used)


def run_probe(provider, tickers, *, max_http, api_units, quota_verified_at="",
              env=None, transport=None, now=lambda: datetime.now(timezone.utc)):
    env = os.environ if env is None else env
    if provider not in KEY_NAMES:
        raise ProbeBlocked("UNAPPROVED_PROVIDER")
    tickers = ticker_list(",".join(tickers))
    session = BoundedSession(max_http, api_units, transport)
    started = now()
    report = {"scope": "SOURCE_ONLY_SAMPLE", "provider": provider,
              "credential_alias": KEY_NAMES[provider], "started_at_utc": started.isoformat(),
              "max_http_requests": max_http, "api_unit_budget": api_units,
              "research_only": True, "h2_eligible": False,
              "production_activation_allowed": False, "historical_pit_certified": False,
              "operational_writes": 0, "raw_provider_payloads_persisted": False, "results": []}
    snapshots = []
    key = env.get(KEY_NAMES[provider], "").strip()
    if not key:
        report["status"] = "MISSING_SELECTED_SECRET"
    elif not re.fullmatch(r"[A-Za-z0-9._-]{16,256}", key):
        report["status"] = "INVALID_SELECTED_SECRET_FORMAT"
    elif provider != "eodhd" and not fresh_quota_stamp(quota_verified_at, started):
        report["status"] = "FRESH_SHARED_QUOTA_EVIDENCE_REQUIRED"
    elif api_units == 0:
        report["status"] = "POSITIVE_VERIFIED_API_UNIT_BUDGET_REQUIRED"
    else:
        try:
            if provider == "eodhd":
                usage = collector.fetch_url_json(session, "https://eodhd.com/api/user",
                    {"api_token": key, "fmt": "json"}, sleep_seconds=0)
                lower_bound = eodhd_daily_lower_bound(usage, started, now())
                if api_units > lower_bound:
                    raise ProbeBlocked("API_UNIT_BUDGET_EXCEEDS_DAILY_LOWER_BOUND")
                report["eodhd_daily_quota_lower_bound"] = lower_bound
            for ticker in tickers:
                errors = []
                observed = now()
                if observed.date() != started.date():
                    raise ProbeBlocked("UTC_COLLECTION_DAY_CHANGED")
                if provider == "eodhd":
                    raw = collector.fetch_url_json(session,
                        "https://eodhd.com/api/v1.1/fundamentals/" + ticker + ".US",
                        {"api_token": key, "fmt": "json", "filter": "General,Earnings"}, sleep_seconds=0)
                    eps, rev = eodhd_payloads(raw, ticker)
                else:
                    eps, rev = collector.fetch_fmp_payloads(session, ticker, key,
                                                            sleep_seconds=0, errors=errors)
                completed = now()
                if completed.date() != started.date():
                    raise ProbeBlocked("UTC_COLLECTION_DAY_CHANGED")
                if errors:
                    codes = [int(error.get("status_code") or 0) for error in errors]
                    report["results"].append({"ticker": ticker, "status": "PROVIDER_REQUEST_FAILED", "http_statuses": codes})
                    if any(code in {401, 403} for code in codes):
                        break
                    continue  # A security-specific FMP 402 does not disable successful securities.
                snapshot = build_snapshot(ticker, eps_payload=eps, revenue_payload=rev,
                    recommendation_payload=None,
                    observed_at=observed.isoformat(), collected_at=completed.isoformat(),
                    fetch_source="fmp" if provider.startswith("fmp") else "eodhd")
                encoded = json.dumps(snapshot, sort_keys=True, allow_nan=False)
                if key in encoded:
                    raise ProbeBlocked("UNSAFE_PROVIDER_PAYLOAD")
                records = json.loads(snapshot["consensus_observations_json"])
                report["results"].append({"ticker": ticker, "status": "SOURCE_RESPONSE_PARSED",
                    "eps_rows_with_value": sum(r["identity"]["metric"] == "EPS" and r["value"] is not None for r in records),
                    "revenue_rows_with_value": sum(r["identity"]["metric"] == "REVENUE" and r["value"] is not None for r in records),
                    "records_with_verified_identity": sum(identity_complete(r["identity"]) for r in records),
                    "identity_status": snapshot["identity_status"]})
                snapshots.append(snapshot)
            has_values = any(result.get("eps_rows_with_value", 0) or result.get("revenue_rows_with_value", 0)
                             for result in report["results"])
            report["status"] = "SAMPLE_PROBED" if has_values else "NO_ESTIMATE_SAMPLE_CONFIRMED"
        except requests.HTTPError as exc:
            report["status"] = "PROVIDER_HTTP_REJECTED"
            report["http_status"] = int(exc.response.status_code) if exc.response is not None else 0
        except ProbeBlocked as exc:
            report["status"] = str(exc)  # All callers generate fixed local enums.
        except Exception:
            report["status"] = "NETWORK_OR_INVALID_PROVIDER_RESPONSE"
    report.update(http_requests_attempted=session.http_attempts,
                  api_units_reserved_upper_bound=session.api_units_reserved,
                  source_snapshots_in_memory=len(snapshots), completed_at_utc=now().isoformat())
    report["securities_with_observed_eps"] = sum(result.get("eps_rows_with_value", 0) > 0 for result in report["results"])
    report["securities_with_observed_revenue"] = sum(result.get("revenue_rows_with_value", 0) > 0 for result in report["results"])
    report["current_universe_usable_coverage_certified"] = False
    return report, snapshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=list(KEY_NAMES), required=True)
    parser.add_argument("--tickers", default="AAPL")
    parser.add_argument("--max-http-requests", type=int, default=3)
    parser.add_argument("--verified-api-units", type=int, default=0)
    parser.add_argument("--quota-verified-at-utc", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    permitted = ROOT / "outputs" / "earnings_estimate_source_probe"
    if permitted.resolve() != permitted or not output.is_relative_to(permitted) or output.suffix != ".json":
        print(json.dumps({"status": "ISOLATED_OUTPUT_PATH_REQUIRED", "http_requests_attempted": 0}))
        return 2
    try:
        tickers = ticker_list(args.tickers)
        report, _ = run_probe(args.provider, tickers, max_http=args.max_http_requests,
                             api_units=args.verified_api_units, quota_verified_at=args.quota_verified_at_utc)
    except ProbeBlocked as exc:
        report = {"scope": "SOURCE_ONLY_SAMPLE", "status": str(exc), "http_requests_attempted": 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report.get("status") == "SAMPLE_PROBED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
