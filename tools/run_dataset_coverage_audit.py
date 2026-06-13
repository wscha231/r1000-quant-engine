#!/usr/bin/env python3
"""Audit dataset coverage and likely missing-name causes for a rebuild.

This sidecar is intentionally read-only. It helps answer whether poor portfolio
coverage is a data problem, a universe problem, or a selection/ranking problem.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/reports"
DEFAULT_WATCHLIST = (
    "SNDK,INTC,AMD,ARM,ASML,TSM,AVGO,QCOM,MU,WDC,STX,LITE,CIEN,GLW,AMAT,KLAC,LRCX,MRVL,"
    "ANET,VRT,SMCI,DELL,HPE,COHR,GEV,PLTR,NVDA,GOOGL,WMT,OKLO,SMR"
)

LATEST_COVERAGE_COLUMNS = [
    "current_price_live",
    "px",
    "market_cap_live",
    "mktcap",
    "dollar_vol_20d",
    "revenues_ttm",
    "gross_profit_ttm",
    "op_income_ttm",
    "net_income_ttm",
    "ocf_ttm",
    "capex_ttm",
    "revenue_growth_final",
    "rev_growth_accel_4q",
    "gross_margins",
    "operating_margins",
    "roe_proxy",
    "eps_revision_score",
    "revision_score",
    "eps_revision_proxy",
    "actual_results_score",
    "event_reaction_score",
    "ownership_flow_pillar_score",
    "insider_cluster_boost_score",
    "leader_emergence_score",
    "dynamic_leader_score",
    "h6_dynamic_leader_score",
    "oneil_leadership_score",
    "growth_onset_composite",
    "score_anticipatory_growth",
    "selection_market_confirmation_score",
    "entry_quality_score",
    "breakout_setup_quality_score",
    "selection_confirmation_score",
    "rs_acceleration_score",
    "relative_strength_composite",
]

HISTORICAL_COVERAGE_COLUMNS = [
    "dollar_vol_20d",
    "market_cap_live",
    "mktcap",
    "revenues_ttm",
    "gross_profit_ttm",
    "op_income_ttm",
    "net_income_ttm",
    "ocf_ttm",
    "capex_ttm",
    "gross_margins",
    "operating_margins",
    "roe_proxy",
    "sales_growth_yoy",
    "eps_growth_yoy",
    "op_income_growth_yoy",
    "ocf_growth_yoy",
    "revenue_growth_final",
    "entry_quality_score",
    "portfolio_monster_early_score",
    "eps_revision_score",
    "portfolio_risk_entry_block_score",
    "r_1m",
    "r_6m",
    "r_12m",
    "period_forward_return",
]

EVIDENCE_COVERAGE_COLUMNS = [
    "available_from",
    "latest_available_from",
    "latest_13f_available_from",
    "latest_etf_available_from",
    "sec_form4_score",
    "sec_13f_score",
    "sec_13f_smart_money_score",
    "institutional_evidence_score",
    "early_evidence_score",
    "sec_combined_evidence_score",
    "leader_onset_sec_v3_score",
    "etf_holdings_score",
    "etf_theme_leadership_score",
    "smart_money_shadow_score",
    "smart_money_evidence_source_count",
    "evidence_fusion_score",
    "valuation_support_score",
    "top7_manager_discovery_lane_score",
    "top7_support_boost",
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


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


def numeric_coverage(df: pd.DataFrame, columns: list[str], scope: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for col in columns:
        if col not in df.columns:
            rows.append(
                {
                    "scope": scope,
                    "column": col,
                    "present": False,
                    "nonnull_ratio": 0.0,
                    "numeric_ratio": 0.0,
                    "nonzero_ratio": 0.0,
                }
            )
            continue
        raw = df[col]
        num = pd.to_numeric(raw, errors="coerce")
        rows.append(
            {
                "scope": scope,
                "column": col,
                "present": True,
                "nonnull_ratio": float(raw.notna().mean()) if len(raw) else 0.0,
                "numeric_ratio": float(num.notna().mean()) if len(num) else 0.0,
                "nonzero_ratio": float(num.fillna(0).ne(0).mean()) if len(num) else 0.0,
            }
        )
    return rows


def column_coverage(df: pd.DataFrame, columns: list[str], scope: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for col in columns:
        if col not in df.columns:
            rows.append(
                {
                    "scope": scope,
                    "column": col,
                    "present": False,
                    "nonnull_ratio": 0.0,
                    "numeric_ratio": 0.0,
                    "nonzero_ratio": 0.0,
                    "nonblank_ratio": 0.0,
                }
            )
            continue
        raw = df[col]
        text = raw.fillna("").astype(str).str.strip()
        num = pd.to_numeric(raw, errors="coerce")
        rows.append(
            {
                "scope": scope,
                "column": col,
                "present": True,
                "nonnull_ratio": float(raw.notna().mean()) if len(raw) else 0.0,
                "numeric_ratio": float(num.notna().mean()) if len(num) else 0.0,
                "nonzero_ratio": float(num.fillna(0).ne(0).mean()) if len(num) else 0.0,
                "nonblank_ratio": float(text.ne("").mean()) if len(text) else 0.0,
            }
        )
    return rows


def effective_numeric_coverage(
    df: pd.DataFrame,
    columns: list[str],
    scope: str,
    output_column: str,
) -> dict[str, Any]:
    effective = pd.Series(pd.NA, index=df.index, dtype="object")
    present_inputs: list[str] = []
    for col in columns:
        if col not in df.columns:
            continue
        present_inputs.append(col)
        values = pd.to_numeric(df[col], errors="coerce")
        effective = effective.where(effective.notna(), values)
    num = pd.to_numeric(effective, errors="coerce")
    return {
        "scope": scope,
        "column": output_column,
        "present": bool(present_inputs),
        "input_columns": ",".join(present_inputs),
        "nonnull_ratio": float(num.notna().mean()) if len(num) else 0.0,
        "numeric_ratio": float(num.notna().mean()) if len(num) else 0.0,
        "nonzero_ratio": float(num.fillna(0).ne(0).mean()) if len(num) else 0.0,
    }


def value_counts_rows(df: pd.DataFrame, col: str, scope: str, limit: int = 20) -> list[dict[str, Any]]:
    if df.empty or col not in df.columns:
        return []
    counts = df[col].fillna("NA").astype(str).value_counts().head(limit)
    return [{"scope": scope, "field": col, "value": str(k), "count": int(v)} for k, v in counts.items()]


def watchlist_rows(scored: pd.DataFrame, book: pd.DataFrame, tickers: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ticker_set = {str(t).upper() for t in tickers if str(t).strip()}
    latest = scored.copy() if not scored.empty else pd.DataFrame()
    if not latest.empty and "ticker" in latest.columns:
        latest["_ticker_upper"] = latest["ticker"].astype(str).str.upper()
    historical = book.copy() if not book.empty else pd.DataFrame()
    if not historical.empty and "ticker" in historical.columns:
        historical["_ticker_upper"] = historical["ticker"].astype(str).str.upper()
    for ticker in sorted(ticker_set):
        latest_hit = latest[latest["_ticker_upper"].eq(ticker)] if "_ticker_upper" in latest.columns else pd.DataFrame()
        hist_hit = historical[historical["_ticker_upper"].eq(ticker)] if "_ticker_upper" in historical.columns else pd.DataFrame()
        row: dict[str, Any] = {
            "ticker": ticker,
            "in_latest_scored": bool(not latest_hit.empty),
            "in_historical_book": bool(not hist_hit.empty),
            "historical_first": "",
            "historical_last": "",
            "historical_months": 0,
            "latest_sleeve": "",
            "latest_gate": "",
            "latest_score": None,
            "latest_market_cap_live": None,
            "latest_revenues_ttm_present": False,
            "latest_op_income_ttm_present": False,
            "latest_eps_revision_nonzero": False,
            "latest_monster_early_score": None,
            "latest_entry_quality_score": None,
            "likely_gap": "not_in_latest_universe",
        }
        if not hist_hit.empty and "rebalance_date" in hist_hit.columns:
            row["historical_first"] = str(hist_hit["rebalance_date"].min())
            row["historical_last"] = str(hist_hit["rebalance_date"].max())
            row["historical_months"] = int(hist_hit["rebalance_date"].nunique())
        if not latest_hit.empty:
            r = latest_hit.iloc[0]
            row["latest_sleeve"] = str(r.get("portfolio_sleeve_label", ""))
            row["latest_gate"] = str(r.get("portfolio_candidate_gate_label", ""))
            row["latest_score"] = float(pd.to_numeric(pd.Series([r.get("score")]), errors="coerce").iloc[0]) if "score" in latest_hit.columns else None
            market_cap_live = pd.to_numeric(pd.Series([r.get("market_cap_live")]), errors="coerce")
            market_cap_fallback = pd.to_numeric(pd.Series([r.get("mktcap")]), errors="coerce")
            row["latest_market_cap_live"] = float(market_cap_live.fillna(market_cap_fallback).fillna(0).iloc[0])
            row["latest_revenues_ttm_present"] = bool(pd.notna(r.get("revenues_ttm")))
            row["latest_op_income_ttm_present"] = bool(pd.notna(r.get("op_income_ttm")))
            row["latest_eps_revision_nonzero"] = bool(pd.to_numeric(pd.Series([r.get("eps_revision_score")]), errors="coerce").fillna(0).iloc[0] != 0)
            row["latest_monster_early_score"] = float(pd.to_numeric(pd.Series([r.get("portfolio_monster_early_score")]), errors="coerce").fillna(0).iloc[0]) if "portfolio_monster_early_score" in latest_hit.columns else None
            row["latest_entry_quality_score"] = float(pd.to_numeric(pd.Series([r.get("entry_quality_score")]), errors="coerce").fillna(0).iloc[0]) if "entry_quality_score" in latest_hit.columns else None
            if row["latest_sleeve"] and row["latest_sleeve"] != "unassigned":
                row["likely_gap"] = "selected_candidate_not_portfolio_ranked_high_enough"
            elif row["latest_gate"] == "rejected" or row["latest_sleeve"] == "unassigned":
                row["likely_gap"] = "selection_gate_or_rank_rejected"
            else:
                row["likely_gap"] = "present_but_unclassified"
        elif not hist_hit.empty:
            row["likely_gap"] = "historical_only_not_current_latest_universe"
        rows.append(row)
    return rows


def render_report(payload: dict[str, Any], output_dir: Path) -> str:
    top_gaps = payload.get("coverage_gaps", [])[:12]
    missing_columns = payload.get("missing_columns", [])[:16]
    watch = payload.get("watchlist", [])
    effective_caps = payload.get("effective_market_cap_coverage", [])
    source_universe = payload.get("historical_source_universe_top", [])[:8]
    evidence_summary = payload.get("sec_enriched_evidence_summary", {})
    lines = [
        "# Dataset Coverage Audit",
        "",
        f"- latest run: `{payload.get('latest_run')}`",
        f"- scored latest rows: {payload.get('latest_scored_rows')}",
        f"- latest scored date: {payload.get('latest_scored_date')}",
        f"- historical candidate rows: {payload.get('historical_candidate_rows')}",
        f"- historical candidate tickers: {payload.get('historical_candidate_tickers')}",
        f"- historical months: {payload.get('historical_months')}",
        f"- historical candidate last date: {payload.get('historical_candidate_last_date')}",
        f"- SEC-enriched candidate present: {payload.get('sec_enriched_candidate_present')}",
        f"- SEC-enriched candidate rows: {payload.get('sec_enriched_candidate_rows')}",
        "",
        "## Universe Source",
        "",
    ]
    for row in source_universe:
        lines.append(f"- `{row.get('value')}`: {row.get('count')}")
    lines.extend(
        [
            "",
            "## Evidence Utilization",
            "",
            f"- rows with SEC evidence: {evidence_summary.get('rows_with_sec_evidence', 0)}",
            f"- rows with 13F evidence: {evidence_summary.get('rows_with_13f_evidence', 0)}",
            f"- rows with ETF evidence: {evidence_summary.get('rows_with_etf_evidence', 0)}",
            f"- rows with smart-money evidence: {evidence_summary.get('rows_with_smart_money_evidence', 0)}",
            f"- coverage ratio: {float(evidence_summary.get('coverage_ratio', 0.0) or 0.0):.1%}",
            f"- 13F coverage ratio: {float(evidence_summary.get('coverage_13f_ratio', 0.0) or 0.0):.1%}",
            "",
            "## Effective Market Cap Coverage",
            "",
        ]
    )
    for row in effective_caps:
        lines.append(
            f"- `{row['scope']}` effective cap numeric={row['numeric_ratio']:.1%}, "
            f"inputs=`{row.get('input_columns', '')}`"
        )
    lines.extend(
        [
            "",
            "## Largest Coverage Gaps",
            "",
        ]
    )
    for row in top_gaps:
        lines.append(
            f"- `{row['scope']}.{row['column']}` numeric={row['numeric_ratio']:.1%}, nonzero={row['nonzero_ratio']:.1%}"
        )
    if missing_columns:
        lines.extend(["", "## Missing Audit Columns", ""])
        for row in missing_columns:
            lines.append(f"- `{row['scope']}.{row['column']}`")
    lines.extend(["", "## Watchlist Gaps", ""])
    for row in watch:
        lines.append(
            f"- `{row['ticker']}`: {row['likely_gap']}; latest={row['in_latest_scored']}; "
            f"hist_months={row['historical_months']}; sleeve=`{row['latest_sleeve']}`; score={row['latest_score']}"
        )
    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- `{output_dir / 'dataset_coverage_audit.json'}`",
            f"- `{output_dir / 'dataset_coverage_audit_coverage.csv'}`",
            f"- `{output_dir / 'dataset_coverage_audit_watchlist.csv'}`",
            f"- `{output_dir / 'dataset_coverage_audit_distributions.csv'}`",
            "",
        ]
    )
    return "\n".join(lines)


def run(latest_run: Path, output_dir: Path, watchlist: list[str]) -> dict[str, Any]:
    scored = read_csv(latest_run / "scored_latest.csv")
    book = read_csv(latest_run / "reports" / "candidate_replay_book.csv")
    sec_enriched_book = read_csv(latest_run / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv")
    sec_enriched_summary = read_json(latest_run / "sec_enriched_candidate_replay" / "summary.json")
    baseline = read_json(latest_run / "reports" / "baseline_registry.json")
    output_dir.mkdir(parents=True, exist_ok=True)

    coverage_rows = numeric_coverage(scored, LATEST_COVERAGE_COLUMNS, "latest_scored")
    coverage_rows.append(
        effective_numeric_coverage(
            scored,
            ["market_cap_live", "mktcap"],
            "latest_scored",
            "effective_market_cap_usd",
        )
    )
    if not book.empty:
        coverage_rows.extend(numeric_coverage(book, HISTORICAL_COVERAGE_COLUMNS, "historical_candidate_book"))
        coverage_rows.extend(column_coverage(book, EVIDENCE_COVERAGE_COLUMNS, "historical_candidate_book"))
        coverage_rows.append(
            effective_numeric_coverage(
                book,
                ["market_cap_live", "mktcap"],
                "historical_candidate_book",
                "effective_market_cap_usd",
            )
        )
    if not sec_enriched_book.empty:
        coverage_rows.extend(column_coverage(sec_enriched_book, EVIDENCE_COVERAGE_COLUMNS, "sec_enriched_candidate_book"))
    coverage = pd.DataFrame(coverage_rows)
    coverage.to_csv(output_dir / "dataset_coverage_audit_coverage.csv", index=False)

    dist_rows: list[dict[str, Any]] = []
    for col in ["universe_source", "source_universe", "fundamental_lane_label", "portfolio_candidate_gate_label", "portfolio_sleeve_label", "sector"]:
        dist_rows.extend(value_counts_rows(scored, col, "latest_scored"))
    for col in ["source_universe", "portfolio_sleeve_label", "sector"]:
        dist_rows.extend(value_counts_rows(book, col, "historical_candidate_book"))
    for col in ["source_universe", "sector"]:
        dist_rows.extend(value_counts_rows(sec_enriched_book, col, "sec_enriched_candidate_book"))
    pd.DataFrame(dist_rows).to_csv(output_dir / "dataset_coverage_audit_distributions.csv", index=False)

    watch = watchlist_rows(scored, book, watchlist)
    pd.DataFrame(watch).to_csv(output_dir / "dataset_coverage_audit_watchlist.csv", index=False)

    missing_columns = sorted(
        [row for row in coverage_rows if not row.get("present")],
        key=lambda row: (str(row["scope"]), str(row["column"])),
    )
    gap_rows = sorted(
        [row for row in coverage_rows if row.get("present") and float(row.get("numeric_ratio", 0.0)) < 0.80],
        key=lambda row: (str(row["scope"]), float(row.get("numeric_ratio", 0.0))),
    )
    latest_scored_date = ""
    if not scored.empty:
        for col in ("feature_date", "rebalance_date"):
            if col in scored.columns:
                latest_scored_date = str(pd.to_datetime(scored[col], errors="coerce").max().date())
                break
    historical_last_date = ""
    if not book.empty and "rebalance_date" in book.columns:
        historical_last_date = str(pd.to_datetime(book["rebalance_date"], errors="coerce").max().date())
    sec_enriched_last_date = ""
    if not sec_enriched_book.empty and "rebalance_date" in sec_enriched_book.columns:
        sec_enriched_last_date = str(pd.to_datetime(sec_enriched_book["rebalance_date"], errors="coerce").max().date())
    historical_source_universe_top = value_counts_rows(book, "source_universe", "historical_candidate_book", limit=12)
    payload = {
        "status": "completed",
        "latest_run": str(latest_run),
        "baseline_git_commit": baseline.get("git_commit"),
        "latest_scored_rows": int(len(scored)),
        "latest_scored_date": latest_scored_date,
        "historical_candidate_rows": int(len(book)),
        "historical_candidate_tickers": int(book["ticker"].nunique()) if not book.empty and "ticker" in book.columns else 0,
        "historical_months": int(book["rebalance_date"].nunique()) if not book.empty and "rebalance_date" in book.columns else 0,
        "historical_candidate_last_date": historical_last_date,
        "historical_source_universe_top": historical_source_universe_top,
        "sec_enriched_candidate_present": bool(not sec_enriched_book.empty),
        "sec_enriched_candidate_rows": int(len(sec_enriched_book)),
        "sec_enriched_candidate_tickers": int(sec_enriched_book["ticker"].nunique()) if not sec_enriched_book.empty and "ticker" in sec_enriched_book.columns else 0,
        "sec_enriched_candidate_last_date": sec_enriched_last_date,
        "sec_enriched_evidence_summary": {
            key: sec_enriched_summary.get(key)
            for key in [
                "status",
                "rows_with_sec_evidence",
                "rows_with_13f_evidence",
                "rows_with_etf_evidence",
                "rows_with_smart_money_evidence",
                "coverage_ratio",
                "coverage_13f_ratio",
                "coverage_etf_ratio",
                "coverage_smart_money_ratio",
                "score_total_changed",
                "production_activation_allowed",
                "research_only",
            ]
        },
        "coverage_gaps": gap_rows,
        "effective_market_cap_coverage": [
            row for row in coverage_rows if row.get("column") == "effective_market_cap_usd"
        ],
        "missing_columns": missing_columns,
        "watchlist": watch,
        "outputs": {
            "coverage_csv": str(output_dir / "dataset_coverage_audit_coverage.csv"),
            "watchlist_csv": str(output_dir / "dataset_coverage_audit_watchlist.csv"),
            "distributions_csv": str(output_dir / "dataset_coverage_audit_distributions.csv"),
        },
        "research_only": True,
    }
    write_json(output_dir / "dataset_coverage_audit.json", payload)
    (output_dir / "dataset_coverage_audit.md").write_text(render_report(payload, output_dir), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--watchlist", default=DEFAULT_WATCHLIST)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        repo_path(args.latest_run),
        repo_path(args.output_dir),
        [item.strip().upper() for item in str(args.watchlist).split(",") if item.strip()],
    )
    print(f"[dataset-audit] status={payload['status']} rows={payload['latest_scored_rows']} wrote {repo_path(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
