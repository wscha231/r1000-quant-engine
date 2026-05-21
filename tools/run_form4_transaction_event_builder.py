#!/usr/bin/env python3
"""Build PIT Form 4 transaction events for post-disclosure alpha studies.

This D5 tool converts normalized Form 4 transactions into event rows that can
be labeled by `run_post_disclosure_alpha_labeler.py`. It keeps all transaction
codes for research, but only `P` open-market purchases are treated as positive
candidate events. Production scoring is not changed.
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

from tools.run_sec_submissions_collector import cik10  # noqa: E402

DEFAULT_FORM4 = "data_pit/sec/form4_transactions.parquet"
DEFAULT_METADATA = "scored_latest.csv"
DEFAULT_OUTPUT_DIR = "outputs/form4_transaction_events"
DEFAULT_PIT_OUTPUT = "data_pit/sec/form4_transaction_events.parquet"

EVENT_COLUMNS = [
    "event_id",
    "source_type",
    "ticker",
    "issuer_cik10",
    "reporting_owner_cik",
    "reporting_owner_name",
    "officer_title",
    "owner_role",
    "is_director",
    "is_officer",
    "is_ten_percent_owner",
    "transaction_date",
    "filing_date",
    "accepted_at",
    "available_from",
    "transaction_code",
    "form4_event_type",
    "is_open_market_buy",
    "is_sale",
    "is_signal_candidate",
    "transaction_shares",
    "transaction_price",
    "transaction_value",
    "transaction_value_score",
    "role_weight",
    "same_filing_owner_count",
    "same_filing_buy_count",
    "same_day_ticker_buy_count",
    "cluster_buy_score",
    "shares_owned_after",
    "direct_or_indirect",
    "security_title",
    "accession_number",
    "filing_url",
    "issuer_market_cap",
    "issuer_float",
    "transaction_value_to_mcap",
    "transaction_shares_to_float",
    "dollar_volume_20d",
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


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def text(frame: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=object)
    return frame[col].fillna(default).astype(str)


def num(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def bool_series(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    values = frame[col]
    if values.dtype == bool:
        return values.fillna(False).astype(bool)
    return values.fillna(False).astype(str).str.lower().isin({"1", "true", "yes", "y"})


def safe_pct(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def first_present(row: pd.Series, names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in row.index:
            value = row.get(name)
            if pd.notna(value) and str(value).strip() != "":
                return value
    return default


def metadata_by_ticker(metadata: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if metadata.empty or "ticker" not in metadata.columns:
        return {}
    d = metadata.copy()
    d["ticker"] = text(d, "ticker").str.upper().str.strip()
    d = d[d["ticker"].ne("")].drop_duplicates("ticker", keep="last")
    out: dict[str, dict[str, Any]] = {}
    for _, row in d.iterrows():
        ticker = str(row.get("ticker", "")).upper().strip()
        mcap = float(pd.to_numeric(pd.Series([first_present(row, ["market_cap_for_audit", "market_cap_live", "market_cap", "mktcap"], 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        issuer_float = float(pd.to_numeric(pd.Series([first_present(row, ["issuer_float", "shares_float", "float_shares", "free_float_shares"], 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        dollar_volume = float(pd.to_numeric(pd.Series([first_present(row, ["dollar_volume_20d", "avg_dollar_volume_20d", "avg_dollar_volume"], 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        out[ticker] = {
            "issuer_market_cap": mcap,
            "issuer_float": issuer_float,
            "dollar_volume_20d": dollar_volume,
            "sector": str(first_present(row, ["sector", "gics_sector", "sector_name"], "")),
            "industry": str(first_present(row, ["industry", "gics_industry", "sub_industry", "industry_group"], "")),
        }
    return out


def role_weight(row: pd.Series) -> float:
    weight = 1.0
    if bool(row.get("is_director", False)):
        weight += 0.25
    if bool(row.get("is_officer", False)):
        weight += 0.50
    if bool(row.get("is_ten_percent_owner", False)):
        weight += 0.20
    title = str(row.get("officer_title", ""))
    if pd.Series([title]).str.contains("CEO|Chief Executive", case=False, na=False).iloc[0]:
        weight += 1.00
    if pd.Series([title]).str.contains("CFO|Chief Financial", case=False, na=False).iloc[0]:
        weight += 0.75
    return float(weight)


def owner_role(row: pd.Series) -> str:
    title = str(row.get("officer_title", "")).strip()
    if title:
        return title
    roles: list[str] = []
    if bool(row.get("is_officer", False)):
        roles.append("officer")
    if bool(row.get("is_director", False)):
        roles.append("director")
    if bool(row.get("is_ten_percent_owner", False)):
        roles.append("ten_percent_owner")
    return "+".join(roles) if roles else "owner"


def form4_event_type(code: str) -> str:
    code = str(code).upper().strip()
    return {
        "P": "open_market_purchase",
        "S": "sale",
        "M": "option_exercise",
        "A": "grant_or_award",
        "F": "tax_withholding",
        "G": "gift",
    }.get(code, "other")


def normalize_transactions(form4: pd.DataFrame) -> pd.DataFrame:
    if form4.empty:
        return pd.DataFrame()
    d = form4.copy()
    d["ticker"] = text(d, "issuer_ticker").str.upper().str.strip()
    d["issuer_cik10"] = text(d, "issuer_cik10").map(cik10)
    d["reporting_owner_cik"] = text(d, "reporting_owner_cik").map(cik10)
    d["transaction_code"] = text(d, "transaction_code").str.upper().str.strip()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True)
    d["accepted_at_ts"] = pd.to_datetime(d.get("accepted_at"), errors="coerce", utc=True)
    d["transaction_shares"] = num(d, "transaction_shares").clip(lower=0.0)
    d["transaction_price"] = num(d, "transaction_price").clip(lower=0.0)
    d["transaction_value"] = num(d, "transaction_value").clip(lower=0.0)
    missing_value = d["transaction_value"].le(0.0) & d["transaction_shares"].gt(0.0) & d["transaction_price"].gt(0.0)
    d.loc[missing_value, "transaction_value"] = d.loc[missing_value, "transaction_shares"] * d.loc[missing_value, "transaction_price"]
    d["shares_owned_after"] = num(d, "shares_owned_after").clip(lower=0.0)
    d["is_director"] = bool_series(d, "is_director")
    d["is_officer"] = bool_series(d, "is_officer")
    d["is_ten_percent_owner"] = bool_series(d, "is_ten_percent_owner")
    d = d[d["ticker"].ne("") & d["available_from_ts"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    d = d.sort_values(["available_from_ts", "ticker", "accession_number", "reporting_owner_cik", "transaction_code"]).reset_index(drop=True)
    d["same_filing_owner_count"] = d.groupby(["ticker", "accession_number"])["reporting_owner_cik"].transform(lambda s: s.replace("", pd.NA).nunique(dropna=True)).fillna(0).astype(int)
    is_buy = d["transaction_code"].eq("P")
    d["same_filing_buy_count"] = is_buy.groupby([d["ticker"], d["accession_number"]]).transform("sum").fillna(0).astype(int)
    day_key = pd.to_datetime(d["available_from_ts"], errors="coerce", utc=True).dt.date.astype(str)
    d["same_day_ticker_buy_count"] = is_buy.groupby([d["ticker"], day_key]).transform("sum").fillna(0).astype(int)
    return d


def event_seed_score(row: pd.Series) -> float:
    code = str(row.get("transaction_code", "")).upper().strip()
    value_score = safe_pct(float(row.get("transaction_value_score") or 0.0))
    role = float(row.get("role_weight") or 1.0)
    cluster = safe_pct(float(row.get("cluster_buy_score") or 0.0))
    if code == "P":
        return float(max(0.0, min(1.0, 0.35 * value_score + 0.25 * safe_pct(role / 3.0) + 0.25 * cluster + 0.15 * safe_pct(float(row.get("transaction_shares_to_float") or 0.0) / 0.002))))
    if code == "S":
        return float(max(-1.0, min(0.0, -0.20 * value_score - 0.10 * safe_pct(role / 3.0))))
    return 0.0


def build_form4_events(form4: pd.DataFrame, metadata: pd.DataFrame | None = None) -> pd.DataFrame:
    d = normalize_transactions(form4)
    if d.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    meta = metadata_by_ticker(metadata if metadata is not None else pd.DataFrame())
    rows: list[dict[str, Any]] = []
    for idx, row in d.iterrows():
        ticker = str(row.get("ticker", "")).upper().strip()
        m = meta.get(ticker, {})
        mcap = float(m.get("issuer_market_cap") or 0.0)
        issuer_float = float(m.get("issuer_float") or 0.0)
        tx_value = float(row.get("transaction_value") or 0.0)
        tx_shares = float(row.get("transaction_shares") or 0.0)
        accession = str(row.get("accession_number") or "")
        code = str(row.get("transaction_code") or "").upper().strip()
        out = {
            "event_id": f"form4:{accession}:{idx}:{ticker}:{code}",
            "source_type": "form4",
            "ticker": ticker,
            "issuer_cik10": str(row.get("issuer_cik10") or ""),
            "reporting_owner_cik": str(row.get("reporting_owner_cik") or ""),
            "reporting_owner_name": str(row.get("reporting_owner_name") or ""),
            "officer_title": str(row.get("officer_title") or ""),
            "owner_role": owner_role(row),
            "is_director": bool(row.get("is_director", False)),
            "is_officer": bool(row.get("is_officer", False)),
            "is_ten_percent_owner": bool(row.get("is_ten_percent_owner", False)),
            "transaction_date": str(row.get("transaction_date") or ""),
            "filing_date": str(row.get("filing_date") or ""),
            "accepted_at": str(row.get("accepted_at") or ""),
            "available_from": str(row.get("available_from") or row.get("accepted_at") or ""),
            "transaction_code": code,
            "form4_event_type": form4_event_type(code),
            "is_open_market_buy": code == "P",
            "is_sale": code == "S",
            "is_signal_candidate": code in {"P", "S"},
            "transaction_shares": tx_shares,
            "transaction_price": float(row.get("transaction_price") or 0.0),
            "transaction_value": tx_value,
            "transaction_value_score": safe_pct(tx_value / 1_000_000.0),
            "role_weight": role_weight(row),
            "same_filing_owner_count": int(row.get("same_filing_owner_count") or 0),
            "same_filing_buy_count": int(row.get("same_filing_buy_count") or 0),
            "same_day_ticker_buy_count": int(row.get("same_day_ticker_buy_count") or 0),
            "cluster_buy_score": safe_pct(max(int(row.get("same_filing_buy_count") or 0), int(row.get("same_day_ticker_buy_count") or 0)) / 3.0),
            "shares_owned_after": float(row.get("shares_owned_after") or 0.0),
            "direct_or_indirect": str(row.get("direct_or_indirect") or ""),
            "security_title": str(row.get("security_title") or ""),
            "accession_number": accession,
            "filing_url": str(row.get("filing_url") or ""),
            "issuer_market_cap": mcap,
            "issuer_float": issuer_float,
            "transaction_value_to_mcap": float(tx_value / mcap) if mcap > 0 else 0.0,
            "transaction_shares_to_float": float(tx_shares / issuer_float) if issuer_float > 0 else 0.0,
            "dollar_volume_20d": float(m.get("dollar_volume_20d") or 0.0),
            "sector": str(m.get("sector") or ""),
            "industry": str(m.get("industry") or ""),
            "research_only": True,
            "production_activation_allowed": False,
        }
        out["post_disclosure_event_seed_score"] = event_seed_score(pd.Series(out))
        rows.append(out)
    events = pd.DataFrame(rows)
    for col in EVENT_COLUMNS:
        if col not in events.columns:
            events[col] = False if col in {"research_only", "production_activation_allowed"} else ""
    return events[EVENT_COLUMNS].sort_values(["available_from", "ticker", "event_id"]).reset_index(drop=True)


def render_report(summary: dict[str, Any], events: pd.DataFrame) -> str:
    lines = [
        "# Form 4 Transaction Events",
        "",
        "Research-only Form 4 event table for post-disclosure alpha studies.",
        "",
        f"- event rows: {summary.get('event_rows', 0)}",
        f"- signal candidates: {summary.get('signal_candidate_rows', 0)}",
        f"- P-code buys: {summary.get('p_code_buy_rows', 0)}",
        f"- S-code sales: {summary.get('s_code_sale_rows', 0)}",
        "",
        "## Code Counts",
        "",
        "| transaction_code | rows |",
        "| --- | ---: |",
    ]
    counts = events["transaction_code"].value_counts().to_dict() if "transaction_code" in events else {}
    for key, value in sorted(counts.items()):
        lines.append(f"| {key} | {int(value)} |")
    lines.extend(
        [
            "",
            "## Top P-Code Events",
            "",
            "| available_from | ticker | owner | role | value | seed | cluster |",
            "| --- | --- | --- | --- | ---: | ---: | ---: |",
        ]
    )
    if not events.empty:
        top = events[events["transaction_code"].eq("P")].sort_values("post_disclosure_event_seed_score", ascending=False).head(20)
        for _, row in top.iterrows():
            lines.append(
                "| {available} | {ticker} | {owner} | {role} | ${value:,.0f} | {seed:.3f} | {cluster:.3f} |".format(
                    available=row.get("available_from", ""),
                    ticker=row.get("ticker", ""),
                    owner=row.get("reporting_owner_name", ""),
                    role=row.get("owner_role", ""),
                    value=float(row.get("transaction_value", 0.0)),
                    seed=float(row.get("post_disclosure_event_seed_score", 0.0)),
                    cluster=float(row.get("cluster_buy_score", 0.0)),
                )
            )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    form4_path = repo_path(args.form4)
    metadata_path = repo_path(args.metadata)
    pit_output = repo_path(args.pit_output)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    form4 = read_table(form4_path)
    metadata = read_table(metadata_path)
    events = build_form4_events(form4, metadata)
    write_table(events, pit_output)
    write_table(events, output_dir / "form4_transaction_events.csv")
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
        "reason": "" if not events.empty else "missing Form 4 transactions with tickers and available_from",
        "schema_version": "form4-transaction-events-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "form4": str(form4_path),
        "metadata": str(metadata_path),
        "pit_output": str(pit_output),
        "event_rows": int(len(events)),
        "latest_rows": int(len(latest)),
        "ticker_count": int(events["ticker"].nunique()) if not events.empty else 0,
        "owner_count": int(events["reporting_owner_cik"].nunique()) if not events.empty else 0,
        "signal_candidate_rows": int(events["is_signal_candidate"].sum()) if not events.empty else 0,
        "p_code_buy_rows": int(events["transaction_code"].eq("P").sum()) if not events.empty else 0,
        "s_code_sale_rows": int(events["transaction_code"].eq("S").sum()) if not events.empty else 0,
        "latest_available_from": available.max().isoformat() if not events.empty and available.notna().any() else "",
        "missing_available_from": int(available.isna().sum()) if not events.empty else 0,
        "available_from_before_accepted_at": int((available[comparable] < accepted[comparable]).sum()) if not events.empty else 0,
        "transaction_code_counts": events["transaction_code"].value_counts().to_dict() if not events.empty else {},
        "outputs": {
            "pit_output": str(pit_output),
            "events_csv": str(output_dir / "form4_transaction_events.csv"),
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
    parser.add_argument("--form4", default=DEFAULT_FORM4)
    parser.add_argument("--metadata", default=DEFAULT_METADATA)
    parser.add_argument("--pit-output", default=DEFAULT_PIT_OUTPUT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
