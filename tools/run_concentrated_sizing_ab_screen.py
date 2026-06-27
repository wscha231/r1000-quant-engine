#!/usr/bin/env python3
"""Target-book audit screen for concentrated score-family sizing.

This is not a broker replay. It keeps the selected names and cash exposure from
the official target book, then tests whether score-tilted weights would have
improved audit-label forward returns. Forward returns are labels only and must
not be used in live ranking or production policy.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "concentrated-sizing-ab-screen-v1"
CASH_TICKERS = {"CASH", "__CASH__"}
EVAL_SPLIT_DATE = pd.Timestamp("2024-06-03")
SIGNAL_COLUMNS = [
    "alphaops_vnext_score",
    "alphaops_vnext_weight_score",
    "weighting_score",
]
VARIANTS = [
    {"variant": "blend25_rank_power1", "blend": 0.25, "power": 1.0},
    {"variant": "blend50_rank_power1", "blend": 0.50, "power": 1.0},
    {"variant": "blend50_rank_power1_5", "blend": 0.50, "power": 1.5},
    {"variant": "blend75_rank_power1_5", "blend": 0.75, "power": 1.5},
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def target_book_path(latest_run: Path, explicit: str | None = None) -> Path:
    if explicit:
        return repo_path(explicit)
    candidates = [
        latest_run / "reports" / "operating_concentrated_target_book.csv",
        latest_run / "alphaops_vnext" / "official_concentrated_target_book.csv",
        latest_run / "market_leader_challenger" / "concentrated_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def load_target_book(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path, low_memory=False)
    required = {"rebalance_date", "ticker", "period_forward_return"}
    if d.empty or not required.issubset(d.columns):
        return pd.DataFrame()
    d = d.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d = d[d["rebalance_date"].notna()]
    d = d[~d["ticker"].isin(CASH_TICKERS)]
    d["forward_return"] = pd.to_numeric(d["period_forward_return"], errors="coerce")
    weight_col = "weight" if "weight" in d.columns else "target_weight"
    d["base_weight"] = pd.to_numeric(d.get(weight_col), errors="coerce")
    d = d[d["forward_return"].notna() & d["base_weight"].notna()]
    return d


def score_allocation(group: pd.DataFrame, signal: str, power: float) -> pd.Series:
    base = pd.to_numeric(group["base_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    gross = float(base.sum())
    if gross <= 0 or signal not in group.columns:
        return base
    values = pd.to_numeric(group[signal], errors="coerce")
    if values.notna().sum() < 2 or values.nunique(dropna=True) < 2:
        return base
    ranks = values.rank(method="average", pct=True).fillna(0.0).clip(lower=0.0)
    raw = ranks.pow(power)
    denom = float(raw.sum())
    if denom <= 0:
        return base
    return raw / denom * gross


def variant_rows(book: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for dt, group in book.groupby("rebalance_date"):
        date = pd.Timestamp(dt).normalize()
        base = group.copy()
        base_weight = pd.to_numeric(base["base_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
        for _, row in base.iterrows():
            rows.append(
                {
                    "rebalance_date": date.date().isoformat(),
                    "ticker": row["ticker"],
                    "variant": "baseline",
                    "signal": "baseline",
                    "weight": safe_float(row.get("base_weight")),
                    "base_weight": safe_float(row.get("base_weight")),
                    "forward_return": safe_float(row.get("forward_return")),
                }
            )
        for signal in SIGNAL_COLUMNS:
            if signal not in base.columns:
                continue
            for spec in VARIANTS:
                alloc = score_allocation(base, signal, float(spec["power"]))
                new_weight = (1.0 - float(spec["blend"])) * base_weight + float(spec["blend"]) * alloc
                for idx, row in base.iterrows():
                    rows.append(
                        {
                            "rebalance_date": date.date().isoformat(),
                            "ticker": row["ticker"],
                            "variant": str(spec["variant"]),
                            "signal": signal,
                            "weight": float(new_weight.loc[idx]),
                            "base_weight": safe_float(row.get("base_weight")),
                            "forward_return": safe_float(row.get("forward_return")),
                        }
                    )
    return pd.DataFrame(rows)


def curve_metrics(returns: pd.DataFrame) -> dict[str, Any]:
    if returns.empty:
        return {"status": "empty"}
    d = returns.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d = d[d["rebalance_date"].notna()].sort_values("rebalance_date")
    if d.empty:
        return {"status": "empty"}
    equity = (1.0 + pd.to_numeric(d["period_return"], errors="coerce").fillna(0.0)).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1.0
    start = pd.Timestamp(d["rebalance_date"].iloc[0])
    end = pd.Timestamp(d["rebalance_date"].iloc[-1])
    years = max((end - start).days / 365.25, 1 / 365.25)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if equity.iloc[-1] > 0 else -1.0
    return {
        "status": "ok",
        "row_count": int(len(d)),
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "years": float(years),
        "ending_equity": float(equity.iloc[-1]),
        "audit_label_cagr_proxy": cagr,
        "audit_label_max_drawdown_proxy": float(dd.min()),
        "mean_period_return": float(pd.to_numeric(d["period_return"], errors="coerce").mean()),
    }


def variant_period_returns(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    d = rows.copy()
    d["weighted_return"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0) * pd.to_numeric(
        d["forward_return"], errors="coerce"
    ).fillna(0.0)
    grouped = (
        d.groupby(["variant", "signal", "rebalance_date"])
        .agg(period_return=("weighted_return", "sum"), gross_weight=("weight", "sum"), max_weight=("weight", "max"))
        .reset_index()
    )
    return grouped


def summarize_variants(periods: pd.DataFrame) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    if periods.empty:
        return [], pd.DataFrame()
    summaries: list[dict[str, Any]] = []
    baseline_periods = periods[(periods["variant"].eq("baseline")) & (periods["signal"].eq("baseline"))]
    baseline_full = curve_metrics(baseline_periods)
    baseline_oos = curve_metrics(baseline_periods[pd.to_datetime(baseline_periods["rebalance_date"]).ge(EVAL_SPLIT_DATE)])
    for (variant, signal), group in periods.groupby(["variant", "signal"]):
        full = curve_metrics(group)
        oos = curve_metrics(group[pd.to_datetime(group["rebalance_date"]).ge(EVAL_SPLIT_DATE)])
        if full.get("status") != "ok":
            continue
        base_cagr = safe_float(baseline_full.get("audit_label_cagr_proxy"))
        base_mdd = safe_float(baseline_full.get("audit_label_max_drawdown_proxy"))
        oos_base_cagr = safe_float(baseline_oos.get("audit_label_cagr_proxy"))
        oos_base_mdd = safe_float(baseline_oos.get("audit_label_max_drawdown_proxy"))
        full_cagr = safe_float(full.get("audit_label_cagr_proxy"))
        full_mdd = safe_float(full.get("audit_label_max_drawdown_proxy"))
        oos_cagr = safe_float(oos.get("audit_label_cagr_proxy"))
        oos_mdd = safe_float(oos.get("audit_label_max_drawdown_proxy"))
        summaries.append(
            {
                "variant": variant,
                "signal": signal,
                "full": full,
                "oos": oos,
                "delta_cagr_proxy": full_cagr - base_cagr,
                "delta_mdd_proxy": full_mdd - base_mdd,
                "oos_delta_cagr_proxy": oos_cagr - oos_base_cagr,
                "oos_delta_mdd_proxy": oos_mdd - oos_base_mdd,
                "gross_weight_min": float(group["gross_weight"].min()),
                "gross_weight_max": float(group["gross_weight"].max()),
                "max_weight_max": float(group["max_weight"].max()),
                "screen_candidate": bool(
                    variant != "baseline"
                    and full_cagr > base_cagr
                    and oos_cagr > oos_base_cagr
                    and (full_mdd - base_mdd) >= -0.03
                    and (oos_mdd - oos_base_mdd) >= -0.05
                ),
            }
        )
    table = pd.DataFrame(
        [
            {
                "variant": item["variant"],
                "signal": item["signal"],
                "delta_cagr_proxy": item["delta_cagr_proxy"],
                "delta_mdd_proxy": item["delta_mdd_proxy"],
                "oos_delta_cagr_proxy": item["oos_delta_cagr_proxy"],
                "oos_delta_mdd_proxy": item["oos_delta_mdd_proxy"],
                "screen_candidate": item["screen_candidate"],
                "max_weight_max": item["max_weight_max"],
            }
            for item in summaries
        ]
    )
    return summaries, table


def build_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Concentrated Sizing A/B Screen",
        "",
        "Research-only target-book audit. This is not broker-ledger evidence.",
        "",
        f"- generated_at_utc: {payload['generated_at_utc']}",
        f"- target_book_source: {payload.get('target_book_source')}",
        f"- next_action: {payload.get('next_action')}",
        "",
        "| variant | signal | delta CAGR proxy | delta MDD proxy | OOS delta CAGR proxy | OOS delta MDD proxy | candidate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in payload.get("variant_table", []):
        lines.append(
            "| {variant} | {signal} | {dc:.2%} | {dm:.2%} | {odc:.2%} | {odm:.2%} | {cand} |".format(
                variant=item["variant"],
                signal=item["signal"],
                dc=safe_float(item.get("delta_cagr_proxy")),
                dm=safe_float(item.get("delta_mdd_proxy")),
                odc=safe_float(item.get("oos_delta_cagr_proxy")),
                odm=safe_float(item.get("oos_delta_mdd_proxy")),
                cand=item.get("screen_candidate"),
            )
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "- Passing here only allows a target-book or broker A/B design.",
            "- Forward returns are audit labels only and are never live sizing inputs.",
            "- Production remains blocked without broker-ledger, PIT universe, and human approval gates.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--target-book", default=None)
    parser.add_argument("--output-dir", default="outputs/concentrated_sizing_ab_screen")
    args = parser.parse_args()

    latest_run = repo_path(args.latest_run)
    target_path = target_book_path(latest_run, args.target_book)
    output_dir = repo_path(args.output_dir)
    book = load_target_book(target_path)
    rows = variant_rows(book)
    periods = variant_period_returns(rows)
    summaries, table = summarize_variants(periods)
    candidates = [item for item in summaries if item.get("screen_candidate")]
    candidate_table = sorted(
        [
            {
                "variant": item["variant"],
                "signal": item["signal"],
                "delta_cagr_proxy": item["delta_cagr_proxy"],
                "delta_mdd_proxy": item["delta_mdd_proxy"],
                "oos_delta_cagr_proxy": item["oos_delta_cagr_proxy"],
                "oos_delta_mdd_proxy": item["oos_delta_mdd_proxy"],
                "max_weight_max": item["max_weight_max"],
            }
            for item in candidates
        ],
        key=lambda x: (safe_float(x.get("delta_cagr_proxy")), safe_float(x.get("oos_delta_cagr_proxy"))),
        reverse=True,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "research_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "broker_replay_executed": False,
        "audit_label_only": True,
        "cash_exposure_preserved": True,
        "target_book_source": str(target_path),
        "split_date": EVAL_SPLIT_DATE.date().isoformat(),
        "next_action": "design_broker_sizing_ab" if candidates else "discard_reweight_variants",
        "candidate_count": int(len(candidates)),
        "recommended_broker_ab_variant": candidate_table[0] if candidate_table else None,
        "candidate_variants": candidate_table,
        "variants": summaries,
        "variant_table": table.to_dict("records") if not table.empty else [],
    }
    write_json(output_dir / "summary.json", payload)
    write_csv(output_dir / "variant_weights.csv", rows)
    write_csv(output_dir / "variant_period_returns.csv", periods)
    write_csv(output_dir / "variant_summary.csv", table)
    (output_dir / "report.md").write_text(build_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
