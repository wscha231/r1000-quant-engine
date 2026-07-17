#!/usr/bin/env python3
"""Build a conservative exact-accepted fundamental-break review sidecar.

The current input signal, ``sec_filing_quality_event``, failed its frozen source
screen.  This builder therefore exposes exact negative comparable filings for
manual review while emitting zero confirmed breaks unless the frozen source
screen itself passed.  Price moves, ranks, and quality proxies are never used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
READY_STATUS = "READY_EXACT_FUNDAMENTAL_BREAK_REVIEW_ONLY"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def read_events(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def build(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = repo_path(args.contract)
    events_path = repo_path(args.events)
    screen_path = repo_path(args.source_screen_summary)
    held_path = repo_path(args.held_risk_watch) if str(args.held_risk_watch or "").strip() else Path()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    contract = read_json(contract_path)
    screen = read_json(screen_path)
    if not events_path.is_file():
        raise FileNotFoundError(events_path)
    decision_time = pd.to_datetime(args.decision_time_utc, errors="raise", utc=True)
    events = read_events(events_path)
    required = {
        "ticker",
        "accession_number",
        "form",
        "fiscal_period",
        "accepted_at",
        "available_from",
        "exact_acceptance",
        "component_coverage",
        "sec_filing_quality_event",
    }
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"filing event input missing columns: {sorted(missing)}")
    events["ticker"] = events["ticker"].astype(str).str.upper().str.strip()
    events["accepted_exact"] = pd.to_datetime(events["accepted_at"], errors="coerce", utc=True)
    events["available_exact"] = pd.to_datetime(events["available_from"], errors="coerce", utc=True)
    events["component_coverage_clean"] = pd.to_numeric(events["component_coverage"], errors="coerce").fillna(0)
    events["exact_acceptance_clean"] = events["exact_acceptance"].map(as_bool)
    future_rows = events["available_exact"].gt(decision_time).fillna(False)
    eligible = events.loc[
        events["ticker"].ne("")
        & events["accepted_exact"].notna()
        & events["available_exact"].notna()
        & events["available_exact"].le(decision_time)
        & events["exact_acceptance_clean"]
        & events["component_coverage_clean"].ge(3)
    ].copy()
    eligible = eligible.sort_values(["ticker", "accepted_exact", "accession_number"])
    latest = eligible.groupby("ticker", sort=False, as_index=False).tail(1).copy()
    latest_event_by_ticker = latest.set_index("ticker").to_dict("index") if not latest.empty else {}
    known_archive_rows = events.loc[
        events["accepted_exact"].notna()
        & events["accepted_exact"].le(decision_time)
        & events["available_exact"].notna()
        & events["available_exact"].le(decision_time)
        & events["exact_acceptance_clean"]
    ]
    archive_max = known_archive_rows["accepted_exact"].max()
    archive_max_date = str(archive_max.date()) if pd.notna(archive_max) else ""
    decision_date = str(decision_time.date())
    source_verdict = str(screen.get("verdict") or "MISSING_SOURCE_SCREEN")
    required_verdict = str(
        ((contract.get("confirmation_gate") or {}).get("source_screen_required_verdict"))
        or "PASS_SOURCE_SCREEN"
    )
    source_screen_pass = source_verdict == required_verdict

    if held_path.is_file():
        held = pd.read_csv(held_path, low_memory=False)
        required_held = {"portfolio_kind", "ticker"}
        if not required_held.issubset(held.columns):
            raise ValueError(f"held risk watch missing columns: {sorted(required_held - set(held.columns))}")
        universe = held[["portfolio_kind", "ticker"]].copy()
        held_as_of = (
            pd.to_datetime(held["as_of_date"], errors="coerce").max()
            if "as_of_date" in held.columns
            else pd.NaT
        )
        universe["portfolio_kind"] = universe["portfolio_kind"].astype(str).str.lower().str.strip()
        universe["ticker"] = universe["ticker"].astype(str).str.upper().str.strip()
        universe = universe.drop_duplicates().sort_values(["portfolio_kind", "ticker"])
    else:
        held_as_of = pd.NaT
        universe = pd.DataFrame({"portfolio_kind": "all", "ticker": sorted(latest_event_by_ticker)})
    archive_expected_through_date = (
        held_as_of.date() if pd.notna(held_as_of) else decision_time.date()
    )
    archive_covers_decision_date = bool(
        pd.notna(archive_max) and archive_max.date() >= archive_expected_through_date
    )

    rows: list[dict[str, Any]] = []
    for row in universe.itertuples(index=False):
        ticker = str(row.ticker)
        event = latest_event_by_ticker.get(ticker, {})
        label = str(event.get("sec_filing_quality_event") or "neutral").lower()
        negative = label == "negative"
        exact = as_bool(event.get("exact_acceptance_clean")) if event else False
        coverage = int(event.get("component_coverage_clean") or 0) if event else 0
        available = event.get("available_exact") if event else pd.NaT
        confirmation_gate = bool(
            negative
            and exact
            and coverage >= 3
            and pd.notna(available)
            and available <= decision_time
            and source_screen_pass
            and archive_covers_decision_date
        )
        if confirmation_gate:
            status = "CONFIRMED_EXACT_ACCEPTED_BREAK"
        elif negative:
            status = "NEGATIVE_EXACT_FILING_REVIEW_ONLY"
        else:
            status = "NO_EXACT_BREAK_EVIDENCE"
        blockers: list[str] = []
        if negative and not source_screen_pass:
            blockers.append(f"source_screen_{source_verdict.lower()}")
        if negative and not archive_covers_decision_date:
            blockers.append("event_archive_not_current_through_decision_date")
        if not event:
            blockers.append("no_comparable_exact_filing")
        rows.append(
            {
                "portfolio_kind": str(row.portfolio_kind),
                "ticker": ticker,
                "break_status": status,
                "available_from": (
                    available.isoformat() if pd.notna(available) else str(args.recorded_at_utc or args.decision_time_utc)
                ),
                "decision_time_utc": decision_time.isoformat(),
                "accession_number": str(event.get("accession_number") or ""),
                "form": str(event.get("form") or ""),
                "fiscal_period": str(event.get("fiscal_period") or ""),
                "accepted_at": (
                    event.get("accepted_exact").isoformat()
                    if event and pd.notna(event.get("accepted_exact"))
                    else ""
                ),
                "exact_acceptance": exact,
                "component_coverage": coverage,
                "sec_filing_quality_event": label,
                "source_screen_verdict": source_verdict,
                "source_screen_pass": source_screen_pass,
                "archive_max_accepted_date": archive_max_date,
                "archive_expected_through_date": str(archive_expected_through_date),
                "archive_covers_decision_date": archive_covers_decision_date,
                "confirmation_gate_pass": confirmation_gate,
                "review_blockers": "|".join(blockers),
                "portfolio_action_authorized": False,
                "orders_generated": False,
            }
        )
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["portfolio_kind", "ticker"]).reset_index(drop=True)
    result.to_csv(output_dir / "fundamental_break_review.csv", index=False, lineterminator="\n")
    result.to_csv(output_dir / "confirmed_breaks.csv", index=False, lineterminator="\n")
    confirmed = int(result["break_status"].eq("CONFIRMED_EXACT_ACCEPTED_BREAK").sum()) if len(result) else 0
    negative_review = int(result["break_status"].eq("NEGATIVE_EXACT_FILING_REVIEW_ONLY").sum()) if len(result) else 0
    payload = {
        "schema_version": "run287-exact-fundamental-break-sidecar-v1",
        "status": READY_STATUS,
        "decision_time_utc": decision_time.isoformat(),
        "decision_date": decision_date,
        "available_from": str(args.recorded_at_utc or args.decision_time_utc),
        "source_screen_verdict": source_verdict,
        "source_screen_required_verdict": required_verdict,
        "source_screen_pass": source_screen_pass,
        "archive_max_accepted_date": archive_max_date,
        "archive_expected_through_date": str(archive_expected_through_date),
        "archive_covers_decision_date": archive_covers_decision_date,
        "input_event_row_count": int(len(events)),
        "future_row_count_excluded": int(future_rows.sum()),
        "eligible_comparable_event_count": int(len(eligible)),
        "universe_row_count": int(len(result)),
        "confirmed_break_count": confirmed,
        "negative_exact_filing_review_count": negative_review,
        "portfolio_ab_allowed": bool(source_screen_pass and archive_covers_decision_date),
        "rejected_signal_reused_as_action_gate": False,
        "price_or_rank_used": False,
        "source_inputs": {
            "events": {"path": str(events_path), "sha256": sha256_file(events_path)},
            "source_screen_summary": {"path": str(screen_path), "sha256": sha256_file(screen_path)},
            "held_risk_watch": {"path": str(held_path), "sha256": sha256_file(held_path)},
            "contract": {"path": str(contract_path), "sha256": sha256_file(contract_path)},
        },
        "target_books_mutated": False,
        "cash_policy_mutated": False,
        "orders_generated": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
    }
    write_json(output_dir / "summary.json", payload)
    lines = [
        "# Run287 exact fundamental-break review",
        "",
        f"- status: `{payload['status']}`",
        f"- source screen: `{source_verdict}`",
        f"- event archive max accepted date: `{archive_max_date}`",
        f"- confirmed exact breaks: `{confirmed}`",
        f"- negative exact filings, review only: `{negative_review}`",
        f"- portfolio A/B allowed: `{str(payload['portfolio_ab_allowed']).lower()}`",
        "",
        "A rejected filing-quality signal is never relabeled as an actionable fundamental break.",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="docs/run287_exact_fundamental_break_contract_v1.json")
    parser.add_argument("--events", required=True)
    parser.add_argument("--source-screen-summary", required=True)
    parser.add_argument("--held-risk-watch", default="")
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument("--recorded-at-utc", default="")
    parser.add_argument("--output-dir", default="outputs/run287_fundamental_breaks")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(build(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
