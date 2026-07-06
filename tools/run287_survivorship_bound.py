#!/usr/bin/env python3
"""Estimate a one-sided run287 survivorship-inflation lower bound.

This R2 tool is measurement-only. It does not invent delisted membership, does
not dispatch a workflow, does not tune thresholds, and does not relabel
production readiness. The bound is intentionally partial: it can only measure
late-inclusion rows that violate first-price-date availability in the committed
candidate/target books. Delisted-name exclusion remains unmeasured.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


PORTFOLIOS = ("main", "concentrated")
DEFAULT_RUN_ROOT = "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe"
DEFAULT_CANDIDATE_BOOK = DEFAULT_RUN_ROOT + "/reports/candidate_replay_book.csv"
DEFAULT_BOOK_ROOT = DEFAULT_RUN_ROOT + "/alphaops_vnext"
DEFAULT_OFFICIAL_METRICS = DEFAULT_RUN_ROOT + "/account_evaluation/official_metrics.json"
DEFAULT_SIDECAR_ARM_METRICS = "outputs/run287_forensics/metric_sidecar_arm_metrics.csv"
DEFAULT_OUTPUT_DIR = "outputs/run287_survivorship"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def path_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def candidate_first_dates(candidate_book: Path) -> pd.DataFrame:
    usecols = ["rebalance_date", "ticker", "px", "source_universe"]
    d = pd.read_csv(candidate_book, usecols=lambda c: c in set(usecols))
    if d.empty:
        return pd.DataFrame(columns=["ticker", "first_price_date", "source_universe_sample"])
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    if "px" in d.columns:
        d = d[pd.to_numeric(d["px"], errors="coerce").fillna(0.0) > 0].copy()
    d = d.dropna(subset=["rebalance_date"])
    grouped = d.groupby("ticker", as_index=False).agg(
        first_price_date=("rebalance_date", "min"),
        source_universe_sample=("source_universe", "last") if "source_universe" in d.columns else ("ticker", "last"),
    )
    return grouped


def load_target_book(path: Path) -> pd.DataFrame:
    usecols = {
        "rebalance_date",
        "ticker",
        "target_weight",
        "weight",
        "source_universe",
        "period_forward_return",
    }
    d = pd.read_csv(path, usecols=lambda c: c in usecols)
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    weight_col = "target_weight" if "target_weight" in d.columns else "weight"
    d["target_weight"] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0)
    if "period_forward_return" in d.columns:
        d["period_forward_return"] = pd.to_numeric(d["period_forward_return"], errors="coerce").fillna(0.0)
    else:
        d["period_forward_return"] = 0.0
    if "source_universe" not in d.columns:
        d["source_universe"] = ""
    d = d.dropna(subset=["rebalance_date"])
    return d[d["ticker"].ne("")].copy()


def sidecar_metrics(path: Path, portfolio: str) -> dict[str, float | str]:
    if not path.exists():
        return {}
    try:
        d = pd.read_csv(path)
    except Exception:
        return {}
    if d.empty or "arm" not in d.columns or "portfolio" not in d.columns:
        return {}
    arm = d[
        d["arm"].astype(str).eq("generated_book_cash_carry")
        & d["portfolio"].astype(str).str.lower().eq(portfolio)
    ]
    if arm.empty:
        return {}
    row = arm.iloc[0]
    return {
        "current_proxy_cagr": safe_float(row.get("cagr")),
        "current_proxy_max_dd": safe_float(row.get("max_dd")),
        "metric_mode": str(row.get("metric_mode") or "broker_ledger_next_close_cash_carry"),
        "metric_source": "generated_book_cash_carry_sidecar",
    }


def portfolio_metrics(official: dict[str, Any], portfolio: str, sidecar_arm_metrics: Path) -> dict[str, Any]:
    sidecar = sidecar_metrics(sidecar_arm_metrics, portfolio)
    if sidecar:
        return sidecar
    item = (official.get("portfolios") or {}).get(portfolio) or {}
    return {
        "current_proxy_cagr": safe_float(item.get("cagr")),
        "current_proxy_max_dd": safe_float(item.get("max_dd")),
        "metric_mode": "broker_ledger_next_close",
        "metric_source": "official_zero_yield_metrics_fallback",
    }


def audit_portfolio(
    book_root: Path,
    first_dates: pd.DataFrame,
    official: dict[str, Any],
    sidecar_arm_metrics: Path,
    portfolio: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    target = load_target_book(book_root / f"official_{portfolio}_target_book.csv")
    target = target[target["ticker"] != "CASH"].copy()
    merged = target.merge(first_dates, on="ticker", how="left")
    merged["first_price_date"] = pd.to_datetime(merged["first_price_date"], errors="coerce")
    merged["late_inclusion_violation"] = merged["first_price_date"].notna() & (merged["rebalance_date"] < merged["first_price_date"])
    merged["unknown_first_price_date"] = merged["first_price_date"].isna()
    merged["current_proxy_source"] = merged["source_universe"].astype(str).str.contains("current_constituents_proxy", regex=False, na=False)
    merged["dropped_weight_proxy_return"] = (
        merged["target_weight"] * merged["period_forward_return"] * merged["late_inclusion_violation"].astype(float)
    )
    by_date = (
        merged.groupby("rebalance_date", as_index=False)
        .agg(
            selected_weight=("target_weight", "sum"),
            current_proxy_weight=("target_weight", lambda s: float(s[merged.loc[s.index, "current_proxy_source"]].sum())),
            stricter_weight_kept=("target_weight", lambda s: float(s[~merged.loc[s.index, "late_inclusion_violation"]].sum())),
            late_inclusion_dropped_weight=("target_weight", lambda s: float(s[merged.loc[s.index, "late_inclusion_violation"]].sum())),
            late_inclusion_row_count=("late_inclusion_violation", "sum"),
            unknown_first_price_date_count=("unknown_first_price_date", "sum"),
            dropped_weight_proxy_return=("dropped_weight_proxy_return", "sum"),
        )
        .sort_values("rebalance_date")
    )
    metrics = portfolio_metrics(official, portfolio, sidecar_arm_metrics)
    dropped_rows = int(merged["late_inclusion_violation"].sum())
    current_proxy_rows = int(merged["current_proxy_source"].sum())
    dropped_weight = safe_float(by_date["late_inclusion_dropped_weight"].sum()) if not by_date.empty else 0.0
    # If the stricter first-price-date filter drops no rows, the measurable
    # late-inclusion lower-bound delta is exactly zero without a replay.
    measurable_cagr_pp = 0.0 if dropped_rows == 0 else safe_float(by_date["dropped_weight_proxy_return"].sum()) * 100.0
    summary = {
        "portfolio": portfolio,
        **metrics,
        "late_inclusion_violation_rows": dropped_rows,
        "unknown_first_price_date_rows": int(merged["unknown_first_price_date"].sum()),
        "current_proxy_selected_rows": current_proxy_rows,
        "current_proxy_selected_weight_sum": safe_float(merged.loc[merged["current_proxy_source"], "target_weight"].sum()),
        "late_inclusion_dropped_weight_sum": dropped_weight,
        "survivorship_inflation_estimate_cagr_pp": measurable_cagr_pp,
        "survivorship_inflation_estimate_max_dd_pp": 0.0 if dropped_rows == 0 else None,
        "deflated_cagr_lower_bound": safe_float(metrics["current_proxy_cagr"]) - measurable_cagr_pp / 100.0,
        "target_gap_current_proxy_pp": (0.35 if portfolio == "main" else 0.50) * 100.0 - safe_float(metrics["current_proxy_cagr"]) * 100.0,
        "target_gap_after_measurable_bound_pp": (0.35 if portfolio == "main" else 0.50) * 100.0 - (safe_float(metrics["current_proxy_cagr"]) - measurable_cagr_pp / 100.0) * 100.0,
    }
    by_date["portfolio"] = portfolio
    by_date["rebalance_date"] = by_date["rebalance_date"].dt.date.astype(str)
    return summary, by_date


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Run287 Survivorship Inflation Bound",
        "",
        "Status: `completed`",
        "",
        "Dominant survivorship component remains unmeasured:",
        "`delisted_exclusion`. The reported CAGR pp value is only the measured",
        "late-inclusion slice and must not be quoted as a clean-survivorship",
        "estimate.",
        "",
        "Research-only R2 audit. This is a one-sided proxy lower bound. It does",
        "not recover delisted-name exclusion and does not make PIT membership clean.",
        "",
        "## Summary",
        "",
        "| Portfolio | Metric | Current CAGR | Measurable inflation pp | Deflated lower-bound CAGR | Current target gap pp | Bound target gap pp | Late-inclusion rows |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for portfolio in PORTFOLIOS:
        row = payload["portfolios"][portfolio]
        lines.append(
            "| {portfolio} | {mode} | {cagr:.2%} | {infl:.2f} | {deflated:.2%} | {gap:.2f} | {bound_gap:.2f} | {rows} |".format(
                portfolio=portfolio,
                mode=row.get("metric_mode", ""),
                cagr=safe_float(row["current_proxy_cagr"]),
                infl=safe_float(row["survivorship_inflation_estimate_cagr_pp"]),
                deflated=safe_float(row["deflated_cagr_lower_bound"]),
                gap=safe_float(row["target_gap_current_proxy_pp"]),
                bound_gap=safe_float(row["target_gap_after_measurable_bound_pp"]),
                rows=int(row["late_inclusion_violation_rows"]),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
        "- `survivorship_inflation_estimate_cagr_pp` is a measured lower bound",
        "  from first-price-date late-inclusion only.",
        "- `unmeasured_component=delisted_exclusion`: free-tier artifacts cannot",
        "  reconstruct deleted historical R1000 members or full ticker lifecycles.",
        "- `survivorship_dominant_component_measured=false`: do not interpret a",
        "  zero late-inclusion slice as a clean PIT universe.",
        "- Label remains `proxy`; `pit_universe_label_clean=false` and production",
        "  promotion remains blocked.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_book = repo_path(args.candidate_book)
    book_root = repo_path(args.book_root)
    official_metrics = repo_path(args.official_metrics)
    sidecar_arm_metrics = repo_path(args.sidecar_arm_metrics)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    first_dates = candidate_first_dates(candidate_book)
    official = read_json(official_metrics)
    portfolio_payload: dict[str, Any] = {}
    frames: list[pd.DataFrame] = []
    for portfolio in PORTFOLIOS:
        summary, by_date = audit_portfolio(book_root, first_dates, official, sidecar_arm_metrics, portfolio)
        portfolio_payload[portfolio] = summary
        frames.append(by_date)
    membership_delta = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    membership_delta.to_csv(output_dir / "membership_delta.csv", index=False)
    max_inflation = max(
        safe_float(item["survivorship_inflation_estimate_cagr_pp"]) for item in portfolio_payload.values()
    ) if portfolio_payload else 0.0
    payload = {
        "schema_version": "run287-survivorship-bound-v1",
        "status": "completed",
        "research_only": True,
        "fullrun_dispatched": False,
        "production_promotion_allowed": False,
        "pit_universe_label_clean": False,
        "threshold_tuning_performed": False,
        "method": "first_price_date_stricter_arm_on_committed_candidate_and_target_books",
        "label": "proxy",
        "survivorship_measured_slice": "first_price_date_late_inclusion_only",
        "survivorship_dominant_component": "delisted_exclusion",
        "survivorship_dominant_component_measured": False,
        "survivorship_zero_bound_quote_allowed": False,
        "unmeasured_component": "delisted_exclusion",
        "survivorship_inflation_estimate_cagr_pp": max_inflation,
        "survivorship_inflation_estimate": {
            "cagr_pp_lower_bound": max_inflation,
            "method": "first_price_date_late_inclusion_only",
            "label": "proxy",
            "unmeasured_component": "delisted_exclusion",
        },
        "candidate_book": path_ref(candidate_book),
        "book_root": path_ref(book_root),
        "official_metrics": path_ref(official_metrics),
        "sidecar_arm_metrics": path_ref(sidecar_arm_metrics),
        "portfolios": portfolio_payload,
        "artifacts": {
            "summary": path_ref(output_dir / "summary.json"),
            "report": path_ref(output_dir / "report.md"),
            "membership_delta": path_ref(output_dir / "membership_delta.csv"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--book-root", default=DEFAULT_BOOK_ROOT)
    parser.add_argument("--official-metrics", default=DEFAULT_OFFICIAL_METRICS)
    parser.add_argument("--sidecar-arm-metrics", default=DEFAULT_SIDECAR_ARM_METRICS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(
        json.dumps(
            {
                "status": payload["status"],
                "label": payload["label"],
                "survivorship_inflation_estimate_cagr_pp": payload["survivorship_inflation_estimate_cagr_pp"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
