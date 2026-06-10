#!/usr/bin/env python3
"""Study PIT top-manager 13F follow signals after public disclosure.

This tool answers a narrower question than a static "smart money" screen:

    At each historical cohort date, which 13F managers were top performers
    using only post-disclosure outcomes already known by that date, and did
    their later new/add 13F positions rise after the filing became available?

The output is research-only. It never changes production scoring and never
uses today's top managers to rank historical events.
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

DEFAULT_EVENTS = "data_pit/sec/13f_position_events.parquet"
DEFAULT_LABELS = "data_pit/sec/post_disclosure_alpha_labels.parquet"
DEFAULT_OUTPUT_DIR = "outputs/pit_top_manager_follow_study"
DEFAULT_COHORT_PIT = "data_pit/sec/pit_top_manager_cohorts.parquet"
DEFAULT_FOLLOW_EVENTS_PIT = "data_pit/sec/top_manager_13f_follow_events.parquet"
DEFAULT_HORIZONS = "21,63,126,252"
BUY_EVENT_TYPES = {"new", "add"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat() if pd.notna(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def parse_horizons(text: str) -> list[int]:
    out: list[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if part:
            value = int(part)
            if value > 0:
                out.append(value)
    return sorted(set(out))


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def text_column(frame: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=object)
    return frame[col].fillna(default).astype(str)


def first_existing_col(frame: pd.DataFrame, names: list[str]) -> str:
    for name in names:
        if name in frame.columns:
            return name
    return ""


def horizon_return_col(frame: pd.DataFrame, horizon: int) -> str:
    excess_col = f"excess_spy_{int(horizon)}d"
    if excess_col in frame.columns:
        return excess_col
    return f"ret_{int(horizon)}d"


def label_completion_ts(frame: pd.DataFrame, horizon: int) -> pd.Series:
    target_col = f"target_date_{int(horizon)}d"
    if target_col in frame.columns:
        ts = pd.to_datetime(frame[target_col], errors="coerce")
    else:
        ts = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    missing = ts.isna()
    if missing.any():
        # Calendar approximation used only when older labels lack target_date.
        fallback = frame["available_from_ts"] + pd.to_timedelta(int(horizon) * 2, unit="D")
        ts = ts.where(~missing, fallback)
    return ts


def normalize_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    d = events.copy()
    if "available_from" not in d.columns and "accepted_at" in d.columns:
        d["available_from"] = d["accepted_at"]
    d["event_id"] = text_column(d, "event_id")
    d["source_type"] = text_column(d, "source_type").str.lower().str.strip()
    d["manager_cik"] = text_column(d, "manager_cik").str.zfill(10)
    d["manager_name"] = text_column(d, "manager_name")
    d["ticker"] = text_column(d, "ticker").str.upper().str.strip()
    d["event_type"] = text_column(d, "event_type").str.lower().str.strip()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True).dt.tz_convert(None)
    d = d[d["event_id"].ne("") & d["ticker"].ne("") & d["manager_cik"].str.strip().ne("") & d["available_from_ts"].notna()].copy()
    for col in ["manager_rank", "external_performance_2y", "post_disclosure_event_seed_score", "issuer_market_cap", "issuer_float", "manager_stake_to_float", "value_delta_usd", "position_weight", "position_rank"]:
        d[col] = numeric(d, col, 0.0)
    for col in ["market_cap_bucket", "liquidity_bucket", "sector", "industry", "allocation_tier"]:
        d[col] = text_column(d, col)
    return d.sort_values(["available_from_ts", "manager_cik", "ticker", "event_id"]).reset_index(drop=True)


def normalize_labels(labels: pd.DataFrame, events: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    if labels.empty:
        return pd.DataFrame()
    d = labels.copy()
    d["event_id"] = text_column(d, "event_id")
    if "available_from" not in d.columns and "accepted_at" in d.columns:
        d["available_from"] = d["accepted_at"]
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True).dt.tz_convert(None)
    d = d[d["event_id"].ne("") & d["available_from_ts"].notna()].copy()

    event_cols = [
        "event_id",
        "source_type",
        "manager_cik",
        "manager_name",
        "ticker",
        "event_type",
        "manager_rank",
        "external_performance_2y",
        "allocation_tier",
        "market_cap_bucket",
        "liquidity_bucket",
        "sector",
        "industry",
        "issuer_market_cap",
        "issuer_float",
        "manager_stake_to_float",
        "value_delta_usd",
        "position_weight",
        "position_rank",
        "post_disclosure_event_seed_score",
    ]
    event_meta = events[[c for c in event_cols if c in events.columns]].drop_duplicates("event_id", keep="last") if not events.empty else pd.DataFrame(columns=["event_id"])
    if not event_meta.empty:
        d = d.merge(event_meta, on="event_id", how="left", suffixes=("", "_event"))
        for col in event_cols:
            event_col = f"{col}_event"
            if event_col in d.columns:
                if col in d.columns:
                    base = d[col]
                    d[col] = base.where(base.notna() & base.astype(str).str.strip().ne(""), d[event_col])
                else:
                    d[col] = d[event_col]
                d = d.drop(columns=[event_col])

    d["source_type"] = text_column(d, "source_type").str.lower().str.strip()
    d["manager_cik"] = text_column(d, "manager_cik").str.zfill(10)
    d["manager_name"] = text_column(d, "manager_name")
    d["ticker"] = text_column(d, "ticker").str.upper().str.strip()
    d["event_type"] = text_column(d, "event_type").str.lower().str.strip()
    for col in ["manager_rank", "external_performance_2y", "post_disclosure_event_seed_score", "issuer_market_cap", "issuer_float", "manager_stake_to_float", "value_delta_usd", "position_weight", "position_rank"]:
        d[col] = numeric(d, col, 0.0)
    for col in ["market_cap_bucket", "liquidity_bucket", "sector", "industry", "allocation_tier"]:
        d[col] = text_column(d, col)
    for horizon in horizons:
        ret_col = f"ret_{horizon}d"
        excess_col = f"excess_spy_{horizon}d"
        if ret_col not in d.columns:
            d[ret_col] = np.nan
        if excess_col not in d.columns:
            d[excess_col] = d[ret_col]
        d[f"label_completion_ts_{horizon}d"] = label_completion_ts(d, horizon)
    return d.sort_values(["available_from_ts", "manager_cik", "ticker", "event_id"]).reset_index(drop=True)


def cohort_dates(frame: pd.DataFrame, refresh_months: int, history_years: int) -> list[pd.Timestamp]:
    if frame.empty or "available_from_ts" not in frame.columns:
        return []
    start = pd.Timestamp(frame["available_from_ts"].min()).normalize().replace(day=1)
    end = pd.Timestamp(frame["available_from_ts"].max()).normalize().replace(day=1)
    if history_years > 0:
        min_start = end - pd.DateOffset(years=int(history_years))
        start = max(start, pd.Timestamp(min_start).normalize().replace(day=1))
    dates: list[pd.Timestamp] = []
    cur = start
    step = max(1, int(refresh_months))
    while cur <= end + pd.DateOffset(months=step):
        dates.append(pd.Timestamp(cur))
        cur = cur + pd.DateOffset(months=step)
    return dates


def manager_score_from_prior(prior: pd.DataFrame, horizon: int, min_manager_events: int) -> pd.DataFrame:
    ret_col = horizon_return_col(prior, horizon)
    if prior.empty or ret_col not in prior.columns:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for manager_cik, group in prior.groupby("manager_cik", sort=True):
        values = pd.to_numeric(group[ret_col], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        sample = int(len(values))
        if sample < int(min_manager_events):
            continue
        avg = float(values.mean())
        median = float(values.median())
        hit = float((values > 0.0).mean())
        recent = float(values.tail(min(5, len(values))).mean()) if len(values) else 0.0
        confidence = min(1.0, sample / max(float(min_manager_events) * 2.0, 1.0))
        # Keep the score rankable but conservative; it is not a production score.
        raw = (3.0 * avg) + (0.75 * median) + (0.50 * (hit - 0.5)) + (1.5 * recent) + (0.03 * math.log1p(sample))
        manager_name = ""
        if group["manager_name"].astype(str).str.strip().ne("").any():
            manager_name = str(group["manager_name"].dropna().astype(str).replace("", pd.NA).dropna().iloc[-1])
        rows.append(
            {
                "manager_cik": str(manager_cik).zfill(10),
                "manager_name": manager_name,
                "manager_follow_score": float(raw * confidence),
                "manager_follow_raw_score": float(raw),
                "manager_follow_confidence": float(confidence),
                "manager_sample_count": sample,
                f"manager_avg_excess_{horizon}d": avg,
                f"manager_median_excess_{horizon}d": median,
                f"manager_hit_rate_{horizon}d": hit,
                f"manager_recent_excess_{horizon}d": recent,
                "score_source": "pit_completed_post_disclosure_labels",
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values(["manager_follow_score", "manager_sample_count"], ascending=False).reset_index(drop=True)
    out["cohort_rank"] = np.arange(1, len(out) + 1)
    return out


def build_cohorts(labels: pd.DataFrame, dates: list[pd.Timestamp], *, top_n: int, ranking_lookback_days: int, ranking_horizon: int, min_manager_events: int) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    if labels.empty:
        return pd.DataFrame()
    d = labels[
        labels["source_type"].eq("13f")
        & labels["event_type"].isin(BUY_EVENT_TYPES)
        & labels["manager_cik"].astype(str).str.strip().ne("")
    ].copy()
    completion_col = f"label_completion_ts_{ranking_horizon}d"
    ret_col = horizon_return_col(d, ranking_horizon)
    if d.empty or completion_col not in d.columns or ret_col not in d.columns:
        return pd.DataFrame()
    d = d[pd.to_numeric(d[ret_col], errors="coerce").notna()].copy()
    for cohort_date in dates:
        as_of = pd.Timestamp(cohort_date)
        start = as_of - pd.Timedelta(days=int(ranking_lookback_days))
        prior = d[
            (d["available_from_ts"] >= start)
            & (d["available_from_ts"] < as_of)
            & (pd.to_datetime(d[completion_col], errors="coerce") < as_of)
        ].copy()
        scored = manager_score_from_prior(prior, ranking_horizon, min_manager_events)
        if scored.empty:
            continue
        scored = scored.head(int(top_n)).copy()
        scored["cohort_date"] = as_of.date().isoformat()
        scored["ranking_lookback_days"] = int(ranking_lookback_days)
        scored["ranking_horizon"] = int(ranking_horizon)
        scored["research_only"] = True
        scored["production_activation_allowed"] = False
        rows.append(scored)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    cols = ["cohort_date", "cohort_rank", "manager_cik", "manager_name"]
    other = [c for c in out.columns if c not in cols]
    return out[cols + other].sort_values(["cohort_date", "cohort_rank"]).reset_index(drop=True)


def assign_top_cohort_events(events: pd.DataFrame, labels: pd.DataFrame, cohorts: pd.DataFrame, dates: list[pd.Timestamp], horizons: list[int]) -> pd.DataFrame:
    if events.empty or cohorts.empty or not dates:
        return pd.DataFrame()
    candidates = events[
        events["source_type"].eq("13f")
        & events["event_type"].isin(BUY_EVENT_TYPES)
        & events["manager_cik"].astype(str).str.strip().ne("")
    ].copy()
    if candidates.empty:
        return pd.DataFrame()

    date_index = pd.DatetimeIndex(dates)
    positions = date_index.searchsorted(pd.to_datetime(candidates["available_from_ts"]), side="right") - 1
    valid = positions >= 0
    candidates = candidates.loc[valid].copy()
    positions = positions[valid]
    if candidates.empty:
        return pd.DataFrame()
    candidates["cohort_date"] = [date_index[int(pos)].date().isoformat() for pos in positions]

    cohort_keys = cohorts.copy()
    candidates = candidates.merge(
        cohort_keys,
        on=["cohort_date", "manager_cik"],
        how="inner",
        suffixes=("", "_cohort"),
    )
    if candidates.empty:
        return pd.DataFrame()

    label_cols = ["event_id", "label_status", "entry_date", "entry_price", "max_dd_63d"]
    for horizon in horizons:
        label_cols.extend([f"ret_{horizon}d", f"excess_spy_{horizon}d", f"target_date_{horizon}d"])
    label_cols = [c for c in label_cols if c in labels.columns]
    label_meta = labels[label_cols].drop_duplicates("event_id", keep="last") if not labels.empty else pd.DataFrame(columns=["event_id"])
    out = candidates.merge(label_meta, on="event_id", how="left", suffixes=("", "_label"))
    out["cohort_rank_bucket"] = np.where(
        pd.to_numeric(out["cohort_rank"], errors="coerce") <= 3,
        "top3",
        np.where(pd.to_numeric(out["cohort_rank"], errors="coerce") <= 7, "top7", "top10"),
    )
    out["discovery_bucket"] = text_column(out, "market_cap_bucket").where(
        text_column(out, "market_cap_bucket").isin(["micro", "small", "mid"]),
        "large_mega_or_unknown",
    )
    out["research_only"] = True
    out["production_activation_allowed"] = False
    return out.sort_values(["available_from_ts", "cohort_rank", "ticker"]).reset_index(drop=True)


def bucket_performance(follow_events: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    if follow_events.empty:
        return pd.DataFrame()
    group_sets = [
        ("all", []),
        ("event_type", ["event_type"]),
        ("market_cap_bucket", ["market_cap_bucket"]),
        ("cohort_rank_bucket", ["cohort_rank_bucket"]),
        ("discovery_bucket", ["discovery_bucket"]),
        ("event_type_x_market_cap", ["event_type", "market_cap_bucket"]),
    ]
    rows: list[dict[str, Any]] = []
    for group_name, group_cols in group_sets:
        groups = [((), follow_events)] if not group_cols else follow_events.groupby(group_cols, dropna=False)
        for keys, group in groups:
            if not isinstance(keys, tuple):
                keys = (keys,)
            base = {"bucket": group_name, "rows_total": int(len(group))}
            for col, value in zip(group_cols, keys):
                base[col] = value
            for horizon in horizons:
                ret_col = f"ret_{horizon}d"
                excess_col = f"excess_spy_{horizon}d" if f"excess_spy_{horizon}d" in group.columns else ret_col
                returns = pd.to_numeric(group.get(ret_col, pd.Series(dtype=float)), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
                excess = pd.to_numeric(group.get(excess_col, pd.Series(dtype=float)), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
                row = dict(base)
                row["horizon"] = int(horizon)
                row["rows"] = int(len(returns))
                row["avg_return"] = float(returns.mean()) if len(returns) else math.nan
                row["median_return"] = float(returns.median()) if len(returns) else math.nan
                row["hit_rate"] = float((returns > 0.0).mean()) if len(returns) else math.nan
                row["avg_excess"] = float(excess.mean()) if len(excess) else math.nan
                row["excess_hit_rate"] = float((excess > 0.0).mean()) if len(excess) else math.nan
                row["worst_return"] = float(returns.min()) if len(returns) else math.nan
                row["best_return"] = float(returns.max()) if len(returns) else math.nan
                rows.append(row)
    return pd.DataFrame(rows)


def render_report(summary: dict[str, Any], cohorts: pd.DataFrame, bucket_stats: pd.DataFrame, horizons: list[int]) -> str:
    primary = 63 if 63 in horizons else (horizons[0] if horizons else 0)
    lines = [
        "# PIT Top-Manager 13F Follow Study",
        "",
        "Research-only study. Manager cohorts are ranked using only completed post-disclosure labels available before each cohort date.",
        "",
        f"- status: `{summary.get('status')}`",
        f"- event rows: {summary.get('event_rows', 0)}",
        f"- label rows: {summary.get('label_rows', 0)}",
        f"- cohort rows: {summary.get('cohort_rows', 0)}",
        f"- selected follow events: {summary.get('selected_follow_events', 0)}",
        f"- ranking horizon: {summary.get('ranking_horizon')}",
        f"- production activation allowed: `{summary.get('production_activation_allowed')}`",
        "",
        "## Latest Cohort",
        "",
        "| rank | manager | cik | score | samples | hit rate |",
        "| ---: | --- | --- | ---: | ---: | ---: |",
    ]
    if not cohorts.empty:
        latest_date = str(cohorts["cohort_date"].max())
        latest = cohorts[cohorts["cohort_date"].eq(latest_date)].sort_values("cohort_rank").head(10)
        hit_col = f"manager_hit_rate_{primary}d"
        lines.append(f"Latest cohort date: `{latest_date}`")
        for _, row in latest.iterrows():
            lines.append(
                "| {rank} | {name} | {cik} | {score:.4f} | {sample} | {hit:.2%} |".format(
                    rank=int(row.get("cohort_rank", 0)),
                    name=str(row.get("manager_name", "")),
                    cik=str(row.get("manager_cik", "")),
                    score=float(row.get("manager_follow_score", 0.0) or 0.0),
                    sample=int(row.get("manager_sample_count", 0) or 0),
                    hit=float(row.get(hit_col, 0.0) or 0.0),
                )
            )
    lines.extend(["", "## Follow Performance", "", "| bucket | horizon | rows | avg return | avg excess | hit rate |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    if not bucket_stats.empty:
        all_rows = bucket_stats[bucket_stats["bucket"].eq("all")].sort_values("horizon")
        for _, row in all_rows.iterrows():
            lines.append(
                "| all | {horizon} | {rows} | {avg:.2%} | {excess:.2%} | {hit:.2%} |".format(
                    horizon=int(row.get("horizon", 0)),
                    rows=int(row.get("rows", 0)),
                    avg=float(row.get("avg_return", 0.0) or 0.0),
                    excess=float(row.get("avg_excess", 0.0) or 0.0),
                    hit=float(row.get("hit_rate", 0.0) or 0.0),
                )
            )
    lines.extend(
        [
            "",
            "This report tests whether following top managers after public 13F availability would have worked.",
            "It does not imply live score activation or automatic trading.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    events_path = repo_path(args.events)
    labels_path = repo_path(args.labels)
    output_dir = repo_path(args.output_dir)
    cohort_pit = repo_path(args.cohort_pit)
    follow_events_pit = repo_path(args.follow_events_pit)
    output_dir.mkdir(parents=True, exist_ok=True)

    horizons = parse_horizons(args.horizons)
    ranking_horizon = int(args.ranking_horizon or (63 if 63 in horizons else horizons[0]))
    if ranking_horizon not in horizons:
        horizons = sorted(set([*horizons, ranking_horizon]))

    events = normalize_events(read_table(events_path))
    labels = normalize_labels(read_table(labels_path), events, horizons)
    dates = cohort_dates(labels if not labels.empty else events, int(args.cohort_refresh_months), int(args.history_years))
    cohorts = build_cohorts(
        labels,
        dates,
        top_n=int(args.top_n),
        ranking_lookback_days=int(args.ranking_lookback_days),
        ranking_horizon=ranking_horizon,
        min_manager_events=int(args.min_manager_events),
    )
    follow_events = assign_top_cohort_events(events, labels, cohorts, dates, horizons)
    stats = bucket_performance(follow_events, horizons)

    write_table(cohorts, cohort_pit)
    write_table(follow_events, follow_events_pit)
    write_table(cohorts, output_dir / "cohort_history.csv")
    write_table(follow_events, output_dir / "event_forward_returns.csv")
    write_table(stats, output_dir / "bucket_performance.csv")

    latest_cohort_date = str(cohorts["cohort_date"].max()) if not cohorts.empty else ""
    summary = {
        "status": "completed" if not cohorts.empty and not follow_events.empty else ("partial" if not cohorts.empty else "blocked"),
        "reason": "" if not cohorts.empty else "no PIT manager cohorts passed the completed-label sample threshold",
        "schema_version": "pit-top-manager-follow-study-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "events": str(events_path),
        "labels": str(labels_path),
        "event_rows": int(len(events)),
        "label_rows": int(len(labels)),
        "cohort_rows": int(len(cohorts)),
        "cohort_count": int(cohorts["cohort_date"].nunique()) if not cohorts.empty else 0,
        "latest_cohort_date": latest_cohort_date,
        "selected_follow_events": int(len(follow_events)),
        "selected_ticker_count": int(follow_events["ticker"].nunique()) if not follow_events.empty else 0,
        "ranking_horizon": int(ranking_horizon),
        "ranking_lookback_days": int(args.ranking_lookback_days),
        "cohort_refresh_months": int(args.cohort_refresh_months),
        "top_n": int(args.top_n),
        "min_manager_events": int(args.min_manager_events),
        "horizons": horizons,
        "outputs": {
            "cohort_pit": str(cohort_pit),
            "follow_events_pit": str(follow_events_pit),
            "cohort_history": str(output_dir / "cohort_history.csv"),
            "event_forward_returns": str(output_dir / "event_forward_returns.csv"),
            "bucket_performance": str(output_dir / "bucket_performance.csv"),
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, cohorts, stats, horizons), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "cohort_rows": summary["cohort_rows"], "selected_follow_events": summary["selected_follow_events"]}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", default=DEFAULT_EVENTS)
    parser.add_argument("--labels", default=DEFAULT_LABELS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cohort-pit", default=DEFAULT_COHORT_PIT)
    parser.add_argument("--follow-events-pit", default=DEFAULT_FOLLOW_EVENTS_PIT)
    parser.add_argument("--horizons", default=DEFAULT_HORIZONS)
    parser.add_argument("--ranking-horizon", type=int, default=63)
    parser.add_argument("--ranking-lookback-days", type=int, default=1095)
    parser.add_argument("--cohort-refresh-months", type=int, default=6)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--min-manager-events", type=int, default=8)
    parser.add_argument("--history-years", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") in {"completed", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
