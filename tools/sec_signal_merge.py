#!/usr/bin/env python3
"""Point-in-time merge helpers for SEC shadow evidence signals."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


SEC_SIGNAL_COLUMNS = [
    "sec_form4_open_market_buy_score",
    "sec_form4_cluster_buy_score",
    "sec_form4_ceo_cfo_buy_score",
    "sec_form4_sale_pressure_score",
    "early_evidence_score",
    "evidence_confidence_score",
]


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def normalize_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def prepare_sec_signals(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty or "ticker" not in signals.columns:
        return pd.DataFrame()
    d = signals.copy()
    d["ticker"] = d["ticker"].map(normalize_ticker)
    date_source = ""
    if "as_of_date" in d.columns:
        date_source = "as_of_date"
    elif "available_from" in d.columns:
        date_source = "available_from"
    if not date_source:
        return pd.DataFrame()
    d["_sec_asof_dt"] = pd.to_datetime(d[date_source], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    d = d[d["ticker"].ne("") & d["_sec_asof_dt"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    keep = ["ticker", "_sec_asof_dt"]
    for col in SEC_SIGNAL_COLUMNS:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
            keep.append(col)
    if len(keep) == 2:
        return pd.DataFrame()
    return d[keep].sort_values(["ticker", "_sec_asof_dt"]).drop_duplicates(["ticker", "_sec_asof_dt"], keep="last")


def _combine_signal_columns(frame: pd.DataFrame, merged: pd.DataFrame, *, overwrite: bool) -> pd.DataFrame:
    out = merged.copy()
    for col in SEC_SIGNAL_COLUMNS:
        signal_col = f"{col}__sec"
        if signal_col not in out.columns:
            if col not in out.columns:
                out[col] = 0.0
            continue
        signal_values = pd.to_numeric(out[signal_col], errors="coerce")
        if col in out.columns and not overwrite:
            base = pd.to_numeric(out[col], errors="coerce")
            out[col] = base.where(base.notna(), signal_values).fillna(0.0)
        else:
            out[col] = signal_values.fillna(0.0)
        out = out.drop(columns=[signal_col])
    if "_sec_asof_dt" in out.columns:
        out["sec_signal_as_of_date"] = pd.to_datetime(out["_sec_asof_dt"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
        out = out.drop(columns=["_sec_asof_dt"])
    else:
        out["sec_signal_as_of_date"] = ""
    out["sec_signal_available"] = out["sec_signal_as_of_date"].astype(str).ne("")
    return out


def merge_sec_ownership_signals(
    frame: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    date_col: str = "rebalance_date",
    overwrite: bool = False,
) -> pd.DataFrame:
    """Merge SEC signals into a candidate/scored frame without look-ahead.

    If `date_col` exists and can be parsed, every row receives only the latest
    signal whose `as_of_date` is on or before that row's date. Frames without a
    usable date column are treated as latest snapshots and receive the latest
    signal per ticker. This helper is research/shadow only; it never changes
    portfolio weights by itself.
    """
    if frame.empty or "ticker" not in frame.columns:
        return frame.copy()
    sec = prepare_sec_signals(signals)
    out = frame.copy()
    out["ticker"] = out["ticker"].map(normalize_ticker)
    if sec.empty:
        for col in SEC_SIGNAL_COLUMNS:
            if col not in out.columns:
                out[col] = 0.0
        out["sec_signal_as_of_date"] = ""
        out["sec_signal_available"] = False
        return out

    if date_col in out.columns:
        row_dt = pd.to_datetime(out[date_col], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    else:
        row_dt = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")

    if row_dt.notna().any():
        left = out.assign(_row_order=range(len(out)), _row_dt=row_dt).sort_values(["ticker", "_row_dt"])
        right = sec.rename(columns={col: f"{col}__sec" for col in SEC_SIGNAL_COLUMNS if col in sec.columns})
        merged_parts: list[pd.DataFrame] = []
        latest = right.sort_values("_sec_asof_dt").drop_duplicates("ticker", keep="last")
        undated = left[left["_row_dt"].isna()].copy()
        if not undated.empty:
            merged_parts.append(undated.drop(columns=["_row_dt"]).merge(latest, on="ticker", how="left"))
        dated = left[left["_row_dt"].notna()].copy()
        for ticker, left_group in dated.groupby("ticker", sort=False):
            right_group = right[right["ticker"].eq(ticker)].sort_values("_sec_asof_dt")
            if right_group.empty:
                merged_parts.append(left_group)
                continue
            merged_parts.append(
                pd.merge_asof(
                    left_group.sort_values("_row_dt"),
                    right_group.drop(columns=["ticker"]),
                    left_on="_row_dt",
                    right_on="_sec_asof_dt",
                    direction="backward",
                    allow_exact_matches=True,
                )
            )
        merged = pd.concat(merged_parts, ignore_index=True).sort_values("_row_order")
        merged = merged.drop(columns=[col for col in ["_row_order", "_row_dt"] if col in merged.columns])
        return _combine_signal_columns(out, merged, overwrite=overwrite)

    latest = sec.sort_values("_sec_asof_dt").drop_duplicates("ticker", keep="last")
    latest = latest.rename(columns={col: f"{col}__sec" for col in SEC_SIGNAL_COLUMNS if col in latest.columns})
    merged = out.merge(latest, on="ticker", how="left")
    return _combine_signal_columns(out, merged, overwrite=overwrite)


def load_and_merge_sec_signals(
    frame: pd.DataFrame,
    signals_path: str | Path,
    *,
    date_col: str = "rebalance_date",
    overwrite: bool = False,
) -> pd.DataFrame:
    path = Path(signals_path)
    signals = read_table(path)
    return merge_sec_ownership_signals(frame, signals, date_col=date_col, overwrite=overwrite)
