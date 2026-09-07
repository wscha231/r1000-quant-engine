"""Scenario fixtures are generic invented companies, never real recommendations."""
import copy
import json
from pathlib import Path
from research_decision_v1_fixture import bundle, rehash


def config():
    return json.loads((Path(__file__).resolve().parents[1] / "docs/research_decision_v1_config.json").read_text())


def with_scenario(market="US", ticker="TEST"):
    b = bundle(market, ticker); s = b["securities"][0]
    sc = copy.deepcopy(s["blocks"]["financials"])
    sc.update(unit="scenario_currency_and_shares", accounting_basis="RESEARCH_ASSUMPTION",
              report_period={"start": "2026-09-07", "end": "2027-09-07"})
    sc["payload"] = {"method": "EV_EBITDA", "company_type": "PROFITABLE_OPERATING",
                     "probability_type": "SUBJECTIVE_SCENARIO", "horizon_months": 12,
                     "target_date": "2027-09-07", "rationale": "Invented fixture assumptions",
                     "scenarios": [
                         {"name": "Bear", "probability": .25, "revenue": 8000., "margin": .15,
                          "multiple": 7., "net_debt": 1000., "diluted_shares": 100., "dividend": 0.},
                         {"name": "Base", "probability": .50, "revenue": 11000., "margin": .20,
                          "multiple": 9., "net_debt": 900., "diluted_shares": 100., "dividend": 0.},
                         {"name": "Bull", "probability": .25, "revenue": 13000., "margin": .23,
                          "multiple": 10., "net_debt": 800., "diluted_shares": 100., "dividend": 0.}]}
    rehash(sc); s["blocks"]["scenario"] = sc
    return b


def context():
    return {"mode": "NEW_CAPITAL_RESEARCH", "capital_krw": 100000000.,
            "capital_is_assumption": True, "decision_cutoff": "2026-09-07T12:00:00Z",
            "fx": {"status": "available", "source": "https://example.org/synthetic",
                   "observed_at": "2026-09-07T11:00:00Z", "pair": "KRW_PER_USD", "spot": 1400.,
                   "scenario_rates": {"Bear": 1400., "Base": 1400., "Bull": 1400.},
                   "assumption_type": "SUBJECTIVE_SCENARIO"},
            "regime": {"state": "CAUTION", "source": "https://example.org/synthetic",
                       "observed_at": "2026-09-07T11:00:00Z", "rationale": "Synthetic risk state"},
            "benchmark_expected_returns": {"US": .08, "KR": .08}}
