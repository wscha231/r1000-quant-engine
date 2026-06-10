#!/usr/bin/env python3
"""Attach monster/leader lifecycle evidence to main and concentrated targets.

This is a recommendation bridge, not a production selector. It converts the
separate monster lifecycle, missed-winner, stale-winner, and rotation sidecars
into operator-facing overlays for the existing main/concentrated books.
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

from tools.run_broker_ledger_replay import repo_path, safe_float


DEFAULT_OUTPUT_DIR = "outputs/monster_recommendations"
PORTFOLIO_TARGETS = {
    "main": "portfolio_latest.csv",
    "concentrated": "concentrated_portfolio_latest.csv",
}
MONSTER_HOLDING_DIRS = {
    "main": ("monster_lifecycle_review_main",),
    "concentrated": ("monster_lifecycle_review_concentrated", "monster_lifecycle_replay"),
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


def normalize_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in {"", "NAN"} else ticker


def clean_float(value: Any) -> float:
    out = safe_float(value, 0.0)
    return float(out) if math.isfinite(float(out)) else 0.0


def latest_rows(frame: pd.DataFrame, date_col: str = "rebalance_date") -> pd.DataFrame:
    if frame.empty or date_col not in frame.columns:
        return frame.copy()
    out = frame.copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out = out.dropna(subset=[date_col])
    if out.empty:
        return out
    return out[out[date_col].eq(out[date_col].max())].copy()


def load_target(latest_run: Path, portfolio: str) -> pd.DataFrame:
    frame = read_csv(latest_run / PORTFOLIO_TARGETS[portfolio])
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["ticker"] = out["ticker"].map(normalize_ticker)
    weight_col = "target_weight" if "target_weight" in out.columns else "weight"
    if weight_col not in out.columns:
        weight_col = "proposed_weight" if "proposed_weight" in out.columns else ""
    out["target_weight"] = pd.to_numeric(out[weight_col], errors="coerce").fillna(0.0) if weight_col else 0.0
    out = out[out["ticker"] != ""].copy()
    return out


def load_scored(latest_run: Path) -> dict[str, dict[str, Any]]:
    frame = read_csv(latest_run / "scored_latest.csv")
    if frame.empty or "ticker" not in frame.columns:
        return {}
    frame = frame.copy()
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    return {str(row.ticker): row._asdict() for row in frame.itertuples(index=False) if str(row.ticker)}


def load_lifecycle_maps(latest_run: Path) -> dict[str, dict[str, dict[str, Any]]]:
    base = latest_run / "winner_lifecycle"
    maps: dict[str, dict[str, dict[str, Any]]] = {"missed": {}, "stale": {}, "rotation_by_held": {}, "rotation_by_challenger": {}}
    missed = read_csv(base / "missed_winner_report.csv")
    if not missed.empty and "ticker" in missed.columns:
        missed["ticker"] = missed["ticker"].map(normalize_ticker)
        for row in missed.to_dict("records"):
            if row.get("ticker"):
                maps["missed"][str(row["ticker"])] = row
    stale = read_csv(base / "stale_winner_report.csv")
    if not stale.empty and "ticker" in stale.columns:
        stale["ticker"] = stale["ticker"].map(normalize_ticker)
        for row in stale.to_dict("records"):
            if row.get("ticker"):
                maps["stale"][str(row["ticker"])] = row
    rotations = read_csv(base / "leadership_rotation_report.csv")
    if not rotations.empty:
        for col in ["held_ticker", "challenger_ticker"]:
            if col not in rotations.columns:
                rotations[col] = ""
            rotations[col] = rotations[col].map(normalize_ticker)
        for row in rotations.to_dict("records"):
            held = str(row.get("held_ticker") or "")
            challenger = str(row.get("challenger_ticker") or "")
            if held:
                maps["rotation_by_held"][held] = row
            if challenger:
                maps["rotation_by_challenger"][challenger] = row
    return maps


def load_monster_holdings(latest_run: Path, portfolio: str) -> dict[str, dict[str, Any]]:
    frames: list[pd.DataFrame] = []
    for folder in MONSTER_HOLDING_DIRS[portfolio]:
        frame = read_csv(latest_run / folder / "holdings.csv")
        if frame.empty or "ticker" not in frame.columns:
            continue
        frame = latest_rows(frame)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["monster_source"] = folder
        frames.append(frame)
    if not frames:
        return {}
    out = pd.concat(frames, ignore_index=True)
    out["ticker"] = out["ticker"].map(normalize_ticker)
    result: dict[str, dict[str, Any]] = {}
    for row in out.to_dict("records"):
        ticker = normalize_ticker(row.get("ticker"))
        if ticker:
            result[ticker] = row
    return result


def score_lookup(scored: dict[str, dict[str, Any]], ticker: str, *cols: str) -> float:
    row = scored.get(ticker) or {}
    return max(clean_float(row.get(col)) for col in cols)


def build_recommendations_for_portfolio(
    *,
    latest_run: Path,
    portfolio: str,
    scored: dict[str, dict[str, Any]],
    lifecycle: dict[str, dict[str, dict[str, Any]]],
    max_candidates: int,
) -> pd.DataFrame:
    target = load_target(latest_run, portfolio)
    held = set(target.get("ticker", pd.Series(dtype=str)).astype(str)) if not target.empty else set()
    monster = load_monster_holdings(latest_run, portfolio)
    rows: list[dict[str, Any]] = []

    for row in target.to_dict("records") if not target.empty else []:
        ticker = normalize_ticker(row.get("ticker"))
        if not ticker:
            continue
        target_weight = clean_float(row.get("target_weight"))
        stale = lifecycle["stale"].get(ticker, {})
        rotation = lifecycle["rotation_by_held"].get(ticker, {})
        monster_row = monster.get(ticker, {})
        stage = str(monster_row.get("stage") or "")
        action = "hold_target"
        reason = "existing target holding"
        priority = target_weight
        if stale:
            action = "review_trim_or_replace"
            reason = str(stale.get("diagnosis") or "stale winner signal")
            priority += clean_float(stale.get("stale_winner_score"))
        elif rotation:
            action = "review_rotation"
            reason = f"challenger {rotation.get('challenger_ticker')} outranks held name"
            priority += clean_float(rotation.get("rotation_score"))
        elif stage in {"winner", "monster"}:
            action = "defend_or_hold_monster"
            reason = f"monster lifecycle stage={stage}"
            priority += 1.0 + clean_float(monster_row.get("monster_onset_score"))
        elif stage in {"scout", "confirm"}:
            action = "stage_position"
            reason = f"monster lifecycle stage={stage}"
            priority += 0.5 + clean_float(monster_row.get("monster_onset_score"))
        rows.append(
            {
                "portfolio": portfolio,
                "ticker": ticker,
                "row_role": "current_target",
                "target_weight": target_weight,
                "monster_recommendation": action,
                "monster_stage": stage,
                "monster_priority_score": priority,
                "monster_reason": reason,
                "replacement_candidate": rotation.get("challenger_ticker", ""),
                "production_activation_allowed": False,
            }
        )

    candidate_rows: list[dict[str, Any]] = []
    for ticker, missed in lifecycle["missed"].items():
        if ticker in held:
            continue
        priority = clean_float(missed.get("missed_winner_score")) + score_lookup(
            scored,
            ticker,
            "portfolio_monster_early_score",
            "portfolio_future_winner_engine_score",
            "h6_dynamic_leader_score",
        )
        action = "consider_main_scout" if portfolio == "main" else "consider_concentrated_challenger"
        candidate_rows.append(
            {
                "portfolio": portfolio,
                "ticker": ticker,
                "row_role": "candidate",
                "target_weight": 0.0,
                "monster_recommendation": action,
                "monster_stage": "",
                "monster_priority_score": priority,
                "monster_reason": str(missed.get("diagnosis") or "missed winner candidate"),
                "replacement_candidate": "",
                "production_activation_allowed": False,
            }
        )
    for ticker, rotation in lifecycle["rotation_by_challenger"].items():
        if ticker in held:
            continue
        priority = clean_float(rotation.get("rotation_score")) + score_lookup(scored, ticker, "score", "h6_dynamic_leader_score") / 10.0
        candidate_rows.append(
            {
                "portfolio": portfolio,
                "ticker": ticker,
                "row_role": "candidate",
                "target_weight": 0.0,
                "monster_recommendation": "consider_rotation_candidate",
                "monster_stage": "",
                "monster_priority_score": priority,
                "monster_reason": f"rotation candidate for {rotation.get('held_ticker')}",
                "replacement_candidate": "",
                "production_activation_allowed": False,
            }
        )
    candidate_rows = sorted(candidate_rows, key=lambda row: clean_float(row.get("monster_priority_score")), reverse=True)[:max_candidates]
    rows.extend(candidate_rows)
    return pd.DataFrame(rows)


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Monster Recommendations Bridge",
        "",
        "Recommendation-only overlay for main and concentrated portfolios.",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Main rows: {payload.get('main_rows')}",
        f"- Concentrated rows: {payload.get('concentrated_rows')}",
        f"- Production activation allowed: `{payload.get('production_activation_allowed')}`",
        "",
        "These rows annotate current targets and candidate challengers. They do not mutate portfolio construction or submit orders.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    scored = load_scored(latest_run)
    lifecycle = load_lifecycle_maps(latest_run)
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for portfolio in ("main", "concentrated"):
        frame = build_recommendations_for_portfolio(
            latest_run=latest_run,
            portfolio=portfolio,
            scored=scored,
            lifecycle=lifecycle,
            max_candidates=int(args.max_candidates),
        )
        frame.to_csv(output_dir / f"{portfolio}_recommendations.csv", index=False)
        counts[portfolio] = int(len(frame))
        frames.append(frame)
    unified = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    unified.to_csv(output_dir / "unified_recommendations.csv", index=False)
    payload = {
        "status": "completed",
        "schema_version": "monster-recommendation-bridge-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "main_rows": counts.get("main", 0),
        "concentrated_rows": counts.get("concentrated", 0),
        "unified_rows": int(len(unified)),
        "production_activation_allowed": False,
        "outputs": {
            "main": str(output_dir / "main_recommendations.csv"),
            "concentrated": str(output_dir / "concentrated_recommendations.csv"),
            "unified": str(output_dir / "unified_recommendations.csv"),
        },
    }
    write_json(output_dir / "monster_recommendation_summary.json", payload)
    (output_dir / "monster_recommendation_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-candidates", type=int, default=12)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload["status"], "unified_rows": payload["unified_rows"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
