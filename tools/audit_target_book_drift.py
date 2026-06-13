#!/usr/bin/env python3
"""Compare two AlphaOps run artifacts for target-book and candidate-score drift.

The official performance gate remains broker-ledger metrics. This audit is a
diagnostic tool for explaining why two broker-valid runs diverged: it compares
candidate score columns, operating target-book weights, and row-level
forward-return proxy deltas across a baseline run and a current run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


PORTFOLIOS = ("main", "concentrated")
TARGET_BOOKS = {
    "main": "operating_main_target_book.csv",
    "concentrated": "operating_concentrated_target_book.csv",
}
TARGET_KEEP_COLUMNS = [
    "rebalance_date",
    "ticker",
    "target_weight",
    "weight",
    "period_forward_return",
    "selection_confirmation_score",
    "rs_benchmark_1m",
    "atr14_pct",
    "ticker_ret_1m",
    "holding_state",
    "market_style_regime_label",
    "regime_state",
    "crisis_state",
    "selection_reason",
]
CANDIDATE_KEY_COLUMNS = ["rebalance_date", "ticker"]
CANDIDATE_SCORE_COLUMNS = [
    "score",
    "alphaops_vnext_score",
    "evidence_fusion_score",
    "sec_combined_evidence_score",
    "institutional_evidence_score",
    "selection_confirmation_score",
    "long_hold_compounder_score",
    "future_winner_scout_score",
    "portfolio_core_compounder_engine_score",
    "portfolio_future_winner_engine_score",
    "portfolio_early_scout_engine_score",
    "period_forward_return",
    "px",
    "atr14_pct",
    "dollar_vol_20d",
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def artifact_path(root: Path, *parts: str) -> Path:
    return root.joinpath(*parts)


def candidate_book_path(root: Path) -> Path:
    enriched = artifact_path(root, "sec_enriched_candidate_replay", "candidate_replay_book_sec_enriched.csv")
    if enriched.exists():
        return enriched
    return artifact_path(root, "reports", "candidate_replay_book.csv")


def target_book_path(root: Path, portfolio: str) -> Path:
    return artifact_path(root, "reports", TARGET_BOOKS[portfolio])


def load_metrics(root: Path, portfolio: str) -> dict[str, Any]:
    metrics = read_json(artifact_path(root, "broker_replay", portfolio, "metrics.json"))
    return {
        "cagr": metrics.get("cagr"),
        "max_dd": metrics.get("max_dd"),
        "sharpe": metrics.get("sharpe"),
        "avg_cash_weight": metrics.get("avg_cash_weight"),
        "ending_capital_usd": metrics.get("ending_capital_usd"),
        "trade_count": metrics.get("trade_count"),
        "total_fees_usd": metrics.get("total_fees_usd"),
        "max_dd_peak_date": metrics.get("max_dd_peak_date"),
        "max_dd_trough_date": metrics.get("max_dd_trough_date"),
        "metric_mode": metrics.get("metric_mode"),
        "valid_for_production": metrics.get("valid_for_production"),
    }


def metric_delta(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(set(current) | set(baseline)):
        cur = current.get(key)
        base = baseline.get(key)
        row: dict[str, Any] = {"baseline": base, "current": cur}
        if isinstance(cur, (int, float)) and isinstance(base, (int, float)):
            row["delta"] = cur - base
        out[key] = row
    return out


def normalize_target_book(path: Path, cutoff_date: str = "") -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["rebalance_date", "ticker", "target_weight"])
    columns = pd.read_csv(path, nrows=0).columns.tolist()
    usecols = [c for c in TARGET_KEEP_COLUMNS if c in columns]
    df = pd.read_csv(path, usecols=usecols, low_memory=False)
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["ticker"] = df["ticker"].astype(str)
    if "target_weight" not in df.columns and "weight" in df.columns:
        df["target_weight"] = df["weight"]
    for column in [
        "target_weight",
        "period_forward_return",
        "selection_confirmation_score",
        "rs_benchmark_1m",
        "atr14_pct",
        "ticker_ret_1m",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if cutoff_date:
        df = df[df["rebalance_date"] <= cutoff_date].copy()
    return df


def prefixed_frame(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    rename = {c: f"{prefix}_{c}" for c in frame.columns if c not in {"rebalance_date", "ticker"}}
    return frame.rename(columns=rename)


def compare_target_books(
    baseline_root: Path,
    current_root: Path,
    portfolio: str,
    output_dir: Path,
    cutoff_date: str = "",
    top_n: int = 25,
) -> dict[str, Any]:
    baseline = normalize_target_book(target_book_path(baseline_root, portfolio), cutoff_date=cutoff_date)
    current = normalize_target_book(target_book_path(current_root, portfolio), cutoff_date=cutoff_date)
    common_dates = sorted(set(baseline["rebalance_date"]) & set(current["rebalance_date"]))
    baseline = baseline[baseline["rebalance_date"].isin(common_dates)].copy()
    current = current[current["rebalance_date"].isin(common_dates)].copy()
    merged = prefixed_frame(baseline, "baseline").merge(
        prefixed_frame(current, "current"), on=["rebalance_date", "ticker"], how="outer"
    )
    for column in ["baseline_target_weight", "current_target_weight"]:
        merged[column] = pd.to_numeric(merged.get(column, 0.0), errors="coerce").fillna(0.0)
    merged["delta_weight"] = merged["current_target_weight"] - merged["baseline_target_weight"]
    merged["abs_delta_weight"] = merged["delta_weight"].abs()
    current_return = pd.to_numeric(merged.get("current_period_forward_return"), errors="coerce")
    baseline_return = pd.to_numeric(merged.get("baseline_period_forward_return"), errors="coerce")
    merged["period_forward_return"] = current_return.combine_first(baseline_return).fillna(0.0)
    merged["proxy_delta_return"] = merged["delta_weight"] * merged["period_forward_return"]
    merged["year"] = merged["rebalance_date"].str.slice(0, 4)

    changed = merged[merged["abs_delta_weight"] > 1e-8].copy()
    top_rows = changed.sort_values("proxy_delta_return").head(top_n)
    top_dates = (
        changed.groupby("rebalance_date", as_index=False)
        .agg(abs_delta_weight=("abs_delta_weight", "sum"), proxy_delta_return=("proxy_delta_return", "sum"))
        .sort_values("proxy_delta_return")
        .head(top_n)
    )
    top_tickers = (
        changed.groupby("ticker", as_index=False)
        .agg(
            abs_delta_weight=("abs_delta_weight", "sum"),
            proxy_delta_return=("proxy_delta_return", "sum"),
            changed_dates=("rebalance_date", "nunique"),
        )
        .sort_values("proxy_delta_return")
        .head(top_n)
    )
    by_year = (
        changed.groupby("year", as_index=False)
        .agg(abs_delta_weight=("abs_delta_weight", "sum"), proxy_delta_return=("proxy_delta_return", "sum"))
        .sort_values("year")
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    top_rows.to_csv(output_dir / f"{portfolio}_top_negative_rows.csv", index=False)
    top_dates.to_csv(output_dir / f"{portfolio}_top_negative_dates.csv", index=False)
    top_tickers.to_csv(output_dir / f"{portfolio}_top_negative_tickers.csv", index=False)
    by_year.to_csv(output_dir / f"{portfolio}_by_year.csv", index=False)

    return {
        "portfolio": portfolio,
        "baseline_target_book": str(target_book_path(baseline_root, portfolio)),
        "current_target_book": str(target_book_path(current_root, portfolio)),
        "common_date_count": int(len(common_dates)),
        "cutoff_date": cutoff_date,
        "baseline_row_count": int(len(baseline)),
        "current_row_count": int(len(current)),
        "changed_row_count": int(len(changed)),
        "total_abs_delta_weight": safe_float(changed["abs_delta_weight"].sum()),
        "proxy_delta_return_sum": safe_float(changed["proxy_delta_return"].sum()),
        "metrics": metric_delta(load_metrics(current_root, portfolio), load_metrics(baseline_root, portfolio)),
        "worst_dates": top_dates.to_dict(orient="records"),
        "worst_tickers": top_tickers.to_dict(orient="records"),
        "by_year": by_year.to_dict(orient="records"),
    }


def normalize_candidate_book(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=CANDIDATE_KEY_COLUMNS)
    columns = pd.read_csv(path, nrows=0).columns.tolist()
    usecols = [c for c in [*CANDIDATE_KEY_COLUMNS, *CANDIDATE_SCORE_COLUMNS] if c in columns]
    df = pd.read_csv(path, usecols=usecols, low_memory=False)
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["ticker"] = df["ticker"].astype(str)
    return df.sort_values(CANDIDATE_KEY_COLUMNS).reset_index(drop=True)


def compare_candidate_scores(baseline_root: Path, current_root: Path, top_n: int = 25) -> dict[str, Any]:
    baseline_path = candidate_book_path(baseline_root)
    current_path = candidate_book_path(current_root)
    baseline = normalize_candidate_book(baseline_path)
    current = normalize_candidate_book(current_path)
    keys_equal = bool(
        len(baseline) == len(current)
        and baseline[CANDIDATE_KEY_COLUMNS].reset_index(drop=True).equals(
            current[CANDIDATE_KEY_COLUMNS].reset_index(drop=True)
        )
    )
    drift_columns: list[dict[str, Any]] = []
    common_columns = [c for c in CANDIDATE_SCORE_COLUMNS if c in baseline.columns and c in current.columns]
    if keys_equal:
        for column in common_columns:
            base = pd.to_numeric(baseline[column], errors="coerce").astype(float)
            cur = pd.to_numeric(current[column], errors="coerce").astype(float)
            diff = (cur - base).abs()
            changed = int((diff.fillna(0.0) > 1e-10).sum())
            if changed:
                drift_columns.append(
                    {
                        "column": column,
                        "changed_count": changed,
                        "changed_ratio": changed / max(len(current), 1),
                        "max_abs_delta": safe_float(diff.max(skipna=True)),
                        "mean_abs_delta": safe_float(diff.mean(skipna=True)),
                    }
                )
    drift_columns.sort(key=lambda row: (row["changed_ratio"], row["max_abs_delta"]), reverse=True)
    return {
        "baseline_candidate_book": str(baseline_path),
        "current_candidate_book": str(current_path),
        "baseline_sha256": file_sha256(baseline_path),
        "current_sha256": file_sha256(current_path),
        "baseline_row_count": int(len(baseline)),
        "current_row_count": int(len(current)),
        "keys_equal": keys_equal,
        "top_changed_columns": drift_columns[:top_n],
    }


def format_pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return f"{value * 100:.4f}%"


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Target Book Drift Audit",
        "",
        f"- baseline: `{payload['baseline_run']}`",
        f"- current: `{payload['current_run']}`",
        f"- cutoff_date: `{payload.get('cutoff_date') or ''}`",
        "",
        "## Candidate Score Drift",
        "",
    ]
    candidate = payload["candidate_score_drift"]
    lines.extend(
        [
            f"- keys_equal: `{str(candidate['keys_equal']).lower()}`",
            f"- rows: baseline `{candidate['baseline_row_count']}`, current `{candidate['current_row_count']}`",
            f"- sha256_equal: `{str(candidate['baseline_sha256'] == candidate['current_sha256']).lower()}`",
            "",
            "| column | changed | ratio | max abs | mean abs |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in candidate["top_changed_columns"][:12]:
        lines.append(
            "| {column} | {changed_count} | {changed_ratio:.2%} | {max_abs_delta:.6f} | {mean_abs_delta:.6f} |".format(
                **row
            )
        )
    for portfolio, item in payload["portfolios"].items():
        metrics = item["metrics"]
        cagr = metrics.get("cagr", {})
        max_dd = metrics.get("max_dd", {})
        lines.extend(
            [
                "",
                f"## {portfolio.title()}",
                "",
                f"- changed rows: `{item['changed_row_count']}`",
                f"- total abs delta weight: `{item['total_abs_delta_weight']:.6f}`",
                f"- proxy delta return sum: `{item['proxy_delta_return_sum']:.6f}`",
                f"- CAGR: baseline `{format_pct(cagr.get('baseline'))}`, current `{format_pct(cagr.get('current'))}`, delta `{format_pct(cagr.get('delta'))}`",
                f"- MDD: baseline `{format_pct(max_dd.get('baseline'))}`, current `{format_pct(max_dd.get('current'))}`, delta `{format_pct(max_dd.get('delta'))}`",
                "",
                "| worst ticker | abs delta weight | proxy delta | changed dates |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for row in item["worst_tickers"][:10]:
            lines.append(
                "| {ticker} | {abs_delta_weight:.6f} | {proxy_delta_return:.6f} | {changed_dates} |".format(
                    **row
                )
            )
    lines.append("")
    return "\n".join(lines)


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    baseline_root = Path(args.baseline_run)
    current_root = Path(args.current_run)
    output_dir = Path(args.output_dir)
    payload = {
        "schema_version": "target-book-drift-audit-v1",
        "baseline_run": str(baseline_root),
        "current_run": str(current_root),
        "cutoff_date": args.cutoff_date,
        "candidate_score_drift": compare_candidate_scores(baseline_root, current_root, top_n=args.top_n),
        "portfolios": {},
    }
    for portfolio in PORTFOLIOS:
        payload["portfolios"][portfolio] = compare_target_books(
            baseline_root=baseline_root,
            current_root=current_root,
            portfolio=portfolio,
            output_dir=output_dir,
            cutoff_date=args.cutoff_date,
            top_n=args.top_n,
        )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-run", required=True, help="Baseline artifact directory")
    parser.add_argument("--current-run", required=True, help="Current artifact directory")
    parser.add_argument("--output-dir", default="outputs/target_book_drift_audit")
    parser.add_argument("--cutoff-date", default="", help="Optional inclusive rebalance-date cutoff")
    parser.add_argument("--top-n", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    output_dir = Path(args.output_dir)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"status": "ok", "output_dir": str(output_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
