#!/usr/bin/env python3
"""Daily theme leadership tape.

This report-only sidecar detects where the market's current speculative and
institutional attention is concentrating. It uses only prices observable up to
the latest cached close plus the latest scored metadata. It does not change
production selection.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


DEFAULT_SCORED = "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv"
DEFAULT_PRICE_CACHE = "cache_prices"
DEFAULT_OUT_DIR = "outputs/theme_leadership_tape"
CASH_TICKERS = {"CASH", "__CASH__"}

THEME_TAXONOMY: dict[str, dict[str, tuple[str, ...]]] = {
    "memory_semiconductors": {
        "tickers": ("MU", "SNDK", "WDC", "STX", "KXSCF", "SSNLF", "HXSCF"),
        "keywords": (
            "memory",
            "dram",
            "nand",
            "flash",
            "hbm",
            "storage",
            "disk drive",
            "solid state",
            "ssd",
            "sandisk",
            "western digital",
            "seagate",
            "micron",
        ),
    },
    "ai_compute_semiconductors": {
        "tickers": ("NVDA", "AMD", "AVGO", "ARM", "MRVL", "TSM", "ASML", "LRCX", "AMAT", "KLAC"),
        "keywords": ("semiconductor", "ai chip", "gpu", "accelerator", "foundry", "semicap", "wafer", "lithography"),
    },
    "nuclear_power": {
        "tickers": ("LEU", "CCJ", "CEG", "OKLO", "SMR", "NNE", "BWXT", "UEC", "UUUU"),
        "keywords": ("nuclear", "uranium", "reactor", "smr", "centrus", "enrichment"),
    },
    "power_grid_gas_turbine": {
        "tickers": ("GEV", "VST", "CEG", "ETN", "PWR", "NVT", "GTLS", "NXT", "FLNC"),
        "keywords": ("power", "grid", "turbine", "electrification", "transformer", "energy storage", "battery storage"),
    },
    "space_launch": {
        "tickers": ("RKLB", "ASTS", "LUNR", "RDW", "PL", "SPIR"),
        "keywords": ("space", "launch", "satellite", "aerospace", "rocket"),
    },
    "rare_earths_battery_materials": {
        "tickers": ("MP", "LAC", "ALB", "SQM", "PLL", "LITM", "REMX"),
        "keywords": ("rare earth", "lithium", "battery material", "critical mineral", "mining"),
    },
    "optical_networking_ai_infra": {
        "tickers": ("CIEN", "LITE", "COHR", "FN", "AAOI", "ACIA"),
        "keywords": ("optical", "photonics", "networking", "transceiver", "datacenter interconnect"),
    },
    "software_ai_platforms": {
        "tickers": ("PLTR", "APP", "SNOW", "DDOG", "NET", "MDB", "CRWD"),
        "keywords": ("software", "ai platform", "cloud", "cybersecurity", "data analytics"),
    },
}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def robust_z(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    med = float(x.median(skipna=True)) if x.notna().any() else 0.0
    mad = float((x - med).abs().median(skipna=True)) if x.notna().any() else 0.0
    if not math.isfinite(mad) or mad <= 1e-12:
        std = float(x.std(skipna=True, ddof=0)) if x.notna().any() else 0.0
        denom = std if std > 1e-12 else 1.0
        return ((x - med) / denom).fillna(0.0)
    return ((x - med) / (1.4826 * mad)).clip(-6, 6).fillna(0.0)


def load_price_cache(price_cache: Path, ticker: str) -> pd.DataFrame:
    path = price_cache / px_cache_name(ticker)
    if not path.exists():
        return pd.DataFrame()
    try:
        px = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if px.empty:
        return pd.DataFrame()
    px = px.copy()
    px.index = pd.to_datetime(px.index, errors="coerce").tz_localize(None)
    px = px[px.index.notna()].sort_index()
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    close_col = "Adj Close" if "Adj Close" in px.columns else "Close"
    if close_col not in px.columns:
        return pd.DataFrame()
    out = pd.DataFrame(index=px.index)
    out["close"] = pd.to_numeric(px[close_col], errors="coerce")
    out["volume"] = pd.to_numeric(px.get("Volume", np.nan), errors="coerce")
    if "Close" in px.columns and "Adj Close" in px.columns:
        raw_close = pd.to_numeric(px["Close"], errors="coerce").replace(0, np.nan)
        adj_ratio = pd.to_numeric(px["Adj Close"], errors="coerce") / raw_close
        out["raw_close"] = pd.to_numeric(px["Close"], errors="coerce")
        out["dollar_volume"] = out["close"] * out["volume"]
        out["split_adjustment_ratio"] = adj_ratio
    else:
        out["raw_close"] = out["close"]
        out["dollar_volume"] = out["close"] * out["volume"]
        out["split_adjustment_ratio"] = 1.0
    return out.dropna(subset=["close"])


def trailing_return(close: pd.Series, days: int) -> float:
    if len(close) <= days:
        return np.nan
    last = safe_float(close.iloc[-1], np.nan)
    base = safe_float(close.iloc[-days - 1], np.nan)
    if not math.isfinite(last) or not math.isfinite(base) or base <= 0:
        return np.nan
    return last / base - 1.0


def price_metrics(price_cache: Path, ticker: str) -> dict[str, Any]:
    px = load_price_cache(price_cache, ticker)
    if px.empty or len(px) < 6:
        return {"ticker": ticker, "price_status": "missing_or_short"}
    close = pd.to_numeric(px["close"], errors="coerce").dropna()
    volume = pd.to_numeric(px["volume"], errors="coerce")
    dollar_volume = pd.to_numeric(px["dollar_volume"], errors="coerce")
    if close.empty:
        return {"ticker": ticker, "price_status": "missing_or_short"}
    ret_1d = trailing_return(close, 1)
    ret_5d = trailing_return(close, 5)
    ret_21d = trailing_return(close, 21)
    ret_63d = trailing_return(close, 63)
    ret_126d = trailing_return(close, 126)
    vol20 = volume.tail(20)
    vol_prev = volume.shift(1).rolling(20).mean()
    vol_z = np.nan
    if len(volume) > 21:
        denom = float(volume.shift(1).rolling(20).std(ddof=0).iloc[-1])
        base = float(vol_prev.iloc[-1])
        if math.isfinite(denom) and denom > 1e-12:
            vol_z = (safe_float(volume.iloc[-1], 0.0) - base) / denom
    high_252 = close.tail(252).max()
    dist_high = float(close.iloc[-1] / high_252 - 1.0) if high_252 and high_252 > 0 else np.nan
    return {
        "ticker": ticker,
        "price_status": "ok",
        "price_date": pd.Timestamp(close.index[-1]).date().isoformat(),
        "close": float(close.iloc[-1]),
        "ret_1d": ret_1d,
        "ret_5d": ret_5d,
        "ret_21d": ret_21d,
        "ret_63d": ret_63d,
        "ret_126d": ret_126d,
        "volume": safe_float(volume.iloc[-1], np.nan),
        "volume_avg_20d": safe_float(vol20.mean(), np.nan),
        "volume_z_20d": vol_z,
        "dollar_volume_20d": safe_float(dollar_volume.tail(20).mean(), np.nan),
        "distance_from_252d_high": dist_high,
    }


def infer_theme(row: pd.Series) -> str:
    ticker = str(row.get("ticker") or "").upper()
    text_fields = [
        row.get("Name"),
        row.get("name"),
        row.get("sector"),
        row.get("industry"),
        row.get("yf_industry"),
        row.get("yf_sector"),
        row.get("theme_phase_primary"),
        row.get("theme_horizon_primary"),
        row.get("theme_holding_profile_primary"),
        row.get("portfolio_sleeve_label"),
    ]
    text = " ".join(str(x).lower() for x in text_fields if x not in (None, "nan"))
    for label, spec in THEME_TAXONOMY.items():
        if ticker in {x.upper() for x in spec.get("tickers", ())}:
            return label
        if any(keyword.lower() in text for keyword in spec.get("keywords", ())):
            return label
    for fallback in ("sage_sector", "yf_industry", "industry", "sector"):
        value = str(row.get(fallback) or "").strip()
        if value and value.lower() not in {"nan", "unknown"}:
            return value.lower().replace(" ", "_")
    return "unclassified"


def read_scored(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def build_ticker_tape(scored: pd.DataFrame, price_cache: Path, min_mcap: float, min_dollar_vol: float) -> pd.DataFrame:
    if scored.empty or "ticker" not in scored.columns:
        return pd.DataFrame()
    d = scored.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = d[(d["ticker"] != "") & ~d["ticker"].isin(CASH_TICKERS)].drop_duplicates("ticker", keep="last")
    rows: list[dict[str, Any]] = []
    for row in d.itertuples(index=False):
        ticker = str(getattr(row, "ticker", "")).upper()
        rec = d.loc[d["ticker"].eq(ticker)].iloc[-1].to_dict()
        rec.update(price_metrics(price_cache, ticker))
        rows.append(rec)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["leadership_theme"] = out.apply(infer_theme, axis=1)
    market_cap_source = out["market_cap_live"] if "market_cap_live" in out.columns else out.get("mktcap", pd.Series(0.0, index=out.index))
    out["market_cap"] = pd.to_numeric(market_cap_source, errors="coerce").fillna(0.0)
    out["dollar_volume_20d"] = pd.to_numeric(out.get("dollar_volume_20d"), errors="coerce").fillna(0.0)
    for col in ("ret_1d", "ret_5d", "ret_21d", "ret_63d", "ret_126d", "volume_z_20d"):
        out[col] = pd.to_numeric(out.get(col), errors="coerce")
    liquid = (out["market_cap"] >= min_mcap) & (out["dollar_volume_20d"] >= min_dollar_vol)
    out["liquidity_pass"] = liquid
    out["ret_5d_z"] = robust_z(out["ret_5d"])
    out["ret_1d_z"] = robust_z(out["ret_1d"])
    out["ret_21d_z"] = robust_z(out["ret_21d"])
    out["ret_63d_z"] = robust_z(out["ret_63d"])
    out["dollar_volume_z"] = robust_z(np.log1p(out["dollar_volume_20d"]))
    out["volume_z_20d"] = out["volume_z_20d"].fillna(0.0).clip(-6, 6)
    out["short_term_acceleration"] = (
        out["ret_5d"].fillna(0.0) - (out["ret_21d"].fillna(0.0) / 4.0)
    )
    def _num_col(name: str, default: float = 0.0) -> pd.Series:
        if name not in out.columns:
            return pd.Series(default, index=out.index, dtype=float)
        return pd.to_numeric(out[name], errors="coerce").fillna(default)

    out["bubble_climax_score"] = (
        0.25 * out["ret_1d_z"]
        + 0.30 * out["ret_5d_z"]
        + 0.20 * out["ret_21d_z"]
        + 0.15 * out["volume_z_20d"]
        + 0.10 * out["dollar_volume_z"]
    )
    out["early_leadership_score"] = (
        0.20 * out["ret_5d_z"]
        + 0.30 * out["ret_21d_z"]
        + 0.20 * out["ret_63d_z"]
        + 0.15 * _num_col("rs_acceleration_score")
        + 0.10 * _num_col("breakout_setup_quality_score")
        + 0.05 * _num_col("h6_dynamic_leader_score")
    )
    out["participation_score"] = (
        0.45 * out["early_leadership_score"]
        + 0.35 * out["bubble_climax_score"]
        + 0.20 * out["dollar_volume_z"]
    )
    out.loc[~out["liquidity_pass"], ["bubble_climax_score", "early_leadership_score", "participation_score"]] -= 2.0
    return out.sort_values("participation_score", ascending=False, na_position="last").reset_index(drop=True)


def aggregate_leadership(tape: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if tape.empty or group_col not in tape.columns:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for label, g in tape.groupby(group_col):
        liquid = g[g["liquidity_pass"]].copy()
        if liquid.empty:
            continue
        top = liquid.sort_values("participation_score", ascending=False).head(8)
        rows.append(
            {
                group_col: label,
                "member_count": int(len(liquid)),
                "active_count_1d_gt_8pct": int((liquid["ret_1d"] >= 0.08).sum()),
                "active_count_5d_gt_20pct": int((liquid["ret_5d"] >= 0.20).sum()),
                "breadth_21d_positive": float((liquid["ret_21d"] > 0).mean()),
                "median_ret_5d": float(liquid["ret_5d"].median(skipna=True)),
                "median_ret_21d": float(liquid["ret_21d"].median(skipna=True)),
                "median_ret_63d": float(liquid["ret_63d"].median(skipna=True)),
                "top_participation_score": float(top["participation_score"].mean()),
                "top_bubble_climax_score": float(top["bubble_climax_score"].mean()),
                "top_early_leadership_score": float(top["early_leadership_score"].mean()),
                "dollar_volume_20d_sum": float(liquid["dollar_volume_20d"].sum()),
                "top_tickers": ",".join(top["ticker"].astype(str).head(8)),
                "leadership_state": classify_group(liquid, top),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["leadership_score"] = (
        0.25 * robust_z(out["median_ret_5d"])
        + 0.25 * robust_z(out["median_ret_21d"])
        + 0.20 * robust_z(out["top_participation_score"])
        + 0.15 * out["breadth_21d_positive"].fillna(0.0)
        + 0.15 * robust_z(np.log1p(out["dollar_volume_20d_sum"]))
    )
    return out.sort_values("leadership_score", ascending=False).reset_index(drop=True)


def classify_group(liquid: pd.DataFrame, top: pd.DataFrame) -> str:
    ret5 = safe_float(liquid["ret_5d"].median(skipna=True), 0.0)
    ret21 = safe_float(liquid["ret_21d"].median(skipna=True), 0.0)
    clim = safe_float(top["bubble_climax_score"].mean(), 0.0)
    breadth = safe_float((liquid["ret_21d"] > 0).mean(), 0.0)
    if ret5 >= 0.12 and ret21 >= 0.20 and breadth >= 0.60 and clim >= 1.0:
        return "climax_hot"
    if ret21 >= 0.12 and breadth >= 0.55:
        return "emerging_leader"
    if ret21 <= -0.08 and breadth <= 0.35:
        return "lagging"
    return "neutral"


def render_report(summary: dict[str, Any], themes: pd.DataFrame, sectors: pd.DataFrame, tickers: pd.DataFrame) -> str:
    lines = [
        "# Theme Leadership Tape",
        "",
        "Report-only daily sidecar. It detects current market leadership concentration and does not alter production portfolios.",
        "",
        "## Freshness",
        "",
        f"- Scored source: `{summary.get('scored_source')}`",
        f"- Latest price date: `{summary.get('latest_price_date')}`",
        f"- Tickers scored: {summary.get('tickers_scored')}",
        f"- Liquid tickers: {summary.get('liquid_tickers')}",
        "",
        "## Top Themes",
        "",
    ]
    for row in (themes.head(10).to_dict("records") if not themes.empty else []):
        lines.append(
            f"- `{row.get('leadership_theme')}`: score {safe_float(row.get('leadership_score')):.2f}, "
            f"state `{row.get('leadership_state')}`, 5d {safe_float(row.get('median_ret_5d')):.2%}, "
            f"21d {safe_float(row.get('median_ret_21d')):.2%}, top `{row.get('top_tickers')}`"
        )
    lines.extend(["", "## Top Tickers", ""])
    keep = [
        "ticker",
        "Name",
        "leadership_theme",
        "ret_1d",
        "ret_5d",
        "ret_21d",
        "participation_score",
        "bubble_climax_score",
        "dollar_volume_20d",
    ]
    for row in (tickers.head(20)[[c for c in keep if c in tickers.columns]].to_dict("records") if not tickers.empty else []):
        lines.append(
            f"- `{row.get('ticker')}` {str(row.get('Name') or '')[:32]}: theme `{row.get('leadership_theme')}`, "
            f"1d {safe_float(row.get('ret_1d')):.2%}, 5d {safe_float(row.get('ret_5d')):.2%}, "
            f"21d {safe_float(row.get('ret_21d')):.2%}, score {safe_float(row.get('participation_score')):.2f}"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `climax_hot` means the theme is already moving violently; use it for tactical participation and tight exit rules, not blind long-term compounding.",
            "- `emerging_leader` is the better early-entry state; the next step is to A/B test staged sizing into these themes.",
            "- This report uses adjusted closes through the latest cached price date, so it can evaluate through the most recent close when cache data is fresh.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(out_dir: Path, ticker_tape: pd.DataFrame, theme_leaders: pd.DataFrame, sector_leaders: pd.DataFrame, summary: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ticker_tape.to_csv(out_dir / "ticker_leadership.csv", index=False)
    theme_leaders.to_csv(out_dir / "theme_leadership.csv", index=False)
    sector_leaders.to_csv(out_dir / "sector_leadership.csv", index=False)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(summary, theme_leaders, sector_leaders, ticker_tape), encoding="utf-8")


def run(scored_path: Path, price_cache: Path, out_dir: Path, min_mcap: float, min_dollar_vol: float) -> dict[str, Any]:
    scored = read_scored(scored_path)
    ticker_tape = build_ticker_tape(scored, price_cache, min_mcap=min_mcap, min_dollar_vol=min_dollar_vol)
    if ticker_tape.empty:
        summary = {
            "status": "blocked",
            "reason": "empty scored input or missing price cache",
            "scored_source": str(scored_path),
            "price_cache": str(price_cache),
        }
        write_outputs(out_dir, ticker_tape, pd.DataFrame(), pd.DataFrame(), summary)
        return summary
    theme_leaders = aggregate_leadership(ticker_tape, "leadership_theme")
    sector_col = "sector" if "sector" in ticker_tape.columns else "leadership_theme"
    sector_leaders = aggregate_leadership(ticker_tape, sector_col)
    latest_price = pd.to_datetime(ticker_tape.get("price_date"), errors="coerce").max()
    summary = {
        "status": "completed",
        "research_only": True,
        "production_activation_allowed": False,
        "scored_source": str(scored_path),
        "price_cache": str(price_cache),
        "latest_price_date": latest_price.date().isoformat() if pd.notna(latest_price) else None,
        "tickers_scored": int(len(ticker_tape)),
        "liquid_tickers": int(ticker_tape["liquidity_pass"].sum()),
        "top_theme": None if theme_leaders.empty else str(theme_leaders.iloc[0]["leadership_theme"]),
        "top_theme_state": None if theme_leaders.empty else str(theme_leaders.iloc[0]["leadership_state"]),
        "top_tickers": ticker_tape.head(20)["ticker"].astype(str).tolist(),
    }
    write_outputs(out_dir, ticker_tape, theme_leaders, sector_leaders, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", default=DEFAULT_SCORED)
    parser.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--output-dir", "--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-mcap", type=float, default=1_000_000_000)
    parser.add_argument("--min-dollar-vol", type=float, default=20_000_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        scored_path=repo_path(args.scored),
        price_cache=repo_path(args.price_cache),
        out_dir=repo_path(args.output_dir),
        min_mcap=args.min_mcap,
        min_dollar_vol=args.min_dollar_vol,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
