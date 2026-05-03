#!/usr/bin/env python3
"""Fast orchestrator replay from existing monthly artifacts.

The preferred path uses:
  - main monthly returns from trade_journal/holdings_history.csv
  - concentrated monthly returns from reports/concentrated_strategy_monthly.csv

When the concentrated monthly file is unavailable, the tool writes an explicit
blocked/proxy report instead of pretending the target is validated.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/orchestrator_replay/concentrated_balanced"

BALANCED_CAPACITY = {
    "deep_bear": {"main": 0.40, "concentrated": 0.00, "cash": 0.60},
    "bear": {"main": 0.55, "concentrated": 0.05, "cash": 0.40},
    "neutral": {"main": 0.55, "concentrated": 0.25, "cash": 0.20},
    "bull": {"main": 0.60, "concentrated": 0.25, "cash": 0.15},
    "strong_bull": {"main": 0.55, "concentrated": 0.30, "cash": 0.15},
}

TARGETS = {
    "main": {"cagr": 0.25, "max_dd": -0.20},
    "concentrated": {"cagr": 0.40, "max_dd": -0.22},
    "unified": {"cagr": 0.28, "max_dd": -0.22},
}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if math.isnan(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def pct(value: float) -> str:
    return f"{value:.2%}"


def calc_metrics(monthly_returns: list[float]) -> dict[str, Any]:
    rets = [float(x) for x in monthly_returns if math.isfinite(float(x))]
    if not rets:
        return {
            "months": 0,
            "cagr": None,
            "sharpe": None,
            "max_dd": None,
            "calmar": None,
            "vol_ann": None,
            "ending_equity": 1.0,
        }
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for ret in rets:
        equity *= 1.0 + ret
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0)
    years = len(rets) / 12.0
    cagr = equity ** (1.0 / years) - 1.0 if years > 0 and equity > 0 else None
    mean = sum(rets) / len(rets)
    variance = sum((ret - mean) ** 2 for ret in rets) / len(rets)
    std = math.sqrt(variance)
    sharpe = (mean * 12.0) / (std * math.sqrt(12.0)) if std > 0 else 0.0
    vol_ann = std * math.sqrt(12.0)
    calmar = cagr / abs(max_dd) if cagr is not None and max_dd < 0 else None
    return {
        "months": len(rets),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "vol_ann": vol_ann,
        "ending_equity": equity,
    }


def load_main_monthly(holdings_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    rows = read_csv_rows(holdings_path)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        dt = str(row.get("rebalance_date") or "")[:10]
        if dt:
            grouped[dt].append(row)
    monthly: dict[str, dict[str, Any]] = {}
    for dt, group in grouped.items():
        ret = 0.0
        regimes = Counter()
        names = 0
        weight_sum = 0.0
        for row in group:
            ticker = str(row.get("ticker") or "").upper()
            if ticker and ticker != "CASH":
                names += 1
            weight = safe_float(row.get("weight"))
            period_return = safe_float(row.get("period_forward_return"), default=float("nan"))
            if math.isfinite(period_return):
                ret += weight * period_return
            weight_sum += weight
            regime = str(row.get("regime_state") or "neutral").strip() or "neutral"
            regimes[regime] += 1
        monthly[dt] = {
            "date": dt,
            "main_return": ret,
            "regime_state": regimes.most_common(1)[0][0] if regimes else "neutral",
            "main_names": names,
            "main_weight_sum": weight_sum,
        }
    return monthly, {"path": str(holdings_path), "rows": len(rows), "months": len(monthly)}


def load_concentrated_monthly(path: Path, target_n: int, weighting_mode: str, interval: int) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    rows = read_csv_rows(path)
    selected: dict[str, dict[str, Any]] = {}
    matched = 0
    for row in rows:
        row_target_n = int(safe_float(row.get("target_n") or row.get("target_stock_names"), -1))
        row_mode = str(row.get("weighting_mode") or "")
        row_interval = int(safe_float(row.get("active_rebalance_interval_months") or row.get("rebalance_interval_months"), -1))
        if row_target_n != int(target_n) or row_mode != weighting_mode or row_interval != int(interval):
            continue
        dt = str(row.get("rebalance_date") or "")[:10]
        if not dt:
            continue
        matched += 1
        selected[dt] = {
            "date": dt,
            "concentrated_return": safe_float(row.get("net_return")),
            "concentrated_turnover": safe_float(row.get("turnover")),
            "bench_return": safe_float(row.get("bench_return"), default=float("nan")),
            "cash_weight": safe_float(row.get("cash_weight")),
        }
    return selected, {
        "path": str(path),
        "rows": len(rows),
        "matched_rows": matched,
        "target_n": target_n,
        "weighting_mode": weighting_mode,
        "interval": interval,
    }


def proxy_concentrated_from_main(main_holdings_path: Path, target_n: int) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Fallback proxy using only selected main holdings.

    This is not a valid concentrated backtest. It exists only to keep the guard
    output informative when the true concentrated monthly artifact is missing.
    """
    rows = read_csv_rows(main_holdings_path)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        dt = str(row.get("rebalance_date") or "")[:10]
        if not dt:
            continue
        period_return = safe_float(row.get("period_forward_return"), default=float("nan"))
        if not math.isfinite(period_return):
            continue
        grouped[dt].append(
            {
                "return": period_return,
                "score": safe_float(row.get("raw_score")),
                "ticker": row.get("ticker"),
            }
        )
    out: dict[str, dict[str, Any]] = {}
    for dt, group in grouped.items():
        selected = sorted(group, key=lambda row: row["score"], reverse=True)[:target_n]
        ret = sum(row["return"] for row in selected) / len(selected) if selected else 0.0
        out[dt] = {"date": dt, "concentrated_return": ret, "proxy_selected_from_main": True}
    return out, {
        "path": str(main_holdings_path),
        "rows": len(rows),
        "months": len(out),
        "target_n": target_n,
        "fallback": "top_raw_score_within_main_holdings",
        "valid_for_promotion": False,
    }


