#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.telegram_event_v1.ingest import build_outputs


def main() -> int:
    ap = argparse.ArgumentParser(description="Research-only Telegram -> A2 discovery input")
    ap.add_argument("--channel", default="insidertracking")
    ap.add_argument("--source-url", default="https://t.me/s/insidertracking")
    ap.add_argument("--checkpoint", type=Path)
    ap.add_argument("--events", type=Path)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--initial-last-post-id", type=int, default=64207)
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args()

    checkpoint_raw = args.checkpoint.read_bytes() if args.checkpoint and args.checkpoint.exists() else None
    event_log_raw = args.events.read_bytes() if args.events and args.events.exists() else None
    outputs = build_outputs(
        channel=args.channel,
        source_url=args.source_url,
        checkpoint_raw=checkpoint_raw,
        event_log_raw=event_log_raw,
        initial_last_post_id=args.initial_last_post_id,
        max_pages=args.max_pages,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in outputs.items():
        (args.output_dir / name).write_bytes(data)
    # Concise stdout, no source text.
    import json
    receipt = json.loads(outputs["receipt.json"])
    print(json.dumps({k: receipt[k] for k in ("status", "new_post_count", "a2_event_count", "gap_unresolved")}, sort_keys=True))
    return 2 if receipt["gap_unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
