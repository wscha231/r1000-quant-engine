#!/usr/bin/env python3
"""Shared required price ticker derivation for AlphaOps integration runs.

This module is intentionally small and dependency-light because it is used by
workflow glue, freshness audit, and fullrun readiness. Keep collection, audit,
and readiness on this one source of truth so an enabled experiment cannot pass
readiness while its required hedge/benchmark price is missing from collection.
"""
from __future__ import annotations

import json
import os
from typing import Any


BASE_REQUIRED_PRICE_TICKERS = ("SPY", "QQQ")
DEFAULT_MAIN_FAST_CRASH_HEDGE_TICKER = "SH"
DEFAULT_MAIN_FAST_CRASH_HEDGE_BENCHMARK = "SPY"
CASH_TICKERS = {"", "CASH", "__CASH__", "USD", "US DOLLAR", "NAN", "NONE"}
TRUTHY = {"1", "true", "yes", "on", "y", "t"}


def is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUTHY


def normalize_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in CASH_TICKERS else ticker


def parse_env_payload(value: str | dict[str, Any] | None) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    raw = str(value or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        if '\\"' in raw:
            try:
                payload = json.loads(raw.replace('\\"', '"'))
            except json.JSONDecodeError:
                payload = None
        else:
            payload = None
        if payload is None and raw.startswith("{") and raw.endswith("}"):
            payload = {}
            for item in raw[1:-1].split(","):
                if ":" not in item:
                    continue
                key, value = item.split(":", 1)
                key = key.strip().strip('"').strip("'")
                value = value.strip().strip('"').strip("'")
                if key:
                    payload[key] = value
        if payload is None:
            return {}
    if not isinstance(payload, dict):
        return {}
    return {str(k): str(v) for k, v in payload.items()}


def env_value(env_payload: dict[str, str], key: str, default: str = "") -> str:
    if key in env_payload:
        return str(env_payload.get(key) or "")
    return str(os.environ.get(key, default) or "")


def required_price_tickers_for_env(env_payload: dict[str, str] | None = None) -> list[str]:
    """Return price tickers required by the active experiment payload.

    Initial contract:
    - SPY and QQQ are always required for benchmark/freshness anchoring.
    - Main fast-crash hedge requires a hedge ticker and benchmark.
    - Hedge ticker/benchmark may be overridden by env payload or process env.
    """
    payload = env_payload or {}
    tickers = {normalize_ticker(t) for t in BASE_REQUIRED_PRICE_TICKERS}
    fast_crash_enabled = payload.get("PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED")
    if fast_crash_enabled is None:
        fast_crash_enabled = os.environ.get("PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED", "")
    if is_truthy(fast_crash_enabled):
        tickers.add(
            normalize_ticker(
                env_value(payload, "R1000_MAIN_FAST_CRASH_HEDGE_TICKER", DEFAULT_MAIN_FAST_CRASH_HEDGE_TICKER)
            )
        )
        tickers.add(
            normalize_ticker(
                env_value(payload, "R1000_MAIN_FAST_CRASH_HEDGE_BENCHMARK", DEFAULT_MAIN_FAST_CRASH_HEDGE_BENCHMARK)
            )
        )
    return sorted(t for t in tickers if t)


def format_tickers_csv(tickers: list[str]) -> str:
    return ",".join(sorted({normalize_ticker(t) for t in tickers if normalize_ticker(t)}))
