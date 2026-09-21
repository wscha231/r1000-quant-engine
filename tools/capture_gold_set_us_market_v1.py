#!/usr/bin/env python3
"""Capture reviewed U.S. Gold Set market/RS research snapshots.

This is a bounded A1 capture, not a selector/fullrun. It downloads the 12 U.S.
Gold Set equities plus SPY from Alpaca's IEX daily-bar endpoint on both raw and
split-adjusted bases, archives the exact HTTP response bytes, and fails closed
if the required 241-session raw/split price grids disagree.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd
import requests

from research.multi_asset_v1.prices import grid as completed_nyse_grid
from research.us_strict_market_snapshot_v1 import compute_snapshot


ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
SOURCE_IDENTITY = "ALPACA_V2_IEX_RAW_SPLIT_CONCORDANCE_V1"
SCHEMA = "gold-set-us-market-capture-v1"


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def encoded(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".us-gold-market-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_registry(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    require(value.get("schema") == "cross-market-gold-set-v1", "registry_schema")
    return value, raw


def us_candidates(registry: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        row for row in registry.get("candidates", [])
        if row.get("country") == "US" and row.get("asset_class") == "EQUITY"
    ]
    require(len(rows) == 12, "us_gold_set_candidate_count")
    require(len({row["id"] for row in rows}) == len(rows), "duplicate_asset_id")
    require(len({row["ticker"] for row in rows}) == len(rows), "duplicate_ticker")
    require(all(row.get("benchmark") == "SPY" for row in rows), "benchmark_not_spy")
    require(all(row.get("currency") == "USD" for row in rows), "currency_not_usd")
    return rows


def _bars_to_frames(
    payloads: list[dict[str, Any]],
    symbols: list[str],
) -> dict[str, pd.DataFrame]:
    rows: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    for payload in payloads:
        bars = payload.get("bars")
        require(isinstance(bars, dict), "alpaca_bars_shape")
        for symbol, values in bars.items():
            require(symbol in rows, "unexpected_symbol")
            require(isinstance(values, list), "alpaca_symbol_bars_shape")
            for bar in values:
                require(isinstance(bar, dict), "alpaca_bar_shape")
                rows[symbol].append({
                    "date": pd.Timestamp(bar["t"]).date().isoformat(),
                    "close": float(bar["c"]),
                    "volume": float(bar["v"]),
                })

    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        require(bool(rows[symbol]), f"alpaca_symbol_empty:{symbol}")
        frame = pd.DataFrame(rows[symbol])
        frame["date"] = pd.to_datetime(frame["date"])
        require(frame["date"].is_unique, f"alpaca_duplicate_session:{symbol}")
        out[symbol] = frame.sort_values("date").reset_index(drop=True)
    return out


def fetch_basis(
    *,
    symbols: list[str],
    adjustment: str,
    start: str,
    end: str,
    attempt: Path,
    key: str,
    secret: str,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    require(adjustment in {"raw", "split"}, "adjustment")
    params: dict[str, Any] = {
        "symbols": ",".join(symbols),
        "timeframe": "1Day",
        "start": start,
        "end": end,
        "adjustment": adjustment,
        "feed": "iex",
        "sort": "asc",
        "limit": 10000,
    }
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
        "User-Agent": "r1000-gold-set-a1/1",
    }

    payloads: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    token: str | None = None
    page = 0
    with requests.Session() as session:
        while True:
            page += 1
            request_params = dict(params)
            if token:
                request_params["page_token"] = token
            try:
                response = session.get(
                    ALPACA_BARS_URL,
                    params=request_params,
                    headers=headers,
                    timeout=30,
                )
            except requests.RequestException as exc:
                raise RuntimeError("alpaca_transport_error") from exc
            require(response.status_code == 200, f"alpaca_http:{response.status_code}")
            raw = response.content
            digest = sha256(raw)
            exclusive(attempt / "raw" / f"{digest}.json", raw)
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("alpaca_non_json") from exc
            require(isinstance(payload, dict), "alpaca_payload_shape")
            payloads.append(payload)
            receipts.append({
                "adjustment": adjustment,
                "page": page,
                "sha256": digest,
                "bytes": len(raw),
                "endpoint": ALPACA_BARS_URL,
                "request": {
                    key: value
                    for key, value in request_params.items()
                    if key != "page_token"
                },
                "page_token_used": bool(token),
            })
            next_token = payload.get("next_page_token")
            if not next_token:
                break
            require(isinstance(next_token, str), "alpaca_page_token_type")
            require(page < 20, "alpaca_pagination_limit")
            token = next_token

    return _bars_to_frames(payloads, symbols), receipts


def build_evidence_bundle(
    *,
    asset_id: str,
    ticker: str,
    session_date: str,
    raw_receipts: list[dict[str, Any]],
    split_receipts: list[dict[str, Any]],
    registry_sha256: str,
    attempt: Path,
) -> tuple[str, str]:
    artifact_id = f"RAW-MKT:{asset_id}:{session_date}:v1"
    value = {
        "schema": "us-gold-set-market-evidence-v1",
        "artifact_id": artifact_id,
        "asset_id": asset_id,
        "ticker": ticker,
        "session_date": session_date,
        "source_identity": SOURCE_IDENTITY,
        "provider": "ALPACA_MARKET_DATA_V2",
        "feed": "iex",
        "timeframe": "1Day",
        "primary_adjustment": "split",
        "basis_crosscheck": "raw_vs_split_exact_required_241_sessions",
        "registry_sha256": registry_sha256,
        "raw_http_pages": raw_receipts,
        "split_http_pages": split_receipts,
        "raw_source_claimed": True,
        "historical_pit_certified": False,
        "validated_er_eligible": False,
    }
    raw = encoded(value)
    digest = sha256(raw)
    exclusive(attempt / "evidence" / f"{digest}.json", raw)
    return artifact_id, digest


def _cutoff(explicit_session: str | None) -> datetime:
    if not explicit_session:
        return datetime.now(timezone.utc)
    session = pd.Timestamp(explicit_session).date()
    # End-of-day UTC is after any NYSE close for the requested civil date.
    return datetime(
        session.year, session.month, session.day, 23, 59, 59, tzinfo=timezone.utc
    )


def capture(
    registry: dict[str, Any],
    registry_raw: bytes,
    attempt: Path,
    explicit_session: str | None,
) -> dict[str, Any]:
    candidates = us_candidates(registry)
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET", "").strip()
    require(bool(key and secret), "alpaca_credentials_missing")

    sessions = completed_nyse_grid(_cutoff(explicit_session), count=281)
    require(len(sessions) == 281, "nyse_grid_count")
    session_date = next(reversed(sessions))
    if explicit_session:
        require(session_date == explicit_session, "explicit_session_not_completed_nyse_session")
    observed_at = sessions[session_date].astimezone(timezone.utc).isoformat()

    symbols = [row["ticker"] for row in candidates] + ["SPY"]
    start = (pd.Timestamp(next(iter(sessions))) - pd.Timedelta(days=5)).date().isoformat()
    end = (pd.Timestamp(session_date) + pd.Timedelta(days=1)).date().isoformat()
    split_frames, split_receipts = fetch_basis(
        symbols=symbols,
        adjustment="split",
        start=start,
        end=end,
        attempt=attempt,
        key=key,
        secret=secret,
    )
    raw_frames, raw_receipts = fetch_basis(
        symbols=symbols,
        adjustment="raw",
        start=start,
        end=end,
        attempt=attempt,
        key=key,
        secret=secret,
    )

    # Collection time is recorded only after both evidence bases have arrived.
    collected_at = datetime.now(timezone.utc).isoformat()
    registry_digest = sha256(registry_raw)
    snapshots = []
    raw_artifacts = []
    for row in candidates:
        artifact_id, artifact_sha = build_evidence_bundle(
            asset_id=row["id"],
            ticker=row["ticker"],
            session_date=session_date,
            raw_receipts=raw_receipts,
            split_receipts=split_receipts,
            registry_sha256=registry_digest,
            attempt=attempt,
        )
        snapshot = compute_snapshot(
            split_frames[row["ticker"]],
            raw_frames[row["ticker"]],
            split_frames["SPY"],
            raw_frames["SPY"],
            asset_id=row["id"],
            ticker=row["ticker"],
            session_date=session_date,
            observed_at=observed_at,
            available_at=collected_at,
            collected_at=collected_at,
            source_identity=SOURCE_IDENTITY,
            raw_artifact_id=artifact_id,
            raw_sha256=artifact_sha,
        )
        snapshots.append(snapshot)
        raw_artifacts.append({
            "asset_id": row["id"],
            "artifact_id": artifact_id,
            "sha256": artifact_sha,
            "path": f"evidence/{artifact_sha}.json",
        })

    require(len({row["asset_id"] for row in snapshots}) == 12, "incomplete_us_gold_set_capture")
    manifest = {
        "schema": SCHEMA,
        "status": "COMPLETE_REVIEWED_RESEARCH_PROXY",
        "research_only": True,
        "review_required": False,
        "session_date": session_date,
        "captured_at": collected_at,
        "source_identity": SOURCE_IDENTITY,
        "return_basis": "PROVIDER_ADJUSTED_CLOSE_PROXY",
        "historical_pit_certified": False,
        "validated_er_available": False,
        "selector_eligible": False,
        "portfolio_weight_effect": 0.0,
        "target_book_write_allowed": False,
        "orders_allowed": False,
        "production_authority": False,
        "registry_sha256": registry_digest,
        "snapshots": snapshots,
        "raw_artifacts": raw_artifacts,
        "raw_http_pages": {
            "raw": raw_receipts,
            "split": split_receipts,
        },
    }
    exclusive(attempt / "capture_manifest.json", encoded(manifest))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("research/cross_market_gold_set_v1.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--session", help="Explicit completed NYSE session YYYY-MM-DD")
    args = parser.parse_args()

    require(
        args.attempt_id
        and all(ch.isalnum() or ch in "-_" for ch in args.attempt_id),
        "attempt_id",
    )
    registry, registry_raw = load_registry(args.registry)
    attempt = args.output_dir / "attempts" / args.attempt_id
    attempt.mkdir(parents=True, exist_ok=False)
    try:
        manifest = capture(registry, registry_raw, attempt, args.session)
        receipt = {
            "schema": "gold-set-us-market-capture-receipt-v1",
            "attempt_id": args.attempt_id,
            "status": manifest["status"],
            "session_date": manifest["session_date"],
            "manifest_sha256": sha256((attempt / "capture_manifest.json").read_bytes()),
            "consumable_as_reviewed_a3_market_snapshot": True,
            "research_only": True,
            "validated_er_available": False,
        }
        exclusive(attempt / "receipt.json", encoded(receipt))
        atomic(args.output_dir / "latest_attempt.json", encoded(receipt))
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {
            "schema": "gold-set-us-market-capture-receipt-v1",
            "attempt_id": args.attempt_id,
            "status": "BLOCKED",
            "reason": str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__,
            "consumable_as_reviewed_a3_market_snapshot": False,
            "research_only": True,
            "validated_er_available": False,
        }
        atomic(args.output_dir / "latest_attempt.json", encoded(blocked))
        print(json.dumps(blocked, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
