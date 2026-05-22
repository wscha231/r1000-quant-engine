#!/usr/bin/env python3
"""Build a research-only deep dive for top-manager 13F new/add positions.

This is a narrower companion to the aggregate smart-money reports. It is
designed to surface the small and mid-sized names that high-priority managers
newly bought or added, especially AI infrastructure, semiconductors, data-center
supply-chain, power, and crypto-compute themes. It does not change production
scores or target books.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_HOLDINGS = "data_pit/sec/institutional_13f_holdings.parquet"
DEFAULT_MANAGERS = "research/sec_13f_manager_universe_20260519/managers.csv"
DEFAULT_OUTPUT_DIR = "outputs/top_manager_13f_deep_dive"
HOLDINGS_COLUMNS = [
    "manager_cik",
    "manager_name",
    "report_period",
    "accepted_at",
    "available_from",
    "cusip",
    "issuer_name",
    "ticker_mapped",
    "ticker",
    "shares",
    "market_value_usd",
    "put_call",
]

AI_COMPUTE_TICKERS = {
    "CRWV",
    "APLD",
    "NBIS",
    "VRT",
    "SMCI",
    "DELL",
    "PSTG",
    "ANET",
    "MOD",
    "LITE",
    "GLW",
    "STX",
    "WYFI",
}
SEMI_TICKERS = {"NVDA", "AMD", "AVGO", "TSM", "ASML", "MU", "MRVL", "ARM", "SNDK", "INTC", "QCOM", "AMAT", "LRCX"}
POWER_TICKERS = {"TE", "BE", "CEG", "OKLO", "SMR", "VST", "GEV", "ETN", "PWR", "PSIX", "BW", "SEI"}
CRYPTO_COMPUTE_TICKERS = {"CLSK", "IREN", "RIOT", "CORZ", "BITF", "BTDR", "HIVE", "CIFR", "MARA", "WULF", "HUT"}

OUTPUT_COLUMNS = [
    "rank",
    "ticker",
    "issuer_name",
    "cusip",
    "theme_bucket",
    "top_manager_focus_score",
    "event_type",
    "manager_label",
    "manager_name",
    "manager_cik",
    "selected_manager_rank",
    "manager_user_priority",
    "manager_external_performance_2y",
    "manager_performance_26q1",
    "allocation_tier",
    "report_period",
    "accepted_at",
    "available_from",
    "shares",
    "previous_shares",
    "shares_delta",
    "market_value_usd",
    "previous_market_value_usd",
    "value_delta_usd",
    "position_weight",
    "position_rank",
    "cross_manager_holder_count",
    "cross_manager_total_value_usd",
    "underfollowed_top_manager_pick",
    "ai_infra_theme_flag",
    "source_expansion_reason",
]


def repo_path(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def read_table(path: str | Path) -> pd.DataFrame:
    p = repo_path(path)
    if not p.exists():
        return pd.DataFrame()
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p)
    return pd.read_csv(p, low_memory=False)


def read_holdings(path: str | Path) -> pd.DataFrame:
    p = repo_path(path)
    if not p.exists():
        return pd.DataFrame()
    if p.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq

            names = set(pq.read_schema(p).names)
            cols = [col for col in HOLDINGS_COLUMNS if col in names]
            return pd.read_parquet(p, columns=cols or None)
        except Exception:
            try:
                return pd.read_parquet(p, columns=[col for col in HOLDINGS_COLUMNS if col != "ticker"])
            except Exception:
                return pd.read_parquet(p)
    try:
        return pd.read_csv(p, low_memory=False, usecols=lambda col: col in set(HOLDINGS_COLUMNS))
    except Exception:
        return pd.read_csv(p, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _bool_series(frame: pd.DataFrame, col: str, default: bool = False) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="bool")
    return frame[col].fillna(default).astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[col], errors="coerce").fillna(default).astype(float)


def _text(frame: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="object")
    return frame[col].fillna(default).astype(str)


def normalize_cik(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return f"{int(float(text)):010d}"
    except Exception:
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits.zfill(10) if digits else text


def normalize_ticker(frame: pd.DataFrame) -> pd.Series:
    if "ticker_mapped" in frame.columns:
        raw = frame["ticker_mapped"]
    elif "ticker" in frame.columns:
        raw = frame["ticker"]
    else:
        raw = pd.Series("", index=frame.index, dtype="object")
    return raw.fillna("").astype(str).str.upper().str.strip()


def select_top_managers(managers: pd.DataFrame, *, top_manager_count: int = 10) -> pd.DataFrame:
    if managers.empty:
        return pd.DataFrame()
    d = managers.copy()
    d["active_bool"] = _bool_series(d, "active", True)
    d["verified_bool"] = _bool_series(d, "verified_cik", False)
    d = d[d["active_bool"] & d["verified_bool"]].copy()
    if d.empty:
        return d
    d["cik10"] = _text(d, "cik10").map(normalize_cik)
    d["user_priority_num"] = _numeric(d, "user_priority", 9999.0)
    d["external_performance_2y_num"] = _numeric(d, "external_performance_2y", float("nan"))
    d["performance_26q1_num"] = _numeric(d, "performance_26q1", float("nan"))
    d["performance_signal"] = d["external_performance_2y_num"].where(
        d["external_performance_2y_num"].notna(), d["performance_26q1_num"]
    )
    d["has_external_performance"] = d["external_performance_2y_num"].notna()
    d["performance_sort"] = d["external_performance_2y_num"].fillna(d["performance_26q1_num"]).fillna(-1.0)
    situational = d[d["label"].astype(str).str.upper().eq("SITUATIONAL")].copy()
    others = d.drop(index=situational.index, errors="ignore")
    others = others.sort_values(
        ["has_external_performance", "performance_sort", "user_priority_num", "label"],
        ascending=[False, False, True, True],
    )
    d = pd.concat([situational.head(1), others], ignore_index=True).head(int(top_manager_count))
    d = d.reset_index(drop=True)
    d["selected_manager_rank"] = range(1, len(d) + 1)
    return d


def theme_bucket(ticker: Any, issuer_name: Any) -> str:
    ticker_text = str(ticker or "").upper().strip()
    issuer = str(issuer_name or "").upper()
    buckets: list[str] = []
    if ticker_text in AI_COMPUTE_TICKERS or any(k in issuer for k in ["COREWEAVE", "APPLIED DIGITAL", "DATA CENTER"]):
        buckets.append("ai_compute")
    if ticker_text in SEMI_TICKERS or any(k in issuer for k in ["SEMICONDUCTOR", "MICRON", "ASML", "SANDISK"]):
        buckets.append("semiconductors")
    if ticker_text in POWER_TICKERS or any(
        k in issuer for k in ["T1 ENERGY", "ENERGY FUELS", "POWER", "NUCLEAR", "SOLAR", "SOLARIS", "BLOOM", "GRID"]
    ):
        buckets.append("power_infrastructure")
    if ticker_text in CRYPTO_COMPUTE_TICKERS or any(k in issuer for k in ["CLEANSPARK", "BITFARMS", "BITDEER", "RIOT"]):
        buckets.append("crypto_compute")
    return ",".join(dict.fromkeys(buckets))


def _event_type(shares_delta: float, previous_shares: float) -> str:
    if previous_shares <= 0.0 and shares_delta > 0.0:
        return "new_position"
    if shares_delta > 0.0:
        return "added_position"
    if shares_delta < 0.0:
        return "trimmed_position"
    return "unchanged_position"


def _score_event(event_type: str) -> float:
    return {
        "new_position": 0.34,
        "added_position": 0.26,
        "unchanged_position": 0.03,
        "trimmed_position": -0.12,
    }.get(str(event_type), 0.0)


def _reason(row: pd.Series) -> str:
    event = str(row.get("event_type", ""))
    theme = str(row.get("theme_bucket", "") or "")
    holders = int(float(row.get("cross_manager_holder_count", 0.0) or 0.0))
    pos_w = float(row.get("position_weight", 0.0) or 0.0)
    delta = float(row.get("value_delta_usd", 0.0) or 0.0)
    parts = [
        f"{row.get('manager_label', '')} {event.replace('_', ' ')}",
        f"position_weight={pos_w:.2%}",
        f"delta=${delta:,.0f}",
        f"cross_manager_holders={holders}",
    ]
    if theme:
        parts.append(f"theme={theme}")
    if bool(row.get("underfollowed_top_manager_pick", False)):
        parts.append("underfollowed_top_manager_pick")
    return "; ".join(parts)


def build_top_manager_deep_dive(
    holdings: pd.DataFrame,
    managers: pd.DataFrame,
    *,
    top_manager_count: int = 10,
) -> pd.DataFrame:
    selected = select_top_managers(managers, top_manager_count=top_manager_count)
    if holdings.empty or selected.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    d = holdings.copy()
    d["manager_cik"] = _text(d, "manager_cik").map(normalize_cik)
    d["ticker"] = normalize_ticker(d)
    d["put_call_text"] = _text(d, "put_call").str.strip()
    d = d[d["manager_cik"].isin(set(selected["cik10"])) & d["ticker"].ne("") & d["put_call_text"].eq("")].copy()
    if d.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    d["report_period_dt"] = pd.to_datetime(_text(d, "report_period"), errors="coerce")
    d["shares_num"] = _numeric(d, "shares", 0.0)
    d["value_num"] = _numeric(d, "market_value_usd", 0.0)
    d["accepted_at"] = _text(d, "accepted_at")
    d["available_from"] = _text(d, "available_from")
    d["issuer_name"] = _text(d, "issuer_name")
    d["cusip"] = _text(d, "cusip")

    manager_periods = (
        d.dropna(subset=["report_period_dt"])
        .groupby("manager_cik")["report_period_dt"]
        .agg(lambda s: sorted(s.dropna().unique())[-2:])
        .to_dict()
    )
    frames: list[pd.DataFrame] = []
    for cik, periods in manager_periods.items():
        if not periods:
            continue
        latest_period = periods[-1]
        previous_period = periods[-2] if len(periods) >= 2 else pd.NaT
        latest = d[(d["manager_cik"].eq(cik)) & (d["report_period_dt"].eq(latest_period))].copy()
        prev = d[(d["manager_cik"].eq(cik)) & (d["report_period_dt"].eq(previous_period))].copy() if pd.notna(previous_period) else pd.DataFrame()
        if latest.empty:
            continue
        latest_g = (
            latest.groupby(["manager_cik", "ticker", "cusip", "issuer_name"], dropna=False)
            .agg(
                shares=("shares_num", "sum"),
                market_value_usd=("value_num", "sum"),
                report_period=("report_period", "max"),
                accepted_at=("accepted_at", "max"),
                available_from=("available_from", "max"),
            )
            .reset_index()
        )
        if prev.empty:
            prev_g = pd.DataFrame(columns=["manager_cik", "ticker", "cusip", "previous_shares", "previous_market_value_usd"])
        else:
            prev_g = (
                prev.groupby(["manager_cik", "ticker", "cusip"], dropna=False)
                .agg(previous_shares=("shares_num", "sum"), previous_market_value_usd=("value_num", "sum"))
                .reset_index()
            )
        merged = latest_g.merge(prev_g, on=["manager_cik", "ticker", "cusip"], how="left")
        merged[["previous_shares", "previous_market_value_usd"]] = merged[["previous_shares", "previous_market_value_usd"]].fillna(0.0)
        frames.append(merged)
    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    out = pd.concat(frames, ignore_index=True)
    out["shares_delta"] = out["shares"] - out["previous_shares"]
    out["value_delta_usd"] = out["market_value_usd"] - out["previous_market_value_usd"]
    out["event_type"] = [
        _event_type(delta, prev) for delta, prev in zip(out["shares_delta"].astype(float), out["previous_shares"].astype(float))
    ]
    latest_totals = out.groupby("manager_cik")["market_value_usd"].transform("sum").replace(0.0, float("nan"))
    out["position_weight"] = (out["market_value_usd"] / latest_totals).fillna(0.0)
    out["position_rank"] = out.groupby("manager_cik")["market_value_usd"].rank(method="first", ascending=False).astype(int)

    latest_all_period = d["report_period_dt"].max()
    latest_all = d[d["report_period_dt"].eq(latest_all_period)].copy()
    breadth = (
        latest_all.groupby("ticker")
        .agg(cross_manager_holder_count=("manager_cik", "nunique"), cross_manager_total_value_usd=("value_num", "sum"))
        .reset_index()
    )
    out = out.merge(breadth, on="ticker", how="left")
    out[["cross_manager_holder_count", "cross_manager_total_value_usd"]] = out[
        ["cross_manager_holder_count", "cross_manager_total_value_usd"]
    ].fillna(0.0)

    selected_cols = selected[
        [
            "label",
            "manager_name",
            "cik10",
            "selected_manager_rank",
            "user_priority_num",
            "external_performance_2y_num",
            "performance_26q1_num",
            "allocation_tier",
        ]
    ].rename(
        columns={
            "label": "manager_label",
            "cik10": "manager_cik",
            "user_priority_num": "manager_user_priority",
            "external_performance_2y_num": "manager_external_performance_2y",
            "performance_26q1_num": "manager_performance_26q1",
        }
    )
    out = out.merge(selected_cols, on="manager_cik", how="left")
    out["theme_bucket"] = [theme_bucket(t, n) for t, n in zip(out["ticker"], out["issuer_name"])]
    out["ai_infra_theme_flag"] = out["theme_bucket"].astype(str).str.len() > 0
    out["underfollowed_top_manager_pick"] = (
        out["event_type"].isin(["new_position", "added_position"])
        & (pd.to_numeric(out["cross_manager_holder_count"], errors="coerce").fillna(0.0) <= 3.0)
    )

    manager_factor = 1.0 - ((pd.to_numeric(out["selected_manager_rank"], errors="coerce").fillna(top_manager_count) - 1.0) / max(1.0, float(top_manager_count)))
    event_score = out["event_type"].map(_score_event).fillna(0.0)
    position_score = out["position_weight"].clip(0.0, 0.20) / 0.20 * 0.18
    delta_score = (out["value_delta_usd"].clip(lower=0.0).map(lambda x: math.log1p(float(x))) / math.log1p(500_000_000.0)).clip(0.0, 1.0) * 0.14
    underfollowed_bonus = out["underfollowed_top_manager_pick"].astype(float) * 0.14
    theme_bonus = out["ai_infra_theme_flag"].astype(float) * 0.12
    out["top_manager_focus_score"] = (
        0.22 * manager_factor + event_score + position_score + delta_score + underfollowed_bonus + theme_bonus
    ).clip(0.0, 1.0)
    out["source_expansion_reason"] = out.apply(_reason, axis=1)
    out = out[out["event_type"].isin(["new_position", "added_position", "unchanged_position", "trimmed_position"])].copy()
    out = out.sort_values(
        ["top_manager_focus_score", "ai_infra_theme_flag", "underfollowed_top_manager_pick", "value_delta_usd"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    for col in OUTPUT_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    return out[OUTPUT_COLUMNS]


def render_report(summary: dict[str, Any], top: pd.DataFrame) -> str:
    lines = [
        "# Top-Manager 13F Deep Dive",
        "",
        "Research-only detail table for the highest-priority managers' latest 13F new/add/trim events.",
        "Production `score_total` and target books are not changed by this artifact.",
        "",
        f"- selected managers: {summary.get('selected_manager_count', 0)}",
        f"- detailed rows: {summary.get('detailed_rows', 0)}",
        f"- new/add rows: {summary.get('new_or_added_rows', 0)}",
        f"- AI/theme rows: {summary.get('ai_theme_rows', 0)}",
        "",
        "| rank | ticker | score | event | manager | theme | reason |",
        "| ---: | --- | ---: | --- | --- | --- | --- |",
    ]
    for _, row in top.iterrows():
        lines.append(
            "| {rank:.0f} | {ticker} | {score:.3f} | {event} | {manager} | {theme} | {reason} |".format(
                rank=float(row.get("rank", 0.0)),
                ticker=str(row.get("ticker", "")),
                score=float(row.get("top_manager_focus_score", 0.0)),
                event=str(row.get("event_type", "")),
                manager=str(row.get("manager_label", "")),
                theme=str(row.get("theme_bucket", "")).replace("|", "/"),
                reason=str(row.get("source_expansion_reason", "")).replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", default=DEFAULT_HOLDINGS)
    parser.add_argument("--managers", default=DEFAULT_MANAGERS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-manager-count", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=200)
    args = parser.parse_args()

    holdings = read_holdings(args.holdings)
    managers = read_table(args.managers)
    ranked = build_top_manager_deep_dive(holdings, managers, top_manager_count=int(args.top_manager_count))
    selected = select_top_managers(managers, top_manager_count=int(args.top_manager_count))

    out_dir = repo_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(out_dir / "top_manager_13f_deep_dive.csv", index=False)
    latest = ranked.head(int(args.top_n)).copy()
    latest.to_csv(out_dir / "latest.csv", index=False)
    selected.to_csv(out_dir / "selected_managers.csv", index=False)
    summary = {
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "holdings_rows": int(len(holdings)),
        "selected_manager_count": int(len(selected)),
        "detailed_rows": int(len(ranked)),
        "new_or_added_rows": int(ranked["event_type"].isin(["new_position", "added_position"]).sum()) if not ranked.empty else 0,
        "ai_theme_rows": int(ranked["ai_infra_theme_flag"].sum()) if "ai_infra_theme_flag" in ranked.columns else 0,
        "top_n": int(args.top_n),
        "latest_csv": str(out_dir / "latest.csv"),
        "ranked_csv": str(out_dir / "top_manager_13f_deep_dive.csv"),
    }
    write_json(out_dir / "summary.json", summary)
    (out_dir / "report.md").write_text(render_report(summary, latest.head(30)), encoding="utf-8")
    print(json.dumps({"status": "ok", **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
