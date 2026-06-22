#!/usr/bin/env python3
"""Sweep target-book-stage levers in a single run.

The concentrated gross-cap floor (``R1000_CONC_GROSS_CAP_FLOOR``) and the daily
position-stop parameters act only at the target-book / replay stage, not in the
walk-forward training that dominates a full rebuild. Re-running the full rebuild
per lever value wastes ~3-4h each. This tool reuses one rebuild's scored output
and price cache to measure a grid of lever values cheaply:

  - conc-gross-floor sweep: rebuild the concentrated target book via
    ``run_alphaops_vnext_policy_replay`` (``shadow_only`` so the operating books
    are never replaced) with each floor injected through
    ``R1000_CONC_GROSS_CAP_FLOOR``, then score the resulting book through
    ``run_broker_ledger_replay`` (next-close) -> CAGR / MaxDD / Sharpe /
    avg_cash. A floor of ``0.0`` reproduces the current production schedule and
    is the control arm.
  - daily-stop sweep: run ``run_broker_position_risk_replay`` with each
    ``hard:trailing`` pair on the existing operating books -> CAGR / MaxDD. The
    ``default`` token uses the tool's own default stop levels.

Each arm is isolated in its own output sub-directory and failures stay
non-fatal, so one arm blocking does not abort the sweep. Results are aggregated
into ``<output-dir>/summary.json`` and ``<output-dir>/sweep_report.md``.

This is measurement infrastructure: it never replaces the operating target
books or the broker-ledger acceptance metric. It is intended to run as an
opt-in sidecar (gated by ``R1000_LEVER_SWEEP=1``) so default runs are unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OUTPUT_DIR = "outputs/lever_sweep"
DEFAULT_CANDIDATE_BOOK = "outputs/reports/candidate_replay_book.csv"
SEC_ENRICHED_CANDIDATE_BOOK = (
    "outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv"
)
OPERATING_MAIN_BOOK = "outputs/reports/operating_main_target_book.csv"
OPERATING_CONCENTRATED_BOOK = "outputs/reports/operating_concentrated_target_book.csv"

METRIC_KEYS = ("cagr", "sharpe", "max_dd", "avg_cash_weight", "years")


def parse_float_list(text: str) -> list[float]:
    """Parse a comma list of floats, dropping blanks and duplicates (ordered)."""
    out: list[float] = []
    for tok in str(text or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        value = float(tok)
        if value not in out:
            out.append(value)
    return out


def parse_daily_stop_grid(text: str) -> list[tuple[str, float | None, float | None]]:
    """Parse a daily-stop grid spec into (label, hard_stop, trailing_stop) tuples.

    Each comma item is either ``default`` (use tool defaults) or
    ``<hard>:<trailing>`` (e.g. ``-0.10:-0.15``). Returns labels safe for use as
    directory names.
    """
    grid: list[tuple[str, float | None, float | None]] = []
    seen: set[str] = set()
    for tok in str(text or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok.lower() == "default":
            label = "default"
            entry = (label, None, None)
        else:
            hard_text, _, trail_text = tok.partition(":")
            hard = float(hard_text.strip())
            trailing = float(trail_text.strip())
            label = f"hard{hard}_trail{trailing}".replace("-", "m").replace(".", "p")
            entry = (label, hard, trailing)
        if label in seen:
            continue
        seen.add(label)
        grid.append(entry)
    return grid


def resolve_candidate_book(explicit: str | None) -> str:
    """Prefer the SEC-enriched candidate book when present, mirroring the sidecar."""
    if explicit:
        return explicit
    if (REPO_ROOT / SEC_ENRICHED_CANDIDATE_BOOK).is_file():
        return SEC_ENRICHED_CANDIDATE_BOOK
    return DEFAULT_CANDIDATE_BOOK


def conc_gross_commands(
    floor: float,
    *,
    latest_run: str,
    candidate_book: str,
    price_cache: str,
    out_dir: Path,
    concentrated_target_n: int,
    cost_bps: float,
    max_fill_lag_days: int,
) -> tuple[list[str], list[str], str]:
    """Build (vnext_cmd, broker_cmd, concentrated_book_path) for one floor arm.

    Pure command construction so the harness is testable without real data.
    """
    vnext_out = out_dir / "vnext"
    broker_out = out_dir / "broker"
    book = str(vnext_out / "variants" / f"concentrated_N{concentrated_target_n}_target_book.csv")
    vnext_cmd = [
        sys.executable,
        "tools/run_alphaops_vnext_policy_replay.py",
        "--latest-run", latest_run,
        "--candidate-book", candidate_book,
        "--price-cache", price_cache,
        "--output-dir", str(vnext_out),
        "--portfolio-kind", "concentrated",
        "--concentrated-target-n", str(concentrated_target_n),
        "--production-output-mode", "shadow_only",
        "--skip-broker-replay",
        "--cost-bps", str(cost_bps),
        "--max-fill-lag-days", str(max_fill_lag_days),
    ]
    broker_cmd = [
        sys.executable,
        "tools/run_broker_ledger_replay.py",
        "--target-book", book,
        "--price-cache", price_cache,
        "--portfolio-kind", "concentrated",
        "--output-dir", str(broker_out),
        "--fill-mode", "next_close",
        "--cost-bps", str(cost_bps),
        "--max-fill-lag-days", str(max_fill_lag_days),
    ]
    return vnext_cmd, broker_cmd, book


def daily_stop_command(
    label: str,
    hard: float | None,
    trailing: float | None,
    *,
    portfolio_kind: str,
    target_book: str,
    price_cache: str,
    out_dir: Path,
    cost_bps: float,
    max_fill_lag_days: int,
) -> list[str]:
    """Build the broker_position_risk_replay command for one daily-stop arm."""
    cmd = [
        sys.executable,
        "tools/run_broker_position_risk_replay.py",
        "--target-book", target_book,
        "--price-cache", price_cache,
        "--portfolio-kind", portfolio_kind,
        "--output-dir", str(out_dir / portfolio_kind),
        "--fill-mode", "next_close",
        "--cost-bps", str(cost_bps),
        "--max-fill-lag-days", str(max_fill_lag_days),
        "--candidate-id", f"{portfolio_kind}_daily_stop_sweep_{label}",
    ]
    if hard is not None:
        cmd += ["--hard-stop", str(hard)]
    if trailing is not None:
        cmd += ["--trailing-stop", str(trailing)]
    return cmd


def read_metrics(path: Path) -> dict[str, Any]:
    """Read the metric subset from a replay metrics.json; tolerate missing files."""
    if not path.is_file():
        return {"status": "missing", "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "unreadable", "path": str(path), "error": str(exc)}
    out: dict[str, Any] = {"status": "ok"}
    for key in METRIC_KEYS:
        if key in data:
            out[key] = data[key]
    return out


def _run(cmd: list[str], env: dict[str, str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            cmd, cwd=str(REPO_ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT
        )
    return proc.returncode


def run_conc_gross_sweep(args: argparse.Namespace, output_dir: Path) -> list[dict[str, Any]]:
    candidate_book = resolve_candidate_book(args.candidate_book)
    rows: list[dict[str, Any]] = []
    for floor in parse_float_list(args.conc_gross_floors):
        tag = f"floor_{floor}".replace("-", "m").replace(".", "p")
        arm_dir = output_dir / f"conc_gross_{tag}"
        vnext_cmd, broker_cmd, book = conc_gross_commands(
            floor,
            latest_run=args.latest_run,
            candidate_book=candidate_book,
            price_cache=args.price_cache,
            out_dir=arm_dir,
            concentrated_target_n=args.concentrated_target_n,
            cost_bps=args.cost_bps,
            max_fill_lag_days=args.max_fill_lag_days,
        )
        row: dict[str, Any] = {"lever": "conc_gross_floor", "floor": floor}
        if args.dry_run:
            row["vnext_cmd"] = " ".join(vnext_cmd)
            row["broker_cmd"] = " ".join(broker_cmd)
            rows.append(row)
            continue
        env = os.environ.copy()
        env["R1000_CONC_GROSS_CAP_FLOOR"] = str(floor)
        rc_vnext = _run(vnext_cmd, env, arm_dir / "vnext.log")
        rc_broker = 1
        if Path(REPO_ROOT / book).is_file():
            rc_broker = _run(broker_cmd, env, arm_dir / "broker.log")
        row["vnext_returncode"] = rc_vnext
        row["broker_returncode"] = rc_broker
        row.update({f"conc_{k}": v for k, v in read_metrics(REPO_ROOT / arm_dir / "broker" / "metrics.json").items()})
        rows.append(row)
    return rows


def run_daily_stop_sweep(args: argparse.Namespace, output_dir: Path) -> list[dict[str, Any]]:
    books = {"main": args.main_book, "concentrated": args.concentrated_book}
    rows: list[dict[str, Any]] = []
    for label, hard, trailing in parse_daily_stop_grid(args.daily_stop_grid):
        arm_dir = output_dir / f"daily_stop_{label}"
        row: dict[str, Any] = {"lever": "daily_stop", "label": label, "hard_stop": hard, "trailing_stop": trailing}
        for kind, book in books.items():
            cmd = daily_stop_command(
                label, hard, trailing,
                portfolio_kind=kind,
                target_book=book,
                price_cache=args.price_cache,
                out_dir=arm_dir,
                cost_bps=args.cost_bps,
                max_fill_lag_days=args.max_fill_lag_days,
            )
            if args.dry_run:
                row[f"{kind}_cmd"] = " ".join(cmd)
                continue
            if not (REPO_ROOT / book).is_file():
                row[f"{kind}_status"] = "missing_book"
                continue
            rc = _run(cmd, os.environ.copy(), arm_dir / f"{kind}.log")
            row[f"{kind}_returncode"] = rc
            row.update({f"{kind}_{k}": v for k, v in read_metrics(REPO_ROOT / arm_dir / kind / "metrics.json").items()})
        rows.append(row)
    return rows


def write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# Lever sweep report", ""]
    cg = summary.get("conc_gross_floor", [])
    if cg:
        lines += ["## Concentrated gross-cap floor (vs broker-ledger next-close)", ""]
        lines += ["| floor | conc CAGR | conc MaxDD | conc Sharpe | conc avg_cash |", "|---|---|---|---|---|"]
        for r in cg:
            lines.append(
                f"| {r.get('floor')} | {r.get('conc_cagr')} | {r.get('conc_max_dd')} | "
                f"{r.get('conc_sharpe')} | {r.get('conc_avg_cash_weight')} |"
            )
        lines.append("")
    ds = summary.get("daily_stop", [])
    if ds:
        lines += ["## Daily position stop (broker position-risk replay)", ""]
        lines += ["| stop | main CAGR | main MaxDD | conc CAGR | conc MaxDD |", "|---|---|---|---|---|"]
        for r in ds:
            lines.append(
                f"| {r.get('label')} | {r.get('main_cagr')} | {r.get('main_max_dd')} | "
                f"{r.get('concentrated_cagr')} | {r.get('concentrated_max_dd')} |"
            )
        lines.append("")
    (output_dir / "sweep_report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--main-book", default=OPERATING_MAIN_BOOK)
    parser.add_argument("--concentrated-book", default=OPERATING_CONCENTRATED_BOOK)
    parser.add_argument("--concentrated-target-n", type=int, default=5)
    parser.add_argument(
        "--conc-gross-floors",
        default="0.0,0.7,0.8,0.9",
        help="comma list; 0.0 reproduces current production schedule (control)",
    )
    parser.add_argument(
        "--daily-stop-grid",
        default="default,-0.12:-0.20,-0.10:-0.15,-0.08:-0.12",
        help="comma list of 'default' or '<hard>:<trailing>' pairs",
    )
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--skip-conc-gross", action="store_true")
    parser.add_argument("--skip-daily-stop", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="build commands only; no execution")
    args = parser.parse_args(argv)

    output_dir = REPO_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "dry_run": bool(args.dry_run),
        "candidate_book": resolve_candidate_book(args.candidate_book),
        "conc_gross_floors": args.conc_gross_floors,
        "daily_stop_grid": args.daily_stop_grid,
    }
    if not args.skip_conc_gross:
        summary["conc_gross_floor"] = run_conc_gross_sweep(args, output_dir)
    if not args.skip_daily_stop:
        summary["daily_stop"] = run_daily_stop_sweep(args, output_dir)

    write_report(output_dir, summary)
    print(f"[lever-sweep] wrote {output_dir / 'summary.json'} (dry_run={args.dry_run})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
