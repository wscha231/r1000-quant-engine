#!/usr/bin/env python3
"""Compare a full rebuild artifact against a fast replay artifact.

Fast replay is useful only when it reproduces the same production semantics as
full rebuild. This audit makes drift explicit across broker metrics, target
books, cash contract, candidate freshness, fees, and price-cache metadata.
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

from tools.validate_target_book_cash_contract import target_cash_by_date

DEFAULT_OUTPUT_DIR = "outputs/fast_full_drift_audit"
PORTFOLIOS = ("main", "concentrated")
TARGETS = {
    "main": {"cagr": 0.30, "max_dd": -0.25},
    "concentrated": {"cagr": 0.45, "max_dd": -0.25},
}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def resolve_run_root(path: Path) -> Path:
    """Accept either artifact root or artifact_root/outputs."""

    if (path / "broker_replay").exists() or (path / "reports").exists():
        return path
    if (path / "outputs" / "broker_replay").exists() or (path / "outputs" / "reports").exists():
        return path / "outputs"
    return path


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


def broker_metrics(root: Path, portfolio: str) -> dict[str, Any]:
    metrics = read_json(root / "broker_replay" / portfolio / "metrics.json")
    gate = TARGETS[portfolio]
    cagr = safe_float(metrics.get("cagr"))
    max_dd = safe_float(metrics.get("max_dd"))
    metrics["target_pass"] = bool(cagr is not None and max_dd is not None and cagr >= gate["cagr"] and max_dd >= gate["max_dd"])
    return metrics


def target_book_path(root: Path, portfolio: str) -> Path:
    return root / "reports" / ("operating_main_target_book.csv" if portfolio == "main" else "operating_concentrated_target_book.csv")


def target_book_summary(root: Path, portfolio: str) -> tuple[dict[str, Any], pd.DataFrame]:
    path = target_book_path(root, portfolio)
    summary, by_date = target_cash_by_date(path)
    raw = read_csv(path)
    if raw.empty:
        summary.update({"row_count": 0, "ticker_count": 0})
        return summary, by_date
    ticker_col = raw["ticker"].astype(str).str.upper().str.strip() if "ticker" in raw.columns else pd.Series(dtype=str)
    summary.update(
        {
            "row_count": int(len(raw)),
            "ticker_count": int(ticker_col[ticker_col.ne("CASH")].nunique()) if not ticker_col.empty else 0,
            "max_rebalance_date": str(pd.to_datetime(raw.get("rebalance_date"), errors="coerce").max().date())
            if "rebalance_date" in raw.columns and pd.to_datetime(raw.get("rebalance_date"), errors="coerce").notna().any()
            else "",
        }
    )
    return summary, by_date


def target_jaccard(full_root: Path, fast_root: Path, portfolio: str) -> dict[str, Any]:
    full = read_csv(target_book_path(full_root, portfolio))
    fast = read_csv(target_book_path(fast_root, portfolio))
    if full.empty or fast.empty:
        return {"status": "missing_target_book"}
    rows: list[dict[str, Any]] = []
    for frame in (full, fast):
        frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.normalize()
        frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    common_dates = sorted(set(full["rebalance_date"].dropna()) & set(fast["rebalance_date"].dropna()))
    for dt in common_dates:
        a = set(full.loc[full["rebalance_date"].eq(dt), "ticker"]) - {"CASH", "__CASH__"}
        b = set(fast.loc[fast["rebalance_date"].eq(dt), "ticker"]) - {"CASH", "__CASH__"}
        rows.append(
            {
                "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                "jaccard": len(a & b) / max(1, len(a | b)),
                "full_count": len(a),
                "fast_count": len(b),
            }
        )
    if not rows:
        return {"status": "no_overlapping_rebalance_dates"}
    j = pd.Series([row["jaccard"] for row in rows], dtype=float)
    return {
        "status": "completed",
        "overlap_date_count": len(rows),
        "avg_target_jaccard": float(j.mean()),
        "min_target_jaccard": float(j.min()),
        "latest_target_jaccard": float(rows[-1]["jaccard"]),
        "latest_date": rows[-1]["rebalance_date"],
    }


def artifact_summary(root: Path) -> dict[str, Any]:
    return {
        "root": str(root),
        "account_evaluation": read_json(root / "account_evaluation" / "official_metrics.json"),
        "portfolio_system_guard": read_json(root / "portfolio_system_guard" / "error_check.json"),
        "replay_price_cache_manifest": read_json(root / "manifests" / "replay_price_cache_manifest.json")
        or read_json(root.parent / "cache_prices" / "replay_price_cache_manifest.json")
        or read_json(root / "cache_prices" / "replay_price_cache_manifest.json"),
        "candidate_rows": int(len(read_csv(root / "reports" / "candidate_replay_book.csv"))),
        "scored_rows": int(len(read_csv(root / "scored_latest.csv"))),
    }


def portfolio_drift(full_root: Path, fast_root: Path, portfolio: str) -> dict[str, Any]:
    full_metrics = broker_metrics(full_root, portfolio)
    fast_metrics = broker_metrics(fast_root, portfolio)
    full_target, _ = target_book_summary(full_root, portfolio)
    fast_target, _ = target_book_summary(fast_root, portfolio)
    fields = ["cagr", "max_dd", "sharpe", "avg_cash_weight", "total_fees_usd", "trade_count"]
    metric_drift = {}
    for field in fields:
        full_value = safe_float(full_metrics.get(field))
        fast_value = safe_float(fast_metrics.get(field))
        metric_drift[field] = {
            "full": full_value,
            "fast": fast_value,
            "delta_fast_minus_full": None if full_value is None or fast_value is None else fast_value - full_value,
        }
    full_pass = bool(full_metrics.get("target_pass"))
    fast_pass = bool(fast_metrics.get("target_pass"))
    return {
        "portfolio": portfolio,
        "full_target_pass": full_pass,
        "fast_target_pass": fast_pass,
        "drift_status": "pass_both" if full_pass and fast_pass else ("fast_only_pass" if fast_pass and not full_pass else "not_fast_pass"),
        "metric_drift": metric_drift,
        "target_book": {
            "full": full_target,
            "fast": fast_target,
            "jaccard": target_jaccard(full_root, fast_root, portfolio),
        },
    }


def run(full_run: Path, fast_run: Path, output_dir: Path) -> dict[str, Any]:
    full_root = resolve_run_root(full_run)
    fast_root = resolve_run_root(fast_run)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "metric_mode": "fast_full_drift_audit",
        "full_run": artifact_summary(full_root),
        "fast_run": artifact_summary(fast_root),
        "portfolios": {},
    }
    for portfolio in PORTFOLIOS:
        payload["portfolios"][portfolio] = portfolio_drift(full_root, fast_root, portfolio)
    payload["fast_full_gate"] = (
        "ship_candidate"
        if all(item["drift_status"] == "pass_both" for item in payload["portfolios"].values())
        else (
            "partial_fast_only"
            if any(item["drift_status"] == "fast_only_pass" for item in payload["portfolios"].values())
            else "reject"
        )
    )
    rows = []
    for portfolio, item in payload["portfolios"].items():
        row = {"portfolio": portfolio, "drift_status": item["drift_status"]}
        for field, values in item["metric_drift"].items():
            row[f"full_{field}"] = values["full"]
            row[f"fast_{field}"] = values["fast"]
            row[f"delta_{field}"] = values["delta_fast_minus_full"]
        row["avg_target_jaccard"] = item["target_book"]["jaccard"].get("avg_target_jaccard")
        row["full_avg_target_cash_weight"] = item["target_book"]["full"].get("avg_target_cash_weight")
        row["fast_avg_target_cash_weight"] = item["target_book"]["fast"].get("avg_target_cash_weight")
        rows.append(row)
    pd.DataFrame(rows).to_csv(output_dir / "fast_full_drift_summary.csv", index=False)
    write_json(output_dir / "fast_full_drift_summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-run", required=True)
    parser.add_argument("--fast-run", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(repo_path(args.full_run), repo_path(args.fast_run), repo_path(args.output_dir))
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("fast_full_gate") == "ship_candidate" else 2


if __name__ == "__main__":
    raise SystemExit(main())
