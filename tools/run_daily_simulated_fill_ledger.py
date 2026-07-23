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
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


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
from tools.run_weekly_evaluation import (  # noqa: E402
    load_price_series,
    price_on_or_after,
    price_on_or_before,
    px_cache_name,
)
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
    RESERVE_REASON_SOURCE_HASH_FIELD,
    ReserveAssetPolicy,
    account_reserve_reason_reconciliation,
    apply_reserve_asset_to_targets,
    ensure_explicit_cash_row,
    reserve_reason_reconciliation,
    resolve_reserve_asset_policy,
)


PORTFOLIOS = ("main", "concentrated")
NYSE_CALENDAR = mcal.get_calendar("NYSE")
GENESIS_HASH = "0" * 64
EVENT_HASH_FIELDS = {"event_hash"}
PRICE_SOURCE_FIELDS = {
    "execution_price_source_path",
    "execution_price_source_sha256",
}
OPTIONAL_EVENT_FIELDS = {"execution_ticker", *PRICE_SOURCE_FIELDS}
PENDING_COLUMNS = [
    "portfolio_kind",
    "signal_date",
    "ticker",
    "execution_ticker",
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
EVENT_CHAIN_COLUMNS = {
    "event_sequence",
    "event_id",
    "event_type",
    "event_date",
    "event_reason",
    "previous_event_hash",
    "event_hash",
}
EVENT_SAFETY_COLUMNS = {
    "review_only",
    "simulated",
    "live_trading_enabled",
    "production_mutation_allowed",
}
FILL_COLUMNS = {
    "portfolio_kind",
    "date",
    "signal_date",
    "ticker",
    "execution_ticker",
    "side",
    "quantity",
    "requested_quantity",
    "fill_price",
    "gross_value",
    "fee_usd",
    "cash_delta",
    "cash_after",
    "shares_after",
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
    "execution_status",
    "record_type",
    *PRICE_SOURCE_FIELDS,
    *EVENT_SAFETY_COLUMNS,
    *EVENT_CHAIN_COLUMNS,
}
REJECTION_COLUMNS = {
    "portfolio_kind",
    "date",
    "signal_date",
    "ticker",
    "execution_ticker",
    "side",
    "requested_quantity",
    "target_weight",
    "sell_taxonomy",
    "sell_taxonomy_reason",
    "client_order_id",
    "idempotency_key",
    "order_batch_id",
    "target_hash",
    "execution_status",
    "fill_mode",
    "cost_bps_per_side",
    *EVENT_SAFETY_COLUMNS,
    *EVENT_CHAIN_COLUMNS,
}
PREVIEW_ORDER_COLUMNS = [
    "ticker",
    "ledger_ticker",
    "side",
    "quantity",
    "reference_price",
    "limit_price",
    "gross_value_usd",
    "estimated_fee_usd",
    "cash_impact_usd",
    "current_shares",
    "current_weight",
    "target_weight",
    "target_value_usd",
    "current_value_usd",
    "trade_value_delta_usd",
    "order_type",
    "time_in_force",
    "reason",
    "sell_taxonomy",
    "sell_taxonomy_reason",
    "status",
    "estimated_cash_after_usd",
    "client_order_id",
    "idempotency_key",
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def portable_path(path_like: str | Path) -> str:
    path = repo_path(path_like).resolve()
    try:
        return path.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


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
    target = target.copy()
    target["ticker"] = target["ticker"].map(clean_ticker)
    target["target_weight"] = pd.to_numeric(target["target_weight"], errors="coerce").fillna(0.0)
    target = target[(target["ticker"] != "") & (target["target_weight"] > 1e-12)].copy()
    return target.sort_values("ticker").reset_index(drop=True)


def target_hash(target: pd.DataFrame) -> str:
    rows = [
        {"ticker": str(row.ticker), "target_weight": round(float(row.target_weight), 12)}
        for row in target.itertuples(index=False)
    ]
    return canonical_hash({"schema": "run287-forward-target-v1", "rows": rows})


def target_reserve_reason_source_hash(target: pd.DataFrame) -> str:
    if RESERVE_REASON_SOURCE_HASH_FIELD not in target.columns:
        return ""
    values = {
        str(value).strip().lower()
        for value in target[RESERVE_REASON_SOURCE_HASH_FIELD].tolist()
        if str(value).strip().lower() not in {"", "nan", "none"}
    }
    if len(values) > 1:
        raise PaperLedgerIntegrityError(
            "BLOCKED_RESERVE_PROVENANCE",
            f"conflicting {RESERVE_REASON_SOURCE_HASH_FIELD} values",
        )
    return next(iter(values), "")


def target_effective_date(target_path: Path, as_of_date: pd.Timestamp) -> pd.Timestamp | None:
    raw = read_csv(target_path)
    if raw.empty or "rebalance_date" not in raw.columns:
        return None
    dates = pd.to_datetime(raw["rebalance_date"], errors="coerce").dropna().dt.normalize()
    eligible = dates[dates <= as_of_date]
    return pd.Timestamp(eligible.max()).normalize() if not eligible.empty else None


def target_contract_dates(target_path: Path, as_of_date: pd.Timestamp) -> tuple[str | None, str | None]:
    raw = read_csv(target_path)
    if raw.empty:
        return None, None
    selected = raw.copy()
    if "rebalance_date" in selected.columns:
        dates = pd.to_datetime(selected["rebalance_date"], errors="coerce").dt.normalize()
        eligible = dates[dates <= as_of_date]
        if not eligible.empty:
            selected = selected.loc[dates.eq(eligible.max())].copy()

    def unique_date(column: str) -> str | None:
        if column not in selected.columns:
            return None
        values = sorted({clean_date(value) for value in selected[column].tolist()} - {""})
        if len(values) > 1:
            raise PaperLedgerIntegrityError(
                "BLOCKED_PREVIEW_PARITY",
                f"conflicting {column} values in target source",
            )
        return values[0] if values else None

    effective = unique_date("target_effective_date")
    if effective is None:
        fallback = target_effective_date(target_path, as_of_date)
        effective = fallback.date().isoformat() if fallback is not None else None
    return effective, unique_date("order_eligible_close_date")


def preview_identity(
    *,
    preview_dir: Path,
    account_path: Path,
    effective_target_path: Path,
    source_target_path: Path,
    portfolio: str,
    as_of_date: pd.Timestamp,
    preview_mode: str,
) -> dict[str, Any]:
    effective_date, source_eligible_close = target_contract_dates(source_target_path, as_of_date)
    order_eligible_close = source_eligible_close if preview_mode == "EXECUTABLE_CANDIDATE" else None
    effective_target = normalized_target(effective_target_path, portfolio, as_of_date)
    identity = {
        "preview_identity_schema_version": "run287-paper-preview-identity-v1",
        "portfolio_kind": portfolio,
        "preview_mode": preview_mode,
        "as_of_date": as_of_date.date().isoformat(),
        "target_effective_date": effective_date,
        "order_eligible_close_date": order_eligible_close,
        "order_eligible_close_rule": (
            "EXACT_DATE_FROM_TARGET" if order_eligible_close else
            "NO_NEW_ORDER" if preview_mode == "NO_NEW_ORDER" else
            "FIRST_EXACT_SESSION_CLOSE_AFTER_SIGNAL_DATE"
        ),
        "source_order_eligible_close_date": source_eligible_close,
        "accepted_account_sha256": file_hash(account_path),
        "effective_target_sha256": file_hash(effective_target_path),
        "source_target_sha256": file_hash(source_target_path),
        "normalized_target_hash": target_hash(effective_target),
        RESERVE_REASON_SOURCE_HASH_FIELD: target_reserve_reason_source_hash(
            effective_target
        ),
        "orders_preview_sha256": file_hash(preview_dir / "orders_preview.csv"),
        "target_weights_sha256": file_hash(preview_dir / "target_weights.csv"),
    }
    identity["preview_identity_hash"] = canonical_hash(identity)
    return identity


def attest_preview_identity(
    *,
    preview_dir: Path,
    account_path: Path,
    effective_target_path: Path,
    source_target_path: Path,
    portfolio: str,
    as_of_date: pd.Timestamp,
    preview_mode: str,
) -> dict[str, Any]:
    identity = preview_identity(
        preview_dir=preview_dir,
        account_path=account_path,
        effective_target_path=effective_target_path,
        source_target_path=source_target_path,
        portfolio=portfolio,
        as_of_date=as_of_date,
        preview_mode=preview_mode,
    )
    orders = read_csv(preview_dir / "orders_preview.csv")
    client_ids = sorted(
        str(value)
        for value in orders.get("client_order_id", pd.Series(dtype=str)).fillna("").tolist()
        if str(value)
    )
    manifest_path = preview_dir / "order_batch_manifest.json"
    manifest = read_json(manifest_path)
    manifest.update(identity)
    manifest.update(
        {
            "schema_version": "account-ledger-preview-order-batch-v2",
            "portfolio_kind": portfolio,
            "order_count": int(len(orders)),
            "ready_order_count": int(
                orders.get("status", pd.Series(dtype=str)).astype(str).eq("ready").sum()
            ) if not orders.empty else 0,
            "client_order_ids": client_ids,
            "new_order_generation_suppressed": preview_mode == "NO_NEW_ORDER",
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
        }
    )
    if not manifest.get("order_batch_id"):
        manifest["order_batch_id"] = canonical_hash(
            {"preview_identity_hash": identity["preview_identity_hash"], "client_order_ids": client_ids}
        )
    write_json(manifest_path, manifest)

    metrics_path = preview_dir / "preview_metrics.json"
    metrics = read_json(metrics_path)
    metrics.update(identity)
    metrics.update(
        {
            "status": "completed",
            "schema_version": "account-ledger-preview-v2",
            "portfolio_kind": portfolio,
            "order_batch_id": manifest["order_batch_id"],
            "order_count": int(len(orders)),
            "ready_order_count": int(manifest["ready_order_count"]),
            "new_order_generation_suppressed": preview_mode == "NO_NEW_ORDER",
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
        }
    )
    write_json(metrics_path, metrics)
    return identity


def write_no_new_order_preview(
    *,
    preview_dir: Path,
    account_path: Path,
    effective_target_path: Path,
    source_target_path: Path,
    portfolio: str,
    as_of_date: pd.Timestamp,
) -> dict[str, Any]:
    preview_dir.mkdir(parents=True, exist_ok=True)
    target = normalized_target(effective_target_path, portfolio, as_of_date)
    write_csv(
        preview_dir / "target_weights.csv",
        target,
        ["ticker", "target_weight", RESERVE_REASON_SOURCE_HASH_FIELD],
    )
    write_csv(preview_dir / "orders_preview.csv", pd.DataFrame(), PREVIEW_ORDER_COLUMNS)
    write_json(preview_dir / "order_batch_manifest.json", {})
    write_json(
        preview_dir / "preview_metrics.json",
        {
            "preview_semantics": "explicit_no_new_order",
            "blocked_order_count": 0,
            "buy_count": 0,
            "sell_count": 0,
        },
    )
    identity = attest_preview_identity(
        preview_dir=preview_dir,
        account_path=account_path,
        effective_target_path=effective_target_path,
        source_target_path=source_target_path,
        portfolio=portfolio,
        as_of_date=as_of_date,
        preview_mode="NO_NEW_ORDER",
    )
    (preview_dir / "preview_report.md").write_text(
        "# NO_NEW_ORDER preview\n\nNo executable order was generated for this suppressed mark-only pass.\n",
        encoding="utf-8",
    )
    return identity


def preview_parity_errors(
    *,
    preview_dir: Path,
    account_path: Path,
    effective_target_path: Path,
    source_target_path: Path,
    portfolio: str,
    as_of_date: pd.Timestamp,
    preview_mode: str,
) -> list[str]:
    required = (
        "preview_metrics.json",
        "order_batch_manifest.json",
        "orders_preview.csv",
        "target_weights.csv",
    )
    missing = [name for name in required if not (preview_dir / name).is_file()]
    if missing:
        return [f"missing:{name}" for name in missing]
    expected = preview_identity(
        preview_dir=preview_dir,
        account_path=account_path,
        effective_target_path=effective_target_path,
        source_target_path=source_target_path,
        portfolio=portfolio,
        as_of_date=as_of_date,
        preview_mode=preview_mode,
    )
    manifest = read_json(preview_dir / "order_batch_manifest.json")
    metrics = read_json(preview_dir / "preview_metrics.json")
    errors: list[str] = []
    for key, value in expected.items():
        if manifest.get(key) != value:
            errors.append(f"manifest:{key}")
        if metrics.get(key) != value:
            errors.append(f"metrics:{key}")
    orders = read_csv(preview_dir / "orders_preview.csv")
    if preview_mode == "NO_NEW_ORDER" and not orders.empty:
        errors.append("no_new_order_has_executable_rows")
    return sorted(set(errors))


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
    if target.empty:
        raise PaperLedgerIntegrityError(
            "BLOCKED_TARGET_EVIDENCE",
            f"empty normalized target allocation:{portfolio}",
        )
    source_non_cash = target.loc[
        ~target["ticker"].isin({"CASH", "__CASH__"})
    ].copy()
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
    terminal_target_tickers = set(target["ticker"].astype(str).str.upper()) & set(
        lifecycle.terminal_tickers
    )
    adjusted = filter_terminal_tickers(target, lifecycle)
    non_cash = adjusted.loc[~adjusted["ticker"].isin({"CASH", "__CASH__"})]
    if not source_non_cash.empty and non_cash.empty:
        cash_columns = list(adjusted.columns if not adjusted.empty else target.columns)
        cash_row = {column: "" for column in cash_columns}
        cash_row.update(
            {
                "ticker": "CASH",
                "target_weight": 1.0,
                "lifecycle_forced_all_cash": True,
                "capacity_unallocated": 1.0,
            }
        )
        adjusted = pd.DataFrame([cash_row])
    adjusted = ensure_explicit_cash_row(adjusted, weight_col="target_weight")
    adjusted["reserve_asset_policy_schema"] = reserve_policy.audit()["schema_version"]
    adjusted["reserve_asset_mode"] = reserve_policy.mode
    adjusted["reserve_asset_ticker"] = reserve_policy.asset_ticker
    adjusted["reserve_asset_tradeable"] = reserve_policy.tradeable
    adjusted["reserve_reason_reconciled"] = True
    explicit_reason_fields = any(reason in adjusted.columns for reason in RESERVE_REASONS)
    for reason in RESERVE_REASONS:
        if reason not in adjusted.columns:
            adjusted[reason] = 0.0
        adjusted[reason] = pd.to_numeric(adjusted[reason], errors="coerce").fillna(0.0)
    reserve_names = {"CASH", "__CASH__"}
    if reserve_policy.tradeable:
        reserve_names.add(reserve_policy.asset_ticker)
    reserve_mask = adjusted["ticker"].astype(str).str.upper().isin(reserve_names)
    reserve_weight = float(adjusted.loc[reserve_mask, "target_weight"].sum())
    labeled_weight = float(
        sum(adjusted.loc[reserve_mask, reason].sum() for reason in RESERVE_REASONS)
    )
    unlabeled_reserve = reserve_weight - labeled_weight
    if unlabeled_reserve > 1e-10:
        reserve_rows = adjusted.index[reserve_mask].tolist()
        if not reserve_rows:
            raise PaperLedgerIntegrityError(
                "BLOCKED_RESERVE_PROVENANCE",
                "reserve weight has no materialized Reserve row",
            )
        unlabeled_reason = (
            "residual_cash" if explicit_reason_fields else "capacity_unallocated"
        )
        adjusted.loc[reserve_rows[0], unlabeled_reason] += unlabeled_reserve
    if terminal_target_tickers:
        adjusted = adjusted.drop(
            columns=[RESERVE_REASON_SOURCE_HASH_FIELD], errors="ignore"
        )
    reconciliation = reserve_reason_reconciliation(
        adjusted,
        policy=reserve_policy,
        weight_col="target_weight",
    )
    adjusted[RESERVE_REASON_SOURCE_HASH_FIELD] = reconciliation[
        RESERVE_REASON_SOURCE_HASH_FIELD
    ]
    rows = adjusted.rename(columns={"target_weight": "weight"}).copy()
    rows.insert(0, "rebalance_date", as_of_date.date().isoformat())
    columns = ["rebalance_date", "ticker", "weight"]
    columns.extend(
        column
        for column in [
            *RESERVE_REASONS,
            RESERVE_REASON_SOURCE_HASH_FIELD,
            "reserve_asset_policy_schema",
            "reserve_asset_mode",
            "reserve_asset_ticker",
            "reserve_asset_tradeable",
            "reserve_reason_reconciled",
        ]
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


def _blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"", "nan", "none", "null"}


def _strict_number(value: Any, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or _blank(value):
        raise ValueError(f"{label}:finite_number_required")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}:finite_number_required") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label}:finite_number_required")
    return number


def _strict_integer(value: Any, label: str, *, positive: bool = False) -> int:
    number = _strict_number(value, label)
    rounded = round(number)
    if not math.isclose(number, rounded, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"{label}:integer_required")
    integer = int(rounded)
    if positive and integer <= 0:
        raise ValueError(f"{label}:positive_integer_required")
    return integer


def _strict_bool(value: Any, label: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise ValueError(f"{label}:boolean_required")


def _valid_sha256_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _strict_date(value: Any, label: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"{label}:date_required")
    return pd.Timestamp(parsed).tz_localize(None).normalize()


def next_nyse_session_after(value: Any, *, label: str) -> pd.Timestamp:
    signal_date = _strict_date(value, label)
    signal_schedule = NYSE_CALENDAR.schedule(
        start_date=signal_date,
        end_date=signal_date,
    )
    if signal_schedule.empty:
        raise ValueError(f"{label}:not_nyse_session")
    start = signal_date + pd.Timedelta(days=1)
    schedule = NYSE_CALENDAR.schedule(
        start_date=start,
        end_date=start + pd.Timedelta(days=14),
    )
    if schedule.empty:
        raise ValueError(f"{label}:next_nyse_session_unavailable")
    return pd.Timestamp(schedule.index[0]).tz_localize(None).normalize()


def _strict_utc_timestamp(value: Any, label: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed) or _blank(value):
        raise ValueError(f"{label}:utc_timestamp_required")
    raw = pd.Timestamp(value)
    if raw.tzinfo is None:
        raise ValueError(f"{label}:timezone_required")
    return pd.Timestamp(parsed)


def _close_enough(left: Any, right: Any) -> bool:
    return math.isclose(
        float(left),
        float(right),
        rel_tol=1e-9,
        abs_tol=1e-6,
    )


def _require_frame_schema(
    frame: pd.DataFrame,
    *,
    required: set[str],
    allowed: set[str],
    label: str,
) -> None:
    if frame.empty:
        return
    columns = {str(column) for column in frame.columns}
    missing = sorted(required - columns)
    extra = sorted(columns - allowed)
    if missing or extra:
        raise ValueError(
            f"{label}:schema_mismatch:missing={missing}:extra={extra}"
        )


def _strict_bootstrap_state(
    *,
    bootstrap_path: Path,
    manifest: dict[str, Any],
    portfolio: str,
    account_date: pd.Timestamp,
    cost_bps: float,
) -> LedgerState:
    if not bootstrap_path.is_file():
        raise ValueError("bootstrap_account_missing")
    if (
        not _valid_sha256_text(manifest.get("seed_account_sha256"))
        or file_hash(bootstrap_path) != str(manifest.get("seed_account_sha256"))
    ):
        raise ValueError("bootstrap_account_hash_mismatch")
    bootstrap = read_json(bootstrap_path)
    validate_seed_account(
        bootstrap,
        portfolio,
        account_date,
        cost_bps,
    )
    cash = _strict_number(bootstrap.get("cash_usd"), "bootstrap.cash_usd")
    if cash < -1e-8:
        raise ValueError("bootstrap.cash_usd:negative")
    positions = (
        bootstrap.get("positions")
        if isinstance(bootstrap.get("positions"), list)
        else []
    )
    shares: dict[str, float] = {}
    basis: dict[str, float] = {}
    for index, row in enumerate(positions):
        if not isinstance(row, dict):
            raise ValueError(f"bootstrap.positions[{index}]:object_required")
        ticker = clean_ticker(row.get("ticker"))
        if not ticker or ticker in shares:
            raise ValueError(
                f"bootstrap.positions[{index}]:ticker_missing_or_duplicate"
            )
        quantity = _strict_integer(
            row.get("shares"),
            f"bootstrap.positions[{index}].shares",
            positive=True,
        )
        cost_basis = _strict_number(
            row.get("cost_basis", row.get("price")),
            f"bootstrap.positions[{index}].cost_basis",
        )
        if cost_basis <= 0:
            raise ValueError(
                f"bootstrap.positions[{index}].cost_basis:positive_required"
            )
        shares[ticker] = float(quantity)
        basis[ticker] = cost_basis
    realized_payload = (
        bootstrap.get("realized_pnl_by_ticker")
        if isinstance(bootstrap.get("realized_pnl_by_ticker"), dict)
        else {}
    )
    realized: dict[str, float] = {}
    for raw_ticker, raw_value in realized_payload.items():
        ticker = clean_ticker(raw_ticker)
        if not ticker or ticker in realized:
            raise ValueError("bootstrap.realized_pnl:ticker_missing_or_duplicate")
        realized[ticker] = _strict_number(
            raw_value, f"bootstrap.realized_pnl.{ticker}"
        )
    return LedgerState(
        cash=cash,
        shares=shares,
        cost_basis=basis,
        realized_pnl=realized,
    )


def _validate_pending_rows(
    *,
    pending: pd.DataFrame,
    manifest: dict[str, Any],
    meta: dict[str, Any],
    portfolio: str,
    account_date: pd.Timestamp,
    cost_bps: float,
) -> None:
    _require_frame_schema(
        pending,
        required=set(PENDING_COLUMNS),
        allowed=set(PENDING_COLUMNS),
        label="pending",
    )
    client_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    priorities: set[int] = set()
    batch_ids: set[str] = set()
    for index, row in enumerate(pending.to_dict("records")):
        label = f"pending[{index}]"
        if str(row.get("portfolio_kind") or "").strip().lower() != portfolio:
            raise ValueError(f"{label}:portfolio_kind")
        signal_date = _strict_date(row.get("signal_date"), f"{label}.signal_date")
        if signal_date > account_date:
            raise ValueError(f"{label}:future_signal_date")
        ticker = clean_ticker(row.get("ticker"))
        execution_ticker = clean_ticker(row.get("execution_ticker"))
        if not ticker or not execution_ticker:
            raise ValueError(f"{label}:ticker_required")
        side = str(row.get("side") or "").strip().upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError(f"{label}:side_invalid")
        quantity = _strict_integer(
            row.get("quantity"), f"{label}.quantity", positive=True
        )
        if quantity <= 0:
            raise ValueError(f"{label}:quantity_invalid")
        reference_price = _strict_number(
            row.get("reference_price"), f"{label}.reference_price"
        )
        if reference_price <= 0:
            raise ValueError(f"{label}:reference_price_positive_required")
        target_weight = _strict_number(
            row.get("target_weight"), f"{label}.target_weight"
        )
        if target_weight < -1e-12 or target_weight > 1.0 + 1e-12:
            raise ValueError(f"{label}:target_weight_out_of_range")
        if not str(row.get("reason") or "").strip():
            raise ValueError(f"{label}:reason_required")
        sell_taxonomy, _taxonomy_reason = normalized_sell_taxonomy(row)
        if side == "BUY" and sell_taxonomy != "NOT_APPLICABLE":
            raise ValueError(f"{label}:buy_sell_taxonomy_invalid")
        if str(row.get("fill_mode") or "") != "next_close":
            raise ValueError(f"{label}:fill_mode_invalid")
        if not _close_enough(
            _strict_number(
                row.get("cost_bps_per_side"),
                f"{label}.cost_bps_per_side",
            ),
            cost_bps,
        ):
            raise ValueError(f"{label}:cost_bps_mismatch")
        client_id = str(row.get("client_order_id") or "").strip()
        idempotency_key = str(row.get("idempotency_key") or "").strip()
        batch_id = str(row.get("order_batch_id") or "").strip()
        if (
            not client_id
            or client_id in client_ids
            or not idempotency_key
            or idempotency_key in idempotency_keys
            or not batch_id
        ):
            raise ValueError(f"{label}:order_identity_invalid")
        client_ids.add(client_id)
        idempotency_keys.add(idempotency_key)
        batch_ids.add(batch_id)
        if (
            not _valid_sha256_text(row.get("target_hash"))
            or str(row.get("target_hash")) != str(manifest.get("target_hash"))
        ):
            raise ValueError(f"{label}:target_hash_mismatch")
        priority = _strict_integer(
            row.get("priority"), f"{label}.priority", positive=True
        )
        if priority in priorities:
            raise ValueError(f"{label}:priority_duplicate")
        priorities.add(priority)
        if str(row.get("pending_status") or "") != "PENDING_NEXT_CLOSE":
            raise ValueError(f"{label}:pending_status_invalid")
        _strict_utc_timestamp(
            row.get("created_at_utc"), f"{label}.created_at_utc"
        )
    if len(batch_ids) > 1:
        raise ValueError("pending:multiple_order_batches")
    if batch_ids and str(meta.get("last_order_batch_id") or "") not in batch_ids:
        raise ValueError("pending:state_meta_order_batch_mismatch")


def _validate_event_identity_and_safety(
    *,
    row: dict[str, Any],
    label: str,
    portfolio: str,
    account_date: pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    if str(row.get("portfolio_kind") or "").strip().lower() != portfolio:
        raise ValueError(f"{label}:portfolio_kind")
    event_date = _strict_date(row.get("date"), f"{label}.date")
    if event_date != _strict_date(row.get("event_date"), f"{label}.event_date"):
        raise ValueError(f"{label}:event_date_mismatch")
    signal_date = _strict_date(row.get("signal_date"), f"{label}.signal_date")
    if signal_date > event_date or event_date > account_date:
        raise ValueError(f"{label}:event_chronology_invalid")
    for field, expected in (
        ("review_only", True),
        ("simulated", True),
        ("live_trading_enabled", False),
        ("production_mutation_allowed", False),
    ):
        if _strict_bool(row.get(field), f"{label}.{field}") is not expected:
            raise ValueError(f"{label}:{field}_unsafe")
    for field in (
        "client_order_id",
        "idempotency_key",
        "order_batch_id",
        "event_id",
        "event_reason",
    ):
        if not str(row.get(field) or "").strip():
            raise ValueError(f"{label}:{field}_required")
    raw_previous = row.get("previous_event_hash")
    previous_text = "" if raw_previous is None else str(raw_previous)
    sequence = _strict_integer(
        row.get("event_sequence"), f"{label}.event_sequence", positive=True
    )
    if sequence == 1 and previous_text in {"0", "0.0"}:
        previous_text = GENESIS_HASH
    if (
        not _valid_sha256_text(previous_text)
        or not _valid_sha256_text(row.get("event_hash"))
    ):
        raise ValueError(f"{label}:event_hash_identity_invalid")
    if not _valid_sha256_text(row.get("target_hash")):
        raise ValueError(f"{label}:target_hash_invalid")
    target_weight = _strict_number(
        row.get("target_weight"), f"{label}.target_weight"
    )
    if target_weight < -1e-12 or target_weight > 1.0 + 1e-12:
        raise ValueError(f"{label}:target_weight_out_of_range")
    return signal_date, event_date


def _validate_execution_price_source(
    *,
    row: dict[str, Any],
    label: str,
    portfolio_dir: Path,
    signal_date: pd.Timestamp,
    event_date: pd.Timestamp,
    fill_price: float,
    max_fill_lag_days: int,
) -> str:
    event_id = str(row.get("event_id") or "").strip()
    client_order_id = str(row.get("client_order_id") or "").strip()
    ticker = clean_ticker(row.get("ticker"))
    execution_ticker = clean_ticker(row.get("execution_ticker"))
    expected_relative = (
        Path("execution_price_sources") / f"{event_id}.json"
    ).as_posix()
    relative = str(row.get("execution_price_source_path") or "").strip()
    expected_sha256 = str(
        row.get("execution_price_source_sha256") or ""
    ).strip()
    if relative != expected_relative:
        raise ValueError(f"{label}:execution_price_source_path_invalid")
    if (
        not _valid_sha256_text(expected_sha256)
        or expected_sha256 != expected_sha256.lower()
    ):
        raise ValueError(f"{label}:execution_price_source_sha256_invalid")
    source_path = portfolio_dir / Path(relative)
    try:
        source_path.resolve().relative_to(portfolio_dir.resolve())
    except ValueError as exc:
        raise ValueError(
            f"{label}:execution_price_source_path_escape"
        ) from exc
    if (
        not source_path.is_file()
        or source_path.is_symlink()
        or file_hash(source_path) != expected_sha256
    ):
        raise ValueError(f"{label}:execution_price_source_hash_mismatch")
    source = read_json(source_path)
    if set(source) != EXECUTION_PRICE_SOURCE_KEYS:
        raise ValueError(f"{label}:execution_price_source_schema_mismatch")
    if (
        source.get("schema_version") != EXECUTION_PRICE_SOURCE_SCHEMA
        or str(source.get("event_id") or "") != event_id
        or str(source.get("client_order_id") or "") != client_order_id
        or clean_ticker(source.get("ticker")) != ticker
        or clean_ticker(source.get("execution_ticker"))
        != execution_ticker
        or str(source.get("source_cache_file") or "")
        != px_cache_name(execution_ticker)
        or str(source.get("source_close_semantics") or "")
        != "adjusted_close_if_available_else_close"
    ):
        raise ValueError(f"{label}:execution_price_source_identity_mismatch")
    source_cache_sha256 = str(
        source.get("source_cache_sha256") or ""
    ).strip()
    if (
        not _valid_sha256_text(source_cache_sha256)
        or source_cache_sha256 != source_cache_sha256.lower()
        or _strict_integer(
            source.get("source_cache_size_bytes"),
            f"{label}.source_cache_size_bytes",
            positive=True,
        )
        <= 0
    ):
        raise ValueError(f"{label}:execution_price_cache_identity_invalid")
    source_signal_date = _strict_date(
        source.get("signal_date"), f"{label}.source_signal_date"
    )
    first_eligible_date = _strict_date(
        source.get("first_eligible_date"),
        f"{label}.source_first_eligible_date",
    )
    source_fill_date = _strict_date(
        source.get("fill_date"), f"{label}.source_fill_date"
    )
    captured_through = _strict_date(
        source.get("captured_through"), f"{label}.source_captured_through"
    )
    expected_first_eligible = next_nyse_session_after(
        signal_date,
        label=f"{label}.signal_date",
    )
    if (
        event_date != expected_first_eligible
        or source_signal_date != signal_date
        or first_eligible_date != expected_first_eligible
        or source_fill_date != event_date
        or captured_through != event_date
        or (event_date - signal_date).days
        > int(max_fill_lag_days)
    ):
        raise ValueError(f"{label}:execution_price_source_chronology_invalid")
    observations = source.get("observations")
    if (
        not isinstance(observations, list)
        or len(observations) != 1
        or not isinstance(observations[0], dict)
        or set(observations[0]) != {"date", "close"}
    ):
        raise ValueError(f"{label}:execution_price_observations_invalid")
    observed_date = _strict_date(
        observations[0].get("date"), f"{label}.source_observation_date"
    )
    observed_close = _strict_number(
        observations[0].get("close"), f"{label}.source_observation_close"
    )
    if (
        observed_date != event_date
        or observed_close <= 0
        or not _close_enough(observed_close, fill_price)
    ):
        raise ValueError(f"{label}:execution_price_exact_close_mismatch")
    return relative


def _validate_and_replay_events(
    *,
    fills: pd.DataFrame,
    rejections: pd.DataFrame,
    replay_state: LedgerState,
    manifest: dict[str, Any],
    portfolio_dir: Path,
    portfolio: str,
    account_date: pd.Timestamp,
    cost_bps: float,
    max_fill_lag_days: int,
) -> tuple[LedgerState, float]:
    _require_frame_schema(
        fills,
        required=FILL_COLUMNS,
        allowed=FILL_COLUMNS,
        label="fills",
    )
    _require_frame_schema(
        rejections,
        required=REJECTION_COLUMNS,
        allowed=REJECTION_COLUMNS,
        label="rejections",
    )
    if any(
        str(value) not in {"FILL", "LIFECYCLE_SETTLEMENT"}
        for value in fills.get("event_type", pd.Series(dtype=str)).tolist()
    ):
        raise ValueError("fills:event_type_invalid")
    if any(
        str(value) != "REJECTION"
        for value in rejections.get(
            "event_type", pd.Series(dtype=str)
        ).tolist()
    ):
        raise ValueError("rejections:event_type_invalid")
    total_fees = 0.0
    referenced_price_sources: set[str] = set()
    for row in combined_events(fills, rejections):
        sequence = _strict_integer(row.get("event_sequence"), "event.sequence")
        label = f"event[{sequence}]"
        signal_date, event_date = _validate_event_identity_and_safety(
            row=row,
            label=label,
            portfolio=portfolio,
            account_date=account_date,
        )
        event_type = str(row.get("event_type") or "")
        ticker = clean_ticker(row.get("ticker"))
        side = str(row.get("side") or "").strip().upper()
        requested = _strict_integer(
            row.get("requested_quantity"),
            f"{label}.requested_quantity",
            positive=True,
        )
        if event_type == "REJECTION":
            if not ticker or side not in {"BUY", "SELL"}:
                raise ValueError(f"{label}:rejection_order_domain_invalid")
            if str(row.get("execution_status") or "") != "SIMULATED_REJECTED":
                raise ValueError(f"{label}:rejection_status_invalid")
            fill_mode = str(row.get("fill_mode") or "")
            if fill_mode not in {"next_close", "lifecycle_cancel"}:
                raise ValueError(f"{label}:rejection_fill_mode_invalid")
            if not _close_enough(
                _strict_number(
                    row.get("cost_bps_per_side"),
                    f"{label}.cost_bps_per_side",
                ),
                cost_bps,
            ):
                raise ValueError(f"{label}:rejection_cost_mismatch")
            sell_taxonomy, _taxonomy_reason = normalized_sell_taxonomy(row)
            if side == "BUY" and sell_taxonomy != "NOT_APPLICABLE":
                raise ValueError(f"{label}:buy_sell_taxonomy_invalid")
            continue
        if event_type not in {"FILL", "LIFECYCLE_SETTLEMENT"}:
            raise ValueError(f"{label}:event_type_invalid")
        if not ticker:
            raise ValueError(f"{label}:ticker_required")
        execution_ticker = clean_ticker(row.get("execution_ticker"))
        if not execution_ticker:
            raise ValueError(f"{label}:execution_ticker_required")
        if not str(row.get("reason") or "").strip():
            raise ValueError(f"{label}:reason_required")
        quantity = _strict_integer(
            row.get("quantity"), f"{label}.quantity", positive=True
        )
        fill_price = _strict_number(
            row.get("fill_price"), f"{label}.fill_price"
        )
        if fill_price <= 0:
            raise ValueError(f"{label}:fill_price_positive_required")
        observed = {
            field: _strict_number(row.get(field), f"{label}.{field}")
            for field in (
                "gross_value",
                "fee_usd",
                "cash_delta",
                "cash_after",
                "shares_after",
            )
        }
        if observed["gross_value"] <= 0 or observed["fee_usd"] < 0:
            raise ValueError(f"{label}:fill_value_domain_invalid")
        if event_type == "FILL":
            if side not in {"BUY", "SELL"}:
                raise ValueError(f"{label}:side_invalid")
            if (
                str(row.get("fill_mode") or "") != "next_close"
                or str(row.get("record_type") or "") != "FORWARD_PAPER"
                or str(row.get("event_reason") or "")
                != "next_close_simulated_fill"
                or not _close_enough(
                    _strict_number(
                        row.get("cost_bps_per_side"),
                        f"{label}.cost_bps_per_side",
                    ),
                    cost_bps,
                )
            ):
                raise ValueError(f"{label}:fill_contract_invalid")
            sell_taxonomy, _taxonomy_reason = normalized_sell_taxonomy(row)
            if side == "BUY" and sell_taxonomy != "NOT_APPLICABLE":
                raise ValueError(f"{label}:buy_sell_taxonomy_invalid")
            source_relative = _validate_execution_price_source(
                row=row,
                label=label,
                portfolio_dir=portfolio_dir,
                signal_date=signal_date,
                event_date=event_date,
                fill_price=fill_price,
                max_fill_lag_days=max_fill_lag_days,
            )
            if source_relative in referenced_price_sources:
                raise ValueError(
                    f"{label}:execution_price_source_duplicate_reference"
                )
            referenced_price_sources.add(source_relative)
            expected = execute_order(
                state=replay_state,
                ticker=ticker,
                side=side,
                desired_qty=float(requested),
                price=fill_price,
                cost_bps=cost_bps,
                integer_shares=True,
            )
            if expected is None:
                raise ValueError(f"{label}:fill_not_executable_from_prior_state")
            expected_status = (
                "SIMULATED_FILL"
                if _close_enough(expected["quantity"], requested)
                else "SIMULATED_PARTIAL_FILL"
            )
            if str(row.get("execution_status") or "") != expected_status:
                raise ValueError(f"{label}:execution_status_mismatch")
            expected_values = {
                "quantity": expected["quantity"],
                "gross_value": expected["gross_value"],
                "fee_usd": expected["fee_usd"],
                "cash_delta": expected["cash_delta"],
                "cash_after": expected["cash_after"],
                "shares_after": expected["shares_after"],
            }
        else:
            if (
                side != "SETTLEMENT"
                or execution_ticker != ticker
                or str(row.get("fill_mode") or "")
                != "verified_lifecycle_proceeds"
                or str(row.get("record_type") or "")
                != "FORWARD_PAPER_LIFECYCLE"
                or str(row.get("execution_status") or "")
                != "SIMULATED_LIFECYCLE_SETTLEMENT"
                or not _close_enough(
                    _strict_number(
                        row.get("cost_bps_per_side"),
                        f"{label}.cost_bps_per_side",
                    ),
                    0.0,
                )
                or str(row.get("order_batch_id") or "") != "LIFECYCLE"
                or str(row.get("target_hash") or "")
                != str(manifest.get("security_lifecycle_snapshot_hash") or "")
            ):
                raise ValueError(f"{label}:lifecycle_fill_contract_invalid")
            held = float(replay_state.shares.get(ticker, 0.0))
            if (
                not _close_enough(held, quantity)
                or requested != quantity
                or not _close_enough(observed["fee_usd"], 0.0)
            ):
                raise ValueError(f"{label}:lifecycle_position_mismatch")
            gross = float(quantity) * fill_price
            basis = float(replay_state.cost_basis.get(ticker, fill_price))
            replay_state.cash += gross
            replay_state.realized_pnl[ticker] = float(
                replay_state.realized_pnl.get(ticker, 0.0)
                + quantity * (fill_price - basis)
            )
            replay_state.shares.pop(ticker, None)
            replay_state.cost_basis.pop(ticker, None)
            expected_values = {
                "quantity": float(quantity),
                "gross_value": gross,
                "fee_usd": 0.0,
                "cash_delta": gross,
                "cash_after": replay_state.cash,
                "shares_after": 0.0,
            }
        for field, expected_value in expected_values.items():
            actual_value = (
                float(quantity) if field == "quantity" else observed[field]
            )
            if not _close_enough(actual_value, expected_value):
                raise ValueError(f"{label}:{field}_mismatch")
        total_fees += observed["fee_usd"]
    source_root = portfolio_dir / "execution_price_sources"
    actual_price_sources: set[str] = set()
    if source_root.exists():
        if not source_root.is_dir() or source_root.is_symlink():
            raise ValueError("execution_price_sources:directory_required")
        for source_path in sorted(source_root.rglob("*")):
            if source_path.is_symlink() or not source_path.is_file():
                raise ValueError(
                    "execution_price_sources:non_regular_source"
                )
            actual_price_sources.add(
                source_path.relative_to(portfolio_dir).as_posix()
            )
    if actual_price_sources != referenced_price_sources:
        raise ValueError("execution_price_sources:reference_set_mismatch")
    return replay_state, total_fees


def _validate_final_state_parity(
    *,
    replay_state: LedgerState,
    total_fees: float,
    account: dict[str, Any],
    positions: pd.DataFrame,
    curve: pd.DataFrame,
    fills: pd.DataFrame,
    portfolio: str,
) -> None:
    account_cash = _strict_number(account.get("cash_usd"), "account.cash_usd")
    if account_cash < -1e-8 or not _close_enough(account_cash, replay_state.cash):
        raise ValueError("account.cash_usd:replay_mismatch")
    equity = _strict_number(account.get("equity_usd"), "account.equity_usd")
    if equity <= 0:
        raise ValueError("account.equity_usd:positive_required")
    if not isinstance(account.get("positions"), list):
        raise ValueError("account.positions:list_required")
    account_positions = account["positions"]
    account_date = _strict_date(account.get("as_of_date"), "account.as_of_date")
    account_by_ticker: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(account_positions):
        if not isinstance(row, dict):
            raise ValueError(f"account.positions[{index}]:object_required")
        if (
            _strict_date(
                row.get("as_of_date"),
                f"account.positions[{index}].as_of_date",
            )
            != account_date
        ):
            raise ValueError(
                f"account.positions[{index}].as_of_date:account_mismatch"
            )
        ticker = clean_ticker(row.get("ticker"))
        if not ticker or ticker in account_by_ticker:
            raise ValueError(
                f"account.positions[{index}]:ticker_missing_or_duplicate"
            )
        shares = _strict_integer(
            row.get("shares"),
            f"account.positions[{index}].shares",
            positive=True,
        )
        cost_basis = _strict_number(
            row.get("cost_basis"),
            f"account.positions[{index}].cost_basis",
        )
        if cost_basis <= 0:
            raise ValueError(
                f"account.positions[{index}].cost_basis:positive_required"
            )
        if (
            ticker not in replay_state.shares
            or not _close_enough(shares, replay_state.shares[ticker])
            or not _close_enough(
                cost_basis, replay_state.cost_basis.get(ticker, math.nan)
            )
        ):
            raise ValueError(f"account.positions[{index}]:replay_mismatch")
        account_by_ticker[ticker] = row
    if set(account_by_ticker) != set(replay_state.shares):
        raise ValueError("account.positions:replay_ticker_set_mismatch")
    account_realized_payload = account.get("realized_pnl_by_ticker")
    if not isinstance(account_realized_payload, dict):
        raise ValueError("account.realized_pnl:object_required")
    account_realized: dict[str, float] = {}
    for raw_ticker, value in account_realized_payload.items():
        ticker = clean_ticker(raw_ticker)
        if not ticker or ticker in account_realized:
            raise ValueError("account.realized_pnl:ticker_missing_or_duplicate")
        account_realized[ticker] = _strict_number(
            value, f"account.realized_pnl.{ticker}"
        )
    if set(account_realized) != set(replay_state.realized_pnl) or any(
        not _close_enough(
            account_realized[ticker], replay_state.realized_pnl[ticker]
        )
        for ticker in account_realized
    ):
        raise ValueError("account.realized_pnl:replay_mismatch")
    expected_fills = len(fills)
    if (
        not _close_enough(
            _strict_number(
                account.get("total_fees_usd"), "account.total_fees_usd"
            ),
            total_fees,
        )
        or _strict_integer(
            account.get("forward_fill_count"),
            "account.forward_fill_count",
        )
        != expected_fills
    ):
        raise ValueError("account.fill_totals:replay_mismatch")
    if "total_realized_pnl_usd" in account and not _close_enough(
        _strict_number(
            account.get("total_realized_pnl_usd"),
            "account.total_realized_pnl_usd",
        ),
        sum(replay_state.realized_pnl.values()),
    ):
        raise ValueError("account.total_realized_pnl_usd:replay_mismatch")

    if len(positions) != len(account_by_ticker):
        raise ValueError("positions_latest:row_count_mismatch")
    stored_by_ticker: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(positions.to_dict("records")):
        if (
            _strict_date(
                row.get("as_of_date"),
                f"positions_latest[{index}].as_of_date",
            )
            != account_date
        ):
            raise ValueError(
                f"positions_latest[{index}].as_of_date:account_mismatch"
            )
        ticker = clean_ticker(row.get("ticker"))
        if not ticker or ticker in stored_by_ticker:
            raise ValueError(
                f"positions_latest[{index}]:ticker_missing_or_duplicate"
            )
        stored_by_ticker[ticker] = row
    if set(stored_by_ticker) != set(account_by_ticker):
        raise ValueError("positions_latest:ticker_set_mismatch")
    market_value = 0.0
    reserve_market_value = 0.0
    for ticker, account_row in account_by_ticker.items():
        stored_row = stored_by_ticker[ticker]
        for field in (
            "shares",
            "price",
            "market_value_usd",
            "weight",
            "cost_basis",
            "unrealized_pnl_usd",
            "realized_pnl_usd",
        ):
            account_value = _strict_number(
                account_row.get(field), f"account.positions.{ticker}.{field}"
            )
            stored_value = _strict_number(
                stored_row.get(field), f"positions_latest.{ticker}.{field}"
            )
            if not _close_enough(account_value, stored_value):
                raise ValueError(
                    f"positions_latest.{ticker}.{field}:account_mismatch"
                )
        shares = _strict_number(
            account_row.get("shares"), f"account.positions.{ticker}.shares"
        )
        price = _strict_number(
            account_row.get("price"), f"account.positions.{ticker}.price"
        )
        value = _strict_number(
            account_row.get("market_value_usd"),
            f"account.positions.{ticker}.market_value_usd",
        )
        basis = _strict_number(
            account_row.get("cost_basis"),
            f"account.positions.{ticker}.cost_basis",
        )
        unrealized = _strict_number(
            account_row.get("unrealized_pnl_usd"),
            f"account.positions.{ticker}.unrealized_pnl_usd",
        )
        weight = _strict_number(
            account_row.get("weight"), f"account.positions.{ticker}.weight"
        )
        realized = _strict_number(
            account_row.get("realized_pnl_usd"),
            f"account.positions.{ticker}.realized_pnl_usd",
        )
        if (
            price <= 0
            or value <= 0
            or not _close_enough(value, shares * price)
            or not _close_enough(unrealized, value - shares * basis)
            or not _close_enough(weight, value / equity)
            or not _close_enough(
                realized, replay_state.realized_pnl.get(ticker, 0.0)
            )
        ):
            raise ValueError(f"account.positions.{ticker}:valuation_mismatch")
        is_reserve = _strict_bool(
            account_row.get("reserve_asset"),
            f"account.positions.{ticker}.reserve_asset",
        )
        stored_reserve = _strict_bool(
            stored_row.get("reserve_asset"),
            f"positions_latest.{ticker}.reserve_asset",
        )
        if is_reserve is not stored_reserve:
            raise ValueError(
                f"positions_latest.{ticker}.reserve_asset:account_mismatch"
            )
        if is_reserve:
            reserve_market_value += value
        else:
            market_value += value
    stock_value = _strict_number(
        account.get("stock_value_usd"), "account.stock_value_usd"
    )
    if (
        not _close_enough(stock_value, market_value)
        or not _close_enough(equity, account_cash + market_value + reserve_market_value)
    ):
        raise ValueError("account:equity_position_arithmetic_mismatch")
    reserve_value = account_cash + reserve_market_value
    if not _close_enough(
        _strict_number(
            account.get("reserve_asset_value_usd"),
            "account.reserve_asset_value_usd",
        ),
        reserve_market_value,
    ):
        raise ValueError("account.reserve_asset_value_usd:mismatch")
    if (
        not _close_enough(
            _strict_number(
                account.get("reserve_value_usd"),
                "account.reserve_value_usd",
            ),
            reserve_value,
        )
        or not _close_enough(
            _strict_number(account.get("cash_weight"), "account.cash_weight"),
            account_cash / equity,
        )
        or not _close_enough(
            _strict_number(
                account.get("reserve_weight"), "account.reserve_weight"
            ),
            reserve_value / equity,
        )
    ):
        raise ValueError("account:reserve_arithmetic_mismatch")
    reserve_count = sum(
        1
        for row in account_by_ticker.values()
        if _strict_bool(row.get("reserve_asset"), "account.reserve_asset")
    )
    equity_count = len(account_by_ticker) - reserve_count
    for field, expected in (
        ("position_count_total", len(account_by_ticker)),
        ("position_count", equity_count),
        ("equity_position_count", equity_count),
        ("reserve_position_count", reserve_count),
    ):
        if _strict_integer(account.get(field), f"account.{field}") != expected:
            raise ValueError(f"account.{field}:position_count_mismatch")
    if not curve.empty:
        curve_dates = pd.to_datetime(curve.get("date"), errors="coerce")
        if (
            curve_dates.isna().any()
            or curve_dates.duplicated().any()
            or not curve_dates.is_monotonic_increasing
            or pd.Timestamp(curve_dates.iloc[-1]).normalize() != account_date
        ):
            raise ValueError("equity_curve:date_sequence_invalid")
        last = curve.iloc[-1]
        for field in ("equity_usd", "cash_usd", "stock_value_usd"):
            if not _close_enough(
                _strict_number(last.get(field), f"equity_curve.{field}"),
                _strict_number(account.get(field), f"account.{field}"),
            ):
                raise ValueError(f"equity_curve.{field}:account_mismatch")
        for index, row in curve.iterrows():
            for field in ("equity_usd", "cash_usd", "stock_value_usd"):
                value = _strict_number(
                    row.get(field), f"equity_curve[{index}].{field}"
                )
                if field == "cash_usd" and value < -1e-8:
                    raise ValueError("equity_curve.cash_usd:negative")


def validate_restored_snapshot(
    portfolio_dir: Path,
    portfolio: str,
    *,
    bootstrap_path: Path | None = None,
) -> None:
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
    positions = read_csv(portfolio_dir / "positions_latest.csv")
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
    try:
        state_from_account(account)
        restored_date = _strict_date(
            account.get("as_of_date"), "account.as_of_date"
        )
        restored_cost_bps = _strict_number(
            manifest.get("cost_bps_per_side"),
            "manifest.cost_bps_per_side",
        )
        restored_max_fill_lag_days = _strict_integer(
            manifest.get("max_fill_lag_days"),
            "manifest.max_fill_lag_days",
            positive=True,
        )
        seed_path = (
            bootstrap_path
            if bootstrap_path is not None
            else portfolio_dir.parent
            / "bootstrap"
            / f"{portfolio}_account.json"
        )
        replay_state = _strict_bootstrap_state(
            bootstrap_path=seed_path,
            manifest=manifest,
            portfolio=portfolio,
            account_date=restored_date,
            cost_bps=restored_cost_bps,
        )
        _validate_pending_rows(
            pending=pending,
            manifest=manifest,
            meta=meta,
            portfolio=portfolio,
            account_date=restored_date,
            cost_bps=restored_cost_bps,
        )
        replay_state, total_fees = _validate_and_replay_events(
            fills=fills,
            rejections=rejections,
            replay_state=replay_state,
            manifest=manifest,
            portfolio_dir=portfolio_dir,
            portfolio=portfolio,
            account_date=restored_date,
            cost_bps=restored_cost_bps,
            max_fill_lag_days=restored_max_fill_lag_days,
        )
        _validate_final_state_parity(
            replay_state=replay_state,
            total_fees=total_fees,
            account=account,
            positions=positions,
            curve=curve,
            fills=fills,
            portfolio=portfolio,
        )
    except (TypeError, ValueError) as exc:
        errors.append(f"semantic_replay:{exc}")
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
        bootstrap_source = bootstrap_paths[portfolio]
        embedded_bootstrap = (
            state_root / "bootstrap" / f"{portfolio}_account.json"
        )
        if not bootstrap_source.is_file():
            raise FileNotFoundError(
                f"missing bootstrap account for {portfolio}"
            )
        embedded_bootstrap.parent.mkdir(parents=True, exist_ok=True)
        if embedded_bootstrap.is_file():
            if file_hash(embedded_bootstrap) != file_hash(bootstrap_source):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_INTEGRITY",
                    f"embedded bootstrap account changed:{portfolio}",
                )
        else:
            shutil.copy2(bootstrap_source, embedded_bootstrap)
        account = read_json(embedded_bootstrap)
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
            "bootstrap_account_sha256": file_hash(embedded_bootstrap),
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
    provider_symbol_links: dict[str, dict[str, str]] | None = None,
) -> dict[str, pd.DataFrame]:
    prices: dict[str, pd.DataFrame] = {}
    for ticker in sorted({clean_ticker(value) for value in tickers if clean_ticker(value)}):
        predecessor = load_price_series(price_cache, ticker)
        provider = (provider_symbol_overrides or {}).get(ticker, ticker)
        successor = load_price_series(price_cache, provider) if provider != ticker else pd.DataFrame()
        link = (provider_symbol_links or {}).get(ticker)
        if link and provider != ticker:
            last_trade = pd.to_datetime(link.get("last_trading_date"), errors="coerce")
            effective = pd.to_datetime(link.get("effective_date"), errors="coerce")
            if pd.isna(last_trade) or pd.isna(effective):
                raise PaperLedgerIntegrityError(
                    "BLOCKED_LIFECYCLE_EVIDENCE",
                    f"invalid provider symbol cutover:{ticker}",
                )
            before = predecessor.loc[
                pd.to_datetime(predecessor.index, errors="coerce").normalize()
                <= pd.Timestamp(last_trade).normalize()
            ].copy() if not predecessor.empty else predecessor
            after = successor.loc[
                pd.to_datetime(successor.index, errors="coerce").normalize()
                >= pd.Timestamp(effective).normalize()
            ].copy() if not successor.empty else successor
            frame = pd.concat([before, after]).sort_index()
            frame = frame.loc[~frame.index.duplicated(keep="last")]
        else:
            frame = predecessor
            if frame.empty and provider != ticker:
                frame = successor
        if not frame.empty:
            prices[ticker] = frame
    return prices


EXECUTION_PRICE_SOURCE_SCHEMA = "run287-paper-execution-price-source-v1"
EXECUTION_PRICE_SOURCE_KEYS = {
    "schema_version",
    "event_id",
    "client_order_id",
    "ticker",
    "execution_ticker",
    "signal_date",
    "first_eligible_date",
    "fill_date",
    "captured_through",
    "source_cache_file",
    "source_cache_sha256",
    "source_cache_size_bytes",
    "source_close_semantics",
    "observations",
}


def event_id_for(
    *,
    client_order_id: str,
    event_type: str,
    event_date: str,
    reason: str,
) -> str:
    return canonical_hash(
        {
            "client_order_id": client_order_id,
            "event_type": event_type,
            "event_date": event_date,
            "reason": reason,
        }
    )[:32]


def materialize_execution_price_source(
    *,
    portfolio_dir: Path,
    price_cache: Path,
    event_id: str,
    client_order_id: str,
    ticker: str,
    execution_ticker: str,
    signal_date: pd.Timestamp,
    fill_date: pd.Timestamp,
    fill_price: float,
) -> tuple[str, str]:
    """Freeze the exact execution-ticker close used by a forward fill.

    The external cache may later append or revise history.  A fill therefore
    carries a hash-chain reference to a canonical, point-in-time source record
    inside the durable paper snapshot.  The directory integrity manifest (and
    accepted publication manifest that binds it) transitively attests the
    frozen source record.
    """

    signal_date = pd.Timestamp(signal_date).tz_localize(None).normalize()
    fill_date = pd.Timestamp(fill_date).tz_localize(None).normalize()
    if fill_date <= signal_date:
        raise PaperLedgerIntegrityError(
            "BLOCKED_EXECUTION_PRICE_EVIDENCE",
            f"same-day or pre-signal fill source:{event_id}",
        )
    execution_ticker = clean_ticker(execution_ticker)
    ticker = clean_ticker(ticker)
    if not event_id or not client_order_id or not ticker or not execution_ticker:
        raise PaperLedgerIntegrityError(
            "BLOCKED_EXECUTION_PRICE_EVIDENCE",
            f"incomplete fill source identity:{event_id}",
        )
    source_cache_path = price_cache / px_cache_name(execution_ticker)
    if (
        not source_cache_path.is_file()
        or source_cache_path.is_symlink()
        or source_cache_path.stat().st_size <= 0
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_EXECUTION_PRICE_EVIDENCE",
            f"missing execution-ticker cache source:{execution_ticker}",
        )
    source = load_price_series(price_cache, execution_ticker)
    if source.empty or "close" not in source.columns:
        raise PaperLedgerIntegrityError(
            "BLOCKED_EXECUTION_PRICE_EVIDENCE",
            f"unreadable execution-ticker cache source:{execution_ticker}",
        )
    source = source.copy()
    source.index = pd.to_datetime(source.index, errors="coerce").tz_localize(
        None
    ).normalize()
    if source.index.isna().any() or source.index.duplicated().any():
        raise PaperLedgerIntegrityError(
            "BLOCKED_EXECUTION_PRICE_EVIDENCE",
            f"non-canonical execution-ticker cache dates:{execution_ticker}",
        )
    source = source.sort_index()
    first_eligible_date = next_nyse_session_after(
        signal_date,
        label="execution_price_source.signal_date",
    )
    if fill_date != first_eligible_date:
        raise PaperLedgerIntegrityError(
            "BLOCKED_EXECUTION_PRICE_EVIDENCE",
            f"fill is not the next NYSE session:{event_id}",
        )
    observed_date, observed_close = price_on_or_after(
        source, first_eligible_date, "close"
    )
    observed_date = (
        pd.Timestamp(observed_date).tz_localize(None).normalize()
        if observed_date is not None
        else None
    )
    if (
        observed_date != fill_date
        or observed_close is None
        or not math.isfinite(float(observed_close))
        or float(observed_close) <= 0
        or not _close_enough(float(observed_close), fill_price)
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_EXECUTION_PRICE_EVIDENCE",
            f"fill is not execution-ticker exact-next-close:{event_id}",
        )
    source_window = source.loc[source.index == fill_date, ["close"]]
    if len(source_window) != 1:
        raise PaperLedgerIntegrityError(
            "BLOCKED_EXECUTION_PRICE_EVIDENCE",
            f"ambiguous execution-ticker exact-next-close:{event_id}",
        )
    close = float(source_window.iloc[0]["close"])
    if not math.isfinite(close) or close <= 0:
        raise PaperLedgerIntegrityError(
            "BLOCKED_EXECUTION_PRICE_EVIDENCE",
            f"invalid execution-ticker exact-next-close:{event_id}",
        )
    payload = {
        "schema_version": EXECUTION_PRICE_SOURCE_SCHEMA,
        "event_id": event_id,
        "client_order_id": client_order_id,
        "ticker": ticker,
        "execution_ticker": execution_ticker,
        "signal_date": signal_date.date().isoformat(),
        "first_eligible_date": first_eligible_date.date().isoformat(),
        "fill_date": fill_date.date().isoformat(),
        "captured_through": fill_date.date().isoformat(),
        "source_cache_file": px_cache_name(execution_ticker),
        "source_cache_sha256": file_hash(source_cache_path),
        "source_cache_size_bytes": int(source_cache_path.stat().st_size),
        "source_close_semantics": "adjusted_close_if_available_else_close",
        "observations": [
            {
                "date": fill_date.date().isoformat(),
                "close": close,
            }
        ],
    }
    relative_path = Path("execution_price_sources") / f"{event_id}.json"
    destination = portfolio_dir / relative_path
    if destination.is_file():
        if read_json(destination) != payload:
            raise PaperLedgerIntegrityError(
                "BLOCKED_EXECUTION_PRICE_EVIDENCE",
                f"immutable execution price source changed:{event_id}",
            )
    else:
        write_json(destination, payload)
    return relative_path.as_posix(), file_hash(destination)


def require_exact_session_closes(
    *,
    price_cache: Path,
    tickers: set[str],
    as_of_date: pd.Timestamp,
    context: str,
    provider_symbol_overrides: dict[str, str] | None = None,
    provider_symbol_links: dict[str, dict[str, str]] | None = None,
) -> None:
    required = {clean_ticker(value) for value in tickers if clean_ticker(value) not in {"", "CASH", "USD"}}
    prices = load_prices(
        price_cache,
        required,
        provider_symbol_overrides,
        provider_symbol_links,
    )
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
    payload: dict[str, Any] = {}
    for key, value in row.items():
        if key in EVENT_HASH_FIELDS:
            continue
        if key in OPTIONAL_EVENT_FIELDS and (
            value is None
            or (isinstance(value, float) and np.isnan(value))
            or str(value).strip() == ""
        ):
            continue
        payload[str(key)] = value
    return payload


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
        raw_previous = row.get("previous_event_hash")
        observed_previous = (
            "" if raw_previous is None else str(raw_previous)
        )
        if sequence == 1 and observed_previous in {"0", "0.0"}:
            # pandas may infer an all-zero genesis hash column as numeric when
            # the ledger contains exactly one event.
            observed_previous = GENESIS_HASH
        if observed_previous != previous:
            raise ValueError("forward paper previous-event hash mismatch")
        normalized_row = dict(row)
        normalized_row["previous_event_hash"] = observed_previous
        expected = canonical_hash(event_payload_for_hash(normalized_row))
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
    event_id = event_id_for(
        client_order_id=client_order_id,
        event_type=event_type,
        event_date=event_date,
        reason=reason,
    )
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
            "execution_ticker": ticker,
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
            "execution_price_source_path": "",
            "execution_price_source_sha256": "",
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
            "execution_ticker": clean_ticker(row.get("execution_ticker")) or ticker,
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
    portfolio_dir: Path,
    state: LedgerState,
    pending: pd.DataFrame,
    fills: pd.DataFrame,
    rejections: pd.DataFrame,
    price_cache: Path,
    as_of_date: pd.Timestamp,
    cost_bps: float,
    max_fill_lag_days: int,
    provider_symbol_overrides: dict[str, str] | None = None,
    provider_symbol_links: dict[str, dict[str, str]] | None = None,
    terminal_fill_cutoffs: dict[str, pd.Timestamp] | None = None,
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
    prices = load_prices(
        price_cache,
        tickers,
        provider_symbol_overrides,
        provider_symbol_links,
    )

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
        try:
            target_date = next_nyse_session_after(
                signal_date,
                label=f"pending.{client_id}.signal_date",
            )
        except ValueError as exc:
            raise PaperLedgerIntegrityError(
                "BLOCKED_PENDING_ORDER_DATE",
                str(exc),
            ) from exc
        if target_date > as_of_date:
            keep_pending.append(row)
            continue
        actual_date, fill_px = price_on_or_after(
            prices.get(ticker, pd.DataFrame()),
            target_date,
            "close",
        )
        actual_date = pd.Timestamp(actual_date).normalize() if actual_date is not None else None
        terminal_cutoff = (terminal_fill_cutoffs or {}).get(ticker)
        if terminal_cutoff is not None and (
            target_date > pd.Timestamp(terminal_cutoff).normalize()
        ):
            keep_pending.append(row)
            continue
        if (
            actual_date is None
            or fill_px is None
            or actual_date != target_date
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_MISSING_EXACT_CLOSE",
                f"{ticker}:{target_date.date().isoformat()}",
            )
        if (actual_date - signal_date).days > int(max_fill_lag_days):
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
            "execution_ticker": clean_ticker(row.get("execution_ticker"))
            or clean_ticker(row.get("ticker")),
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
                "execution_ticker": clean_ticker(row.get("execution_ticker"))
                or clean_ticker(row.get("ticker")),
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
        execution_ticker = (
            clean_ticker(row.get("execution_ticker"))
            or clean_ticker(row.get("ticker"))
        )
        event_date_text = fill_date.date().isoformat()
        event_reason = "next_close_simulated_fill"
        event_id = event_id_for(
            client_order_id=client_id,
            event_type="FILL",
            event_date=event_date_text,
            reason=event_reason,
        )
        execution_price_source_path, execution_price_source_sha256 = (
            materialize_execution_price_source(
                portfolio_dir=portfolio_dir,
                price_cache=price_cache,
                event_id=event_id,
                client_order_id=client_id,
                ticker=clean_ticker(row.get("ticker")),
                execution_ticker=execution_ticker,
                signal_date=pd.Timestamp(row.get("signal_date")),
                fill_date=fill_date,
                fill_price=float(order.get("fill_price") or fill_px),
            )
        )
        payload = {
            "portfolio_kind": portfolio,
            "date": event_date_text,
            "signal_date": clean_date(row.get("signal_date")),
            "ticker": clean_ticker(row.get("ticker")),
            "execution_ticker": execution_ticker,
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
            "execution_price_source_path": execution_price_source_path,
            "execution_price_source_sha256":
                execution_price_source_sha256,
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
            event_date=event_date_text,
            reason=event_reason,
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
    provider_symbol_links: dict[str, dict[str, str]] | None = None,
    reserve_policy: ReserveAssetPolicy,
    reserve_reconciliation: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    prices = load_prices(
        price_cache,
        set(state.shares),
        provider_symbol_overrides,
        provider_symbol_links,
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
        "position_count_total": len(position_rows),
        "equity_position_count": sum(
            1 for row in position_rows if not row["reserve_asset"]
        ),
        "reserve_position_count": sum(
            1 for row in position_rows if row["reserve_asset"]
        ),
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
        RESERVE_REASON_SOURCE_HASH_FIELD: actual_reconciliation[
            RESERVE_REASON_SOURCE_HASH_FIELD
        ],
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
                    "position_count_total": int(
                        safe_float(
                            seed_account.get("position_count_total"),
                            len(seed_account.get("positions") or []),
                        )
                    ),
                    "equity_position_count": int(
                        safe_float(
                            seed_account.get("equity_position_count"),
                            seed_account.get("position_count"),
                        )
                    ),
                    "reserve_position_count": int(
                        safe_float(seed_account.get("reserve_position_count"), 0)
                    ),
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
        "position_count_total": int(account["position_count_total"]),
        "equity_position_count": int(account["equity_position_count"]),
        "reserve_position_count": int(account["reserve_position_count"]),
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

    def valid_sha256(value: Any) -> bool:
        text = str(value or "").strip().lower()
        return len(text) == 64 and all(character in "0123456789abcdef" for character in text)

    if not valid_sha256(lifecycle.source_sha256):
        raise PaperLedgerIntegrityError(
            "BLOCKED_LIFECYCLE_EVIDENCE",
            f"same-session reuse requires lifecycle source hash:{portfolio}",
        )
    if not valid_sha256(lifecycle.snapshot_hash):
        raise PaperLedgerIntegrityError(
            "BLOCKED_LIFECYCLE_EVIDENCE",
            f"same-session reuse requires lifecycle snapshot hash:{portfolio}",
        )
    if not valid_sha256(manifest.get("security_lifecycle_source_sha256")):
        raise PaperLedgerIntegrityError(
            "BLOCKED_LIFECYCLE_EVIDENCE",
            f"stored exact bundle lacks lifecycle source hash:{portfolio}",
        )
    if not valid_sha256(manifest.get("security_lifecycle_snapshot_hash")):
        raise PaperLedgerIntegrityError(
            "BLOCKED_LIFECYCLE_EVIDENCE",
            f"stored exact bundle lacks lifecycle snapshot hash:{portfolio}",
        )

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
    allow_target_to_suppressed_reuse = bool(
        not target_changed and not prior_suppressed and suppress_new_orders
    )
    if not allow_suppressed_to_target_transition:
        require(not target_changed, "target_identity")
    require(str(manifest.get("seed_account_sha256") or "") == file_hash(bootstrap_path), "seed_account_sha256")
    if not allow_suppressed_to_target_transition:
        require(manifest.get("target_effective_date") == effective_text, "target_effective_date")
    if not allow_suppressed_to_target_transition and not allow_target_to_suppressed_reuse:
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
    current_reserve_source_hash = target_reserve_reason_source_hash(
        normalized_target(target_path, portfolio, as_of_date)
    )
    require(bool(current_reserve_source_hash), "reserve_reason_source_hash_missing")
    stored_reserve_source_hash = str(
        manifest.get(RESERVE_REASON_SOURCE_HASH_FIELD) or ""
    )
    require(bool(stored_reserve_source_hash), "stored_reserve_reason_source_hash_missing")
    require(
        str(account.get(RESERVE_REASON_SOURCE_HASH_FIELD) or "")
        == stored_reserve_source_hash,
        "account_manifest_reserve_reason_source_hash",
    )
    if not allow_suppressed_to_target_transition:
        require(
            stored_reserve_source_hash == current_reserve_source_hash,
            "manifest_reserve_reason_source_hash",
        )

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
        for count_field in (
            "position_count",
            "position_count_total",
            "equity_position_count",
            "reserve_position_count",
        ):
            if count_field in account:
                require(
                    int(safe_float(curve_row.get(count_field), -1))
                    == int(safe_float(account.get(count_field), -2)),
                    f"equity_curve_{count_field}",
                )

    positions = read_csv(portfolio_dir / "positions_latest.csv")
    account_positions = account.get("positions") if isinstance(account.get("positions"), list) else []
    require(len(positions) == len(account_positions), "positions_row_count")
    require(
        len(account_positions)
        == int(
            safe_float(
                account.get("position_count_total"),
                account.get("position_count"),
            )
        ),
        "account_position_count_total",
    )
    reserve_positions = sum(
        1 for row in account_positions if isinstance(row, dict) and row.get("reserve_asset") is True
    )
    require(
        len(account_positions) - reserve_positions
        == int(
            safe_float(
                account.get("equity_position_count"),
                account.get("position_count"),
            )
        ),
        "account_equity_position_count",
    )
    require(
        reserve_positions
        == int(safe_float(account.get("reserve_position_count"), reserve_positions)),
        "account_reserve_position_count",
    )
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
            "same_session_mark_only_reuse": allow_target_to_suppressed_reuse,
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
    provider_symbol_links: dict[str, dict[str, str]] | None = None,
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
        ),
        provider_symbol_links=provider_symbol_links,
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
        execution_ticker = clean_ticker(row.get("ticker"))
        ticker = clean_ticker(row.get("ledger_ticker")) or execution_ticker
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
                "execution_ticker": execution_ticker or ticker,
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
    validate_restored_snapshot(
        portfolio_dir,
        portfolio,
        bootstrap_path=bootstrap_path,
    )
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
        expected_mode = "NO_NEW_ORDER" if suppress_new_orders else "EXECUTABLE_CANDIDATE"
        parity_errors = preview_parity_errors(
            preview_dir=preview_dir,
            account_path=portfolio_dir / "account_state_latest.json",
            effective_target_path=target_path,
            source_target_path=source_target_path,
            portfolio=portfolio,
            as_of_date=as_of_date,
            preview_mode=expected_mode,
        )
        if suppress_new_orders:
            write_no_new_order_preview(
                preview_dir=preview_dir,
                account_path=portfolio_dir / "account_state_latest.json",
                effective_target_path=target_path,
                source_target_path=source_target_path,
                portfolio=portfolio,
                as_of_date=as_of_date,
            )
        elif parity_errors:
            preview = build_order_preview(
                account_path=portfolio_dir / "account_state_latest.json",
                target_path=target_path,
                price_cache=price_cache,
                output_dir=preview_dir,
                portfolio=portfolio,
                as_of_date=as_of_date,
                cost_bps=cost_bps,
                provider_symbol_overrides=lifecycle.provider_symbol_overrides,
                provider_symbol_links=lifecycle.provider_symbol_links,
                reserve_mode=reserve_policy.mode,
            )
            if preview.get("status") != "completed":
                raise ValueError(
                    f"same-session paper account preview failed for {portfolio}: "
                    f"{preview.get('reason')}"
                )
            attest_preview_identity(
                preview_dir=preview_dir,
                account_path=portfolio_dir / "account_state_latest.json",
                effective_target_path=target_path,
                source_target_path=source_target_path,
                portfolio=portfolio,
                as_of_date=as_of_date,
                preview_mode="EXECUTABLE_CANDIDATE",
            )
        remaining_errors = preview_parity_errors(
            preview_dir=preview_dir,
            account_path=portfolio_dir / "account_state_latest.json",
            effective_target_path=target_path,
            source_target_path=source_target_path,
            portfolio=portfolio,
            as_of_date=as_of_date,
            preview_mode=expected_mode,
        )
        if remaining_errors:
            raise PaperLedgerIntegrityError(
                "BLOCKED_PREVIEW_PARITY",
                f"{portfolio}:{','.join(remaining_errors)}",
            )
        preview_changed = bool(parity_errors) or suppress_new_orders
        reusable["same_session_preview_rebuilt"] = preview_changed
        reusable["same_session_preview_parity_errors_before_rebuild"] = parity_errors
        reusable["result_status"] = (
            "NO_NEW_ORDER_PREVIEW" if suppress_new_orders else
            "PREVIEW_REBUILT" if preview_changed else
            "SAME_SESSION_REUSE"
        )
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
    terminal_fill_cutoffs = {
        alias: pd.Timestamp(event["last_trading_date"]).normalize()
        for alias, event in verified_settlement_by_ticker(lifecycle).items()
    }
    pending, fills, rejections, resolved = resolve_pending_orders(
        portfolio=portfolio,
        portfolio_dir=portfolio_dir,
        state=state,
        pending=pending,
        fills=fills,
        rejections=rejections,
        price_cache=price_cache,
        as_of_date=as_of_date,
        cost_bps=cost_bps,
        max_fill_lag_days=max_fill_lag_days,
        provider_symbol_overrides=lifecycle.provider_symbol_overrides,
        provider_symbol_links=lifecycle.provider_symbol_links,
        terminal_fill_cutoffs=terminal_fill_cutoffs,
    )
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
        provider_symbol_links=lifecycle.provider_symbol_links,
    )
    write_csv(portfolio_dir / "pending_orders.csv", pending, PENDING_COLUMNS)
    # A restored append-only ledger owns its CSV header order.  Reordering the
    # same schema here would make a valid descendant fail the exact-prefix
    # continuity proof even though no historical event changed.
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
        provider_symbol_links=lifecycle.provider_symbol_links,
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
            provider_symbol_links=lifecycle.provider_symbol_links,
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
    if suppress_new_orders:
        write_no_new_order_preview(
            preview_dir=preview_dir,
            account_path=account_path,
            effective_target_path=target_path,
            source_target_path=source_target_path,
            portfolio=portfolio,
            as_of_date=as_of_date,
        )
    else:
        attest_preview_identity(
            preview_dir=preview_dir,
            account_path=account_path,
            effective_target_path=target_path,
            source_target_path=source_target_path,
            portfolio=portfolio,
            as_of_date=as_of_date,
            preview_mode="EXECUTABLE_CANDIDATE",
        )
    parity_errors = preview_parity_errors(
        preview_dir=preview_dir,
        account_path=account_path,
        effective_target_path=target_path,
        source_target_path=source_target_path,
        portfolio=portfolio,
        as_of_date=as_of_date,
        preview_mode="NO_NEW_ORDER" if suppress_new_orders else "EXECUTABLE_CANDIDATE",
    )
    if parity_errors:
        raise PaperLedgerIntegrityError(
            "BLOCKED_PREVIEW_PARITY",
            f"{portfolio}:{','.join(parity_errors)}",
        )
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
        RESERVE_REASON_SOURCE_HASH_FIELD: reserve_reconciliation[
            RESERVE_REASON_SOURCE_HASH_FIELD
        ],
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


def stage_file_copy(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{destination.name}.candidate-",
        dir=destination.parent,
    )
    os.close(handle)
    candidate = Path(name)
    shutil.copy2(source, candidate)
    return candidate


def accepted_publication_payload(
    *,
    stage_state: Path,
    stage_preview: Path,
    target_paths: dict[str, Path],
    publish_paths: dict[str, Path],
    as_of_date: pd.Timestamp,
    suppress_new_orders: bool,
) -> dict[str, Any]:
    portfolios: dict[str, Any] = {}
    for portfolio in PORTFOLIOS:
        source = target_paths[portfolio]
        published = publish_paths.get(portfolio, source)
        preview_manifest = read_json(stage_preview / portfolio / "order_batch_manifest.json")
        portfolios[portfolio] = {
            "source_target_path": portable_path(source),
            "source_target_sha256": file_hash(source),
            "published_target_path": portable_path(published),
            "published_target_sha256": file_hash(source),
            "account_state_sha256": file_hash(stage_state / portfolio / "account_state_latest.json"),
            "ledger_manifest_sha256": file_hash(stage_state / portfolio / "manifest.json"),
            "preview_identity_at_acceptance": preview_manifest.get("preview_identity_hash"),
            "preview_mode_at_acceptance": preview_manifest.get("preview_mode"),
        }
    return {
        "schema_version": "run287-paper-accepted-publication-v1",
        "status": "ACCEPTED_ATOMIC_PUBLICATION",
        "as_of_date": as_of_date.date().isoformat(),
        "transaction_mode": "MARK_ONLY" if suppress_new_orders else "SELECTED_TARGET",
        "portfolios": portfolios,
        "review_only": True,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
    }


def verify_accepted_publication(
    state_root: Path,
    preview_root: Path,
) -> dict[str, Any]:
    payload = read_json(state_root / "accepted_publication.json")
    if (
        payload.get("schema_version")
        != "run287-paper-accepted-publication-v1"
        or payload.get("status") != "ACCEPTED_ATOMIC_PUBLICATION"
        or payload.get("transaction_mode") not in {"MARK_ONLY", "SELECTED_TARGET"}
        or payload.get("review_only") is not True
        or payload.get("live_trading_enabled") is not False
        or payload.get("production_mutation_allowed") is not False
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_PUBLICATION_PARITY",
            "accepted publication contract invalid",
        )
    suppress_new_orders = payload.get("transaction_mode") == "MARK_ONLY"
    summary = read_json(state_root / "summary.json")
    if (
        summary.get("schema_version")
        != "daily-simulated-fill-ledger-summary-v1"
        or summary.get("status") != "completed"
        or summary.get("new_order_generation_suppressed")
        is not suppress_new_orders
    ):
        raise PaperLedgerIntegrityError(
            "BLOCKED_PUBLICATION_PARITY",
            "accepted publication summary mode mismatch",
        )
    for portfolio in PORTFOLIOS:
        row = (payload.get("portfolios") or {}).get(portfolio) or {}
        published_path = Path(str(row.get("published_target_path") or ""))
        if not published_path.is_absolute():
            published_path = repo_path(published_path)
        checks = {
            "published_target_sha256": file_hash(published_path),
            "account_state_sha256": file_hash(state_root / portfolio / "account_state_latest.json"),
            "ledger_manifest_sha256": file_hash(state_root / portfolio / "manifest.json"),
        }
        for field, actual in checks.items():
            if not actual or str(row.get(field) or "") != actual:
                raise PaperLedgerIntegrityError(
                    "BLOCKED_PUBLICATION_PARITY",
                    f"{portfolio}:{field}",
                )
        preview_manifest = read_json(preview_root / portfolio / "order_batch_manifest.json")
        ledger_manifest = read_json(state_root / portfolio / "manifest.json")
        expected_preview_mode = (
            "NO_NEW_ORDER" if suppress_new_orders else "EXECUTABLE_CANDIDATE"
        )
        if (
            ledger_manifest.get("new_order_generation_suppressed")
            is not suppress_new_orders
            or preview_manifest.get("new_order_generation_suppressed")
            is not suppress_new_orders
            or preview_manifest.get("preview_mode") != expected_preview_mode
            or row.get("preview_mode_at_acceptance") != expected_preview_mode
        ):
            raise PaperLedgerIntegrityError(
                "BLOCKED_PUBLICATION_PARITY",
                f"{portfolio}:transaction_mode",
            )
        if str(preview_manifest.get("accepted_account_sha256") or "") != checks["account_state_sha256"]:
            raise PaperLedgerIntegrityError(
                "BLOCKED_PREVIEW_PARITY",
                f"{portfolio}:accepted_account_sha256",
            )
        if str(preview_manifest.get("source_target_sha256") or "") != str(row.get("source_target_sha256") or ""):
            raise PaperLedgerIntegrityError(
                "BLOCKED_PREVIEW_PARITY",
                f"{portfolio}:source_target_sha256",
            )
    return payload


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
    preview_journal_path = preview_root.parent / f".{preview_root.name}.preview-transaction.json"
    recover_interrupted_publish(preview_journal_path)
    recover_interrupted_publish(journal_path)
    prior_integrity = (
        verify_integrity_manifest(state_root, require=True)
        if (state_root / INTEGRITY_FILE).is_file()
        else {"status": "LEGACY_UNATTESTED", "snapshot_hash": ""}
    )
    bootstrap_paths = {
        portfolio: repo_path(getattr(args, f"{portfolio}_bootstrap_account")) for portfolio in PORTFOLIOS
    }
    target_paths = {portfolio: repo_path(getattr(args, f"{portfolio}_target")) for portfolio in PORTFOLIOS}
    publish_values = {
        portfolio: str(getattr(args, f"{portfolio}_publish_target", "") or "").strip()
        for portfolio in PORTFOLIOS
    }
    if any(publish_values.values()) and not all(publish_values.values()):
        raise ValueError("both --main-publish-target and --concentrated-publish-target are required")
    publish_paths = {
        portfolio: repo_path(value) for portfolio, value in publish_values.items() if value
    }
    stage_state = clone_directory(state_root, state_root.parent, f".{state_root.name}.candidate-")
    stage_preview = clone_directory(preview_root, preview_root.parent, f".{preview_root.name}.candidate-")
    staged_publication_files: list[Path] = []
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
        no_new_order_count = sum(
            1 for payload in results.values() if payload.get("result_status") == "NO_NEW_ORDER_PREVIEW"
        )
        summary = {
            "schema_version": "daily-simulated-fill-ledger-summary-v1",
            "status": "completed",
            "result_status": (
                "NO_NEW_ORDER_PREVIEW" if no_new_order_count == len(PORTFOLIOS) else
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
            "no_new_order_preview_portfolio_count": no_new_order_count,
            "new_order_generation_suppressed": suppress_new_orders,
            "generated_at_utc": utc_now(),
        }
        legacy_attestation_required = bool(
            same_session_count == len(PORTFOLIOS)
            and prior_integrity.get("status") == "LEGACY_UNATTESTED"
        )
        if legacy_attestation_required:
            summary["result_status"] = "LEGACY_ATTESTED"
            summary["legacy_snapshot_semantically_validated"] = True
        if same_session_count == len(PORTFOLIOS) and not legacy_attestation_required:
            for portfolio, destination in publish_paths.items():
                if file_hash(destination) != file_hash(target_paths[portfolio]):
                    raise PaperLedgerIntegrityError(
                        "BLOCKED_PUBLICATION_PARITY",
                        f"same-session published target mismatch:{portfolio}",
                    )
            # The committed ledger, including its root summary and checksum,
            # remains byte-identical.  Missing review-only previews may be
            # reconstructed independently from the frozen account mark.
            if directory_hashes(stage_preview) != directory_hashes(preview_root):
                atomic_publish_bundle(
                    [(stage_preview, preview_root)],
                    journal_path=preview_journal_path,
                    failpoint=failpoint,
                )
            return summary

        write_json(stage_state / "summary.json", summary)
        write_json(
            stage_state / "accepted_publication.json",
            accepted_publication_payload(
                stage_state=stage_state,
                stage_preview=stage_preview,
                target_paths=target_paths,
                publish_paths=publish_paths,
                as_of_date=as_of_date,
                suppress_new_orders=suppress_new_orders,
            ),
        )
        write_integrity_manifest(
            stage_state,
            as_of_date=as_of_date.date().isoformat(),
            previous_snapshot_hash=str(prior_integrity.get("snapshot_hash") or ""),
        )
        verify_integrity_manifest(stage_state, require=True)
        publish_pairs: list[tuple[Path, Path]] = [
            (stage_preview, preview_root),
            (stage_state, state_root),
        ]
        for portfolio in PORTFOLIOS:
            if portfolio in publish_paths:
                candidate = stage_file_copy(target_paths[portfolio], publish_paths[portfolio])
                staged_publication_files.append(candidate)
                publish_pairs.append((candidate, publish_paths[portfolio]))
        atomic_publish_bundle(
            publish_pairs,
            journal_path=journal_path,
            validators=[
                lambda: verify_integrity_manifest(state_root, require=True),
                lambda: verify_accepted_publication(state_root, preview_root),
            ],
            failpoint=failpoint,
        )
        return summary
    finally:
        for candidate in (stage_state, stage_preview):
            if candidate.is_dir():
                shutil.rmtree(candidate)
        for candidate in staged_publication_files:
            if candidate.exists():
                candidate.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="outputs/daily_simulated_fill_ledger")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--order-preview-root", default="outputs/account_ledger_preview")
    parser.add_argument("--main-bootstrap-account", default="outputs/broker_replay/main/account_state_latest.json")
    parser.add_argument("--concentrated-bootstrap-account", default="outputs/broker_replay/concentrated/account_state_latest.json")
    parser.add_argument("--main-target", default="outputs/reports/operating_main_target_book.csv")
    parser.add_argument("--concentrated-target", default="outputs/reports/operating_concentrated_target_book.csv")
    parser.add_argument("--main-publish-target", default="")
    parser.add_argument("--concentrated-publish-target", default="")
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
