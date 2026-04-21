from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

CASH_PROXY_TICKER = "CASH"
LIVE_STATE_SCHEMA_VERSION = "2026-04-15-v1"

POSITION_COLUMNS = [
    "ticker",
    "shares",
    "weight",
    "target_weight",
    "avg_cost",
    "reference_price",
    "entry_date",
    "last_trade_date",
    "manual_lock",
    "min_hold_until",
    "thesis_status",
    "source",
    "notes",
]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_float(value: Any, default: float = np.nan) -> float:
    try:
        if value is None:
            return float(default)
        out = float(value)
        return out if np.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _normalize_ticker(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _safe_read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _safe_read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _append_history_parquet(
    path: Path,
    frame: pd.DataFrame,
    *,
    dedupe_subset: Optional[list[str]] = None,
    sort_columns: Optional[list[str]] = None,
) -> None:
    if frame is None or frame.empty:
        return
    combined = frame.copy()
    if path.exists():
        existing = _safe_read_parquet(path)
        if not existing.empty:
            combined = pd.concat([existing, combined], ignore_index=True, sort=False)
    if dedupe_subset:
        keep_cols = [c for c in dedupe_subset if c in combined.columns]
        if keep_cols:
            combined = combined.drop_duplicates(subset=keep_cols, keep="last")
    if sort_columns:
        keep_sort = [c for c in sort_columns if c in combined.columns]
        if keep_sort:
            combined = combined.sort_values(keep_sort).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)


def resolve_live_state_paths(base_dir_or_paths: str | Path | Mapping[str, Any]) -> dict[str, Path]:
    if isinstance(base_dir_or_paths, Mapping):
        if "ops" in base_dir_or_paths:
            ops_dir = Path(base_dir_or_paths["ops"])
            out_dir = Path(base_dir_or_paths.get("out", ops_dir.parent))
        elif "base" in base_dir_or_paths:
            base_dir = Path(base_dir_or_paths["base"])
            out_dir = base_dir / "outputs"
            ops_dir = out_dir / "ops"
        else:
            base_dir = Path(str(base_dir_or_paths.get("base_dir", "")))
            out_dir = base_dir / "outputs"
            ops_dir = out_dir / "ops"
    else:
        base_dir = Path(base_dir_or_paths)
        out_dir = base_dir / "outputs"
        ops_dir = out_dir / "ops"
    ops_dir.mkdir(parents=True, exist_ok=True)
    return {
        "ops": ops_dir,
        "out": out_dir,
        "state_json": ops_dir / "live_portfolio_state.json",
        "positions_latest": ops_dir / "live_portfolio_positions_latest.parquet",
        "state_history": ops_dir / "live_portfolio_state_history.parquet",
        "manual_overrides_json": ops_dir / "live_portfolio_manual_overrides.json",
    }


def empty_live_portfolio_state() -> dict[str, Any]:
    return {
        "schema_version": LIVE_STATE_SCHEMA_VERSION,
        "state_source": "empty",
        "last_synced_utc": _now_utc_iso(),
        "strategy_version": "",
        "as_of_date": None,
        "positions": [],
    }


