#!/usr/bin/env python3
"""Research-only Main crash-fragility screen.

This screen asks whether PIT-observable fragility features on Main target-book
holdings explain future short-horizon downside. Forward returns are audit labels
only; they are not emitted as a live selection signal.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series, price_on_or_after, price_on_or_before  # noqa: E402

SCHEMA_VERSION = "main-crash-fragility-screen-v1"
CASH_TICKERS = {"CASH", "__CASH__"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def pct(value: Any) -> str:
    if value is None or not math.isfinite(safe_float(value, float("nan"))):
        return ""
    return f"{safe_float(value):.2%}"


def normalize_target_book(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    required = {"rebalance_date", "ticker"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"target book missing required columns: {sorted(missing)}")
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    out["ticker"] = out["ticker"].map(clean_ticker)
    if "target_weight" not in out.columns:
        out["target_weight"] = out.get("weight", 0.0)
    out["target_weight"] = pd.to_numeric(out["target_weight"], errors="coerce").fillna(0.0)
    out = out.dropna(subset=["rebalance_date"])
    out = out[(out["ticker"] != "") & (~out["ticker"].isin(CASH_TICKERS)) & (out["target_weight"] > 1e-12)]
    return out.sort_values(["rebalance_date", "target_weight"], ascending=[True, False]).reset_index(drop=True)


def normalize_crisis_state(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "date" not in frame.columns:
        return pd.DataFrame(columns=["date", "crisis_state", "spy_drawdown"])
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    if "crisis_state" not in out.columns:
        out["crisis_state"] = out.get("state", "GREEN")
    out["crisis_state"] = out["crisis_state"].astype(str).str.upper().str.strip().replace({"": "GREEN"})
    out["spy_drawdown"] = pd.to_numeric(out.get("spy_drawdown", np.nan), errors="coerce")
    return out.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")


def price_at_or_before(prices: pd.DataFrame, dt: pd.Timestamp) -> tuple[pd.Timestamp | None, float | None]:
    actual_dt, px = price_on_or_before(prices, dt, "adj_close")
    if px is None:
        actual_dt, px = price_on_or_before(prices, dt, "close")
    return actual_dt, px


def price_at_or_after(prices: pd.DataFrame, dt: pd.Timestamp) -> tuple[pd.Timestamp | None, float | None]:
    actual_dt, px = price_on_or_after(prices, dt, "adj_close")
    if px is None:
        actual_dt, px = price_on_or_after(prices, dt, "close")
    return actual_dt, px


def trailing_return(prices: pd.DataFrame, dt: pd.Timestamp, days: int) -> float:
    now_dt, now_px = price_at_or_before(prices, dt)
    old_dt, old_px = price_at_or_before(prices, dt - pd.Timedelta(days=days))
    if now_px is None or old_px is None or old_px <= 0:
        return float("nan")
    return float(now_px / old_px - 1.0)


def forward_return(prices: pd.DataFrame, dt: pd.Timestamp, days: int) -> float:
    start_dt, start_px = price_at_or_after(prices, dt + pd.Timedelta(days=1))
    end_dt, end_px = price_at_or_after(prices, dt + pd.Timedelta(days=days))
    if start_px is None or end_px is None or start_px <= 0:
        return float("nan")
    return float(end_px / start_px - 1.0)


def trailing_volatility(prices: pd.DataFrame, dt: pd.Timestamp, days: int = 63) -> float:
    if prices.empty:
        return float("nan")
    d = prices.copy()
    d = d[d.index <= dt].tail(days + 1)
    if len(d) < max(10, days // 3):
        return float("nan")
    col = "adj_close" if "adj_close" in d.columns else "close"
    close = pd.to_numeric(d[col], errors="coerce").dropna()
    returns = close.pct_change().dropna()
    if returns.empty:
        return float("nan")
    return float(returns.std(ddof=0) * math.sqrt(252.0))


def ma_distance(prices: pd.DataFrame, dt: pd.Timestamp, days: int) -> float:
    if prices.empty:
        return float("nan")
    d = prices[prices.index <= dt].tail(days)
    if len(d) < max(10, days // 3):
        return float("nan")
    col = "adj_close" if "adj_close" in d.columns else "close"
    close = pd.to_numeric(d[col], errors="coerce").dropna()
    if close.empty:
        return float("nan")
    current = float(close.iloc[-1])
    avg = float(close.mean())
    if avg <= 0:
        return float("nan")
    return current / avg - 1.0


def crisis_state_for_date(crisis: pd.DataFrame, dt: pd.Timestamp) -> dict[str, Any]:
    if crisis.empty:
        return {"crisis_state": "UNKNOWN", "spy_drawdown": np.nan}
    d = crisis[crisis["date"] <= dt]
    if d.empty:
        return {"crisis_state": "UNKNOWN", "spy_drawdown": np.nan}
    row = d.iloc[-1].to_dict()
    return {"crisis_state": row.get("crisis_state", "UNKNOWN"), "spy_drawdown": safe_float(row.get("spy_drawdown"), float("nan"))}


def percentile_rank(values: pd.Series, *, high_is_fragile: bool = True) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    ranks = numeric.rank(pct=True)
    if not high_is_fragile:
        ranks = 1.0 - ranks
    return ranks.fillna(0.5).clip(0.0, 1.0)


def build_feature_rows(targets: pd.DataFrame, price_cache: Path, crisis: pd.DataFrame) -> pd.DataFrame:
    prices: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []
    for rec in targets.to_dict(orient="records"):
        ticker = clean_ticker(rec.get("ticker"))
        if ticker not in prices:
            prices[ticker] = load_price_series(price_cache, ticker)
        px = prices[ticker]
        dt = pd.Timestamp(rec["rebalance_date"]).normalize()
        crisis_row = crisis_state_for_date(crisis, dt)
        mom_21 = trailing_return(px, dt, 21)
        mom_63 = trailing_return(px, dt, 63)
        vol_63 = trailing_volatility(px, dt, 63)
        ma50 = ma_distance(px, dt, 50)
        ma200 = ma_distance(px, dt, 200)
        fwd_21 = forward_return(px, dt, 21)
        fwd_42 = forward_return(px, dt, 42)
        rows.append(
            {
                "rebalance_date": dt.date().isoformat(),
                "ticker": ticker,
                "target_weight": safe_float(rec.get("target_weight"), safe_float(rec.get("weight"))),
                "sector": rec.get("sector", ""),
                "industry_group": rec.get("industry_group", ""),
                "crisis_state": crisis_row["crisis_state"],
                "spy_drawdown": crisis_row["spy_drawdown"],
                "trailing_return_21d": mom_21,
                "trailing_return_63d": mom_63,
                "trailing_volatility_63d": vol_63,
                "ma50_distance": ma50,
                "ma200_distance": ma200,
                "rs_benchmark_3m": safe_float(rec.get("rs_benchmark_3m"), float("nan")),
                "atr14_pct": safe_float(rec.get("atr14_pct"), float("nan")),
                "price_above_ma200": safe_float(rec.get("price_above_ma200"), float("nan")),
                "actual_results_score": safe_float(rec.get("actual_results_score"), float("nan")),
                "audit_forward_return_21d": fwd_21,
                "audit_forward_return_42d": fwd_42,
                "audit_forward_downside_21d": min(0.0, fwd_21) if math.isfinite(fwd_21) else float("nan"),
                "audit_forward_downside_42d": min(0.0, fwd_42) if math.isfinite(fwd_42) else float("nan"),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["date_year"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.year
    frame["cluster_key"] = frame["sector"].astype(str).fillna("") + "|" + frame["industry_group"].astype(str).fillna("")
    cluster_weight = frame.groupby(["rebalance_date", "cluster_key"])["target_weight"].transform("sum")
    frame["cluster_weight"] = pd.to_numeric(cluster_weight, errors="coerce").fillna(0.0)
    frame["vol_rank"] = frame.groupby("rebalance_date")["trailing_volatility_63d"].transform(lambda s: percentile_rank(s, high_is_fragile=True))
    frame["atr_rank"] = frame.groupby("rebalance_date")["atr14_pct"].transform(lambda s: percentile_rank(s, high_is_fragile=True))
    frame["ma200_fragility_rank"] = frame.groupby("rebalance_date")["ma200_distance"].transform(lambda s: percentile_rank(s, high_is_fragile=False))
    frame["rs_fragility_rank"] = frame.groupby("rebalance_date")["rs_benchmark_3m"].transform(lambda s: percentile_rank(s, high_is_fragile=False))
    frame["cluster_rank"] = frame.groupby("rebalance_date")["cluster_weight"].transform(lambda s: percentile_rank(s, high_is_fragile=True))
    state_score = frame["crisis_state"].map({"GREEN": 0.0, "REENTRY_READY": 0.15, "WATCH": 0.35, "DEFENSE_REVIEW": 0.65, "CRISIS_DEFENSE": 0.85}).fillna(0.25)
    frame["market_fragility_score"] = state_score.clip(0.0, 1.0)
    frame["main_crash_fragility_score"] = (
        0.22 * frame["vol_rank"]
        + 0.16 * frame["atr_rank"]
        + 0.18 * frame["ma200_fragility_rank"]
        + 0.18 * frame["rs_fragility_rank"]
        + 0.14 * frame["cluster_rank"]
        + 0.12 * frame["market_fragility_score"]
    ).clip(0.0, 1.0)
    frame["fragility_bucket"] = pd.cut(
        frame["main_crash_fragility_score"],
        bins=[-0.01, 0.33, 0.66, 1.01],
        labels=["low", "medium", "high"],
    ).astype(str)
    return frame


def bucket_report(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for bucket, group in frame.groupby("fragility_bucket", dropna=False):
        rows.append(
            {
                "fragility_bucket": bucket,
                "rows": int(len(group)),
                "avg_weight": float(group["target_weight"].mean()),
                "avg_score": float(group["main_crash_fragility_score"].mean()),
                "avg_forward_return_21d": float(pd.to_numeric(group["audit_forward_return_21d"], errors="coerce").mean()),
                "avg_forward_downside_21d": float(pd.to_numeric(group["audit_forward_downside_21d"], errors="coerce").mean()),
                "avg_forward_return_42d": float(pd.to_numeric(group["audit_forward_return_42d"], errors="coerce").mean()),
                "avg_forward_downside_42d": float(pd.to_numeric(group["audit_forward_downside_42d"], errors="coerce").mean()),
                "negative_42d_rate": float((pd.to_numeric(group["audit_forward_return_42d"], errors="coerce") < 0).mean()),
            }
        )
    return pd.DataFrame(rows)


def mdd_window_rows(frame: pd.DataFrame, peak_date: str, trough_date: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    d = frame.copy()
    dates = pd.to_datetime(d["rebalance_date"], errors="coerce")
    peak = pd.to_datetime(peak_date, errors="coerce")
    trough = pd.to_datetime(trough_date, errors="coerce")
    if pd.isna(peak) or pd.isna(trough):
        return pd.DataFrame()
    return d[(dates >= peak - pd.Timedelta(days=45)) & (dates <= trough)].copy()


def verdict_from_reports(buckets: pd.DataFrame, frame: pd.DataFrame) -> dict[str, Any]:
    if buckets.empty or frame.empty:
        return {"screen_pass": False, "verdict": "blocked_empty_screen"}
    by_bucket = {str(row.fragility_bucket): row for row in buckets.itertuples(index=False)}
    high = by_bucket.get("high")
    low = by_bucket.get("low")
    if high is None or low is None:
        return {"screen_pass": False, "verdict": "blocked_missing_high_or_low_bucket"}
    high_down = safe_float(getattr(high, "avg_forward_downside_42d", None), 0.0)
    low_down = safe_float(getattr(low, "avg_forward_downside_42d", None), 0.0)
    high_rows = int(getattr(high, "rows", 0))
    low_rows = int(getattr(low, "rows", 0))
    years = frame.groupby(["date_year", "fragility_bucket"]).size().reset_index(name="rows")
    high_year_count = int(years[(years["fragility_bucket"].astype(str).eq("high")) & (years["rows"] >= 3)]["date_year"].nunique())
    downside_gap = high_down - low_down
    screen_pass = bool(high_rows >= 50 and low_rows >= 50 and high_year_count >= 3 and downside_gap <= -0.01)
    return {
        "screen_pass": screen_pass,
        "verdict": "screen_pass_design_default_off_hook" if screen_pass else "screen_reject_no_material_fragility_edge",
        "high_rows": high_rows,
        "low_rows": low_rows,
        "high_year_count": high_year_count,
        "avg_downside_42d_gap_high_minus_low": float(downside_gap),
    }


def render_report(summary: dict[str, Any], buckets: pd.DataFrame) -> str:
    lines = [
        "# Main Crash Fragility Screen",
        "",
        f"- status: `{summary.get('verdict')}`",
        f"- screen_pass: `{summary.get('screen_pass')}`",
        f"- rows: `{summary.get('rows')}`",
        f"- high-minus-low 42d downside gap: `{pct(summary.get('avg_downside_42d_gap_high_minus_low'))}`",
        "",
        "## Bucket Report",
        "",
        "| bucket | rows | avg score | avg 21d return | avg 42d return | avg 42d downside | negative 42d rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in buckets.sort_values("fragility_bucket").to_dict(orient="records"):
        lines.append(
            "| {fragility_bucket} | {rows} | {avg_score:.3f} | {r21} | {r42} | {d42} | {neg42} |".format(
                fragility_bucket=row.get("fragility_bucket"),
                rows=int(row.get("rows") or 0),
                avg_score=safe_float(row.get("avg_score")),
                r21=pct(row.get("avg_forward_return_21d")),
                r42=pct(row.get("avg_forward_return_42d")),
                d42=pct(row.get("avg_forward_downside_42d")),
                neg42=pct(row.get("negative_42d_rate")),
            )
        )
    lines.extend(
        [
            "",
            "Forward returns are audit labels only. This report does not create a",
            "live ranking signal, mutate production policy, or justify a fullrun.",
            "",
        ]
    )
    return "\n".join(lines)


def run(
    *,
    target_book: Path,
    price_cache: Path,
    crisis_state: Path,
    output_dir: Path,
    mdd_peak_date: str = "2020-02-19",
    mdd_trough_date: str = "2020-03-18",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = normalize_target_book(read_csv(target_book))
    crisis = normalize_crisis_state(read_csv(crisis_state))
    features = build_feature_rows(targets, price_cache, crisis)
    buckets = bucket_report(features)
    mdd_rows = mdd_window_rows(features, mdd_peak_date, mdd_trough_date)
    verdict = verdict_from_reports(buckets, features)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "research_only": True,
        "production_activation_allowed": False,
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "crisis_state": str(crisis_state),
        "rows": int(len(features)),
        "date_count": int(features["rebalance_date"].nunique()) if not features.empty else 0,
        "ticker_count": int(features["ticker"].nunique()) if not features.empty else 0,
        "mdd_peak_date": mdd_peak_date,
        "mdd_trough_date": mdd_trough_date,
        "mdd_window_rows": int(len(mdd_rows)),
        **verdict,
    }
    features.to_csv(output_dir / "fragility_rows.csv", index=False)
    buckets.to_csv(output_dir / "fragility_bucket_report.csv", index=False)
    mdd_rows.to_csv(output_dir / "mdd_window_attribution.csv", index=False)
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, buckets), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", default="outputs/alphaops_vnext/official_main_target_book.csv")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--crisis-state", default="outputs/alphaops_vnext/daily_crisis_state.csv")
    parser.add_argument("--output-dir", default="outputs/main_crash_fragility_screen")
    parser.add_argument("--mdd-peak-date", default="2020-02-19")
    parser.add_argument("--mdd-trough-date", default="2020-03-18")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run(
        target_book=repo_path(args.target_book),
        price_cache=repo_path(args.price_cache),
        crisis_state=repo_path(args.crisis_state),
        output_dir=repo_path(args.output_dir),
        mdd_peak_date=args.mdd_peak_date,
        mdd_trough_date=args.mdd_trough_date,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
