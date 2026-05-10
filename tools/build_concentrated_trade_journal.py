#!/usr/bin/env python3
"""Build a champion-only concentrated trade journal for AutoLearning.

The concentrated backtest writes a full grid of monthly holdings. That is good
for research, but it is too broad for the learner: N=1/N=2 experiments should
not be treated as the production concentrated history when the validated
champion is N=3 score_power. This sidecar filters the grid to the current
champion and emits the same trade/grade files as the main trade journal.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_config import ENGINE_REUSE_VERSION, EngineConfig  # noqa: E402
from r1000_pipeline import select_concentrated_champion_comparison  # noqa: E402
from r1000_trade_journal import (  # noqa: E402
    SIGNAL_BREAKDOWN_COLUMNS,
    grade_trades,
    pair_entries_with_exits,
    persist_holdings_history,
    summary_digest,
)


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/concentrated_trade_journal"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if np.isnan(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def champion_row(compare: pd.DataFrame) -> dict[str, Any]:
    if compare.empty:
        return {}
    cfg = EngineConfig(base_dir=REPO_ROOT)
    champion = select_concentrated_champion_comparison(cfg, compare)
    if champion.empty:
        return {}
    return {str(k): v for k, v in champion.iloc[0].to_dict().items()}


def filter_champion_frame(df: pd.DataFrame, champion: dict[str, Any]) -> pd.DataFrame:
    if df.empty or not champion:
        return pd.DataFrame()
    out = df.copy()
    target_n = int(safe_float(champion.get("target_stock_names"), safe_float(champion.get("target_n"), 0)))
    weighting_mode = str(champion.get("weighting_mode") or "")
    interval = int(safe_float(champion.get("rebalance_interval_months"), 1))
    mask = pd.Series(True, index=out.index)
    if target_n > 0:
        n_col = "target_stock_names" if "target_stock_names" in out.columns else "target_n"
        if n_col in out.columns:
            mask &= pd.to_numeric(out[n_col], errors="coerce").fillna(-1).astype(int).eq(target_n)
    if weighting_mode and "weighting_mode" in out.columns:
        mask &= out["weighting_mode"].fillna("").astype(str).eq(weighting_mode)
    interval_col = "active_rebalance_interval_months"
    if interval_col not in out.columns and "rebalance_interval_months" in out.columns:
        interval_col = "rebalance_interval_months"
    if interval_col in out.columns:
        mask &= pd.to_numeric(out[interval_col], errors="coerce").fillna(-1).astype(int).eq(interval)
    return out.loc[mask].copy()


def add_regime_state(holdings: pd.DataFrame, latest_run: Path) -> pd.DataFrame:
    if holdings.empty or "regime_state" in holdings.columns:
        return holdings
    regime = read_csv(latest_run / "reports" / "regime_by_month.csv")
    if regime.empty or "rebalance_date" not in regime.columns:
        holdings["regime_state"] = "neutral"
        holdings["regime_state_score"] = 0
        return holdings
    reg_cols = ["rebalance_date"]
    for col in ["regime_label", "regime_state", "regime_state_score"]:
        if col in regime.columns:
            reg_cols.append(col)
    reg = regime[reg_cols].drop_duplicates("rebalance_date").copy()
    reg["rebalance_date"] = pd.to_datetime(reg["rebalance_date"], errors="coerce")
    holdings = holdings.copy()
    holdings["rebalance_date"] = pd.to_datetime(holdings["rebalance_date"], errors="coerce")
    if "regime_state" not in reg.columns and "regime_label" in reg.columns:
        reg["regime_state"] = reg["regime_label"]
    if "regime_state_score" not in reg.columns:
        reg["regime_state_score"] = 0
    merged = holdings.merge(
        reg[["rebalance_date", "regime_state", "regime_state_score"]],
        on="rebalance_date",
        how="left",
    )
    merged["regime_state"] = merged["regime_state"].fillna("neutral")
    merged["regime_state_score"] = pd.to_numeric(merged["regime_state_score"], errors="coerce").fillna(0).astype(int)
    return merged


def signal_breakdown(row: pd.Series) -> str:
    payload: dict[str, float] = {}
    for col in SIGNAL_BREAKDOWN_COLUMNS:
        payload[col] = safe_float(row.get(col), 0.0)
    return json.dumps(payload, sort_keys=True)


def normalize_holdings(holdings: pd.DataFrame, latest_run: Path) -> pd.DataFrame:
    if holdings.empty:
        return holdings
    out = holdings.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date", "ticker"]).copy()
    out["portfolio_sleeve_label"] = "concentrated_alpha"
    out["portfolio_sleeve_role"] = "concentrated_alpha"
    out["portfolio_selection_path"] = out.get("concentrated_selection_source", "concentrated_champion")
    if "raw_score" not in out.columns:
        out["raw_score"] = pd.to_numeric(out.get("concentrated_score", 0.0), errors="coerce").fillna(0.0)
    if "period_forward_return" not in out.columns:
        out["period_forward_return"] = pd.to_numeric(
            out.get("risk_adjusted_forward_return", out.get("raw_period_forward_return", 0.0)),
            errors="coerce",
        ).fillna(0.0)
    if "weighted_forward_return" not in out.columns:
        out["weighted_forward_return"] = (
            pd.to_numeric(out.get("weight", 0.0), errors="coerce").fillna(0.0)
            * pd.to_numeric(out["period_forward_return"], errors="coerce").fillna(0.0)
        )
    out = add_regime_state(out, latest_run)
    out["entry_signal_breakdown"] = out.apply(signal_breakdown, axis=1)
    out["source_journal"] = "concentrated_champion"
    return out


def build(latest_run: Path, output_dir: Path) -> dict[str, Any]:
    reports = latest_run / "reports"
    compare = read_csv(reports / "concentrated_strategy_comparison.csv")
    holdings = read_csv(reports / "concentrated_strategy_holdings.csv")
    monthly = read_csv(reports / "concentrated_strategy_monthly.csv")
    champ = champion_row(compare)
    selected_holdings = normalize_holdings(filter_champion_frame(holdings, champ), latest_run)
    selected_monthly = filter_champion_frame(monthly, champ)
    output_dir.mkdir(parents=True, exist_ok=True)

    if selected_holdings.empty:
        payload = {
            "status": "blocked_missing_champion_holdings",
            "latest_run": str(latest_run),
            "output_dir": str(output_dir),
            "champion": champ,
            "research_only": True,
        }
        write_json(output_dir / "summary.json", payload)
        return payload

    benchmark_returns = pd.DataFrame()
    if not selected_monthly.empty and {"rebalance_date", "bench_return"}.issubset(selected_monthly.columns):
        benchmark_returns = selected_monthly[["rebalance_date", "bench_return"]].copy()

    paths = {"outputs": output_dir.parent, "trade_journal_dir": output_dir}
    persist_holdings_history(selected_holdings, paths, ENGINE_REUSE_VERSION)
    trades = pair_entries_with_exits(selected_holdings, paths, ENGINE_REUSE_VERSION, benchmark_returns=benchmark_returns)
    grades = grade_trades(trades, paths) if trades is not None and not trades.empty else pd.DataFrame()
    digest = summary_digest(grades) if grades is not None and not grades.empty else {"n_trades": 0}
    payload = {
        "status": "completed",
        "latest_run": str(latest_run),
        "output_dir": str(output_dir),
        "research_only": True,
        "source": "concentrated_strategy_grid_champion",
        "champion": {
            "target_stock_names": int(safe_float(champ.get("target_stock_names"), 0)),
            "weighting_mode": str(champ.get("weighting_mode") or ""),
            "rebalance_interval_months": int(safe_float(champ.get("rebalance_interval_months"), 1)),
            "strategy_cagr": safe_float(champ.get("strategy_cagr")),
            "sharpe": safe_float(champ.get("sharpe")),
            "max_dd": safe_float(champ.get("max_dd")),
        },
        "holding_rows": int(len(selected_holdings)),
        "monthly_rows": int(len(selected_monthly)),
        "trade_digest": digest,
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    payload = build(repo_path(args.latest_run), repo_path(args.output_dir))
    print(f"[concentrated-trade-journal] status={payload.get('status')} wrote {repo_path(args.output_dir)}")
    return 0 if payload.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
