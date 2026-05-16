#!/usr/bin/env python3
"""Refresh account-like reports after the market close.

This wrapper is intentionally a connector, not a new strategy. It takes the
latest full-rebuild artifacts plus a refreshed price cache, then regenerates
the broker-ledger/account-report path that users actually inspect:

1. operating target books
2. broker-ledger replay for main and concentrated
3. order previews
4. safety/risk-control reports
5. operating snapshot, user reports, and account evaluation

It does not update model weights, promote AutoLearning proposals, or place
orders. Existing full-run artifacts remain untouched unless the caller points
``--output-dir`` at the same directory.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def copy_file_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def copy_tree_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists() or not src.is_dir():
        return False
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return True


def latest_observable_date(frame: pd.DataFrame) -> str:
    dates: list[pd.Timestamp] = []
    for col in ["feature_date", "as_of_date", "rebalance_date", "last_trade_date"]:
        if col not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[col], errors="coerce").dropna()
        if not parsed.empty:
            dates.append(pd.Timestamp(parsed.max()).normalize())
    return max(dates).date().isoformat() if dates else ""


def enrich_target_dates(output_dir: Path) -> dict[str, Any]:
    """Attach an observable signal date to latest target files when missing.

    Some user-facing target files intentionally omit ``feature_date`` even
    though their source ``scored_latest.csv`` is dated. Operating target books
    require an observable date; otherwise the broker-ledger path can stay stuck
    at the last monthly history row. This enrichment uses the max source
    ``scored_latest`` feature/as-of/rebalance date, never a future scheduling
    hint such as ``recommended_next_run_date``.
    """
    scored_path = output_dir / "scored_latest.csv"
    if not scored_path.exists():
        return {"status": "skipped", "reason": "scored_latest.csv missing"}
    try:
        scored = pd.read_csv(scored_path, low_memory=False)
    except Exception as exc:
        return {"status": "skipped", "reason": f"could not read scored_latest.csv: {exc}"}
    signal_date = latest_observable_date(scored)
    if not signal_date:
        return {"status": "skipped", "reason": "no observable date in scored_latest.csv"}
    touched: list[str] = []
    for name in ["portfolio_latest.csv", "concentrated_portfolio_latest.csv"]:
        path = output_dir / name
        if not path.exists():
            continue
        try:
            target = pd.read_csv(path, low_memory=False)
        except Exception:
            continue
        target_signal_date = latest_observable_date(target)
        if target_signal_date:
            continue
        target["feature_date"] = signal_date
        target["as_of_date"] = signal_date
        target.to_csv(path, index=False)
        touched.append(name)
    return {"status": "completed", "source_signal_date": signal_date, "touched": touched}


def run_step(name: str, cmd: list[str], *, required: bool = True) -> dict[str, Any]:
    print(f"[after_close_refresh] >>> {name}", flush=True)
    print("[after_close_refresh] " + " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=REPO_ROOT)
    return {"name": name, "returncode": int(proc.returncode), "required": bool(required)}


def staged_latest_run(source: Path, output_dir: Path) -> dict[str, Any]:
    copied: list[str] = []
    for name in [
        "portfolio_latest.csv",
        "concentrated_portfolio_latest.csv",
        "scored_latest.csv",
        "backtest_metrics.json",
        "concentrated_backtest_metrics.json",
    ]:
        if copy_file_if_exists(source / name, output_dir / name):
            copied.append(name)
    for name in [
        "orchestrator",
        "macro_policy_engine",
        "cash_policy_reconciliation",
        "leader_drop_diagnostics",
        "selection_quality",
        "portfolio_goal_search",
        "reports",
    ]:
        if copy_tree_if_exists(source / name, output_dir / name):
            copied.append(f"{name}/")
    return {"copied": copied, "source": str(source), "staged_root": str(output_dir)}


def latest_report_dates(output_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for portfolio in ["main", "concentrated"]:
        metrics = read_json(output_dir / "broker_replay" / portfolio / "metrics.json")
        state = read_json(output_dir / "broker_replay" / portfolio / "account_state_latest.json")
        out[portfolio] = {
            "broker_replay_end_date": metrics.get("end_date") or metrics.get("as_of_date"),
            "account_state_as_of_date": state.get("as_of_date"),
            "cagr": metrics.get("cagr") or metrics.get("strategy_cagr"),
            "max_drawdown": metrics.get("max_drawdown") or metrics.get("strategy_max_drawdown"),
            "sharpe": metrics.get("sharpe") or metrics.get("strategy_sharpe"),
        }
    user_summary = read_json(output_dir / "user_portfolio_reports" / "summary.json")
    if user_summary:
        out["user_portfolio_reports"] = {
            "status": user_summary.get("status"),
            "as_of_date": user_summary.get("as_of_date"),
        }
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not latest_run.exists():
        raise FileNotFoundError(f"latest_run does not exist: {latest_run}")
    if not price_cache.exists():
        raise FileNotFoundError(f"price_cache does not exist: {price_cache}")

    steps: list[dict[str, Any]] = []
    staged = staged_latest_run(latest_run, output_dir)
    target_date_enrichment = enrich_target_dates(output_dir)

    def finish(status: str) -> dict[str, Any]:
        required_failures = [s for s in steps if s["required"] and s["returncode"] != 0]
        optional_failures = [s for s in steps if not s["required"] and s["returncode"] != 0]
        payload = {
            "status": status,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_latest_run": str(latest_run),
            "price_cache": str(price_cache),
            "output_dir": str(output_dir),
            "official_metric_mode": f"broker_ledger_{args.fill_mode}",
            "staged": staged,
            "target_date_enrichment": target_date_enrichment,
            "steps": steps,
            "required_failure_count": len(required_failures),
            "optional_failure_count": len(optional_failures),
            "dates": latest_report_dates(output_dir),
        }
        write_json(output_dir / "after_close_account_refresh_manifest.json", payload)
        return payload

    py = sys.executable
    build_cmd = [
        py,
        "tools/build_operating_target_books.py",
        "--latest-run",
        str(output_dir),
        "--price-cache",
        str(price_cache),
        "--output-dir",
        str(output_dir / "reports"),
        "--require-current-latest-target",
    ]
    if args.apply_regime_capacity_filter:
        build_cmd.extend(
            [
                "--apply-regime-capacity-filter",
                "--main-multipliers",
                args.main_multipliers,
                "--concentrated-multipliers",
                args.concentrated_multipliers,
            ]
        )
    build_result = run_step("build operating target books", build_cmd, required=not args.allow_stale_target_book)
    steps.append(build_result)
    if build_result["required"] and build_result["returncode"] != 0:
        return finish("failed")

    for portfolio in ["main", "concentrated"]:
        target_book = output_dir / "reports" / f"operating_{portfolio}_target_book.csv"
        replay_result = run_step(
            f"broker ledger replay {portfolio}",
            [
                py,
                "tools/run_broker_ledger_replay.py",
                "--target-book",
                str(target_book),
                "--price-cache",
                str(price_cache),
                "--portfolio-kind",
                portfolio,
                "--output-dir",
                str(output_dir / "broker_replay" / portfolio),
                "--fill-mode",
                args.fill_mode,
                "--cost-bps",
                str(args.cost_bps),
                "--max-fill-lag-days",
                str(args.max_fill_lag_days),
            ],
        )
        steps.append(replay_result)
        if replay_result["returncode"] != 0:
            return finish("failed")

    target_files = {
        "main": output_dir / "portfolio_latest.csv",
        "concentrated": output_dir / "concentrated_portfolio_latest.csv",
    }
    for portfolio, target in target_files.items():
        steps.append(
            run_step(
                f"account order preview {portfolio}",
                [
                    py,
                    "tools/run_account_order_preview.py",
                    "--account-state",
                    str(output_dir / "broker_replay" / portfolio / "account_state_latest.json"),
                    "--target",
                    str(target),
                    "--price-cache",
                    str(price_cache),
                    "--portfolio-kind",
                    portfolio,
                    "--output-dir",
                    str(output_dir / "account_ledger_preview" / portfolio),
                    "--cost-bps",
                    str(args.cost_bps),
                ],
                required=False,
            )
        )

    steps.extend(
        [
            run_step(
                "live trading safety audit",
                [
                    py,
                    "tools/run_live_trading_safety_audit.py",
                    "--latest-run",
                    str(output_dir),
                    "--output-dir",
                    str(output_dir / "live_trading_safety"),
                ],
                required=False,
            ),
            run_step(
                "live trading risk controls",
                [
                    py,
                    "tools/run_live_trading_risk_controls.py",
                    "--latest-run",
                    str(output_dir),
                    "--price-cache",
                    str(price_cache),
                    "--output-dir",
                    str(output_dir / "live_trading_risk_controls"),
                ],
                required=False,
            ),
            run_step(
                "operating snapshot",
                [
                    py,
                    "tools/run_operating_snapshot.py",
                    "--latest-run",
                    str(output_dir),
                    "--output-dir",
                    str(output_dir / "operating_snapshot"),
                ],
                required=False,
            ),
            run_step(
                "user portfolio reports",
                [
                    py,
                    "tools/run_user_portfolio_reports.py",
                    "--latest-run",
                    str(output_dir),
                    "--price-cache",
                    str(price_cache),
                    "--output-dir",
                    str(output_dir / "user_portfolio_reports"),
                ],
                required=False,
            ),
            run_step(
                "account evaluation",
                [
                    py,
                    "tools/run_account_evaluation.py",
                    "--latest-run",
                    str(output_dir),
                    "--output-dir",
                    str(output_dir / "account_evaluation"),
                ],
                required=False,
            ),
        ]
    )

    return finish("completed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="cloud_results/full_rebuild/latest_global_alpha_universe")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/after_close_account_refresh")
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--allow-stale-target-book", action="store_true")
    parser.add_argument("--apply-regime-capacity-filter", action="store_true")
    parser.add_argument("--main-multipliers", default="bear=0.5,deep_bear=0.25")
    parser.add_argument("--concentrated-multipliers", default="bear=0.5,deep_bear=0.25,neutral=0.85")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload["status"], "dates": payload.get("dates", {})}, indent=2, sort_keys=True))
    return 0 if payload["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
