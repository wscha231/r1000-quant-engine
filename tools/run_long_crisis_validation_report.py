#!/usr/bin/env python3
"""Render stress-window validation for the selected long crisis thresholds."""
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


DEFAULT_FEATURES = "data_pit/macro/long_crisis_daily_features.parquet"
DEFAULT_THRESHOLDS = "outputs/long_crisis_learning/best_thresholds.json"
DEFAULT_OUTPUT_DIR = "outputs/long_crisis_learning"

STRESS_WINDOWS = {
    "dotcom_2000_2002": ("2000-03-01", "2002-10-31"),
    "gfc_2008": ("2007-10-01", "2009-03-31"),
    "covid_2020": ("2020-02-01", "2020-05-31"),
    "rate_shock_2022": ("2021-11-01", "2022-12-31"),
    "recent_2024_2026": ("2024-01-01", "2026-12-31"),
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_features(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    else:
        frame = pd.read_csv(path, low_memory=False)
    if "date" in frame.columns:
        frame.index = pd.to_datetime(frame.pop("date"), errors="coerce")
    else:
        frame.index = pd.to_datetime(frame.index, errors="coerce")
    return frame[~frame.index.isna()].sort_index()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def window_metrics(features: pd.DataFrame, name: str, start: str, end: str, thresholds: dict[str, Any]) -> dict[str, Any]:
    d = features.loc[(features.index >= pd.Timestamp(start)) & (features.index <= pd.Timestamp(end))].copy()
    if d.empty:
        return {"window": name, "status": "no_rows", "rows": 0}
    crisis_gate = float(thresholds.get("crisis_gate", 0.55))
    liquidity_gate = float(thresholds.get("liquidity_gate", 0.35))
    trend_gate = float(thresholds.get("trend_gate", 0.35))
    signal = (
        pd.to_numeric(d.get("crisis_score"), errors="coerce").fillna(0.0).ge(crisis_gate)
        & pd.to_numeric(d.get("liquidity_confirmation_score"), errors="coerce").fillna(0.0).ge(liquidity_gate)
        & pd.to_numeric(d.get("market_trend_damage_score"), errors="coerce").fillna(0.0).ge(trend_gate)
    )
    label = pd.to_numeric(d.get("future_63d_drawdown_le_15pct"), errors="coerce").fillna(0).astype(int).eq(1)
    max_future_dd = float(pd.to_numeric(d.get("future_63d_drawdown"), errors="coerce").min())
    return {
        "window": name,
        "status": "ok",
        "rows": int(len(d)),
        "signal_days": int(signal.sum()),
        "signal_rate": float(signal.mean()),
        "drawdown_label_days": int(label.sum()),
        "recall": float((signal & label).sum() / max(label.sum(), 1)),
        "false_signal_days": int((signal & ~label).sum()),
        "max_future_63d_drawdown": max_future_dd,
    }


def render_report(summary: dict[str, Any], windows: pd.DataFrame) -> str:
    def int0(value: Any) -> int:
        try:
            return int(value) if pd.notna(value) else 0
        except (TypeError, ValueError):
            return 0

    def float0(value: Any) -> float:
        try:
            return float(value) if pd.notna(value) else 0.0
        except (TypeError, ValueError):
            return 0.0

    lines = [
        "# Long Crisis Validation Report",
        "",
        f"- status: `{summary.get('status')}`",
        f"- thresholds: `{summary.get('thresholds_path')}`",
        "",
        "## Stress Windows",
        "",
        "| window | signal days | signal rate | drawdown label days | recall | max future 63d DD |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    if not windows.empty:
        for _, row in windows.iterrows():
            lines.append(
                f"| {row['window']} | {int0(row.get('signal_days', 0))} | "
                f"{float0(row.get('signal_rate', 0.0)):.3f} | {int0(row.get('drawdown_label_days', 0))} | "
                f"{float0(row.get('recall', 0.0)):.3f} | {float0(row.get('max_future_63d_drawdown', 0.0)):.2%} |"
            )
    lines.extend(
        [
            "",
            "This report validates crisis threshold candidates only. Promotion still requires Phase G broker-ledger replay.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    features_path = repo_path(args.features)
    thresholds_path = repo_path(args.thresholds)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    features = read_features(features_path)
    thresholds = read_json(thresholds_path)
    if features.empty or not thresholds:
        summary = {
            "status": "blocked",
            "reason": "missing features or selected thresholds",
            "features": str(features_path),
            "thresholds_path": str(thresholds_path),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "validation_summary.json", summary)
        (output_dir / "validation_report.md").write_text(render_report(summary, pd.DataFrame()), encoding="utf-8")
        print(json.dumps({"status": "blocked", "reason": summary["reason"]}, sort_keys=True))
        return summary

    rows = [window_metrics(features, name, start, end, thresholds) for name, (start, end) in STRESS_WINDOWS.items()]
    windows = pd.DataFrame(rows)
    windows_path = output_dir / "stress_window_report.csv"
    windows.to_csv(windows_path, index=False)
    summary = {
        "status": "completed",
        "schema_version": "long-crisis-validation-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "features": str(features_path),
        "thresholds_path": str(thresholds_path),
        "stress_window_report": str(windows_path),
        "selected": thresholds,
    }
    write_json(output_dir / "validation_summary.json", summary)
    (output_dir / "validation_report.md").write_text(render_report(summary, windows), encoding="utf-8")
    print(json.dumps({"status": "completed", "windows": int(len(windows))}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", default=DEFAULT_FEATURES)
    parser.add_argument("--thresholds", default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
