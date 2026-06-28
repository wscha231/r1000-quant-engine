#!/usr/bin/env python3
"""Build PIT earnings-call keyword shock signals."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "earnings-call-keyword-signals-v1"
DEFAULT_INPUT = "data_raw/events/earnings_call_keywords.csv"
DEFAULT_OUTPUT = "data_pit/events/earnings_call_keyword_signals.parquet"

KEYWORD_FAMILIES: dict[str, tuple[str, ...]] = {
    "AI_CAPEX": ("ai capex", "datacenter capex", "accelerator", "cluster", "inference", "training"),
    "MEMORY": ("hbm", "dram", "nand", "memory", "storage constrained", "ssd"),
    "POWER": ("power", "grid", "electricity", "nuclear", "ppa", "baseload"),
    "NETWORKING": ("ethernet", "aec", "optical", "retimer", "serdes", "cpo"),
    "COST_PRESSURE": ("oil", "fuel", "freight", "resin", "metals", "tungsten"),
    "PRICING_POWER": ("price increase", "asp", "tight supply", "sold out", "shortage", "backlog"),
    "CUSTOMER_PUSHBACK": ("inventory digestion", "design change", "substitution", "delay", "pushback"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if pd.notna(out) else default
    except (TypeError, ValueError):
        return default


def text_count(text: str, phrase: str) -> int:
    if not text or not phrase:
        return 0
    return len(re.findall(re.escape(phrase.lower()), text.lower()))


def family_count(row: pd.Series, family: str, keywords: tuple[str, ...]) -> float:
    text = " ".join(str(row.get(col, "") or "") for col in ["text", "snippet", "transcript", "context"]).lower()
    count = sum(text_count(text, keyword) for keyword in keywords)
    for keyword in keywords:
        normalized = re.sub(r"[^a-z0-9]+", "_", keyword.lower()).strip("_")
        for col in [normalized, f"keyword_{normalized}", f"{family.lower()}_{normalized}"]:
            if col in row.index:
                count += safe_float(row.get(col), 0.0)
    if family.lower() in row.index:
        count += safe_float(row.get(family.lower()), 0.0)
    return float(count)


def build_signals(raw: pd.DataFrame, *, as_of: pd.Timestamp | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = {"ticker", "available_from"}
    missing = sorted(required - set(raw.columns))
    if missing:
        return pd.DataFrame(), {"status": "blocked", "reason": f"missing_required_columns:{','.join(missing)}"}
    d = raw.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["available_from"] = pd.to_datetime(d["available_from"], errors="coerce").dt.normalize()
    invalid_available_from = int(d["available_from"].isna().sum())
    future_available_from = int((d["available_from"] > as_of).sum()) if as_of is not None else 0
    d = d[d["available_from"].notna() & d["ticker"].ne("")]
    if as_of is not None:
        d = d[d["available_from"] <= as_of]
    for family, keywords in KEYWORD_FAMILIES.items():
        d[f"keyword_family_{family.lower()}_count"] = d.apply(lambda row: family_count(row, family, keywords), axis=1)
    d["ai_capex_demand_keyword_score"] = (
        d["keyword_family_ai_capex_count"] + d["keyword_family_memory_count"] + d["keyword_family_networking_count"]
    )
    d["bottleneck_pricing_power_keyword_score"] = d["keyword_family_pricing_power_count"]
    d["downstream_cost_pressure_keyword_score"] = d["keyword_family_cost_pressure_count"]
    d["customer_pushback_keyword_score"] = d["keyword_family_customer_pushback_count"]
    d["guidance_risk_keyword_score"] = d["customer_pushback_keyword_score"] + d["downstream_cost_pressure_keyword_score"]
    max_cols = [
        "ai_capex_demand_keyword_score",
        "bottleneck_pricing_power_keyword_score",
        "downstream_cost_pressure_keyword_score",
        "customer_pushback_keyword_score",
        "guidance_risk_keyword_score",
    ]
    for col in max_cols:
        d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0).clip(lower=0.0)
    summary = {
        "status": "completed",
        "input_rows": int(len(raw)),
        "output_rows": int(len(d)),
        "invalid_available_from_rows": invalid_available_from,
        "future_available_from_rows_filtered": future_available_from,
        "available_from_required": True,
        "keyword_families": sorted(KEYWORD_FAMILIES),
    }
    return d, summary


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", default="outputs/earnings_call_keyword_signals/summary.json")
    parser.add_argument("--as-of", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = repo_path(args.input)
    output_path = repo_path(args.output)
    summary_path = repo_path(args.summary)
    if not input_path.exists():
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "missing_input",
            "input": str(input_path),
            "research_only": True,
        }
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    raw = pd.read_csv(input_path, low_memory=False)
    as_of = pd.Timestamp(args.as_of).normalize() if args.as_of else None
    out, summary = build_signals(raw, as_of=as_of)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "input": str(input_path),
        "output": str(output_path),
        "research_only": True,
        "production_activation_allowed": False,
        **summary,
    }
    if out.empty:
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(output_path, index=False)
    write_json(summary_path, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
