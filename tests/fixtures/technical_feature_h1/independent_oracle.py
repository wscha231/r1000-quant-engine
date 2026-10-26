#!/usr/bin/env python3
"""Independent OFFLINE OHLCV feature reference; never a production R1000 signal.

Purpose: compare existing repository feature consumers to a deterministic pure
reference on supplied calendar-verified frames. Does not fetch providers, infer
source rights, publish a generation, update a cache, rank securities or trade.
Expected columns raw and split: session, open, high, low, close, volume.
Benchmark columns: session, close. `split` must be a price+volume coherent
split-adjusted basis, never a dividend-adjusted close mixed into split OHLC.

This module is an independent QA oracle, NOT a new canonical OHLCV engine.
"""
from __future__ import annotations

import math
from typing import Any, Sequence
import numpy as np
import pandas as pd

LOOKBACKS = (5, 20, 60, 120, 240)
SMAS = (20, 50, 150, 200)


class InputError(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not bool(ok):
        raise InputError(code)


def _frame(frame: pd.DataFrame, expected: Sequence[str], calendar: pd.DatetimeIndex, label: str) -> pd.DataFrame:
    require(isinstance(frame, pd.DataFrame), f"{label}_FRAME")
    require(set(expected).issubset(frame.columns), f"{label}_COLUMNS")
    d = frame.loc[:, expected].copy()
    dates = pd.to_datetime(d["session"], errors="coerce", utc=False)
    require(dates.notna().all() and dates.dt.tz is None, f"{label}_DATES")
    dates = dates.dt.normalize()
    require(dates.isin(calendar).all(), f"{label}_NONSESSION")
    require(dates.is_unique and dates.is_monotonic_increasing, f"{label}_ORDER")
    d.index = pd.DatetimeIndex(dates)
    d.drop(columns=["session"], inplace=True)
    for col in d.columns:
        original = d[col]
        require(original.map(lambda v: not isinstance(v,(bool, np.bool_))).all(),f"{label}_{col}_TYPE")
        d[col] = pd.to_numeric(original, errors="coerce")
        require(np.isfinite(d[col].to_numpy(dtype=float)).all(), f"{label}_{col}_NONFINITE")
    if set(("open", "high", "low", "close", "volume")).issubset(d.columns):
        o,h,l,c,v = (d[x] for x in ("open","high","low","close","volume"))
        require((o>0).all() and (h>0).all() and (l>0).all() and (c>0).all(),f"{label}_PRICE")
        require((h>=np.maximum(o,c)).all() and (l<=np.minimum(o,c)).all(),f"{label}_OHLC_ORDER")
        require((v>=0).all(), f"{label}_VOLUME")
        if label == "RAW":
            require((v == np.floor(v)).all(), f"{label}_VOLUME_INTEGER")
    else:
        require((d["close"]>0).all(),f"{label}_CLOSE")
    return d


def compute_preview(
    raw: pd.DataFrame,
    split: pd.DataFrame,
    spy_split: pd.DataFrame | None,
    completed_sessions: Sequence[str],
    *,
    as_of: str,
    source_description: str,
    split_volume_comparable: bool = False,
) -> dict[str, Any]:
    """Return descriptive, NEVER officially admitted or executable features.

    `completed_sessions` MUST originate from independently verified calendar
    when used on real sources. In-memory fixtures use explicit synthetic grids.
    Missing *sessions* fail feature-window readiness without filling prices.
    If split-adjusted volume comparability is unproved, volume-based pattern
    features stay NULL. Raw close*volume proxy is reported separately.
    """
    require(isinstance(source_description,str) and bool(source_description.strip()),"SOURCE_REQUIRED")
    require(type(split_volume_comparable) is bool,"VOLUME_BASIS_FLAG")
    try:
        sessions = pd.DatetimeIndex(pd.to_datetime(list(completed_sessions)))
        cutoff = pd.Timestamp(as_of)
    except (ValueError, TypeError, OverflowError):
        raise InputError("CALENDAR_OR_ASOF") from None
    require(sessions.tz is None and cutoff.tzinfo is None,"UTC_LOCAL_CALENDAR_MIX")
    sessions=sessions.normalize()
    require(sessions.is_unique and sessions.is_monotonic_increasing and len(sessions)>0,"CALENDAR_ORDER")
    require(cutoff==sessions[-1],"ASOF_NOT_LAST_COMPLETED_SESSION")
    rawf=_frame(raw,("session","open","high","low","close","volume"),sessions,"RAW")
    adj=_frame(split,("session","open","high","low","close","volume"),sessions,"SPLIT")
    spy=(_frame(spy_split,("session","close"),sessions,"SPY")
         if spy_split is not None else pd.DataFrame(columns=["close"]))
    require(len(rawf)>0 and len(adj)>0,"EMPTY_SOURCE")
    require(rawf.index.equals(adj.index),"RAW_SPLIT_SESSION_GRID_MISMATCH")
    require(cutoff in rawf.index,"EXACT_CLOSE_MISSING")

    features:dict[str,float|bool|None]={}
    reasons:dict[str,str]={}
    def emit(name:str, value: Any=None, reason:str=""):
        if value is None or (isinstance(value,(float,np.floating)) and not math.isfinite(float(value))):
            features[name]=None
            reasons[name]=reason or "INVALID_OR_UNSUPPORTED"
        else:
            features[name]=bool(value) if type(value) is bool else float(value)
    def window(d:pd.DataFrame,n:int)->pd.DataFrame|None:
        if len(sessions)<n:
            return None
        idx=sessions[-n:]
        if not pd.Index(idx).isin(d.index).all():
            return None
        return d.loc[idx]
    c=adj["close"]
    for n in LOOKBACKS:
        w=window(adj,n+1)
        wb=window(spy,n+1) if len(spy)>0 else None
        if w is None:
            emit(f"ret_{n}s",reason=f"MISSING_{n+1}_COMPLETED_SESSIONS")
            emit(f"rs_log_spy_{n}s",reason="STOCK_OR_BENCHMARK_GAP")
        else:
            a=float(w["close"].iloc[-1]/w["close"].iloc[0])
            emit(f"ret_{n}s",a-1)
            emit(f"rs_log_spy_{n}s",math.log(a)-math.log(float(wb["close"].iloc[-1]/wb["close"].iloc[0])) if wb is not None else None,"SPY_NOT_PROVIDED_OR_GAP")
    for n in SMAS:
        w=window(adj,n)
        if w is None:
            emit(f"sma_{n}s",reason=f"MISSING_{n}_COMPLETED_SESSIONS")
            emit(f"distance_sma_{n}s",reason=f"MISSING_{n}_COMPLETED_SESSIONS")
        else:
            ma=float(w["close"].mean())
            emit(f"sma_{n}s",ma)
            emit(f"distance_sma_{n}s",float(c.loc[cutoff]/ma-1))

    vol_raw=window(rawf,21)
    if vol_raw is None:
        emit("close_x_raw_volume_proxy",reason="RAW_CLOSE_VOLUME_MISSING")
    else:
        emit("close_x_raw_volume_proxy",float(rawf.loc[cutoff,"close"]*rawf.loc[cutoff,"volume"]))
    v=window(adj,21)
    if v is None or not split_volume_comparable:
        reason="SPLIT_VOLUME_BASIS_NOT_VERIFIED" if not split_volume_comparable else "MISSING_21_COMPLETED_SESSIONS"
        for key in ("rvol_20s_prior_only","volume_z_20s_prior_only","volume_dryup_5v20"):
            emit(key,reason=reason)
    else:
        hist=v["volume"].iloc[:-1]
        mu=float(hist.mean())
        sd=float(hist.std(ddof=0))
        now=float(v["volume"].iloc[-1])
        emit("rvol_20s_prior_only",now/mu if mu>0 else None,"ZERO_BASELINE")
        emit("volume_z_20s_prior_only",(now-mu)/sd if sd>0 else None,"ZERO_VARIANCE")
        emit("volume_dryup_5v20",float(hist.tail(5).mean())/mu if mu>0 else None,"ZERO_BASELINE")

    p252=window(adj,253)
    if p252 is None:
        emit("prior_high_252s",reason="MISSING_253_COMPLETED_SESSIONS")
        emit("breakout_prior_high_252s",reason="MISSING_253_COMPLETED_SESSIONS")
    else:
        prior_high=float(p252["high"].iloc[:-1].max())
        emit("prior_high_252s",prior_high)
        emit("breakout_prior_high_252s",bool(c.loc[cutoff]>prior_high))
    p15=window(adj,15)
    if p15 is None:
        emit("atr_14s_pct",reason="MISSING_15_COMPLETED_SESSIONS")
    else:
        prev=p15["close"].shift(1)
        tr=pd.concat([(p15.high-p15.low),(p15.high-prev).abs(),(p15.low-prev).abs()],axis=1).max(axis=1)
        emit("atr_14s_pct",float(tr.iloc[-14:].mean()/c.loc[cutoff]))
    p64=window(adj,64)
    if p64 is None:
        emit("realized_volatility_20s_over_63s",reason="MISSING_64_COMPLETED_SESSIONS")
    else:
        changes=p64["close"].pct_change().dropna()
        rv20=float(changes.tail(20).std(ddof=0))
        rv63=float(changes.tail(63).std(ddof=0))
        emit("realized_volatility_20s_over_63s",rv20/rv63 if rv63>0 else None,"ZERO_LONG_VOLATILITY")
    return {"schema":"technical-feature-qa-preview-v1", "as_of_completed_session":str(cutoff.date()),
            "evidence_role":"INDEPENDENT_OFFLINE_QA_NOT_SOURCE_ADMISSION",
            "source_description":source_description,"source_status":"NOT_AUTHENTICATED_BY_THIS_FUNCTION",
            "A2_candidate_allowed":False,"A3_ER_allowed":False,"A5_portfolio_allowed":False,
            "execution_allowed":False,"data_admitted":False,"PIT_certified":False,
            "features":features,"feature_blockers":reasons,
            "raw_rows":len(rawf),"split_rows":len(adj),"benchmark_rows":len(spy),
            "split_volume_comparability_supplied":split_volume_comparable}
