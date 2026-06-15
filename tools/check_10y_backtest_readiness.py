#!/usr/bin/env python3
"""Audit whether the engine is ready for a requested multi-year backtest window.

The original artifact was 10-year research readiness. PR64 also needs an
official 8-year broker-ledger readiness artifact, so this tool keeps the old
10-year keys for compatibility and emits generic window keys for the actual
requested horizon.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shlex
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_COVERAGE = "data_pit/free/coverage_audit.json"
DEFAULT_MANIFEST = "manifests/free_data/latest_manifest.json"
DEFAULT_PRICE_CACHE = "cache_prices"
DEFAULT_PRICE_MANIFEST = "data_raw/free/prices/replay_price_cache_manifest.json"
DEFAULT_OUTPUT_DIR = "outputs/ten_year_backtest_readiness"


def window_slug(min_years: float) -> str:
    if min_years >= 9.5:
        return "ten_year"
    if 7.95 <= min_years < 8.5:
        return "eight_year"
    return f"{str(min_years).replace('.', 'p')}_year"


def window_label(min_years: float) -> str:
    if min_years >= 9.5:
        return "10-year"
    if 7.95 <= min_years < 8.5:
        return "8-year"
    return f"{min_years:g}-year"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def years_input(min_years: float) -> str:
    if 7.95 <= min_years < 8.5:
        return "8"
    if min_years >= 9.5:
        return "10"
    return str(int(math.ceil(min_years)))


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def count_price_files(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(1 for item in path.glob("*.parquet") if item.is_file())


def non_cash_tickers_from_csv(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if "ticker" not in (reader.fieldnames or []):
            return set()
        for row in reader:
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker and ticker not in {"CASH", "__CASH__"}:
                out.add(ticker)
    return out


def csv_date_range(path: Path, columns: tuple[str, ...]) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "rows": 0, "min_date": None, "max_date": None, "unique_months": 0}
    rows = 0
    dates: list[date] = []
    months: set[str] = set()
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows += 1
            value = None
            for col in columns:
                if col in row:
                    value = row.get(col)
                    break
            dt = parse_date(value)
            if dt:
                dates.append(dt)
                months.add(dt.strftime("%Y-%m"))
    return {
        "exists": True,
        "rows": rows,
        "min_date": min(dates).isoformat() if dates else None,
        "max_date": max(dates).isoformat() if dates else None,
        "unique_months": len(months),
    }


def metric_summary(path: Path) -> dict[str, Any]:
    metrics = read_json(path, {}) or {}
    start = parse_date(metrics.get("start_date"))
    end = parse_date(metrics.get("end_date"))
    years = safe_float(metrics.get("years"))
    if years is None and start and end:
        years = (end - start).days / 365.25
    return {
        "exists": path.exists(),
        "status": metrics.get("status"),
        "start_date": start.isoformat() if start else None,
        "end_date": end.isoformat() if end else None,
        "years": round(years, 4) if years is not None else None,
        "cagr": safe_float(metrics.get("cagr")),
        "sharpe": safe_float(metrics.get("sharpe")),
        "max_dd": safe_float(metrics.get("max_dd") if "max_dd" in metrics else metrics.get("max_drawdown")),
        "valid_for_production": metrics.get("valid_for_production"),
        "metric_mode": metrics.get("metric_mode"),
    }


def years_ready(start: date | None, end: date | None, min_years: float) -> bool:
    if not start or not end:
        return False
    return ((end - start).days / 365.25) >= min_years


def required_start_date(end: date | None, min_years: float) -> date | None:
    if not end:
        return None
    return end - timedelta(days=int(math.ceil(min_years * 365.25)))


def iso_or_none(value: date | None) -> str | None:
    return value.isoformat() if value else None


def plan_status(ok: bool) -> str:
    return "ready" if ok else "needs_extension"


def add_plan_task(
    tasks: list[dict[str, Any]],
    *,
    task_id: str,
    scope: str,
    ready: bool,
    current: Any,
    required: Any,
    action: str,
    hard_blocker: bool = True,
) -> None:
    tasks.append(
        {
            "task_id": task_id,
            "scope": scope,
            "status": plan_status(ready),
            "hard_blocker": bool(hard_blocker and not ready),
            "current": current,
            "required": required,
            "action": action if not ready else "none",
        }
    )


def build_data_extension_plan(
    *,
    latest_run: Path,
    price_start: date | None,
    price_end: date | None,
    required_tickers: int,
    requested_tickers: int,
    effective_price_files: int,
    main_book: dict[str, Any],
    concentrated_book: dict[str, Any],
    main_broker: dict[str, Any],
    concentrated_broker: dict[str, Any],
    sec_available: bool,
    pit_safe: bool,
    min_years: float,
    label: str,
) -> dict[str, Any]:
    observed_ends = [
        item
        for item in [
            price_end,
            parse_date(main_book.get("max_date")),
            parse_date(concentrated_book.get("max_date")),
            parse_date(main_broker.get("end_date")),
            parse_date(concentrated_broker.get("end_date")),
        ]
        if item is not None
    ]
    target_end = max(observed_ends) if observed_ends else datetime.now(timezone.utc).date()
    target_start = required_start_date(target_end, min_years)
    main_tickers = non_cash_tickers_from_csv(latest_run / "reports" / "main_monthly_weights.csv")
    concentrated_tickers = non_cash_tickers_from_csv(latest_run / "reports" / "concentrated_strategy_holdings.csv")
    target_book_tickers = sorted(main_tickers.union(concentrated_tickers))
    effective_required_tickers = required_tickers if required_tickers > 0 else len(target_book_tickers)

    tasks: list[dict[str, Any]] = []
    price_window_ready = years_ready(price_start, price_end, min_years)
    add_plan_task(
        tasks,
        task_id="price_cache_window",
        scope="prices",
        ready=price_window_ready,
        current={"start_date": iso_or_none(price_start), "end_date": iso_or_none(price_end)},
        required={"start_date_on_or_before": iso_or_none(target_start), "end_date_on_or_after": iso_or_none(target_end)},
        action="Run free_data_lake_bootstrap.yml with price_mode=target_books and max_price_tickers=0.",
    )
    files_ready = effective_required_tickers > 0 and effective_price_files >= effective_required_tickers
    add_plan_task(
        tasks,
        task_id="price_cache_ticker_count",
        scope="prices",
        ready=files_ready,
        current={"effective_price_files": effective_price_files, "requested_tickers": requested_tickers},
        required={"required_target_book_tickers": effective_required_tickers},
        action="Refresh replay price cache for every non-cash ticker selected by the operating target books.",
    )
    for portfolio, book in (("main", main_book), ("concentrated", concentrated_book)):
        book_start = parse_date(book.get("min_date"))
        book_end = parse_date(book.get("max_date"))
        add_plan_task(
            tasks,
            task_id=f"{portfolio}_target_book_window",
            scope="target_books",
            ready=years_ready(book_start, book_end, min_years),
            current={"start_date": book.get("min_date"), "end_date": book.get("max_date"), "rows": book.get("rows")},
            required={"start_date_on_or_before": iso_or_none(target_start), "end_date_on_or_after": iso_or_none(target_end)},
            action=f"Run full_rebuild_manual.yml with backtest_years={years_input(min_years)} after price readiness so {portfolio} target books extend across the full {label} window.",
        )
    for portfolio, broker in (("main", main_broker), ("concentrated", concentrated_broker)):
        broker_start = parse_date(broker.get("start_date"))
        broker_end = parse_date(broker.get("end_date"))
        add_plan_task(
            tasks,
            task_id=f"{portfolio}_broker_replay_window",
            scope="broker_replay",
            ready=years_ready(broker_start, broker_end, min_years),
            current={"start_date": broker.get("start_date"), "end_date": broker.get("end_date"), "years": broker.get("years")},
            required={"start_date_on_or_before": iso_or_none(target_start), "end_date_on_or_after": iso_or_none(target_end)},
            action=f"Rerun broker-ledger replay/account evaluation after target books cover the full {label} window.",
        )
    add_plan_task(
        tasks,
        task_id="sec_companyfacts_archive",
        scope="macro_sec_fundamentals",
        ready=sec_available,
        current={"available": sec_available},
        required={"available": True},
        action="Run or restore SEC companyfacts into data_raw/free/sec/companyfacts.zip before official evaluation.",
        hard_blocker=False,
    )
    add_plan_task(
        tasks,
        task_id="pit_universe_label",
        scope="universe",
        ready=pit_safe,
        current={"pit_safe": pit_safe},
        required={"pit_safe": True},
        action="Keep the run labeled proxy until historical membership, delistings, ADR eligibility, and ticker changes are PIT-safe.",
    )

    blockers = [row["task_id"] for row in tasks if row.get("hard_blocker")]
    return {
        "schema_version": "data-extension-plan-v1",
        "window_label": label,
        "target_start_date": iso_or_none(target_start),
        "target_end_date": iso_or_none(target_end),
        "selected_target_book_ticker_count": len(target_book_tickers),
        "effective_required_price_tickers": effective_required_tickers,
        "sample_target_book_tickers": target_book_tickers[:50],
        "main_target_book_ticker_count": len(main_tickers),
        "concentrated_target_book_ticker_count": len(concentrated_tickers),
        "tasks": tasks,
        "hard_blocker_count": len(blockers),
        "hard_blockers": blockers,
        "next_dispatch_hint": "bootstrap_price_cache_then_full_rebuild" if blockers else "none",
    }


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    coverage = read_json(repo_path(args.coverage), {}) or {}
    manifest = read_json(repo_path(args.manifest), {}) or {}
    price_manifest = read_json(repo_path(args.price_manifest), {}) or {}
    price_cache = repo_path(args.price_cache)

    main_book = csv_date_range(latest_run / "reports" / "main_monthly_weights.csv", ("rebalance_date", "date", "Date"))
    concentrated_book = csv_date_range(
        latest_run / "reports" / "concentrated_strategy_holdings.csv",
        ("rebalance_date", "date", "Date"),
    )
    main_broker = metric_summary(latest_run / "broker_replay" / "main" / "metrics.json")
    concentrated_broker = metric_summary(latest_run / "broker_replay" / "concentrated" / "metrics.json")

    local_price_files = count_price_files(price_cache)
    coverage_prices = (coverage.get("sources") or {}).get("prices") or {}
    coverage_sec = (coverage.get("sources") or {}).get("sec_companyfacts") or {}
    price_start = parse_date(price_manifest.get("start"))
    price_end = parse_date(price_manifest.get("end"))
    required_tickers = int(price_manifest.get("book_ticker_count") or coverage_prices.get("required_target_book_ticker_count") or 0)
    requested_tickers = int(price_manifest.get("ticker_count") or coverage_prices.get("requested_ticker_count") or 0)
    manifest_price_files = int(coverage_prices.get("cache_data_file_count") or 0)
    effective_price_files = max(local_price_files, manifest_price_files)

    min_years = float(args.min_years)
    slug = window_slug(min_years)
    label = window_label(min_years)
    price_window_ready = (
        coverage.get("readiness") == "ready_for_proxy_replay"
        and years_ready(price_start, price_end, min_years)
        and required_tickers > 0
        and effective_price_files >= required_tickers
    )
    main_book_ready = years_ready(parse_date(main_book["min_date"]), parse_date(main_book["max_date"]), min_years)
    concentrated_book_ready = years_ready(parse_date(concentrated_book["min_date"]), parse_date(concentrated_book["max_date"]), min_years)
    main_official_ready = years_ready(parse_date(main_broker["start_date"]), parse_date(main_broker["end_date"]), min_years)
    concentrated_official_ready = years_ready(
        parse_date(concentrated_broker["start_date"]),
        parse_date(concentrated_broker["end_date"]),
        min_years,
    )
    sec_available = (repo_path("data_raw/free/sec/companyfacts.zip").exists() or coverage_sec.get("status") == "available")
    pit_safe = coverage.get("pit_label") == "pit_safe"

    proxy_ready = price_window_ready
    official_ready = (
        price_window_ready
        and main_book_ready
        and concentrated_book_ready
        and main_official_ready
        and concentrated_official_ready
        and sec_available
        and pit_safe
    )

    blockers: list[str] = []
    warnings: list[str] = []
    if not price_window_ready:
        blockers.append(f"{label} price cache/manifest is not ready for proxy replay")
    if not main_book_ready or not concentrated_book_ready:
        blockers.append(f"monthly target books do not cover the requested {label} window")
    if not main_official_ready or not concentrated_official_ready:
        blockers.append(f"broker-ledger official replay does not yet cover the requested {label} window")
    if not sec_available:
        warnings.append("SEC companyfacts archive is not available under data_raw/free/sec")
    if not pit_safe:
        warnings.append("universe is labeled proxy, not PIT-safe official Russell 1000 history")
    for gap in coverage.get("known_gaps", []) or []:
        if gap not in warnings:
            warnings.append(str(gap))
    data_extension_plan = build_data_extension_plan(
        latest_run=latest_run,
        price_start=price_start,
        price_end=price_end,
        required_tickers=required_tickers,
        requested_tickers=requested_tickers,
        effective_price_files=effective_price_files,
        main_book=main_book,
        concentrated_book=concentrated_book,
        main_broker=main_broker,
        concentrated_broker=concentrated_broker,
        sec_available=sec_available,
        pit_safe=pit_safe,
        min_years=min_years,
        label=label,
    )

    if slug == "ten_year":
        status = "official_10y_ready" if official_ready else ("proxy_10y_price_ready" if proxy_ready else "not_ready")
    else:
        status = f"official_{slug}_ready" if official_ready else (f"proxy_{slug}_price_ready" if proxy_ready else "not_ready")
    return {
        "schema_version": "backtest-window-readiness-v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "min_years": min_years,
        "requested_years": min_years,
        "window_label": label,
        "window_slug": slug,
        "status": status,
        "proxy_price_ready": proxy_ready,
        "official_window_ready": official_ready,
        "proxy_10y_price_ready": proxy_ready if slug == "ten_year" else False,
        "official_10y_ready": official_ready if slug == "ten_year" else False,
        "pit_label": coverage.get("pit_label"),
        "coverage_readiness": coverage.get("readiness"),
        "price_cache": {
            "manifest_path": str(repo_path(args.price_manifest)),
            "cache_path": str(price_cache),
            "start_date": price_start.isoformat() if price_start else None,
            "end_date": price_end.isoformat() if price_end else None,
            "local_price_files": local_price_files,
            "manifest_price_files": manifest_price_files,
            "effective_price_files": effective_price_files,
            "required_target_book_tickers": required_tickers,
            "requested_tickers": requested_tickers,
            "window_ready": price_window_ready,
            "ten_year_ready": price_window_ready if slug == "ten_year" else False,
        },
        "target_books": {
            "main": main_book,
            "concentrated": concentrated_book,
            "window_ready": main_book_ready and concentrated_book_ready,
            "ten_year_ready": (main_book_ready and concentrated_book_ready) if slug == "ten_year" else False,
        },
        "broker_replay": {
            "main": main_broker,
            "concentrated": concentrated_broker,
            "window_ready": main_official_ready and concentrated_official_ready,
            "ten_year_ready": (main_official_ready and concentrated_official_ready) if slug == "ten_year" else False,
        },
        "free_data": {
            "manifest_exists": repo_path(args.manifest).exists(),
            "coverage_exists": repo_path(args.coverage).exists(),
            "sec_companyfacts_available": sec_available,
            "manifest_generated_at_utc": manifest.get("generated_at_utc"),
        },
        "blockers": blockers,
        "warnings": warnings,
        "data_extension_plan": data_extension_plan,
        "next_actions": next_actions(status, blockers, warnings, min_years=min_years, label=label),
    }


def write_tasks_csv(path: Path, tasks: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["task_id", "scope", "status", "hard_blocker", "current", "required", "action"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in tasks:
            out = dict(row)
            out["current"] = json.dumps(out.get("current"), sort_keys=True, default=str)
            out["required"] = json.dumps(out.get("required"), sort_keys=True, default=str)
            writer.writerow(out)


def render_data_extension_plan(plan: dict[str, Any]) -> str:
    lines = [
        "# Data Extension Plan",
        "",
        f"- window: `{plan.get('window_label')}`",
        f"- target start: `{plan.get('target_start_date')}`",
        f"- target end: `{plan.get('target_end_date')}`",
        f"- selected target-book tickers: `{plan.get('selected_target_book_ticker_count')}`",
        f"- hard blockers: `{plan.get('hard_blocker_count')}`",
        "",
        "| Task | Scope | Status | Hard Blocker | Action |",
        "| --- | --- | --- | :---: | --- |",
    ]
    for row in plan.get("tasks") or []:
        lines.append(
            f"| {row.get('task_id')} | {row.get('scope')} | {row.get('status')} | {str(row.get('hard_blocker')).lower()} | {row.get('action')} |"
        )
    lines.extend(["", "## Sample Target-Book Tickers", ""])
    tickers = plan.get("sample_target_book_tickers") or []
    lines.append(", ".join(str(item) for item in tickers) if tickers else "none")
    lines.append("")
    return "\n".join(lines)


def next_actions(status: str, blockers: list[str], warnings: list[str], *, min_years: float, label: str) -> list[str]:
    if status.startswith("official_") and status.endswith("_ready"):
        return [
            f"Run the full {label} broker-ledger backtest and compare main/concentrated production metrics.",
            "Promote only if broker-ledger metrics pass production gates without proxy-only labels.",
        ]
    actions: list[str] = []
    if status.startswith("proxy_") and status.endswith("_price_ready"):
        years_arg = "10" if min_years >= 9.5 else "8"
        actions.append(f"Run a {label} full rebuild with backtest_years={years_arg} so monthly target books extend to the full window.")
        actions.append("Keep results labeled pit_proxy_universe until historical membership and delisted coverage are solved.")
    else:
        actions.append("Run free_data_lake_bootstrap.yml with price_mode=target_books and max_price_tickers=0.")
    if any("SEC companyfacts" in item for item in warnings):
        actions.append("Restore or copy companyfacts.zip into data_raw/free/sec/companyfacts.zip, or run with sec_companyfacts=true.")
    if any("broker-ledger" in item for item in blockers):
        actions.append(f"After {label} target books exist, rerun broker-ledger replay and account evaluation.")
    return actions


def build_dispatch_payloads(payload: dict[str, Any], *, ref: str = "master") -> list[dict[str, Any]]:
    if payload.get("official_window_ready") is True:
        return []
    min_years = float(payload.get("min_years") or 8.0)
    slug = str(payload.get("window_slug") or window_slug(min_years))
    years_arg = years_input(min_years)
    source_latest_run = str(payload.get("latest_run") or DEFAULT_LATEST_RUN)
    latest_run = source_latest_run if source_latest_run.startswith("cloud_results/") else DEFAULT_LATEST_RUN
    dispatches: list[dict[str, Any]] = []
    dependency_ids: list[str] = []
    if payload.get("proxy_price_ready") is not True:
        plan_id = f"bootstrap_free_data_for_{slug}_window"
        dependency_ids.append(plan_id)
        dispatches.append(
            {
                "plan_id": plan_id,
                "workflow_id": "free_data_lake_bootstrap.yml",
                "ref": ref,
                "requires_user_approval": True,
                "production_mutation_allowed": False,
                "reason": f"{payload.get('window_label') or slug} price cache is not ready; restore/extend target-book price history first.",
                "source_status": payload.get("status"),
                "source_latest_run": source_latest_run,
                "source_blockers": payload.get("blockers") or [],
                "inputs": {
                    "latest_run": latest_run,
                    "sec_companyfacts": "true",
                    "price_mode": "target_books",
                    "max_price_tickers": "0",
                    "run_proxy_replay": "true",
                    "sync_to_gdrive": "true",
                },
            }
        )
    dispatches.append(
        {
            "plan_id": f"full_rebuild_{slug}_official_window",
            "workflow_id": "full_rebuild_manual.yml",
            "ref": ref,
            "requires_user_approval": True,
            "production_mutation_allowed": False,
            "depends_on_plan_ids": dependency_ids,
            "reason": f"Run the official {payload.get('window_label') or slug} broker-ledger rebuild after data readiness is available.",
            "source_status": payload.get("status"),
            "source_latest_run": source_latest_run,
            "source_blockers": payload.get("blockers") or [],
            "inputs": {
                "universe_mode": "global_alpha_universe",
                "backtest_years": years_arg,
                "skip_collector": "false",
                "fast_mode": "true",
                "sidecar_profile": "operating_minimal",
                "artifact_profile": "minimal",
                "gdrive_sync_mode": "minimal",
                "portfolio_policy": "alphaops_vnext_production",
                "cache_key_suffix": f"official-{slug}-window",
                "experiment_env_json": "",
            },
        }
    )
    return dispatches


def render_dispatch_script(payloads: list[dict[str, Any]], repo: str) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "# Review-only generated commands. Inspect before running.",
        "",
    ]
    for payload in payloads:
        workflow_id = shlex.quote(str(payload.get("workflow_id") or ""))
        ref = shlex.quote(str(payload.get("ref") or "master"))
        parts = ["gh", "workflow", "run", workflow_id, "--repo", shlex.quote(repo), "--ref", ref]
        for key, value in sorted((payload.get("inputs") or {}).items()):
            parts.extend(["-f", shlex.quote(f"{key}={value}")])
        lines.append("# " + str(payload.get("plan_id") or payload.get("workflow_id")))
        lines.append("# " + str(payload.get("reason") or ""))
        lines.append(" ".join(parts))
        lines.append("")
    return "\n".join(lines)


def render_report(payload: dict[str, Any]) -> str:
    pc = payload["price_cache"]
    tb = payload["target_books"]
    br = payload["broker_replay"]
    label = payload.get("window_label") or "10-year"
    title = label[:1].upper() + label[1:]
    lines = [
        f"# {title} Backtest Readiness",
        "",
        f"- Status: `{payload['status']}`",
        f"- Min years: `{payload['min_years']}`",
        f"- PIT label: `{payload.get('pit_label')}`",
        f"- Coverage readiness: `{payload.get('coverage_readiness')}`",
        "",
        "## Price Cache",
        "",
        f"- Range: `{pc.get('start_date')}` to `{pc.get('end_date')}`",
        f"- Effective files: `{pc.get('effective_price_files')}` / required `{pc.get('required_target_book_tickers')}`",
        f"- Window ready: `{pc.get('window_ready')}`",
        "",
        "## Target Books",
        "",
        f"- Main: `{tb['main'].get('min_date')}` to `{tb['main'].get('max_date')}`, rows `{tb['main'].get('rows')}`",
        f"- Concentrated: `{tb['concentrated'].get('min_date')}` to `{tb['concentrated'].get('max_date')}`, rows `{tb['concentrated'].get('rows')}`",
        f"- Window ready: `{tb.get('window_ready')}`",
        "",
        "## Broker Replay",
        "",
        f"- Main: `{br['main'].get('start_date')}` to `{br['main'].get('end_date')}`, CAGR `{br['main'].get('cagr')}`",
        f"- Concentrated: `{br['concentrated'].get('start_date')}` to `{br['concentrated'].get('end_date')}`, CAGR `{br['concentrated'].get('cagr')}`",
        f"- Window ready: `{br.get('window_ready')}`",
        "",
        "## Blockers",
        "",
    ]
    if payload["blockers"]:
        lines.extend(f"- {item}" for item in payload["blockers"])
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if payload["warnings"]:
        lines.extend(f"- {item}" for item in payload["warnings"])
    else:
        lines.append("- none")
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- {item}" for item in payload["next_actions"])
    plan = payload.get("data_extension_plan") or {}
    lines.extend(
        [
            "",
            "## Data Extension Plan",
            "",
            f"- Target window: `{plan.get('target_start_date')}` to `{plan.get('target_end_date')}`",
            f"- Target-book tickers: `{plan.get('selected_target_book_ticker_count')}`",
            f"- Hard blockers: `{plan.get('hard_blocker_count')}`",
            "",
            "| Task | Status | Action |",
            "| --- | --- | --- |",
        ]
    )
    for row in plan.get("tasks") or []:
        lines.append(f"| {row.get('task_id')} | {row.get('status')} | {row.get('action')} |")
    dispatches = payload.get("workflow_dispatch_payloads") or []
    lines.extend(["", "## Review Dispatch Plan", ""])
    if dispatches:
        lines.extend(
            [
                "- `workflow_dispatch_payloads.json` and `workflow_dispatch_commands.sh` are review-only.",
                "- They require explicit user approval before use.",
                "",
                "| Plan | Workflow | Dependencies | Reason |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in dispatches:
            deps = ",".join(item.get("depends_on_plan_ids") or [])
            lines.append(f"| {item.get('plan_id')} | {item.get('workflow_id')} | {deps} | {item.get('reason')} |")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_payload(args)
    ref = str(getattr(args, "ref", "master") or "master")
    repo = str(getattr(args, "repo", "wscha231/r1000-quant-engine") or "wscha231/r1000-quant-engine")
    dispatch_payloads = build_dispatch_payloads(payload, ref=ref)
    payload["workflow_dispatch_payloads"] = dispatch_payloads
    payload["workflow_dispatch_payload_count"] = len(dispatch_payloads)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    write_json(output_dir / "data_extension_plan.json", payload.get("data_extension_plan") or {})
    write_tasks_csv(output_dir / "data_extension_tasks.csv", (payload.get("data_extension_plan") or {}).get("tasks") or [])
    (output_dir / "data_extension_plan.md").write_text(
        render_data_extension_plan(payload.get("data_extension_plan") or {}),
        encoding="utf-8",
    )
    write_json(output_dir / "workflow_dispatch_payloads.json", dispatch_payloads)
    (output_dir / "workflow_dispatch_commands.sh").write_text(render_dispatch_script(dispatch_payloads, repo) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "summary": str(output_dir / "summary.json")}, indent=2))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--coverage", default=DEFAULT_COVERAGE)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--price-manifest", default=DEFAULT_PRICE_MANIFEST)
    parser.add_argument("--min-years", type=float, default=9.8)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--ref", default="master")
    parser.add_argument("--repo", default="wscha231/r1000-quant-engine")
    return parser.parse_args()


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
