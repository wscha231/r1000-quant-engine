#!/usr/bin/env python3
"""Research-only W4 Form4 + 13F source screen for run287 candidate rows.

This is a cheap source screen, not broker-ledger evidence. It combines
decision-time SEC Form4 transaction evidence with 13F position-change evidence
against run287 candidate rows, using `period_forward_return` only as an audit
label. It does not add hooks, tune thresholds, dispatch fullruns, or mutate
production state.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_form4_transaction_event_builder import build_form4_events, read_table as read_any_table  # noqa: E402

SCHEMA_VERSION = "run287-w4-form4-13f-source-screen-v1"
DEFAULT_CANDIDATE_BOOK = (
    "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe/reports/candidate_replay_book.csv"
)
DEFAULT_FORM4_PATH = (
    "H:/codex/alphaops_deep_research_context/artifacts/form4_26425151497/"
    "sec-form4-daily-26425151497/data_pit/sec/form4_transactions.parquet"
)
DEFAULT_13F_PATH = (
    "H:/codex/alphaops_deep_research_context/artifacts/sec_13f_26387370997/"
    "sec-13f-quarterly-26387370997/data_pit/sec/institutional_13f_holdings.parquet"
)
DEFAULT_MANAGER_UNIVERSE = "research/sec_13f_manager_universe_20260519/managers.csv"
DEFAULT_OUTPUT_DIR = "outputs/run287_w4_form4_13f_source_screen"
DEFAULT_OOS_START = "2024-07-01"

BASE_COLUMNS = [
    "rebalance_date",
    "ticker",
    "Name",
    "sector",
    "industry_group",
    "period_forward_return",
]
SIGNAL_COLUMNS = [
    "w4_form4_score",
    "w4_13f_score",
    "w4_combined_score",
    "w4_consensus_score",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def clean_ticker(value: Any) -> str:
    text = "" if pd.isna(value) else str(value).upper().strip()
    text = text.strip("()[]{} ")
    text = re.sub(r"[^A-Z0-9.\-]", "", text)
    return text


def read_candidate_book(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0)
    usecols = [col for col in BASE_COLUMNS if col in header.columns]
    return pd.read_csv(path, usecols=usecols, low_memory=False)


def prepare_candidate_book(frame: pd.DataFrame, oos_start: str) -> pd.DataFrame:
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d.get("rebalance_date"), errors="coerce").dt.normalize()
    d["ticker"] = d.get("ticker", pd.Series(index=d.index, dtype=object)).map(clean_ticker)
    d["forward_return_audit_only"] = pd.to_numeric(d.get("period_forward_return"), errors="coerce")
    d = d[d["rebalance_date"].notna() & d["ticker"].ne("") & d["forward_return_audit_only"].notna()].copy()
    oos_ts = pd.Timestamp(oos_start)
    d["split"] = np.where(d["rebalance_date"].ge(oos_ts), "oos", "is")
    d = d.reset_index(drop=True)
    d["_row_id"] = np.arange(len(d), dtype=np.int64)
    return d


def read_13f_holdings(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def build_form4_source_events(form4_path: Path, metadata: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    form4 = read_any_table(form4_path)
    events = build_form4_events(form4, metadata)
    if events.empty:
        return pd.DataFrame(columns=["ticker", "available_date", "score"]), {
            "source": str(form4_path),
            "raw_rows": int(len(form4)),
            "event_rows": 0,
            "ticker_count": 0,
        }
    d = events.copy()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d["available_ts"] = pd.to_datetime(d["available_from"], errors="coerce", utc=True)
    d["available_date"] = d["available_ts"].dt.tz_convert(None).dt.normalize()
    d["score"] = pd.to_numeric(d["post_disclosure_event_seed_score"], errors="coerce").fillna(0.0).clip(-1.0, 1.0)
    d = d[d["ticker"].ne("") & d["available_date"].notna()].copy()
    d["positive_event"] = d["score"].gt(0.0)
    d["negative_event"] = d["score"].lt(0.0)
    out = d[["ticker", "available_date", "score", "positive_event", "negative_event"]].copy()
    summary = {
        "source": str(form4_path),
        "raw_rows": int(len(form4)),
        "event_rows": int(len(out)),
        "ticker_count": int(out["ticker"].nunique()) if not out.empty else 0,
        "positive_event_rows": int(out["positive_event"].sum()) if not out.empty else 0,
        "negative_event_rows": int(out["negative_event"].sum()) if not out.empty else 0,
        "latest_available_date": out["available_date"].max().date().isoformat() if not out.empty else None,
    }
    return out, summary


def manager_rank_map(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    managers = read_any_table(path)
    if managers.empty:
        return {}
    cik_col = "cik10" if "cik10" in managers.columns else "manager_cik" if "manager_cik" in managers.columns else None
    if cik_col is None:
        return {}
    rank_col = "user_priority" if "user_priority" in managers.columns else "manager_rank" if "manager_rank" in managers.columns else None
    if rank_col is None:
        return {}
    out: dict[str, float] = {}
    for _, row in managers.iterrows():
        cik = re.sub(r"\D", "", str(row.get(cik_col, ""))).zfill(10)
        if cik.strip("0"):
            out[cik] = safe_float(row.get(rank_col), 0.0)
    return out


def build_13f_source_events(holdings_path: Path, manager_universe_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    holdings = read_13f_holdings(holdings_path)
    if holdings.empty:
        return pd.DataFrame(columns=["ticker", "available_date", "score"]), {
            "source": str(holdings_path),
            "raw_rows": 0,
            "event_rows": 0,
            "ticker_count": 0,
            "manager_universe_status": "missing_or_empty",
        }
    d = holdings.copy()
    if "ticker_mapped" in d.columns:
        fallback = d["ticker"] if "ticker" in d.columns else pd.Series("", index=d.index)
        d["ticker"] = d["ticker_mapped"].where(d["ticker_mapped"].fillna("").astype(str).str.strip().ne(""), fallback)
    d["ticker"] = d.get("ticker", pd.Series(index=d.index, dtype=object)).map(clean_ticker)
    d["manager_cik"] = d.get("manager_cik", pd.Series("", index=d.index)).fillna("").astype(str).map(
        lambda value: re.sub(r"\D", "", value).zfill(10)
    )
    d["report_period_ts"] = pd.to_datetime(d.get("report_period"), errors="coerce").dt.normalize()
    d["available_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True)
    d["available_date"] = d["available_ts"].dt.tz_convert(None).dt.normalize()
    d["shares"] = pd.to_numeric(d.get("shares"), errors="coerce").fillna(0.0).clip(lower=0.0)
    d["market_value_usd"] = pd.to_numeric(d.get("market_value_usd"), errors="coerce").fillna(0.0).clip(lower=0.0)
    d = d[
        d["ticker"].ne("")
        & d["manager_cik"].ne("0000000000")
        & d["report_period_ts"].notna()
        & d["available_date"].notna()
    ].copy()
    if d.empty:
        return pd.DataFrame(columns=["ticker", "available_date", "score"]), {
            "source": str(holdings_path),
            "raw_rows": int(len(holdings)),
            "event_rows": 0,
            "ticker_count": 0,
            "manager_universe_status": "missing_or_empty",
        }

    d = d.sort_values(["manager_cik", "ticker", "report_period_ts", "available_ts"])
    d = d.drop_duplicates(["manager_cik", "ticker", "report_period_ts"], keep="last")
    total_value = d.groupby(["manager_cik", "report_period_ts"])["market_value_usd"].transform("sum").replace(0.0, np.nan)
    d["position_weight"] = (d["market_value_usd"] / total_value).fillna(0.0).clip(0.0, 1.0)
    d["position_weight_pct_rank"] = (
        d.groupby(["manager_cik", "report_period_ts"])["position_weight"].rank(pct=True).fillna(0.0).clip(0.0, 1.0)
    )
    grouped = d.groupby(["manager_cik", "ticker"], sort=False)
    d["previous_shares"] = grouped["shares"].shift(1).fillna(0.0)
    d["previous_market_value_usd"] = grouped["market_value_usd"].shift(1).fillna(0.0)
    d["history_boundary"] = grouped.cumcount().eq(0)
    d["shares_delta"] = d["shares"] - d["previous_shares"]
    d["value_delta_usd"] = d["market_value_usd"] - d["previous_market_value_usd"]
    prev_value = d["previous_market_value_usd"].replace(0.0, np.nan)
    d["value_delta_pct"] = (d["value_delta_usd"] / prev_value).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    ranks = manager_rank_map(manager_universe_path)
    d["manager_rank"] = d["manager_cik"].map(ranks).fillna(0.0)
    manager_rank_bonus = (d["manager_rank"].clip(lower=0.0, upper=10.0) / 10.0) * 0.15
    add_score = (
        0.45 * d["value_delta_pct"].clip(lower=0.0, upper=1.0)
        + 0.35 * d["position_weight_pct_rank"]
        + 0.20 * (d["position_weight"].clip(lower=0.0, upper=0.05) / 0.05)
        + manager_rank_bonus
    )
    trim_score = -(
        0.35 * (-d["value_delta_pct"]).clip(lower=0.0, upper=1.0)
        + 0.20 * (d["position_weight_pct_rank"])
        + 0.10 * (d["position_weight"].clip(lower=0.0, upper=0.05) / 0.05)
    )
    d["score"] = np.where(
        d["history_boundary"],
        0.0,
        np.where(d["value_delta_usd"].gt(0.0), add_score, np.where(d["value_delta_usd"].lt(0.0), trim_score, 0.0)),
    )
    d["score"] = pd.to_numeric(d["score"], errors="coerce").fillna(0.0).clip(-1.0, 1.0)
    d = d[d["score"].ne(0.0)].copy()
    d["positive_event"] = d["score"].gt(0.0)
    d["negative_event"] = d["score"].lt(0.0)
    out = d[["ticker", "available_date", "score", "positive_event", "negative_event"]].copy()
    summary = {
        "source": str(holdings_path),
        "raw_rows": int(len(holdings)),
        "event_rows": int(len(out)),
        "ticker_count": int(out["ticker"].nunique()) if not out.empty else 0,
        "positive_event_rows": int(out["positive_event"].sum()) if not out.empty else 0,
        "negative_event_rows": int(out["negative_event"].sum()) if not out.empty else 0,
        "latest_available_date": out["available_date"].max().date().isoformat() if not out.empty else None,
        "manager_universe": str(manager_universe_path),
        "manager_universe_status": "available" if ranks else "missing_or_empty",
        "manager_rank_mapped_count": int(len(ranks)),
        "explicit_exit_events_included": False,
        "explicit_exit_events_note": "Direct holdings screen captures add/trim/new-like deltas; absent-position exits require full 13F event builder and are not used in this cheap source screen.",
    }
    return out, summary


def daily_aggregate(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["ticker", "available_date", "score_sum", "positive_count", "negative_count", "event_count"])
    d = events.copy()
    return (
        d.groupby(["ticker", "available_date"], as_index=False)
        .agg(
            score_sum=("score", "sum"),
            positive_count=("positive_event", "sum"),
            negative_count=("negative_event", "sum"),
            event_count=("score", "size"),
        )
        .sort_values(["ticker", "available_date"])
        .reset_index(drop=True)
    )


def attach_window_features(candidate: pd.DataFrame, events: pd.DataFrame, prefix: str, lookback_days: int) -> pd.DataFrame:
    out = candidate.copy()
    columns = [f"{prefix}_score_sum_{lookback_days}d", f"{prefix}_positive_count_{lookback_days}d", f"{prefix}_negative_count_{lookback_days}d", f"{prefix}_event_count_{lookback_days}d"]
    for col in columns:
        out[col] = 0.0
    if events.empty or out.empty:
        return out

    event_daily = daily_aggregate(events)
    for ticker, c_idx in out.groupby("ticker", sort=False).groups.items():
        e = event_daily[event_daily["ticker"].eq(ticker)]
        if e.empty:
            continue
        dates = e["available_date"].to_numpy(dtype="datetime64[ns]")
        score_cum = np.r_[0.0, e["score_sum"].astype(float).cumsum().to_numpy()]
        pos_cum = np.r_[0.0, e["positive_count"].astype(float).cumsum().to_numpy()]
        neg_cum = np.r_[0.0, e["negative_count"].astype(float).cumsum().to_numpy()]
        cnt_cum = np.r_[0.0, e["event_count"].astype(float).cumsum().to_numpy()]
        row_pos = np.fromiter(c_idx, dtype=np.int64)
        decisions = out.loc[row_pos, "rebalance_date"].to_numpy(dtype="datetime64[ns]")
        starts = decisions - np.timedelta64(int(lookback_days), "D")
        # Strictly exclude same-day disclosures; without intraday rebalance time,
        # same-day accepted_at could otherwise leak after-market filings.
        end_idx = np.searchsorted(dates, decisions, side="left")
        start_idx = np.searchsorted(dates, starts, side="left")
        out.loc[row_pos, f"{prefix}_score_sum_{lookback_days}d"] = score_cum[end_idx] - score_cum[start_idx]
        out.loc[row_pos, f"{prefix}_positive_count_{lookback_days}d"] = pos_cum[end_idx] - pos_cum[start_idx]
        out.loc[row_pos, f"{prefix}_negative_count_{lookback_days}d"] = neg_cum[end_idx] - neg_cum[start_idx]
        out.loc[row_pos, f"{prefix}_event_count_{lookback_days}d"] = cnt_cum[end_idx] - cnt_cum[start_idx]
    return out


def add_w4_scores(candidate: pd.DataFrame, form4_events: pd.DataFrame, sec13f_events: pd.DataFrame) -> pd.DataFrame:
    d = attach_window_features(candidate, form4_events, "form4", 90)
    d = attach_window_features(d, sec13f_events, "sec13f", 270)
    form4_raw = (
        d["form4_score_sum_90d"].astype(float)
        + 0.05 * d["form4_positive_count_90d"].astype(float)
        - 0.05 * d["form4_negative_count_90d"].astype(float)
    )
    sec13f_raw = (
        d["sec13f_score_sum_270d"].astype(float)
        + 0.03 * d["sec13f_positive_count_270d"].astype(float)
        - 0.03 * d["sec13f_negative_count_270d"].astype(float)
    )
    d["w4_form4_score"] = np.tanh(form4_raw).clip(-1.0, 1.0)
    d["w4_13f_score"] = np.tanh(sec13f_raw).clip(-1.0, 1.0)
    consensus = np.where(
        (d["w4_form4_score"] > 0.0) & (d["w4_13f_score"] > 0.0),
        np.minimum(d["w4_form4_score"], d["w4_13f_score"]),
        np.where(
            (d["w4_form4_score"] < 0.0) & (d["w4_13f_score"] < 0.0),
            np.maximum(d["w4_form4_score"], d["w4_13f_score"]),
            0.0,
        ),
    )
    d["w4_consensus_score"] = consensus
    d["w4_combined_score"] = (0.60 * d["w4_form4_score"] + 0.40 * d["w4_13f_score"] + 0.10 * d["w4_consensus_score"]).clip(-1.0, 1.0)
    return d


def quantile_stats(frame: pd.DataFrame, signal: str, min_rows: int) -> dict[str, Any]:
    d = frame[[signal, "forward_return_audit_only"]].dropna().copy()
    d = d[d[signal].astype(float).abs().gt(1.0e-12)].copy()
    if len(d) < min_rows or d[signal].nunique() < 2:
        return {"status": "insufficient_signal_coverage", "row_count": int(len(d))}
    try:
        d["quantile"] = pd.qcut(d[signal], q=min(5, d[signal].nunique()), labels=False, duplicates="drop")
    except ValueError:
        return {"status": "insufficient_unique_values", "row_count": int(len(d))}
    if d["quantile"].nunique() < 2:
        return {"status": "insufficient_quantiles", "row_count": int(len(d))}
    grouped = d.groupby("quantile")["forward_return_audit_only"].agg(["count", "mean"]).reset_index()
    low = grouped.sort_values("quantile").iloc[0]
    high = grouped.sort_values("quantile").iloc[-1]
    high_rows = d[d["quantile"].eq(high["quantile"])]
    spearman = float(d[signal].rank(method="average").corr(d["forward_return_audit_only"].rank(method="average")))
    return {
        "status": "ok",
        "row_count": int(len(d)),
        "spearman": spearman if math.isfinite(spearman) else 0.0,
        "low_quantile_count": int(low["count"]),
        "high_quantile_count": int(high["count"]),
        "low_quantile_mean": float(low["mean"]),
        "high_quantile_mean": float(high["mean"]),
        "high_minus_low": float(high["mean"] - low["mean"]),
        "high_quantile_positive_rate": float((high_rows["forward_return_audit_only"] > 0).mean()),
    }


def screen_signal(frame: pd.DataFrame, signal: str, min_rows: int, min_oos_high_count: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    split_stats: dict[str, dict[str, Any]] = {}
    for split, subset in [
        ("full", frame),
        ("is", frame[frame["split"].eq("is")]),
        ("oos", frame[frame["split"].eq("oos")]),
    ]:
        stats = quantile_stats(subset, signal, min_rows)
        split_stats[split] = stats
        rows.append({"signal": signal, "split": split, **stats})
    full = split_stats.get("full", {})
    is_stats = split_stats.get("is", {})
    oos = split_stats.get("oos", {})
    source_positive = (
        full.get("status") == "ok"
        and is_stats.get("status") == "ok"
        and oos.get("status") == "ok"
        and safe_float(full.get("high_minus_low")) > 0
        and safe_float(is_stats.get("high_minus_low")) > 0
        and safe_float(oos.get("high_minus_low")) > 0
        and safe_float(oos.get("high_quantile_count")) >= min_oos_high_count
    )
    summary = {
        "signal": signal,
        "source_positive": bool(source_positive),
        "full_high_minus_low": full.get("high_minus_low"),
        "is_high_minus_low": is_stats.get("high_minus_low"),
        "oos_high_minus_low": oos.get("high_minus_low"),
        "oos_high_quantile_count": oos.get("high_quantile_count"),
        "oos_high_quantile_positive_rate": oos.get("high_quantile_positive_rate"),
        "full_spearman": full.get("spearman"),
        "oos_spearman": oos.get("spearman"),
    }
    return summary, rows


def source_coverage(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "candidate_rows": int(len(frame)),
        "candidate_tickers": int(frame["ticker"].nunique()) if not frame.empty else 0,
        "form4_signal_rows": int(frame["w4_form4_score"].astype(float).abs().gt(1.0e-12).sum()) if not frame.empty else 0,
        "form4_signal_tickers": int(frame.loc[frame["w4_form4_score"].astype(float).abs().gt(1.0e-12), "ticker"].nunique()) if not frame.empty else 0,
        "sec13f_signal_rows": int(frame["w4_13f_score"].astype(float).abs().gt(1.0e-12).sum()) if not frame.empty else 0,
        "sec13f_signal_tickers": int(frame.loc[frame["w4_13f_score"].astype(float).abs().gt(1.0e-12), "ticker"].nunique()) if not frame.empty else 0,
        "combined_signal_rows": int(frame["w4_combined_score"].astype(float).abs().gt(1.0e-12).sum()) if not frame.empty else 0,
        "combined_signal_tickers": int(frame.loc[frame["w4_combined_score"].astype(float).abs().gt(1.0e-12), "ticker"].nunique()) if not frame.empty else 0,
    }


def render_report(payload: dict[str, Any], signal_summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# Run287 W4 Form4 + 13F Source Screen",
        "",
        f"- Status: `{payload['status']}`",
        f"- Decision label: `{payload['decision_label']}`",
        f"- Candidate allowed: `{payload['candidate_allowed']}`",
        f"- Forward returns audit only: `{payload['forward_returns_audit_only']}`",
        f"- Same-day disclosure policy: `{payload['same_day_disclosure_policy']}`",
        "",
        "## Signal Screen",
        "",
        "| Signal | Source positive | Full high-low | IS high-low | OOS high-low | OOS high count | OOS hit rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in signal_summaries:
        lines.append(
            "| {signal} | {positive} | {full:.2%} | {is_:.2%} | {oos:.2%} | {count} | {hit:.2%} |".format(
                signal=item.get("signal"),
                positive=item.get("source_positive"),
                full=safe_float(item.get("full_high_minus_low")),
                is_=safe_float(item.get("is_high_minus_low")),
                oos=safe_float(item.get("oos_high_minus_low")),
                count=int(safe_float(item.get("oos_high_quantile_count"))),
                hit=safe_float(item.get("oos_high_quantile_positive_rate")),
            )
        )
    coverage = payload.get("coverage", {})
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- Candidate rows: `{coverage.get('candidate_rows', 0)}`",
            f"- Form4 signal rows: `{coverage.get('form4_signal_rows', 0)}`",
            f"- 13F signal rows: `{coverage.get('sec13f_signal_rows', 0)}`",
            f"- Combined signal rows: `{coverage.get('combined_signal_rows', 0)}`",
            "",
            "## Interpretation",
            "",
            "- Form4 contributes timelier insider transaction evidence.",
            "- 13F contributes slower but broader institutional position-change evidence.",
            "- The combined score is a fixed source-screen blend, not a tuned policy threshold.",
            "- Any positive result can only justify a default-off broker A/B design review after OOS review.",
            "- A mixed or negative result blocks W4 hook design from this Form4/13F source family.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_path = repo_path(args.input)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = read_candidate_book(input_path)
    if raw.empty:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "reason": "missing_or_empty_candidate_book",
            "input": str(input_path),
            "research_only": True,
            "production_promotion_allowed": False,
            "fullrun_dispatched": False,
        }
        write_json(output_dir / "summary.json", payload)
        return payload

    candidate = prepare_candidate_book(raw, args.oos_start)
    form4_events, form4_summary = build_form4_source_events(repo_path(args.form4_path), candidate)
    sec13f_events, sec13f_summary = build_13f_source_events(repo_path(args.sec13f_path), repo_path(args.manager_universe))
    enriched = add_w4_scores(candidate, form4_events, sec13f_events)

    signal_summaries: list[dict[str, Any]] = []
    stat_rows: list[dict[str, Any]] = []
    for signal in SIGNAL_COLUMNS:
        summary, rows = screen_signal(enriched, signal, args.min_rows, args.min_oos_high_count)
        signal_summaries.append(summary)
        stat_rows.extend(rows)
    positives = [item["signal"] for item in signal_summaries if item.get("source_positive")]
    combined_positive = "w4_combined_score" in positives or "w4_consensus_score" in positives
    decision_label = (
        "w4_combined_positive_requires_broker_ab_review"
        if combined_positive
        else "w4_single_source_positive_requires_review"
        if positives
        else "blocked_no_robust_w4_form4_13f_signal"
    )
    coverage = source_coverage(enriched)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "input": str(input_path),
        "row_count": int(len(enriched)),
        "ticker_count": int(enriched["ticker"].nunique()),
        "oos_start": args.oos_start,
        "form4": form4_summary,
        "sec13f": sec13f_summary,
        "coverage": coverage,
        "signal_summaries": signal_summaries,
        "positive_signal_count": int(len(positives)),
        "positive_signals": positives,
        "decision_label": decision_label,
        "next_action_allowed": "default_off_broker_ab_design_review_only" if positives else "do_not_design_hook_from_form4_13f_family",
        "candidate_allowed": False,
        "source_screen_only": True,
        "research_only": True,
        "forward_returns_audit_only": True,
        "used_forward_return_in_ranking": False,
        "same_day_disclosure_policy": "excluded_no_intraday_rebalance_contract",
        "score_formula": {
            "form4": "tanh(sum_90d(seed_score) + 0.05*buy_like_count - 0.05*sale_like_count)",
            "sec13f": "tanh(sum_270d(position_delta_score) + 0.03*positive_count - 0.03*negative_count)",
            "combined": "clip(0.60*form4 + 0.40*13f + 0.10*consensus, -1, 1)",
            "consensus": "positive only when both sources positive; negative only when both sources negative",
        },
        "fullrun_dispatched": False,
        "new_alpha_hook_added": False,
        "threshold_tuning_performed": False,
        "production_promotion_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
        "artifacts": {
            "summary": str(output_dir / "summary.json"),
            "signal_stats": str(output_dir / "signal_stats.csv"),
            "enriched_candidate_sample": str(output_dir / "enriched_candidate_sample.csv"),
            "report": str(output_dir / "report.md"),
        },
    }
    pd.DataFrame(stat_rows).to_csv(output_dir / "signal_stats.csv", index=False)
    sample_cols = [
        col
        for col in [
            "rebalance_date",
            "ticker",
            "Name",
            "sector",
            "industry_group",
            "forward_return_audit_only",
            "w4_form4_score",
            "w4_13f_score",
            "w4_consensus_score",
            "w4_combined_score",
            "form4_event_count_90d",
            "sec13f_event_count_270d",
        ]
        if col in enriched.columns
    ]
    sample = enriched.loc[enriched["w4_combined_score"].astype(float).abs().gt(1.0e-12), sample_cols].copy()
    sample = sample.reindex(sample["w4_combined_score"].abs().sort_values(ascending=False).index).head(int(args.sample_rows))
    sample.to_csv(output_dir / "enriched_candidate_sample.csv", index=False)
    (output_dir / "report.md").write_text(render_report(payload, signal_summaries), encoding="utf-8")
    write_json(output_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--form4-path", default=DEFAULT_FORM4_PATH)
    parser.add_argument("--sec13f-path", default=DEFAULT_13F_PATH)
    parser.add_argument("--manager-universe", default=DEFAULT_MANAGER_UNIVERSE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START)
    parser.add_argument("--min-rows", type=int, default=50)
    parser.add_argument("--min-oos-high-count", type=int, default=20)
    parser.add_argument("--sample-rows", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
