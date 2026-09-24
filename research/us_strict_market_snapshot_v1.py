"""Strict U.S. Gold Set market/RS snapshot helper.

Research-only admission helper for A3 market snapshots. It compares the exact
241-session raw and split-adjusted Alpaca bars before allowing a provider-
adjusted-close proxy into the reviewed A3 research seam. Any corporate-action
basis mismatch fails closed instead of being neutral-filled or guessed.
"""
from __future__ import annotations

from datetime import datetime
import base64
import hashlib
import json
import math
import re
from typing import Any

import pandas as pd

HORIZONS = (20, 60, 120, 240)
SCHEMA = "a3-market-valuation-snapshot-v1"
RETURN_BASIS = "PROVIDER_ADJUSTED_CLOSE_PROXY"
RS_METHOD = "LOG_RELATIVE_RETURN"
SOURCE_BUNDLE_SCHEMA = "us-gold-set-market-source-bundle-v2"


class UsStrictMarketError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise UsStrictMarketError(code)


def _prepare(df: pd.DataFrame, label: str) -> pd.DataFrame:
    _require(isinstance(df, pd.DataFrame) and not df.empty, f"{label}_empty")
    _require({"date", "close"}.issubset(df.columns), f"{label}_columns")
    work = df[["date", "close"]].copy()
    work["date"] = pd.to_datetime(work["date"], errors="raise").dt.normalize()
    work["close"] = pd.to_numeric(work["close"], errors="raise").astype(float)
    _require(work["date"].is_unique, f"{label}_duplicate_date")
    _require(work["close"].map(math.isfinite).all(), f"{label}_nonfinite")
    _require((work["close"] > 0.0).all(), f"{label}_nonpositive_close")
    return work.sort_values("date").reset_index(drop=True)