def replay(
    main_monthly: dict[str, dict[str, Any]],
    concentrated_monthly: dict[str, dict[str, Any]],
    capacity_map: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    equity = 1.0
    for dt in sorted(set(main_monthly) & set(concentrated_monthly)):
        main = main_monthly[dt]
        conc = concentrated_monthly[dt]
        regime = str(main.get("regime_state") or "neutral")
        caps = capacity_map.get(regime, capacity_map["neutral"])
        main_cap = safe_float(caps.get("main"))
        conc_cap = safe_float(caps.get("concentrated"))
        cash = max(0.0, 1.0 - main_cap - conc_cap)
        main_ret = safe_float(main.get("main_return"))
        conc_ret = safe_float(conc.get("concentrated_return"))
        net_ret = main_cap * main_ret + conc_cap * conc_ret
        equity *= 1.0 + net_ret
        rows.append(
            {
                "rebalance_date": dt,
                "regime_state": regime,
                "main_capacity": main_cap,
                "concentrated_capacity": conc_cap,
                "cash_capacity": cash,
                "main_return": main_ret,
                "concentrated_return": conc_ret,
                "net_return": net_ret,
                "equity": equity,
                "main_names": main.get("main_names"),
                "concentrated_source_proxy": bool(conc.get("proxy_selected_from_main")),
            }
        )
    return rows


def target_status(name: str, metrics: dict[str, Any], target: dict[str, float]) -> dict[str, Any]:
    cagr = metrics.get("cagr")
    max_dd = metrics.get("max_dd")
    cagr_pass = cagr is not None and cagr >= target["cagr"]
    dd_pass = max_dd is not None and max_dd >= target["max_dd"]
    return {
        "portfolio": name,
        "cagr": cagr,
        "cagr_target": target["cagr"],
        "cagr_gap_pp": max(0.0, (target["cagr"] - (cagr or 0.0)) * 100.0),
        "cagr_pass": cagr_pass,
        "max_dd": max_dd,
        "max_dd_target": target["max_dd"],
        "max_dd_improvement_needed_pp": max(0.0, (target["max_dd"] - (max_dd or -1.0)) * 100.0),
        "max_dd_pass": dd_pass,
        "target_pass": cagr_pass and dd_pass,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Orchestrator Replay",
        "",
        f"- Status: `{payload['status']}`",
        f"- Data mode: `{payload['data_mode']}`",
        f"- Production activation allowed: `{str(payload['production_activation_allowed']).lower()}`",
        "",
        "## Metrics",
        "",
        "| Portfolio | CAGR | Target | MaxDD | Target | Pass |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["target_status"]:
        cagr = row.get("cagr")
        max_dd = row.get("max_dd")
        lines.append(
            "| {portfolio} | {cagr} | {cagr_target} | {max_dd} | {max_dd_target} | {passed} |".format(
                portfolio=row["portfolio"],
                cagr="" if cagr is None else pct(cagr),
                cagr_target=pct(row["cagr_target"]),
                max_dd="" if max_dd is None else pct(max_dd),
                max_dd_target=pct(row["max_dd_target"]),
                passed=str(row["target_pass"]).lower(),
            )
        )
    lines.extend(["", "## Interpretation", ""])
    lines.extend(payload.get("interpretation") or [])
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    holdings_path = latest_run / "trade_journal" / "holdings_history.csv"
    concentrated_path = latest_run / "reports" / "concentrated_strategy_monthly.csv"
    if args.concentrated_monthly:
        concentrated_path = repo_path(args.concentrated_monthly)

    main_monthly, main_audit = load_main_monthly(holdings_path)
    concentrated_monthly, conc_audit = load_concentrated_monthly(
        concentrated_path,
        target_n=args.target_n,
        weighting_mode=args.weighting_mode,
        interval=args.interval,
    )
    data_mode = "historical_concentrated_monthly"
    if not concentrated_monthly:
        concentrated_monthly, conc_audit = proxy_concentrated_from_main(holdings_path, target_n=args.target_n)
        data_mode = "proxy_top_raw_score_within_main_holdings"

    replay_rows = replay(main_monthly, concentrated_monthly, BALANCED_CAPACITY)
    main_rets = [safe_float(row["main_return"]) for row in replay_rows]
    conc_rets = [safe_float(row["concentrated_return"]) for row in replay_rows]
    unified_rets = [safe_float(row["net_return"]) for row in replay_rows]
    metrics = {
        "main_proxy": calc_metrics(main_rets),
        "concentrated": calc_metrics(conc_rets),
        "unified_balanced": calc_metrics(unified_rets),
    }
    production_activation_allowed = False
    valid_for_promotion = data_mode == "historical_concentrated_monthly"
    status = "completed" if valid_for_promotion else "blocked_missing_concentrated_monthly"
    target_rows = [
        target_status("main_proxy", metrics["main_proxy"], TARGETS["main"]),
        target_status("concentrated", metrics["concentrated"], TARGETS["concentrated"]),
        target_status("unified_balanced", metrics["unified_balanced"], TARGETS["unified"]),
    ]
    interpretation = []
    if valid_for_promotion:
        interpretation.append("Replay used historical concentrated monthly returns and can be used as a challenger input.")
    else:
        interpretation.append(
            "Historical concentrated_strategy_monthly.csv is missing, so concentrated returns are only a proxy from selected main holdings."
        )
        interpretation.append(
            "Run the full rebuild after this change so reports/concentrated_strategy_monthly.csv is preserved into cloud_results."
        )
    interpretation.append("Production remains blocked until target gates and human approval pass.")

    payload = {
        "experiment_id": "E4_concentrated_balanced_replay",
        "status": status,
        "data_mode": data_mode,
        "valid_for_promotion": valid_for_promotion,
        "production_activation_allowed": production_activation_allowed,
        "main_audit": main_audit,
        "concentrated_audit": conc_audit,
        "capacity_map": BALANCED_CAPACITY,
        "metrics": metrics,
        "target_status": target_rows,
        "interpretation": interpretation,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", payload)
    write_csv(
        output_dir / "equity_curve.csv",
        replay_rows,
        [
            "rebalance_date",
            "regime_state",
            "main_capacity",
            "concentrated_capacity",
            "cash_capacity",
            "main_return",
            "concentrated_return",
            "net_return",
            "equity",
            "main_names",
            "concentrated_source_proxy",
        ],
    )
    write_csv(
        output_dir / "target_status.csv",
        target_rows,
        [
            "portfolio",
            "cagr",
            "cagr_target",
            "cagr_gap_pp",
            "cagr_pass",
            "max_dd",
            "max_dd_target",
            "max_dd_improvement_needed_pp",
            "max_dd_pass",
            "target_pass",
        ],
    )
    write_text(output_dir / "replay_report.md", render_report(payload))
    return payload


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--concentrated-monthly", default="")
    parser.add_argument("--target-n", type=int, default=5)
    parser.add_argument("--weighting-mode", default="score_power")
    parser.add_argument("--interval", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
