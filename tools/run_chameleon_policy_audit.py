#!/usr/bin/env python3
"""Research-only R1b chameleon policy audit.

This translates an R1 regime state into review-only operating guidance. It
cannot create executable orders and cannot mutate production policy.
"""
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

from tools.research_audit_utils import read_csv, repo_path, safe_float, write_json  # noqa: E402

DEFAULT_OUTPUT_DIR = "outputs/chameleon_policy_audit"
SUPPORTED_STATES = ["BULL", "LATE_CYCLE", "CORRECTION", "BEAR", "RECOVERY", "DATA_INSUFFICIENT"]

ACTION_MAP: dict[str, list[tuple[str, str]]] = {
    "BULL": [
        ("normal_monthly_alphaops_target_process", "Allow the normal monthly AlphaOps target process review."),
        ("passed_replacement_quality_candidates", "Allow separately passed replacement-quality research candidates."),
        ("cash_carry_accounting", "Maintain cash-carry accounting."),
    ],
    "LATE_CYCLE": [
        ("leader_momentum_active", "Keep leader momentum active."),
        ("eps_guidance_revenue_confirmation", "Require earnings, guidance, or revenue confirmation where PIT evidence exists."),
        ("concentration_warning", "Raise single-name and cluster concentration warnings."),
        ("no_broad_gross_floor_revival", "Do not revive broad gross-floor."),
    ],
    "CORRECTION": [
        ("no_new_discretionary_entries", "No new discretionary entries from this layer."),
        ("position_shock_review", "Trigger position shock review."),
        ("trim_to_cap_review", "Trigger trim-to-cap review when concentration exceeds configured limits."),
        ("cash_tbill_reserve_destination", "Destination for reviewed risk reduction is cash or T-bill reserve."),
        ("no_contrarian_buying", "No contrarian buying."),
    ],
    "BEAR": [
        ("strategy_allocation_review", "Trigger strategy-allocation review."),
        ("no_contrarian_entry", "No contrarian entry."),
        ("capital_preservation", "Preserve capital."),
        ("cash_tbill_or_approved_fallback", "Destination is cash, T-bill reserve, or separately approved portfolio fallback."),
    ],
    "RECOVERY": [
        ("staged_reentry_candidates_only", "Permit only staged re-entry candidates from R4."),
        ("trend_breadth_confirmation_required", "Full risk-on restoration requires trend and breadth confirmation."),
    ],
    "DATA_INSUFFICIENT": [
        ("no_current_regime_claim", "Do not claim a current regime without refreshed signal coverage."),
        ("expand_r1_coverage", "Refresh or expand R1 inputs before linking alerts or automation."),
    ],
}

SHOCK_LABEL_ORDER = ["WATCH", "SHOCK_REVIEW", "TRIM_TO_CAP_REVIEW", "EXIT_REVIEW"]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def normalize_state(value: Any) -> str:
    state = str(value or "").strip().upper()
    return state if state in SUPPORTED_STATES else "DATA_INSUFFICIENT"


