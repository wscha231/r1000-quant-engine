#!/usr/bin/env python3
"""Re-score completed Run287 A/B arms under a CAGR-first research objective.

The audit does not create a new alpha arm or tune a threshold.  It only reads
completed arm metrics, applies the preregistered CAGR-first gates, and (when
provided) verifies a fixed 25/50/100 bps cash-carry/zero-yield sensitivity
packet.  Maximum drawdown remains reported but is not a pass/fail gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DELTA_COLUMNS = (
    "delta_cagr_pp",
    "delta_windows.oos.cagr_pp",
    "delta_windows.oos2.cagr_pp",
    "delta_sharpe",
    "delta_max_dd_pp",
)
ERA_BUCKETS = (
    ("2019_2021_pre_ai_bull", "2019-01-01", "2021-12-31"),
    ("2022_bear", "2022-01-01", "2022-12-31"),
    ("2023_2024_ai_bull", "2023-01-01", "2024-12-31"),
    ("2025_plus", "2025-01-01", "2099-12-31"),
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=False, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def infer_context(file_value: Any) -> tuple[str, str]:
    parts = str(file_value or "").replace("\\", "/").split("/")
    if "signal_replays" in parts:
        index = parts.index("signal_replays")
        if len(parts) > index + 2:
            return parts[index + 1], parts[index + 2]
    return "", ""


def normalized_signal(signal: str) -> str:
    value = str(signal or "").strip().lower()
    return value.removesuffix("_score")


def registry_matches(signal: str, registry: dict[str, Any]) -> list[str]:
    target = normalized_signal(signal)
    matches: list[str] = []
    for entry in registry.get("entries", []):
        if not isinstance(entry, dict) or not entry.get("blocked_reuse"):
            continue
        registered = normalized_signal(str(entry.get("signal") or ""))
        if registered == target or (target == "growth_confirmation" and registered == "growth_confirmation"):
            matches.append(str(entry.get("id") or ""))
    return sorted(item for item in matches if item)


def metric_delta(candidate: dict[str, Any], baseline: dict[str, Any], key: str) -> float | None:
    candidate_value = finite_float(candidate.get(key))
    baseline_value = finite_float(baseline.get(key))
    if candidate_value is None or baseline_value is None:
        return None
    return (candidate_value - baseline_value) * 100.0


def window_delta(candidate: dict[str, Any], baseline: dict[str, Any], window: str) -> float | None:
    candidate_windows = candidate.get("windows") if isinstance(candidate.get("windows"), dict) else {}
    baseline_windows = baseline.get("windows") if isinstance(baseline.get("windows"), dict) else {}
    candidate_window = candidate_windows.get(window) if isinstance(candidate_windows.get(window), dict) else {}
    baseline_window = baseline_windows.get(window) if isinstance(baseline_windows.get(window), dict) else {}
    return metric_delta(candidate_window, baseline_window, "cagr")


def candidate_rows(
    inventory: pd.DataFrame,
    contract: dict[str, Any],
    registry: dict[str, Any],
) -> pd.DataFrame:
    missing = [column for column in ("file", "arm", *REQUIRED_DELTA_COLUMNS) if column not in inventory]
    if missing:
        raise ValueError(f"inventory missing columns: {missing}")
    core = contract.get("core_gates") if isinstance(contract.get("core_gates"), dict) else {}
    minimum_sharpe = finite_float(core.get("minimum_delta_sharpe"))
    minimum_sharpe = -0.05 if minimum_sharpe is None else minimum_sharpe
    rows: list[dict[str, Any]] = []
    selected = inventory[
        inventory["file"].astype(str).str.replace("\\", "/", regex=False).str.endswith("/arm_metrics.csv")
        & ~inventory["arm"].astype(str).eq("baseline")
        & inventory["delta_cagr_pp"].notna()
    ].copy()
    selected = selected.drop_duplicates(["file", "arm"], keep="first")
    for record in selected.to_dict(orient="records"):
        signal, portfolio = infer_context(record.get("file"))
        arm_metrics_path = repo_path(str(record.get("file") or ""))
        summary = read_json(arm_metrics_path.parent / "summary.json")
        broker_path = repo_path(str(record.get("broker_metrics_path") or ""))
        broker = read_json(broker_path)
        d_full = finite_float(record.get("delta_cagr_pp"))
        d_oos = finite_float(record.get("delta_windows.oos.cagr_pp"))
        d_oos2 = finite_float(record.get("delta_windows.oos2.cagr_pp"))
        d_sharpe = finite_float(record.get("delta_sharpe"))
        d_mdd = finite_float(record.get("delta_max_dd_pp"))
        provenance_ok = summary.get("used_forward_return_in_ranking") is False
        execution_ok = (
            broker.get("fill_mode") == core.get("fill_mode", "next_close")
            and broker.get("integer_shares") is bool(core.get("integer_shares", True))
            and finite_float(broker.get("cost_bps_per_side"))
            == finite_float(core.get("reference_cost_bps_per_side", 25.0))
        )
        core_pass = all(
            (
                d_full is not None and d_full > 0,
                d_oos is not None and d_oos > 0,
                d_oos2 is not None and d_oos2 > 0,
                d_sharpe is not None and d_sharpe >= minimum_sharpe,
                provenance_ok,
                execution_ok,
            )
        )
        blocked_ids = registry_matches(signal, registry)
        rows.append(
            {
                "signal": signal,
                "portfolio": portfolio,
                "arm": str(record.get("arm") or ""),
                "cagr": finite_float(record.get("cagr")),
                "max_dd": finite_float(record.get("max_dd")),
                "delta_cagr_pp": d_full,
                "delta_oos_cagr_pp": d_oos,
                "delta_oos2_cagr_pp": d_oos2,
                "delta_sharpe": d_sharpe,
                "delta_max_dd_pp_diagnostic": d_mdd,
                "used_forward_return_in_ranking": summary.get("used_forward_return_in_ranking"),
                "execution_contract_pass": execution_ok,
                "core_growth_gate_pass": core_pass,
                "do_not_repeat_match_ids": "|".join(blocked_ids),
                "new_grid_allowed": False,
                "exact_completed_arm_rescore_allowed": True,
                "arm_metrics_path": str(arm_metrics_path),
                "broker_metrics_path": str(broker_path),
                "target_book_path": str(record.get("target_book_path") or ""),
                "original_ab_verdict": str(record.get("ab_verdict") or ""),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.sort_values(
        ["core_growth_gate_pass", "delta_cagr_pp", "delta_oos_cagr_pp", "arm"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)


def sensitivity_rows(root: Path, contract: dict[str, Any]) -> pd.DataFrame:
    required = contract.get("required_sensitivities") if isinstance(contract.get("required_sensitivities"), dict) else {}
    rows: list[dict[str, Any]] = []
    for mode in required.get("cash_modes", ["cash_carry", "zero_yield"]):
        for bps in required.get("cost_bps_per_side", [25, 50, 100]):
            base_path = root / "replays" / str(mode) / f"{int(bps)}bps" / "baseline" / "metrics.json"
            candidate_path = root / "replays" / str(mode) / f"{int(bps)}bps" / "candidate" / "metrics.json"
            baseline = read_json(base_path)
            candidate = read_json(candidate_path)
            exists = bool(baseline and candidate)
            d_full = metric_delta(candidate, baseline, "cagr") if exists else None
            d_oos = window_delta(candidate, baseline, "oos") if exists else None
            d_oos2 = window_delta(candidate, baseline, "oos2") if exists else None
            passed = bool(
                exists
                and d_full is not None and d_full > 0
                and d_oos is not None and d_oos > 0
                and d_oos2 is not None and d_oos2 > 0
            )
            rows.append(
                {
                    "cash_mode": mode,
                    "cost_bps_per_side": int(bps),
                    "metrics_present": exists,
                    "baseline_cagr": finite_float(baseline.get("cagr")) if exists else None,
                    "candidate_cagr": finite_float(candidate.get("cagr")) if exists else None,
                    "delta_cagr_pp": d_full,
                    "baseline_oos_cagr": finite_float((baseline.get("windows") or {}).get("oos", {}).get("cagr")) if exists else None,
                    "candidate_oos_cagr": finite_float((candidate.get("windows") or {}).get("oos", {}).get("cagr")) if exists else None,
                    "delta_oos_cagr_pp": d_oos,
                    "baseline_oos2_cagr": finite_float((baseline.get("windows") or {}).get("oos2", {}).get("cagr")) if exists else None,
                    "candidate_oos2_cagr": finite_float((candidate.get("windows") or {}).get("oos2", {}).get("cagr")) if exists else None,
                    "delta_oos2_cagr_pp": d_oos2,
                    "baseline_max_dd_diagnostic": finite_float(baseline.get("max_dd")) if exists else None,
                    "candidate_max_dd_diagnostic": finite_float(candidate.get("max_dd")) if exists else None,
                    "delta_max_dd_pp_diagnostic": metric_delta(candidate, baseline, "max_dd") if exists else None,
                    "direction_gate_pass": passed,
                    "baseline_metrics_path": str(base_path),
                    "candidate_metrics_path": str(candidate_path),
                }
            )
    return pd.DataFrame(rows)


def account_ticker_pnl(account_root: Path) -> pd.DataFrame:
    holdings_path = account_root / "holdings_daily.csv"
    trades_path = account_root / "trades.csv"
    equity_path = account_root / "equity_curve.csv"
    if not holdings_path.is_file() or not trades_path.is_file() or not equity_path.is_file():
        return pd.DataFrame(columns=["ticker", "pnl_usd"])
    holdings = pd.read_csv(holdings_path, usecols=["date", "ticker", "market_value_usd"])
    trades = pd.read_csv(trades_path, usecols=["date", "ticker", "side", "gross_value", "fee_usd"])
    dates = pd.to_datetime(pd.read_csv(equity_path, usecols=["date"])["date"], errors="coerce").dropna().sort_values()
    holdings["date"] = pd.to_datetime(holdings["date"], errors="coerce")
    trades["date"] = pd.to_datetime(trades["date"], errors="coerce")
    holdings["market_value_usd"] = pd.to_numeric(holdings["market_value_usd"], errors="coerce").fillna(0.0)
    market = holdings.pivot_table(index="date", columns="ticker", values="market_value_usd", aggfunc="sum", fill_value=0.0)
    market = market.reindex(index=dates, fill_value=0.0).sort_index()
    market_change = market.diff().fillna(market)
    trades["gross_value"] = pd.to_numeric(trades["gross_value"], errors="coerce").fillna(0.0)
    trades["fee_usd"] = pd.to_numeric(trades["fee_usd"], errors="coerce").fillna(0.0)
    trades["signed_position_flow"] = trades["gross_value"].where(trades["side"].astype(str).eq("BUY"), -trades["gross_value"])
    flow = trades.pivot_table(index="date", columns="ticker", values="signed_position_flow", aggfunc="sum", fill_value=0.0)
    fees = trades.pivot_table(index="date", columns="ticker", values="fee_usd", aggfunc="sum", fill_value=0.0)
    tickers = sorted(set(market_change.columns) | set(flow.columns) | set(fees.columns))
    pnl = (
        market_change.reindex(index=dates, columns=tickers, fill_value=0.0)
        - flow.reindex(index=dates, columns=tickers, fill_value=0.0)
        - fees.reindex(index=dates, columns=tickers, fill_value=0.0)
    )
    out = pnl.sum(axis=0).rename("pnl_usd").reset_index().rename(columns={"index": "ticker"})
    return out.sort_values("pnl_usd", ascending=False, kind="mergesort").reset_index(drop=True)


def assign_era(value: Any) -> str:
    date = pd.to_datetime(value, errors="coerce")
    if pd.isna(date):
        return "unknown"
    for name, start, end in ERA_BUCKETS:
        if pd.Timestamp(start) <= date <= pd.Timestamp(end):
            return name
    return "unknown"


def reference_attribution(root: Path, contract: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    reference_root = root / "replays" / "cash_carry" / "25bps"
    baseline_root = reference_root / "baseline"
    candidate_root = reference_root / "candidate"
    base_equity_path = baseline_root / "equity_curve.csv"
    candidate_equity_path = candidate_root / "equity_curve.csv"
    if not base_equity_path.is_file() or not candidate_equity_path.is_file():
        return {"available": False}, pd.DataFrame(), pd.DataFrame()
    base_equity = pd.read_csv(base_equity_path)
    candidate_equity = pd.read_csv(candidate_equity_path)
    for frame in (base_equity, candidate_equity):
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["equity_usd"] = pd.to_numeric(frame["equity_usd"], errors="coerce")
        frame["cash_interest_daily"] = pd.to_numeric(frame.get("cash_interest_daily", 0.0), errors="coerce").fillna(0.0)
    joined = base_equity[["date", "equity_usd"]].merge(
        candidate_equity[["date", "equity_usd"]], on="date", how="inner", suffixes=("_baseline", "_candidate")
    ).sort_values("date")
    joined["baseline_change"] = joined["equity_usd_baseline"].diff().fillna(joined["equity_usd_baseline"] - 100000.0)
    joined["candidate_change"] = joined["equity_usd_candidate"].diff().fillna(joined["equity_usd_candidate"] - 100000.0)
    joined["incremental_pnl_usd"] = joined["candidate_change"] - joined["baseline_change"]
    joined["era"] = joined["date"].map(assign_era)
    era = joined.groupby("era", as_index=False)["incremental_pnl_usd"].sum()
    total_incremental = float(joined["equity_usd_candidate"].iloc[-1] - joined["equity_usd_baseline"].iloc[-1])
    era["share_of_net_incremental_pnl"] = era["incremental_pnl_usd"] / total_incremental if total_incremental else math.nan
    era = era.sort_values("incremental_pnl_usd", ascending=False, kind="mergesort").reset_index(drop=True)

    base_ticker = account_ticker_pnl(baseline_root).rename(columns={"pnl_usd": "baseline_pnl_usd"})
    candidate_ticker = account_ticker_pnl(candidate_root).rename(columns={"pnl_usd": "candidate_pnl_usd"})
    ticker = base_ticker.merge(candidate_ticker, on="ticker", how="outer").fillna(0.0)
    ticker["incremental_pnl_usd"] = ticker["candidate_pnl_usd"] - ticker["baseline_pnl_usd"]
    base_cash = float(base_equity["cash_interest_daily"].sum())
    candidate_cash = float(candidate_equity["cash_interest_daily"].sum())
    ticker = pd.concat(
        [
            ticker,
            pd.DataFrame(
                [{
                    "ticker": "__CASH_CARRY__",
                    "baseline_pnl_usd": base_cash,
                    "candidate_pnl_usd": candidate_cash,
                    "incremental_pnl_usd": candidate_cash - base_cash,
                }]
            ),
        ],
        ignore_index=True,
    )
    attributed = float(ticker["incremental_pnl_usd"].sum())
    residual = total_incremental - attributed
    if abs(residual) > 1e-6:
        ticker = pd.concat(
            [
                ticker,
                pd.DataFrame(
                    [{
                        "ticker": "__ATTRIBUTION_RESIDUAL__",
                        "baseline_pnl_usd": 0.0,
                        "candidate_pnl_usd": residual,
                        "incremental_pnl_usd": residual,
                    }]
                ),
            ],
            ignore_index=True,
        )
    ticker["share_of_net_incremental_pnl"] = ticker["incremental_pnl_usd"] / total_incremental if total_incremental else math.nan
    ticker = ticker.sort_values("incremental_pnl_usd", ascending=False, kind="mergesort").reset_index(drop=True)
    security_ticker = ticker[~ticker["ticker"].astype(str).str.startswith("__")]
    top_ticker = security_ticker.iloc[0].to_dict() if not security_ticker.empty else {}
    top_era = era.iloc[0].to_dict() if not era.empty else {}
    generalization = contract.get("generalization_gates") if isinstance(contract.get("generalization_gates"), dict) else {}
    ticker_limit = finite_float(generalization.get("maximum_single_ticker_share_of_net_incremental_pnl")) or 0.5
    era_limit = finite_float(generalization.get("maximum_single_era_share_of_net_incremental_pnl")) or 0.5
    top_ticker_share = finite_float(top_ticker.get("share_of_net_incremental_pnl"))
    top_era_share = finite_float(top_era.get("share_of_net_incremental_pnl"))
    concentration_pass = bool(
        top_ticker_share is not None and top_ticker_share <= ticker_limit
        and top_era_share is not None and top_era_share <= era_limit
    )
    summary = {
        "available": True,
        "reference_scenario": "cash_carry_25bps",
        "total_incremental_ending_equity_usd": total_incremental,
        "attribution_residual_usd": residual,
        "top_ticker": top_ticker.get("ticker"),
        "top_ticker_share_of_net_incremental_pnl": top_ticker_share,
        "top_era": top_era.get("era"),
        "top_era_share_of_net_incremental_pnl": top_era_share,
        "single_ticker_and_era_concentration_pass": concentration_pass,
    }
    return summary, ticker, era


def audit(
    inventory: pd.DataFrame,
    contract: dict[str, Any],
    registry: dict[str, Any],
    sensitivity_root: Path | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates = candidate_rows(inventory, contract, registry)
    core_passes = candidates[candidates["core_growth_gate_pass"]] if not candidates.empty else candidates
    selected = core_passes.iloc[0].to_dict() if not core_passes.empty else None
    sensitivities = sensitivity_rows(sensitivity_root, contract) if sensitivity_root else pd.DataFrame()
    sensitivity_complete = bool(not sensitivities.empty and sensitivities["metrics_present"].all())
    sensitivity_pass = bool(sensitivity_complete and sensitivities["direction_gate_pass"].all())
    any_sensitivity_failure = bool(
        not sensitivities.empty
        and sensitivities["metrics_present"].any()
        and (~sensitivities.loc[sensitivities["metrics_present"], "direction_gate_pass"]).any()
    )
    attribution, ticker_attribution, era_attribution = (
        reference_attribution(sensitivity_root, contract)
        if sensitivity_root else ({"available": False}, pd.DataFrame(), pd.DataFrame())
    )
    if selected is None:
        status = "BLOCKED_NO_GROWTH_FIRST_CANDIDATE"
    elif any_sensitivity_failure:
        status = "REJECT_GROWTH_FIRST_SENSITIVITY"
    elif sensitivity_pass and not attribution.get("available"):
        status = "READY_INCREMENTAL_PNL_ATTRIBUTION"
    elif sensitivity_pass and attribution.get("available") and not attribution.get("single_ticker_and_era_concentration_pass"):
        status = "REJECT_GROWTH_FIRST_CONCENTRATION"
    elif sensitivity_pass:
        status = "PASS_GROWTH_FIRST_RESEARCH_CANDIDATE_PENDING_126D_EMBARGO"
    else:
        status = "READY_TARGETED_SENSITIVITY_ONLY"
    summary = {
        "schema_version": "run287-cagr-first-objective-audit-v1",
        "status": status,
        "objective": "maximize_net_geometric_cagr",
        "max_drawdown_role": "diagnostic_only_not_a_pass_fail_gate",
        "candidate_count": int(len(candidates)),
        "core_growth_gate_pass_count": int(len(core_passes)),
        "selected_arm": selected,
        "sensitivity_complete": sensitivity_complete,
        "sensitivity_pass": sensitivity_pass,
        "incremental_pnl_attribution": attribution,
        "embargo_walk_forward_sessions": 126,
        "embargo_walk_forward_completed": False,
        "backtest_executed_by_audit": False,
        "threshold_tuning_performed": False,
        "new_arm_created": False,
        "fullrun_dispatched": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "target_books_mutated": False,
        "orders_generated": False,
        "pit_universe_label_clean": False,
    }
    return summary, candidates, sensitivities, ticker_attribution, era_attribution


def write_outputs(
    output_dir: Path,
    result: tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame],
    *,
    inputs: dict[str, Path] | None = None,
) -> None:
    summary, candidates, sensitivities, ticker_attribution, era_attribution = result
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    candidates.to_csv(output_dir / "candidate_ranking.csv", index=False)
    sensitivities.to_csv(output_dir / "sensitivity_results.csv", index=False)
    ticker_attribution.to_csv(output_dir / "ticker_incremental_pnl.csv", index=False)
    era_attribution.to_csv(output_dir / "era_incremental_pnl.csv", index=False)
    selected = summary.get("selected_arm") or {}
    report = [
        "# Run287 CAGR-first objective audit",
        "",
        f"- status: `{summary['status']}`",
        f"- core growth gate passes: `{summary['core_growth_gate_pass_count']}`",
        f"- selected arm: `{selected.get('arm', '')}`",
        f"- full dCAGR: `{selected.get('delta_cagr_pp', '')}` pp",
        f"- OOS dCAGR: `{selected.get('delta_oos_cagr_pp', '')}` pp",
        f"- OOS2 dCAGR: `{selected.get('delta_oos2_cagr_pp', '')}` pp",
        f"- MDD delta (diagnostic only): `{selected.get('delta_max_dd_pp_diagnostic', '')}` pp",
        f"- sensitivity complete/pass: `{summary['sensitivity_complete']}` / `{summary['sensitivity_pass']}`",
        f"- concentration pass: `{(summary.get('incremental_pnl_attribution') or {}).get('single_ticker_and_era_concentration_pass')}`",
        f"- 126-session embargo walk-forward complete: `{summary['embargo_walk_forward_completed']}`",
        "- completed arms were re-scored; no new arm, threshold grid, target mutation, order, fullrun, or production action occurred.",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    manifest = {
        "schema_version": "run287-cagr-first-objective-audit-manifest-v1",
        "git_head": git_head(),
        "status": summary["status"],
        "inputs": {name: fingerprint(path) for name, path in (inputs or {}).items()},
        "outputs": {
            name: fingerprint(output_dir / name)
            for name in (
                "summary.json", "candidate_ranking.csv", "sensitivity_results.csv",
                "ticker_incremental_pnl.csv", "era_incremental_pnl.csv", "report.md",
            )
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--contract", default="docs/run287_cagr_first_objective_contract_v1.json")
    parser.add_argument("--registry", default="docs/run287_do_not_repeat_registry.json")
    parser.add_argument("--sensitivity-root")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    inventory_path = repo_path(args.inventory)
    contract_path = repo_path(args.contract)
    registry_path = repo_path(args.registry)
    sensitivity_root = repo_path(args.sensitivity_root) if args.sensitivity_root else None
    inventory = pd.read_csv(inventory_path)
    contract = read_json(contract_path)
    registry = read_json(registry_path)
    result = audit(inventory, contract, registry, sensitivity_root)
    inputs = {"inventory": inventory_path, "contract": contract_path, "registry": registry_path}
    write_outputs(repo_path(args.output_dir), result, inputs=inputs)
    print(json.dumps(result[0], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
