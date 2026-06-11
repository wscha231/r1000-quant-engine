#!/usr/bin/env python3
"""Preemptive crisis-governor overlay filter (research-only).

Takes one operating target book + the PIT daily crisis features parquet, applies
the Phase E exposure ladder (``r1000_crisis_governor.apply_exposure_ladder`` via
``build_crisis_governed_target_books.build_governed_book``), and writes the
governed book in the same schema so it can be broker-replayed.

This wraps the existing Phase E builder into the same single-book CLI shape used
by the other overlay filters (run_neutral_regime_churn_filter,
run_macro_circuit_breaker_filter, run_regime_capacity_filter,
run_main_top_n_concentration_filter, run_residual_cash_redeploy_filter,
run_gate_ablation_filter). That lets ``run_overlay_combination_search`` chain it
exactly like every other knob and grade preemptive crisis defense on the
official broker-daily next-close metric.

Graceful degradation: if ``--crisis-features`` is missing or empty, the filter
PASSES THROUGH (copies input to output) with status ``passthrough_no_features``
so the overlay search's A/B (off vs conservative) just shows zero effect rather
than crashing. Mode ``off`` is also explicit passthrough (sanity baseline).

Research-only. Never mutates production code or live policy. The Phase E
governor itself is unchanged; this wrapper only re-shapes its CLI surface.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_governor_builder():
    """Lazy-load build_crisis_governed_target_books so import errors surface clearly."""
    spec = importlib.util.spec_from_file_location(
        "bcgtb", str(REPO_ROOT / "tools" / "build_crisis_governed_target_books.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def repo_path(path_like: str | Path) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else REPO_ROOT / p


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def passthrough(input_book: Path, output_book: Path, reason: str) -> dict[str, Any]:
    """Copy input -> output unchanged."""
    output_book.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_book, output_book)
    return {
        "status": "passthrough",
        "passthrough_reason": reason,
        "input_book": str(input_book),
        "output_book": str(output_book),
    }


def run(
    *,
    input_book: Path,
    output_book: Path,
    diagnostics_path: Path,
    crisis_features: Path,
    portfolio_kind: str,
    mode: str,
    allow_normal_cash_deploy: bool,
    cash_hard_gate: bool,
    thresholds_json: Path | None,
) -> dict[str, Any]:
    if not input_book.exists():
        payload = {"status": "blocked", "reason": f"input book not found: {input_book}", "input_book": str(input_book)}
        write_json(diagnostics_path, payload)
        return payload

    # Passthrough for explicit off mode or when features are absent — the
    # overlay search A/B then just measures "no change" for that combo.
    if mode == "off":
        payload = passthrough(input_book, output_book, "mode=off")
        write_json(diagnostics_path, payload)
        return payload
    if not crisis_features.exists():
        payload = passthrough(input_book, output_book, f"crisis_features missing: {crisis_features}")
        write_json(diagnostics_path, payload)
        return payload

    bcgtb = _load_governor_builder()
    if mode not in bcgtb.GOVERNOR_MODES:
        payload = {
            "status": "blocked",
            "reason": f"unknown mode '{mode}' (have: {sorted(bcgtb.GOVERNOR_MODES)})",
            "input_book": str(input_book),
        }
        write_json(diagnostics_path, payload)
        return payload

    try:
        governed, audit, summary = bcgtb.build_governed_book(
            target_book=input_book,
            crisis_features=crisis_features,
            portfolio_kind=portfolio_kind,
            mode=mode,
            allow_normal_cash_deploy=bool(allow_normal_cash_deploy),
            cash_hard_gate=bool(cash_hard_gate),
            thresholds_json=thresholds_json,
        )
    except Exception as exc:  # pragma: no cover - surface clean error
        payload = {
            "status": "blocked",
            "reason": f"build_governed_book raised: {exc!r}",
            "input_book": str(input_book),
            "mode": mode,
        }
        write_json(diagnostics_path, payload)
        return payload

    if governed is None or governed.empty:
        # The builder returned no rows (e.g. mode disabled + no schedule);
        # safer to passthrough than write an empty book.
        payload = passthrough(input_book, output_book, "governor produced empty book")
        write_json(diagnostics_path, payload)
        return payload

    output_book.parent.mkdir(parents=True, exist_ok=True)
    governed.to_csv(output_book, index=False)
    # Compress audit + summary into diagnostics so the overlay search worker can
    # tail it without re-loading the full files.
    diag = {
        "status": "completed",
        "input_book": str(input_book),
        "output_book": str(output_book),
        "crisis_features": str(crisis_features),
        "portfolio_kind": portfolio_kind,
        "mode": mode,
        "allow_normal_cash_deploy": bool(allow_normal_cash_deploy),
        "cash_hard_gate": bool(cash_hard_gate),
        "thresholds_json": str(thresholds_json) if thresholds_json else None,
        "rows": int(len(governed)),
        "audit_rows": int(len(audit)) if audit is not None else 0,
        "summary": summary if isinstance(summary, dict) else {},
    }
    write_json(diagnostics_path, diag)
    return diag


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-book", required=True)
    p.add_argument("--output-book", required=True)
    p.add_argument("--diagnostics", required=True)
    p.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="concentrated")
    p.add_argument("--mode", default="conservative",
                   help="Governor mode: off | conservative | aggressive | learned. 'off' is explicit passthrough.")
    p.add_argument("--crisis-features", default="outputs/crisis_signals/daily_features.parquet",
                   help="PIT daily crisis features parquet. If missing, the filter passes through.")
    p.add_argument("--allow-normal-cash-deploy", action="store_true",
                   help="Allow the ladder to deploy cash on normal-zone dates (paired with redeploy filter).")
    p.add_argument("--cash-hard-gate", action="store_true",
                   help="Require liquidity/trend/credit confirmation before defense/crisis cash raises.")
    p.add_argument("--thresholds-json", default="",
                   help="Optional best_thresholds.json from long crisis learning (overrides mode defaults).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    thresholds = repo_path(args.thresholds_json) if args.thresholds_json else None
    payload = run(
        input_book=repo_path(args.input_book),
        output_book=repo_path(args.output_book),
        diagnostics_path=repo_path(args.diagnostics),
        crisis_features=repo_path(args.crisis_features),
        portfolio_kind=args.portfolio_kind,
        mode=str(args.mode),
        allow_normal_cash_deploy=bool(args.allow_normal_cash_deploy),
        cash_hard_gate=bool(args.cash_hard_gate),
        thresholds_json=thresholds,
    )
    print(json.dumps({k: v for k, v in payload.items() if k != "summary"}, indent=2, default=str))
    return 0 if payload.get("status") in {"completed", "passthrough"} else 2


if __name__ == "__main__":
    sys.exit(main())
