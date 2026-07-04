#!/usr/bin/env python3
"""Research-only M2 RS horizon IC audit."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.research_audit_utils import first_existing, read_csv, repo_path, spearman, write_json  # noqa: E402

DEFAULT_OUTPUT_DIR = "outputs/rs_horizon_ic_audit"
RS_FEATURES = [
    "rs_spy_1w",
    "rs_spy_1m",
    "rs_spy_3m",
    "rs_spy_6m",
    "rs_spy_12m",
    "rs_qqq_1m",
    "rs_qqq_3m",
    "rs_qqq_6m",
    "rs_industry_3m",
    "rs_sector_3m",
    "rs_theme_3m",
    "ai_bucket_rs_3m",
]
FORWARD_LABELS = ["forward_63d_excess", "forward_126d_excess", "period_forward_return"]
ROW_TYPE_COLUMNS = ["decision_row_type", "row_type", "candidate_context", "event_type", "source_event_type"]


def load_inputs(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        frame = read_csv(path)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["source_file"] = str(path)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def attach_row_type(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    row_type_col = first_existing(out, ROW_TYPE_COLUMNS)
    if row_type_col:
        out["_row_type"] = out[row_type_col].astype(str).str.strip().str.lower().replace({"": "unknown"})
    else:
        out["_row_type"] = "unknown"
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = [repo_path(path) for path in args.inputs]
    frame = load_inputs(inputs)
    label_col = first_existing(frame, FORWARD_LABELS)
    rows: list[dict[str, Any]] = []
    by_portfolio: list[dict[str, Any]] = []
    if not frame.empty and label_col:
        frame = attach_row_type(frame)
        if "portfolio" not in frame.columns:
            frame["portfolio"] = frame["portfolio_kind"] if "portfolio_kind" in frame.columns else "unknown"
        for feature in RS_FEATURES:
            if feature not in frame.columns:
                rows.append({"horizon": feature, "status": "missing_feature", "sample_count": 0, "ic": None})
                continue
            d = frame[[feature, label_col]].dropna()
            rows.append(
                {
                    "horizon": feature,
                    "status": "completed" if len(d) >= int(args.min_samples) else "insufficient_sample",
                    "sample_count": int(len(d)),
                    "ic": spearman(d[feature], d[label_col]),
                    "forward_label": label_col,
                    "forward_return_is_audit_label_only": True,
                }
            )
            for portfolio, group in frame.groupby("portfolio", dropna=False):
                g = group[[feature, label_col]].dropna()
                by_portfolio.append(
                    {
                        "portfolio": portfolio,
                        "horizon": feature,
                        "status": "completed" if len(g) >= int(args.min_samples) else "insufficient_sample",
                        "sample_count": int(len(g)),
                        "ic": spearman(g[feature], g[label_col]),
                        "forward_label": label_col,
                    }
                )
            for row_type, group in frame.groupby("_row_type", dropna=False):
                g = group[[feature, label_col]].dropna()
                by_portfolio.append(
                    {
                        "portfolio": f"row_type:{row_type}",
                        "horizon": feature,
                        "status": "completed" if len(g) >= int(args.min_samples) else "insufficient_sample",
                        "sample_count": int(len(g)),
                        "ic": spearman(g[feature], g[label_col]),
                        "forward_label": label_col,
                    }
                )
    horizon_df = pd.DataFrame(rows)
    portfolio_df = pd.DataFrame(by_portfolio)
    horizon_df.to_csv(output_dir / "ic_by_horizon.csv", index=False)
    portfolio_df.to_csv(output_dir / "ic_by_portfolio.csv", index=False)
    row_type_df = portfolio_df[portfolio_df["portfolio"].astype(str).str.startswith("row_type:")].copy() if not portfolio_df.empty else pd.DataFrame()
    row_type_df.to_csv(output_dir / "ic_by_row_type.csv", index=False)
    completed = horizon_df[horizon_df.get("status", pd.Series(dtype=str)).eq("completed")] if not horizon_df.empty else pd.DataFrame()
    short_bad = bool(
        not completed.empty
        and any(
            completed.loc[completed["horizon"].eq(h), "ic"].dropna().le(0).any()
            for h in ["rs_spy_1w", "rs_spy_1m"]
        )
    )
    payload = {
        "schema_version": "rs-horizon-ic-audit-v1",
        "status": "completed" if rows else "blocked",
        "reason": "" if rows else "missing_rs_features_or_forward_labels",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": [str(path) for path in inputs],
        "forward_label": label_col,
        "entry_side_short_horizon_demote_backlog": short_bad,
        "forward_return_is_audit_label_only": True,
        "forward_labels_used_for_ranking": False,
        "research_only": True,
        "production_activation_allowed": False,
        "policy_hook_allowed": False,
        "canonical_input_rule": "fixed_official_rows_preferred_until_w1_control_reproduction_passes",
        "regenerated_target_book_acceptance_allowed": False,
        "row_type_splits_supported": True,
    }
    write_json(output_dir / "summary.json", payload)
    lines = [
        "# RS Horizon IC Audit",
        "",
        f"- status: `{payload['status']}`",
        f"- forward label: `{label_col}`",
        f"- short-horizon demote backlog: `{str(short_bad).lower()}`",
        "- policy hook allowed: `false`",
        "",
        "| horizon | n | IC | status |",
        "|---|---:|---:|---|",
    ]
    for row in rows:
        lines.append(f"| {row.get('horizon')} | {row.get('sample_count')} | {row.get('ic')} | {row.get('status')} |")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-samples", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
