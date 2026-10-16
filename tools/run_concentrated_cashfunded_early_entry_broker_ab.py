"""Cash-funded early-entry broker A/B for the Concentrated sleeve.

This research-only harness tests whether unused Concentrated cash can fund a
small position in the highest-ranked unheld candidate at each rebalance date.
It does not replace existing winners, does not force gross exposure above the
existing cash budget, and does not alter operating target books.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CASH_TICKERS = {"CASH", "__CASH__"}

SCHEMA_VERSION = "concentrated-cashfunded-early-entry-broker-ab-v1"
DEFAULT_OUTPUT_DIR = "outputs/concentrated_cashfunded_early_entry_broker_ab"
DEFAULT_SIGNALS = [
    "future_winner_scout_score",
    "breakout_setup_quality_score",
    "portfolio_future_winner_engine_score",
]
DEFAULT_ADD_WEIGHTS = [0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
FORBIDDEN_SIGNAL_EXACT = {
    "period_forward_return",
    "forward_return",
    "forward_return_coverage_score",
    "future_return",
    "future_63d_return",
    "future_126d_return",
    "next_63d_return",
    "next_126d_return",
    "audit_forward_return",
    "audit_forward_63d_excess",
    "audit_forward_126d_excess",
    "forward_63d_excess",
    "forward_126d_excess",
}
FORBIDDEN_SIGNAL_PATTERNS = (
    "period_forward",
    "forward_return",
    "future_return",
    "audit_forward",
    "forward_excess",
    "future_excess",
    "next_63d_return",
    "next_126d_return",
)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def parse_csv_list(raw: str, defaults: list[str]) -> list[str]:
    values = [part.strip() for part in str(raw or "").split(",") if part.strip()]
    return values or list(defaults)


def parse_float_list(raw: str, defaults: list[float]) -> list[float]:
    if not str(raw or "").strip():
        return list(defaults)
    out: list[float] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    return out or list(defaults)


def validate_signal_names(signals: list[str]) -> None:
    """Reject realized-return/audit-label columns as selection signals.

    `future_winner_scout_score` is an existing PIT composite feature despite
    its name; this guard targets explicit forward-return labels.
    """
    blocked: list[str] = []
    for signal in signals:
        name = str(signal or "").strip().lower()
        if not name:
            continue
        if name in FORBIDDEN_SIGNAL_EXACT or any(pattern in name for pattern in FORBIDDEN_SIGNAL_PATTERNS):
            blocked.append(signal)
    if blocked:
        raise ValueError(f"selection signals cannot use forward-return/audit-label columns: {blocked}")


def resolve_target_book(latest_run: Path, explicit: str) -> Path:
    if explicit:
        path = repo_path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"target book not found: {path}")
        return path
    candidates = [
        latest_run / "alphaops_vnext" / "official_concentrated_target_book.csv",
        latest_run / "reports" / "operating_concentrated_target_book.csv",
        latest_run / "market_leader_challenger" / "concentrated_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("no Concentrated target book found")


def resolve_candidate_book(latest_run: Path, explicit: str) -> Path:
    if explicit:
        path = repo_path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"candidate book not found: {path}")
        return path
    candidates = [
        latest_run / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
        latest_run / "reports" / "candidate_replay_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("no candidate replay book found")


def normalize_target_book(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"rebalance_date", "ticker", "weight"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"target book missing columns: {missing}")
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["ticker"] = out["ticker"].map(clean_ticker)
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
    if "target_weight" in out.columns:
        out["target_weight"] = pd.to_numeric(out["target_weight"], errors="coerce").fillna(out["weight"])
    else:
        out["target_weight"] = out["weight"]
    out = out.dropna(subset=["rebalance_date"])
    out = out[(out["ticker"] != "") & (out["weight"] > 1e-12)].copy()
    return out.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def normalize_candidate_book(frame: pd.DataFrame, signals: list[str]) -> pd.DataFrame:
    required = {"rebalance_date", "ticker"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"candidate book missing columns: {missing}")
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["ticker"] = out["ticker"].map(clean_ticker)
    out = out.dropna(subset=["rebalance_date"])
    out = out[(out["ticker"] != "") & (~out["ticker"].isin(CASH_TICKERS))].copy()
    for signal in signals:
        if signal in out.columns:
            out[signal] = pd.to_numeric(out[signal], errors="coerce")
    return out.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def filter_candidates_for_deployment(frame: pd.DataFrame, *, allow_crisis_deployment: bool) -> pd.DataFrame:
    if allow_crisis_deployment or "crisis_state" not in frame.columns:
        return frame.copy()
    crisis = frame["crisis_state"].astype(str).str.upper()
    return frame.loc[~crisis.str.contains("CRISIS|DEFENSE", na=False)].copy()


def is_cash_ticker(value: Any) -> bool:
    return clean_ticker(value) in CASH_TICKERS


def cash_weight(group: pd.DataFrame) -> float:
    cash = group[group["ticker"].map(is_cash_ticker)]
    if cash.empty:
        return 0.0
    return float(pd.to_numeric(cash["weight"], errors="coerce").fillna(0.0).clip(lower=0.0).sum())


def reduce_cash_rows(group: pd.DataFrame, amount: float) -> pd.DataFrame:
    if amount <= 1e-12:
        return group
    out = group.copy()
    remaining = float(amount)
    cash_indices = list(out.index[out["ticker"].map(is_cash_ticker)])
    for idx in cash_indices:
        old_weight = max(0.0, safe_float(out.at[idx, "weight"]))
        take = min(old_weight, remaining)
        out.at[idx, "weight"] = old_weight - take
        out.at[idx, "target_weight"] = max(0.0, safe_float(out.at[idx, "target_weight"], old_weight) - take)
        remaining -= take
        if remaining <= 1e-12:
            break
    return out


def make_cashfunded_book(
    *,
    target_book: pd.DataFrame,
    candidates: pd.DataFrame,
    signal: str,
    add_weight: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if signal not in candidates.columns:
        raise ValueError(f"candidate book missing signal column: {signal}")
    rows: list[pd.DataFrame] = []
    events: list[dict[str, Any]] = []
    for date_text, group in target_book.groupby("rebalance_date", sort=True):
        current = group.copy()
        held = set(current.loc[~current["ticker"].map(is_cash_ticker), "ticker"].astype(str))
        cash_before = cash_weight(current)
        inject = min(float(add_weight), cash_before)
        candidate_slice = candidates[
            (candidates["rebalance_date"].astype(str) == str(date_text))
            & (~candidates["ticker"].astype(str).isin(held))
        ].copy()
        candidate_slice = candidate_slice.dropna(subset=[signal]).sort_values(signal, ascending=False).head(1)
        if inject > 1e-12 and not candidate_slice.empty:
            chosen = candidate_slice.iloc[0]
            new_row = {key: "" for key in current.columns}
            if not current.empty:
                new_row.update(current.iloc[0].to_dict())
            ticker = clean_ticker(chosen.get("ticker"))
            new_row.update(
                {
                    "rebalance_date": date_text,
                    "ticker": ticker,
                    "weight": inject,
                    "target_weight": inject,
                    "portfolio_kind": "concentrated",
                    "selection_reason": f"cashfunded_early_entry|signal={signal}|add={add_weight:g}",
                }
            )
            current = reduce_cash_rows(current, inject)
            rows.append(pd.DataFrame([new_row]))
            events.append(
                {
                    "rebalance_date": date_text,
                    "ticker": ticker,
                    "signal": signal,
                    "signal_value": safe_float(chosen.get(signal)),
                    "added_weight": inject,
                    "cash_before": cash_before,
                }
            )
        rows.append(current)
    book = pd.concat(rows, ignore_index=True) if rows else target_book.copy()
    book["weight"] = pd.to_numeric(book["weight"], errors="coerce").fillna(0.0)
    book["target_weight"] = pd.to_numeric(book["target_weight"], errors="coerce").fillna(book["weight"])
    book = book[book["weight"] > 1e-12].copy()
    return book.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True), pd.DataFrame(events)


def run_broker_replay(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    cost_bps: float,
    max_fill_lag_days: int,
    starting_capital: float,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "run_broker_ledger_replay.py"),
        "--target-book",
        str(target_book),
        "--price-cache",
        str(price_cache),
        "--output-dir",
        str(output_dir),
        "--portfolio-kind",
        "concentrated",
        "--fill-mode",
        "next_close",
        "--cost-bps",
        str(cost_bps),
        "--max-fill-lag-days",
        str(max_fill_lag_days),
        "--starting-capital",
        str(starting_capital),
        "--disable-concentrated-champion-filter",
        "--oos-start",
        "2024-06-03",
        "--oos2-start",
        "2023-06-03",
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True)
    metrics_path = output_dir / "metrics.json"
    if not metrics_path.exists():
        return {
            "status": "broker_failed",
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["broker_returncode"] = proc.returncode
    return payload


def verdict_for_arm(metrics: dict[str, Any], *, target_cagr: float, target_mdd: float) -> str:
    if metrics.get("metric_mode") != "broker_ledger_next_close":
        return "blocked_invalid_metric_mode"
    if safe_float(metrics.get("years")) < 7.0:
        return "blocked_invalid_window"
    cagr = safe_float(metrics.get("cagr"))
    mdd = safe_float(metrics.get("max_dd"))
    if cagr >= target_cagr and mdd >= target_mdd:
        return "research_pass_concentrated_candidate"
    if cagr < target_cagr and mdd < target_mdd:
        return "reject_cagr_and_mdd"
    if cagr < target_cagr:
        return "reject_no_cagr_edge"
    return "reject_mdd_worse"


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Concentrated Cash-Funded Early Entry Broker A/B",
        "",
        "Research-only harness. It deploys existing cash into the highest-ranked unheld candidate for one PIT signal at each rebalance date.",
        "",
        "| Arm | Verdict | CAGR | MaxDD | Sharpe | Avg cash | Events |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary.get("arms", []):
        lines.append(
            "| {arm} | {verdict} | {cagr:.2%} | {mdd:.2%} | {sharpe:.3f} | {cash:.2%} | {events} |".format(
                arm=row.get("arm"),
                verdict=row.get("ab_verdict"),
                cagr=safe_float(row.get("cagr")),
                mdd=safe_float(row.get("max_dd")),
                sharpe=safe_float(row.get("sharpe")),
                cash=safe_float(row.get("avg_cash_weight")),
                events=row.get("event_count"),
            )
        )
    lines.extend(
        [
            "",
            "This is not production evidence. PIT-universe cleanliness, full policy replay, data freshness, and a fullrun remain required before any promotion claim.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    output_dir.mkdir(parents=True, exist_ok=True)
    signals = parse_csv_list(args.signals, DEFAULT_SIGNALS)
    validate_signal_names(signals)
    add_weights = parse_float_list(args.add_weights, DEFAULT_ADD_WEIGHTS)
    target_path = resolve_target_book(latest_run, args.target_book)
    candidate_path = resolve_candidate_book(latest_run, args.candidate_book)
    target_book = normalize_target_book(read_csv(target_path))
    candidate_book = normalize_candidate_book(read_csv(candidate_path), signals)
    candidate_book = filter_candidates_for_deployment(
        candidate_book,
        allow_crisis_deployment=bool(args.allow_crisis_deployment),
    )

    arms: list[dict[str, Any]] = []
    for signal in signals:
        if signal not in candidate_book.columns:
            arms.append({"arm": f"{signal}_missing", "signal": signal, "ab_verdict": "blocked_missing_signal"})
            continue
        for add_weight in add_weights:
            arm = f"{signal}_add{int(round(float(add_weight) * 100))}"
            arm_dir = output_dir / arm
            arm_dir.mkdir(parents=True, exist_ok=True)
            book, events = make_cashfunded_book(
                target_book=target_book,
                candidates=candidate_book,
                signal=signal,
                add_weight=float(add_weight),
            )
            target_out = arm_dir / "target_book.csv"
            write_csv(target_out, book)
            write_csv(arm_dir / "events.csv", events)
            metrics = run_broker_replay(
                target_book=target_out,
                price_cache=price_cache,
                output_dir=arm_dir / "broker",
                cost_bps=float(args.cost_bps),
                max_fill_lag_days=int(args.max_fill_lag_days),
                starting_capital=float(args.starting_capital),
            )
            verdict = verdict_for_arm(
                metrics,
                target_cagr=float(args.target_cagr),
                target_mdd=float(args.target_mdd),
            )
            windows = metrics.get("windows") or {}
            arms.append(
                {
                    "arm": arm,
                    "signal": signal,
                    "add_weight": float(add_weight),
                    "event_count": int(len(events)),
                    "ab_verdict": verdict,
                    "metric_mode": metrics.get("metric_mode"),
                    "status": metrics.get("status"),
                    "start_date": metrics.get("start_date"),
                    "end_date": metrics.get("end_date"),
                    "years": metrics.get("years"),
                    "cagr": metrics.get("cagr"),
                    "max_dd": metrics.get("max_dd"),
                    "sharpe": metrics.get("sharpe"),
                    "avg_cash_weight": metrics.get("avg_cash_weight"),
                    "trade_count": metrics.get("trade_count"),
                    "oos_cagr": (windows.get("oos") or {}).get("cagr"),
                    "oos_max_dd": (windows.get("oos") or {}).get("max_dd"),
                    "oos2_cagr": (windows.get("oos2") or {}).get("cagr"),
                    "oos2_max_dd": (windows.get("oos2") or {}).get("max_dd"),
                    "target_book_path": str(target_out),
                    "broker_metrics_path": str(arm_dir / "broker" / "metrics.json"),
                    "events_path": str(arm_dir / "events.csv"),
                }
            )
    arms = sorted(arms, key=lambda row: (safe_float(row.get("cagr")), safe_float(row.get("max_dd"))), reverse=True)
    policy_candidates = [row for row in arms if row.get("ab_verdict") == "research_pass_concentrated_candidate"]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "latest_run": str(latest_run),
        "target_book": str(target_path),
        "candidate_book": str(candidate_path),
        "price_cache": str(price_cache),
        "signals": signals,
        "add_weights": add_weights,
        "target_cagr": float(args.target_cagr),
        "target_mdd": float(args.target_mdd),
        "arms": arms,
        "policy_candidates": policy_candidates,
        "screen_pass": bool(policy_candidates),
        "next_action": "design_default_off_cashfunded_early_entry_hook" if policy_candidates else "discard_or_refine",
        "research_only": True,
        "production_activation_allowed": False,
        "production_promotion_allowed": False,
        "production_promotion_blocker": "pit_universe_label_clean_required",
    }
    write_json(output_dir / "summary.json", summary)
    pd.DataFrame(arms).to_csv(output_dir / "arm_metrics.csv", index=False)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--target-book", default="")
    parser.add_argument("--candidate-book", default="")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--signals", default=",".join(DEFAULT_SIGNALS))
    parser.add_argument("--add-weights", default=",".join(str(x) for x in DEFAULT_ADD_WEIGHTS))
    parser.add_argument("--target-cagr", type=float, default=0.50)
    parser.add_argument("--target-mdd", type=float, default=-0.25)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--allow-crisis-deployment", action="store_true")
    return parser.parse_args()


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
