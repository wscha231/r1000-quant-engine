"""Reuse strict Theme/ETF log-RS with complete exchange-session grids.

UTC crypto closes stay on a separate calendar. Never fill missing sessions,
relabel a daily crypto bar as a NY close, or turn price return into total return.
"""
from __future__ import annotations

from datetime import timedelta
import math
import numpy as np
import pandas_market_calendars as mcal

from r1000_legacy_input_guard import latest_completed_close
from research.theme_etf_runtime_v1.strict import compute_leadership
from .contracts import HORIZONS, ContractError, day, metadata, number, require, stamp

BASE_RS_WEIGHTS={"20":.2,"60":.3,"120":.3,"240":.2}


def grid(cutoff, count=281):
    session, _, _ = latest_completed_close(cutoff)
    end = day(session)
    table = mcal.get_calendar("NYSE").schedule(start_date=end-timedelta(days=count*2+30), end_date=end)
    table = table.iloc[-count:]
    return {d.date().isoformat(): close.to_pydatetime() for d, close in table["market_close"].items()}


def admit_prices(rows, asset, cutoff, policy, sessions, clock="NYSE_CLOSE"):
    require(asset.get("corporate_action_quarantine") is False, "registry_corporate_action_quarantine")
    values = {}
    for row in rows:
        require(row.get("asset_id") == asset["asset_id"], "price_identity")
        require(row.get("clock") == clock, "price_clock")
        require(row.get("currency") == "USD" and row.get("unit") == asset["price_unit"], "price_unit_currency")
        require(row.get("return_basis") in {"TOTAL_RETURN","PROVIDER_ADJUSTED_CLOSE_PROXY"}, "total_return_required")
        require(row.get("corporate_action_quarantine") is False, "corporate_action_quarantine")
        obs, _, _ = metadata(row, cutoff, policy, "price", fresh=False)
        require(row["return_basis"] in policy["sources"][row["source"]].get("return_bases",[]),"source_return_basis_not_approved")
        session = row.get("session")
        day(session)
        require(session not in values, "duplicate_price_session")
        if clock == "NYSE_CLOSE":
            require(session in sessions and obs == sessions[session], "non_session_or_wrong_close")
        else:
            require(asset["asset_class"] == "CRYPTO", "utc_only_crypto")
            expected = stamp(session+"T00:00:00Z")+timedelta(days=1)
            require(obs == expected, "wrong_utc_close")
        require(number(row.get("price"), 0) > 0, "positive_price")
        require(number(row.get("total_return_index"), 0) > 0, "positive_total_return_index")
        if row.get("volume") is not None:
            number(row["volume"], 0)
        values[session] = row
    require(bool(values), "missing_price_history")
    require(len({r["return_basis"] for r in values.values()})==1,"mixed_return_basis")
    if clock == "NYSE_CLOSE":
        required = list(sessions)[-261:]
    else:
        last = (stamp(cutoff)-timedelta(days=1)).date()
        required = [(last-timedelta(days=x)).isoformat() for x in range(260, -1, -1)]
    require(all(s in values for s in required), "stale_or_incomplete_price_grid")
    metadata(values[required[-1]], cutoff, policy, "price")
    return values


def one_asset(values, benchmark, cutoff, benchmark_id, sessions):
    end=list(sessions)[-1]
    require(values[end]["return_basis"]==benchmark[end]["return_basis"],"benchmark_return_basis_mismatch")
    rows = []
    for ident, series in (("ASSET", values), (benchmark_id, benchmark)):
        rows.extend({"security_id": ident, "session": s,
                     "total_return_index": r["total_return_index"], "available_at": r["available_at"]}
                    for s, r in series.items())
    result = compute_leadership(rows, benchmark_id, decision_at=cutoff)[0]
    keys = list(sessions)
    tri = np.asarray([values[s]["total_return_index"] for s in keys[-261:]], dtype=float)
    daily = np.diff(np.log(tri))
    vols = [values[s].get("volume") for s in keys[-25:]]
    vol60 = float(np.std(daily[-60:], ddof=1)*math.sqrt(252))
    result.update(price=values[keys[-1]]["price"], volume=values[keys[-1]].get("volume"),
                  return_basis=values[keys[-1]]["return_basis"],
                  benchmark_return_basis=benchmark[keys[-1]]["return_basis"],
                  realized_volatility=vol60,
                  drawdown=float(tri[-1]/np.maximum.accumulate(tri)[-1]-1),
                  high_52w_distance=float(tri[-1]/max(tri[-252:])-1),
                  volatility_change=float(np.std(daily[-20:], ddof=1)-np.std(daily[-40:-20], ddof=1)),
                  volume_acceleration=None)
    if all(v is not None for v in vols) and sum(vols[:20]) > 0:
        result["volume_acceleration"] = (sum(vols[-5:])/5)/(sum(vols[:20])/20)-1
    for h in HORIZONS:
        result[f"ret{h}"] = result.pop(f"return_{h}")
        result[f"RS{h}"] = result.pop(f"rs_log_{h}")
        result[f"MA{h}_total_return_index"] = float(np.mean(tri[-h:]))
        hv = float(np.std(daily[-h:], ddof=1)*math.sqrt(h))
        result[f"vol_adjusted_RS{h}"] = result[f"RS{h}"]/hv if hv > 1e-12 else None
        for lag in (5,20):
            oldend, oldstart = keys[-1-lag], keys[-1-lag-h]
            old = math.log(values[oldend]["total_return_index"]/values[oldstart]["total_return_index"])-math.log(benchmark[oldend]["total_return_index"]/benchmark[oldstart]["total_return_index"])
            result[f"RS{h}_change_{lag}d"] = result[f"RS{h}"]-old
    result["daily_log_returns"] = daily[-60:].tolist()
    return result


def cross_section(rows):
    """One correlated block, with disclosed effective baseline weights; no imputation."""
    eligible = [r for r in rows if all(r.get(f"vol_adjusted_RS{h}") is not None for h in HORIZONS)]
    if len(eligible) < 3:
        return {"status":"INSUFFICIENT_CROSS_SECTION", "effective_weights":None}
    arr = np.array([[r[f"vol_adjusted_RS{h}"] for h in HORIZONS] for r in eligible])
    clipped = np.clip(arr, np.quantile(arr,.05,axis=0), np.quantile(arr,.95,axis=0))
    std = np.std(clipped,axis=0)
    if np.any(std < 1e-12):
        return {"status":"DEGENERATE_CROSS_SECTION", "effective_weights":None}
    z = (clipped-np.mean(clipped,axis=0))/std
    corr = np.corrcoef(z,rowvar=False)
    base = np.array([BASE_RS_WEIGHTS[str(h)] for h in HORIZONS])
    weights = base/(1+(np.abs(corr)-np.eye(4))@base)
    weights /= sum(weights)
    for i, row in enumerate(eligible):
        for j,h in enumerate(HORIZONS):
            row[f"RS{h}_zscore"] = float(z[i,j])
            row[f"RS{h}_percentile"] = float((sum(arr[:,j] < arr[i,j])+.5*sum(arr[:,j] == arr[i,j]))/len(arr)*100)
        row["RS_composite"] = float(z[i]@weights)
    ordered=sorted(eligible,key=lambda r:(-r["RS_composite"],r["asset_id"]))
    for i,row in enumerate(ordered,1):
        row["discovery_rank"] = i
    return {"status":"CALCULATED", "effective_weights":dict(zip(map(str,HORIZONS),map(float,weights))),
            "horizon_correlation":corr.tolist(), "cohort":[r["asset_id"] for r in eligible]}
