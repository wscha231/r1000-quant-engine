from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from r1000_portfolio_state import (
    CASH_PROXY_TICKER,
    ensure_live_portfolio_state,
    load_live_portfolio_state,
    positions_frame_from_state,
    resolve_live_state_paths,
)

OPERATOR_POLICY_VERSION = "2026-04-15-v1"

FULL_REBALANCE_ACTIONS = {
    "rebalance",
    "initial_rebalance",
    "full_rebalance",
    "review_then_rebalance",
    "circuit_breaker_rebalance",
    "circuit_breaker_release",
}


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


def _safe_read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
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
        try:
            existing = pd.read_parquet(path)
        except Exception:
            existing = pd.DataFrame()
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


def _policy_defaults() -> dict[str, float]:
    return {
        "min_weight_trade_delta": 0.0075,
        "min_new_position_weight": 0.02,
        "intramonth_new_position_weight": 0.03,
        "intramonth_rank_max": 8.0,
        "monthly_legacy_hold_rank_buffer": 45.0,
        "monthly_legacy_keep_max_weight": 0.025,
        "min_hold_days": 21.0,
        "intramonth_exit_loss_threshold": -0.12,
        "intramonth_exit_risk_threshold": 0.65,
        "intramonth_hold_support_floor": 0.52,
    }


# ---------------------------------------------------------------------------
# Sleeve-specific operator policy thresholds
# ---------------------------------------------------------------------------
_SLEEVE_POLICIES: dict[str, dict[str, float]] = {
    "core_compounder": {
        "min_hold_days": 42.0,
        "intramonth_exit_loss_threshold": -0.15,
        "intramonth_exit_risk_threshold": 0.70,
        "intramonth_hold_support_floor": 0.60,
        "monthly_legacy_hold_rank_buffer": 50.0,
        "monthly_legacy_keep_max_weight": 0.03,
    },
    "future_winner": {
        "min_hold_days": 21.0,
        "intramonth_exit_loss_threshold": -0.12,
        "intramonth_exit_risk_threshold": 0.65,
        "intramonth_hold_support_floor": 0.52,
        "monthly_legacy_hold_rank_buffer": 45.0,
        "monthly_legacy_keep_max_weight": 0.025,
    },
    "early_scout": {
        "min_hold_days": 14.0,
        "intramonth_exit_loss_threshold": -0.10,
        "intramonth_exit_risk_threshold": 0.60,
        "intramonth_hold_support_floor": 0.45,
        "monthly_legacy_hold_rank_buffer": 35.0,
        "monthly_legacy_keep_max_weight": 0.015,
    },
}

_SLEEVE_LABEL_COLUMNS = [
    "portfolio_sleeve_label",
    "sleeve_label",
    "sleeve",
]


def _resolve_sleeve(target_row: Any, top_row: Any) -> str:
    """Resolve the sleeve label for a ticker from portfolio or top30 data."""
    for source in [target_row, top_row]:
        if source is None:
            continue
        for col in _SLEEVE_LABEL_COLUMNS:
            val = source.get(col) if hasattr(source, "get") else getattr(source, col, None)
            if val is not None and str(val).strip() not in {"", "nan", "None"}:
                return str(val).strip()
    return "core_compounder"


def _sleeve_threshold(sleeve: str, key: str, defaults: dict[str, float]) -> float:
    """Get a sleeve-specific threshold, falling back to base defaults."""
    return float(_SLEEVE_POLICIES.get(sleeve, {}).get(key, defaults.get(key, 0.0)))


def _days_between(start_value: Any, end_value: Any) -> float:
    start_dt = pd.to_datetime(start_value, errors="coerce")
    end_dt = pd.to_datetime(end_value, errors="coerce")
    if pd.isna(start_dt) or pd.isna(end_dt):
        return np.nan
    return float((pd.Timestamp(end_dt) - pd.Timestamp(start_dt)).days)


