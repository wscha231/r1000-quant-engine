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
DEFAULT_WATCHLIST = "SNDK,INTC,AMD,MU,WDC,STX,LITE,CIEN,GEV,PLTR,NVDA,IONQ,RGTI,QBTS,ACHR,ASTS,LEU,SMR,OKLO"
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
    score_cols = [col for col in ["score_total", "score", "concentrated_score", "portfolio_monster_early_score", "portfolio_future_winner_engine_score"] if col in scored.columns]
    for col in score_cols:
        values = pd.to_numeric(scored[col], errors="coerce")
        ranks = values.rank(ascending=False, method="min")
        for t, rank, value in zip(scored.index.astype(str), ranks, values):
            entry = out.setdefault(str(t), {})
            entry[f"{col}_rank"] = safe_float(rank)
            entry[col] = safe_float(value)
    return out


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
    replay = latest_by_ticker(read_csv(latest_run / "reports" / "candidate_replay_book.csv"))
    if scored.empty and not replay.empty:
        scored = replay
    main_target = ticker_weight_map(latest_run / "portfolio_latest.csv")
    concentrated_target = ticker_weight_map(latest_run / "concentrated_portfolio_latest.csv")
    main_preview_target = ticker_weight_map(latest_run / "account_ledger_preview" / "main" / "target_weights.csv", ["target_weight"])
    conc_preview_target = ticker_weight_map(latest_run / "account_ledger_preview" / "concentrated" / "target_weights.csv", ["target_weight"])
    main_actionable, main_blocked, main_status = order_maps(latest_run, "main")
    conc_actionable, conc_blocked, conc_status = order_maps(latest_run, "concentrated")
    ranks = rank_scores(scored)

    all_tickers = set(pre.index.astype(str)) | set(scored.index.astype(str)) | set(main_target) | set(concentrated_target)
    all_tickers |= set(main_preview_target) | set(conc_preview_target)
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
