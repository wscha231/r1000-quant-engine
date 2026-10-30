#!/usr/bin/env python3
"""Daily theme leadership tape.

This report-only sidecar detects where the market's current speculative and
institutional attention is concentrating. It uses only prices observable up to
the latest cached close plus the latest scored metadata. It does not change
production selection.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
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
SCORE_FIELDS = ('participation_score', 'bubble_climax_score', 'early_leadership_score')

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
            "data storage device",
            "computer storage",
            "hard disk",
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


def format_percent(value: Any) -> str:
    """Missing observations must not render as an observed zero return."""
    number = safe_float(value, np.nan)
    return f"{number:.2%}" if math.isfinite(number) else "UNKNOWN"


def format_number(value: Any) -> str:
    number = safe_float(value, np.nan)
    return f"{number:.2f}" if math.isfinite(number) else "UNKNOWN"


def observed_score_rows(frame: pd.DataFrame) -> pd.Series:
    scores = frame.reindex(columns=SCORE_FIELDS).apply(pd.to_numeric, errors='coerce')
    return scores.replace([np.inf, -np.inf], np.nan).notna().all(axis=1)


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


def price_metrics(price_cache: Path, ticker: str, *, session: str | None = None) -> dict[str, Any]:
    # These fields belong to the selected cache read, never scored metadata.
    # A missing/short cache must overwrite old CSV values as well as its status.
    missing = dict.fromkeys(('price_date', 'close', 'ret_1d', 'ret_5d', 'ret_21d',
        'ret_63d', 'ret_126d', 'volume', 'volume_avg_20d', 'volume_z_20d',
        'dollar_volume_20d', 'distance_from_252d_high'))
    missing.update(ticker=ticker, price_status='missing_or_short')
    px = load_price_cache(price_cache, ticker)
    if session is not None and not px.empty:
        px = px.loc[px.index <= pd.Timestamp(session)]
    if px.empty or len(px) < 6:
        return missing
    close = pd.to_numeric(px["close"], errors="coerce").dropna()
    volume = pd.to_numeric(px["volume"], errors="coerce")
    dollar_volume = pd.to_numeric(px["dollar_volume"], errors="coerce")
    if close.empty:
        return missing
    ret_1d = trailing_return(close, 1)
    ret_5d = trailing_return(close, 5)
    ret_21d = trailing_return(close, 21)
    ret_63d = trailing_return(close, 63)
    ret_126d = trailing_return(close, 126)
    vol20 = volume.tail(20)
    vol_prev = volume.shift(1).rolling(20).mean()
    vol_z = np.nan
    if len(volume) > 21 and np.isfinite(volume.tail(21)).all():
        denom = float(volume.shift(1).rolling(20).std(ddof=0).iloc[-1])
        base = float(vol_prev.iloc[-1])
        vol_z = 0.0
        if math.isfinite(denom) and denom > 1e-12:
            vol_z = (float(volume.iloc[-1]) - base) / denom
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


def etf_price_frame(price_cache: Path, ticker: str) -> pd.DataFrame:
    # Research observation is held-input only; a cache miss is not permission
    # to contact a provider. The existing collector owns any separate refresh.
    return load_price_cache(price_cache, ticker)


def etf_attention(price_cache: Path, *, session: str | None = None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for ticker, spec in ETF_LOOKTHROUGH.items():
        px = etf_price_frame(price_cache, ticker)
        if session is not None and not px.empty:
            px = px.loc[px.index <= pd.Timestamp(session)]
        if px.empty or len(px) < 22:
            rows.append(
                {
                    "etf": ticker,
                    "theme": spec["theme"],
                    "label": spec["label"],
                    "price_status": "missing_or_short",
                    "price_date": None if px.empty else pd.Timestamp(px.index[-1]).date().isoformat(),
                    "price_as_of_status": "MISSING_OR_SHORT",
                    "holdings": ",".join(spec.get("holdings", ())),
                }
            )
            continue
        close = pd.to_numeric(px["close"], errors="coerce").dropna()
        volume = pd.to_numeric(px.get("volume"), errors="coerce")
        dollar_volume = pd.to_numeric(px.get("dollar_volume"), errors="coerce")
        vol_z = np.nan
        if len(volume) > 21 and np.isfinite(volume.tail(21)).all():
            denom = safe_float(volume.shift(1).rolling(20).std(ddof=0).iloc[-1], 0.0)
            base = safe_float(volume.shift(1).rolling(20).mean().iloc[-1], 0.0)
            vol_z = 0.0  # observed constant volume, including genuine zero
            if denom > 1e-12:
                vol_z = (float(volume.iloc[-1]) - base) / denom
        rows.append(
            {
                "etf": ticker,
                "theme": spec["theme"],
                "label": spec["label"],
                "price_status": "ok",
                "price_date": pd.Timestamp(close.index[-1]).date().isoformat(),
                "price_as_of_status": "NOT_VERIFIED" if session is None else
                    "ALIGNED_TO_SUPPLIED_SESSION" if pd.Timestamp(close.index[-1]).date().isoformat() == session else "STALE",
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
        out[col] = pd.to_numeric(out.get(col, pd.Series(np.nan, index=out.index)), errors="coerce").replace([np.inf, -np.inf], np.nan)
    complete = out[['ret_5d','ret_21d','ret_63d','volume_z_20d','dollar_volume_20d']].notna().all(axis=1) & out.price_status.eq('ok')
    complete &= ~out.price_as_of_status.eq('STALE')
    observed = out.loc[complete]
    out['attention_score'] = np.nan
    # Invalid rows must not alter valid rows' normalization population.
    out.loc[complete, 'attention_score'] = (
        0.25 * robust_z(observed["ret_5d"])
        + 0.25 * robust_z(observed["ret_21d"])
        + 0.20 * robust_z(observed["ret_63d"])
        + 0.15 * observed["volume_z_20d"].clip(-6, 6)
        + 0.15 * robust_z(np.log1p(observed["dollar_volume_20d"]))
    )
    return out.sort_values("attention_score", ascending=False, na_position="last").reset_index(drop=True)


def build_etf_lookthrough_watchlist(ticker_tape: pd.DataFrame, etf_attention_frame: pd.DataFrame) -> pd.DataFrame:
    if etf_attention_frame.empty:
        return pd.DataFrame()
    tape_by_ticker = ticker_tape.set_index("ticker", drop=False) if not ticker_tape.empty and "ticker" in ticker_tape.columns else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for etf in etf_attention_frame.to_dict("records"):
        attention = safe_float(etf.get("attention_score"), np.nan)
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
        pd.to_numeric(out["etf_attention_score"], errors="coerce")
        + 0.50 * pd.to_numeric(out["ticker_participation_score"], errors="coerce")
    )
    return out.sort_values(["combined_watch_score", "etf_attention_score"], ascending=False, na_position="last").reset_index(drop=True)


_BUSINESS_FIELDS = ("Name", "name", "industry", "yf_industry", "sector", "yf_sector")
_BUSINESS_NORMALIZE = re.compile(r"[^a-z0-9]+")
_MISSING_BUSINESS = frozenset({"nan", "none", "null", "unknown", "n a", "na"})
_THEME_TICKERS = {label: frozenset(spec.get("tickers", ()))
                  for label, spec in THEME_TAXONOMY.items()}
_CURATED_TICKERS = frozenset().union(*_THEME_TICKERS.values())


def _business_text(value: Any) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    text = _BUSINESS_NORMALIZE.sub(" ", str(value).lower()).strip()
    return "" if text in _MISSING_BUSINESS else text


def _business_pattern(terms: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(_business_text(t)) for t in terms) + r")\b")


_MEMORY_EXCLUDED = _business_pattern((
    "real estate", "reit", "reits", "self storage", "warehouse", "warehousing", "cold storage",
    "energy storage", "battery storage", "oil storage", "gas storage", "logistics",
))
_MEMORY_HARDWARE = _business_pattern((
    "semiconductor", "semiconductors", "computer hardware", "electronic components",
    "electronic equipment parts", "electronic storage", "data storage devices",
))
_MEMORY_PRECISE = _business_pattern((
    "flash memory", "memory chip", "memory chips", "memory semiconductor",
    "memory semiconductors", "dynamic random access memory", "static random access memory",
    "high bandwidth memory", "non volatile memory", "disk drive", "disk drives", "hard disk",
    "solid state drive", "solid state drives", "data storage device", "data storage devices",
    "computer storage",
))
_MEMORY_HINT = _business_pattern((*THEME_TAXONOMY["memory_semiconductors"]["keywords"], "storage"))
_STORAGE = re.compile(r"\bstorage\b")
_REAL_ESTATE = re.compile(r"\b(?:reits?|real estate)\b")


def _memory_business_match(fields: tuple[str, ...]) -> bool:
    """Direct business evidence only; include memory chips and digital hardware."""
    if _MEMORY_EXCLUDED.search(" ".join(fields)):
        return False
    industry_fields = fields[2:4]
    hardware = any(_MEMORY_HARDWARE.search(field) for field in industry_fields)
    if any(industry_fields) and not hardware:
        return False
    if any(_MEMORY_PRECISE.search(field) for field in fields):
        return True
    return hardware and any(_MEMORY_HINT.search(field) for field in fields)


def infer_theme(row: pd.Series) -> str:
    ticker_value = row.get("ticker")
    ticker = "" if pd.isna(ticker_value) else str(ticker_value).upper().strip()
    # Self-storage REIT business metadata outranks ambiguous storage/space names.
    # Keep every curated issuer mapping intact, including digital-storage makers.
    fields = tuple(_business_text(row.get(key)) for key in _BUSINESS_FIELDS)
    business = " ".join(fields)
    if ticker not in _CURATED_TICKERS and _STORAGE.search(business) and _REAL_ESTATE.search(business):
        return "real_estate"
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
    text = " ".join(str(x).lower() for x in text_fields if x is not None and not pd.isna(x) and str(x).lower() != "nan")
    for label, spec in THEME_TAXONOMY.items():
        if ticker in _THEME_TICKERS[label]:
            return label
        if label == "memory_semiconductors":
            if _memory_business_match(fields):
                return label
        elif any(keyword.lower() in text for keyword in spec.get("keywords", ())):
            return label
    for fallback in ("sage_sector", "yf_industry", "industry", "sector"):
        raw_value = row.get(fallback)
        value = "" if pd.isna(raw_value) else str(raw_value).strip()
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


def build_ticker_tape(scored: pd.DataFrame, price_cache: Path, min_mcap: float, min_dollar_vol: float,
                      *, comparison_session: str | None = None) -> pd.DataFrame:
    if scored.empty or "ticker" not in scored.columns:
        return pd.DataFrame()
    d = scored.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = d[(d["ticker"] != "") & ~d["ticker"].isin(CASH_TICKERS)].drop_duplicates("ticker", keep="last")
    rows: list[dict[str, Any]] = []
    for row in d.itertuples(index=False):
        ticker = str(getattr(row, "ticker", "")).upper()
        rec = d.loc[d["ticker"].eq(ticker)].iloc[-1].to_dict()
        rec.update(price_metrics(price_cache, ticker) if comparison_session is None else
                   price_metrics(price_cache, ticker, session=comparison_session))
        rows.append(rec)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["leadership_theme"] = out.apply(infer_theme, axis=1)
    missing = pd.Series(np.nan, index=out.index)
    market_cap_source = out["market_cap_live"] if "market_cap_live" in out.columns else out.get("mktcap", missing)
    out["market_cap"] = pd.to_numeric(market_cap_source, errors="coerce")
    out["dollar_volume_20d"] = pd.to_numeric(out.get("dollar_volume_20d", missing), errors="coerce")
    out["price_date"] = out.get("price_date", pd.Series(None, index=out.index, dtype=object))
    for col in ("ret_1d", "ret_5d", "ret_21d", "ret_63d", "ret_126d", "volume_z_20d"):
        out[col] = pd.to_numeric(out.get(col, missing), errors="coerce")
    liquid = (out["market_cap"] >= min_mcap) & (out["dollar_volume_20d"] >= min_dollar_vol)
    out["liquidity_pass"] = liquid
    required = ['ret_1d','ret_5d','ret_21d','ret_63d','volume_z_20d','dollar_volume_20d','market_cap']
    observed = out[required].replace([np.inf,-np.inf],np.nan).notna().all(axis=1)
    if comparison_session is not None:
        observed &= out.price_date.eq(comparison_session)
    for horizon in (1,5,21,63):
        out[f'ret_{horizon}d_z'] = robust_z(out[f'ret_{horizon}d'].where(observed)).where(observed)
    out["dollar_volume_z"] = robust_z(np.log1p(out["dollar_volume_20d"].where(observed))).where(observed)
    out["volume_z_20d"] = out["volume_z_20d"].clip(-6, 6)
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
    out.loc[~observed, ['bubble_climax_score','early_leadership_score','participation_score']] = np.nan
    return out.sort_values("participation_score", ascending=False, na_position="last").reset_index(drop=True)


def aggregate_leadership(tape: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if tape.empty or group_col not in tape.columns:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for label, g in tape.groupby(group_col):
        liquid = g[g["liquidity_pass"]].copy()
        if liquid.empty:
            continue
        top = liquid.loc[observed_score_rows(liquid)].sort_values("participation_score", ascending=False).head(8)
        ret21 = pd.to_numeric(liquid["ret_21d"], errors="coerce").replace([np.inf, -np.inf], np.nan)
        observed = int(ret21.notna().sum())
        positive = int(ret21.gt(0).sum())
        rows.append(
            {
                group_col: label,
                "member_count": int(len(liquid)),
                "input_member_count": int(len(g)),
                "liquidity_excluded_count": int(len(g) - len(liquid)),
                "observed_count_21d": observed,
                "missing_count_21d": int(len(liquid) - observed),
                "positive_count_21d": positive,
                "coverage_21d": observed / len(liquid),
                "active_count_1d_gt_8pct": int((liquid["ret_1d"] >= 0.08).sum()),
                "active_count_5d_gt_20pct": int((liquid["ret_5d"] >= 0.20).sum()),
                "breadth_21d_positive": positive / observed if observed else np.nan,
                "breadth_21d_denominator": "OBSERVED_LIQUID_MEMBERS",
                "positive_share_all_liquid_members": positive / len(liquid),
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
    complete = out.leadership_state.ne('data_pending') & out[[
        'median_ret_5d','median_ret_21d','top_participation_score',
        'breadth_21d_positive','dollar_volume_20d_sum']].notna().all(axis=1)
    observed = out.loc[complete]
    out['leadership_score'] = np.nan
    out.loc[complete, 'leadership_score'] = (
        0.25 * robust_z(observed["median_ret_5d"])
        + 0.25 * robust_z(observed["median_ret_21d"])
        + 0.20 * robust_z(observed["top_participation_score"])
        + 0.15 * observed["breadth_21d_positive"]
        + 0.15 * robust_z(np.log1p(observed["dollar_volume_20d_sum"]))
    )
    return out.sort_values("leadership_score", ascending=False).reset_index(drop=True)


def classify_group(liquid: pd.DataFrame, top: pd.DataFrame) -> str:
    # No new minimum-coverage threshold: only complete required observations
    # may receive the existing judgment. Partial facts remain visible above.
    if liquid.empty or not observed_score_rows(liquid).all():
        return 'data_pending'
    if 'price_as_of_status' in liquid and liquid['price_as_of_status'].isin(['MISSING','STALE']).any():
        return 'data_pending'
    for column in ("ret_5d", "ret_21d"):
        values = pd.to_numeric(liquid[column], errors="coerce")
        if values.empty or values.isna().any() or not np.isfinite(values).all():
            return "data_pending"
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


def render_report(
    summary: dict[str, Any],
    themes: pd.DataFrame,
    sectors: pd.DataFrame,
    tickers: pd.DataFrame,
    etfs: pd.DataFrame,
    lookthrough: pd.DataFrame,
) -> str:
    lines = [
        "# Theme Leadership Tape",
        "",
        "Report-only observed subset. Computation completion does not certify current market coverage.",
        "",
        "## Freshness",
        "",
        f"- Scored source: `{summary.get('scored_source')}`",
        f"- Maximum row date (watermark only): `{summary.get('latest_price_date')}`",
        f"- Minimum row date: `{summary.get('earliest_price_date')}`",
        f"- Observation status: `{summary.get('observation_status')}`; freshness: `{summary.get('freshness_status')}`",
        f"- Comparison session: `{summary.get('comparison_session')}`; row dates: `{summary.get('price_date_counts')}`",
        f"- Missing price rows: {summary.get('missing_price_rows')}; currentness verified: False",
        f"- Tickers scored: {summary.get('tickers_scored')}",
        f"- Liquid tickers: {summary.get('liquid_tickers')}",
        "",
        "## Top Themes",
        "",
    ]
    for row in (themes.head(10).to_dict("records") if not themes.empty else []):
        lines.append(
            f"- `{row.get('leadership_theme')}`: score {format_number(row.get('leadership_score'))}, "
            f"state `{row.get('leadership_state')}`, 5d {format_percent(row.get('median_ret_5d'))}, "
            f"21d {format_percent(row.get('median_ret_21d'))}, "
            f"total/observed/missing `{row.get('member_count')}/{row.get('observed_count_21d')}/{row.get('missing_count_21d')}`, "
            f"top `{row.get('top_tickers')}`"
        )
    lines.extend(["", "## Ticker Observations", ""])
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
            f"1d {format_percent(row.get('ret_1d'))}, 5d {format_percent(row.get('ret_5d'))}, "
            f"21d {format_percent(row.get('ret_21d'))}, score {format_number(row.get('participation_score'))}"
        )
    lines.extend(["", "## ETF Attention", ""])
    for row in (etfs.head(10).to_dict("records") if not etfs.empty else []):
        lines.append(
            f"- `{row.get('etf')}` {row.get('label')}: theme `{row.get('theme')}`, "
            f"date `{row.get('price_date')}`, as-of `{row.get('price_as_of_status')}`, "
            f"5d {format_percent(row.get('ret_5d'))}, 21d {format_percent(row.get('ret_21d'))}, "
            f"attention {format_number(row.get('attention_score'))}, holdings `{row.get('holdings')}`"
        )
    lines.extend(["", "## ETF Look-Through Watchlist", ""])
    for row in (lookthrough.head(20).to_dict("records") if not lookthrough.empty else []):
        lines.append(
            f"- `{row.get('ticker')}` via `{row.get('source_etf')}`/{row.get('source_etf_theme')}: "
            f"ETF attention {format_number(row.get('etf_attention_score'))}, "
            f"ticker score {format_number(row.get('ticker_participation_score'))}, "
            f"5d {format_percent(row.get('ticker_ret_5d'))}, in universe `{row.get('ticker_in_scored_universe')}`"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `climax_hot` means the theme is already moving violently; use it for tactical participation and tight exit rules, not blind long-term compounding.",
            "- `emerging_leader` is the better early-entry state; the next step is to A/B test staged sizing into these themes.",
            "- ETF attention is a proxy from ETF price/volume/dollar-volume behavior plus a curated look-through seed list; it is not a verified fund-flow feed.",
            "- Row dates and coverage describe the supplied subset; maximum date and completed computation do not authenticate freshness, Source/PIT, or whole-market breadth.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    out_dir: Path,
    ticker_tape: pd.DataFrame,
    theme_leaders: pd.DataFrame,
    sector_leaders: pd.DataFrame,
    etf_attention_frame: pd.DataFrame,
    lookthrough: pd.DataFrame,
    summary: dict[str, Any],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ticker_tape.to_csv(out_dir / "ticker_leadership.csv", index=False)
    theme_leaders.to_csv(out_dir / "theme_leadership.csv", index=False)
    sector_leaders.to_csv(out_dir / "sector_leadership.csv", index=False)
    etf_attention_frame.to_csv(out_dir / "etf_attention.csv", index=False)
    lookthrough.to_csv(out_dir / "etf_lookthrough_watchlist.csv", index=False)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (out_dir / "report.md").write_text(
        render_report(summary, theme_leaders, sector_leaders, ticker_tape, etf_attention_frame, lookthrough),
        encoding="utf-8",
    )


def prepare_research_roster(reader, generations: dict[str, str], *, roster_raw: bytes,
                            identities_raw: bytes, session: str, as_of: str,
                            observed_at: str, intake_cutoff: str,
                            out_dir: Path, source_kind: str,
                            benchmark_ids=None, raw_generations=None,
                            expected_qualification_sha256=None,
                            trusted_qualification_source=None) -> dict[str, Any]:
    """Explicit pre-ranking roster -> existing Feature -> existing A2 proposal.

    Reads only caller-held generations through the existing Reader. A missing
    generation retains the requested security as DATA_PENDING. A supplied but
    refused generation stops the handoff, preserving global provenance failure.
    New local output directory only; no canonical store or A3 admission.
    Feature horizons remain 5/20/60/120/240 sessions, never relabeled 21/63 days.
    """
    from tools import run_a2_research_intake as caller
    from tools.build_run287_ohlcv_location_timing_challenger import research_feature_snapshot
    h = caller.intake
    roster = h.decode(roster_raw)
    h.need(type(roster) is dict and set(roster) == {'scope', 'rows'} and
           roster['scope'] == 'PRE_RANKING_RESEARCH_ROSTER', 'OBSERVATION_ROSTER')
    h.need(type(roster['rows']) is list and 0 < len(roster['rows']) <= 1000, 'OBSERVATION_ROSTER')
    identities = h._identities(identities_raw)
    aliases = {}
    for sid, (issuer, tickers) in identities.items():
        for ticker in tickers:
            aliases.setdefault(ticker, []).append((sid, issuer))
    h.need(h.stamp(as_of) <= h.stamp(observed_at) <= h.stamp(intake_cutoff),
           'OBSERVATION_HANDOFF_CLOCK')
    h.need(type(generations) is dict and (raw_generations is None or type(raw_generations) is dict),
           'OBSERVATION_GENERATIONS')
    raw_generations = raw_generations or {}
    requested, subjects, rows, snapshots = [], set(), [], []
    # Validate the entire requested roster before any source reads or outputs.
    for row in roster['rows']:
        h.need(type(row) is dict and 'ticker' in row and
               set(row) <= {'ticker', 'Name', 'sector', 'industry'} and
               all(value is None or type(value) is str for value in row.values()),
               'OBSERVATION_ROSTER_ROW')
        ticker = h.identifier(row['ticker'])
        h.need(ticker not in requested and len(aliases.get(ticker, [])) == 1,
               'OBSERVATION_EXACT_IDENTITY')
        sid, issuer = aliases[ticker][0]
        h.need(sid not in subjects, 'OBSERVATION_DUPLICATE_SECURITY')
        subjects.add(sid); requested.append(ticker)
        rows.append(dict(row, security_id=sid, issuer_id=issuer))
    h.need(set(generations) <= subjects and set(raw_generations) <= set(generations),
           'OBSERVATION_GENERATION_SUBJECT')
    for row in rows:
        sid = row['security_id']
        row.update(observation_status='DATA_PENDING', snapshot_sha256=None,
                   source_generation=generations.get(sid))
        if sid in generations:
            snapshot = research_feature_snapshot(reader, generations[sid], security_id=sid,
                session=session, as_of=as_of, benchmark_ids=benchmark_ids,
                raw_generation=raw_generations.get(sid),
                expected_qualification_sha256=expected_qualification_sha256,
                trusted_qualification_source=trusted_qualification_source)
            # Do not turn a supplied corrupt/expired/unauthorized source into
            # ordinary absence or continue other subjects after its refusal.
            h.need(snapshot['feature_state'] != 'BLOCKED_RESEARCH_FEATURES',
                   'OBSERVATION_SOURCE_REFUSED:' + ','.join(sorted(set(snapshot['blocker'].values()))))
            h.need(snapshot['security_id'] == sid and
                   snapshot['ticker'] in identities[sid][1], 'OBSERVATION_EXACT_IDENTITY')
            row.update(observation_status=snapshot['feature_state'],
                       snapshot_sha256=h.digest(h.canonical(snapshot)))
            snapshots.append(snapshot)
        else:
            snapshot = None
        # No rank, score, liquidity filter or missing-value substitution here.
        for horizon in (5, 20, 60, 120, 240):
            key = f'ret_{horizon}s'
            row[key] = snapshot['features'][key] if snapshot is not None else None
        row['leadership_theme'] = infer_theme(pd.Series(row))
    observation = dict(schema='research-roster-observation-h1-v1',
        scope='PRE_RANKING_RESEARCH_ROSTER', session=session, as_of=as_of,
        observed_at=observed_at, intake_cutoff=intake_cutoff,
        roster_sha256=h.digest(roster_raw), identities_sha256=h.digest(identities_raw),
        requested_count=len(rows), source_observed_count=len(snapshots),
        missing_source_count=len(rows)-len(snapshots), rows=rows, snapshots=snapshots,
        source_authenticity='NOT_ADMITTED_BY_THIS_ADAPTER', identity_scope='SUPPLIED_US_IDENTITY_ASSERTIONS',
        ranking_allowed=False, whole_market_coverage_verified=False,
        authority=h.closed())
    observation_raw = h.canonical(observation)
    h.need(len(observation_raw) <= h.MAX_TOTAL_BYTES, 'OBSERVATION_BYTE_BUDGET')
    columns = ['ticker', 'security_id', 'issuer_id', 'leadership_theme', 'observation_status',
               'source_generation', 'snapshot_sha256'] + [f'ret_{n}s' for n in (5,20,60,120,240)]
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, columns, extrasaction='ignore'); writer.writeheader(); writer.writerows(rows)
    csv_raw = stream.getvalue().encode('utf-8')
    request = dict(schema='a2-candidate-queue-files-v1', retain_missing_candidates=True,
        identities=dict(path='identities.json', sha256=h.digest(identities_raw)),
        sources=[dict(kind=source_kind,
            file=dict(path='observations.csv', sha256=h.digest(csv_raw)), ticker_column='ticker',
            tickers=requested, polarity='CANDIDATE', observed_at=observed_at)])
    request_raw = h.canonical(request)
    # This caller-owned directory must be new. Partial output is not completion.
    out_dir = Path(out_dir)
    out_dir.mkdir()
    for name, raw in [('roster.json', roster_raw), ('observations.json', observation_raw), ('observations.csv', csv_raw),
                      ('identities.json', identities_raw), ('request.json', request_raw)]:
        with (out_dir / name).open('xb') as target:
            target.write(raw)
    proposal = caller.prepare(input_root=out_dir, request_path='request.json',
                              request_sha256=h.digest(request_raw), cutoff=intake_cutoff)
    caller.write_result(out_dir / 'a2_result.json', proposal)
    return dict(observation=observation, observation_sha256=h.digest(observation_raw),
                a2_result=proposal, a2_result_sha256=h.digest(h.canonical(proposal)),
                a3_consumer_ack=None, canonical_current_verified=False)


def run(scored_path: Path, price_cache: Path, out_dir: Path, min_mcap: float, min_dollar_vol: float,
        *, comparison_session: str | None = None) -> dict[str, Any]:
    if comparison_session is not None:
        from datetime import date
        if date.fromisoformat(comparison_session).isoformat() != comparison_session:
            raise ValueError("COMPARISON_SESSION")
    scored = read_scored(scored_path)
    ticker_tape = build_ticker_tape(scored, price_cache, min_mcap=min_mcap, min_dollar_vol=min_dollar_vol,
                                    comparison_session=comparison_session)
    if ticker_tape.empty:
        summary = {
            "status": "blocked",
            "reason": "empty scored input or missing price cache",
            "scored_source": str(scored_path),
            "price_cache": str(price_cache),
        }
        write_outputs(out_dir, ticker_tape, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), summary)
        return summary
    latest_price = pd.to_datetime(ticker_tape.get("price_date"), errors="coerce").max()
    dates = pd.to_datetime(ticker_tape["price_date"], errors="coerce")
    date_counts = ticker_tape["price_date"].dropna().value_counts().sort_index().to_dict()
    missing_count = int(dates.isna().sum())
    stale_count = int((dates < pd.Timestamp(comparison_session)).sum()) if comparison_session else None
    freshness = ("NOT_VERIFIED_WITHOUT_COMPARISON_SESSION" if comparison_session is None else
                 "PARTIAL_AS_OF" if missing_count or stale_count else "ALIGNED_TO_SUPPLIED_SESSION")
    if len(date_counts) > 1:
        freshness = "MIXED_AS_OF"
    ticker_tape["price_as_of_status"] = [
        "MISSING" if pd.isna(d) else "NOT_VERIFIED" if comparison_session is None else
        "STALE" if d < pd.Timestamp(comparison_session) else "ALIGNED_TO_SUPPLIED_SESSION" for d in dates]
    theme_leaders = aggregate_leadership(ticker_tape, "leadership_theme")
    sector_col = "sector" if "sector" in ticker_tape.columns else "leadership_theme"
    sector_leaders = aggregate_leadership(ticker_tape, sector_col)
    etf_attention_frame = etf_attention(price_cache, session=comparison_session)
    lookthrough = build_etf_lookthrough_watchlist(ticker_tape, etf_attention_frame)
    assessed_themes = theme_leaders.loc[theme_leaders.leadership_score.notna()] if not theme_leaders.empty else theme_leaders
    assessed_etfs = etf_attention_frame.loc[etf_attention_frame.attention_score.notna()] if not etf_attention_frame.empty else etf_attention_frame
    assessed_tickers = ticker_tape.loc[observed_score_rows(ticker_tape)]
    summary = {
        "status": "completed",
        "research_only": True,
        "production_activation_allowed": False,
        "scored_source": str(scored_path),
        "price_cache": str(price_cache),
        "latest_price_date": latest_price.date().isoformat() if pd.notna(latest_price) else None,
        "earliest_price_date": dates.min().date().isoformat() if dates.notna().any() else None,
        "comparison_session": comparison_session,
        "price_date_counts": {str(k): int(v) for k, v in date_counts.items()},
        "missing_price_rows": missing_count,
        "stale_price_rows": stale_count,
        "freshness_status": freshness,
        "currentness_verified": False,
        "observation_status": "DATA_PENDING" if not dates.notna().any() else
                              "PARTIAL" if missing_count or len(date_counts) > 1 or stale_count else "OBSERVED_SUBSET",
        "input_scope": "SUPPLIED_SCORED_ROWS_NOT_PRE_RANKING_UNIVERSE",
        "denominator_scope": "SUPPLIED_ROWS; GROUP_BREADTH_IS_OBSERVED_LIQUID_MEMBERS_ONLY",
        "whole_market_coverage_verified": False,
        "etf_stale_rows": int(etf_attention_frame.price_as_of_status.eq('STALE').sum()) if not etf_attention_frame.empty else 0,
        "tickers_scored": int(len(ticker_tape)),
        "tickers_with_observed_scores": int(len(assessed_tickers)),
        "liquid_tickers": int(ticker_tape["liquidity_pass"].sum()),
        "top_theme": None if assessed_themes.empty else str(assessed_themes.iloc[0]["leadership_theme"]),
        "top_theme_state": None if assessed_themes.empty else str(assessed_themes.iloc[0]["leadership_state"]),
        "top_etf_attention": None if assessed_etfs.empty else str(assessed_etfs.iloc[0].get("etf")),
        "top_etf_attention_theme": None if assessed_etfs.empty else str(assessed_etfs.iloc[0].get("theme")),
        "top_tickers": assessed_tickers.head(20)["ticker"].astype(str).tolist(),
    }
    write_outputs(out_dir, ticker_tape, theme_leaders, sector_leaders, etf_attention_frame, lookthrough, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", default=DEFAULT_SCORED)
    parser.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--output-dir", "--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-mcap", type=float, default=1_000_000_000)
    parser.add_argument("--min-dollar-vol", type=float, default=20_000_000)
    parser.add_argument("--comparison-session", help="Explicit comparison date; not a Source freshness certificate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        scored_path=repo_path(args.scored),
        price_cache=repo_path(args.price_cache),
        out_dir=repo_path(args.output_dir),
        min_mcap=args.min_mcap,
        min_dollar_vol=args.min_dollar_vol,
        comparison_session=args.comparison_session,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
