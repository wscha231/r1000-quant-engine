#!/usr/bin/env python3
"""Research-only late-cycle AI capex regime audit."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "late-cycle-ai-regime-audit-v1"
DEFAULT_OUTPUT_DIR = "outputs/late_cycle_ai_regime"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        if path.suffix.lower() in {".parquet", ".pq"}:
            return pd.read_parquet(path)
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if pd.notna(out) else default
    except (TypeError, ValueError):
        return default


def positive_ratio(frame: pd.DataFrame, columns: list[str]) -> float:
    for col in columns:
        if col in frame.columns and len(frame):
            return float((pd.to_numeric(frame[col], errors="coerce").fillna(0.0) > 0).mean())
    return 0.0


def latest_numeric(frame: pd.DataFrame, columns: list[str], default: float = 0.0) -> float:
    for col in columns:
        if col in frame.columns and len(frame):
            series = pd.to_numeric(frame[col], errors="coerce").dropna()
            if not series.empty:
                return float(series.iloc[-1])
    return default


def audit(
    *,
    revisions: pd.DataFrame,
    candidates: pd.DataFrame,
    market: pd.DataFrame,
) -> dict[str, Any]:
    eps_revision_positive_ratio = positive_ratio(revisions, ["eps_revision_13w"])
    guidance_positive_ratio = positive_ratio(revisions, ["positive_guidance_flag", "guidance_vs_consensus_score"])
    it_revision_ratio = 0.0
    if not revisions.empty and "sector" in revisions.columns:
        sector = revisions[revisions["sector"].astype(str).str.lower().isin(["information technology", "technology", "it"])]
        it_revision_ratio = positive_ratio(sector, ["eps_revision_13w"])
    ai_revision_ratio = positive_ratio(candidates, ["eps_revision_13w", "revenue_revision_13w"])
    ai_bottleneck_ratio = positive_ratio(candidates, ["ai_capex_bottleneck_score"])
    momentum_dominance_score = positive_ratio(candidates, ["rs_benchmark_3m", "rs_spy_3m", "momentum_3m"])
    breadth_compression_score = max(0.0, 1.0 - latest_numeric(market, ["breadth_above_ma200", "pct_above_ma200"], 1.0))
    valuation_stretch_score = max(0.0, latest_numeric(market, ["forward_pe_vs_10y_avg", "valuation_stretch_score"], 0.0))
    rate_shock_risk_score = max(0.0, latest_numeric(market, ["rate_shock_risk_score", "ten_year_yield_change_3m"], 0.0))
    bubble_precondition_score = max(
        0.0,
        min(
            1.0,
            0.20 * eps_revision_positive_ratio
            + 0.20 * guidance_positive_ratio
            + 0.15 * it_revision_ratio
            + 0.15 * ai_revision_ratio
            + 0.15 * momentum_dominance_score
            + 0.10 * valuation_stretch_score
            + 0.05 * breadth_compression_score,
        ),
    )
    late_cycle_ai_capex_regime = bool(
        bubble_precondition_score >= 0.55
        and momentum_dominance_score >= 0.50
        and (ai_revision_ratio >= 0.45 or it_revision_ratio >= 0.45)
    )
    return {
        "eps_revision_positive_ratio": eps_revision_positive_ratio,
        "guidance_positive_ratio": guidance_positive_ratio,
        "it_revision_leadership_ratio": it_revision_ratio,
        "ai_revision_positive_ratio": ai_revision_ratio,
        "ai_bottleneck_positive_ratio": ai_bottleneck_ratio,
        "momentum_dominance_score": momentum_dominance_score,
        "breadth_compression_score": breadth_compression_score,
        "valuation_stretch_score": valuation_stretch_score,
        "rate_shock_risk_score": rate_shock_risk_score,
        "bubble_precondition_score": bubble_precondition_score,
        "late_cycle_ai_capex_regime": late_cycle_ai_capex_regime,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def render_report(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Late-Cycle AI Regime Audit",
            "",
            f"- Status: `{payload.get('status')}`",
            f"- late_cycle_ai_capex_regime: `{payload.get('late_cycle_ai_capex_regime')}`",
            f"- bubble_precondition_score: {safe_float(payload.get('bubble_precondition_score')):.2f}",
            f"- momentum_dominance_score: {safe_float(payload.get('momentum_dominance_score')):.2f}",
            f"- breadth_compression_score: {safe_float(payload.get('breadth_compression_score')):.2f}",
            f"- valuation_stretch_score: {safe_float(payload.get('valuation_stretch_score')):.2f}",
            "",
            "Telemetry only. This report does not force trades or mutate policy.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revisions", default=None)
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--market", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    revisions = read_table(repo_path(args.revisions) if args.revisions else None)
    candidates = read_table(repo_path(args.candidates) if args.candidates else None)
    market = read_table(repo_path(args.market) if args.market else None)
    result = audit(revisions=revisions, candidates=candidates, market=market)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "research_only": True,
        "production_activation_allowed": False,
        "force_trades": False,
        "revision_rows": int(len(revisions)),
        "candidate_rows": int(len(candidates)),
        "market_rows": int(len(market)),
        **result,
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
