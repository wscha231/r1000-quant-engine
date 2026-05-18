#!/usr/bin/env python3
"""Package research data artifacts for cross-machine/agent handoff.

This tool creates a zip bundle plus a machine-readable manifest. It is designed
for large local artifacts that should be shared through GitHub release assets,
GitHub Actions artifacts, or Google Drive rather than committed to the repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OUTPUT_DIR = "outputs/research_handoff"

DEFAULT_INCLUDE_PATHS = [
    "data_pit/sec/sec_filings_index.parquet",
    "data_pit/sec/sec_filings_index_summary.json",
    "data_pit/sec/sec_filings_index_recent_1200.parquet",
    "data_pit/sec/sec_filings_index_recent_300.parquet",
    "data_pit/sec/form4_transactions.parquet",
    "data_pit/sec/form4_transactions_summary.json",
    "outputs/sec_ownership_signals",
    "outputs/sec_enriched_candidate_replay",
    "outputs/cagr_mdd_recovery_20260518/alpha_selector_broker_grid/main_highconviction/best_metrics.json",
    "outputs/cagr_mdd_recovery_20260518/alpha_selector_broker_grid/main_highconviction/best_target_distance_metrics.json",
    "outputs/cagr_mdd_recovery_20260518/alpha_selector_broker_grid/main_highconviction/summary.csv",
    "outputs/cagr_mdd_recovery_20260518/alpha_selector_broker_grid/main_highconviction/report.md",
    "outputs/cagr_mdd_recovery_20260518/alpha_selector_broker_grid/main_highconviction/monster_heavy_N3_cap0.5",
    "outputs/cagr_mdd_recovery_20260518/alpha_selector_market_circuit_grid/main_highconviction/best_metrics.json",
    "outputs/cagr_mdd_recovery_20260518/alpha_selector_market_circuit_grid/main_highconviction/summary.csv",
    "outputs/cagr_mdd_recovery_20260518/alpha_selector_market_circuit_grid/main_highconviction/report.md",
    "outputs/cagr_mdd_recovery_20260518/alpha_selector_market_circuit_grid/main_highconviction/monster_heavy_N3_cap0.5/ma50_caution_0p60_crisis_0p25",
    "outputs/cagr_mdd_recovery_20260518/concentrated_broker_grid/best_metrics.json",
    "outputs/cagr_mdd_recovery_20260518/concentrated_broker_grid/summary.csv",
    "outputs/cagr_mdd_recovery_20260518/concentrated_broker_grid/report.md",
    "outputs/cagr_mdd_recovery_20260518/concentrated_broker_grid/N5_winner_take_all_I1",
    "outputs/cagr_mdd_recovery_20260518/concentrated_market_circuit_grid/best_metrics.json",
    "outputs/cagr_mdd_recovery_20260518/concentrated_market_circuit_grid/summary.csv",
    "outputs/cagr_mdd_recovery_20260518/concentrated_market_circuit_grid/report.md",
    "outputs/cagr_mdd_recovery_20260518/concentrated_market_circuit_grid/ma50_caution_0p90_crisis_0p70",
    "cache_prices/replay_price_cache_manifest.json",
]

HEAVY_PATHS = {
    "outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv",
}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_value(args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.stdout.strip()
    except Exception:
        return ""


def collect_files(paths: list[str], *, include_heavy: bool) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    missing: list[str] = []
    seen: set[Path] = set()
    for item in paths:
        path = repo_path(item)
        if not path.exists():
            missing.append(str(item))
            continue
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = rel(candidate)
            if not include_heavy and relative in HEAVY_PATHS:
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            files.append(candidate)
            seen.add(resolved)
    return sorted(files, key=lambda p: rel(p)), missing


def default_bundle_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"r1000_research_handoff_{stamp}.zip"


def restore_readme(manifest_name: str) -> str:
    return "\n".join(
        [
            "# R1000 Research Handoff Bundle",
            "",
            "Unzip this archive at the repository root on another computer or runner.",
            "",
            "```powershell",
            "Expand-Archive .\\r1000_research_handoff_*.zip -DestinationPath . -Force",
            "python tools\\run_agent_board.py --latest-run outputs --output-dir outputs\\agent_board",
            "python tools\\run_pr_validation.py --only sec_form4_parser_smoke --only agent_board_smoke",
            "```",
            "",
            f"Read `{manifest_name}` for exact file checksums, source commit, and included artifact paths.",
            "",
            "The bundle is research-only. It does not activate production defaults.",
            "",
        ]
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def build_manifest(
    *,
    files: list[Path],
    missing: list[str],
    bundle_path: Path,
    include_heavy: bool,
    label: str,
) -> dict[str, Any]:
    file_rows = []
    total_bytes = 0
    for path in files:
        size = int(path.stat().st_size)
        total_bytes += size
        file_rows.append({"path": rel(path), "bytes": size, "sha256": sha256_file(path)})
    return {
        "schema_version": "research-handoff-bundle-v1",
        "label": label,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "repo": git_value(["remote", "get-url", "origin"]),
        "branch": git_value(["branch", "--show-current"]),
        "commit": git_value(["rev-parse", "HEAD"]),
        "research_only": True,
        "production_activation_allowed": False,
        "include_heavy": include_heavy,
        "bundle": str(bundle_path),
        "file_count": len(file_rows),
        "total_bytes": total_bytes,
        "missing_inputs": missing,
        "files": file_rows,
        "restore": {
            "destination": "repository root",
            "commands": [
                "Expand-Archive .\\r1000_research_handoff_*.zip -DestinationPath . -Force",
                "python tools\\run_agent_board.py --latest-run outputs --output-dir outputs\\agent_board",
            ],
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    include_paths = list(DEFAULT_INCLUDE_PATHS)
    include_paths.extend(args.include or [])
    files, missing = collect_files(include_paths, include_heavy=bool(args.include_heavy))
    bundle_path = output_dir / (args.bundle_name or default_bundle_name())
    manifest_name = bundle_path.with_suffix(".manifest.json").name
    readme_name = bundle_path.with_suffix(".README.md").name
    manifest = build_manifest(
        files=files,
        missing=missing,
        bundle_path=bundle_path,
        include_heavy=bool(args.include_heavy),
        label=args.label,
    )
    manifest_in_zip = json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n"
    readme = restore_readme(manifest_name)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(manifest_name, manifest_in_zip)
        zf.writestr(readme_name, readme)
        for path in files:
            zf.write(path, arcname=rel(path))
    bundle_sha = sha256_file(bundle_path)
    manifest.update(
        {
            "bundle_bytes": int(bundle_path.stat().st_size),
            "bundle_sha256": bundle_sha,
            "manifest": str(bundle_path.with_suffix(".manifest.json")),
            "readme": str(bundle_path.with_suffix(".README.md")),
        }
    )
    write_json(bundle_path.with_suffix(".manifest.json"), manifest)
    bundle_path.with_suffix(".README.md").write_text(readme, encoding="utf-8")
    latest = output_dir / "latest_manifest.json"
    write_json(latest, manifest)
    return {
        "status": "ok",
        "bundle": str(bundle_path),
        "bundle_bytes": manifest["bundle_bytes"],
        "bundle_sha256": bundle_sha,
        "manifest": str(bundle_path.with_suffix(".manifest.json")),
        "file_count": len(files),
        "missing_count": len(missing),
        "missing_inputs": missing,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bundle-name", default="")
    parser.add_argument("--label", default="r1000 research handoff")
    parser.add_argument("--include", action="append", default=[], help="Additional file or directory path to include.")
    parser.add_argument("--include-heavy", action="store_true", help="Include heavy files such as enriched candidate CSVs.")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
