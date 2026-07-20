#!/usr/bin/env python3
"""Advance a review-only forward paper ledger at the next observable close.

The daily operating workflow produces target books and account order previews,
but those previews are proposals rather than fills.  This tool keeps a separate
append-only forward paper state:

1. restore the last private paper account and pending orders;
2. resolve prior pending orders at the first cached close after the signal;
3. mark the paper account at the requested completed-market close;
4. build a fresh order preview from that paper account; and
5. enqueue it only when the normalized target allocation changed.

It never calls a broker, places an order, or mutates canonical production
outputs.  Private quantities and dollar values stay in the workflow artifact;
the public dashboard applies a separate allowlist before publishing fills.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_account_order_preview import normalize_target, run as run_order_preview  # noqa: E402
from tools.run_broker_ledger_replay import LedgerState, account_equity, execute_order, safe_float  # noqa: E402
from tools.run287_hold_exit_policy import SELL_TAXONOMY  # noqa: E402
from tools.run287_paper_ledger_integrity import (  # noqa: E402
    INTEGRITY_FILE,
    PaperLedgerIntegrityError,
    atomic_publish_bundle,
    clone_directory,
    directory_hashes,
    recover_interrupted_publish,
    verify_integrity_manifest,
    write_integrity_manifest,
)
from tools.run_weekly_evaluation import load_price_series, price_on_or_after, price_on_or_before  # noqa: E402
from tools.security_lifecycle import (  # noqa: E402
    SecurityLifecycleSnapshot,
    filter_terminal_tickers,
    resolve_security_lifecycle,
    verified_settlement_by_ticker,
)
from tools.reserve_asset_policy import (  # noqa: E402
    DEFAULT_CURRENT_PAPER_MODE,
    RESERVE_MODES,
    RESERVE_REASONS,
    ReserveAssetPolicy,
    account_reserve_reason_reconciliation,
    apply_reserve_asset_to_targets,
    reserve_reason_reconciliation,
    resolve_reserve_asset_policy,
)


PORTFOLIOS = ("main", "concentrated")
GENESIS_HASH = "0" * 64
EVENT_HASH_FIELDS = {"event_hash"}
PENDING_COLUMNS = [
    "portfolio_kind",
    "signal_date",
    "ticker",
    "side",
    "quantity",
    "reference_price",
    "target_weight",
    "reason",
    "sell_taxonomy",
    "sell_taxonomy_reason",
    "fill_mode",
    "cost_bps_per_side",
    "client_order_id",
    "idempotency_key",
    "order_batch_id",
    "target_hash",
    "priority",
    "pending_status",
    "created_at_utc",
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def write_csv(path: Path, frame: pd.DataFrame, columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = frame.copy()
    if columns is not None:
        for column in columns:
            if column not in out.columns:
                out[column] = ""
        extras = [column for column in out.columns if column not in columns]
        out = out.reindex(columns=[*columns, *extras])
    out.to_csv(path, index=False)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_hash(payload: Any) -> str:
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))


def file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in {"", "NAN", "NONE"} else ticker


def clean_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else pd.Timestamp(parsed).date().isoformat()


def normalized_sell_taxonomy(row: dict[str, Any]) -> tuple[str, str]:
    side = str(row.get("side") or "").upper()
    if side != "SELL":
        return "NOT_APPLICABLE", "buy_or_non_sell_event"
    raw = str(row.get("sell_taxonomy") or "").strip().upper()
    reason = str(row.get("sell_taxonomy_reason") or "").strip()
    if raw in {"", "NAN", "NONE", "NULL"}:
        return "EXECUTION_RECONCILIATION", "legacy_pending_order_without_taxonomy"
    if raw not in SELL_TAXONOMY:
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", f"invalid sell taxonomy:{raw}")
    return raw, reason or "canonical_sell_taxonomy"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalized_target(target_path: Path, portfolio: str, as_of_date: pd.Timestamp) -> pd.DataFrame:
    target = normalize_target(read_csv(target_path), portfolio, as_of_date.date().isoformat())
    if target.empty:
        return pd.DataFrame(columns=["ticker", "target_weight"])
    target = target[["ticker", "target_weight"]].copy()
    target["ticker"] = target["ticker"].map(clean_ticker)
    target["target_weight"] = pd.to_numeric(target["target_weight"], errors="coerce").fillna(0.0)
    target = target[(target["ticker"] != "") & (target["target_weight"] > 1e-12)].copy()
    target = target.groupby("ticker", as_index=False)["target_weight"].sum()
    return target.sort_values("ticker").reset_index(drop=True)


def target_hash(target: pd.DataFrame) -> str:
    rows = [
        {"ticker": str(row.ticker), "target_weight": round(float(row.target_weight), 12)}
        for row in target.itertuples(index=False)
    ]
    return canonical_hash({"schema": "run287-forward-target-v1", "rows": rows})


def target_effective_date(target_path: Path, as_of_date: pd.Timestamp) -> pd.Timestamp | None:
    raw = read_csv(target_path)
    if raw.empty or "rebalance_date" not in raw.columns:
        return None
    dates = pd.to_datetime(raw["rebalance_date"], errors="coerce").dropna().dt.normalize()
    eligible = dates[dates <= as_of_date]
    return pd.Timestamp(eligible.max()).normalize() if not eligible.empty else None


def materialize_lifecycle_adjusted_target(
    *,
    source_target_path: Path,
    output_path: Path,
    portfolio: str,
    as_of_date: pd.Timestamp,
    lifecycle: SecurityLifecycleSnapshot,
    reserve_policy: ReserveAssetPolicy,
    reserve_mode_explicit: bool,
) -> tuple[Path, pd.DataFrame]:
    """Write the effective target without silently reallocating terminal weight."""

    target = normalized_target(source_target_path, portfolio, as_of_date)
    if reserve_mode_explicit:
        target, _reserve_audit = apply_reserve_asset_to_targets(
            target,
            policy=reserve_policy,
            weight_col="target_weight",
        )
    if reserve_policy.tradeable and reserve_policy.asset_ticker in lifecycle.terminal_tickers:
        raise PaperLedgerIntegrityError(
            "BLOCKED_RESERVE_LIFECYCLE",
            f"Reserve asset is terminal at decision time: {reserve_policy.asset_ticker}",
        )
    adjusted = filter_terminal_tickers(target, lifecycle)
    rows = adjusted.rename(columns={"target_weight": "weight"}).copy()
    rows.insert(0, "rebalance_date", as_of_date.date().isoformat())
    columns = ["rebalance_date", "ticker", "weight"]
    if reserve_mode_explicit:
        columns.extend(
            column
            for column in [*RESERVE_REASONS, "reserve_asset_policy_schema", "reserve_asset_mode", "reserve_asset_ticker", "reserve_asset_tradeable", "reserve_reason_reconciled"]
            if column in rows.columns
        )
    write_csv(output_path, rows, columns)
    return output_path, adjusted


def state_from_account(account: dict[str, Any]) -> LedgerState:
    positions = account.get("positions") if isinstance(account.get("positions"), list) else []
    shares: dict[str, float] = {}
    basis: dict[str, float] = {}
    for row in positions:
        if not isinstance(row, dict):
            continue
        ticker = clean_ticker(row.get("ticker"))
        quantity = safe_float(row.get("shares"), 0.0)
        if not ticker or quantity <= 1e-12:
            continue
        shares[ticker] = float(quantity)
        basis[ticker] = float(safe_float(row.get("cost_basis"), safe_float(row.get("price"), 0.0)))
    realized = account.get("realized_pnl_by_ticker") if isinstance(account.get("realized_pnl_by_ticker"), dict) else {}
    state = LedgerState(
        cash=float(safe_float(account.get("cash_usd"), 0.0)),
        shares=shares,
        cost_basis=basis,
        realized_pnl={clean_ticker(key): float(safe_float(value, 0.0)) for key, value in realized.items() if clean_ticker(key)},
    )
    if state.cash < -1e-6:
        raise ValueError("paper account contains negative cash")
    return state


def validate_seed_account(account: dict[str, Any], portfolio: str, as_of_date: pd.Timestamp, cost_bps: float) -> None:
    if not account:
        raise FileNotFoundError(f"missing bootstrap account for {portfolio}")
    if str(account.get("portfolio_kind") or portfolio).lower() != portfolio:
        raise ValueError(f"bootstrap portfolio mismatch for {portfolio}")
    seed_date = pd.to_datetime(account.get("as_of_date"), errors="coerce")
    if pd.notna(seed_date) and pd.Timestamp(seed_date).normalize() > as_of_date:
        raise ValueError(f"bootstrap account is from the future for {portfolio}")
    fill_mode = str(account.get("fill_mode") or "next_close").lower()
    if fill_mode != "next_close":
        raise ValueError(f"bootstrap account must use next_close for {portfolio}")
    if account.get("integer_shares") is False:
        raise ValueError(f"bootstrap account must use integer shares for {portfolio}")
    account_cost = safe_float(account.get("cost_bps_per_side"), cost_bps)
    if abs(float(account_cost) - float(cost_bps)) > 1e-9:
        raise ValueError(f"bootstrap cost mismatch for {portfolio}")


def load_or_seed_account(
    *,
    portfolio_dir: Path,
    bootstrap_path: Path,
    portfolio: str,
    as_of_date: pd.Timestamp,
    cost_bps: float,
) -> tuple[dict[str, Any], LedgerState, bool]:
    state_path = portfolio_dir / "account_state_latest.json"
    account = read_json(state_path)
    seeded = False
    if not account:
        account = read_json(bootstrap_path)
        validate_seed_account(account, portfolio, as_of_date, cost_bps)
        seed_date = pd.to_datetime(account.get("seed_as_of_date") or account.get("as_of_date"), errors="coerce")
        canonical_genesis = (
            str(account.get("schema_version") or "") == "run287-daily-paper-bootstrap-account-v1"
            or bool(account.get("account_id"))
        )
        if canonical_genesis and pd.notna(seed_date) and as_of_date > pd.Timestamp(seed_date).normalize():
            raise PaperLedgerIntegrityError(
                "BLOCKED_MISSING_PERSISTENCE_AFTER_GENESIS",
                f"missing {portfolio} durable state after genesis {pd.Timestamp(seed_date).date().isoformat()}",
            )
        seeded = True
    else:
        if account.get("review_only") is not True or account.get("live_trading_enabled") is not False:
            raise ValueError(f"restored paper account safety flags invalid for {portfolio}")
        state_date = pd.to_datetime(account.get("as_of_date"), errors="coerce")
        if pd.notna(state_date) and pd.Timestamp(state_date).normalize() > as_of_date:
            raise ValueError(f"restored paper account is from the future for {portfolio}")
    return account, state_from_account(account), seeded


def validate_restored_snapshot(portfolio_dir: Path, portfolio: str) -> None:
    """Validate a prior committed portfolio before advancing its state."""
    account_path = portfolio_dir / "account_state_latest.json"
    if not account_path.is_file():
        return
    required = (
        "positions_latest.csv",
        "pending_orders.csv",
        "fills.csv",
        "rejections.csv",
        "equity_curve.csv",
        "state_meta.json",
        "manifest.json",
    )
    missing = [name for name in required if not (portfolio_dir / name).is_file()]
    if missing:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", f"incomplete restored {portfolio} snapshot; missing={missing}"
        )
    account = read_json(account_path)
    manifest = read_json(portfolio_dir / "manifest.json")
    meta = read_json(portfolio_dir / "state_meta.json")
    curve = read_csv(portfolio_dir / "equity_curve.csv")
    pending = read_csv(portfolio_dir / "pending_orders.csv")
    fills = read_csv(portfolio_dir / "fills.csv")
    rejections = read_csv(portfolio_dir / "rejections.csv")
    errors: list[str] = []
    account_date = clean_date(account.get("as_of_date"))
    manifest_date = clean_date(manifest.get("as_of_date"))
    meta_date = clean_date(meta.get("as_of_date"))
    curve_dates = pd.to_datetime(curve.get("date", pd.Series(dtype=str)), errors="coerce").dropna()
    curve_date = curve_dates.iloc[-1].date().isoformat() if not curve_dates.empty else ""
    if not account_date or len({account_date, manifest_date, meta_date, curve_date}) != 1:
        errors.append("as_of_date_mismatch")
    for payload, label in ((account, "account"), (manifest, "manifest"), (meta, "meta")):
        if str(payload.get("portfolio_kind") or "").lower() != portfolio:
            errors.append(f"{label}_portfolio")
        if payload.get("review_only") is not True or payload.get("live_trading_enabled") is not False:
            errors.append(f"{label}_safety")
    try:
        sequence, chain_hash, client_ids = validate_event_chain(fills, rejections)
    except ValueError as exc:
        errors.append(f"event_chain:{exc}")
        sequence, chain_hash, client_ids = -1, "", set()
    event_client_ids = [
        str(value) for value in pd.concat(
            [fills.get("client_order_id", pd.Series(dtype=str)), rejections.get("client_order_id", pd.Series(dtype=str))],
            ignore_index=True,
        ).fillna("").tolist() if str(value)
    ]
    if len(event_client_ids) != len(set(event_client_ids)) or len(client_ids) != len(set(event_client_ids)):
        errors.append("duplicate_resolved_client_order_id")
    pending_ids = [str(value) for value in pending.get("client_order_id", pd.Series(dtype=str)).fillna("").tolist() if str(value)]
    if len(pending_ids) != len(set(pending_ids)) or set(pending_ids) & set(event_client_ids):
        errors.append("duplicate_pending_client_order_id")
    expected_counts = {
        "pending_order_count": len(pending),
        "fill_count": len(fills),
        "rejection_count": len(rejections),
        "event_sequence": sequence,
    }
    for key, expected in expected_counts.items():
        if int(safe_float(manifest.get(key), -1)) != expected or int(safe_float(meta.get(key), -1)) != expected:
            errors.append(f"stored_{key}")
    if str(manifest.get("event_chain_hash") or "") != chain_hash or str(meta.get("event_chain_hash") or "") != chain_hash:
        errors.append("stored_event_chain_hash")
    if int(safe_float(account.get("pending_order_count"), -1)) != len(pending):
        errors.append("account_pending_order_count")
    state_from_account(account)
    if errors:
        raise PaperLedgerIntegrityError(
            "BLOCKED_INTEGRITY", f"restored {portfolio} snapshot validation failed: {','.join(errors)}"
        )


def ensure_genesis_identity(
    *,
    state_root: Path,
    bootstrap_paths: dict[str, Path],
    target_paths: dict[str, Path],
    cost_bps: float,
    max_fill_lag_days: int,
) -> dict[str, Any]:
    portfolios: dict[str, Any] = {}
    seed_dates: set[str] = set()
    starting_capitals: set[float] = set()
    for portfolio in PORTFOLIOS:
        account = read_json(bootstrap_paths[portfolio])
        validate_seed_account(account, portfolio, pd.Timestamp.max.normalize(), cost_bps)
        seed_date = clean_date(account.get("seed_as_of_date") or account.get("as_of_date"))
        if not seed_date:
            raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", f"missing genesis date for {portfolio}")
        seed_dates.add(seed_date)
        capital = float(safe_float(account.get("starting_capital_usd"), safe_float(account.get("equity_usd"), 0.0)))
        if capital <= 0:
            raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", f"invalid genesis capital for {portfolio}")
        starting_capitals.add(capital)
        seed_target = normalized_target(target_paths[portfolio], portfolio, pd.Timestamp(seed_date))
        digest = str(account.get("assumed_applied_target_hash") or target_hash(seed_target))
        portfolios[portfolio] = {
            "account_id": str(account.get("account_id") or f"run287-paper-{portfolio}-{seed_date}"),
            "starting_capital_usd": capital,
            "target_hash": digest,
            "target_sha256": str(account.get("target_sha256") or file_hash(target_paths[portfolio])),
            "bootstrap_account_sha256": file_hash(bootstrap_paths[portfolio]),
        }
    contract = {
        "fill_mode": "next_close",
        "integer_shares": True,
        "cost_bps_per_side": float(cost_bps),
        "max_fill_lag_days": int(max_fill_lag_days),
        "sell_before_buy": True,
        "cash_must_be_nonnegative": True,
    }
    identity = {
        "schema_version": "run287-paper-genesis-identity-v1",
        "seed_dates": sorted(seed_dates),
        "starting_capitals_usd": sorted(starting_capitals),
        "portfolios": portfolios,
        "execution_contract": contract,
        "policy_hash": canonical_hash({"schema": "run287-paper-policy-v1", "portfolios": portfolios, "contract": contract}),
    }
    identity["genesis_identity_hash"] = canonical_hash(identity)
    path = state_root / "genesis_identity.json"
    existing = read_json(path)
    if existing and existing != identity:
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", "genesis identity changed")
    if not existing:
        write_json(path, identity)
    return identity


def load_prices(
    price_cache: Path,
    tickers: set[str],
    provider_symbol_overrides: dict[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    prices: dict[str, pd.DataFrame] = {}
    for ticker in sorted({clean_ticker(value) for value in tickers if clean_ticker(value)}):
        frame = load_price_series(price_cache, ticker)
        provider = (provider_symbol_overrides or {}).get(ticker, ticker)
        if frame.empty and provider != ticker:
            frame = load_price_series(price_cache, provider)
        if not frame.empty:
            prices[ticker] = frame
    return prices


def require_exact_session_closes(
    *,
    price_cache: Path,
    tickers: set[str],
    as_of_date: pd.Timestamp,
    context: str,
    provider_symbol_overrides: dict[str, str] | None = None,
) -> None:
    required = {clean_ticker(value) for value in tickers if clean_ticker(value) not in {"", "CASH", "USD"}}
    prices = load_prices(price_cache, required, provider_symbol_overrides)
    failures: list[str] = []
    for ticker in sorted(required):
        actual_date, price = price_on_or_before(prices.get(ticker, pd.DataFrame()), as_of_date, "close")
        actual_date = pd.Timestamp(actual_date).normalize() if actual_date is not None else None
        value = float(price) if price is not None else math.nan
        if actual_date != as_of_date or not math.isfinite(value) or value <= 0:
            failures.append(ticker)
    if failures:
        raise PaperLedgerIntegrityError(
            "BLOCKED_MISSING_EXACT_CLOSE",
            f"missing exact completed-session {context} closes on {as_of_date.date().isoformat()}: {failures}",
        )


def event_payload_for_hash(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in row.items() if key not in EVENT_HASH_FIELDS}


def combined_events(fills: pd.DataFrame, rejections: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for frame in (fills, rejections):
        if not frame.empty:
            rows.extend(frame.to_dict("records"))
    return sorted(rows, key=lambda row: int(safe_float(row.get("event_sequence"), 0.0)))


def validate_event_chain(fills: pd.DataFrame, rejections: pd.DataFrame) -> tuple[int, str, set[str]]:
    rows = combined_events(fills, rejections)
    previous = GENESIS_HASH
    last_sequence = 0
    event_ids: set[str] = set()
    client_ids: set[str] = set()
    for row in rows:
        sequence = int(safe_float(row.get("event_sequence"), 0.0))
        event_id = str(row.get("event_id") or "")
        if sequence != last_sequence + 1:
            raise ValueError("forward paper event sequence is not contiguous")
        if not event_id or event_id in event_ids:
            raise ValueError("forward paper event id is missing or duplicated")
        if str(row.get("previous_event_hash") or "") != previous:
            raise ValueError("forward paper previous-event hash mismatch")
        expected = canonical_hash(event_payload_for_hash(row))
        if str(row.get("event_hash") or "") != expected:
            raise ValueError("forward paper event hash mismatch")
        previous = expected
        last_sequence = sequence
        event_ids.add(event_id)
        client_id = str(row.get("client_order_id") or "")
        if client_id:
            if client_id in client_ids:
                raise ValueError("forward paper client order id is duplicated")
            client_ids.add(client_id)
    return last_sequence, previous, client_ids


def append_event(
    *,
    rows: list[dict[str, Any]],
    sequence: int,
    previous_hash: str,
    client_order_id: str,
    event_type: str,
    event_date: str,
    reason: str,
    payload: dict[str, Any],
) -> tuple[int, str]:
    sequence += 1
    event_id = canonical_hash(
        {
            "client_order_id": client_order_id,
            "event_type": event_type,
            "event_date": event_date,
            "reason": reason,
        }
    )[:32]
    row = {
        **payload,
        "event_sequence": sequence,
        "event_id": event_id,
        "event_type": event_type,
        "event_date": event_date,
        "event_reason": reason,
        "previous_event_hash": previous_hash,
    }
    row["event_hash"] = canonical_hash(event_payload_for_hash(row))
    rows.append(row)
    return sequence, str(row["event_hash"])


def apply_lifecycle_actions(
    *,
    portfolio: str,
    state: LedgerState,
    pending: pd.DataFrame,
    fills: pd.DataFrame,
    rejections: pd.DataFrame,
    lifecycle: SecurityLifecycleSnapshot,
    as_of_date: pd.Timestamp,
    cost_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Settle verified terminal positions and cancel impossible pending orders."""

    settlement_map = verified_settlement_by_ticker(lifecycle)
    if not settlement_map:
        return pending, fills, rejections, {
            "settled_positions": 0,
            "cancelled_pending_orders": 0,
        }

    sequence, previous_hash, resolved_client_ids = validate_event_chain(
        fills, rejections
    )
    fill_rows = fills.to_dict("records") if not fills.empty else []
    rejection_rows = rejections.to_dict("records") if not rejections.empty else []
    settled_positions = 0
    handled_events: set[str] = set()

    for ticker in sorted(set(state.shares) & set(settlement_map)):
        event = settlement_map[ticker]
        stable_event_id = str(event["stable_event_id"])
        if stable_event_id in handled_events:
            raise PaperLedgerIntegrityError(
                "BLOCKED_LIFECYCLE_EVIDENCE",
                f"same economic security is held under multiple aliases:{stable_event_id}",
            )
        handled_events.add(stable_event_id)
        quantity = float(state.shares.get(ticker, 0.0))
        if quantity <= 1e-12:
            continue
        client_id = canonical_hash(
            {
                "portfolio": portfolio,
                "stable_event_id": stable_event_id,
                "event_type": "LIFECYCLE_SETTLEMENT",
            }
        )[:32]
        if client_id in resolved_client_ids:
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                f"settled lifecycle position reappeared:{ticker}",
            )
        proceeds_per_share = float(event["verified_proceeds"])
        gross_value = quantity * proceeds_per_share
        basis = float(state.cost_basis.get(ticker, proceeds_per_share))
        state.cash += gross_value
        state.realized_pnl[ticker] = float(
            state.realized_pnl.get(ticker, 0.0)
            + quantity * (proceeds_per_share - basis)
        )
        del state.shares[ticker]
        state.cost_basis.pop(ticker, None)
        payload = {
            "portfolio_kind": portfolio,
            "date": as_of_date.date().isoformat(),
            "signal_date": str(event["available_from"]),
            "ticker": ticker,
            "side": "SETTLEMENT",
            "quantity": quantity,
            "requested_quantity": quantity,
            "fill_price": proceeds_per_share,
            "gross_value": gross_value,
            "fee_usd": 0.0,
            "cash_delta": gross_value,
            "cash_after": float(state.cash),
            "shares_after": 0.0,
            "target_weight": 0.0,
            "reason": str(event["event_type"]),
            "sell_taxonomy": "LIFECYCLE_EXIT",
            "sell_taxonomy_reason": "verified_security_lifecycle",
            "fill_mode": "verified_lifecycle_proceeds",
            "cost_bps_per_side": 0.0,
            "client_order_id": client_id,
            "idempotency_key": stable_event_id,
            "order_batch_id": "LIFECYCLE",
            "target_hash": lifecycle.snapshot_hash,
            "execution_status": "SIMULATED_LIFECYCLE_SETTLEMENT",
            "record_type": "FORWARD_PAPER_LIFECYCLE",
            "review_only": True,
            "simulated": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
        }
        sequence, previous_hash = append_event(
            rows=fill_rows,
            sequence=sequence,
            previous_hash=previous_hash,
            client_order_id=client_id,
            event_type="LIFECYCLE_SETTLEMENT",
            event_date=as_of_date.date().isoformat(),
            reason=str(event["event_type"]),
            payload=payload,
        )
        resolved_client_ids.add(client_id)
        settled_positions += 1

    keep_pending: list[dict[str, Any]] = []
    cancelled_pending_orders = 0
    for row in pending.to_dict("records") if not pending.empty else []:
        ticker = clean_ticker(row.get("ticker"))
        if ticker not in settlement_map:
            keep_pending.append(row)
            continue
        client_id = str(row.get("client_order_id") or "")
        if not client_id or client_id in resolved_client_ids:
            raise PaperLedgerIntegrityError(
                "BLOCKED_INTEGRITY",
                f"invalid lifecycle-cancelled pending order:{ticker}",
            )
        payload = {
            "portfolio_kind": portfolio,
            "date": as_of_date.date().isoformat(),
            "signal_date": clean_date(row.get("signal_date")),
            "ticker": ticker,
            "side": str(row.get("side") or "").upper(),
            "requested_quantity": safe_float(row.get("quantity"), 0.0),
            "target_weight": safe_float(row.get("target_weight"), 0.0),
            "sell_taxonomy": str(row.get("sell_taxonomy") or "LIFECYCLE_EXIT"),
            "sell_taxonomy_reason": str(row.get("sell_taxonomy_reason") or "lifecycle_terminal_cancelled"),
            "client_order_id": client_id,
            "idempotency_key": str(row.get("idempotency_key") or ""),
            "order_batch_id": str(row.get("order_batch_id") or ""),
            "target_hash": str(row.get("target_hash") or ""),
            "execution_status": "SIMULATED_REJECTED",
            "fill_mode": "lifecycle_cancel",
            "cost_bps_per_side": float(cost_bps),
            "review_only": True,
            "simulated": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
        }
        sequence, previous_hash = append_event(
            rows=rejection_rows,
            sequence=sequence,
            previous_hash=previous_hash,
            client_order_id=client_id,
            event_type="REJECTION",
            event_date=as_of_date.date().isoformat(),
            reason="lifecycle_terminal_cancelled",
            payload=payload,
        )
        resolved_client_ids.add(client_id)
        cancelled_pending_orders += 1

    fills_out = pd.DataFrame(fill_rows)
    rejections_out = pd.DataFrame(rejection_rows)
    validate_event_chain(fills_out, rejections_out)
    return (
        pd.DataFrame(keep_pending, columns=pending.columns),
        fills_out,
        rejections_out,
        {
            "settled_positions": settled_positions,
            "cancelled_pending_orders": cancelled_pending_orders,
        },
    )


