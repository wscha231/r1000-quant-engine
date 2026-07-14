#!/usr/bin/env python3
"""Audit current holdings against the refreshed Run287 research ranking.

This is deliberately not a selector.  It joins the exact-close scored snapshot
to already marked paper accounts and the held-security risk watch, then emits a
review packet.  It never assigns target weights, generates orders, mutates a
book, or treats a partial decision frame as executable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCORED = "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv"
DEFAULT_RISK = "outputs/run287_holding_risk_watch_20260714_close_20260713/holding_risk_watch.csv"
DEFAULT_MAIN_ACCOUNT = (
    "outputs/run287_temporal_extension_20260713_close_20260710_attempt02_commit_4323ce11/"
    "replays/main/account_state_latest.json"
)
DEFAULT_CONCENTRATED_ACCOUNT = (
    "outputs/run287_temporal_extension_20260713_close_20260710_attempt02_commit_4323ce11/"
    "replays/concentrated/account_state_latest.json"
)
DEFAULT_OUTPUT = "outputs/run287_scored_latest_selector_diff_20260714_close_20260713"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def require_columns(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"BLOCKED_SELECTOR_DIFF:missing_{label}_columns:{sorted(missing)}")


def review_bucket(row: pd.Series, target_n: int) -> str:
    if not bool(row["research_eligible"]):
        return "HELD_INELIGIBLE_REVIEW"
    if row["risk_state"] == "ALERT":
        return "HELD_ALERT_REVIEW"
    if pd.notna(row["research_score_rank"]) and float(row["research_score_rank"]) > target_n:
        return "HELD_OUTSIDE_TOP_N_REVIEW"
    if row["risk_state"] == "WATCH":
        return "HELD_WATCH_REVIEW"
    return "HELD_MONITOR"


def audit(
    *,
    scored_path: str | Path,
    risk_path: str | Path,
    account_paths: dict[str, str | Path],
    output_dir: str | Path,
    as_of_date: str,
    challenger_rank_ceiling: int = 30,
) -> dict[str, Any]:
    scored_file = repo_path(scored_path)
    risk_file = repo_path(risk_path)
    output = repo_path(output_dir)
    accounts_files = {name: repo_path(path) for name, path in account_paths.items()}

    scored = pd.read_csv(scored_file, low_memory=False)
    risk = pd.read_csv(risk_file, low_memory=False)
    require_columns(
        scored,
        {
            "ticker",
            "score",
            "research_score_rank",
            "research_eligible_after_quarantine",
            "technical_available_after_close",
            "score_available_from",
            "decision_feature_complete",
            "decision_ranking_allowed",
        },
        "scored",
    )
    require_columns(
        risk,
        {
            "as_of_date",
            "portfolio_kind",
            "ticker",
            "shares",
            "current_weight",
            "risk_state",
            "advisory_action",
            "reason_codes",
            "portfolio_return_contribution_1d",
        },
        "risk",
    )
    if scored.empty or risk.empty:
        raise ValueError("BLOCKED_SELECTOR_DIFF:empty_input")

    scored["ticker"] = scored["ticker"].astype(str).str.upper().str.strip()
    risk["ticker"] = risk["ticker"].astype(str).str.upper().str.strip()
    if scored["ticker"].duplicated().any():
        raise ValueError("BLOCKED_SELECTOR_DIFF:duplicate_scored_ticker")
    if risk[["portfolio_kind", "ticker"]].duplicated().any():
        raise ValueError("BLOCKED_SELECTOR_DIFF:duplicate_risk_holding")
    if set(risk["as_of_date"].astype(str)) != {as_of_date}:
        raise ValueError("BLOCKED_SELECTOR_DIFF:risk_asof_mismatch")
    technical_dates = set(scored["technical_available_after_close"].dropna().astype(str))
    if technical_dates != {as_of_date}:
        raise ValueError(f"BLOCKED_SELECTOR_DIFF:technical_asof_mismatch:{sorted(technical_dates)}")
    score_times = pd.to_datetime(scored["score_available_from"], utc=True, errors="coerce")
    if score_times.isna().any():
        raise ValueError("BLOCKED_SELECTOR_DIFF:invalid_score_available_from")

    scored["research_eligible"] = as_bool(scored["research_eligible_after_quarantine"])
    scored["decision_feature_complete_bool"] = as_bool(scored["decision_feature_complete"])
    scored["decision_ranking_allowed_bool"] = as_bool(scored["decision_ranking_allowed"])
    scored["research_score_rank"] = pd.to_numeric(scored["research_score_rank"], errors="coerce")
    scored["score"] = pd.to_numeric(scored["score"], errors="coerce")
    ranked = scored[scored["research_score_rank"].notna()].copy()
    if ranked.empty or ranked["research_score_rank"].duplicated().any():
        raise ValueError("BLOCKED_SELECTOR_DIFF:invalid_research_ranks")
    expected_ranks = list(range(1, len(ranked) + 1))
    actual_ranks = sorted(ranked["research_score_rank"].astype(int).tolist())
    if actual_ranks != expected_ranks:
        raise ValueError("BLOCKED_SELECTOR_DIFF:noncontiguous_research_ranks")
    if not np.isfinite(ranked["score"]).all():
        raise ValueError("BLOCKED_SELECTOR_DIFF:nonfinite_ranked_score")

    score_columns = [
        "ticker",
        "score",
        "research_score_rank",
        "research_eligible",
        "decision_feature_complete_bool",
        "decision_ranking_allowed_bool",
    ]
    optional_score_columns = [
        "portfolio_candidate_gate_label",
        "portfolio_sleeve_label",
        "sector",
        "industry",
        "ret_1d",
        "mom_1m",
        "mom_3m",
        "atr14_pct",
        "current_price_live",
    ]
    score_columns += [name for name in optional_score_columns if name in scored.columns]
    score_view = scored[score_columns].copy()

    holding_frames: list[pd.DataFrame] = []
    portfolio_summaries: dict[str, Any] = {}
    account_hashes: dict[str, str] = {}
    for portfolio, account_file in account_paths.items():
        account_path = accounts_files[portfolio]
        account = read_json(account_path)
        if str(account.get("portfolio_kind", "")) != portfolio:
            raise ValueError(f"BLOCKED_SELECTOR_DIFF:account_portfolio_mismatch:{portfolio}")
        positions = pd.DataFrame(account.get("positions", []))
        require_columns(positions, {"ticker", "shares"}, f"{portfolio}_positions")
        positions["ticker"] = positions["ticker"].astype(str).str.upper().str.strip()
        if positions["ticker"].duplicated().any():
            raise ValueError(f"BLOCKED_SELECTOR_DIFF:duplicate_account_holding:{portfolio}")

        portfolio_risk = risk[risk["portfolio_kind"] == portfolio].copy()
        if set(positions["ticker"]) != set(portfolio_risk["ticker"]):
            raise ValueError(f"BLOCKED_SELECTOR_DIFF:account_risk_holding_mismatch:{portfolio}")
        missing_scores = sorted(set(positions["ticker"]) - set(scored["ticker"]))
        if missing_scores:
            raise ValueError(f"BLOCKED_SELECTOR_DIFF:held_ticker_missing_score:{portfolio}:{missing_scores}")

        target_n = int(len(positions))
        joined = portfolio_risk.merge(score_view, on="ticker", how="left", validate="one_to_one")
        joined["target_n_reference"] = target_n
        joined["review_bucket"] = joined.apply(review_bucket, axis=1, target_n=target_n)
        joined["trade_instruction"] = "NONE_REVIEW_ONLY"
        joined["execution_allowed"] = False
        joined["target_weight_changed"] = False
        joined["portfolio_kind"] = portfolio
        holding_frames.append(joined)

        current_stock_weight = float(pd.to_numeric(joined["current_weight"], errors="raise").sum())
        current_cash_weight = 1.0 - current_stock_weight
        bucket_counts = joined["review_bucket"].value_counts().to_dict()
        portfolio_summaries[portfolio] = {
            "account_as_of_date": str(account.get("as_of_date", "")),
            "held_count": target_n,
            "marked_stock_weight": current_stock_weight,
            "marked_cash_weight": current_cash_weight,
            "risk_state_counts": joined["risk_state"].value_counts().to_dict(),
            "review_bucket_counts": bucket_counts,
            "ranked_held_count": int(joined["research_score_rank"].notna().sum()),
            "ineligible_held_count": int((~joined["research_eligible"]).sum()),
            "held_inside_top_n_count": int(
                (joined["research_score_rank"].notna() & (joined["research_score_rank"] <= target_n)).sum()
            ),
        }
        account_hashes[f"{portfolio}_account_sha256"] = sha256_file(account_path)

    holdings = pd.concat(holding_frames, ignore_index=True)
    held_by_portfolio = {
        portfolio: set(group["ticker"]) for portfolio, group in holdings.groupby("portfolio_kind")
    }
    held_anywhere = set(holdings["ticker"])

    challenger_rows: list[pd.DataFrame] = []
    pair_rows: list[dict[str, Any]] = []
    top_ranked = ranked[ranked["research_score_rank"] <= challenger_rank_ceiling].sort_values(
        "research_score_rank"
    )
    for portfolio, held_tickers in held_by_portfolio.items():
        challengers = top_ranked[~top_ranked["ticker"].isin(held_tickers)][score_columns].copy()
        challengers.insert(0, "portfolio_kind", portfolio)
        challengers["held_in_other_portfolio"] = challengers["ticker"].isin(held_anywhere - held_tickers)
        challengers["review_label"] = "UNHELD_TOP_RANK_REVIEW_ONLY"
        challengers["trade_instruction"] = "NONE_REVIEW_ONLY"
        challengers["execution_allowed"] = False
        challenger_rows.append(challengers)

        vulnerable = holdings[holdings["portfolio_kind"] == portfolio].copy()
        vulnerable = vulnerable[
            (~vulnerable["research_eligible"])
            | vulnerable["research_score_rank"].isna()
            | (vulnerable["research_score_rank"] > int(len(vulnerable)))
        ].copy()
        vulnerable["sort_ineligible"] = (~vulnerable["research_eligible"]).astype(int)
        vulnerable["sort_rank"] = vulnerable["research_score_rank"].fillna(1_000_000)
        vulnerable = vulnerable.sort_values(
            ["sort_ineligible", "sort_rank", "current_weight"], ascending=[False, False, False]
        )
        for (_, challenger), (_, incumbent) in zip(challengers.iterrows(), vulnerable.iterrows()):
            incumbent_rank = incumbent["research_score_rank"]
            pair_rows.append(
                {
                    "portfolio_kind": portfolio,
                    "challenger_ticker": challenger["ticker"],
                    "challenger_rank": int(challenger["research_score_rank"]),
                    "challenger_score": float(challenger["score"]),
                    "incumbent_ticker": incumbent["ticker"],
                    "incumbent_rank": "" if pd.isna(incumbent_rank) else int(incumbent_rank),
                    "incumbent_score": float(incumbent["score"]),
                    "incumbent_research_eligible": bool(incumbent["research_eligible"]),
                    "incumbent_risk_state": incumbent["risk_state"],
                    "incumbent_current_weight": float(incumbent["current_weight"]),
                    "review_question": "CHECK_REGISTERED_SELECTOR_AND_TRANSITION_COSTS",
                    "trade_instruction": "NONE_REVIEW_ONLY",
                    "execution_allowed": False,
                    "target_weight_changed": False,
                }
            )

    challengers = pd.concat(challenger_rows, ignore_index=True)
    pairs = pd.DataFrame(pair_rows)
    output.mkdir(parents=True, exist_ok=True)
    holdings_path = output / "held_score_risk_audit.csv"
    challengers_path = output / "top_rank_challenger_review.csv"
    pairs_path = output / "rank_gap_review_pairs.csv"
    holdings.sort_values(["portfolio_kind", "review_bucket", "research_score_rank"], na_position="last").to_csv(
        holdings_path, index=False
    )
    challengers.sort_values(["portfolio_kind", "research_score_rank"]).to_csv(challengers_path, index=False)
    pairs.to_csv(pairs_path, index=False)

    feature_complete_count = int(scored["decision_feature_complete_bool"].sum())
    decision_ranking_allowed_count = int(scored["decision_ranking_allowed_bool"].sum())
    summary = {
        "schema_version": "run287-scored-latest-selector-diff-v1",
        "status": "READY_DIAGNOSTIC_SELECTOR_DIFF_REVIEW",
        "as_of_date": as_of_date,
        "score_row_count": int(len(scored)),
        "research_ranked_count": int(len(ranked)),
        "score_available_from_min": score_times.min().isoformat(),
        "score_available_from_max": score_times.max().isoformat(),
        "decision_feature_complete_count": feature_complete_count,
        "decision_ranking_allowed_count": decision_ranking_allowed_count,
        "registered_selector_allowed": bool(feature_complete_count == len(scored) and decision_ranking_allowed_count > 0),
        "registered_selector_executed": False,
        "research_rank_only": True,
        "same_close_execution_allowed": False,
        "next_close_only_if_future_gates_pass": True,
        "target_books_mutated": False,
        "orders_generated": False,
        "cash_policy_changed": False,
        "historical_cagr_mdd_evidence_changed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "challenger_rank_ceiling": challenger_rank_ceiling,
        "top_rank_challenger_rows": int(len(challengers)),
        "rank_gap_review_pair_count": int(len(pairs)),
        "portfolio_summaries": portfolio_summaries,
        "blocking_reasons": [
            "decision_feature_frame_incomplete",
            "research_rank_is_not_registered_selector_output",
            f"score_observed_after_{as_of_date}_close_next_close_only",
            "transition_cost_and_policy_controls_not_run",
        ],
        "recommended_next_step": (
            "build and validate a decision-complete exact-close feature frame, then rerun the pinned "
            "registered selector as advisory-only before any fixed-book or portfolio A/B"
        ),
        "input_hashes": {
            "scored_latest_sha256": sha256_file(scored_file),
            "holding_risk_watch_sha256": sha256_file(risk_file),
            **account_hashes,
        },
        "output_hashes": {
            "held_score_risk_audit_sha256": sha256_file(holdings_path),
            "top_rank_challenger_review_sha256": sha256_file(challengers_path),
            "rank_gap_review_pairs_sha256": sha256_file(pairs_path),
        },
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report_lines = [
        "# Run287 scored-latest selector diff",
        "",
        f"- as-of close: `{as_of_date}`",
        f"- research ranked: `{len(ranked)}/{len(scored)}`",
        f"- decision-complete rows: `{feature_complete_count}/{len(scored)}`",
        f"- registered selector executed: `false`",
        f"- rank-gap review pairs: `{len(pairs)}`",
        "",
        "This packet is diagnostic only. It contains no target weights or order instructions.",
        "The 2026-07-13 score was observed after that close and can only enter a future next-close decision after all gates pass.",
    ]
    (output / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", default=DEFAULT_SCORED)
    parser.add_argument("--risk", default=DEFAULT_RISK)
    parser.add_argument("--main-account", default=DEFAULT_MAIN_ACCOUNT)
    parser.add_argument("--concentrated-account", default=DEFAULT_CONCENTRATED_ACCOUNT)
    parser.add_argument("--as-of-date", default="2026-07-13")
    parser.add_argument("--challenger-rank-ceiling", type=int, default=30)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = audit(
        scored_path=args.scored,
        risk_path=args.risk,
        account_paths={"main": args.main_account, "concentrated": args.concentrated_account},
        output_dir=args.output_dir,
        as_of_date=args.as_of_date,
        challenger_rank_ceiling=args.challenger_rank_ceiling,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
