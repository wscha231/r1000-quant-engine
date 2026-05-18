#!/usr/bin/env python3
"""Regime-adaptive broker-ledger grid for alpha-selector target books.

Fixed-N alpha-selector variants proved that the leader selector can produce
high broker-ledger CAGR, but the same fixed concentration carries too much
account drawdown in hostile regimes. This research-only sidecar keeps the same
point-in-time candidate features and next-close broker replay, but switches the
style/N/cap recipe by the candidate book's same-date `regime_state`.

It does not change production defaults and never uses forward-return labels for
selection.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alpha_selector_broker_grid import (  # noqa: E402
    STYLE_WEIGHTS,
    add_price_cache_tradeability,
    build_target_book,
    clean_label,
    prepare_candidates,
    read_csv,
    target_distance,
)
from tools.run_broker_ledger_replay import replay as broker_replay, repo_path, safe_float  # noqa: E402


DEFAULT_CANDIDATE_BOOK = "outputs/reports/candidate_replay_book.csv"
DEFAULT_OUT_DIR = "outputs/alpha_selector_dynamic_regime_grid"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def parse_variant(value: str) -> tuple[str, int, float]:
    text = str(value or "").strip()
    parts = text.split("_N")
    if len(parts) != 2 or "_cap" not in parts[1]:
        raise ValueError(f"invalid alpha-selector variant spec: {value!r}")
    style = parts[0]
    n_text, cap_text = parts[1].split("_cap", 1)
    if style not in STYLE_WEIGHTS:
        raise ValueError(f"unknown alpha-selector style in variant spec: {value!r}")
    return style, int(float(n_text)), float(cap_text)


def parse_csv(value: str, default: list[str]) -> list[str]:
    out = [x.strip() for x in str(value or "").split(",") if x.strip()]
    return out or list(default)


def parse_float_csv(value: str, default: list[float]) -> list[float]:
    out: list[float] = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out or list(default)


def variant_label(spec: tuple[str, int, float]) -> str:
    style, n, cap = spec
    return f"{style}_N{int(n)}_cap{clean_label(cap)}"


def combo_label(
    bull: tuple[str, int, float],
    neutral: tuple[str, int, float],
    bear: tuple[str, int, float],
    bear_multiplier: float,
    neutral_multiplier: float,
) -> str:
    return (
        f"dyn_b{variant_label(bull)}"
        f"_n{variant_label(neutral)}"
        f"_r{variant_label(bear)}"
        f"_bm{clean_label(bear_multiplier)}"
        f"_nm{clean_label(neutral_multiplier)}"
    )


def regime_by_date(candidates: pd.DataFrame) -> dict[pd.Timestamp, str]:
    if candidates.empty or "rebalance_date" not in candidates.columns:
        return {}
    d = candidates[["rebalance_date"] + (["regime_state"] if "regime_state" in candidates.columns else [])].copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    if "regime_state" not in d.columns:
        d["regime_state"] = "neutral"
    d["regime_state"] = d["regime_state"].fillna("neutral").astype(str).str.lower()
    return d.dropna(subset=["rebalance_date"]).drop_duplicates("rebalance_date").set_index("rebalance_date")["regime_state"].to_dict()


def build_base_targets(
    candidates: pd.DataFrame,
    specs: set[tuple[str, int, float]],
    *,
    min_mcap: float,
    min_dollar_vol: float,
    min_price: float,
    require_price_cache: bool,
) -> dict[tuple[str, int, float], pd.DataFrame]:
    out: dict[tuple[str, int, float], pd.DataFrame] = {}
    for style, n, cap in sorted(specs):
        target = build_target_book(
            candidates,
            style=style,
            target_n=n,
            single_name_cap=cap,
            min_mcap=min_mcap,
            min_dollar_vol=min_dollar_vol,
            min_price=min_price,
            require_price_cache=require_price_cache,
        )
        if not target.empty:
            target["rebalance_date"] = pd.to_datetime(target["rebalance_date"], errors="coerce").dt.normalize()
        out[(style, n, cap)] = target
    return out


def stitch_dynamic_target(
    base_targets: dict[tuple[str, int, float], pd.DataFrame],
    regimes: dict[pd.Timestamp, str],
    *,
    bull: tuple[str, int, float],
    neutral: tuple[str, int, float],
    bear: tuple[str, int, float],
    bear_multiplier: float,
    neutral_multiplier: float,
) -> pd.DataFrame:
    dates: set[pd.Timestamp] = set()
    for target in base_targets.values():
        if not target.empty:
            dates.update(pd.to_datetime(target["rebalance_date"], errors="coerce").dropna().dt.normalize().tolist())
    rows: list[pd.DataFrame] = []
    for dt in sorted(dates):
        state = str(regimes.get(pd.Timestamp(dt), "neutral") or "neutral").lower()
        if state in {"bull", "strong_bull"}:
            spec = bull
            multiplier = 1.0
        elif state == "neutral":
            spec = neutral
            multiplier = float(neutral_multiplier)
        else:
            spec = bear
            multiplier = float(bear_multiplier)
        target = base_targets.get(spec, pd.DataFrame())
        if target.empty:
            continue
        sub = target[target["rebalance_date"].eq(pd.Timestamp(dt))].copy()
        if sub.empty:
            continue
        sub["weight"] = pd.to_numeric(sub["weight"], errors="coerce").fillna(0.0) * max(0.0, multiplier)
        sub = sub[sub["weight"] > 1e-12]
        if sub.empty:
            continue
        sub["dynamic_regime_state"] = state
        sub["dynamic_regime_source_variant"] = variant_label(spec)
        sub["dynamic_regime_multiplier"] = float(multiplier)
        rows.append(sub)
    if not rows:
        return pd.DataFrame(columns=["rebalance_date", "ticker", "weight"])
    out = pd.concat(rows, ignore_index=True)
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
    return out.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_book = repo_path(args.candidate_book)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = prepare_candidates(read_csv(candidate_book))
    require_price_cache = not bool(getattr(args, "allow_unfillable_targets", False))
    if require_price_cache:
        candidates = add_price_cache_tradeability(candidates, price_cache, int(args.max_fill_lag_days))
    if candidates.empty:
        payload = {
            "status": "blocked",
            "reason": "candidate replay book is missing or empty",
            "candidate_book": str(candidate_book),
            "valid_for_production": False,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "best_metrics.json", payload)
        return payload

    bull_specs = [parse_variant(x) for x in parse_csv(args.bull_variants, ["rs_heavy_N2_cap0.5", "rs_heavy_N3_cap0.5"])]
    neutral_specs = [parse_variant(x) for x in parse_csv(args.neutral_variants, ["rs_heavy_N2_cap0.4", "rs_heavy_N3_cap0.33"])]
    bear_specs = [parse_variant(x) for x in parse_csv(args.bear_variants, ["rs_heavy_N3_cap0.25", "rs_heavy_N4_cap0.33"])]
    bear_multipliers = parse_float_csv(args.bear_multipliers, [0.5, 0.75, 1.0])
    neutral_multipliers = parse_float_csv(args.neutral_multipliers, [0.9, 1.0])

    specs = set(bull_specs + neutral_specs + bear_specs)
    base_targets = build_base_targets(
        candidates,
        specs,
        min_mcap=float(args.min_market_cap_usd),
        min_dollar_vol=float(args.min_dollar_volume_usd),
        min_price=float(args.min_price),
        require_price_cache=require_price_cache,
    )
    regimes = regime_by_date(candidates)

    rows: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    variant_count = 0
    stop = False
    for bull in bull_specs:
        for neutral in neutral_specs:
            for bear in bear_specs:
                for bear_multiplier in bear_multipliers:
                    for neutral_multiplier in neutral_multipliers:
                        if variant_count >= int(args.max_variants):
                            stop = True
                            break
                        variant_count += 1
                        vid = combo_label(bull, neutral, bear, bear_multiplier, neutral_multiplier)
                        variant_dir = output_dir / vid
                        variant_dir.mkdir(parents=True, exist_ok=True)
                        target = stitch_dynamic_target(
                            base_targets,
                            regimes,
                            bull=bull,
                            neutral=neutral,
                            bear=bear,
                            bear_multiplier=bear_multiplier,
                            neutral_multiplier=neutral_multiplier,
                        )
                        target_path = variant_dir / "target_book.csv"
                        target.to_csv(target_path, index=False)
                        try:
                            metrics = broker_replay(
                                target_book=target_path,
                                price_cache=price_cache,
                                output_dir=variant_dir,
                                portfolio_kind=args.portfolio_kind,
                                starting_capital=float(args.starting_capital),
                                fill_mode=args.fill_mode,
                                cost_bps=float(args.cost_bps),
                                integer_shares=not bool(args.no_integer_shares),
                                max_fill_lag_days=int(args.max_fill_lag_days),
                            )
                        except Exception as exc:
                            metrics = {
                                "status": "blocked",
                                "reason": f"broker replay failed: {type(exc).__name__}: {exc}",
                                "valid_for_production": False,
                            }
                        metrics.update(
                            {
                                "candidate_id": f"{args.portfolio_kind}_alpha_selector_dynamic_regime_grid_{vid}",
                                "metric_mode": "alpha_selector_dynamic_regime_next_close",
                                "data_mode": "same_date_regime_adaptive_alpha_selector",
                                "portfolio_kind": args.portfolio_kind,
                                "dynamic_regime_variant": vid,
                                "bull_variant": variant_label(bull),
                                "neutral_variant": variant_label(neutral),
                                "bear_variant": variant_label(bear),
                                "neutral_multiplier": float(neutral_multiplier),
                                "bear_multiplier": float(bear_multiplier),
                                "candidate_book": str(candidate_book),
                                "target_book": str(target_path),
                                "require_price_cache": require_price_cache,
                                "research_only": True,
                                "production_activation_allowed": False,
                            }
                        )
                        write_json(variant_dir / "metrics.json", metrics)
                        rows.append(
                            {
                                "variant_id": vid,
                                "status": metrics.get("status"),
                                "cagr": metrics.get("cagr"),
                                "max_dd": metrics.get("max_dd", metrics.get("max_drawdown")),
                                "sharpe": metrics.get("sharpe"),
                                "trade_count": metrics.get("trade_count"),
                                "avg_cash_weight": metrics.get("avg_cash_weight"),
                                "target_distance": target_distance(args.portfolio_kind, metrics),
                                "valid_for_production": bool(metrics.get("valid_for_production")),
                                "bull_variant": variant_label(bull),
                                "neutral_variant": variant_label(neutral),
                                "bear_variant": variant_label(bear),
                                "neutral_multiplier": float(neutral_multiplier),
                                "bear_multiplier": float(bear_multiplier),
                                "reason": metrics.get("reason", ""),
                            }
                        )
                        if metrics.get("status") == "completed" and metrics.get("valid_for_production"):
                            completed.append(metrics)
                    if stop:
                        break
                if stop:
                    break
            if stop:
                break
        if stop:
            break

    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(["target_distance", "cagr", "max_dd"], ascending=[True, False, False])
    summary.to_csv(output_dir / "summary.csv", index=False)

    if completed:
        best_by_distance = sorted(completed, key=lambda m: (target_distance(args.portfolio_kind, m), -safe_float(m.get("cagr"), -1.0)))[0]
        best_distance_payload = dict(best_by_distance)
        best_distance_payload.update(
            {
                "candidate_id": f"{args.portfolio_kind}_alpha_selector_dynamic_regime_grid_best_distance",
                "metric_mode": "alpha_selector_dynamic_regime_grid_best_distance_next_close",
                "variant_count": variant_count,
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": True,
            }
        )
        write_json(output_dir / "best_target_distance_metrics.json", best_distance_payload)
        best = sorted(
            completed,
            key=lambda m: (
                -safe_float(m.get("cagr"), -1.0),
                -safe_float(m.get("sharpe"), -1.0),
                safe_float(m.get("max_dd", m.get("max_drawdown")), -1.0),
            ),
        )[0]
        best_payload = dict(best)
        best_payload.update(
            {
                "candidate_id": f"{args.portfolio_kind}_alpha_selector_dynamic_regime_grid_best",
                "metric_mode": "alpha_selector_dynamic_regime_grid_best_next_close",
                "variant_count": variant_count,
                "selection_rule": "best_cagr_then_sharpe_then_max_dd",
                "best_target_distance_metrics": str(output_dir / "best_target_distance_metrics.json"),
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": True,
            }
        )
    else:
        best_payload = {
            "status": "blocked",
            "reason": "no completed alpha selector dynamic regime grid variants",
            "portfolio_kind": args.portfolio_kind,
            "variant_count": variant_count,
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
    write_json(output_dir / "best_metrics.json", best_payload)
    report = [
        "# Alpha Selector Dynamic Regime Grid",
        "",
        "Research-only account-ledger grid that adapts alpha-selector concentration by same-date regime_state.",
        "",
        f"- portfolio_kind: {args.portfolio_kind}",
        f"- variants_tested: {variant_count}",
        f"- best_cagr: {safe_float(best_payload.get('cagr'), math.nan):.2%}" if best_payload.get("cagr") is not None else "- best_cagr: n/a",
        f"- best_max_dd: {safe_float(best_payload.get('max_dd', best_payload.get('max_drawdown')), math.nan):.2%}"
        if best_payload.get("max_dd", best_payload.get("max_drawdown")) is not None
        else "- best_max_dd: n/a",
        "",
        "Promotion requires broker-ledger target gates, stress-window review, leakage audit, and human approval.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return best_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="main")
    parser.add_argument("--bull-variants", default="rs_heavy_N2_cap0.5,rs_heavy_N3_cap0.5")
    parser.add_argument("--neutral-variants", default="rs_heavy_N2_cap0.4,rs_heavy_N3_cap0.33,rs_heavy_N3_cap0.25")
    parser.add_argument("--bear-variants", default="rs_heavy_N3_cap0.25,rs_heavy_N4_cap0.33,rs_heavy_N2_cap0.4")
    parser.add_argument("--neutral-multipliers", default="0.9,1.0")
    parser.add_argument("--bear-multipliers", default="0.5,0.75,1.0")
    parser.add_argument("--min-market-cap-usd", type=float, default=1_000_000_000)
    parser.add_argument("--min-dollar-volume-usd", type=float, default=10_000_000)
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--no-integer-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--allow-unfillable-targets", action="store_true")
    parser.add_argument("--max-variants", type=int, default=54)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload.get("status"), "cagr": payload.get("cagr"), "max_dd": payload.get("max_dd")}, indent=2))
    return 0 if payload.get("status") != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
