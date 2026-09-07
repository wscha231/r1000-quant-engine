#!/usr/bin/env python3
"""US-owned export only. KR uses its own repository's export entrypoint."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.research_decision_v1.data import export_market
from tools.research_decision_v1.io import immutable_json, read_json, research_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    result = export_market(read_json(args.input), "US")
    path = immutable_json(research_root(ROOT) / "exports" / (result["export_hash"] + ".json"), result)
    admitted = sum(s["data_quality_pass"] for s in result["securities"])
    print(json.dumps({"path": str(path), "admitted": admitted, "total": len(result["securities"]), "orders_allowed": False}))
    return 0 if admitted == len(result["securities"]) and admitted else 2


if __name__ == "__main__": raise SystemExit(main())
