#!/usr/bin/env python3
"""Print AlphaOps required price tickers for workflow shell glue."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.alphaops_required_price_tickers import (  # noqa: E402
    format_tickers_csv,
    parse_env_payload,
    required_price_tickers_for_env,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-env-json", default="")
    parser.add_argument("--output-format", choices=["csv", "json"], default="csv")
    args = parser.parse_args()

    tickers = required_price_tickers_for_env(parse_env_payload(args.experiment_env_json))
    if args.output_format == "json":
        print(json.dumps(tickers, sort_keys=True))
    else:
        print(format_tickers_csv(tickers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
