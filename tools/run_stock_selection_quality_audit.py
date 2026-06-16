#!/usr/bin/env python3
"""Explain selected names and ex-ante leaders missed by the operating books.

Measurement-only sidecar. It reads candidate/target artifacts already produced
by a rebuild and writes diagnostics under outputs/stock_selection_quality. It
does not mutate scores, target books, portfolio sizing, cash policy, universe,
or production gates.
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from historical_replay_lib import read_table, repo_path, safe_float, write_json, write_text


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/stock_selection_quality"
CASH_TICKER = "CASH"

COMMON_METADATA_COLUMNS = [
    "source_run_id",
    "source_commit_sha",
    "source_branch",
    "portfolio_policy",
    "metric_mode",
    "official_metric_source",
    "candidate_source",
    "target_book_source",
    "generated_at",
    "production_mutation_allowed",
]

FEATURE_COLUMNS = [
    "ticker",
    "rebalance_date",
    "portfolio",
    "selected",
    "target_weight",
    "lane",
    "theme",
    "sector",
    "subindustry",
    "leader_rank_ex_ante",
    "selected_rank",
    "was_selected",
    "was_missed_leader",
    "selection_reason",
    "rejection_reason",
    "binding_constraint",
    "cap_binding",
    "cash_binding",
    "data_missing_binding",
    "valuation_binding",
    "liquidity_binding",
    "rs_spy_1w",
    "rs_spy_1m",
    "rs_spy_3m",
    "rs_spy_6m",
    "rs_qqq_1w",
    "rs_qqq_1m",
    "rs_qqq_3m",
    "rs_qqq_6m",
    "rs_theme_1m",
    "rs_theme_3m",
    "rs_theme_6m",
    "forward_pe",
    "peg",
    "ev_ebitda",
    "ev_sales",
    "fcf_yield",
    "sector_relative_valuation",
    "revenue_growth",
    "fcf_margin",
    "gross_margin",
    "operating_margin",
    "cash_runway",
    "dilution_risk",
    "top7_score",
    "form4_score",
    "etf_score",
    "evidence_boost",
    "chase_risk",
    "liquidity_score",
    "atr",
    "volatility",
    "forward_21d_excess",
    "forward_63d_excess",
    "forward_126d_excess",
]

RS_SCORE_CANDIDATES = [
    "relative_strength_composite",
    "oneil_leadership_score",
    "rs_acceleration_score",
    "industry_group_strength_score",
    "etf_theme_leadership_score",
    "theme_leadership_score",
    "score",
    "score_total",
    "concentrated_score",
]

COLUMN_ALIASES = {
    "lane": ["portfolio_sleeve_label", "portfolio_sleeve_role", "candidate_lane", "lane"],
    "theme": ["theme", "portfolio_theme", "theme_label", "etf_theme", "industry_group"],
    "sector": ["sector", "Sector"],
    "subindustry": ["subindustry", "industry", "industry_group"],
    "rs_spy_1w": ["rs_spy_1w", "spy_relative_1w", "rel_spy_1w"],
    "rs_spy_1m": ["rs_spy_1m", "spy_relative_1m", "rel_spy_1m", "rs_benchmark_1m"],
    "rs_spy_3m": ["rs_spy_3m", "spy_relative_3m", "rel_spy_3m", "rs_benchmark_3m"],
    "rs_spy_6m": ["rs_spy_6m", "spy_relative_6m", "rel_spy_6m", "rs_benchmark_6m"],
    "rs_qqq_1w": ["rs_qqq_1w", "qqq_relative_1w", "rel_qqq_1w"],
    "rs_qqq_1m": ["rs_qqq_1m", "qqq_relative_1m", "rel_qqq_1m"],
    "rs_qqq_3m": ["rs_qqq_3m", "qqq_relative_3m", "rel_qqq_3m"],
    "rs_qqq_6m": ["rs_qqq_6m", "qqq_relative_6m", "rel_qqq_6m"],
    "rs_theme_1m": ["rs_theme_1m", "theme_rs_1m", "theme_relative_1m"],
    "rs_theme_3m": ["rs_theme_3m", "theme_rs_3m", "theme_relative_3m"],
    "rs_theme_6m": ["rs_theme_6m", "theme_rs_6m", "theme_relative_6m"],
    "forward_pe": ["forward_pe", "pe_forward", "fwd_pe"],
    "peg": ["peg", "peg_ratio"],
    "ev_ebitda": ["ev_ebitda"],
    "ev_sales": ["ev_sales", "ev_to_sales"],
    "fcf_yield": ["fcf_yield"],
    "sector_relative_valuation": ["sector_relative_valuation", "sector_rel_valuation"],
    "revenue_growth": ["revenue_growth", "sales_growth_yoy", "revenue_growth_yoy"],
    "fcf_margin": ["fcf_margin"],
    "gross_margin": ["gross_margin"],
    "operating_margin": ["operating_margin"],
    "cash_runway": ["cash_runway"],
    "dilution_risk": ["dilution_risk"],
    "top7_score": ["top7_score", "smart_money_shadow_score", "sec_13f_smart_money_score"],
    "form4_score": ["form4_score", "sec_form4_score", "sec_form4_open_market_buy_score"],
    "etf_score": ["etf_score", "etf_holdings_score", "etf_theme_leadership_score"],
    "evidence_boost": ["evidence_boost", "evidence_fusion_score", "early_evidence_score"],
    "chase_risk": ["chase_risk", "portfolio_stale_mega_leader_score", "portfolio_risk_entry_block_score"],
    "liquidity_score": ["liquidity_score", "dollar_vol_20d"],
    "atr": ["atr", "atr_14d"],
    "volatility": ["volatility", "volatility_63d"],
    "forward_21d_excess": ["forward_21d_excess", "forward_21d_return", "ret_fwd_21d"],
    "forward_63d_excess": ["forward_63d_excess", "forward_63d_return", "ret_fwd_63d"],
    "forward_126d_excess": ["forward_126d_excess", "forward_126d_return", "ret_fwd_126d"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_value(args: list[str], default: str = "unknown") -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo_path("."), text=True, stderr=subprocess.DEVNULL).strip() or default
    except Exception:
        return default


def _metadata(
    latest_run: Path,
    candidate_source: str,
    target_book_source: str,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "source_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "source_commit_sha": os.environ.get("GITHUB_SHA") or _git_value(["rev-parse", "--short", "HEAD"]),
        "source_branch": os.environ.get("GITHUB_REF_NAME") or _git_value(["branch", "--show-current"]),
        "portfolio_policy": os.environ.get("PORTFOLIO_POLICY", "alphaops_vnext_production"),
        "metric_mode": "broker_ledger_next_close",
        "official_metric_source": "outputs/account_evaluation/official_metrics.json",
        "candidate_source": candidate_source,
        "target_book_source": target_book_source,
        "generated_at": generated_at,
        "production_mutation_allowed": False,
        "latest_run": str(latest_run),
    }


def _normalize_ticker(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out = out[(out["ticker"] != "") & (out["ticker"] != CASH_TICKER)].copy()
    return out


def _normalize_date(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "rebalance_date" not in out.columns:
        out["rebalance_date"] = "latest"
        return out
    parsed = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out["rebalance_date"] = parsed.dt.strftime("%Y-%m-%d").fillna(out["rebalance_date"].astype(str)).fillna("latest")
    return out


def _first_existing(frame: pd.DataFrame, names: list[str]) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return frame[name]
    return pd.Series([""] * len(frame), index=frame.index)


def _numeric(frame: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name not in frame.columns:
        return pd.Series([default] * len(frame), index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce").fillna(default).astype(float)


def _load_candidates(latest_run: Path, candidate_book: Path | None = None) -> tuple[pd.DataFrame, str]:
    paths = []
    if candidate_book is not None:
        paths.append(candidate_book)
    paths.extend(
        [
            latest_run / "reports" / "candidate_replay_book.csv",
            latest_run / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
            latest_run / "scored_latest.csv",
        ]
    )
    for path in paths:
        frame = _normalize_ticker(read_table(path))
        if not frame.empty:
            return _normalize_date(frame), str(path)
    return pd.DataFrame(), ""


def _load_target(path: Path, portfolio: str, fallback_date: str) -> pd.DataFrame:
    frame = _normalize_ticker(read_table(path))
    if frame.empty:
        return pd.DataFrame(columns=["ticker", "rebalance_date", "portfolio", "target_weight"])
    frame = _normalize_date(frame)
    if "rebalance_date" not in frame.columns:
        frame["rebalance_date"] = fallback_date
    frame["portfolio"] = portfolio
    if "weight" in frame.columns:
        frame["target_weight"] = pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0)
    elif "target_weight" in frame.columns:
        frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="coerce").fillna(0.0)
    else:
        frame["target_weight"] = 0.0
    return frame[["ticker", "rebalance_date", "portfolio", "target_weight"]].copy()


def _target_cash_by_date(path: Path) -> dict[str, float]:
    frame = read_table(path)
    if frame.empty or "ticker" not in frame.columns:
        return {}
    d = frame.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = _normalize_date(d)
    weight_col = "weight" if "weight" in d.columns else "target_weight" if "target_weight" in d.columns else ""
    if not weight_col:
        return {}
    d["_weight"] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0)
    return {
        str(date): float(group.loc[group["ticker"].eq(CASH_TICKER), "_weight"].sum())
        for date, group in d.groupby("rebalance_date", dropna=False)
    }


def _load_targets(latest_run: Path, fallback_date: str) -> tuple[pd.DataFrame, str, dict[tuple[str, str], float]]:
    specs = [
        ("main", latest_run / "reports" / "operating_main_target_book.csv"),
        ("concentrated", latest_run / "reports" / "operating_concentrated_target_book.csv"),
        ("main", latest_run / "portfolio_latest.csv"),
        ("concentrated", latest_run / "concentrated_portfolio_latest.csv"),
    ]
    frames = []
    sources = []
    cash: dict[tuple[str, str], float] = {}
    for portfolio, path in specs:
        frame = _load_target(path, portfolio, fallback_date)
        if not frame.empty:
            frames.append(frame)
            sources.append(str(path))
        for date, cash_weight in _target_cash_by_date(path).items():
            cash[(portfolio, date)] = max(cash.get((portfolio, date), 0.0), cash_weight)
    if not frames:
        return pd.DataFrame(columns=["ticker", "rebalance_date", "portfolio", "target_weight"]), "", cash
    targets = pd.concat(frames, ignore_index=True)
    targets = targets.drop_duplicates(["portfolio", "rebalance_date", "ticker"], keep="last")
    return targets, ";".join(sources), cash


def _prepare_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    out = candidates.copy()
    for canonical, aliases in COLUMN_ALIASES.items():
        if canonical not in out.columns:
            out[canonical] = _first_existing(out, aliases)
    for col in FEATURE_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    score = pd.Series(0.0, index=out.index, dtype=float)
    used = 0
    for col in RS_SCORE_CANDIDATES:
        if col not in out.columns:
            continue
        values = pd.to_numeric(out[col], errors="coerce")
        if values.notna().sum() == 0:
            continue
        ranks = values.groupby(out["rebalance_date"]).rank(pct=True, method="average").fillna(0.0)
        score += ranks
        used += 1
    if used == 0:
        score = pd.Series(0.0, index=out.index, dtype=float)
    else:
        score = score / float(used)
    out["_leader_score_ex_ante"] = score
    out["leader_rank_ex_ante"] = (
        out.groupby("rebalance_date")["_leader_score_ex_ante"]
        .rank(ascending=False, method="first")
        .astype(int)
    )
    return out


def _nearest_candidate_slice(candidates: pd.DataFrame, date: str) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    if date in set(candidates["rebalance_date"].astype(str)):
        return candidates[candidates["rebalance_date"].astype(str).eq(date)].copy()
    if date == "latest":
        latest_date = sorted(candidates["rebalance_date"].astype(str).unique())[-1]
        return candidates[candidates["rebalance_date"].astype(str).eq(latest_date)].copy()
    return candidates.copy()


def _cash_binding(cash_by_date: dict[tuple[str, str], float], portfolio: str, date: str) -> bool:
    return safe_float(cash_by_date.get((portfolio, date), 0.0), 0.0) >= 0.10


def _boolish(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return default


def _binding_reason(row: pd.Series) -> tuple[str, str, bool, bool, bool, bool, bool]:
    data_missing = bool(row.get("_candidate_missing", False))
    cash_binding = bool(row.get("_cash_binding", False))
    cap_binding = bool(row.get("_cap_binding", False))
    valuation_binding = safe_float(row.get("forward_pe"), 0.0) >= 90.0 or safe_float(row.get("ev_sales"), 0.0) >= 30.0
    liquidity_binding = safe_float(row.get("liquidity_score"), 0.0) <= 0.05
    if data_missing:
        return "data_missing", "data_missing_binding", cap_binding, cash_binding, True, valuation_binding, liquidity_binding
    if not _boolish(row.get("portfolio_candidate_minimum_pass"), default=True):
        return "candidate_gate", "candidate_gate", cap_binding, cash_binding, data_missing, valuation_binding, liquidity_binding
    if safe_float(row.get("portfolio_risk_entry_block_score"), 0.0) >= 0.55:
        return "risk_entry_block", "risk_entry_block", cap_binding, cash_binding, data_missing, valuation_binding, liquidity_binding
    if liquidity_binding:
        return "liquidity", "liquidity_binding", cap_binding, cash_binding, data_missing, valuation_binding, True
    if valuation_binding:
        return "valuation", "valuation_binding", cap_binding, cash_binding, data_missing, True, liquidity_binding
    if cash_binding:
        return "cash", "cash_binding", cap_binding, True, data_missing, valuation_binding, liquidity_binding
    if cap_binding:
        return "cap_or_replacement", "cap_binding", True, cash_binding, data_missing, valuation_binding, liquidity_binding
    return "unknown_requires_investigation", "unknown", cap_binding, cash_binding, data_missing, valuation_binding, liquidity_binding


def _selection_reason(row: pd.Series) -> str:
    reasons = []
    if safe_float(row.get("_leader_score_ex_ante"), 0.0) >= 0.75:
        reasons.append("ex_ante_leader")
    if safe_float(row.get("rs_spy_3m"), 0.0) > 0 or safe_float(row.get("rs_qqq_3m"), 0.0) > 0:
        reasons.append("benchmark_relative_strength")
    if safe_float(row.get("rs_theme_3m"), 0.0) > 0 or str(row.get("theme", "")).strip():
        reasons.append("theme_leadership")
    if safe_float(row.get("evidence_boost"), 0.0) > 0 or safe_float(row.get("top7_score"), 0.0) > 0:
        reasons.append("evidence_support")
    if safe_float(row.get("target_weight"), 0.0) > 0:
        reasons.append("target_book_weight")
    return ";".join(reasons) if reasons else "selected_by_existing_engine"


def _output_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in [*COMMON_METADATA_COLUMNS, *FEATURE_COLUMNS]:
        if col not in out.columns:
            out[col] = ""
    return out[[*COMMON_METADATA_COLUMNS, *FEATURE_COLUMNS]].copy()


def _theme_contains(value: Any, tokens: tuple[str, ...]) -> bool:
    text = str(value or "").lower()
    return any(token in text for token in tokens)


def _capture_table(frame: pd.DataFrame, group_col: str, tokens: tuple[str, ...] | None = None) -> pd.DataFrame:
    d = frame.copy()
    if tokens is not None:
        mask = d[[c for c in ("theme", "sector", "subindustry") if c in d.columns]].apply(
            lambda row: any(_theme_contains(v, tokens) for v in row),
            axis=1,
        )
        d = d[mask].copy()
    if d.empty:
        return pd.DataFrame(columns=[group_col, "rebalance_date", "portfolio", "leader_count", "selected_count", "capture_rate"])
    d[group_col] = d[group_col].fillna("").astype(str).replace("", "unassigned")
    rows = []
    for (date, portfolio, group), g in d.groupby(["rebalance_date", "portfolio", group_col], dropna=False):
        leader_count = int(len(g))
        selected_count = int(pd.Series(g["was_selected"]).astype(bool).sum())
        rows.append(
            {
                "rebalance_date": date,
                "portfolio": portfolio,
                group_col: group,
                "leader_count": leader_count,
                "selected_count": selected_count,
                "capture_rate": float(selected_count / leader_count) if leader_count else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values(["rebalance_date", "portfolio", "capture_rate"], ascending=[True, True, False])


def run(
    latest_run: Path,
    output_dir: Path,
    candidate_book: Path | None = None,
    leaders_per_date: int = 25,
) -> dict[str, Any]:
    generated_at = _now_iso()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_raw, candidate_source = _load_candidates(latest_run, candidate_book)
    if candidates_raw.empty:
        payload = {
            "status": "blocked",
            "reason": "missing candidate_replay_book/scored_latest",
            **_metadata(latest_run, candidate_source, "", generated_at),
        }
        write_json(output_dir / "summary.json", payload)
        write_text(output_dir / "report.md", "# Stock Selection Quality Audit\n\nBlocked: missing candidate data.\n")
        return payload

    candidates = _prepare_candidates(candidates_raw)
    latest_candidate_date = sorted(candidates["rebalance_date"].astype(str).unique())[-1]
    targets, target_source, cash_by_date = _load_targets(latest_run, latest_candidate_date)
    meta = _metadata(latest_run, candidate_source, target_source, generated_at)

    selected_rows: list[pd.DataFrame] = []
    target_keys = set()
    for (portfolio, date), group in targets.groupby(["portfolio", "rebalance_date"], dropna=False):
        date = str(date)
        cand_slice = _nearest_candidate_slice(candidates, date)
        selected = group.merge(cand_slice, on=["ticker", "rebalance_date"], how="left", suffixes=("", "_candidate"))
        if selected.empty:
            continue
        selected["_candidate_missing"] = selected["_leader_score_ex_ante"].isna()
        selected["_cash_binding"] = _cash_binding(cash_by_date, str(portfolio), date)
        selected["_cap_binding"] = False
        selected["portfolio"] = str(portfolio)
        selected["selected"] = True
        selected["was_selected"] = True
        selected["was_missed_leader"] = False
        selected["selected_rank"] = selected["leader_rank_ex_ante"].fillna("").astype(str)
        selected["selection_reason"] = selected.apply(_selection_reason, axis=1)
        selected["rejection_reason"] = ""
        selected["binding_constraint"] = ""
        selected_rows.append(selected)
        for ticker in selected["ticker"].astype(str):
            target_keys.add((str(portfolio), date, ticker))

    selected_audit = pd.concat(selected_rows, ignore_index=True) if selected_rows else pd.DataFrame()
    if not selected_audit.empty:
        for key, value in meta.items():
            selected_audit[key] = value
        selected_audit = _output_columns(selected_audit)
    else:
        selected_audit = pd.DataFrame(columns=[*COMMON_METADATA_COLUMNS, *FEATURE_COLUMNS])

    available_rows: list[pd.DataFrame] = []
    target_groups = list(targets.groupby(["portfolio", "rebalance_date"], dropna=False))
    if not target_groups:
        target_groups = [("main", latest_candidate_date), ("concentrated", latest_candidate_date)]  # type: ignore[list-item]
    for key in target_groups:
        if isinstance(key[0], tuple):
            (portfolio, date), group = key
        else:
            portfolio, date = key  # type: ignore[misc]
            group = pd.DataFrame()
        portfolio = str(portfolio)
        date = str(date)
        cand_slice = _nearest_candidate_slice(candidates, date)
        leaders = cand_slice.sort_values(["_leader_score_ex_ante", "leader_rank_ex_ante"], ascending=[False, True]).head(int(leaders_per_date)).copy()
        if leaders.empty:
            continue
        selected_tickers = set(group["ticker"].astype(str)) if not group.empty else set()
        selected_count = len(selected_tickers)
        leaders["portfolio"] = portfolio
        leaders["selected"] = leaders["ticker"].isin(selected_tickers)
        leaders["was_selected"] = leaders["selected"]
        leaders["was_missed_leader"] = ~leaders["selected"]
        leaders["target_weight"] = leaders["ticker"].map({str(r["ticker"]): safe_float(r.get("target_weight"), 0.0) for _, r in group.iterrows()}) if not group.empty else 0.0
        leaders["selected_rank"] = leaders["leader_rank_ex_ante"].where(leaders["selected"], "")
        leaders["_candidate_missing"] = False
        leaders["_cash_binding"] = _cash_binding(cash_by_date, portfolio, date)
        leaders["_cap_binding"] = (~leaders["selected"]) & (selected_count >= 5)
        leaders["selection_reason"] = leaders.apply(lambda row: _selection_reason(row) if bool(row.get("selected")) else "", axis=1)
        binding = leaders.apply(_binding_reason, axis=1, result_type="expand")
        binding.columns = [
            "rejection_reason",
            "binding_constraint",
            "cap_binding",
            "cash_binding",
            "data_missing_binding",
            "valuation_binding",
            "liquidity_binding",
        ]
        leaders.loc[leaders["selected"], ["rejection_reason", "binding_constraint"]] = ""
        for col in binding.columns:
            leaders[col] = binding[col]
        leaders.loc[leaders["selected"], ["cap_binding", "cash_binding", "data_missing_binding", "valuation_binding", "liquidity_binding"]] = False
        for k, value in meta.items():
            leaders[k] = value
        available_rows.append(leaders)

    available = pd.concat(available_rows, ignore_index=True) if available_rows else pd.DataFrame()
    available = _output_columns(available) if not available.empty else pd.DataFrame(columns=[*COMMON_METADATA_COLUMNS, *FEATURE_COLUMNS])
    missed = available[available["was_missed_leader"].astype(bool)].copy() if not available.empty else available.copy()

    selected_audit.to_csv(output_dir / "selected_names_audit.csv", index=False)
    missed.to_csv(output_dir / "missed_leaders_audit.csv", index=False)
    available.to_csv(output_dir / "selected_vs_available_leaders.csv", index=False)
    semi = _capture_table(available, "theme", ("semi", "semiconductor", "chip", "ai", "nvda", "soxx", "smh"))
    semi.to_csv(output_dir / "semiconductor_leader_capture.csv", index=False)
    theme = _capture_table(available, "theme")
    theme.to_csv(output_dir / "theme_leader_capture.csv", index=False)
    rejection_summary = (
        missed.groupby(["portfolio", "rejection_reason", "binding_constraint"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["portfolio", "count"], ascending=[True, False])
        if not missed.empty
        else pd.DataFrame(columns=["portfolio", "rejection_reason", "binding_constraint", "count"])
    )
    rejection_summary.to_csv(output_dir / "rejection_reason_summary.csv", index=False)

    payload = {
        "status": "completed",
        "schema_version": "stock_selection_quality_audit_v1",
        **meta,
        "candidate_rows": int(len(candidates)),
        "selected_rows": int(len(selected_audit)),
        "available_leader_rows": int(len(available)),
        "missed_leader_rows": int(len(missed)),
        "leaders_per_date": int(leaders_per_date),
        "rejection_reason_counts": {
            str(k): int(v)
            for k, v in (missed["rejection_reason"].value_counts(dropna=False).to_dict() if not missed.empty else {}).items()
        },
    }
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", _render_report(payload))
    return payload


def _render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Stock Selection Quality Audit",
        "",
        "Measurement-only diagnostic. No strategy, target-book, sizing, cash-policy, universe, or gate mutation.",
        "",
        "## Summary",
        "",
        f"- status: `{payload.get('status')}`",
        f"- metric mode: `{payload.get('metric_mode')}`",
        f"- production mutation allowed: `{payload.get('production_mutation_allowed')}`",
        f"- candidate rows: {payload.get('candidate_rows', 0)}",
        f"- selected rows: {payload.get('selected_rows', 0)}",
        f"- available ex-ante leader rows: {payload.get('available_leader_rows', 0)}",
        f"- missed ex-ante leader rows: {payload.get('missed_leader_rows', 0)}",
        "",
        "## Rejection Reasons",
        "",
    ]
    counts = payload.get("rejection_reason_counts") or {}
    if counts:
        for key, value in sorted(counts.items(), key=lambda kv: str(kv[0])):
            lines.append(f"- `{key}`: {value}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Interpretation Rules",
            "",
            "- Missed leaders are defined from T-date ex-ante features only.",
            "- Forward returns are labels for review, not live selection signals.",
            "- Top7/Form4/ETF evidence cannot be a standalone buy reason.",
            "- Missing evidence is not a penalty.",
            "- Negative FCF is not a hard reject for Emerging lane.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--candidate-book", default="")
    parser.add_argument("--leaders-per-date", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else None
    payload = run(
        repo_path(args.latest_run),
        repo_path(args.output_dir),
        candidate_book=candidate_book,
        leaders_per_date=int(args.leaders_per_date),
    )
    print(f"[stock-selection-quality] {payload.get('status')} -> {repo_path(args.output_dir)}")
    return 0 if payload.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
