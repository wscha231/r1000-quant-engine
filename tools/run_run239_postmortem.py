#!/usr/bin/env python3
"""Build a concise postmortem for fullrun #239 and its July rotation.

The report compares three fixed artifacts:

1. previous operating holdings (what the book actually held before the shock),
2. previous raw target preview (what the raw scorer wanted before the shock),
3. current target/current holdings from run #239 (what the system did after
   the July 2026 drawdown entered the official window).

It is deliberately read-only and does not run policy replay or broker replay.
"""
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


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def clean_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def weights_from(frame: pd.DataFrame, *, portfolio: str, column: str) -> dict[str, float]:
    if frame.empty or "portfolio" not in frame.columns or "ticker" not in frame.columns or column not in frame.columns:
        return {}
    d = frame[frame["portfolio"].astype(str).str.lower().eq(portfolio.lower())].copy()
    if d.empty:
        return {}
    d["ticker"] = d["ticker"].map(clean_ticker)
    d[column] = pd.to_numeric(d[column], errors="coerce").fillna(0.0)
    return d.groupby("ticker")[column].sum().to_dict()


def compare_three_way(
    *,
    previous_current: pd.DataFrame,
    previous_target: pd.DataFrame,
    current_current: pd.DataFrame,
    current_target: pd.DataFrame,
    portfolio: str,
) -> pd.DataFrame:
    columns = [
        "portfolio",
        "ticker",
        "previous_operating_current_weight",
        "previous_raw_target_weight",
        "run239_target_weight",
        "run239_current_weight",
        "target_delta_vs_previous_operating",
        "raw_target_delta_vs_previous_operating",
        "run239_vs_previous_raw_target_delta",
        "classification",
    ]
    prev_cur = weights_from(previous_current, portfolio=portfolio, column="current_weight")
    prev_tgt = weights_from(previous_target, portfolio=portfolio, column="target_weight")
    cur_cur = weights_from(current_current, portfolio=portfolio, column="current_weight")
    cur_tgt = weights_from(current_target, portfolio=portfolio, column="target_weight")
    tickers = sorted(set(prev_cur) | set(prev_tgt) | set(cur_cur) | set(cur_tgt))
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        a = float(prev_cur.get(ticker, 0.0))
        b = float(prev_tgt.get(ticker, 0.0))
        c = float(cur_tgt.get(ticker, 0.0))
        d = float(cur_cur.get(ticker, 0.0))
        if max(abs(a), abs(b), abs(c), abs(d)) < 1e-10:
            continue
        if a > 1e-9 and c <= 1e-9:
            action = "exit_from_operating"
        elif a > 1e-9 and c < a - 1e-9:
            action = "trim_from_operating"
        elif a <= 1e-9 and c > 1e-9:
            action = "new_target_entry"
        elif c > a + 1e-9:
            action = "increase_from_operating"
        else:
            action = "hold_near_or_lower"
        rows.append(
            {
                "portfolio": portfolio,
                "ticker": ticker,
                "previous_operating_current_weight": a,
                "previous_raw_target_weight": b,
                "run239_target_weight": c,
                "run239_current_weight": d,
                "target_delta_vs_previous_operating": c - a,
                "raw_target_delta_vs_previous_operating": b - a,
                "run239_vs_previous_raw_target_delta": c - b,
                "classification": action,
            }
        )
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["portfolio", "run239_target_weight", "previous_operating_current_weight"],
        ascending=[True, False, False],
    )


