"""USD wealth metrics and development-only CAGR selection, never promotion."""
from __future__ import annotations
from datetime import timedelta
from bisect import bisect_right
import itertools
import math
import statistics

from tools.research_decision_v1.data import number, timestamp, digest


OBJECTIVE = "after_cost_usd_cagr"


def metrics(curve):
    """The first row is pre-trade capital, including the first loss in MDD."""
    if len(curve) < 2:
        raise ValueError("fund_curve_too_short")
    times = [timestamp(r["time"]) for r in curve]
    values = [number(r["equity_usd"], positive=True) for r in curve]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("fund_curve_dates_not_increasing")
    years = (times[-1] - times[0]).total_seconds() / (365.25 * 86400)
    returns = [b/a - 1. for a, b in zip(values, values[1:])]
    rf = [number(r["risk_free_return"]) for r in curve[1:]]
    if any(r <= -1 for r in rf):
        raise ValueError("fund_risk_free_domain")
    excess = [r - f for r, f in zip(returns, rf)]
    annualization = len(returns) / years
    stdev = statistics.stdev(excess) if len(excess) > 1 else 0.
    volatility = statistics.stdev(returns) * math.sqrt(annualization) if len(returns) > 1 else 0.
    peak, peak_at, worst, worst_peak, trough = values[0], times[0], 0., times[0], times[0]
    drawdowns = []
    for t, value in zip(times, values):
        if value > peak: peak, peak_at = value, t
        dd = value / peak - 1.
        drawdowns.append(dd)
        if dd < worst: worst, worst_peak, trough = dd, peak_at, t
    recovery = next((t for t, v in zip(times, values) if t > trough and v >= values[times.index(worst_peak)]), None) if worst < 0 else times[0]
    cagr = math.expm1(math.log(values[-1]/values[0]) / years)
    downside = math.sqrt(sum(min(r, 0.)**2 for r in excess) / len(excess))
    result = {
        "objective": OBJECTIVE, "base_currency": "USD", "starting_capital_usd": values[0],
        "ending_capital_usd": values[-1], "total_return": values[-1]/values[0]-1.,
        "years": years, "cagr": cagr, "max_drawdown": worst,
        "sharpe": statistics.mean(excess)/stdev*math.sqrt(annualization) if stdev else None,
        "sharpe_convention": "sample_std_daily_arithmetic_excess_vs_observed_risk_free",
        "sortino": statistics.mean(excess)/downside*math.sqrt(annualization) if downside else None,
        "calmar": cagr/abs(worst) if worst else None, "annualized_volatility": volatility,
        "annualization_periods": annualization, "max_drawdown_peak": worst_peak.isoformat(),
        "max_drawdown_trough": trough.isoformat(),
        "recovery_time": recovery.isoformat() if recovery else None,
        "drawdown_duration_days": ((recovery or times[-1])-worst_peak).total_seconds()/86400 if worst else 0.,
        "unrecovered_drawdown": worst < 0 and recovery is None,
        "daily_drawdown": drawdowns,
        "average_cash_weight": statistics.mean(number(r["cash_usd"], nonnegative=True)/v for r,v in zip(curve[1:],values[1:])),
    }
    for label, width in (("monthly_returns", 7), ("annual_returns", 4)):
        periods = {}
        for i in range(1, len(curve)):
            key = times[i].date().isoformat()[:width]
            periods[key] = (1+periods.get(key, 0.)) * (values[i]/values[i-1]) - 1.
        result[label] = periods
    for label, days in (("rolling_12m", 365), ("rolling_36m", 1096)):
        windows = []
        for i, t in enumerate(times):
            cutoff = t - timedelta(days=days)
            j = bisect_right(times,cutoff,0,i)-1
            if j < 0: continue
            duration = (t-times[j]).total_seconds()/(365.25*86400)
            windows.append({"end": t.isoformat(), "start": times[j].isoformat(),
                            "total_return": values[i]/values[j]-1.,
                            "cagr": math.expm1(math.log(values[i]/values[j])/duration)})
        result[label] = windows
    if all(r.get("benchmark_equity_usd") is not None for r in curve):
        bench = [number(r["benchmark_equity_usd"], positive=True) for r in curve]
        b_returns = [b/a-1 for a,b in zip(bench, bench[1:])]
        active = [r-b for r,b in zip(returns,b_returns)]
        tracking = statistics.stdev(active) * math.sqrt(annualization) if len(active)>1 else 0.
        bcagr = math.expm1(math.log(bench[-1]/bench[0])/years)
        result["benchmark"] = {"ending_capital_usd": bench[-1], "cagr": bcagr,
            "total_return": bench[-1]/bench[0]-1., "cagr_difference": cagr-bcagr,
            "tracking_error": tracking,
            "information_ratio": statistics.mean(active)*annualization/tracking if tracking else None}
    else:
        result["benchmark"] = None
    return result


