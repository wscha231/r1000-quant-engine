#!/usr/bin/env python3
"""Audit whether a candidate file is a true same-close selector snapshot.

The daily operating workflow can legitimately revalue a restored target book at
the latest close.  That is not evidence that the full selector was recomputed.
This sidecar keeps those clocks separate and fails closed when provenance or
selector-qualification fields are missing.  It never changes a target book.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
READY_STATUS = "READY_SAME_CLOSE_SELECTOR_SNAPSHOT"
BLOCKED_STATUS = "BLOCKED_SAME_CLOSE_SELECTOR_PROVENANCE"


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


def portfolio_kind(frame: pd.DataFrame) -> pd.Series:
    if "portfolio_kind" in frame.columns:
        result = frame["portfolio_kind"].astype(str).str.lower().str.strip()
    else:
        source = frame.get("daily_candidate_source", pd.Series("", index=frame.index))
        result = source.astype(str).str.lower().map(
            lambda value: "concentrated" if "concentrated" in value else "main"
        )
    return result.where(result.isin(["main", "concentrated"]), "unknown")


def explicit_signal_date(frame: pd.DataFrame) -> pd.Series:
    """Return only dates whose source semantics are explicit.

    Legacy ``rebalance_date`` is intentionally excluded.  The historical daily
    workflow backfilled that column with the valuation close when a restored
    target had no signal date, so treating it as selector provenance would
    manufacture freshness.
    """
    candidates = [
        column
        for column in (
            "signal_source_date",
            "selector_decision_date",
            "source_rebalance_date",
            "feature_date",
        )
        if column in frame.columns
    ]
    if not candidates:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    parsed = pd.DataFrame(
        {column: pd.to_datetime(frame[column], errors="coerce") for column in candidates}
    )
    return parsed.max(axis=1)


def build(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = repo_path(args.contract)
    candidate_path = repo_path(args.candidate_book)
    session_path = repo_path(args.session_json)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    contract = read_json(contract_path)
    session = read_json(session_path)
    if not candidate_path.is_file():
        raise FileNotFoundError(candidate_path)
    frame = pd.read_csv(candidate_path, low_memory=False)
    required = {"ticker"}
    if not required.issubset(frame.columns):
        raise ValueError(f"candidate book missing columns: {sorted(required - set(frame.columns))}")
    session_date = str(session.get("session_date") or session.get("market_session_date") or "")
    session_ts = pd.to_datetime(session_date, errors="coerce")
    if pd.isna(session_ts):
        raise ValueError("session json does not contain a valid completed session date")

    detail = frame.copy()
    detail["ticker"] = detail["ticker"].astype(str).str.upper().str.strip()
    detail["portfolio_kind"] = portfolio_kind(detail)
    signal = explicit_signal_date(detail)
    detail["signal_source_date_audited"] = signal.dt.strftime("%Y-%m-%d").fillna("")
    if "valuation_close_date" in detail.columns:
        valuation = pd.to_datetime(detail["valuation_close_date"], errors="coerce")
    else:
        valuation = pd.Series(session_ts, index=detail.index)
    detail["valuation_close_date_audited"] = valuation.dt.strftime("%Y-%m-%d").fillna("")
    if "same_close_rank_recomputed" in detail.columns:
        recomputed = detail["same_close_rank_recomputed"].map(as_bool)
    else:
        recomputed = pd.Series(False, index=detail.index)
    detail["same_close_rank_recomputed_audited"] = recomputed
    qualification_columns = ["selector_selected", "final_rank", "decision_feature_complete_bool"]
    qualification_present = all(column in detail.columns for column in qualification_columns)
    if qualification_present:
        selected = detail["selector_selected"].map(as_bool)
        complete = detail["decision_feature_complete_bool"].map(as_bool)
        ranks = pd.to_numeric(detail["final_rank"], errors="coerce")
        qualified = selected & complete & ranks.notna()
    else:
        qualified = pd.Series(False, index=detail.index)
    detail["selector_qualified_candidate"] = qualified
    future = signal.notna() & signal.gt(session_ts)
    stale = signal.notna() & signal.lt(session_ts)
    same_signal = signal.notna() & signal.eq(session_ts)
    same_valuation = valuation.notna() & valuation.eq(session_ts)
    detail["future_signal_row"] = future
    detail["same_close_signal_date"] = same_signal
    detail["same_close_valuation_date"] = same_valuation

    def row_status(index: int) -> str:
        if future.iloc[index]:
            return "BLOCKED_FUTURE_SIGNAL_DATE"
        if pd.isna(signal.iloc[index]):
            return "BLOCKED_MISSING_SIGNAL_PROVENANCE"
        if stale.iloc[index]:
            return "BLOCKED_STALE_SIGNAL_DATE"
        if not recomputed.iloc[index]:
            return "BLOCKED_RESTORED_TARGET_REVALUATION_ONLY"
        if not qualification_present:
            return "BLOCKED_SELECTOR_QUALIFICATION_MISSING"
        return "READY_SAME_CLOSE_SELECTOR_ROW"

    detail["row_readiness_status"] = [row_status(index) for index in range(len(detail))]
    portfolio_rows: list[dict[str, Any]] = []
    for portfolio, group in detail.groupby("portfolio_kind", sort=True):
        signal_values = group["signal_source_date_audited"]
        ready = bool(
            len(group)
            and group["same_close_signal_date"].all()
            and group["same_close_valuation_date"].all()
            and group["same_close_rank_recomputed_audited"].all()
            and qualification_present
            and group["selector_qualified_candidate"].any()
            and not group["future_signal_row"].any()
        )
        blockers: list[str] = []
        if signal_values.eq("").any():
            blockers.append("missing_signal_provenance")
        if group["future_signal_row"].any():
            blockers.append("future_signal_date")
        if (~group["same_close_signal_date"]).any():
            blockers.append("signal_not_same_close")
        if (~group["same_close_valuation_date"]).any():
            blockers.append("valuation_not_same_close")
        if (~group["same_close_rank_recomputed_audited"]).any():
            blockers.append("rank_recomputation_unproven")
        if not qualification_present:
            blockers.append("selector_qualification_columns_missing")
        elif not group["selector_qualified_candidate"].any():
            blockers.append("no_complete_selected_candidate")
        source_dates = sorted(value for value in signal_values.unique() if value)
        portfolio_rows.append(
            {
                "portfolio_kind": portfolio,
                "market_session_date": session_date,
                "candidate_row_count": int(len(group)),
                "signal_date_coverage": float(signal_values.ne("").mean()),
                "signal_source_dates": "|".join(source_dates),
                "valuation_same_close_count": int(group["same_close_valuation_date"].sum()),
                "rank_recomputed_count": int(group["same_close_rank_recomputed_audited"].sum()),
                "selector_qualified_count": int(group["selector_qualified_candidate"].sum()),
                "same_close_selector_ready": ready,
                "readiness_status": READY_STATUS if ready else BLOCKED_STATUS,
                "blockers": "|".join(dict.fromkeys(blockers)),
            }
        )
    portfolios = pd.DataFrame(portfolio_rows)
    all_ready = bool(len(portfolios) and portfolios["same_close_selector_ready"].all())
    detail.to_csv(output_dir / "candidate_provenance_rows.csv", index=False, lineterminator="\n")
    portfolios.to_csv(output_dir / "selector_snapshot_readiness.csv", index=False, lineterminator="\n")
    payload = {
        "schema_version": "run287-same-close-selector-snapshot-v1",
        "status": READY_STATUS if all_ready else BLOCKED_STATUS,
        "market_session_date": session_date,
        "available_from": str(args.recorded_at_utc or ""),
        "candidate_row_count": int(len(detail)),
        "portfolio_count": int(len(portfolios)),
        "ready_portfolio_count": int(portfolios["same_close_selector_ready"].sum()) if len(portfolios) else 0,
        "portfolio_statuses": {
            str(row.portfolio_kind): str(row.readiness_status)
            for row in portfolios.itertuples(index=False)
        },
        "source_run_id": str(args.source_run_id or ""),
        "source_commit_sha": str(args.source_commit_sha or ""),
        "source_inputs": {
            "candidate_book": {"path": str(candidate_path), "sha256": sha256_file(candidate_path)},
            "session_json": {"path": str(session_path), "sha256": sha256_file(session_path)},
            "contract": {"path": str(contract_path), "sha256": sha256_file(contract_path)},
        },
        "legacy_rebalance_date_trusted_as_signal_date": False,
        "restored_target_revaluation_is_selector_snapshot": False,
        "selector_mutated": False,
        "target_books_mutated": False,
        "orders_generated": False,
        "production_activation_allowed": False,
        "contract_schema_version": contract.get("schema_version", ""),
    }
    write_json(output_dir / "summary.json", payload)
    lines = [
        "# Run287 same-close selector snapshot audit",
        "",
        f"- status: `{payload['status']}`",
        f"- completed market session: `{session_date}`",
        f"- candidate rows: `{len(detail)}`",
        "- restored target revaluation counts as selector recomputation: `false`",
        "",
        "| Portfolio | Rows | Signal coverage | Recomputed | Qualified | Ready | Blockers |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in portfolios.itertuples(index=False):
        lines.append(
            f"| {row.portfolio_kind} | {row.candidate_row_count} | {row.signal_date_coverage:.1%} | "
            f"{row.rank_recomputed_count} | {row.selector_qualified_count} | "
            f"{str(bool(row.same_close_selector_ready)).lower()} | {row.blockers} |"
        )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="docs/run287_same_close_selector_snapshot_contract_v1.json")
    parser.add_argument("--candidate-book", required=True)
    parser.add_argument("--session-json", required=True)
    parser.add_argument("--recorded-at-utc", default="")
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--source-commit-sha", default="")
    parser.add_argument("--output-dir", default="outputs/run287_same_close_selector_snapshot")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(build(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
