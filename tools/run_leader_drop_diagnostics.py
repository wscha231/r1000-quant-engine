#!/usr/bin/env python3
"""Diagnose where potential leaders drop out from universe to broker orders.

This sidecar is research/reporting only. It combines existing pre-filter
diagnostics, latest scored rows, target books, and account order previews into a
single gate map so missed leaders can be debugged without hardcoding tickers.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/leader_drop_diagnostics"
DEFAULT_WATCHLIST = "SNDK,INTC,AMD,ARM,ASML,MU,WDC,STX,LITE,CIEN,GEV,PLTR,NVDA,IONQ,RGTI,QBTS,ACHR,ASTS,LEU,SMR,OKLO"
CASH_TICKERS = {"CASH", "__CASH__"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text == "NAN" else text


def latest_by_ticker(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    if "rebalance_date" in d.columns:
        dates = pd.to_datetime(d["rebalance_date"], errors="coerce")
        if dates.notna().any():
            d = d.loc[dates.eq(dates.max())].copy()
    d["ticker"] = d["ticker"].map(ticker)
    d = d[(d["ticker"] != "") & (~d["ticker"].isin(CASH_TICKERS))].copy()
    return d.drop_duplicates("ticker", keep="first").set_index("ticker", drop=False)


def ticker_weight_map(path: Path, weight_cols: list[str] | None = None) -> dict[str, float]:
    frame = read_csv(path)
    if frame.empty or "ticker" not in frame.columns:
        return {}
    d = frame.copy()
    d["ticker"] = d["ticker"].map(ticker)
    weight_cols = weight_cols or ["weight", "target_weight", "recommended_weight"]
    weight_col = next((col for col in weight_cols if col in d.columns), "")
    if not weight_col:
        return {str(t): 0.0 for t in d["ticker"] if str(t)}
    d[weight_col] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0)
    return {
        str(row.ticker): float(getattr(row, weight_col))
        for row in d.itertuples(index=False)
        if str(row.ticker) and str(row.ticker) not in CASH_TICKERS
    }


def order_maps(latest_run: Path, portfolio: str) -> tuple[set[str], set[str], dict[str, str]]:
    base = latest_run / "account_ledger_preview" / portfolio
    actionable = read_csv(base / "orders_preview.csv")
    review = read_csv(base / "order_deltas_review.csv")
    actionable_tickers: set[str] = set()
    blocked_tickers: set[str] = set()
    status_map: dict[str, str] = {}
    if not actionable.empty and "ticker" in actionable.columns:
        for row in actionable.to_dict("records"):
            t = ticker(row.get("ticker"))
            if not t:
                continue
            actionable_tickers.add(t)
            status_map[t] = str(row.get("status") or "ready")
    if not review.empty and "ticker" in review.columns:
        for row in review.to_dict("records"):
            t = ticker(row.get("ticker"))
            if not t:
                continue
            status = str(row.get("status") or "")
            if status.startswith("blocked") or safe_float(row.get("quantity"), 0.0) <= 0:
                blocked_tickers.add(t)
                status_map[t] = status or "non_actionable"
    return actionable_tickers, blocked_tickers, status_map


def rank_scores(scored: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if scored.empty:
        return out
    score_cols = [
        col
        for col in [
            "score_total",
            "score",
            "concentrated_score",
            "portfolio_monster_early_score",
            "portfolio_future_winner_engine_score",
            "leader_onset_score",
            "early_evidence_score",
            "sec_form4_cluster_buy_score",
        ]
        if col in scored.columns
    ]
    for col in score_cols:
        values = pd.to_numeric(scored[col], errors="coerce")
        ranks = values.rank(ascending=False, method="min")
        for t, rank, value in zip(scored.index.astype(str), ranks, values):
            entry = out.setdefault(str(t), {})
            entry[f"{col}_rank"] = safe_float(rank)
            entry[col] = safe_float(value)
    return out


def parse_date(value: Any) -> pd.Timestamp | None:
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return None
    return pd.Timestamp(dt).normalize()


def first_date_by_ticker(frame: pd.DataFrame, date_cols: list[str], *, side: str | None = None) -> dict[str, str]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    d = frame.copy()
    if side is not None and "side" in d.columns:
        d = d[d["side"].astype(str).str.upper().eq(side.upper())].copy()
    date_col = next((col for col in date_cols if col in d.columns), "")
    if not date_col:
        return {}
    d["ticker"] = d["ticker"].map(ticker)
    d["_dt"] = pd.to_datetime(d[date_col], errors="coerce")
    d = d[(d["ticker"] != "") & d["_dt"].notna()].copy()
    if d.empty:
        return {}
    grouped = d.groupby("ticker")["_dt"].min()
    return {str(t): pd.Timestamp(dt).date().isoformat() for t, dt in grouped.items()}


def historical_candidate_stats(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    d = frame.copy()
    if "rebalance_date" not in d.columns:
        return {}
    d["ticker"] = d["ticker"].map(ticker)
    d["_dt"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d[(d["ticker"] != "") & d["_dt"].notna()].copy()
    if d.empty:
        return {}
    for col in [
        "portfolio_monster_early_score",
        "portfolio_future_winner_engine_score",
        "portfolio_early_scout_engine_score",
        "rs_acceleration_score",
        "period_forward_return",
    ]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    out: dict[str, dict[str, Any]] = {}
    for t, group in d.groupby("ticker", sort=False):
        g = group.sort_values("_dt").copy()
        onset_mask = pd.Series(False, index=g.index)
        if "portfolio_monster_early_score" in g.columns:
            onset_mask = onset_mask | g["portfolio_monster_early_score"].fillna(0.0).ge(0.58)
        if "portfolio_future_winner_engine_score" in g.columns:
            onset_mask = onset_mask | g["portfolio_future_winner_engine_score"].fillna(0.0).ge(0.65)
        if "rs_acceleration_score" in g.columns:
            onset_mask = onset_mask | g["rs_acceleration_score"].fillna(0.0).ge(0.65)
        onset = g[onset_mask].head(1)
        first = g.iloc[0]
        best_forward = safe_float(g.get("period_forward_return", pd.Series(dtype=float)).max(), math.nan)
        if not onset.empty:
            onset_row = onset.iloc[0]
            onset_dt = pd.Timestamp(onset_row["_dt"]).date().isoformat()
            onset_forward = safe_float(onset_row.get("period_forward_return"), math.nan)
        else:
            onset_dt = ""
            onset_forward = math.nan
        out[str(t)] = {
            "first_scored_date": pd.Timestamp(first["_dt"]).date().isoformat(),
            "first_onset_signal_date": onset_dt,
            "missed_return_after_onset": onset_forward if math.isfinite(onset_forward) else best_forward,
            "best_historical_forward_return": best_forward,
            "historical_candidate_months": int(len(g)),
        }
    return out


def target_history_maps(latest_run: Path) -> dict[str, str]:
    paths = [
        latest_run / "reports" / "operating_main_target_book.csv",
        latest_run / "reports" / "operating_concentrated_target_book.csv",
        latest_run / "reports" / "main_monthly_weights.csv",
        latest_run / "reports" / "concentrated_strategy_holdings.csv",
        latest_run / "reports" / "weekly_leader_main_target_book.csv",
        latest_run / "reports" / "weekly_leader_concentrated_target_book.csv",
    ]
    merged: dict[str, str] = {}
    for path in paths:
        dates = first_date_by_ticker(read_csv(path), ["rebalance_date", "date", "signal_date"])
        for t, dt in dates.items():
            if t not in merged or dt < merged[t]:
                merged[t] = dt
    return merged


def broker_trade_history(latest_run: Path, side: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    for portfolio in ["main", "concentrated"]:
        dates = first_date_by_ticker(read_csv(latest_run / "broker_replay" / portfolio / "trades.csv"), ["date", "fill_date"], side=side)
        for t, dt in dates.items():
            if t not in merged or dt < merged[t]:
                merged[t] = dt
    return merged


def boolish(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def prefilter_reason(row: dict[str, Any]) -> str:
    explicit = str(row.get("drop_reason") or "").strip()
    if explicit:
        return explicit
    for col, reason in [
        ("failed_min_price", "failed_min_price"),
        ("failed_dollar_vol", "failed_dollar_vol"),
        ("failed_mktcap", "failed_mktcap"),
        ("failed_vol_252", "failed_vol_252"),
        ("failed_dd_1y", "failed_dd_1y"),
        ("failed_rank_size", "failed_rank_size"),
    ]:
        if boolish(row.get(col)):
            return reason
    return ""


def classify(row: dict[str, Any]) -> str:
    if row.get("in_main_target") or row.get("in_concentrated_target"):
        if row.get("has_actionable_order"):
            return "selected_target_actionable_order"
        if row.get("has_blocked_delta"):
            return "selected_target_order_blocked_or_zero"
        return "selected_target_no_order_needed_or_no_preview_delta"
    if not row.get("in_scored_universe") and row.get("in_prefilter"):
        reason = str(row.get("prefilter_drop_reason") or "filtered_before_scoring")
        return f"filtered_before_scoring:{reason}"
    if not row.get("in_scored_universe"):
        return "not_in_latest_universe_or_missing_data"
    gate = str(row.get("portfolio_candidate_gate_label") or "").lower()
    if gate and "reject" in gate:
        return "candidate_gate_rejected"
    if safe_float(row.get("portfolio_risk_entry_block_score"), 0.0) >= 0.75:
        return "risk_entry_blocked"
    if safe_float(row.get("portfolio_stale_mega_leader_score"), 0.0) >= 0.75:
        return "stale_leader_blocked"
    if safe_float(row.get("portfolio_monster_early_score"), 0.0) >= 0.58:
        return "monster_candidate_not_selected"
    return "rank_or_cap_not_selected"


def build_rows(latest_run: Path, watchlist: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pre = latest_by_ticker(read_csv(latest_run / "reports" / "leader_drop_diagnostics_latest.csv"))
    scored = latest_by_ticker(read_csv(latest_run / "scored_latest.csv"))
    replay_frame = read_csv(latest_run / "reports" / "candidate_replay_book.csv")
    replay = latest_by_ticker(replay_frame)
    if scored.empty and not replay.empty:
        scored = replay
    main_target = ticker_weight_map(latest_run / "portfolio_latest.csv")
    concentrated_target = ticker_weight_map(latest_run / "concentrated_portfolio_latest.csv")
    main_preview_target = ticker_weight_map(latest_run / "account_ledger_preview" / "main" / "target_weights.csv", ["target_weight"])
    conc_preview_target = ticker_weight_map(latest_run / "account_ledger_preview" / "concentrated" / "target_weights.csv", ["target_weight"])
    main_actionable, main_blocked, main_status = order_maps(latest_run, "main")
    conc_actionable, conc_blocked, conc_status = order_maps(latest_run, "concentrated")
    ranks = rank_scores(scored)
    candidate_history = historical_candidate_stats(replay_frame)
    first_target_dates = target_history_maps(latest_run)
    first_buy_dates = broker_trade_history(latest_run, "BUY")
    first_sell_dates = broker_trade_history(latest_run, "SELL")

    all_tickers = set(pre.index.astype(str)) | set(scored.index.astype(str)) | set(main_target) | set(concentrated_target)
    all_tickers |= set(main_preview_target) | set(conc_preview_target)
    all_tickers |= set(candidate_history) | set(first_target_dates) | set(first_buy_dates)
    all_tickers |= {ticker(t) for t in watchlist if ticker(t)}
    rows: list[dict[str, Any]] = []
    for t in sorted(all_tickers):
        prow = pre.loc[t].to_dict() if t in pre.index else {}
        srow = scored.loc[t].to_dict() if t in scored.index else {}
        row: dict[str, Any] = {
            "ticker": t,
            "Name": srow.get("Name", srow.get("name", prow.get("Name", ""))),
            "sector": srow.get("sector", prow.get("sector", "")),
            "source_universe": srow.get("source_universe", prow.get("universe_source", "")),
            "in_prefilter": bool(prow),
            "in_scored_universe": bool(srow),
            "in_main_target": t in main_target,
            "in_concentrated_target": t in concentrated_target,
            "main_target_weight": main_target.get(t, 0.0),
            "concentrated_target_weight": concentrated_target.get(t, 0.0),
            "main_preview_target_weight": main_preview_target.get(t, 0.0),
            "concentrated_preview_target_weight": conc_preview_target.get(t, 0.0),
            "has_actionable_order": t in main_actionable or t in conc_actionable,
            "has_blocked_delta": t in main_blocked or t in conc_blocked,
            "main_order_status": main_status.get(t, ""),
            "concentrated_order_status": conc_status.get(t, ""),
            "prefilter_drop_reason": prefilter_reason(prow),
            "first_scored_date": candidate_history.get(t, {}).get("first_scored_date", ""),
            "first_onset_signal_date": candidate_history.get(t, {}).get("first_onset_signal_date", ""),
            "first_target_date": first_target_dates.get(t, ""),
            "first_broker_buy_date": first_buy_dates.get(t, ""),
            "first_broker_exit_date": first_sell_dates.get(t, ""),
            "missed_return_after_onset": candidate_history.get(t, {}).get("missed_return_after_onset", math.nan),
            "best_historical_forward_return": candidate_history.get(t, {}).get("best_historical_forward_return", math.nan),
            "historical_candidate_months": candidate_history.get(t, {}).get("historical_candidate_months", 0),
        }
        for col in [
            "price_cache_exists",
            "price_cache_last_date",
            "price_cache_stale_days",
            "failed_min_price",
            "failed_dollar_vol",
            "failed_mktcap",
            "failed_vol_252",
            "failed_dd_1y",
            "failed_rank_size",
            "px",
            "dollar_vol_20d",
            "mktcap",
            "dd_1y",
        ]:
            row[col] = prow.get(col, "")
        for col in [
            "portfolio_sleeve_label",
            "portfolio_candidate_gate_label",
            "portfolio_defensive_rotation_action",
            "portfolio_monster_early_score",
            "portfolio_stale_mega_leader_score",
            "portfolio_risk_entry_block_score",
            "rs_acceleration_score",
            "oneil_leadership_score",
            "industry_group_strength_score",
            "relative_strength_composite",
            "period_forward_return",
        ]:
            row[col] = srow.get(col, "")
        row.update(ranks.get(t, {}))
        row["drop_reason"] = classify(row)
        rows.append(row)

    reason_counts = Counter(str(row.get("drop_reason")) for row in rows)
    gate_counts = Counter(str(row.get("drop_reason")).split(":", 1)[0] for row in rows)
    missed = [
        row for row in rows
        if not row.get("in_main_target")
        and not row.get("in_concentrated_target")
        and (
            safe_float(row.get("portfolio_monster_early_score"), 0.0) >= 0.58
            or safe_float(row.get("rs_acceleration_score"), 0.0) >= 0.65
            or safe_float(row.get("portfolio_future_winner_engine_score"), 0.0) >= 0.65
            or safe_float(row.get("period_forward_return"), 0.0) >= 0.25
        )
    ]
    missed = sorted(
        missed,
        key=lambda row: (
            safe_float(row.get("portfolio_future_winner_engine_score"), 0.0),
            safe_float(row.get("portfolio_monster_early_score"), 0.0),
            safe_float(row.get("period_forward_return"), 0.0),
        ),
        reverse=True,
    )[:100]
    summary = {
        "status": "completed",
        "schema_version": "leader-drop-diagnostics-v1",
        "research_only": True,
        "production_activation_allowed": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "rows": len(rows),
        "watchlist_count": len([t for t in watchlist if ticker(t)]),
        "reason_counts": dict(reason_counts),
        "gate_counts": dict(gate_counts),
        "missed_leader_candidate_count": len(missed),
        "source_files": {
            "prefilter_diagnostics": str(latest_run / "reports" / "leader_drop_diagnostics_latest.csv"),
            "scored_latest": str(latest_run / "scored_latest.csv"),
            "candidate_replay_book": str(latest_run / "reports" / "candidate_replay_book.csv"),
            "main_target": str(latest_run / "portfolio_latest.csv"),
            "concentrated_target": str(latest_run / "concentrated_portfolio_latest.csv"),
        },
    }
    return rows, summary | {"missed_leader_candidates": missed}


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Leader Drop Diagnostics",
        "",
        "Research-only diagnostic. It does not change target weights.",
        "",
        f"- status: `{summary.get('status')}`",
        f"- rows: {summary.get('rows')}",
        f"- missed leader candidates: {summary.get('missed_leader_candidate_count')}",
        "",
        "## Gate Counts",
        "",
    ]
    for gate, count in sorted((summary.get("gate_counts") or {}).items(), key=lambda item: (-int(item[1]), item[0])):
        lines.append(f"- `{gate}`: {count}")
    lines.extend(["", "## Drop Reasons", ""])
    for reason, count in sorted((summary.get("reason_counts") or {}).items(), key=lambda item: (-int(item[1]), item[0])):
        lines.append(f"- `{reason}`: {count}")
    lines.append("")
    return "\n".join(lines)


def run(latest_run: str | Path = DEFAULT_LATEST_RUN, output_dir: str | Path = DEFAULT_OUTPUT_DIR, watchlist: str = DEFAULT_WATCHLIST) -> dict[str, Any]:
    latest = repo_path(latest_run)
    out = repo_path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    watch = [ticker(t) for t in str(watchlist or "").replace(";", ",").split(",") if ticker(t)]
    rows, payload = build_rows(latest, watch)
    missed = payload.pop("missed_leader_candidates", [])
    pd.DataFrame(rows).to_csv(out / "leader_drop_by_gate.csv", index=False)
    pd.DataFrame(missed).to_csv(out / "missed_leader_candidates.csv", index=False)
    write_json(out / "leader_drop_summary.json", payload)
    (out / "leader_drop_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--watchlist", default=DEFAULT_WATCHLIST)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(args.latest_run, args.output_dir, args.watchlist)
    print(json.dumps({"status": payload.get("status"), "rows": payload.get("rows")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
