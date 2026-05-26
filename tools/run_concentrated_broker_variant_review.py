#!/usr/bin/env python3
"""Broker-ledger review for concentrated historical grid variants.

This sidecar tests a small set of concentrated grid variants through the same
next-close broker ledger used for official metrics. It is intentionally
operator-review only: most historical grid books stop before the live operating
target extension, so passing rows are extension candidates, not production
evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import replay as broker_replay  # noqa: E402


DEFAULT_VARIANTS = "3:score_power:1,5:score_power:1,7:score_power:1,10:score_power:1,5:score_power:2,7:score_power:2"
BASELINE_VARIANT_ID = "N3_score_power_I1"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def parse_variants(value: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for chunk in value.split(","):
        text = chunk.strip()
        if not text:
            continue
        parts = [part.strip() for part in text.split(":")]
        if len(parts) != 3:
            raise ValueError(f"invalid variant {text!r}; expected N:weighting_mode:interval")
        n = int(parts[0])
        mode = parts[1]
        interval = int(parts[2])
        out.append(
            {
                "variant_id": f"N{n}_{mode}_I{interval}",
                "target_stock_names": n,
                "weighting_mode": mode,
                "active_rebalance_interval_months": interval,
            }
        )
    return out


def metric_delta(candidate: dict[str, Any], base: dict[str, Any], key: str) -> float | None:
    lhs = safe_float(candidate.get(key), None)
    rhs = safe_float(base.get(key), None)
    if lhs is None or rhs is None:
        return None
    return float(lhs - rhs)


def date_text(value: Any) -> str:
    return str(value or "")[:10]


def decision_for(row: dict[str, Any]) -> str:
    if row.get("status") != "completed":
        return "NO_REPLAY"
    if row.get("metric_mode") != "broker_ledger_next_close":
        return "DO_NOT_USE"
    cagr_delta = safe_float(row.get("cagr_delta_vs_baseline"), None)
    mdd = safe_float(row.get("max_dd"), None)
    mdd_improvement = safe_float(row.get("mdd_improvement_vs_baseline"), None)
    if cagr_delta is None or mdd is None or mdd_improvement is None:
        return "REVIEW_REQUIRED"
    if mdd < -0.35:
        return "REJECT_MDD"
    if cagr_delta < -0.03:
        return "REJECT_CAGR_DRAG"
    if mdd > -0.32 and cagr_delta >= -0.03:
        return "EXTENSION_CANDIDATE_RESEARCH_ONLY" if not row.get("coverage_reaches_official_end") else "BROKER_LEDGER_CANDIDATE"
    if mdd_improvement > 0 and cagr_delta >= -0.03:
        return "REVIEW_REQUIRED_COVERAGE"
    return "REVIEW_REQUIRED"


def run_variant(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    variant: dict[str, Any],
    cost_bps: float,
    max_fill_lag_days: int,
) -> dict[str, Any]:
    variant_id = str(variant["variant_id"])
    variant_dir = output_dir / "concentrated_broker_variant_replay" / variant_id
    try:
        metrics = broker_replay(
            target_book=target_book,
            price_cache=price_cache,
            output_dir=variant_dir,
            portfolio_kind="concentrated",
            fill_mode="next_close",
            cost_bps=cost_bps,
            integer_shares=True,
            max_fill_lag_days=max_fill_lag_days,
            concentrated_champion_filters={
                "target_stock_names": variant["target_stock_names"],
                "weighting_mode": variant["weighting_mode"],
                "active_rebalance_interval_months": variant["active_rebalance_interval_months"],
            },
        )
    except Exception as exc:
        metrics = {
            "status": "error",
            "metric_mode": "broker_ledger_next_close",
            "error": str(exc),
        }
        variant_dir.mkdir(parents=True, exist_ok=True)
        write_json(variant_dir / "metrics.json", metrics)
    return metrics


def build_review(
    latest_run: Path,
    price_cache: Path,
    output_dir: Path,
    variants: list[dict[str, Any]],
    cost_bps: float,
    max_fill_lag_days: int,
) -> dict[str, Any]:
    target_book = latest_run / "reports" / "concentrated_strategy_holdings.csv"
    official = load_json(latest_run / "account_evaluation" / "official_metrics.json")
    official_conc = {}
    if isinstance(official.get("portfolios"), dict):
        official_conc = official["portfolios"].get("concentrated") or {}
    official_end = date_text(official_conc.get("end_date"))

    rows: list[dict[str, Any]] = []
    raw_metrics: dict[str, dict[str, Any]] = {}
    for variant in variants:
        metrics = run_variant(
            target_book=target_book,
            price_cache=price_cache,
            output_dir=output_dir,
            variant=variant,
            cost_bps=cost_bps,
            max_fill_lag_days=max_fill_lag_days,
        )
        raw_metrics[str(variant["variant_id"])] = metrics

    baseline = raw_metrics.get(BASELINE_VARIANT_ID) or next(iter(raw_metrics.values()), {})
    baseline_id = BASELINE_VARIANT_ID if BASELINE_VARIANT_ID in raw_metrics else (variants[0]["variant_id"] if variants else "")
    for variant in variants:
        variant_id = str(variant["variant_id"])
        metrics = raw_metrics.get(variant_id, {})
        end_date = date_text(metrics.get("end_date"))
        coverage_reaches_official_end = bool(official_end and end_date and end_date >= official_end)
        row = {
            "variant_id": variant_id,
            "target_stock_names": variant["target_stock_names"],
            "weighting_mode": variant["weighting_mode"],
            "active_rebalance_interval_months": variant["active_rebalance_interval_months"],
            "status": metrics.get("status", "missing"),
            "metric_mode": metrics.get("metric_mode", ""),
            "valid_for_production_raw": bool(metrics.get("valid_for_production")),
            "review_valid_for_promotion": bool(metrics.get("valid_for_production")) and coverage_reaches_official_end,
            "coverage_reaches_official_end": coverage_reaches_official_end,
            "start_date": metrics.get("start_date"),
            "end_date": metrics.get("end_date"),
            "official_end_date": official_end,
            "cagr": safe_float(metrics.get("cagr"), None),
            "max_dd": safe_float(metrics.get("max_dd"), None),
            "sharpe": safe_float(metrics.get("sharpe"), None),
            "trade_count": safe_float(metrics.get("trade_count"), None),
            "total_fees_usd": safe_float(metrics.get("total_fees_usd"), None),
            "avg_cash_weight": safe_float(metrics.get("avg_cash_weight"), None),
            "cagr_delta_vs_baseline": metric_delta(metrics, baseline, "cagr"),
            "mdd_improvement_vs_baseline": metric_delta(metrics, baseline, "max_dd"),
            "baseline_variant_id": baseline_id,
            "metrics_path": f"operator_review/concentrated_broker_variant_replay/{variant_id}/metrics.json",
        }
        row["decision"] = decision_for(row)
        rows.append(row)

    rows.sort(
        key=lambda row: (
            0 if str(row.get("decision", "")).startswith("EXTENSION_CANDIDATE") else 1,
            -(safe_float(row.get("max_dd"), -1.0) or -1.0),
            -(safe_float(row.get("cagr"), -1.0) or -1.0),
        )
    )
    return {
        "schema_version": "concentrated-broker-variant-review-v1",
        "production_activation_allowed": False,
        "research_only": True,
        "official_metric_required": "broker_ledger_next_close",
        "review_scope": "historical_concentrated_grid_variants",
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "baseline_variant_id": baseline_id,
        "official_concentrated": {
            "cagr": official_conc.get("cagr"),
            "max_dd": official_conc.get("max_dd"),
            "sharpe": official_conc.get("sharpe"),
            "end_date": official_end,
            "metric_mode": official_conc.get("official_metric_mode") or official.get("official_metric_mode"),
        },
        "rows": rows,
    }


def pct(value: Any) -> str:
    number = safe_float(value, None)
    return "" if number is None else f"{number:.2%}"


def number(value: Any) -> str:
    number_value = safe_float(value, None)
    return "" if number_value is None else f"{number_value:,.0f}"


def render_markdown(payload: dict[str, Any]) -> str:
    official = payload.get("official_concentrated") or {}
    lines = [
        "# Concentrated Broker Variant Review",
        "",
        "Research-only broker-ledger review of concentrated historical grid variants.",
        "",
        f"- Production activation allowed: `{str(payload.get('production_activation_allowed')).lower()}`",
        f"- Baseline variant: `{payload.get('baseline_variant_id')}`",
        f"- Official concentrated CAGR/MDD: {pct(official.get('cagr'))} / {pct(official.get('max_dd'))}",
        f"- Official end date: `{official.get('end_date')}`",
        "",
        "| Variant | Decision | CAGR | MDD | Sharpe | CAGR vs Base | MDD vs Base | Trades | Avg Cash | End | Promotion Valid |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for row in payload.get("rows", []):
        lines.append(
            "| {variant} | `{decision}` | {cagr} | {mdd} | {sharpe} | {cagr_delta} | {mdd_delta} | {trades} | {cash} | {end} | {valid} |".format(
                variant=row.get("variant_id", ""),
                decision=row.get("decision", ""),
                cagr=pct(row.get("cagr")),
                mdd=pct(row.get("max_dd")),
                sharpe="" if row.get("sharpe") is None else f"{safe_float(row.get('sharpe')):.3f}",
                cagr_delta=pct(row.get("cagr_delta_vs_baseline")),
                mdd_delta=pct(row.get("mdd_improvement_vs_baseline")),
                trades=number(row.get("trade_count")),
                cash=pct(row.get("avg_cash_weight")),
                end=row.get("end_date", ""),
                valid=str(bool(row.get("review_valid_for_promotion"))).lower(),
            )
        )
    lines.extend(
        [
            "",
            "Rules:",
            "- This is not a trade instruction.",
            "- Variants that do not reach the official broker end date are extension candidates only.",
            "- Promotion still requires current target-book generation, official broker-ledger replay, cost sensitivity, and human approval.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "concentrated_broker_variant_review.json", payload)
    (output_dir / "concentrated_broker_variant_review.md").write_text(render_markdown(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/operator_review")
    parser.add_argument("--variants", default=DEFAULT_VARIANTS)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    variants = parse_variants(args.variants)
    payload = build_review(
        repo_path(args.latest_run),
        repo_path(args.price_cache),
        repo_path(args.output_dir),
        variants,
        cost_bps=args.cost_bps,
        max_fill_lag_days=args.max_fill_lag_days,
    )
    write_outputs(payload, repo_path(args.output_dir))
    print(json.dumps({"schema_version": payload["schema_version"], "rows": len(payload["rows"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
