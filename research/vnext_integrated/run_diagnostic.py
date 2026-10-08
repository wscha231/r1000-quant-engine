#!/usr/bin/env python3
"""One-shot vNext integrated diagnostic replay.

This research script deliberately ignores every legacy model score/weight and
recomputes a new cross-sectional score from raw component features.  It is a
DIAGNOSTIC, not production/OOS certification, because the recovered historical
candidate book is not yet Russell-membership PIT certified and lacks the newer
feature-availability columns documented by the source-recovery audit.

Selection inputs never include r_1m/bench_r_1m.  Those columns are outcome
labels consumed only after target weights are frozen for each decision date.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EXPECTED_SOURCE_SHA256 = "ebdbbe7e764b735ca129f662c42ec80b68659f4e3196b5a364cf32c506c4c818"
EXPECTED_ROWS = 47435
EXPECTED_TICKERS = 981
EXPECTED_DECISIONS = 85
EXPECTED_FIRST = "2019-05-31"
EXPECTED_LAST = "2026-05-29"

LEGACY_SCORE_PREFIXES = (
    "score_",
    "pred_",
    "z_",
    "portfolio_seed_score",
    "ensemble_weight_",
    "sleeve_",
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_zip_member(zf: zipfile.ZipFile, member: str) -> str:
    h = hashlib.sha256()
    with zf.open(member) as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_member(zf: zipfile.ZipFile, basename: str) -> str:
    hits = [n for n in zf.namelist() if Path(n).name == basename]
    if len(hits) != 1:
        fail(f"expected exactly one {basename}; found={len(hits)}")
    return hits[0]


def as_bool_series(s: pd.Series) -> pd.Series:
    text = s.astype(str).str.strip().str.lower()
    return text.isin({"1", "true", "yes", "y"})


def pct_rank(s: pd.Series, *, ascending: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if x.notna().sum() <= 1:
        return pd.Series(np.nan, index=s.index, dtype=float)
    return x.rank(pct=True, method="average", ascending=ascending) * 100.0


def clamp01(x: Any) -> float | None:
    try:
        v = float(x)
    except Exception:
        return None
    if not math.isfinite(v) or v < 0.0 or v > 1.0:
        return None
    return v


def max_drawdown(nav: list[float]) -> float | None:
    if not nav:
        return None
    peak = nav[0]
    worst = 0.0
    for value in nav:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return float(worst)


def metrics(returns: list[float], nav: list[float]) -> dict[str, Any]:
    n = len(returns)
    if n == 0 or not nav:
        return {"periods": 0, "cagr": None, "max_drawdown": None, "sharpe": None, "sortino": None, "calmar": None}
    arr = np.asarray(returns, dtype=float)
    ending = float(nav[-1])
    cagr = ending ** (12.0 / n) - 1.0 if ending > 0 else None
    mdd = max_drawdown(nav)
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    sharpe = float(arr.mean() / std * math.sqrt(12.0)) if std > 0 else None
    downside = arr[arr < 0]
    downside_std = float(np.sqrt(np.mean(np.square(downside)))) if len(downside) else 0.0
    sortino = float(arr.mean() / downside_std * math.sqrt(12.0)) if downside_std > 0 else None
    calmar = float(cagr / abs(mdd)) if cagr is not None and mdd not in (None, 0.0) else None
    return {
        "periods": n,
        "ending_multiple": ending,
        "cagr": cagr,
        "max_drawdown": mdd,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "monthly_mean": float(arr.mean()),
        "monthly_median": float(np.median(arr)),
        "positive_month_fraction": float((arr > 0).mean()),
    }


def capped_weights(raw: pd.Series, exposure: float, cap: float) -> pd.Series:
    raw = pd.to_numeric(raw, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    if raw.sum() <= 0 or exposure <= 0:
        return pd.Series(0.0, index=raw.index)
    result = pd.Series(0.0, index=raw.index, dtype=float)
    remaining = float(exposure)
    active = list(raw.index)
    while active and remaining > 1e-12:
        vals = raw.loc[active]
        if vals.sum() <= 0:
            proposal = pd.Series(remaining / len(active), index=active)
        else:
            proposal = vals / vals.sum() * remaining
        hit = proposal[proposal > cap + 1e-12]
        if hit.empty:
            result.loc[active] += proposal
            remaining = 0.0
            break
        for idx in hit.index:
            add = min(cap - result.loc[idx], remaining)
            if add > 0:
                result.loc[idx] += add
                remaining -= add
            active.remove(idx)
    return result


def regime_exposure(group: pd.DataFrame, config: dict[str, Any]) -> tuple[float, str, float | None]:
    vals: list[float] = []
    for col in config["regime"]["features"]:
        if col not in group.columns:
            continue
        med = pd.to_numeric(group[col], errors="coerce").median()
        v = clamp01(med)
        if v is not None:
            vals.append(v)
    if not vals:
        return 0.65, "UNKNOWN_FAIL_CLOSED", None
    risk = float(statistics.median(vals))
    for row in config["regime"]["thresholds"]:
        if risk >= float(row["min"]):
            return float(row["equity_exposure"]), "OBSERVED", risk
    return 0.65, "INVALID_FAIL_CLOSED", risk


def build_scores(group: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    g = group.copy()
    pillar_scores: dict[str, pd.Series] = {}
    pillar_seen: dict[str, pd.Series] = {}
    for pillar, weight in config["pillars"].items():
        feature_scores: list[pd.Series] = []
        for col in config["pillar_features"].get(pillar, []):
            if col not in g.columns:
                continue
            feature_scores.append(pct_rank(g[col], ascending=True))
        if feature_scores:
            table = pd.concat(feature_scores, axis=1)
            pillar_scores[pillar] = table.mean(axis=1, skipna=True)
            pillar_seen[pillar] = table.notna().any(axis=1).astype(float)
        else:
            pillar_scores[pillar] = pd.Series(np.nan, index=g.index)
            pillar_seen[pillar] = pd.Series(0.0, index=g.index)

    numerator = pd.Series(0.0, index=g.index)
    coverage = pd.Series(0.0, index=g.index)
    for pillar, weight in config["pillars"].items():
        score = pillar_scores[pillar]
        present = score.notna()
        numerator.loc[present] += float(weight) * score.loc[present]
        coverage.loc[present] += float(weight)
        g[f"pillar_{pillar}"] = score
    base = numerator / coverage.replace(0.0, np.nan)

    risk_parts: list[pd.Series] = []
    for col in config["risk_features"]:
        if col not in g.columns:
            continue
        x = pd.to_numeric(g[col], errors="coerce")
        if col == "dd_1y":
            x = -x
        risk_parts.append(pct_rank(x, ascending=True))
    if risk_parts:
        risk_pct = pd.concat(risk_parts, axis=1).mean(axis=1, skipna=True)
    else:
        risk_pct = pd.Series(np.nan, index=g.index)
    penalty = risk_pct.fillna(100.0) / 100.0 * float(config["risk_penalty_max_points"])

    g["pillar_weight_coverage"] = coverage
    g["vnext_base_score"] = base
    g["vnext_risk_penalty"] = penalty
    # Missing evidence can never improve rank: score is explicitly scaled down by coverage.
    g["vnext_score"] = base * coverage - penalty

    eligible = coverage >= float(config["minimum_pillar_weight_coverage"])
    vol = pd.to_numeric(g.get("vol_252d"), errors="coerce") if "vol_252d" in g.columns else pd.Series(np.nan, index=g.index)
    eligible &= vol.notna() & (vol > 0)
    if "backtest_usable" in g.columns:
        eligible &= as_bool_series(g["backtest_usable"])
    g["vnext_eligible"] = eligible
    g["vnext_rank"] = g["vnext_score"].where(eligible).rank(ascending=False, method="min")
    return g


def choose_names(scored: pd.DataFrame, previous: set[str], spec: dict[str, Any]) -> list[str]:
    eligible = scored[scored["vnext_eligible"]].copy().sort_values(["vnext_rank", "ticker"])
    if eligible.empty:
        return []
    by_ticker = eligible.set_index("ticker")
    retained = [
        t for t in previous
        if t in by_ticker.index and float(by_ticker.loc[t, "vnext_rank"]) <= float(spec["retention_rank"])
    ]
    retained.sort(key=lambda t: (float(by_ticker.loc[t, "vnext_rank"]), t))
    chosen = retained[: int(spec["target_names"])]
    for ticker in eligible["ticker"].astype(str):
        if ticker in chosen:
            continue
        chosen.append(ticker)
        if len(chosen) >= int(spec["target_names"]):
            break
    return chosen


def target_weights(scored: pd.DataFrame, names: list[str], exposure: float, spec: dict[str, Any]) -> pd.Series:
    if not names:
        return pd.Series(dtype=float)
    x = scored.set_index("ticker").loc[names].copy()
    strength = (pd.to_numeric(x["vnext_score"], errors="coerce") - 40.0).clip(lower=1.0)
    vol = pd.to_numeric(x["vol_252d"], errors="coerce")
    raw = strength / vol.clip(lower=0.10)
    max_equity = min(float(exposure), 1.0 - float(spec["minimum_cash"]))
    return capped_weights(raw, max_equity, float(spec["max_weight"]))


@dataclass
class ReplayResult:
    periods: pd.DataFrame
    metrics: dict[str, Any]
    benchmark_metrics: dict[str, Any]


def run_portfolio(frame: pd.DataFrame, config: dict[str, Any], portfolio: str, cost_bps: int) -> ReplayResult:
    spec = config[portfolio]
    dates = sorted(frame["rebalance_date"].dropna().unique())
    prev_names: set[str] = set()
    prev_end_weights: dict[str, float] = {}
    nav = 1.0
    bench_nav = 1.0
    nav_path: list[float] = []
    bench_path: list[float] = []
    returns: list[float] = []
    bench_returns: list[float] = []
    rows: list[dict[str, Any]] = []

    for date in dates:
        group = frame[frame["rebalance_date"] == date].copy()
        scored = build_scores(group, config)
        exposure, regime_status, risk_score = regime_exposure(scored, config)
        names = choose_names(scored, prev_names, spec)
        weights = target_weights(scored, names, exposure, spec)
        cash_weight = 1.0 - float(weights.sum())

        outcome = pd.to_numeric(scored.set_index("ticker").get(config["execution"]["outcome_column"]), errors="coerce")
        missing = [t for t in names if t not in outcome.index or not math.isfinite(float(outcome.loc[t]))]
        if missing and bool(config["execution"]["require_all_selected_outcomes"]):
            rows.append({
                "rebalance_date": str(date), "status": "BLOCKED_OUTCOME_MISSING", "missing_tickers": ";".join(missing),
                "selected": ";".join(names), "equity_exposure": float(weights.sum()), "cash_weight": cash_weight,
                "regime_status": regime_status, "regime_risk_score": risk_score,
            })
            break

        if names:
            abs_outcomes = outcome.loc[names].abs()
            if abs_outcomes.max() > 5.0:
                fail(f"outcome scale invalid on {date}: max_abs_r_1m={abs_outcomes.max()}")

        target = {t: float(weights.loc[t]) for t in weights.index}
        turnover = sum(abs(target.get(t, 0.0) - prev_end_weights.get(t, 0.0)) for t in set(target) | set(prev_end_weights))
        cost = float(cost_bps) / 10000.0 * turnover
        gross = sum(target[t] * float(outcome.loc[t]) for t in names)
        if cash_weight - cost < -1e-9:
            fail(f"transaction cost exceeds cash buffer on {date}")
        net = gross - cost
        nav *= 1.0 + net

        bench_col = config["execution"]["benchmark_outcome_column"]
        bench_series = pd.to_numeric(scored[bench_col], errors="coerce") if bench_col in scored.columns else pd.Series(dtype=float)
        bench = float(bench_series.median()) if bench_series.notna().any() else math.nan
        if not math.isfinite(bench):
            fail(f"benchmark outcome missing on {date}")
        if bench_series.notna().sum() > 1 and float(bench_series.std()) > 1e-6:
            bench_status = "CROSS_SECTION_VARIATION"
        else:
            bench_status = "OK"
        bench_nav *= 1.0 + bench

        total_end = 1.0 + net
        end_weights = {t: target[t] * (1.0 + float(outcome.loc[t])) / total_end for t in names}
        end_cash = (cash_weight - cost) / total_end
        if end_cash < -1e-8:
            fail(f"negative ending cash on {date}")

        returns.append(net)
        bench_returns.append(bench)
        nav_path.append(nav)
        bench_path.append(bench_nav)
        rows.append({
            "rebalance_date": str(date), "status": "OK", "portfolio": portfolio, "cost_bps_per_side": int(cost_bps),
            "selected": ";".join(names), "selected_count": len(names),
            "equity_exposure": float(weights.sum()), "cash_weight": cash_weight,
            "regime_status": regime_status, "regime_risk_score": risk_score,
            "turnover_stock_notional": turnover, "cost_return_drag": cost,
            "gross_return": gross, "net_return": net, "benchmark_return": bench,
            "benchmark_status": bench_status, "nav": nav, "benchmark_nav": bench_nav,
            "end_cash_weight": end_cash,
        })
        prev_names = set(names)
        prev_end_weights = end_weights

    periods = pd.DataFrame(rows)
    ok = periods[periods["status"] == "OK"] if not periods.empty else periods
    return ReplayResult(periods=periods, metrics=metrics(returns, nav_path), benchmark_metrics=metrics(bench_returns, bench_path))


def window_metrics(periods: pd.DataFrame, start: str, end: str) -> dict[str, Any]:
    if periods.empty:
        return metrics([], [])
    x = periods[periods["status"] == "OK"].copy()
    d = pd.to_datetime(x["rebalance_date"], errors="coerce")
    mask = (d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))
    x = x[mask]
    rets = pd.to_numeric(x["net_return"], errors="coerce").dropna().tolist()
    nav: list[float] = []
    value = 1.0
    for r in rets:
        value *= 1.0 + float(r)
        nav.append(value)
    return metrics(rets, nav)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-zip", required=True)
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()
    source = Path(args.source_zip)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads(Path(args.experiment).read_text(encoding="utf-8"))

    source_sha = sha256_file(source)
    if source_sha != EXPECTED_SOURCE_SHA256:
        fail(f"source archive sha mismatch: {source_sha}")

    desired_features = set(["rebalance_date", "ticker", "sector", "r_1m", "bench_r_1m", "backtest_usable", "vol_252d"])
    for cols in config["pillar_features"].values():
        desired_features.update(cols)
    desired_features.update(config["risk_features"])
    desired_features.update(config["regime"]["features"])

    with zipfile.ZipFile(source) as zf:
        member = unique_member(zf, "candidate_replay_book_sec_enriched.csv")
        raw_member = unique_member(zf, "candidate_replay_book.csv")
        enriched_sha = sha256_zip_member(zf, member)
        raw_sha = sha256_zip_member(zf, raw_member)
        header = pd.read_csv(zf.open(member), nrows=0).columns.tolist()
        for col in header:
            if col.startswith(LEGACY_SCORE_PREFIXES):
                # Deliberately present in the archive but never admitted by usecols.
                continue
        usecols = [c for c in header if c in desired_features]
        required = {"rebalance_date", "ticker", "r_1m", "bench_r_1m", "vol_252d"}
        missing_required = sorted(required - set(usecols))
        if missing_required:
            fail(f"required columns absent: {missing_required}")
        frame = pd.read_csv(zf.open(member), usecols=usecols, low_memory=False)

    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    if len(frame) != EXPECTED_ROWS:
        fail(f"candidate row count drift: {len(frame)}")
    if int(frame["ticker"].nunique()) != EXPECTED_TICKERS:
        fail(f"ticker count drift: {frame['ticker'].nunique()}")
    dates = sorted(frame["rebalance_date"].dropna().unique())
    if len(dates) != EXPECTED_DECISIONS or dates[0] != EXPECTED_FIRST or dates[-1] != EXPECTED_LAST:
        fail(f"decision date contract drift: count={len(dates)} first={dates[0]} last={dates[-1]}")

    forbidden_used = [c for c in usecols if c.startswith(LEGACY_SCORE_PREFIXES)]
    if forbidden_used:
        fail(f"legacy model score leaked into vNext inputs: {forbidden_used}")

    summaries: dict[str, Any] = {
        "schema_version": "vnext-integrated-diagnostic-result-v1",
        "experiment_id": config["experiment_id"],
        "authority": "RESEARCH_ONLY",
        "source_archive_sha256": source_sha,
        "candidate_member": member,
        "candidate_member_sha256": enriched_sha,
        "raw_candidate_member_sha256": raw_sha,
        "rows": len(frame),
        "tickers": int(frame["ticker"].nunique()),
        "decision_dates": len(dates),
        "date_range": [dates[0], dates[-1]],
        "used_columns": sorted(usecols),
        "legacy_score_columns_used": forbidden_used,
        "historical_pit_certified": False,
        "production_allowed": False,
        "orders_allowed": False,
        "results": {},
    }

    experiment_hash = hashlib.sha256(Path(args.experiment).read_bytes()).hexdigest()
    summaries["experiment_config_sha256"] = experiment_hash

    for portfolio in ("main", "concentrated"):
        summaries["results"][portfolio] = {}
        for bps in config["execution"]["cost_sensitivity_bps_per_side"]:
            rr = run_portfolio(frame, config, portfolio, int(bps))
            csv_name = f"periods_{portfolio}_{int(bps)}bps.csv"
            rr.periods.to_csv(out / csv_name, index=False)
            entry = {
                "metrics": rr.metrics,
                "benchmark_metrics": rr.benchmark_metrics,
                "blocked_rows": int((rr.periods["status"] != "OK").sum()) if not rr.periods.empty else 0,
                "period_file": csv_name,
                "windows": {},
            }
            for label, (start, end) in config["evaluation_windows"].items():
                entry["windows"][label] = window_metrics(rr.periods, start, end)
            summaries["results"][portfolio][str(bps)] = entry

    # Latest historical cross-section is diagnostic only; no current 2026-09-16 claim.
    latest = build_scores(frame[frame["rebalance_date"] == dates[-1]].copy(), config)
    latest.sort_values(["vnext_rank", "ticker"]).to_csv(out / "latest_historical_scores_20260529.csv", index=False)

    (out / "summary.json").write_text(json.dumps(summaries, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    base = summaries["results"]["main"][str(config["execution"]["baseline_cost_bps_per_side"])]
    conc = summaries["results"]["concentrated"][str(config["execution"]["baseline_cost_bps_per_side"])]
    def f(v: Any) -> str:
        return "N/A" if v is None else f"{float(v):.4f}"
    report = [
        "# vNext Integrated Core — one-shot diagnostic replay",
        "",
        "RESEARCH_ONLY. This is a newly recomputed model; no legacy score_total, old champion weights, or current opinions are used as selection inputs.",
        "",
        f"- experiment: `{config['experiment_id']}`",
        f"- config SHA256: `{experiment_hash}`",
        f"- source archive SHA256: `{source_sha}`",
        f"- rows/tickers/decision dates: `{len(frame)}` / `{frame['ticker'].nunique()}` / `{len(dates)}`",
        f"- date range: `{dates[0]}` to `{dates[-1]}`",
        "- historical Russell membership PIT-certified: **NO**",
        "- feature_available_from / valuation_price_cutoff provenance in recovered candidate book: **NO**",
        "",
        "## Baseline 25 bps/side diagnostic",
        "",
        "| portfolio | CAGR | MDD | Sharpe | Sortino | Calmar | periods |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Main | {f(base['metrics'].get('cagr'))} | {f(base['metrics'].get('max_drawdown'))} | {f(base['metrics'].get('sharpe'))} | {f(base['metrics'].get('sortino'))} | {f(base['metrics'].get('calmar'))} | {base['metrics'].get('periods')} |",
        f"| Concentrated | {f(conc['metrics'].get('cagr'))} | {f(conc['metrics'].get('max_drawdown'))} | {f(conc['metrics'].get('sharpe'))} | {f(conc['metrics'].get('sortino'))} | {f(conc['metrics'].get('calmar'))} | {conc['metrics'].get('periods')} |",
        "",
        "## Interpretation boundary",
        "",
        "This is a one-shot diagnostic of the new architecture, not final OOS certification. Theme/ETF current mappings, qualitative judgments, strict 13F manager skill, Form4, and forward-consensus overlays are excluded from historical scoring until contemporaneous PIT histories exist. Macro affects only gross equity exposure. r_1m is used only after target weights are frozen, as an outcome label.",
    ]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "OK",
        "experiment_id": config["experiment_id"],
        "source_sha256": source_sha,
        "rows": len(frame),
        "tickers": int(frame["ticker"].nunique()),
        "decision_dates": len(dates),
        "main_25bps": base["metrics"],
        "concentrated_25bps": conc["metrics"],
    }, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
