#!/usr/bin/env python3
"""Build a research-only discovery universe from 13F, Form 4, and ETF evidence.

This is the stock-expansion bridge for the evidence system. It intentionally
does not alter production scoring or target books. The output is a ranked
watchlist of tickers surfaced by SEC/ETF evidence, including names that may be
outside the current Russell/global-alpha candidate set, for later challenger
tests.
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
DEFAULT_OUTPUT_DIR = "outputs/evidence_discovery_universe"

OUTPUT_COLUMNS = [
    "rank",
    "ticker",
    "evidence_discovery_score",
    "evidence_source_count",
    "has_13f",
    "has_form4",
    "has_etf",
    "candidate_bucket",
    "source_expansion_reason",
    "latest_available_from",
    "sec_13f_score",
    "sec_form4_score",
    "etf_holdings_score_component",
    "convergence_bonus",
    "small_mid_discovery_bonus",
    "risk_penalty",
    "sec_13f_manager_count",
    "sec_13f_buying_manager_count",
    "sec_13f_new_position_manager_count",
    "sec_13f_total_value_usd",
    "sec_13f_value_delta_usd",
    "insider_buy_count",
    "insider_buy_value",
    "insider_sale_value",
    "sec_form4_open_market_buy_score",
    "sec_form4_cluster_buy_score",
    "sec_form4_ceo_cfo_buy_score",
    "etf_consensus_count",
    "etf_weight_sum",
    "etf_theme_leadership_score",
    "etf_themes",
    "etf_sources",
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


def _numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[col], errors="coerce").fillna(default).astype(float)


def _normalize_ticker(frame: pd.DataFrame, col: str = "ticker") -> pd.Series:
    if col in frame.columns:
        raw = frame[col]
    elif "holding_ticker" in frame.columns:
        raw = frame["holding_ticker"]
    else:
        raw = pd.Series("", index=frame.index, dtype="object")
    return raw.fillna("").astype(str).str.upper().str.strip()


def _clean_source(frame: pd.DataFrame, keep_cols: list[str], *, source: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["ticker", *keep_cols])
    out = frame.copy()
    out["ticker"] = _normalize_ticker(out)
    out = out[out["ticker"].ne("") & out["ticker"].ne("NAN") & out["ticker"].ne("NONE")].copy()
    if out.empty:
        return pd.DataFrame(columns=["ticker", *keep_cols])
    for col in keep_cols:
        if col not in out.columns:
            out[col] = ""
    out = out[["ticker", *keep_cols]].drop_duplicates("ticker", keep="first")
    out[f"has_{source}"] = True
    return out


def _latest_available(row: pd.Series) -> str:
    values = [
        row.get("latest_available_from_13f", ""),
        row.get("latest_available_from_form4", ""),
        row.get("latest_available_from_etf", ""),
        row.get("available_from_13f", ""),
        row.get("available_from_form4", ""),
        row.get("available_from_etf", ""),
    ]
    parsed = [pd.to_datetime(v, errors="coerce", utc=True) for v in values if str(v or "").strip()]
    parsed = [v for v in parsed if pd.notna(v)]
    if not parsed:
        return ""
    return max(parsed).isoformat()


def _bucket(row: pd.Series) -> str:
    has_13f = bool(row.get("has_13f", False))
    has_form4 = bool(row.get("has_form4", False))
    has_etf = bool(row.get("has_etf", False))
    if has_13f and has_form4 and has_etf:
        return "triple_source"
    if sum([has_13f, has_form4, has_etf]) >= 2:
        return "multi_source"
    if has_13f:
        new_pos = float(row.get("sec_13f_new_position_manager_count", 0.0) or 0.0)
        return "13f_first_buy" if new_pos > 0 else "13f_only"
    if has_form4:
        return "form4_open_market_buy"
    if has_etf:
        return "etf_new_or_thematic_holder"
    return "unknown"


def _reason(row: pd.Series) -> str:
    parts: list[str] = []
    if bool(row.get("has_13f", False)):
        mgrs = int(float(row.get("sec_13f_manager_count", 0.0) or 0.0))
        buyers = int(float(row.get("sec_13f_buying_manager_count", 0.0) or 0.0))
        new_pos = int(float(row.get("sec_13f_new_position_manager_count", 0.0) or 0.0))
        parts.append(f"13F managers={mgrs} buyers={buyers} new={new_pos}")
    if bool(row.get("has_form4", False)):
        buys = int(float(row.get("insider_buy_count", 0.0) or 0.0))
        value = float(row.get("insider_buy_value", 0.0) or 0.0)
        parts.append(f"Form4 buys={buys} buy_value=${value:,.0f}")
    if bool(row.get("has_etf", False)):
        consensus = int(float(row.get("etf_consensus_count", 0.0) or 0.0))
        themes = str(row.get("etf_themes", "") or "")
        parts.append(f"ETF consensus={consensus}" + (f" themes={themes}" if themes else ""))
    return "; ".join(parts)


def _safe_clip(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0).clip(0.0, 1.0)


def build_discovery_universe(
    institutional: pd.DataFrame,
    form4: pd.DataFrame,
    etf: pd.DataFrame,
    *,
    institutional_weight: float = 0.42,
    form4_weight: float = 0.38,
    etf_weight: float = 0.20,
) -> pd.DataFrame:
    inst_cols = [
        "latest_available_from",
        "available_from",
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
        "available_from",
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
        "available_from",
        "etf_consensus_count",
        "etf_weight_sum",
        "etf_theme_leadership_score",
        "etf_crowding_score",
        "etf_holdings_score",
        "etf_evidence_confidence",
        "etf_themes",
        "etf_sources",
    ]
    inst = _clean_source(institutional, inst_cols, source="13f").rename(
        columns={"latest_available_from": "latest_available_from_13f", "available_from": "available_from_13f"}
    )
    f4 = _clean_source(form4, form4_cols, source="form4").rename(
        columns={"latest_available_from": "latest_available_from_form4", "available_from": "available_from_form4"}
    )
    etf_d = _clean_source(etf, etf_cols, source="etf").rename(
        columns={"latest_available_from": "latest_available_from_etf", "available_from": "available_from_etf"}
    )
    out = inst.merge(f4, on="ticker", how="outer").merge(etf_d, on="ticker", how="outer")
    if out.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    for col in ["has_13f", "has_form4", "has_etf"]:
        if col not in out.columns:
            out[col] = False
        out[col] = out[col].map(lambda value: bool(value) if pd.notna(value) else False)

    inst_score = _safe_clip(_numeric(out, "institutional_evidence_score", 0.0))
    inst_conf = _safe_clip(_numeric(out, "institutional_evidence_confidence_score", 0.0))
    form4_score = _safe_clip(_numeric(out, "early_evidence_score", 0.0))
    form4_conf = _safe_clip(_numeric(out, "evidence_confidence_score", 0.0))
    etf_score = _safe_clip(_numeric(out, "etf_holdings_score", 0.0))
    etf_conf = _safe_clip(_numeric(out, "etf_evidence_confidence", 0.0))

    out["sec_13f_score"] = inst_score * inst_conf
    out["sec_form4_score"] = form4_score * form4_conf
    out["etf_holdings_score_component"] = etf_score * etf_conf
    out["evidence_source_count"] = out[["has_13f", "has_form4", "has_etf"]].sum(axis=1).astype(int)

    new_position = _numeric(out, "sec_13f_new_position_manager_count", 0.0).clip(lower=0.0)
    buyer_count = _numeric(out, "sec_13f_buying_manager_count", 0.0).clip(lower=0.0)
    insider_buy_count = _numeric(out, "insider_buy_count", 0.0).clip(lower=0.0)
    etf_consensus = _numeric(out, "etf_consensus_count", 0.0).clip(lower=0.0)
    out["convergence_bonus"] = (out["evidence_source_count"].clip(0, 3) - 1).clip(lower=0) * 0.06
    out["small_mid_discovery_bonus"] = (
        0.03 * (new_position > 0).astype(float)
        + 0.02 * (buyer_count >= 2).astype(float)
        + 0.02 * (insider_buy_count >= 2).astype(float)
        + 0.02 * (etf_consensus >= 2).astype(float)
    ).clip(0.0, 0.08)
    out["risk_penalty"] = (
        0.05 * _safe_clip(_numeric(out, "sec_13f_crowding_score", 0.0))
        + 0.03 * _safe_clip(_numeric(out, "sec_13f_stale_penalty", 0.0))
        + 0.04 * _safe_clip(_numeric(out, "sec_form4_sale_pressure_score", 0.0))
        + 0.03 * _safe_clip(_numeric(out, "etf_crowding_score", 0.0))
    )
    raw = (
        float(institutional_weight) * out["sec_13f_score"]
        + float(form4_weight) * out["sec_form4_score"]
        + float(etf_weight) * out["etf_holdings_score_component"]
        + out["convergence_bonus"]
        + out["small_mid_discovery_bonus"]
        - out["risk_penalty"]
    )
    out["evidence_discovery_score"] = raw.clip(0.0, 1.0)
    out["candidate_bucket"] = out.apply(_bucket, axis=1)
    out["source_expansion_reason"] = out.apply(_reason, axis=1)
    out["latest_available_from"] = out.apply(_latest_available, axis=1)
    out = out[out["evidence_discovery_score"] > 0.0].copy()
    out = out.sort_values(
        ["evidence_discovery_score", "evidence_source_count", "small_mid_discovery_bonus"],
        ascending=False,
    ).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    for col in OUTPUT_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col in {"ticker", "candidate_bucket", "source_expansion_reason", "latest_available_from", "etf_themes", "etf_sources"} else 0.0
    return out[OUTPUT_COLUMNS]


def render_report(summary: dict[str, Any], top: pd.DataFrame) -> str:
    lines = [
        "# Evidence Discovery Universe",
        "",
        "Research-only stock expansion watchlist from SEC 13F, Form 4, and ETF holdings evidence.",
        "Production `score_total` and target books are not changed by this artifact.",
        "",
        f"- 13F rows: {summary.get('institutional_rows', 0)}",
        f"- Form 4 rows: {summary.get('form4_rows', 0)}",
        f"- ETF rows: {summary.get('etf_rows', 0)}",
        f"- ranked tickers: {summary.get('ranked_tickers', 0)}",
        "",
        "| rank | ticker | score | sources | bucket | reason |",
        "| ---: | --- | ---: | ---: | --- | --- |",
    ]
    for _, row in top.iterrows():
        lines.append(
            "| {rank:.0f} | {ticker} | {score:.3f} | {sources:.0f} | {bucket} | {reason} |".format(
                rank=float(row.get("rank", 0.0)),
                ticker=row.get("ticker", ""),
                score=float(row.get("evidence_discovery_score", 0.0)),
                sources=float(row.get("evidence_source_count", 0.0)),
                bucket=str(row.get("candidate_bucket", "")).replace("|", "/"),
                reason=str(row.get("source_expansion_reason", "")).replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institutional", default=DEFAULT_INSTITUTIONAL)
    parser.add_argument("--form4", default=DEFAULT_FORM4)
    parser.add_argument("--etf", default=DEFAULT_ETF)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=500)
    parser.add_argument("--institutional-weight", type=float, default=0.42)
    parser.add_argument("--form4-weight", type=float, default=0.38)
    parser.add_argument("--etf-weight", type=float, default=0.20)
    args = parser.parse_args()

    institutional = read_table(args.institutional)
    form4 = read_table(args.form4)
    etf = read_table(args.etf)
    ranked = build_discovery_universe(
        institutional,
        form4,
        etf,
        institutional_weight=args.institutional_weight,
        form4_weight=args.form4_weight,
        etf_weight=args.etf_weight,
    )

    out = repo_path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    all_path = out / "evidence_discovery_universe.csv"
    latest_path = out / "latest.csv"
    ranked.to_csv(all_path, index=False)
    top = ranked.head(int(args.top_n)).copy()
    top.to_csv(latest_path, index=False)
    summary = {
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "institutional_rows": int(len(institutional)),
        "form4_rows": int(len(form4)),
        "etf_rows": int(len(etf)),
        "ranked_tickers": int(len(ranked)),
        "top_n": int(args.top_n),
        "latest_csv": str(latest_path),
        "ranked_csv": str(all_path),
        "source_counts": {
            "13f": int(ranked["has_13f"].sum()) if "has_13f" in ranked.columns else 0,
            "form4": int(ranked["has_form4"].sum()) if "has_form4" in ranked.columns else 0,
            "etf": int(ranked["has_etf"].sum()) if "has_etf" in ranked.columns else 0,
            "multi_source": int((ranked["evidence_source_count"] >= 2).sum()) if "evidence_source_count" in ranked.columns else 0,
        },
        "weights": {
            "institutional": float(args.institutional_weight),
            "form4": float(args.form4_weight),
            "etf": float(args.etf_weight),
        },
    }
    write_json(out / "summary.json", summary)
    (out / "report.md").write_text(render_report(summary, top.head(30)), encoding="utf-8")
    print(json.dumps({"status": "ok", **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