def positions_frame_from_state(payload: Mapping[str, Any] | None) -> pd.DataFrame:
    if not isinstance(payload, Mapping):
        return pd.DataFrame(columns=POSITION_COLUMNS)
    positions = payload.get("positions") or []
    if isinstance(positions, Mapping):
        positions = [{"ticker": k, **(v if isinstance(v, Mapping) else {"weight": v})} for k, v in positions.items()]
    if not isinstance(positions, list):
        return pd.DataFrame(columns=POSITION_COLUMNS)
    frame = pd.DataFrame(positions)
    if frame.empty:
        return pd.DataFrame(columns=POSITION_COLUMNS)
    if "ticker" not in frame.columns:
        frame["ticker"] = ""
    frame["ticker"] = frame["ticker"].map(_normalize_ticker)
    frame = frame[frame["ticker"].ne("")]
    for col in ["shares", "weight", "target_weight", "avg_cost", "reference_price"]:
        frame[col] = pd.to_numeric(frame.get(col), errors="coerce")
    for col in ["entry_date", "last_trade_date", "min_hold_until"]:
        frame[col] = pd.to_datetime(frame.get(col), errors="coerce").dt.strftime("%Y-%m-%d")
    frame["manual_lock"] = frame.get("manual_lock", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    frame["thesis_status"] = frame.get("thesis_status", pd.Series("active", index=frame.index)).fillna("active").astype(str)
    frame["source"] = frame.get("source", pd.Series("unknown", index=frame.index)).fillna("unknown").astype(str)
    frame["notes"] = frame.get("notes", pd.Series("", index=frame.index)).fillna("").astype(str)
    for col in POSITION_COLUMNS:
        if col not in frame.columns:
            frame[col] = np.nan if col not in {"manual_lock", "thesis_status", "source", "notes"} else ""
    frame = frame[POSITION_COLUMNS].copy()
    frame = frame.drop_duplicates(subset=["ticker"], keep="last").reset_index(drop=True)
    return frame


def load_live_portfolio_state(base_dir_or_paths: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    state_paths = resolve_live_state_paths(base_dir_or_paths)
    payload = _safe_read_json(state_paths["state_json"], default={})
    if not isinstance(payload, dict):
        payload = {}
    state = empty_live_portfolio_state()
    state.update(payload)
    state["schema_version"] = LIVE_STATE_SCHEMA_VERSION
    state["positions"] = positions_frame_from_state(state).to_dict(orient="records")
    return state


def build_bootstrap_state_from_weights(
    weights_payload: Mapping[str, Any] | None,
    portfolio_latest: Optional[pd.DataFrame] = None,
    *,
    strategy_version: str = "",
) -> dict[str, Any]:
    state = empty_live_portfolio_state()
    state["state_source"] = "bootstrapped_from_weights_latest"
    state["strategy_version"] = str(strategy_version or "")
    if not isinstance(weights_payload, Mapping):
        return state
    as_of_date = weights_payload.get("rebalance_date")
    state["as_of_date"] = as_of_date
    holdings = weights_payload.get("holdings") or {}
    latest_lookup = pd.DataFrame()
    if portfolio_latest is not None and not portfolio_latest.empty and "ticker" in portfolio_latest.columns:
        latest_lookup = portfolio_latest.copy()
        latest_lookup["ticker"] = latest_lookup["ticker"].astype(str).str.upper()
        latest_lookup = latest_lookup.drop_duplicates(subset=["ticker"], keep="first").set_index("ticker", drop=False)
    rows: list[dict[str, Any]] = []
    for raw_ticker, raw_weight in holdings.items():
        ticker = _normalize_ticker(raw_ticker)
        weight = _safe_float(raw_weight, default=np.nan)
        if not ticker or not np.isfinite(weight) or weight <= 1e-10:
            continue
        ref_price = np.nan
        if not latest_lookup.empty and ticker in latest_lookup.index:
            row = latest_lookup.loc[ticker]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            ref_price = _safe_float(row.get("current_price_live"), default=np.nan)
        rows.append(
            {
                "ticker": ticker,
                "shares": np.nan,
                "weight": float(weight),
                "target_weight": float(weight),
                "avg_cost": np.nan,
                "reference_price": ref_price,
                "entry_date": as_of_date,
                "last_trade_date": as_of_date,
                "manual_lock": False,
                "min_hold_until": None,
                "thesis_status": "active",
                "source": "bootstrap_model",
                "notes": "bootstrapped from weights_latest.json",
            }
        )
    state["positions"] = positions_frame_from_state({"positions": rows}).to_dict(orient="records")
    return state


def save_live_portfolio_state(
    base_dir_or_paths: str | Path | Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    snapshot_reason: str = "manual_save",
) -> dict[str, str]:
    state_paths = resolve_live_state_paths(base_dir_or_paths)
    state = empty_live_portfolio_state()
    if isinstance(payload, Mapping):
        state.update(dict(payload))
    state["schema_version"] = LIVE_STATE_SCHEMA_VERSION
    state["last_synced_utc"] = _now_utc_iso()
    positions = positions_frame_from_state(state)
    state["positions"] = positions.to_dict(orient="records")
    state_paths["state_json"].write_text(json.dumps(state, indent=2), encoding="utf-8")
    if not positions.empty:
        latest_snapshot = positions.copy()
        latest_snapshot["snapshot_reason"] = str(snapshot_reason)
        latest_snapshot["snapshot_timestamp_utc"] = state["last_synced_utc"]
        latest_snapshot.to_parquet(state_paths["positions_latest"], index=False)
        _append_history_parquet(
            state_paths["state_history"],
            latest_snapshot,
            dedupe_subset=["snapshot_timestamp_utc", "ticker"],
            sort_columns=["entry_date", "snapshot_timestamp_utc", "ticker"],
        )
    return {
        "live_portfolio_state.json": str(state_paths["state_json"]),
        "live_portfolio_positions_latest.parquet": str(state_paths["positions_latest"]),
        "live_portfolio_state_history.parquet": str(state_paths["state_history"]),
    }


def ensure_live_portfolio_state(
    base_dir_or_paths: str | Path | Mapping[str, Any],
    *,
    weights_payload: Mapping[str, Any] | None = None,
    portfolio_latest: Optional[pd.DataFrame] = None,
    strategy_version: str = "",
    force_refresh: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Bootstrap or refresh live portfolio state from weights_latest.json.

    When *force_refresh* is True the state is re-bootstrapped even if
    positions already exist, preserving entry_date and avg_cost from the
    previous state for tickers that remain held.
    """
    state = load_live_portfolio_state(base_dir_or_paths)
    positions = positions_frame_from_state(state)
    if not positions.empty and not force_refresh:
        return state, False
    boot = build_bootstrap_state_from_weights(
        weights_payload,
        portfolio_latest=portfolio_latest,
        strategy_version=strategy_version,
    )
    boot_positions = positions_frame_from_state(boot)
    if boot_positions.empty:
        return state, False
    # On force-refresh, carry over entry_date and avg_cost from old state
    if force_refresh and not positions.empty:
        old_lookup: dict[str, dict[str, Any]] = {}
        for pos in state.get("positions") or []:
            if isinstance(pos, dict) and pos.get("ticker"):
                old_lookup[str(pos["ticker"]).upper()] = pos
        refreshed: list[dict[str, Any]] = []
        for pos in boot.get("positions") or []:
            if not isinstance(pos, dict):
                continue
            ticker = str(pos.get("ticker", "")).upper()
            old = old_lookup.get(ticker, {})
            if old.get("entry_date"):
                pos["entry_date"] = old["entry_date"]
            if old.get("avg_cost") is not None:
                try:
                    if np.isfinite(float(old["avg_cost"])):
                        pos["avg_cost"] = old["avg_cost"]
                except Exception:
                    pass
            refreshed.append(pos)
        boot["positions"] = refreshed
    reason = "force_refresh_from_weights" if force_refresh else "bootstrap_from_weights_latest"
    save_live_portfolio_state(base_dir_or_paths, boot, snapshot_reason=reason)
    return load_live_portfolio_state(base_dir_or_paths), True


def apply_actual_holdings(
    base_dir_or_paths: str | Path | Mapping[str, Any],
    holdings: Mapping[str, Any],
    *,
    as_of_date: Optional[str] = None,
    strategy_version: str = "",
) -> dict[str, str]:
    """Update live state with actual broker/manual holdings.

    *holdings* is a dict mapping ticker to weight (float) or to a dict
    with optional keys ``weight``, ``avg_cost``, ``shares``,
    ``reference_price``.  Example::

        apply_actual_holdings(paths, {
            "NVDA": 0.14,
            "GOOG": {"weight": 0.13, "avg_cost": 172.50, "shares": 45},
        })
    """
    state = load_live_portfolio_state(base_dir_or_paths)
    old_lookup: dict[str, dict[str, Any]] = {}
    for pos in state.get("positions") or []:
        if isinstance(pos, dict) and pos.get("ticker"):
            old_lookup[str(pos["ticker"]).upper()] = pos

    date_str = str(as_of_date or _now_utc_iso()[:10])
    rows: list[dict[str, Any]] = []
    for raw_ticker, raw_val in (holdings or {}).items():
        ticker = _normalize_ticker(raw_ticker)
        if not ticker:
            continue
        user_entry_date = ""
        user_notes = ""
        user_thesis = ""
        if isinstance(raw_val, Mapping):
            weight = _safe_float(raw_val.get("weight"), default=0.0)
            avg_cost = _safe_float(raw_val.get("avg_cost"), default=np.nan)
            shares = _safe_float(raw_val.get("shares"), default=np.nan)
            ref_price = _safe_float(raw_val.get("reference_price"), default=np.nan)
            user_entry_date = str(raw_val.get("entry_date") or "").strip()
            user_notes = str(raw_val.get("notes") or "").strip()
            user_thesis = str(raw_val.get("thesis_status") or "").strip()
        else:
            weight = _safe_float(raw_val, default=0.0)
            avg_cost = np.nan
            shares = np.nan
            ref_price = np.nan
        if weight <= 1e-10:
            continue
        old = old_lookup.get(ticker, {})
        # Phase 12B (2026-04-21): user-provided entry_date / notes / thesis_status
        # from manual_positions.yaml take precedence over old state and date_str.
        # This is critical for backtest <-> live continuity (Phase 12C) so the
        # entry_date reflects the actual trade date, not the YAML edit date.
        resolved_entry_date = user_entry_date or old.get("entry_date") or date_str
        resolved_notes = user_notes or f"Manual holdings update {date_str}"
        resolved_thesis = user_thesis or "active"
        rows.append({
            "ticker": ticker,
            "shares": shares if np.isfinite(shares) else old.get("shares", np.nan),
            "weight": float(weight),
            "target_weight": float(weight),
            "avg_cost": avg_cost if np.isfinite(avg_cost) else old.get("avg_cost", np.nan),
            "reference_price": ref_price if np.isfinite(ref_price) else old.get("reference_price", np.nan),
            "entry_date": resolved_entry_date,
            "last_trade_date": date_str,
            "manual_lock": old.get("manual_lock", False),
            "min_hold_until": old.get("min_hold_until"),
            "thesis_status": resolved_thesis,
            "source": "manual_actual",
            "notes": resolved_notes,
        })
    state["positions"] = positions_frame_from_state({"positions": rows}).to_dict(orient="records")
    state["state_source"] = "manual_actual"
    state["strategy_version"] = str(strategy_version or state.get("strategy_version", ""))
    state["as_of_date"] = date_str
    return save_live_portfolio_state(base_dir_or_paths, state, snapshot_reason="manual_actual_holdings")


# =====================================================================
# Phase 12B (2026-04-21): manual_positions.yaml input UX
# =====================================================================
# Schema documented in MANUAL_POSITIONS_SCHEMA below. User edits a YAML file
# at base_dir/manual_positions.yaml with their actual broker positions
# (avg_cost, shares, entry_date). Engine reads it on each run and updates
# live_portfolio_state.json so portfolio_latest.csv shows real buy info.

MANUAL_POSITIONS_FILENAME = "manual_positions.yaml"

MANUAL_POSITIONS_SCHEMA = """\
# manual_positions.yaml — record your actual broker holdings here.
# Engine reads this on every run and merges into live_portfolio_state.json.
# Drop file at base_dir (G:\\내 드라이브\\r1000_top30_institutional\\).
#
# All fields are optional EXCEPT weight. Engine fills NaN/empty for the rest.
# Use either:
#   (1) Simple form -- just weight:    NVDA: 0.14
#   (2) Full form -- with buy info:    NVDA: {weight: 0.14, shares: 75, avg_cost: 172.50, entry_date: "2024-08-15"}
#
# Example:
# ---
# as_of_date: "2026-04-21"               # optional, defaults to today
# strategy_version: "phase9_c3_ce_v2"    # optional, free-text label
# positions:
#   NVDA:
#     weight: 0.14
#     shares: 75
#     avg_cost: 172.50
#     entry_date: "2024-08-15"
#     notes: "first AI conviction add"
#   GOOG:
#     weight: 0.14
#     shares: 100
#     avg_cost: 158.20
#     entry_date: "2025-02-10"
#   AVGO: 0.082                  # simple form, no buy info (NaN stays)
"""


def manual_positions_path(base_dir_or_paths: str | Path | Mapping[str, Any]) -> Path:
    """Return the canonical path for manual_positions.yaml.

    Prefers the engine base_dir (G:/내 드라이브/r1000_top30_institutional/manual_positions.yaml)
    so users can edit it without diving into outputs/ops/. Falls back to ops_dir
    if base_dir cannot be resolved.
    """
    if isinstance(base_dir_or_paths, Mapping):
        for key in ("base", "base_dir"):
            if key in base_dir_or_paths and base_dir_or_paths[key]:
                return Path(base_dir_or_paths[key]) / MANUAL_POSITIONS_FILENAME
        # Derive from out_dir parent if base not provided
        if "out" in base_dir_or_paths:
            return Path(base_dir_or_paths["out"]).parent / MANUAL_POSITIONS_FILENAME
        if "ops" in base_dir_or_paths:
            return Path(base_dir_or_paths["ops"]).parent.parent / MANUAL_POSITIONS_FILENAME
    else:
        return Path(base_dir_or_paths) / MANUAL_POSITIONS_FILENAME
    # Last-resort fallback: drop into ops dir
    state_paths = resolve_live_state_paths(base_dir_or_paths)
    return state_paths["ops"] / MANUAL_POSITIONS_FILENAME


def load_manual_positions_yaml(
    base_dir_or_paths: str | Path | Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """Read base_dir/manual_positions.yaml. Returns None if missing or invalid."""
    p = manual_positions_path(base_dir_or_paths)
    if not p.exists():
        return None
    try:
        import yaml  # PyYAML is a dep already (used elsewhere)
    except Exception:
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    else:
        try:
            payload = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    if not isinstance(payload, Mapping):
        return None
    positions = payload.get("positions") or {}
    if not isinstance(positions, Mapping) or not positions:
        return None
    return {
        "as_of_date": payload.get("as_of_date"),
        "strategy_version": str(payload.get("strategy_version", "") or ""),
        "positions": dict(positions),
    }


def apply_manual_positions_from_yaml(
    base_dir_or_paths: str | Path | Mapping[str, Any],
) -> tuple[dict[str, str], bool]:
    """If manual_positions.yaml exists, parse it and apply via apply_actual_holdings.

    Returns (paths_dict, applied_bool). applied=False when YAML missing or empty,
    so callers know to fall back to bootstrap.
    """
    payload = load_manual_positions_yaml(base_dir_or_paths)
    if not payload:
        return {}, False
    paths = apply_actual_holdings(
        base_dir_or_paths,
        payload["positions"],
        as_of_date=payload.get("as_of_date"),
        strategy_version=payload.get("strategy_version", ""),
    )
    return paths, True


def write_manual_positions_template(
    base_dir_or_paths: str | Path | Mapping[str, Any],
    *,
    overwrite: bool = False,
) -> Path:
    """Write a commented template YAML if file doesn't exist (or overwrite=True).

    Used to bootstrap user UX: first run creates the template so user knows
    where to edit.
    """
    p = manual_positions_path(base_dir_or_paths)
    if p.exists() and not overwrite:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(MANUAL_POSITIONS_SCHEMA, encoding="utf-8")
    return p
