#!/usr/bin/env python3
"""Research-only broker A/B for run287 multi-source fusion scores.

This tool bridges the multi-source source screen to fixed-book broker evidence:
it recomputes decision-time fusion scores, joins them onto official run287
target books, and runs default-off top-quintile tilt A/B through the existing
broker-ledger replay harness. It does not dispatch a fullrun, add a policy
hook, tune thresholds, or mutate production state.
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

import tools.run_run287_profitability_broker_ab as broker_ab  # noqa: E402
from tools.alphaops_governance import (  # noqa: E402
    measurement_contract_acceptance_blockers,
    measurement_contract_caveat_fields,
)
from tools.run_run287_multisource_fusion_screen import (  # noqa: E402
    DEFAULT_13F_PATH,
    DEFAULT_CANDIDATE_BOOK,
    DEFAULT_FORM4_PATH,
    DEFAULT_MANAGER_UNIVERSE,
    add_source_scores,
    build_13f_source_events,
    build_form4_source_events,
    clean_ticker,
    prepare_candidate_book,
    read_candidate_book,
)

SCHEMA_VERSION = "run287-multisource-fusion-broker-ab-v1"
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/run287_multisource_fusion_broker_ab"
DEFAULT_PRICE_CACHE = "H:/codex/tmp_r1000_grossfloor_20260625/outputs/run287_price_cache_full_candidate/cache_prices"
DEFAULT_CASH_RATE_PATH = "H:/codex/tmp_r1000_grossfloor_20260625/cache_macro/fred_dgs3mo_DGS3MO.parquet"
DEFAULT_REPLAY_END_DATE = "2026-07-02"
DEFAULT_PARITY_SUMMARY = "outputs/run287_parity/summary.json"
DEFAULT_SURVIVORSHIP_SUMMARY = "outputs/run287_survivorship/summary.json"
DEFAULT_SIGNAL = "growth_confirmation_score"
JOIN_COLUMNS = [
    "w4_form4_score",
    "w4_13f_score",
    "w4_combined_score",
    "w4_consensus_score",
    "w4_sec_score",
    "financial_statement_proxy_score",
    "technical_momentum_score",
    "macro_regime_score",
    "risk_control_score",
    "all_source_equal_score",
    "growth_confirmation_score",
    "drawdown_aware_fusion_score",
    "three_plus_sleeve_consensus_score",
    "positive_sleeve_count",
    "negative_sleeve_count",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def target_cagr_for_portfolio(portfolio_kind: str) -> float:
    return 0.50 if str(portfolio_kind).lower() == "concentrated" else 0.35


def build_fusion_lookup(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    candidate_path = repo_path(args.candidate_book)
    raw = read_candidate_book(candidate_path)
    if raw.empty:
        raise FileNotFoundError(f"candidate book missing or empty: {candidate_path}")
    candidate = prepare_candidate_book(raw, args.oos_start)
    form4_events, form4_summary = build_form4_source_events(repo_path(args.form4_path), candidate)
    sec13f_events, sec13f_summary = build_13f_source_events(repo_path(args.sec13f_path), repo_path(args.manager_universe))
    enriched, source_columns_used = add_source_scores(candidate, form4_events, sec13f_events)
    enriched["rebalance_date"] = pd.to_datetime(enriched["rebalance_date"], errors="coerce").dt.date.astype(str)
    enriched["ticker"] = enriched["ticker"].map(clean_ticker)
    available = [col for col in JOIN_COLUMNS if col in enriched.columns]
    lookup = (
        enriched[["rebalance_date", "ticker", *available]]
        .dropna(subset=["rebalance_date", "ticker"])
        .groupby(["rebalance_date", "ticker"], as_index=False)
        .mean(numeric_only=True)
    )
    meta = {
        "candidate_book": str(candidate_path),
        "candidate_rows": int(len(candidate)),
        "fusion_lookup_rows": int(len(lookup)),
        "fusion_lookup_tickers": int(lookup["ticker"].nunique()),
        "source_columns_used": source_columns_used,
        "form4": form4_summary,
        "sec13f": sec13f_summary,
    }
    return lookup, meta


def enrich_target_book(target_book: Path, lookup: pd.DataFrame, output_path: Path) -> dict[str, Any]:
    book = pd.read_csv(target_book, low_memory=False)
    if "rebalance_date" not in book.columns or "ticker" not in book.columns:
        raise ValueError(f"target book must include rebalance_date and ticker: {target_book}")
    d = book.copy()
    d["_target_order"] = range(len(d))
    d["_target_rebalance_ts"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.date.astype(str)
    d["ticker"] = d["ticker"].map(clean_ticker)
    for col in JOIN_COLUMNS:
        if col in d.columns:
            d = d.drop(columns=[col])
    merged = d.merge(lookup, on=["rebalance_date", "ticker"], how="left")
    cash_mask = merged["ticker"].isin(broker_ab.CASH_TICKERS)
    exact_mask = ~cash_mask & merged[DEFAULT_SIGNAL].notna()
    merged["fusion_score_join_mode"] = ""
    merged["fusion_score_source_rebalance_date"] = ""
    merged.loc[exact_mask, "fusion_score_join_mode"] = "exact"
    merged.loc[exact_mask, "fusion_score_source_rebalance_date"] = merged.loc[exact_mask, "rebalance_date"]

    lookup_asof = lookup.copy()
    lookup_asof["_source_rebalance_ts"] = pd.to_datetime(lookup_asof["rebalance_date"], errors="coerce").dt.normalize()
    lookup_asof = lookup_asof[lookup_asof["_source_rebalance_ts"].notna()].sort_values(
        ["ticker", "_source_rebalance_ts"]
    )
    lookup_by_ticker = {ticker: group for ticker, group in lookup_asof.groupby("ticker", sort=False)}
    asof_count = 0
    missing_before_asof_mask = ~cash_mask & merged[DEFAULT_SIGNAL].isna()
    for idx, row in merged.loc[missing_before_asof_mask].iterrows():
        ticker_lookup = lookup_by_ticker.get(row["ticker"])
        target_ts = row["_target_rebalance_ts"]
        if ticker_lookup is None or pd.isna(target_ts):
            continue
        prior = ticker_lookup[ticker_lookup["_source_rebalance_ts"].le(target_ts)]
        if prior.empty:
            continue
        source = prior.iloc[-1]
        for col in JOIN_COLUMNS:
            if col in source.index:
                merged.at[idx, col] = source[col]
        merged.at[idx, "fusion_score_join_mode"] = "asof_prior"
        merged.at[idx, "fusion_score_source_rebalance_date"] = str(pd.Timestamp(source["_source_rebalance_ts"]).date())
        asof_count += 1

    missing_mask = ~cash_mask & merged[DEFAULT_SIGNAL].isna()
    non_cash_count = int((~cash_mask).sum())
    missing_non_cash_count = int(missing_mask.sum())
    for col in JOIN_COLUMNS:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)
    merged = merged.sort_values("_target_order").drop(columns=["_target_order", "_target_rebalance_ts"])
    write_csv(output_path, merged)
    return {
        "source_target_book": str(target_book),
        "enriched_target_book": str(output_path),
        "row_count": int(len(merged)),
        "non_cash_row_count": non_cash_count,
        "cash_row_count": int(cash_mask.sum()),
        "exact_score_rows": int(exact_mask.sum()),
        "asof_prior_score_rows": int(asof_count),
        "missing_fusion_score_non_cash_rows_before_asof": int(missing_before_asof_mask.sum()),
        "missing_fusion_score_non_cash_rows": missing_non_cash_count,
        "missing_fusion_score_non_cash_rate": float(missing_non_cash_count / non_cash_count) if non_cash_count else 0.0,
        "score_join_modes": merged["fusion_score_join_mode"].value_counts(dropna=False).to_dict(),
        "target_ticker_count": int(merged.loc[~cash_mask, "ticker"].nunique()),
    }


def run_signal_broker_ab(
    *,
    signal: str,
    portfolio_kind: str,
    enriched_target_book: Path,
    args: argparse.Namespace,
    output_root: Path,
) -> dict[str, Any]:
    class BrokerArgs:
        pass

    broker_args = BrokerArgs()
    broker_args.latest_run = str(repo_path(args.latest_run))
    broker_args.target_book = str(enriched_target_book)
    broker_args.portfolio_kind = portfolio_kind
    broker_args.price_cache = str(repo_path(args.price_cache))
    broker_args.signal = signal
    broker_args.output_dir = str(output_root / "signal_replays" / signal)
    broker_args.cost_bps = float(args.cost_bps)
    broker_args.max_fill_lag_days = int(args.max_fill_lag_days)
    broker_args.starting_capital = float(args.starting_capital)
    broker_args.single_cap = float(args.single_cap)
    broker_args.cash_carry_mode = str(args.cash_carry_mode)
    broker_args.cash_rate_source = str(args.cash_rate_source)
    broker_args.cash_rate_path = str(repo_path(args.cash_rate_path)) if args.cash_rate_path else ""
    broker_args.cash_rate_lag_days = int(args.cash_rate_lag_days)
    broker_args.cash_carry_haircut_bps = float(args.cash_carry_haircut_bps)
    broker_args.cash_carry_day_count = int(args.cash_carry_day_count)
    broker_args.replay_end_date = str(args.replay_end_date)
    broker_args.official_baseline_end_date = str(args.official_baseline_end_date)
    return broker_ab.run(broker_args)


def flatten_arm_rows(signal: str, portfolio_kind: str, replay_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    target_cagr = target_cagr_for_portfolio(portfolio_kind)
    for row in replay_payload.get("arms", []):
        out = dict(row)
        out["signal"] = signal
        out["portfolio_kind"] = portfolio_kind
        out["target_cagr"] = target_cagr
        out["target_contract_pass"] = bool(
            safe_float(out.get("cagr")) >= target_cagr and safe_float(out.get("max_dd")) >= -0.25
        )
        rows.append(out)
    return rows


def classify_overall(rows: list[dict[str, Any]], contract_blockers: list[str]) -> str:
    positive = [
        row
        for row in rows
        if row.get("ab_verdict") == "broker_ab_positive_requires_review" and bool(row.get("target_contract_pass"))
    ]
    edge_not_contract = [
        row
        for row in rows
        if row.get("ab_verdict") == "broker_ab_positive_requires_review" and not bool(row.get("target_contract_pass"))
    ]
    if not positive and not edge_not_contract:
        return "reject_no_broker_ab_candidate"
    if contract_blockers:
        return "broker_ab_positive_but_measurement_contract_blocks_acceptance" if positive else "edge_positive_but_contract_not_restored"
    return "broker_ab_positive_requires_human_review" if positive else "edge_positive_but_contract_not_restored"


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Run287 Multi-Source Fusion Broker A/B",
        "",
        f"- Status: `{payload['status']}`",
        f"- Decision label: `{payload['decision_label']}`",
        f"- Signals: `{', '.join(payload['signals'])}`",
        f"- Cash carry mode: `{payload['cash_carry_mode']}`",
        f"- Replay end date: `{payload['replay_end_date']}`",
        f"- Runner parity status: `{payload['runner_parity_status']}`",
        f"- Measurement acceptance allowed: `{payload['measurement_contract_acceptance_allowed']}`",
        "- No fullrun, hook, threshold tuning, production promotion, or live trading.",
        "",
        "## Score Join Coverage",
        "",
        "| Portfolio | Non-cash rows | Exact rows | As-of prior rows | Missing rows | Missing rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for portfolio, meta in payload.get("enriched_target_books", {}).items():
        lines.append(
            "| {portfolio} | {non_cash} | {exact} | {asof} | {missing} | {rate:.2%} |".format(
                portfolio=portfolio,
                non_cash=int(safe_float(meta.get("non_cash_row_count"))),
                exact=int(safe_float(meta.get("exact_score_rows"))),
                asof=int(safe_float(meta.get("asof_prior_score_rows"))),
                missing=int(safe_float(meta.get("missing_fusion_score_non_cash_rows"))),
                rate=safe_float(meta.get("missing_fusion_score_non_cash_rate")),
            )
        )
    lines.extend(
        [
            "",
            "- As-of prior rows use the latest ticker score available on or before the target rebalance date.",
            "- No missing non-cash scores remain after the as-of prior join.",
            "",
            "## Broker A/B",
            "",
        "| Portfolio | Signal | Arm | Verdict | CAGR | MaxDD | dCAGR pp | dMDD pp | Contract pass |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in payload["arm_rows"]:
        lines.append(
            "| {portfolio} | {signal} | {arm} | `{verdict}` | {cagr:.2%} | {mdd:.2%} | {dc:+.2f} | {dm:+.2f} | {passed} |".format(
                portfolio=row.get("portfolio_kind"),
                signal=row.get("signal"),
                arm=row.get("arm"),
                verdict=row.get("ab_verdict"),
                cagr=safe_float(row.get("cagr")),
                mdd=safe_float(row.get("max_dd")),
                dc=safe_float(row.get("delta_cagr_pp")),
                dm=safe_float(row.get("delta_max_dd_pp")),
                passed=row.get("target_contract_pass"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This is fixed-book broker-ledger evidence on enriched official run287 target books.",
            "- Selected ticker sets are preserved; the A/B shifts weight only among already-selected non-cash names.",
            f"- Measurement contract blockers: `{', '.join(payload.get('measurement_contract_acceptance_blockers', [])) or 'none'}`.",
            "- A positive arm remains review-only while runner parity is not exact and PIT membership is not clean.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    lookup, lookup_meta = build_fusion_lookup(args)
    enriched_meta: dict[str, Any] = {}
    replay_payloads: dict[str, Any] = {}
    arm_rows: list[dict[str, Any]] = []
    portfolios = [str(item).lower() for item in args.portfolio_kind]
    signals = [str(item) for item in args.signals]
    for portfolio_kind in portfolios:
        target_book = broker_ab.resolve_target_book(repo_path(args.latest_run), portfolio_kind, "")
        enriched_book_path = output_dir / "enriched_target_books" / f"{portfolio_kind}_target_book.csv"
        enriched_meta[portfolio_kind] = enrich_target_book(target_book, lookup, enriched_book_path)
        if safe_float(enriched_meta[portfolio_kind]["missing_fusion_score_non_cash_rate"]) > float(args.max_missing_score_rate):
            raise ValueError(f"too many missing fusion scores for {portfolio_kind}: {enriched_meta[portfolio_kind]}")
        for signal in signals:
            replay = run_signal_broker_ab(
                signal=signal,
                portfolio_kind=portfolio_kind,
                enriched_target_book=enriched_book_path,
                args=args,
                output_root=output_dir,
            )
            replay_payloads[f"{portfolio_kind}:{signal}"] = replay
            arm_rows.extend(flatten_arm_rows(signal, portfolio_kind, replay))

    caveats = measurement_contract_caveat_fields(
        parity_summary_path=repo_path(args.parity_summary),
        survivorship_summary_path=repo_path(args.survivorship_summary),
    )
    blockers = measurement_contract_acceptance_blockers(caveats)
    decision_label = classify_overall(arm_rows, blockers)
    measurement_contract_acceptance_allowed = decision_label == "broker_ab_positive_requires_human_review" and not blockers
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "decision_label": decision_label,
        "source_run_id": "28725350727",
        "latest_run": str(repo_path(args.latest_run)),
        "candidate_book": str(repo_path(args.candidate_book)),
        "price_cache": str(repo_path(args.price_cache)),
        "cash_rate_path": str(repo_path(args.cash_rate_path)) if args.cash_rate_path else "",
        "cash_carry_mode": str(args.cash_carry_mode),
        "replay_end_date": str(args.replay_end_date),
        "official_baseline_end_date": str(args.official_baseline_end_date),
        "signals": signals,
        "portfolios": portfolios,
        "fusion_lookup": lookup_meta,
        "enriched_target_books": enriched_meta,
        "arm_rows": arm_rows,
        "replay_payloads": replay_payloads,
        **caveats,
        "measurement_contract_acceptance_blockers": blockers,
        "measurement_contract_acceptance_allowed": measurement_contract_acceptance_allowed,
        "candidate_allowed": False,
        "next_action_allowed": "human_review_only_no_hook_no_fullrun" if arm_rows else "blocked_no_replay",
        "research_only": True,
        "fullrun_dispatched": False,
        "new_alpha_hook_added": False,
        "threshold_tuning_performed": False,
        "used_forward_return_in_ranking": False,
        "production_promotion_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
    }
    write_csv(output_dir / "arm_metrics.csv", pd.DataFrame(arm_rows))
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--form4-path", default=DEFAULT_FORM4_PATH)
    parser.add_argument("--sec13f-path", default=DEFAULT_13F_PATH)
    parser.add_argument("--manager-universe", default=DEFAULT_MANAGER_UNIVERSE)
    parser.add_argument("--portfolio-kind", nargs="+", choices=["main", "concentrated"], default=["main", "concentrated"])
    parser.add_argument("--signals", nargs="+", default=[DEFAULT_SIGNAL])
    parser.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--oos-start", default="2024-07-01")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--single-cap", type=float, default=0.30)
    parser.add_argument("--cash-carry-mode", choices=["none", "risk_free_rate"], default="risk_free_rate")
    parser.add_argument("--cash-rate-source", default="DGS3MO")
    parser.add_argument("--cash-rate-path", default=DEFAULT_CASH_RATE_PATH)
    parser.add_argument("--cash-rate-lag-days", type=int, default=1)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=50.0)
    parser.add_argument("--cash-carry-day-count", type=int, default=365)
    parser.add_argument("--replay-end-date", default=DEFAULT_REPLAY_END_DATE)
    parser.add_argument("--official-baseline-end-date", default=DEFAULT_REPLAY_END_DATE)
    parser.add_argument("--parity-summary", default=DEFAULT_PARITY_SUMMARY)
    parser.add_argument("--survivorship-summary", default=DEFAULT_SURVIVORSHIP_SUMMARY)
    parser.add_argument("--max-missing-score-rate", type=float, default=0.001)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
