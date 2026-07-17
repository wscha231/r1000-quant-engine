#!/usr/bin/env python3
"""Backtest exact-accepted SEC capital-allocation events, normalized by market cap.

This is a research-only source screen.  It does not alter a portfolio book.
Companyfacts ``filed`` dates are never used as availability: every fact must
join by accession number to an exact SEC ``accepted_at`` timestamp.
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
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


FORMS = quality.RESEARCH_FORMS
MATERIALITY = 0.01
MIN_VALID_SHARES = 100_000.0
MIN_VALID_MARKET_CAP = 1_000_000.0
MAX_VALID_MARKET_CAP = 20_000_000_000_000.0
OOS_START = quality.DEFAULT_OOS_START
OOS2_START = quality.DEFAULT_OOS2_START
HORIZONS = (21, 63, 126)

# Repurchase tags are aliases, so only the first available tag is used.  The
# retirement tag is retained as confirmation and is never added a second time.
REPURCHASE_TAGS = (
    "PaymentsForRepurchaseOfCommonStock",
    "StockRepurchasedAndRetiredDuringPeriodValue",
    "StockRepurchasedDuringPeriodValue",
)
COMMON_ISSUANCE_TAGS = (
    "ProceedsFromIssuanceOfCommonStock",
    "StockIssuedDuringPeriodValueNewIssues",
)
CONVERTIBLE_DEBT_TAGS = ("ProceedsFromConvertibleDebt",)
CONVERTIBLE_PREFERRED_TAGS = (
    "ProceedsFromIssuanceOfConvertiblePreferredStock",
    "ProceedsFromIssuanceOfRedeemableConvertiblePreferredStock",
)
RETIREMENT_TAGS = (
    "StockRepurchasedAndRetiredDuringPeriodValue",
    "StockRepurchasedAndRetiredDuringPeriodShares",
)
SHARE_TAGS = (
    "EntityCommonStockSharesOutstanding",
    "CommonStockSharesOutstanding",
)

FLOW_GROUPS = {
    "repurchase": REPURCHASE_TAGS,
    "common_issuance": COMMON_ISSUANCE_TAGS,
    "convertible_debt": CONVERTIBLE_DEBT_TAGS,
    "convertible_preferred": CONVERTIBLE_PREFERRED_TAGS,
}
PIT_CAVEATS = (
    "research_only",
    "pit_universe_label_clean=false",
    "exact_sec_acceptance_required",
    "filed_date_fallback_forbidden",
    "missing_actions_are_neutral_not_imputed",
    "current_identity_mapping_not_historical_membership",
    "raw_close_used_for_market_cap_adjusted_close_used_for_returns",
    "reported_flow_annualized_as_value_times_365_over_duration_days",
    "multi_class_market_cap_may_not_equal_total_issuer_market_cap",
)


def _fact_units(fact: dict[str, Any], *, shares: bool) -> list[tuple[str, list[dict[str, Any]]]]:
    units = fact.get("units") or {}
    if not isinstance(units, dict):
        return []
    preferred = ("shares",) if shares else ("usd",)
    selected = [(name, rows) for name, rows in units.items() if str(name).lower() in preferred and isinstance(rows, list)]
    if selected:
        return selected
    return []


def extract_capital_facts(item: quality.CompanyfactsPayload) -> pd.DataFrame:
    """Extract accession-preserving action and share facts from one issuer."""
    facts = item.payload.get("facts") or {}
    rows: list[dict[str, Any]] = []
    wanted: dict[str, tuple[str, int]] = {}
    for group, tags in FLOW_GROUPS.items():
        for rank, tag in enumerate(tags):
            wanted[tag] = (group, rank)
    for rank, tag in enumerate(RETIREMENT_TAGS):
        wanted.setdefault(tag, ("retirement_confirmation", rank))
    for rank, tag in enumerate(SHARE_TAGS):
        wanted[tag] = ("shares_outstanding", rank)

    for namespace in ("dei", "us-gaap", "ifrs-full"):
        namespace_facts = facts.get(namespace) or {}
        if not isinstance(namespace_facts, dict):
            continue
        for tag, (group, rank) in wanted.items():
            fact = namespace_facts.get(tag)
            if not isinstance(fact, dict):
                continue
            is_shares = group == "shares_outstanding" or tag.endswith("Shares")
            for unit, observations in _fact_units(fact, shares=is_shares):
                for raw in observations:
                    if not isinstance(raw, dict):
                        continue
                    form = str(raw.get("form") or "").upper().strip()
                    accn = str(raw.get("accn") or "").strip()
                    accn_key = quality.accession_key(accn)
                    value = pd.to_numeric(raw.get("val"), errors="coerce")
                    end = pd.to_datetime(raw.get("end"), errors="coerce")
                    if form not in FORMS or not accn_key or pd.isna(end) or not np.isfinite(value) or float(value) < 0:
                        continue
                    days = quality.duration_days(raw.get("start"), raw.get("end"))
                    rows.append(
                        {
                            "cik10": item.cik10,
                            "accession_number": accn,
                            "accession_key": accn_key,
                            "form": form,
                            "fiscal_year": raw.get("fy"),
                            "fiscal_quarter": str(raw.get("fp") or "").upper().strip(),
                            "start": pd.to_datetime(raw.get("start"), errors="coerce"),
                            "period": end,
                            "duration_days": days,
                            "duration_bucket": quality.duration_bucket(days),
                            "fact_group": group,
                            "source_tag": tag,
                            "alias_rank": int(rank),
                            "unit": str(unit),
                            "value": float(value),
                            "companyfacts_sha256": item.sha256,
                            "companyfacts_member": item.source_member,
                        }
                    )
    return pd.DataFrame(rows)


def load_capital_facts(
    path: str | Path, *, wanted_ciks: Iterable[str]
) -> tuple[pd.DataFrame, dict[str, dict[str, str]]]:
    frames: list[pd.DataFrame] = []
    sources: dict[str, dict[str, str]] = {}
    for item in quality.iter_companyfacts_payloads(path, wanted_ciks=wanted_ciks):
        sources[item.cik10] = {
            "companyfacts_sha256": item.sha256,
            "companyfacts_member": item.source_member,
        }
        frame = extract_capital_facts(item)
        if not frame.empty:
            frames.append(frame)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), sources


def _choose_period_rows(filing: pd.Series, facts: pd.DataFrame) -> pd.DataFrame:
    same = facts[
        facts["cik10"].eq(filing["cik10"])
        & facts["accession_key"].eq(filing["accession_key"])
    ].copy()
    if same.empty:
        return same
    report_period = filing.get("period")
    if pd.notna(report_period):
        same = same[same["period"].eq(pd.Timestamp(report_period))].copy()
    else:
        same = same[same["period"].eq(same["period"].max())].copy()
    return same


def _select_flow(group: str, rows: pd.DataFrame, form: str) -> pd.Series | None:
    candidates = rows[rows["fact_group"].eq(group)].copy()
    candidates = candidates[pd.to_numeric(candidates["duration_days"], errors="coerce").between(60, 410)]
    if candidates.empty:
        return None
    if form.startswith("10-K") and candidates["duration_bucket"].eq("annual").any():
        candidates = candidates[candidates["duration_bucket"].eq("annual")]
    elif form.startswith("10-Q"):
        order = {"nine_month_ytd": 0, "half_ytd": 1, "quarter": 2, "annual": 3, "other": 4}
        candidates["bucket_rank"] = candidates["duration_bucket"].map(order).fillna(9)
        candidates = candidates[candidates["bucket_rank"].eq(candidates["bucket_rank"].min())]
    candidates["duration_distance"] = (
        pd.to_numeric(candidates["duration_days"], errors="coerce")
        - candidates["duration_bucket"].map({"quarter": 91, "half_ytd": 182, "nine_month_ytd": 273, "annual": 365}).fillna(365)
    ).abs()
    return candidates.sort_values(["alias_rank", "duration_distance", "source_tag"]).iloc[0]


def _select_shares(rows: pd.DataFrame) -> pd.Series | None:
    candidates = rows[rows["fact_group"].eq("shares_outstanding")].copy()
    candidates = candidates[pd.to_numeric(candidates["value"], errors="coerce").ge(MIN_VALID_SHARES)]
    if candidates.empty:
        return None
    return candidates.sort_values(["alias_rank", "period", "source_tag"], ascending=[True, False, True]).iloc[0]


def load_price_cache(path: str | Path, tickers: Iterable[str]) -> pd.DataFrame:
    """Load raw close for market cap and adjusted close for return labels."""
    root = quality.repo_path(path)
    if root.is_file():
        raw = quality.read_table(root)
        aliases = {str(c).lower().replace(" ", "_"): c for c in raw.columns}
        ticker_col = aliases.get("ticker") or aliases.get("symbol")
        date_col = aliases.get("date") or aliases.get("timestamp")
        adj_col = aliases.get("adjusted_close") or aliases.get("adj_close") or aliases.get("adjclose")
        close_col = aliases.get("close") or adj_col
        if None in (ticker_col, date_col, adj_col, close_col):
            raise quality.DataContractError("price table needs ticker, date, close, and adjusted_close")
        out = raw[[ticker_col, date_col, close_col, adj_col]].copy()
        out.columns = ["ticker", "date", "raw_close", "adjusted_close"]
    elif root.is_dir():
        frames: list[pd.DataFrame] = []
        for ticker in sorted({str(t).upper().strip() for t in tickers if str(t).strip()}):
            item = root / px_cache_name(ticker)
            if not item.is_file():
                continue
            try:
                px = pd.read_parquet(item)
            except Exception:
                continue
            if isinstance(px.columns, pd.MultiIndex):
                px.columns = px.columns.get_level_values(0)
            if "Close" not in px.columns:
                continue
            adj = "Adj Close" if "Adj Close" in px.columns else "Close"
            frames.append(
                pd.DataFrame(
                    {
                        "ticker": ticker,
                        "date": pd.to_datetime(px.index, errors="coerce").tz_localize(None),
                        "raw_close": pd.to_numeric(px["Close"], errors="coerce").to_numpy(),
                        "adjusted_close": pd.to_numeric(px[adj], errors="coerce").to_numpy(),
                    }
                )
            )
        out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    else:
        raise FileNotFoundError(root)
    if out.empty:
        return pd.DataFrame(columns=["ticker", "date", "raw_close", "adjusted_close"])
    out["ticker"] = out["ticker"].fillna("").astype(str).str.upper().str.strip()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    for column in ("raw_close", "adjusted_close"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out.dropna(subset=["date", "raw_close", "adjusted_close"]).sort_values(["ticker", "date"]).drop_duplicates(
        ["ticker", "date"], keep="last"
    )


def build_events(
    facts: pd.DataFrame,
    filings: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    sources: dict[str, dict[str, str]],
    submissions_sha256: str,
    materiality: float = MATERIALITY,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    prepared, diagnostics = quality.prepare_filings(filings)
    if facts.empty:
        return pd.DataFrame(), {**diagnostics, "status": "no_capital_facts"}
    all_prepared = prepared.copy()
    action_mask = facts["fact_group"].isin(FLOW_GROUPS)
    action_keys = pd.MultiIndex.from_frame(
        facts.loc[action_mask, ["cik10", "accession_key"]].drop_duplicates()
    )
    filing_keys = pd.MultiIndex.from_frame(prepared[["cik10", "accession_key"]])
    prepared = prepared[filing_keys.isin(action_keys)].copy()
    available_tickers = set(prices["ticker"])
    prepared["price_rank"] = (~prepared["ticker"].isin(available_tickers)).astype(int)
    # One economic event per CIK/accession; prefer a current ticker with price data.
    prepared = prepared.sort_values(["cik10", "accession_key", "price_rank", "ticker"]).drop_duplicates(
        ["cik10", "accession_key"], keep="first"
    )
    price_groups = {ticker: group.set_index("date") for ticker, group in prices.groupby("ticker", sort=False)}
    all_dates = prices["date"].tolist() + prepared["accepted_at"].tolist()
    close_map = quality.nyse_market_close_map(all_dates)
    sessions = sorted((pd.Timestamp(date).normalize(), close) for date, close in close_map.items())
    session_dates = [date for date, _ in sessions]
    session_close_ns = np.asarray([int(close.value) for _, close in sessions], dtype=np.int64)
    fact_groups = {
        key: group.copy()
        for key, group in facts.groupby(["cik10", "accession_key"], sort=False)
    }
    accepted_lookup = all_prepared[["cik10", "accession_key", "accepted_ts"]].drop_duplicates(
        ["cik10", "accession_key"], keep="last"
    )
    share_states = facts[facts["fact_group"].eq("shares_outstanding")].merge(
        accepted_lookup, on=["cik10", "accession_key"], how="inner"
    )
    share_states = share_states[pd.to_numeric(share_states["value"], errors="coerce").ge(MIN_VALID_SHARES)].copy()
    share_states_by_cik = {
        cik: group.sort_values(["accepted_ts", "alias_rank", "period"], ascending=[True, True, True])
        for cik, group in share_states.groupby("cik10", sort=False)
    }

    rows: list[dict[str, Any]] = []
    for filing in prepared.itertuples(index=False):
        f = pd.Series(filing._asdict())
        current = fact_groups.get((str(f["cik10"]), str(f["accession_key"])), facts.iloc[0:0]).copy()
        report_period = f.get("period")
        if pd.notna(report_period):
            current = current[current["period"].eq(pd.Timestamp(report_period))].copy()
        elif not current.empty:
            current = current[current["period"].eq(current["period"].max())].copy()
        if current.empty:
            continue
        selected = {group: _select_flow(group, current, str(f["form"])) for group in FLOW_GROUPS}
        if not any(value is not None for value in selected.values()):
            continue
        shares = _select_shares(current)
        # If this action filing does not repeat shares, use the most recently
        # accepted exact-accession share state known by this time.
        if shares is None:
            issuer_states = share_states_by_cik.get(str(f["cik10"]), share_states.iloc[0:0])
            share_candidates = issuer_states[issuer_states["accepted_ts"].le(f["accepted_ts"])].copy()
            if not share_candidates.empty:
                shares = share_candidates.sort_values(
                    ["accepted_ts", "alias_rank", "period"], ascending=[False, True, False]
                ).iloc[0]

        ticker = str(f["ticker"])
        ticker_prices = price_groups.get(ticker)
        market_date = ""
        raw_close = np.nan
        if ticker_prices is not None:
            market_pos = int(np.searchsorted(session_close_ns, int(f["accepted_ts"].value), side="right") - 1)
            if market_pos >= 0:
                candidate_date = session_dates[market_pos]
                if candidate_date in ticker_prices.index:
                    market_date = candidate_date.date().isoformat()
                    raw_close = float(ticker_prices.loc[candidate_date, "raw_close"])
        share_value = float(shares["value"]) if shares is not None else np.nan
        market_cap = share_value * raw_close if np.isfinite(share_value) and np.isfinite(raw_close) else np.nan
        market_cap_valid = bool(
            np.isfinite(market_cap)
            and MIN_VALID_MARKET_CAP <= market_cap <= MAX_VALID_MARKET_CAP
        )
        amounts: dict[str, float] = {}
        raw_amounts: dict[str, float] = {}
        tags: dict[str, str] = {}
        durations: dict[str, float] = {}
        for group, fact in selected.items():
            raw_value = float(fact["value"]) if fact is not None else np.nan
            days = float(fact["duration_days"]) if fact is not None else np.nan
            raw_amounts[group] = raw_value
            durations[group] = days
            tags[group] = str(fact["source_tag"]) if fact is not None else ""
            amounts[group] = raw_value * 365.0 / days if np.isfinite(raw_value) and np.isfinite(days) and days > 0 else np.nan
        repurchase = amounts["repurchase"]
        negatives = [amounts["common_issuance"], amounts["convertible_debt"], amounts["convertible_preferred"]]
        observed_negative = [value for value in negatives if np.isfinite(value)]
        observed_count = int(np.isfinite(repurchase)) + len(observed_negative)
        net_amount = (repurchase if np.isfinite(repurchase) else 0.0) - sum(observed_negative)
        intensity = net_amount / market_cap if observed_count and market_cap_valid else np.nan
        event = "neutral"
        if np.isfinite(intensity) and intensity >= materiality:
            event = "positive"
        elif np.isfinite(intensity) and intensity <= -materiality:
            event = "negative"
        source = sources.get(str(f["cik10"]), {})
        rows.append(
            {
                "ticker": ticker,
                "cik10": f["cik10"],
                "accession_number": f["accession_number"],
                "form": f["form"],
                "fiscal_period": f["period"].date().isoformat() if pd.notna(f["period"]) else "",
                "accepted_at": f["accepted_at"],
                "available_from": f["available_from"],
                "exact_acceptance": True,
                "sec_capital_allocation_event": event,
                "net_capital_return_intensity": intensity,
                "materiality_threshold": float(materiality),
                "market_cap": market_cap,
                "market_cap_valid": market_cap_valid,
                "market_cap_date": market_date,
                "shares_outstanding": share_value,
                "raw_close": raw_close,
                "repurchase_annualized": repurchase,
                "common_issuance_annualized": amounts["common_issuance"],
                "convertible_debt_annualized": amounts["convertible_debt"],
                "convertible_preferred_annualized": amounts["convertible_preferred"],
                "repurchase_raw": raw_amounts["repurchase"],
                "common_issuance_raw": raw_amounts["common_issuance"],
                "convertible_debt_raw": raw_amounts["convertible_debt"],
                "convertible_preferred_raw": raw_amounts["convertible_preferred"],
                "observed_component_count": observed_count,
                "source_tags": quality.canonical_json(tags),
                "duration_days": quality.canonical_json(durations),
                "source_hashes": quality.canonical_json(
                    {**source, "submissions_index_sha256": submissions_sha256, "submissions_row_sha256": f["submissions_row_sha256"]}
                ),
                "pit_caveats": quality.canonical_json(PIT_CAVEATS),
            }
        )
    events = pd.DataFrame(rows)
    if events.empty:
        return events, {**diagnostics, "status": "no_joined_capital_events"}
    events["accepted_ts"] = pd.to_datetime(events["accepted_at"], errors="coerce", utc=True)
    # Identical 8-K/10-Q disclosure of the same action is one economic event.
    signature = [
        "cik10", "fiscal_period", "repurchase_raw", "common_issuance_raw",
        "convertible_debt_raw", "convertible_preferred_raw",
    ]
    events = events.sort_values("accepted_ts").drop_duplicates(signature, keep="first").drop(columns="accepted_ts")
    diagnostics.update(
        {
            "status": "ok",
            "event_count": int(len(events)),
            "positive_count": int(events["sec_capital_allocation_event"].eq("positive").sum()),
            "negative_count": int(events["sec_capital_allocation_event"].eq("negative").sum()),
            "neutral_count": int(events["sec_capital_allocation_event"].eq("neutral").sum()),
            "market_cap_coverage": float(events["market_cap_valid"].mean()),
            "market_cap_invalid_count": int((~events["market_cap_valid"]).sum()),
            "filed_date_fallback_used": False,
            "research_only": True,
        }
    )
    return events.reset_index(drop=True), diagnostics


def label_excess_returns(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    features = events.rename(columns={"sec_capital_allocation_event": "sec_filing_quality_event"})
    price_input = prices[["ticker", "date", "adjusted_close"]]
    labeled = quality.label_forward_returns(features, price_input)
    spy = price_input[price_input["ticker"].eq("SPY")].set_index("date")["adjusted_close"]
    for horizon in HORIZONS:
        excess: list[float] = []
        for row in labeled.itertuples(index=False):
            entry = pd.to_datetime(getattr(row, "entry_date"), errors="coerce")
            if pd.isna(entry) or entry not in spy.index:
                excess.append(np.nan)
                continue
            position = int(spy.index.searchsorted(entry, side="left"))
            exit_position = position + horizon
            if position >= len(spy) or exit_position >= len(spy):
                excess.append(np.nan)
                continue
            benchmark_return = float(spy.iloc[exit_position] / spy.iloc[position] - 1.0)
            raw_return = getattr(row, f"forward_return_{horizon}d")
            excess.append(float(raw_return - benchmark_return) if np.isfinite(raw_return) else np.nan)
        labeled[f"spy_excess_return_{horizon}d"] = excess
    return labeled.rename(columns={"sec_filing_quality_event": "sec_capital_allocation_event"})


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
        horizon_metrics: dict[str, Any] = {"event_count": int(len(scoped))}
        for horizon in HORIZONS:
            column = f"spy_excess_return_{horizon}d"
            positive = pd.to_numeric(scoped.loc[scoped["sec_capital_allocation_event"].eq("positive"), column], errors="coerce").dropna()
            negative = pd.to_numeric(scoped.loc[scoped["sec_capital_allocation_event"].eq("negative"), column], errors="coerce").dropna()
            bootstrap_frame = scoped.rename(
                columns={"sec_capital_allocation_event": "sec_filing_quality_event"}
            ).copy()
            bootstrap_frame[f"forward_return_{horizon}d"] = pd.to_numeric(
                bootstrap_frame[column], errors="coerce"
            )
            lower, upper = quality.cluster_bootstrap_spread(
                bootstrap_frame, f"forward_return_{horizon}d", iterations=iterations, seed=seed + horizon
            )
            horizon_metrics[f"horizon_{horizon}"] = {
                "return_basis": "SPY excess return",
                "positive_count": int(len(positive)),
                "negative_count": int(len(negative)),
                "filing_week_count": int(scoped.loc[
                    scoped["sec_capital_allocation_event"].isin(["positive", "negative"]) & scoped[column].notna(), "filing_week"
                ].nunique()),
                "positive_mean": float(positive.mean()) if not positive.empty else None,
                "negative_mean": float(negative.mean()) if not negative.empty else None,
                "positive_minus_negative": float(positive.mean() - negative.mean()) if not positive.empty and not negative.empty else None,
                "filing_week_cluster_bootstrap_95_lower": lower if np.isfinite(lower) else None,
                "filing_week_cluster_bootstrap_95_upper": upper if np.isfinite(upper) else None,
            }
        metrics[segment] = horizon_metrics
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
        lowers = [metrics[name]["horizon_63"]["filing_week_cluster_bootstrap_95_lower"] for name in ("oos", "oos2")]
        verdict = "PASS_SOURCE_SCREEN" if all(value is not None and value > 0 for value in spreads) and all(
            value is not None and value >= 0 for value in lowers
        ) else "REJECT_SOURCE_SCREEN"
    return labeled, {
        "verdict": verdict,
        "primary_horizon_sessions": 63,
        "secondary_horizons_sessions": [21, 126],
        "return_basis": "SPY excess return; adjusted-close raw returns retained in row output",
        "entry_rule": "first NYSE close strictly after exact accepted_at",
        "oos_start": oos_start,
        "oos2_start": oos2_start,
        "materiality_threshold": MATERIALITY,
        "power_gate": {"positive_per_oos": 100, "negative_per_oos": 100, "filing_weeks_per_oos": 12},
        "segments": metrics,
        "bootstrap": {"cluster": "filing_week", "iterations": iterations, "seed": seed},
        "research_only": True,
        "portfolio_ab_authorized": verdict == "PASS_SOURCE_SCREEN",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companyfacts", default="data_raw/free/sec/companyfacts.zip")
    parser.add_argument("--submissions", default="data_pit/sec/sec_filings_index.parquet")
    parser.add_argument("--prices", default=r"H:\codex\tmp_r1000_grossfloor_20260625\outputs\run287_price_cache_full_candidate\cache_prices")
    parser.add_argument("--output-dir", default="outputs/sec_capital_allocation_event_20260717")
    parser.add_argument("--oos-start", default=OOS_START)
    parser.add_argument("--oos2-start", default=OOS2_START)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=287)
    args = parser.parse_args()

    submissions_path = quality.repo_path(args.submissions)
    output = quality.repo_path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    filings = quality.read_table(submissions_path)
    wanted_ciks = sorted({quality.cik10(value) for value in filings["cik10"] if quality.cik10(value)})
    wanted_tickers = sorted(set(filings["ticker"].fillna("").astype(str).str.upper()) | {"SPY"})
    prices = load_price_cache(args.prices, wanted_tickers)
    fact_cache = output / "capital_facts_accession_cache.parquet"
    if fact_cache.is_file():
        facts = pd.read_parquet(fact_cache)
        sources = {
            str(cik): {
                "companyfacts_sha256": str(group["companyfacts_sha256"].iloc[0]),
                "companyfacts_member": str(group["companyfacts_member"].iloc[0]),
            }
            for cik, group in facts.groupby("cik10", sort=False)
        }
    else:
        facts, sources = load_capital_facts(args.companyfacts, wanted_ciks=wanted_ciks)
        facts.to_parquet(fact_cache, index=False)
    events, diagnostics = build_events(
        facts, filings, prices, sources=sources, submissions_sha256=quality.sha256_file(submissions_path)
    )
    if events.empty:
        raise quality.DataContractError("no exact accepted-time capital-allocation events")
    labeled, summary = source_screen(
        events, prices, oos_start=args.oos_start, oos2_start=args.oos2_start,
        iterations=max(1, int(args.bootstrap_iterations)), seed=int(args.seed),
    )
    paths = {
        "fact_cache": fact_cache,
        "events": output / "sec_capital_allocation_events.parquet",
        "events_csv": output / "sec_capital_allocation_events.csv",
        "screen_rows": output / "source_screen_event_returns.csv",
        "screen_summary": output / "source_screen_summary.json",
        "summary": output / "summary.json",
    }
    events.to_parquet(paths["events"], index=False)
    events.to_csv(paths["events_csv"], index=False)
    labeled.to_csv(paths["screen_rows"], index=False)
    provenance = {
        "companyfacts": quality.fingerprint_path(quality.repo_path(args.companyfacts)),
        "submissions": quality.fingerprint_path(submissions_path),
        "prices": quality.fingerprint_path(quality.repo_path(args.prices)),
        "producer_sha256": quality.sha256_file(Path(__file__)),
    }
    summary = {**summary, "provenance": provenance, "paths": {key: str(value) for key, value in paths.items()}}
    paths["screen_summary"].write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    run_summary = {**diagnostics, "source_screen_verdict": summary["verdict"], "paths": {key: str(value) for key, value in paths.items()}}
    paths["summary"].write_text(json.dumps(run_summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(run_summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
