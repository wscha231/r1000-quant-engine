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
SCHEMA_VERSION = "run287-hierarchical-leadership-tape-v2"
BENCHMARK_TICKERS = ("SPY", "QQQ")
RETURN_HORIZONS = {
    "1d": 1,
    "5d": 5,
    "21d": 21,
    "63d": 63,
    "126d": 126,
}
UNKNOWN_LABELS = {"", "nan", "none", "unknown", "unclassified", "n/a"}

SECTOR_ALIASES = {
    "basic materials": "Materials",
    "communication": "Communication Services",
    "communications": "Communication Services",
    "communication services": "Communication Services",
    "consumer cyclical": "Consumer Discretionary",
    "consumer discretionary": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "consumer staples": "Consumer Staples",
    "energy": "Energy",
    "financial": "Financials",
    "financials": "Financials",
    "health care": "Health Care",
    "healthcare": "Health Care",
    "industrial": "Industrials",
    "industrials": "Industrials",
    "information technology": "Information Technology",
    "internet": "Communication Services",
    "materials": "Materials",
    "real estate": "Real Estate",
    "semiconductor": "Information Technology",
    "semiconductors": "Information Technology",
    "software": "Information Technology",
    "tech": "Information Technology",
    "technology": "Information Technology",
    "utilities": "Utilities",
}

ETF_LOOKTHROUGH: dict[str, dict[str, Any]] = {
    "DRAM": {
        "theme": "memory_semiconductors",
        "label": "Roundhill Memory ETF",
        "holdings": ("MU", "SNDK", "WDC", "STX"),
    },
    "SOXX": {
        "theme": "semiconductors_broad",
        "label": "iShares Semiconductor ETF",
        "holdings": ("NVDA", "AVGO", "AMD", "MU", "INTC", "QCOM", "MRVL", "LRCX", "AMAT", "KLAC", "MCHP", "ON", "MPWR"),
    },
    "SMH": {
        "theme": "semiconductors_broad",
        "label": "VanEck Semiconductor ETF",
        "holdings": ("NVDA", "TSM", "AVGO", "ASML", "AMD", "MU", "INTC", "QCOM", "LRCX", "AMAT", "KLAC", "ARM"),
    },
    "XSD": {
        "theme": "semiconductors_equal_weight",
        "label": "SPDR S&P Semiconductor ETF",
        "holdings": ("AMD", "INTC", "MU", "MRVL", "ON", "MCHP", "LSCC", "MPWR", "TER", "ALAB", "CRUS", "ONTO"),
    },
    "ARKK": {
        "theme": "innovation_beta",
        "label": "ARK Innovation ETF",
        "holdings": ("TSLA", "COIN", "ROKU", "HOOD", "CRSP", "PATH", "PLTR"),
    },
    "XME": {
        "theme": "metals_mining",
        "label": "SPDR Metals & Mining ETF",
        "holdings": ("MP", "FCX", "CLF", "X", "NUE", "STLD", "AA"),
    },
    "URA": {
        "theme": "nuclear_uranium",
        "label": "Global X Uranium ETF",
        "holdings": ("CCJ", "UEC", "UUUU", "LEU", "NXE", "DNN"),
    },
    "NLR": {
        "theme": "nuclear_power",
        "label": "VanEck Uranium and Nuclear ETF",
        "holdings": ("CEG", "BWXT", "CCJ", "LEU", "SMR", "OKLO"),
    },
    "ITA": {
        "theme": "aerospace_defense",
        "label": "iShares U.S. Aerospace & Defense ETF",
        "holdings": ("RTX", "LMT", "NOC", "GD", "RKLB", "KTOS", "HWM"),
    },
    "XBI": {
        "theme": "biotech_small",
        "label": "SPDR Biotech ETF",
        "holdings": ("EXEL", "INSM", "CRSP", "BEAM", "EDIT"),
    },
}

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
        "tickers": ("NVDA", "AMD", "AVGO", "ARM", "MRVL", "TSM", "ASML", "LRCX", "AMAT", "KLAC", "INTC", "QCOM", "ON", "MCHP", "TER", "ALAB", "LSCC"),
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


