#!/usr/bin/env python3
"""Learn post-disclosure event patterns from labeled SEC/ETF events.

This D2/D3 tool is research-only. It summarizes whether 13F, Form 4, and ETF
holding events were followed by positive/excess returns and builds PIT-style
manager alpha scores using only labels whose target dates are known before the
manager score `as_of_date`.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_LABELS = "data_pit/sec/post_disclosure_alpha_labels.parquet"
DEFAULT_OUTPUT_DIR = "outputs/post_disclosure_signal_learning"
DEFAULT_MANAGER_OUTPUT = "data_pit/sec/manager_disclosure_alpha_scores.parquet"
DEFAULT_HORIZONS = "21,63,126"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def parse_horizons(text: str) -> list[int]:
    out: list[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return sorted(set(x for x in out if x > 0))


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def text_column(frame: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=object)
    return frame[col].fillna(default).astype(str)


def safe_mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if len(values) else math.nan


def safe_hit(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float((values > 0.0).mean()) if len(values) else math.nan


def prepare_labels(labels: pd.DataFrame) -> pd.DataFrame:
    if labels.empty or "ticker" not in labels.columns:
        return pd.DataFrame()
    d = labels.copy()
    d["ticker"] = text_column(d, "ticker").str.upper().str.strip()
    d["source_type"] = text_column(d, "source_type")
    d["event_type"] = text_column(d, "event_type")
    d["manager_cik"] = text_column(d, "manager_cik")
    d["manager_name"] = text_column(d, "manager_name")
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True).dt.tz_convert(None)
    d["event_seed_score"] = numeric(d, "event_seed_score", 0.0).clip(-1.0, 1.0)
    d = d[d["ticker"].ne("") & d["available_from_ts"].notna()].copy()
    return d.sort_values(["available_from_ts", "source_type", "ticker"]).reset_index(drop=True)


def horizon_return_col(frame: pd.DataFrame, horizon: int) -> str:
    col = f"excess_spy_{int(horizon)}d"
    if col in frame.columns:
        return col
    return f"ret_{int(horizon)}d"


def target_date_col(frame: pd.DataFrame, horizon: int) -> str:
    col = f"target_date_{int(horizon)}d"
    return col if col in frame.columns else ""


def bucket_stats(frame: pd.DataFrame, group_cols: list[str], horizons: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame()
    for keys, group in frame.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {col: value for col, value in zip(group_cols, keys)}
        row["rows"] = int(len(group))
        row["avg_event_seed_score"] = safe_mean(group["event_seed_score"])
        for horizon in horizons:
            ret_col = f"ret_{horizon}d"
            excess_col = f"excess_spy_{horizon}d" if f"excess_spy_{horizon}d" in group.columns else ret_col
            row[f"avg_return_{horizon}d"] = safe_mean(group.get(ret_col, pd.Series(dtype=float)))
            row[f"avg_excess_{horizon}d"] = safe_mean(group.get(excess_col, pd.Series(dtype=float)))
            row[f"hit_rate_{horizon}d"] = safe_hit(group.get(ret_col, pd.Series(dtype=float)))
            row[f"excess_hit_rate_{horizon}d"] = safe_hit(group.get(excess_col, pd.Series(dtype=float)))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["rows"], ascending=False)


def signal_ic(frame: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame(columns=["horizon", "scope", "rows", "spearman_ic"])
    scopes: list[tuple[str, pd.DataFrame]] = [("all", frame)]
    for source, group in frame.groupby("source_type"):
        scopes.append((f"source:{source}", group))
    for horizon in horizons:
        ret_col = horizon_return_col(frame, horizon)
        for scope, group in scopes:
            if ret_col not in group.columns:
                rows.append({"horizon": int(horizon), "scope": scope, "rows": 0, "spearman_ic": math.nan})
                continue
            valid = group[["event_seed_score", ret_col]].replace([np.inf, -np.inf], np.nan).dropna()
            ic = math.nan
            if len(valid) >= 3 and valid["event_seed_score"].nunique() > 1:
                ic = float(valid["event_seed_score"].corr(valid[ret_col], method="spearman"))
            rows.append({"horizon": int(horizon), "scope": scope, "rows": int(len(valid)), "spearman_ic": ic})
    return pd.DataFrame(rows)


def follow_vs_fade(frame: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame()
    d = frame.copy()
    d["action"] = "neutral"
    d.loc[d["event_seed_score"] > 0.05, "action"] = "follow"
    d.loc[d["event_seed_score"] < -0.05, "action"] = "fade_or_avoid"
    for horizon in horizons:
        ret_col = horizon_return_col(d, horizon)
        for (source, action), group in d.groupby(["source_type", "action"], dropna=False):
            values = pd.to_numeric(group[ret_col], errors="coerce").dropna() if ret_col in group.columns else pd.Series(dtype=float)
            rows.append(
                {
                    "source_type": source,
                    "action": action,
                    "horizon": int(horizon),
                    "rows": int(len(values)),
                    "avg_return_or_excess": float(values.mean()) if len(values) else math.nan,
                    "hit_rate": float((values > 0.0).mean()) if len(values) else math.nan,
                    "worst_return": float(values.min()) if len(values) else math.nan,
                    "best_return": float(values.max()) if len(values) else math.nan,
                }
            )
    return pd.DataFrame(rows)


def manager_alpha_scores(frame: pd.DataFrame, *, horizon: int) -> pd.DataFrame:
    if frame.empty or "manager_cik" not in frame.columns:
        return pd.DataFrame()
    ret_col = horizon_return_col(frame, horizon)
    target_col = target_date_col(frame, horizon)
    d = frame[frame["manager_cik"].astype(str).str.strip().ne("")].copy()
    if d.empty:
        return pd.DataFrame()
    if ret_col not in d.columns:
        return pd.DataFrame()
    d["target_ts"] = pd.to_datetime(d[target_col], errors="coerce") if target_col else pd.NaT
    rows: list[dict[str, Any]] = []
    for manager_cik, group in d.groupby("manager_cik", sort=True):
        group = group.sort_values("available_from_ts").copy()
        manager_name = str(group["manager_name"].dropna().astype(str).replace("", pd.NA).dropna().iloc[-1]) if group["manager_name"].astype(str).str.strip().ne("").any() else ""
        for as_of in sorted(group["available_from_ts"].dropna().unique()):
            as_of_ts = pd.Timestamp(as_of)
            prior = group[group["target_ts"].notna() & (group["target_ts"] < as_of_ts)].copy()
            if prior.empty and target_col == "":
                prior = group[group["available_from_ts"] < as_of_ts].copy()
            values = pd.to_numeric(prior[ret_col], errors="coerce").dropna() if ret_col in prior.columns else pd.Series(dtype=float)
            sample = int(len(values))
            avg = float(values.mean()) if sample else 0.0
            hit = float((values > 0.0).mean()) if sample else 0.0
            confidence = min(sample / 20.0, 1.0)
            recent = float(values.tail(5).mean()) if sample else 0.0
            rows.append(
                {
                    "manager_cik": manager_cik,
                    "manager_name": manager_name,
                    "as_of_date": as_of_ts.date().isoformat(),
                    "horizon": int(horizon),
                    "sample_count": sample,
                    "avg_excess_return": avg,
                    "hit_rate": hit,
                    "recent_alpha": recent,
                    "manager_disclosure_alpha_score": max(0.0, min(1.0, 0.50 + 3.0 * avg + 0.25 * (hit - 0.5))) * confidence,
                    "manager_confidence": confidence,
                    "research_only": True,
                    "production_activation_allowed": False,
                }
            )
    return pd.DataFrame(rows)


def feature_importance(frame: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    ic = signal_ic(frame, horizons)
    for _, row in ic.iterrows():
        if row.get("scope") == "all":
            rows.append({"feature": "event_seed_score", "horizon": row.get("horizon"), "importance_proxy": abs(float(row.get("spearman_ic", 0.0) or 0.0)), "rows": row.get("rows")})
    for group_col in ["source_type", "event_type"]:
        stats = bucket_stats(frame, [group_col], horizons)
        for _, row in stats.iterrows():
            for horizon in horizons:
                value = row.get(f"avg_excess_{horizon}d", row.get(f"avg_return_{horizon}d", math.nan))
                rows.append(
                    {
                        "feature": f"{group_col}={row.get(group_col)}",
                        "horizon": int(horizon),
                        "importance_proxy": abs(float(value)) if pd.notna(value) else math.nan,
                        "rows": int(row.get("rows", 0)),
                    }
                )
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["feature", "horizon", "importance_proxy", "rows"])
    return out.sort_values(["horizon", "importance_proxy"], ascending=[True, False], na_position="last")


def render_report(summary: dict[str, Any], source_stats: pd.DataFrame, horizons: list[int]) -> str:
    lines = [
        "# Post-Disclosure Signal Learning",
        "",
        "Research-only learning report for SEC/ETF disclosure events.",
        "",
        f"- status: `{summary.get('status')}`",
        f"- label rows: {summary.get('label_rows', 0)}",
        f"- manager score rows: {summary.get('manager_score_rows', 0)}",
        "",
        "## Source Summary",
        "",
        "| source | rows | avg 63d excess | hit 63d |",
        "| --- | ---: | ---: | ---: |",
    ]
    if not source_stats.empty:
        for _, row in source_stats.iterrows():
            horizon = 63 if 63 in horizons else horizons[0]
            lines.append(
                "| {source} | {rows} | {avg:.2%} | {hit:.2%} |".format(
                    source=row.get("source_type", ""),
                    rows=int(row.get("rows", 0)),
                    avg=float(row.get(f"avg_excess_{horizon}d", 0.0) or 0.0),
                    hit=float(row.get(f"excess_hit_rate_{horizon}d", 0.0) or 0.0),
                )
            )
    lines.extend(["", "Production activation remains disabled; use these outputs only to design broker-ledger challengers.", ""])
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    labels_path = repo_path(args.labels)
    output_dir = repo_path(args.output_dir)
    manager_output = repo_path(args.manager_output)
    output_dir.mkdir(parents=True, exist_ok=True)
    horizons = parse_horizons(args.horizons)
    labels = prepare_labels(read_table(labels_path))
    if labels.empty:
        empty = pd.DataFrame()
        for name in [
            "signal_ic_by_horizon.csv",
            "source_alpha.csv",
            "event_type_alpha.csv",
            "manager_alpha_ranking.csv",
            "event_feature_importance.csv",
            "follow_vs_fade_report.csv",
        ]:
            empty.to_csv(output_dir / name, index=False)
        write_table(empty, manager_output)
        summary = {
            "status": "blocked",
            "reason": "missing post-disclosure label rows",
            "research_only": True,
            "production_activation_allowed": False,
            "score_total_changed": False,
            "labels": str(labels_path),
            "label_rows": 0,
        }
        write_json(output_dir / "summary.json", summary)
        (output_dir / "report.md").write_text(render_report(summary, empty, horizons or [63]), encoding="utf-8")
        print(json.dumps({"status": "blocked", "label_rows": 0}, sort_keys=True))
        return summary

    source_stats = bucket_stats(labels, ["source_type"], horizons)
    event_stats = bucket_stats(labels, ["source_type", "event_type"], horizons)
    ic = signal_ic(labels, horizons)
    follow = follow_vs_fade(labels, horizons)
    managers = manager_alpha_scores(labels, horizon=63 if 63 in horizons else horizons[-1])
    latest_managers = pd.DataFrame()
    if not managers.empty:
        latest_managers = managers.sort_values(["manager_cik", "as_of_date"]).groupby("manager_cik", as_index=False).tail(1)
        latest_managers = latest_managers.sort_values(["manager_disclosure_alpha_score", "sample_count"], ascending=False)
    importance = feature_importance(labels, horizons)

    ic.to_csv(output_dir / "signal_ic_by_horizon.csv", index=False)
    source_stats.to_csv(output_dir / "source_alpha.csv", index=False)
    event_stats.to_csv(output_dir / "event_type_alpha.csv", index=False)
    latest_managers.to_csv(output_dir / "manager_alpha_ranking.csv", index=False)
    importance.to_csv(output_dir / "event_feature_importance.csv", index=False)
    follow.to_csv(output_dir / "follow_vs_fade_report.csv", index=False)
    write_table(managers, manager_output)
    summary = {
        "status": "completed",
        "schema_version": "post-disclosure-signal-learning-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "labels": str(labels_path),
        "label_rows": int(len(labels)),
        "source_count": int(labels["source_type"].nunique()),
        "event_type_count": int(labels["event_type"].nunique()),
        "manager_score_rows": int(len(managers)),
        "latest_manager_rows": int(len(latest_managers)),
        "outputs": {
            "signal_ic_by_horizon": str(output_dir / "signal_ic_by_horizon.csv"),
            "source_alpha": str(output_dir / "source_alpha.csv"),
            "event_type_alpha": str(output_dir / "event_type_alpha.csv"),
            "manager_alpha_ranking": str(output_dir / "manager_alpha_ranking.csv"),
            "event_feature_importance": str(output_dir / "event_feature_importance.csv"),
            "follow_vs_fade_report": str(output_dir / "follow_vs_fade_report.csv"),
            "manager_disclosure_alpha_scores": str(manager_output),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, source_stats, horizons), encoding="utf-8")
    print(json.dumps({"status": "completed", "label_rows": len(labels)}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", default=DEFAULT_LABELS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manager-output", default=DEFAULT_MANAGER_OUTPUT)
    parser.add_argument("--horizons", default=DEFAULT_HORIZONS)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
