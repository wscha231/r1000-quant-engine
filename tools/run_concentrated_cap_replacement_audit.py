#!/usr/bin/env python3
"""Audit concentrated cap/replacement missed leaders.

Research-only diagnostic. This consumes the stock-selection quality audit output
and asks: among ex-ante leaders missed because of cap/replacement constraints,
which PIT-visible feature slices later had strong forward excess returns?

Forward returns are labels only. This tool must never feed live ranking,
selection, target books, cash policy, or production gates.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd


DEFAULT_STOCK_SELECTION_DIR = "outputs/stock_selection_quality"
DEFAULT_OUTPUT_DIR = "outputs/concentrated_cap_replacement_audit"
FORWARD_HORIZON = "forward_126d_excess"
PIT_NUMERIC_COLUMNS = (
    "leader_rank_ex_ante",
    "rs_spy_1m",
    "rs_spy_3m",
    "rs_spy_6m",
    "rs_qqq_1m",
    "rs_qqq_3m",
    "rs_qqq_6m",
    "rs_theme_1m",
    "rs_theme_3m",
    "rs_theme_6m",
    "revenue_growth",
    "liquidity_score",
    "evidence_boost",
    "top7_score",
    "form4_score",
    "etf_score",
    "chase_risk",
    "volatility",
)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in PIT_NUMERIC_COLUMNS + (FORWARD_HORIZON, "forward_21d_excess", "forward_63d_excess"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in ("portfolio", "rejection_reason", "theme", "sector", "ticker", "rebalance_date"):
        if col not in out.columns:
            out[col] = ""
    if "used_forward_return_in_ranking" not in out.columns:
        out["used_forward_return_in_ranking"] = False
    return out


def pct(value: Any) -> str:
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return ""


def rule_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    rank = pd.to_numeric(frame.get("leader_rank_ex_ante"), errors="coerce")
    rs3 = pd.to_numeric(frame.get("rs_spy_3m"), errors="coerce")
    rs6 = pd.to_numeric(frame.get("rs_spy_6m"), errors="coerce")
    rev = pd.to_numeric(frame.get("revenue_growth"), errors="coerce")
    liq = pd.to_numeric(frame.get("liquidity_score"), errors="coerce")
    theme = frame.get("theme", pd.Series("", index=frame.index)).astype(str)
    sector = frame.get("sector", pd.Series("", index=frame.index)).astype(str)
    semis = theme.str.contains("Semiconductor", case=False, na=False) | sector.str.contains(
        "Semiconductor", case=False, na=False
    )
    return {
        "all_cap_or_replacement": pd.Series(True, index=frame.index),
        "rank_top_10": rank <= 10,
        "rank_top_15": rank <= 15,
        "rs3_ge_20pct": rs3 >= 0.20,
        "rs3_ge_30pct": rs3 >= 0.30,
        "rank_top_10_and_rs3_ge_20pct": (rank <= 10) & (rs3 >= 0.20),
        "rank_top_15_and_rs3_ge_30pct": (rank <= 15) & (rs3 >= 0.30),
        "rank_top_10_and_revenue_growth_ge_10pct": (rank <= 10) & (rev >= 0.10),
        "rank_top_15_and_revenue_growth_ge_10pct": (rank <= 15) & (rev >= 0.10),
        "rs6_ge_50pct": rs6 >= 0.50,
        "liquidity_ge_500m": liq >= 500_000_000,
        "semiconductors": semis,
        "semiconductors_rank_top_10": semis & (rank <= 10),
        "semiconductors_rs3_ge_20pct": semis & (rs3 >= 0.20),
    }


def summarize_slice(name: str, frame: pd.DataFrame) -> dict[str, Any]:
    labelled = frame[pd.to_numeric(frame.get(FORWARD_HORIZON), errors="coerce").notna()].copy()
    values = pd.to_numeric(labelled.get(FORWARD_HORIZON), errors="coerce")
    out: dict[str, Any] = {
        "rule": name,
        "row_count": int(len(frame)),
        "labelled_count": int(values.notna().sum()),
        "production_activation_allowed": False,
        "policy_mutation_allowed": False,
        "uses_pit_features_only_for_rule": True,
        "forward_return_is_audit_label_only": True,
    }
    if values.notna().sum() == 0:
        out.update(
            {
                "mean_126d_excess": None,
                "median_126d_excess": None,
                "sum_126d_excess": None,
                "positive_rate_126d": None,
                "q25_126d_excess": None,
                "q75_126d_excess": None,
            }
        )
        return out
    out.update(
        {
            "mean_126d_excess": float(values.mean()),
            "median_126d_excess": float(values.median()),
            "sum_126d_excess": float(values.sum()),
            "positive_rate_126d": float((values > 0).mean()),
            "q25_126d_excess": float(values.quantile(0.25)),
            "q75_126d_excess": float(values.quantile(0.75)),
        }
    )
    return out


def top_rows(frame: pd.DataFrame, limit: int) -> pd.DataFrame:
    keep = [
        "rebalance_date",
        "ticker",
        "theme",
        "sector",
        "subindustry",
        "leader_rank_ex_ante",
        "rs_spy_3m",
        "rs_spy_6m",
        "revenue_growth",
        "liquidity_score",
        "forward_21d_excess",
        "forward_63d_excess",
        "forward_126d_excess",
    ]
    cols = [c for c in keep if c in frame.columns]
    return frame.sort_values(FORWARD_HORIZON, ascending=False).head(limit)[cols]


def render_report(payload: dict[str, Any], rule_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Concentrated Cap/Replacement Audit",
        "",
        "Research-only audit of ex-ante leaders missed by the concentrated book due to cap/replacement constraints.",
        "",
        f"- status: `{payload.get('status')}`",
        f"- missed rows: `{payload.get('missed_rows')}`",
        f"- cap/replacement rows: `{payload.get('cap_or_replacement_rows')}`",
        f"- forward labels used for ranking: `{str(payload.get('forward_labels_used_for_ranking')).lower()}`",
        f"- production activation allowed: `{str(payload.get('production_activation_allowed')).lower()}`",
        f"- best selective rule: `{(payload.get('best_rule') or {}).get('rule', '')}`",
        "",
        "Forward returns are audit labels only and must not be used for live ranking.",
        "",
        "## Top Rule Slices",
        "",
        "| rule | n | labelled | mean 126d excess | median | sum | positive rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    ranked = sorted(
        [r for r in rule_rows if r.get("sum_126d_excess") is not None],
        key=lambda r: (safe_float(r.get("sum_126d_excess")), safe_float(r.get("mean_126d_excess"))),
        reverse=True,
    )
    for row in ranked[:12]:
        lines.append(
            "| {rule} | {row_count} | {labelled_count} | {mean} | {median} | {sumv} | {pos} |".format(
                rule=row.get("rule"),
                row_count=row.get("row_count"),
                labelled_count=row.get("labelled_count"),
                mean=pct(row.get("mean_126d_excess")),
                median=pct(row.get("median_126d_excess")),
                sumv=f"{safe_float(row.get('sum_126d_excess')):.3f}",
                pos=pct(row.get("positive_rate_126d")),
            )
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "- A high-scoring slice is not a policy by itself.",
        "- Next policy work must express the slice using only PIT-visible fields, then measure a default-OFF target-book challenger through broker-ledger replay.",
        "- Reject any challenger that replaces intact DUAL/SECTOR leaders or improves audit labels without broker-ledger CAGR/MDD improvement.",
        "",
    ]
    return "\n".join(lines)


def best_selective_rule(rules: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        r
        for r in rules
        if r.get("rule") != "all_cap_or_replacement"
        and safe_float(r.get("labelled_count")) >= 3
        and r.get("sum_126d_excess") is not None
    ]
    if not candidates:
        return {}
    return sorted(
        candidates,
        key=lambda r: (
            safe_float(r.get("sum_126d_excess")),
            safe_float(r.get("mean_126d_excess")),
            safe_float(r.get("positive_rate_126d")),
        ),
        reverse=True,
    )[0]


def run(stock_selection_dir: Path, output_dir: Path, top_n: int = 30) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    missed = normalize(read_csv(stock_selection_dir / "missed_leaders_audit.csv"))
    if missed.empty:
        payload = {
            "schema_version": "concentrated-cap-replacement-audit-v1",
            "status": "blocked",
            "reason": "missing_or_empty_missed_leaders_audit",
            "stock_selection_dir": str(stock_selection_dir),
            "production_activation_allowed": False,
            "policy_mutation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        write_text(output_dir / "report.md", render_report(payload, []))
        return payload

    forward_used = missed["used_forward_return_in_ranking"].astype(str).str.lower().isin({"true", "1"}).any()
    cap = missed[
        missed["portfolio"].astype(str).eq("concentrated")
        & missed["rejection_reason"].astype(str).eq("cap_or_replacement")
    ].copy()

    rules: list[dict[str, Any]] = []
    masks = rule_masks(cap) if not cap.empty else {}
    for name, mask in masks.items():
        rules.append(summarize_slice(name, cap[mask.fillna(False)]))
    rules = sorted(
        rules,
        key=lambda r: (
            -1 if r.get("sum_126d_excess") is None else safe_float(r.get("sum_126d_excess")),
            -1 if r.get("mean_126d_excess") is None else safe_float(r.get("mean_126d_excess")),
        ),
        reverse=True,
    )

    top = top_rows(cap, top_n) if not cap.empty and FORWARD_HORIZON in cap.columns else pd.DataFrame()
    top.to_csv(output_dir / "top_missed_cap_replacement.csv", index=False)
    pd.DataFrame(rules).to_csv(output_dir / "rule_scan.csv", index=False)

    payload = {
        "schema_version": "concentrated-cap-replacement-audit-v1",
        "status": "blocked_forward_labels_used_for_ranking" if forward_used else "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stock_selection_dir": str(stock_selection_dir),
        "missed_rows": int(len(missed)),
        "cap_or_replacement_rows": int(len(cap)),
        "cap_or_replacement_labelled_126d_rows": int(pd.to_numeric(cap.get(FORWARD_HORIZON), errors="coerce").notna().sum()) if not cap.empty else 0,
        "forward_labels_used_for_ranking": bool(forward_used),
        "forward_return_is_audit_label_only": True,
        "production_activation_allowed": False,
        "policy_mutation_allowed": False,
        "live_trading_enabled": False,
        "recommended_next_step": "Design a default-OFF PIT-only concentrated leader-capture challenger from the best rule slices, then measure by broker-ledger replay.",
        "broad_baseline_rule": next((r for r in rules if r.get("rule") == "all_cap_or_replacement"), {}),
        "best_rule": best_selective_rule(rules),
        "rule_scan_path": str(output_dir / "rule_scan.csv"),
        "top_missed_path": str(output_dir / "top_missed_cap_replacement.csv"),
    }
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload, rules))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-selection-dir", default=DEFAULT_STOCK_SELECTION_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=30)
    args = parser.parse_args(argv)
    payload = run(Path(args.stock_selection_dir), Path(args.output_dir), top_n=args.top_n)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
