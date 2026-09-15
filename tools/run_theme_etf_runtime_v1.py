#!/usr/bin/env python3
"""Run the research-only theme/ETF runtime against a JSON input."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = REPO_ROOT / "research" / "theme_etf_runtime_v1"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from runtime import ContractError, digest, run_payload  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--expected-input-sha256", default="")
    p.add_argument("--output-dir", required=True)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    raw = input_path.read_bytes()
    actual = __import__("hashlib").sha256(raw).hexdigest()
    if args.expected_input_sha256 and actual != args.expected_input_sha256.lower():
        print(json.dumps({"status": "BLOCKED", "reason": "INPUT_HASH_MISMATCH", "actual_sha256": actual}))
        return 2
    try:
        payload = json.loads(raw.decode("utf-8"))
        result = run_payload(payload)
    except (ContractError, KeyError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPLETED_RESEARCH_ONLY", "result_sha256": result["result_sha256"], "input_sha256": actual, "summary_sha256": digest(result["summary"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
