"""Build broker-replay operating target books from historical books plus latest targets.

The historical research books can be monthly, but the operating account should
not be locked to month-end decisions. This tool appends the latest target
recommendation as an operating decision row with an arbitrary signal date,
normally the latest available close across target tickers.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/reports"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
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


def clean_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def date_text(value: Any) -> str:
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return ""
    return pd.Timestamp(dt).date().isoformat()


def latest_date_from_columns(frame: pd.DataFrame, columns: list[str]) -> pd.Timestamp | None:
    dates: list[pd.Timestamp] = []
    for col in columns:
        if col not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[col], errors="coerce").dropna()
        if not parsed.empty:
            dates.append(pd.Timestamp(parsed.max()).normalize())
    return max(dates) if dates else None


def latest_price_close_date(price_cache: Path, tickers: list[str]) -> pd.Timestamp | None:
    dates: list[pd.Timestamp] = []
    for ticker in sorted({clean_ticker(t) for t in tickers if clean_ticker(t)}):
        px = load_price_series(price_cache, ticker)
        if px.empty:
            continue
        dates.append(pd.Timestamp(px.index.max()).normalize())
    return min(dates) if dates else None


def normalize_latest_target(frame: pd.DataFrame, portfolio: str) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns or "weight" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["ticker"] = out["ticker"].map(clean_ticker)
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
    out = out[(out["ticker"] != "") & (out["weight"] > 1e-12)].copy()
    if out.empty:
        return out
    out["portfolio_kind"] = portfolio
    out["operating_target_source"] = f"{portfolio}_latest_target"
    out["decision_frequency"] = "event_driven_latest_close"
    out["operating_decision_semantics"] = "latest_target_recommendation_appended_to_historical_book"
    return out


def add_missing_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = ""
    return out


def build_book(
    *,
    portfolio: str,
    history_path: Path,
    latest_target_path: Path,
    price_cache: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    history = read_csv(history_path)
    latest = normalize_latest_target(read_csv(latest_target_path), portfolio)
    if history.empty:
        history = pd.DataFrame(columns=["rebalance_date", "ticker", "weight"])
    if "rebalance_date" not in history.columns:
        history["rebalance_date"] = ""
    if "ticker" not in history.columns:
        history["ticker"] = ""
    if "weight" not in history.columns:
        history["weight"] = 0.0
    history = history.copy()
    history["rebalance_date"] = pd.to_datetime(history["rebalance_date"], errors="coerce").dt.normalize()
    history["ticker"] = history["ticker"].map(clean_ticker)
    history["weight"] = pd.to_numeric(history["weight"], errors="coerce").fillna(0.0)
    history = history[(history["ticker"] != "") & (history["weight"] > 1e-12)].copy()
    if not history.empty:
        history["operating_target_source"] = history.get("operating_target_source", "historical_target_book")
        history["decision_frequency"] = history.get("decision_frequency", "historical_research_schedule")
        history["operating_decision_semantics"] = history.get("operating_decision_semantics", "historical_research_target_book")

    history_max = latest_date_from_columns(history, ["rebalance_date"])
    # Do not use recommended_next_run_date here. It is a future scheduling hint,
    # not an observable signal date. Operating books must be dated to a price
    # close or an already-known feature/rebalance/as-of date.
    latest_target_date = latest_date_from_columns(latest, ["rebalance_date", "feature_date", "as_of_date", "last_trade_date"])
    price_close = latest_price_close_date(price_cache, latest["ticker"].astype(str).tolist()) if not latest.empty else None
    signal_date = price_close or latest_target_date
    appended = False
    append_reason = "latest target unavailable"
    latest_rows = pd.DataFrame()
    if not latest.empty and signal_date is not None:
        if history_max is None or pd.Timestamp(signal_date).normalize() > pd.Timestamp(history_max).normalize():
            latest_rows = latest.copy()
            latest_rows["rebalance_date"] = pd.Timestamp(signal_date).normalize()
            latest_rows["operating_signal_source_date"] = date_text(latest_target_date)
            latest_rows["operating_latest_price_date"] = date_text(price_close)
            latest_rows["operating_appended"] = True
            appended = True
            append_reason = "latest target appended as operating decision"
        else:
            append_reason = "latest signal date is not newer than historical target book"

    if "operating_appended" not in history.columns:
        history["operating_appended"] = False
    if "operating_signal_source_date" not in history.columns:
        history["operating_signal_source_date"] = ""
    if "operating_latest_price_date" not in history.columns:
        history["operating_latest_price_date"] = ""

    all_cols = list(dict.fromkeys(list(history.columns) + list(latest_rows.columns)))
    combined = pd.concat(
        [add_missing_columns(history, all_cols), add_missing_columns(latest_rows, all_cols)],
        ignore_index=True,
    )
    if not combined.empty:
        combined["rebalance_date"] = pd.to_datetime(combined["rebalance_date"], errors="coerce").dt.date.astype(str)
        combined = combined.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)

    output_name = f"operating_{portfolio}_target_book.csv"
    summary = {
        "portfolio": portfolio,
        "history_path": str(history_path),
        "latest_target_path": str(latest_target_path),
        "output_name": output_name,
        "history_row_count": int(len(history)),
        "latest_target_row_count": int(len(latest)),
        "output_row_count": int(len(combined)),
        "history_max_rebalance_date": date_text(history_max),
        "latest_target_source_date": date_text(latest_target_date),
        "latest_price_close_date": date_text(price_close),
        "operating_signal_date": date_text(signal_date),
        "latest_target_appended": bool(appended),
        "append_reason": append_reason,
        "decision_frequency": "event_driven_latest_close",
    }
    return combined, summary


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Operating Target Books",
        "",
        "Broker replay should use these operating target books when simulating the current account.",
        "Historical research books remain available, but they may be monthly and stale.",
        "",
        "| Portfolio | Rows | History max | Latest target source | Latest close | Operating signal | Appended |",
        "| --- | ---: | --- | --- | --- | --- | ---: |",
    ]
    for row in payload.get("books", []):
        lines.append(
            "| {portfolio} | {rows} | {history} | {source} | {close} | {signal} | {appended} |".format(
                portfolio=row.get("portfolio"),
                rows=row.get("output_row_count"),
                history=row.get("history_max_rebalance_date") or "",
                source=row.get("latest_target_source_date") or "",
                close=row.get("latest_price_close_date") or "",
                signal=row.get("operating_signal_date") or "",
                appended=str(row.get("latest_target_appended")).lower(),
            )
        )
    lines.append("")
    lines.append("A latest operating signal can be dated to the latest available close and filled by broker replay at the next available close.")
    lines.append("")
    return "\n".join(lines)


def build(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        ("main", latest_run / "reports" / "main_monthly_weights.csv", latest_run / "portfolio_latest.csv"),
        ("concentrated", latest_run / "reports" / "concentrated_strategy_holdings.csv", latest_run / "concentrated_portfolio_latest.csv"),
    ]
    summaries: list[dict[str, Any]] = []
    outputs: dict[str, str] = {}
    for portfolio, history_path, latest_target_path in specs:
        book, summary = build_book(
            portfolio=portfolio,
            history_path=history_path,
            latest_target_path=latest_target_path,
            price_cache=price_cache,
        )
        out_path = output_dir / str(summary["output_name"])
        book.to_csv(out_path, index=False)
        summary["output_path"] = str(out_path)
        outputs[f"{portfolio}_operating_target_book"] = str(out_path)
        summaries.append(summary)
    payload = {
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "books": summaries,
        "outputs": {
            **outputs,
            "summary_json": str(output_dir / "operating_target_books_summary.json"),
            "report_md": str(output_dir / "operating_target_books_report.md"),
        },
    }
    write_json(output_dir / "operating_target_books_summary.json", payload)
    (output_dir / "operating_target_books_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
