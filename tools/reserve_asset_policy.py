"""Canonical Run287 Reserve asset and reason policy.

The policy is deliberately independent of broker, selector, and filesystem
I/O.  Historical replay, current target construction, order preview, and the
forward paper ledger use the same mode names and reason reconciliation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


SCHEMA_VERSION = "run287-reserve-asset-policy-v1"

BROKER_CASH_OR_MMF = "BROKER_CASH_OR_MMF"
DGS3MO_CARRY = "DGS3MO_CARRY"
BIL_TOTAL_RETURN = "BIL_TOTAL_RETURN"
SGOV_TOTAL_RETURN = "SGOV_TOTAL_RETURN"
BLOCKED_SHORT_HISTORY = "BLOCKED_SHORT_HISTORY"

RESERVE_MODES = (
    BROKER_CASH_OR_MMF,
    DGS3MO_CARRY,
    BIL_TOTAL_RETURN,
    SGOV_TOTAL_RETURN,
)
RESERVE_REASONS = (
    "crisis_reserve",
    "capacity_unallocated",
    "reentry_pending",
    "data_block_reserve",
    "transaction_buffer",
    "residual_cash",
)
RESERVE_REASON_SOURCE_HASH_FIELD = "reserve_reason_source_hash"
DEFAULT_HISTORICAL_MODE = DGS3MO_CARRY
DEFAULT_CURRENT_PAPER_MODE = BROKER_CASH_OR_MMF

LEGACY_MODE_ALIASES = {
    "": BROKER_CASH_OR_MMF,
    "NONE": BROKER_CASH_OR_MMF,
    "ZERO_YIELD": BROKER_CASH_OR_MMF,
    "RISK_FREE_RATE": DGS3MO_CARRY,
    "DGS3MO": DGS3MO_CARRY,
    "BIL": BIL_TOTAL_RETURN,
    "SGOV": SGOV_TOTAL_RETURN,
}


@dataclass(frozen=True)
class ReserveAssetPolicy:
    mode: str
    asset_ticker: str
    tradeable: bool
    cash_interest_enabled: bool
    adjusted_close_total_return: bool
    price_execution: str
    integer_shares: bool
    lifecycle_required: bool
    historical_default: bool
    current_paper_default: bool
    research_only: bool = True
    production_enabled: bool = False
    live_trading_enabled: bool = False

    def audit(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


def canonical_reserve_mode(value: Any) -> str:
    raw = str(value or "").upper().strip()
    mode = LEGACY_MODE_ALIASES.get(raw, raw)
    if mode not in RESERVE_MODES:
        raise ValueError(f"unsupported Reserve mode: {value}")
    return mode


def resolve_reserve_asset_policy(
    mode: Any = None,
    *,
    context: str = "current_paper",
) -> ReserveAssetPolicy:
    context_name = str(context or "current_paper").lower().strip()
    if mode is None or str(mode).strip() == "":
        mode = (
            DEFAULT_HISTORICAL_MODE
            if context_name == "historical"
            else DEFAULT_CURRENT_PAPER_MODE
        )
    canonical = canonical_reserve_mode(mode)
    asset = "BIL" if canonical == BIL_TOTAL_RETURN else "SGOV" if canonical == SGOV_TOTAL_RETURN else "CASH"
    tradeable = canonical in {BIL_TOTAL_RETURN, SGOV_TOTAL_RETURN}
    return ReserveAssetPolicy(
        mode=canonical,
        asset_ticker=asset,
        tradeable=tradeable,
        cash_interest_enabled=canonical == DGS3MO_CARRY,
        adjusted_close_total_return=tradeable,
        price_execution="next_close" if tradeable else "cash_ledger",
        integer_shares=tradeable,
        lifecycle_required=tradeable,
        historical_default=canonical == DEFAULT_HISTORICAL_MODE,
        current_paper_default=canonical == DEFAULT_CURRENT_PAPER_MODE,
    )


def _safe_weight(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if np.isfinite(result) else 0.0


def _reserve_mask(frame: pd.DataFrame, policy: ReserveAssetPolicy) -> pd.Series:
    ticker = frame.get("ticker", pd.Series(index=frame.index, dtype=str)).astype(str).str.upper().str.strip()
    names = {"CASH", "__CASH__"}
    if policy.tradeable:
        names.add(policy.asset_ticker)
    return ticker.isin(names)


def ensure_explicit_cash_row(
    frame: pd.DataFrame,
    *,
    weight_col: str,
    tolerance: float = 1e-8,
) -> pd.DataFrame:
    """Materialize implicit cash without changing any non-cash allocation."""
    if frame.empty:
        return frame.copy()
    if "ticker" not in frame.columns or weight_col not in frame.columns:
        raise ValueError("explicit cash normalization requires ticker and weight")
    out = frame.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out[weight_col] = pd.to_numeric(out[weight_col], errors="coerce")
    if out[weight_col].isna().any() or (out[weight_col] < -tolerance).any():
        raise ValueError("invalid target weight during explicit cash normalization")
    total = float(out[weight_col].sum())
    if total > 1.0 + tolerance:
        raise ValueError(f"target weight exceeds one: {total:.12f}")
    residual = max(0.0, 1.0 - total)
    if residual <= tolerance:
        return out
    explicit_reasons = any(reason in out.columns for reason in RESERVE_REASONS)
    cash_rows = out.index[out["ticker"].isin({"CASH", "__CASH__"})].tolist()
    if cash_rows:
        index = cash_rows[0]
        out.loc[index, weight_col] = float(out.loc[index, weight_col]) + residual
        if "capacity_unallocated" not in out.columns:
            out["capacity_unallocated"] = 0.0
        out["capacity_unallocated"] = pd.to_numeric(
            out["capacity_unallocated"], errors="coerce"
        ).fillna(0.0)
        if explicit_reasons:
            out.loc[index, "capacity_unallocated"] += residual
        else:
            final_cash_weight = float(
                out.loc[out["ticker"].isin({"CASH", "__CASH__"}), weight_col].sum()
            )
            out.loc[index, "capacity_unallocated"] = final_cash_weight
        return out
    row = {column: np.nan for column in out.columns}
    row["ticker"] = "CASH"
    row[weight_col] = residual
    row["capacity_unallocated"] = residual
    return pd.concat([out, pd.DataFrame([row])], ignore_index=True)


def reserve_reason_source_hash(
    *,
    policy: ReserveAssetPolicy,
    reserve_weight: float,
    reasons: dict[str, float],
) -> str:
    payload = {
        "schema_version": "run287-reserve-reason-source-v1",
        "reserve_weight": round(float(reserve_weight), 12),
        "reason_weights": {
            reason: round(float(reasons.get(reason, 0.0)), 12)
            for reason in RESERVE_REASONS
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reserve_reason_reconciliation(
    frame: pd.DataFrame,
    *,
    policy: ReserveAssetPolicy,
    weight_col: str,
    tolerance: float = 1e-8,
) -> dict[str, Any]:
    """Reconcile one target/account snapshot to the six Reserve reasons."""
    if weight_col not in frame.columns:
        raise ValueError(f"missing Reserve weight column: {weight_col}")
    mask = _reserve_mask(frame, policy)
    reserve_weight = float(
        pd.to_numeric(frame.loc[mask, weight_col], errors="coerce").fillna(0.0).sum()
    )
    reasons = {reason: 0.0 for reason in RESERVE_REASONS}
    explicit = False
    for reason in RESERVE_REASONS:
        if reason in frame.columns:
            explicit = True
            reasons[reason] = float(
                pd.to_numeric(frame.loc[mask, reason], errors="coerce").fillna(0.0).sum()
            )
    if not explicit:
        reasons["capacity_unallocated"] = reserve_weight
    reason_sum = float(sum(reasons.values()))
    if abs(reason_sum - reserve_weight) > tolerance:
        raise ValueError(
            "Reserve reason reconciliation failure: "
            f"reasons={reason_sum:.12f} reserve={reserve_weight:.12f}"
        )
    source_hash = reserve_reason_source_hash(
        policy=policy,
        reserve_weight=reserve_weight,
        reasons=reasons,
    )
    if RESERVE_REASON_SOURCE_HASH_FIELD in frame.columns:
        embedded = {
            str(value).strip().lower()
            for value in frame[RESERVE_REASON_SOURCE_HASH_FIELD].tolist()
            if str(value).strip().lower() not in {"", "nan", "none"}
        }
        if len(embedded) > 1:
            raise ValueError(
                "conflicting Reserve reason source hashes: "
                f"{sorted(embedded)}"
            )
        if embedded and next(iter(embedded)) != source_hash:
            raise ValueError(
                "stale Reserve reason source hash: "
                f"embedded={next(iter(embedded))} computed={source_hash}"
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": policy.mode,
        "asset_ticker": policy.asset_ticker,
        "reserve_weight": reserve_weight,
        "reason_weights": reasons,
        "reason_weight_sum": reason_sum,
        "reconciled": True,
        "explicit_reason_fields": explicit,
        RESERVE_REASON_SOURCE_HASH_FIELD: source_hash,
    }


def account_reserve_reason_reconciliation(
    target_reconciliation: dict[str, Any],
    *,
    actual_reserve_weight: float,
) -> dict[str, Any]:
    """Scale target reasons to the actually marked Reserve without relabeling."""
    actual = float(np.clip(_safe_weight(actual_reserve_weight), 0.0, 1.0))
    target = max(_safe_weight(target_reconciliation.get("reserve_weight")), 0.0)
    source = target_reconciliation.get("reason_weights") or {}
    reasons = {reason: max(_safe_weight(source.get(reason)), 0.0) for reason in RESERVE_REASONS}
    if target > 1e-12:
        scale = actual / target
        reasons = {reason: value * scale for reason, value in reasons.items()}
    else:
        reasons = {reason: 0.0 for reason in RESERVE_REASONS}
        reasons["residual_cash"] = actual
    reason_sum = float(sum(reasons.values()))
    residual = actual - reason_sum
    reasons["residual_cash"] += residual
    reason_sum = float(sum(reasons.values()))
    if abs(reason_sum - actual) > 1e-10:
        raise ValueError("account Reserve reason reconciliation failure")
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": target_reconciliation.get("mode"),
        "asset_ticker": target_reconciliation.get("asset_ticker"),
        "target_reserve_weight": target,
        "actual_reserve_weight": actual,
        "reason_weights": reasons,
        "reason_weight_sum": reason_sum,
        "reconciled": True,
        "method": "target_reason_proportions_scaled_to_actual_mark",
        RESERVE_REASON_SOURCE_HASH_FIELD: str(
            target_reconciliation.get(RESERVE_REASON_SOURCE_HASH_FIELD) or ""
        ),
    }


def apply_reserve_asset_to_targets(
    frame: pd.DataFrame,
    *,
    policy: ReserveAssetPolicy,
    weight_col: str,
    date_col: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Materialize the Reserve instrument without changing stock weights."""
    if frame.empty:
        return frame.copy(), pd.DataFrame()
    if "ticker" not in frame.columns or weight_col not in frame.columns:
        raise ValueError("Reserve target requires ticker and weight")
    groups = [None]
    if date_col and date_col in frame.columns:
        groups = list(pd.to_datetime(frame[date_col], errors="coerce").dropna().unique())
    output: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    for raw_date in groups:
        if raw_date is None:
            part = frame.copy()
        else:
            normalized = pd.Timestamp(raw_date).normalize()
            dates = pd.to_datetime(frame[date_col], errors="coerce").dt.normalize()
            part = frame.loc[dates.eq(normalized)].copy()
        part = ensure_explicit_cash_row(part, weight_col=weight_col)
        if date_col and date_col in part.columns and raw_date is not None:
            part[date_col] = part[date_col].fillna(pd.Timestamp(raw_date).normalize())
        before = reserve_reason_reconciliation(part, policy=policy, weight_col=weight_col)
        part[RESERVE_REASON_SOURCE_HASH_FIELD] = before[
            RESERVE_REASON_SOURCE_HASH_FIELD
        ]
        before_stock = float(part.loc[~_reserve_mask(part, policy), weight_col].sum())
        if policy.tradeable:
            part.loc[part["ticker"].isin({"CASH", "__CASH__"}), "ticker"] = policy.asset_ticker
            aggregations: dict[str, str] = {weight_col: "sum"}
            for column in part.columns:
                if column in {"ticker", weight_col}:
                    continue
                aggregations[column] = "sum" if column in RESERVE_REASONS else "last"
            part = part.groupby("ticker", as_index=False, dropna=False).agg(aggregations)
        part["reserve_asset_policy_schema"] = SCHEMA_VERSION
        part["reserve_asset_mode"] = policy.mode
        part["reserve_asset_ticker"] = policy.asset_ticker
        part["reserve_asset_tradeable"] = policy.tradeable
        part["reserve_reason_reconciled"] = True
        after = reserve_reason_reconciliation(part, policy=policy, weight_col=weight_col)
        after_stock = float(part.loc[~_reserve_mask(part, policy), weight_col].sum())
        stock_unchanged = bool(abs(before_stock - after_stock) <= 1e-12)
        if not stock_unchanged:
            raise ValueError("Reserve materialization changed stock weight")
        audits.append(
            {
                "date": pd.Timestamp(raw_date).date().isoformat() if raw_date is not None else "",
                **after,
                "stock_weight_unchanged": stock_unchanged,
                "input_reserve_weight": before["reserve_weight"],
            }
        )
        output.append(part)
    combined = pd.concat(output, ignore_index=True, sort=False)
    return combined, pd.DataFrame(audits)


