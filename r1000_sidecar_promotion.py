#!/usr/bin/env python3
"""Promotion bridge for AlphaOps research sidecar target books.

The bridge intentionally separates three concerns:

* shadow review: show what integrated targets would do without production writes
* promotion checks: record per-portfolio gate status
* approved promotion: copy a previously validated target book into the
  operating target-book path before broker replay runs
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import DISABLE_CONCENTRATED_CHAMPION_FILTERS, replay as broker_replay  # noqa: E402


PORTFOLIOS = ("main", "concentrated")
CASH_TICKERS = {"CASH", "__CASH__"}
H_CASE_LABEL = "multi_lane_crisis_hold_replace"
SOURCE_INTEGRATED_H = "integrated_h"
SOURCE_MARKET_LEADER = "market_leader"
SOURCE_POLICIES = {SOURCE_INTEGRATED_H, SOURCE_MARKET_LEADER}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "sha256": "", "size": 0}
    return {"path": str(path), "exists": True, "sha256": file_sha256(path), "size": int(path.stat().st_size)}


def operating_target_book(latest_run: Path, portfolio: str) -> Path:
    name = "operating_concentrated_target_book.csv" if portfolio == "concentrated" else "operating_main_target_book.csv"
    return latest_run / "reports" / name


def default_policy_example() -> dict[str, Any]:
    return {
        "schema_version": "alphaops-approved-target-policy-v1",
        "approved_portfolios": [],
        "source_run_id": "",
        "source_policy_main": SOURCE_INTEGRATED_H,
        "source_policy_concentrated": SOURCE_INTEGRATED_H,
        "source_case_id_main": "H",
        "source_case_id_concentrated": "H",
        "source_target_book_path_main": "",
        "source_target_book_path_concentrated": "",
        "source_target_book_sha256_main": "",
        "source_target_book_sha256_concentrated": "",
        "main": {
            "approved": False,
            "source_policy": SOURCE_INTEGRATED_H,
            "source_case_id": "H",
            "manual_gate_override": False,
            "allow_stale_holding_exit_override": False,
            "manual_gate_override_reason": "",
        },
        "concentrated": {
            "approved": False,
            "source_policy": SOURCE_INTEGRATED_H,
            "source_case_id": "H",
            "manual_gate_override": False,
            "allow_stale_holding_exit_override": False,
            "manual_gate_override_reason": "",
        },
        "human_approved": False,
        "approved_by": "",
        "approved_at": "",
        "production_mutation_allowed": False,
        "allow_replace_operating_target_books": False,
        "required_metric_mode": "broker_ledger_next_close",
        "notes": "Default is false. Approve only a previously validated source target book.",
    }


def market_leader_concentrated_policy_example() -> dict[str, Any]:
    payload = default_policy_example()
    payload.update(
        {
            "approved_portfolios": ["concentrated"],
            "source_policy_concentrated": SOURCE_MARKET_LEADER,
            "source_case_id_concentrated": "market_leader",
            "source_target_book_path_concentrated": "outputs/market_leader_challenger/concentrated_target_book.csv",
            "notes": "Example only. Fill source_target_book_sha256_concentrated from the previously validated artifact before approval.",
        }
    )
    payload["concentrated"] = {
        "approved": False,
        "source_policy": SOURCE_MARKET_LEADER,
        "source_case_id": "market_leader",
        "source_target_book_path": "outputs/market_leader_challenger/concentrated_target_book.csv",
        "source_target_book_sha256": "",
        "manual_gate_override": False,
        "allow_stale_holding_exit_override": False,
        "manual_gate_override_reason": "Concentrated production holdings are stale versus approved Market Leader target.",
    }
    return payload


def ensure_promotion_dirs(output_root: Path) -> dict[str, Path]:
    paths = {
        "shadow": output_root / "shadow_operating",
        "operator": output_root / "operator_review",
        "promotion": output_root / "promotion_review",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    example = paths["promotion"] / "approved_target_policy.example.json"
    if not example.exists():
        write_json(example, default_policy_example())
    ml_example = paths["promotion"] / "approved_market_leader_concentrated_policy.example.json"
    if not ml_example.exists():
        write_json(ml_example, market_leader_concentrated_policy_example())
    return paths


def normalize_target_book(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["rebalance_date", "ticker", "weight"])
    d = frame.copy()
    if "target_weight" in d.columns and "weight" not in d.columns:
        d["weight"] = d["target_weight"]
    for col in ("rebalance_date", "ticker", "weight"):
        if col not in d.columns:
            d[col] = 0.0 if col == "weight" else ""
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["ticker"] = d["ticker"].map(clean_ticker)
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    d = d[(d["ticker"] != "") & (d["weight"] > 1e-12)].copy()
    d["rebalance_date"] = d["rebalance_date"].dt.date.astype(str)
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def h_case_target_path(integrated_dir: Path, portfolio: str) -> Path:
    return integrated_dir / "crisis_adjusted_target_books" / f"{portfolio}_H_{H_CASE_LABEL}_target_book.csv"


def market_leader_target_path(latest_run: Path, portfolio: str) -> Path:
    return latest_run / "market_leader_challenger" / f"{portfolio}_target_book.csv"


def load_h_case_target(integrated_dir: Path, portfolio: str) -> tuple[pd.DataFrame, Path, str]:
    direct = h_case_target_path(integrated_dir, portfolio)
    if direct.exists():
        return normalize_target_book(read_csv(direct)), direct, "crisis_adjusted_target_book"
    lane = integrated_dir / "lane_target_book.csv"
    frame = normalize_target_book(read_csv(lane))
    if frame.empty:
        return frame, direct, "missing"
    raw = read_csv(lane)
    if "case_id" in raw.columns:
        raw = raw[raw["case_id"].astype(str).eq("H")].copy()
    if "portfolio_kind" in raw.columns:
        raw = raw[raw["portfolio_kind"].astype(str).eq(portfolio)].copy()
    return normalize_target_book(raw), lane, "lane_target_book_filtered"


def load_market_leader_target(latest_run: Path, portfolio: str) -> tuple[pd.DataFrame, Path, str]:
    path = market_leader_target_path(latest_run, portfolio)
    if not path.exists():
        return pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]), path, "missing"
    return normalize_target_book(read_csv(path)), path, "market_leader_target_book"


def load_target_source(
    *,
    latest_run: Path,
    integrated_dir: Path,
    portfolio: str,
    source_policy: str,
) -> tuple[pd.DataFrame, Path, str]:
    policy = source_policy if source_policy in SOURCE_POLICIES else SOURCE_INTEGRATED_H
    if policy == SOURCE_MARKET_LEADER:
        return load_market_leader_target(latest_run, portfolio)
    return load_h_case_target(integrated_dir, portfolio)


def read_positions(latest_run: Path, portfolio: str) -> pd.DataFrame:
    candidates = [
        latest_run / "broker_replay" / portfolio / "positions_latest.csv",
        latest_run / "operating_snapshot" / "current_operating_holdings_latest.csv",
        latest_run / "user_current" / "01_current_holdings.csv",
    ]
    for path in candidates:
        frame = read_csv(path)
        if frame.empty:
            continue
        d = frame.copy()
        if "portfolio_kind" in d.columns:
            d = d[d["portfolio_kind"].astype(str).eq(portfolio)].copy()
        if d.empty:
            continue
        if "ticker" not in d.columns:
            continue
        d["ticker"] = d["ticker"].map(clean_ticker)
        if "current_weight" not in d.columns and "weight" in d.columns:
            d["current_weight"] = d["weight"]
        if "current_value_usd" not in d.columns and "market_value_usd" in d.columns:
            d["current_value_usd"] = d["market_value_usd"]
        if "current_shares" not in d.columns and "shares" in d.columns:
            d["current_shares"] = d["shares"]
        if "current_weight" not in d.columns:
            total = pd.to_numeric(d.get("current_value_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()
            d["current_weight"] = pd.to_numeric(d.get("current_value_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0) / max(total, 1e-12)
        d["current_weight"] = pd.to_numeric(d["current_weight"], errors="coerce").fillna(0.0)
        d["current_value_usd"] = pd.to_numeric(d.get("current_value_usd", 0.0), errors="coerce").fillna(0.0)
        return d[d["ticker"].ne("")].copy()
    return pd.DataFrame(columns=["ticker", "current_weight", "current_value_usd", "current_shares"])


def latest_target_weights(target: pd.DataFrame) -> dict[str, float]:
    d = normalize_target_book(target)
    if d.empty:
        return {}
    latest = pd.to_datetime(d["rebalance_date"], errors="coerce").max()
    part = d[pd.to_datetime(d["rebalance_date"], errors="coerce").eq(latest)].copy()
    part = part[~part["ticker"].isin(CASH_TICKERS)].copy()
    grouped = part.groupby("ticker", as_index=False)["weight"].sum()
    return {str(row.ticker).upper(): float(row.weight) for row in grouped.itertuples(index=False)}


def classify_action(current_weight: float, target_weight: float) -> str:
    eps = 0.0025
    if current_weight > eps and target_weight <= eps:
        return "FULL_EXIT"
    if current_weight <= eps and target_weight > eps:
        return "ADD"
    if target_weight > current_weight + eps:
        return "INCREASE"
    if current_weight > target_weight + eps:
        return "TRIM"
    if current_weight > eps or target_weight > eps:
        return "HOLD"
    return "NO_CHANGE"


def projected_holdings_for_source(latest_run: Path, integrated_dir: Path, *, source_policy: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for portfolio in PORTFOLIOS:
        target, target_path, target_source = load_target_source(
            latest_run=latest_run,
            integrated_dir=integrated_dir,
            portfolio=portfolio,
            source_policy=source_policy,
        )
        target_weights = latest_target_weights(target)
        current = read_positions(latest_run, portfolio)
        current_map = {str(row.get("ticker")).upper(): row for row in current.to_dict("records")}
        total_value = float(pd.to_numeric(current.get("current_value_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
        if total_value <= 0:
            total_value = 100000.0
        for ticker in sorted(set(current_map) | set(target_weights)):
            if ticker in CASH_TICKERS:
                continue
            cur = current_map.get(ticker, {})
            current_weight = safe_float(cur.get("current_weight"))
            target_weight = safe_float(target_weights.get(ticker))
            action = classify_action(current_weight, target_weight)
            rows.append(
                {
                    "portfolio": portfolio,
                    "ticker": ticker,
                    "current_weight": current_weight,
                    "integrated_target_weight": target_weight,
                    "delta_weight": target_weight - current_weight,
                    "projected_weight": target_weight,
                    "action": action,
                    "current_value": safe_float(cur.get("current_value_usd"), current_weight * total_value),
                    "projected_value": target_weight * total_value,
                    "reason": f"{source_policy}_target:{target_source}",
                    "review_flag": "operator_review_only",
                    "source_policy": source_policy,
                    "source_target_book_path": str(target_path),
                }
            )
    return pd.DataFrame(rows)


def projected_holdings(latest_run: Path, integrated_dir: Path) -> pd.DataFrame:
    return projected_holdings_for_source(latest_run, integrated_dir, source_policy=SOURCE_INTEGRATED_H)


def projected_orders(projected: pd.DataFrame) -> pd.DataFrame:
    if projected.empty:
        return pd.DataFrame()
    out = projected.copy()
    out["order_side"] = out["delta_weight"].apply(lambda x: "BUY" if safe_float(x) > 0 else ("SELL" if safe_float(x) < 0 else "NONE"))
    out["order_review_action"] = out["action"].map(
        {
            "FULL_EXIT": "FULL_EXIT_REVIEW",
            "TRIM": "TRIM_REVIEW",
            "ADD": "ADD_REVIEW",
            "INCREASE": "INCREASE_REVIEW",
            "HOLD": "HOLD_REVIEW",
            "NO_CHANGE": "NO_CHANGE",
        }
    )
    return out


def promotion_gate_from_files(latest_run: Path, integrated_dir: Path) -> dict[str, Any]:
    acceptance = read_csv(integrated_dir / "acceptance_gate_report.csv")
    ab = read_csv(integrated_dir / "ab_matrix.csv")
    replay_gate = read_json(integrated_dir / "replay_gate_status.json")
    promotion_gate = read_json(integrated_dir / "promotion_gate_status.json")
    rows: dict[str, Any] = {}
    for portfolio in PORTFOLIOS:
        blockers: list[str] = []
        accepted = acceptance[
            acceptance.get("portfolio_kind", pd.Series(dtype=str)).astype(str).eq(portfolio)
            & acceptance.get("case_id", pd.Series(dtype=str)).astype(str).eq("H")
        ].copy()
        ab_row = ab[
            ab.get("portfolio_kind", pd.Series(dtype=str)).astype(str).eq(portfolio)
            & ab.get("case_id", pd.Series(dtype=str)).astype(str).eq("H")
        ].copy()
        if accepted.empty and ab_row.empty:
            blockers.append("missing_H_case_gate_data")
        if not accepted.empty:
            status = str(accepted.iloc[0].get("acceptance_status") or "")
            if status != "passed":
                blockers.extend(
                    [
                        item
                        for item in str(accepted.iloc[0].get("acceptance_blockers") or "").split(",")
                        if item
                    ]
                )
        if not ab_row.empty:
            rec = ab_row.iloc[0].to_dict()
            if str(rec.get("status") or "") != "completed":
                blockers.append("H_case_not_completed")
            if str(rec.get("metric_mode") or "") != "broker_ledger_next_close":
                blockers.append("metric_mode_not_broker_ledger_next_close")
            if portfolio == "concentrated":
                if str(rec.get("target_book_filter_source") or "") == "default_static":
                    blockers.append("concentrated_default_static_filter")
                actual_n = safe_float(rec.get("actual_median_position_count"), math.nan)
                if not math.isfinite(actual_n) or int(round(actual_n)) not in {3, 5}:
                    blockers.append("concentrated_actual_n_not_3_or_5")
        target, target_path, target_source = load_h_case_target(integrated_dir, portfolio)
        if target.empty:
            blockers.append("missing_source_target_book")
        rows[portfolio] = {
            "status": "passed" if not blockers else "rejected",
            "case_id": "H",
            "blockers": sorted(set(blockers)),
            "source_target_book_path": str(target_path),
            "source_target_book_sha256": file_sha256(target_path) if target_path.exists() else "",
            "source_target_book_mode": target_source,
            "target_row_count": int(len(target)),
        }
    market_leader_review: dict[str, Any] = {}
    for portfolio in PORTFOLIOS:
        ml_target, ml_path, ml_source = load_market_leader_target(latest_run, portfolio)
        latest_weights = latest_target_weights(ml_target)
        market_leader_review[portfolio] = {
            "source_policy": SOURCE_MARKET_LEADER,
            "source_target_book_path": str(ml_path),
            "source_target_book_sha256": file_sha256(ml_path) if ml_path.exists() else "",
            "source_target_book_mode": ml_source,
            "target_row_count": int(len(ml_target)),
            "latest_tickers": sorted(latest_weights),
            "review_only": True,
            "note": "Market Leader source is separate from integrated H; production use still requires explicit policy, sha match, env flag, and gate pass or manual override.",
        }
    combined = "passed" if rows["main"]["status"] == "passed" and rows["concentrated"]["status"] == "passed" else "rejected"
    return {
        "schema_version": "alphaops-sidecar-promotion-check-v1",
        "generated_at_utc": now_utc(),
        "status": combined,
        "main_promotion_gate": rows["main"],
        "concentrated_promotion_gate": rows["concentrated"],
        "market_leader_review": market_leader_review,
        "combined_promotion_gate": {
            "status": combined,
            "production_activation_allowed": False,
            "reason": "portfolio gates are independent; explicit approved policy is still required",
        },
        "replay_gate_status": replay_gate.get("status", "missing"),
        "integrated_promotion_gate_status": promotion_gate.get("status", "missing"),
        "latest_run": str(latest_run),
        "integrated_dir": str(integrated_dir),
    }


def run_check_promotion(*, latest_run: Path, integrated_dir: Path, output_root: Path) -> dict[str, Any]:
    paths = ensure_promotion_dirs(output_root)
    payload = promotion_gate_from_files(latest_run, integrated_dir)
    write_json(paths["promotion"] / "integrated_target_promotion_check.json", payload)
    return payload


def _run_shadow_for_source(
    *,
    latest_run: Path,
    integrated_dir: Path,
    price_cache: Path,
    output_root: Path,
    source_policy: str,
    mode: str,
    projected_filename: str,
    orders_filename: str,
    diff_filename: str,
    shadow_prefix: str,
    target_prefix: str,
    cost_bps: float = 25.0,
    max_fill_lag_days: int = 7,
) -> dict[str, Any]:
    paths = ensure_promotion_dirs(output_root)
    promotion_status = "not_requested"
    if source_policy == SOURCE_INTEGRATED_H:
        promotion = run_check_promotion(latest_run=latest_run, integrated_dir=integrated_dir, output_root=output_root)
        promotion_status = str(promotion.get("status") or "missing")
    projected = projected_holdings_for_source(latest_run, integrated_dir, source_policy=source_policy)
    write_csv(paths["operator"] / projected_filename, projected)
    write_csv(paths["operator"] / orders_filename, projected_orders(projected))
    write_csv(paths["operator"] / diff_filename, projected)
    target_dir = paths["shadow"] / "target_books"
    metrics: dict[str, Any] = {}
    for portfolio in PORTFOLIOS:
        target, _target_path, source = load_target_source(
            latest_run=latest_run,
            integrated_dir=integrated_dir,
            portfolio=portfolio,
            source_policy=source_policy,
        )
        if target.empty:
            metrics[portfolio] = {"status": "blocked", "reason": f"missing_{source_policy}_target_book", "source": source}
            continue
        target_path = target_dir / f"{target_prefix}_{portfolio}_target_book.csv"
        write_csv(target_path, target)
        replay_root = "broker_replay" if shadow_prefix == "integrated" else f"{shadow_prefix}_broker_replay"
        out_dir = paths["shadow"] / replay_root / portfolio
        try:
            metrics[portfolio] = broker_replay(
                target_book=target_path,
                price_cache=price_cache,
                output_dir=out_dir,
                portfolio_kind=portfolio,
                fill_mode="next_close",
                cost_bps=cost_bps,
                integer_shares=True,
                max_fill_lag_days=max_fill_lag_days,
                concentrated_champion_filters=DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy() if portfolio == "concentrated" else None,
            )
        except Exception as exc:
            metrics[portfolio] = {"status": "error", "reason": str(exc), "metric_mode": "DO_NOT_USE"}
            out_dir.mkdir(parents=True, exist_ok=True)
            write_json(out_dir / "metrics.json", metrics[portfolio])
        latest_positions = out_dir / "positions_latest.csv"
        if latest_positions.exists():
            dest_name = f"{shadow_prefix}_{portfolio}_current_holdings.csv"
            shutil.copy2(latest_positions, paths["shadow"] / dest_name)
    payload = {
        "schema_version": "alphaops-sidecar-shadow-v1",
        "generated_at_utc": now_utc(),
        "status": "completed",
        "mode": mode,
        "source_policy": source_policy,
        "production_mutated": False,
        "promotion_check_status": promotion_status,
        "shadow_metrics": metrics,
        "projected_holdings_path": str(paths["operator"] / projected_filename),
    }
    write_json(paths["shadow"] / f"{shadow_prefix}_shadow_broker_metrics.json", payload)
    write_json(paths["promotion"] / "sidecar_promotion_bridge_status.json", payload)
    return payload


def run_shadow(
    *,
    latest_run: Path,
    integrated_dir: Path,
    price_cache: Path,
    output_root: Path,
    cost_bps: float = 25.0,
    max_fill_lag_days: int = 7,
) -> dict[str, Any]:
    return _run_shadow_for_source(
        latest_run=latest_run,
        integrated_dir=integrated_dir,
        price_cache=price_cache,
        output_root=output_root,
        source_policy=SOURCE_INTEGRATED_H,
        mode="integrated_shadow",
        projected_filename="projected_holdings_after_integrated_target.csv",
        orders_filename="projected_orders_from_integrated_target.csv",
        diff_filename="sidecar_vs_current_diff.csv",
        shadow_prefix="integrated",
        target_prefix="integrated_H",
        cost_bps=cost_bps,
        max_fill_lag_days=max_fill_lag_days,
    )


def run_market_leader_shadow(
    *,
    latest_run: Path,
    integrated_dir: Path,
    price_cache: Path,
    output_root: Path,
    cost_bps: float = 25.0,
    max_fill_lag_days: int = 7,
) -> dict[str, Any]:
    return _run_shadow_for_source(
        latest_run=latest_run,
        integrated_dir=integrated_dir,
        price_cache=price_cache,
        output_root=output_root,
        source_policy=SOURCE_MARKET_LEADER,
        mode="market_leader_shadow",
        projected_filename="projected_holdings_after_market_leader_target.csv",
        orders_filename="projected_orders_from_market_leader_target.csv",
        diff_filename="market_leader_vs_current_diff.csv",
        shadow_prefix="market_leader",
        target_prefix="market_leader",
        cost_bps=cost_bps,
        max_fill_lag_days=max_fill_lag_days,
    )


def load_policy(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not payload:
        return default_policy_example()
    return payload


def policy_portfolio_approved(policy: dict[str, Any], portfolio: str) -> bool:
    approved_portfolios = {str(x) for x in policy.get("approved_portfolios") or []}
    specific = policy.get(portfolio, {}) if isinstance(policy.get(portfolio), dict) else {}
    return portfolio in approved_portfolios and bool(specific.get("approved", True))


def source_policy_from_policy(policy: dict[str, Any], portfolio: str) -> str:
    key = f"source_policy_{portfolio}"
    specific = policy.get(portfolio, {}) if isinstance(policy.get(portfolio), dict) else {}
    value = str(specific.get("source_policy") or policy.get(key) or SOURCE_INTEGRATED_H).strip().lower()
    return value if value in SOURCE_POLICIES else SOURCE_INTEGRATED_H


def source_case_id_from_policy(policy: dict[str, Any], portfolio: str) -> str:
    key = f"source_case_id_{portfolio}"
    specific = policy.get(portfolio, {}) if isinstance(policy.get(portfolio), dict) else {}
    return str(specific.get("source_case_id") or policy.get(key) or ("market_leader" if source_policy_from_policy(policy, portfolio) == SOURCE_MARKET_LEADER else "H"))


def source_path_from_policy(policy: dict[str, Any], portfolio: str, *, latest_run: Path | None = None, integrated_dir: Path | None = None) -> Path:
    key = f"source_target_book_path_{portfolio}"
    specific = policy.get(portfolio, {}) if isinstance(policy.get(portfolio), dict) else {}
    configured = str(specific.get("source_target_book_path") or policy.get(key) or "")
    if configured:
        return repo_path(configured)
    source_policy = source_policy_from_policy(policy, portfolio)
    if source_policy == SOURCE_MARKET_LEADER and latest_run is not None:
        return market_leader_target_path(latest_run, portfolio)
    if integrated_dir is not None:
        return h_case_target_path(integrated_dir, portfolio)
    return repo_path("")


def source_sha_from_policy(policy: dict[str, Any], portfolio: str) -> str:
    key = f"source_target_book_sha256_{portfolio}"
    specific = policy.get(portfolio, {}) if isinstance(policy.get(portfolio), dict) else {}
    return str(specific.get("source_target_book_sha256") or policy.get(key) or "")


def manual_gate_override_from_policy(policy: dict[str, Any], portfolio: str) -> tuple[bool, str]:
    specific = policy.get(portfolio, {}) if isinstance(policy.get(portfolio), dict) else {}
    enabled = bool(specific.get("manual_gate_override")) and bool(specific.get("allow_stale_holding_exit_override"))
    reason = str(specific.get("manual_gate_override_reason") or "").strip()
    return bool(enabled and reason), reason


def snapshot(paths: list[Path]) -> dict[str, Any]:
    return {str(path): file_record(path) for path in paths}


def run_approved_integrated(*, latest_run: Path, output_root: Path, policy_path: Path, integrated_dir: Path) -> dict[str, Any]:
    paths = ensure_promotion_dirs(output_root)
    policy = load_policy(policy_path)
    existing_check = paths["promotion"] / "integrated_target_promotion_check.json"
    promotion = read_json(existing_check)
    if not promotion:
        promotion = run_check_promotion(latest_run=latest_run, integrated_dir=integrated_dir, output_root=output_root)
    blockers: list[str] = []
    if os.environ.get("ALLOW_PRODUCTION_MUTATION") != "1":
        blockers.append("ALLOW_PRODUCTION_MUTATION_env_not_set")
    for field in ("human_approved", "production_mutation_allowed", "allow_replace_operating_target_books"):
        if not bool(policy.get(field)):
            blockers.append(f"policy_{field}_false")
    approved_portfolios = [p for p in PORTFOLIOS if policy_portfolio_approved(policy, p)]
    if not approved_portfolios:
        blockers.append("no_approved_portfolios")

    backup_dir = paths["promotion"] / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    operating_paths = [operating_target_book(latest_run, p) for p in PORTFOLIOS]
    before = snapshot(operating_paths)
    actual_changes: list[dict[str, Any]] = []
    if blockers:
        payload = {
            "schema_version": "alphaops-production-mutation-audit-v1",
            "generated_at_utc": now_utc(),
            "mode": "approved_integrated",
            "status": "blocked",
            "blockers": blockers,
            "allowed_changes": [],
            "actual_changes": [],
            "unexpected_changes": [],
            "before": before,
        }
        write_json(paths["promotion"] / "production_mutation_audit.json", payload)
        write_json(
            paths["promotion"] / "sidecar_promotion_bridge_status.json",
            {
                "schema_version": "alphaops-sidecar-promotion-bridge-v1",
                "generated_at_utc": now_utc(),
                "mode": "approved_integrated",
                "status": "blocked",
                "production_mutated": False,
                "blockers": blockers,
            },
        )
        return payload

    copy_plan: list[dict[str, Any]] = []
    for portfolio in approved_portfolios:
        gate = promotion.get(f"{portfolio}_promotion_gate", {})
        override_allowed, override_reason = manual_gate_override_from_policy(policy, portfolio)
        gate_override_used = False
        if gate.get("status") != "passed":
            if not override_allowed:
                blockers.append(f"{portfolio}_promotion_gate_not_passed")
                continue
            gate_override_used = True
        source_policy = source_policy_from_policy(policy, portfolio)
        source_case_id = source_case_id_from_policy(policy, portfolio)
        source = source_path_from_policy(policy, portfolio, latest_run=latest_run, integrated_dir=integrated_dir)
        expected_sha = source_sha_from_policy(policy, portfolio)
        if not source.is_file():
            blockers.append(f"{portfolio}_source_target_book_missing")
            continue
        actual_sha = file_sha256(source)
        if not expected_sha or actual_sha != expected_sha:
            blockers.append(f"{portfolio}_source_target_book_sha_mismatch")
            continue
        dest = operating_target_book(latest_run, portfolio)
        if not dest.exists():
            blockers.append(f"{portfolio}_operating_target_book_missing")
            continue
        copy_plan.append(
            {
                "portfolio": portfolio,
                "source": source,
                "destination": dest,
                "source_sha256": actual_sha,
                "source_policy": source_policy,
                "source_case_id": source_case_id,
                "gate_override_used": gate_override_used,
                "gate_override_reason": override_reason if gate_override_used else "",
                "promotion_gate_status": gate.get("status", "missing"),
            }
        )

    if blockers:
        payload = {
            "schema_version": "alphaops-production-mutation-audit-v1",
            "generated_at_utc": now_utc(),
            "mode": "approved_integrated",
            "status": "blocked",
            "policy_path": str(policy_path),
            "approved_portfolios": approved_portfolios,
            "allowed_changes": [],
            "actual_changes": [],
            "unexpected_changes": [],
            "blockers": sorted(set(blockers)),
            "before": before,
        }
        write_json(paths["promotion"] / "production_mutation_audit.json", payload)
        write_json(
            paths["promotion"] / "sidecar_promotion_bridge_status.json",
            {
                "schema_version": "alphaops-sidecar-promotion-bridge-v1",
                "generated_at_utc": now_utc(),
                "mode": "approved_integrated",
                "status": "blocked",
                "production_mutated": False,
                "blockers": sorted(set(blockers)),
            },
        )
        return payload

    for item in copy_plan:
        portfolio = str(item["portfolio"])
        source = Path(item["source"])
        dest = Path(item["destination"])
        backup = backup_dir / f"{dest.stem}.before_approved_integrated.csv"
        shutil.copy2(dest, backup)
        shutil.copy2(source, dest)
        actual_changes.append(
            {
                "portfolio": portfolio,
                "source": str(source),
                "destination": str(dest),
                "backup": str(backup),
                "source_sha256": str(item["source_sha256"]),
                "source_policy": str(item.get("source_policy") or ""),
                "source_case_id": str(item.get("source_case_id") or ""),
                "promotion_gate_status": str(item.get("promotion_gate_status") or ""),
                "gate_override_used": bool(item.get("gate_override_used")),
                "gate_override_reason": str(item.get("gate_override_reason") or ""),
            }
        )

    after = snapshot(operating_paths)
    allowed = {str(operating_target_book(latest_run, p)) for p in approved_portfolios}
    unexpected = [
        path
        for path, rec in after.items()
        if before.get(path, {}).get("sha256") != rec.get("sha256") and path not in allowed
    ]
    status = "applied" if actual_changes and not blockers and not unexpected else ("blocked" if blockers else "failed")
    payload = {
        "schema_version": "alphaops-production-mutation-audit-v1",
        "generated_at_utc": now_utc(),
        "mode": "approved_integrated",
        "status": status,
        "policy_path": str(policy_path),
        "approved_portfolios": approved_portfolios,
        "source_run_id": policy.get("source_run_id", ""),
        "source_case_id_main": policy.get("source_case_id_main", ""),
        "source_case_id_concentrated": policy.get("source_case_id_concentrated", ""),
        "allowed_changes": sorted(allowed),
        "actual_changes": actual_changes,
        "unexpected_changes": unexpected,
        "blockers": sorted(set(blockers)),
        "before": before,
        "after": after,
        "next_step": "broker_replay_must_run_after_this_hook_in_same_full_rebuild" if actual_changes else "",
    }
    write_json(paths["promotion"] / "production_mutation_audit.json", payload)
    write_json(
        paths["promotion"] / "sidecar_promotion_bridge_status.json",
        {
            "schema_version": "alphaops-sidecar-promotion-bridge-v1",
            "generated_at_utc": now_utc(),
            "mode": "approved_integrated",
            "status": payload.get("status"),
            "production_mutated": bool(payload.get("status") == "applied"),
            "blockers": payload.get("blockers", []),
        },
    )
    if status != "applied":
        return payload
    return payload


def rollback_targets(*, latest_run: Path, output_root: Path, rerun: bool = False, price_cache: Path | None = None) -> dict[str, Any]:
    paths = ensure_promotion_dirs(output_root)
    backup_dir = paths["promotion"] / "backups"
    restored: list[dict[str, Any]] = []
    for portfolio in PORTFOLIOS:
        dest = operating_target_book(latest_run, portfolio)
        backup = backup_dir / f"{dest.stem}.before_approved_integrated.csv"
        if backup.exists():
            shutil.copy2(backup, dest)
            restored.append({"portfolio": portfolio, "backup": str(backup), "destination": str(dest)})
    rerun_status: dict[str, Any] = {"requested": bool(rerun), "executed": False}
    if rerun:
        commands = [
            [sys.executable, "tools/run_broker_ledger_replay.py", "--target-book", "outputs/reports/operating_main_target_book.csv", "--price-cache", str(price_cache or "cache_prices"), "--portfolio-kind", "main", "--output-dir", "outputs/broker_replay/main", "--fill-mode", "next_close", "--cost-bps", "25", "--max-fill-lag-days", "7"],
            [sys.executable, "tools/run_broker_ledger_replay.py", "--target-book", "outputs/reports/operating_concentrated_target_book.csv", "--price-cache", str(price_cache or "cache_prices"), "--portfolio-kind", "concentrated", "--output-dir", "outputs/broker_replay/concentrated", "--fill-mode", "next_close", "--cost-bps", "25", "--max-fill-lag-days", "7"],
            [sys.executable, "tools/run_account_evaluation.py", "--latest-run", "outputs", "--output-dir", "outputs/account_evaluation"],
            [sys.executable, "tools/run_user_current_report.py", "--latest-run", "outputs", "--price-cache", str(price_cache or "cache_prices"), "--output-dir", "outputs/user_current", "--strict"],
        ]
        results = []
        for cmd in commands:
            proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False, capture_output=True, text=True)
            results.append({"cmd": cmd, "returncode": proc.returncode, "stdout_tail": proc.stdout[-1000:], "stderr_tail": proc.stderr[-1000:]})
        rerun_status = {"requested": True, "executed": True, "results": results}
    payload = {
        "schema_version": "alphaops-sidecar-rollback-v1",
        "generated_at_utc": now_utc(),
        "status": "completed" if restored else "blocked",
        "restored": restored,
        "rerun": rerun_status,
    }
    write_json(paths["promotion"] / "rollback_status.json", payload)
    return payload


def run_production_baseline(*, latest_run: Path, integrated_dir: Path, output_root: Path) -> dict[str, Any]:
    paths = ensure_promotion_dirs(output_root)
    payload = {
        "schema_version": "alphaops-sidecar-promotion-bridge-v1",
        "generated_at_utc": now_utc(),
        "mode": "production_baseline",
        "status": "completed",
        "production_mutated": False,
        "promotion_check_status": "not_requested",
        "message": "Production baseline mode leaves operating target books unchanged.",
    }
    write_json(paths["promotion"] / "sidecar_promotion_bridge_status.json", payload)
    return payload
