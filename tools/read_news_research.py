#!/usr/bin/env python3
"""Read a hash-pinned source capture restored from Drive, without execution authority."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.news_event_alpha_v1.shared_reader import read_capture_attempt

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--attempt-dir", type=Path, required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--allow-synthetic", action="store_true")
    args = p.parse_args()
    result = read_capture_attempt(args.attempt_dir,
                                 as_of=args.as_of, top_n=args.top_n, allow_synthetic=args.allow_synthetic)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))

if __name__ == "__main__":
    main()
