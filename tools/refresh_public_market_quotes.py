#!/usr/bin/env python3
"""Public, exact-session price observations. Never revalue or mutate a portfolio."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from tools.build_public_portfolio_dashboard import validate_public_payload
from tools.run_daily_market_session_gate import evaluate_market_session

PUBLIC_DASHBOARD = "https://wscha231.github.io/r1000-quant-engine/data/dashboard.json"
NY = ZoneInfo("America/New_York")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # In particular, never forward Alpaca authentication headers.
        return None


def fetch_json(url, headers=None):
    request = Request(url, headers={"User-Agent": "Run287-public-market-quotes/1.0", **(headers or {})})
    with build_opener(NoRedirect()).open(request, timeout=25) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError("response_too_large")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def atomic_json(path, payload):
    validate_public_payload(payload)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_dashboard(data):
    validate_public_payload(data)
    if (data.get("schema_version") != "run287-public-dashboard-v1"
            or data.get("status", {}).get("review_only") is not True
            or data.get("status", {}).get("live_trading_enabled") is not False):
        raise ValueError("unsafe_public_dashboard")
    datetime.strptime(data["as_of_close"], "%Y-%m-%d")
    if set(data.get("portfolios", {})) != {"main", "concentrated"}:
        raise ValueError("missing_portfolio")


def preserve_deployed(path, deployed):
    """A static-assets deployment must never reset a newer published account."""
    tracked = json.loads(path.read_text(encoding="utf-8"))
    for data in (tracked, deployed):
        validate_dashboard(data)
    # The default-branch source can contain a reviewed same-date correction.
    # Only a strictly newer deployed session may replace those source bytes.
    if deployed["as_of_close"] > tracked["as_of_close"]:
        atomic_json(path, deployed)


def public_tickers(dashboard):
    validate_dashboard(dashboard)
    tickers = sorted({h["ticker"] for p in dashboard["portfolios"].values() for h in p["holdings"]})
    if not tickers or len(tickers) > 100 or any(not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", t) for t in tickers):
        raise ValueError("invalid_public_tickers")
    return tickers


def exact_close(rows, session):
    matches = []
    for stamp, close in rows:
        observed = datetime.fromtimestamp(stamp, timezone.utc).astimezone(NY).date().isoformat()
        if observed == session:
            if isinstance(close, bool) or close is None:
                raise ValueError("invalid_close")
            value = float(close)
            if not math.isfinite(value) or value <= 0:
                raise ValueError("invalid_close")
            matches.append(value)
    if len(matches) != 1:
        raise ValueError("missing_or_duplicate_session_close")
    return matches[0]


def yahoo_close(ticker, session):
    # Same provider convention as build_replay_price_cache.yfinance_symbol;
    # keep the dotted public identity in collect(), not in the provider URL.
    provider_symbol = ticker.replace(".", "-")
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + provider_symbol + "?" + urlencode({"range": "5d", "interval": "1d", "includePrePost": "false"})
    payload, digest = fetch_json(url)
    result = payload["chart"]["result"]
    if len(result) != 1:
        raise ValueError("ambiguous_symbol")
    item = result[0]
    if item["meta"]["symbol"] != provider_symbol or item["meta"]["currency"] != "USD":
        raise ValueError("symbol_or_currency_mismatch")
    if item["meta"].get("dataGranularity") != "1d":
        raise ValueError("not_a_daily_bar")
    stamps = item["timestamp"]
    closes = item["indicators"]["quote"][0]["close"]
    if len(stamps) != len(closes):
        raise ValueError("bar_length_mismatch")
    return exact_close(zip(stamps, closes), session), digest


def alpaca_closes(tickers, session, key, secret):
    start = datetime.strptime(session, "%Y-%m-%d").replace(tzinfo=NY)
    end = min(start + timedelta(days=1), datetime.now(timezone.utc) - timedelta(minutes=16))
    query = urlencode({"symbols": ",".join(tickers), "timeframe": "1Day", "start": start.isoformat(),
                       "end": end.isoformat(), "feed": "sip", "adjustment": "raw", "limit": 10000})
    payload, digest = fetch_json("https://data.alpaca.markets/v2/stocks/bars?" + query,
                               {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
    if payload.get("next_page_token"):
        raise ValueError("unexpected_pagination")
    prices = {}
    for ticker in tickers:
        try:
            bars = payload["bars"].get(ticker, [])
            rows = [(datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp(), b["c"]) for b in bars]
            prices[ticker] = (exact_close(rows, session), digest)
        except (KeyError, TypeError, ValueError):
            pass
    return prices


def collect(dashboard, *, now=None, yahoo=yahoo_close, alpaca=alpaca_closes):
    tickers = public_tickers(dashboard)
    # Includes long weekends; never override the 90-minute settlement buffer.
    gate = evaluate_market_session(now_utc=now, max_close_age_hours=120)
    session = gate["session_date"]
    result = {"schema_version": "run287-public-market-quotes-v1", "checked_at_utc": gate["checked_at_utc"],
              "expected_session_date": session, "portfolio_as_of_close": dashboard["as_of_close"],
              "as_of_close": None, "status": "UNAVAILABLE", "quotes": [], "missing_tickers": tickers,
              "scope": "published_holdings_only", "portfolio_revalued": False,
              "review_only": True, "live_trading_enabled": False}
    if not gate["ready"]:
        result["status"] = "WAITING_FOR_COMPLETED_CLOSE"
        return result
    if dashboard["as_of_close"] > session:
        raise ValueError("future_portfolio_date")
    key, secret = os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_API_SECRET", "")
    observed = {}
    source = "Yahoo Finance daily unadjusted close"
    if key and secret:
        source = "Alpaca SIP daily unadjusted close"
        try:
            observed = alpaca(tickers, session, key, secret)
        except Exception:
            # Do not log credential-bearing provider errors, retry auth, or
            # silently substitute IEX bars for consolidated SIP observations.
            result["status"] = "PROVIDER_UNAVAILABLE"
            return result
    else:
        for ticker in tickers:
            try:
                observed[ticker] = yahoo(ticker, session)
            except HTTPError as exc:
                if exc.code == 429:
                    break
            except Exception:
                pass
    result["quotes"] = [{"ticker": t, "close": observed[t][0], "session_date": session,
                          "currency": "USD", "source": source, "response_sha256": observed[t][1]}
                         for t in tickers if t in observed]
    result["missing_tickers"] = [t for t in tickers if t not in observed]
    result["status"] = "COMPLETE" if not result["missing_tickers"] else "PARTIAL" if observed else "UNAVAILABLE"
    if result["status"] == "COMPLETE":
        result["as_of_close"] = session
    validate_public_payload(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", type=Path, default=Path("docs/public/data/dashboard.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/public/data/market-quotes.json"))
    preservation = parser.add_mutually_exclusive_group()
    preservation.add_argument("--preserve-deployed", action="store_true")
    preservation.add_argument("--preserve-from", type=Path)
    args = parser.parse_args()
    if args.preserve_deployed:
        deployed, _ = fetch_json(PUBLIC_DASHBOARD)
        preserve_deployed(args.dashboard, deployed)
        return
    if args.preserve_from:
        preserve_deployed(args.dashboard, json.loads(args.preserve_from.read_text(encoding="utf-8")))
        return
    result = collect(json.loads(args.dashboard.read_text(encoding="utf-8")))
    atomic_json(args.output, result)
    print(json.dumps({k: result[k] for k in ("status", "expected_session_date", "as_of_close", "missing_tickers")}))


if __name__ == "__main__":
    main()