def load_regime_state(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.state:
        state = normalize_state(args.state)
        return state, {"source": "arg", "current_state": state}

    summary = read_json(repo_path(args.regime_summary))
    if summary:
        state = normalize_state(summary.get("current_state"))
        return state, {**summary, "source": str(repo_path(args.regime_summary))}

    history = read_csv(repo_path(args.state_history))
    if not history.empty and "state" in history.columns:
        latest = history.sort_values("date").iloc[-1].to_dict() if "date" in history.columns else history.iloc[-1].to_dict()
        state = normalize_state(latest.get("state"))
        return state, {**latest, "source": str(repo_path(args.state_history))}

    return "DATA_INSUFFICIENT", {"source": "missing_r1_output", "current_state": "DATA_INSUFFICIENT"}


def base_action_rows(state: str, regime_meta: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for action, detail in ACTION_MAP.get(state, ACTION_MAP["DATA_INSUFFICIENT"]):
        rows.append(
            {
                "subject": "portfolio",
                "state": state,
                "action_label": action,
                "action_detail": detail,
                "shock_guard_label": "",
                "review_status": "REVIEW_ONLY",
                "executable_order_allowed": False,
                "production_policy_mutation_allowed": False,
                "live_trading_allowed": False,
                "bear_warning_score": regime_meta.get("bear_warning_score"),
                "confidence": regime_meta.get("confidence"),
            }
        )
    return rows


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def shock_label(row: pd.Series) -> str:
    one_day = safe_float(row.get("one_day_return"), 0.0)
    three_day = safe_float(row.get("three_day_return"), 0.0)
    gap_down = safe_float(row.get("gap_down"), 0.0)
    volume_z = safe_float(row.get("volume_z"), 0.0)
    weight = safe_float(row.get("current_position_weight", row.get("current_weight")), 0.0)
    rs_3m = safe_float(row.get("rs_3m", row.get("rs_spy_3m")), 0.0)
    ma50_failed = _bool(row.get("ma50_failed"))
    ma200_failed = _bool(row.get("ma200_failed"))

    if ma50_failed and ma200_failed and rs_3m < 0.0:
        return "EXIT_REVIEW"
    if weight > 0.25:
        return "TRIM_TO_CAP_REVIEW"
    if one_day <= -0.12 or three_day <= -0.18 or (gap_down <= -0.10 and volume_z > 2.0):
        return "SHOCK_REVIEW"
    if one_day < 0.0 or three_day < 0.0 or rs_3m < 0.0:
        return "WATCH"
    return ""


def shock_action_rows(shock_panel: Path, state: str, regime_meta: dict[str, Any]) -> list[dict[str, Any]]:
    panel = read_csv(shock_panel)
    if panel.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in panel.iterrows():
        label = shock_label(row)
        if not label:
            continue
        ticker = str(row.get("ticker", row.get("symbol", "portfolio"))).strip() or "portfolio"
        rows.append(
            {
                "subject": ticker,
                "state": state,
                "action_label": label.lower(),
                "action_detail": f"{label} label only; no automatic sell is allowed.",
                "shock_guard_label": label,
                "review_status": "REVIEW_ONLY",
                "executable_order_allowed": False,
                "production_policy_mutation_allowed": False,
                "live_trading_allowed": False,
                "bear_warning_score": regime_meta.get("bear_warning_score"),
                "confidence": regime_meta.get("confidence"),
            }
        )
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    state, regime_meta = load_regime_state(args)
    rows = base_action_rows(state, regime_meta)
    if args.shock_panel:
        rows.extend(shock_action_rows(repo_path(args.shock_panel), state, regime_meta))
    actions = pd.DataFrame(rows)
    actions.to_csv(output_dir / "recommended_actions.csv", index=False)

    shock_counts = {}
    if not actions.empty and "shock_guard_label" in actions.columns:
        labels = actions["shock_guard_label"].astype(str)
        shock_counts = {label: int((labels == label).sum()) for label in SHOCK_LABEL_ORDER}

    payload = {
        "schema_version": "chameleon-policy-audit-v1",
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_state": state,
        "regime_source": regime_meta.get("source"),
        "recommended_action_count": int(len(actions)),
        "shock_guard_label_counts": shock_counts,
        "all_actions_review_only": bool(actions["review_status"].eq("REVIEW_ONLY").all()) if not actions.empty else True,
        "executable_order_allowed": False,
        "production_policy_mutation_allowed": False,
        "live_trading_allowed": False,
        "w7_alert_feed_allowed": True,
        "automation_connection_requires_existing_outputs": True,
        "automation_connection_allowed_without_separate_w7_work": False,
        "research_only": True,
    }
    write_json(output_dir / "summary.json", payload)

    lines = [
        "# Chameleon Policy Audit",
        "",
        f"- status: `{payload['status']}`",
        f"- current state: `{payload['current_state']}`",
        f"- recommended actions: `{payload['recommended_action_count']}`",
        "- all rows review-only: `true`",
        "- executable orders allowed: `false`",
        "- production policy mutation allowed: `false`",
        "- live trading allowed: `false`",
        "",
    ]
    if not actions.empty:
        lines.extend(["Recommended action labels:", ""])
        lines.extend([f"- `{label}`" for label in actions["action_label"].astype(str).tolist()])
        lines.append("")
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regime-summary", default="outputs/regime_nowcast_dial/summary.json")
    parser.add_argument("--state-history", default="outputs/regime_nowcast_dial/state_history.csv")
    parser.add_argument("--state", default="")
    parser.add_argument("--shock-panel", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
