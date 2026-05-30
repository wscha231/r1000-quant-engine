#!/usr/bin/env python3
"""Run the AlphaOps sidecar promotion bridge."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_sidecar_promotion import (  # noqa: E402
    repo_path,
    rollback_targets,
    run_approved_integrated,
    run_check_promotion,
    run_production_baseline,
    run_shadow,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=[
            "production_baseline",
            "integrated_shadow",
            "check_promotion",
            "approved_integrated",
            "rollback_targets_only",
            "rollback_and_rerun_broker_replay",
        ],
        default="production_baseline",
    )
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--approved-policy", default="outputs/promotion_review/approved_target_policy.json")
    parser.add_argument("--source-integrated-dir", default="outputs/integrated_theme_leader_crisis_replay")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_root = repo_path(args.output_root)
    integrated_dir = repo_path(args.source_integrated_dir)
    policy_path = repo_path(args.approved_policy)
    if args.mode == "production_baseline":
        payload = run_production_baseline(latest_run=latest_run, integrated_dir=integrated_dir, output_root=output_root)
    elif args.mode == "integrated_shadow":
        payload = run_shadow(
            latest_run=latest_run,
            integrated_dir=integrated_dir,
            price_cache=price_cache,
            output_root=output_root,
            cost_bps=float(args.cost_bps),
            max_fill_lag_days=int(args.max_fill_lag_days),
        )
    elif args.mode == "check_promotion":
        payload = run_check_promotion(latest_run=latest_run, integrated_dir=integrated_dir, output_root=output_root)
    elif args.mode == "approved_integrated":
        payload = run_approved_integrated(
            latest_run=latest_run,
            output_root=output_root,
            policy_path=policy_path,
            integrated_dir=integrated_dir,
        )
    elif args.mode == "rollback_targets_only":
        payload = rollback_targets(latest_run=latest_run, output_root=output_root, rerun=False, price_cache=price_cache)
    else:
        payload = rollback_targets(latest_run=latest_run, output_root=output_root, rerun=True, price_cache=price_cache)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    status = str(payload.get("status") or "").lower()
    if args.mode == "approved_integrated" and status != "applied":
        return 2
    if args.mode.startswith("rollback") and status != "completed":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
