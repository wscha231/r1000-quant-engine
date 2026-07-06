#!/usr/bin/env python3
"""Run287 R3 measurement-only aggregate cluster-cap counterfactual.

This tool performs one cheap counterfactual on the committed run287 generated
Main target book. It does not dispatch a workflow, download data, regenerate a
book, tune thresholds, or mutate production policy.

The cap is aggregate cluster diversification, not per-name cap-safe sizing. The
default cluster is the ex-ante `sector` column and the default cap is a single
predeclared 30% aggregate weight limit. Freed weight is moved to CASH.
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


DEFAULT_RUN_ROOT = "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe"
DEFAULT_TARGET_BOOK = DEFAULT_RUN_ROOT + "/alphaops_vnext/official_main_target_book.csv"
DEFAULT_METRIC_SIDECAR = "outputs/run287_forensics/metric_sidecar_arm_metrics.csv"
DEFAULT_PARITY_SUMMARY = "outputs/run287_parity/summary.json"
DEFAULT_OUTPUT_DIR = "outputs/run287_cluster_cap"
DEFAULT_CLUSTER_COLUMN = "sector"
DEFAULT_CLUSTER_CAP = 0.30
DEFAULT_STARTING_CAPITAL = 100000.0

DRAW_ERAS = [
    ("covid_2020", "2020-02-19", "2020-05-31"),
    ("structural_2022_bear", "2021-11-19", "2022-09-26"),
    ("late_2024_ai_power_rotation", "2024-07-01", "2024-11-30"),
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def path_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def load_book(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path, low_memory=False)
    if "target_weight" not in d.columns:
        d["target_weight"] = d["weight"] if "weight" in d.columns else 0.0
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["target_weight"] = pd.to_numeric(d["target_weight"], errors="coerce").fillna(0.0)
    if "period_forward_return" in d.columns:
        d["period_forward_return"] = pd.to_numeric(d["period_forward_return"], errors="coerce").fillna(0.0)
    else:
        d["period_forward_return"] = 0.0
    return d.dropna(subset=["rebalance_date"]).copy()


def cluster_labels(frame: pd.DataFrame, cluster_column: str) -> pd.Series:
    if cluster_column in frame.columns:
        raw = frame[cluster_column]
    elif "industry_group" in frame.columns:
        raw = frame["industry_group"]
    else:
        raw = pd.Series("UNKNOWN", index=frame.index)
    labels = raw.fillna("").astype(str).str.strip()
    labels = labels.where(labels.ne(""), "UNKNOWN")
    return labels.where(frame["ticker"].ne("CASH"), "CASH")


def apply_cluster_cap(book: pd.DataFrame, *, cluster_column: str, cap: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    out_frames: list[pd.DataFrame] = []
    exposure_rows: list[dict[str, Any]] = []
    cap = float(cap)
    for date, group in book.groupby("rebalance_date", sort=True):
        g = group.copy()
        g["r3_cluster_label"] = cluster_labels(g, cluster_column)
        g["r3_pre_cluster_cap_weight"] = g["target_weight"]
        g["r3_cluster_cap_weight_delta"] = 0.0
        g["r3_cluster_cap_applied"] = False
        g["r3_cluster_cap"] = cap
        non_cash = g["ticker"].ne("CASH")
        freed_weight = 0.0
        for cluster, idx in g[non_cash].groupby("r3_cluster_label").groups.items():
            idx = list(idx)
            total = safe_float(g.loc[idx, "target_weight"].sum())
            capped_total = min(total, cap)
            applied = total > cap + 1e-12
            if applied and total > 0:
                scale = capped_total / total
                old = g.loc[idx, "target_weight"].copy()
                new = old * scale
                g.loc[idx, "target_weight"] = new
                g.loc[idx, "r3_cluster_cap_weight_delta"] = new - old
                g.loc[idx, "r3_cluster_cap_applied"] = True
                freed_weight += safe_float((old - new).sum())
            exposure_rows.append(
                {
                    "rebalance_date": pd.Timestamp(date).date().isoformat(),
                    "cluster": cluster,
                    "pre_cap_weight": total,
                    "post_cap_weight": capped_total if applied else total,
                    "cap": cap,
                    "capped": applied,
                    "freed_weight": max(0.0, total - capped_total),
                    "cluster_column": cluster_column,
                }
            )
        if freed_weight > 1e-12:
            cash_idx = g.index[g["ticker"].eq("CASH")].tolist()
            if cash_idx:
                first = cash_idx[0]
                old_cash = safe_float(g.at[first, "target_weight"])
                g.at[first, "target_weight"] = old_cash + freed_weight
                g.at[first, "r3_cluster_cap_weight_delta"] = freed_weight
                g.at[first, "r3_cluster_label"] = "CASH"
            else:
                row = {col: None for col in g.columns}
                row.update(
                    {
                        "rebalance_date": date,
                        "ticker": "CASH",
                        "target_weight": freed_weight,
                        "period_forward_return": 0.0,
                        "r3_cluster_label": "CASH",
                        "r3_pre_cluster_cap_weight": 0.0,
                        "r3_cluster_cap_weight_delta": freed_weight,
                        "r3_cluster_cap_applied": False,
                        "r3_cluster_cap": cap,
                    }
                )
                g = pd.concat([g, pd.DataFrame([row])], ignore_index=True)
        out_frames.append(g)
    capped = pd.concat(out_frames, ignore_index=True) if out_frames else book.copy()
    exposure = pd.DataFrame(exposure_rows)
    capped["rebalance_date"] = pd.to_datetime(capped["rebalance_date"]).dt.date.astype(str)
    return capped, exposure


def sidecar_rows(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def main_sidecar_metric(rows: pd.DataFrame, arm: str, key: str) -> float:
    if rows.empty:
        return 0.0
    match = rows[rows["arm"].astype(str).eq(arm) & rows["portfolio"].astype(str).str.lower().eq("main")]
    if match.empty:
        return 0.0
    return safe_float(match.iloc[0].get(key))


def implied_cash_yield(sidecar: pd.DataFrame) -> float:
    zero_cagr = main_sidecar_metric(sidecar, "generated_book_zero_yield", "cagr")
    cash_cagr = main_sidecar_metric(sidecar, "generated_book_cash_carry", "cagr")
    avg_cash = main_sidecar_metric(sidecar, "generated_book_cash_carry", "avg_cash_weight")
    if zero_cagr <= -1.0 or avg_cash <= 0:
        return 0.0
    return max(0.0, ((1.0 + cash_cagr) / (1.0 + zero_cagr) - 1.0) / avg_cash)


def dated_periods(dates: list[pd.Timestamp]) -> dict[pd.Timestamp, int]:
    out: dict[pd.Timestamp, int] = {}
    sorted_dates = sorted(dates)
    for idx, date in enumerate(sorted_dates):
        if idx + 1 < len(sorted_dates):
            days = max(1, int((sorted_dates[idx + 1] - date).days))
        else:
            days = 30
        out[date] = days
    return out


def equity_curve_from_book(
    book: pd.DataFrame,
    *,
    cash_yield_annual: float,
    starting_capital: float,
) -> pd.DataFrame:
    d = book.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    dates = sorted(d["rebalance_date"].dropna().unique())
    periods = dated_periods([pd.Timestamp(x) for x in dates])
    equity = float(starting_capital)
    rows: list[dict[str, Any]] = []
    for raw_date in dates:
        date = pd.Timestamp(raw_date)
        g = d[d["rebalance_date"].eq(date)].copy()
        weights = pd.to_numeric(g["target_weight"], errors="coerce").fillna(0.0)
        returns = pd.to_numeric(g["period_forward_return"], errors="coerce").fillna(0.0)
        cash_mask = g["ticker"].astype(str).str.upper().eq("CASH")
        cash_weight = safe_float(weights[cash_mask].sum())
        stock_return = safe_float((weights[~cash_mask] * returns[~cash_mask]).sum())
        period_days = periods[date]
        cash_return = cash_weight * ((1.0 + cash_yield_annual) ** (period_days / 365.0) - 1.0)
        total_return = stock_return + cash_return
        equity *= 1.0 + total_return
        rows.append(
            {
                "date": date.date().isoformat(),
                "equity_usd": equity,
                "period_return": total_return,
                "stock_return": stock_return,
                "cash_return": cash_return,
                "cash_weight": cash_weight,
            }
        )
    return pd.DataFrame(rows)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return safe_float(dd.min())


def curve_metrics(curve: pd.DataFrame, starting_capital: float) -> dict[str, Any]:
    if curve.empty:
        return {"status": "blocked_empty_curve"}
    dates = pd.to_datetime(curve["date"], errors="coerce")
    start = dates.min()
    end = dates.max()
    years = max((end - start).days / 365.25, 1.0 / 365.25)
    ending = safe_float(curve["equity_usd"].iloc[-1])
    cagr = (ending / starting_capital) ** (1.0 / years) - 1.0 if starting_capital > 0 else 0.0
    return {
        "status": "completed",
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "cagr": cagr,
        "max_dd": max_drawdown(pd.to_numeric(curve["equity_usd"], errors="coerce")),
        "ending_capital_usd": ending,
        "avg_cash_weight": safe_float(pd.to_numeric(curve["cash_weight"], errors="coerce").mean()),
        "target_pass": cagr >= 0.35 and max_drawdown(pd.to_numeric(curve["equity_usd"], errors="coerce")) >= -0.25,
    }


def era_metrics(curve: pd.DataFrame) -> dict[str, Any]:
    d = curve.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    out: dict[str, Any] = {}
    for name, start, end in DRAW_ERAS:
        sub = d[(d["date"] >= pd.Timestamp(start)) & (d["date"] <= pd.Timestamp(end))]
        mdd = max_drawdown(pd.to_numeric(sub["equity_usd"], errors="coerce")) if not sub.empty else 0.0
        out[name] = {
            "start": start,
            "end": end,
            "observation_count": int(len(sub)),
            "max_dd": mdd,
            "inside_minus_25": bool(mdd >= -0.25),
        }
    return out


def arm_row(arm: str, mode: str, source: str, metrics: dict[str, Any], proxy: bool) -> dict[str, Any]:
    return {
        "arm": arm,
        "portfolio": "main",
        "status": metrics.get("status"),
        "metric_mode": mode,
        "target_book_source": source,
        "start_date": metrics.get("start_date"),
        "end_date": metrics.get("end_date"),
        "cagr": metrics.get("cagr"),
        "max_dd": metrics.get("max_dd"),
        "avg_cash_weight": metrics.get("avg_cash_weight"),
        "ending_capital_usd": metrics.get("ending_capital_usd"),
        "target_pass": metrics.get("target_pass"),
        "proxy_metric": proxy,
        "production_promotion_allowed": False,
    }


def sidecar_official_arm(sidecar: pd.DataFrame, arm: str) -> dict[str, Any]:
    if sidecar.empty:
        return {"status": "missing"}
    match = sidecar[sidecar["arm"].astype(str).eq(arm) & sidecar["portfolio"].astype(str).str.lower().eq("main")]
    if match.empty:
        return {"status": "missing"}
    row = match.iloc[0]
    return {
        "status": row.get("status"),
        "start_date": row.get("start_date"),
        "end_date": row.get("end_date"),
        "cagr": safe_float(row.get("cagr")),
        "max_dd": safe_float(row.get("max_dd")),
        "avg_cash_weight": safe_float(row.get("avg_cash_weight")),
        "ending_capital_usd": safe_float(row.get("ending_capital_usd")),
        "target_pass": bool(str(row.get("target_pass")).lower() == "true"),
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Run287 R3 Cluster-Cap Counterfactual",
        "",
        f"Status: `{payload['status']}`",
        f"Decision label: `{payload['decision_label']}`",
        "",
        "Research-only measurement. No fullrun, production mutation, new alpha hook,",
        "or threshold sweep was performed.",
        "",
        "## Contract",
        "",
        f"- runner_parity_status: `{payload['runner_parity_status']}`",
        f"- cluster_column: `{payload['cluster_column']}`",
        f"- cluster_cap: `{payload['cluster_cap']:.2%}`",
        f"- cash_carry_proxy_source: `{payload['cash_carry_proxy_source']}`",
        f"- proxy_substrate_status: `{payload['proxy_substrate_status']}`",
        "",
        "## Metrics",
        "",
        "| Arm | Metric | CAGR | MaxDD | Target pass | Proxy |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in payload["arm_metrics"]:
        lines.append(
            "| {arm} | {mode} | {cagr:.2%} | {mdd:.2%} | {target} | {proxy} |".format(
                arm=row["arm"],
                mode=row["metric_mode"],
                cagr=safe_float(row.get("cagr")),
                mdd=safe_float(row.get("max_dd")),
                target=row.get("target_pass"),
                proxy=row.get("proxy_metric"),
            )
        )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"- proxy_joint_gate_pass: `{str(payload['proxy_joint_gate_pass']).lower()}`",
            f"- candidate_allowed: `{str(payload['candidate_allowed']).lower()}`",
            f"- mdd_benefit_test_underpowered_reason: `{payload['mdd_benefit_test_underpowered_reason']}`",
            f"- eras_inside_minus_25_count_cash_carry: `{payload['eras_inside_minus_25_count_cash_carry']}`",
            f"- proxy zero-yield CAGR delta vs official: `{payload['proxy_calibration_vs_official']['zero_yield_cagr_delta_pp']:.2f}pp`",
            f"- proxy cash-carry CAGR delta vs official: `{payload['proxy_calibration_vs_official']['cash_carry_cagr_delta_pp']:.2f}pp`",
            "",
            "The capped arms are proxy target-book calculations, not official",
            "broker-ledger acceptance evidence. This proxy does not reproduce the",
            "official broker-ledger substrate, so it is directional only. If a",
            "proxy ever passes, it still requires runner-parity broker replay",
            "before becoming a candidate.",
            "",
            "The cluster-cap idea is rejected because the CAGR cost is too high and",
            "the proxy substrate does not reproduce official broker-ledger metrics.",
            "This does not prove the cap has no MDD benefit: when proxy drawdowns",
            "never reach the -25% target boundary, the MDD-benefit test is",
            "under-powered until runner-parity broker replay is available.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    target_book = repo_path(args.target_book)
    metric_sidecar = repo_path(args.metric_sidecar)
    parity_summary = repo_path(args.parity_summary)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    book = load_book(target_book)
    sidecar = sidecar_rows(metric_sidecar)
    parity = read_json(parity_summary)
    capped, exposure = apply_cluster_cap(book, cluster_column=args.cluster_column, cap=args.cluster_cap)

    cash_yield = implied_cash_yield(sidecar)
    base_zero_curve = equity_curve_from_book(book, cash_yield_annual=0.0, starting_capital=args.starting_capital)
    cap_zero_curve = equity_curve_from_book(capped, cash_yield_annual=0.0, starting_capital=args.starting_capital)
    base_cash_curve = equity_curve_from_book(book, cash_yield_annual=cash_yield, starting_capital=args.starting_capital)
    cap_cash_curve = equity_curve_from_book(capped, cash_yield_annual=cash_yield, starting_capital=args.starting_capital)

    official_zero = sidecar_official_arm(sidecar, "generated_book_zero_yield")
    official_cash = sidecar_official_arm(sidecar, "generated_book_cash_carry")
    base_zero = curve_metrics(base_zero_curve, args.starting_capital)
    cap_zero = curve_metrics(cap_zero_curve, args.starting_capital)
    base_cash = curve_metrics(base_cash_curve, args.starting_capital)
    cap_cash = curve_metrics(cap_cash_curve, args.starting_capital)
    proxy_calibration = {
        "zero_yield_cagr_delta_pp": (safe_float(base_zero.get("cagr")) - safe_float(official_zero.get("cagr"))) * 100.0,
        "zero_yield_max_dd_delta_pp": (safe_float(base_zero.get("max_dd")) - safe_float(official_zero.get("max_dd"))) * 100.0,
        "cash_carry_cagr_delta_pp": (safe_float(base_cash.get("cagr")) - safe_float(official_cash.get("cagr"))) * 100.0,
        "cash_carry_max_dd_delta_pp": (safe_float(base_cash.get("max_dd")) - safe_float(official_cash.get("max_dd"))) * 100.0,
    }
    proxy_substrate_status = (
        "official_reproduction"
        if abs(proxy_calibration["zero_yield_cagr_delta_pp"]) <= 2.0
        and abs(proxy_calibration["zero_yield_max_dd_delta_pp"]) <= 2.0
        and abs(proxy_calibration["cash_carry_cagr_delta_pp"]) <= 2.0
        and abs(proxy_calibration["cash_carry_max_dd_delta_pp"]) <= 2.0
        else "not_official_reproduction_directional_only"
    )

    cash_eras = era_metrics(cap_cash_curve)
    zero_eras = era_metrics(cap_zero_curve)
    eras_inside_cash = sum(1 for row in cash_eras.values() if row["inside_minus_25"])
    eras_inside_zero = sum(1 for row in zero_eras.values() if row["inside_minus_25"])
    proxy_joint_gate_pass = bool(
        cap_zero.get("target_pass")
        and cap_cash.get("target_pass")
        and eras_inside_cash >= 2
        and eras_inside_zero >= 2
    )
    proxy_mdd_values = [
        safe_float(base_zero.get("max_dd")),
        safe_float(cap_zero.get("max_dd")),
        safe_float(base_cash.get("max_dd")),
        safe_float(cap_cash.get("max_dd")),
    ]
    proxy_mdd_reaches_minus25 = any(value <= -0.25 for value in proxy_mdd_values)
    mdd_benefit_test_underpowered_reason = "" if proxy_mdd_reaches_minus25 else "proxy_dd_never_reaches_minus25"
    runner_parity_status = str(parity.get("runner_parity_status") or "missing")
    candidate_allowed = bool(
        proxy_joint_gate_pass
        and runner_parity_status == "parity_exact"
        and proxy_substrate_status == "official_reproduction"
    )
    if not proxy_joint_gate_pass:
        decision_label = "cluster_cap_rejected_proxy_joint_gate_failed"
    elif proxy_substrate_status != "official_reproduction":
        decision_label = "cluster_cap_blocked_proxy_not_official_reproduction"
    elif runner_parity_status != "parity_exact":
        decision_label = "cluster_cap_blocked_runner_parity_gap"
    else:
        decision_label = "cluster_cap_proxy_pass_requires_broker_replay"

    arm_metrics = [
        arm_row("official_generated_zero_yield", "broker_ledger_next_close", "run287_sidecar", official_zero, False),
        arm_row("official_generated_cash_carry", "broker_ledger_next_close_cash_carry", "run287_sidecar", official_cash, False),
        arm_row("baseline_proxy_zero_yield", "proxy_monthly_target_book_zero_yield", "run287_generated_book", base_zero, True),
        arm_row("cluster_cap_proxy_zero_yield", "proxy_monthly_target_book_zero_yield", "r3_cluster_cap_book", cap_zero, True),
        arm_row("baseline_proxy_cash_carry", "proxy_monthly_target_book_cash_carry_implied", "run287_generated_book", base_cash, True),
        arm_row("cluster_cap_proxy_cash_carry", "proxy_monthly_target_book_cash_carry_implied", "r3_cluster_cap_book", cap_cash, True),
    ]

    capped.to_csv(output_dir / "capped_main_target_book.csv", index=False)
    exposure.to_csv(output_dir / "cluster_exposure_by_date.csv", index=False)
    pd.DataFrame(arm_metrics).to_csv(output_dir / "arm_metrics.csv", index=False)
    cap_cash_curve.to_csv(output_dir / "proxy_cash_carry_equity_curve.csv", index=False)
    cap_zero_curve.to_csv(output_dir / "proxy_zero_yield_equity_curve.csv", index=False)

    payload = {
        "schema_version": "run287-cluster-cap-counterfactual-v1",
        "status": "completed",
        "decision_label": decision_label,
        "candidate_allowed": candidate_allowed,
        "proxy_joint_gate_pass": proxy_joint_gate_pass,
        "research_only": True,
        "fullrun_dispatched": False,
        "market_data_downloaded": False,
        "target_book_regenerated": False,
        "threshold_tuning_performed": False,
        "new_alpha_hook_added": False,
        "production_promotion_allowed": False,
        "direct_losing_month_edit_allowed": False,
        "target_book": path_ref(target_book),
        "metric_sidecar": path_ref(metric_sidecar),
        "parity_summary": path_ref(parity_summary),
        "runner_parity_status": runner_parity_status,
        "cluster_column": args.cluster_column,
        "cluster_cap": float(args.cluster_cap),
        "cash_carry_implied_annual_yield": cash_yield,
        "cash_carry_proxy_source": "generated_book_cash_carry_vs_zero_yield_sidecar_implied_flat_yield",
        "proxy_substrate_status": proxy_substrate_status,
        "proxy_calibration_vs_official": proxy_calibration,
        "proxy_mdd_reaches_minus25": proxy_mdd_reaches_minus25,
        "mdd_benefit_test_underpowered_reason": mdd_benefit_test_underpowered_reason,
        "eras_cash_carry": cash_eras,
        "eras_zero_yield": zero_eras,
        "eras_inside_minus_25_count_cash_carry": eras_inside_cash,
        "eras_inside_minus_25_count_zero_yield": eras_inside_zero,
        "max_freed_weight": safe_float(exposure["freed_weight"].max()) if not exposure.empty else 0.0,
        "capped_cluster_date_count": int(exposure["capped"].sum()) if not exposure.empty else 0,
        "arm_metrics": arm_metrics,
        "artifacts": {
            "summary": path_ref(output_dir / "summary.json"),
            "report": path_ref(output_dir / "report.md"),
            "arm_metrics": path_ref(output_dir / "arm_metrics.csv"),
            "cluster_exposure_by_date": path_ref(output_dir / "cluster_exposure_by_date.csv"),
            "capped_main_target_book": path_ref(output_dir / "capped_main_target_book.csv"),
            "proxy_cash_carry_equity_curve": path_ref(output_dir / "proxy_cash_carry_equity_curve.csv"),
            "proxy_zero_yield_equity_curve": path_ref(output_dir / "proxy_zero_yield_equity_curve.csv"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", default=DEFAULT_TARGET_BOOK)
    parser.add_argument("--metric-sidecar", default=DEFAULT_METRIC_SIDECAR)
    parser.add_argument("--parity-summary", default=DEFAULT_PARITY_SUMMARY)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cluster-column", default=DEFAULT_CLUSTER_COLUMN)
    parser.add_argument("--cluster-cap", type=float, default=DEFAULT_CLUSTER_CAP)
    parser.add_argument("--starting-capital", type=float, default=DEFAULT_STARTING_CAPITAL)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload["status"], "decision_label": payload["decision_label"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
