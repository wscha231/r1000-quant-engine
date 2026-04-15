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
) -> tuple[dict[str, Any], bool]:
    state = load_live_portfolio_state(base_dir_or_paths)
    positions = positions_frame_from_state(state)
    if not positions.empty:
        return state, False
    boot = build_bootstrap_state_from_weights(
        weights_payload,
        portfolio_latest=portfolio_latest,
        strategy_version=strategy_version,
    )
    if positions_frame_from_state(boot).empty:
        return state, False
    save_live_portfolio_state(base_dir_or_paths, boot, snapshot_reason="bootstrap_from_weights_latest")
    return load_live_portfolio_state(base_dir_or_paths), True
