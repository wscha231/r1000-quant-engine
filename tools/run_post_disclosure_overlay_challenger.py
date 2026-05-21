#!/usr/bin/env python3
"""Build post-disclosure evidence overlays and run broker-ledger challengers.

This C4 sidecar joins 13F/Form 4/ETF event rows to a PIT candidate replay book
by `available_from <= rebalance_date`. It emits shadow post-disclosure scores
and can feed them into the existing alpha-selector broker grid. It never
modifies production scores or target books.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alpha_selector_broker_grid import run as run_alpha_selector_grid  # noqa: E402

DEFAULT_CANDIDATE_BOOK = "cloud_results/full_rebuild/latest_global_alpha_universe/reports/candidate_replay_book.csv"
DEFAULT_13F_EVENTS = "data_pit/sec/13f_position_events.parquet"
DEFAULT_FORM4_EVENTS = "data_pit/sec/form4_transaction_events.parquet"
DEFAULT_ETF_EVENTS = "data_pit/etf_holdings/etf_holding_events.parquet"
DEFAULT_OUTPUT_DIR = "outputs/post_disclosure_overlay_challenger"

PDA_COLUMNS = [
    "pda_13f_event_score",
    "pda_13f_event_count",
    "pda_13f_new_or_add_score",
    "pda_13f_new_or_add_count",
    "pda_13f_first_buy_surprise_score",
    "pda_13f_first_buy_surprise_count",
    "pda_form4_event_score",
    "pda_form4_event_count",
    "pda_form4_open_market_buy_score",
    "pda_form4_open_market_buy_count",
    "pda_etf_event_score",
    "pda_etf_event_count",
    "pda_etf_new_or_increase_score",
    "pda_etf_new_or_increase_count",
    "pda_event_convergence_score",
    "pda_negative_event_score",
    "post_disclosure_alpha_score",
    "post_disclosure_discovery_score",
    "post_disclosure_mega_confirmation_score",
    "pda_size_discovery_score",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def safe_pct(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def size_discovery_score(value: float) -> float:
    try:
        mcap = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(mcap) or mcap < 300_000_000:
        return 0.0
    if mcap < 2_000_000_000:
        return 1.0
    if mcap < 10_000_000_000:
        return 0.85
    if mcap < 50_000_000_000:
        return 0.55
    if mcap < 200_000_000_000:
        return 0.25
    return 0.10


def mega_confirmation_size_score(value: float) -> float:
    try:
        mcap = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(mcap) or mcap <= 0:
        return 0.0
    if mcap >= 200_000_000_000:
        return 1.0
    if mcap >= 50_000_000_000:
        return 0.70
    if mcap >= 10_000_000_000:
        return 0.45
    if mcap >= 2_000_000_000:
        return 0.20
    return 0.05


def prepare_candidate_book(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns or "rebalance_date" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d = d[d["ticker"].ne("") & d["rebalance_date"].notna()].copy()
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def normalize_events(events: pd.DataFrame, *, source: str, score_col: str) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["ticker", "available_from_ts", "event_score", "source", "event_type"])
    d = events.copy()
    d["ticker"] = d.get("ticker", d.get("holding_ticker", "")).fillna("").astype(str).str.upper().str.strip()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True).dt.tz_convert(None)
    d["event_score"] = numeric(d, score_col, 0.0).clip(-1.0, 1.0)
    d["source"] = source
    d["event_type"] = d.get("event_type", d.get("form4_event_type", "")).fillna("").astype(str).str.lower().str.strip()
    d = d[d["ticker"].ne("") & d["available_from_ts"].notna()].copy()
    if "history_boundary" in d.columns:
        d["history_boundary"] = d["history_boundary"].fillna(False).astype(bool)
    else:
        d["history_boundary"] = False
    keep = ["ticker", "available_from_ts", "event_score", "source", "event_type", "history_boundary"]
    for optional in [
        "position_weight",
        "position_rank",
        "manager_conviction_rank",
        "value_delta_to_mcap",
        "manager_stake_to_float",
        "holding_weight",
        "holding_weight_delta",
        "etf_consensus_count",
        "transaction_value_to_mcap",
        "transaction_shares_to_float",
            "cluster_buy_score",
        ]:
        if optional in d.columns:
            d[optional] = pd.to_numeric(d[optional], errors="coerce").fillna(0.0)
            keep.append(optional)
    if source == "13f":
        conviction = numeric(d, "manager_conviction_rank", 0.0).clip(0.0, 1.0)
        position_weight = numeric(d, "position_weight", 0.0).clip(lower=0.0)
        value_delta_to_mcap = numeric(d, "value_delta_to_mcap", 0.0).clip(lower=0.0)
        manager_stake_to_float = numeric(d, "manager_stake_to_float", 0.0).clip(lower=0.0)
        position_weight_score = (position_weight / 0.05).clip(0.0, 1.0)
        issuer_impact_score = pd.concat(
            [(value_delta_to_mcap / 0.01).clip(0.0, 1.0), (manager_stake_to_float / 0.02).clip(0.0, 1.0)],
            axis=1,
        ).max(axis=1)
        d["first_buy_surprise_score"] = (
            0.35 * d["event_score"].clip(lower=0.0)
            + 0.25 * conviction
            + 0.20 * position_weight_score
            + 0.20 * issuer_impact_score
        ).fillna(0.0).clip(0.0, 1.0)
        keep.append("first_buy_surprise_score")
    return d[keep]


def event_features_by_date(
    events: pd.DataFrame,
    candidate_dates: list[pd.Timestamp],
    *,
    prefix: str,
    lookback_days: int,
    event_half_life_days: float = 63.0,
) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["rebalance_date", "ticker", f"{prefix}_event_score", f"{prefix}_event_count", f"{prefix}_negative_event_score"])
    rows: list[dict[str, Any]] = []
    for dt in sorted({pd.Timestamp(x).normalize() for x in candidate_dates}):
        end = dt + pd.Timedelta(hours=23, minutes=59, seconds=59)
        start = end - pd.Timedelta(days=int(lookback_days))
        window = events[(events["available_from_ts"] <= end) & (events["available_from_ts"] >= start)].copy()
        if window.empty:
            continue
        age_days = (end - window["available_from_ts"]).dt.total_seconds().clip(lower=0.0) / 86400.0
        half_life = float(event_half_life_days or 0.0)
        if half_life > 0:
            window["event_recency_weight"] = np.power(0.5, age_days / half_life).clip(0.0, 1.0)
        else:
            window["event_recency_weight"] = 1.0
        for ticker, group in window.groupby("ticker"):
            score = numeric(group, "event_score", 0.0)
            recency_weight = numeric(group, "event_recency_weight", 1.0).clip(0.0, 1.0)
            weighted_score = score * recency_weight
            positive = float(weighted_score[weighted_score > 0].sum())
            negative = float(abs(weighted_score[weighted_score < 0].sum()))
            event_type = group.get("event_type", pd.Series("", index=group.index)).astype(str).str.lower()
            new_add_mask = event_type.isin(["new", "add"])
            history_boundary = group.get("history_boundary", pd.Series(False, index=group.index)).astype(bool)
            first_buy_mask = event_type.eq("new") & (~history_boundary)
            form4_buy_mask = event_type.isin(["open_market_purchase", "p"])
            etf_new_mask = event_type.isin(["inclusion", "weight_increase"])
            if "first_buy_surprise_score" in group.columns:
                first_buy_surprise = pd.to_numeric(group["first_buy_surprise_score"], errors="coerce").fillna(0.0)
            else:
                first_buy_surprise = score.clip(lower=0.0)
            first_buy_surprise = first_buy_surprise * recency_weight
            rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    f"{prefix}_event_score": safe_pct(positive),
                    f"{prefix}_event_count": int(len(group)),
                    f"{prefix}_negative_event_score": safe_pct(negative),
                    f"{prefix}_new_or_add_score": safe_pct(float(weighted_score[new_add_mask].clip(lower=0.0).sum())),
                    f"{prefix}_new_or_add_count": int(new_add_mask.sum()),
                    f"{prefix}_first_buy_surprise_score": safe_pct(float(first_buy_surprise[first_buy_mask].sum())),
                    f"{prefix}_first_buy_surprise_count": int(first_buy_mask.sum()),
                    f"{prefix}_open_market_buy_score": safe_pct(float(weighted_score[form4_buy_mask].clip(lower=0.0).sum())),
                    f"{prefix}_open_market_buy_count": int(form4_buy_mask.sum()),
                    f"{prefix}_new_or_increase_score": safe_pct(float(weighted_score[etf_new_mask].clip(lower=0.0).sum())),
                    f"{prefix}_new_or_increase_count": int(etf_new_mask.sum()),
                    f"{prefix}_latest_available_from": group["available_from_ts"].max().isoformat(),
                    f"{prefix}_event_recency_weight_avg": float(recency_weight.mean()),
                }
            )
    return pd.DataFrame(rows)


def merge_features(base: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    if features.empty:
        return base
    return base.merge(features, on=["rebalance_date", "ticker"], how="left")


def add_post_disclosure_overlay(
    candidates: pd.DataFrame,
    events_13f: pd.DataFrame,
    events_form4: pd.DataFrame,
    events_etf: pd.DataFrame,
    *,
    lookback_days: int,
    event_half_life_days: float = 63.0,
) -> pd.DataFrame:
    d = prepare_candidate_book(candidates)
    if d.empty:
        return pd.DataFrame()
    dates = list(pd.to_datetime(d["rebalance_date"], errors="coerce").dropna().unique())
    f13 = normalize_events(events_13f, source="13f", score_col="post_disclosure_event_seed_score")
    f4 = normalize_events(events_form4, source="form4", score_col="post_disclosure_event_seed_score")
    etf = normalize_events(events_etf, source="etf", score_col="etf_event_seed_score")
    d = merge_features(d, event_features_by_date(f13, dates, prefix="pda_13f", lookback_days=lookback_days, event_half_life_days=event_half_life_days))
    d = merge_features(d, event_features_by_date(f4, dates, prefix="pda_form4", lookback_days=lookback_days, event_half_life_days=event_half_life_days))
    d = merge_features(d, event_features_by_date(etf, dates, prefix="pda_etf", lookback_days=lookback_days, event_half_life_days=event_half_life_days))
    for col in PDA_COLUMNS:
        if col not in d.columns:
            d[col] = 0.0
    for source in ("pda_13f", "pda_form4", "pda_etf"):
        neg_col = f"{source}_negative_event_score"
        if neg_col not in d.columns:
            d[neg_col] = 0.0
        d[f"{source}_event_score"] = numeric(d, f"{source}_event_score", 0.0).clip(0.0, 1.0)
        d[f"{source}_event_count"] = numeric(d, f"{source}_event_count", 0.0).clip(lower=0.0)
        for suffix in [
            "new_or_add_score",
            "new_or_add_count",
            "first_buy_surprise_score",
            "first_buy_surprise_count",
            "open_market_buy_score",
            "open_market_buy_count",
            "new_or_increase_score",
            "new_or_increase_count",
        ]:
            col = f"{source}_{suffix}"
            if col not in d.columns:
                d[col] = 0.0
            d[col] = numeric(d, col, 0.0).clip(lower=0.0)
        d[neg_col] = numeric(d, neg_col, 0.0).clip(0.0, 1.0)
    source_count = (
        (d["pda_13f_event_score"] > 0.05).astype(int)
        + (d["pda_form4_event_score"] > 0.05).astype(int)
        + (d["pda_etf_event_score"] > 0.05).astype(int)
    )
    d["pda_event_convergence_score"] = (source_count / 3.0).clip(0.0, 1.0)
    d["pda_negative_event_score"] = (
        numeric(d, "pda_13f_negative_event_score", 0.0)
        + numeric(d, "pda_form4_negative_event_score", 0.0)
        + numeric(d, "pda_etf_negative_event_score", 0.0)
    ).clip(0.0, 1.0)
    d["post_disclosure_alpha_score"] = (
        0.34 * d["pda_13f_event_score"]
        + 0.34 * d["pda_form4_event_score"]
        + 0.20 * d["pda_etf_event_score"]
        + 0.12 * d["pda_event_convergence_score"]
        - 0.15 * d["pda_negative_event_score"]
    ).fillna(0.0).clip(0.0, 1.0)
    mcap = pd.concat(
        [numeric(d, "market_cap_live", float("nan")), numeric(d, "mktcap", float("nan"))],
        axis=1,
    ).max(axis=1).fillna(0.0)
    d["pda_size_discovery_score"] = [size_discovery_score(value) for value in mcap]
    d["pda_mega_confirmation_size_score"] = [mega_confirmation_size_score(value) for value in mcap]
    d["post_disclosure_discovery_score"] = (
        0.22 * d["pda_13f_first_buy_surprise_score"]
        + 0.08 * d["pda_13f_new_or_add_score"]
        + 0.22 * d["pda_form4_open_market_buy_score"]
        + 0.18 * d["pda_etf_new_or_increase_score"]
        + 0.14 * d["pda_event_convergence_score"]
        + 0.12 * d["pda_size_discovery_score"]
        + 0.04 * d["post_disclosure_alpha_score"]
        - 0.15 * d["pda_negative_event_score"]
    ).fillna(0.0).clip(0.0, 1.0)
    d["post_disclosure_mega_confirmation_score"] = (
        0.30 * d["post_disclosure_alpha_score"]
        + 0.20 * d["pda_13f_event_score"]
        + 0.18 * d["pda_form4_event_score"]
        + 0.14 * d["pda_etf_event_score"]
        + 0.10 * d["pda_event_convergence_score"]
        + 0.08 * d["pda_mega_confirmation_size_score"]
        - 0.10 * d["pda_negative_event_score"]
    ).fillna(0.0).clip(0.0, 1.0)
    market_confirmation = (
        0.40 * numeric(d, "selection_market_confirmation_score", 0.0).clip(0.0, 1.0)
        + 0.25 * numeric(d, "rs_acceleration_score", 0.0).clip(0.0, 1.0)
        + 0.20 * numeric(d, "entry_quality_score", 0.0).clip(0.0, 1.0)
        + 0.15 * numeric(d, "industry_group_strength_score", 0.0).clip(0.0, 1.0)
    ).fillna(0.0).clip(0.0, 1.0)
    d["post_disclosure_price_confirmation_score"] = market_confirmation
    d["post_disclosure_price_confirmed_score"] = (
        d["post_disclosure_discovery_score"] * (0.25 + 0.75 * market_confirmation)
        - 0.10 * d["pda_negative_event_score"]
    ).fillna(0.0).clip(0.0, 1.0)
    d["post_disclosure_evidence_source_count"] = source_count
    return d


def portfolio_target_ns(args: argparse.Namespace, portfolio: str) -> str:
    legacy = str(getattr(args, "target_ns", "") or "").strip()
    if legacy:
        return legacy
    if portfolio == "main":
        return str(getattr(args, "main_target_ns", "12,15,18") or "12,15,18")
    return str(getattr(args, "concentrated_target_ns", "3,5") or "3,5")


def portfolio_single_name_caps(args: argparse.Namespace, portfolio: str) -> str:
    legacy = str(getattr(args, "single_name_caps", "") or "").strip()
    if legacy:
        return legacy
    if portfolio == "main":
        return str(getattr(args, "main_single_name_caps", "0.08,0.12,0.18") or "0.08,0.12,0.18")
    return str(getattr(args, "concentrated_single_name_caps", "0.33,0.50") or "0.33,0.50")


def run_broker_grid(args: argparse.Namespace, enriched_csv: Path, out_dir: Path) -> dict[str, Any]:
    if not bool(args.run_broker_grid):
        return {"status": "skipped", "reason": "run_broker_grid is false"}
    results: dict[str, Any] = {"status": "completed", "portfolios": {}}
    for portfolio in [p.strip() for p in str(args.portfolio_kinds).split(",") if p.strip()]:
        if portfolio not in {"main", "concentrated"}:
            continue
        payload = run_alpha_selector_grid(
            argparse.Namespace(
                candidate_book=str(enriched_csv),
                price_cache=str(args.price_cache),
                output_dir=str(out_dir / "alpha_selector_broker_grid" / portfolio),
                portfolio_kind=portfolio,
                starting_capital=float(args.starting_capital),
                fill_mode=args.fill_mode,
                cost_bps=float(args.cost_bps),
                no_integer_shares=False,
                max_fill_lag_days=int(args.max_fill_lag_days),
                styles=args.styles,
                target_ns=portfolio_target_ns(args, portfolio),
                single_name_caps=portfolio_single_name_caps(args, portfolio),
                max_variants=int(args.max_variants),
                min_market_cap_usd=float(args.min_market_cap_usd),
                min_dollar_volume_usd=float(args.min_dollar_volume_usd),
                min_price=float(args.min_price),
                allow_unfillable_targets=bool(args.allow_unfillable_targets),
            )
        )
        results["portfolios"][portfolio] = payload
    return results


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Post-Disclosure Overlay Challenger",
        "",
        "Research-only post-disclosure evidence overlay and broker-ledger challenger harness.",
        "",
        f"- status: `{summary.get('status', '')}`",
        f"- enriched rows: {summary.get('enriched_rows', 0)}",
        f"- rows with PDA score: {summary.get('rows_with_post_disclosure_score', 0)}",
        f"- run broker grid: `{summary.get('broker_grid', {}).get('status', '')}`",
        "",
        "Production activation is disabled. Promotion requires broker-ledger improvement, PIT/leakage audits, and human approval.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = repo_path(args.candidate_book)
    candidates = read_table(candidate_path)
    enriched = add_post_disclosure_overlay(
        candidates,
        read_table(repo_path(args.events_13f)),
        read_table(repo_path(args.events_form4)),
        read_table(repo_path(args.events_etf)),
        lookback_days=int(args.lookback_days),
        event_half_life_days=float(getattr(args, "event_half_life_days", 63.0)),
    )
    enriched_csv = output_dir / "candidate_replay_book_post_disclosure_enriched.csv"
    enriched.to_csv(enriched_csv, index=False)
    broker = run_broker_grid(args, enriched_csv, output_dir) if not enriched.empty else {"status": "blocked", "reason": "enriched candidate book is empty"}
    summary = {
        "status": "completed" if not enriched.empty else "blocked",
        "reason": "" if not enriched.empty else "missing candidate replay rows",
        "schema_version": "post-disclosure-overlay-challenger-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "candidate_book": str(candidate_path),
        "events_13f": str(repo_path(args.events_13f)),
        "events_form4": str(repo_path(args.events_form4)),
        "events_etf": str(repo_path(args.events_etf)),
        "lookback_days": int(args.lookback_days),
        "event_half_life_days": float(getattr(args, "event_half_life_days", 63.0)),
        "enriched_csv": str(enriched_csv),
        "enriched_rows": int(len(enriched)),
        "rows_with_post_disclosure_score": int((numeric(enriched, "post_disclosure_alpha_score", 0.0) > 0.0).sum()) if not enriched.empty else 0,
        "broker_grid": broker,
        "outputs": {
            "enriched_csv": str(enriched_csv),
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "enriched_rows": summary["enriched_rows"]}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--events-13f", default=DEFAULT_13F_EVENTS)
    parser.add_argument("--events-form4", default=DEFAULT_FORM4_EVENTS)
    parser.add_argument("--events-etf", default=DEFAULT_ETF_EVENTS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument("--event-half-life-days", type=float, default=63.0)
    parser.add_argument("--run-broker-grid", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--portfolio-kinds", default="main,concentrated")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--styles", default="future_heavy,future_heavy_post_disclosure_tiny_tiebreaker,future_heavy_post_disclosure_optional_satellite,future_heavy_post_disclosure_satellite,future_heavy_post_disclosure_confirmed,future_heavy_post_disclosure_micro,post_disclosure_price_confirmed,monster_heavy,post_disclosure_tiebreaker,post_disclosure_discovery,post_disclosure_mega_confirmation,post_disclosure_light,post_disclosure_balanced")
    parser.add_argument("--target-ns", default="")
    parser.add_argument("--single-name-caps", default="")
    parser.add_argument("--main-target-ns", default="12,15,18")
    parser.add_argument("--concentrated-target-ns", default="3,5")
    parser.add_argument("--main-single-name-caps", default="0.08,0.12,0.18")
    parser.add_argument("--concentrated-single-name-caps", default="0.33,0.50")
    parser.add_argument("--max-variants", type=int, default=48)
    parser.add_argument("--min-market-cap-usd", type=float, default=300_000_000.0)
    parser.add_argument("--min-dollar-volume-usd", type=float, default=5_000_000.0)
    parser.add_argument("--min-price", type=float, default=2.0)
    parser.add_argument("--allow-unfillable-targets", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
