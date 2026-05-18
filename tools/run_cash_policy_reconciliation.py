#!/usr/bin/env python3
"""Reconcile latest macro cash policy, orchestrator cash, and broker cash.

This diagnostic is latest-snapshot only and research/reporting only. It answers
whether target cash is coming from explicit macro defense or from portfolio
capacity / merge mechanics that can create CAGR drag in green regimes.
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
DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/cash_policy_reconciliation"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


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
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def latest_macro(latest_run: Path) -> dict[str, Any]:
    payload = read_json(latest_run / "macro_policy_engine" / "summary.json")
    latest = payload.get("latest")
    return latest if isinstance(latest, dict) else {}


def orchestrator_cash(latest_run: Path) -> dict[str, Any]:
    payload = read_json(latest_run / "orchestrator" / "unified_target_latest.json")
    frame = read_csv(latest_run / "orchestrator" / "unified_target_latest.csv")
    cash_from_csv = math.nan
    if not frame.empty and {"ticker", "target_weight"} <= set(frame.columns):
        d = frame.copy()
        d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
        d["target_weight"] = pd.to_numeric(d["target_weight"], errors="coerce").fillna(0.0)
        cash_from_csv = float(d.loc[d["ticker"].eq("CASH"), "target_weight"].sum())
        if cash_from_csv <= 1e-12:
            stock_sum = float(d.loc[~d["ticker"].eq("CASH"), "target_weight"].sum())
            cash_from_csv = max(0.0, 1.0 - stock_sum)
    audit = payload.get("audit") if isinstance(payload.get("audit"), dict) else {}
    policy = audit.get("policy_capacity") if isinstance(audit.get("policy_capacity"), dict) else {}
    target_cash = safe_float(payload.get("cash_target"), cash_from_csv)
    expected_invested = safe_float(policy.get("expected_total_invested"), math.nan)
    actual_invested = safe_float(policy.get("actual_total_invested_after_merge"), 1.0 - target_cash)
    conflict_cash = safe_float(policy.get("merged_below_expected_due_to_conflicts"), max(0.0, expected_invested - actual_invested) if math.isfinite(expected_invested) and math.isfinite(actual_invested) else math.nan)
    capacity_leftover = max(0.0, 1.0 - expected_invested) if math.isfinite(expected_invested) else math.nan
    return {
        "target_cash_weight": target_cash,
        "expected_total_invested": expected_invested,
        "actual_total_invested_after_merge": actual_invested,
        "capacity_leftover_cash_weight": capacity_leftover,
        "conflict_merge_cash_weight": conflict_cash,
        "regime_state": str(payload.get("regime_state") or ""),
        "by_mandate_capacity": payload.get("by_mandate_capacity") or {},
        "source": str(latest_run / "orchestrator" / "unified_target_latest.json"),
    }


def account_cash(latest_run: Path) -> dict[str, Any]:
    operating = read_json(latest_run / "operating_snapshot" / "operating_snapshot_latest.json")
    current_snapshot = read_json(latest_run / "operating_snapshot" / "current_portfolio_snapshot_summary.json")
    out: dict[str, Any] = {
        "operating_current_cash_weight": safe_float(operating.get("current_cash_weight"), safe_float(current_snapshot.get("combined_current_cash_weight"), math.nan)),
        "operating_target_cash_weight": safe_float(operating.get("target_cash_weight"), safe_float(current_snapshot.get("combined_target_cash_weight"), math.nan)),
        "cash_policy_flag": str(operating.get("cash_policy_flag") or current_snapshot.get("cash_policy_flag") or ""),
        "cash_policy_review_action": str(operating.get("cash_policy_review_action") or current_snapshot.get("cash_policy_review_action") or ""),
    }
    for portfolio in ["main", "concentrated"]:
        preview = read_json(latest_run / "account_ledger_preview" / portfolio / "preview_metrics.json")
        state = read_json(latest_run / "broker_replay" / portfolio / "account_state_latest.json")
        out[f"{portfolio}_preview_target_cash_weight"] = safe_float(preview.get("target_cash_weight"), math.nan)
        out[f"{portfolio}_preview_current_cash_weight"] = safe_float(preview.get("cash_weight"), safe_float(state.get("cash_weight"), math.nan))
        out[f"{portfolio}_preview_projected_cash_weight"] = safe_float(preview.get("projected_cash_weight"), math.nan)
        out[f"{portfolio}_preview_order_count"] = int(safe_float(preview.get("order_count"), 0.0))
        out[f"{portfolio}_preview_blocked_order_count"] = int(safe_float(preview.get("blocked_order_count"), 0.0))
    return out


def rows_by_source(macro: dict[str, Any], orch: dict[str, Any], cash: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"source": "macro_policy_floor", "cash_weight": safe_float(macro.get("recommended_cash_floor"), math.nan), "notes": "minimum cash from macro policy"},
        {"source": "orchestrator_target_cash", "cash_weight": safe_float(orch.get("target_cash_weight"), math.nan), "notes": "target cash after mandate merge"},
        {"source": "orchestrator_capacity_leftover", "cash_weight": safe_float(orch.get("capacity_leftover_cash_weight"), math.nan), "notes": "cash implied by total mandate capacity below 100%"},
        {"source": "orchestrator_conflict_merge_cash", "cash_weight": safe_float(orch.get("conflict_merge_cash_weight"), math.nan), "notes": "extra cash from max-merge conflicts below expected invested"},
        {"source": "operating_target_cash", "cash_weight": safe_float(cash.get("operating_target_cash_weight"), math.nan), "notes": "target cash from operating snapshot"},
        {"source": "operating_current_cash", "cash_weight": safe_float(cash.get("operating_current_cash_weight"), math.nan), "notes": "current broker-ledger cash"},
        {"source": "main_preview_target_cash", "cash_weight": safe_float(cash.get("main_preview_target_cash_weight"), math.nan), "notes": "main account preview target cash"},
        {"source": "concentrated_preview_target_cash", "cash_weight": safe_float(cash.get("concentrated_preview_target_cash_weight"), math.nan), "notes": "concentrated account preview target cash"},
    ]


def render_report(payload: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        v = safe_float(value, math.nan)
        return "n/a" if not math.isfinite(v) else f"{v:.2%}"

    lines = [
        "# Cash Policy Reconciliation",
        "",
        "Latest-snapshot diagnostic only. No portfolio weights are changed.",
        "",
        "## Verdict",
        "",
        f"- status: `{payload.get('status')}`",
        f"- review required: `{payload.get('review_required')}`",
        f"- decision point: {payload.get('decision_point')}",
        "",
        "## Key Values",
        "",
        f"- macro risk/style: `{payload.get('macro_risk_state')}` / `{payload.get('macro_style_state')}`",
        f"- macro cash floor: {pct(payload.get('macro_recommended_cash_floor'))}",
        f"- orchestrator target cash: {pct(payload.get('orchestrator_target_cash_weight'))}",
        f"- current account cash: {pct(payload.get('operating_current_cash_weight'))}",
        f"- target cash above macro floor: {pct(payload.get('target_cash_above_macro_floor'))}",
        f"- capacity leftover cash: {pct(payload.get('capacity_leftover_cash_weight'))}",
        f"- conflict merge cash: {pct(payload.get('conflict_merge_cash_weight'))}",
        f"- opportunity cost at 10% return assumption: {pct(payload.get('annual_opportunity_cost_at_10pct_return'))}",
        "",
        "## Notes",
        "",
    ]
    for note in payload.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def run(latest_run: str | Path = DEFAULT_LATEST_RUN, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    latest = repo_path(latest_run)
    out_dir = repo_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    macro = latest_macro(latest)
    orch = orchestrator_cash(latest)
    cash = account_cash(latest)

    macro_floor = safe_float(macro.get("recommended_cash_floor"), 0.0)
    target_cash = safe_float(orch.get("target_cash_weight"), safe_float(cash.get("operating_target_cash_weight"), math.nan))
    current_cash = safe_float(cash.get("operating_current_cash_weight"), math.nan)
    target_above_floor = max(0.0, target_cash - macro_floor) if math.isfinite(target_cash) else math.nan
    confirmed_raise = bool(macro.get("confirmed_cash_raise")) or str(macro.get("cash_raise_gate") or "").lower() not in {"", "none"}
    confirmations = safe_float(macro.get("cash_raise_confirmation_count"), 0.0)
    risk_state = str(macro.get("macro_risk_state") or "")
    review_required = (
        math.isfinite(target_above_floor)
        and target_above_floor >= 0.10
        and not confirmed_raise
        and confirmations < 2
        and risk_state.lower() in {"", "green", "recovery", "yellow"}
    )
    decision_point = (
        "target_cash_exceeds_macro_floor_without_confirmation"
        if review_required
        else "cash_target_aligned_or_macro_defense_confirmed"
    )
    rows = rows_by_source(macro, orch, cash)
    pd.DataFrame(rows).to_csv(out_dir / "cash_target_by_source.csv", index=False)

    payload = {
        "status": "completed",
        "schema_version": "cash-policy-reconciliation-v1",
        "research_only": True,
        "production_activation_allowed": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest),
        "macro_risk_state": risk_state,
        "macro_style_state": str(macro.get("macro_style_state") or ""),
        "macro_recommended_cash_floor": macro_floor,
        "macro_cash_raise_gate": str(macro.get("cash_raise_gate") or ""),
        "macro_cash_raise_confirmation_count": confirmations,
        "macro_confirmed_cash_raise": bool(macro.get("confirmed_cash_raise")),
        "orchestrator_target_cash_weight": target_cash,
        "operating_target_cash_weight": safe_float(cash.get("operating_target_cash_weight"), math.nan),
        "operating_current_cash_weight": current_cash,
        "target_cash_above_macro_floor": target_above_floor,
        "current_cash_gap_to_target": target_cash - current_cash if math.isfinite(target_cash) and math.isfinite(current_cash) else math.nan,
        "capacity_leftover_cash_weight": safe_float(orch.get("capacity_leftover_cash_weight"), math.nan),
        "conflict_merge_cash_weight": safe_float(orch.get("conflict_merge_cash_weight"), math.nan),
        "expected_total_invested": safe_float(orch.get("expected_total_invested"), math.nan),
        "actual_total_invested_after_merge": safe_float(orch.get("actual_total_invested_after_merge"), math.nan),
        "annual_opportunity_cost_at_10pct_return": target_above_floor * 0.10 if math.isfinite(target_above_floor) else math.nan,
        "review_required": bool(review_required),
        "decision_point": decision_point,
        "cash_policy_flag": cash.get("cash_policy_flag"),
        "cash_policy_review_action": cash.get("cash_policy_review_action"),
        "preview": {k: v for k, v in cash.items() if k.startswith("main_") or k.startswith("concentrated_")},
        "by_mandate_capacity": orch.get("by_mandate_capacity") or {},
        "outputs": {
            "summary_json": str(out_dir / "cash_policy_reconciliation_summary.json"),
            "by_source_csv": str(out_dir / "cash_target_by_source.csv"),
            "report_md": str(out_dir / "cash_policy_reconciliation_report.md"),
        },
        "notes": [
            "A high orchestrator target cash in a green/recovery macro state should be treated as a decision point, not as confirmed risk defense.",
            "Capacity leftover cash means mandate weights sum below 100%; conflict merge cash means max-merge overlap reduced invested exposure.",
            "This sidecar does not redeploy cash. It only separates macro defense from mechanical cash drag candidates.",
        ],
    }
    write_json(out_dir / "cash_policy_reconciliation_summary.json", payload)
    (out_dir / "cash_policy_reconciliation_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(args.latest_run, args.output_dir)
    print(json.dumps({"status": payload.get("status"), "review_required": payload.get("review_required")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