def percentile_rank(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if not numeric.notna().any():
        return pd.Series(0.5, index=values.index, dtype=float)
    return numeric.rank(method="average", pct=True).fillna(0.5)


def normalize_label(value: Any, default: str = "Unknown") -> str:
    text = " ".join(str(value or "").strip().split())
    return default if text.lower() in UNKNOWN_LABELS else text


def canonical_sector(value: Any) -> str:
    text = normalize_label(value)
    return SECTOR_ALIASES.get(text.lower(), text)


def first_present(row: pd.Series, columns: tuple[str, ...]) -> str:
    for column in columns:
        value = normalize_label(row.get(column), "")
        if value:
            return value
    return ""


def truthy(values: pd.Series) -> pd.Series:
    return values.astype(str).str.strip().str.lower().isin(
        {"1", "true", "yes", "y"}
    )


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


def common_benchmark_close(
    price_cache: Path,
    requested_as_of: pd.Timestamp | None = None,
) -> tuple[pd.Timestamp | None, dict[str, pd.DataFrame]]:
    frames = {
        ticker: load_price_cache(price_cache, ticker)
        for ticker in BENCHMARK_TICKERS
    }
    if any(frame.empty for frame in frames.values()):
        return None, frames
    common: pd.DatetimeIndex | None = None
    for frame in frames.values():
        dates = pd.DatetimeIndex(frame.index).normalize().unique()
        if requested_as_of is not None:
            dates = dates[dates <= requested_as_of.normalize()]
        common = dates if common is None else common.intersection(dates)
    if common is None or common.empty:
        return None, frames
    return pd.Timestamp(common.max()).normalize(), frames


def benchmark_metrics(
    frames: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    for ticker, frame in frames.items():
        close = pd.to_numeric(
            frame.loc[frame.index.normalize() <= as_of, "close"],
            errors="coerce",
        ).dropna()
        row = {
            f"ret_{label}": trailing_return(close, days)
            for label, days in RETURN_HORIZONS.items()
        }
        row["close"] = safe_float(close.iloc[-1], np.nan) if not close.empty else np.nan
        metrics[ticker] = row
    return metrics


def price_metrics(
    price_cache: Path,
    ticker: str,
    *,
    as_of: pd.Timestamp | None = None,
) -> dict[str, Any]:
    px = load_price_cache(price_cache, ticker)
    if px.empty or len(px) < 6:
        return {"ticker": ticker, "price_status": "missing_or_short"}
    if as_of is not None:
        px = px.loc[px.index.normalize() <= as_of.normalize()].copy()
        if px.empty:
            return {"ticker": ticker, "price_status": "missing_or_short"}
    close = pd.to_numeric(px["close"], errors="coerce").dropna()
    volume = pd.to_numeric(px["volume"], errors="coerce")
    dollar_volume = pd.to_numeric(px["dollar_volume"], errors="coerce")
    if close.empty:
        return {"ticker": ticker, "price_status": "missing_or_short"}
    price_date = pd.Timestamp(close.index[-1]).normalize()
    if as_of is not None and price_date != as_of.normalize():
        return {
            "ticker": ticker,
            "price_status": "stale_close",
            "price_date": price_date.date().isoformat(),
        }
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
    ma20 = safe_float(close.tail(20).mean(), np.nan)
    ma50 = safe_float(close.tail(50).mean(), np.nan)
    ma200 = safe_float(close.tail(200).mean(), np.nan)
    last_close = safe_float(close.iloc[-1], np.nan)
    return {
        "ticker": ticker,
        "price_status": "ok",
        "price_date": price_date.date().isoformat(),
        "close": last_close,
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
        "price_above_ma20": bool(math.isfinite(ma20) and last_close >= ma20),
        "price_above_ma50": bool(math.isfinite(ma50) and last_close >= ma50),
        "price_above_ma200": bool(math.isfinite(ma200) and last_close >= ma200),
    }


def fetch_yfinance_history(ticker: str, days: int = 260) -> pd.DataFrame:
    try:
        import yfinance as yf
    except Exception:
        return pd.DataFrame()
    try:
        from datetime import datetime, timedelta

        end = datetime.now()
        start = end - timedelta(days=int(days * 1.8))
        df = yf.Ticker(ticker).history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), auto_adjust=True)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.index = pd.to_datetime(out.index, errors="coerce").tz_localize(None)
    out = out[out.index.notna()].sort_index()
    if "Close" not in out.columns:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "close": pd.to_numeric(out["Close"], errors="coerce"),
            "volume": pd.to_numeric(out.get("Volume", np.nan), errors="coerce"),
            "dollar_volume": pd.to_numeric(out["Close"], errors="coerce") * pd.to_numeric(out.get("Volume", np.nan), errors="coerce"),
        },
        index=out.index,
    ).dropna(subset=["close"])


def etf_price_frame(
    price_cache: Path,
    ticker: str,
    *,
    allow_network: bool = True,
) -> pd.DataFrame:
    cached = load_price_cache(price_cache, ticker)
    if not cached.empty and len(cached) >= 22:
        return cached
    return fetch_yfinance_history(ticker) if allow_network else pd.DataFrame()


