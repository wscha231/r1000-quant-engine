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

SEC_EVIDENCE_FEATURE_COLUMNS = [
    "smart_money_score",
    "smart_money_shadow_score",
    "smart_money_convergence_bonus",
    "sec_evidence_score",
    "sec_combined_evidence_score",
    "sec_form4_score",
    "form4_net_buy_score",
    "institutional_13f_score",
    "institutional_evidence_score",
    "institutional_accumulation_score",
    "sec_13f_smart_money_score",
    "sec_13f_accumulation_score",
    "leader_onset_sec_v3_score",
    "evidence_fusion_score",
    "etf_theme_leadership_score",
    "etf_holdings_score",
    "rows_with_smart_money_evidence",
    "latest_available_from",
    "latest_13f_available_from",
    "latest_etf_available_from",
    "latest_top_manager_available_from",
    "sec_evidence_research_only",
    "sec_evidence_production_activation_allowed",
    "sec_evidence_source",
]


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


def clean_filter_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        number = float(text)
        if pd.notna(number) and abs(number - round(number)) < 1e-9:
            return str(int(round(number)))
    except (TypeError, ValueError):
        pass
    return text


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


def latest_sec_enriched_candidates(
    latest_run: Path,
    *,
    as_of_date: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    metadata: dict[str, Any] = {
        "sec_evidence_feature_as_of_date": date_text(as_of_date),
        "sec_evidence_feature_future_rows_excluded": 0,
    }
    candidates = [
        latest_run / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
        REPO_ROOT / "outputs" / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
    ]
    for path in candidates:
        frame = read_csv(path)
        if frame.empty or "ticker" not in frame.columns:
            continue
        d = frame.copy()
        d["ticker"] = d["ticker"].map(clean_ticker)
        d = d[d["ticker"].ne("")].copy()
        if d.empty:
            continue
        date_cols = [col for col in ("rebalance_date", "feature_date", "as_of_date", "date") if col in d.columns]
        if date_cols:
            parsed = pd.DataFrame({col: pd.to_datetime(d[col], errors="coerce") for col in date_cols})
            d["_sec_evidence_row_date"] = parsed.max(axis=1)
            if as_of_date is not None and d["_sec_evidence_row_date"].notna().any():
                cutoff = pd.Timestamp(as_of_date).normalize()
                future = d["_sec_evidence_row_date"].notna() & (d["_sec_evidence_row_date"] > cutoff)
                metadata["sec_evidence_feature_future_rows_excluded"] = int(future.sum())
                d = d.loc[~future].copy()
                if d.empty:
                    continue
            if d["_sec_evidence_row_date"].notna().any():
                d = d.sort_values(["ticker", "_sec_evidence_row_date"]).copy()
        keep = ["ticker", *[col for col in SEC_EVIDENCE_FEATURE_COLUMNS if col in d.columns]]
        if len(keep) <= 1:
            continue
        d = d[keep].drop_duplicates(subset=["ticker"], keep="last").copy()
        return d, str(path), metadata
    return pd.DataFrame(), "", metadata


def attach_sec_evidence_features(
    latest_run: Path,
    latest_rows: pd.DataFrame,
    *,
    as_of_date: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    metadata: dict[str, Any] = {
        "sec_evidence_feature_source": "",
        "sec_evidence_feature_columns_added": [],
        "sec_evidence_feature_rows_matched": 0,
        "sec_evidence_feature_rows_total": int(len(latest_rows)),
        "sec_evidence_feature_as_of_date": date_text(as_of_date),
        "sec_evidence_feature_future_rows_excluded": 0,
    }
    if latest_rows.empty or "ticker" not in latest_rows.columns:
        return latest_rows, metadata
    enriched, source, source_metadata = latest_sec_enriched_candidates(latest_run, as_of_date=as_of_date)
    metadata.update(source_metadata)
    if enriched.empty:
        return latest_rows, metadata
    feature_cols = [col for col in enriched.columns if col != "ticker"]
    out = latest_rows.drop(columns=[col for col in feature_cols if col in latest_rows.columns], errors="ignore").merge(
        enriched,
        on="ticker",
        how="left",
    )
    matched = int(out[feature_cols].notna().any(axis=1).sum()) if feature_cols else 0
    if "rows_with_smart_money_evidence" in out.columns:
        out["rows_with_smart_money_evidence"] = pd.to_numeric(out["rows_with_smart_money_evidence"], errors="coerce").fillna(0.0)
    for col in [
        "smart_money_score",
        "smart_money_shadow_score",
        "smart_money_convergence_bonus",
        "sec_evidence_score",
        "sec_combined_evidence_score",
        "sec_form4_score",
        "form4_net_buy_score",
        "institutional_13f_score",
        "institutional_evidence_score",
        "institutional_accumulation_score",
        "sec_13f_smart_money_score",
        "sec_13f_accumulation_score",
        "leader_onset_sec_v3_score",
        "evidence_fusion_score",
        "etf_theme_leadership_score",
        "etf_holdings_score",
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if "sec_evidence_research_only" in out.columns:
        out["sec_evidence_research_only"] = out["sec_evidence_research_only"].fillna(True)
    if "sec_evidence_production_activation_allowed" in out.columns:
        out["sec_evidence_production_activation_allowed"] = out["sec_evidence_production_activation_allowed"].fillna(False)
    if "sec_evidence_source" in out.columns:
        out["sec_evidence_source"] = out["sec_evidence_source"].fillna("form4_13f_etf_shadow")
    metadata.update(
        {
            "sec_evidence_feature_source": source,
            "sec_evidence_feature_columns_added": feature_cols,
            "sec_evidence_feature_rows_matched": matched,
        }
    )
    return out, metadata


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


def concentrated_champion_metadata(history_path: Path, latest: pd.DataFrame) -> dict[str, str]:
    metadata: dict[str, str] = {}
    comparison_path = history_path.parent / "concentrated_strategy_comparison.csv"
    comparison = read_csv(comparison_path)
    if not comparison.empty:
        d = comparison.copy()
        if "portfolio_mode" in d.columns:
            d = d[d["portfolio_mode"].astype(str).eq("concentrated_alpha")].copy()
        for col in ["target_stock_names", "strategy_cagr", "sharpe", "max_dd"]:
            if col not in d.columns:
                d[col] = pd.NA
            d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d[
            d["target_stock_names"].notna()
            & d["strategy_cagr"].notna()
            & d["sharpe"].notna()
            & d["max_dd"].notna()
        ].copy()
        if not d.empty:
            row = d.iloc[0].to_dict()
            metadata = {
                "target_stock_names": clean_filter_value(row.get("target_stock_names")),
                "weighting_mode": clean_filter_value(row.get("weighting_mode") or "score_power"),
                "active_rebalance_interval_months": clean_filter_value(
                    row.get("rebalance_interval_months")
                    or row.get("active_rebalance_interval_months")
                    or 1
                ),
            }
    if not metadata:
        metadata = {
            "target_stock_names": clean_filter_value(
                latest["target_stock_names"].dropna().iloc[0]
                if "target_stock_names" in latest.columns and latest["target_stock_names"].notna().any()
                else ""
            ),
            "weighting_mode": clean_filter_value(
                latest["weighting_mode"].dropna().iloc[0]
                if "weighting_mode" in latest.columns and latest["weighting_mode"].notna().any()
                else "score_power"
            ),
            "active_rebalance_interval_months": clean_filter_value(
                latest["active_rebalance_interval_months"].dropna().iloc[0]
                if "active_rebalance_interval_months" in latest.columns
                and latest["active_rebalance_interval_months"].notna().any()
                else 1
            ),
        }
    return {key: value for key, value in metadata.items() if value}


def fill_latest_concentrated_filter_metadata(
    latest_rows: pd.DataFrame,
    *,
    portfolio: str,
    history_path: Path,
    latest: pd.DataFrame,
) -> pd.DataFrame:
    if portfolio != "concentrated" or latest_rows.empty:
        return latest_rows
    out = latest_rows.copy()
    metadata = concentrated_champion_metadata(history_path, latest)
    for col, value in metadata.items():
        if col not in out.columns:
            out[col] = value
            continue
        out[col] = out[col].astype("object")
        blank = out[col].isna() | out[col].astype(str).str.strip().eq("")
        out.loc[blank, col] = value
    if "target_n" not in out.columns:
        out["target_n"] = ""
    out["target_n"] = out["target_n"].astype("object")
    if "target_stock_names" in out.columns:
        blank_target_n = out["target_n"].isna() | out["target_n"].astype(str).str.strip().eq("")
        out.loc[blank_target_n, "target_n"] = out.loc[blank_target_n, "target_stock_names"].map(clean_filter_value)
    if "portfolio_mode" not in out.columns:
        out["portfolio_mode"] = "concentrated_alpha"
    else:
        blank_mode = out["portfolio_mode"].isna() | out["portfolio_mode"].astype(str).str.strip().eq("")
        out.loc[blank_mode, "portfolio_mode"] = "concentrated_alpha"
    return out


def add_missing_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    missing = [col for col in columns if col not in out.columns]
    if missing:
        out = pd.concat([out, pd.DataFrame({col: "" for col in missing}, index=out.index)], axis=1)
    return out[columns].copy()


def build_book(
    *,
    portfolio: str,
    history_path: Path,
    latest_target_path: Path,
    price_cache: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    history = read_csv(history_path)
    latest = normalize_latest_target(read_csv(latest_target_path), portfolio)
    latest_target_date = latest_date_from_columns(latest, ["rebalance_date", "feature_date", "as_of_date", "last_trade_date"])
    latest, sec_metadata = attach_sec_evidence_features(
        latest_target_path.parent,
        latest,
        as_of_date=latest_target_date,
    )
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
            latest_rows = fill_latest_concentrated_filter_metadata(
                latest_rows,
                portfolio=portfolio,
                history_path=history_path,
                latest=latest,
            )
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
    parts = [add_missing_columns(part, all_cols) for part in (history, latest_rows) if not part.empty]
    combined = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=all_cols)
    if not combined.empty:
        combined["rebalance_date"] = pd.to_datetime(combined["rebalance_date"], errors="coerce").dt.date.astype(str)
        combined = combined.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)
    output_max = latest_date_from_columns(combined, ["rebalance_date"])
    operating_book_current = bool(
        not latest.empty
        and signal_date is not None
        and output_max is not None
        and pd.Timestamp(output_max).normalize() >= pd.Timestamp(signal_date).normalize()
    )
    freshness_error = ""
    if latest.empty:
        freshness_error = "latest target file is empty"
    elif signal_date is None:
        freshness_error = "could not infer an observable latest signal date from price cache or target dates"
    elif not operating_book_current:
        freshness_error = "operating target book does not reach the latest observable signal date"

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
        "output_max_rebalance_date": date_text(output_max),
        "latest_target_source_date": date_text(latest_target_date),
        "latest_price_close_date": date_text(price_close),
        "operating_signal_date": date_text(signal_date),
        "latest_target_appended": bool(appended),
        "operating_book_current": bool(operating_book_current),
        "freshness_error": freshness_error,
        "append_reason": append_reason,
        "decision_frequency": "event_driven_latest_close",
        **sec_metadata,
    }
    return combined, summary


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Operating Target Books",
        "",
        "Broker replay should use these operating target books when simulating the current account.",
        "Historical research books remain available, but they may be monthly and stale.",
        "",
        "| Portfolio | Rows | History max | Output max | Latest target source | Latest close | Operating signal | Appended | Current |",
        "| --- | ---: | --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in payload.get("books", []):
        lines.append(
            "| {portfolio} | {rows} | {history} | {output_max} | {source} | {close} | {signal} | {appended} | {current} |".format(
                portfolio=row.get("portfolio"),
                rows=row.get("output_row_count"),
                history=row.get("history_max_rebalance_date") or "",
                output_max=row.get("output_max_rebalance_date") or "",
                source=row.get("latest_target_source_date") or "",
                close=row.get("latest_price_close_date") or "",
                signal=row.get("operating_signal_date") or "",
                appended=str(row.get("latest_target_appended")).lower(),
                current=str(row.get("operating_book_current")).lower(),
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
    blocked_books = [
        row
        for row in summaries
        if bool(getattr(args, "require_current_latest_target", False))
        and not bool(row.get("operating_book_current"))
    ]
    payload = {
        "status": "blocked" if blocked_books else "completed",
        "blocked_reason": "operating target book did not reach the latest target close" if blocked_books else "",
        "blocked_books": blocked_books,
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
    parser.add_argument(
        "--require-current-latest-target",
        action="store_true",
        help="Exit nonzero unless each operating book reaches the latest observable target signal date.",
    )
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