def reserve_history_status(
    prices: pd.DataFrame,
    *,
    policy: ReserveAssetPolicy,
    required_start: Any,
    required_end: Any,
    max_fill_lag_days: int = 7,
) -> dict[str, Any]:
    if not policy.tradeable:
        return {"status": "READY", "mode": policy.mode, "asset_ticker": policy.asset_ticker}
    if prices.empty:
        return {
            "status": BLOCKED_SHORT_HISTORY,
            "mode": policy.mode,
            "asset_ticker": policy.asset_ticker,
            "reason": "reserve_price_history_missing",
        }
    index = pd.DatetimeIndex(pd.to_datetime(prices.index, errors="coerce")).dropna().tz_localize(None)
    first = pd.Timestamp(index.min()).normalize()
    last = pd.Timestamp(index.max()).normalize()
    start = pd.Timestamp(required_start).normalize()
    end = pd.Timestamp(required_end).normalize()
    start_ok = first <= start + pd.Timedelta(days=max_fill_lag_days)
    end_ok = last >= end
    return {
        "status": "READY" if start_ok and end_ok else BLOCKED_SHORT_HISTORY,
        "mode": policy.mode,
        "asset_ticker": policy.asset_ticker,
        "required_start": start.date().isoformat(),
        "required_end": end.date().isoformat(),
        "history_start": first.date().isoformat(),
        "history_end": last.date().isoformat(),
        "start_covered": bool(start_ok),
        "end_covered": bool(end_ok),
        "price_mode": "adjusted_close_total_return",
    }


def assert_no_double_count(
    policy: ReserveAssetPolicy,
    *,
    cash_interest_enabled: bool,
) -> None:
    if policy.tradeable and cash_interest_enabled:
        raise ValueError("ETF total return and cash interest may not be credited together")
