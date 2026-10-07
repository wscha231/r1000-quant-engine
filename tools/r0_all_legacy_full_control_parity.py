#!/usr/bin/env python3
"""R0 direct-native vs modular all-LEGACY full-Control parity runner.

Research-only. The runner never mutates paper/public/broker authority and
never applies G2. It uses the existing AlphaOps native Control, the G1
all-LEGACY adapter, the existing broker-ledger replay CLI, and the G3 read-only
difference reporter. Missing real frozen inputs fail closed as
BLOCKED_REAL_R0_INPUT; structural fixtures are never promoted to R0 PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import subprocess
import sys
from argparse import Namespace
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from tools.legacy_control_adapter import (
    EvaluationSpec,
    LEGACY_ACCOUNTING_EVALUATOR_REF,
    LEGACY_EXECUTION_MODE,
    LEGACY_MODULE_ID,
    LEGACY_NATIVE_STARTING_CAPITAL,
    LEGACY_STRATEGY_VERSION,
    StrategySpec,
    run_control,
    validate_evaluation_spec,
    validate_strategy_spec,
)
from tools.strategy_difference_reporter import (
    NOT_AVAILABLE,
    compare_replay_outputs,
    load_replay_bundle,
)

TASK_KEY = "R1000-R0-ALL-LEGACY-FULL-CONTROL-PARITY-20261007"
STATUS_PASS = "R0_FULL_CONTROL_PARITY_PASS"
STATUS_BLOCKED = "BLOCKED_REAL_R0_INPUT"
STATUS_TARGET_FAIL = "R0_TARGET_PARITY_FAIL"
STATUS_BROKER_FAIL = "R0_BROKER_PARITY_FAIL"
STATUS_G3_FAIL = "R0_G3_DIVERGENCE"
MASTER_AT_START = "6a2fa606896a2f263fffa07b9273d60f2d011626"
G1_HEAD = "a37d50026850eb76e7454fa7ae02ad7a66d43319"
G2_HEAD = "f7bd98b43209b4cebb0e0c78f17963b6aba3795d"
G3_HEAD = "451b67cfb132921088b73a883f03116417b85fa6"
RTOL = 1e-9
ATOL = 1e-10
NON_ECONOMIC_COLUMNS = {
    "generated_at",
    "generated_at_utc",
    "output_dir",
    "output_path",
    "temporary_output_path",
}
REQUIRED_REPLAY_FILES = (
    "trades.csv",
    "holdings_daily.csv",
    "positions_latest.csv",
    "cash_ledger.csv",
    "equity_curve.csv",
    "account_state_latest.json",
    "metrics.json",
)
OPTIONAL_REPLAY_FILES = ("orders.csv",)
REDACT_JSON_KEYS = {
    "generated_at",
    "generated_at_utc",
    "output_dir",
    "output_path",
    "temporary_output_path",
}


class R0ContractError(RuntimeError):
    pass


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_path(path: Path) -> dict[str, Any]:
    """Deterministic content identity for one file or directory."""
    path = path.resolve()
    if not path.exists():
        raise R0ContractError(f"missing frozen input:{path}")
    if path.is_symlink():
        raise R0ContractError(f"symlink frozen input is not admitted:{path}")
    if path.is_file():
        if path.stat().st_size <= 0:
            raise R0ContractError(f"empty frozen input:{path}")
        return {
            "kind": "file",
            "sha256": _sha256_file(path),
            "size": path.stat().st_size,
        }
    if not path.is_dir():
        raise R0ContractError(f"unsupported frozen input type:{path}")
    files = sorted(p for p in path.rglob("*") if p.is_file())
    if not files:
        raise R0ContractError(f"empty frozen input directory:{path}")
    digest = hashlib.sha256()
    total = 0
    members = 0
    for member in files:
        if member.is_symlink():
            raise R0ContractError(f"symlink member is not admitted:{member}")
        rel = member.relative_to(path).as_posix()
        file_sha = _sha256_file(member)
        size = member.stat().st_size
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_sha.encode("ascii"))
        digest.update(b"\n")
        total += size
        members += 1
    return {
        "kind": "directory",
        "sha256": digest.hexdigest(),
        "file_count": members,
        "total_size": total,
    }


def identity_for_ref(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        raise R0ContractError("blank frozen input reference")
    path = Path(text)
    if path.exists():
        return {"ref": text, "content": hash_path(path)}
    return {
        "ref": text,
        "content": None,
        "ref_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "identity_mode": "deterministic_reference_only",
    }


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_isolated_paths(
    *,
    direct_dir: Path,
    modular_dir: Path,
    frozen_paths: list[Path],
) -> None:
    direct = direct_dir.resolve()
    modular = modular_dir.resolve()
    if direct == modular:
        raise R0ContractError("direct and modular output directories must differ")
    if _is_relative_to(direct, modular) or _is_relative_to(modular, direct):
        raise R0ContractError("direct and modular output directories must not overlap")
    for raw in frozen_paths:
        frozen = raw.resolve()
        if direct == frozen or modular == frozen:
            raise R0ContractError("output directory aliases frozen input")
        if _is_relative_to(direct, frozen) or _is_relative_to(modular, frozen):
            raise R0ContractError("output directory is nested inside frozen input")
        if _is_relative_to(frozen, direct) or _is_relative_to(frozen, modular):
            raise R0ContractError("frozen input is nested inside output directory")


def build_legacy_specs(
    *,
    candidate_ref: str,
    crisis_features_ref: str,
    crisis_thresholds_ref: str,
) -> tuple[StrategySpec, StrategySpec]:
    common = dict(
        candidate_source_ref=candidate_ref,
        regime_crisis_ref=(crisis_features_ref, crisis_thresholds_ref),
        discovery_module=LEGACY_MODULE_ID,
        entry_module=LEGACY_MODULE_ID,
        hold_exit_module=LEGACY_MODULE_ID,
        regime_module=LEGACY_MODULE_ID,
        allocation_module=LEGACY_MODULE_ID,
        version=LEGACY_STRATEGY_VERSION,
        parameters=(),
    )
    main = StrategySpec(portfolio_kind="main", target_n=15, **common)
    concentrated = StrategySpec(portfolio_kind="concentrated", target_n=5, **common)
    validate_r0_strategy(main)
    validate_r0_strategy(concentrated)
    return main, concentrated


def validate_r0_strategy(spec: StrategySpec) -> None:
    validate_strategy_spec(spec)
    if spec.hold_exit_module != LEGACY_MODULE_ID or spec.parameters != ():
        raise R0ContractError("G2 treatment is forbidden in R0")
    modules = (
        spec.discovery_module,
        spec.entry_module,
        spec.hold_exit_module,
        spec.regime_module,
        spec.allocation_module,
    )
    if any(module != LEGACY_MODULE_ID for module in modules):
        raise R0ContractError("R0 requires all-LEGACY modules")


def build_evaluation_spec(
    *,
    universe_data_ref: str,
    calendar_ref: str,
    price_cache_ref: str,
) -> EvaluationSpec:
    spec = EvaluationSpec(
        universe_data_ref=universe_data_ref,
        calendar_ref=calendar_ref,
        price_cache_ref=price_cache_ref,
        execution_mode=LEGACY_EXECUTION_MODE,
        cost_bps=25.0,
        integer_shares=True,
        max_fill_lag_days=7,
        accounting_evaluator_ref=LEGACY_ACCOUNTING_EVALUATOR_REF,
        evaluation_window=(None, None),
        initial_capital=LEGACY_NATIVE_STARTING_CAPITAL,
    )
    validate_evaluation_spec(spec)
    return spec


def _native_args(
    *,
    latest_run: Path,
    candidate_book: Path,
    price_cache: Path,
    output_dir: Path,
    crisis_features: Path,
    crisis_thresholds: Path,
) -> Namespace:
    return Namespace(
        latest_run=str(latest_run),
        candidate_book=str(candidate_book),
        price_cache=str(price_cache),
        output_dir=str(output_dir),
        portfolio_kind="both",
        main_target_n=15,
        concentrated_target_n=5,
        production_output_mode="shadow_only",
        skip_broker_replay=True,
        run_current_report=False,
        cost_bps=25.0,
        max_fill_lag_days=7,
        long_crisis_features=str(crisis_features),
        long_crisis_thresholds=str(crisis_thresholds),
    )


def validate_native_identity(
    main_spec: StrategySpec,
    concentrated_spec: StrategySpec,
    evaluation: EvaluationSpec,
    args: Namespace,
) -> None:
    validate_r0_strategy(main_spec)
    validate_r0_strategy(concentrated_spec)
    validate_evaluation_spec(evaluation)
    if args.portfolio_kind != "both":
        raise R0ContractError("R0 native arm requires portfolio_kind=both")
    if args.main_target_n != 15 or args.concentrated_target_n != 5:
        raise R0ContractError("R0 target counts must be Main15/Concentrated5")
    if args.production_output_mode != "shadow_only":
        raise R0ContractError("R0 must not replace operating target books")
    if not args.skip_broker_replay:
        raise R0ContractError("R0 target parity must gate broker replay")
    if str(args.candidate_book) != main_spec.candidate_source_ref:
        raise R0ContractError("candidate identity mismatch")
    if str(args.candidate_book) != concentrated_spec.candidate_source_ref:
        raise R0ContractError("candidate identity mismatch")
    crisis = (str(args.long_crisis_features), str(args.long_crisis_thresholds))
    if crisis != main_spec.regime_crisis_ref or crisis != concentrated_spec.regime_crisis_ref:
        raise R0ContractError("crisis identity mismatch")
    if str(args.price_cache) != evaluation.price_cache_ref:
        raise R0ContractError("price-cache identity mismatch")
    if float(args.cost_bps) != float(evaluation.cost_bps):
        raise R0ContractError("cost contract mismatch")
    if int(args.max_fill_lag_days) != evaluation.max_fill_lag_days:
        raise R0ContractError("max-fill-lag contract mismatch")


def _normalize_cell(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return float(value)
    return str(value)


def _numeric_equal(left: Any, right: Any) -> bool:
    try:
        a = float(left)
        b = float(right)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(a) or not math.isfinite(b):
        return a == b
    return math.isclose(a, b, rel_tol=RTOL, abs_tol=ATOL)


def _frame_records(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    frame = pd.read_csv(path)
    columns = [c for c in frame.columns if c not in NON_ECONOMIC_COLUMNS]
    frame = frame[columns].copy()
    sort_keys = [c for c in ("rebalance_date", "date", "ticker", "side", "reason") if c in frame.columns]
    if sort_keys:
        frame = frame.sort_values(sort_keys, kind="mergesort", na_position="last").reset_index(drop=True)
    else:
        frame = frame.reset_index(drop=True)
    rows = [
        {col: _normalize_cell(row[col]) for col in columns}
        for _, row in frame.iterrows()
    ]
    return columns, rows


def _numeric_or_equal(left: Any, right: Any) -> bool:
    return left == right or _numeric_equal(left, right)


def compare_csv(path_a: Path, path_b: Path) -> dict[str, Any]:
    if not path_a.exists() or not path_b.exists():
        return {
            "status": "divergence",
            "reason": "missing_file",
            "left_exists": path_a.exists(),
            "right_exists": path_b.exists(),
        }
    cols_a, rows_a = _frame_records(path_a)
    cols_b, rows_b = _frame_records(path_b)
    if cols_a != cols_b:
        return {
            "status": "divergence",
            "reason": "columns",
            "left": cols_a,
            "right": cols_b,
        }
    if len(rows_a) != len(rows_b):
        return {
            "status": "divergence",
            "reason": "row_count",
            "left": len(rows_a),
            "right": len(rows_b),
        }
    for index, (left, right) in enumerate(zip(rows_a, rows_b)):
        for col in cols_a:
            a = left[col]
            b = right[col]
            if _numeric_or_equal(a, b):
                continue
            return {
                "status": "divergence",
                "reason": "value",
                "row": index,
                "column": col,
                "left": a,
                "right": b,
                "row_identity": {
                    key: left.get(key)
                    for key in ("rebalance_date", "date", "ticker", "side")
                    if key in left
                },
            }
    return {"status": "parity", "rows": len(rows_a), "columns": cols_a}


def _strip_json_provenance(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_json_provenance(child)
            for key, child in sorted(value.items())
            if key not in REDACT_JSON_KEYS
        }
    if isinstance(value, list):
        return [_strip_json_provenance(child) for child in value]
    return value


def _compare_json_values(left: Any, right: Any, path: str = "$") -> dict[str, Any] | None:
    if type(left) is not type(right):
        if _numeric_equal(left, right):
            return None
        return {"path": path, "left": left, "right": right, "reason": "type_or_value"}
    if isinstance(left, dict):
        if set(left) != set(right):
            return {
                "path": path,
                "left_keys": sorted(left),
                "right_keys": sorted(right),
                "reason": "keys",
            }
        for key in sorted(left):
            diff = _compare_json_values(left[key], right[key], f"{path}.{key}")
            if diff is not None:
                return diff
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return {"path": path, "left": len(left), "right": len(right), "reason": "length"}
        for index, (a, b) in enumerate(zip(left, right)):
            diff = _compare_json_values(a, b, f"{path}[{index}]")
            if diff is not None:
                return diff
        return None
    if _numeric_or_equal(left, right):
        return None
    return {"path": path, "left": left, "right": right, "reason": "value"}


def compare_json(path_a: Path, path_b: Path) -> dict[str, Any]:
    if not path_a.exists() or not path_b.exists():
        return {
            "status": "divergence",
            "reason": "missing_file",
            "left_exists": path_a.exists(),
            "right_exists": path_b.exists(),
        }
    left = _strip_json_provenance(json.loads(path_a.read_text(encoding="utf-8")))
    right = _strip_json_provenance(json.loads(path_b.read_text(encoding="utf-8")))
    diff = _compare_json_values(left, right)
    return {"status": "parity"} if diff is None else {"status": "divergence", **diff}


def compare_target_books(direct_dir: Path, modular_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind in ("main", "concentrated"):
        name = f"official_{kind}_target_book.csv"
        result[kind] = compare_csv(direct_dir / name, modular_dir / name)
    result["status"] = (
        "parity"
        if all(result[kind]["status"] == "parity" for kind in ("main", "concentrated"))
        else "divergence"
    )
    return result


def target_gate_then(
    target_result: dict[str, Any],
    broker_callable: Callable[[], Any],
) -> tuple[bool, Any]:
    if target_result.get("status") != "parity":
        return False, None
    return True, broker_callable()


def _run_broker_cli(
    *,
    target_book: Path,
    price_cache: Path,
    portfolio_kind: str,
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.exists():
        raise R0ContractError(f"broker output already exists:{output_dir}")
    cmd = [
        sys.executable,
        "tools/run_broker_ledger_replay.py",
        "--target-book",
        str(target_book),
        "--price-cache",
        str(price_cache),
        "--portfolio-kind",
        portfolio_kind,
        "--output-dir",
        str(output_dir),
        "--fill-mode",
        "next_close",
        "--cost-bps",
        "25",
        "--max-fill-lag-days",
        "7",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise R0ContractError(
            f"broker replay failed:{portfolio_kind}:{proc.returncode}:"
            + (proc.stderr[-2000:] or proc.stdout[-2000:])
        )
    return {"command": cmd, "returncode": proc.returncode}


def compare_replay_artifacts(control: Path, candidate: Path) -> dict[str, Any]:
    if control.resolve() == candidate.resolve():
        raise R0ContractError("replay refs accidentally point to the same directory")
    artifacts: dict[str, Any] = {}
    not_available: list[str] = []
    for name in REQUIRED_REPLAY_FILES:
        left = control / name
        right = candidate / name
        if name.endswith(".json"):
            result = compare_json(left, right)
        else:
            result = compare_csv(left, right)
        artifacts[name] = result
        if result.get("status") != "parity":
            return {
                "status": "divergence",
                "artifact": name,
                "first_divergence": result,
                "artifacts": artifacts,
                "not_available": not_available,
            }
    for name in OPTIONAL_REPLAY_FILES:
        left = control / name
        right = candidate / name
        if not left.exists() and not right.exists():
            artifacts[name] = {"status": NOT_AVAILABLE}
            not_available.append(name)
            continue
        result = compare_csv(left, right)
        artifacts[name] = result
        if result.get("status") != "parity":
            return {
                "status": "divergence",
                "artifact": name,
                "first_divergence": result,
                "artifacts": artifacts,
                "not_available": not_available,
            }

    trades = pd.read_csv(control / "trades.csv")
    if trades.empty:
        return {
            "status": "blocked_empty_trades",
            "reason": "real admissible R0 requires nonempty economic replay",
            "artifacts": artifacts,
            "not_available": not_available,
        }
    metrics = json.loads((control / "metrics.json").read_text(encoding="utf-8"))
    trade_count = metrics.get("trade_count")
    if trade_count is None or float(trade_count) <= 0:
        return {
            "status": "blocked_empty_trades",
            "reason": "evaluator trade_count is unavailable or zero",
            "artifacts": artifacts,
            "not_available": not_available,
        }
    return {
        "status": "parity",
        "artifacts": artifacts,
        "not_available": not_available,
    }


def run_g3_comparison(control: Path, candidate: Path, portfolio_kind: str) -> dict[str, Any]:
    if control.resolve() == candidate.resolve():
        raise R0ContractError("G3 control/candidate replay refs must differ")
    before = {
        "control": hash_path(control),
        "candidate": hash_path(candidate),
    }
    report, events, deltas = compare_replay_outputs(
        load_replay_bundle(control, label=f"r0_direct_{portfolio_kind}"),
        load_replay_bundle(candidate, label=f"r0_modular_{portfolio_kind}"),
        strategy_id="r0-all-legacy-control-parity",
        variant_id="modular-all-legacy",
        parent_strategy_id="direct-native-control",
        changed_module="none",
        changed_module_version="LEGACY",
        evaluation_ref="eval:broker_ledger_next_close:25bps:integer:maxlag7:100000",
        control_replay_ref=str(control),
        candidate_replay_ref=str(candidate),
        module_id="LEGACY",
        module_version=LEGACY_STRATEGY_VERSION,
        policy_id="R0_ZERO_TREATMENT",
        hold_exit_policy_config="{}",
        policy_audit_identity=hashlib.sha256(b"R0_ZERO_TREATMENT").hexdigest(),
    )
    after = {
        "control": hash_path(control),
        "candidate": hash_path(candidate),
    }
    if before != after:
        raise R0ContractError("G3 comparison mutated replay input")
    return {
        "report": report,
        "event_rows": int(len(events)),
        "session_delta_rows": int(len(deltas)),
        "read_only_verified": True,
    }


def _blocked_inputs(
    *,
    latest_run: Path,
    candidate_book: Path,
    price_cache: Path,
    crisis_features: Path,
    crisis_thresholds: Path,
) -> list[str]:
    missing: list[str] = []
    required_files = {
        "candidate_book": candidate_book,
        "crisis_features": crisis_features,
        "crisis_thresholds": crisis_thresholds,
    }
    if not latest_run.is_dir():
        missing.append(f"latest_run:{latest_run}")
    for label, path in required_files.items():
        if not path.is_file() or path.stat().st_size <= 0:
            missing.append(f"{label}:{path}")
    if not price_cache.is_dir():
        missing.append(f"price_cache:{price_cache}")
    elif not any(p.is_file() and p.stat().st_size > 0 for p in price_cache.rglob("*")):
        missing.append(f"price_cache_empty:{price_cache}")
    return missing


def _policy_env_identity() -> str:
    allowed_prefixes = (
        "PHASE_",
        "ALPHAOPS_",
        "R1000_CONC_",
    )
    values = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(allowed_prefixes)
    }
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _receipt_base(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "task_key": TASK_KEY,
        "master_sha": args.master_sha,
        "g1_head": G1_HEAD,
        "g2_head": G2_HEAD,
        "g3_head": G3_HEAD,
        "r0_integration_head": args.integration_head or "UNKNOWN_UNTIL_COMMIT",
        "authority": "RESEARCH_VALIDATION_ONLY",
        "approved_target_authority": False,
        "paper_authority": False,
        "broker_authority": False,
        "public_authority": False,
        "g2_treatment_applied": False,
    }


def _metric_view(metrics_path: Path) -> dict[str, Any]:
    if not metrics_path.exists():
        return {}
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    keys = (
        "ending_capital_usd",
        "ending_equity_usd",
        "cash_usd",
        "ending_cash_usd",
        "total_fees_usd",
        "trade_count",
        "turnover",
        "cagr",
        "max_dd",
    )
    return {
        key: payload.get(key, NOT_AVAILABLE)
        for key in keys
        if key in payload or key == "turnover"
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    receipt = _receipt_base(args)
    if args.g2_treatment:
        raise R0ContractError("G2 selected in R0: fail closed")

    latest_run = Path(args.latest_run).resolve()
    candidate_book = Path(args.candidate_book).resolve()
    price_cache = Path(args.price_cache).resolve()
    crisis_features = Path(args.long_crisis_features).resolve()
    crisis_thresholds = Path(args.long_crisis_thresholds).resolve()
    output_root = Path(args.output_root).resolve()
    direct_target_dir = output_root / "direct_control" / "target"
    modular_target_dir = output_root / "modular_legacy" / "target"
    direct_replay_root = output_root / "direct_control" / "replay"
    modular_replay_root = output_root / "modular_legacy" / "replay"

    validate_isolated_paths(
        direct_dir=direct_target_dir,
        modular_dir=modular_target_dir,
        frozen_paths=[
            latest_run,
            candidate_book,
            price_cache,
            crisis_features,
            crisis_thresholds,
        ],
    )
    validate_isolated_paths(
        direct_dir=direct_replay_root,
        modular_dir=modular_replay_root,
        frozen_paths=[
            latest_run,
            candidate_book,
            price_cache,
            crisis_features,
            crisis_thresholds,
        ],
    )
    if output_root.exists():
        raise R0ContractError(f"R0 output root already exists:{output_root}")

    missing = _blocked_inputs(
        latest_run=latest_run,
        candidate_book=candidate_book,
        price_cache=price_cache,
        crisis_features=crisis_features,
        crisis_thresholds=crisis_thresholds,
    )
    if missing:
        receipt.update(
            {
                "status": STATUS_BLOCKED,
                "blockers": missing,
                "not_run": [
                    "direct native target materialization",
                    "modular G1 target materialization",
                    "broker replay",
                    "G3 comparison",
                    "G2 treatment",
                    "R1",
                ],
            }
        )
        output_root.mkdir(parents=True, exist_ok=False)
        _json_dump(output_root / "r0_receipt.json", receipt)
        return receipt

    input_paths = {
        "latest_run": latest_run,
        "candidate_book": candidate_book,
        "price_cache": price_cache,
        "crisis_features": crisis_features,
        "crisis_thresholds": crisis_thresholds,
    }
    input_hashes_before = {key: hash_path(path) for key, path in input_paths.items()}
    reference_identities = {
        "universe_data_ref": identity_for_ref(args.universe_data_ref),
        "calendar_ref": identity_for_ref(args.calendar_ref),
    }

    main_spec, concentrated_spec = build_legacy_specs(
        candidate_ref=str(candidate_book),
        crisis_features_ref=str(crisis_features),
        crisis_thresholds_ref=str(crisis_thresholds),
    )
    evaluation = build_evaluation_spec(
        universe_data_ref=args.universe_data_ref,
        calendar_ref=args.calendar_ref,
        price_cache_ref=str(price_cache),
    )
    direct_args = _native_args(
        latest_run=latest_run,
        candidate_book=candidate_book,
        price_cache=price_cache,
        output_dir=direct_target_dir,
        crisis_features=crisis_features,
        crisis_thresholds=crisis_thresholds,
    )
    modular_args = deepcopy(direct_args)
    modular_args.output_dir = str(modular_target_dir)
    validate_native_identity(main_spec, concentrated_spec, evaluation, direct_args)
    validate_native_identity(main_spec, concentrated_spec, evaluation, modular_args)

    receipt["direct_strategy_identity"] = {
        "route": "DIRECT_NATIVE_CONTROL",
        "module": "tools.run_alphaops_vnext_policy_replay.build",
        "main": asdict(main_spec),
        "concentrated": asdict(concentrated_spec),
    }
    receipt["modular_strategy_identity"] = {
        "route": "MODULAR_G1_ALL_LEGACY",
        "module": "tools.legacy_control_adapter.run_control",
        "main": asdict(main_spec),
        "concentrated": asdict(concentrated_spec),
    }
    receipt["evaluation_identity"] = asdict(evaluation)
    receipt["input_hashes"] = input_hashes_before
    receipt["reference_identities"] = reference_identities
    receipt["policy_env_sha256"] = _policy_env_identity()

    native = importlib.import_module("tools.run_alphaops_vnext_policy_replay")
    direct_result = native.build(direct_args)
    modular_result = run_control(
        main_spec,
        concentrated_spec,
        evaluation,
        args=modular_args,
    )
    receipt["direct_target_result_status"] = direct_result.get("status")
    receipt["modular_target_result_status"] = modular_result.get("status")

    input_hashes_after_target = {key: hash_path(path) for key, path in input_paths.items()}
    if input_hashes_after_target != input_hashes_before:
        raise R0ContractError("target materialization mutated frozen input")

    target_parity = compare_target_books(direct_target_dir, modular_target_dir)
    receipt["target_parity"] = target_parity
    if target_parity["status"] != "parity":
        receipt["status"] = STATUS_TARGET_FAIL
        receipt["first_divergence"] = next(
            (
                {"portfolio_kind": kind, **target_parity[kind]}
                for kind in ("main", "concentrated")
                if target_parity[kind]["status"] != "parity"
            ),
            None,
        )
        _json_dump(output_root / "r0_receipt.json", receipt)
        return receipt

    def broker_stage() -> dict[str, Any]:
        calls = {}
        for kind in ("main", "concentrated"):
            direct_replay = direct_replay_root / kind
            modular_replay = modular_replay_root / kind
            calls[f"direct_{kind}"] = _run_broker_cli(
                target_book=direct_target_dir / f"official_{kind}_target_book.csv",
                price_cache=price_cache,
                portfolio_kind=kind,
                output_dir=direct_replay,
            )
            calls[f"modular_{kind}"] = _run_broker_cli(
                target_book=modular_target_dir / f"official_{kind}_target_book.csv",
                price_cache=price_cache,
                portfolio_kind=kind,
                output_dir=modular_replay,
            )
        return calls

    gated, broker_calls = target_gate_then(target_parity, broker_stage)
    if not gated:
        raise R0ContractError("broker stage reached without target parity")
    receipt["broker_calls"] = broker_calls

    input_hashes_after_broker = {key: hash_path(path) for key, path in input_paths.items()}
    if input_hashes_after_broker != input_hashes_before:
        raise R0ContractError("broker replay mutated frozen input")

    broker_parity: dict[str, Any] = {}
    for kind in ("main", "concentrated"):
        broker_parity[kind] = compare_replay_artifacts(
            direct_replay_root / kind,
            modular_replay_root / kind,
        )
    receipt["broker_parity"] = broker_parity
    if any(
        broker_parity[kind]["status"] != "parity"
        for kind in ("main", "concentrated")
    ):
        receipt["status"] = STATUS_BROKER_FAIL
        receipt["first_divergence"] = next(
            (
                {"portfolio_kind": kind, **broker_parity[kind]}
                for kind in ("main", "concentrated")
                if broker_parity[kind]["status"] != "parity"
            ),
            None,
        )
        _json_dump(output_root / "r0_receipt.json", receipt)
        return receipt

    receipt["metric_parity"] = {
        kind: {
            "status": compare_json(
                direct_replay_root / kind / "metrics.json",
                modular_replay_root / kind / "metrics.json",
            )["status"],
            "metrics": _metric_view(direct_replay_root / kind / "metrics.json"),
        }
        for kind in ("main", "concentrated")
    }

    g3 = {
        kind: run_g3_comparison(
            direct_replay_root / kind,
            modular_replay_root / kind,
            kind,
        )
        for kind in ("main", "concentrated")
    }
    receipt["g3"] = g3
    bad_g3 = [
        kind
        for kind in ("main", "concentrated")
        if g3[kind]["report"].get("status") != "no_divergence"
    ]
    if bad_g3:
        receipt["status"] = STATUS_G3_FAIL
        kind = bad_g3[0]
        receipt["first_divergence"] = {
            "portfolio_kind": kind,
            "g3_report": g3[kind]["report"],
        }
        _json_dump(output_root / "r0_receipt.json", receipt)
        return receipt

    receipt["status"] = STATUS_PASS
    receipt["direct_replay_ref"] = str(direct_replay_root)
    receipt["modular_replay_ref"] = str(modular_replay_root)
    receipt["first_divergence"] = None
    receipt["not_available"] = sorted(
        {
            field
            for kind in ("main", "concentrated")
            for field in broker_parity[kind].get("not_available", [])
        }
    )
    _json_dump(output_root / "r0_receipt.json", receipt)
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--latest-run",
        default="cloud_results/full_rebuild/latest_global_alpha_universe",
    )
    parser.add_argument(
        "--candidate-book",
        default="cloud_results/full_rebuild/latest_global_alpha_universe/"
        "sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv",
    )
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument(
        "--long-crisis-features",
        default="cloud_results/full_rebuild/latest_global_alpha_universe/"
        "crisis_signals/daily_features.parquet",
    )
    parser.add_argument(
        "--long-crisis-thresholds",
        default="cloud_results/full_rebuild/latest_global_alpha_universe/"
        "long_crisis_learning/best_thresholds.json",
    )
    parser.add_argument(
        "--universe-data-ref",
        default="R1000_FULL_REBUILD_FROZEN_UNIVERSE",
    )
    parser.add_argument("--calendar-ref", default="NYSE_FULL_REBUILD_CALENDAR")
    parser.add_argument(
        "--output-root",
        default="outputs/research/r0_all_legacy_full_control_parity",
    )
    parser.add_argument("--master-sha", default=MASTER_AT_START)
    parser.add_argument("--integration-head", default="")
    parser.add_argument("--g2-treatment", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = run(args)
    except (R0ContractError, ValueError, TypeError) as exc:
        print(
            json.dumps(
                {
                    "task_key": TASK_KEY,
                    "status": "R0_FAIL_CLOSED",
                    "error": str(exc),
                },
                indent=2,
            )
        )
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
    return 0 if receipt.get("status") in {STATUS_PASS, STATUS_BLOCKED} else 3


if __name__ == "__main__":
    raise SystemExit(main())
