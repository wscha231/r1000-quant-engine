#!/usr/bin/env python3
"""Build a bounded SEC 13F manager CIK list from a reviewed universe file.

The universe file is a human-reviewed control plane for manager tracking. It
can include external performance/AUM notes, but collection uses only verified
CIKs and downstream scoring still learns manager quality from repo evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_submissions_collector import cik10, repo_path  # noqa: E402

DEFAULT_MANAGER_UNIVERSE = "research/sec_13f_manager_universe_20260519/managers.csv"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def numeric_value(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        out = float(str(value).replace(",", "").replace("%", ""))
        return out if math.isfinite(out) else default
    except Exception:
        return default


def parse_extra_tokens(value: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for token in str(value or "").replace(";", ",").split(","):
        text = token.strip()
        if not text:
            continue
        label = ""
        raw_cik = text
        if ":" in text:
            label, raw_cik = [part.strip() for part in text.split(":", 1)]
        norm = cik10(raw_cik)
        if not norm:
            continue
        rows.append(
            {
                "label": (label or f"CIK{norm}").upper(),
                "manager_name": label or "",
                "cik10": norm,
                "active": True,
                "verified_cik": True,
                "user_priority": 999,
                "source": "extra",
            }
        )
    return pd.DataFrame(rows)


def load_manager_universe(path: Path, *, extra: str = "") -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if path.exists():
        frames.append(pd.read_csv(path, dtype=str).fillna(""))
    extra_frame = parse_extra_tokens(extra)
    if not extra_frame.empty:
        frames.append(extra_frame)
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True, sort=False).fillna("")
    d["label"] = d.get("label", "").astype(str).str.upper().str.strip()
    d["manager_name"] = d.get("manager_name", "").astype(str).str.strip()
    d["cik10"] = d.get("cik10", "").map(cik10)
    active_col = d["active"] if "active" in d.columns else pd.Series("true", index=d.index)
    verified_col = d["verified_cik"] if "verified_cik" in d.columns else pd.Series("false", index=d.index)
    priority_col = d["user_priority"] if "user_priority" in d.columns else pd.Series(999, index=d.index)
    perf_26q1_col = d["performance_26q1"] if "performance_26q1" in d.columns else pd.Series(0.0, index=d.index)
    perf_2y_col = d["external_performance_2y"] if "external_performance_2y" in d.columns else pd.Series(0.0, index=d.index)
    aum_col = d["aum_13f_usd"] if "aum_13f_usd" in d.columns else pd.Series(0.0, index=d.index)
    d["active_flag"] = active_col.map(truthy)
    d["verified_flag"] = verified_col.map(truthy)
    d["user_priority_num"] = priority_col.map(lambda value: numeric_value(value, 999.0))
    d["performance_26q1_num"] = perf_26q1_col.map(lambda value: numeric_value(value, 0.0))
    d["performance_2y_num"] = perf_2y_col.map(lambda value: numeric_value(value, 0.0))
    d["aum_13f_usd_num"] = aum_col.map(lambda value: numeric_value(value, 0.0))
    d = d[d["cik10"].ne("")].copy()
    if d.empty:
        return pd.DataFrame()
    d = d.sort_values(["user_priority_num", "aum_13f_usd_num", "performance_2y_num", "performance_26q1_num"], ascending=[True, False, False, False])
    d = d.drop_duplicates("cik10", keep="first")
    return d


def manager_tokens(frame: pd.DataFrame, *, require_verified: bool, min_aum_usd: float, max_managers: int) -> list[str]:
    if frame.empty:
        return []
    d = frame.copy()
    d = d[d["active_flag"]].copy()
    if require_verified:
        d = d[d["verified_flag"]].copy()
    if min_aum_usd > 0:
        keep = d["aum_13f_usd_num"].ge(float(min_aum_usd)) | d["user_priority_num"].le(10)
        d = d[keep].copy()
    if max_managers > 0:
        d = d.head(int(max_managers)).copy()
    tokens: list[str] = []
    for _, row in d.iterrows():
        label = str(row.get("label") or row.get("manager_name") or f"CIK{row.get('cik10')}").upper().replace(",", "_").replace(":", "_")
        tokens.append(f"{label}:{row.get('cik10')}")
    return tokens


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_path = repo_path(args.input)
    output_ciks = repo_path(args.output_ciks)
    output_summary = repo_path(args.output_summary)
    frame = load_manager_universe(input_path, extra=str(args.extra or ""))
    tokens = manager_tokens(
        frame,
        require_verified=bool(args.require_verified),
        min_aum_usd=float(args.min_aum_usd),
        max_managers=int(args.max_managers),
    )
    output_ciks.parent.mkdir(parents=True, exist_ok=True)
    output_ciks.write_text(",".join(tokens), encoding="utf-8")
    summary = {
        "status": "completed" if tokens else "blocked",
        "research_only": True,
        "production_activation_allowed": False,
        "input": str(input_path),
        "output_ciks": str(output_ciks),
        "manager_rows": int(len(frame)),
        "selected_managers": int(len(tokens)),
        "tokens": tokens,
        "annual_review_required": True,
        "semiannual_review_required": True,
        "review_rule": "Refresh manager selection at least semiannually with repo manager_alpha; external performance/AUM fields are review notes only.",
    }
    write_json(output_summary, summary)
    print(json.dumps({"status": summary["status"], "selected_managers": summary["selected_managers"], "tokens": tokens}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_MANAGER_UNIVERSE)
    parser.add_argument("--output-ciks", default="outputs/sec_institutional_signals/manager_ciks.txt")
    parser.add_argument("--output-summary", default="outputs/sec_institutional_signals/manager_universe_summary.json")
    parser.add_argument("--extra", default="")
    parser.add_argument("--min-aum-usd", type=float, default=0.0)
    parser.add_argument("--max-managers", type=int, default=50)
    parser.add_argument("--require-verified", action="store_true", default=True)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
