#!/usr/bin/env python3
"""Verify user_current and account preview target contracts agree.

This is a cheap pre-fullrun contract check. It does not evaluate strategy
quality; it only ensures the user-facing target file and account-ledger preview
are describing the same canonical target snapshot.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PORTFOLIOS = ("main", "concentrated")
SNAPSHOT_HASH_COL = "target_snapshot_hash"
SNAPSHOT_SEMANTICS_COL = "target_snapshot_semantics"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def norm_ticker(value: Any) -> str:
    out = str(value or "").strip().upper()
    return "" if out in {"", "NAN", "NONE"} else out


def norm_portfolio(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "concentrated" in text:
        return "concentrated"
    if "main" in text:
        return "main"
    return text


def weight_col(frame: pd.DataFrame) -> str:
    for col in ["target_weight", "weight", "proposed_weight"]:
        if col in frame.columns:
            return col
    return ""


def normalize_target(frame: pd.DataFrame, *, portfolio: str | None = None, tolerance: float = 1e-8) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(columns=["portfolio", "ticker", "target_weight", SNAPSHOT_HASH_COL, SNAPSHOT_SEMANTICS_COL])
    col = weight_col(frame)
    if not col:
        return pd.DataFrame(columns=["portfolio", "ticker", "target_weight", SNAPSHOT_HASH_COL, SNAPSHOT_SEMANTICS_COL])
    out = frame.copy()
    out["ticker"] = out["ticker"].map(norm_ticker)
    out["target_weight"] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if portfolio is None:
        if "portfolio" in out.columns:
            out["portfolio"] = out["portfolio"].map(norm_portfolio)
        elif "portfolio_kind" in out.columns:
            out["portfolio"] = out["portfolio_kind"].map(norm_portfolio)
        else:
            out["portfolio"] = ""
    else:
        out["portfolio"] = portfolio
    for meta_col in [SNAPSHOT_HASH_COL, SNAPSHOT_SEMANTICS_COL]:
        if meta_col not in out.columns:
            out[meta_col] = ""
    out = out[(out["ticker"] != "") & (out["target_weight"] > tolerance)].copy()
    if out.empty:
        return pd.DataFrame(columns=["portfolio", "ticker", "target_weight", SNAPSHOT_HASH_COL, SNAPSHOT_SEMANTICS_COL])
    out = out.groupby(["portfolio", "ticker"], as_index=False).agg(
        {
            "target_weight": "sum",
            SNAPSHOT_HASH_COL: "last",
            SNAPSHOT_SEMANTICS_COL: "last",
        }
    )
    return out


def unique_nonempty(frame: pd.DataFrame, col: str) -> list[str]:
    if frame.empty or col not in frame.columns:
        return []
    return sorted({str(v).strip() for v in frame[col].dropna().astype(str) if str(v).strip()})


def compare_portfolio(
    *,
    portfolio: str,
    user_frame: pd.DataFrame,
    preview_frame: pd.DataFrame,
    tolerance: float,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    user = user_frame[user_frame["portfolio"].eq(portfolio)].copy()
    preview = preview_frame[preview_frame["portfolio"].eq(portfolio)].copy()
    user_tickers = set(user["ticker"].astype(str))
    preview_tickers = set(preview["ticker"].astype(str))
    missing_in_preview = sorted(user_tickers - preview_tickers)
    extra_in_preview = sorted(preview_tickers - user_tickers)
    if missing_in_preview or extra_in_preview:
        issues.append(
            {
                "check_id": f"{portfolio}_target_ticker_mismatch",
                "severity": "error",
                "missing_in_preview": missing_in_preview,
                "extra_in_preview": extra_in_preview,
            }
        )
    merged = user[["ticker", "target_weight"]].merge(
        preview[["ticker", "target_weight"]],
        on="ticker",
        how="inner",
        suffixes=("_user_current", "_preview"),
    )
    weight_mismatches: list[dict[str, Any]] = []
    for row in merged.to_dict("records"):
        lhs = float(row.get("target_weight_user_current") or 0.0)
        rhs = float(row.get("target_weight_preview") or 0.0)
        if not math.isclose(lhs, rhs, rel_tol=0.0, abs_tol=tolerance):
            weight_mismatches.append(
                {
                    "ticker": row.get("ticker"),
                    "user_current_weight": lhs,
                    "preview_weight": rhs,
                    "delta": rhs - lhs,
                }
            )
    if weight_mismatches:
        issues.append(
            {
                "check_id": f"{portfolio}_target_weight_mismatch",
                "severity": "error",
                "examples": weight_mismatches[:20],
                "tolerance": tolerance,
            }
        )
    user_hashes = unique_nonempty(user, SNAPSHOT_HASH_COL)
    preview_hashes = unique_nonempty(preview, SNAPSHOT_HASH_COL)
    if not user_hashes or not preview_hashes or user_hashes != preview_hashes:
        issues.append(
            {
                "check_id": f"{portfolio}_target_snapshot_hash_mismatch",
                "severity": "error",
                "user_current_hashes": user_hashes,
                "preview_hashes": preview_hashes,
            }
        )
    user_semantics = unique_nonempty(user, SNAPSHOT_SEMANTICS_COL)
    preview_semantics = unique_nonempty(preview, SNAPSHOT_SEMANTICS_COL)
    if not user_semantics or not preview_semantics or user_semantics != preview_semantics:
        issues.append(
            {
                "check_id": f"{portfolio}_target_snapshot_semantics_mismatch",
                "severity": "error",
                "user_current_semantics": user_semantics,
                "preview_semantics": preview_semantics,
            }
        )
    return {
        "portfolio": portfolio,
        "user_target_count": int(len(user)),
        "preview_target_count": int(len(preview)),
        "user_target_weight_sum": float(user["target_weight"].sum()) if not user.empty else 0.0,
        "preview_target_weight_sum": float(preview["target_weight"].sum()) if not preview.empty else 0.0,
        "issues": issues,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    user_path = repo_path(args.user_current_target) if args.user_current_target else latest_run / "user_current" / "02_target_weights.csv"
    user_targets = normalize_target(read_csv(user_path), tolerance=args.weight_tolerance)
    preview_frames: list[pd.DataFrame] = []
    for portfolio in PORTFOLIOS:
        path = latest_run / "account_ledger_preview" / portfolio / "target_weights.csv"
        preview_frames.append(normalize_target(read_csv(path), portfolio=portfolio, tolerance=args.weight_tolerance))
    preview_targets = pd.concat(preview_frames, ignore_index=True) if preview_frames else pd.DataFrame()
    portfolio_results = [
        compare_portfolio(
            portfolio=portfolio,
            user_frame=user_targets,
            preview_frame=preview_targets,
            tolerance=args.weight_tolerance,
        )
        for portfolio in PORTFOLIOS
    ]
    issues = [issue for result in portfolio_results for issue in result["issues"]]
    payload = {
        "status": "pass" if not issues else "blocked",
        "schema_version": "user-current-preview-contract-v1",
        "latest_run": str(latest_run),
        "user_current_target": str(user_path),
        "output_dir": str(output_dir),
        "weight_tolerance": float(args.weight_tolerance),
        "portfolio_results": portfolio_results,
        "issues": issues,
        "error_count": int(sum(1 for issue in issues if issue.get("severity") == "error")),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_activation_allowed": False,
    }
    write_json(output_dir / "summary.json", payload)
    lines = ["# User Current / Preview Contract", ""]
    lines.append(f"- Status: `{payload['status']}`")
    lines.append(f"- Error count: {payload['error_count']}")
    lines.append("")
    lines.append("| Portfolio | User targets | Preview targets | User sum | Preview sum |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for result in portfolio_results:
        lines.append(
            f"| {result['portfolio']} | {result['user_target_count']} | {result['preview_target_count']} | "
            f"{result['user_target_weight_sum']:.6f} | {result['preview_target_weight_sum']:.6f} |"
        )
    if issues:
        lines.append("")
        lines.append("## Issues")
        for issue in issues:
            lines.append(f"- `{issue.get('check_id')}`: {json.dumps(issue, sort_keys=True, default=str)}")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--user-current-target", default="")
    parser.add_argument("--output-dir", default="outputs/user_current_preview_contract")
    parser.add_argument("--weight-tolerance", type=float, default=1e-6)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(args)
    print(json.dumps({"status": payload["status"], "error_count": payload["error_count"]}, indent=2))
    return 2 if args.strict and payload.get("status") != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
