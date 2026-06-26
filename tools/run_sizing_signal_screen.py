#!/usr/bin/env python3
"""Cheap sizing-signal screen for AlphaOps target books.

This diagnostic asks whether PIT selection/weighting scores in the official
target book were positively associated with subsequent audit-label returns. It
does not mutate sizing, run broker replay, or use forward returns as signals.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "sizing-signal-screen-v1"
CASH_TICKERS = {"CASH", "__CASH__"}
EVAL_SPLIT_DATE = pd.Timestamp("2024-06-03")
SIGNAL_COLUMNS = [
    "alphaops_vnext_score",
    "alphaops_vnext_weight_score",
    "weighting_score",
    "weight",
    "target_weight",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def target_book_path(latest_run: Path, portfolio: str, explicit: str | None = None) -> Path:
    if explicit:
        return repo_path(explicit)
    candidates = [
        latest_run / "reports" / f"operating_{portfolio}_target_book.csv",
        latest_run / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
        latest_run / "market_leader_challenger" / f"{portfolio}_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def load_target_book(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path, low_memory=False)
    if d.empty or "rebalance_date" not in d.columns or "ticker" not in d.columns:
        return pd.DataFrame()
    d = d.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d = d[d["rebalance_date"].notna()]
    d = d[~d["ticker"].isin(CASH_TICKERS)]
    return d


def prep_frame(book: pd.DataFrame) -> pd.DataFrame:
    if book.empty:
        return pd.DataFrame()
    d = book.copy()
    if "period_forward_return" not in d.columns:
        return pd.DataFrame()
    d["forward_return"] = pd.to_numeric(d["period_forward_return"], errors="coerce")
    d = d[d["forward_return"].notna()]
    d["split"] = d["rebalance_date"].apply(lambda dt: "oos" if pd.Timestamp(dt) >= EVAL_SPLIT_DATE else "is")
    for col in SIGNAL_COLUMNS:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    return d


def quantile_stats(d: pd.DataFrame, signal: str) -> dict[str, Any]:
    cols = [signal, "forward_return"]
    x = d[cols].dropna().copy()
    if len(x) < 20 or x[signal].nunique() < 3:
        return {
            "row_count": int(len(x)),
            "status": "insufficient_rows",
        }
    try:
        x["quantile"] = pd.qcut(x[signal], q=min(5, x[signal].nunique()), labels=False, duplicates="drop")
    except ValueError:
        return {
            "row_count": int(len(x)),
            "status": "insufficient_unique_values",
        }
    if x["quantile"].nunique() < 2:
        return {
            "row_count": int(len(x)),
            "status": "insufficient_quantiles",
        }
    grouped = x.groupby("quantile")["forward_return"].agg(["count", "mean"]).reset_index()
    low = grouped.sort_values("quantile").iloc[0]
    high = grouped.sort_values("quantile").iloc[-1]
    # Avoid scipy dependency in PR validation: Spearman = Pearson corr of ranks.
    spearman = float(x[signal].rank(method="average").corr(x["forward_return"].rank(method="average")))
    return {
        "row_count": int(len(x)),
        "status": "ok",
        "spearman": spearman,
        "low_quantile_mean": float(low["mean"]),
        "high_quantile_mean": float(high["mean"]),
        "high_minus_low": float(high["mean"] - low["mean"]),
        "low_quantile_count": int(low["count"]),
        "high_quantile_count": int(high["count"]),
    }


def signal_summary(d: pd.DataFrame, signal: str) -> dict[str, Any]:
    out = {"signal": signal}
    full = quantile_stats(d, signal)
    is_stats = quantile_stats(d[d["split"].eq("is")], signal)
    oos_stats = quantile_stats(d[d["split"].eq("oos")], signal)
    out["full"] = full
    out["is"] = is_stats
    out["oos"] = oos_stats
    oos_ok = (
        oos_stats.get("status") == "ok"
        and safe_float(oos_stats.get("spearman")) > 0.03
        and safe_float(oos_stats.get("high_minus_low")) > 0.0
        and safe_float(oos_stats.get("high_quantile_count")) >= 20
    )
    is_supportive = is_stats.get("status") == "ok" and safe_float(is_stats.get("high_minus_low")) > 0.0
    full_ok = (
        full.get("status") == "ok"
        and safe_float(full.get("spearman")) > 0.0
        and safe_float(full.get("high_minus_low")) > 0.0
    )
    out["is_supportive"] = bool(is_supportive)
    out["candidate_positive"] = bool(full_ok and is_supportive and oos_ok)
    return out


def screen_portfolio(book: pd.DataFrame, portfolio: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    d = prep_frame(book)
    if d.empty:
        return [], {
            "portfolio": portfolio,
            "status": "blocked",
            "reason": "missing_target_book_or_forward_return",
        }
    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for signal in SIGNAL_COLUMNS:
        if signal not in d.columns:
            continue
        summary = signal_summary(d, signal)
        summaries.append(summary)
        for split in ["full", "is", "oos"]:
            stats = summary.get(split, {})
            rows.append(
                {
                    "portfolio": portfolio,
                    "signal": signal,
                    "split": split,
                    "status": stats.get("status"),
                    "row_count": stats.get("row_count"),
                    "spearman": stats.get("spearman"),
                    "low_quantile_mean": stats.get("low_quantile_mean"),
                    "high_quantile_mean": stats.get("high_quantile_mean"),
                    "high_minus_low": stats.get("high_minus_low"),
                    "candidate_positive": summary.get("candidate_positive"),
                }
            )
    positives = [item["signal"] for item in summaries if item.get("candidate_positive")]
    return rows, {
        "portfolio": portfolio,
        "status": "screen_passed" if positives else "no_positive_sizing_signal",
        "row_count": int(len(d)),
        "is_rows": int(d["split"].eq("is").sum()),
        "oos_rows": int(d["split"].eq("oos").sum()),
        "positive_signals": positives,
        "signal_summaries": summaries,
    }


def build_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Sizing Signal Screen",
        "",
        "Research-only sizing diagnostic. Forward returns are audit labels only.",
        "",
        f"- generated_at_utc: {payload['generated_at_utc']}",
        f"- split_date: {payload['split_date']}",
        f"- next_action: {payload['next_action']}",
        "",
        "| portfolio | status | rows | OOS rows | positive signals |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in payload.get("portfolios", []):
        lines.append(
            "| {portfolio} | {status} | {rows} | {oos} | {signals} |".format(
                portfolio=item.get("portfolio"),
                status=item.get("status"),
                rows=item.get("row_count", 0),
                oos=item.get("oos_rows", 0),
                signals=", ".join(item.get("positive_signals") or []),
            )
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "- Positive signal requires full-period and OOS positive rank relationship.",
            "- If no positive signal exists, do not run concentrated sizing A/B from this score family.",
            "- Broker acceptance still requires broker_ledger_next_close.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/sizing_signal_screen")
    parser.add_argument("--main-target-book", default=None)
    parser.add_argument("--concentrated-target-book", default=None)
    args = parser.parse_args()

    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    specs = [
        ("main", target_book_path(latest_run, "main", args.main_target_book)),
        ("concentrated", target_book_path(latest_run, "concentrated", args.concentrated_target_book)),
    ]
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for portfolio, book_path in specs:
        rows, summary = screen_portfolio(load_target_book(book_path), portfolio)
        summary["target_book_source"] = str(book_path)
        summaries.append(summary)
        all_rows.extend(rows)
    any_conc_positive = any(
        item.get("portfolio") == "concentrated" and item.get("positive_signals") for item in summaries
    )
    next_action = "design_concentrated_sizing_ab" if any_conc_positive else "discard_score_family_sizing_ab"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "research_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "broker_replay_executed": False,
        "split_date": EVAL_SPLIT_DATE.date().isoformat(),
        "next_action": next_action,
        "portfolios": summaries,
    }
    write_json(output_dir / "summary.json", payload)
    write_csv(output_dir / "signal_quantile_stats.csv", pd.DataFrame(all_rows))
    (output_dir / "report.md").write_text(build_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
