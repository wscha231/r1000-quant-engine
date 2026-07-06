#!/usr/bin/env python3
"""Archive target-generation inputs needed for runner-fidelity reproduction.

This copies only already-materialized local files. It does not download market
data, regenerate target books, tune thresholds, dispatch workflows, or promote
production. The bundle is intended for GitHub Actions artifacts, not for
committed cloud_results history.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def path_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def nested(payload: dict[str, Any], *keys: str) -> Any:
    cur: Any = payload
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def copy_file(src: Path, dst: Path) -> dict[str, Any]:
    row = {
        "source": path_ref(src),
        "destination": path_ref(dst),
        "exists": bool(src.exists() and src.is_file()),
        "bytes": 0,
        "sha256": "",
        "copied": False,
    }
    if not row["exists"]:
        return row
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    row["bytes"] = int(dst.stat().st_size)
    row["sha256"] = sha256_file(dst)
    row["copied"] = True
    return row


def copy_price_files(price_cache: Path, dst_cache: Path) -> dict[str, Any]:
    dst_cache.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if price_cache.exists() and price_cache.is_dir():
        for src in sorted(price_cache.iterdir()):
            if not src.is_file() or src.suffix.lower() not in {".parquet", ".csv"}:
                continue
            rows.append(copy_file(src, dst_cache / src.name))
    return {
        "source": path_ref(price_cache),
        "destination": path_ref(dst_cache),
        "price_file_count": int(len(rows)),
        "price_file_bytes": int(sum(int(row.get("bytes") or 0) for row in rows)),
    }


def candidate_book_path(latest_run: Path) -> Path:
    candidates = [
        latest_run / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
        latest_run / "reports" / "candidate_replay_book.csv",
    ]
    return next((path for path in candidates if path.exists()), candidates[0])


def render_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Target Generation Substrate Archive",
        "",
        f"Status: `{payload['status']}`",
        "",
        "This bundle is research-only reproduction substrate. It was copied from already-materialized files and does not create strategy output.",
        "",
        "## Summary",
        "",
        f"- archived_price_file_count: `{payload['price_cache']['price_file_count']}`",
        f"- expected_price_file_count: `{payload['expected_price_file_count']}`",
        f"- manifest_available: `{str(payload['manifest_available']).lower()}`",
        f"- candidate_book_sha_matches_manifest: `{str(payload['candidate_book_sha_matches_manifest']).lower()}`",
        f"- long_crisis_features_sha_matches_manifest: `{str(payload['long_crisis_features_sha_matches_manifest']).lower()}`",
        f"- long_crisis_thresholds_sha_matches_manifest: `{str(payload['long_crisis_thresholds_sha_matches_manifest']).lower()}`",
        "",
        "## Governance",
        "",
        "- fullrun_dispatched=false",
        "- market_data_downloaded=false",
        "- target_book_regenerated=false",
        "- threshold_tuning_performed=false",
        "- production_promotion_allowed=false",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)

    manifest_src = latest_run / "alphaops_vnext" / "target_generation_input_manifest.json"
    candidate_src = candidate_book_path(latest_run)
    price_manifest_src = price_cache / "replay_price_cache_manifest.json"
    long_features_src = repo_path(args.long_crisis_features)
    long_thresholds_src = repo_path(args.long_crisis_thresholds)

    manifest = read_json(manifest_src)
    expected_candidate_sha = str(nested(manifest, "candidate_book", "sha256") or "")
    expected_price_file_count = int(nested(manifest, "price_cache", "required_price_file_count") or 0)
    expected_features_sha = str(nested(manifest, "macro_crisis_inputs", "long_crisis_features", "sha256") or "")
    expected_thresholds_sha = str(nested(manifest, "macro_crisis_inputs", "long_crisis_thresholds", "sha256") or "")

    files = {
        "target_generation_input_manifest": copy_file(
            manifest_src, output_dir / "alphaops_vnext" / "target_generation_input_manifest.json"
        ),
        "candidate_book": copy_file(
            candidate_src,
            output_dir / "sec_enriched_candidate_replay" / candidate_src.name,
        ),
        "price_cache_manifest": copy_file(
            price_manifest_src,
            output_dir / "cache_prices" / "replay_price_cache_manifest.json",
        ),
        "long_crisis_features": copy_file(
            long_features_src,
            output_dir / "data_pit" / "macro" / "long_crisis_daily_features.parquet",
        ),
        "long_crisis_thresholds": copy_file(
            long_thresholds_src,
            output_dir / "outputs" / "long_crisis_learning" / "best_thresholds.json",
        ),
    }
    price_summary = copy_price_files(price_cache, output_dir / "cache_prices")

    candidate_sha = str(files["candidate_book"].get("sha256") or "")
    features_sha = str(files["long_crisis_features"].get("sha256") or "")
    thresholds_sha = str(files["long_crisis_thresholds"].get("sha256") or "")
    required_ready = all(
        [
            files["target_generation_input_manifest"]["copied"],
            files["candidate_book"]["copied"],
            files["price_cache_manifest"]["copied"],
            files["long_crisis_features"]["copied"],
            files["long_crisis_thresholds"]["copied"],
            price_summary["price_file_count"] >= expected_price_file_count if expected_price_file_count else True,
        ]
    )
    payload = {
        "schema_version": "target-generation-substrate-archive-v1",
        "status": "completed" if required_ready else "completed_with_missing_inputs",
        "research_only": True,
        "fullrun_dispatched": False,
        "market_data_downloaded": False,
        "target_book_regenerated": False,
        "threshold_tuning_performed": False,
        "new_alpha_hook_added": False,
        "production_promotion_allowed": False,
        "latest_run": path_ref(latest_run),
        "output_dir": path_ref(output_dir),
        "manifest_available": bool(files["target_generation_input_manifest"]["copied"]),
        "expected_price_file_count": expected_price_file_count,
        "candidate_book_sha_matches_manifest": bool(expected_candidate_sha and candidate_sha == expected_candidate_sha),
        "long_crisis_features_sha_matches_manifest": bool(expected_features_sha and features_sha == expected_features_sha),
        "long_crisis_thresholds_sha_matches_manifest": bool(
            expected_thresholds_sha and thresholds_sha == expected_thresholds_sha
        ),
        "files": files,
        "price_cache": price_summary,
        "artifacts": {
            "summary": path_ref(output_dir / "summary.json"),
            "report": path_ref(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    render_report(output_dir / "report.md", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/target_generation_substrate")
    parser.add_argument("--long-crisis-features", default="data_pit/macro/long_crisis_daily_features.parquet")
    parser.add_argument("--long-crisis-thresholds", default="outputs/long_crisis_learning/best_thresholds.json")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
