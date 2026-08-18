#!/usr/bin/env python3
"""Build a HedgeFollow-style smart-money ranking from research-only evidence.

The output is intentionally separate from production scoring. It combines
current 13F, Form 4, and thematic ETF evidence into a standalone Top-N report
that can be used for review and later broker-ledger challenger tests.
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


DEFAULT_INSTITUTIONAL = "outputs/sec_institutional_signals/13f_latest.csv"
DEFAULT_FORM4 = "outputs/sec_ownership_signals/form4_latest.csv"
DEFAULT_ETF = "outputs/etf_thematic_signals/signals_latest.csv"
DEFAULT_13F_FRESHNESS = "outputs/sec_institutional_signals/13f_filing_freshness.json"
DEFAULT_OUTPUT_DIR = "outputs/smart_money"

OUTPUT_COLUMNS = [
    "rank",
    "ticker",
    "smart_money_score",
    "institutional_component",
    "insider_component",
    "etf_component",
    "convergence_bonus",
    "risk_penalty",
    "evidence_source_count",
    "smart_money_convergence_flag",
    "latest_available_from",
    "sec_13f_manager_count",
    "sec_13f_buying_manager_count",
    "sec_13f_selling_manager_count",
    "sec_13f_new_position_manager_count",
    "sec_13f_total_value_usd",
    "sec_13f_value_delta_usd",
    "sec_13f_smart_money_score",
    "institutional_evidence_score",
    "institutional_evidence_confidence_score",
    "insider_buy_count",
    "insider_buy_value",
    "insider_sale_value",
    "sec_form4_open_market_buy_score",
    "sec_form4_cluster_buy_score",
    "sec_form4_ceo_cfo_buy_score",
    "sec_form4_sale_pressure_score",
    "early_evidence_score",
    "evidence_confidence_score",
    "etf_consensus_count",
    "etf_weight_sum",
    "etf_theme_leadership_score",
    "etf_crowding_score",
    "etf_holdings_score",
    "etf_evidence_confidence",
    "etf_themes",
    "etf_sources",
    "smart_money_explanation",
]


def repo_path(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def read_table(path: str | Path) -> pd.DataFrame:
    p = repo_path(path)
    if not p.exists():
        return pd.DataFrame()
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p)
    return pd.read_csv(p, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: str | Path) -> dict[str, Any]:
    resolved = repo_path(path)
    if not resolved.exists():
        return {}
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _safe_pct(value: Any) -> float:
    try:
        out = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(out):
        return 0.0
    return float(max(0.0, min(1.0, out)))


def _numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[col], errors="coerce").fillna(default).astype(float)


def _text(frame: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="object")
    return frame[col].fillna(default).astype(str)


def _normalize_ticker_series(frame: pd.DataFrame, col: str = "ticker") -> pd.Series:
    if col not in frame.columns:
        return pd.Series("", index=frame.index, dtype="object")
    return frame[col].fillna("").astype(str).str.upper().str.strip()


def _prepare_source(frame: pd.DataFrame, keep_cols: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["ticker", *keep_cols])
    d = frame.copy()
    d["ticker"] = _normalize_ticker_series(d)
    d = d[d["ticker"].ne("") & d["ticker"].ne("NAN") & d["ticker"].ne("NONE")].copy()
    if d.empty:
        return pd.DataFrame(columns=["ticker", *keep_cols])
    for col in keep_cols:
        if col not in d.columns:
            d[col] = ""
    return d[["ticker", *keep_cols]].drop_duplicates("ticker", keep="first")


def _latest_available(row: pd.Series) -> str:
    values = [
        row.get("latest_available_from_13f", ""),
        row.get("latest_available_from_form4", ""),
        row.get("latest_available_from_etf", ""),
    ]
    parsed = [pd.to_datetime(v, errors="coerce", utc=True) for v in values if str(v or "").strip()]
    parsed = [v for v in parsed if pd.notna(v)]
    if not parsed:
        return ""
    return max(parsed).isoformat()


def _explain(row: pd.Series) -> str:
    def safe_float(value: Any) -> float:
        try:
            out = float(value)
        except Exception:
            return 0.0
        return out if math.isfinite(out) else 0.0

    parts: list[str] = []
    mgrs = int(safe_float(row.get("sec_13f_manager_count", 0.0)))
    buyers = int(safe_float(row.get("sec_13f_buying_manager_count", 0.0)))
    new_pos = int(safe_float(row.get("sec_13f_new_position_manager_count", 0.0)))
    if mgrs > 0:
        parts.append(f"13F: {mgrs} managers, {buyers} buyers, {new_pos} new positions")
    insider_count = int(safe_float(row.get("insider_buy_count", 0.0)))
    insider_value = safe_float(row.get("insider_buy_value", 0.0))
    if insider_count > 0:
        parts.append(f"Form4: {insider_count} buys, ${insider_value:,.0f} buy value")
    etf_count = int(safe_float(row.get("etf_consensus_count", 0.0)))
    themes = str(row.get("etf_themes", "") or "")
    if etf_count > 0:
        theme_text = f" across {themes}" if themes else ""
        parts.append(f"ETF: {etf_count} thematic holders{theme_text}")
    return "; ".join(parts)


def build_smart_money_rank(
    institutional: pd.DataFrame,
    form4: pd.DataFrame,
    etf: pd.DataFrame,
    *,
    institutional_weight: float = 0.45,
    insider_weight: float = 0.35,
    etf_weight: float = 0.20,
) -> pd.DataFrame:
    inst_cols = [
        "latest_available_from",
        "sec_13f_manager_count",
        "sec_13f_buying_manager_count",
        "sec_13f_selling_manager_count",
        "sec_13f_new_position_manager_count",
        "sec_13f_total_value_usd",
        "sec_13f_value_delta_usd",
        "sec_13f_smart_money_score",
        "sec_13f_crowding_score",
        "sec_13f_stale_penalty",
        "institutional_evidence_score",
        "institutional_evidence_confidence_score",
    ]
    form4_cols = [
        "latest_available_from",
        "insider_buy_count",
        "insider_buy_value",
        "insider_sale_value",
        "sec_form4_open_market_buy_score",
        "sec_form4_cluster_buy_score",
        "sec_form4_ceo_cfo_buy_score",
        "sec_form4_sale_pressure_score",
        "early_evidence_score",
        "evidence_confidence_score",
    ]
    etf_cols = [
        "latest_available_from",
        "etf_consensus_count",
        "etf_weight_sum",
        "etf_theme_leadership_score",
        "etf_crowding_score",
        "etf_holdings_score",
        "etf_evidence_confidence",
        "etf_themes",
        "etf_sources",
    ]
    inst = _prepare_source(institutional, inst_cols).rename(columns={"latest_available_from": "latest_available_from_13f"})
    insider = _prepare_source(form4, form4_cols).rename(columns={"latest_available_from": "latest_available_from_form4"})
    etf_d = _prepare_source(etf, etf_cols).rename(columns={"latest_available_from": "latest_available_from_etf"})
    out = inst.merge(insider, on="ticker", how="outer").merge(etf_d, on="ticker", how="outer")
    if out.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    inst_score = _numeric(out, "institutional_evidence_score", 0.0).clip(0.0, 1.0)
    inst_conf = _numeric(out, "institutional_evidence_confidence_score", 0.0).clip(0.0, 1.0)
    insider_score = _numeric(out, "early_evidence_score", 0.0).clip(0.0, 1.0)
    insider_conf = _numeric(out, "evidence_confidence_score", 0.0).clip(0.0, 1.0)
    etf_score = _numeric(out, "etf_holdings_score", 0.0).clip(0.0, 1.0)
    etf_conf = _numeric(out, "etf_evidence_confidence", 0.0).clip(0.0, 1.0)

    out["institutional_component"] = inst_score * inst_conf
    out["insider_component"] = insider_score * insider_conf
    out["etf_component"] = etf_score * etf_conf
    has_inst = out["institutional_component"] > 0.0
    has_insider = out["insider_component"] > 0.0
    has_etf = out["etf_component"] > 0.0
    out["evidence_source_count"] = has_inst.astype(int) + has_insider.astype(int) + has_etf.astype(int)
    out["convergence_bonus"] = (out["evidence_source_count"].clip(0, 3) - 1).clip(lower=0) * 0.06
    out["risk_penalty"] = (
        0.05 * _numeric(out, "sec_13f_crowding_score", 0.0).clip(0.0, 1.0)
        + 0.03 * _numeric(out, "sec_13f_stale_penalty", 0.0).clip(0.0, 1.0)
        + 0.04 * _numeric(out, "sec_form4_sale_pressure_score", 0.0).clip(0.0, 1.0)
        + 0.03 * _numeric(out, "etf_crowding_score", 0.0).clip(0.0, 1.0)
    )
    raw = (
        float(institutional_weight) * out["institutional_component"]
        + float(insider_weight) * out["insider_component"]
        + float(etf_weight) * out["etf_component"]
        + out["convergence_bonus"]
        - out["risk_penalty"]
    )
    out["smart_money_score"] = raw.clip(0.0, 1.0)
    out["smart_money_convergence_flag"] = out["evidence_source_count"] >= 2
    out["latest_available_from"] = out.apply(_latest_available, axis=1)
    out["smart_money_explanation"] = out.apply(_explain, axis=1)

    for col in OUTPUT_COLUMNS:
        if col not in out.columns and col != "rank":
            out[col] = 0.0 if col not in {"ticker", "latest_available_from", "etf_themes", "etf_sources", "smart_money_explanation"} else ""
    out = out[out["smart_money_score"] > 0.0].copy()
    out = out.sort_values(
        ["smart_money_score", "evidence_source_count", "institutional_component", "insider_component"],
        ascending=False,
    ).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out[OUTPUT_COLUMNS]


def render_report(summary: dict[str, Any], top: pd.DataFrame) -> str:
    freshness = summary.get("13f_freshness") or {}
    source_identity = freshness.get("source_identity") or {}
    lines = [
        "# Smart Money Top 30",
        "",
        "Research-only ranking from SEC 13F, Form 4, and thematic ETF evidence.",
        "Production `score_total` is not changed.",
        "",
        f"- 13F source rows: {summary.get('institutional_rows', 0)}",
        f"- Form 4 source rows: {summary.get('form4_rows', 0)}",
        f"- ETF source rows: {summary.get('etf_rows', 0)}",
        f"- ranked tickers: {summary.get('ranked_tickers', 0)}",
        f"- 13F required period: {freshness.get('required_due_period_end', '')}",
        f"- 13F freshness: {freshness.get('status', 'not_bound')}",
        f"- 13F parsed manager coverage: {freshness.get('required_period_parsed_manager_coverage', 'n/a')}",
        f"- triggering workflow run/head: {source_identity.get('workflow_run_id', '')} / {source_identity.get('head_sha', '')}",
        "",
        "## Top Ranked",
        "",
        "| rank | ticker | score | sources | 13F managers | insider buys | ETF consensus | explanation |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for _, row in top.iterrows():
        lines.append(
            "| {rank:.0f} | {ticker} | {score:.3f} | {sources:.0f} | {mgr:.0f} | {buys:.0f} | {etfs:.0f} | {explain} |".format(
                rank=float(row.get("rank", 0.0)),
                ticker=row.get("ticker", ""),
                score=float(row.get("smart_money_score", 0.0)),
                sources=float(row.get("evidence_source_count", 0.0)),
                mgr=float(row.get("sec_13f_manager_count", 0.0) or 0.0),
                buys=float(row.get("insider_buy_count", 0.0) or 0.0),
                etfs=float(row.get("etf_consensus_count", 0.0) or 0.0),
                explain=str(row.get("smart_money_explanation", "")).replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institutional", default=DEFAULT_INSTITUTIONAL)
    parser.add_argument("--form4", default=DEFAULT_FORM4)
    parser.add_argument("--etf", default=DEFAULT_ETF)
    parser.add_argument(
        "--13f-freshness-manifest",
        dest="freshness_manifest",
        default=DEFAULT_13F_FRESHNESS,
    )
    parser.add_argument("--require-13f-freshness", action="store_true")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--institutional-weight", type=float, default=0.45)
    parser.add_argument("--insider-weight", type=float, default=0.35)
    parser.add_argument("--etf-weight", type=float, default=0.20)
    args = parser.parse_args()

    freshness = read_json(args.freshness_manifest)
    if args.require_13f_freshness and not freshness.get("freshness_ready"):
        raise SystemExit("13F freshness manifest is missing or blocked; refusing to publish Smart Money scores")

    institutional = read_table(args.institutional)
    form4 = read_table(args.form4)
    etf = read_table(args.etf)
    ranked = build_smart_money_rank(
        institutional,
        form4,
        etf,
        institutional_weight=args.institutional_weight,
        insider_weight=args.insider_weight,
        etf_weight=args.etf_weight,
    )

    out = repo_path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    all_path = out / "smart_money_ranked.csv"
    top_path = out / "top30_latest.csv"
    ranked.to_csv(all_path, index=False)
    top = ranked.head(int(args.top_n)).copy()
    top.to_csv(top_path, index=False)
    summary = {
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "institutional_rows": int(len(institutional)),
        "form4_rows": int(len(form4)),
        "etf_rows": int(len(etf)),
        "ranked_tickers": int(len(ranked)),
        "top_n": int(args.top_n),
        "top_csv": str(top_path),
        "ranked_csv": str(all_path),
        "weights": {
            "institutional": float(args.institutional_weight),
            "insider": float(args.insider_weight),
            "etf": float(args.etf_weight),
        },
        "13f_freshness": {
            key: freshness.get(key)
            for key in [
                "status",
                "freshness_ready",
                "as_of_date",
                "required_due_period_end",
                "required_due_deadline",
                "monitored_period_end",
                "next_scheduled_period_end",
                "next_scheduled_deadline",
                "selected_manager_coverage",
                "latest_accepted_at",
                "filings_index_sha256",
                "holdings_sha256",
                "required_period_parsed_manager_coverage",
                "required_period_parse_error_manager_count",
                "required_period_mapped_row_coverage",
                "required_period_mapped_value_coverage",
                "required_period_amendment_accession_count",
                "required_period_parsed_amendment_accession_count",
                "source_identity",
                "score_consumption",
            ]
        },
    }
    write_json(out / "smart_money_summary.json", summary)
    (out / "report.md").write_text(render_report(summary, top), encoding="utf-8")
    print(json.dumps({"status": "ok", **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
