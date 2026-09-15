#!/usr/bin/env python3
"""Build shadow institutional ownership signals from SEC 13F holdings.

H1 invariant: security identity is preserved before any stock-level aggregation.
CALL/PUT/PRN rows remain auditable but cannot overwrite or masquerade as cash
common-stock evidence. This module is research-only and does not change targets.
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

from tools.run_sec_submissions_collector import cik10, repo_path  # noqa: E402

DEFAULT_13F = "data_pit/sec/institutional_13f_holdings.parquet"
DEFAULT_OUTPUT_DIR = "outputs/sec_institutional_signals"

SECURITY_IDENTITY_COLUMNS = [
    "cusip",
    "title_of_class",
    "put_call",
    "share_type",
    "investment_discretion",
    "other_manager",
]

INSTITUTIONAL_SIGNAL_COLUMNS = [
    "ticker",
    "latest_available_from",
    "sec_13f_manager_count",
    "sec_13f_buying_manager_count",
    "sec_13f_selling_manager_count",
    "sec_13f_new_position_manager_count",
    "sec_13f_total_value_usd",
    "sec_13f_value_delta_usd",
    "sec_13f_shares_delta",
    "sec_13f_consensus_buy_score",
    "sec_13f_conviction_score",
    "sec_13f_accumulation_score",
    "sec_13f_new_position_score",
    "sec_13f_crowding_score",
    "sec_13f_stale_penalty",
    "sec_13f_smart_money_score",
    "institutional_evidence_score",
    "institutional_evidence_confidence_score",
]


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _safe_pct(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def _log_score(value: float, scale: float) -> float:
    if value <= 0 or scale <= 0:
        return 0.0
    return _safe_pct(math.log1p(value) / math.log1p(scale))


def _norm_identity_text(value: Any, *, upper: bool = True) -> str:
    text = " ".join(str(value or "").strip().split())
    return text.upper() if upper else text


def _normalize_other_manager(value: Any) -> str:
    raw = str(value or "").replace(";", ",")
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return ",".join(sorted(set(values)))


def _security_identity_frame(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    for column in SECURITY_IDENTITY_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    out["cusip"] = out["cusip"].fillna("").astype(str).str.upper().str.replace(r"[^A-Z0-9*@#]", "", regex=True)
    out["title_of_class"] = out["title_of_class"].map(_norm_identity_text)
    out["put_call"] = out["put_call"].fillna("").astype(str).str.upper().str.strip()
    out["share_type"] = out["share_type"].fillna("").astype(str).str.upper().str.strip()
    out["investment_discretion"] = out["investment_discretion"].map(_norm_identity_text)
    out["other_manager"] = out["other_manager"].map(_normalize_other_manager)
    required = ["cusip", "title_of_class", "share_type", "investment_discretion"]
    if out[required].eq("").any(axis=None):
        raise ValueError("13f_security_identity_required_field_missing")
    bad_put_call = ~out["put_call"].isin(["", "CALL", "PUT"])
    if bad_put_call.any():
        raise ValueError("13f_security_identity_invalid_put_call")
    bad_share_type = ~out["share_type"].isin(["SH", "PRN"])
    if bad_share_type.any():
        raise ValueError("13f_security_identity_invalid_share_type")
    out["security_identity"] = out[SECURITY_IDENTITY_COLUMNS].astype(str).agg("|".join, axis=1)
    out["cash_equity_eligible"] = out["put_call"].eq("") & out["share_type"].eq("SH")
    return out


def apply_13f_amendment_semantics(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    effective_groups: list[pd.DataFrame] = []
    for _, group in frame.groupby(["manager_cik", "report_period_ts"], sort=False):
        restatements = group[group["amendment_type"].eq("RESTATEMENT")].copy()
        if restatements.empty:
            effective_groups.append(group)
            continue
        latest_restatement = restatements.sort_values(["accepted_at_ts", "source_accession"]).iloc[-1]
        restatement_accession = str(latest_restatement.get("source_accession") or "")
        restatement_at = latest_restatement.get("accepted_at_ts")
        keep = group["source_accession"].eq(restatement_accession)
        if pd.notna(restatement_at):
            keep = keep | (
                group["amendment_type"].eq("NEW HOLDINGS")
                & group["accepted_at_ts"].gt(restatement_at)
            )
        effective_groups.append(group[keep].copy())
    return pd.concat(effective_groups, ignore_index=True) if effective_groups else frame.iloc[0:0].copy()


def prepare_13f_holdings(frame: pd.DataFrame, *, as_of: str | None = None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    d = frame.copy()
    d["manager_cik"] = d.get("manager_cik", "").map(cik10)
    d["ticker"] = d.get("ticker_mapped", "").astype(str).str.upper().str.strip()
    d["report_period_ts"] = pd.to_datetime(d.get("report_period"), errors="coerce").dt.normalize()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True)
    d["accepted_at_ts"] = pd.to_datetime(d.get("accepted_at"), errors="coerce", utc=True)
    for column in ["source_accession", "form_type", "amendment_type"]:
        if column not in d.columns:
            d[column] = ""
        d[column] = d[column].fillna("").astype(str).str.strip()
    d["form_type"] = d["form_type"].str.upper()
    d["amendment_type"] = d["amendment_type"].str.upper().str.replace(r"[_-]+", " ", regex=True)
    shares = pd.to_numeric(d.get("shares"), errors="coerce")
    values = pd.to_numeric(d.get("market_value_usd"), errors="coerce")
    if shares.isna().any() or values.isna().any() or shares.lt(0).any() or values.lt(0).any():
        raise ValueError("13f_signal_required_numeric_invalid")
    d["shares"] = shares.astype(float)
    d["market_value_usd"] = values.astype(float)
    if as_of:
        cutoff = pd.to_datetime(as_of, errors="coerce", utc=True)
        if pd.isna(cutoff):
            raise ValueError(f"invalid institutional signal as-of timestamp: {as_of}")
        d = d[d["available_from_ts"].notna() & (d["available_from_ts"] <= cutoff)].copy()
    d = d[d["manager_cik"].ne("") & d["ticker"].ne("") & d["report_period_ts"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    d = _security_identity_frame(d)
    d = apply_13f_amendment_semantics(d)
    if d.empty:
        return pd.DataFrame()
    duplicate_key = ["manager_cik", "security_identity", "report_period_ts"]
    if d.duplicated(duplicate_key, keep=False).any():
        raise ValueError("13f_duplicate_security_identity_after_amendment_resolution")
    d = d.sort_values(["manager_cik", "security_identity", "report_period_ts", "accepted_at_ts"])
    total = d.groupby(["manager_cik", "report_period_ts"])["market_value_usd"].transform("sum").replace(0.0, float("nan"))
    d["manager_position_weight"] = (d["market_value_usd"] / total).fillna(0.0).clip(0.0, 1.0)
    cash_total = (
        d["market_value_usd"].where(d["cash_equity_eligible"], 0.0)
        .groupby([d["manager_cik"], d["report_period_ts"]])
        .transform("sum")
        .replace(0.0, float("nan"))
    )
    d["manager_cash_position_weight"] = (
        d["market_value_usd"].where(d["cash_equity_eligible"], 0.0) / cash_total
    ).fillna(0.0).clip(0.0, 1.0)
    d["manager_conviction_rank"] = 0.0
    cash = d["cash_equity_eligible"]
    if cash.any():
        d.loc[cash, "manager_conviction_rank"] = (
            d.loc[cash]
            .groupby(["manager_cik", "report_period_ts"])["manager_cash_position_weight"]
            .rank(pct=True)
            .fillna(0.0)
            .clip(0.0, 1.0)
        )
    return d


def append_13f_exit_tombstones(frame: pd.DataFrame) -> pd.DataFrame:
    """Represent securities omitted from a newer complete snapshot as exits."""
    if frame.empty:
        return frame.copy()
    d = frame.copy()
    d["synthetic_exit"] = False
    tombstones: list[pd.Series] = []
    for _, manager in d.groupby("manager_cik", sort=False):
        previous_active: set[str] = set()
        previous_rows: dict[str, pd.Series] = {}
        periods = sorted(manager["report_period_ts"].dropna().unique())
        for period in periods:
            current = manager[manager["report_period_ts"].eq(period)].copy()
            if current.empty:
                continue
            present = set(current["security_identity"].astype(str))
            active = set(current.loc[current["shares"].gt(0.0), "security_identity"].astype(str))
            complete = current[current["amendment_type"].eq("RESTATEMENT")]
            if complete.empty:
                complete = current[~current["amendment_type"].eq("NEW HOLDINGS")]
            if complete.empty:
                for sid, row in current[current["shares"].gt(0.0)].set_index("security_identity", drop=False).iterrows():
                    previous_rows[str(sid)] = row
                previous_active |= active
                continue
            template = complete.sort_values(["accepted_at_ts", "source_accession"]).iloc[-1]
            removed = previous_active - active
            for sid in sorted(removed - present):
                negated = previous_rows.get(sid)
                if negated is None:
                    continue
                row = negated.copy()
                # The exit belongs to the newer complete report period, but it
                # cannot become knowable before either the newer complete filing
                # or a later restatement that proves the prior security existed.
                for source_col in ["report_period_ts", "report_period", "source_accession", "form_type", "amendment_type"]:
                    if source_col in template.index:
                        row[source_col] = template[source_col]
                for ts_column, raw_column in [
                    ("available_from_ts", "available_from"),
                    ("accepted_at_ts", "accepted_at"),
                ]:
                    current_ts = template.get(ts_column)
                    prior_ts = negated.get(ts_column)
                    candidates = [value for value in [current_ts, prior_ts] if pd.notna(value)]
                    if candidates:
                        effective_ts = max(candidates)
                        row[ts_column] = effective_ts
                        row[raw_column] = effective_ts.isoformat()
                row["shares"] = 0.0
                row["market_value_usd"] = 0.0
                row["manager_position_weight"] = 0.0
                row["manager_cash_position_weight"] = 0.0
                row["manager_conviction_rank"] = 0.0
                row["synthetic_exit"] = True
                tombstones.append(row)
            previous_active = active
            previous_rows = {
                str(sid): row
                for sid, row in current[current["shares"].gt(0.0)].set_index("security_identity", drop=False).iterrows()
            }
    if not tombstones:
        return d
    return pd.concat([d, pd.DataFrame(tombstones)], ignore_index=True)


def add_13f_position_deltas(frame: pd.DataFrame, *, as_of: str | None = None) -> pd.DataFrame:
    d = prepare_13f_holdings(frame, as_of=as_of)
    if d.empty:
        return pd.DataFrame()
    d = append_13f_exit_tombstones(d)
    d = d.sort_values(["manager_cik", "security_identity", "report_period_ts", "available_from_ts"]).copy()
    keys = ["manager_cik", "security_identity"]
    prev_shares = d.groupby(keys)["shares"].shift(1)
    prev_value = d.groupby(keys)["market_value_usd"].shift(1)
    d["previous_shares"] = prev_shares.fillna(0.0)
    d["previous_market_value_usd"] = prev_value.fillna(0.0)
    d["shares_delta"] = d["shares"] - d["previous_shares"]
    d["market_value_delta_usd"] = d["market_value_usd"] - d["previous_market_value_usd"]
    d["new_position"] = (d["previous_shares"] <= 0.0) & (d["shares"] > 0.0)
    d["added_position"] = d["shares_delta"] > 0.0
    d["trimmed_position"] = (d["shares"] > 0.0) & (d["shares_delta"] < 0.0)
    d["exited_position"] = (d["previous_shares"] > 0.0) & (d["shares"] <= 0.0)
    return d


def _manager_ticker_states(group: pd.DataFrame) -> tuple[set[str], set[str], set[str]]:
    buyers: set[str] = set()
    sellers: set[str] = set()
    new_managers: set[str] = set()
    for manager_cik, manager in group.groupby("manager_cik", sort=False):
        positive = bool((manager["added_position"] | manager["new_position"]).any())
        negative = bool((manager["trimmed_position"] | manager["exited_position"]).any())
        current = bool(manager["shares"].gt(0.0).any())
        had_previous = bool(manager["previous_shares"].gt(0.0).any())
        if positive and not negative:
            buyers.add(str(manager_cik))
        if negative and not positive:
            sellers.add(str(manager_cik))
        if current and not had_previous:
            new_managers.add(str(manager_cik))
    return buyers, sellers, new_managers


def build_13f_signal(df: pd.DataFrame, *, as_of: str | None = None, lookback_days: int = 210) -> pd.DataFrame:
    d = add_13f_position_deltas(df, as_of=as_of)
    if d.empty:
        return pd.DataFrame(columns=INSTITUTIONAL_SIGNAL_COLUMNS)
    # Stock-level selector evidence is cash-equity only. Options/PRN remain in
    # the validated holding/event table and cannot overwrite cash positions.
    d = d[d["cash_equity_eligible"]].copy()
    if d.empty:
        return pd.DataFrame(columns=INSTITUTIONAL_SIGNAL_COLUMNS)
    if as_of:
        cutoff = pd.to_datetime(as_of, errors="coerce", utc=True)
        if pd.notna(cutoff):
            d = d[d["available_from_ts"].notna() & (d["available_from_ts"] <= cutoff)].copy()
            d = d[d["available_from_ts"] >= cutoff - pd.Timedelta(days=int(lookback_days))].copy()
    if d.empty:
        return pd.DataFrame(columns=INSTITUTIONAL_SIGNAL_COLUMNS)
    d = d.sort_values(["manager_cik", "security_identity", "available_from_ts", "report_period_ts"]).drop_duplicates(
        ["manager_cik", "security_identity"], keep="last"
    )
    rows: list[dict[str, Any]] = []
    now = pd.to_datetime(as_of, errors="coerce", utc=True) if as_of else d["available_from_ts"].max()
    for ticker, group in d.groupby("ticker"):
        current = group[group["shares"] > 0.0]
        manager_count = int(current["manager_cik"].nunique())
        buyers, sellers, new_managers = _manager_ticker_states(group)
        buying_count = len(buyers)
        selling_count = len(sellers)
        new_count = len(new_managers)
        total_value = float(current["market_value_usd"].sum())
        positive_delta = float(group["market_value_delta_usd"].clip(lower=0.0).sum())
        net_delta = float(group["market_value_delta_usd"].sum())
        shares_delta = float(group["shares_delta"].sum())
        conviction = float((current["manager_cash_position_weight"] * current["manager_conviction_rank"]).sum())
        latest_ts = group["available_from_ts"].max()
        age_days = float((now - latest_ts).days) if pd.notna(now) and pd.notna(latest_ts) else 999.0
        consensus = _safe_pct((buying_count - 0.5 * selling_count) / max(manager_count, 1))
        accumulation = _safe_pct(0.50 * _log_score(positive_delta, 250_000_000.0) + 0.50 * _safe_pct(buying_count / 8.0))
        conviction_score = _safe_pct(conviction / 0.20)
        new_position_score = _safe_pct(new_count / 5.0)
        crowding = _safe_pct(manager_count / 35.0)
        stale = _safe_pct(max(age_days - 120.0, 0.0) / 180.0)
        smart_money = _safe_pct(
            0.32 * consensus
            + 0.28 * accumulation
            + 0.18 * conviction_score
            + 0.12 * new_position_score
            + 0.10 * _safe_pct(net_delta / 250_000_000.0)
            - 0.12 * crowding
            - 0.10 * stale
        )
        confidence = _safe_pct(min(manager_count, 20) / 20.0 + 0.25 * min(len(group), 40) / 40.0)
        rows.append({
            "ticker": ticker,
            "latest_available_from": latest_ts.isoformat() if pd.notna(latest_ts) else "",
            "sec_13f_manager_count": manager_count,
            "sec_13f_buying_manager_count": buying_count,
            "sec_13f_selling_manager_count": selling_count,
            "sec_13f_new_position_manager_count": new_count,
            "sec_13f_total_value_usd": total_value,
            "sec_13f_value_delta_usd": net_delta,
            "sec_13f_shares_delta": shares_delta,
            "sec_13f_consensus_buy_score": consensus,
            "sec_13f_conviction_score": conviction_score,
            "sec_13f_accumulation_score": accumulation,
            "sec_13f_new_position_score": new_position_score,
            "sec_13f_crowding_score": crowding,
            "sec_13f_stale_penalty": stale,
            "sec_13f_smart_money_score": smart_money,
            "institutional_evidence_score": smart_money,
            "institutional_evidence_confidence_score": confidence,
        })
    if not rows:
        return pd.DataFrame(columns=INSTITUTIONAL_SIGNAL_COLUMNS)
    return pd.DataFrame(rows, columns=INSTITUTIONAL_SIGNAL_COLUMNS).sort_values(
        ["institutional_evidence_score", "sec_13f_value_delta_usd"], ascending=False
    )


def render_report(summary: dict[str, Any], latest: pd.DataFrame) -> str:
    lines = [
        "# SEC Institutional Signals",
        "",
        "Research-only 13F shadow evidence. Production `score_total` is not changed.",
        "",
        f"- 13F holding rows: {summary.get('holding_rows', 0)}",
        f"- signal tickers: {summary.get('signal_tickers', 0)}",
        f"- as_of: {summary.get('as_of') or 'latest available'}",
        "",
        "## Top 13F Evidence",
        "",
        "| ticker | institutional evidence | managers | buyers | new positions | net value delta | crowding | stale |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in latest.head(20).iterrows():
        lines.append(
            "| {ticker} | {score:.3f} | {mgr:.0f} | {buy:.0f} | {new:.0f} | ${delta:,.0f} | {crowd:.3f} | {stale:.3f} |".format(
                ticker=row.get("ticker", ""),
                score=float(row.get("institutional_evidence_score", 0.0)),
                mgr=float(row.get("sec_13f_manager_count", 0.0)),
                buy=float(row.get("sec_13f_buying_manager_count", 0.0)),
                new=float(row.get("sec_13f_new_position_manager_count", 0.0)),
                delta=float(row.get("sec_13f_value_delta_usd", 0.0)),
                crowd=float(row.get("sec_13f_crowding_score", 0.0)),
                stale=float(row.get("sec_13f_stale_penalty", 0.0)),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", default=DEFAULT_13F)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--lookback-days", type=int, default=210)
    parser.add_argument("--require-nonempty", action="store_true")
    args = parser.parse_args()

    holdings = read_table(repo_path(args.holdings))
    try:
        latest = build_13f_signal(holdings, as_of=args.as_of or None, lookback_days=int(args.lookback_days))
    except ValueError as exc:
        raise SystemExit(f"verified 13F holdings failed identity/integrity checks: {exc}") from exc
    if args.require_nonempty and latest.empty:
        raise SystemExit("verified 13F holdings produced no institutional signals; refusing publication")
    out = repo_path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    latest_csv = out / "13f_latest.csv"
    latest.to_csv(latest_csv, index=False)
    summary = {
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "holding_rows": int(len(holdings)),
        "signal_tickers": int(len(latest)),
        "security_identity_preserved": True,
        "stock_signal_scope": "CASH_EQUITY_ONLY_OPTIONS_AND_PRN_EXCLUDED_FROM_STOCK_SCORE",
        "as_of": args.as_of or "",
        "latest_csv": str(latest_csv),
    }
    write_json(out / "institutional_signal_summary.json", summary)
    (out / "report.md").write_text(render_report(summary, latest), encoding="utf-8")
    print(json.dumps({"status": "ok", **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