def resolve_pending_orders(
    *,
    portfolio: str,
    state: LedgerState,
    pending: pd.DataFrame,
    fills: pd.DataFrame,
    rejections: pd.DataFrame,
    price_cache: Path,
    as_of_date: pd.Timestamp,
    cost_bps: float,
    max_fill_lag_days: int,
    provider_symbol_overrides: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    sequence, previous_hash, resolved_client_ids = validate_event_chain(fills, rejections)
    fill_rows = fills.to_dict("records") if not fills.empty else []
    rejection_rows = rejections.to_dict("records") if not rejections.empty else []
    if pending.empty:
        return pd.DataFrame(columns=PENDING_COLUMNS), pd.DataFrame(fill_rows), pd.DataFrame(rejection_rows), {
            "resolved_fills": 0,
            "resolved_rejections": 0,
        }

    pending_client_ids = [
        str(value) for value in pending.get("client_order_id", pd.Series(dtype=str)).fillna("").tolist()
    ]
    if any(not value for value in pending_client_ids) or len(pending_client_ids) != len(set(pending_client_ids)):
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", "pending client order id is missing or duplicated")
    if set(pending_client_ids) & resolved_client_ids:
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", "pending client order id was already resolved")

    candidates: list[tuple[pd.Timestamp, int, int, dict[str, Any], float]] = []
    keep_pending: list[dict[str, Any]] = []
    stale_rejections: list[tuple[dict[str, Any], str]] = []
    tickers = {clean_ticker(value) for value in pending.get("ticker", pd.Series(dtype=str)).tolist()}
    prices = load_prices(price_cache, tickers, provider_symbol_overrides)

    for index, row in enumerate(pending.to_dict("records")):
        client_id = str(row.get("client_order_id") or "")
        if client_id in resolved_client_ids:
            continue
        ticker = clean_ticker(row.get("ticker"))
        side = str(row.get("side") or "").upper()
        signal_date = pd.to_datetime(row.get("signal_date"), errors="coerce")
        if not client_id or not ticker or side not in {"BUY", "SELL"} or pd.isna(signal_date):
            stale_rejections.append((row, "invalid_pending_order"))
            continue
        signal_date = pd.Timestamp(signal_date).normalize()
        if signal_date >= as_of_date:
            keep_pending.append(row)
            continue
        target_date = signal_date + pd.Timedelta(days=1)
        actual_date, fill_px = price_on_or_after(prices.get(ticker, pd.DataFrame()), target_date, "close")
        actual_date = pd.Timestamp(actual_date).normalize() if actual_date is not None else None
        lag_expired = as_of_date > target_date + pd.Timedelta(days=int(max_fill_lag_days))
        if actual_date is None or fill_px is None or actual_date > as_of_date:
            if lag_expired:
                stale_rejections.append((row, "missing_next_close_after_max_lag"))
            else:
                keep_pending.append(row)
            continue
        if (actual_date - target_date).days > int(max_fill_lag_days):
            stale_rejections.append((row, "next_close_exceeds_max_lag"))
            continue
        side_priority = 0 if side == "SELL" else 1
        priority = int(safe_float(row.get("priority"), index))
        candidates.append((actual_date, side_priority, priority, row, float(fill_px)))

    new_fill_count = 0
    new_rejection_count = 0
    for row, reason in stale_rejections:
        client_id = str(row.get("client_order_id") or "")
        signal = clean_date(row.get("signal_date"))
        sell_taxonomy, sell_taxonomy_reason = normalized_sell_taxonomy(row)
        payload = {
            "portfolio_kind": portfolio,
            "date": as_of_date.date().isoformat(),
            "signal_date": signal,
            "ticker": clean_ticker(row.get("ticker")),
            "side": str(row.get("side") or "").upper(),
            "requested_quantity": safe_float(row.get("quantity"), 0.0),
            "target_weight": safe_float(row.get("target_weight"), 0.0),
            "sell_taxonomy": sell_taxonomy,
            "sell_taxonomy_reason": sell_taxonomy_reason,
            "client_order_id": client_id,
            "idempotency_key": str(row.get("idempotency_key") or ""),
            "order_batch_id": str(row.get("order_batch_id") or ""),
            "target_hash": str(row.get("target_hash") or ""),
            "execution_status": "SIMULATED_REJECTED",
            "fill_mode": "next_close",
            "cost_bps_per_side": float(cost_bps),
            "review_only": True,
            "simulated": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
        }
        sequence, previous_hash = append_event(
            rows=rejection_rows,
            sequence=sequence,
            previous_hash=previous_hash,
            client_order_id=client_id,
            event_type="REJECTION",
            event_date=as_of_date.date().isoformat(),
            reason=reason,
            payload=payload,
        )
        new_rejection_count += 1

    for fill_date, _side_priority, _priority, row, fill_px in sorted(
        candidates, key=lambda item: (item[0], item[1], item[2], clean_ticker(item[3].get("ticker")))
    ):
        client_id = str(row.get("client_order_id") or "")
        requested = float(safe_float(row.get("quantity"), 0.0))
        sell_taxonomy, sell_taxonomy_reason = normalized_sell_taxonomy(row)
        order = execute_order(
            state=state,
            ticker=clean_ticker(row.get("ticker")),
            side=str(row.get("side") or "").upper(),
            desired_qty=requested,
            price=float(fill_px),
            cost_bps=float(cost_bps),
            integer_shares=True,
        )
        if not order:
            payload = {
                "portfolio_kind": portfolio,
                "date": fill_date.date().isoformat(),
                "signal_date": clean_date(row.get("signal_date")),
                "ticker": clean_ticker(row.get("ticker")),
                "side": str(row.get("side") or "").upper(),
                "requested_quantity": requested,
                "target_weight": safe_float(row.get("target_weight"), 0.0),
                "sell_taxonomy": sell_taxonomy,
                "sell_taxonomy_reason": sell_taxonomy_reason,
                "client_order_id": client_id,
                "idempotency_key": str(row.get("idempotency_key") or ""),
                "order_batch_id": str(row.get("order_batch_id") or ""),
                "target_hash": str(row.get("target_hash") or ""),
                "execution_status": "SIMULATED_REJECTED",
                "fill_mode": "next_close",
                "cost_bps_per_side": float(cost_bps),
                "review_only": True,
                "simulated": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
            }
            sequence, previous_hash = append_event(
                rows=rejection_rows,
                sequence=sequence,
                previous_hash=previous_hash,
                client_order_id=client_id,
                event_type="REJECTION",
                event_date=fill_date.date().isoformat(),
                reason="insufficient_cash_or_position",
                payload=payload,
            )
            new_rejection_count += 1
            continue
        filled_quantity = float(order.get("quantity") or 0.0)
        execution_status = "SIMULATED_FILL" if abs(filled_quantity - requested) <= 1e-9 else "SIMULATED_PARTIAL_FILL"
        payload = {
            "portfolio_kind": portfolio,
            "date": fill_date.date().isoformat(),
            "signal_date": clean_date(row.get("signal_date")),
            "ticker": clean_ticker(row.get("ticker")),
            "side": str(row.get("side") or "").upper(),
            "quantity": filled_quantity,
            "requested_quantity": requested,
            "fill_price": float(order.get("fill_price") or fill_px),
            "gross_value": float(order.get("gross_value") or 0.0),
            "fee_usd": float(order.get("fee_usd") or 0.0),
            "cash_delta": float(order.get("cash_delta") or 0.0),
            "cash_after": float(order.get("cash_after") or state.cash),
            "shares_after": float(order.get("shares_after") or 0.0),
            "target_weight": safe_float(row.get("target_weight"), 0.0),
            "reason": str(row.get("reason") or "target_rebalance"),
            "sell_taxonomy": sell_taxonomy,
            "sell_taxonomy_reason": sell_taxonomy_reason,
            "fill_mode": "next_close",
            "cost_bps_per_side": float(cost_bps),
            "client_order_id": client_id,
            "idempotency_key": str(row.get("idempotency_key") or ""),
            "order_batch_id": str(row.get("order_batch_id") or ""),
            "target_hash": str(row.get("target_hash") or ""),
            "execution_status": execution_status,
            "record_type": "FORWARD_PAPER",
            "review_only": True,
            "simulated": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
        }
        sequence, previous_hash = append_event(
            rows=fill_rows,
            sequence=sequence,
            previous_hash=previous_hash,
            client_order_id=client_id,
            event_type="FILL",
            event_date=fill_date.date().isoformat(),
            reason="next_close_simulated_fill",
            payload=payload,
        )
        new_fill_count += 1

    pending_out = pd.DataFrame(keep_pending)
    fills_out = pd.DataFrame(fill_rows)
    rejections_out = pd.DataFrame(rejection_rows)
    validate_event_chain(fills_out, rejections_out)
    return pending_out, fills_out, rejections_out, {
        "resolved_fills": new_fill_count,
        "resolved_rejections": new_rejection_count,
    }


def mark_account(
    *,
    account: dict[str, Any],
    state: LedgerState,
    portfolio: str,
    as_of_date: pd.Timestamp,
    price_cache: Path,
    fills: pd.DataFrame,
    pending: pd.DataFrame,
    cost_bps: float,
    seed_path: Path,
    provider_symbol_overrides: dict[str, str] | None = None,
    reserve_policy: ReserveAssetPolicy,
    reserve_reconciliation: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    prices = load_prices(
        price_cache, set(state.shares), provider_symbol_overrides
    )
    equity, values = account_equity(state, prices, as_of_date)
    if equity <= 0 or state.cash < -1e-6:
        raise ValueError(f"invalid paper account equity/cash for {portfolio}")
    reserve_asset_value = (
        float(values.get(reserve_policy.asset_ticker, 0.0))
        if reserve_policy.tradeable
        else 0.0
    )
    reserve_value = float(state.cash) + reserve_asset_value
    actual_reconciliation = account_reserve_reason_reconciliation(
        reserve_reconciliation,
        actual_reserve_weight=reserve_value / equity,
    )
    position_rows: list[dict[str, Any]] = []
    for ticker in sorted(state.shares):
        quantity = float(state.shares.get(ticker, 0.0))
        if quantity <= 1e-12:
            continue
        exact_date, price = price_on_or_before(prices.get(ticker, pd.DataFrame()), as_of_date, "close")
        exact_date = pd.Timestamp(exact_date).normalize() if exact_date is not None else None
        if exact_date is None or exact_date != as_of_date or price is None:
            raise PaperLedgerIntegrityError(
                "BLOCKED_MISSING_EXACT_CLOSE",
                f"missing exact completed-session close for held {ticker} on {as_of_date.date().isoformat()}",
            )
        price = float(price)
        if not math.isfinite(price) or price <= 0:
            raise PaperLedgerIntegrityError(
                "BLOCKED_MISSING_EXACT_CLOSE",
                f"invalid exact completed-session close for held {ticker} on {as_of_date.date().isoformat()}",
            )
        market_value = float(values.get(ticker, quantity * price))
        basis = float(state.cost_basis.get(ticker, price))
        position_rows.append(
            {
                "as_of_date": as_of_date.date().isoformat(),
                "ticker": ticker,
                "shares": quantity,
                "price": price,
                "market_value_usd": market_value,
                "weight": market_value / equity,
                "cost_basis": basis,
                "unrealized_pnl_usd": market_value - quantity * basis,
                "realized_pnl_usd": float(state.realized_pnl.get(ticker, 0.0)),
                "reserve_asset": bool(
                    reserve_policy.tradeable and ticker == reserve_policy.asset_ticker
                ),
            }
        )
    total_fees = (
        float(pd.to_numeric(fills.get("fee_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
        if not fills.empty
        else 0.0
    )
    seed_date = str(account.get("seed_as_of_date") or account.get("as_of_date") or "")
    seed_equity = float(safe_float(account.get("seed_equity_usd"), safe_float(account.get("equity_usd"), equity)))
    output = {
        "schema_version": "daily-simulated-account-v1",
        "portfolio_kind": portfolio,
        "as_of_date": as_of_date.date().isoformat(),
        "seed_as_of_date": seed_date,
        "seed_equity_usd": seed_equity,
        "seed_account_sha256": str(account.get("seed_account_sha256") or file_hash(seed_path)),
        "starting_capital_usd": float(safe_float(account.get("starting_capital_usd"), seed_equity)),
        "equity_usd": float(equity),
        "cash_usd": float(state.cash),
        "cash_weight": float(state.cash / equity),
        "stock_value_usd": float(
            sum(
                value
                for ticker, value in values.items()
                if ticker != reserve_policy.asset_ticker or not reserve_policy.tradeable
            )
        ),
        "reserve_asset_value_usd": reserve_asset_value,
        "reserve_value_usd": reserve_value,
        "position_count": sum(1 for row in position_rows if not row["reserve_asset"]),
        "fill_mode": "next_close",
        "cost_bps_per_side": float(cost_bps),
        "integer_shares": True,
        "cash_carry_mode": "none",
        "cash_carry_note": "forward execution monitor; official historical cash-carry metrics remain separate",
        "reserve_asset_policy": reserve_policy.audit(),
        "reserve_asset_mode": reserve_policy.mode,
        "reserve_asset_ticker": reserve_policy.asset_ticker,
        "reserve_weight": float(actual_reconciliation["actual_reserve_weight"]),
        "target_reserve_reason_reconciliation": reserve_reconciliation,
        "reserve_reason_reconciliation": actual_reconciliation,
        **{
            reason: float(actual_reconciliation["reason_weights"][reason])
            for reason in RESERVE_REASONS
        },
        "positions": position_rows,
        "realized_pnl_by_ticker": {key: float(value) for key, value in sorted(state.realized_pnl.items())},
        "total_realized_pnl_usd": float(sum(state.realized_pnl.values())),
        "total_fees_usd": total_fees,
        "forward_fill_count": int(len(fills)),
        "pending_order_count": int(len(pending)),
        "review_only": True,
        "simulated_broker_ledger": True,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "human_approval_required_for_live_orders": True,
    }
    return output, pd.DataFrame(position_rows)


def update_equity_curve(
    *,
    path: Path,
    account: dict[str, Any],
    seed_account: dict[str, Any],
    as_of_date: pd.Timestamp,
) -> pd.DataFrame:
    curve = read_csv(path)
    rows = curve.to_dict("records") if not curve.empty else []
    if not rows:
        seed_date = clean_date(account.get("seed_as_of_date") or seed_account.get("as_of_date"))
        seed_equity = float(safe_float(account.get("seed_equity_usd"), safe_float(seed_account.get("equity_usd"), 0.0)))
        seed_cash = float(safe_float(seed_account.get("cash_usd"), 0.0))
        if seed_date and seed_date != as_of_date.date().isoformat() and seed_equity > 0:
            rows.append(
                {
                    "date": seed_date,
                    "equity_usd": seed_equity,
                    "cash_usd": seed_cash,
                    "cash_weight": seed_cash / seed_equity,
                    "stock_value_usd": seed_equity - seed_cash,
                    "position_count": int(safe_float(seed_account.get("position_count"), len(seed_account.get("positions") or []))),
                    "record_type": "SEED_ACCOUNT",
                }
            )
    current = {
        "date": as_of_date.date().isoformat(),
        "equity_usd": float(account["equity_usd"]),
        "cash_usd": float(account["cash_usd"]),
        "cash_weight": float(account["cash_weight"]),
        "stock_value_usd": float(account["stock_value_usd"]),
        "position_count": int(account["position_count"]),
        "record_type": "FORWARD_MARK",
    }
    existing = next((row for row in rows if clean_date(row.get("date")) == current["date"]), None)
    if existing is not None:
        prior_equity = float(safe_float(existing.get("equity_usd"), np.nan))
        if not math.isclose(prior_equity, current["equity_usd"], rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("same-date forward equity mark changed; refusing non-append mutation")
    else:
        rows.append(current)
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out = out.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="first").reset_index(drop=True)
    write_csv(path, out)
    return out


def forward_metrics(curve: pd.DataFrame) -> dict[str, Any]:
    if curve.empty:
        return {
            "observations": 0,
            "forward_return": None,
            "forward_max_drawdown": None,
            "forward_cagr": None,
            "cagr_status": "UNDERPOWERED",
        }
    values = pd.to_numeric(curve["equity_usd"], errors="coerce").dropna()
    dates = pd.to_datetime(curve.loc[values.index, "date"], errors="coerce")
    if values.empty:
        return {
            "observations": 0,
            "forward_return": None,
            "forward_max_drawdown": None,
            "forward_cagr": None,
            "cagr_status": "UNDERPOWERED",
        }
    running_peak = values.cummax()
    drawdown = values / running_peak - 1.0
    total_return = float(values.iloc[-1] / values.iloc[0] - 1.0) if values.iloc[0] > 0 else None
    elapsed_days = int((dates.iloc[-1] - dates.iloc[0]).days) if len(dates) > 1 else 0
    powered = len(values) >= 252 and elapsed_days >= 300
    cagr = None
    if powered and total_return is not None and values.iloc[0] > 0 and values.iloc[-1] > 0:
        cagr = float((values.iloc[-1] / values.iloc[0]) ** (365.25 / elapsed_days) - 1.0)
    return {
        "observations": int(len(values)),
        "start_date": dates.iloc[0].date().isoformat(),
        "end_date": dates.iloc[-1].date().isoformat(),
        "elapsed_days": elapsed_days,
        "forward_return": total_return,
        "forward_max_drawdown": float(drawdown.min()),
        "forward_cagr": cagr,
        "cagr_status": "MEASURED" if powered else "UNDERPOWERED",
        "historical_metric_replacement_allowed": False,
    }


def load_reusable_same_session_manifest(
    *,
    portfolio: str,
    portfolio_dir: Path,
    bootstrap_path: Path,
    target_path: Path,
    source_target_path: Path,
    lifecycle: SecurityLifecycleSnapshot,
    as_of_date: pd.Timestamp,
    cost_bps: float,
    max_fill_lag_days: int,
    suppress_new_orders: bool,
) -> dict[str, Any] | None:
    """Reuse an already-committed mark for the same market session.

    Provider caches can revise a close after the first exact-session mark was
    archived.  Re-marking the same date would mutate an append-only forward
    curve.  Reuse is therefore allowed only when the complete stored state and
    every non-price input still match; any mismatch fails closed before a state
    file is written.
    """

    requested_date = as_of_date.date().isoformat()
    manifest = read_json(portfolio_dir / "manifest.json")
    account = read_json(portfolio_dir / "account_state_latest.json")
    curve = read_csv(portfolio_dir / "equity_curve.csv")
    manifest_date = clean_date(manifest.get("as_of_date"))
    account_date = clean_date(account.get("as_of_date"))
    curve_dates = (
        pd.to_datetime(curve.get("date", pd.Series(dtype=str)), errors="coerce").dt.strftime("%Y-%m-%d")
        if not curve.empty
        else pd.Series(dtype=str)
    )
    curve_has_requested = bool((curve_dates == requested_date).any())

    if manifest_date != requested_date:
        if account_date == requested_date or curve_has_requested:
            raise ValueError(
                f"incomplete same-session paper state for {portfolio}; refusing recovery mutation"
            )
        return None

    errors: list[str] = []

    def require(condition: bool, reason: str) -> None:
        if not condition:
            errors.append(reason)

    target = normalized_target(target_path, portfolio, as_of_date)
    digest = target_hash(target)
    effective_date = target_effective_date(source_target_path, as_of_date)
    effective_text = effective_date.date().isoformat() if effective_date is not None else None
    require(str(manifest.get("schema_version") or "") == "daily-simulated-fill-ledger-manifest-v2", "manifest_schema")
    require(str(manifest.get("portfolio_kind") or "").lower() == portfolio, "manifest_portfolio")
    require(str(manifest.get("fill_mode") or "").lower() == "next_close", "fill_mode")
    require(manifest.get("integer_shares") is True, "integer_shares")
    require(manifest.get("review_only") is True, "manifest_review_only")
    require(manifest.get("live_trading_enabled") is False, "manifest_live_trading")
    require(manifest.get("production_mutation_allowed") is False, "manifest_production_mutation")
    require(math.isclose(float(safe_float(manifest.get("cost_bps_per_side"), np.nan)), cost_bps, abs_tol=1e-9), "cost_bps")
    require(int(safe_float(manifest.get("max_fill_lag_days"), -1)) == int(max_fill_lag_days), "max_fill_lag_days")
    target_changed = bool(
        str(manifest.get("target_hash") or "") != digest
        or str(manifest.get("target_sha256") or "") != file_hash(target_path)
        or str(manifest.get("source_target_sha256") or "") != file_hash(source_target_path)
    )
    prior_suppressed = manifest.get("new_order_generation_suppressed") is True
    allow_suppressed_to_target_transition = bool(
        target_changed and prior_suppressed and not suppress_new_orders
    )
    if not allow_suppressed_to_target_transition:
        require(not target_changed, "target_identity")
    require(str(manifest.get("seed_account_sha256") or "") == file_hash(bootstrap_path), "seed_account_sha256")
    if not allow_suppressed_to_target_transition:
        require(manifest.get("target_effective_date") == effective_text, "target_effective_date")
        require(
            manifest.get("new_order_generation_suppressed") is suppress_new_orders,
            "new_order_generation_suppressed",
        )
    require(str(manifest.get("security_lifecycle_source_sha256") or "") == lifecycle.source_sha256, "security_lifecycle_source_sha256")
    require(str(manifest.get("security_lifecycle_snapshot_hash") or "") == lifecycle.snapshot_hash, "security_lifecycle_snapshot_hash")

    require(bool(account), "account_missing")
    require(account_date == requested_date, "account_as_of_date")
    require(str(account.get("portfolio_kind") or "").lower() == portfolio, "account_portfolio")
    require(account.get("review_only") is True, "account_review_only")
    require(account.get("live_trading_enabled") is False, "account_live_trading")
    require(account.get("production_mutation_allowed") is False, "account_production_mutation")

    matching_curve = curve.loc[curve_dates == requested_date].copy() if not curve.empty else pd.DataFrame()
    require(len(matching_curve) == 1, "equity_curve_same_date_count")
    require(not curve_dates.empty and str(curve_dates.iloc[-1]) == requested_date, "equity_curve_latest_date")
    if len(matching_curve) == 1 and account:
        curve_row = matching_curve.iloc[0]
        for field in ("equity_usd", "cash_usd", "stock_value_usd"):
            require(
                math.isclose(
                    float(safe_float(curve_row.get(field), np.nan)),
                    float(safe_float(account.get(field), np.nan)),
                    rel_tol=1e-9,
                    abs_tol=1e-6,
                ),
                f"equity_curve_{field}",
            )
        require(
            int(safe_float(curve_row.get("position_count"), -1))
            == int(safe_float(account.get("position_count"), -2)),
            "equity_curve_position_count",
        )

    positions = read_csv(portfolio_dir / "positions_latest.csv")
    account_positions = account.get("positions") if isinstance(account.get("positions"), list) else []
    require(len(positions) == len(account_positions), "positions_row_count")
    require(len(account_positions) == int(safe_float(account.get("position_count"), -1)), "account_position_count")
    if account_positions:
        account_position_map = {
            clean_ticker(row.get("ticker")): float(safe_float(row.get("shares"), np.nan))
            for row in account_positions
            if isinstance(row, dict) and clean_ticker(row.get("ticker"))
        }
        stored_position_map = {
            clean_ticker(row.get("ticker")): float(safe_float(row.get("shares"), np.nan))
            for row in positions.to_dict("records")
            if clean_ticker(row.get("ticker"))
        }
        require(account_position_map.keys() == stored_position_map.keys(), "positions_tickers")
        require(
            all(
                math.isclose(account_position_map[ticker], stored_position_map[ticker], abs_tol=1e-9)
                for ticker in account_position_map.keys() & stored_position_map.keys()
            ),
            "positions_shares",
        )

    pending = read_csv(portfolio_dir / "pending_orders.csv")
    fills = read_csv(portfolio_dir / "fills.csv")
    rejections = read_csv(portfolio_dir / "rejections.csv")
    try:
        sequence, chain_hash, _client_ids = validate_event_chain(fills, rejections)
    except ValueError as exc:
        errors.append(f"event_chain:{exc}")
        sequence, chain_hash = -1, ""
    require(int(safe_float(manifest.get("pending_order_count"), -1)) == len(pending), "manifest_pending_count")
    require(int(safe_float(manifest.get("fill_count"), -1)) == len(fills), "manifest_fill_count")
    require(int(safe_float(manifest.get("rejection_count"), -1)) == len(rejections), "manifest_rejection_count")
    require(int(safe_float(manifest.get("event_sequence"), -1)) == sequence, "manifest_event_sequence")
    require(str(manifest.get("event_chain_hash") or "") == chain_hash, "manifest_event_chain_hash")
    require(int(safe_float(account.get("pending_order_count"), -1)) == len(pending), "account_pending_count")

    meta = read_json(portfolio_dir / "state_meta.json")
    require(clean_date(meta.get("as_of_date")) == requested_date, "state_meta_as_of_date")
    require(int(safe_float(meta.get("event_sequence"), -1)) == sequence, "state_meta_event_sequence")
    require(str(meta.get("event_chain_hash") or "") == chain_hash, "state_meta_event_chain_hash")
    require(int(safe_float(meta.get("pending_order_count"), -1)) == len(pending), "state_meta_pending_count")
    require(int(safe_float(meta.get("fill_count"), -1)) == len(fills), "state_meta_fill_count")
    require(int(safe_float(meta.get("rejection_count"), -1)) == len(rejections), "state_meta_rejection_count")

    if errors:
        raise ValueError(
            f"same-session paper ledger reuse validation failed for {portfolio}: {','.join(errors)}"
        )

    if allow_suppressed_to_target_transition:
        return None

    reused = dict(manifest)
    reused.update(
        {
            "seeded_this_run": False,
            "resolved_fills_this_run": 0,
            "resolved_rejections_this_run": 0,
            "enqueued_this_run": 0,
            "same_session_reused": True,
            "same_session_reuse_reason": "verified_first_exact_mark_preserved",
        }
    )
    return reused


def build_order_preview(
    *,
    account_path: Path,
    target_path: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio: str,
    as_of_date: pd.Timestamp,
    cost_bps: float,
    provider_symbol_overrides: dict[str, str] | None = None,
    reserve_mode: str = DEFAULT_CURRENT_PAPER_MODE,
) -> dict[str, Any]:
    return run_order_preview(
        SimpleNamespace(
            account_state=str(account_path),
            target=str(target_path),
            price_cache=str(price_cache),
            portfolio_kind=portfolio,
            output_dir=str(output_dir),
            as_of_date=as_of_date.date().isoformat(),
            target_date=as_of_date.date().isoformat(),
            cost_bps=float(cost_bps),
            limit_margin_pct=0.25,
            min_trade_usd=25.0,
            fractional_shares=False,
            provider_symbol_override=[
                f"{logical}={provider}"
                for logical, provider in sorted(
                    (provider_symbol_overrides or {}).items()
                )
            ],
            reserve_mode=reserve_mode,
        )
    )


def enqueue_preview_orders(
    *,
    portfolio: str,
    portfolio_dir: Path,
    preview_dir: Path,
    target: pd.DataFrame,
    target_digest: str,
    as_of_date: pd.Timestamp,
    meta: dict[str, Any],
    pending: pd.DataFrame,
    cost_bps: float,
) -> tuple[pd.DataFrame, dict[str, Any], int]:
    if not target_digest or target.empty:
        raise ValueError(f"empty target allocation for {portfolio}")
    if str(meta.get("last_enqueued_target_hash") or "") == target_digest:
        return pending, meta, 0
    if not pending.empty:
        pending_hashes = {str(value) for value in pending.get("target_hash", pd.Series(dtype=str)).tolist()}
        if target_digest in pending_hashes:
            return pending, meta, 0
        raise ValueError(f"unresolved pending target would be superseded for {portfolio}")

    orders = read_csv(preview_dir / "orders_preview.csv")
    manifest = read_json(preview_dir / "order_batch_manifest.json")
    batch_id = str(manifest.get("order_batch_id") or "")
    queued: list[dict[str, Any]] = []
    order_client_ids = [
        str(value) for value in orders.get("client_order_id", pd.Series(dtype=str)).fillna("").tolist()
        if str(value)
    ]
    if len(order_client_ids) != len(set(order_client_ids)):
        raise PaperLedgerIntegrityError("BLOCKED_INTEGRITY", f"duplicate preview client order id for {portfolio}")
    for priority, row in enumerate(orders.to_dict("records"), start=1):
        status = str(row.get("status") or "")
        quantity = float(safe_float(row.get("quantity"), 0.0))
        ticker = clean_ticker(row.get("ticker"))
        side = str(row.get("side") or "").upper()
        if status.startswith("blocked") or quantity <= 0 or not ticker or side not in {"BUY", "SELL"}:
            continue
        client_id = str(row.get("client_order_id") or "")
        if not client_id:
            raise ValueError(f"preview order missing client id for {portfolio}")
        sell_taxonomy, sell_taxonomy_reason = normalized_sell_taxonomy(row)
        queued.append(
            {
                "portfolio_kind": portfolio,
                "signal_date": as_of_date.date().isoformat(),
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "reference_price": float(safe_float(row.get("reference_price"), 0.0)),
                "target_weight": float(safe_float(row.get("target_weight"), 0.0)),
                "reason": str(row.get("reason") or "target_rebalance"),
                "sell_taxonomy": sell_taxonomy,
                "sell_taxonomy_reason": sell_taxonomy_reason,
                "fill_mode": "next_close",
                "cost_bps_per_side": float(cost_bps),
                "client_order_id": client_id,
                "idempotency_key": str(row.get("idempotency_key") or ""),
                "order_batch_id": batch_id,
                "target_hash": target_digest,
                "priority": priority,
                "pending_status": "PENDING_NEXT_CLOSE",
                "created_at_utc": utc_now(),
            }
        )
    meta = dict(meta)
    meta.update(
        {
            "last_enqueued_target_hash": target_digest,
            "last_enqueued_signal_date": as_of_date.date().isoformat(),
            "last_order_batch_id": batch_id,
            "last_enqueue_status": "QUEUED" if queued else "NOOP_MATCHED_TARGET",
            "last_enqueue_count": len(queued),
        }
    )
    if queued:
        queued_frame = pd.DataFrame(queued)
        pending_out = queued_frame if pending.empty else pd.concat([pending, queued_frame], ignore_index=True, sort=False)
    else:
        pending_out = pending
    write_csv(portfolio_dir / "pending_orders.csv", pending_out, PENDING_COLUMNS)
    return pending_out, meta, len(queued)


def run_portfolio(
    *,
    portfolio: str,
    state_root: Path,
    bootstrap_path: Path,
    target_path: Path,
    price_cache: Path,
    preview_root: Path,
    as_of_date: pd.Timestamp,
    cost_bps: float,
    max_fill_lag_days: int,
    lifecycle: SecurityLifecycleSnapshot,
    suppress_new_orders: bool,
    reserve_policy: ReserveAssetPolicy,
    reserve_mode_explicit: bool,
) -> dict[str, Any]:
    portfolio_dir = state_root / portfolio
    portfolio_dir.mkdir(parents=True, exist_ok=True)
    validate_restored_snapshot(portfolio_dir, portfolio)
    source_target_path = target_path
    target_path, _adjusted_target = materialize_lifecycle_adjusted_target(
        source_target_path=source_target_path,
        output_path=portfolio_dir / "effective_target_latest.csv",
        portfolio=portfolio,
        as_of_date=as_of_date,
        lifecycle=lifecycle,
        reserve_policy=reserve_policy,
        reserve_mode_explicit=reserve_mode_explicit,
    )
    reserve_reconciliation = reserve_reason_reconciliation(
        _adjusted_target,
        policy=reserve_policy,
        weight_col="target_weight",
    )
    reusable = load_reusable_same_session_manifest(
        portfolio=portfolio,
        portfolio_dir=portfolio_dir,
        bootstrap_path=bootstrap_path,
        target_path=target_path,
        source_target_path=source_target_path,
        lifecycle=lifecycle,
        as_of_date=as_of_date,
        cost_bps=cost_bps,
        max_fill_lag_days=max_fill_lag_days,
        suppress_new_orders=suppress_new_orders,
    )
    if reusable is not None:
        preview_dir = preview_root / portfolio
        required_preview_files = (
            "preview_metrics.json",
            "order_batch_manifest.json",
            "orders_preview.csv",
            "target_weights.csv",
        )
        missing_preview_files = [
            name for name in required_preview_files if not (preview_dir / name).is_file()
        ]
        if missing_preview_files and not suppress_new_orders:
            preview = build_order_preview(
                account_path=portfolio_dir / "account_state_latest.json",
                target_path=target_path,
                price_cache=price_cache,
                output_dir=preview_dir,
                portfolio=portfolio,
                as_of_date=as_of_date,
                cost_bps=cost_bps,
                provider_symbol_overrides=lifecycle.provider_symbol_overrides,
                reserve_mode=reserve_policy.mode,
            )
            if preview.get("status") != "completed":
                raise ValueError(
                    f"same-session paper account preview failed for {portfolio}: "
                    f"{preview.get('reason')}"
                )
        reusable["same_session_preview_rebuilt"] = bool(missing_preview_files)
        reusable["same_session_preview_missing_before_rebuild"] = missing_preview_files
        reusable["result_status"] = "PREVIEW_REBUILT" if missing_preview_files else "SAME_SESSION_REUSE"
        return reusable
    account, state, seeded = load_or_seed_account(
        portfolio_dir=portfolio_dir,
        bootstrap_path=bootstrap_path,
        portfolio=portfolio,
        as_of_date=as_of_date,
        cost_bps=cost_bps,
    )
    seed_account = read_json(bootstrap_path)
    pending = read_csv(portfolio_dir / "pending_orders.csv")
    fills = read_csv(portfolio_dir / "fills.csv")
    rejections = read_csv(portfolio_dir / "rejections.csv")
    meta = read_json(portfolio_dir / "state_meta.json")
    pending, fills, rejections, lifecycle_actions = apply_lifecycle_actions(
        portfolio=portfolio,
        state=state,
        pending=pending,
        fills=fills,
        rejections=rejections,
        lifecycle=lifecycle,
        as_of_date=as_of_date,
        cost_bps=cost_bps,
    )
    target_for_close = normalized_target(target_path, portfolio, as_of_date)
    required_close_tickers = set(state.shares)
    required_close_tickers.update(target_for_close.get("ticker", pd.Series(dtype=str)).tolist())
    required_close_tickers.update(pending.get("ticker", pd.Series(dtype=str)).tolist())
    require_exact_session_closes(
        price_cache=price_cache,
        tickers=required_close_tickers,
        as_of_date=as_of_date,
        context=f"{portfolio} held/target/pending",
        provider_symbol_overrides=lifecycle.provider_symbol_overrides,
    )

    pending, fills, rejections, resolved = resolve_pending_orders(
        portfolio=portfolio,
        state=state,
        pending=pending,
        fills=fills,
        rejections=rejections,
        price_cache=price_cache,
        as_of_date=as_of_date,
        cost_bps=cost_bps,
        max_fill_lag_days=max_fill_lag_days,
        provider_symbol_overrides=lifecycle.provider_symbol_overrides,
    )
    write_csv(portfolio_dir / "pending_orders.csv", pending, PENDING_COLUMNS)
    write_csv(portfolio_dir / "fills.csv", fills)
    write_csv(portfolio_dir / "rejections.csv", rejections)

    marked_account, positions = mark_account(
        account=account,
        state=state,
        portfolio=portfolio,
        as_of_date=as_of_date,
        price_cache=price_cache,
        fills=fills,
        pending=pending,
        cost_bps=cost_bps,
        seed_path=bootstrap_path,
        provider_symbol_overrides=lifecycle.provider_symbol_overrides,
        reserve_policy=reserve_policy,
        reserve_reconciliation=reserve_reconciliation,
    )
    account_path = portfolio_dir / "account_state_latest.json"
    write_json(account_path, marked_account)
    write_csv(portfolio_dir / "positions_latest.csv", positions)

    preview_dir = preview_root / portfolio
    target = normalized_target(target_path, portfolio, as_of_date)
    digest = target_hash(target)
    effective_date = target_effective_date(source_target_path, as_of_date)
    seed_date = pd.to_datetime(account.get("seed_as_of_date") or account.get("as_of_date"), errors="coerce")
    if (
        seeded
        and not meta.get("last_enqueued_target_hash")
        and effective_date is not None
        and pd.notna(seed_date)
        and effective_date <= pd.Timestamp(seed_date).normalize()
    ):
        meta.update(
            {
                "last_enqueued_target_hash": digest,
                "last_enqueued_signal_date": pd.Timestamp(seed_date).date().isoformat(),
                "last_order_batch_id": "",
                "last_enqueue_status": "BOOTSTRAP_TARGET_ASSUMED_APPLIED",
                "last_enqueue_count": 0,
            }
        )
    if suppress_new_orders:
        enqueued = 0
        meta.update(
            {
                "last_enqueue_status": "SUPPRESSED_PENDING_SAME_CLOSE_SELECTOR",
                "last_enqueue_count": 0,
            }
        )
    else:
        preview = build_order_preview(
            account_path=account_path,
            target_path=target_path,
            price_cache=price_cache,
            output_dir=preview_dir,
            portfolio=portfolio,
            as_of_date=as_of_date,
            cost_bps=cost_bps,
            provider_symbol_overrides=lifecycle.provider_symbol_overrides,
            reserve_mode=reserve_policy.mode,
        )
        if preview.get("status") != "completed":
            raise ValueError(f"paper account preview failed for {portfolio}: {preview.get('reason')}")
        pending, meta, enqueued = enqueue_preview_orders(
            portfolio=portfolio,
            portfolio_dir=portfolio_dir,
            preview_dir=preview_dir,
            target=target,
            target_digest=digest,
            as_of_date=as_of_date,
            meta=meta,
            pending=pending,
            cost_bps=cost_bps,
        )
    marked_account["pending_order_count"] = int(len(pending))
    write_json(account_path, marked_account)
    curve = update_equity_curve(
        path=portfolio_dir / "equity_curve.csv",
        account=marked_account,
        seed_account=seed_account or account,
        as_of_date=as_of_date,
    )
    sequence, chain_hash, _client_ids = validate_event_chain(fills, rejections)
    metrics = forward_metrics(curve)
    meta.update(
        {
            "schema_version": "daily-simulated-fill-ledger-state-v2",
            "portfolio_kind": portfolio,
            "as_of_date": as_of_date.date().isoformat(),
            "event_sequence": sequence,
            "event_chain_hash": chain_hash,
            "pending_order_count": int(len(pending)),
            "fill_count": int(len(fills)),
            "rejection_count": int(len(rejections)),
            "security_lifecycle_snapshot_hash": lifecycle.snapshot_hash,
            "review_only": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
            "updated_at_utc": utc_now(),
        }
    )
    write_json(portfolio_dir / "state_meta.json", meta)
    manifest = {
        "schema_version": "daily-simulated-fill-ledger-manifest-v2",
        "portfolio_kind": portfolio,
        "as_of_date": as_of_date.date().isoformat(),
        "seeded_this_run": seeded,
        "fill_mode": "next_close",
        "cost_bps_per_side": float(cost_bps),
        "integer_shares": True,
        "max_fill_lag_days": int(max_fill_lag_days),
        "target_hash": digest,
        "target_effective_date": effective_date.date().isoformat() if effective_date is not None else None,
        "target_sha256": file_hash(target_path),
        "source_target_sha256": file_hash(source_target_path),
        "seed_account_sha256": file_hash(bootstrap_path),
        "security_lifecycle_schema_version": "run287-security-lifecycle-v1",
        "security_lifecycle_source_sha256": lifecycle.source_sha256,
        "security_lifecycle_snapshot_hash": lifecycle.snapshot_hash,
        "security_lifecycle_terminal_tickers": sorted(lifecycle.terminal_tickers),
        "security_lifecycle_actions": lifecycle_actions,
        "reserve_asset_policy": reserve_policy.audit(),
        "reserve_reason_reconciliation": reserve_reconciliation,
        "event_sequence": sequence,
        "event_chain_hash": chain_hash,
        "resolved_fills_this_run": resolved["resolved_fills"],
        "resolved_rejections_this_run": resolved["resolved_rejections"],
        "enqueued_this_run": enqueued,
        "new_order_generation_suppressed": bool(suppress_new_orders),
        "pending_order_count": int(len(pending)),
        "fill_count": int(len(fills)),
        "rejection_count": int(len(rejections)),
        "forward_metrics": metrics,
        "review_only": True,
        "simulated": True,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "historical_cagr_mdd_replacement_allowed": False,
        "result_status": "GENESIS" if seeded else "RESTORED_CONTINUATION",
    }
    write_json(portfolio_dir / "manifest.json", manifest)
    return manifest


def run(args: argparse.Namespace) -> dict[str, Any]:
    state_root = repo_path(args.state_dir)
    price_cache = repo_path(args.price_cache)
    preview_root = repo_path(args.order_preview_root)
    as_of_date = pd.Timestamp(args.as_of_date).normalize()
    suppress_new_orders = bool(getattr(args, "suppress_new_orders", False))
    reserve_mode_raw = str(getattr(args, "reserve_mode", "") or "").strip()
    reserve_mode_explicit = bool(reserve_mode_raw)
    reserve_policy = resolve_reserve_asset_policy(
        reserve_mode_raw or DEFAULT_CURRENT_PAPER_MODE,
        context="current_paper",
    )
    if pd.isna(as_of_date):
        raise ValueError("--as-of-date must be a completed market date")
    state_root.parent.mkdir(parents=True, exist_ok=True)
    preview_root.parent.mkdir(parents=True, exist_ok=True)
    journal_path = state_root.parent / f".{state_root.name}.transaction.json"
    recover_interrupted_publish(journal_path)
    prior_integrity = (
        verify_integrity_manifest(state_root, require=True)
        if (state_root / INTEGRITY_FILE).is_file()
        else {"status": "LEGACY_UNATTESTED", "snapshot_hash": ""}
    )
    stage_state = clone_directory(state_root, state_root.parent, f".{state_root.name}.candidate-")
    stage_preview = clone_directory(preview_root, preview_root.parent, f".{preview_root.name}.candidate-")
    bootstrap_paths = {
        portfolio: repo_path(getattr(args, f"{portfolio}_bootstrap_account")) for portfolio in PORTFOLIOS
    }
    target_paths = {portfolio: repo_path(getattr(args, f"{portfolio}_target")) for portfolio in PORTFOLIOS}
    failpoint = str(getattr(args, "transaction_failpoint", "") or "")
    try:
        active_tickers: set[str] = set()
        for portfolio in PORTFOLIOS:
            active_tickers.update(
                normalized_target(target_paths[portfolio], portfolio, as_of_date)
                .get("ticker", pd.Series(dtype=str))
                .map(clean_ticker)
                .tolist()
            )
            account = read_json(stage_state / portfolio / "account_state_latest.json")
            if not account:
                account = read_json(bootstrap_paths[portfolio])
            active_tickers.update(state_from_account(account).shares)
            active_tickers.update(
                read_csv(stage_state / portfolio / "pending_orders.csv")
                .get("ticker", pd.Series(dtype=str))
                .map(clean_ticker)
                .tolist()
            )
        if reserve_policy.tradeable:
            active_tickers.add(reserve_policy.asset_ticker)
        lifecycle_value = str(
            getattr(args, "security_lifecycle_events", "") or ""
        ).strip()
        lifecycle_path = repo_path(lifecycle_value) if lifecycle_value else None
        decision_time = pd.to_datetime(
            getattr(args, "decision_time_utc", ""), errors="coerce", utc=True
        )
        if pd.isna(decision_time):
            raise ValueError(
                "--decision-time-utc is required and must be timezone-aware"
            )
        lifecycle = resolve_security_lifecycle(
            lifecycle_path,
            session_date=as_of_date,
            decision_time_utc=pd.Timestamp(decision_time),
            active_tickers=active_tickers,
        )
        identity = ensure_genesis_identity(
            state_root=stage_state,
            bootstrap_paths=bootstrap_paths,
            target_paths=target_paths,
            cost_bps=float(args.cost_bps),
            max_fill_lag_days=int(args.max_fill_lag_days),
        )
        results: dict[str, Any] = {}
        for portfolio in PORTFOLIOS:
            results[portfolio] = run_portfolio(
                portfolio=portfolio,
                state_root=stage_state,
                bootstrap_path=bootstrap_paths[portfolio],
                target_path=target_paths[portfolio],
                price_cache=price_cache,
                preview_root=stage_preview,
                as_of_date=as_of_date,
                cost_bps=float(args.cost_bps),
                max_fill_lag_days=int(args.max_fill_lag_days),
                lifecycle=lifecycle,
                suppress_new_orders=suppress_new_orders,
                reserve_policy=reserve_policy,
                reserve_mode_explicit=reserve_mode_explicit,
            )
        same_session_count = sum(
            1 for payload in results.values() if payload.get("same_session_reused") is True
        )
        preview_rebuilt_count = sum(
            1 for payload in results.values() if payload.get("same_session_preview_rebuilt") is True
        )
        summary = {
            "schema_version": "daily-simulated-fill-ledger-summary-v1",
            "status": "completed",
            "result_status": (
                "PREVIEW_REBUILT" if preview_rebuilt_count else
                "SAME_SESSION_REUSE" if same_session_count == len(PORTFOLIOS) else
                "GENESIS" if all(payload.get("result_status") == "GENESIS" for payload in results.values()) else
                "RESTORED_CONTINUATION"
            ),
            "as_of_date": as_of_date.date().isoformat(),
            "portfolios": results,
            "genesis_identity_hash": identity["genesis_identity_hash"],
            "security_lifecycle": lifecycle.audit(),
            "reserve_asset_policy": reserve_policy.audit(),
            "review_only": True,
            "simulated": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
            "historical_cagr_mdd_replacement_allowed": False,
            "same_session_reused_portfolio_count": same_session_count,
            "same_session_preview_rebuilt_portfolio_count": preview_rebuilt_count,
            "new_order_generation_suppressed": suppress_new_orders,
            "generated_at_utc": utc_now(),
        }
        if same_session_count == len(PORTFOLIOS):
            # The committed ledger, including its root summary and checksum,
            # remains byte-identical.  Missing review-only previews may be
            # reconstructed independently from the frozen account mark.
            if directory_hashes(stage_preview) != directory_hashes(preview_root):
                preview_journal = preview_root.parent / f".{preview_root.name}.preview-transaction.json"
                atomic_publish_bundle(
                    [(stage_preview, preview_root)],
                    journal_path=preview_journal,
                    failpoint=failpoint,
                )
            return summary

        write_json(stage_state / "summary.json", summary)
        write_integrity_manifest(
            stage_state,
            as_of_date=as_of_date.date().isoformat(),
            previous_snapshot_hash=str(prior_integrity.get("snapshot_hash") or ""),
        )
        verify_integrity_manifest(stage_state, require=True)
        atomic_publish_bundle(
            [(stage_preview, preview_root), (stage_state, state_root)],
            journal_path=journal_path,
            validators=[lambda: verify_integrity_manifest(state_root, require=True)],
            failpoint=failpoint,
        )
        return summary
    finally:
        for candidate in (stage_state, stage_preview):
            if candidate.is_dir():
                shutil.rmtree(candidate)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="outputs/daily_simulated_fill_ledger")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--order-preview-root", default="outputs/account_ledger_preview")
    parser.add_argument("--main-bootstrap-account", default="outputs/broker_replay/main/account_state_latest.json")
    parser.add_argument("--concentrated-bootstrap-account", default="outputs/broker_replay/concentrated/account_state_latest.json")
    parser.add_argument("--main-target", default="outputs/reports/operating_main_target_book.csv")
    parser.add_argument("--concentrated-target", default="outputs/reports/operating_concentrated_target_book.csv")
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument(
        "--security-lifecycle-events",
        default="data_static/run287_exact_packet/security_lifecycle_events.csv",
    )
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument(
        "--reserve-mode",
        choices=list(RESERVE_MODES),
        default="",
        help=f"ReserveAssetPolicy mode; default {DEFAULT_CURRENT_PAPER_MODE}.",
    )
    parser.add_argument(
        "--suppress-new-orders",
        action="store_true",
        help="Resolve prior pending orders and mark accounts, but create no new preview/order.",
    )
    return parser.parse_args()


def main() -> int:
    try:
        payload = run(parse_args())
    except Exception as exc:
        status = str(getattr(exc, "status", "BLOCKED_INTEGRITY"))
        print(json.dumps({"status": status, "reason": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 2
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