def _stamp(value: str, code: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as exc:
        raise UsStrictMarketError(code) from exc
    _require(result.tzinfo is not None, code)
    return result


def _required_grid(benchmark: pd.DataFrame, session: pd.Timestamp) -> list[pd.Timestamp]:
    bench = benchmark[benchmark["date"] <= session].copy()
    _require(not bench.empty, "benchmark_session_missing")
    _require(bench.iloc[-1]["date"] == session, "benchmark_latest_session")
    sessions = bench["date"].tolist()
    _require(len(sessions) >= 241, "benchmark_insufficient_240d")
    return sessions[-241:]


def _series_on_grid(
    df: pd.DataFrame,
    required: list[pd.Timestamp],
    label: str,
) -> dict[pd.Timestamp, float]:
    mapping = dict(zip(df["date"], df["close"]))
    _require(all(day in mapping for day in required), f"{label}_incomplete_241_session_grid")
    return {day: float(mapping[day]) for day in required}


def _require_raw_split_concordance(
    raw: dict[pd.Timestamp, float],
    split: dict[pd.Timestamp, float],
    label: str,
) -> None:
    _require(raw.keys() == split.keys(), f"{label}_grid_mismatch")
    for day in raw:
        _require(
            math.isclose(raw[day], split[day], rel_tol=1e-10, abs_tol=1e-8),
            f"{label}_corporate_action_basis_mismatch:{day.date().isoformat()}",
        )


def build_source_bundle(
    *,
    session_date: str,
    source_identity: str,
    registry_sha256: str,
    raw_receipts: list[dict[str, Any]],
    raw_pages: list[bytes],
    split_receipts: list[dict[str, Any]],
    split_pages: list[bytes],
) -> tuple[str, bytes]:
    """Bind exact provider response bytes into the artifact A3 resolves.

    Request metadata contains no API credentials. Each body is base64 encoded
    only so the deterministic JSON artifact can carry the exact bytes that were
    parsed into the market frames.
    """
    _require(
        isinstance(registry_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", registry_sha256) is not None,
        "source_bundle_registry_hash",
    )
    _require(bool(source_identity), "source_bundle_source_identity")

    def basis(
        adjustment: str,
        receipts: list[dict[str, Any]],
        pages: list[bytes],
    ) -> dict[str, Any]:
        _require(len(receipts) == len(pages) and bool(pages), f"{adjustment}_page_count")
        out = []
        for expected_page, (receipt, body) in enumerate(zip(receipts, pages), 1):
            _require(isinstance(body, bytes) and bool(body), f"{adjustment}_page_bytes")
            _require(receipt.get("adjustment") == adjustment, f"{adjustment}_receipt_basis")
            _require(receipt.get("page") == expected_page, f"{adjustment}_receipt_order")
            digest = hashlib.sha256(body).hexdigest()
            _require(receipt.get("sha256") == digest, f"{adjustment}_page_hash")
            _require(receipt.get("bytes") == len(body), f"{adjustment}_page_size")
            out.append({
                "page": expected_page,
                "sha256": digest,
                "bytes": len(body),
                "endpoint": receipt.get("endpoint"),
                "request": receipt.get("request"),
                "page_token_used": receipt.get("page_token_used"),
                "body_base64": base64.b64encode(body).decode("ascii"),
            })
        return {"adjustment": adjustment, "pages": out}

    artifact_id = f"RAW-MKT:US-GOLD-SET:{session_date}:v2"
    value = {
        "schema": SOURCE_BUNDLE_SCHEMA,
        "artifact_id": artifact_id,
        "session_date": session_date,
        "source_identity": source_identity,
        "provider": "ALPACA_MARKET_DATA_V2",
        "feed": "iex",
        "timeframe": "1Day",
        "registry_sha256": registry_sha256,
        "bases": [
            basis("raw", raw_receipts, raw_pages),
            basis("split", split_receipts, split_pages),
        ],
        "raw_source_claimed": True,
        "historical_pit_certified": False,
        "validated_er_eligible": False,
    }
    raw = (
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return artifact_id, raw


def compute_snapshot(
    asset_split_df: pd.DataFrame,
    asset_raw_df: pd.DataFrame,
    benchmark_split_df: pd.DataFrame,
    benchmark_raw_df: pd.DataFrame,
    *,
    asset_id: str,
    ticker: str,
    session_date: str,
    observed_at: str,
    available_at: str,
    collected_at: str,
    source_identity: str,
    raw_artifact_id: str,
    raw_sha256: str,
) -> dict[str, Any]:
    """Build a reviewed research proxy snapshot or fail closed.

    "Reviewed" here means source/time/hash/grid/corporate-action-basis admission
    was mechanically checked for the 241-session window. It is explicitly not
    historical PIT certification and is never validated ER/target evidence.
    """
    asset_split = _prepare(asset_split_df, "asset_split")
    asset_raw = _prepare(asset_raw_df, "asset_raw")
    benchmark_split = _prepare(benchmark_split_df, "benchmark_split")
    benchmark_raw = _prepare(benchmark_raw_df, "benchmark_raw")

    session = pd.Timestamp(session_date).normalize()
    observed = _stamp(observed_at, "observed_at")
    available = _stamp(available_at, "available_at")
    collected = _stamp(collected_at, "collected_at")
    _require(observed <= available <= collected, "market_time_order")

    required = _required_grid(benchmark_split, session)
    asset_split_map = _series_on_grid(asset_split, required, "asset_split")
    asset_raw_map = _series_on_grid(asset_raw, required, "asset_raw")
    bench_split_map = _series_on_grid(benchmark_split, required, "benchmark_split")
    bench_raw_map = _series_on_grid(benchmark_raw, required, "benchmark_raw")

    _require_raw_split_concordance(asset_raw_map, asset_split_map, "asset")
    _require_raw_split_concordance(bench_raw_map, bench_split_map, "benchmark")

    end = required[-1]
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "data_quality": "REVIEWED_OBSERVED",
        "research_only": True,
        "completed_session": True,
        "session_date": end.date().isoformat(),
        "observed_at": observed.isoformat(),
        "available_at": available.isoformat(),
        "collected_at": collected.isoformat(),
        "asset_id": asset_id,
        "ticker": ticker,
        "price": float(asset_split_map[end]),
        "currency": "USD",
        "benchmark_id": "US:SPY",
        "source_identity": source_identity,
        "raw_artifact_id": raw_artifact_id,
        "raw_sha256": raw_sha256,
        "basis_review_status": "REVIEWED",
        "corporate_action_quarantine": False,
        "historical_pit_certified": False,
        "validated_er_eligible": False,
        "return_basis": RETURN_BASIS,
        "rs_method": RS_METHOD,
        "selector_eligible": False,
        "portfolio_weight_effect": 0.0,
        "target_book_write_allowed": False,
        "orders_allowed": False,
    }

    for horizon in HORIZONS:
        start = required[-(horizon + 1)]
        asset_ret = asset_split_map[end] / asset_split_map[start] - 1.0
        bench_ret = bench_split_map[end] / bench_split_map[start] - 1.0
        out[f"return_{horizon}d"] = asset_ret
        out[f"benchmark_return_{horizon}d"] = bench_ret
        out[f"rs_{horizon}d"] = math.log1p(asset_ret) - math.log1p(bench_ret)

    return out


__all__ = [
    "HORIZONS",
    "RETURN_BASIS",
    "RS_METHOD",
    "SCHEMA",
    "SOURCE_BUNDLE_SCHEMA",
    "UsStrictMarketError",
    "build_source_bundle",
    "compute_snapshot",
]