def etf_attention(
    price_cache: Path,
    *,
    as_of: pd.Timestamp | None = None,
    allow_network: bool = True,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for ticker, spec in ETF_LOOKTHROUGH.items():
        px = etf_price_frame(
            price_cache,
            ticker,
            allow_network=allow_network,
        )
        if as_of is not None and not px.empty:
            px = px.loc[px.index.normalize() <= as_of.normalize()].copy()
        if px.empty or len(px) < 22:
            rows.append(
                {
                    "etf": ticker,
                    "theme": spec["theme"],
                    "label": spec["label"],
                    "price_status": "missing_or_short",
                    "holdings": ",".join(spec.get("holdings", ())),
                }
            )
            continue
        close = pd.to_numeric(px["close"], errors="coerce").dropna()
        price_date = pd.Timestamp(close.index[-1]).normalize()
        if as_of is not None and price_date != as_of.normalize():
            rows.append(
                {
                    "etf": ticker,
                    "theme": spec["theme"],
                    "label": spec["label"],
                    "price_status": "stale_close",
                    "price_date": price_date.date().isoformat(),
                    "holdings": ",".join(spec.get("holdings", ())),
                }
            )
            continue
        volume = pd.to_numeric(px.get("volume"), errors="coerce")
        dollar_volume = pd.to_numeric(px.get("dollar_volume"), errors="coerce")
        vol_z = 0.0
        if len(volume) > 21:
            denom = safe_float(volume.shift(1).rolling(20).std(ddof=0).iloc[-1], 0.0)
            base = safe_float(volume.shift(1).rolling(20).mean().iloc[-1], 0.0)
            if denom > 1e-12:
                vol_z = (safe_float(volume.iloc[-1]) - base) / denom
        rows.append(
            {
                "etf": ticker,
                "theme": spec["theme"],
                "label": spec["label"],
                "price_status": "ok",
                "price_date": price_date.date().isoformat(),
                "ret_1d": trailing_return(close, 1),
                "ret_5d": trailing_return(close, 5),
                "ret_21d": trailing_return(close, 21),
                "ret_63d": trailing_return(close, 63),
                "volume_z_20d": vol_z,
                "dollar_volume_20d": safe_float(dollar_volume.tail(20).mean(), np.nan),
                "holdings": ",".join(spec.get("holdings", ())),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    for col in ("ret_1d", "ret_5d", "ret_21d", "ret_63d", "volume_z_20d", "dollar_volume_20d"):
        out[col] = pd.to_numeric(out.get(col), errors="coerce")
    out["attention_score"] = (
        0.25 * robust_z(out["ret_5d"])
        + 0.25 * robust_z(out["ret_21d"])
        + 0.20 * robust_z(out["ret_63d"])
        + 0.15 * out["volume_z_20d"].fillna(0.0).clip(-6, 6)
        + 0.15 * robust_z(np.log1p(out["dollar_volume_20d"].fillna(0.0)))
    )
    return out.sort_values("attention_score", ascending=False, na_position="last").reset_index(drop=True)


def build_etf_lookthrough_watchlist(ticker_tape: pd.DataFrame, etf_attention_frame: pd.DataFrame) -> pd.DataFrame:
    if etf_attention_frame.empty:
        return pd.DataFrame()
    tape_by_ticker = ticker_tape.set_index("ticker", drop=False) if not ticker_tape.empty and "ticker" in ticker_tape.columns else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for etf in etf_attention_frame.to_dict("records"):
        attention = safe_float(etf.get("attention_score"))
        holdings = [x.strip().upper() for x in str(etf.get("holdings") or "").split(",") if x.strip()]
        for ticker in holdings:
            tape = tape_by_ticker.loc[ticker].to_dict() if not tape_by_ticker.empty and ticker in tape_by_ticker.index else {}
            rows.append(
                {
                    "ticker": ticker,
                    "source_etf": etf.get("etf"),
                    "source_etf_theme": etf.get("theme"),
                    "source_etf_label": etf.get("label"),
                    "etf_attention_score": attention,
                    "ticker_in_scored_universe": bool(tape),
                    "ticker_participation_score": safe_float(tape.get("participation_score"), np.nan),
                    "ticker_ret_5d": safe_float(tape.get("ret_5d"), np.nan),
                    "ticker_ret_21d": safe_float(tape.get("ret_21d"), np.nan),
                    "ticker_dollar_volume_20d": safe_float(tape.get("dollar_volume_20d"), np.nan),
                    "ticker_market_cap": safe_float(tape.get("market_cap"), np.nan),
                    "ticker_name": tape.get("Name") or tape.get("name") or "",
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["combined_watch_score"] = (
        pd.to_numeric(out["etf_attention_score"], errors="coerce").fillna(0.0)
        + 0.50 * pd.to_numeric(out["ticker_participation_score"], errors="coerce").fillna(0.0)
    )
    return out.sort_values(["combined_watch_score", "etf_attention_score"], ascending=False, na_position="last").reset_index(drop=True)


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


def add_hierarchy_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["sector_normalized"] = out.apply(
        lambda row: canonical_sector(
            first_present(row, ("sector", "yf_sector", "sage_sector"))
        ),
        axis=1,
    )
    out["industry_group_normalized"] = out.apply(
        lambda row: normalize_label(
            first_present(
                row,
                ("industry_group", "industry", "yf_industry", "sage_sector"),
            )
        ),
        axis=1,
    )
    out["subindustry_normalized"] = out.apply(
        lambda row: normalize_label(
            first_present(
                row,
                (
                    "subindustry",
                    "sub_industry",
                    "industry",
                    "yf_industry",
                    "industry_group",
                ),
            )
        ),
        axis=1,
    )
    return out


def build_ticker_tape(
    scored: pd.DataFrame,
    price_cache: Path,
    min_mcap: float,
    min_dollar_vol: float,
    *,
    as_of: pd.Timestamp,
    benchmarks: dict[str, dict[str, float]],
) -> pd.DataFrame:
    if scored.empty or "ticker" not in scored.columns:
        return pd.DataFrame()
    d = scored.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = d[(d["ticker"] != "") & ~d["ticker"].isin(CASH_TICKERS)].drop_duplicates("ticker", keep="last")
    rows: list[dict[str, Any]] = []
    for row in d.itertuples(index=False):
        ticker = str(getattr(row, "ticker", "")).upper()
        rec = d.loc[d["ticker"].eq(ticker)].iloc[-1].to_dict()
        rec.update(price_metrics(price_cache, ticker, as_of=as_of))
        rows.append(rec)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["leadership_theme"] = out.apply(infer_theme, axis=1)
    out = add_hierarchy_columns(out)
    market_cap_source = out["market_cap_live"] if "market_cap_live" in out.columns else out.get("mktcap", pd.Series(0.0, index=out.index))
    out["market_cap"] = pd.to_numeric(market_cap_source, errors="coerce").fillna(0.0)
    out["dollar_volume_20d"] = pd.to_numeric(out.get("dollar_volume_20d"), errors="coerce").fillna(0.0)
    for col in ("ret_1d", "ret_5d", "ret_21d", "ret_63d", "ret_126d", "volume_z_20d"):
        source = out[col] if col in out.columns else pd.Series(np.nan, index=out.index)
        out[col] = pd.to_numeric(source, errors="coerce")
    out["exact_close"] = out.get(
        "price_status",
        pd.Series("", index=out.index),
    ).eq("ok")
    eligible = pd.Series(True, index=out.index)
    if "research_eligible_after_quarantine" in out.columns:
        eligible &= truthy(out["research_eligible_after_quarantine"])
    if "corporate_action_quarantine" in out.columns:
        eligible &= ~truthy(out["corporate_action_quarantine"])
    out["research_eligible"] = eligible
    liquid = (
        out["exact_close"]
        & out["research_eligible"]
        & (out["market_cap"] >= min_mcap)
        & (out["dollar_volume_20d"] >= min_dollar_vol)
    )
    out["liquidity_pass"] = liquid
    for benchmark in BENCHMARK_TICKERS:
        key = benchmark.lower()
        benchmark_row = benchmarks.get(benchmark, {})
        for label in RETURN_HORIZONS:
            out[f"rs_{key}_{label}"] = (
                out[f"ret_{label}"]
                - safe_float(benchmark_row.get(f"ret_{label}"), np.nan)
            )
    for label in RETURN_HORIZONS:
        out[f"market_rs_{label}"] = (
            out[f"rs_spy_{label}"] + out[f"rs_qqq_{label}"]
        ) / 2.0
    out["ret_5d_z"] = robust_z(out["ret_5d"])
    out["ret_1d_z"] = robust_z(out["ret_1d"])
    out["ret_21d_z"] = robust_z(out["ret_21d"])
    out["ret_63d_z"] = robust_z(out["ret_63d"])
    out["dollar_volume_z"] = robust_z(np.log1p(out["dollar_volume_20d"]))
    out["volume_z_20d"] = out["volume_z_20d"].fillna(0.0).clip(-6, 6)
    out["short_term_acceleration"] = (
        out["ret_5d"].fillna(0.0) - (out["ret_21d"].fillna(0.0) / 4.0)
    )
    out["market_rs_acceleration"] = (
        out["market_rs_5d"].fillna(0.0)
        - (out["market_rs_21d"].fillna(0.0) / 4.0)
    )
    out["market_rs_5d_z"] = robust_z(out["market_rs_5d"])
    out["market_rs_21d_z"] = robust_z(out["market_rs_21d"])
    out["market_rs_63d_z"] = robust_z(out["market_rs_63d"])
    out["market_rs_126d_z"] = robust_z(out["market_rs_126d"])
    out["market_rs_acceleration_z"] = robust_z(out["market_rs_acceleration"])
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
        0.15 * out["market_rs_5d_z"]
        + 0.30 * out["market_rs_21d_z"]
        + 0.25 * out["market_rs_63d_z"]
        + 0.10 * out["market_rs_126d_z"]
        + 0.10 * out["market_rs_acceleration_z"]
        + 0.05 * _num_col("breakout_setup_quality_score")
        + 0.05 * _num_col("h6_dynamic_leader_score")
    )
    out["participation_score"] = (
        0.45 * out["early_leadership_score"]
        + 0.35 * out["bubble_climax_score"]
        + 0.20 * out["dollar_volume_z"]
    )
    out["stock_leadership_score"] = (
        0.65 * out["early_leadership_score"]
        + 0.15 * out["ret_1d_z"]
        + 0.10 * out["volume_z_20d"]
        + 0.10 * out["dollar_volume_z"]
    )
    out.loc[~out["liquidity_pass"], ["bubble_climax_score", "early_leadership_score", "participation_score"]] -= 2.0
    out.loc[~out["liquidity_pass"], "stock_leadership_score"] -= 2.0
    out["stock_leadership_rank_pct"] = percentile_rank(
        out["stock_leadership_score"]
    )
    out["stock_state"] = np.select(
        [
            out["exact_close"]
            & out["market_rs_1d"].le(-0.025)
            & out["market_rs_5d"].le(-0.04),
            out["exact_close"]
            & out["market_rs_21d"].gt(0.0)
            & out["market_rs_5d"].lt(-0.02),
            out["liquidity_pass"]
            & out["stock_leadership_rank_pct"].ge(0.85)
            & out["market_rs_21d"].gt(0.0)
            & out["market_rs_63d"].gt(0.0),
            out["liquidity_pass"]
            & out["stock_leadership_rank_pct"].ge(0.70)
            & out["market_rs_acceleration"].gt(0.0),
        ],
        ["BREAKDOWN", "WEAKENING", "LEADING", "EMERGING_WATCH"],
        default="NEUTRAL",
    )
    return out.sort_values("stock_leadership_score", ascending=False, na_position="last").reset_index(drop=True)


def aggregate_leadership(
    tape: pd.DataFrame,
    group_col: str | list[str] | tuple[str, ...],
    *,
    level: str | None = None,
) -> pd.DataFrame:
    group_cols = [group_col] if isinstance(group_col, str) else list(group_col)
    if tape.empty or any(column not in tape.columns for column in group_cols):
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for labels, g in tape.groupby(group_cols, dropna=False):
        if not isinstance(labels, tuple):
            labels = (labels,)
        liquid = g[g["liquidity_pass"]].copy()
        if liquid.empty:
            continue
        top = liquid.sort_values("stock_leadership_score", ascending=False).head(8)
        record: dict[str, Any] = {
            column: normalize_label(value)
            for column, value in zip(group_cols, labels)
        }
        record.update(
            {
                "level": level or group_cols[-1],
                "group_label": normalize_label(labels[-1]),
                "group_key": "|".join(normalize_label(value) for value in labels),
                "member_count": int(len(liquid)),
                "active_count_1d_gt_8pct": int((liquid["ret_1d"] >= 0.08).sum()),
                "active_count_5d_gt_20pct": int((liquid["ret_5d"] >= 0.20).sum()),
                "breadth_1d_positive": float((liquid["ret_1d"] > 0).mean()),
                "breadth_5d_positive": float((liquid["ret_5d"] > 0).mean()),
                "breadth_21d_positive": float((liquid["ret_21d"] > 0).mean()),
                "breadth_above_ma20": float(truthy(liquid["price_above_ma20"]).mean()),
                "breadth_above_ma50": float(truthy(liquid["price_above_ma50"]).mean()),
                "breadth_above_ma200": float(truthy(liquid["price_above_ma200"]).mean()),
                "median_ret_1d": float(liquid["ret_1d"].median(skipna=True)),
                "median_ret_5d": float(liquid["ret_5d"].median(skipna=True)),
                "median_ret_21d": float(liquid["ret_21d"].median(skipna=True)),
                "median_ret_63d": float(liquid["ret_63d"].median(skipna=True)),
                "median_ret_126d": float(liquid["ret_126d"].median(skipna=True)),
                "median_market_rs_1d": float(liquid["market_rs_1d"].median(skipna=True)),
                "median_market_rs_5d": float(liquid["market_rs_5d"].median(skipna=True)),
                "median_market_rs_21d": float(liquid["market_rs_21d"].median(skipna=True)),
                "median_market_rs_63d": float(liquid["market_rs_63d"].median(skipna=True)),
                "median_market_rs_126d": float(liquid["market_rs_126d"].median(skipna=True)),
                "median_market_rs_acceleration": float(
                    liquid["market_rs_acceleration"].median(skipna=True)
                ),
                "top_participation_score": float(top["participation_score"].mean()),
                "top_stock_leadership_score": float(top["stock_leadership_score"].mean()),
                "top_bubble_climax_score": float(top["bubble_climax_score"].mean()),
                "top_early_leadership_score": float(top["early_leadership_score"].mean()),
                "dollar_volume_20d_sum": float(liquid["dollar_volume_20d"].sum()),
                "top_tickers": ",".join(top["ticker"].astype(str).head(8)),
            }
        )
        rows.append(record)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["leadership_score"] = (
        0.15 * robust_z(out["median_market_rs_5d"])
        + 0.25 * robust_z(out["median_market_rs_21d"])
        + 0.20 * robust_z(out["median_market_rs_63d"])
        + 0.10 * robust_z(out["median_market_rs_126d"])
        + 0.10 * robust_z(out["median_market_rs_acceleration"])
        + 0.10 * out["breadth_21d_positive"].fillna(0.0)
        + 0.05 * out["breadth_above_ma50"].fillna(0.0)
        + 0.05 * robust_z(out["top_stock_leadership_score"])
    )
    out["leadership_rank_pct"] = percentile_rank(out["leadership_score"])
    out["leadership_rank"] = out["leadership_score"].rank(
        method="first",
        ascending=False,
    ).astype(int)
    out["raw_leadership_state"] = out.apply(classify_group, axis=1)
    out["leadership_state"] = out["raw_leadership_state"]
    return out.sort_values("leadership_score", ascending=False).reset_index(drop=True)


def classify_group(row: pd.Series) -> str:
    members = int(safe_float(row.get("member_count"), 0.0))
    rs1 = safe_float(row.get("median_market_rs_1d"), 0.0)
    rs5 = safe_float(row.get("median_market_rs_5d"), 0.0)
    rs21 = safe_float(row.get("median_market_rs_21d"), 0.0)
    rs63 = safe_float(row.get("median_market_rs_63d"), 0.0)
    acceleration = safe_float(row.get("median_market_rs_acceleration"), 0.0)
    breadth1 = safe_float(row.get("breadth_1d_positive"), 0.0)
    breadth5 = safe_float(row.get("breadth_5d_positive"), 0.0)
    breadth21 = safe_float(row.get("breadth_21d_positive"), 0.0)
    rank_pct = safe_float(row.get("leadership_rank_pct"), 0.0)
    if members < 2:
        return "DEGRADED_DATA"
    if (rs1 <= -0.025 and breadth1 <= 0.25) or (
        rs5 <= -0.05 and breadth21 <= 0.35
    ):
        return "BREAKDOWN"
    if rs21 > 0.0 and (rs5 < -0.02 or acceleration < -0.015):
        return "WEAKENING"
    if rs5 > 0.02 and rs21 < 0.0 and breadth5 >= 0.55:
        return "REENTRY"
    if (
        rank_pct >= 0.80
        and rs21 > 0.02
        and rs63 > 0.0
        and breadth21 >= 0.55
    ):
        return "LEADING"
    if (
        rank_pct >= 0.70
        and rs5 > 0.0
        and acceleration > 0.0
        and breadth21 >= 0.50
    ):
        return "EMERGING"
    return "NEUTRAL"


def attach_parent_relative(
    child: pd.DataFrame,
    parent: pd.DataFrame,
    *,
    parent_columns: tuple[str, ...],
) -> pd.DataFrame:
    if child.empty or parent.empty:
        return child
    parent_metrics = parent[
        [*parent_columns, "median_ret_21d", "median_market_rs_21d"]
    ].rename(
        columns={
            "median_ret_21d": "parent_median_ret_21d",
            "median_market_rs_21d": "parent_median_market_rs_21d",
        }
    )
    out = child.merge(parent_metrics, on=list(parent_columns), how="left")
    out["relative_to_parent_21d"] = (
        out["median_ret_21d"] - out["parent_median_ret_21d"]
    )
    out["leadership_score"] = (
        out["leadership_score"]
        + 0.15 * robust_z(out["relative_to_parent_21d"])
    )
    out["leadership_rank_pct"] = percentile_rank(out["leadership_score"])
    out["leadership_rank"] = out["leadership_score"].rank(
        method="first",
        ascending=False,
    ).astype(int)
    out["raw_leadership_state"] = out.apply(classify_group, axis=1)
    out["leadership_state"] = out["raw_leadership_state"]
    return out.sort_values("leadership_score", ascending=False).reset_index(drop=True)


def combine_hierarchy(
    sector: pd.DataFrame,
    industry: pd.DataFrame,
    subsector: pd.DataFrame,
    themes: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    frames = [
        frame
        for frame in (sector, industry, subsector, themes)
        if not frame.empty
    ]
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    out["as_of_date"] = as_of.date().isoformat()
    out["research_only"] = True
    out["production_activation_allowed"] = False
    return out


def apply_state_confirmation(
    current: pd.DataFrame,
    previous: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if current.empty:
        return current, pd.DataFrame()
    key = ["level", "group_key"]
    prior_columns = [
        *key,
        "as_of_date",
        "raw_leadership_state",
        "leadership_state",
        "state_confirmation_count",
        "leadership_rank",
    ]
    prior = (
        previous[[column for column in prior_columns if column in previous.columns]]
        .copy()
        if not previous.empty
        else pd.DataFrame(columns=prior_columns)
    )
    for column in prior_columns:
        if column not in prior.columns:
            prior[column] = np.nan
    rename = {
        "as_of_date": "previous_as_of_date",
        "raw_leadership_state": "previous_raw_state",
        "leadership_state": "previous_state",
        "state_confirmation_count": "previous_confirmation_count",
        "leadership_rank": "previous_rank",
    }
    prior = prior.rename(columns=rename)
    out = current.merge(prior, on=key, how="left")
    same_state = out["raw_leadership_state"].eq(out.get("previous_raw_state"))
    same_date = out.get(
        "previous_as_of_date",
        pd.Series("", index=out.index),
    ).astype(str).eq(as_of.date().isoformat())
    prior_count = pd.to_numeric(
        out.get("previous_confirmation_count", 0),
        errors="coerce",
    ).fillna(0).astype(int)
    out["state_confirmation_count"] = np.where(
        same_date & same_state,
        prior_count.clip(lower=1),
        np.where(same_state, prior_count + 1, 1),
    )

    def published_state(row: pd.Series) -> str:
        state = str(row.get("raw_leadership_state") or "NEUTRAL")
        count = int(safe_float(row.get("state_confirmation_count"), 1.0))
        if state == "EMERGING":
            return "EMERGING_CONFIRMED" if count >= 2 else "EMERGING_WATCH"
        if state == "REENTRY":
            return "REENTRY_CONFIRMED" if count >= 2 else "REENTRY_WATCH"
        return state

    out["leadership_state"] = out.apply(published_state, axis=1)
    out["state_transition"] = (
        out.get("previous_state", pd.Series("", index=out.index))
        .fillna("NEW")
        .astype(str)
        + "->"
        + out["leadership_state"].astype(str)
    )
    out["rank_change"] = (
        pd.to_numeric(out.get("previous_rank"), errors="coerce")
        - pd.to_numeric(out["leadership_rank"], errors="coerce")
    )
    transition_columns = [
        "as_of_date",
        "level",
        "group_key",
        "group_label",
        "previous_as_of_date",
        "previous_state",
        "leadership_state",
        "state_transition",
        "state_confirmation_count",
        "previous_rank",
        "leadership_rank",
        "rank_change",
        "top_tickers",
        "research_only",
        "production_activation_allowed",
    ]
    transitions = out[
        [column for column in transition_columns if column in out.columns]
    ].copy()
    return out, transitions


def build_leader_watchlist(
    tape: pd.DataFrame,
    hierarchy: pd.DataFrame,
) -> pd.DataFrame:
    if tape.empty or hierarchy.empty:
        return pd.DataFrame()
    sector = hierarchy[hierarchy["level"].eq("sector")][
        ["sector_normalized", "leadership_state", "leadership_rank"]
    ].rename(
        columns={
            "leadership_state": "sector_state",
            "leadership_rank": "sector_rank",
        }
    )
    subsector = hierarchy[hierarchy["level"].eq("subsector")][
        [
            "sector_normalized",
            "industry_group_normalized",
            "subindustry_normalized",
            "leadership_state",
            "leadership_rank",
            "relative_to_parent_21d",
        ]
    ].rename(
        columns={
            "leadership_state": "subsector_state",
            "leadership_rank": "subsector_rank",
        }
    )
    out = tape.merge(sector, on="sector_normalized", how="left")
    out = out.merge(
        subsector,
        on=[
            "sector_normalized",
            "industry_group_normalized",
            "subindustry_normalized",
        ],
        how="left",
    )
    out["within_subsector_rank_pct"] = out.groupby(
        [
            "sector_normalized",
            "industry_group_normalized",
            "subindustry_normalized",
        ],
        dropna=False,
    )["stock_leadership_score"].rank(method="average", pct=True)
    positive_group = out["subsector_state"].isin(
        {
            "LEADING",
            "EMERGING_WATCH",
            "EMERGING_CONFIRMED",
            "REENTRY_WATCH",
            "REENTRY_CONFIRMED",
        }
    ) | out["sector_state"].isin(
        {"LEADING", "EMERGING_WATCH", "EMERGING_CONFIRMED"}
    )
    risk_group = out["subsector_state"].isin({"BREAKDOWN", "WEAKENING"}) | out[
        "sector_state"
    ].isin({"BREAKDOWN", "WEAKENING"})
    out["suggested_action"] = np.select(
        [
            out["stock_state"].eq("BREAKDOWN") | risk_group,
            out["liquidity_pass"]
            & positive_group
            & out["within_subsector_rank_pct"].ge(0.60)
            & out["market_rs_21d"].gt(0.0),
            out["liquidity_pass"]
            & out["stock_state"].eq("EMERGING_WATCH")
            & out["market_rs_acceleration"].gt(0.0),
        ],
        ["RISK_REVIEW", "LEADER_REVIEW", "EMERGING_REVIEW"],
        default="WATCH",
    )
    out["is_new_leader"] = out["suggested_action"].isin(
        {"LEADER_REVIEW", "EMERGING_REVIEW"}
    ) & (
        out["stock_state"].eq("EMERGING_WATCH")
        | out["subsector_state"].astype(str).str.startswith("EMERGING")
        | out["subsector_state"].astype(str).str.startswith("REENTRY")
    )
    out["research_only"] = True
    out["production_activation_allowed"] = False
    out["target_book_mutation_allowed"] = False
    keep = [
        "ticker",
        "Name",
        "price_date",
        "sector_normalized",
        "industry_group_normalized",
        "subindustry_normalized",
        "leadership_theme",
        "sector_state",
        "sector_rank",
        "subsector_state",
        "subsector_rank",
        "stock_state",
        "ret_1d",
        "ret_5d",
        "ret_21d",
        "ret_63d",
        "rs_spy_5d",
        "rs_spy_21d",
        "rs_qqq_5d",
        "rs_qqq_21d",
        "market_rs_acceleration",
        "relative_to_parent_21d",
        "stock_leadership_score",
        "stock_leadership_rank_pct",
        "within_subsector_rank_pct",
        "liquidity_pass",
        "suggested_action",
        "is_new_leader",
        "research_only",
        "production_activation_allowed",
        "target_book_mutation_allowed",
    ]
    out = out[[column for column in keep if column in out.columns]]
    priority = {
        "LEADER_REVIEW": 0,
        "EMERGING_REVIEW": 1,
        "RISK_REVIEW": 2,
        "WATCH": 3,
    }
    out["_priority"] = out["suggested_action"].map(priority).fillna(9)
    out = out.sort_values(
        ["_priority", "stock_leadership_score"],
        ascending=[True, False],
    ).drop(columns="_priority")
    return out.head(100).reset_index(drop=True)


def render_report(
    summary: dict[str, Any],
    themes: pd.DataFrame,
    sectors: pd.DataFrame,
    industries: pd.DataFrame,
    subsectors: pd.DataFrame,
    tickers: pd.DataFrame,
    etfs: pd.DataFrame,
    lookthrough: pd.DataFrame,
    watchlist: pd.DataFrame,
) -> str:
    lines = [
        "# Hierarchical Market Leadership Tape",
        "",
        "Report-only daily sidecar. It detects sector, industry, subsector, theme, and stock leadership and does not alter production portfolios.",
        "",
        "## Freshness",
        "",
        f"- Scored source: `{summary.get('scored_source')}`",
        f"- Common benchmark close: `{summary.get('common_close_date')}`",
        f"- Tickers scored: {summary.get('tickers_scored')}",
        f"- Exact-close coverage: {safe_float(summary.get('exact_close_coverage')):.1%}",
        f"- Liquid tickers: {summary.get('liquid_tickers')}",
        "",
        "## Top Sectors",
        "",
    ]
    for row in (sectors.head(11).to_dict("records") if not sectors.empty else []):
        lines.append(
            f"- `{row.get('group_label')}`: rank {int(safe_float(row.get('leadership_rank'), 0))}, "
            f"state `{row.get('leadership_state')}`, market RS 5d "
            f"{safe_float(row.get('median_market_rs_5d')):.2%}, 21d "
            f"{safe_float(row.get('median_market_rs_21d')):.2%}, breadth "
            f"{safe_float(row.get('breadth_21d_positive')):.0%}, top `{row.get('top_tickers')}`"
        )
    lines.extend(["", "## Top Subsectors", ""])
    for row in (subsectors.head(15).to_dict("records") if not subsectors.empty else []):
        lines.append(
            f"- `{row.get('sector_normalized')}` / `{row.get('group_label')}`: "
            f"state `{row.get('leadership_state')}`, parent-relative 21d "
            f"{safe_float(row.get('relative_to_parent_21d')):.2%}, top `{row.get('top_tickers')}`"
        )
    lines.extend(["", "## Top Themes", ""])
    for row in (themes.head(10).to_dict("records") if not themes.empty else []):
        lines.append(
            f"- `{row.get('group_label')}`: score {safe_float(row.get('leadership_score')):.2f}, "
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
    lines.extend(["", "## New Leader Review", ""])
    for row in (
        watchlist[
            watchlist.get(
                "suggested_action",
                pd.Series("", index=watchlist.index),
            ).isin({"LEADER_REVIEW", "EMERGING_REVIEW"})
        ]
        .head(20)
        .to_dict("records")
        if not watchlist.empty
        else []
    ):
        lines.append(
            f"- `{row.get('ticker')}`: `{row.get('suggested_action')}`, "
            f"{row.get('sector_normalized')} / {row.get('subindustry_normalized')}, "
            f"SPY RS 21d {safe_float(row.get('rs_spy_21d')):.2%}, "
            f"QQQ RS 21d {safe_float(row.get('rs_qqq_21d')):.2%}"
        )
    lines.extend(["", "## ETF Attention", ""])
    for row in (etfs.head(10).to_dict("records") if not etfs.empty else []):
        lines.append(
            f"- `{row.get('etf')}` {row.get('label')}: theme `{row.get('theme')}`, "
            f"5d {safe_float(row.get('ret_5d')):.2%}, 21d {safe_float(row.get('ret_21d')):.2%}, "
            f"attention {safe_float(row.get('attention_score')):.2f}, holdings `{row.get('holdings')}`"
        )
    lines.extend(["", "## ETF Look-Through Watchlist", ""])
    for row in (lookthrough.head(20).to_dict("records") if not lookthrough.empty else []):
        lines.append(
            f"- `{row.get('ticker')}` via `{row.get('source_etf')}`/{row.get('source_etf_theme')}: "
            f"ETF attention {safe_float(row.get('etf_attention_score')):.2f}, "
            f"ticker score {safe_float(row.get('ticker_participation_score')):.2f}, "
            f"5d {safe_float(row.get('ticker_ret_5d')):.2%}, in universe `{row.get('ticker_in_scored_universe')}`"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `EMERGING_WATCH` and `REENTRY_WATCH` need a second distinct close before confirmation.",
            "- `BREAKDOWN` and `WEAKENING` are review signals for the affected hierarchy only; they do not raise whole-portfolio cash.",
            "- ETF attention is a proxy from ETF price/volume/dollar-volume behavior plus a curated look-through seed list; it is not a verified fund-flow feed.",
            "- All stock and benchmark comparisons are truncated to one common cached close. Future and stale rows are excluded.",
            "- `LEADER_REVIEW` is not an order or target weight. Promotion still requires historical/OOS and forward-paper validation.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    out_dir: Path,
    ticker_tape: pd.DataFrame,
    theme_leaders: pd.DataFrame,
    sector_leaders: pd.DataFrame,
    industry_leaders: pd.DataFrame,
    subsector_leaders: pd.DataFrame,
    hierarchy: pd.DataFrame,
    transitions: pd.DataFrame,
    watchlist: pd.DataFrame,
    etf_attention_frame: pd.DataFrame,
    lookthrough: pd.DataFrame,
    summary: dict[str, Any],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ticker_tape.to_csv(out_dir / "ticker_leadership.csv", index=False)
    theme_leaders.to_csv(out_dir / "theme_leadership.csv", index=False)
    sector_leaders.to_csv(out_dir / "sector_leadership.csv", index=False)
    industry_leaders.to_csv(out_dir / "industry_group_leadership.csv", index=False)
    subsector_leaders.to_csv(out_dir / "subsector_leadership.csv", index=False)
    hierarchy.to_csv(out_dir / "hierarchical_leadership.csv", index=False)
    transitions.to_csv(out_dir / "leadership_transitions.csv", index=False)
    watchlist.to_csv(out_dir / "leader_watchlist.csv", index=False)
    etf_attention_frame.to_csv(out_dir / "etf_attention.csv", index=False)
    lookthrough.to_csv(out_dir / "etf_lookthrough_watchlist.csv", index=False)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (out_dir / "report.md").write_text(
        render_report(
            summary,
            theme_leaders,
            sector_leaders,
            industry_leaders,
            subsector_leaders,
            ticker_tape,
            etf_attention_frame,
            lookthrough,
            watchlist,
        ),
        encoding="utf-8",
    )


def run(
    scored_path: Path,
    price_cache: Path,
    out_dir: Path,
    min_mcap: float,
    min_dollar_vol: float,
    *,
    as_of: str = "",
    allow_network: bool = True,
    min_exact_close_coverage: float = 0.10,
) -> dict[str, Any]:
    previous_path = out_dir / "hierarchical_leadership.csv"
    try:
        previous = pd.read_csv(previous_path) if previous_path.exists() else pd.DataFrame()
    except Exception:
        previous = pd.DataFrame()
    scored = read_scored(scored_path)
    requested_as_of = (
        pd.Timestamp(as_of).normalize()
        if str(as_of or "").strip()
        else None
    )
    common_close, benchmark_frames = common_benchmark_close(
        price_cache,
        requested_as_of=requested_as_of,
    )
    empty = pd.DataFrame()
    if common_close is None:
        summary = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "data_status": "DEGRADED_DATA",
            "reason": "missing common exact close for SPY and QQQ",
            "scored_source": str(scored_path),
            "price_cache": str(price_cache),
            "research_only": True,
            "production_activation_allowed": False,
            "target_books_mutated": False,
            "orders_generated": False,
            "fullrun_executed": False,
        }
        write_outputs(
            out_dir,
            empty,
            empty,
            empty,
            empty,
            empty,
            empty,
            empty,
            empty,
            empty,
            empty,
            summary,
        )
        return summary
    benchmarks = benchmark_metrics(benchmark_frames, common_close)
    ticker_tape = build_ticker_tape(
        scored,
        price_cache,
        min_mcap=min_mcap,
        min_dollar_vol=min_dollar_vol,
        as_of=common_close,
        benchmarks=benchmarks,
    )
    if ticker_tape.empty:
        summary = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "reason": "empty scored input or missing price cache",
            "scored_source": str(scored_path),
            "price_cache": str(price_cache),
            "common_close_date": common_close.date().isoformat(),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_outputs(
            out_dir,
            ticker_tape,
            empty,
            empty,
            empty,
            empty,
            empty,
            empty,
            empty,
            empty,
            empty,
            summary,
        )
        return summary
    theme_leaders = aggregate_leadership(
        ticker_tape,
        "leadership_theme",
        level="theme",
    )
    sector_leaders = aggregate_leadership(
        ticker_tape,
        "sector_normalized",
        level="sector",
    )
    industry_leaders = aggregate_leadership(
        ticker_tape,
        ["sector_normalized", "industry_group_normalized"],
        level="industry_group",
    )
    industry_leaders = attach_parent_relative(
        industry_leaders,
        sector_leaders,
        parent_columns=("sector_normalized",),
    )
    subsector_leaders = aggregate_leadership(
        ticker_tape,
        [
            "sector_normalized",
            "industry_group_normalized",
            "subindustry_normalized",
        ],
        level="subsector",
    )
    subsector_leaders = attach_parent_relative(
        subsector_leaders,
        industry_leaders,
        parent_columns=("sector_normalized", "industry_group_normalized"),
    )
    hierarchy = combine_hierarchy(
        sector_leaders,
        industry_leaders,
        subsector_leaders,
        theme_leaders,
        as_of=common_close,
    )
    hierarchy, transitions = apply_state_confirmation(
        hierarchy,
        previous,
        as_of=common_close,
    )
    sector_leaders = hierarchy[hierarchy["level"].eq("sector")].copy()
    industry_leaders = hierarchy[hierarchy["level"].eq("industry_group")].copy()
    subsector_leaders = hierarchy[hierarchy["level"].eq("subsector")].copy()
    theme_leaders = hierarchy[hierarchy["level"].eq("theme")].copy()
    watchlist = build_leader_watchlist(ticker_tape, hierarchy)
    etf_attention_frame = etf_attention(
        price_cache,
        as_of=common_close,
        allow_network=allow_network,
    )
    lookthrough = build_etf_lookthrough_watchlist(ticker_tape, etf_attention_frame)
    exact_count = int(ticker_tape["exact_close"].sum())
    exact_coverage = exact_count / max(1, len(ticker_tape))
    data_status = (
        "READY_REPORT_ONLY"
        if exact_coverage >= min_exact_close_coverage
        else "DEGRADED_DATA"
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "data_status": data_status,
        "research_only": True,
        "production_activation_allowed": False,
        "target_books_mutated": False,
        "orders_generated": False,
        "fullrun_executed": False,
        "scored_source": str(scored_path),
        "price_cache": str(price_cache),
        "common_close_date": common_close.date().isoformat(),
        "requested_as_of": (
            requested_as_of.date().isoformat()
            if requested_as_of is not None
            else None
        ),
        "benchmark_returns": benchmarks,
        "tickers_scored": int(len(ticker_tape)),
        "exact_close_tickers": exact_count,
        "exact_close_coverage": exact_coverage,
        "minimum_exact_close_coverage": min_exact_close_coverage,
        "liquid_tickers": int(ticker_tape["liquidity_pass"].sum()),
        "sector_count": int(len(sector_leaders)),
        "industry_group_count": int(len(industry_leaders)),
        "subsector_count": int(len(subsector_leaders)),
        "top_sector": None if sector_leaders.empty else str(sector_leaders.iloc[0]["group_label"]),
        "top_sector_state": None if sector_leaders.empty else str(sector_leaders.iloc[0]["leadership_state"]),
        "top_theme": None if theme_leaders.empty else str(theme_leaders.iloc[0]["group_label"]),
        "top_theme_state": None if theme_leaders.empty else str(theme_leaders.iloc[0]["leadership_state"]),
        "top_etf_attention": None if etf_attention_frame.empty else str(etf_attention_frame.iloc[0].get("etf")),
        "top_etf_attention_theme": None if etf_attention_frame.empty else str(etf_attention_frame.iloc[0].get("theme")),
        "top_tickers": ticker_tape[ticker_tape["liquidity_pass"]]
        .head(20)["ticker"]
        .astype(str)
        .tolist(),
        "new_leader_review_tickers": (
            watchlist[watchlist["is_new_leader"]]["ticker"].astype(str).head(20).tolist()
            if not watchlist.empty
            else []
        ),
    }
    write_outputs(
        out_dir,
        ticker_tape,
        theme_leaders,
        sector_leaders,
        industry_leaders,
        subsector_leaders,
        hierarchy,
        transitions,
        watchlist,
        etf_attention_frame,
        lookthrough,
        summary,
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", default=DEFAULT_SCORED)
    parser.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--output-dir", "--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-mcap", type=float, default=1_000_000_000)
    parser.add_argument("--min-dollar-vol", type=float, default=20_000_000)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--min-exact-close-coverage", type=float, default=0.10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        scored_path=repo_path(args.scored),
        price_cache=repo_path(args.price_cache),
        out_dir=repo_path(args.output_dir),
        min_mcap=args.min_mcap,
        min_dollar_vol=args.min_dollar_vol,
        as_of=args.as_of,
        allow_network=not args.no_network,
        min_exact_close_coverage=args.min_exact_close_coverage,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
