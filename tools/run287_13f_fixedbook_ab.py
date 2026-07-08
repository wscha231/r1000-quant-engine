#!/usr/bin/env python3
"""One-pass 13F-confirmed fixed-book broker A/B for run287 Concentrated.

This tool consumes the PR #237 source packet and tests exactly one pure-13F
confirmation design. It reconstructs a replacement-quality hook-off book from
the official fixed book, then keeps only replacement-quality swaps whose added
ticker has an ex-ante `w4_13f_score > 0`.

It is research-only evidence. It does not dispatch a fullrun, add a production
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

from tools.run287_13f_pit_gate import audit_13f_pit  # noqa: E402
from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_NONE,
    CASH_CARRY_MODE_RISK_FREE,
    CashCarryConfig,
    replay,
)
from tools.run_run287_w4_form4_13f_source_screen import (  # noqa: E402
    DEFAULT_13F_PATH,
    DEFAULT_CANDIDATE_BOOK,
    DEFAULT_MANAGER_UNIVERSE,
    add_w4_scores,
    build_13f_source_events,
    clean_ticker,
    prepare_candidate_book,
    read_candidate_book,
)

SCHEMA_VERSION = "run287-13f-fixedbook-ab-v1"
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe"
DEFAULT_TARGET_BOOK = (
    "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe/"
    "alphaops_vnext/official_concentrated_target_book.csv"
)
DEFAULT_MISS_SET = "outputs/run287_conc_alpha_source_packet/miss_set_candidates.csv"
DEFAULT_SIGNAL_STATS = "outputs/run287_conc_alpha_source_packet/source_screen_signal_stats.csv"
DEFAULT_OUTPUT_DIR = "outputs/run287_13f_fixedbook_ab"
DEFAULT_PRICE_CACHE = "H:/codex/tmp_r1000_grossfloor_20260625/outputs/run287_price_cache_full_candidate/cache_prices"
DEFAULT_CASH_RATE_PATH = "H:/codex/tmp_r1000_grossfloor_20260625/cache_macro/fred_dgs3mo_DGS3MO.parquet"
DEFAULT_REPLAY_END_DATE = "2026-07-02"
DEFAULT_OOS_START = "2024-07-01"
DEFAULT_OOS2_START = "2023-01-01"
PURE_13F_SIGNAL = "w4_13f_score"


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


def norm_ticker(value: Any) -> str:
    return clean_ticker(value)


def norm_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).date().isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def build_w4_13f_lookup(
    *,
    candidate_book: Path,
    sec13f_path: Path,
    manager_universe: Path,
    oos_start: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = read_candidate_book(candidate_book)
    if raw.empty:
        raise FileNotFoundError(f"missing or empty candidate book: {candidate_book}")
    candidate = prepare_candidate_book(raw, oos_start)
    sec13f_events, sec13f_summary = build_13f_source_events(sec13f_path, manager_universe)
    empty_form4 = pd.DataFrame(columns=["ticker", "available_date", "score", "positive_event", "negative_event"])
    scored = add_w4_scores(candidate, empty_form4, sec13f_events)
    scored["rebalance_date"] = pd.to_datetime(scored["rebalance_date"], errors="coerce").dt.date.astype(str)
    scored["ticker"] = scored["ticker"].map(norm_ticker)
    lookup = (
        scored[["rebalance_date", "ticker", PURE_13F_SIGNAL]]
        .dropna(subset=["rebalance_date", "ticker"])
        .groupby(["rebalance_date", "ticker"], as_index=False)
        .mean(numeric_only=True)
    )
    return lookup, {
        "candidate_book": str(candidate_book),
        "candidate_rows": int(len(candidate)),
        "lookup_rows": int(len(lookup)),
        "lookup_tickers": int(lookup["ticker"].nunique()) if not lookup.empty else 0,
        "sec13f_summary": sec13f_summary,
        "signal": PURE_13F_SIGNAL,
        "signal_threshold": 0.0,
    }


def load_miss_set(path: Path, lookup: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"missing miss-set packet: {path}")
    miss = pd.read_csv(path, low_memory=False)
    required = {
        "rebalance_date",
        "ticker",
        "concentrated_replacement_quality_added_ticker",
        "concentrated_replacement_quality_removed_ticker",
    }
    missing = sorted(required - set(miss.columns))
    if missing:
        raise ValueError(f"miss-set missing required columns: {missing}")
    d = miss.copy()
    d["rebalance_date"] = d["rebalance_date"].map(norm_date)
    d["ticker"] = d["ticker"].map(norm_ticker)
    d["added_ticker"] = d["concentrated_replacement_quality_added_ticker"].map(norm_ticker)
    d["removed_ticker"] = d["concentrated_replacement_quality_removed_ticker"].map(norm_ticker)
    d["replacement_weight"] = pd.to_numeric(
        d.get("concentrated_replacement_quality_replacement_weight", pd.Series(index=d.index)), errors="coerce"
    )
    d["forward_return_audit_only"] = pd.to_numeric(d.get("period_forward_return"), errors="coerce")
    d["latest_13f_available_from_ts"] = pd.to_datetime(d.get("latest_13f_available_from"), errors="coerce", utc=True)
    d["latest_13f_available_from_date"] = d["latest_13f_available_from_ts"].dt.tz_convert(None).dt.normalize()
    d["decision_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d = d[d["rebalance_date"].ne("") & d["added_ticker"].ne("") & d["removed_ticker"].ne("")].copy()

    lookup_d = lookup.copy()
    lookup_d["rebalance_date"] = lookup_d["rebalance_date"].map(norm_date)
    lookup_d["ticker"] = lookup_d["ticker"].map(norm_ticker)
    d = d.merge(
        lookup_d.rename(columns={"ticker": "added_ticker"})[["rebalance_date", "added_ticker", PURE_13F_SIGNAL]],
        on=["rebalance_date", "added_ticker"],
        how="left",
    )
    d[PURE_13F_SIGNAL] = pd.to_numeric(d[PURE_13F_SIGNAL], errors="coerce").fillna(0.0)
    d["thirteen_f_confirmed"] = d[PURE_13F_SIGNAL].gt(0.0)
    valid_time = d["latest_13f_available_from_date"].notna() & d["decision_date"].notna()
    d["latest_13f_after_decision"] = valid_time & d["latest_13f_available_from_date"].gt(d["decision_date"])
    d.loc[d["latest_13f_after_decision"], "thirteen_f_confirmed"] = False
    d = d.drop_duplicates(["rebalance_date", "added_ticker", "removed_ticker"], keep="last").copy()
    confirmed = d[d["thirteen_f_confirmed"]].copy()
    not_confirmed = d[~d["thirteen_f_confirmed"]].copy()
    separation = {
        "status": "ok" if d["thirteen_f_confirmed"].nunique() == 2 else "insufficient_groups",
        "confirmed_count": int(len(confirmed)),
        "unconfirmed_count": int(len(not_confirmed)),
        "confirmed_mean_forward_return_audit_only": float(confirmed["forward_return_audit_only"].mean())
        if not confirmed.empty
        else None,
        "unconfirmed_mean_forward_return_audit_only": float(not_confirmed["forward_return_audit_only"].mean())
        if not not_confirmed.empty
        else None,
    }
    if separation["status"] == "ok":
        separation["confirmed_minus_unconfirmed_forward_return_audit_only"] = safe_float(
            separation["confirmed_mean_forward_return_audit_only"]
        ) - safe_float(separation["unconfirmed_mean_forward_return_audit_only"])
    else:
        separation["confirmed_minus_unconfirmed_forward_return_audit_only"] = None
    meta = {
        "miss_set_path": str(path),
        "miss_set_rows": int(len(d)),
        "miss_set_unique_dates": int(d["rebalance_date"].nunique()),
        "miss_set_unique_added_tickers": int(d["added_ticker"].nunique()),
        "w4_13f_score_joined_rows": int(d[PURE_13F_SIGNAL].abs().gt(1e-12).sum()),
        "confirmed_swap_count": int(d["thirteen_f_confirmed"].sum()),
        "unconfirmed_revert_count": int((~d["thirteen_f_confirmed"]).sum()),
        "rows_with_latest_13f_available_from_after_decision": int(d["latest_13f_after_decision"].sum()),
        "miss_set_overlap_separation": separation,
    }
    return d, meta


def revert_rows(base_book: pd.DataFrame, miss_set: pd.DataFrame, *, revert_confirmed: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    book = base_book.copy()
    book["rebalance_date"] = book["rebalance_date"].map(norm_date)
    book["ticker"] = book["ticker"].map(norm_ticker)
    book["weight"] = pd.to_numeric(book["weight"], errors="coerce").fillna(0.0)
    if "target_weight" in book.columns:
        book["target_weight"] = pd.to_numeric(book["target_weight"], errors="coerce").fillna(book["weight"])
    else:
        book["target_weight"] = book["weight"]

    rows: list[pd.DataFrame] = []
    applied: list[dict[str, Any]] = []
    for dt, day in book.groupby("rebalance_date", sort=True):
        day_out = day.copy()
        swaps = miss_set[miss_set["rebalance_date"].eq(str(dt))].copy()
        if not revert_confirmed:
            swaps = swaps[~swaps["thirteen_f_confirmed"]].copy()
        if swaps.empty:
            rows.append(day_out)
            continue
        # Max one replacement-quality event per date by construction; if more
        # exist, keep the strongest 13F score as a deterministic predeclared tie.
        swaps = swaps.sort_values([PURE_13F_SIGNAL, "added_ticker"], ascending=[False, True]).head(1)
        swap = swaps.iloc[0]
        added = norm_ticker(swap["added_ticker"])
        removed = norm_ticker(swap["removed_ticker"])
        mask = day_out["ticker"].eq(added)
        if not mask.any():
            rows.append(day_out)
            applied.append(
                {
                    "rebalance_date": str(dt),
                    "added_ticker": added,
                    "removed_ticker": removed,
                    "action": "skip_added_not_in_official_book",
                    "w4_13f_score": safe_float(swap.get(PURE_13F_SIGNAL)),
                    "thirteen_f_confirmed": bool(swap.get("thirteen_f_confirmed")),
                }
            )
            continue
        idx = day_out[mask].index[0]
        before = day_out.loc[idx].copy()
        day_out.at[idx, "ticker"] = removed
        if "Name" in day_out.columns:
            day_out.at[idx, "Name"] = removed
        if "holding_state_reason" in day_out.columns:
            day_out.at[idx, "holding_state_reason"] = "research_only_13f_confirm_reverted_unconfirmed_replacement"
        if "operating_target_source" in day_out.columns:
            day_out.at[idx, "operating_target_source"] = "fixed_book_13f_confirmation_counterfactual"
        applied.append(
            {
                "rebalance_date": str(dt),
                "added_ticker": added,
                "removed_ticker": removed,
                "action": "revert_added_to_removed",
                "official_weight": safe_float(before.get("weight")),
                "replacement_weight": safe_float(swap.get("replacement_weight")),
                "w4_13f_score": safe_float(swap.get(PURE_13F_SIGNAL)),
                "thirteen_f_confirmed": bool(swap.get("thirteen_f_confirmed")),
                "forward_return_audit_only": safe_float(swap.get("forward_return_audit_only")),
            }
        )
        rows.append(day_out)
    out = pd.concat(rows, ignore_index=True) if rows else book
    out = out.sort_values(["rebalance_date", "weight", "ticker"], ascending=[True, False, True]).reset_index(drop=True)
    return out, pd.DataFrame(applied)


def broad_oos_ic(signal_stats_path: Path) -> dict[str, Any]:
    if not signal_stats_path.exists():
        return {"status": "missing_signal_stats", "sign_positive": False}
    stats = pd.read_csv(signal_stats_path)
    row = stats[(stats["signal"].eq(PURE_13F_SIGNAL)) & (stats["split"].eq("oos"))]
    if row.empty:
        return {"status": "missing_w4_13f_oos_row", "sign_positive": False}
    r = row.iloc[0]
    high_low = safe_float(r.get("high_minus_low"))
    spearman = safe_float(r.get("spearman"))
    return {
        "status": str(r.get("status") or "unknown"),
        "high_minus_low": high_low,
        "spearman": spearman,
        "high_quantile_count": int(safe_float(r.get("high_quantile_count"))),
        "high_quantile_positive_rate": safe_float(r.get("high_quantile_positive_rate")),
        "sign_positive": bool(high_low > 0.0),
    }


def replay_arm(
    *,
    target_book: Path,
    output_dir: Path,
    price_cache: Path,
    mode: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    cash_cfg = CashCarryConfig(
        mode=mode,
        rate_source=args.cash_rate_source,
        rate_lag_days=int(args.cash_rate_lag_days),
        haircut_bps=float(args.cash_carry_haircut_bps),
        day_count=int(args.cash_carry_day_count),
        rate_path=repo_path(args.cash_rate_path) if mode == CASH_CARRY_MODE_RISK_FREE and args.cash_rate_path else None,
    )
    return replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=output_dir,
        portfolio_kind="concentrated",
        starting_capital=float(args.starting_capital),
        fill_mode="next_close",
        cost_bps=float(args.cost_bps),
        integer_shares=True,
        max_fill_lag_days=int(args.max_fill_lag_days),
        disable_concentrated_champion_filter=True,
        max_reasonable_weight_sum=float(args.max_reasonable_weight_sum),
        oos_start=args.oos_start,
        oos2_start=args.oos2_start,
        cash_carry_config=cash_cfg,
        replay_end_date=args.replay_end_date,
        official_baseline_end_date=args.replay_end_date,
        benchmark_ticker=args.benchmark_ticker,
    )


def metric_value(metrics: dict[str, Any], window: str, key: str) -> float:
    if window == "full":
        return safe_float(metrics.get(key))
    return safe_float(((metrics.get("windows") or {}).get(window) or {}).get(key))


def metric_row(accounting: str, arm: str, metrics: dict[str, Any], official: dict[str, Any], hook_off: dict[str, Any]) -> dict[str, Any]:
    row = {
        "accounting_mode": accounting,
        "arm": arm,
        "status": metrics.get("status"),
        "metric_mode": metrics.get("metric_mode"),
        "cagr": metrics.get("cagr"),
        "max_dd": metrics.get("max_dd"),
        "sharpe": metrics.get("sharpe"),
        "absolute_mission_pass": metrics.get("absolute_mission_pass"),
        "excess_cagr_vs_benchmark": metrics.get("excess_cagr_vs_benchmark"),
        "relative_max_dd_vs_benchmark": metrics.get("relative_max_dd_vs_benchmark"),
        "down_capture_vs_benchmark": metrics.get("down_capture_vs_benchmark"),
        "beta_adjusted_alpha_annualized": metrics.get("beta_adjusted_alpha_annualized"),
    }
    for prefix, base in [("vs_official", official), ("vs_hook_off", hook_off)]:
        row[f"{prefix}.delta_cagr_pp"] = (metric_value(metrics, "full", "cagr") - metric_value(base, "full", "cagr")) * 100.0
        row[f"{prefix}.delta_max_dd_pp"] = (metric_value(metrics, "full", "max_dd") - metric_value(base, "full", "max_dd")) * 100.0
        for window in ("is", "oos", "oos2"):
            row[f"{prefix}.delta_{window}_cagr_pp"] = (
                metric_value(metrics, window, "cagr") - metric_value(base, window, "cagr")
            ) * 100.0
            row[f"{prefix}.delta_{window}_max_dd_pp"] = (
                metric_value(metrics, window, "max_dd") - metric_value(base, window, "max_dd")
            ) * 100.0
    return row


def classify(payload: dict[str, Any]) -> str:
    if payload.get("pit_gate_status") != "clean":
        return "blocked_pit_gate_not_clean"
    power = payload.get("statistical_power_guard", {})
    if not power.get("broad_and_miss_set_sign_agree"):
        return "inconclusive_underpowered"
    if int(payload.get("confirmed_swap_count") or 0) <= 0:
        return "reject_no_confirmed_swaps"
    rows = [
        row
        for row in payload.get("arm_metrics", [])
        if row.get("arm") == "13f_confirmed_candidate"
    ]
    if not rows:
        return "blocked_missing_candidate_metrics"
    for row in rows:
        if safe_float(row.get("vs_official.delta_oos_cagr_pp")) < 0.0:
            return "reject_oos_worse"
        if safe_float(row.get("vs_official.delta_oos2_cagr_pp")) < 0.0:
            return "reject_oos2_worse"
        if safe_float(row.get("max_dd")) < -0.25:
            return "reject_mdd_breach"
    cash = next((row for row in rows if row.get("accounting_mode") == "cash_carry"), None)
    if not cash or not bool(cash.get("absolute_mission_pass")):
        return "reject_absolute_mission_not_restored"
    return "13f_confirm_candidate_pass"


def render_report(payload: dict[str, Any]) -> str:
    power_guard = payload.get("statistical_power_guard") or {}
    lines = [
        "# Run287 13F Fixed-Book Broker A/B",
        "",
        f"- status: `{payload['status']}`",
        f"- decision_label: `{payload['decision_label']}`",
        f"- pit_gate_status: `{payload['pit_gate_status']}`",
        f"- confirmed swaps: `{payload.get('confirmed_swap_count', 0)}`",
        f"- unconfirmed reverts: `{payload.get('unconfirmed_revert_count', 0)}`",
        f"- broad/miss-set sign agreement: `{power_guard.get('broad_and_miss_set_sign_agree')}`",
        "- No fullrun, hook promotion, threshold grid, production promotion, or live trading.",
        "",
        "## Broker Metrics",
        "",
        "| Accounting | Arm | CAGR | MaxDD | dCAGR vs official pp | OOS dCAGR pp | OOS2 dCAGR pp | Mission pass | Excess CAGR vs SPY | Down capture | Beta-adj alpha |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in payload.get("arm_metrics", []):
        lines.append(
            "| {acct} | {arm} | {cagr:.2%} | {mdd:.2%} | {dc:+.2f} | {oos:+.2f} | {oos2:+.2f} | {mission} | {excess:+.2%} | {down} | {alpha} |".format(
                acct=row.get("accounting_mode"),
                arm=row.get("arm"),
                cagr=safe_float(row.get("cagr")),
                mdd=safe_float(row.get("max_dd")),
                dc=safe_float(row.get("vs_official.delta_cagr_pp")),
                oos=safe_float(row.get("vs_official.delta_oos_cagr_pp")),
                oos2=safe_float(row.get("vs_official.delta_oos2_cagr_pp")),
                mission=row.get("absolute_mission_pass"),
                excess=safe_float(row.get("excess_cagr_vs_benchmark")),
                down="" if row.get("down_capture_vs_benchmark") is None else f"{safe_float(row.get('down_capture_vs_benchmark')):.3f}",
                alpha="" if row.get("beta_adjusted_alpha_annualized") is None else f"{safe_float(row.get('beta_adjusted_alpha_annualized')):.2%}",
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `official_baseline` is the run287 fixed official book.",
            "- `rq_hook_off_reconstructed` reverts all replacement-quality policy-month replacements to their recorded donor tickers.",
            "- `13f_confirmed_candidate` keeps only replacements whose added ticker has ex-ante pure `w4_13f_score > 0`; unconfirmed replacements are reverted.",
            "- Forward returns appear only in `swaps.csv` as audit labels and are not used for ranking or threshold tuning.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pit_payload = audit_13f_pit(repo_path(args.sec13f_path), repo_path(args.miss_set))
    pit_dir = repo_path(args.pit_output_dir)
    pit_dir.mkdir(parents=True, exist_ok=True)
    write_json(pit_dir / "summary.json", pit_payload)
    if pit_payload.get("pit_gate_status") != "clean":
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "decision_label": "blocked_pit_gate_not_clean",
            "pit_gate_status": pit_payload.get("pit_gate_status"),
            "pit_gate_summary": str(pit_dir / "summary.json"),
            "research_only": True,
            "fullrun_dispatched": False,
            "new_alpha_hook_added": False,
            "threshold_tuning_performed": False,
            "production_promotion_allowed": False,
            "live_trading_enabled": False,
        }
        write_json(output_dir / "summary.json", payload)
        (output_dir / "report.md").write_text(render_report({**payload, "confirmed_swap_count": 0, "unconfirmed_revert_count": 0, "statistical_power_guard": {}}), encoding="utf-8")
        return payload

    lookup, lookup_meta = build_w4_13f_lookup(
        candidate_book=repo_path(args.candidate_book),
        sec13f_path=repo_path(args.sec13f_path),
        manager_universe=repo_path(args.manager_universe),
        oos_start=args.oos_start,
    )
    miss, miss_meta = load_miss_set(repo_path(args.miss_set), lookup)
    broad = broad_oos_ic(repo_path(args.signal_stats))
    miss_sep = miss_meta["miss_set_overlap_separation"]
    miss_sign_positive = safe_float(miss_sep.get("confirmed_minus_unconfirmed_forward_return_audit_only")) > 0.0
    power_guard = {
        "broad_oos_ic": broad,
        "miss_set_overlap_separation": miss_sep,
        "broad_and_miss_set_sign_agree": bool(broad.get("sign_positive") and miss_sign_positive),
    }

    base = pd.read_csv(repo_path(args.target_book), low_memory=False)
    hook_off, hook_off_swaps = revert_rows(base, miss, revert_confirmed=True)
    candidate, reverted_unconfirmed = revert_rows(base, miss, revert_confirmed=False)
    official_book = output_dir / "official_baseline_target_book.csv"
    hook_off_book = output_dir / "rq_hook_off_reconstructed_target_book.csv"
    candidate_book = output_dir / "13f_confirmed_target_book.csv"
    swaps_path = output_dir / "swaps.csv"
    write_csv(official_book, base)
    write_csv(hook_off_book, hook_off)
    write_csv(candidate_book, candidate)
    swap_rows = pd.concat(
        [
            hook_off_swaps.assign(arm="rq_hook_off_reconstructed"),
            reverted_unconfirmed.assign(arm="13f_confirmed_candidate_unconfirmed_reverts"),
        ],
        ignore_index=True,
    )
    write_csv(swaps_path, swap_rows)

    arm_metrics: list[dict[str, Any]] = []
    raw_metrics: dict[str, dict[str, Any]] = {}
    price_cache = repo_path(args.price_cache)
    for accounting, mode in [("zero_yield", CASH_CARRY_MODE_NONE), ("cash_carry", CASH_CARRY_MODE_RISK_FREE)]:
        raw_metrics[accounting] = {}
        books = {
            "official_baseline": official_book,
            "rq_hook_off_reconstructed": hook_off_book,
            "13f_confirmed_candidate": candidate_book,
        }
        for arm, path in books.items():
            metrics = replay_arm(
                target_book=path,
                output_dir=output_dir / "replays" / accounting / arm,
                price_cache=price_cache,
                mode=mode,
                args=args,
            )
            raw_metrics[accounting][arm] = metrics
        official = raw_metrics[accounting]["official_baseline"]
        hook_off_metrics = raw_metrics[accounting]["rq_hook_off_reconstructed"]
        for arm, metrics in raw_metrics[accounting].items():
            arm_metrics.append(metric_row(accounting, arm, metrics, official, hook_off_metrics))

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "decision_label": "",
        "portfolio_kind": "concentrated",
        "run_id": "28725350727",
        "pit_gate_status": pit_payload.get("pit_gate_status"),
        "pit_gate_summary": str(pit_dir / "summary.json"),
        "target_book": str(repo_path(args.target_book)),
        "miss_set": str(repo_path(args.miss_set)),
        "pure_signal": PURE_13F_SIGNAL,
        "score_threshold": 0.0,
        "confirmed_swap_count": miss_meta["confirmed_swap_count"],
        "unconfirmed_revert_count": miss_meta["unconfirmed_revert_count"],
        "hook_off_reverted_count": int(len(hook_off_swaps[hook_off_swaps["action"].eq("revert_added_to_removed")]))
        if not hook_off_swaps.empty
        else 0,
        "signal_lookup": lookup_meta,
        "miss_set_meta": miss_meta,
        "statistical_power_guard": power_guard,
        "arm_metrics": arm_metrics,
        "artifacts": {
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "report.md"),
            "arm_metrics": str(output_dir / "arm_metrics.csv"),
            "swaps": str(swaps_path),
            "official_baseline_target_book": str(official_book),
            "rq_hook_off_reconstructed_target_book": str(hook_off_book),
            "13f_confirmed_target_book": str(candidate_book),
        },
        "research_only": True,
        "fullrun_dispatched": False,
        "new_alpha_hook_added": False,
        "threshold_tuning_performed": False,
        "production_promotion_allowed": False,
        "live_trading_enabled": False,
        "forward_returns_audit_only": True,
    }
    payload["decision_label"] = classify(payload)
    pd.DataFrame(arm_metrics).to_csv(output_dir / "arm_metrics.csv", index=False)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--target-book", default=DEFAULT_TARGET_BOOK)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--miss-set", default=DEFAULT_MISS_SET)
    parser.add_argument("--signal-stats", default=DEFAULT_SIGNAL_STATS)
    parser.add_argument("--sec13f-path", default=DEFAULT_13F_PATH)
    parser.add_argument("--manager-universe", default=DEFAULT_MANAGER_UNIVERSE)
    parser.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--cash-rate-path", default=DEFAULT_CASH_RATE_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pit-output-dir", default="outputs/run287_13f_pit_gate")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--max-reasonable-weight-sum", type=float, default=1.05)
    parser.add_argument("--replay-end-date", default=DEFAULT_REPLAY_END_DATE)
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START)
    parser.add_argument("--oos2-start", default=DEFAULT_OOS2_START)
    parser.add_argument("--cash-rate-source", default="DGS3MO")
    parser.add_argument("--cash-rate-lag-days", type=int, default=1)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=50.0)
    parser.add_argument("--cash-carry-day-count", type=int, default=365)
    parser.add_argument("--benchmark-ticker", default="SPY")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
