#!/usr/bin/env python3
"""AI capex value-chain taxonomy helpers.

This module is research-only. Known tickers are seed examples for taxonomy
coverage and diagnostics; they are not buy lists and should not be used as a
selection rule without PIT earnings/revision/RS confirmation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

BUCKETS = [
    "AI_COMPUTE",
    "AI_MEMORY",
    "AI_STORAGE",
    "AI_CONNECT",
    "AI_POWER",
    "AI_GRID",
    "AI_COOLING",
    "AI_EQUIPMENT",
    "AI_FOUNDRY",
    "AI_OTHER",
]


@dataclass(frozen=True)
class BucketSpec:
    bucket: str
    keywords: tuple[str, ...]
    industries: tuple[str, ...]
    seed_tickers: tuple[str, ...]
    risk_types: tuple[str, ...]
    primary_metrics: tuple[str, ...]


SPECS: tuple[BucketSpec, ...] = (
    BucketSpec(
        "AI_COMPUTE",
        ("gpu", "accelerator", "asic", "ai chip", "compute", "dpu", "xpu", "server cpu"),
        ("semiconductor", "processors", "accelerators"),
        ("NVDA", "AMD", "AVGO", "MRVL"),
        ("cuda_lock_in", "node_supply", "customer_concentration", "valuation_heat"),
        ("datacenter_revenue_growth", "accelerator_backlog", "gross_margin", "eps_revision"),
    ),
    BucketSpec(
        "AI_MEMORY",
        ("hbm", "dram", "memory", "ddr5", "high bandwidth memory"),
        ("memory", "semiconductor memory"),
        ("MU", "SKHYNIX", "005930", "WDC"),
        ("memory_cycle", "capacity_addition", "china_supply", "asp_rollover"),
        ("hbm_mix", "dram_asp", "gross_margin", "eps_revision"),
    ),
    BucketSpec(
        "AI_STORAGE",
        ("nand", "ssd", "enterprise ssd", "storage", "data lake", "nearline", "hard disk"),
        ("storage", "disk drives", "computer storage"),
        ("SNDK", "WDC", "STX"),
        ("nand_cycle", "customer_pushback", "capacity_addition", "substitution"),
        ("enterprise_ssd_growth", "nand_asp", "backlog", "gross_margin"),
    ),
    BucketSpec(
        "AI_CONNECT",
        ("ethernet", "optical", "aec", "retimer", "serdes", "cpo", "switch", "networking"),
        ("communications equipment", "networking", "semiconductor connectivity"),
        ("CRDO", "CIEN", "LITE", "COHR", "ANET", "MRVL", "AVGO"),
        ("customer_concentration", "cpo_substitution", "pricing_pressure", "valuation_heat"),
        ("800g_1_6t_exposure", "design_wins", "gross_margin", "eps_revision"),
    ),
    BucketSpec(
        "AI_POWER",
        ("power", "electricity", "nuclear", "ppa", "baseload", "gas turbine", "generation"),
        ("utilities", "independent power", "electric power"),
        ("TLN", "CEG", "VST", "GEV", "BE"),
        ("regulatory", "fuel_price", "single_asset", "tail_risk"),
        ("contracted_power", "ppa_duration", "capacity_price", "free_cash_flow"),
    ),
    BucketSpec(
        "AI_GRID",
        ("grid", "transformer", "switchgear", "substation", "transmission", "electrification"),
        ("electrical equipment", "industrial machinery", "grid equipment"),
        ("PWR", "ETN", "HUBB", "VRT"),
        ("project_delay", "commodity_cost", "policy", "valuation_heat"),
        ("backlog", "book_to_bill", "margin_revision", "revenue_revision"),
    ),
    BucketSpec(
        "AI_COOLING",
        ("cooling", "liquid cooling", "thermal", "heat exchanger", "hvac"),
        ("thermal management", "hvac", "electrical equipment"),
        ("VRT", "TT", "MOD"),
        ("component_shortage", "margin_pressure", "customer_concentration"),
        ("thermal_backlog", "datacenter_revenue", "margin_revision"),
    ),
    BucketSpec(
        "AI_EQUIPMENT",
        ("semicap", "wafer", "lithography", "etch", "deposition", "test", "packaging", "cowos"),
        ("semiconductor equipment", "semiconductor materials", "test equipment"),
        ("AMAT", "LRCX", "KLAC", "ASML", "TER", "COHU"),
        ("cycle_peak", "export_control", "capex_delay", "china_restriction"),
        ("orders", "book_to_bill", "backlog", "eps_revision"),
    ),
    BucketSpec(
        "AI_FOUNDRY",
        ("foundry", "advanced node", "2nm", "3nm", "tsmc", "cowos", "advanced packaging"),
        ("foundry", "semiconductor manufacturing"),
        ("TSM", "UMC", "005930"),
        ("node_yield", "geopolitical", "customer_concentration", "capex_intensity"),
        ("advanced_node_mix", "packaging_capacity", "gross_margin", "eps_revision"),
    ),
)

SPEC_BY_BUCKET = {spec.bucket: spec for spec in SPECS}
TICKER_TO_BUCKET: dict[str, str] = {}
for spec in SPECS:
    for ticker in spec.seed_tickers:
        TICKER_TO_BUCKET.setdefault(ticker.upper(), spec.bucket)

SUBSTITUTION_KEYWORDS = (
    "substitution",
    "alternative",
    "cpo",
    "cuda",
    "hdd replacement",
    "cxmt",
    "open networking",
)
CUSTOMER_CONCENTRATION_KEYWORDS = (
    "hyperscaler",
    "single customer",
    "customer concentration",
    "microsoft",
    "amazon",
    "google",
    "meta",
    "openai",
)
PEAKOUT_KEYWORDS = (
    "capacity expansion",
    "inventory digestion",
    "asp down",
    "pricing pressure",
    "order delay",
    "cycle peak",
)
PRICING_POWER_KEYWORDS = (
    "tight supply",
    "sold out",
    "price increase",
    "asp up",
    "backlog",
    "shortage",
    "capacity constrained",
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).lower().strip()


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def row_text(row: pd.Series | dict[str, Any]) -> str:
    fields = [
        "ticker",
        "Name",
        "name",
        "sector",
        "industry_group",
        "industry",
        "subindustry",
        "theme",
        "theme_primary",
        "leadership_theme",
        "business_description",
        "description",
        "rationale",
    ]
    parts = [clean_text(row.get(field, "")) for field in fields if hasattr(row, "get")]
    return " ".join(part for part in parts if part)


def count_matches(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword.lower() in text)


def classify_row(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    text = row_text(row)
    ticker = clean_ticker(row.get("ticker", "") if hasattr(row, "get") else "")
    scores: dict[str, int] = {}
    details: dict[str, dict[str, int]] = {}
    for spec in SPECS:
        keyword_hits = count_matches(text, spec.keywords)
        industry_hits = count_matches(text, spec.industries)
        seed_hit = 1 if ticker in {item.upper() for item in spec.seed_tickers} else 0
        scores[spec.bucket] = keyword_hits * 2 + industry_hits * 2 + seed_hit
        details[spec.bucket] = {"keyword_hits": keyword_hits, "industry_hits": industry_hits, "seed_hit": seed_hit}
    bucket = max(scores, key=scores.get) if scores else "AI_OTHER"
    if scores.get(bucket, 0) <= 0:
        bucket = "AI_OTHER"
    spec = SPEC_BY_BUCKET.get(bucket)
    detail = details.get(bucket, {"keyword_hits": 0, "industry_hits": 0, "seed_hit": 0})
    keyword_score = min(1.0, (scores.get(bucket, 0) or 0) / 6.0)
    pricing_power = min(1.0, count_matches(text, PRICING_POWER_KEYWORDS) / 3.0)
    substitution_risk = min(1.0, count_matches(text, SUBSTITUTION_KEYWORDS) / 2.0)
    customer_concentration_risk = min(1.0, count_matches(text, CUSTOMER_CONCENTRATION_KEYWORDS) / 3.0)
    peakout_risk = min(1.0, count_matches(text, PEAKOUT_KEYWORDS) / 3.0)
    if bucket == "AI_OTHER":
        source_confidence = "unclassified"
    elif ticker in TICKER_TO_BUCKET and scores.get(bucket, 0) == 1:
        source_confidence = "seed_example_only"
    else:
        source_confidence = "text_or_industry_match"
    structural_bucket_bonus = 0.10 if bucket in {"AI_MEMORY", "AI_STORAGE", "AI_CONNECT", "AI_POWER", "AI_GRID"} else 0.0
    evidence_floor = 0.0
    if bucket != "AI_OTHER":
        if detail.get("keyword_hits", 0) > 0:
            evidence_floor = max(evidence_floor, 0.55)
        if detail.get("industry_hits", 0) > 0:
            evidence_floor = max(evidence_floor, 0.50 + structural_bucket_bonus)
        if detail.get("seed_hit", 0) > 0:
            # Seed examples are still idea-only, but they should be testable in
            # cheap screens when paired with PIT earnings/RS confirmation.
            evidence_floor = max(evidence_floor, 0.50 + structural_bucket_bonus)
    raw_score = (
        0.55 * keyword_score
        + 0.35 * pricing_power
        + structural_bucket_bonus
        - 0.15 * substitution_risk
        - 0.10 * peakout_risk
    )
    bottleneck_score = max(0.0, min(1.0, max(raw_score, evidence_floor)))
    return {
        "ai_capex_value_chain_bucket": bucket,
        "ai_capex_supplier_type": "none" if bucket == "AI_OTHER" else "capex_supplier",
        "ai_capex_bottleneck_score": float(bottleneck_score),
        "ai_capex_pricing_power_score": float(pricing_power),
        "ai_capex_substitution_risk": float(substitution_risk),
        "ai_capex_customer_concentration_risk": float(customer_concentration_risk),
        "ai_capex_peakout_risk": float(peakout_risk),
        "ai_capex_source_confidence": source_confidence,
        "ai_capex_primary_metrics": ";".join(spec.primary_metrics if spec else ()),
        "ai_capex_risk_types": ";".join(spec.risk_types if spec else ()),
    }


def enrich_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    additions = [classify_row(row) for _, row in frame.iterrows()]
    return pd.concat([frame.reset_index(drop=True), pd.DataFrame(additions)], axis=1)


def taxonomy_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "bucket": spec.bucket,
                "keywords": ";".join(spec.keywords),
                "industries": ";".join(spec.industries),
                "seed_tickers": ";".join(spec.seed_tickers),
                "risk_types": ";".join(spec.risk_types),
                "primary_metrics": ";".join(spec.primary_metrics),
            }
            for spec in SPECS
        ]
    )
