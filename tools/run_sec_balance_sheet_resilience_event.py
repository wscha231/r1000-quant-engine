#!/usr/bin/env python3
"""Run a research-only exact-accepted SEC balance-sheet resilience screen.

The signal is deliberately threshold-free.  For one issuer, both debt/assets
and net-debt/assets must move in the same direction versus the latest earlier
comparable fiscal-period state.  Companyfacts ``filed`` is never availability;
every observation must join by accession to an exact SEC acceptance timestamp.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tools.run_sec_filing_quality_event as quality  # noqa: E402


BALANCE_FORMS = frozenset({"10-Q", "10-Q/A", "10-K", "10-K/A"})
OOS_START = quality.DEFAULT_OOS_START
OOS2_START = quality.DEFAULT_OOS2_START
HORIZONS = (21, 63, 126)
MIN_PRIOR_PERIOD_GAP_DAYS = 45
MAX_PRIOR_PERIOD_GAP_DAYS = 460

TAG_ALIASES: dict[str, tuple[str, ...]] = {
    "assets": ("Assets",),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "debt_noncurrent": (
        "LongTermDebtNoncurrent",
        "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
        "NoncurrentBorrowings",
    ),
    "debt_current": (
        "LongTermDebtCurrent",
        "LongTermDebtAndFinanceLeaseObligationsCurrent",
        "DebtCurrent",
        "ShortTermBorrowings",
        "ShortTermDebtCurrent",
        "CurrentDebtAndCapitalLeaseObligations",
    ),
    "debt_total": (
        "LongTermDebt",
        "LongTermDebtAndFinanceLeaseObligations",
        "DebtAndFinanceLeaseObligations",
    ),
}

PIT_CAVEATS = (
    "research_only",
    "pit_universe_label_clean=false",
    "exact_sec_acceptance_required",
    "filed_date_fallback_forbidden",
    "missing_or_incomparable_components_are_neutral",
    "current_identity_mapping_not_historical_membership",
    "foreign_issuers_without_comparable_companyfacts_are_neutral",
)


def _usd_rows(fact: dict[str, Any]) -> list[dict[str, Any]]:
    units = fact.get("units") or {}
    if not isinstance(units, dict):
        return []
    for name, rows in units.items():
        if str(name).upper() == "USD" and isinstance(rows, list):
            return rows
    return []


def extract_balance_facts(item: quality.CompanyfactsPayload) -> pd.DataFrame:
    """Extract accession-preserving instant balance-sheet facts."""
    payload_facts = item.payload.get("facts") or {}
    rows: list[dict[str, Any]] = []
    for namespace_rank, namespace in enumerate(("us-gaap", "ifrs-full")):
        namespace_facts = payload_facts.get(namespace) or {}
        if not isinstance(namespace_facts, dict):
            continue
        for fact_group, aliases in TAG_ALIASES.items():
            for alias_rank, tag in enumerate(aliases):
                fact = namespace_facts.get(tag)
                if not isinstance(fact, dict):
                    continue
                for raw in _usd_rows(fact):
                    if not isinstance(raw, dict):
                        continue
                    form = str(raw.get("form") or "").upper().strip()
                    accession_number = str(raw.get("accn") or "").strip()
                    accession_key = quality.accession_key(accession_number)
                    period = pd.to_datetime(raw.get("end"), errors="coerce")
                    value = pd.to_numeric(raw.get("val"), errors="coerce")
                    if (
                        form not in BALANCE_FORMS
                        or not accession_key
                        or pd.isna(period)
                        or not np.isfinite(value)
                        or float(value) < 0.0
                    ):
                        continue
                    rows.append(
                        {
                            "cik10": item.cik10,
                            "accession_number": accession_number,
                            "accession_key": accession_key,
                            "form": form,
                            "fiscal_year": raw.get("fy"),
                            "fiscal_quarter": str(raw.get("fp") or "").upper().strip(),
                            "period": pd.Timestamp(period).normalize(),
                            "fact_group": fact_group,
                            "source_tag": tag,
                            "alias_rank": int(alias_rank),
                            "namespace": namespace,
                            "namespace_rank": int(namespace_rank),
                            "unit": "USD",
                            "value": float(value),
                            "companyfacts_sha256": item.sha256,
                            "companyfacts_member": item.source_member,
                        }
                    )
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(
            ["cik10", "accession_key", "period", "fact_group", "namespace_rank", "alias_rank", "source_tag"]
        )
        .drop_duplicates(["cik10", "accession_key", "period", "fact_group", "source_tag"], keep="last")
        .reset_index(drop=True)
    )


def load_balance_facts(
    path: str | Path, *, wanted_ciks: Iterable[str]
) -> tuple[pd.DataFrame, dict[str, dict[str, str]]]:
    frames: list[pd.DataFrame] = []
    sources: dict[str, dict[str, str]] = {}
    for item in quality.iter_companyfacts_payloads(path, wanted_ciks=wanted_ciks):
        sources[item.cik10] = {
            "companyfacts_sha256": item.sha256,
            "companyfacts_member": item.source_member,
        }
        frame = extract_balance_facts(item)
        if not frame.empty:
            frames.append(frame)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), sources


def _select_fact(rows: pd.DataFrame, fact_group: str) -> pd.Series | None:
    candidates = rows[rows["fact_group"].eq(fact_group)].copy()
    if candidates.empty:
        return None
    return candidates.sort_values(["namespace_rank", "alias_rank", "source_tag"]).iloc[0]


def _statement_state(filing: pd.Series, facts: pd.DataFrame) -> dict[str, Any] | None:
    same = facts[
        facts["cik10"].eq(filing["cik10"])
        & facts["accession_key"].eq(filing["accession_key"])
    ].copy()
    if same.empty:
        return None
    report_period = filing.get("period")
    if pd.notna(report_period):
        same = same[same["period"].eq(pd.Timestamp(report_period).normalize())].copy()
    else:
        same = same[same["period"].eq(same["period"].max())].copy()
    if same.empty:
        return None

    selected = {name: _select_fact(same, name) for name in TAG_ALIASES}
    assets = float(selected["assets"]["value"]) if selected["assets"] is not None else np.nan
    cash = float(selected["cash"]["value"]) if selected["cash"] is not None else np.nan
    noncurrent = (
        float(selected["debt_noncurrent"]["value"])
        if selected["debt_noncurrent"] is not None
        else np.nan
    )
    current = (
        float(selected["debt_current"]["value"])
        if selected["debt_current"] is not None
        else np.nan
    )
    total_reported = (
        float(selected["debt_total"]["value"])
        if selected["debt_total"] is not None
        else np.nan
    )
    if np.isfinite(noncurrent) and np.isfinite(current):
        total_debt = noncurrent + current
        debt_scope = "NONCURRENT_PLUS_CURRENT_COMPLETE"
        debt_tags = [selected["debt_noncurrent"]["source_tag"], selected["debt_current"]["source_tag"]]
    elif np.isfinite(total_reported):
        total_debt = total_reported
        debt_scope = "REPORTED_TOTAL_COMPLETE"
        debt_tags = [selected["debt_total"]["source_tag"]]
    else:
        total_debt = np.nan
        debt_scope = "INCOMPLETE_DEBT_SCOPE"
        debt_tags = []

    complete = bool(
        np.isfinite(assets)
        and assets > 0.0
        and np.isfinite(cash)
        and np.isfinite(total_debt)
    )
    debt_to_assets = total_debt / assets if complete else np.nan
    net_debt_to_assets = (total_debt - cash) / assets if complete else np.nan
    period = same["period"].max()
    tags = {
        name: (str(value["source_tag"]) if value is not None else "")
        for name, value in selected.items()
    }
    tags["debt_components_used"] = debt_tags
    return {
        "ticker": filing["ticker"],
        "cik10": filing["cik10"],
        "accession_number": filing["accession_number"],
        "accession_key": filing["accession_key"],
        "form": filing["form"],
        "fiscal_period": pd.Timestamp(period).date().isoformat(),
        "period_ts": pd.Timestamp(period).normalize(),
        "accepted_at": filing["accepted_at"],
        "available_from": filing["available_from"],
        "accepted_ts": filing["accepted_ts"],
        "exact_acceptance": True,
        "assets": assets,
        "cash": cash,
        "total_debt": total_debt,
        "debt_to_assets": debt_to_assets,
        "net_debt_to_assets": net_debt_to_assets,
        "current_component_coverage": 2 if complete else 0,
        "debt_scope": debt_scope,
        "source_tags": quality.canonical_json(tags),
        "submissions_row_sha256": filing["submissions_row_sha256"],
    }


def _add_event_direction(states: pd.DataFrame) -> pd.DataFrame:
    if states.empty:
        return states
    rows: list[dict[str, Any]] = []
    groups = {
        cik: group.sort_values(["period_ts", "accepted_ts", "accession_key"]).copy()
        for cik, group in states.groupby("cik10", sort=False)
    }
    for current in states.sort_values(["accepted_ts", "cik10", "accession_key"]).itertuples(index=False):
        row = current._asdict()
        prior_accession = ""
        prior_period = ""
        prior_accepted_at = ""
        prior_debt_scope = ""
        prior_debt_ratio = np.nan
        prior_net_debt_ratio = np.nan
        comparison_coverage = 0
        event = "neutral"
        issuer = groups[str(row["cik10"])]
        gap = (pd.Timestamp(row["period_ts"]) - issuer["period_ts"]).dt.days
        candidates = issuer[
            issuer["accepted_ts"].lt(row["accepted_ts"])
            & issuer["period_ts"].lt(row["period_ts"])
            & gap.between(MIN_PRIOR_PERIOD_GAP_DAYS, MAX_PRIOR_PERIOD_GAP_DAYS)
            & issuer["current_component_coverage"].eq(2)
            & issuer["debt_scope"].eq(row["debt_scope"])
        ].copy()
        if int(row["current_component_coverage"]) == 2 and not candidates.empty:
            prior = candidates.sort_values(
                ["period_ts", "accepted_ts", "accession_key"], ascending=[False, False, False]
            ).iloc[0]
            prior_accession = str(prior["accession_number"])
            prior_period = pd.Timestamp(prior["period_ts"]).date().isoformat()
            prior_accepted_at = pd.Timestamp(prior["accepted_ts"]).isoformat()
            prior_debt_scope = str(prior["debt_scope"])
            prior_debt_ratio = float(prior["debt_to_assets"])
            prior_net_debt_ratio = float(prior["net_debt_to_assets"])
            comparison_coverage = 2
            debt_change = float(row["debt_to_assets"]) - prior_debt_ratio
            net_debt_change = float(row["net_debt_to_assets"]) - prior_net_debt_ratio
            if debt_change <= 0.0 and net_debt_change <= 0.0 and (debt_change < 0.0 or net_debt_change < 0.0):
                event = "positive"
            elif debt_change >= 0.0 and net_debt_change >= 0.0 and (debt_change > 0.0 or net_debt_change > 0.0):
                event = "negative"
            row["debt_to_assets_change"] = debt_change
            row["net_debt_to_assets_change"] = net_debt_change
        else:
            row["debt_to_assets_change"] = np.nan
            row["net_debt_to_assets_change"] = np.nan
        row.update(
            {
                "prior_accession_number": prior_accession,
                "prior_fiscal_period": prior_period,
                "prior_accepted_at": prior_accepted_at,
                "prior_debt_scope": prior_debt_scope,
                "prior_debt_to_assets": prior_debt_ratio,
                "prior_net_debt_to_assets": prior_net_debt_ratio,
                "component_coverage": comparison_coverage,
                "sec_balance_sheet_resilience_event": event,
                "event_score": {"positive": 1, "negative": -1}.get(event, 0),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_events(
    facts: pd.DataFrame,
    filings: pd.DataFrame,
    *,
    sources: dict[str, dict[str, str]],
    submissions_sha256: str,
    available_tickers: Iterable[str] = (),
) -> tuple[pd.DataFrame, dict[str, Any]]:
    prepared, diagnostics = quality.prepare_filings(filings)
    prepared = prepared[prepared["form"].isin(BALANCE_FORMS)].copy()
    if facts.empty or prepared.empty:
        return pd.DataFrame(), {**diagnostics, "status": "no_balance_facts_or_filings"}
    fact_keys = pd.MultiIndex.from_frame(facts[["cik10", "accession_key"]].drop_duplicates())
    prepared_keys = pd.MultiIndex.from_frame(prepared[["cik10", "accession_key"]])
    prepared = prepared[prepared_keys.isin(fact_keys)].copy()
    priced = {str(value).upper().strip() for value in available_tickers if str(value).strip()}
    prepared["price_rank"] = (~prepared["ticker"].isin(priced)).astype(int) if priced else 0
    prepared = prepared.sort_values(["cik10", "accession_key", "price_rank", "ticker"]).drop_duplicates(
        ["cik10", "accession_key"], keep="first"
    )
    fact_groups = {
        key: group.copy()
        for key, group in facts.groupby(["cik10", "accession_key"], sort=False)
    }
    states: list[dict[str, Any]] = []
    for filing in prepared.itertuples(index=False):
        filing_row = pd.Series(filing._asdict())
        current_facts = fact_groups.get(
            (str(filing_row["cik10"]), str(filing_row["accession_key"])), facts.iloc[0:0]
        )
        state = _statement_state(filing_row, current_facts)
        if state is not None:
            states.append(state)
    events = _add_event_direction(pd.DataFrame(states))
    if events.empty:
        return events, {**diagnostics, "status": "no_joined_balance_states"}
    events["source_hashes"] = events.apply(
        lambda row: quality.canonical_json(
            {
                **sources.get(str(row["cik10"]), {}),
                "submissions_index_sha256": submissions_sha256,
                "submissions_row_sha256": str(row["submissions_row_sha256"]),
            }
        ),
        axis=1,
    )
    events["pit_caveats"] = quality.canonical_json(PIT_CAVEATS)
    accepted = pd.to_datetime(events["accepted_at"], errors="coerce", utc=True)
    available = pd.to_datetime(events["available_from"], errors="coerce", utc=True)
    fired = events["sec_balance_sheet_resilience_event"].isin(["positive", "negative"])
    violations = accepted.isna() | available.isna() | accepted.ne(available) | ~events["exact_acceptance"]
    if violations.any():
        raise quality.DataContractError("exact-acceptance balance-sheet contract violation")
    if fired.any() and events.loc[fired, "component_coverage"].ne(2).any():
        raise quality.DataContractError("fired balance-sheet event lacks both comparable ratios")
    diagnostics.update(
        {
            "status": "ok",
            "event_count": int(len(events)),
            "issuer_count": int(events["cik10"].nunique()),
            "positive_count": int(events["sec_balance_sheet_resilience_event"].eq("positive").sum()),
            "negative_count": int(events["sec_balance_sheet_resilience_event"].eq("negative").sum()),
            "neutral_count": int(events["sec_balance_sheet_resilience_event"].eq("neutral").sum()),
            "current_complete_count": int(events["current_component_coverage"].eq(2).sum()),
            "comparable_complete_count": int(events["component_coverage"].eq(2).sum()),
            "history_start_accepted_at": str(events["accepted_at"].min()),
            "history_end_accepted_at": str(events["accepted_at"].max()),
            "future_row_count": 0,
            "filed_date_fallback_used": False,
            "pit_universe_label_clean": False,
            "research_only": True,
        }
    )
    drop_columns = ["accepted_ts", "period_ts", "accession_key", "submissions_row_sha256"]
    return events.drop(columns=drop_columns).sort_values(["accepted_at", "cik10"]).reset_index(drop=True), diagnostics


def label_excess_returns(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    features = events.rename(
        columns={"sec_balance_sheet_resilience_event": "sec_filing_quality_event"}
    )
    labeled = quality.label_forward_returns(features, prices[["ticker", "date", "adjusted_close"]])
    spy = (
        prices[prices["ticker"].eq("SPY")]
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .set_index("date")["adjusted_close"]
    )
    for horizon in HORIZONS:
        excess: list[float] = []
        for row in labeled.itertuples(index=False):
            entry = pd.to_datetime(getattr(row, "entry_date"), errors="coerce")
            raw_return = pd.to_numeric(getattr(row, f"forward_return_{horizon}d"), errors="coerce")
            if pd.isna(entry) or entry not in spy.index or not np.isfinite(raw_return):
                excess.append(np.nan)
                continue
            position = int(spy.index.searchsorted(entry, side="left"))
            exit_position = position + horizon
            if position >= len(spy) or exit_position >= len(spy):
                excess.append(np.nan)
                continue
            benchmark_return = float(spy.iloc[exit_position] / spy.iloc[position] - 1.0)
            excess.append(float(raw_return - benchmark_return))
        labeled[f"spy_excess_return_{horizon}d"] = excess
    return labeled.rename(
        columns={"sec_filing_quality_event": "sec_balance_sheet_resilience_event"}
    )


def source_screen(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    oos_start: str,
    oos2_start: str,
    iterations: int,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    labeled = label_excess_returns(events, prices)
    labeled["filing_week"] = labeled["available_from"].map(quality.filing_week)
    accepted = pd.to_datetime(labeled["accepted_at"], errors="coerce", utc=True)
    segments = {
        "full": pd.Series(True, index=labeled.index),
        "oos": accepted.ge(quality.parse_utc(oos_start)),
        "oos2": accepted.ge(quality.parse_utc(oos2_start)),
    }
    metrics: dict[str, Any] = {}
    for segment, mask in segments.items():
        scoped = labeled[mask].copy()
        segment_metrics: dict[str, Any] = {"event_count": int(len(scoped))}
        for horizon in HORIZONS:
            column = f"spy_excess_return_{horizon}d"
            positive = pd.to_numeric(
                scoped.loc[scoped["sec_balance_sheet_resilience_event"].eq("positive"), column],
                errors="coerce",
            ).dropna()
            negative = pd.to_numeric(
                scoped.loc[scoped["sec_balance_sheet_resilience_event"].eq("negative"), column],
                errors="coerce",
            ).dropna()
            bootstrap = scoped.rename(
                columns={"sec_balance_sheet_resilience_event": "sec_filing_quality_event"}
            ).copy()
            bootstrap[f"forward_return_{horizon}d"] = pd.to_numeric(bootstrap[column], errors="coerce")
            lower, upper = quality.cluster_bootstrap_spread(
                bootstrap,
                f"forward_return_{horizon}d",
                iterations=iterations,
                seed=seed + horizon,
            )
            segment_metrics[f"horizon_{horizon}"] = {
                "return_basis": "SPY excess return",
                "positive_count": int(len(positive)),
                "negative_count": int(len(negative)),
                "filing_week_count": int(
                    scoped.loc[
                        scoped["sec_balance_sheet_resilience_event"].isin(["positive", "negative"])
                        & pd.to_numeric(scoped[column], errors="coerce").notna(),
                        "filing_week",
                    ].replace("", pd.NA).nunique()
                ),
                "positive_mean": float(positive.mean()) if not positive.empty else None,
                "negative_mean": float(negative.mean()) if not negative.empty else None,
                "positive_minus_negative": (
                    float(positive.mean() - negative.mean())
                    if not positive.empty and not negative.empty
                    else None
                ),
                "filing_week_cluster_bootstrap_95_lower": lower if np.isfinite(lower) else None,
                "filing_week_cluster_bootstrap_95_upper": upper if np.isfinite(upper) else None,
            }
        metrics[segment] = segment_metrics
    powered = all(
        metrics[name]["horizon_63"]["positive_count"] >= 100
        and metrics[name]["horizon_63"]["negative_count"] >= 100
        and metrics[name]["horizon_63"]["filing_week_count"] >= 12
        for name in ("oos", "oos2")
    )
    if not powered:
        verdict = "UNDERPOWERED"
    else:
        spreads = [metrics[name]["horizon_63"]["positive_minus_negative"] for name in ("full", "oos", "oos2")]
        lowers = [
            metrics[name]["horizon_63"]["filing_week_cluster_bootstrap_95_lower"]
            for name in ("oos", "oos2")
        ]
        verdict = (
            "PASS_SOURCE_SCREEN"
            if all(value is not None and value > 0.0 for value in spreads)
            and all(value is not None and value >= 0.0 for value in lowers)
            else "REJECT_SOURCE_SCREEN"
        )
    return labeled, {
        "verdict": verdict,
        "signal": "sec_balance_sheet_resilience_event",
        "primary_horizon_sessions": 63,
        "secondary_horizons_sessions": [21, 126],
        "return_basis": "SPY excess return",
        "entry_rule": "first NYSE close strictly after exact accepted_at",
        "oos_start": oos_start,
        "oos2_start": oos2_start,
        "power_gate": {"positive_per_oos": 100, "negative_per_oos": 100, "filing_weeks_per_oos": 12},
        "segments": metrics,
        "bootstrap": {"cluster": "filing_week", "iterations": int(iterations), "seed": int(seed)},
        "research_only": True,
        "portfolio_ab_authorized": verdict == "PASS_SOURCE_SCREEN",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companyfacts", default="data_raw/free/sec/companyfacts.zip")
    parser.add_argument("--submissions", default="data_pit/sec/sec_filings_index.parquet")
    parser.add_argument(
        "--prices",
        default=r"H:\codex\tmp_r1000_grossfloor_20260625\outputs\run287_price_cache_full_candidate\cache_prices",
    )
    parser.add_argument("--output-dir", default="outputs/sec_balance_sheet_resilience_event_20260718")
    parser.add_argument("--reuse-fact-cache", default="")
    parser.add_argument("--oos-start", default=OOS_START)
    parser.add_argument("--oos2-start", default=OOS2_START)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=287)
    args = parser.parse_args()

    submissions_path = quality.repo_path(args.submissions)
    companyfacts_path = quality.repo_path(args.companyfacts)
    prices_path = quality.repo_path(args.prices)
    output = quality.repo_path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    filings = quality.read_table(submissions_path)
    wanted_ciks = sorted({quality.cik10(value) for value in filings["cik10"] if quality.cik10(value)})
    wanted_tickers = sorted(set(filings["ticker"].fillna("").astype(str).str.upper()) | {"SPY"})
    prices = quality.load_prices(prices_path, wanted_tickers=wanted_tickers)

    fact_cache = output / "balance_facts_accession_cache.parquet"
    reuse = quality.repo_path(args.reuse_fact_cache) if str(args.reuse_fact_cache).strip() else None
    if reuse is not None:
        facts = pd.read_parquet(reuse)
        required = {"cik10", "accession_key", "fact_group", "companyfacts_sha256", "companyfacts_member"}
        missing = required - set(facts.columns)
        if missing:
            raise quality.DataContractError(f"reused balance fact cache missing {sorted(missing)}")
        sources = {
            str(cik): {
                "companyfacts_sha256": str(group["companyfacts_sha256"].iloc[0]),
                "companyfacts_member": str(group["companyfacts_member"].iloc[0]),
            }
            for cik, group in facts.groupby("cik10", sort=False)
        }
    else:
        facts, sources = load_balance_facts(companyfacts_path, wanted_ciks=wanted_ciks)
    facts.to_parquet(fact_cache, index=False)

    events, diagnostics = build_events(
        facts,
        filings,
        sources=sources,
        submissions_sha256=quality.sha256_file(submissions_path),
        available_tickers=prices["ticker"].unique(),
    )
    if events.empty:
        raise quality.DataContractError("no exact accepted-time balance-sheet events")
    labeled, screen = source_screen(
        events,
        prices,
        oos_start=args.oos_start,
        oos2_start=args.oos2_start,
        iterations=max(1, int(args.bootstrap_iterations)),
        seed=int(args.seed),
    )
    paths = {
        "fact_cache": fact_cache,
        "events": output / "sec_balance_sheet_resilience_events.parquet",
        "events_csv": output / "sec_balance_sheet_resilience_events.csv",
        "screen_rows": output / "source_screen_event_returns.csv",
        "screen_summary": output / "source_screen_summary.json",
        "summary": output / "summary.json",
    }
    events.to_parquet(paths["events"], index=False)
    events.to_csv(paths["events_csv"], index=False)
    labeled.to_csv(paths["screen_rows"], index=False)
    provenance = {
        "companyfacts": quality.fingerprint_path(companyfacts_path),
        "submissions": quality.fingerprint_path(submissions_path),
        "prices": quality.fingerprint_path(prices_path),
        "producer_sha256": quality.sha256_file(Path(__file__)),
        "fact_cache": quality.fingerprint_path(fact_cache),
        "reused_fact_cache": (
            quality.fingerprint_path(reuse)
            if reuse is not None
            else {"path": "", "sha256": "", "file_count": 0, "total_bytes": 0}
        ),
        "contract": quality.fingerprint_path(
            REPO_ROOT / "docs" / "run287_sec_balance_sheet_resilience_event_contract_v1.json"
        ),
    }
    screen = {
        **screen,
        "provenance": provenance,
        "paths": {key: str(value) for key, value in paths.items()},
    }
    paths["screen_summary"].write_text(
        json.dumps(screen, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    run_summary = {
        **diagnostics,
        "source_screen_verdict": screen["verdict"],
        "paths": {key: str(value) for key, value in paths.items()},
        "fullrun_executed": False,
        "portfolio_mutated": False,
        "orders_generated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    paths["summary"].write_text(
        json.dumps(run_summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(run_summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
