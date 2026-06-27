"""Audit reproducibility drift between official clean-7Y metrics and an A/B baseline.

This is a diagnostic tool. It does not run policy replay, broker replay, data
refresh, or any production mutation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "baseline-replay-repro-audit-v1"
DEFAULT_OUTPUT_DIR = "outputs/baseline_replay_repro_audit"
NEXT_CLOSE_MODE = "broker_ledger_next_close"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pp_delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return (candidate - baseline) * 100.0


def resolve_official_metrics(latest_run: Path, explicit: str | None = None) -> Path:
    if explicit:
        path = repo_path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"official metrics not found: {path}")
        return path
    path = latest_run / "account_evaluation" / "official_metrics.json"
    if not path.exists():
        raise FileNotFoundError(f"official metrics not found: {path}")
    return path


def resolve_ab_summary(ab_dir: Path, explicit: str | None = None) -> Path:
    if explicit:
        path = repo_path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"A/B summary not found: {path}")
        return path
    path = ab_dir / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"A/B summary not found: {path}")
    return path


def find_baseline_arm(summary: dict[str, Any]) -> dict[str, Any]:
    for arm in summary.get("arms", []):
        if str(arm.get("arm", "")).lower() == "baseline":
            return arm
    raise ValueError("A/B summary has no baseline arm")


def resolve_baseline_metrics(ab_dir: Path, baseline_arm: dict[str, Any]) -> Path:
    raw = baseline_arm.get("broker_metrics_path")
    if raw:
        path = repo_path(str(raw))
        if path.exists():
            return path
    path = ab_dir / "baseline" / "broker" / "metrics.json"
    if not path.exists():
        raise FileNotFoundError(f"baseline broker metrics not found: {path}")
    return path


def resolve_target_book(ab_dir: Path, baseline_arm: dict[str, Any]) -> Path | None:
    raw = baseline_arm.get("target_book_path")
    if raw:
        path = repo_path(str(raw))
        if path.exists():
            return path
    path = ab_dir / "baseline" / "target_book.csv"
    return path if path.exists() else None


def resolve_price_manifest(latest_run: Path, ab_dir: Path, explicit: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(repo_path(explicit))
    candidates.extend(
        [
            latest_run.parent / "cache_prices" / "replay_price_cache_manifest.json",
            ab_dir.parent / "cache_prices" / "replay_price_cache_manifest.json",
            REPO_ROOT / "cache_prices" / "replay_price_cache_manifest.json",
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def target_book_stats(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "exists": False,
            "path": str(path) if path else None,
            "sha256": None,
            "row_count": 0,
            "date_count": 0,
            "min_rebalance_date": None,
            "max_rebalance_date": None,
            "cash_row_count": 0,
            "ticker_count": 0,
        }
    row_count = 0
    dates: set[str] = set()
    tickers: set[str] = set()
    cash_rows = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row_count += 1
            date_text = str(row.get("rebalance_date", "")).strip()
            ticker = str(row.get("ticker", "")).strip().upper()
            if date_text:
                dates.add(date_text)
            if ticker:
                tickers.add(ticker)
            if ticker in {"CASH", "USD", "BIL", "SGOV", "SHV", "TBIL"}:
                cash_rows += 1
    return {
        "exists": True,
        "path": str(path),
        "sha256": sha256_file(path),
        "row_count": row_count,
        "date_count": len(dates),
        "min_rebalance_date": min(dates) if dates else None,
        "max_rebalance_date": max(dates) if dates else None,
        "cash_row_count": cash_rows,
        "ticker_count": len(tickers),
    }


def metrics_subset(metrics: dict[str, Any], portfolio: str | None = None) -> dict[str, Any]:
    source = metrics
    if portfolio and "portfolios" in metrics:
        source = metrics.get("portfolios", {}).get(portfolio, {})
    return {
        "metric_mode": source.get("metric_mode") or source.get("official_metric_mode") or metrics.get("official_metric_mode"),
        "cagr": safe_float(source.get("cagr")),
        "max_dd": safe_float(source.get("max_dd")),
        "sharpe": safe_float(source.get("sharpe")),
        "start_date": source.get("start_date"),
        "end_date": source.get("end_date"),
        "years": safe_float(source.get("years")),
        "avg_cash_weight": safe_float(source.get("avg_cash_weight")),
        "trade_count": source.get("trade_count") or source.get("broker_trade_count"),
        "gross_traded_usd": safe_float(source.get("gross_traded_usd")),
        "total_fees_usd": safe_float(source.get("total_fees_usd")),
        "official_source": source.get("official_source"),
        "evidence_window_label": source.get("evidence_window_label"),
        "pit_universe_label_clean": source.get("pit_universe_label_clean"),
        "production_promotion_allowed": source.get("production_promotion_allowed"),
    }


def build_report(summary: dict[str, Any]) -> str:
    official = summary["official_metrics"]
    baseline = summary["ab_baseline_metrics"]
    drift = summary["metric_deltas"]
    blockers = summary["blockers"]
    lines = [
        "# Baseline Replay Reproducibility Audit",
        "",
        f"- schema_version: `{summary['schema_version']}`",
        f"- generated_at: `{summary['generated_at']}`",
        f"- conclusion: `{summary['conclusion']}`",
        f"- drift_changes_score_sizing_decision: `{summary['drift_changes_score_sizing_decision']}`",
        "",
        "## Metrics",
        "",
        "| Metric | Official clean-7Y | A/B baseline | Delta |",
        "| --- | ---: | ---: | ---: |",
        f"| CAGR | {official.get('cagr')} | {baseline.get('cagr')} | {drift.get('cagr_pp')} pp |",
        f"| MaxDD | {official.get('max_dd')} | {baseline.get('max_dd')} | {drift.get('max_dd_pp')} pp |",
        f"| Sharpe | {official.get('sharpe')} | {baseline.get('sharpe')} | {drift.get('sharpe')} |",
        f"| Years | {official.get('years')} | {baseline.get('years')} | {drift.get('years')} |",
        f"| End date | {official.get('end_date')} | {baseline.get('end_date')} |  |",
        "",
        "## Blockers",
        "",
    ]
    for key, value in blockers.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Target Book",
            "",
            f"- path: `{summary['target_book'].get('path')}`",
            f"- sha256: `{summary['target_book'].get('sha256')}`",
            f"- rows: `{summary['target_book'].get('row_count')}`",
            f"- dates: `{summary['target_book'].get('date_count')}`",
            f"- date range: `{summary['target_book'].get('min_rebalance_date')}` to `{summary['target_book'].get('max_rebalance_date')}`",
            f"- cash rows: `{summary['target_book'].get('cash_row_count')}`",
            "",
            "## Price Cache",
            "",
            f"- manifest path: `{summary['price_cache_manifest'].get('path')}`",
            f"- start: `{summary['price_cache_manifest'].get('start')}`",
            f"- end: `{summary['price_cache_manifest'].get('end')}`",
            f"- status: `{summary['price_cache_manifest'].get('status')}`",
            "",
            "## Interpretation",
            "",
            "This audit explains baseline reproducibility drift only. It does not turn",
            "score-sizing into a policy candidate and it does not permit a fullrun.",
            "Cap-safe score sizing remains rejected unless a future broker-ledger A/B",
            "produces a `research_pass_policy_candidate` under the same governance.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    ab_dir = repo_path(args.ab_dir)
    out_dir = repo_path(args.output_dir)

    official_path = resolve_official_metrics(latest_run, args.official_metrics)
    ab_summary_path = resolve_ab_summary(ab_dir, args.ab_summary)
    official_payload = load_json(official_path)
    ab_summary = load_json(ab_summary_path)
    baseline_arm = find_baseline_arm(ab_summary)
    baseline_metrics_path = resolve_baseline_metrics(ab_dir, baseline_arm)
    baseline_payload = load_json(baseline_metrics_path)
    target_book_path = resolve_target_book(ab_dir, baseline_arm)
    manifest_path = resolve_price_manifest(latest_run, ab_dir, args.price_cache_manifest)

    official = metrics_subset(official_payload, args.portfolio)
    baseline = metrics_subset(baseline_payload)
    target_stats = target_book_stats(target_book_path)
    manifest_payload = load_json(manifest_path) if manifest_path else {}
    price_manifest = {
        "exists": bool(manifest_path),
        "path": str(manifest_path) if manifest_path else None,
        "sha256": sha256_file(manifest_path) if manifest_path else None,
        "start": manifest_payload.get("start"),
        "end": manifest_payload.get("end"),
        "requested_start": manifest_payload.get("requested_start"),
        "requested_end": manifest_payload.get("requested_end"),
        "status": manifest_payload.get("status"),
        "ticker_count": manifest_payload.get("ticker_count") or manifest_payload.get("actual_cached_ticker_count"),
    }

    official_mode = official.get("metric_mode")
    baseline_mode = baseline.get("metric_mode")
    official_years = official.get("years")
    baseline_years = baseline.get("years")
    years_delta = None
    if official_years is not None and baseline_years is not None:
        years_delta = baseline_years - official_years

    metric_deltas = {
        "cagr_pp": pp_delta(baseline.get("cagr"), official.get("cagr")),
        "max_dd_pp": pp_delta(baseline.get("max_dd"), official.get("max_dd")),
        "sharpe": None
        if baseline.get("sharpe") is None or official.get("sharpe") is None
        else baseline["sharpe"] - official["sharpe"],
        "years": years_delta,
        "avg_cash_weight_pp": pp_delta(baseline.get("avg_cash_weight"), official.get("avg_cash_weight")),
    }

    policy_candidates = ab_summary.get("policy_candidates", [])
    arms = ab_summary.get("arms", [])
    cap_safe_arms = [
        arm
        for arm in arms
        if str(arm.get("arm")) != "baseline" and int(safe_float(arm.get("cap_breach_count"), 0.0) or 0) == 0
    ]
    cap_safe_verdicts = {str(arm.get("arm")): arm.get("ab_verdict") for arm in cap_safe_arms}

    blockers = {
        "window_mismatch_gt_0_03y": bool(years_delta is not None and abs(years_delta) > 0.03),
        "metric_mode_not_next_close": bool(official_mode != NEXT_CLOSE_MODE or baseline_mode != NEXT_CLOSE_MODE),
        "target_book_source_unexplained": bool(not target_stats["exists"] or not target_stats["sha256"]),
    }
    warnings = {
        "end_date_mismatch": bool(official.get("end_date") != baseline.get("end_date")),
        "cagr_delta_gt_1pp": bool(
            metric_deltas["cagr_pp"] is not None and abs(metric_deltas["cagr_pp"]) > 1.0
        ),
        "price_manifest_missing": not price_manifest["exists"],
        "policy_candidates_present": bool(policy_candidates),
    }
    drift_changes_decision = bool(any(blockers.values()) or warnings["policy_candidates_present"])
    if blockers["window_mismatch_gt_0_03y"] or blockers["metric_mode_not_next_close"]:
        conclusion = "blocked_reproducibility_mismatch"
    elif blockers["target_book_source_unexplained"]:
        conclusion = "blocked_target_book_source_unexplained"
    elif warnings["end_date_mismatch"]:
        conclusion = "explained_drift_end_date_mismatch"
    else:
        conclusion = "reproducible_baseline"

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "latest_run": str(latest_run),
        "ab_dir": str(ab_dir),
        "portfolio": args.portfolio,
        "official_metrics_path": str(official_path),
        "ab_summary_path": str(ab_summary_path),
        "ab_baseline_metrics_path": str(baseline_metrics_path),
        "official_metrics": official,
        "ab_baseline_metrics": baseline,
        "metric_deltas": metric_deltas,
        "target_book": target_stats,
        "price_cache_manifest": price_manifest,
        "blockers": blockers,
        "warnings": warnings,
        "cap_safe_verdicts": cap_safe_verdicts,
        "policy_candidates": policy_candidates,
        "drift_changes_score_sizing_decision": drift_changes_decision,
        "production_promotion_allowed": False,
        "fullrun_allowed_from_score_sizing": False,
        "conclusion": conclusion,
    }
    write_json(out_dir / "summary.json", summary)
    write_text(out_dir / "report.md", build_report(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs", help="Path to the fullrun outputs directory.")
    parser.add_argument("--ab-dir", default="outputs/concentrated_score_sizing_broker_ab")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio", default="concentrated")
    parser.add_argument("--official-metrics", default="")
    parser.add_argument("--ab-summary", default="")
    parser.add_argument("--price-cache-manifest", default="")
    args = parser.parse_args()
    payload = run(args)
    print(json.dumps({"status": "completed", "conclusion": payload["conclusion"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
