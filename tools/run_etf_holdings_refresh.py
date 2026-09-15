"""Refresh thematic ETF holdings and build shadow ETF evidence signals.

This tool is intentionally research-only. It creates a PIT holdings lake under
data_pit/etf_holdings and latest signals under outputs/etf_thematic_signals.
Missing holdings are neutral evidence, not a negative quality signal.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml

try:
    import yfinance as yf
except Exception:  # pragma: no cover - yfinance is optional for fixture tests
    yf = None

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UNIVERSE = "research/etf_holdings_universe_20260520/thematic_etfs.yaml"
DEFAULT_PIT_DIR = "data_pit/etf_holdings"
DEFAULT_OUTPUT_DIR = "outputs/etf_thematic_signals"
WEIGHT_UNITS = {"FRACTION", "PERCENT"}
COVERAGE_KINDS = {"FULL", "TOP_ONLY", "PARTIAL", "PCF", "PROXY", "NPORT"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def safe_pct(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def load_universe(path: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    rows = payload.get("etfs", []) if isinstance(payload, dict) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        out.append(
            {
                "etf_ticker": ticker,
                "etf_label": str(row.get("label") or ticker).strip(),
                "theme": str(row.get("theme") or "unknown").strip(),
                "holdings_url": str(row.get("holdings_url") or "").strip(),
                "holdings_weight_unit": str(row.get("holdings_weight_unit") or "").upper().strip(),
                "coverage_kind": str(row.get("coverage_kind") or "TOP_ONLY").upper().strip(),
            }
        )
    return out


def _normalize_weight_series(series: pd.Series, *, weight_unit: str) -> pd.Series:
    unit = str(weight_unit or "").upper().strip()
    if unit not in WEIGHT_UNITS:
        return pd.Series(float("nan"), index=series.index, dtype=float)
    raw = series.astype(str).str.strip()
    if unit == "FRACTION" and raw.str.contains("%", regex=False).any():
        return pd.Series(float("nan"), index=series.index, dtype=float)
    numeric = pd.to_numeric(raw.str.replace("%", "", regex=False), errors="coerce")
    if unit == "PERCENT":
        numeric = numeric / 100.0
    numeric = numeric.where(numeric.map(lambda value: bool(math.isfinite(float(value))) if pd.notna(value) else False))
    return numeric.where(numeric.between(0.0, 1.0))


def normalize_holding_rows(
    frame: pd.DataFrame,
    spec: dict[str, Any],
    *,
    as_of: str,
    source: str,
    max_holdings: int,
    weight_unit: str,
    coverage_kind: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    unit = str(weight_unit or "").upper().strip()
    coverage = str(coverage_kind or "").upper().strip()
    if unit not in WEIGHT_UNITS or coverage not in COVERAGE_KINDS:
        return pd.DataFrame()
    d = frame.copy()
    lower = {str(c).lower().strip(): c for c in d.columns}
    ticker_col = next((lower[c] for c in ["holding_ticker", "ticker", "symbol", "holding symbol", "identifier"] if c in lower), None)
    name_col = next((lower[c] for c in ["holding_name", "name", "company", "security", "holding name"] if c in lower), None)
    weight_col = next(
        (
            lower[c]
            for c in [
                "holding_weight",
                "holding percent",
                "weight",
                "% assets",
                "weight (%)",
                "market value weight",
            ]
            if c in lower
        ),
        None,
    )
    if ticker_col is None or weight_col is None:
        return pd.DataFrame()
    out = pd.DataFrame(index=d.index)
    out["holding_ticker"] = d[ticker_col].astype(str).str.upper().str.strip()
    out["holding_name"] = d[name_col].astype(str).str.strip() if name_col else ""
    out["holding_weight"] = _normalize_weight_series(d[weight_col], weight_unit=unit)
    valid = out["holding_ticker"].ne("") & out["holding_weight"].notna()
    out = out[valid].head(int(max_holdings)).copy()
    if out.empty:
        return pd.DataFrame()
    out["etf_ticker"] = spec["etf_ticker"]
    out["etf_label"] = spec["etf_label"]
    out["theme"] = spec["theme"]
    out["source"] = source
    out["source_weight_unit"] = unit
    out["coverage_kind"] = coverage
    out["as_of_date"] = as_of
    out["available_from"] = as_of
    return out[
        [
            "etf_ticker",
            "etf_label",
            "theme",
            "holding_ticker",
            "holding_name",
            "holding_weight",
            "source_weight_unit",
            "coverage_kind",
            "source",
            "as_of_date",
            "available_from",
        ]
    ]


def fetch_yfinance_holdings(spec: dict[str, Any], *, as_of: str, max_holdings: int) -> pd.DataFrame:
    if yf is None:
        return pd.DataFrame()
    try:
        ticker = yf.Ticker(spec["etf_ticker"])
        funds_data = getattr(ticker, "funds_data", None)
        top = getattr(funds_data, "top_holdings", None)
        if top is None or top.empty:
            return pd.DataFrame()
        top = top.reset_index() if top.index.name else top.copy()
        # yfinance FundsData.top_holdings exposes Holding Percent as a fraction.
        # It is also a top-holdings view, not proof of a complete portfolio.
        return normalize_holding_rows(
            top,
            spec,
            as_of=as_of,
            source="yfinance",
            max_holdings=max_holdings,
            weight_unit="FRACTION",
            coverage_kind="TOP_ONLY",
        )
    except Exception:
        return pd.DataFrame()


def fetch_url_holdings(spec: dict[str, Any], *, as_of: str, max_holdings: int) -> pd.DataFrame:
    url = str(spec.get("holdings_url") or "").strip()
    unit = str(spec.get("holdings_weight_unit") or "").upper().strip()
    coverage = str(spec.get("coverage_kind") or "").upper().strip()
    if not url or unit not in WEIGHT_UNITS or coverage not in COVERAGE_KINDS:
        return pd.DataFrame()
    try:
        response = requests.get(url, timeout=30, headers={"User-Agent": "R1000QuantEngine research"})
        response.raise_for_status()
        frame = pd.read_csv(io.StringIO(response.text))
        return normalize_holding_rows(
            frame,
            spec,
            as_of=as_of,
            source=url,
            max_holdings=max_holdings,
            weight_unit=unit,
            coverage_kind=coverage,
        )
    except Exception:
        return pd.DataFrame()


def _single_value(group: pd.DataFrame, column: str, default: str) -> str:
    if column not in group.columns:
        return default
    values = [str(value).strip() for value in group[column].dropna().tolist() if str(value).strip()]
    unique = sorted(set(values))
    return unique[0] if len(unique) == 1 else ""


def load_fixture_holdings(path: Path, specs: list[dict[str, Any]], *, as_of: str, max_holdings: int) -> pd.DataFrame:
    frame = read_table(path)
    if frame.empty or "etf_ticker" not in frame.columns:
        return pd.DataFrame()
    specs_by_ticker = {s["etf_ticker"]: s for s in specs}
    rows: list[pd.DataFrame] = []
    grouped = frame.groupby(frame["etf_ticker"].astype(str).str.upper().str.strip())
    for etf, group in grouped:
        spec = specs_by_ticker.get(etf, {"etf_ticker": etf, "etf_label": etf, "theme": "fixture"})
        unit = _single_value(group, "weight_unit", "FRACTION").upper()
        coverage = _single_value(group, "coverage_kind", "TOP_ONLY").upper()
        normalized = normalize_holding_rows(
            group,
            spec,
            as_of=as_of,
            source="fixture",
            max_holdings=max_holdings,
            weight_unit=unit,
            coverage_kind=coverage,
        )
        if not normalized.empty:
            rows.append(normalized)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def previous_holdings(pit_file: Path) -> pd.DataFrame:
    prev = read_table(pit_file)
    if prev.empty or "available_from" not in prev.columns or "etf_ticker" not in prev.columns:
        return pd.DataFrame()
    prev = prev.copy()
    prev["_available_ts"] = pd.to_datetime(prev["available_from"], errors="coerce", utc=True)
    prev = prev[prev["_available_ts"].notna()].copy()
    if prev.empty:
        return pd.DataFrame()
    latest_by_fund = prev.groupby(prev["etf_ticker"].astype(str).str.upper().str.strip())["_available_ts"].transform("max")
    prev = prev[prev["_available_ts"].eq(latest_by_fund)].copy()
    return prev.drop(columns=["_available_ts"])


def _full_coverage_funds(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "coverage_kind" not in frame.columns or "etf_ticker" not in frame.columns:
        return set()
    out: set[str] = set()
    for fund, group in frame.groupby(frame["etf_ticker"].astype(str).str.upper().str.strip()):
        kinds = {str(value).upper().strip() for value in group["coverage_kind"].dropna()}
        if kinds == {"FULL"}:
            out.add(str(fund).upper())
    return out


def build_signals(holdings: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    if holdings.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "latest_available_from",
                "etf_consensus_count",
                "etf_weight_sum",
                "etf_recent_add_score",
                "etf_theme_leadership_score",
                "etf_crowding_score",
                "etf_holdings_score",
                "etf_evidence_confidence",
            ]
        )
    d = holdings.copy()
    d["ticker"] = d["holding_ticker"].astype(str).str.upper().str.strip()
    prev_pairs: set[tuple[str, str]] = set()
    if not previous.empty and {"etf_ticker", "holding_ticker"}.issubset(previous.columns):
        prev_pairs = set(zip(previous["etf_ticker"].astype(str).str.upper(), previous["holding_ticker"].astype(str).str.upper()))
    current_full = _full_coverage_funds(d)
    previous_full = _full_coverage_funds(previous)
    eligible_add_funds = current_full & previous_full
    d["is_recent_add"] = [
        str(row.etf_ticker).upper() in eligible_add_funds
        and (str(row.etf_ticker).upper(), str(row.holding_ticker).upper()) not in prev_pairs
        for row in d[["etf_ticker", "holding_ticker"]].itertuples(index=False)
    ]
    rows: list[dict[str, Any]] = []
    for ticker, group in d[d["ticker"].ne("")].groupby("ticker"):
        consensus = int(group["etf_ticker"].nunique())
        weight_values = pd.to_numeric(group["holding_weight"], errors="coerce").dropna()
        weight_sum = float(weight_values.sum()) if not weight_values.empty else 0.0
        recent_add = safe_pct(float(group["is_recent_add"].sum()) / max(consensus, 1))
        theme_score = safe_pct(0.55 * safe_pct(weight_sum / 0.15) + 0.25 * safe_pct(consensus / 3.0) + 0.20 * recent_add)
        crowding = safe_pct(consensus / 8.0)
        confidence = safe_pct(0.55 * safe_pct(consensus / 3.0) + 0.45 * safe_pct(len(group) / 6.0))
        rows.append(
            {
                "ticker": ticker,
                "latest_available_from": str(group["available_from"].max()),
                "etf_consensus_count": consensus,
                "etf_weight_sum": weight_sum,
                "etf_recent_add_score": recent_add,
                "etf_theme_leadership_score": theme_score,
                "etf_crowding_score": crowding,
                "etf_holdings_score": safe_pct(theme_score * (1.0 - 0.15 * crowding)),
                "etf_evidence_confidence": confidence,
                "etf_themes": ",".join(sorted(set(group["theme"].astype(str)))),
                "etf_sources": ",".join(sorted(set(group["etf_ticker"].astype(str)))),
            }
        )
    return pd.DataFrame(rows).sort_values(["etf_holdings_score", "etf_weight_sum"], ascending=False)


def render_report(summary: dict[str, Any], signals: pd.DataFrame) -> str:
    lines = [
        "# ETF Thematic Holdings Signals",
        "",
        "Research-only ETF holdings evidence. Missing data is neutral with lower confidence.",
        "",
        f"- holdings rows: {summary.get('holding_rows', 0)}",
        f"- signal tickers: {summary.get('signal_tickers', 0)}",
        f"- as_of: {summary.get('as_of', '')}",
        "",
        "| ticker | score | consensus | weight sum | recent add | themes |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for _, row in signals.head(30).iterrows():
        lines.append(
            "| {ticker} | {score:.3f} | {consensus:.0f} | {weight:.3f} | {recent:.3f} | {themes} |".format(
                ticker=row.get("ticker", ""),
                score=float(row.get("etf_holdings_score", 0.0)),
                consensus=float(row.get("etf_consensus_count", 0.0)),
                weight=float(row.get("etf_weight_sum", 0.0)),
                recent=float(row.get("etf_recent_add_score", 0.0)),
                themes=row.get("etf_themes", ""),
            )
        )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    as_of = args.as_of or datetime.now(timezone.utc).isoformat()
    specs = load_universe(repo_path(args.universe))
    pit_dir = repo_path(args.pit_dir)
    out_dir = repo_path(args.output_dir)
    pit_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.input_holdings:
        holdings = load_fixture_holdings(repo_path(args.input_holdings), specs, as_of=as_of, max_holdings=args.max_holdings)
    else:
        frames: list[pd.DataFrame] = []
        for spec in specs:
            frame = fetch_yfinance_holdings(spec, as_of=as_of, max_holdings=args.max_holdings)
            if frame.empty:
                frame = fetch_url_holdings(spec, as_of=as_of, max_holdings=args.max_holdings)
            if not frame.empty:
                frames.append(frame)
            time.sleep(float(args.sleep))
        holdings = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    pit_file = pit_dir / "etf_holdings.parquet"
    history = read_table(pit_file)
    prev = previous_holdings(pit_file)
    if not history.empty and not holdings.empty:
        combined = pd.concat([history, holdings], ignore_index=True, sort=False)
        combined = combined.drop_duplicates(["etf_ticker", "holding_ticker", "available_from"], keep="last")
    elif not history.empty:
        combined = history
    else:
        combined = holdings
    if not combined.empty:
        write_table(combined, pit_file)
        combined.to_csv(pit_dir / "etf_holdings.csv", index=False)
    signals = build_signals(holdings, prev)
    write_table(signals, pit_dir / "etf_thematic_signals.parquet")
    signals.to_csv(out_dir / "etf_latest.csv", index=False)
    signals.to_csv(out_dir / "signals_latest.csv", index=False)
    summary = {
        "status": "completed",
        "schema_version": "etf-holdings-signals-v2",
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "as_of": as_of,
        "etf_universe_count": int(len(specs)),
        "holding_rows": int(len(holdings)),
        "historical_rows_retained": int(len(history)),
        "pit_rows_after_refresh": int(len(combined)),
        "full_coverage_etfs": int(len(_full_coverage_funds(holdings))),
        "signal_tickers": int(len(signals)),
        "pit_file": str(pit_file),
        "latest_csv": str(out_dir / "etf_latest.csv"),
    }
    write_json(out_dir / "etf_holding_signal_summary.json", summary)
    (out_dir / "report.md").write_text(render_report(summary, signals), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE)
    parser.add_argument("--pit-dir", default=DEFAULT_PIT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--input-holdings", default="", help="Optional CSV/parquet fixture or pre-fetched holdings file.")
    parser.add_argument("--max-holdings", type=int, default=25)
    parser.add_argument("--sleep", type=float, default=0.25)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