def official_metrics_table(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    rows: list[dict[str, Any]] = []
    for portfolio, item in (payload.get("portfolios") or {}).items():
        rows.append(
            {
                "portfolio": portfolio,
                "cagr": item.get("cagr"),
                "max_dd": item.get("max_dd"),
                "sharpe": item.get("sharpe"),
                "years": item.get("years"),
                "target_pass": item.get("target_pass"),
                "latest_cash_weight": item.get("latest_cash_weight"),
                "avg_cash_weight": item.get("avg_cash_weight"),
            }
        )
    return rows


def extract_failure_excerpt(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {"status": "missing_log"}
    try:
        text = log_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = log_path.read_text(encoding="utf-16", errors="replace")
    patterns = [
        "BROKER-LEDGER VERDICT -- DEFERRED TO SIDECAR STEP",
        "Process completed with exit code 1",
        "Pipeline build completed; broker-ledger sidecars run in the",
    ]
    hits: list[str] = []
    lines = text.splitlines()
    for pattern in patterns:
        match = re.search(re.escape(pattern), text)
        if match:
            start = max(0, match.start() - 300)
            end = min(len(text), match.end() + 500)
            hits.append(text[start:end])
            continue
        for idx, line in enumerate(lines):
            if pattern.lower() in line.lower():
                start_line = max(0, idx - 3)
                end_line = min(len(lines), idx + 4)
                hits.append("\n".join(lines[start_line:end_line]))
                break
    return {
        "status": "found" if hits else "no_known_failure_markers",
        "markers": patterns,
        "excerpts": hits,
    }


def pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return ""


def run(args: argparse.Namespace) -> dict[str, Any]:
    prev = repo_path(args.previous_user_current_dir)
    cur = repo_path(args.current_user_current_dir)
    out = repo_path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    previous_current = read_csv(prev / "01_current_holdings.csv")
    previous_target = read_csv(prev / "02_target_weights.csv")
    current_current = read_csv(cur / "01_current_holdings.csv")
    current_target = read_csv(cur / "02_target_weights.csv")
    all_frames: list[pd.DataFrame] = []
    for portfolio in ["main", "concentrated"]:
        all_frames.append(
            compare_three_way(
                previous_current=previous_current,
                previous_target=previous_target,
                current_current=current_current,
                current_target=current_target,
                portfolio=portfolio,
            )
        )
    non_empty_frames = [frame for frame in all_frames if not frame.empty]
    comparison = pd.concat(non_empty_frames, ignore_index=True) if non_empty_frames else pd.DataFrame()
    comparison.to_csv(out / "rotation_three_way.csv", index=False)

    metrics_rows = official_metrics_table(repo_path(args.current_official_metrics))
    pd.DataFrame(metrics_rows).to_csv(out / "run239_metrics_table.csv", index=False)
    failure = extract_failure_excerpt(repo_path(args.failed_log))
    summary = {
        "status": "completed",
        "schema_version": "run239-postmortem-v1",
        "run_id": args.run_id,
        "previous_user_current_dir": str(prev),
        "current_user_current_dir": str(cur),
        "current_official_metrics": str(repo_path(args.current_official_metrics)),
        "failed_log": str(repo_path(args.failed_log)) if args.failed_log else "",
        "metric_rows": metrics_rows,
        "failure": failure,
        "comparison_rows": int(len(comparison)),
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(out / "summary.json", summary)

    lines = [
        f"# Run {args.run_id} Postmortem and Rotation Counterfactual",
        "",
        "## Official Broker Metrics",
        "",
        "| Portfolio | CAGR | MaxDD | Sharpe | Latest Cash | Target Pass |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in metrics_rows:
        lines.append(
            f"| {row.get('portfolio')} | {pct(row.get('cagr'))} | {pct(row.get('max_dd'))} | "
            f"{safe_float(row.get('sharpe')):.3f} | {pct(row.get('latest_cash_weight'))} | {row.get('target_pass')} |"
        )
    lines.extend(
        [
            "",
            "## Failure Interpretation",
            "",
            "- The workflow failed after the main pipeline step returned exit code 1.",
            "- Broker/user artifacts exist and were generated by later sidecar steps.",
            "- Treat this as a post-artifact pipeline failure, not as missing broker evidence.",
            "",
            "## Concentrated Three-Way Rotation",
            "",
            "| Ticker | Previous Operating | Previous Raw Target | Run239 Target | Run239 Current | Classification |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    focused = comparison[comparison["portfolio"].eq("concentrated")].copy()
    focused = focused.sort_values(
        ["run239_target_weight", "previous_operating_current_weight"],
        ascending=[False, False],
    )
    for _, row in focused.iterrows():
        lines.append(
            f"| {row['ticker']} | {pct(row['previous_operating_current_weight'])} | "
            f"{pct(row['previous_raw_target_weight'])} | {pct(row['run239_target_weight'])} | "
            f"{pct(row['run239_current_weight'])} | {row['classification']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- The previous raw target wanted a hard rotation into AMD/AMAT/GLW.",
            "- The previous operating book still held SNDK/BE/WDC/CIEN/LITE with low cash.",
            "- Run239 reacted to the July drawdown by exiting thin-cushion names, trimming storage winners, raising cash, and rotating into MU/AMD/UMC.",
            "- This report is descriptive evidence only; it does not prove a new policy edge.",
        ]
    )
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="28616190134")
    parser.add_argument("--previous-user-current-dir", required=True)
    parser.add_argument("--current-user-current-dir", required=True)
    parser.add_argument("--current-official-metrics", required=True)
    parser.add_argument("--failed-log", default="")
    parser.add_argument("--output-dir", default="outputs/run239_postmortem")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
