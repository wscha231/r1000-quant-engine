"""Synthetic contract fixtures. Never current investment evidence."""
from datetime import timedelta


def bundle(market="US", ticker="TEST"):
    from tools.research_decision_v1.data import digest, sessions
    cutoff = "2026-09-07T12:00:00Z"
    currency = "USD" if market == "US" else "KRW"
    ticker = ticker if market == "US" else "999999"
    sid = f"{market}:{ticker}"
    dates = sessions(market, "2025-06-01", cutoff)
    bars = [{"session": d, "close": 100.0, "volume": 1000000,
             "split_ratio": 1.0, "dividend": 0.0} for d in dates]
    period = {"start": "2025-07-01", "end": "2026-06-30"}
    metrics = {"revenue": 10000., "ebitda": 2000., "net_income": 1200.,
               "operating_cash_flow": 1600., "capex": 400., "fcf": 1200.,
               "sbc": 100., "net_debt": 1000., "diluted_shares": 100.}

    def envelope(payload, unit, basis="NOT_APPLICABLE"):
        return {"status": "available", "source": "https://example.org/synthetic",
                "security_id": sid, "published_at": "2026-08-01T00:00:00Z",
                "public_available_at": "2026-08-01T00:00:00Z",
                "first_seen_at": "2026-09-07T10:00:00Z",
                "ingested_at": "2026-09-07T11:00:00Z", "decision_cutoff": cutoff,
                "report_period": period, "unit": unit, "currency": currency,
                "accounting_basis": basis, "data_hash": digest(payload), "payload": payload}

    price = {"feed": "SYNTHETIC", "price_basis": "raw_unadjusted", "volume_basis": "raw_unadjusted",
             "quote_type": "official_close", "bars": bars,
             "corporate_actions_status": "no_event", "corporate_actions_through": dates[-1],
             "benchmark_id": "SPY" if market == "US" else "KOSPI200",
             "benchmark_bars": bars, "benchmark_actions_status": "no_event",
             "benchmark_price_basis": "raw_unadjusted"}
    thesis = {"id": f"fixture-{sid}", "intact": True, "strengthened": False,
              "confidence": 0.7, "company_quality": "pass",
              "business": "Synthetic business", "segments": "Synthetic segments",
              "customers": "Synthetic customer", "bottleneck": "Synthetic capacity",
              "competition": "Synthetic competitor", "catalyst": "Synthetic launch",
              "strongest_bear_case": "Synthetic margin contraction",
              "invalidation_condition": "Synthetic loss of customer",
              "valuation_rationale": "Synthetic multiple only",
              "source_evidence": [{"source": "https://example.org/synthetic", "claim": "fixture only"}]}
    financials = {"period": period, "ttm": metrics,
                  "recent_quarters": [{"start": "2026-04-01", "end": "2026-06-30", "revenue": 2700.}],
                  "recent_annual": [{"start": "2025-01-01", "end": "2025-12-31", "revenue": 9000.}]}
    risk = {"exposures": {"industry:test": 1., "theme:test": 1., "customer:test": 0.4},
            "complete_assessment": True, "stress_loss": 0.45, "uncertainty": 0.2,
            "liquidity_restriction": False, "integrity_alert": False}
    blocks = {"price": envelope(price, "currency_per_share"),
              "financials": envelope(financials, "currency_and_shares", "US_GAAP" if market == "US" else "K_IFRS_CONSOLIDATED"),
              "thesis": envelope(thesis, "text"), "risk": envelope(risk, "fraction")}
    return {"schema_version": "research-input-v1", "data_kind": "SYNTHETIC",
            "market": market, "decision_cutoff": cutoff,
            "securities": [{"security_id": sid, "ticker": ticker, "market": market,
                            "currency": currency, "blocks": blocks, "optional": {}}]}


def rehash(envelope):
    from tools.research_decision_v1.data import digest
    envelope["data_hash"] = digest(envelope["payload"])
