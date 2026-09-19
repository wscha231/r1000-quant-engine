#!/usr/bin/env python3
"""Schema-adapted vNext one-shot diagnostic.

The experiment weights are defined in experiment.json and are not changed here.
This v2 only adapts to the verified recovered schema discovered before any
performance result was produced: benchmark outcome is optional and risk sizing
uses the first contemporaneous scale available from vol_252d, atr14_pct, or
absolute dd_1y.  No legacy model score is admitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SOURCE_SHA = "ebdbbe7e764b735ca129f662c42ec80b68659f4e3196b5a364cf32c506c4c818"
ROWS = 47435
TICKERS = 981
DATES = 85
FIRST = "2019-05-31"
LAST = "2026-05-29"
FORBIDDEN_PREFIXES = ("score_", "pred_", "z_", "portfolio_seed_score", "ensemble_weight_", "sleeve_")


def die(msg: str) -> None:
    raise RuntimeError(msg)


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def member_sha(zf: zipfile.ZipFile, name: str) -> str:
    h = hashlib.sha256()
    with zf.open(name) as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def one_member(zf: zipfile.ZipFile, base: str) -> str:
    hits = [n for n in zf.namelist() if Path(n).name == base]
    if len(hits) != 1:
        die(f"member contract failed for {base}: {len(hits)}")
    return hits[0]


def pct(s: pd.Series, ascending: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return x.rank(pct=True, method="average", ascending=ascending) * 100.0 if x.notna().sum() > 1 else pd.Series(np.nan, index=s.index)


def bools(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def risk_scale(df: pd.DataFrame) -> tuple[pd.Series, str]:
    if "vol_252d" in df.columns:
        x = pd.to_numeric(df["vol_252d"], errors="coerce")
        if (x > 0).sum() > 1:
            return x.where(x > 0), "vol_252d"
    if "atr14_pct" in df.columns:
        x = pd.to_numeric(df["atr14_pct"], errors="coerce")
        if (x > 0).sum() > 1:
            return x.where(x > 0), "atr14_pct"
    if "dd_1y" in df.columns:
        x = pd.to_numeric(df["dd_1y"], errors="coerce").abs()
        if (x > 0).sum() > 1:
            return x.where(x > 0), "abs_dd_1y"
    return pd.Series(np.nan, index=df.index), "MISSING"


def score_date(g: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    x = g.copy()
    weighted = pd.Series(0.0, index=x.index)
    coverage = pd.Series(0.0, index=x.index)
    for pillar, weight in cfg["pillars"].items():
        parts = []
        for col in cfg["pillar_features"].get(pillar, []):
            if col in x.columns:
                parts.append(pct(x[col]))
        ps = pd.concat(parts, axis=1).mean(axis=1, skipna=True) if parts else pd.Series(np.nan, index=x.index)
        x[f"pillar_{pillar}"] = ps
        ok = ps.notna()
        weighted.loc[ok] += float(weight) * ps.loc[ok]
        coverage.loc[ok] += float(weight)
    base = weighted / coverage.replace(0, np.nan)

    risks = []
    for col in cfg["risk_features"]:
        if col not in x.columns:
            continue
        v = pd.to_numeric(x[col], errors="coerce")
        if col == "dd_1y":
            v = -v
        risks.append(pct(v))
    rpct = pd.concat(risks, axis=1).mean(axis=1, skipna=True) if risks else pd.Series(np.nan, index=x.index)
    penalty = rpct.fillna(100.0) / 100.0 * float(cfg["risk_penalty_max_points"])

    rscale, rname = risk_scale(x)
    x["pillar_weight_coverage"] = coverage
    x["vnext_base_score"] = base
    x["vnext_risk_penalty"] = penalty
    x["vnext_score"] = base * coverage - penalty
    x["risk_scale"] = rscale
    x["risk_scale_source"] = rname
    elig = (coverage >= float(cfg["minimum_pillar_weight_coverage"])) & rscale.notna()
    if "backtest_usable" in x.columns:
        elig &= bools(x["backtest_usable"])
    x["vnext_eligible"] = elig
    x["vnext_rank"] = x["vnext_score"].where(elig).rank(ascending=False, method="min")
    return x


def regime(g: pd.DataFrame, cfg: dict[str, Any]) -> tuple[float, str, float | None]:
    values = []
    for col in cfg["regime"]["features"]:
        if col not in g.columns:
            continue
        v = pd.to_numeric(g[col], errors="coerce").median()
        if pd.notna(v) and 0.0 <= float(v) <= 1.0:
            values.append(float(v))
    if not values:
        return 0.65, "UNKNOWN_FAIL_CLOSED", None
    r = float(statistics.median(values))
    for row in cfg["regime"]["thresholds"]:
        if r >= float(row["min"]):
            return float(row["equity_exposure"]), "OBSERVED", r
    return 0.65, "INVALID_FAIL_CLOSED", r


def cap_weights(raw: pd.Series, exposure: float, cap: float) -> pd.Series:
    raw = pd.to_numeric(raw, errors="coerce").fillna(0.0).clip(lower=0.0)
    out = pd.Series(0.0, index=raw.index)
    active = list(raw.index)
    left = float(exposure)
    while active and left > 1e-12:
        vals = raw.loc[active]
        prop = vals / vals.sum() * left if vals.sum() > 0 else pd.Series(left / len(active), index=active)
        over = prop[prop > cap + 1e-12]
        if over.empty:
            out.loc[active] += prop
            break
        for idx in list(over.index):
            add = min(cap - out.loc[idx], left)
            if add > 0:
                out.loc[idx] += add
                left -= add
            active.remove(idx)
    return out


def choose(g: pd.DataFrame, prev: set[str], spec: dict[str, Any]) -> list[str]:
    e = g[g["vnext_eligible"]].sort_values(["vnext_rank", "ticker"])
    if e.empty:
        return []
    m = e.set_index("ticker")
    keep = [t for t in prev if t in m.index and float(m.loc[t, "vnext_rank"]) <= float(spec["retention_rank"])]
    keep.sort(key=lambda t: (float(m.loc[t, "vnext_rank"]), t))
    out = keep[: int(spec["target_names"])]
    for t in e["ticker"].astype(str):
        if t not in out:
            out.append(t)
        if len(out) >= int(spec["target_names"]):
            break
    return out


def weights(g: pd.DataFrame, names: list[str], exposure: float, spec: dict[str, Any]) -> pd.Series:
    if not names:
        return pd.Series(dtype=float)
    m = g.set_index("ticker").loc[names]
    strength = (pd.to_numeric(m["vnext_score"], errors="coerce") - 40.0).clip(lower=1.0)
    rs = pd.to_numeric(m["risk_scale"], errors="coerce").clip(lower=0.02)
    raw = strength / rs
    exp = min(float(exposure), 1.0 - float(spec["minimum_cash"]))
    return cap_weights(raw, exp, float(spec["max_weight"]))


def mdd(nav: list[float]) -> float | None:
    if not nav:
        return None
    peak, worst = nav[0], 0.0
    for v in nav:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return worst


def stats(rets: list[float]) -> dict[str, Any]:
    if not rets:
        return {"periods": 0, "ending_multiple": None, "cagr": None, "max_drawdown": None, "sharpe": None, "sortino": None, "calmar": None}
    nav, value = [], 1.0
    for r in rets:
        value *= 1.0 + float(r)
        nav.append(value)
    a = np.asarray(rets, dtype=float)
    cagr = value ** (12.0 / len(rets)) - 1.0 if value > 0 else None
    draw = mdd(nav)
    sd = float(a.std(ddof=1)) if len(a) > 1 else 0.0
    neg = a[a < 0]
    dsd = float(np.sqrt(np.mean(np.square(neg)))) if len(neg) else 0.0
    return {
        "periods": len(rets), "ending_multiple": value, "cagr": cagr, "max_drawdown": draw,
        "sharpe": float(a.mean() / sd * math.sqrt(12.0)) if sd > 0 else None,
        "sortino": float(a.mean() / dsd * math.sqrt(12.0)) if dsd > 0 else None,
        "calmar": float(cagr / abs(draw)) if cagr is not None and draw not in (None, 0.0) else None,
        "monthly_mean": float(a.mean()), "positive_month_fraction": float((a > 0).mean()),
    }


def replay(frame: pd.DataFrame, cfg: dict[str, Any], portfolio: str, bps: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    spec = cfg[portfolio]
    prev_names: set[str] = set()
    prev_end: dict[str, float] = {}
    rows, rets = [], []
    for date in sorted(frame["rebalance_date"].dropna().unique()):
        g = score_date(frame[frame["rebalance_date"] == date], cfg)
        exp, rstatus, rscore = regime(g, cfg)
        names = choose(g, prev_names, spec)
        w = weights(g, names, exp, spec)
        cash = 1.0 - float(w.sum())
        outcomes = pd.to_numeric(g.set_index("ticker")[cfg["execution"]["outcome_column"]], errors="coerce")
        missing = [t for t in names if t not in outcomes.index or not math.isfinite(float(outcomes.loc[t]))]
        if missing:
            rows.append({"rebalance_date": date, "status": "BLOCKED_OUTCOME_MISSING", "missing": ";".join(missing)})
            break
        if names and float(outcomes.loc[names].abs().max()) > 5.0:
            die(f"outcome scale invalid on {date}")
        target = {t: float(w.loc[t]) for t in w.index}
        turnover = sum(abs(target.get(t, 0.0) - prev_end.get(t, 0.0)) for t in set(target) | set(prev_end))
        cost = float(bps) / 10000.0 * turnover
        if cash - cost < -1e-9:
            die(f"cost exceeds cash buffer on {date}")
        gross = sum(target[t] * float(outcomes.loc[t]) for t in names)
        net = gross - cost
        total = 1.0 + net
        prev_end = {t: target[t] * (1.0 + float(outcomes.loc[t])) / total for t in names}
        prev_names = set(names)
        rets.append(net)
        rows.append({
            "rebalance_date": date, "status": "OK", "portfolio": portfolio, "cost_bps_per_side": bps,
            "selected": ";".join(names), "selected_count": len(names), "equity_exposure": float(w.sum()),
            "cash_weight": cash, "regime_status": rstatus, "regime_risk_score": rscore,
            "risk_scale_sources": ";".join(sorted(set(g.loc[g["ticker"].isin(names), "risk_scale_source"].astype(str)))),
            "turnover_stock_notional": turnover, "cost_return_drag": cost, "gross_return": gross, "net_return": net,
        })
    return pd.DataFrame(rows), stats(rets)


def subset_stats(periods: pd.DataFrame, start: str, end: str) -> dict[str, Any]:
    if periods.empty:
        return stats([])
    d = pd.to_datetime(periods["rebalance_date"], errors="coerce")
    x = periods[(periods["status"] == "OK") & (d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]
    return stats(pd.to_numeric(x["net_return"], errors="coerce").dropna().tolist())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-zip", required=True)
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--output-dir", required=True)
    a = ap.parse_args()
    cfg = json.loads(Path(a.experiment).read_text(encoding="utf-8"))
    source = Path(a.source_zip)
    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    src_sha = file_sha(source)
    if src_sha != SOURCE_SHA:
        die(f"source sha mismatch: {src_sha}")

    known = {"rebalance_date", "ticker", "sector", "r_1m", "bench_r_1m", "backtest_usable", "vol_252d", "atr14_pct", "dd_1y"}
    for xs in cfg["pillar_features"].values():
        known.update(xs)
    known.update(cfg["risk_features"])
    known.update(cfg["regime"]["features"])

    with zipfile.ZipFile(source) as zf:
        member = one_member(zf, "candidate_replay_book_sec_enriched.csv")
        raw_member = one_member(zf, "candidate_replay_book.csv")
        enriched_sha, raw_sha = member_sha(zf, member), member_sha(zf, raw_member)
        header = pd.read_csv(zf.open(member), nrows=0).columns.tolist()
        usecols = [c for c in header if c in known and not c.startswith(FORBIDDEN_PREFIXES)]
        required = {"rebalance_date", "ticker", "r_1m"}
        if required - set(usecols):
            die(f"required columns absent: {sorted(required-set(usecols))}")
        frame = pd.read_csv(zf.open(member), usecols=usecols, low_memory=False)

    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    dates = sorted(frame["rebalance_date"].dropna().unique())
    if len(frame) != ROWS or frame["ticker"].nunique() != TICKERS or len(dates) != DATES or dates[0] != FIRST or dates[-1] != LAST:
        die(f"source contract drift rows={len(frame)} tickers={frame['ticker'].nunique()} dates={len(dates)} first={dates[0]} last={dates[-1]}")
    leaked = [c for c in usecols if c.startswith(FORBIDDEN_PREFIXES)]
    if leaked:
        die(f"legacy score leak: {leaked}")

    summary: dict[str, Any] = {
        "schema_version": "vnext-integrated-diagnostic-result-v2",
        "experiment_id": cfg["experiment_id"], "authority": "RESEARCH_ONLY",
        "source_archive_sha256": src_sha, "candidate_member_sha256": enriched_sha,
        "raw_candidate_member_sha256": raw_sha, "rows": len(frame), "tickers": int(frame["ticker"].nunique()),
        "decision_dates": len(dates), "date_range": [dates[0], dates[-1]], "used_columns": sorted(usecols),
        "benchmark_outcome_available": "bench_r_1m" in frame.columns, "legacy_score_columns_used": leaked,
        "historical_pit_certified": False, "production_allowed": False, "orders_allowed": False,
        "experiment_config_sha256": hashlib.sha256(Path(a.experiment).read_bytes()).hexdigest(), "results": {},
    }

    for portfolio in ("main", "concentrated"):
        summary["results"][portfolio] = {}
        for bps in cfg["execution"]["cost_sensitivity_bps_per_side"]:
            periods, metr = replay(frame, cfg, portfolio, int(bps))
            fname = f"periods_{portfolio}_{int(bps)}bps.csv"
            periods.to_csv(out / fname, index=False)
            windows = {k: subset_stats(periods, *v) for k, v in cfg["evaluation_windows"].items()}
            summary["results"][portfolio][str(bps)] = {
                "metrics": metr, "windows": windows, "blocked_rows": int((periods["status"] != "OK").sum()), "period_file": fname,
            }

    latest = score_date(frame[frame["rebalance_date"] == dates[-1]], cfg).sort_values(["vnext_rank", "ticker"])
    latest.to_csv(out / "latest_historical_scores_20260529.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    b = str(cfg["execution"]["baseline_cost_bps_per_side"])
    main_m = summary["results"]["main"][b]["metrics"]
    conc_m = summary["results"]["concentrated"][b]["metrics"]
    def ff(v: Any) -> str:
        return "N/A" if v is None else f"{float(v):.4f}"
    report = [
        "# vNext Integrated Core — one-shot diagnostic replay v2", "",
        "RESEARCH_ONLY. Fresh score architecture; no legacy score_total/champion/paper weights are selection inputs.", "",
        f"- experiment: `{cfg['experiment_id']}`", f"- config SHA256: `{summary['experiment_config_sha256']}`",
        f"- source SHA256: `{src_sha}`", f"- rows/tickers/dates: `{len(frame)}` / `{frame['ticker'].nunique()}` / `{len(dates)}`",
        f"- date range: `{dates[0]}` to `{dates[-1]}`", f"- admitted columns: `{', '.join(sorted(usecols))}`", "",
        "| portfolio | CAGR | MDD | Sharpe | Sortino | Calmar | periods |", "|---|---:|---:|---:|---:|---:|---:|",
        f"| Main | {ff(main_m.get('cagr'))} | {ff(main_m.get('max_drawdown'))} | {ff(main_m.get('sharpe'))} | {ff(main_m.get('sortino'))} | {ff(main_m.get('calmar'))} | {main_m.get('periods')} |",
        f"| Concentrated | {ff(conc_m.get('cagr'))} | {ff(conc_m.get('max_drawdown'))} | {ff(conc_m.get('sharpe'))} | {ff(conc_m.get('sortino'))} | {ff(conc_m.get('calmar'))} | {conc_m.get('periods')} |", "",
        "## Boundary", "",
        "This is not final OOS certification. Historical Russell membership remains unproven PIT-safe and the recovered book lacks feature_available_from/valuation_price_cutoff provenance. Current Theme/ETF, qualitative, 13F-manager, Form4 and consensus overlays are not backfilled. Missing benchmark outcome stays N/A rather than being manufactured.",
    ]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"status": "OK", "main_25bps": main_m, "concentrated_25bps": conc_m, "used_columns": sorted(usecols)}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
