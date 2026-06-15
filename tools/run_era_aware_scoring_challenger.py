#!/usr/bin/env python3
"""Build review-only era-aware target-book challengers.

This sidecar turns the era-leadership diagnosis into broker-replayable target
books without mutating production operating books. Promotion requires a
separate A/B, account-evaluation gate, and explicit review.
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


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_broker_ledger_replay import replay as broker_replay  # noqa: E402


CASH_TICKERS = {"CASH", "__CASH__"}
ERA_BUCKETS = [
    ("2019_2021_pre_ai_bull", "2019-01-01", "2021-12-31"),
    ("2022_bear", "2022-01-01", "2022-12-31"),
    ("2023_2024_ai_bull", "2023-01-01", "2024-12-31"),
    ("2025_plus", "2025-01-01", "2099-12-31"),
]

ERA_FEATURE_WEIGHTS: dict[str, list[tuple[str, float]]] = {
    "2019_2021_pre_ai_bull": [
        ("alphaops_vnext_score", 0.30),
        ("score", 0.18),
        ("mom_12m", 0.14),
        ("breakout_setup_quality_score", 0.12),
        ("quality_compounder_lane_score", 0.10),
        ("selection_confirmation_score", 0.08),
        ("oneil_leadership_score", 0.08),
    ],
    "2022_bear": [
        ("quality_compounder_lane_score", 0.22),
        ("price_above_ma200", 0.14),
        ("selection_confirmation_score", 0.12),
        ("evidence_fusion_score", 0.10),
        ("market_leader_lane_score", 0.10),
        ("alphaops_vnext_score", 0.10),
        ("risk_penalty", -0.12),
        ("atr14_pct", -0.10),
        ("live_event_risk_score", -0.10),
    ],
    "2023_2024_ai_bull": [
        ("alphaops_vnext_score", 0.24),
        ("theme_leadership_score", 0.18),
        ("etf_theme_leadership_score", 0.14),
        ("evidence_fusion_score", 0.12),
        ("rs_semis_3m", 0.10),
        ("rs_benchmark_3m", 0.08),
        ("h6_dynamic_leader_score", 0.08),
        ("breakout_setup_quality_score", 0.06),
    ],
    "2025_plus": [
        ("alphaops_vnext_score", 0.22),
        ("h6_dynamic_leader_score", 0.16),
        ("market_leader_lane_score", 0.14),
        ("mom_6m", 0.12),
        ("rs_benchmark_3m", 0.10),
        ("evidence_fusion_score", 0.10),
        ("selection_confirmation_score", 0.08),
        ("breakout_setup_quality_score", 0.08),
    ],
}
FALLBACK_FEATURES = ["alphaops_vnext_score", "score", "concentrated_score", "period_forward_return"]
OUTPUT_COLUMNS_FIRST = [
    "rebalance_date",
    "ticker",
    "Name",
    "sector",
    "industry_group",
    "weight",
    "target_weight",
    "portfolio_kind",
    "variant_id",
    "target_n",
    "target_stock_names",
    "weighting_mode",
    "era_bucket",
    "era_aware_score",
    "era_aware_rank",
    "era_feature_count",
    "selection_reason",
    "operating_target_source",
    "production_policy",
    "production_activation_allowed",
    "sidecar_only",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def assign_era(date_value: Any) -> str | None:
    ts = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(ts):
        return None
    for name, start, end in ERA_BUCKETS:
        if pd.Timestamp(start) <= ts <= pd.Timestamp(end):
            return name
    return None


def clean_ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text.replace(".", "-")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def candidate_book_path(args: argparse.Namespace) -> tuple[Path, str]:
    if args.candidate_book:
        return repo_path(args.candidate_book), "explicit"
    latest = repo_path(args.latest_run)
    candidates = [
        (latest / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv", "sec_enriched"),
        (latest / "reports" / "candidate_replay_book.csv", "candidate_replay_book"),
        (latest / "scored_latest.csv", "scored_latest"),
    ]
    for path, label in candidates:
        if path.exists():
            return path, label
    return candidates[0][0], "missing"


def read_candidates(args: argparse.Namespace) -> tuple[pd.DataFrame, Path, str]:
    path, source = candidate_book_path(args)
    if not path.exists():
        return pd.DataFrame(), path, source
    frame = pd.read_csv(path, low_memory=False)
    return frame, path, source


def usable_candidates(frame: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns or "rebalance_date" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    out["ticker"] = out["ticker"].map(clean_ticker)
    out = out.dropna(subset=["rebalance_date"])
    out = out[(out["ticker"] != "") & (~out["ticker"].isin(CASH_TICKERS))].copy()
    if "pit_evidence_blocked" in out.columns:
        blocked = out["pit_evidence_blocked"].astype(str).str.lower().isin({"true", "1", "yes"})
        out = out[~blocked].copy()
    if args.min_dollar_volume > 0 and "dollar_vol_20d" in out.columns:
        out = out[pd.to_numeric(out["dollar_vol_20d"], errors="coerce").fillna(0.0) >= float(args.min_dollar_volume)].copy()
    out["era_bucket"] = out["rebalance_date"].map(assign_era)
    return out[out["era_bucket"].notna()].copy()


def feature_rank_score(month: pd.DataFrame, feature: str, weight: float) -> pd.Series:
    values = pd.to_numeric(month.get(feature, pd.Series(index=month.index, dtype=float)), errors="coerce")
    if values.notna().sum() < 2 or values.nunique(dropna=True) < 2:
        return pd.Series(0.0, index=month.index)
    ranks = values.rank(pct=True, method="average").fillna(0.5)
    if weight >= 0:
        return ranks * abs(float(weight))
    return (1.0 - ranks) * abs(float(weight))


def score_candidates(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    scored_parts: list[pd.DataFrame] = []
    factor_rows: list[dict[str, Any]] = []
    for dt, month in frame.groupby("rebalance_date", sort=True):
        era = str(month["era_bucket"].iloc[0])
        weights = [(feature, weight) for feature, weight in ERA_FEATURE_WEIGHTS.get(era, []) if feature in month.columns]
        if not weights:
            weights = [(feature, 1.0 / max(len(FALLBACK_FEATURES), 1)) for feature in FALLBACK_FEATURES if feature in month.columns]
        work = month.copy()
        score = pd.Series(0.0, index=work.index)
        for feature, weight in weights:
            score = score.add(feature_rank_score(work, feature, weight), fill_value=0.0)
            factor_rows.append(
                {
                    "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                    "era_bucket": era,
                    "feature": feature,
                    "weight": float(weight),
                    "direction": "high_is_better" if weight >= 0 else "low_is_better",
                    "available": True,
                }
            )
        if score.max() > score.min():
            work["era_aware_score"] = (score - score.min()) / max(score.max() - score.min(), 1e-12)
        else:
            work["era_aware_score"] = score
        work["era_feature_count"] = len(weights)
        work["era_aware_rank"] = work["era_aware_score"].rank(ascending=False, method="first")
        scored_parts.append(work)
    scored = pd.concat(scored_parts, ignore_index=True) if scored_parts else pd.DataFrame()
    return scored, pd.DataFrame(factor_rows)


def capped_score_weights(selected: pd.DataFrame, gross_exposure: float, single_cap: float, score_power: float) -> list[float]:
    if selected.empty:
        return []
    scores = pd.to_numeric(selected["era_aware_score"], errors="coerce").fillna(0.0)
    raw = (scores - float(scores.min()) + 0.25).clip(lower=1e-6) ** max(float(score_power), 0.1)
    weights = (raw / max(float(raw.sum()), 1e-12) * max(0.0, min(float(gross_exposure), 1.0))).clip(upper=float(single_cap))
    out = [float(x) for x in weights]
    target = max(0.0, min(float(gross_exposure), 1.0))
    for _ in range(len(out) + 3):
        residual = target - sum(out)
        if residual <= 1e-10:
            break
        rooms = [max(0.0, float(single_cap) - value) for value in out]
        room_total = sum(rooms)
        if room_total <= 1e-12:
            break
        for idx, room in enumerate(rooms):
            out[idx] += min(room, residual * room / room_total)
    return out


def era_cash_target(era: str, portfolio_kind: str) -> float:
    if era == "2022_bear":
        return 0.20 if portfolio_kind == "main" else 0.25
    if portfolio_kind == "concentrated":
        return 0.05
    return 0.03


def build_book(
    scored: pd.DataFrame,
    *,
    portfolio_kind: str,
    target_n: int,
    single_cap: float,
    score_power: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    variant_id = f"era_aware_{portfolio_kind}_N{int(target_n)}"
    for dt, month in scored.groupby("rebalance_date", sort=True):
        era = str(month["era_bucket"].iloc[0])
        ordered = month.sort_values(["era_aware_score", "ticker"], ascending=[False, True]).copy()
        selected = ordered.head(int(target_n)).copy()
        cash_target = era_cash_target(era, portfolio_kind)
        weights = capped_score_weights(selected, 1.0 - cash_target, single_cap, score_power)
        selected_tickers = set(selected["ticker"].astype(str))
        for _, rec in ordered.iterrows():
            audit_rows.append(
                {
                    "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                    "ticker": rec.get("ticker"),
                    "portfolio_kind": portfolio_kind,
                    "variant_id": variant_id,
                    "era_bucket": era,
                    "era_aware_score": safe_float(rec.get("era_aware_score")),
                    "era_aware_rank": int(safe_float(rec.get("era_aware_rank"), 0)),
                    "selected": str(rec.get("ticker")) in selected_tickers,
                }
            )
        for idx, (_, rec) in enumerate(selected.iterrows()):
            weight = weights[idx] if idx < len(weights) else 0.0
            if weight <= 1e-12:
                continue
            row = rec.to_dict()
            row.update(
                {
                    "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                    "ticker": clean_ticker(rec.get("ticker")),
                    "weight": float(weight),
                    "target_weight": float(weight),
                    "portfolio_kind": portfolio_kind,
                    "variant_id": variant_id,
                    "target_n": int(target_n),
                    "target_stock_names": int(target_n),
                    "weighting_mode": "era_aware_score_power",
                    "selection_reason": f"era_aware_score:{era}",
                    "operating_target_source": "era_aware_scoring_challenger",
                    "production_policy": "review_only_era_aware_challenger",
                    "production_activation_allowed": False,
                    "sidecar_only": True,
                    "current_holdings_source": "era_aware_review_target_book",
                }
            )
            rows.append(row)
        cash_weight = max(0.0, 1.0 - sum(weights))
        if cash_weight > 1e-10:
            rows.append(
                {
                    "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                    "ticker": "CASH",
                    "Name": "Cash",
                    "sector": "Cash",
                    "industry_group": "Cash",
                    "weight": float(cash_weight),
                    "target_weight": float(cash_weight),
                    "portfolio_kind": portfolio_kind,
                    "variant_id": variant_id,
                    "target_n": int(target_n),
                    "target_stock_names": int(target_n),
                    "weighting_mode": "era_aware_score_power",
                    "era_bucket": era,
                    "era_aware_score": 0.0,
                    "era_aware_rank": 999999,
                    "era_feature_count": 0,
                    "selection_reason": f"cash_residual:{era}",
                    "primary_lane": "CASH",
                    "operating_target_source": "era_aware_scoring_challenger",
                    "production_policy": "review_only_era_aware_challenger",
                    "production_activation_allowed": False,
                    "sidecar_only": True,
                    "current_holdings_source": "era_aware_review_target_book",
                }
            )
    book = pd.DataFrame(rows)
    if not book.empty:
        first = [c for c in OUTPUT_COLUMNS_FIRST if c in book.columns]
        rest = [c for c in book.columns if c not in first]
        book = book[first + rest].sort_values(["rebalance_date", "portfolio_kind", "weight"], ascending=[True, True, False])
    return book.reset_index(drop=True), pd.DataFrame(audit_rows)


def maybe_run_broker_replay(args: argparse.Namespace, output_dir: Path, books: dict[str, Path]) -> dict[str, Any]:
    if not bool(args.run_broker_replay):
        return {"requested": False, "status": "skipped"}
    price_cache = repo_path(args.price_cache)
    if not price_cache.exists():
        return {"requested": True, "status": "skipped", "reason": "missing_price_cache", "price_cache": str(price_cache)}
    out: dict[str, Any] = {"requested": True, "status": "completed", "portfolios": {}}
    for portfolio_kind, path in books.items():
        book = pd.read_csv(path, low_memory=False) if path.exists() else pd.DataFrame()
        if book.get("rebalance_date", pd.Series(dtype=str)).nunique() < 2:
            out["portfolios"][portfolio_kind] = {"status": "skipped", "reason": "insufficient_rebalance_history"}
            continue
        metrics = broker_replay(
            target_book=path,
            price_cache=price_cache,
            output_dir=output_dir / "broker_replay" / portfolio_kind,
            portfolio_kind=portfolio_kind,
            fill_mode="next_close",
            cost_bps=float(args.cost_bps),
            max_fill_lag_days=int(args.max_fill_lag_days),
            disable_concentrated_champion_filter=portfolio_kind == "concentrated",
        )
        out["portfolios"][portfolio_kind] = metrics
        if metrics.get("status") != "completed":
            out["status"] = "partial"
    return out


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Era-Aware Scoring Challenger",
        "",
        "- sidecar_only: `true`",
        "- production_activation_allowed: `false`",
        f"- status: `{summary.get('status')}`",
        f"- candidate_book: `{summary.get('candidate_book')}`",
        f"- candidate_rows: `{summary.get('candidate_row_count', 0)}`",
        f"- scored_rows: `{summary.get('scored_row_count', 0)}`",
        f"- rebalance_dates: `{summary.get('rebalance_date_count', 0)}`",
        "",
        "## Outputs",
        "",
        "| Portfolio | Target Book | Rows |",
        "| --- | --- | ---: |",
    ]
    for portfolio, meta in sorted(summary.get("target_books", {}).items()):
        lines.append(f"| {portfolio} | `{meta.get('path')}` | {int(meta.get('rows', 0))} |")
    lines.extend(
        [
            "",
            "The generated books are review-only challengers. They are broker-replayable, but they do not replace `outputs/reports/operating_*_target_book.csv`.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw, source_path, source_mode = read_candidates(args)
    usable = usable_candidates(raw, args)
    if usable.empty:
        summary = {
            "schema_version": "era-aware-scoring-challenger-v1",
            "status": "blocked",
            "reason": "missing_or_invalid_candidate_book",
            "sidecar_only": True,
            "production_activation_allowed": False,
            "production_mutation_allowed": False,
            "candidate_book": str(source_path),
            "candidate_source_mode": source_mode,
            "candidate_row_count": int(len(raw)),
            "scored_row_count": 0,
            "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        write_json(output_dir / "summary.json", summary)
        write_csv(output_dir / "selection_audit.csv", pd.DataFrame())
        (output_dir / "summary.md").write_text(render_report(summary), encoding="utf-8")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return summary

    scored, factors = score_candidates(usable)
    main_book, main_audit = build_book(
        scored,
        portfolio_kind="main",
        target_n=int(args.main_target_n),
        single_cap=float(args.main_single_cap),
        score_power=float(args.score_power),
    )
    concentrated_book, concentrated_audit = build_book(
        scored,
        portfolio_kind="concentrated",
        target_n=int(args.concentrated_target_n),
        single_cap=float(args.concentrated_single_cap),
        score_power=float(args.score_power),
    )
    main_path = output_dir / "era_aware_main_target_book.csv"
    concentrated_path = output_dir / "era_aware_concentrated_target_book.csv"
    write_csv(main_path, main_book)
    write_csv(concentrated_path, concentrated_book)
    write_csv(output_dir / "main_target_book.csv", main_book)
    write_csv(output_dir / "concentrated_target_book.csv", concentrated_book)
    write_csv(output_dir / "era_factor_weights.csv", factors)
    write_csv(output_dir / "selection_audit.csv", pd.concat([main_audit, concentrated_audit], ignore_index=True))

    replay_summary = maybe_run_broker_replay(args, output_dir, {"main": main_path, "concentrated": concentrated_path})
    summary = {
        "schema_version": "era-aware-scoring-challenger-v1",
        "status": "completed",
        "sidecar_only": True,
        "production_activation_allowed": False,
        "production_mutation_allowed": False,
        "candidate_book": str(source_path),
        "candidate_source_mode": source_mode,
        "candidate_row_count": int(len(raw)),
        "scored_row_count": int(len(scored)),
        "rebalance_date_count": int(scored["rebalance_date"].nunique()),
        "era_buckets": [{"name": n, "start": s, "end": e} for n, s, e in ERA_BUCKETS],
        "target_books": {
            "main": {"path": str(main_path), "rows": int(len(main_book)), "target_n": int(args.main_target_n)},
            "concentrated": {
                "path": str(concentrated_path),
                "rows": int(len(concentrated_book)),
                "target_n": int(args.concentrated_target_n),
            },
        },
        "broker_replay": replay_summary,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "summary.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--candidate-book", default="")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/era_aware_scoring_challenger")
    parser.add_argument("--main-target-n", type=int, default=15)
    parser.add_argument("--concentrated-target-n", type=int, default=5)
    parser.add_argument("--main-single-cap", type=float, default=0.12)
    parser.add_argument("--concentrated-single-cap", type=float, default=0.30)
    parser.add_argument("--score-power", type=float, default=2.0)
    parser.add_argument("--min-dollar-volume", type=float, default=0.0)
    parser.add_argument("--run-broker-replay", action="store_true")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = run(parse_args(argv))
    return 0 if summary.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
