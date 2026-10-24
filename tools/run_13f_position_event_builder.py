#!/usr/bin/env python3
"""Build PIT 13F position events for post-disclosure alpha studies.

This D1 tool converts quarterly 13F holdings snapshots into event rows keyed by
manager, ticker, and filing availability. It is research-only and does not
change production scoring.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_submissions_collector import cik10  # noqa: E402

DEFAULT_13F = "data_pit/sec/institutional_13f_holdings.parquet"
DEFAULT_OUTPUT_DIR = "outputs/13f_position_events"
DEFAULT_PIT_OUTPUT = "data_pit/sec/13f_position_events.parquet"
DEFAULT_METADATA = "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv"
DEFAULT_MANAGER_UNIVERSE = "research/sec_13f_manager_universe_20260519/managers.csv"

EVENT_COLUMNS = [
    "event_id",
    "source_type",
    "manager_cik",
    "manager_name",
    "manager_rank",
    "external_performance_2y",
    "allocation_tier",
    "ticker",
    "cusip",
    "issuer_name",
    "report_period",
    "filing_date",
    "accepted_at",
    "available_from",
    "event_type",
    "history_boundary",
    "shares",
    "previous_shares",
    "shares_delta",
    "market_value_usd",
    "previous_market_value_usd",
    "value_delta_usd",
    "position_weight",
    "previous_position_weight",
    "position_rank",
    "manager_conviction_rank",
    "issuer_market_cap",
    "issuer_float",
    "issuer_float_pct_owned",
    "manager_stake_to_float",
    "value_delta_to_mcap",
    "dollar_volume_20d",
    "market_cap_bucket",
    "liquidity_bucket",
    "sector",
    "industry",
    "post_disclosure_event_seed_score",
    "research_only",
    "production_activation_allowed",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def num(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def txt(frame: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=object)
    return frame[col].fillna(default).astype(str)


def safe_pct(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def market_cap_bucket(value: float) -> str:
    if not math.isfinite(value) or value <= 0:
        return "unknown"
    if value < 300_000_000:
        return "micro"
    if value < 2_000_000_000:
        return "small"
    if value < 10_000_000_000:
        return "mid"
    if value < 200_000_000_000:
        return "large"
    return "mega"


def liquidity_bucket(value: float) -> str:
    if not math.isfinite(value) or value <= 0:
        return "unknown"
    if value < 5_000_000:
        return "thin"
    if value < 20_000_000:
        return "low"
    if value < 100_000_000:
        return "medium"
    return "high"


def first_present(row: pd.Series, names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in row.index:
            value = row.get(name)
            if pd.notna(value) and str(value).strip() != "":
                return value
    return default


def normalize_holdings(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    d = frame.copy()
    d["manager_cik"] = txt(d, "manager_cik").map(cik10)
    d["ticker"] = txt(d, "ticker_mapped").where(txt(d, "ticker_mapped").str.strip().ne(""), txt(d, "ticker")).str.upper().str.strip()
    d["report_period_ts"] = pd.to_datetime(d.get("report_period"), errors="coerce").dt.normalize()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True)
    d["accepted_at_ts"] = pd.to_datetime(d.get("accepted_at"), errors="coerce", utc=True)
    d["source_accession"] = txt(d, "source_accession").str.strip()
    d["form_type"] = txt(d, "form_type").str.upper().str.strip()
    d["amendment_type"] = txt(d, "amendment_type").str.upper().str.replace(r"[_-]+", " ", regex=True).str.strip()
    d["shares"] = num(d, "shares").clip(lower=0.0)
    d["market_value_usd"] = num(d, "market_value_usd").clip(lower=0.0)
    d = d[d["manager_cik"].ne("") & d["ticker"].ne("") & d["report_period_ts"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    fallback_identity = (
        d["report_period_ts"].astype(str)
        + "|"
        + d["available_from_ts"].astype(str)
        + "|"
        + d["accepted_at_ts"].astype(str)
        + "|"
        + d["form_type"]
    )
    d["filing_identity"] = d["source_accession"].where(d["source_accession"].ne(""), fallback_identity)
    d = d.sort_values(
        ["manager_cik", "available_from_ts", "accepted_at_ts", "report_period_ts", "filing_identity", "ticker"]
    )
    d = d.drop_duplicates(["manager_cik", "filing_identity", "ticker"], keep="last")
    return d


def snapshot_with_weights(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    d = frame.sort_values(["accepted_at_ts", "available_from_ts", "filing_identity"]).drop_duplicates(
        "ticker", keep="last"
    )
    total = d.groupby(["manager_cik", "report_period_ts"])["market_value_usd"].transform("sum").replace(0.0, pd.NA)
    d["position_weight"] = (d["market_value_usd"] / total).fillna(0.0).clip(0.0, 1.0)
    d["position_rank"] = (
        d.groupby(["manager_cik", "report_period_ts"])["market_value_usd"].rank(method="first", ascending=False).fillna(0).astype(int)
    )
    d["manager_conviction_rank"] = (
        d.groupby(["manager_cik", "report_period_ts"])["position_weight"].rank(pct=True).fillna(0.0).clip(0.0, 1.0)
    )
    return d


def metadata_by_ticker(metadata: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if metadata.empty or "ticker" not in metadata.columns:
        return {}
    d = metadata.copy()
    d["ticker"] = txt(d, "ticker").str.upper().str.strip()
    d = d[d["ticker"].ne("")].drop_duplicates("ticker", keep="last")
    out: dict[str, dict[str, Any]] = {}
    for _, row in d.iterrows():
        ticker = str(row.get("ticker", "")).upper().strip()
        mcap = float(pd.to_numeric(pd.Series([first_present(row, ["market_cap_for_audit", "market_cap_live", "market_cap", "mktcap", "current_market_cap"], 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        issuer_float = float(pd.to_numeric(pd.Series([first_present(row, ["issuer_float", "shares_float", "float_shares", "free_float_shares"], 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        dollar_volume = float(pd.to_numeric(pd.Series([first_present(row, ["dollar_volume_20d", "avg_dollar_volume_20d", "avg_dollar_volume", "dollar_volume"], 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        out[ticker] = {
            "issuer_market_cap": mcap,
            "issuer_float": issuer_float,
            "dollar_volume_20d": dollar_volume,
            "sector": str(first_present(row, ["sector", "gics_sector", "sector_name"], "")),
            "industry": str(first_present(row, ["industry", "gics_industry", "sub_industry", "industry_group"], "")),
        }
    return out


def manager_metadata_by_cik(manager_universe: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if manager_universe.empty or "cik10" not in manager_universe.columns:
        return {}
    d = manager_universe.copy()
    d["manager_cik"] = txt(d, "cik10").map(cik10)
    d = d[d["manager_cik"].ne("")].drop_duplicates("manager_cik", keep="last")
    out: dict[str, dict[str, Any]] = {}
    for _, row in d.iterrows():
        cik = str(row.get("manager_cik", "")).strip()
        out[cik] = {
            "manager_rank": float(pd.to_numeric(pd.Series([row.get("user_priority", 0)]), errors="coerce").fillna(0).iloc[0]),
            "external_performance_2y": float(pd.to_numeric(pd.Series([row.get("external_performance_2y", 0)]), errors="coerce").fillna(0.0).iloc[0]),
            "allocation_tier": str(row.get("allocation_tier", "") or ""),
            "manager_label": str(row.get("label", "") or ""),
            "manager_name": str(row.get("manager_name", "") or ""),
        }
    return out


def period_filing_meta(period_frame: pd.DataFrame) -> dict[str, Any]:
    d = period_frame.sort_values(["accepted_at_ts", "available_from_ts"])
    row = d.iloc[-1]
    return {
        "filing_date": str(first_present(row, ["filing_date"], "")),
        "accepted_at": str(first_present(row, ["accepted_at"], "")),
        "available_from": str(first_present(row, ["available_from", "accepted_at"], "")),
        "accepted_at_ts": row.get("accepted_at_ts"),
        "available_from_ts": row.get("available_from_ts"),
        "manager_name": str(first_present(row, ["manager_name"], "")),
    }


def event_type_for(current_shares: float, previous_shares: float, *, initial_period: bool) -> str:
    if initial_period and current_shares > 0 and previous_shares <= 0:
        return "initial"
    if current_shares > 0 and previous_shares <= 0:
        return "new"
    if current_shares <= 0 and previous_shares > 0:
        return "exit"
    if current_shares > 0 and previous_shares > 0 and current_shares > previous_shares:
        return "add"
    if current_shares > 0 and previous_shares > 0 and current_shares < previous_shares:
        return "trim"
    return "hold"


def seed_score(event: dict[str, Any]) -> float:
    event_type = str(event.get("event_type") or "")
    score = {
        "new": 0.35,
        "add": 0.22,
        "hold": 0.06,
        "initial": 0.02,
        "trim": -0.10,
        "exit": -0.25,
    }.get(event_type, 0.0)
    rank = float(event.get("position_rank") or 0.0)
    if 0 < rank <= 10:
        score += 0.16 * (1.0 - min(rank - 1.0, 9.0) / 9.0)
    score += 0.18 * safe_pct(float(event.get("value_delta_to_mcap") or 0.0) / 0.01)
    score += 0.12 * safe_pct(float(event.get("manager_stake_to_float") or 0.0) / 0.01)
    if str(event.get("market_cap_bucket")) in {"micro", "small"} and event_type in {"new", "add"}:
        score += 0.10
    if str(event.get("liquidity_bucket")) in {"thin", "unknown"} and event_type in {"new", "add"}:
        score -= 0.08
    return float(max(-1.0, min(1.0, score)))


def build_position_events(
    holdings: pd.DataFrame,
    metadata: pd.DataFrame | None = None,
    manager_universe: pd.DataFrame | None = None,
) -> pd.DataFrame:
    d = normalize_holdings(holdings)
    if d.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    meta = metadata_by_ticker(metadata if metadata is not None else pd.DataFrame())
    manager_meta = manager_metadata_by_cik(manager_universe if manager_universe is not None else pd.DataFrame())
    rows: list[dict[str, Any]] = []
    for manager_cik, manager_frame in d.groupby("manager_cik", sort=True):
        mgr = manager_meta.get(str(manager_cik), {})
        effective_by_period: dict[pd.Timestamp, pd.DataFrame] = {}
        complete_periods: set[pd.Timestamp] = set()
        ordered = manager_frame.sort_values(
            ["available_from_ts", "accepted_at_ts", "report_period_ts", "filing_identity"]
        )
        for _, filing_rows in ordered.groupby("filing_identity", sort=False):
            filing_rows = filing_rows.copy()
            period = pd.Timestamp(filing_rows["report_period_ts"].iloc[0]).normalize()
            filing = period_filing_meta(filing_rows)
            amendment_types = set(filing_rows["amendment_type"].astype(str)) - {""}
            if "RESTATEMENT" in amendment_types:
                amendment_type = "RESTATEMENT"
            elif "NEW HOLDINGS" in amendment_types:
                amendment_type = "NEW HOLDINGS"
            else:
                amendment_type = ""

            same_period_before = effective_by_period.get(period, pd.DataFrame()).copy()
            period_was_seen = not same_period_before.empty
            filing_snapshot = snapshot_with_weights(filing_rows)
            if amendment_type == "NEW HOLDINGS" and period_was_seen:
                current = snapshot_with_weights(pd.concat([same_period_before, filing_snapshot], ignore_index=True))
            else:
                current = filing_snapshot

            prior_periods = sorted(candidate for candidate in complete_periods if candidate < period)
            later_periods = sorted(candidate for candidate in complete_periods if candidate > period)
            event_period = period
            event_current = current
            ticker_filter: set[str] | None = None
            if later_periods:
                if period_was_seen:
                    before_by_ticker = same_period_before.set_index("ticker", drop=False)
                    corrected_by_ticker = current.set_index("ticker", drop=False)
                    correction_tickers = set(before_by_ticker.index.astype(str)) | set(
                        corrected_by_ticker.index.astype(str)
                    )
                    ticker_filter = {
                        ticker
                        for ticker in correction_tickers
                        if float(
                            corrected_by_ticker.loc[ticker].get("shares", 0.0)
                            if ticker in corrected_by_ticker.index
                            else 0.0
                        )
                        != float(
                            before_by_ticker.loc[ticker].get("shares", 0.0)
                            if ticker in before_by_ticker.index
                            else 0.0
                        )
                        or float(
                            corrected_by_ticker.loc[ticker].get("market_value_usd", 0.0)
                            if ticker in corrected_by_ticker.index
                            else 0.0
                        )
                        != float(
                            before_by_ticker.loc[ticker].get("market_value_usd", 0.0)
                            if ticker in before_by_ticker.index
                            else 0.0
                        )
                    }
                elif amendment_type == "NEW HOLDINGS":
                    # Omission from an additive-only filing is not evidence,
                    # so reconcile only the newly disclosed tickers.
                    ticker_filter = set(current["ticker"].astype(str))
                event_period = later_periods[-1]
                previous = current
                event_current = effective_by_period[event_period].copy()
                history_boundary = False
                emit_only_changes = True
            elif period_was_seen:
                previous = same_period_before
                history_boundary = False
                emit_only_changes = True
            elif amendment_type == "NEW HOLDINGS":
                # An additive-only filing cannot establish omissions or exits.
                previous = pd.DataFrame()
                history_boundary = not prior_periods
                emit_only_changes = False
            else:
                previous = effective_by_period[prior_periods[-1]].copy() if prior_periods else pd.DataFrame()
                history_boundary = not prior_periods
                emit_only_changes = False

            cur = event_current.set_index("ticker", drop=False)
            prev = previous.set_index("ticker", drop=False) if not previous.empty else pd.DataFrame()
            tickers = sorted(set(cur.index.astype(str)) | (set(prev.index.astype(str)) if not prev.empty else set()))
            if ticker_filter is not None:
                tickers = [ticker for ticker in tickers if ticker in ticker_filter]
            for ticker in tickers:
                cur_row = cur.loc[ticker] if ticker in cur.index else pd.Series(dtype=object)
                prev_row = prev.loc[ticker] if not prev.empty and ticker in prev.index else pd.Series(dtype=object)
                shares = float(cur_row.get("shares", 0.0) or 0.0)
                prev_shares = float(prev_row.get("shares", 0.0) or 0.0)
                value = float(cur_row.get("market_value_usd", 0.0) or 0.0)
                prev_value = float(prev_row.get("market_value_usd", 0.0) or 0.0)
                if emit_only_changes and shares == prev_shares and value == prev_value:
                    continue
                event = event_type_for(shares, prev_shares, initial_period=history_boundary)
                m = meta.get(str(ticker).upper(), {})
                issuer_float = float(m.get("issuer_float") or 0.0)
                mcap = float(m.get("issuer_market_cap") or 0.0)
                dollar_volume = float(m.get("dollar_volume_20d") or 0.0)
                shares_delta = shares - prev_shares
                value_delta = value - prev_value
                filing_identity = str(filing_rows["filing_identity"].iloc[0])
                event_period_label = event_period.date().isoformat()
                row = {
                    "event_id": (
                        f"13f:{manager_cik}:{period.date().isoformat()}:{event_period_label}:"
                        f"{filing_identity}:{ticker}"
                    ),
                    "source_type": "13f",
                    "manager_cik": manager_cik,
                    "manager_name": str(
                        mgr.get("manager_name")
                        or cur_row.get("manager_name")
                        or prev_row.get("manager_name")
                        or filing.get("manager_name")
                        or ""
                    ),
                    "manager_rank": float(mgr.get("manager_rank") or 0.0),
                    "external_performance_2y": float(mgr.get("external_performance_2y") or 0.0),
                    "allocation_tier": str(mgr.get("allocation_tier") or ""),
                    "ticker": str(ticker).upper().strip(),
                    "cusip": str(cur_row.get("cusip") or prev_row.get("cusip") or ""),
                    "issuer_name": str(cur_row.get("issuer_name") or prev_row.get("issuer_name") or ""),
                    "report_period": event_period_label,
                    "filing_date": filing["filing_date"],
                    "accepted_at": filing["accepted_at"],
                    "available_from": filing["available_from"],
                    "event_type": event,
                    "history_boundary": bool(history_boundary),
                    "shares": shares,
                    "previous_shares": prev_shares,
                    "shares_delta": shares_delta,
                    "market_value_usd": value,
                    "previous_market_value_usd": prev_value,
                    "value_delta_usd": value_delta,
                    "position_weight": float(cur_row.get("position_weight", 0.0) or 0.0),
                    "previous_position_weight": float(prev_row.get("position_weight", 0.0) or 0.0),
                    "position_rank": int(cur_row.get("position_rank", 0) or 0),
                    "manager_conviction_rank": float(cur_row.get("manager_conviction_rank", 0.0) or 0.0),
                    "issuer_market_cap": mcap,
                    "issuer_float": issuer_float,
                    "issuer_float_pct_owned": float(shares / issuer_float) if issuer_float > 0 else 0.0,
                    "manager_stake_to_float": float(max(shares_delta, 0.0) / issuer_float) if issuer_float > 0 else 0.0,
                    "value_delta_to_mcap": float(value_delta / mcap) if mcap > 0 else 0.0,
                    "dollar_volume_20d": dollar_volume,
                    "market_cap_bucket": market_cap_bucket(mcap),
                    "liquidity_bucket": liquidity_bucket(dollar_volume),
                    "sector": str(m.get("sector") or ""),
                    "industry": str(m.get("industry") or ""),
                    "research_only": True,
                    "production_activation_allowed": False,
                }
                row["post_disclosure_event_seed_score"] = seed_score(row)
                rows.append(row)
            effective_by_period[period] = current
            if amendment_type != "NEW HOLDINGS":
                complete_periods.add(period)
    out = pd.DataFrame(rows)
    for col in EVENT_COLUMNS:
        if col not in out.columns:
            out[col] = False if col in {"history_boundary", "research_only", "production_activation_allowed"} else ""
    return out[EVENT_COLUMNS].sort_values(["available_from", "manager_cik", "ticker"]).reset_index(drop=True)


def build_disclosure_research_events(holdings: pd.DataFrame, filing_receipts: dict) -> list[dict]:
    """Compare complete disclosed constituents without collapsing security classes.

    The supplied receipts must bind the original documents and complete parsing.
    Mapping/coverage failures permit content review, never an inferred exit.
    These are manager-aggregate disclosures, not trades attributed to a fund.
    """
    import hashlib
    keys = ("cusip", "title_of_class", "share_type", "put_call",
            "investment_discretion", "other_manager")
    snapshots, result, incomplete_periods, originals = {}, [], {}, {}
    groups = {str(a): f for a, f in holdings.groupby("source_accession", sort=False)}
    timeline = []
    for accession, receipt in filing_receipts.items():
        frame = groups.get(str(accession), holdings.iloc[:0])
        meta = frame.iloc[0].to_dict() if len(frame) else receipt
        stamp = pd.Timestamp(meta["accepted_at"])
        if pd.isna(stamp) or stamp.tzinfo is None:
            raise ValueError("13F_FILING_CLOCK")
        timeline.append((stamp.tz_convert("UTC"), str(accession), frame, receipt, meta))
    if set(groups) - set(filing_receipts):
        raise ValueError("13F_SOURCE_RECEIPT_REQUIRED")
    for _, accession, frame, receipt, meta in sorted(timeline, key=lambda x: (x[0], x[1])):
        if receipt.get("parsing_status") not in {"PARSED", "PARSED_EMPTY"} or not receipt.get("document_sha256"):
            raise ValueError("13F_SOURCE_RECEIPT_REQUIRED")
        records = [{k: (None if pd.isna(v) else v) for k, v in r.items()}
                   for r in frame.to_dict("records")]
        if not records and receipt.get("parsing_status") != "PARSED_EMPTY":
            raise ValueError("13F_EMPTY_PARSE_PROOF_REQUIRED")
        manager, period = str(meta["manager_cik"]), str(meta["report_period"])
        if any(str(r["manager_cik"]) != manager or str(r["report_period"]) != period for r in records):
            raise ValueError("13F_MIXED_FILING")
        current = {}
        for row in records:
            key = tuple(row.get(k) for k in keys)
            if not key[0] or key in current:
                raise ValueError("13F_AMBIGUOUS_CONSTITUENT_ROWS")
            for name in ("shares", "market_value_usd"):
                if row.get(name) is None or not math.isfinite(float(row[name])) or float(row[name]) < 0:
                    raise ValueError("13F_MISSING_POSITION_MEASURE")
            current[key] = row
        row_sources = {key: accession for key in current}
        amendment = str(meta.get("amendment_type") or "").upper().replace("_", " ").replace("-", " ")
        same = snapshots.get((manager, period))
        complete = receipt.get("complete") is True and receipt.get("mapping_complete") is True
        parent = receipt.get("original_accession")
        forms = {str(r.get("form_type") or "").upper().strip() for r in records} or {str(meta["form_type"])}
        if len(forms) != 1:
            raise ValueError("13F_MIXED_FORM_TYPE")
        is_amendment = next(iter(forms)).endswith("/A")
        amendment_types = {str(r.get("amendment_type") or "").upper().replace("_", " ").replace("-", " ") for r in records} or {amendment}
        amendment_type_known = len(amendment_types) == 1 and amendment in {"RESTATEMENT", "NEW HOLDINGS"}
        if is_amendment and not amendment_type_known:
            complete = False
        # Original identity survives incomplete mapping. A verified full
        # restatement can establish a boundary without a complete old snapshot.
        if not is_amendment:
            root = originals.setdefault((manager, period), accession)
            if root != accession:
                raise ValueError("13F_AMBIGUOUS_ORIGINAL")
        root = originals.get((manager, period))
        lineage_ok = not is_amendment or (root is not None and parent == root)
        if not lineage_ok:
            complete = False
        previous = same
        blocked_accessions = []
        if not is_amendment:
            # Retain old originals, but never skip a known incomplete revision.
            prior_period = (pd.Timestamp(period) - pd.offsets.QuarterEnd()).date().isoformat()
            previous = snapshots.get((manager, prior_period))
            blocked_accessions = list(incomplete_periods.get((manager, prior_period), []))
            if blocked_accessions:
                previous = None
        if is_amendment and amendment_type_known and amendment == "NEW HOLDINGS":
            blocked_accessions = list(incomplete_periods.get((manager, period), []))
            if same is None or blocked_accessions:
                complete = False
            else:
                # Additive reports cannot delete or overwrite an existing constituent.
                if set(current) & set(same["rows"]):
                    raise ValueError("13F_ADDITIVE_OVERLAP_REQUIRES_REVIEW")
                current = {**same["rows"], **current}
                row_sources = {**same["row_sources"], **row_sources}
                complete = lineage_ok and same["complete"] and receipt.get("complete") is True and receipt.get("mapping_complete") is True
        denominator = sum(float(r["market_value_usd"]) for r in current.values())
        prior_rows = previous["rows"] if previous and previous["complete"] and complete else {}
        all_keys = set(current) | set(prior_rows)
        for key in sorted(all_keys, key=str):
            now_row, old_row = current.get(key), prior_rows.get(key)
            row = now_row or old_row
            shares = float(now_row["shares"]) if now_row else None
            old_shares = float(old_row["shares"]) if old_row else None
            weight = float(now_row["market_value_usd"]) / denominator if now_row and denominator > 0 else None
            old_weight = (float(old_row["market_value_usd"]) / previous["denominator"]
                          if old_row and previous["denominator"] > 0 else None)
            if not complete:
                kind = "DISCLOSURE_REVIEW_INCOMPLETE"
            elif not previous or not previous["complete"]:
                kind = "INITIAL_OBSERVATION"
            elif now_row is None:
                kind = "REPORTED_POSITION_REMOVAL"
            elif old_row is None:
                kind = "NEW_REPORTED_POSITION"
            elif shares > old_shares:
                kind = "REPORTED_SHARES_INCREASE"
            elif shares < old_shares:
                kind = "REPORTED_SHARES_DECREASE"
            elif weight != old_weight:
                kind = "WEIGHT_CHANGE_ONLY"
            else:
                continue
            identity = [manager, period, str(accession), receipt["document_sha256"], key]
            evidence = [("CURRENT_REPORT", accession)]
            if is_amendment and lineage_ok:
                evidence.append(("VERIFIED_ORIGINAL", root))
            evidence.extend(("CURRENT_CONSTITUENT", a) for a in sorted(set(row_sources.values())))
            if previous:
                evidence.extend(("PRIOR_CONSTITUENT", a) for a in sorted(set(previous["row_sources"].values())))
            evidence.extend(("INCOMPLETE_COMPARISON_BOUNDARY", a) for a in blocked_accessions)
            source_accession = row_sources[key] if now_row else previous["row_sources"][key]
            result.append(dict(event_id="SEC:" + hashlib.sha256(json.dumps(identity).encode()).hexdigest(),
                source_type="SEC_FILING", family="13F", accession=str(accession), manager_cik=manager,
                report_period=period, ticker=row.get("ticker_mapped"), issuer_cik10=row.get("issuer_cik10"),
                document_sha256=receipt["document_sha256"], form_type=meta.get("form_type"),
                accepted_at=meta["accepted_at"], available_at=meta["available_from"],
                event_type=kind, constituent_identity=dict(zip(keys, key)), source_row=row,
                source_row_accession=source_accession,
                previous_source_row=old_row,
                evidence_refs=[dict(role=role, accession=a, document_sha256=filing_receipts[a]["document_sha256"],
                                    cover_document_sha256=filing_receipts[a].get("cover_document_sha256"))
                               for role, a in evidence],
                shares=shares, previous_shares=old_shares,
                shares_delta=shares-old_shares if shares is not None and old_shares is not None else None,
                position_weight=weight, previous_position_weight=old_weight,
                weight_delta=weight-old_weight if weight is not None and old_weight is not None else None,
                reported_value_denominator=denominator, denominator_complete=complete,
                is_amendment=is_amendment, original_accession=parent, amendment_type=amendment,
                amendment_type_recognized=amendment_type_known if is_amendment else None,
                prior_accession=previous["accession"] if previous else None,
                comparison_blocker="INCOMPLETE_PRIOR_DISCLOSURE" if blocked_accessions else None,
                comparison_blocker_accessions=blocked_accessions,
                scope="MANAGER_AGGREGATE_DISCLOSED_CONSTITUENT", fund_trade_attribution=False,
                trade_inferred=False, liquidation_confirmed=False,
                research_only=True, score_contribution=0, production_activation_allowed=False))
        # Keep verified root identity separate from complete comparison state.
        if complete:
            snapshots[manager, period] = dict(rows=current, row_sources=row_sources, complete=True, accession=str(accession),
                original_accession=root,
                period=period, denominator=denominator)
            incomplete_periods.pop((manager, period), None)
        elif lineage_ok:
            # An unlinked/rejected revision cannot invalidate an accepted root.
            incomplete_periods.setdefault((manager, period), []).append(str(accession))
    return result


def render_report(summary: dict[str, Any], events: pd.DataFrame) -> str:
    lines = [
        "# 13F Position Events",
        "",
        "Research-only event table for post-disclosure alpha studies.",
        "",
        f"- event rows: {summary.get('event_rows', 0)}",
        f"- manager count: {summary.get('manager_count', 0)}",
        f"- ticker count: {summary.get('ticker_count', 0)}",
        f"- latest available_from: `{summary.get('latest_available_from', '')}`",
        "",
        "## Event Counts",
        "",
        "| event_type | rows |",
        "| --- | ---: |",
    ]
    counts = events["event_type"].value_counts().to_dict() if "event_type" in events else {}
    for key, value in sorted(counts.items()):
        lines.append(f"| {key} | {int(value)} |")
    lines.extend(
        [
            "",
            "## Top Seed Events",
            "",
            "| available_from | manager | ticker | type | seed | mcap bucket | value delta |",
            "| --- | --- | --- | --- | ---: | --- | ---: |",
        ]
    )
    if not events.empty:
        top = events.sort_values("post_disclosure_event_seed_score", ascending=False).head(20)
        for _, row in top.iterrows():
            lines.append(
                "| {available} | {manager} | {ticker} | {event} | {score:.3f} | {bucket} | {delta:.0f} |".format(
                    available=row.get("available_from", ""),
                    manager=row.get("manager_name", ""),
                    ticker=row.get("ticker", ""),
                    event=row.get("event_type", ""),
                    score=float(row.get("post_disclosure_event_seed_score", 0.0)),
                    bucket=row.get("market_cap_bucket", ""),
                    delta=float(row.get("value_delta_usd", 0.0)),
                )
            )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    holdings_path = repo_path(args.holdings)
    metadata_path = repo_path(args.metadata)
    manager_universe_path = repo_path(getattr(args, "manager_universe", DEFAULT_MANAGER_UNIVERSE))
    pit_output = repo_path(args.pit_output)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    holdings = read_table(holdings_path)
    metadata = read_table(metadata_path)
    manager_universe = read_table(manager_universe_path)
    events = build_position_events(holdings, metadata, manager_universe)
    write_table(events, pit_output)
    write_table(events, output_dir / "13f_position_events.csv")
    latest = events.copy()
    if not latest.empty and "available_from" in latest.columns:
        latest_ts = pd.to_datetime(latest["available_from"], errors="coerce", utc=True)
        latest = latest[latest_ts.eq(latest_ts.max())].copy() if latest_ts.notna().any() else latest.head(0)
    write_table(latest, output_dir / "latest.csv")

    available = pd.to_datetime(events.get("available_from"), errors="coerce", utc=True) if not events.empty else pd.Series(dtype="datetime64[ns, UTC]")
    accepted = pd.to_datetime(events.get("accepted_at"), errors="coerce", utc=True) if not events.empty else pd.Series(dtype="datetime64[ns, UTC]")
    comparable = available.notna() & accepted.notna()
    summary = {
        "status": "completed" if not events.empty else "blocked",
        "reason": "" if not events.empty else "missing 13F holdings with mapped tickers",
        "schema_version": "13f-position-events-v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "holdings": str(holdings_path),
        "metadata": str(metadata_path),
        "manager_universe": str(manager_universe_path),
        "pit_output": str(pit_output),
        "event_rows": int(len(events)),
        "latest_rows": int(len(latest)),
        "manager_count": int(events["manager_cik"].nunique()) if not events.empty else 0,
        "ticker_count": int(events["ticker"].nunique()) if not events.empty else 0,
        "latest_available_from": available.max().isoformat() if not events.empty and available.notna().any() else "",
        "missing_available_from": int(available.isna().sum()) if not events.empty else 0,
        "available_from_before_accepted_at": int((available[comparable] < accepted[comparable]).sum()) if not events.empty else 0,
        "event_counts": events["event_type"].value_counts().to_dict() if not events.empty else {},
        "outputs": {
            "pit_output": str(pit_output),
            "events_csv": str(output_dir / "13f_position_events.csv"),
            "latest_csv": str(output_dir / "latest.csv"),
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, events), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "event_rows": summary["event_rows"]}, sort_keys=True))
    return summary


DISCLOSURE_AUTHORITY = dict(research_only=True, score_contribution=0,
    production_activation_allowed=False, canonical_write=False, selector_eligible=False,
    portfolio=False, orders_allowed=False, dispatch=False, economic_admission=False,
    fund_trade_attribution=False, trade_inferred=False, liquidation_confirmed=False)


def _disclosure_codec(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _disclosure_digest(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def _disclosure_source():
    from tools import run_sec_13f_parser
    return run_sec_13f_parser


def _disclosure_safe(path):
    import os
    path = Path(path).absolute()
    for p in (path, *path.parents):
        _disclosure_source().disclosure_need(not p.is_symlink() and
            not getattr(p, "is_junction", lambda: False)(), "13F_STORE_PATH_ALIAS")
    if path.exists():
        _disclosure_source().disclosure_need(path.is_dir() or
            (path.is_file() and os.stat(path).st_nlink == 1), "13F_STORE_FILE_TYPE")
    return path


def _disclosure_atomic(path, value):
    import os
    import uuid
    path = _disclosure_safe(path)
    temporary = _disclosure_safe(path.with_name(path.name + ".tmp." + uuid.uuid4().hex))
    with temporary.open("xb") as stream:
        stream.write(_disclosure_codec(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _disclosure_put(root, raw):
    import os
    _disclosure_source().disclosure_need(len(raw) <= _disclosure_source().DISCLOSURE_FILE_LIMIT,
                                       "13F_ARTIFACT_BYTE_BUDGET")
    digest = _disclosure_digest(raw)
    path = _disclosure_safe(root / "artifacts" / digest)
    if path.exists():
        _disclosure_source().disclosure_need(path.read_bytes() == raw, "13F_ARTIFACT_CONFLICT")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return dict(path="artifacts/" + digest, sha256=digest)


def _disclosure_ref(root, ref):
    import re
    need = _disclosure_source().disclosure_need
    need(type(ref) is dict and set(ref) == {"path", "sha256"} and
         type(ref["sha256"]) is str and re.fullmatch("[0-9a-f]{64}", ref["sha256"]) and
         ref["path"] == "artifacts/" + ref["sha256"], "13F_STORE_REFERENCE")
    path = _disclosure_safe(root / ref["path"])
    raw = _disclosure_source().disclosure_read(path)
    need(_disclosure_digest(raw) == ref["sha256"], "13F_STORE_HASH")
    return raw


def _disclosure_code_pins():
    return {name: _disclosure_digest((REPO_ROOT / name).read_bytes()) for name in (
        "tools/run_13f_position_event_builder.py", "tools/run_sec_13f_parser.py",
        "tools/run_sec_submissions_collector.py")}


def _disclosure_events(validated):
    return build_disclosure_research_events(validated["holdings"], validated["filing_receipts"])


def _disclosure_prefix(validated):
    result = []
    frame = validated["holdings"]
    for accession, receipt in validated["filing_receipts"].items():
        rows = _disclosure_source().disclosure_records(frame[frame["source_accession"] == accession])
        result.append(dict(accession=accession, manager_cik=receipt["manager_cik"],
            report_period=receipt["report_period"], form_type=receipt["form_type"],
            accepted_at=receipt["accepted_at"], available_from=receipt["available_from"],
            document_sha256=receipt["document_sha256"],
            cover_document_sha256=receipt["cover_document_sha256"],
            rows_sha256=_disclosure_digest(_disclosure_codec(rows)),
            original_accession=receipt["original_accession"], amendment_type=receipt["amendment_type"]))
    return result


def _disclosure_event_table(events, generation):
    return pd.DataFrame([dict(generation_id=generation, event_id=e["event_id"],
                              event_json=_disclosure_codec(e).decode("utf-8")) for e in events],
                        columns=["generation_id", "event_id", "event_json"])


def read_disclosure_generation(root, *, historical=False, _pointer_path=None):
    """Verify every current-generation byte and recompute its complete timeline.

    A parent identifier records history only: comparison operands are all present
    in this generation's verified, self-contained Source prefix.
    """
    source = _disclosure_source()
    need = source.disclosure_need
    root = _disclosure_safe(root)
    pointer_path = _pointer_path if _pointer_path is not None else root / "current_generation.json"
    pointer = source.disclosure_json(source.disclosure_read(_disclosure_safe(pointer_path)))
    need(pointer.get("schema") == "sec-13f-disclosure-pointer-v1", "13F_POINTER_SCHEMA")
    manifest = source.disclosure_json(_disclosure_ref(root, pointer["manifest_ref"]))
    need(manifest.get("schema") == "sec-13f-disclosure-generation-v1" and
         manifest["generation_id"] == pointer["generation_id"], "13F_GENERATION_SCHEMA")
    need(manifest["code_sha256"] == _disclosure_code_pins(), "13F_DERIVATION_CODE_CHANGED")
    need(type(manifest["source_refs"]) is dict and len(manifest["source_refs"]) <= 1600,
         "13F_SOURCE_FILE_COUNT")
    inputs = {}
    for key, ref in manifest["source_refs"].items():
        inputs[key] = _disclosure_ref(root, ref)
        need(sum(map(len, inputs.values())) <= source.DISCLOSURE_BUNDLE_LIMIT, "13F_SOURCE_BUNDLE_BUDGET")
    identity = dict(source_sha256={k: _disclosure_digest(v) for k, v in inputs.items()},
                    manager_scope=manifest["manager_scope"], decision_at=manifest["decision_at"],
                    code_sha256=manifest["code_sha256"])
    need(_disclosure_digest(_disclosure_codec(identity)) == manifest["input_identity_sha256"],
         "13F_INPUT_IDENTITY")
    logical = dict(input_identity_sha256=manifest["input_identity_sha256"],
                   parent_generation_id=manifest["parent_generation_id"])
    need(_disclosure_digest(_disclosure_codec(logical)) == manifest["generation_id"],
         "13F_GENERATION_IDENTITY")
    validated = source.verify_disclosure_source_inputs(inputs, manager_ciks=manifest["manager_scope"],
                                                       decision_at=manifest["decision_at"])
    expected_metadata = dict(filing_receipts=validated["filing_receipts"],
        source_coverage=validated["source_coverage"],
        source_status=validated["source_status"], source_checks=validated["source_checks"],
        last_successful_source_check=validated["last_successful_source_check"],
        latest_accepted_at=validated["latest_accepted_at"].isoformat() if validated["latest_accepted_at"] else None,
        current_source_eligible=True, aggregate_analysis_admitted=False,
        due_quarter_coverage=validated["due_quarter_coverage"])
    need(all(_disclosure_codec(manifest[k]) == _disclosure_codec(v)
             for k, v in expected_metadata.items()), "13F_STORED_SOURCE_METADATA")
    derivation = _disclosure_digest(_disclosure_codec(dict(code_sha256=manifest["code_sha256"],
        manager_scope=manifest["manager_scope"],
        mapping_sha256={k: v for k, v in identity["source_sha256"].items() if k.startswith("cusip_map.")})))
    need(manifest["derivation_contract_sha256"] == derivation, "13F_STORED_DERIVATION_CONTRACT")
    need(source.exact_utc(manifest["decision_at"]) <= source.exact_utc(manifest["generated_at"]) <=
         datetime.now(timezone.utc), "13F_STORED_GENERATION_CLOCK")
    need(manifest["filing_prefix"] == _disclosure_prefix(validated), "13F_STORED_PREFIX")
    events = _disclosure_events(validated)
    need(type(manifest["event_count"]) is int and len(events) <= 20000 and
         len(events) == manifest["event_count"] == len(manifest["events"]),
         "13F_STORED_EVENT_COUNT")
    seen = set()
    for event, stored in zip(events, manifest["events"]):
        need(event["event_id"] not in seen and stored["event_id"] == event["event_id"] and
             _disclosure_ref(root, stored["ref"]) == _disclosure_codec(event), "13F_STORED_EVENT_SEMANTICS")
        seen.add(event["event_id"])
        for evidence in event["evidence_refs"]:
            need(evidence["accession"] in validated["filing_receipts"] and
                 all(evidence[k] == validated["filing_receipts"][evidence["accession"]][k]
                     for k in ("document_sha256", "cover_document_sha256")),
                 "13F_CONSTITUENT_RAW_LINEAGE")
    outputs = {k: _disclosure_ref(root, r) for k, r in manifest["outputs"].items()}
    csv = source._disclosure_table(outputs["csv"])
    parquet = source._disclosure_table(outputs["parquet"], True)
    expected = _disclosure_event_table(events, manifest["generation_id"])
    need(csv.to_dict("records") == parquet.to_dict("records") == expected.to_dict("records"),
         "13F_EVENT_TABLE_PARITY")
    summary = source.disclosure_json(outputs["summary"])
    need(summary["generation_id"] == manifest["generation_id"] and
         type(summary["row_count"]) is int and summary["row_count"] == len(events) and
         summary["output_sha256"] == {k: _disclosure_digest(outputs[k]) for k in ("csv", "parquet")},
         "13F_EVENT_SUMMARY_PARITY")
    need(all(manifest.get(k) == v and type(manifest.get(k)) is type(v)
             for k, v in DISCLOSURE_AUTHORITY.items()), "13F_STORED_AUTHORITY")
    if not historical:
        attempt = source.disclosure_json(source.disclosure_read(_disclosure_safe(root / "attempt.json")))
        need(attempt.get("status") == "COMPLETED_DISCLOSURE_STORAGE" and
             attempt.get("generation_id") == manifest["generation_id"] and
             attempt.get("current_eligible") is True, "13F_CURRENT_ATTEMPT_NOT_SUCCESSFUL")
        now = datetime.now(timezone.utc)
        need(source.exact_utc(manifest["decision_at"]) <= now and
             now - source.exact_utc(validated["last_successful_source_check"]) <
             source.timedelta(hours=36), "STALE")
    return manifest


def run_disclosure_generation(*, holdings, filings_index, raw_dir, cusip_map,
                              manager_ciks, output_root, decision_at):
    """One serial, offline research transaction. No collector or Main dispatch."""
    import io
    import os
    source = _disclosure_source()
    need = source.disclosure_need
    root = _disclosure_safe(repo_path(output_root))
    # Typed storage cannot be nested in, or replace, any supplied Source tree.
    protected = [Path(holdings).absolute().parent, Path(filings_index).absolute().parent,
                 Path(raw_dir).absolute(), Path(cusip_map).absolute().parent]
    need(all(not root.is_relative_to(p) and not p.is_relative_to(root) for p in protected),
         "13F_SOURCE_OUTPUT_OVERLAP")
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "store.json"
    if marker.exists():
        need(source.disclosure_json(source.disclosure_read(_disclosure_safe(marker))) ==
             {"schema": "sec-13f-disclosure-store-v1"}, "13F_STORE_OWNER")
    else:
        need(not list(root.iterdir()), "13F_OUTPUT_NOT_EMPTY")
        _disclosure_atomic(marker, {"schema": "sec-13f-disclosure-store-v1"})
    lock = _disclosure_safe(root / ".writer.lock")
    with lock.open("x") as stream:
        stream.write("SEC13F_DISCLOSURE_SINGLE_WRITER")
    generated = datetime.now(timezone.utc).isoformat()
    attempt = dict(schema="sec-13f-disclosure-attempt-v1", status="BUILDING",
                   generated_at=generated, decision_at=decision_at, current_eligible=False,
                   new_events=0, new_notification_intents=0, notifications_sent=0,
                   **DISCLOSURE_AUTHORITY)
    try:
        _disclosure_atomic(root / "attempt.json", attempt)
        need(source.exact_utc(decision_at) <= datetime.now(timezone.utc), "13F_FUTURE_DECISION")
        previous = read_disclosure_generation(root, historical=True) if (root / "current_generation.json").exists() else None
        inputs = source.load_disclosure_source_inputs(holdings=holdings, filings_index=filings_index,
            raw_dir=raw_dir, cusip_map=cusip_map, manager_ciks=manager_ciks)
        validated = source.verify_disclosure_source_inputs(inputs, manager_ciks=manager_ciks, decision_at=decision_at)
        need(datetime.now(timezone.utc) - source.exact_utc(validated["last_successful_source_check"]) <
             source.timedelta(hours=36), "STALE")
        code = _disclosure_code_pins()
        identity = dict(source_sha256={k: _disclosure_digest(v) for k, v in inputs.items()},
                        manager_scope=validated["manager_scope"], decision_at=decision_at, code_sha256=code)
        input_id = _disclosure_digest(_disclosure_codec(identity))
        prefix = _disclosure_prefix(validated)
        derivation = _disclosure_digest(_disclosure_codec(dict(code_sha256=code,
            manager_scope=validated["manager_scope"],
            mapping_sha256={k: v for k, v in identity["source_sha256"].items() if k.startswith("cusip_map.")})))
        if previous:
            need(previous["derivation_contract_sha256"] == derivation, "13F_DERIVATION_CONTEXT_CONFLICT")
            prior_by_acc = {r["accession"]: r for r in previous["filing_prefix"]}
            current_by_acc = {r["accession"]: r for r in prefix}
            need(all(current_by_acc.get(a) == r for a, r in prior_by_acc.items()), "13F_HISTORY_PREFIX_CONFLICT")
            for manager in validated["manager_scope"]:
                old = [r for r in previous["filing_prefix"] if r["manager_cik"] == manager]
                new = [r for r in prefix if r["manager_cik"] == manager and r["accession"] not in prior_by_acc]
                if old:
                    last = max(source.exact_utc(r["accepted_at"]) for r in old)
                    need(all(source.exact_utc(r["accepted_at"]) >= last for r in new), "13F_HISTORY_BACKFILL_CONFLICT")
        if previous and previous["input_identity_sha256"] == input_id:
            attempt.update(status="COMPLETED_DISCLOSURE_STORAGE", generation_id=previous["generation_id"],
                           current_eligible=True, replayed=True)
            _disclosure_atomic(root / "attempt.json", attempt)
            read_disclosure_generation(root)
            return attempt
        events = _disclosure_events(validated)
        need(len(events) <= 20000 and len({e["event_id"] for e in events}) == len(events), "13F_EVENT_BUDGET_OR_DUPLICATE")
        previous_events = {e["event_id"]: e["ref"] for e in previous["events"]} if previous else {}
        current_events = {e["event_id"]: e for e in events}
        need(all(e in current_events and _disclosure_ref(root, r) == _disclosure_codec(current_events[e])
                 for e, r in previous_events.items()), "13F_EVENT_CONTEXT_CONFLICT")
        root.joinpath("artifacts").mkdir(exist_ok=True)
        source_refs = {k: _disclosure_put(root, v) for k, v in inputs.items()}
        parent_id = previous["generation_id"] if previous else None
        generation = _disclosure_digest(_disclosure_codec(dict(input_identity_sha256=input_id,
                                                               parent_generation_id=parent_id)))
        stored_events = [dict(event_id=e["event_id"], ref=_disclosure_put(root, _disclosure_codec(e))) for e in events]
        table = _disclosure_event_table(events, generation)
        buffer = io.BytesIO()
        table.to_parquet(buffer, index=False)
        output_bytes = dict(csv=table.to_csv(index=False).encode("utf-8"), parquet=buffer.getvalue())
        output_bytes["summary"] = _disclosure_codec(dict(schema="sec-13f-disclosure-tables-v1",
            generation_id=generation, row_count=len(events),
            output_sha256={k: _disclosure_digest(v) for k, v in output_bytes.items()}))
        outputs = {k: _disclosure_put(root, v) for k, v in output_bytes.items()}
        manifest = dict(schema="sec-13f-disclosure-generation-v1", generation_id=generation,
            input_identity_sha256=input_id, derivation_contract_sha256=derivation,
            parent_generation_id=parent_id, parent_purpose="HISTORY_ONLY_SELF_CONTAINED_COMPARISON_PREFIX",
            generated_at=datetime.now(timezone.utc).isoformat(), decision_at=decision_at,
            manager_scope=validated["manager_scope"], code_sha256=code, source_refs=source_refs,
            filing_prefix=prefix, filing_receipts=validated["filing_receipts"],
            source_status=validated["source_status"], source_checks=validated["source_checks"],
            source_coverage=validated["source_coverage"],
            last_successful_source_check=validated["last_successful_source_check"],
            latest_accepted_at=validated["latest_accepted_at"].isoformat() if validated["latest_accepted_at"] else None,
            current_source_eligible=True, aggregate_analysis_admitted=False,
            due_quarter_coverage=validated["due_quarter_coverage"],
            event_count=len(events), events=stored_events, outputs=outputs, **DISCLOSURE_AUTHORITY)
        manifest_ref = _disclosure_put(root, _disclosure_codec(manifest))
        # Verify through the same reader before publishing the current pointer.
        pending = root / "pending_generation.json"
        _disclosure_atomic(pending, dict(schema="sec-13f-disclosure-pointer-v1",
                                        generation_id=generation, manifest_ref=manifest_ref))
        # The reader accepts an explicit immutable pointer during this one lock.
        _verify_disclosure_pending(root, pending)
        _disclosure_atomic(root / "current_generation.json",
                           source.disclosure_json(source.disclosure_read(pending)))
        attempt.update(status="COMPLETED_DISCLOSURE_STORAGE", generation_id=generation,
            current_eligible=True, replayed=False, new_events=len(set(current_events) - set(previous_events)))
        _disclosure_atomic(root / "attempt.json", attempt)
        read_disclosure_generation(root)
        pending.unlink()
        return attempt
    except (ValueError, OSError, KeyError, TypeError, RecursionError) as error:
        reason = str(error) if isinstance(error, ValueError) and str(error).replace("_", "").isalnum() else (
            "SOURCE_UNAVAILABLE" if isinstance(error, OSError) else "13F_INPUT_CONTRACT_ERROR")
        attempt.update(status="BLOCKED_DISCLOSURE_STORAGE", reason=reason, current_eligible=False, new_events=0)
        _disclosure_atomic(root / "attempt.json", attempt)
        return attempt
    finally:
        lock.unlink()


def _verify_disclosure_pending(root, pending):
    # Select a pointer without replacing the historical success pointer.
    read_disclosure_generation(root, historical=True, _pointer_path=pending)


def _disclosure_refuse_owned_store(output_root, reason, decision_at):
    """Invalidate a named owned store on CLI prerequisite failure, without claiming another lock."""
    if not output_root:
        return
    root = _disclosure_safe(repo_path(output_root))
    marker = root / "store.json"
    if not root.is_dir() or not marker.is_file():
        return
    source = _disclosure_source()
    if source.disclosure_json(source.disclosure_read(_disclosure_safe(marker))) != {"schema": "sec-13f-disclosure-store-v1"}:
        return
    lock = _disclosure_safe(root / ".writer.lock")
    with lock.open("x") as stream:
        stream.write("SEC13F_DISCLOSURE_PREFLIGHT_REFUSAL")
    try:
        _disclosure_atomic(root / "attempt.json", dict(schema="sec-13f-disclosure-attempt-v1",
            status="BLOCKED_DISCLOSURE_STORAGE", generated_at=datetime.now(timezone.utc).isoformat(),
            decision_at=decision_at, current_eligible=False, reason=reason,
            new_events=0, new_notification_intents=0, notifications_sent=0, **DISCLOSURE_AUTHORITY))
    finally:
        lock.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", default=DEFAULT_13F)
    parser.add_argument("--metadata", default=DEFAULT_METADATA)
    parser.add_argument("--manager-universe", default=DEFAULT_MANAGER_UNIVERSE)
    parser.add_argument("--pit-output", default=DEFAULT_PIT_OUTPUT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--disclosure-research", action="store_true",
                        help="Offline source-bound typed generation; no Main research admission")
    parser.add_argument("--filings-index", default="data_pit/sec/sec_filings_index.parquet")
    parser.add_argument("--raw-dir", default="data_raw/sec")
    parser.add_argument("--cusip-map", default="")
    parser.add_argument("--manager-ciks", default="", help="Explicit comma-separated manager CIK10 scope")
    parser.add_argument("--decision-at", default="")
    parser.add_argument("--disclosure-output-dir", default="", help="Explicit separate standalone store")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.disclosure_research:
        if not all((args.cusip_map, args.manager_ciks, args.decision_at, args.disclosure_output_dir)):
            try:
                _disclosure_refuse_owned_store(args.disclosure_output_dir, "13F_RESEARCH_ARGUMENTS_REQUIRED", args.decision_at)
            except (ValueError, OSError, KeyError, TypeError, RecursionError):
                pass  # Unowned, aliased or locked stores must remain untouched.
            print(json.dumps(dict(status="blocked", reason="13F_RESEARCH_ARGUMENTS_REQUIRED")))
            return 2
        try:
            payload = run_disclosure_generation(holdings=repo_path(args.holdings),
                filings_index=repo_path(args.filings_index), raw_dir=repo_path(args.raw_dir),
                cusip_map=repo_path(args.cusip_map), manager_ciks=args.manager_ciks.split(","),
                output_root=repo_path(args.disclosure_output_dir), decision_at=args.decision_at)
        except (ValueError, OSError, KeyError, TypeError, RecursionError):
            payload = dict(status="blocked", reason="13F_STORE_PREFLIGHT_REFUSED")
            try:
                _disclosure_refuse_owned_store(args.disclosure_output_dir, payload["reason"], args.decision_at)
            except (ValueError, OSError, KeyError, TypeError, RecursionError):
                pass
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload.get("status") == "COMPLETED_DISCLOSURE_STORAGE" else 2
    payload = run(args)
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