def select_cagr_trial(trials, *, development_end, test_start, max_drawdown, registered_trial_ids):
    """Select only from development data; higher Sharpe cannot beat higher CAGR.

    No post-cutoff row, changed trial roster, invalid curve, or risk violation
    participates. Caller must separately prove Git registration and complete
    experiment history; this function is not the canonical promotion gate.
    """
    end, start = timestamp(development_end), timestamp(test_start)
    if end >= start: raise ValueError("selection_overlaps_test")
    limit = number(max_drawdown)
    if not -1 < limit < 0: raise ValueError("selection_risk_limit_invalid")
    ids = [t["trial_id"] for t in trials]
    if len(ids) != len(set(ids)) or sorted(ids) != sorted(registered_trial_ids):
        raise ValueError("selection_trial_roster_mismatch")
    output = []
    windows = set()
    for trial in trials:
        curve = trial["curve"]
        if any(timestamp(r["time"]) > end for r in curve):
            raise ValueError("selection_contains_test_or_future_data")
        windows.add(tuple(r["time"] for r in curve))
        m = metrics(curve)
        output.append({"trial_id": trial["trial_id"], "curve_hash": digest(curve),
                       "cagr": m["cagr"], "max_drawdown": m["max_drawdown"],
                       "eligible": m["max_drawdown"] >= limit})
    if len(windows) != 1: raise ValueError("selection_windows_not_identical")
    eligible = [r for r in output if r["eligible"]]
    ordered = sorted(eligible, key=lambda r: (-r["cagr"], -r["max_drawdown"], r["trial_id"]))
    return {"objective": OBJECTIVE, "selected_trial_id": ordered[0]["trial_id"] if ordered else None,
            "trials": output, "development_end": development_end, "test_start": test_start,
            "production_promoted": False, "independent_registration_verified": False}


def cagr_selection_pbo(return_columns, *, blocks=8):
    """CSCV diagnostic using compound growth for BOTH IS selection and OOS rank.

    Accept actual after-cost returns, never arithmetic excess returns relabelled
    as wealth. It is diagnostic only; DSR/WRC and experiment-history gates remain.
    """
    ids = sorted(return_columns)
    n = len(return_columns[ids[0]]) if ids else 0
    if type(blocks) is not int or len(ids) < 2 or not 4 <= blocks <= 16 or blocks % 2 or n < blocks or n % blocks:
        raise ValueError("pbo_shape_invalid")
    if any(len(return_columns[k]) != n for k in ids): raise ValueError("pbo_unaligned")
    logs = {k: [math.log1p(number(r)) if number(r) > -1 else None for r in return_columns[k]] for k in ids}
    if any(None in values for values in logs.values()): raise ValueError("pbo_return_domain")
    size, bad, count = n//blocks, 0, 0
    for inside in itertools.combinations(range(blocks), blocks//2):
        train = {i for block in inside for i in range(block*size,(block+1)*size)}
        test = set(range(n))-train
        selected = min(ids, key=lambda k: (-sum(logs[k][i] for i in train), k))
        scores = {k: sum(logs[k][i] for i in test) for k in ids}
        # Average tied rank: best=1, worst=N. Bottom half counts as overfit.
        rank = 1 + sum(v > scores[selected] for v in scores.values()) + (sum(v == scores[selected] for v in scores.values())-1)/2
        bad += rank >= (len(ids)+1)/2
        count += 1
    return {"objective": OBJECTIVE, "pbo": bad/count, "splits": count, "diagnostic_only": True}