def _load_inputs(base_dir_or_paths: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    state_paths = resolve_live_state_paths(base_dir_or_paths)
    out_dir = state_paths["out"]
    portfolio_latest = _safe_read_csv(out_dir / "portfolio_latest.csv")
    top30_latest = _safe_read_csv(out_dir / "top30_latest.csv")
    run_summary = _safe_read_json(out_dir / "run_summary.json", default={}) or {}
    weights_payload = _safe_read_json(out_dir / "weights_latest.json", default={}) or {}
    return {
        "paths": state_paths,
        "portfolio_latest": portfolio_latest,
        "top30_latest": top30_latest,
        "run_summary": run_summary,
        "weights_payload": weights_payload,
    }


def _coerce_target_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["ticker", "target_weight"])
    out = frame.copy()
    out["ticker"] = out.get("ticker", pd.Series(dtype=object)).astype(str).str.upper()
    out["target_weight"] = pd.to_numeric(out.get("weight"), errors="coerce").fillna(0.0)
    if "rank" not in out.columns:
        out["rank"] = np.nan
    if "score" not in out.columns:
        out["score"] = np.nan
    return out.drop_duplicates(subset=["ticker"], keep="first").reset_index(drop=True)


def _coerce_top30_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["ticker", "rank", "score"])
    out = frame.copy()
    out["ticker"] = out.get("ticker", pd.Series(dtype=object)).astype(str).str.upper()
    for col in [
        "rank",
        "score",
        "current_price_live",
        "portfolio_hold_policy_support",
        "portfolio_hold_policy_exit_risk",
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.drop_duplicates(subset=["ticker"], keep="first").reset_index(drop=True)


def _infer_current_positions(
    state_payload: Mapping[str, Any],
    *,
    as_of_date: Any = None,
) -> pd.DataFrame:
    positions = positions_frame_from_state(state_payload)
    if positions.empty:
        return positions
    out = positions.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper()
    out["current_weight"] = pd.to_numeric(out.get("weight"), errors="coerce").fillna(0.0)
    if out["ticker"].ne(CASH_PROXY_TICKER).any() and not out["ticker"].eq(CASH_PROXY_TICKER).any():
        residual_cash = max(0.0, 1.0 - float(out["current_weight"].sum()))
        if residual_cash > 1e-10:
            out = pd.concat(
                [
                    out,
                    pd.DataFrame(
                        [
                            {
                                "ticker": CASH_PROXY_TICKER,
                                "shares": np.nan,
                                "weight": residual_cash,
                                "target_weight": residual_cash,
                                "avg_cost": 1.0,
                                "reference_price": 1.0,
                                "entry_date": as_of_date,
                                "last_trade_date": as_of_date,
                                "manual_lock": False,
                                "min_hold_until": None,
                                "thesis_status": "cash",
                                "source": "derived_cash",
                                "notes": "Derived residual cash position.",
                                "current_weight": residual_cash,
                            }
                        ]
                    ),
                ],
                ignore_index=True,
                sort=False,
            )
    return out


def build_live_operator_plan(
    base_dir_or_paths: str | Path | Mapping[str, Any],
    *,
    strategy_version: str = "",
    run_id: str = "",
    run_ts: str = "",
    git_commit: str = "",
    config_fingerprint: str = "",
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, str]]:
    inputs = _load_inputs(base_dir_or_paths)
    state_paths = inputs["paths"]
    run_summary = inputs["run_summary"]
    portfolio_latest = _coerce_target_frame(inputs["portfolio_latest"])
    top30_latest = _coerce_top30_frame(inputs["top30_latest"])
    weights_payload = inputs["weights_payload"]
    _, bootstrapped = ensure_live_portfolio_state(
        base_dir_or_paths,
        weights_payload=weights_payload,
        portfolio_latest=inputs["portfolio_latest"],
        strategy_version=strategy_version,
    )
    state_payload = load_live_portfolio_state(base_dir_or_paths)
    latest_dt = pd.to_datetime(run_summary.get("latest_rebalance_date") or weights_payload.get("rebalance_date"), errors="coerce")
    current_positions = _infer_current_positions(
        state_payload,
        as_of_date=str(pd.Timestamp(latest_dt).date()) if pd.notna(latest_dt) else None,
    )
    current_map = {
        str(row.ticker): float(row.current_weight)
        for row in current_positions.itertuples(index=False)
        if pd.notna(row.current_weight) and float(row.current_weight) > 1e-10
    }
    target_map = {
        str(row.ticker): float(row.target_weight)
        for row in portfolio_latest[["ticker", "target_weight"]].itertuples(index=False)
        if pd.notna(row.target_weight) and float(row.target_weight) > 1e-10
    }
    run_action = str(run_summary.get("rebalance_action") or "").strip()
    policy_due = bool(run_summary.get("policy_rebalance_due", True))
    full_rebalance_due = policy_due or run_action in FULL_REBALANCE_ACTIONS
    defaults = _policy_defaults()

    current_lookup = (
        current_positions.drop_duplicates(subset=["ticker"], keep="first").set_index("ticker", drop=False)
        if not current_positions.empty
        else pd.DataFrame()
    )
    target_lookup = (
        portfolio_latest.drop_duplicates(subset=["ticker"], keep="first").set_index("ticker", drop=False)
        if not portfolio_latest.empty
        else pd.DataFrame()
    )
    top_lookup = (
        top30_latest.drop_duplicates(subset=["ticker"], keep="first").set_index("ticker", drop=False)
        if not top30_latest.empty
        else pd.DataFrame()
    )

    recommended_map = dict(current_map or target_map)
    recommended_map.setdefault(CASH_PROXY_TICKER, max(0.0, 1.0 - float(sum(v for k, v in recommended_map.items() if k != CASH_PROXY_TICKER))))
    universe_tickers = sorted(set(recommended_map) | set(target_map) | set(top_lookup.index if isinstance(top_lookup, pd.DataFrame) and not top_lookup.empty else []))

    rows: list[dict[str, Any]] = []
    intramonth_add_candidates: list[tuple[str, float]] = []
    cash_ticker = CASH_PROXY_TICKER
    min_trade = float(defaults["min_weight_trade_delta"])

    for ticker in universe_tickers:
        current_row = current_lookup.loc[ticker] if isinstance(current_lookup, pd.DataFrame) and not current_lookup.empty and ticker in current_lookup.index else None
        target_row = target_lookup.loc[ticker] if isinstance(target_lookup, pd.DataFrame) and not target_lookup.empty and ticker in target_lookup.index else None
        top_row = top_lookup.loc[ticker] if isinstance(top_lookup, pd.DataFrame) and not top_lookup.empty and ticker in top_lookup.index else None
        current_weight = float(current_map.get(ticker, 0.0))
        target_weight = float(target_map.get(ticker, 0.0))
        # --- Sleeve-aware thresholds ---
        sleeve = _resolve_sleeve(target_row, top_row)
        s_min_hold = _sleeve_threshold(sleeve, "min_hold_days", defaults)
        s_exit_loss = _sleeve_threshold(sleeve, "intramonth_exit_loss_threshold", defaults)
        s_exit_risk_thr = _sleeve_threshold(sleeve, "intramonth_exit_risk_threshold", defaults)
        s_support_floor = _sleeve_threshold(sleeve, "intramonth_hold_support_floor", defaults)
        s_rank_buffer = _sleeve_threshold(sleeve, "monthly_legacy_hold_rank_buffer", defaults)
        s_keep_weight = _sleeve_threshold(sleeve, "monthly_legacy_keep_max_weight", defaults)

        rank = _safe_float(top_row.get("rank") if top_row is not None else np.nan, default=np.nan)
        score = _safe_float(top_row.get("score") if top_row is not None else np.nan, default=np.nan)
        hold_support = _safe_float(
            (target_row.get("portfolio_hold_policy_support") if target_row is not None else np.nan),
            default=_safe_float(top_row.get("portfolio_hold_policy_support") if top_row is not None else np.nan, default=np.nan),
        )
        exit_risk = _safe_float(
            (target_row.get("portfolio_hold_policy_exit_risk") if target_row is not None else np.nan),
            default=_safe_float(top_row.get("portfolio_hold_policy_exit_risk") if top_row is not None else np.nan, default=np.nan),
        )
        manual_lock = bool(current_row.get("manual_lock")) if current_row is not None and "manual_lock" in current_row else False
        entry_date = current_row.get("entry_date") if current_row is not None else None
        held_days = _days_between(entry_date, latest_dt)
        avg_cost = _safe_float(current_row.get("avg_cost") if current_row is not None else np.nan, default=np.nan)
        ref_price = _safe_float(
            (target_row.get("current_price_live") if target_row is not None and "current_price_live" in target_row else np.nan),
            default=_safe_float(top_row.get("current_price_live") if top_row is not None else np.nan, default=np.nan),
        )
        if not np.isfinite(ref_price):
            ref_price = _safe_float(current_row.get("reference_price") if current_row is not None else np.nan, default=np.nan)
        unrealized_return = np.nan
        if np.isfinite(avg_cost) and avg_cost > 0 and np.isfinite(ref_price):
            unrealized_return = float(ref_price / avg_cost - 1.0)

        recommended_weight = current_weight
        action = "hold"
        action_reason = "Keep the current position until the next scheduled rebalance."

        if ticker == cash_ticker:
            recommended_weight = current_weight
            action = "hold_cash"
            action_reason = "Cash placeholder."
        elif manual_lock:
            action = "hold_locked"
            action_reason = "Manual lock enabled in live portfolio state."
        elif current_weight > 0 and target_weight > 0:
            if full_rebalance_due:
                recommended_weight = target_weight
                delta = target_weight - current_weight
                if abs(delta) < min_trade:
                    action = "hold"
                    action_reason = "Target drift is below the trade threshold."
                elif delta > 0:
                    action = "add"
                    action_reason = "Monthly rebalance increases the position toward the model target."
                else:
                    action = "reduce"
                    action_reason = "Monthly rebalance trims the position toward the model target."
            else:
                action = "hold_in_cycle"
                action_reason = "Target is still active; keep the existing size intramonth."
        elif current_weight > 0 and target_weight <= 0:
            if full_rebalance_due:
                keep_allowed = (
                    (np.isfinite(rank) and rank <= s_rank_buffer)
                    or (np.isfinite(hold_support) and hold_support >= s_support_floor)
                    or (np.isfinite(held_days) and held_days < s_min_hold)
                )
                if keep_allowed:
                    recommended_weight = min(current_weight, s_keep_weight)
                    action = "trim_legacy" if recommended_weight < current_weight - min_trade else "hold_legacy"
                    action_reason = f"Monthly rebalance keeps a residual legacy weight ({sleeve})."
                else:
                    recommended_weight = 0.0
                    action = "exit"
                    action_reason = f"Monthly rebalance exits a name no longer in target ({sleeve})."
            else:
                hard_exit = (
                    (np.isfinite(unrealized_return) and unrealized_return <= s_exit_loss)
                    or (np.isfinite(exit_risk) and exit_risk >= s_exit_risk_thr)
                )
                if hard_exit and (not np.isfinite(held_days) or held_days >= s_min_hold):
                    recommended_weight = 0.0
                    action = "exit_intramonth"
                    action_reason = f"Intramonth risk exit ({sleeve}: loss<={s_exit_loss:.0%} or risk>={s_exit_risk_thr:.0%})."
                else:
                    action = "hold_watch"
                    action_reason = "Not in the current target, but still held until the next scheduled rebalance."
        elif current_weight <= 0 and target_weight > 0:
            if full_rebalance_due:
                recommended_weight = target_weight
                action = "add"
                action_reason = "Monthly rebalance adds a new target position."
            else:
                if (
                    target_weight >= float(defaults["intramonth_new_position_weight"])
                    and np.isfinite(rank)
                    and rank <= float(defaults["intramonth_rank_max"])
                ):
                    intramonth_add_candidates.append((ticker, target_weight))
                    recommended_weight = 0.0
                    action = "watch_add"
                    action_reason = "Candidate intramonth add if exits or trims free enough capital."
                else:
                    recommended_weight = 0.0
                    action = "watch"
                    action_reason = "Watch-only until the next scheduled rebalance."

        rows.append(
            {
                "ticker": ticker,
                "sleeve_label": sleeve,
                "current_weight": current_weight,
                "target_weight_model": target_weight,
                "recommended_weight": recommended_weight,
                "rank": rank,
                "score": score,
                "held_days": held_days,
                "manual_lock": manual_lock,
                "avg_cost": avg_cost,
                "reference_price": ref_price,
                "unrealized_return": unrealized_return,
                "hold_policy_support": hold_support,
                "hold_policy_exit_risk": exit_risk,
                "entry_date": entry_date,
                "action": action,
                "action_reason": action_reason,
            }
        )

    plan = pd.DataFrame(rows)
    if plan.empty:
        plan = pd.DataFrame(columns=["ticker", "current_weight", "target_weight_model", "recommended_weight", "action", "action_reason"])

    if not full_rebalance_due and intramonth_add_candidates:
        current_cash = float(recommended_map.get(cash_ticker, 0.0))
        exit_funding = float(
            plan.loc[plan["current_weight"] > plan["recommended_weight"], "current_weight"].sum()
            - plan.loc[plan["current_weight"] > plan["recommended_weight"], "recommended_weight"].sum()
        )
        add_budget = max(current_cash + exit_funding - 0.01, 0.0)
        for ticker, target_weight in sorted(intramonth_add_candidates, key=lambda item: item[1], reverse=True):
            if add_budget < float(defaults["min_new_position_weight"]):
                break
            add_weight = min(float(defaults["intramonth_new_position_weight"]), float(target_weight), add_budget)
            if add_weight < float(defaults["min_new_position_weight"]):
                continue
            plan.loc[plan["ticker"] == ticker, "recommended_weight"] = add_weight
            plan.loc[plan["ticker"] == ticker, "action"] = "add_intramonth"
            plan.loc[plan["ticker"] == ticker, "action_reason"] = "Intramonth add funded by exits, trims, or available cash."
            add_budget -= add_weight

    recommended_map = {
        str(row.ticker): float(row.recommended_weight)
        for row in plan[["ticker", "recommended_weight"]].itertuples(index=False)
        if pd.notna(row.recommended_weight) and float(row.recommended_weight) > 1e-10
    }
    stock_weight_sum = float(sum(v for k, v in recommended_map.items() if k != cash_ticker))
    recommended_map[cash_ticker] = max(0.0, 1.0 - stock_weight_sum)
    total = float(sum(recommended_map.values()))
    if total > 0:
        recommended_map = {k: float(v / total) for k, v in recommended_map.items()}
    plan["recommended_weight"] = plan["ticker"].map(recommended_map).fillna(0.0)
    plan["weight_delta"] = plan["recommended_weight"] - plan["current_weight"]

    def _finalize_action(row: pd.Series) -> str:
        if str(row.get("ticker", "")) == cash_ticker:
            return str(row.get("action", "hold_cash"))
        existing = str(row.get("action", "hold"))
        delta = _safe_float(row.get("weight_delta"), default=0.0)
        if existing in {"hold", "hold_in_cycle", "hold_watch", "hold_locked", "hold_legacy", "hold_cash", "watch", "watch_add"}:
            return existing
        if abs(delta) < min_trade and existing in {"add", "reduce", "exit", "trim_legacy", "exit_intramonth", "add_intramonth"}:
            return "hold"
        if row.get("current_weight", 0.0) <= 1e-10 and row.get("recommended_weight", 0.0) > 1e-10:
            return "add" if full_rebalance_due else existing
        if row.get("current_weight", 0.0) > 1e-10 and row.get("recommended_weight", 0.0) <= 1e-10:
            return existing if existing.startswith("exit") else "exit"
        if delta > 0:
            return "add"
        if delta < 0:
            return "reduce"
        return "hold"

    plan["action"] = plan.apply(_finalize_action, axis=1)
    plan = plan.sort_values(["recommended_weight", "target_weight_model", "current_weight"], ascending=False).reset_index(drop=True)
    plan.insert(0, "decision_rank", np.arange(1, len(plan) + 1))

    summary = {
        "operator_policy_version": OPERATOR_POLICY_VERSION,
        "generated_at_utc": _now_utc_iso(),
        "run_ts": str(run_ts or ""),
        "strategy_version": str(strategy_version or state_payload.get("strategy_version") or ""),
        "engine_version": str(strategy_version or state_payload.get("strategy_version") or ""),
        "run_id": str(run_id or ""),
        "git_commit": str(git_commit or ""),
        "config_fingerprint": str(config_fingerprint or ""),
        "bootstrapped_state": bool(bootstrapped),
        "rebalance_action": run_action,
        "policy_rebalance_due": bool(policy_due),
        "full_rebalance_due": bool(full_rebalance_due),
        "current_position_count": int(sum(1 for k, v in current_map.items() if k != cash_ticker and float(v) > 1e-10)),
        "target_position_count": int(sum(1 for k, v in target_map.items() if k != cash_ticker and float(v) > 1e-10)),
        "recommended_position_count": int(sum(1 for k, v in recommended_map.items() if k != cash_ticker and float(v) > 1e-10)),
        "current_cash_weight": float(current_map.get(cash_ticker, 0.0)),
        "recommended_cash_weight": float(recommended_map.get(cash_ticker, 0.0)),
        "turnover_estimate": float(plan["weight_delta"].abs().sum() / 2.0) if not plan.empty else 0.0,
        "action_counts": {str(k): int(v) for k, v in plan["action"].value_counts().items()} if not plan.empty else {},
        "state_source": state_payload.get("state_source"),
        "state_sync_mode": "manual_apply_required",
        "state_sync_note": "Operator output is a recommendation only; live state is not auto-updated.",
    }

    ops_dir = state_paths["ops"]
    plan_path = ops_dir / "live_operator_plan_latest.csv"
    summary_path = ops_dir / "live_operator_summary.json"
    history_path = ops_dir / "live_operator_decision_history.parquet"
    plan.to_csv(plan_path, index=False)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if not plan.empty:
        hist = plan.copy()
        hist["generated_at_utc"] = summary["generated_at_utc"]
        _append_history_parquet(
            history_path,
            hist,
            dedupe_subset=["generated_at_utc", "ticker"],
            sort_columns=["generated_at_utc", "decision_rank"],
        )
    return plan, summary, {
        "live_operator_plan_latest.csv": str(plan_path),
        "live_operator_summary.json": str(summary_path),
        "live_operator_decision_history.parquet": str(history_path),
    }


def refresh_live_operator_outputs(
    base_dir_or_paths: str | Path | Mapping[str, Any],
    *,
    strategy_version: str = "",
    run_id: str = "",
    run_ts: str = "",
    git_commit: str = "",
    config_fingerprint: str = "",
) -> dict[str, Any]:
    plan, summary, output_files = build_live_operator_plan(
        base_dir_or_paths,
        strategy_version=strategy_version,
        run_id=run_id,
        run_ts=run_ts,
        git_commit=git_commit,
        config_fingerprint=config_fingerprint,
    )
    return {
        "plan": plan,
        "summary": summary,
        "output_files": output_files,
    }
