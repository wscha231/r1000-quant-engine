#!/usr/bin/env python3
"""Build PIT 13F position events for post-disclosure alpha studies.

This D1 tool converts quarterly 13F holdings snapshots into event rows keyed by
manager, ticker, and filing availability. It is research-only and does not
change production scoring.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_submissions_collector import cik10  # noqa: E402

DEFAULT_13F = "data_pit/sec/institutional_13f_holdings.parquet"
DEFAULT_OUTPUT_DIR = "outputs/13f_position_events"
DEFAULT_PIT_OUTPUT = "data_pit/sec/13f_position_events.parquet"
DEFAULT_METADATA = "scored_latest.csv"

EVENT_COLUMNS = [
    "event_id",
    "source_type",
    "manager_cik",
    "manager_name",
    "ticker",
    "cusip",
    "issuer_name",
    "report_period",
    "filing_date",
    "accepted_at",
    "available_from",
    "event_type",
    "history_boundary",
    "shares",
    "previous_shares",
    "shares_delta",
    "market_value_usd",
    "previous_market_value_usd",
    "value_delta_usd",
    "position_weight",
    "previous_position_weight",
    "position_rank",
    "manager_conviction_rank",
    "issuer_market_cap",
    "issuer_float",
    "issuer_float_pct_owned",
    "manager_stake_to_float",
    "value_delta_to_mcap",
    "dollar_volume_20d",
    "market_cap_bucket",
    "liquidity_bucket",
    "sector",
    "industry",
    "post_disclosure_event_seed_score",
    "research_only",
    "production_activation_allowed",
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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def num(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def txt(frame: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=object)
    return frame[col].fillna(default).astype(str)


def safe_pct(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def market_cap_bucket(value: float) -> str:
    if not math.isfinite(value) or value <= 0:
        return "unknown"
    if value < 300_000_000:
        return "micro"
    if value < 2_000_000_000:
        return "small"
    if value < 10_000_000_000:
        return "mid"
    if value < 200_000_000_000:
        return "large"
    return "mega"


def liquidity_bucket(value: float) -> str:
    if not math.isfinite(value) or value <= 0:
        return "unknown"
    if value < 5_000_000:
        return "thin"
    if value < 20_000_000:
        return "low"
    if value < 100_000_000:
        return "medium"
    return "high"


def first_present(row: pd.Series, names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in row.index:
            value = row.get(name)
            if pd.notna(value) and str(value).strip() != "":
                return value
    return default


def normalize_holdings(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    d = frame.copy()
    d["manager_cik"] = txt(d, "manager_cik").map(cik10)
    d["ticker"] = txt(d, "ticker_mapped").where(txt(d, "ticker_mapped").str.strip().ne(""), txt(d, "ticker")).str.upper().str.strip()
    d["report_period_ts"] = pd.to_datetime(d.get("report_period"), errors="coerce").dt.normalize()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True)
    d["accepted_at_ts"] = pd.to_datetime(d.get("accepted_at"), errors="coerce", utc=True)
    d["shares"] = num(d, "shares").clip(lower=0.0)
    d["market_value_usd"] = num(d, "market_value_usd").clip(lower=0.0)
    d = d[d["manager_cik"].ne("") & d["ticker"].ne("") & d["report_period_ts"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    d = d.sort_values(["manager_cik", "ticker", "report_period_ts", "accepted_at_ts", "available_from_ts"])
    d = d.drop_duplicates(["manager_cik", "ticker", "report_period_ts"], keep="last")
    total = d.groupby(["manager_cik", "report_period_ts"])["market_value_usd"].transform("sum").replace(0.0, pd.NA)
    d["position_weight"] = (d["market_value_usd"] / total).fillna(0.0).clip(0.0, 1.0)
    d["position_rank"] = (
        d.groupby(["manager_cik", "report_period_ts"])["market_value_usd"].rank(method="first", ascending=False).fillna(0).astype(int)
    )
    d["manager_conviction_rank"] = (
        d.groupby(["manager_cik", "report_period_ts"])["position_weight"].rank(pct=True).fillna(0.0).clip(0.0, 1.0)
    )
    return d


def metadata_by_ticker(metadata: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if metadata.empty or "ticker" not in metadata.columns:
        return {}
    d = metadata.copy()
    d["ticker"] = txt(d, "ticker").str.upper().str.strip()
    d = d[d["ticker"].ne("")].drop_duplicates("ticker", keep="last")
    out: dict[str, dict[str, Any]] = {}
    for _, row in d.iterrows():
        ticker = str(row.get("ticker", "")).upper().strip()
        mcap = float(pd.to_numeric(pd.Series([first_present(row, ["market_cap_for_audit", "market_cap_live", "market_cap", "mktcap", "current_market_cap"], 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        issuer_float = float(pd.to_numeric(pd.Series([first_present(row, ["issuer_float", "shares_float", "float_shares", "free_float_shares"], 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        dollar_volume = float(pd.to_numeric(pd.Series([first_present(row, ["dollar_volume_20d", "avg_dollar_volume_20d", "avg_dollar_volume", "dollar_volume"], 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        out[ticker] = {
            "issuer_market_cap": mcap,
            "issuer_float": issuer_float,
            "dollar_volume_20d": dollar_volume,
            "sector": str(first_present(row, ["sector", "gics_sector", "sector_name"], "")),
            "industry": str(first_present(row, ["industry", "gics_industry", "sub_industry", "industry_group"], "")),
        }
    return out


def period_filing_meta(period_frame: pd.DataFrame) -> dict[str, Any]:
    d = period_frame.sort_values(["accepted_at_ts", "available_from_ts"])
    row = d.iloc[-1]
    return {
        "filing_date": str(first_present(row, ["filing_date"], "")),
        "accepted_at": str(first_present(row, ["accepted_at"], "")),
        "available_from": str(first_present(row, ["available_from", "accepted_at"], "")),
        "accepted_at_ts": row.get("accepted_at_ts"),
        "available_from_ts": row.get("available_from_ts"),
        "manager_name": str(first_present(row, ["manager_name"], "")),
    }


def event_type_for(current_shares: float, previous_shares: float, *, initial_period: bool) -> str:
    if initial_period and current_shares > 0 and previous_shares <= 0:
        return "initial"
    if current_shares > 0 and previous_shares <= 0:
        return "new"
    if current_shares <= 0 and previous_shares > 0:
        return "exit"
    if current_shares > 0 and previous_shares > 0 and current_shares > previous_shares:
        return "add"
    if current_shares > 0 and previous_shares > 0 and current_shares < previous_shares:
        return "trim"
    return "hold"


def seed_score(event: dict[str, Any]) -> float:
    event_type = str(event.get("event_type") or "")
    score = {
        "new": 0.35,
        "add": 0.22,
        "hold": 0.06,
        "initial": 0.02,
        "trim": -0.10,
        "exit": -0.25,
    }.get(event_type, 0.0)
    rank = float(event.get("position_rank") or 0.0)
    if 0 < rank <= 10:
        score += 0.16 * (1.0 - min(rank - 1.0, 9.0) / 9.0)
    score += 0.18 * safe_pct(float(event.get("value_delta_to_mcap") or 0.0) / 0.01)
    score += 0.12 * safe_pct(float(event.get("manager_stake_to_float") or 0.0) / 0.01)
    if str(event.get("market_cap_bucket")) in {"micro", "small"} and event_type in {"new", "add"}:
        score += 0.10
    if str(event.get("liquidity_bucket")) in {"thin", "unknown"} and event_type in {"new", "add"}:
        score -= 0.08
    return float(max(-1.0, min(1.0, score)))


def build_position_events(holdings: pd.DataFrame, metadata: pd.DataFrame | None = None) -> pd.DataFrame:
    d = normalize_holdings(holdings)
    if d.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    meta = metadata_by_ticker(metadata if metadata is not None else pd.DataFrame())
    rows: list[dict[str, Any]] = []
    for manager_cik, manager_frame in d.groupby("manager_cik", sort=True):
        periods = sorted(manager_frame["report_period_ts"].dropna().unique())
        previous = pd.DataFrame()
        for index, period in enumerate(periods):
            current = manager_frame[manager_frame["report_period_ts"].eq(period)].copy()
            filing = period_filing_meta(current)
            cur = current.set_index("ticker", drop=False)
            prev = previous.set_index("ticker", drop=False) if not previous.empty else pd.DataFrame()
            tickers = sorted(set(cur.index.astype(str)) | (set(prev.index.astype(str)) if not prev.empty else set()))
            for ticker in tickers:
                cur_row = cur.loc[ticker] if ticker in cur.index else pd.Series(dtype=object)
                prev_row = prev.loc[ticker] if not prev.empty and ticker in prev.index else pd.Series(dtype=object)
                shares = float(cur_row.get("shares", 0.0) or 0.0)
                prev_shares = float(prev_row.get("shares", 0.0) or 0.0)
                value = float(cur_row.get("market_value_usd", 0.0) or 0.0)
                prev_value = float(prev_row.get("market_value_usd", 0.0) or 0.0)
                event = event_type_for(shares, prev_shares, initial_period=(index == 0))
                m = meta.get(str(ticker).upper(), {})
                issuer_float = float(m.get("issuer_float") or 0.0)
                mcap = float(m.get("issuer_market_cap") or 0.0)
                dollar_volume = float(m.get("dollar_volume_20d") or 0.0)
                shares_delta = shares - prev_shares
                value_delta = value - prev_value
                row = {
                    "event_id": f"13f:{manager_cik}:{pd.Timestamp(period).date().isoformat()}:{ticker}",
                    "source_type": "13f",
                    "manager_cik": manager_cik,
                    "manager_name": str(cur_row.get("manager_name") or prev_row.get("manager_name") or filing.get("manager_name") or ""),
                    "ticker": str(ticker).upper().strip(),
                    "cusip": str(cur_row.get("cusip") or prev_row.get("cusip") or ""),
                    "issuer_name": str(cur_row.get("issuer_name") or prev_row.get("issuer_name") or ""),
                    "report_period": pd.Timestamp(period).date().isoformat(),
                    "filing_date": filing["filing_date"],
                    "accepted_at": filing["accepted_at"],
                    "available_from": filing["available_from"],
                    "event_type": event,
                    "history_boundary": bool(index == 0),
                    "shares": shares,
                    "previous_shares": prev_shares,
                    "shares_delta": shares_delta,
                    "market_value_usd": value,
                    "previous_market_value_usd": prev_value,
                    "value_delta_usd": value_delta,
                    "position_weight": float(cur_row.get("position_weight", 0.0) or 0.0),
                    "previous_position_weight": float(prev_row.get("position_weight", 0.0) or 0.0),
                    "position_rank": int(cur_row.get("position_rank", 0) or 0),
                    "manager_conviction_rank": float(cur_row.get("manager_conviction_rank", 0.0) or 0.0),
                    "issuer_market_cap": mcap,
                    "issuer_float": issuer_float,
                    "issuer_float_pct_owned": float(shares / issuer_float) if issuer_float > 0 else 0.0,
                    "manager_stake_to_float": float(max(shares_delta, 0.0) / issuer_float) if issuer_float > 0 else 0.0,
                    "value_delta_to_mcap": float(value_delta / mcap) if mcap > 0 else 0.0,
                    "dollar_volume_20d": dollar_volume,
                    "market_cap_bucket": market_cap_bucket(mcap),
                    "liquidity_bucket": liquidity_bucket(dollar_volume),
                    "sector": str(m.get("sector") or ""),
                    "industry": str(m.get("industry") or ""),
                    "research_only": True,
                    "production_activation_allowed": False,
                }
                row["post_disclosure_event_seed_score"] = seed_score(row)
                rows.append(row)
            previous = current
    out = pd.DataFrame(rows)
    for col in EVENT_COLUMNS:
        if col not in out.columns:
            out[col] = False if col in {"history_boundary", "research_only", "production_activation_allowed"} else ""
    return out[EVENT_COLUMNS].sort_values(["available_from", "manager_cik", "ticker"]).reset_index(drop=True)


def render_report(summary: dict[str, Any], events: pd.DataFrame) -> str:
    lines = [
        "# 13F Position Events",
        "",
        "Research-only event table for post-disclosure alpha studies.",
        "",
        f"- event rows: {summary.get('event_rows', 0)}",
        f"- manager count: {summary.get('manager_count', 0)}",
        f"- ticker count: {summary.get('ticker_count', 0)}",
        f"- latest available_from: `{summary.get('latest_available_from', '')}`",
        "",
        "## Event Counts",
        "",
        "| event_type | rows |",
        "| --- | ---: |",
    ]
    counts = events["event_type"].value_counts().to_dict() if "event_type" in events else {}
    for key, value in sorted(counts.items()):
        lines.append(f"| {key} | {int(value)} |")
    lines.extend(
        [
            "",
            "## Top Seed Events",
            "",
            "| available_from | manager | ticker | type | seed | mcap bucket | value delta |",
            "| --- | --- | --- | --- | ---: | --- | ---: |",
        ]
    )
    if not events.empty:
        top = events.sort_values("post_disclosure_event_seed_score", ascending=False).head(20)
        for _, row in top.iterrows():
            lines.append(
                "| {available} | {manager} | {ticker} | {event} | {score:.3f} | {bucket} | {delta:.0f} |".format(
                    available=row.get("available_from", ""),
                    manager=row.get("manager_name", ""),
                    ticker=row.get("ticker", ""),
                    event=row.get("event_type", ""),
                    score=float(row.get("post_disclosure_event_seed_score", 0.0)),
                    bucket=row.get("market_cap_bucket", ""),
                    delta=float(row.get("value_delta_usd", 0.0)),
                )
            )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    holdings_path = repo_path(args.holdings)
    metadata_path = repo_path(args.metadata)
    pit_output = repo_path(args.pit_output)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    holdings = read_table(holdings_path)
    metadata = read_table(metadata_path)
    events = build_position_events(holdings, metadata)
    write_table(events, pit_output)
    write_table(events, output_dir / "13f_position_events.csv")
    latest = events.copy()
    if not latest.empty and "available_from" in latest.columns:
        latest_ts = pd.to_datetime(latest["available_from"], errors="coerce", utc=True)
        latest = latest[latest_ts.eq(latest_ts.max())].copy() if latest_ts.notna().any() else latest.head(0)
    write_table(latest, output_dir / "latest.csv")

    available = pd.to_datetime(events.get("available_from"), errors="coerce", utc=True) if not events.empty else pd.Series(dtype="datetime64[ns, UTC]")
    accepted = pd.to_datetime(events.get("accepted_at"), errors="coerce", utc=True) if not events.empty else pd.Series(dtype="datetime64[ns, UTC]")
    comparable = available.notna() & accepted.notna()
    summary = {
        "status": "completed" if not events.empty else "blocked",
        "reason": "" if not events.empty else "missing 13F holdings with mapped tickers",
        "schema_version": "13f-position-events-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "holdings": str(holdings_path),
        "metadata": str(metadata_path),
        "pit_output": str(pit_output),
        "event_rows": int(len(events)),
        "latest_rows": int(len(latest)),
        "manager_count": int(events["manager_cik"].nunique()) if not events.empty else 0,
        "ticker_count": int(events["ticker"].nunique()) if not events.empty else 0,
        "latest_available_from": available.max().isoformat() if not events.empty and available.notna().any() else "",
        "missing_available_from": int(available.isna().sum()) if not events.empty else 0,
        "available_from_before_accepted_at": int((available[comparable] < accepted[comparable]).sum()) if not events.empty else 0,
        "event_counts": events["event_type"].value_counts().to_dict() if not events.empty else {},
        "outputs": {
            "pit_output": str(pit_output),
            "events_csv": str(output_dir / "13f_position_events.csv"),
            "latest_csv": str(output_dir / "latest.csv"),
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, events), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "event_rows": summary["event_rows"]}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", default=DEFAULT_13F)
    parser.add_argument("--metadata", default=DEFAULT_METADATA)
    parser.add_argument("--pit-output", default=DEFAULT_PIT_OUTPUT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
