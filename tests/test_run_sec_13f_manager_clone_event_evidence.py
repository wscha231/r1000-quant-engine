from __future__ import annotations
import tempfile, unittest
from pathlib import Path
import sys
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from tools.run_sec_13f_manager_clone_event_evidence import (
    CloneEvidenceError, config_from_json, evaluate, manager_map_from_registry, publish_immutable,
)


def prices(start_px):
    idx = pd.bdate_range("2020-01-02", periods=900)
    return pd.DataFrame({"close": [start_px + 0.1*i for i in range(len(idx))]}, index=idx)

REG = {"candidates": [{"economic_manager_id": "DUQUESNE", "reporting_cik": "0001536411"}]}
PROV = {"adjusted_close_total_return_proxy_verified": True, "benchmark_total_return_verified": True,
        "calendar_verified": True, "prices_pit_or_frozen_snapshot_verified": True,
        "price_snapshot_id": "P", "calendar_id": "C", "benchmark_id": "B", "cost_model_id": "K"}
CONF = {"horizons": [63,126,252,504], "entry_delays": [0,2,5], "per_side_cost_bps": 10, "benchmark_ticker": "SPY"}
EVENTS = pd.DataFrame([{"event_id":"E1","manager_cik":"1536411","ticker":"AAA","event_type":"new","available_from":"2020-01-03T22:00:00Z","report_period":"2019-12-31"}])

class RunnerTests(unittest.TestCase):
    def test_registry_aliases_cik_forms(self):
        m = manager_map_from_registry(REG)
        self.assertEqual(m["1536411"], "DUQUESNE")
        self.assertEqual(m["0001536411"], "DUQUESNE")

    def test_registry_conflicting_cik_blocks(self):
        bad = {"candidates": REG["candidates"] + [{"economic_manager_id":"OTHER","reporting_cik":"1536411"}]}
        with self.assertRaises(CloneEvidenceError): manager_map_from_registry(bad)

    def test_unknown_config_key_blocks(self):
        with self.assertRaises(CloneEvidenceError): config_from_json({**CONF, "magic_alpha": 1})

    def test_evaluate_connects_registry_and_core(self):
        frames = {"AAA": prices(100), "SPY": prices(200)}
        out = evaluate(events=EVENTS, registry=REG, provenance=PROV, config_value=CONF,
                       decision_cutoff="2024-12-31T23:59:59Z", price_loader=lambda t: frames[t])
        self.assertGreater(out["matured_rows"], 0)
        self.assertEqual({r["economic_manager_id"] for r in out["event_rows"]}, {"DUQUESNE"})

    def test_publish_is_identical_rerun_only(self):
        frames = {"AAA": prices(100), "SPY": prices(200)}
        out = evaluate(events=EVENTS, registry=REG, provenance=PROV, config_value=CONF,
                       decision_cutoff="2024-12-31T23:59:59Z", price_loader=lambda t: frames[t])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"artifact"
            a = publish_immutable(p, out, {"decision_cutoff": out["decision_cutoff"]})
            b = publish_immutable(p, out, {"decision_cutoff": out["decision_cutoff"]})
            self.assertEqual(a["publication"], "NEW_LOCAL_DIAGNOSTIC")
            self.assertEqual(b["publication"], "IDENTICAL_RERUN_VERIFIED")
            (p/"summary.json").write_text("tampered", encoding="utf-8")
            with self.assertRaises(CloneEvidenceError): publish_immutable(p, out, {"decision_cutoff": out["decision_cutoff"]})

if __name__ == "__main__": unittest.main()
