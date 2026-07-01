#!/usr/bin/env python3
"""Audit whether a regenerated target book reproduces an official artifact book."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_book(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "rebalance_date" not in df.columns or "ticker" not in df.columns:
        raise ValueError(f"{path} must contain rebalance_date and ticker")
    weight_col = "weight" if "weight" in df.columns else "target_weight"
    if weight_col not in df.columns:
        raise ValueError(f"{path} must contain weight or target_weight")
    out = pd.DataFrame(
        {
            "rebalance_date": pd.to_datetime(df["rebalance_date"], errors="coerce").dt.date.astype(str),
            "ticker": df["ticker"].astype(str).str.upper().str.strip(),
            "weight": pd.to_numeric(df[weight_col], errors="coerce").fillna(0.0),
        }
    )
    out = out.dropna(subset=["rebalance_date"])
    out = out[out["ticker"].ne("") & out["ticker"].ne("NAN")]
    return (
        out.groupby(["rebalance_date", "ticker"], as_index=False)["weight"]
        .sum()
        .sort_values(["rebalance_date", "ticker"])
        .reset_index(drop=True)
    )


def env_snapshot(keys: list[str]) -> dict[str, str]:
    return {key: os.environ.get(key, "") for key in keys}


def run(args: argparse.Namespace) -> dict[str, Any]:
    official_book = repo_path(args.official_book)
    generated_book = repo_path(args.generated_book)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    official = normalize_book(official_book)
    generated = normalize_book(generated_book)
    official_dates = set(official["rebalance_date"].astype(str))
    generated_dates = set(generated["rebalance_date"].astype(str))
    date_rows = []
    for dt in sorted(official_dates | generated_dates):
        official_day = official[official["rebalance_date"].eq(dt)]
        generated_day = generated[generated["rebalance_date"].eq(dt)]
        official_tickers = set(official_day["ticker"].astype(str))
        generated_tickers = set(generated_day["ticker"].astype(str))
        date_rows.append(
            {
                "rebalance_date": dt,
                "date_in_official": bool(dt in official_dates),
                "date_in_generated": bool(dt in generated_dates),
                "official_ticker_count": int(len(official_tickers)),
                "generated_ticker_count": int(len(generated_tickers)),
                "missing_tickers": ",".join(sorted(official_tickers - generated_tickers)),
                "extra_tickers": ",".join(sorted(generated_tickers - official_tickers)),
                "ticker_set_equal": bool(official_tickers == generated_tickers),
            }
        )
    date_diff = pd.DataFrame(date_rows)

    merged = official.merge(
        generated,
        on=["rebalance_date", "ticker"],
        how="outer",
        suffixes=("_official", "_generated"),
    )
    merged["weight_official"] = pd.to_numeric(merged["weight_official"], errors="coerce").fillna(0.0)
    merged["weight_generated"] = pd.to_numeric(merged["weight_generated"], errors="coerce").fillna(0.0)
    merged["weight_delta"] = merged["weight_generated"] - merged["weight_official"]
    merged["abs_weight_delta"] = merged["weight_delta"].abs()
    merged = merged.sort_values(["rebalance_date", "abs_weight_delta"], ascending=[True, False]).reset_index(drop=True)

    date_diff.to_csv(output_dir / "date_ticker_diff.csv", index=False)
    merged.to_csv(output_dir / "weight_delta.csv", index=False)

    max_abs_delta = float(merged["abs_weight_delta"].max()) if not merged.empty else 0.0
    total_abs_delta = float(merged["abs_weight_delta"].sum()) if not merged.empty else 0.0
    mismatch_dates = int((~date_diff["ticker_set_equal"]).sum()) if not date_diff.empty else 0
    official_only_dates = sorted(official_dates - generated_dates)
    generated_only_dates = sorted(generated_dates - official_dates)
    exact_match = bool(
        not official_only_dates
        and not generated_only_dates
        and mismatch_dates == 0
        and max_abs_delta <= float(args.weight_tolerance)
    )
    near_match = bool(
        not official_only_dates
        and not generated_only_dates
        and mismatch_dates <= int(args.max_ticker_mismatch_dates)
        and max_abs_delta <= float(args.near_weight_tolerance)
    )

    payload = {
        "status": "completed",
        "schema_version": "target-book-control-repro-audit-v1",
        "official_book": str(official_book),
        "generated_book": str(generated_book),
        "official_book_sha256": file_sha256(official_book),
        "generated_book_sha256": file_sha256(generated_book),
        "portfolio_kind": args.portfolio_kind,
        "candidate_book": args.candidate_book,
        "price_cache": args.price_cache,
        "code_commit": args.code_commit,
        "env": env_snapshot([key.strip() for key in args.env_keys.split(",") if key.strip()]),
        "official_date_count": int(len(official_dates)),
        "generated_date_count": int(len(generated_dates)),
        "official_only_date_count": int(len(official_only_dates)),
        "generated_only_date_count": int(len(generated_only_dates)),
        "official_only_dates": official_only_dates[:20],
        "generated_only_dates": generated_only_dates[:20],
        "ticker_mismatch_date_count": mismatch_dates,
        "max_abs_weight_delta": max_abs_delta,
        "total_abs_weight_delta": total_abs_delta,
        "exact_control_reproduced": exact_match,
        "near_control_reproduced": near_match,
        "weight_tolerance": float(args.weight_tolerance),
        "near_weight_tolerance": float(args.near_weight_tolerance),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_activation_allowed": False,
        "research_only": True,
    }
    write_json(output_dir / "summary.json", payload)
    lines = ["# Target Book Control Reproduction Audit", ""]
    lines.append(f"- Exact control reproduced: `{payload['exact_control_reproduced']}`")
    lines.append(f"- Near control reproduced: `{payload['near_control_reproduced']}`")
    lines.append(f"- Official dates: `{payload['official_date_count']}`")
    lines.append(f"- Generated dates: `{payload['generated_date_count']}`")
    lines.append(f"- Official-only dates: `{payload['official_only_date_count']}`")
    lines.append(f"- Generated-only dates: `{payload['generated_only_date_count']}`")
    lines.append(f"- Ticker mismatch dates: `{payload['ticker_mismatch_date_count']}`")
    lines.append(f"- Max abs weight delta: `{payload['max_abs_weight_delta']}`")
    lines.append("")
    lines.append("Artifacts:")
    lines.append("")
    lines.append("- `date_ticker_diff.csv`")
    lines.append("- `weight_delta.csv`")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-book", required=True)
    parser.add_argument("--generated-book", required=True)
    parser.add_argument("--output-dir", default="outputs/target_book_control_repro_audit")
    parser.add_argument("--portfolio-kind", default="")
    parser.add_argument("--candidate-book", default="")
    parser.add_argument("--price-cache", default="")
    parser.add_argument("--code-commit", default="")
    parser.add_argument(
        "--env-keys",
        default=(
            "PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED,"
            "PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED,"
            "PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED,"
            "PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED,"
            "R1000_CONC_GROSS_CAP_FLOOR"
        ),
    )
    parser.add_argument("--weight-tolerance", type=float, default=1e-9)
    parser.add_argument("--near-weight-tolerance", type=float, default=1e-4)
    parser.add_argument("--max-ticker-mismatch-dates", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
