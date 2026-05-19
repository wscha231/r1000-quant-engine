#!/usr/bin/env python3
"""Build shadow ownership evidence scores from normalized SEC transactions."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_submissions_collector import repo_path  # noqa: E402

DEFAULT_FORM4 = "data_pit/sec/form4_transactions.parquet"
DEFAULT_OUTPUT_DIR = "outputs/sec_ownership_signals"
SIGNAL_COLUMNS = [
    "ticker",
    "latest_available_from",
    "insider_buy_count",
    "ten_percent_owner_buy_count",
    "ceo_cfo_buy_count",
    "insider_buy_value",
    "insider_sale_value",
    "sec_form4_open_market_buy_score",
    "sec_form4_cluster_buy_score",
    "sec_form4_ceo_cfo_buy_score",
    "sec_form4_ten_percent_owner_buy_score",
    "sec_form4_net_buy_score",
    "sec_form4_sale_pressure_score",
    "sec_form4_sale_risk_score",
    "early_evidence_score",
    "evidence_confidence_score",
]


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _safe_pct(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def bool_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def text_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].astype(str)


def valid_ticker_mask(series: pd.Series) -> pd.Series:
    ticker = series.astype(str).str.upper().str.strip()
    invalid = {"", "NONE", "N/A", "NA", "NAN", "NULL", "NOTAVAIL", "UNKNOWN"}
    pattern = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
    return ticker.map(lambda value: value not in invalid and bool(pattern.match(value)))


def build_form4_signal(df: pd.DataFrame, *, as_of: str | None = None, lookback_days: int = 90) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    d = df.copy()
    d["ticker"] = d.get("issuer_ticker", "").astype(str).str.upper().str.strip()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True)
    if as_of:
        cutoff = pd.to_datetime(as_of, errors="coerce", utc=True)
        if pd.notna(cutoff):
            d = d[d["available_from_ts"].notna() & (d["available_from_ts"] <= cutoff)].copy()
            d = d[d["available_from_ts"] >= cutoff - pd.Timedelta(days=int(lookback_days))].copy()
    d = d[valid_ticker_mask(d["ticker"])].copy()
    if d.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    code = d.get("transaction_code", "").astype(str).str.upper().str.strip()
    d["is_open_market_buy"] = code.eq("P")
    d["is_sale"] = code.eq("S")
    d["transaction_value_num"] = pd.to_numeric(d.get("transaction_value", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0)
    d["is_director_flag"] = bool_column(d, "is_director")
    d["is_officer_flag"] = bool_column(d, "is_officer")
    d["is_ten_percent_owner_flag"] = bool_column(d, "is_ten_percent_owner")
    d["role_weight"] = 1.0
    d.loc[d["is_director_flag"], "role_weight"] += 0.25
    d.loc[d["is_officer_flag"], "role_weight"] += 0.50
    d.loc[d["is_ten_percent_owner_flag"], "role_weight"] += 0.65
    title = text_column(d, "officer_title")
    d.loc[title.str.contains("CEO|Chief Executive", case=False, na=False), "role_weight"] += 1.00
    d.loc[title.str.contains("CFO|Chief Financial", case=False, na=False), "role_weight"] += 0.75
    d["value_score"] = (d["transaction_value_num"] / 1_000_000.0).clip(0.0, 3.0)
    d["form4_signal_raw"] = 0.0
    d.loc[d["is_open_market_buy"], "form4_signal_raw"] = d.loc[d["is_open_market_buy"], "role_weight"] * d.loc[
        d["is_open_market_buy"], "value_score"
    ]
    d["ceo_cfo_buy_raw"] = 0.0
    d.loc[d["is_open_market_buy"] & title.str.contains("CEO|CFO|Chief Executive|Chief Financial", case=False, na=False), "ceo_cfo_buy_raw"] = d[
        "form4_signal_raw"
    ]
    d["ten_percent_owner_buy_raw"] = 0.0
    d.loc[d["is_open_market_buy"] & d["is_ten_percent_owner_flag"], "ten_percent_owner_buy_raw"] = d["form4_signal_raw"]

    rows: list[dict[str, Any]] = []
    for ticker, group in d[d["ticker"].ne("")].groupby("ticker"):
        buy = group[group["is_open_market_buy"]]
        sale = group[group["is_sale"]]
        raw = float(group["form4_signal_raw"].sum())
        ceo_cfo_raw = float(group["ceo_cfo_buy_raw"].sum())
        ten_percent_raw = float(group["ten_percent_owner_buy_raw"].sum())
        buy_value = float(buy["transaction_value_num"].sum())
        sale_value = float(sale["transaction_value_num"].sum())
        cluster_count = int(buy["reporting_owner_cik"].astype(str).replace("", pd.NA).nunique(dropna=True))
        ten_percent_count = int((buy["is_ten_percent_owner_flag"]).sum()) if "is_ten_percent_owner_flag" in buy.columns else 0
        ceo_cfo_count = int(
            title.loc[buy.index].str.contains("CEO|CFO|Chief Executive|Chief Financial", case=False, na=False).sum()
        )
        open_market_score = _safe_pct(raw / 5.0)
        cluster_score = _safe_pct((raw / 5.0) + max(cluster_count - 1, 0) * 0.10)
        ceo_cfo_score = _safe_pct(ceo_cfo_raw / 3.0)
        ten_percent_owner_score = _safe_pct(ten_percent_raw / 3.0)
        sale_pressure = _safe_pct(sale_value / max(buy_value + sale_value, 1.0))
        net_buy_score = _safe_pct((buy_value - sale_value) / max(buy_value + sale_value, 1.0))
        sale_risk = _safe_pct(sale_pressure if buy_value <= 0.0 else 0.35 * sale_pressure)
        # Open-market buys are the signal. Sales are common for taxes, scheduled
        # plans, and diversification, so keep them as a light risk flag only.
        early_evidence = _safe_pct(
            0.45 * cluster_score
            + 0.22 * ceo_cfo_score
            + 0.15 * ten_percent_owner_score
            + 0.15 * open_market_score
            + 0.10 * net_buy_score
            - 0.08 * sale_risk
        )
        rows.append(
            {
                "ticker": ticker,
                "latest_available_from": group["available_from_ts"].max().isoformat()
                if pd.notna(group["available_from_ts"].max())
                else "",
                "insider_buy_count": int(len(buy)),
                "ten_percent_owner_buy_count": ten_percent_count,
                "ceo_cfo_buy_count": ceo_cfo_count,
                "insider_buy_value": buy_value,
                "insider_sale_value": sale_value,
                "sec_form4_open_market_buy_score": open_market_score,
                "sec_form4_cluster_buy_score": cluster_score,
                "sec_form4_ceo_cfo_buy_score": ceo_cfo_score,
                "sec_form4_ten_percent_owner_buy_score": ten_percent_owner_score,
                "sec_form4_net_buy_score": net_buy_score,
                "sec_form4_sale_pressure_score": sale_pressure,
                "sec_form4_sale_risk_score": sale_risk,
                "early_evidence_score": early_evidence,
                "evidence_confidence_score": _safe_pct(min(len(group), 10) / 10.0),
            }
        )
    if not rows:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    return pd.DataFrame(rows, columns=SIGNAL_COLUMNS).sort_values(
        ["early_evidence_score", "insider_buy_value"], ascending=False
    )


def render_report(summary: dict[str, Any], latest: pd.DataFrame) -> str:
    lines = [
        "# SEC Ownership Signals",
        "",
        "Research-only shadow evidence. Production score_total is not changed.",
        "",
        f"- form4 rows: {summary.get('form4_rows', 0)}",
        f"- signal tickers: {summary.get('signal_tickers', 0)}",
        f"- as_of: {summary.get('as_of') or 'latest available'}",
        "",
        "## Top Form 4 Evidence",
        "",
        "| ticker | early evidence | cluster | CEO/CFO | 10% owner | net buy | buy value | sale risk |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in latest.head(20).iterrows():
        lines.append(
            "| {ticker} | {early:.3f} | {cluster:.3f} | {ceo:.3f} | {tenpct:.3f} | {net:.3f} | ${buy:,.0f} | {sale:.3f} |".format(
                ticker=row.get("ticker", ""),
                early=float(row.get("early_evidence_score", 0.0)),
                cluster=float(row.get("sec_form4_cluster_buy_score", 0.0)),
                ceo=float(row.get("sec_form4_ceo_cfo_buy_score", 0.0)),
                tenpct=float(row.get("sec_form4_ten_percent_owner_buy_score", 0.0)),
                net=float(row.get("sec_form4_net_buy_score", 0.0)),
                buy=float(row.get("insider_buy_value", 0.0)),
                sale=float(row.get("sec_form4_sale_risk_score", 0.0)),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--form4", default=DEFAULT_FORM4)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--lookback-days", type=int, default=90)
    args = parser.parse_args()

    form4 = read_table(repo_path(args.form4))
    latest = build_form4_signal(form4, as_of=args.as_of or None, lookback_days=int(args.lookback_days))
    out = repo_path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    latest_csv = out / "form4_latest.csv"
    latest.to_csv(latest_csv, index=False)
    summary = {
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "insider_scope": "all Form 4 reporting owners; CEO/CFO and 10 percent owners receive higher shadow weights",
        "form4_rows": int(len(form4)),
        "signal_tickers": int(len(latest)),
        "as_of": args.as_of or "",
        "latest_csv": str(latest_csv),
    }
    write_json(out / "ownership_signal_summary.json", summary)
    (out / "report.md").write_text(render_report(summary, latest), encoding="utf-8")
    print(json.dumps({"status": "ok", **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
