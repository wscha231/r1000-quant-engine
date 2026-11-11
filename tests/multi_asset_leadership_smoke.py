#!/usr/bin/env python3
"""Offline synthetic fixtures; never evidence of live returns or coverage."""
from __future__ import annotations

import copy
from datetime import timedelta
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research.multi_asset_v1.contracts import ContractError,digest,encoded,load_json,metadata,registry_rows,stamp
from research.multi_asset_v1.prices import grid,admit_prices
from research.multi_asset_v1.runtime import run,feature_identity,feature_availability
from research.multi_asset_v1.decisions import classify,evaluation,event_memory,lookthrough,propose
from tools.run_multi_asset_leadership import parse_chart,publish,read_latest,configuration_bytes,verified_source_hashes,prepare_model_snapshot
from research.multi_asset_v1.sources import candles,capture_spot_metrics,crypto_chart

CUTOFF="2026-09-19T10:00:00+00:00"
SESSIONS=grid(CUTOFF)
CODE_SHA=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()


def configuration_args(out):
    return ["--expected-registry-sha256",hashlib.sha256((out/"registry.json").read_bytes()).hexdigest(),
            "--expected-policy-sha256",hashlib.sha256((out/"policy.json").read_bytes()).hexdigest()]


def fixture():
    registry=json.loads((ROOT/"docs/multi_asset_registry_v1.json").read_bytes())
    ids={"US:SPY","US:FCX","US:CCJ","US:FTI"}
    registry["assets"]=[a for a in registry["assets"] if a["asset_id"] in ids]
    for a in registry["assets"]:
        a.update(identity_verified=True,tradable=True,corporate_action_quarantine=False)
    policy=json.loads((ROOT/"docs/multi_asset_policy_v1.json").read_bytes())
    payload={"schema":"multi-asset-input-v1","as_of":CUTOFF,"prices":[],"events":[],"metrics":[],"base_equity_ids":["US:FTI"]}
    for i,a in enumerate(registry["assets"]):
        value=100.0
        for t,(session,close) in enumerate(SESSIONS.items()):
            value*=math.exp(.0004+i*.0007+(.001+i*.0008)*math.sin(t*.53+i))
            payload["prices"].append(dict(asset_id=a["asset_id"],session=session,clock="NYSE_CLOSE",price=value,total_return_index=value,volume=1_000_000,return_basis="TOTAL_RETURN",unit=a["price_unit"],currency="USD",corporate_action_quarantine=False,observed_at=close.isoformat(),available_at=(close+timedelta(minutes=1)).isoformat(),collected_at=CUTOFF,source="CANONICAL_PRICE_ARCHIVE",data_quality="OBSERVED",evidence_kind="PIT_ARCHIVE",raw_sha256="a"*64))
    return payload,registry,policy


def meta(source):
    close=list(SESSIONS.values())[-1].isoformat()
    return dict(observed_at=close,available_at=CUTOFF,collected_at=CUTOFF,source=source,data_quality="OBSERVED",evidence_kind="FORWARD_CAPTURE",raw_sha256="b"*64)


def reviewed(p,r,policy):
    feature_hash=feature_identity(p,r)
    policy["validated_models"]={"TEST_MODEL":{"asset_classes":["US_EQUITY","COMMODITY_EQUITY"],"validation_sha256":"c"*64,"benchmark_id":"US:SPY"}}
    policy["reviewed_pins"]["company_evidence"]=["d"*64]
    policy["reviewed_pins"]["underlying_evidence"]=["e"*64]
    p["evaluations"]=[]
    for a in r["assets"]:
        if a["symbol"]=="SPY":continue
        e=dict(**meta("REVIEWED_EVALUATOR"),asset_id=a["asset_id"],feature_sha256=feature_hash,unit="RETURN_FRACTION",currency="USD",validation_status="WALK_FORWARD_VALIDATED",model_id="TEST_MODEL",validation_sha256="c"*64,training_labels_available_before="2026-01-01T00:00:00Z",thesis_status="POSITIVE",thesis_id="THESIS:"+a["symbol"],valuation_acceptable=True,net_of_costs=True,cost_assumptions={k:0 for k in ["spread_bps","commission_bps","slippage_bps","tax_bps","expense_bps","roll_bps"]},cost_basis="INCREMENTAL_NOT_ALREADY_IN_TOTAL_RETURN",signal_confidence=.8,thesis_confidence=.9,downside_probability=.2,expected_drawdown=.2,company_evidence_sha256="d"*64,underlying_evidence_sha256="e"*64,scenarios={})
        for h in ("1m","3m","6m","12m"):
            e["scenarios"][h]={"bear":{"return":-.1,"probability":.2},"base":{"return":.2,"probability":.6},"bull":{"return":.5,"probability":.2}}
            e["expected_return_"+h]=.2
            e["benchmark_expected_return_"+h]=.05
        e.update(observed_at=CUTOFF,benchmark_id="US:SPY")
        policy["reviewed_pins"]["evaluation"].append(digest(e))
        p["evaluations"].append(e)
    receipt={**meta("CANONICAL_UNIVERSE"),"asset_ids":sorted(p["base_equity_ids"]),"as_of":list(SESSIONS)[-1]}
    p["base_universe_receipt"]=receipt
    policy["reviewed_pins"]["base_universe"].append(digest(receipt))
    return p,r,policy


def risk(p,r,policy):
    risk=dict(**meta("REVIEWED_RISK"),feature_sha256=feature_identity(p,r),regime="RISK_OFF",max_gross=.4,max_security_weight=.1,max_pair_correlation=1.0,minimum_expected_alpha=.01,risk_multipliers={"US_EQUITY":1,"COMMODITY_EQUITY":1},risk_group_limits={g:.3 for a in r["assets"] for g in a["risk_group_ids"]})
    risk["observed_at"]=CUTOFF
    policy["reviewed_pins"]["risk"].append(digest(risk))
    p["risk"]=risk
    return risk


class Integrity(unittest.TestCase):
    def setUp(self):self.p,self.r,self.policy=fixture()

    def test_registry_separates_underlying_vehicle_and_no_account_permission(self):
        real=json.loads((ROOT/"docs/multi_asset_registry_v1.json").read_bytes())
        u,a=registry_rows(real)
        self.assertEqual(len(u),12)
        self.assertEqual(a["US:CPER"]["underlying"],a["US:FCX"]["underlying"])
        self.assertNotEqual(a["US:CPER"]["vehicle_type"],a["US:FCX"]["vehicle_type"])
        self.assertTrue(all(x["tradable"] is False for x in a.values()))

    def test_duplicate_json_rejected(self):
        with self.assertRaises(ContractError):load_json(b'{"a":1,"a":2}')

    def test_nonfinite_json_rejected(self):
        with self.assertRaises(ContractError):load_json(b'{"a":NaN}')

    def test_time_quality_unit_boundaries(self):
        a=self.r["assets"][0]
        source=[x for x in self.p["prices"] if x["asset_id"]==a["asset_id"]]
        for k,v in [("available_at","2027-01-01T00:00:00Z"),("available_at","2026-09-18T21:00:00"),("source","SYNTHETIC"),("data_quality","SYNTHETIC"),("unit","USD_PER_TONNE"),("currency","KRW"),("total_return_index",True),("total_return_index",float('inf')),("return_basis","PRICE_RETURN"),("corporate_action_quarantine",True),("clock","UTC_DAY")]:
            with self.subTest(k=k,v=v):
                rows=copy.deepcopy(source);rows[-1][k]=v
                with self.assertRaises((ContractError,ValueError)):admit_prices(rows,a,CUTOFF,self.policy,SESSIONS)

    def test_missing_intermediate_session_blocks_not_common_date_shortening(self):
        a=self.r["assets"][0];rows=[x for x in self.p["prices"] if x["asset_id"]==a["asset_id"]]
        del rows[-12]
        with self.assertRaisesRegex(ContractError,"incomplete_price"):admit_prices(rows,a,CUTOFF,self.policy,SESSIONS)

    def test_registry_quarantine_cannot_be_cleared_by_payload(self):
        a=self.r["assets"][0]
        rows=[x for x in self.p["prices"] if x["asset_id"]==a["asset_id"]]
        for flag in (True,None):
            with self.subTest(flag=flag):
                a["corporate_action_quarantine"]=flag
                with self.assertRaisesRegex(ContractError,"registry_corporate_action_quarantine"):
                    admit_prices(rows,a,CUTOFF,self.policy,SESSIONS)

    def test_duplicate_price_blocks(self):
        self.p["prices"].append(copy.deepcopy(self.p["prices"][0]))
        out=run(self.p,self.r,self.policy)
        self.assertTrue(any("duplicate_price_session" in x["blockers"] for x in out["multi_asset_leadership_latest"]))

    def test_nyse_holiday_and_early_close(self):
        g=grid("2026-11-27T19:00:00Z")
        self.assertNotIn("2026-11-26",g)
        self.assertEqual(g["2026-11-27"].hour,18)

    def test_boolean_registry_flag_rejected(self):
        for field in ("tradable","identity_verified","corporate_action_quarantine"):
            with self.subTest(field=field):
                altered=copy.deepcopy(self.r);altered["assets"][0][field]="false"
                with self.assertRaises(ContractError):registry_rows(altered)

    def test_price_rs_matches_independent_ratio(self):
        out=run(self.p,self.r,self.policy)
        row=out["multi_asset_leadership_latest"][0]
        stock=[x for x in self.p["prices"] if x["asset_id"]==row["asset_id"]]
        bench=[x for x in self.p["prices"] if x["asset_id"]=="US:SPY"]
        expected=math.log((stock[-1]["price"]/stock[-21]["price"])/(bench[-1]["price"]/bench[-21]["price"]))
        self.assertAlmostEqual(row["RS20"],expected,12)

    def test_no_evaluation_never_becomes_buy_or_expected_return(self):
        out=run(self.p,self.r,self.policy)
        self.assertTrue(all(x["expected_return_12m"] is None and x["portfolio_status"]=="RESEARCH" for x in out["multi_asset_leadership_latest"]))
        self.assertFalse(out["global_ranking_ready"])
        self.assertIsNone(out["proposal"]["proposed_weights"])

    def test_missing_benchmark_blocks_all(self):
        self.p["prices"]=[x for x in self.p["prices"] if x["asset_id"]!="US:SPY"]
        out=run(self.p,self.r,self.policy)
        self.assertTrue(all(x["RS20"] is None for x in out["multi_asset_leadership_latest"]))

    def test_genuine_zero_metric_preserved_missing_blocked(self):
        self.p["metrics"]=[dict(**meta("REVIEWED_NETWORK"),subject_id="BTC",metric="net_issuance",unit="TOKEN",currency="BTC",value=0)]
        out=run(self.p,self.r,self.policy);self.assertEqual(out["metrics"][0]["value"],0)
        self.p["metrics"][0]["value"]=None
        out=run(self.p,self.r,self.policy);self.assertIsNone(out["metrics"][0]["value"])
        self.assertEqual(out["metrics"][0]["admission"],"BLOCKED")

    def test_stale_observation_not_refreshed_by_collection(self):
        row=dict(**meta("EIA"),subject_id="NATURAL_GAS",metric="inventory",unit="BCF",value=100)
        row["observed_at"]="2026-08-01T00:00:00Z"
        with self.assertRaisesRegex(ContractError,"stale"):metadata(row,CUTOFF,self.policy,"metric")

    def test_current_capture_cannot_be_historical_pit(self):
        for x in self.p["prices"]:x["evidence_kind"]="FORWARD_CAPTURE"
        out=run(self.p,self.r,self.policy)
        self.assertIn("forward_capture_not_historical_pit",out["historical_replay"]["blockers"])
        self.assertIsNone(out["historical_replay"]["net_cagr"])

    def test_proxy_rs_is_labeled_and_cannot_enter_expected_return(self):
        reviewed(self.p,self.r,self.policy)
        for x in self.p["prices"]:x.update(return_basis="PROVIDER_ADJUSTED_CLOSE_PROXY",source="YAHOO_CHART")
        out=run(self.p,self.r,self.policy)
        self.assertTrue(all(x["RS20"] is not None and x["data_quality"]=="PRICE_PROXY_RESEARCH_ONLY" and x["expected_return_12m"] is None for x in out["multi_asset_leadership_latest"]))

    def test_crypto_utc_history_is_not_nyse_history(self):
        real=json.loads((ROOT/"docs/multi_asset_registry_v1.json").read_bytes())
        a=next(a for a in real["assets"] if a["asset_id"]=="CRYPTO:BTC-USD")
        self.r["assets"].append(a)
        from research.multi_asset_v1.contracts import stamp
        end=stamp(CUTOFF).replace(hour=0,minute=0,second=0)
        for i in range(261):
            close=end-timedelta(days=260-i)
            row=dict(**meta("CANONICAL_PRICE_ARCHIVE"),asset_id=a["asset_id"],session=(close-timedelta(days=1)).date().isoformat(),clock="UTC_DAY",price=100+i,total_return_index=100+i,volume=1000,return_basis="TOTAL_RETURN",unit=a["price_unit"],currency="USD",corporate_action_quarantine=False)
            row["observed_at"]=close.isoformat()
            self.p["prices"].append(row)
        out=run(self.p,self.r,self.policy)
        self.assertEqual(out["crypto_market_latest"][0]["status"],"UTC_ONLY")
        ny=next(r for r in out["multi_asset_leadership_latest"] if r["asset_id"]==a["asset_id"])
        self.assertIsNone(ny["RS20"])
        self.assertAlmostEqual(out["crypto_market_latest"][0]["utc_calendar"]["ret20_calendar_days"],360/340-1)

    def test_conflicting_horizon_basis_rejected(self):
        a=self.r["assets"][0]
        rows=[x for x in self.p["prices"] if x["asset_id"]==a["asset_id"]]
        rows[0]["return_basis"]="PROVIDER_ADJUSTED_CLOSE_PROXY"
        rows[0]["source"]="YAHOO_CHART"
        with self.assertRaisesRegex(ContractError,"mixed_return_basis"):admit_prices(rows,a,CUTOFF,self.policy,SESSIONS)

    def test_yahoo_cannot_self_declare_total_return(self):
        a=self.r["assets"][0]
        rows=[{**x,"source":"YAHOO_CHART"} for x in self.p["prices"] if x["asset_id"]==a["asset_id"]]
        with self.assertRaisesRegex(ContractError,"source_return_basis_not_approved"):
            admit_prices(rows,a,CUTOFF,self.policy,SESSIONS)

    def test_spy_relative_returns_require_same_basis(self):
        for x in self.p["prices"]:
            if x["asset_id"]=="US:SPY":x.update(source="YAHOO_CHART",return_basis="PROVIDER_ADJUSTED_CLOSE_PROXY")
        out=run(self.p,self.r,self.policy)
        self.assertTrue(all(x["RS20"] is None and x["discovery_rank"] is None and "benchmark_return_basis_mismatch" in x["blockers"] for x in out["multi_asset_leadership_latest"]))

    def test_unsupported_baseline_policy_does_not_mislabel_results(self):
        for field,key in (("baseline_rs_weights","20"),("baseline_commodity_weights","price")):
            with self.subTest(field=field):
                policy=copy.deepcopy(self.policy);policy[field][key]=.5
                with self.assertRaisesRegex(ContractError,"unsupported_.*_baseline"):
                    run(self.p,self.r,policy)

    def test_crypto_relative_returns_require_matching_source_basis(self):
        from research.multi_asset_v1.contracts import stamp
        real=json.loads((ROOT/"docs/multi_asset_registry_v1.json").read_bytes())
        end=stamp(CUTOFF).replace(hour=0,minute=0,second=0)
        for aid,basis,source in (("CRYPTO:BTC-USD","TOTAL_RETURN","CANONICAL_PRICE_ARCHIVE"),("CRYPTO:ETH-USD","PROVIDER_ADJUSTED_CLOSE_PROXY","YAHOO_CHART")):
            a=next(a for a in real["assets"] if a["asset_id"]==aid);self.r["assets"].append(a)
            for i in range(261):
                close=end-timedelta(days=260-i)
                row=dict(**meta(source),asset_id=aid,session=(close-timedelta(days=1)).date().isoformat(),clock="UTC_DAY",price=100+i,total_return_index=100+i,volume=1000,return_basis=basis,unit=a["price_unit"],currency="USD",corporate_action_quarantine=False)
                row["observed_at"]=close.isoformat();self.p["prices"].append(row)
        out=run(self.p,self.r,self.policy)
        eth=next(x for x in out["crypto_market_latest"] if x["asset_id"]=="CRYPTO:ETH-USD")["utc_calendar"]
        self.assertIsNone(eth["RS_BTC"])
        self.assertEqual(eth["BTC_return_basis"],"TOTAL_RETURN")
        self.assertEqual(eth["RS_BTC_blocker"],"crypto_benchmark_return_basis_mismatch")


class Decisions(unittest.TestCase):
    def setUp(self):self.p,self.r,self.policy=reviewed(*fixture())

    def test_unreviewed_prediction_not_admitted(self):
        self.policy["reviewed_pins"]["evaluation"]=[]
        out=run(self.p,self.r,self.policy)
        self.assertTrue(all(x["expected_return_12m"] is None for x in out["multi_asset_leadership_latest"]))

    def test_reviewed_scenario_expected_return(self):
        out=run(self.p,self.r,self.policy)
        self.assertTrue(all(abs(x["expected_return_12m"]-.2)<1e-10 for x in out["multi_asset_leadership_latest"]))
        self.assertEqual(sorted(x["rank"] for x in out["multi_asset_leadership_latest"]),[1,2,3])

    def test_changed_features_invalidate_prediction(self):
        self.p["prices"][-1]["price"]+=1
        out=run(self.p,self.r,self.policy)
        self.assertTrue(all(x["expected_return_12m"] is None for x in out["multi_asset_leadership_latest"]))

    def test_scenario_probability_and_cost_checks(self):
        a=self.r["assets"][0];row=self.p["evaluations"][0]
        for field,value in [("net_of_costs",False),("expected_return_12m",.9),("company_evidence_sha256","f"*64),("training_labels_available_before",CUTOFF)]:
            with self.subTest(field=field):
                e=copy.deepcopy(row);e[field]=value
                self.policy["reviewed_pins"]["evaluation"].append(digest(e))
                with self.assertRaises(ContractError):evaluation(e,a,CUTOFF,self.policy,feature_identity(self.p,self.r),feature_availability(self.p))

    def test_evaluation_cannot_predate_any_bound_feature(self):
        close=list(SESSIONS.values())[-1]
        early=(close+timedelta(minutes=10)).isoformat()
        late=(close+timedelta(minutes=30)).isoformat()
        for kind in ("price","metric","event"):
            with self.subTest(kind=kind):
                p,r,policy=fixture()
                if kind=="price":p["prices"][-1]["available_at"]=late
                elif kind=="metric":
                    p["metrics"]=[{**meta("EIA"),"available_at":late,"subject_id":"NATURAL_GAS","metric":"inventory","unit":"BCF","value":100}]
                else:
                    p["events"]=[{**meta("CANONICAL_NEWS"),"available_at":late,"published_at":late,"event_id":"EVENT:1","event_type":"MINE_OUTAGE","confidence":.9,"materiality":.8,"confirmed":True,"thesis_effect":"REVIEW_NEGATIVE","estimated_duration":"2_WEEKS","asset_ids":[],"commodity_ids":["COPPER"],"theme_ids":[],"duplicate_cluster":"OUTAGE:1"}]
                reviewed(p,r,policy)
                for e in p["evaluations"]:
                    e.update(observed_at=early,available_at=early)
                    policy["reviewed_pins"]["evaluation"].append(digest(e))
                risk(p,r,policy)
                out=run(p,r,policy)
                self.assertTrue(all(x["expected_return_12m"] is None and "evaluation:evaluation_predates_feature_inputs" in x["blockers"] for x in out["multi_asset_leadership_latest"]))
                self.assertEqual(out["proposal"]["status"],"BLOCKED")

    def test_benchmark_identity_must_match_evaluation_model_policy_and_asset(self):
        for location in ("evaluation","model","registry"):
            for bad in (None,"US:CASH"):
                with self.subTest(location=location,bad=bad):
                    p,r,policy=fixture()
                    aid=next(a["asset_id"] for a in r["assets"] if a["symbol"]!="SPY")
                    if location=="registry":next(a for a in r["assets"] if a["asset_id"]==aid)["benchmark"]=bad or "US:UNKNOWN"
                    reviewed(p,r,policy)
                    e=next(e for e in p["evaluations"] if e["asset_id"]==aid)
                    if location=="evaluation":
                        e["benchmark_id"]=bad;policy["reviewed_pins"]["evaluation"].append(digest(e))
                    elif location=="model":policy["validated_models"]["TEST_MODEL"]["benchmark_id"]=bad
                    out=run(p,r,policy)
                    row=next(x for x in out["multi_asset_leadership_latest"] if x["asset_id"]==aid)
                    self.assertIsNone(row["expected_return_12m"])
                    self.assertIn("evaluation:evaluation_benchmark_mismatch",row["blockers"])

    def test_incomplete_evaluation_coverage_suppresses_all_global_ranks(self):
        for aid in ("US:FTI","US:FCX"):
            for missing in ("prices","evaluation"):
                with self.subTest(aid=aid,missing=missing):
                    p,r,policy=fixture()
                    if missing=="prices":p["prices"]=[x for x in p["prices"] if x["asset_id"]!=aid]
                    reviewed(p,r,policy)
                    if missing=="evaluation":p["evaluations"]=[x for x in p["evaluations"] if x["asset_id"]!=aid]
                    risk(p,r,policy);out=run(p,r,policy)
                    self.assertTrue(any(x["expected_return_12m"] is not None for x in out["multi_asset_leadership_latest"]))
                    self.assertFalse(out["global_ranking_ready"])
                    self.assertEqual(out["ranking_scope"],"INCOMPLETE_EVALUATION_COVERAGE")
                    self.assertTrue(all(x["rank"] is None for x in out["multi_asset_leadership_latest"]))
                    self.assertTrue(all(x["best_vehicle"] is None and x["best_equity"] is None for x in out["commodity_market_latest"]))
                    self.assertEqual(out["proposal"]["status"],"BLOCKED")

    def test_risk_packet_cannot_predate_bound_features(self):
        riskrow=risk(self.p,self.r,self.policy)
        riskrow["observed_at"]=list(SESSIONS.values())[-1].isoformat()
        self.policy["reviewed_pins"]["risk"].append(digest(riskrow))
        out=run(self.p,self.r,self.policy)
        self.assertTrue(out["global_ranking_ready"])
        self.assertEqual(out["proposal"]["reasons"],["risk_predates_feature_inputs"])

    def test_invalid_bound_metric_blocks_evaluation_and_proposal(self):
        for field,value in (("observed_at","2026-08-01T00:00:00Z"),("unit","MW"),("value",None),("source","UNAPPROVED"),("data_quality","SYNTHETIC")):
            with self.subTest(field=field):
                p,r,policy=fixture()
                metric=dict(**meta("EIA"),subject_id="NATURAL_GAS",metric="inventory",unit="BCF",value=100)
                metric[field]=value;p["metrics"]=[metric]
                reviewed(p,r,policy);risk(p,r,policy)
                out=run(p,r,policy)
                self.assertEqual(out["metrics"][0]["admission"],"BLOCKED")
                self.assertTrue(all(x["expected_return_12m"] is None and x["rank"] is None and "evaluation:feature_metric_not_admitted" in x["blockers"] for x in out["multi_asset_leadership_latest"]))
                self.assertFalse(out["global_ranking_ready"])
                self.assertEqual(out["proposal"]["status"],"BLOCKED")

    def test_short_rs_does_not_sell_or_remove_held_thesis(self):
        f={"RS20":-.15,"RS60":.05,"RS120":.2,"RS240":.3,"RS20_change_5d":-.1,"RS60_change_5d":-.1}
        state,status=classify(f,self.p["evaluations"][0],True)
        self.assertEqual((state,status),("REVERSAL_PANIC","HOLD"))

    def test_risk_off_is_gross_cap_without_automatic_exit(self):
        risk(self.p,self.r,self.policy)
        out=run(self.p,self.r,self.policy)
        self.assertEqual(out["proposal"]["status"],"RESEARCH_PROPOSAL")
        self.assertLessEqual(sum(out["proposal"]["proposed_weights"].values()),.4)
        self.assertFalse(out["orders_generated"])

    def test_no_commodity_floor(self):
        riskrow=risk(self.p,self.r,self.policy)
        assets={a["asset_id"]:a for a in self.r["assets"]}
        row=dict(asset_id="US:FTI",portfolio_status="CANDIDATE",thesis_status="POSITIVE",valuation_acceptable=True,expected_alpha_12m=.3,liquidity_pass=True,RS20_change_5d=.1,RS60_change_5d=.1,RS120=.1,RS240=.1,signal_confidence=.8,thesis_confidence=.8,expected_drawdown=.2,daily_log_returns=[math.sin(i) for i in range(60)])
        proposal=propose([row],assets,riskrow,{},CUTOFF,self.policy,feature_identity(self.p,self.r))
        self.assertEqual(set(proposal["proposed_weights"]),{"US:FTI"})
        self.assertGreater(proposal["cash"],.8)

    def test_weak_short_rs_carries_existing_weight_in_proposal(self):
        riskrow=risk(self.p,self.r,self.policy)
        assets={a["asset_id"]:a for a in self.r["assets"]}
        row=dict(asset_id="US:FTI",portfolio_status="HOLD",expected_alpha_12m=.3,liquidity_pass=True,RS20_change_5d=-.1,RS60_change_5d=-.1,RS120=.1,RS240=.1,signal_confidence=.8,thesis_confidence=.8,expected_drawdown=.2,daily_log_returns=[math.sin(i) for i in range(60)])
        proposal=propose([row],assets,riskrow,{},CUTOFF,self.policy,feature_identity(self.p,self.r),{"US:FTI":.08})
        self.assertEqual(proposal["proposed_weights"],{"US:FTI":.08})
        self.assertIsNone(proposal["reduction_basis"])

    def test_gross_risk_reduction_is_separate_from_entry_signal(self):
        riskrow=risk(self.p,self.r,self.policy);riskrow["max_gross"]=.04
        self.policy["reviewed_pins"]["risk"].append(digest(riskrow))
        assets={a["asset_id"]:a for a in self.r["assets"]}
        row=dict(asset_id="US:FTI",portfolio_status="HOLD",expected_alpha_12m=.3,liquidity_pass=True,RS20_change_5d=-.1,RS60_change_5d=-.1,RS120=.1,RS240=.1,signal_confidence=.8,thesis_confidence=.8,expected_drawdown=.2,daily_log_returns=[math.sin(i) for i in range(60)])
        proposal=propose([row],assets,riskrow,{},CUTOFF,self.policy,feature_identity(self.p,self.r),{"US:FTI":.08})
        self.assertEqual(proposal["proposed_weights"],{"US:FTI":.04})
        self.assertEqual(proposal["reduction_basis"],"REVIEWED_RISK_CEILINGS_ONLY")

    def test_incomplete_base_universe_blocks_proposal(self):
        risk(self.p,self.r,self.policy)
        self.policy["reviewed_pins"]["base_universe"]=[]
        out=run(self.p,self.r,self.policy)
        self.assertEqual(out["proposal"]["status"],"BLOCKED")
        self.assertTrue(all(x["rank"] is None for x in out["multi_asset_leadership_latest"]))

    def test_missing_future_or_stale_base_receipt_blocks_ranking(self):
        risk(self.p,self.r,self.policy)
        for field,value in (("available_at",None),("available_at","2026-09-20T00:00:00Z"),("observed_at","2026-08-01T00:00:00Z")):
            with self.subTest(field=field,value=value):
                bad=copy.deepcopy(self.p);bad["base_universe_receipt"][field]=value
                self.policy["reviewed_pins"]["base_universe"].append(digest(bad["base_universe_receipt"]))
                out=run(bad,self.r,self.policy)
                self.assertFalse(out["global_ranking_ready"])
                self.assertEqual(out["proposal"]["status"],"BLOCKED")
                self.assertTrue(all(r["rank"] is None for r in out["multi_asset_leadership_latest"]))

    def test_held_benchmark_without_comparator_blocks_proposal(self):
        risk(self.p,self.r,self.policy)
        self.p["positions"]=[{"asset_id":"US:SPY","weight":.08}]
        self.p["position_book_kind"]="PAPER"
        receipt={**meta("CANONICAL_BOOK"),"as_of":list(SESSIONS)[-1],"book_kind":"PAPER","positions_sha256":digest(self.p["positions"])}
        self.policy["reviewed_pins"]["positions"].append(digest(receipt));self.p["position_receipt"]=receipt
        out=run(self.p,self.r,self.policy)
        self.assertEqual(out["proposal"]["status"],"BLOCKED")
        self.assertIn("held_comparison_missing",out["proposal"]["reasons"])

    def test_future_position_receipt_cannot_pass_its_pin(self):
        self.p["positions"]=[{"asset_id":"US:FTI","weight":.08}];self.p["position_book_kind"]="PAPER"
        receipt={**meta("CANONICAL_BOOK"),"as_of":list(SESSIONS)[-1],"book_kind":"PAPER","positions_sha256":digest(self.p["positions"])}
        receipt["available_at"]="2026-09-20T00:00:00Z"
        self.policy["reviewed_pins"]["positions"].append(digest(receipt));self.p["position_receipt"]=receipt
        with self.assertRaisesRegex(ContractError,"future_or_conflicting_time"):run(self.p,self.r,self.policy)

    def test_model_label_or_account_pin_does_not_admit_model_incumbents(self):
        original=copy.deepcopy(self.p)
        for book_kind in ("PAPER","ACTUAL_BROKER","APPROVED_TARGET","MODEL"):
            self.p=copy.deepcopy(original)
            self.p["positions"]=[{"asset_id":"US:FTI","weight":.08}]
            self.p["position_book_kind"]="MODEL"
            receipt={**meta("CANONICAL_BOOK"),"as_of":list(SESSIONS)[-1],"book_kind":book_kind,
                     "positions_sha256":digest(self.p["positions"])}
            self.policy["reviewed_pins"]["positions"].append(digest(receipt))
            self.p["position_receipt"]=receipt
            with self.subTest(source=book_kind),self.assertRaisesRegex(ContractError,"^current_model_incumbents_required$"):
                run(self.p,self.r,self.policy)

    def test_unknown_empty_model_is_not_genesis_or_actual_empty(self):
        self.p.update(position_book_kind="MODEL",positions=[],cash_weight=1.0)
        with self.assertRaisesRegex(ContractError,"^current_model_incumbents_required$"):
            run(self.p,self.r,self.policy)

    def test_held_negative_thesis_or_bad_valuation_never_adds(self):
        riskrow=risk(self.p,self.r,self.policy);assets={a["asset_id"]:a for a in self.r["assets"]}
        row=dict(asset_id="US:FTI",portfolio_status="HOLD",thesis_status="POSITIVE",valuation_acceptable=True,expected_alpha_12m=.3,liquidity_pass=True,RS20_change_5d=.1,RS60_change_5d=.1,RS120=.1,RS240=.1,signal_confidence=.8,thesis_confidence=.8,expected_drawdown=.2,daily_log_returns=[math.sin(i) for i in range(60)])
        for field,value in (("thesis_status","NEGATIVE"),("valuation_acceptable",False),("thesis_status",None)):
            with self.subTest(field=field,value=value):
                changed={**row,field:value}
                proposal=propose([changed],assets,riskrow,{},CUTOFF,self.policy,feature_identity(self.p,self.r),{"US:FTI":.08})
                self.assertEqual(proposal["proposed_weights"],{"US:FTI":.08})
                self.assertEqual(changed["portfolio_status"],"HOLD")

    def test_carried_pairs_must_obey_correlation_ceiling_without_entry_signal(self):
        riskrow=risk(self.p,self.r,self.policy);riskrow["max_pair_correlation"]=.5
        self.policy["reviewed_pins"]["risk"].append(digest(riskrow))
        assets={a["asset_id"]:a for a in self.r["assets"]}
        first=dict(asset_id="US:FTI",portfolio_status="HOLD",thesis_status="POSITIVE",valuation_acceptable=True,expected_alpha_12m=.3,liquidity_pass=True,RS20_change_5d=-.1,RS60_change_5d=-.1,RS120=.1,RS240=.1,signal_confidence=.8,thesis_confidence=.8,expected_drawdown=.2,daily_log_returns=[math.sin(i) for i in range(60)])
        second={**first,"asset_id":"US:FCX"}
        weights={"US:FTI":.05,"US:FCX":.05}
        with self.assertRaisesRegex(ContractError,"carried_pair_correlation_limit"):
            propose([first,second],assets,riskrow,{},CUTOFF,self.policy,feature_identity(self.p,self.r),weights)
        second["daily_log_returns"]=[math.cos(i) for i in range(60)]
        proposal=propose([first,second],assets,riskrow,{},CUTOFF,self.policy,feature_identity(self.p,self.r),weights)
        self.assertEqual(proposal["proposed_weights"],weights)

    def test_position_book_must_be_pinned(self):
        self.p["positions"]=[{"asset_id":"US:FTI","weight":.2}]
        self.p["position_book_kind"]="ACTUAL_BROKER"
        with self.assertRaisesRegex(ContractError,"position_book"):run(self.p,self.r,self.policy)

    def test_evaluator_cannot_overwrite_price_features(self):
        self.p["evaluations"][0]["RS20"]=999
        self.policy["reviewed_pins"]["evaluation"].append(digest(self.p["evaluations"][0]))
        out=run(self.p,self.r,self.policy)
        self.assertTrue(all(x["RS20"]!=999 for x in out["multi_asset_leadership_latest"]))

    def test_rank_changes_not_fabricated_without_previous_cohort(self):
        out=run(self.p,self.r,self.policy)
        self.assertTrue(all(x["rank_change_5d"] is None and x["score_change_20d"] is None for x in out["multi_asset_leadership_latest"]))

    def test_retrospective_history_cannot_claim_old_rank_changes(self):
        current=run(self.p,self.r,self.policy)
        old_session=list(SESSIONS)[-6];close=SESSIONS[old_session];then=(close+timedelta(hours=1)).isoformat()
        # Explicit synthetic historical observations, not relabeled current rows.
        old_rows=[{"asset_id":r["asset_id"],"as_of":old_session,"latest_session":old_session,"rank":i+1,"RS_composite":i*.1} for i,r in enumerate(current["multi_asset_leadership_latest"])]
        previous={"as_of":old_session,"computed_at":then,"registry_sha256":digest(self.r),"multi_asset_leadership_latest":old_rows}
        receipt={**meta("CANONICAL_HISTORY"),"observed_at":close.isoformat(),"available_at":then,"evidence_kind":"PIT_ARCHIVE","snapshot_sha256":digest(previous)}
        previous["availability_receipt"]=receipt
        self.policy["reviewed_pins"]["history_availability"].append(digest(receipt))
        self.policy["reviewed_pins"]["history"].append(digest(previous));self.p["history"]=[previous]
        out=run(self.p,self.r,self.policy)
        old_by_id={r["asset_id"]:r for r in old_rows}
        self.assertTrue(all(x["rank_change_5d"]==old_by_id[x["asset_id"]]["rank"]-x["rank"] for x in out["multi_asset_leadership_latest"]))
        for mode in ("missing","retrospective","as_of","latest_session"):
            with self.subTest(mode=mode):
                altered=copy.deepcopy(previous)
                if mode=="missing":altered.pop("availability_receipt")
                elif mode=="retrospective":
                    later=(list(SESSIONS.values())[-1]+timedelta(hours=1)).isoformat()
                    altered["computed_at"]=later;altered["availability_receipt"]["available_at"]=later
                    altered["availability_receipt"]["snapshot_sha256"]=digest({k:v for k,v in altered.items() if k!="availability_receipt"})
                    self.policy["reviewed_pins"]["history_availability"].append(digest(altered["availability_receipt"]))
                else:
                    altered["multi_asset_leadership_latest"][0][mode]=list(SESSIONS)[-1]
                    altered["availability_receipt"]["snapshot_sha256"]=digest({k:v for k,v in altered.items() if k!="availability_receipt"})
                    self.policy["reviewed_pins"]["history_availability"].append(digest(altered["availability_receipt"]))
                self.policy["reviewed_pins"]["history"].append(digest(altered));self.p["history"]=[altered]
                with self.assertRaises(ContractError):run(self.p,self.r,self.policy)

        conflict=copy.deepcopy(previous)
        conflict["multi_asset_leadership_latest"][0]["rank"]+=1
        conflict["availability_receipt"]["snapshot_sha256"]=digest({k:v for k,v in conflict.items() if k!="availability_receipt"})
        self.policy["reviewed_pins"]["history_availability"].append(digest(conflict["availability_receipt"]))
        self.policy["reviewed_pins"]["history"].append(digest(conflict))
        for snapshots in ([previous,previous],[previous,conflict],[conflict,previous]):
            with self.subTest(history_order=[digest(s) for s in snapshots]):
                self.p["history"]=snapshots
                with self.assertRaisesRegex(ContractError,"duplicate_history_session"):
                    run(self.p,self.r,self.policy)

    def test_impossible_historical_ranks_are_rejected_even_when_pinned(self):
        current=run(self.p,self.r,self.policy)
        old_session=list(SESSIONS)[-6];close=SESSIONS[old_session];then=(close+timedelta(hours=1)).isoformat()
        for ranks in ([1,1,3],[1.5,2,3],[True,2,3],[0,2,3],[1,2,5]):
            with self.subTest(ranks=ranks):
                old_rows=[{"asset_id":r["asset_id"],"as_of":old_session,"latest_session":old_session,"rank":rank,"RS_composite":.1} for r,rank in zip(current["multi_asset_leadership_latest"],ranks)]
                previous={"as_of":old_session,"computed_at":then,"registry_sha256":digest(self.r),"multi_asset_leadership_latest":old_rows}
                receipt={**meta("CANONICAL_HISTORY"),"observed_at":close.isoformat(),"available_at":then,"evidence_kind":"PIT_ARCHIVE","snapshot_sha256":digest(previous)}
                previous["availability_receipt"]=receipt
                self.policy["reviewed_pins"]["history_availability"].append(digest(receipt))
                self.policy["reviewed_pins"]["history"].append(digest(previous));self.p["history"]=[previous]
                with self.assertRaisesRegex(ContractError,"invalid_history_ranks"):
                    run(self.p,self.r,self.policy)

    def test_event_reprints_never_multiply_score(self):
        assets={a["asset_id"]:a for a in self.r["assets"]}
        event=dict(**meta("CANONICAL_NEWS"),event_id="EVENT:1",published_at=CUTOFF,event_type="MINE_OUTAGE",confidence=.9,materiality=.8,confirmed=True,thesis_effect="REVIEW_NEGATIVE",estimated_duration="2_WEEKS",asset_ids=[],commodity_ids=["COPPER"],theme_ids=[],duplicate_cluster="OUTAGE:1")
        other={**event,"event_id":"EVENT:2"}
        events=event_memory([event,other],assets,CUTOFF,self.policy)
        self.assertEqual(len(events),1);self.assertEqual(events[0]["source_count"],1)
        self.assertEqual(events[0]["affected_asset_ids"],["US:FCX"])
        self.assertIsNone(events[0]["score_change"])
        self.assertEqual(events[0]["available_at"],CUTOFF)
        self.assertEqual(len(events[0]["evidence"]),2)

    def test_news_future_time_rejected(self):
        event=dict(**meta("CANONICAL_NEWS"),event_id="EVENT:1",published_at="2027-01-01T00:00:00Z")
        with self.assertRaises(ContractError):event_memory([event],{},CUTOFF,self.policy)

    def test_later_event_attributes_are_not_available_at_first_seen(self):
        assets={a["asset_id"]:a for a in self.r["assets"]}
        first=dict(**meta("CANONICAL_NEWS"),event_id="EVENT:1",published_at="2026-09-18T21:00:00Z",event_type="MINE_OUTAGE",confidence=.5,materiality=.4,confirmed=False,thesis_effect="REVIEW_UNKNOWN",estimated_duration="UNKNOWN",asset_ids=[],commodity_ids=[],theme_ids=[],duplicate_cluster="OUTAGE:1")
        first["available_at"]="2026-09-18T21:00:00Z"
        later={**first,"event_id":"EVENT:2","available_at":CUTOFF,"confirmed":True,"commodity_ids":["COPPER"]}
        merged=event_memory([later,first],assets,CUTOFF,self.policy)[0]
        self.assertEqual(merged["first_seen"],first["available_at"])
        self.assertEqual(merged["available_at"],CUTOFF)
        self.assertTrue(merged["confirmed"])
        self.assertEqual(merged["affected_asset_ids"],["US:FCX"])


class ExposureAndPublication(unittest.TestCase):
    def holdings_fixture(self):
        p,r,policy=fixture()
        assets={a["asset_id"]:a for a in r["assets"]}
        assets["US:URNM"]={**assets["US:CCJ"],"asset_id":"US:URNM","vehicle_type":"EQUITY_ETF"}
        raw=dict(**meta("ISSUER_HOLDINGS"),fund_id="US:URNM",source_id="ISSUER_HOLDINGS",portfolio_scope="FULL_PORTFOLIO",coverage_kind="FULL",weight_unit="FRACTION",holdings_as_of=list(SESSIONS)[-1],expected_unique_rows=2,rows=[{"security_id":"US:CCJ","instrument":"COMMON","identity_verified":True,"weight":.3},{"security_id":"US:FCX","instrument":"COMMON","identity_verified":True,"weight":.7}])
        policy["reviewed_pins"]["holdings"]=[digest(raw)]
        return assets,raw,policy

    def test_direct_and_etf_exposure_added_exactly_once(self):
        assets,raw,policy=self.holdings_fixture()
        out=lookthrough({"US:URNM":.2,"US:CCJ":.1},assets,{"US:URNM":raw},CUTOFF,policy)
        self.assertAlmostEqual(out["security_exposure"]["US:CCJ"],.16)
        self.assertAlmostEqual(sum(out["security_exposure"].values()),.3)

    def test_partial_and_stale_holdings_block(self):
        assets,raw,policy=self.holdings_fixture()
        for field,value in [("coverage_kind","TOP_ONLY"),("holdings_as_of","2026-07-01")]:
            altered={**raw,field:value};policy["reviewed_pins"]["holdings"].append(digest(altered))
            with self.assertRaises(ContractError):lookthrough({"US:URNM":.2},assets,{"US:URNM":altered},CUTOFF,policy)

    def test_missing_holdings_does_not_hide_risk(self):
        assets,raw,policy=self.holdings_fixture()
        with self.assertRaises(ContractError):lookthrough({"US:URNM":.2},assets,{},CUTOFF,policy)

    def test_normalized_holdings_future_publication_and_validation_block(self):
        assets,raw,policy=self.holdings_fixture()
        for field in ("published_at","validated_at"):
            with self.subTest(field=field):
                altered={**raw,field:"2026-09-20T00:00:00Z"}
                policy["reviewed_pins"]["holdings"].append(digest(altered))
                with self.assertRaisesRegex(ContractError,"future_normalized_holdings"):
                    lookthrough({"US:URNM":.2},assets,{"US:URNM":altered},CUTOFF,policy)

    def test_carried_etf_vehicle_cap_applies_even_when_leaves_are_below_cap(self):
        assets,raw,policy=self.holdings_fixture()
        p,r,_=fixture();riskrow=risk(p,r,policy)
        row=dict(asset_id="US:URNM",portfolio_status="HOLD",expected_alpha_12m=.3,liquidity_pass=True,RS20_change_5d=-.1,RS60_change_5d=-.1,RS120=.1,RS240=.1,signal_confidence=.8,thesis_confidence=.8,expected_drawdown=.2,daily_log_returns=[math.sin(i) for i in range(60)])
        proposal=propose([row],assets,riskrow,{"US:URNM":raw},CUTOFF,policy,feature_identity(p,r),{"US:URNM":.14})
        self.assertAlmostEqual(proposal["proposed_weights"]["US:URNM"],.1)
        self.assertAlmostEqual(proposal["exposure"]["security_exposure"]["US:FCX"],.07)
        self.assertEqual(proposal["reduction_basis"],"REVIEWED_RISK_CEILINGS_ONLY")

    def test_etf_cycle_rejected(self):
        assets,raw,policy=self.holdings_fixture()
        raw["rows"]=[{"security_id":"US:URNM","instrument":"ETF","identity_verified":True,"weight":1.0}]
        raw["expected_unique_rows"]=1;policy["reviewed_pins"]["holdings"]=[digest(raw)]
        with self.assertRaisesRegex(ContractError,"cycle"):lookthrough({"US:URNM":.2},assets,{"US:URNM":raw},CUTOFF,policy)

    def test_failed_attempt_preserves_previous_bytes_and_revokes_read(self):
        p,r,policy=reviewed(*fixture());risk(p,r,policy)
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);publish(p,r,policy,out,"one",CODE_SHA)
            saved=(out/"last_success.json").read_bytes();result=(out/"attempts/one/result.json").read_bytes()
            bad=copy.deepcopy(p);bad["schema"]="wrong"
            with self.assertRaises(ContractError):publish(bad,r,policy,out,"two",CODE_SHA)
            self.assertEqual((out/"last_success.json").read_bytes(),saved)
            self.assertEqual((out/"attempts/one/result.json").read_bytes(),result)
            with self.assertRaises(ContractError):read_latest(out)

    def test_model_publication_opt_in_does_not_promote_legacy_or_missing_model(self):
        p,r,policy=reviewed(*fixture());risk(p,r,policy)
        with tempfile.TemporaryDirectory() as temp, patch(
                'tools.run_multi_asset_leadership.verified_source_hashes',return_value={'synthetic-code':'a'*64}):
            out=Path(temp)
            publish(p,r,policy,out,'normal-proposal',CODE_SHA)
            original=(out/'attempts/normal-proposal/receipt.json').read_bytes()
            self.assertNotIn('model_allocation_ref',load_json(original))
            with self.assertRaisesRegex(ContractError,'model_publication_current_research_blocked'):
                publish(p,r,policy,out,'not-model',CODE_SHA,
                    model_publication=dict(candidate_receipt={},owner_decision={}))
            self.assertEqual((out/'attempts/normal-proposal/receipt.json').read_bytes(),original)
            self.assertEqual(load_json((out/'latest_attempt.json').read_bytes())['status'],'BLOCKED')
            with self.assertRaisesRegex(ContractError,'not_ready'):read_latest(out,consumed_at=CUTOFF)
            unknown=copy.deepcopy(p)
            unknown.update(position_book_kind='MODEL',model_identity={'model_id':'UNACCEPTED'})
            with self.assertRaisesRegex(ContractError,'current_model_incumbents_required'):
                publish(unknown,r,policy,out,'unknown-model',CODE_SHA,
                    model_publication=dict(candidate_receipt={},owner_decision={}))
            self.assertEqual((out/'attempts/normal-proposal/receipt.json').read_bytes(),original)

    def test_model_physical_source_pair_rejects_unbacked_rehash_and_latest_swap(self):
        from tools import run_multi_asset_leadership as publisher
        from research.multi_asset_v1.contracts import stamp
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);expiry='2026-09-20T10:00:00+00:00'
            observed='2026-09-19T10:00:03+00:00';cutoff=stamp('2026-09-19T10:01:00+00:00')
            def put(name,value):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('xb') as handle:handle.write(encoded(value))
                return dict(path=name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    observed_at=observed,available_at=observed,collected_at=observed,expires_at=expiry,status='VERIFIED')
            context=put('context.json',dict(decision_time=CUTOFF))
            packet=dict(task_key='a'*64,identity=dict(code_sha=CODE_SHA),inputs=dict(portfolio_context=context))
            result=dict(as_of=list(SESSIONS)[-1],computed_at=CUTOFF,global_ranking_ready=True,
                code_identity_verified=True,code_sha=CODE_SHA,proposal=dict(status='RESEARCH_PROPOSAL'),
                a3_reference_coverage=dict(current_review=dict(context_sha256=context['sha256'],task_keys=dict(A5='a'*64))))
            result_ref=put('source/attempts/one/result.json',result)
            receipt=dict(attempt_id='one',as_of=result['as_of'],global_ranking_ready=True,consumable=True,
                         result_sha256=result_ref['sha256'])
            receipt_ref=put('source/attempts/one/receipt.json',receipt)
            (root/'source/latest_attempt.json').write_bytes(encoded(receipt))
            candidate=dict(proposal_receipt=receipt_ref,proposal_result=result_ref,portfolio_context=context,
                proposal_receipt_sha256=receipt_ref['sha256'],proposal_result_sha256=result_ref['sha256'],
                publication_read_at=observed,publication_clock_scope='PREPARE_READ_OBSERVATION_NOT_ORIGINAL_COLLECTION_OR_PUBLICATION',
                state=dict(expires_at=expiry))
            selection=dict(proposal_receipt_sha256=receipt_ref['sha256'],selected_at='2026-09-19T10:00:02+00:00')
            original=dict(available_at='2026-09-19T10:00:01+00:00')
            def check(value,decision=selection,source_packet=packet):
                read,_=publisher._model_originals(root,cutoff,cutoff)
                return publisher._model_candidate_source(value,decision,read,source_packet,original,
                    candidate_observed_at='2026-09-19T10:00:04+00:00')
            self.assertEqual(len(check(candidate)),3)  # byte provenance only, no MODEL admission
            absent=copy.deepcopy(candidate);absent.pop('proposal_result')
            with self.assertRaisesRegex(ContractError,'model_source_refs_required'):check(absent)
            missing=copy.deepcopy(candidate);missing['proposal_result']['path']='missing.json'
            with self.assertRaises(OSError):check(missing)
            changed=copy.deepcopy(result);changed['code_sha']='b'*40
            replaced=copy.deepcopy(candidate);replaced['proposal_result']=put('rehashed_result.json',changed)
            replaced['proposal_result_sha256']=replaced['proposal_result']['sha256']
            with self.assertRaisesRegex(ContractError,'model_original_publication_pair'):check(replaced)
            forged=copy.deepcopy(candidate);forged['proposal_receipt_sha256']='f'*64
            forged_owner={**selection,'proposal_receipt_sha256':'f'*64}
            with self.assertRaisesRegex(ContractError,'model_original_publication_pair'):check(forged,forged_owner)
            wrong_packet=copy.deepcopy(packet);wrong_packet['task_key']='b'*64
            with self.assertRaisesRegex(ContractError,'model_published_a5_origin_mismatch'):check(candidate,source_packet=wrong_packet)
            alias=copy.deepcopy(candidate);alias['portfolio_context']=put('alias_context.json',dict(decision_time=CUTOFF))
            with self.assertRaisesRegex(ContractError,'model_published_a5_origin_mismatch'):check(alias)
            def swap_latest(*args,**kwargs):
                (root/'source/latest_attempt.json').write_bytes(encoded({**receipt,'attempt_id':'other'}))
                return result
            with patch.object(publisher,'read_latest',side_effect=swap_latest):
                with self.assertRaisesRegex(ContractError,'model_original_publication_changed'):
                    prepare_model_snapshot(root/'source',root/'candidate',proposal_receipt_sha256=receipt_ref['sha256'],
                        owner_decision={},portfolio_context={},review_root=root,policy={},now=cutoff.isoformat())
            self.assertFalse((root/'candidate').exists())

    def test_result_tampering_rejected(self):
        p,r,policy=reviewed(*fixture());risk(p,r,policy)
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);publish(p,r,policy,out,"one",CODE_SHA)
            (out/"attempts/one/result.json").write_text('{}')
            with self.assertRaisesRegex(ContractError,"tampered"):read_latest(out)

    def test_complete_rank_with_missing_or_invalid_risk_is_not_consumable(self):
        p,r,policy=reviewed(*fixture());risk(p,r,policy)
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);publish(p,r,policy,out,"good",CODE_SHA)
            self.assertEqual(read_latest(out,consumed_at=CUTOFF)["proposal"]["status"],"RESEARCH_PROPOSAL")
            saved=(out/"last_success.json").read_bytes()
            for mode in ("missing","invalid"):
                with self.subTest(mode=mode):
                    bad=copy.deepcopy(p)
                    if mode=="missing":bad.pop("risk")
                    else:bad["risk"]["max_gross"]=.9
                    result=publish(bad,r,policy,out,mode,CODE_SHA)
                    self.assertTrue(result["global_ranking_ready"])
                    self.assertEqual(result["proposal"]["status"],"BLOCKED")
                    self.assertEqual((out/"last_success.json").read_bytes(),saved)
                    with self.assertRaisesRegex(ContractError,"not_ready"):read_latest(out)
                    for name,obj in (("input",bad),("registry",r),("policy",policy)):
                        (out/(name+".json")).write_bytes(encoded(obj))
                    proc=subprocess.run([sys.executable,str(ROOT/"tools/run_multi_asset_leadership.py"),"--input",str(out/"input.json"),"--expected-input-sha256",hashlib.sha256(encoded(bad)).hexdigest(),"--registry",str(out/"registry.json"),"--policy",str(out/"policy.json"),"--output-dir",str(out),"--attempt-id",mode+"-cli"]+configuration_args(out),capture_output=True,text=True)
                    self.assertEqual(proc.returncode,2,proc.stdout+proc.stderr)
                    self.assertEqual((out/"last_success.json").read_bytes(),saved)

    def test_cli_missing_input_revokes_prior_success(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);(out/"latest_attempt.json").write_text('{"global_ranking_ready":true}')
            proc=subprocess.run([sys.executable,str(ROOT/"tools/run_multi_asset_leadership.py"),"--input",str(out/"missing.json"),"--output-dir",str(out),"--attempt-id","missing"],capture_output=True,text=True)
            self.assertEqual(proc.returncode,2)
            self.assertEqual(json.loads((out/"latest_attempt.json").read_bytes())["status"],"BLOCKED")

    def test_successful_old_attempt_cannot_be_read_as_current(self):
        p,r,policy=reviewed(*fixture());risk(p,r,policy)
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);publish(p,r,policy,out,"historical",CODE_SHA)
            self.assertEqual(read_latest(out,consumed_at=CUTOFF)["as_of"],list(SESSIONS)[-1])
            with self.assertRaisesRegex(ContractError,"latest_session_stale"):
                read_latest(out,consumed_at="2026-10-01T22:00:00Z")
            with self.assertRaisesRegex(ContractError,"latest_decision_in_future"):
                read_latest(out,consumed_at="2026-09-18T22:00:00Z")

    def test_cli_retains_noncanonical_authorized_input_byte_hash(self):
        p,r,policy=reviewed(*fixture());risk(p,r,policy)
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)
            for name,obj in (("input",p),("registry",r),("policy",policy)):
                (out/(name+".json")).write_text(json.dumps(obj,indent=2))
            authorized=hashlib.sha256((out/"input.json").read_bytes()).hexdigest()
            self.assertNotEqual(authorized,digest(p))
            proc=subprocess.run([sys.executable,str(ROOT/"tools/run_multi_asset_leadership.py"),"--input",str(out/"input.json"),"--expected-input-sha256",authorized,"--registry",str(out/"registry.json"),"--policy",str(out/"policy.json"),"--output-dir",str(out),"--attempt-id","pretty"]+configuration_args(out),capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            receipt=json.loads((out/"latest_attempt.json").read_bytes())
            self.assertEqual(receipt["input_sha256"],authorized)
            self.assertEqual(receipt["canonical_payload_sha256"],digest(p))

    def test_custom_configuration_cannot_approve_itself(self):
        with tempfile.TemporaryDirectory() as temp:
            for name in ("policy","registry"):
                with self.subTest(name=name):
                    path=Path(temp)/(name+".json");raw=b'{"caller_created":true}\n';path.write_bytes(raw)
                    repository_path="docs/multi_asset_"+name+"_v1.json"
                    with self.assertRaisesRegex(ContractError,"requires_external_hash"):
                        configuration_bytes(path,None,repository_path)
                    with self.assertRaisesRegex(ContractError,"configuration_hash_mismatch"):
                        configuration_bytes(path,"0"*64,repository_path)
                    self.assertEqual(configuration_bytes(path,hashlib.sha256(raw).hexdigest(),repository_path),raw)

    def test_dirty_source_revokes_publication_and_latest_consumption(self):
        p,r,policy=reviewed(*fixture());risk(p,r,policy)
        source=ROOT/"research/multi_asset_v1/prices.py"
        actual_read=Path.read_bytes
        def changed_read(path):
            raw=actual_read(path)
            return raw+b'\n# simulated uncommitted source change\n' if path==source else raw
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);publish(p,r,policy,out,"clean",CODE_SHA)
            saved=(out/"last_success.json").read_bytes()
            with patch.object(Path,"read_bytes",changed_read):
                with self.assertRaisesRegex(ContractError,"source_differs_from_claimed_commit"):
                    read_latest(out,consumed_at=CUTOFF)
                with self.assertRaisesRegex(ContractError,"source_differs_from_claimed_commit"):
                    publish(p,r,policy,out,"dirty",CODE_SHA)
            self.assertEqual((out/"last_success.json").read_bytes(),saved)
            with self.assertRaisesRegex(ContractError,"not_ready"):read_latest(out,consumed_at=CUTOFF)

    def test_source_failure_receipts_reach_published_diagnostics(self):
        p,r,policy=fixture()
        receipt={"asset_id":"US:FCX","clock":"NYSE_CLOSE","status":"BLOCKED","reason":"provider_unavailable_or_schema"}
        p["collection_receipts"]=[{**receipt,"raw_response":"should-not-publish","url":"should-not-publish"}]
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);publish(p,r,policy,out,"diagnostics",CODE_SHA)
            result=json.loads((out/"attempts/diagnostics/result.json").read_bytes())
            self.assertEqual(result["collection_receipts"],[receipt])

    def test_parser_never_uses_close_when_adjusted_missing(self):
        _,r,_=fixture();a=r["assets"][0]
        close=list(SESSIONS.values())[-1]
        chart={"chart":{"error":None,"result":[{"meta":{"symbol":a["symbol"],"currency":"USD","instrumentType":"EQUITY","exchangeTimezoneName":"America/New_York"},"timestamp":[int(close.timestamp())],"indicators":{"quote":[{"close":[100],"volume":[10]}],"adjclose":[{"adjclose":[None]}]}}]}}
        self.assertEqual(parse_chart(encoded(chart),a,CUTOFF,SESSIONS),[])

    def test_workflow_capture_has_no_secret_or_pr_execution(self):
        text=(ROOT/".github/workflows/multi_asset_leadership_v1.yml").read_text()
        self.assertNotIn('secrets.',text)
        self.assertIn("github.event_name != 'pull_request'",text)
        self.assertIn("workflows: ['Run287 Daily Research Monitor']",text)
        self.assertNotIn("schedule:",text)
        for path in ("research/theme_etf_runtime_v1/**","r1000_legacy_input_guard.py","tools/macro_history_sources.py"):
            self.assertIn("- '"+path+"'",text.split("workflow_dispatch:")[0])

    def test_crypto_adapter_distinguishes_hour_volume_and_daily_volume(self):
        r=json.loads((ROOT/"docs/multi_asset_registry_v1.json").read_bytes())
        a=next(a for a in r["assets"] if a["symbol"]=="BTC-USD")
        end=int(list(SESSIONS.values())[-1].timestamp());start=end-3600
        raw=encoded([[start,90,110,95,100,42]])
        rows=candles(raw,a,CUTOFF,SESSIONS,"NYSE_CLOSE",start,end)
        self.assertEqual(rows[0]["price"],100)
        self.assertIsNone(rows[0]["volume"])
        self.assertEqual(rows[0]["source_bucket_volume"],42)
        self.assertEqual(rows[0]["unit"],"USD_PER_TOKEN")

    def test_crypto_adapter_rejects_incomplete_and_duplicate_bars(self):
        r=json.loads((ROOT/"docs/multi_asset_registry_v1.json").read_bytes())
        a=next(a for a in r["assets"] if a["symbol"]=="BTC-USD")
        end=int(list(SESSIONS.values())[-1].timestamp());start=end-3600
        for data in [[[start,90,110,95,100,42]]*2,[[start,101,110,95,100,42]]]:
            with self.assertRaises(ContractError):candles(encoded(data),a,CUTOFF,SESSIONS,"NYSE_CLOSE",start,end)

    def test_fred_spot_units_are_not_equity_price_units(self):
        from datetime import datetime,timezone
        today=datetime.now(timezone.utc).date().isoformat()
        def fetch(url):
            series='DHHNGSP' if 'DHHNGSP' in url else 'DCOILWTICO'
            return f'observation_date,{series}\n{today},2.0\n'.encode()
        with tempfile.TemporaryDirectory() as temp:
            rows,receipts=capture_spot_metrics(Path(temp),fetch)
        self.assertEqual({r['unit'] for r in rows},{'USD_PER_MMBTU','USD_PER_BARREL'})
        self.assertTrue(all(r['evidence_kind']=='FORWARD_CAPTURE' for r in rows))
        self.assertEqual(len(receipts),2)

    def test_missing_provider_never_gets_replaced_by_retained_quote(self):
        def fail(_):raise OSError('failure')
        with tempfile.TemporaryDirectory() as temp:rows,receipts=capture_spot_metrics(Path(temp),fail)
        self.assertEqual(rows,[])
        self.assertTrue(all(r['status']=='BLOCKED' for r in receipts))

    def test_crypto_fallback_is_utc_proxy_and_excludes_partial_day(self):
        from research.multi_asset_v1.contracts import stamp
        asset={'symbol':'BTC-USD','asset_id':'CRYPTO:BTC-USD'}
        end=int(stamp('2026-09-19T00:00:00Z').timestamp())
        raw=encoded({'chart':{'result':[{'meta':{'symbol':'BTC-USD','currency':'USD','instrumentType':'CRYPTOCURRENCY','exchangeTimezoneName':'UTC'},'timestamp':[end-86400,end], 'indicators':{'quote':[{'close':[100,110],'volume':[10,20]}]}}],'error':None}})
        rows=crypto_chart(raw,asset,CUTOFF)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['clock'],'UTC_DAY')
        self.assertEqual(rows[0]['return_basis'],'PROVIDER_ADJUSTED_CLOSE_PROXY')

    def test_crypto_fallback_requires_correct_identity_and_clock(self):
        asset={'symbol':'BTC-USD','asset_id':'CRYPTO:BTC-USD'}
        raw=encoded({'chart':{'result':[{'meta':{'symbol':'ETH-USD','currency':'USD','instrumentType':'CRYPTOCURRENCY','exchangeTimezoneName':'UTC'}}],'error':None}})
        with self.assertRaises(ContractError):crypto_chart(raw,asset,CUTOFF)


class FundamentalSources(unittest.TestCase):
    def setUp(self):
        from research.multi_asset_v1.fundamentals import gas_storage, network_metrics
        self.gas=gas_storage
        self.network=network_metrics
        self.collected="2026-09-20T08:00:00Z"
        self.gas_data={"release_name":"Weekly Natural Gas Storage Report","fuel_type":"natural gas",
            "process":"storage","periodicity":"weekly","current_week":"2026-09-11",
            "week_ago":"2026-09-04","release_date":"2026-Sep-17 00:00:00","5yr_avg":"5-year (2021-25) average",
            "series":[{"series_id":"png.nw2_epg0_swo_r48_bcf.w","source":"U.S. Energy Information Administration",
            "units":"billion cubic feet","unitsshort":"bcf","data":[["2026-09-11",3000],["2026-09-04",2950]],
            "calculated":{"5yr-avg":2500,"net_change":50},"revision_flag":["false","false"]}]}

    def cm(self,subject="btc",metric="HashRate",value="1000",date="2026-09-19"):
        return {"data":[{"asset":subject,"time":date+"T00:00:00.000000000Z",metric:value}]}

    def parse(self,data,subject="BTC",metric="HashRate"):
        return self.network(encoded(data),subject,metric,self.collected,"2026-09-13","2026-09-19")

    def test_storage_units_comparison_and_retrieval_availability(self):
        rows=self.gas(encoded(self.gas_data),self.collected)
        self.assertEqual([r['value'] for r in rows[:3]],[3000,2500,50])
        self.assertAlmostEqual(rows[3]['value'],.2)
        self.assertTrue(all(r['available_at']==self.collected and r['evidence_kind']=='FORWARD_CAPTURE' for r in rows))
        self.assertEqual(rows[0]['observed_at'],'2026-09-11T00:00:00Z')
        self.assertIsNone(rows[0]['currency'])

    def test_storage_does_not_sum_regional_and_total_rows(self):
        extra=copy.deepcopy(self.gas_data['series'][0]);extra['series_id']='regional'
        self.gas_data['series'].append(extra)
        self.assertEqual(self.gas(encoded(self.gas_data),self.collected)[0]['value'],3000)

    def test_storage_rejects_wrong_unit_identity_and_duplicates(self):
        for field,value in [('units','million cubic feet'),('source','unknown'),('series_id','regional')]:
            data=copy.deepcopy(self.gas_data);data['series'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ContractError):self.gas(encoded(data),self.collected)
        self.gas_data['series']*=2
        with self.assertRaises(ContractError):self.gas(encoded(self.gas_data),self.collected)

    def test_storage_rejects_missing_zero_inconsistent_comparison(self):
        for average,change in [(None,50),(0,50),(2500,90)]:
            data=copy.deepcopy(self.gas_data);data['series'][0]['calculated'].update({'5yr-avg':average,'net_change':change})
            with self.subTest(average=average,change=change),self.assertRaises(ContractError):self.gas(encoded(data),self.collected)

    def test_storage_stale_and_future_release_block(self):
        for collected in ['2026-09-16T12:00:00Z','2026-09-27T12:00:00Z']:
            with self.subTest(collected=collected),self.assertRaises(ContractError):self.gas(encoded(self.gas_data),collected)

    def test_storage_preserves_revision_without_claiming_pit(self):
        self.gas_data['series'][0]['revision_flag'][0]='true'
        row=self.gas(encoded(self.gas_data),self.collected)[0]
        self.assertEqual(row['source_revision_flags'][0],'true')
        self.assertEqual(row['evidence_kind'],'FORWARD_CAPTURE')

    def test_eia_redirect_only_allows_same_host_fixed_document(self):
        from research.multi_asset_v1.fundamentals import eia_url
        self.assertEqual(eia_url('https://ir.eia.gov/secure/ngs/wngsr.json?Signature=test'),
                         'https://ir.eia.gov/secure/ngs/wngsr.json?Signature=test')
        for url in ['http://ir.eia.gov/ngs/wngsr.json','https://evil.test/ngs/wngsr.json',
                    'https://ir.eia.gov@evil.test/ngs/wngsr.json','https://ir.eia.gov/other',
                    'https://ir.eia.gov:443/ngs/wngsr.json','https://ir.eia.gov/ngs/wngsr.json#bad']:
            with self.subTest(url=url),self.assertRaises(ContractError):eia_url(url)

    def test_network_hashrate_ths_to_hs(self):
        row=self.parse(self.cm())[0]
        self.assertEqual(row['value'],1e15)
        self.assertEqual(row['unit'],'HASH_PER_SECOND')
        self.assertEqual(row['observed_at'],'2026-09-20T00:00:00+00:00')
        self.assertEqual(row['available_at'],self.collected)

    def test_network_native_fees_keep_token_currency(self):
        row=self.parse(self.cm('eth','FeeTotNtv','12.5'),'ETH','FeeTotNtv')[0]
        self.assertEqual((row['value'],row['unit'],row['currency']),(12.5,'TOKEN','ETH'))

    def test_network_missing_latest_not_filled_with_old_value(self):
        data=self.cm(value=None)
        data['data']+=self.cm(value='9999',date='2026-09-18')['data']
        row=self.parse(data)[0]
        self.assertIsNone(row['value'])
        self.assertEqual(row['data_quality'],'MISSING')

    def test_network_rejects_partial_pagination(self):
        data=self.cm();data['next_page_token']='more'
        with self.assertRaises(ContractError):self.parse(data)

    def test_network_rejects_wrong_asset_duplicate_or_future_dates(self):
        for data in [self.cm(subject='eth'),self.cm(date='2026-09-20'),{'data':self.cm()['data']*2}]:
            with self.subTest(data=data),self.assertRaises(ContractError):self.parse(data)

    def test_network_rejects_nonfinite_negative_numeric_coercion(self):
        for value in ['NaN','Infinity','-1',True,1000,'1e999',' 10']:
            with self.subTest(value=value),self.assertRaises(ContractError):self.parse(self.cm(value=value))

    def test_network_rejects_fractional_counts(self):
        with self.assertRaises(ContractError):self.parse(self.cm('eth','TxCnt','1.1'),'ETH','TxCnt')

    def test_network_no_eth_mining_metric(self):
        from research.multi_asset_v1.fundamentals import NETWORK
        self.assertNotIn('HashRate',NETWORK['ETH'])

    def test_network_stale_and_token_currency_admission(self):
        from research.multi_asset_v1.runtime import metric_rows
        row=self.parse(self.cm('eth','FeeTotNtv','1'),'ETH','FeeTotNtv')[0]
        policy=json.loads((ROOT/'docs/multi_asset_policy_v1.json').read_bytes())
        self.assertEqual(metric_rows([row],self.collected,policy)[0]['admission'],'OBSERVED')
        self.assertEqual(metric_rows([row],'2026-09-25T12:00:00Z',policy)[0]['admission'],'BLOCKED')
        for currency in [None,'USD','BTC']:
            row['currency']=currency
            self.assertEqual(metric_rows([row],self.collected,policy)[0]['reason'],'metric_token_currency')

    def test_collectors_preserve_raw_bytes_and_isolate_one_failure(self):
        from research.multi_asset_v1.fundamentals import capture_fundamentals
        from research.multi_asset_v1.contracts import stamp
        from urllib.parse import urlsplit,parse_qs
        def fetch(url):
            q=parse_qs(urlsplit(url).query);subject=q['assets'][0];metric=q['metrics'][0]
            if metric=='CapMVRVCur':raise ValueError('secret-bearing provider exception')
            return encoded(self.cm(subject,metric,'10'))
        with tempfile.TemporaryDirectory() as tmp:
            rows,receipts=capture_fundamentals(Path(tmp),fetch,lambda _:encoded(self.gas_data),lambda:stamp(self.collected))
            self.assertEqual(len(rows),10)
            self.assertEqual(len(receipts),8)
            self.assertEqual(sum(r['status']=='BLOCKED' for r in receipts),1)
            self.assertNotIn('secret-bearing',json.dumps(receipts))
            for r in rows:
                raw=(Path(tmp)/'raw'/r['raw_sha256']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),r['raw_sha256'])

    def test_capture_parser_failure_preserves_raw_receipt(self):
        from research.multi_asset_v1.fundamentals import capture_fundamentals
        from research.multi_asset_v1.contracts import stamp
        with tempfile.TemporaryDirectory() as tmp:
            rows,receipts=capture_fundamentals(Path(tmp),lambda _:b'{}',lambda _:b'{}',lambda:stamp(self.collected))
            self.assertEqual(rows,[])
            self.assertTrue(all(r['status']=='BLOCKED' and 'raw_sha256' in r for r in receipts))
            self.assertTrue((Path(tmp)/'raw'/hashlib.sha256(b'{}').hexdigest()).is_file())

    def test_runtime_keeps_network_metrics_separate_from_score(self):
        from research.multi_asset_v1.runtime import render
        p,r,policy=fixture();p['as_of']=self.collected
        registry=json.loads((ROOT/'docs/multi_asset_registry_v1.json').read_bytes())
        r['assets'] += [a for a in registry['assets'] if a['asset_class']=='CRYPTO']
        p['metrics']=self.parse(self.cm('eth','FeeTotNtv','12.5'),'ETH','FeeTotNtv')
        result=run(p,r,policy)
        eth=next(a for a in result['crypto_market_latest'] if a['asset_id']=='CRYPTO:ETH-USD')
        self.assertEqual(eth['metrics'][0]['value'],12.5)
        self.assertIsNone(eth['network_score'])
        self.assertFalse(result['global_ranking_ready'])
        self.assertIn('Commodity and network observations',render(result))

    def test_workflow_archives_capture_input_and_raw_objects(self):
        workflow=(ROOT/'.github/workflows/multi_asset_leadership_v1.yml').read_text()
        self.assertIn('outputs/multi_asset/captures/',workflow)

    def complete_capture_fixture(self):
        from research.multi_asset_v1.fundamentals import capture_fundamentals
        from research.multi_asset_v1.contracts import stamp
        from urllib.parse import urlsplit,parse_qs
        def fetch(url):
            q=parse_qs(urlsplit(url).query)
            return encoded(self.cm(q['assets'][0],q['metrics'][0],'10',q['end_time'][0]))
        with tempfile.TemporaryDirectory() as tmp:
            rows,receipts=capture_fundamentals(Path(tmp),fetch,lambda _:encoded(self.gas_data),lambda:stamp(CUTOFF))
        p,r,policy=fixture();p.update(metrics=rows,collection_receipts=receipts)
        return p,r,policy

    def test_complete_fundamental_receipts_match_all_admitted_rows(self):
        p,r,policy=self.complete_capture_fixture();reviewed(p,r,policy);risk(p,r,policy)
        result=run(p,r,policy)
        self.assertEqual(len(result['metrics']),11)
        self.assertEqual(result['fundamental_collection_blockers'],[])
        self.assertTrue(result['global_ranking_ready'])
        self.assertEqual(result['proposal']['status'],'RESEARCH_PROPOSAL')

    def test_success_receipt_contradictions_block_reviewed_sparse_er(self):
        for mutation in ['missing_gas','missing_network','wrong_count','wrong_hash','wrong_series',
                         'duplicate_receipt','missing_receipt','unclaimed_metric','all_metrics_removed']:
            p,r,policy=self.complete_capture_fixture()
            if mutation=='missing_gas':p['metrics'].pop(0)
            elif mutation=='missing_network':p['metrics'].pop()
            elif mutation=='wrong_count':p['collection_receipts'][0]['rows']=3
            elif mutation=='wrong_hash':p['collection_receipts'][0]['raw_sha256']='f'*64
            elif mutation=='wrong_series':p['collection_receipts'][1]['series']='FeeTotNtv'
            elif mutation=='duplicate_receipt':p['collection_receipts'].append(copy.deepcopy(p['collection_receipts'][0]))
            elif mutation=='missing_receipt':p['collection_receipts'].pop()
            elif mutation=='unclaimed_metric':
                extra=copy.deepcopy(p['metrics'][-1]);extra['source_metric']='Other';extra['metric']='issuance';p['metrics'].append(extra)
            elif mutation=='all_metrics_removed':p['metrics']=[]
            reviewed(p,r,policy);risk(p,r,policy)
            with self.subTest(mutation=mutation):
                result=run(p,r,policy)
                self.assertTrue(result['fundamental_collection_blocked'])
                self.assertFalse(result['global_ranking_ready'])
                self.assertEqual(result['proposal']['status'],'BLOCKED')

    def test_fundamental_rows_without_receipts_cannot_authorize_er(self):
        p,r,policy=self.complete_capture_fixture();p['collection_receipts']=[]
        reviewed(p,r,policy)
        result=run(p,r,policy)
        self.assertTrue(result['fundamental_collection_blocked'])
        self.assertFalse(result['global_ranking_ready'])

    def test_failed_fundamental_receipt_blocks_even_reviewed_sparse_er(self):
        for status in ['BLOCKED','PARTIAL_MISSING']:
            p,r,policy=fixture()
            p['collection_receipts']=[{'source':'COINMETRICS_COMMUNITY','subject_id':'ETH',
                                      'series':'FeeTotNtv','status':status}]
            reviewed(p,r,policy);risk(p,r,policy)
            result=run(p,r,policy)
            self.assertTrue(result['fundamental_collection_blocked'])
            self.assertFalse(result['global_ranking_ready'])
            self.assertEqual(result['proposal']['status'],'BLOCKED')
            self.assertTrue(all('evaluation:fundamental_collection_incomplete' in x['blockers']
                                for x in result['multi_asset_leadership_latest']))

    def test_collection_receipts_bound_to_evaluator_feature_identity(self):
        p,r,policy=fixture();before=feature_identity(p,r)
        p['collection_receipts']=[{'source':'EIA_STORAGE','status':'BLOCKED'}]
        self.assertNotEqual(before,feature_identity(p,r))

    def test_malformed_metric_still_publishes_diagnostics(self):
        for missing in ['metric','unit','observed_at']:
            p,r,policy=fixture()
            row=dict(**meta('EIA'),subject_id='NATURAL_GAS',metric='inventory',unit='BCF',value=100)
            row.pop(missing);p['metrics']=[row]
            with self.subTest(missing=missing),tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)
                result=publish(p,r,policy,out,'invalid-metric',CODE_SHA)
                self.assertEqual(result['metrics'][0]['admission'],'BLOCKED')
                self.assertTrue((out/'attempts/invalid-metric/receipt.json').is_file())
                report=(out/'attempts/invalid-metric/daily_monitoring_report.md').read_text()
                self.assertIn('MISSING',report)


class A3OriginalInputs(unittest.TestCase):
    """Real A3 replay and runtime contracts over synthetic local evidence only."""
    def setUp(self):
        self.p,self.r,self.policy=fixture()
        self.p['requested_security_ids']=['US:FTI']
        reviewed(self.p,self.r,self.policy)
        risk(self.p,self.r,self.policy)
        self.original=next(e for e in self.p['evaluations'] if e['asset_id']=='US:FTI')
        self.original['issuer_id']='CIK:1'
        self.policy['reviewed_pins']['evaluation'].append(digest(self.original))
        self.p['evaluations']=[e for e in self.p['evaluations'] if e['asset_id']!='US:FTI']
        with patch.object(sys,'path',[str(ROOT/'tests'),str(ROOT/'research'),*sys.path]):
            import candidate_registry_v1_smoke as reference_fixture
        self.refs=reference_fixture.RegistryTests('runTest');self.refs.setUp()
        self.entry=self.refs.fixture(asset='US:FTI',issuer='CIK:1')
        self.packet=self.refs.read(self.entry['a3_packet_ref'])
        self.packet.update(as_of=CUTOFF,reviewed_at=CUTOFF)
        self.packet['thesis']['status']='POSITIVE'
        market_ref=self.packet['artifacts']['market_valuation']
        market=self.refs.read(market_ref)
        prices={s['session']:s for s in self.p['prices'] if s['asset_id']=='US:FTI'}
        benchmark={s['session']:s for s in self.p['prices'] if s['asset_id']=='US:SPY'}
        market['price']=prices[list(SESSIONS)[-1]]['price']
        for h in (20,60,120,240):
            end,start=list(SESSIONS)[-1],list(SESSIONS)[-1-h]
            ret=prices[end]['total_return_index']/prices[start]['total_return_index']-1
            bench=benchmark[end]['total_return_index']/benchmark[start]['total_return_index']-1
            market[f'return_{h}d']=ret;market[f'benchmark_return_{h}d']=bench
            market[f'rs_{h}d']=math.log1p(ret)-math.log1p(bench)
        self.market=market
        self.reseal()

    def reseal(self, *, include_er=True):
        from research.a3_candidate_packet_v1 import evaluate_packet
        def reference(kind,aid,value):
            ref=self.refs.put(aid,value,at=CUTOFF)
            return dict(kind=kind,**{k:v for k,v in ref.items()
                                   if k not in {'collected_at','expires_at'}},review_status='REVIEWED')
        self.packet['artifacts']['market_valuation']=reference('MARKET_VALUATION_SNAPSHOT','BIND:MKT',self.market)
        if include_er:
            self.packet['artifacts']['validated_er']=reference('VALIDATED_ER_EVALUATION','BIND:ER',self.original)
        else:self.packet['artifacts'].pop('validated_er',None)
        result=evaluate_packet(self.packet,CUTOFF,self.refs.resolve)
        self.entry['a3_packet_ref']=self.refs.put('BIND:PACKET',self.packet,at=CUTOFF)
        self.entry['a3_result_ref']=self.refs.put('BIND:RESULT',result,at=CUTOFF)
        self.p['a3_reference_entries']=[self.entry]

    def memory(self):
        from research.a2_research_intake_v1 import MemoryArtifacts
        return MemoryArtifacts({aid:raw for (aid,_),raw in self.refs.raw.items()})

    def execute(self):
        return run(self.p,self.r,self.policy,artifact_resolver=self.memory())

    def stock_review_inputs(self):
        """Exact synthetic full-base pin; the unreviewed member stays UNKNOWN."""
        self.policy['stock_cash_research']['enabled']=True
        self.p['base_equity_ids']=['US:FTI','US:UNMAPPED']
        self.p['base_universe_receipt']['asset_ids']=sorted(self.p['base_equity_ids'])
        self.policy['reviewed_pins']['base_universe'].append(digest(self.p['base_universe_receipt']))
        self.original['feature_sha256']=feature_identity(self.p,self.r)
        self.original['cost_assumptions']['commission_bps']=25
        self.original['portfolio_cost_basis']=dict(schema='reviewed-portfolio-cost-basis-v1',
            horizon='12_CALENDAR_MONTHS',kind='NET_REFERENCE_ROUND_TRIP',
            cost_assumptions_sha256=digest(self.original['cost_assumptions']),evidence_sha256='c'*64,
            reference_cost_bps_per_side=25,embedded_cost_fraction=.005,
            embedded_transaction_cost_fraction=.005,embedded_ongoing_cost_fraction=0,
            gross_expected_return=self.original['expected_return_12m']+.005)
        self.policy['reviewed_pins']['evaluation'].append(digest(self.original))
        raw=b'DATE,DGS3MO\n2026-09-17,3.0\n';sha=hashlib.sha256(raw).hexdigest()
        self.refs.raw[('CASH:SOURCE',sha)]=raw
        rr=self.p['risk'];rr.update(feature_sha256=feature_identity(self.p,self.r),max_security_weight=.2)
        rr['stock_cash_allocation']=dict(horizon='12_CALENDAR_MONTHS',events_sha256=digest([]),
            decision_asset_ids=['US:FTI'],evaluation_sha256_by_asset={'US:FTI':digest(self.original)},
            cash_carry=dict(**{**meta('FRED_ARCHIVE'),'raw_sha256':sha},metric='dgs3mo',unit='FRACTION',
                value=.03,observation_date='2026-09-17',original_ref=dict(artifact_id='CASH:SOURCE',sha256=sha,bytes=len(raw))),
            exception_reviews=[],exit_reviews=[])
        self.policy['reviewed_pins']['risk'].append(digest(rr))

    def current_review(self, prefix=None, *, stock=False):
        from tests.control_plane_agent_contract_smoke import ControlPlaneTests
        # Actual original evidence exists at 10:00; selection/review happens
        # afterwards, before this later decision. Never backdate QA clocks.
        self.p['as_of']='2026-09-19T10:10:00+00:00'
        reviewed(self.p,self.r,self.policy);risk(self.p,self.r,self.policy)
        self.original=next(e for e in self.p['evaluations'] if e['asset_id']=='US:FTI')
        self.original['issuer_id']='CIK:1'
        self.policy['reviewed_pins']['evaluation'].append(digest(self.original))
        self.p['evaluations']=[e for e in self.p['evaluations'] if e['asset_id']!='US:FTI']
        if stock:self.stock_review_inputs()
        self.reseal()
        case=ControlPlaneTests('runTest');case.setUp();self.addCleanup(case.doCleanups)
        if prefix is not None: case._artifact_prefix=prefix
        binding,graph,principals=case.current_review_case(self)
        self.p['current_a3_review']=binding
        self.policy['current_a3_review_profile']=dict(schema='current-a3-review-profile-v1',
            purpose='CURRENT_RESEARCH_FORWARD_ONLY',context_sha256=binding['portfolio_context']['sha256'],
            graph_sha256=binding['review_graph']['sha256'],binding_sha256=digest(binding),policy_base_sha256=digest(self.policy),
            feature_sha256=feature_identity(self.p,self.r),risk_sha256=digest(self.p['risk']),code_sha=CODE_SHA,
            available_at=case.at(-5.25),expires_at=case.at(30),principals=principals)
        return case,graph

    def test_model_snapshot_publisher_replays_owner_post_qa_and_current_admission(self):
        from tools import run_agent_board as board
        from tests.control_plane_agent_contract_smoke import ControlPlaneTests
        case,_=self.current_review(prefix='publisher_origin',stock=True)
        source_binding=copy.deepcopy(self.p['current_a3_review'])
        packet=copy.deepcopy(next(p for p in case.tasks() if p['agent']=='A5'))
        aid=self.p['requested_security_ids'][0]
        original_target=dict(status='PROPOSAL_ONLY',proposed_weights={aid:.2},
                             orders_generated=False,accepted_target_written=False)
        origin=copy.deepcopy(case.complete('A5',{'target_proposal':original_target}))
        selected=board.timestamp(origin['available_at'])+timedelta(seconds=1)
        prepared_at=case.now.isoformat()
        expiry=case.at(30)
        def put(name,value,at):
            path=case.root/'publisher_proof'/(name+'.json');path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as handle: handle.write(encoded(value))
            return dict(path=path.relative_to(case.root).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                observed_at=at,available_at=at,collected_at=at,expires_at=expiry,status='VERIFIED')
        packet_ref=put('a5_packet',packet,origin['available_at'])
        receipt_ref=put('a5_receipt',origin,origin['available_at'])
        identity=dict(model_id='SYNTHETIC:PUBLISHER',model_version='fixture-v1',model_code_sha=CODE_SHA,
            model_config_sha256='1'*64,model_recipe_sha256='2'*64,data_identity_sha256='3'*64,
            cost_context_sha256='4'*64)
        source_out=case.root/'proposal_source';candidate_out=case.root/'model_candidates'
        # Isolate only publisher Git-source attestation for this dirty synthetic
        # fixture. Current A3/ER/A4, original completion and MODEL QA verifiers
        # all execute their real implementations; no Source authority is claimed.
        synthetic_code={'synthetic-fixture-source': 'a'*64}
        with patch('tools.run_multi_asset_leadership.verified_source_hashes',return_value=synthetic_code):
            initial=publish(self.p,self.r,self.policy,source_out,'original',CODE_SHA,
                    artifact_resolver=self.memory(),review_root=case.root)
            self.assertFalse(read_latest(source_out,consumed_at=prepared_at)['global_ranking_ready'])
            self.assertEqual(initial['proposal']['intent'],'NO_ENTRY_HOLD_CASH')
            self.assertEqual(initial['proposal']['cash'],1.0)
            self.assertEqual(initial['proposal']['proposed_weights'],{})
            self.assertTrue(any(r['asset_id']=='US:UNMAPPED' and r['expected_return_12m'] is None
                for r in initial['multi_asset_leadership_latest']))
            selected=max(board.timestamp(origin['available_at']),board.timestamp(self.p['as_of']))+timedelta(seconds=1)
            source_hash=hashlib.sha256((source_out/'latest_attempt.json').read_bytes()).hexdigest()
            selection=dict(schema_version='model-allocation-selection-v1',change_kind='SELECT_ALLOCATION',
                owner_principal='OWNER:FIXTURE',selected_at=selected.isoformat(),expires_at=expiry,
                reason='Explicit comparison allocation .15; preserve original .20 proposal',
                proposal_receipt_sha256=source_hash,a5_packet=packet_ref,a5_receipt=receipt_ref,
                model_identity=identity,positions=[dict(asset_id=aid,weight=.15)],cash_weight=.85)
            # A second genuinely completed MODEL A5 is not the A5 named by
            # this immutable publication. Reuse the same evidence base while
            # issuing a different task identity; do not forge a failing receipt.
            request_a5=next(r for r in case.state['requests'] if r['agent']=='A5')
            saved_parameters=copy.deepcopy(request_a5['parameters'])
            saved_completed=copy.deepcopy(case.state['completed_tasks'])
            saved_prefix=case._artifact_prefix
            try:
                request_a5['parameters']['synthetic_unrelated_task']=True
                case.state['completed_tasks']=[r for r in case.state['completed_tasks'] if r['agent']!='A5']
                case._artifact_prefix='publisher_unrelated'
                alternate_packet=copy.deepcopy(next(p for p in case.tasks() if p['agent']=='A5'))
                alternate_receipt=copy.deepcopy(case.complete('A5',{'target_proposal':original_target}))
                alternate=copy.deepcopy(selection)
                alternate['a5_packet']=put('unrelated_packet',alternate_packet,alternate_receipt['available_at'])
                alternate['a5_receipt']=put('unrelated_receipt',alternate_receipt,alternate_receipt['available_at'])
                from tools import run_multi_asset_leadership as publisher
                read,_=publisher._model_originals(case.root,board.timestamp(prepared_at),board.timestamp(prepared_at))
                replayed,_,_=publisher._model_origin(alternate,read,board.timestamp(prepared_at))
                self.assertEqual(replayed['task_key'],alternate_packet['task_key'])
                self.assertNotEqual(replayed['task_key'],packet['task_key'])
                alternate_ref=put('unrelated_owner',alternate,selected.isoformat())
                with self.assertRaisesRegex(ContractError,'model_published_a5_origin_mismatch'):
                    prepare_model_snapshot(source_out,candidate_out,proposal_receipt_sha256=source_hash,
                        owner_decision=alternate_ref,portfolio_context=source_binding['portfolio_context'],
                        review_root=case.root,policy=self.policy,now=prepared_at)
                self.assertFalse(candidate_out.exists())
            finally:
                request_a5['parameters']=saved_parameters
                case.state['completed_tasks']=saved_completed
                case._artifact_prefix=saved_prefix
            owner_ref=put('owner_selection',selection,selected.isoformat())
            candidate=prepare_model_snapshot(source_out,candidate_out,proposal_receipt_sha256=source_hash,
                owner_decision=owner_ref,portfolio_context=source_binding['portfolio_context'],
                review_root=case.root,policy=self.policy,now=prepared_at)
            candidate_path=candidate_out/'attempts'/candidate['attempt_id']/'receipt.json'
            saved=candidate_path.read_bytes()
            repeated=prepare_model_snapshot(source_out,candidate_out,proposal_receipt_sha256=source_hash,
                owner_decision=owner_ref,portfolio_context=source_binding['portfolio_context'],
                review_root=case.root,policy=self.policy,now=prepared_at)
            self.assertEqual(repeated,candidate);self.assertEqual(candidate_path.read_bytes(),saved)
            self.assertFalse(candidate['consumable']);self.assertFalse(candidate['model_acceptance_issued'])
            state_bytes=(case.root/candidate['state']['path']).read_bytes()
            original_origin=publisher._model_origin
            latest_bytes=(source_out/'latest_attempt.json').read_bytes()
            def block_after_real_origin(*args,**kwargs):
                replay=original_origin(*args,**kwargs)
                (source_out/'latest_attempt.json').write_bytes(encoded(dict(status='BLOCKED',attempt_id='later')))
                return replay
            try:
                with patch.object(publisher,'_model_origin',side_effect=block_after_real_origin):
                    with self.assertRaisesRegex(ContractError,'model_original_publication_changed'):
                        prepare_model_snapshot(source_out,candidate_out,proposal_receipt_sha256=source_hash,
                            owner_decision=owner_ref,portfolio_context=source_binding['portfolio_context'],
                            review_root=case.root,policy=self.policy,now=prepared_at)
                self.assertEqual(candidate_path.read_bytes(),saved)
                self.assertEqual((case.root/candidate['state']['path']).read_bytes(),state_bytes)
            finally:
                # Restore only this isolated synthetic fixture's exact saved
                # bytes for subsequent cases, never a production latest status.
                (source_out/'latest_attempt.json').write_bytes(latest_bytes)
            candidate_ref=dict(path=candidate_path.relative_to(case.root).as_posix(),
                sha256=hashlib.sha256(saved).hexdigest(),observed_at=prepared_at,available_at=prepared_at,
                collected_at=prepared_at,expires_at=expiry,status='VERIFIED')
            state=load_json((case.root/candidate['state']['path']).read_bytes())
            self.assertEqual(state['positions'],[dict(asset_id=aid,weight=.15)])
            self.assertEqual(board.read_json(case.root/origin['outputs']['target_proposal']['path']),original_target)
            covered=dict(state=candidate['state'],target=origin['outputs']['target_proposal'],
                a5_packet=packet_ref,a5_receipt=receipt_ref,owner_decision=owner_ref,candidate_receipt=candidate_ref)
            covered.update(proposal_receipt=candidate['proposal_receipt'],proposal_result=candidate['proposal_result'])
            covered.update({'input:'+k:v for k,v in packet['inputs'].items()})
            inventory=copy.deepcopy(board.read_json(case.root/source_binding['portfolio_context']['path'])['artifact_inventory'])
            for key,ref in covered.items(): inventory['MODEL:publication:'+key]=ref
            for agent,dep in packet['dependency_outputs'].items():
                for role,ref in dep['outputs'].items(): inventory['MODEL:dependency:'+agent+':'+role]=ref
            case.now+=timedelta(minutes=10)
            case.state['as_of'],case.state['expires_at']=case.at(-5),case.at(40)
            bundle_ref=put('post_bundle',dict(schema_version='qa-review-bundle-v2',artifacts=covered),prepared_at)
            qa=next(r for r in case.state['requests'] if r['agent']=='A6');qa['inputs']['review_bundle']=bundle_ref
            case.state['completed_tasks']=[r for r in case.state['completed_tasks'] if r['agent']!='A6']
            post_packet=copy.deepcopy(next(p for p in case.tasks() if p['agent']=='A6'))
            case._artifact_prefix='publisher_post_qa'
            post_receipt=copy.deepcopy(case.complete('A6'))
            post_at=board.timestamp(post_receipt['available_at'])+timedelta(seconds=1)
            post_packet_ref=put('a6_packet',post_packet,post_at.isoformat())
            post_receipt_ref=put('a6_receipt',post_receipt,post_at.isoformat())
            for role,ref in post_receipt['outputs'].items(): inventory['MODEL:post:'+role]=ref
            inventory.update({'MODEL:bundle':bundle_ref,'MODEL:a6_packet':post_packet_ref,'MODEL:a6_receipt':post_receipt_ref})
            accepted=dict(schema_version='model-incumbents-acceptance-v1',book_kind='MODEL',
                state_role='ADMITTED_MODEL_ALLOCATION',current=True,model_identity=identity,as_of=state['as_of'],
                decision_time=state['decision_time'],expires_at=candidate['state']['expires_at'],
                positions=state['positions'],cash_weight=state['cash_weight'],positions_sha256=digest(state['positions']),
                producer_code_sha=packet['identity']['code_sha'],producer_config_hash=packet['identity']['config_hash'],
                principals=dict(A5='PRODUCER:MODEL',A6='REVIEWER:INDEPENDENT'),
                proofs=dict(state=candidate['state'],a5_packet=packet_ref,a5_receipt=receipt_ref,
                    a6_packet=post_packet_ref,a6_receipt=post_receipt_ref),
                observed_at=(post_at+timedelta(seconds=1)).isoformat(),available_at=(post_at+timedelta(seconds=2)).isoformat(),
                collected_at=(post_at+timedelta(seconds=3)).isoformat(),source='CANONICAL_BOOK',
                data_quality='OBSERVED',evidence_kind='FORWARD_CAPTURE',raw_sha256=candidate['state']['sha256'])
            accepted_ref=put('external_acceptance',accepted,(post_at+timedelta(seconds=4)).isoformat())
            inventory['MODEL:acceptance']=accepted_ref
            model_context=copy.deepcopy(board.read_json(case.root/source_binding['portfolio_context']['path']))
            model_context.update(artifact_inventory=inventory,
                model_state=dict(kind='INCUMBENTS',artifact=accepted_ref,model_identity=identity))
            self.p['as_of']='2026-09-19T10:30:00+00:00'
            reviewed(self.p,self.r,self.policy);risk(self.p,self.r,self.policy)
            self.original=next(e for e in self.p['evaluations'] if e['asset_id']=='US:FTI')
            self.original['issuer_id']='CIK:1';self.policy['reviewed_pins']['evaluation'].append(digest(self.original))
            self.p['evaluations']=[e for e in self.p['evaluations'] if e['asset_id']!='US:FTI'];self.reseal()
            self.stock_review_inputs();self.reseal()
            self.policy.pop('current_a3_review_profile',None)
            self.policy['reviewed_pins']['positions']=[digest(accepted)]  # External fixture OWNER, not publisher code.
            current=ControlPlaneTests('runTest');current.setUp();self.addCleanup(current.doCleanups)
            binding,_,principals=current.current_review_case(self,model_binding=(model_context,case.root),model_policy=self.policy)
            self.p.update(current_a3_review=binding,position_book_kind='MODEL',model_identity=identity)
            self.policy['current_a3_review_profile']=dict(schema='current-a3-review-profile-v1',
                purpose='CURRENT_RESEARCH_FORWARD_ONLY',context_sha256=binding['portfolio_context']['sha256'],
                graph_sha256=binding['review_graph']['sha256'],binding_sha256=digest(binding),
                policy_base_sha256=digest(self.policy),feature_sha256=feature_identity(self.p,self.r),
                risk_sha256=digest(self.p['risk']),code_sha=CODE_SHA,available_at=current.at(-5.25),
                expires_at=min(current.at(30),binding['review_graph']['expires_at']),principals=principals)
            request=dict(candidate_receipt=candidate_ref,owner_decision=owner_ref)
            out=current.root/'published'
            source_packet=copy.deepcopy(next(p for p in current.tasks() if p['agent']=='A5'))
            current._artifact_prefix='publisher_no_change_source'
            source_receipt=copy.deepcopy(current.complete('A5',{'target_proposal':original_target}))
            current_source_refs={}
            for role,value in (('a5_packet',source_packet),('a5_receipt',source_receipt)):
                ref=current.artifact('current_'+role);current.set_payload(ref,value)
                ref['observed_at']=ref['available_at']=ref['collected_at']=source_receipt['available_at']
                current_source_refs[role]=ref
            result=publish(self.p,self.r,self.policy,out,'accepted-once',CODE_SHA,
                artifact_resolver=self.memory(),review_root=current.root,model_publication=request)
            receipt=load_json((out/'attempts/accepted-once/receipt.json').read_bytes())
            self.assertEqual(receipt['model_allocation_ref']['artifact'],accepted_ref)
            self.assertEqual(result['model_allocation_publication']['model_identity'],identity)
            self.assertFalse(receipt['model_allocation_ref']['accepted_model_state_written'])
            self.assertEqual(read_latest(out,consumed_at=self.p['as_of'])['proposal_context']['book_kind'],'MODEL')
            original_bytes=(out/'attempts/accepted-once/receipt.json').read_bytes()
            # A NEW current A5 assessment may reaffirm the same allocation.
            # Its immutable parent and original QA are never restamped.
            no_change=copy.deepcopy(selection)
            no_change.update(change_kind='REAFFIRM_HOLD',proposal_receipt_sha256=hashlib.sha256(
                (out/'latest_attempt.json').read_bytes()).hexdigest(),
                selected_at=(board.timestamp(self.p['as_of'])+timedelta(seconds=1)).isoformat(),**current_source_refs)
            nc_path=current.root/'no_change_selection.json'
            with nc_path.open('xb') as handle: handle.write(encoded(no_change))
            nc_at=(board.timestamp(self.p['as_of'])+timedelta(seconds=2)).isoformat()
            nc_ref=dict(path=nc_path.relative_to(current.root).as_posix(),
                sha256=hashlib.sha256(nc_path.read_bytes()).hexdigest(),observed_at=no_change['selected_at'],
                available_at=no_change['selected_at'],collected_at=no_change['selected_at'],expires_at=expiry,status='VERIFIED')
            nc=prepare_model_snapshot(out,current.root/'no_change',proposal_receipt_sha256=no_change['proposal_receipt_sha256'],
                owner_decision=nc_ref,portfolio_context=binding['portfolio_context'],review_root=current.root,
                policy=self.policy,now=nc_at)
            self.assertEqual(nc['status'],'PENDING_MODEL_REVIEW');self.assertFalse(nc['consumable'])
            held_state=board.read_json(current.root/nc['state']['path'])
            self.assertEqual(held_state['assessment_kind'],'HOLD_REAFFIRMATION')
            self.assertEqual(held_state['positions'],state['positions'])
            self.assertEqual(held_state['cash_weight'],state['cash_weight'])
            self.assertNotEqual(nc['state']['sha256'],candidate['state']['sha256'])
            self.assertEqual(held_state['parent_state_sha256'],candidate['state']['sha256'])
            self.assertEqual(held_state['parent_acceptance_sha256'],accepted_ref['sha256'])
            same=prepare_model_snapshot(out,current.root/'no_change',
                proposal_receipt_sha256=no_change['proposal_receipt_sha256'],owner_decision=nc_ref,
                portfolio_context=binding['portfolio_context'],review_root=current.root,policy=self.policy,now=nc_at)
            self.assertEqual(same,nc)
            self.assertEqual((case.root/candidate['state']['path']).read_bytes(),state_bytes)
            with self.assertRaisesRegex(ContractError,'model_publication_fields'):
                publish(self.p,self.r,self.policy,out,'forged',CODE_SHA,artifact_resolver=self.memory(),
                    review_root=current.root,model_publication={**request,'approved':True})
            self.assertEqual((out/'attempts/accepted-once/receipt.json').read_bytes(),original_bytes)
            # A later assessment can use an EXPIRED, explicitly authenticated
            # last parent as lineage. Its fresh Source/A3/A4/pre-QA are genuinely
            # rebuilt; the old QA/ER is not made current by a new read timestamp.
            from tools.run_multi_asset_leadership import prepare_model_parent_read_observation
            old_acceptance_bytes=(current.root/accepted_ref['path']).read_bytes()
            self.p['as_of']='2026-09-19T11:10:00+00:00'
            self.policy.pop('current_a3_review_profile')
            reviewed(self.p,self.r,self.policy);risk(self.p,self.r,self.policy)
            self.original=next(e for e in self.p['evaluations'] if e['asset_id']==aid)
            self.original['issuer_id']='CIK:1'
            self.p['evaluations']=[e for e in self.p['evaluations'] if e['asset_id']!=aid]
            self.stock_review_inputs()
            # Verified MODEL-only positive weight remains reviewable after it
            # leaves the base. Membership alone never creates a SELL.
            self.p['base_equity_ids']=['US:UNMAPPED']
            self.p['base_universe_receipt']['asset_ids']=['US:UNMAPPED']
            self.policy['reviewed_pins']['base_universe'].append(digest(self.p['base_universe_receipt']))
            self.original['feature_sha256']=feature_identity(self.p,self.r)
            self.policy['reviewed_pins']['evaluation'].append(digest(self.original))
            self.p['risk']['feature_sha256']=feature_identity(self.p,self.r)
            self.p['risk']['stock_cash_allocation']['evaluation_sha256_by_asset']={aid:digest(self.original)}
            self.policy['reviewed_pins']['risk'].append(digest(self.p['risk']));self.reseal()
            parent_expiry='2026-09-19T12:00:00+00:00'
            self.policy['model_lineage_parent']=dict(schema='model-lineage-parent-policy-v1',
                purpose='PARENT_LINEAGE_ONLY',acceptance=accepted_ref,accepted_at=accepted_ref['collected_at'],
                state_sha256=candidate['state']['sha256'],model_identity_sha256=digest(identity),
                available_at='2026-09-19T11:00:00+00:00',expires_at=parent_expiry)
            parent_context=copy.deepcopy(model_context)
            for ref in parent_context['artifact_inventory'].values():
                ref.update(observed_at='2026-09-19T11:00:00+00:00',available_at='2026-09-19T11:00:00+00:00',
                    collected_at='2026-09-19T11:00:00+00:00',expires_at=parent_expiry)
            observed=prepare_model_parent_read_observation(self.policy,current.root,now='2026-09-19T11:00:00+00:00')
            parent_context['model_state'].update(kind='PARENT_LINEAGE_ONLY',artifact=observed['artifact'])
            for key,ref in parent_context['artifact_inventory'].items():
                if ref['path']==accepted_ref['path']:parent_context['artifact_inventory'][key]=observed['artifact']
            later=ControlPlaneTests('runTest');later.setUp();self.addCleanup(later.doCleanups)
            later_binding,_,later_principals=later.current_review_case(self,
                model_binding=(parent_context,current.root),model_policy=self.policy)
            self.p['current_a3_review']=later_binding
            self.policy['current_a3_review_profile']=dict(schema='current-a3-review-profile-v1',
                purpose='CURRENT_RESEARCH_FORWARD_ONLY',context_sha256=later_binding['portfolio_context']['sha256'],
                graph_sha256=later_binding['review_graph']['sha256'],binding_sha256=digest(later_binding),
                policy_base_sha256=digest(self.policy),feature_sha256=feature_identity(self.p,self.r),
                risk_sha256=digest(self.p['risk']),code_sha=CODE_SHA,available_at=later.at(-5.25),
                expires_at=min(later.at(30),later_binding['review_graph']['expires_at']),principals=later_principals)
            latest_packet=copy.deepcopy(next(p for p in later.tasks() if p['agent']=='A5'))
            later._artifact_prefix='new_hold_source'
            latest_receipt=copy.deepcopy(later.complete('A5',{'target_proposal':original_target}))
            latest_refs={}
            for role,value in (('a5_packet',latest_packet),('a5_receipt',latest_receipt)):
                ref=later.artifact('current_'+role);later.set_payload(ref,value)
                ref['observed_at']=ref['available_at']=ref['collected_at']=latest_receipt['available_at']
                latest_refs[role]=ref
            later_out=later.root/'new_proposal'
            later_result=publish(self.p,self.r,self.policy,later_out,'fresh-hold',CODE_SHA,
                artifact_resolver=self.memory(),review_root=later.root)
            self.assertEqual(later_result['proposal']['proposed_weights'].get(aid),.15)
            self.assertFalse(later_result['global_ranking_ready'])
            selected_at=(board.timestamp(self.p['as_of'])+timedelta(seconds=1)).isoformat()
            new_owner={**no_change,**latest_refs,'selected_at':selected_at,'expires_at':parent_expiry,
                'proposal_receipt_sha256':hashlib.sha256((later_out/'latest_attempt.json').read_bytes()).hexdigest()}
            owner_path=later.root/'fresh_hold_owner.json';owner_path.write_bytes(encoded(new_owner))
            new_owner_ref=dict(path=owner_path.name,sha256=hashlib.sha256(owner_path.read_bytes()).hexdigest(),
                observed_at=selected_at,available_at=selected_at,collected_at=selected_at,
                expires_at=parent_expiry,status='VERIFIED')
            fresh=prepare_model_snapshot(later_out,later.root/'fresh_hold',
                proposal_receipt_sha256=new_owner['proposal_receipt_sha256'],owner_decision=new_owner_ref,
                portfolio_context=later_binding['portfolio_context'],review_root=later.root,policy=self.policy,
                now=(board.timestamp(selected_at)+timedelta(seconds=1)).isoformat())
            fresh_state=board.read_json(later.root/fresh['state']['path'])
            self.assertEqual(fresh_state['assessment_kind'],'HOLD_REAFFIRMATION')
            self.assertGreater(stamp(fresh['state']['expires_at']),stamp(accepted['expires_at']))
            self.assertEqual(fresh_state['parent_acceptance_sha256'],accepted_ref['sha256'])
            self.assertEqual((current.root/accepted_ref['path']).read_bytes(),old_acceptance_bytes)
            self.assertFalse(fresh['model_acceptance_issued']);self.assertFalse(fresh['consumable'])
            self.assertFalse(result['accepted_target_written']);self.assertFalse(result['orders_generated'])

    def test_current_review_original_graph_can_conditionally_admit_without_registry_promotion(self):
        case,_=self.current_review()
        result=run(self.p,self.r,self.policy,artifact_resolver=self.memory(),review_root=case.root,code_sha=CODE_SHA)
        coverage=result['a3_reference_coverage']
        self.assertEqual(coverage['held_count'],0,coverage)
        self.assertTrue(coverage['records'][0]['runtime_evaluation_admitted'])
        self.assertEqual(coverage['current_review']['purpose'],'CURRENT_RESEARCH_FORWARD_ONLY')
        self.assertIn('INDEPENDENT_REVIEW_NOT_AUTHENTICATED',coverage['records'][0]['consumption_blockers'])
        self.assertFalse(coverage['source_admission_granted'])
        self.assertFalse(result['accepted_target_written'])
        self.assertFalse(result['orders_generated'])

    def test_current_model_allocation_replays_real_verifiers_into_existing_propose(self):
        from tests.control_plane_agent_contract_smoke import ControlPlaneTests
        def refresh(cutoff):
            self.p['as_of']=cutoff
            reviewed(self.p,self.r,self.policy);risk(self.p,self.r,self.policy)
            self.original=next(e for e in self.p['evaluations'] if e['asset_id']=='US:FTI')
            self.original['issuer_id']='CIK:1'
            self.policy['reviewed_pins']['evaluation'].append(digest(self.original))
            self.p['evaluations']=[e for e in self.p['evaluations'] if e['asset_id']!='US:FTI']
            self.stock_review_inputs();self.reseal()
        refresh('2026-09-19T10:10:00+00:00')
        origin=ControlPlaneTests('runTest');origin.setUp();self.addCleanup(origin.doCleanups)
        model_context,model_policy,acceptance,aid=origin.model_incumbents_case(self)
        model_context,model_policy,_=origin.model_cash_variant(model_context,model_policy,acceptance)
        self.policy['reviewed_pins']['positions']=model_policy['reviewed_pins']['positions']
        refresh('2026-09-19T10:20:00+00:00')
        case=ControlPlaneTests('runTest');case.setUp();self.addCleanup(case.doCleanups)
        binding,_,principals=case.current_review_case(self,
            model_binding=(model_context,origin.root),model_policy=self.policy)
        self.p.update(current_a3_review=binding,position_book_kind='MODEL',
            model_identity=copy.deepcopy(model_context['model_state']['model_identity']))
        self.policy['current_a3_review_profile']=dict(schema='current-a3-review-profile-v1',
            purpose='CURRENT_RESEARCH_FORWARD_ONLY',context_sha256=binding['portfolio_context']['sha256'],
            graph_sha256=binding['review_graph']['sha256'],binding_sha256=digest(binding),
            policy_base_sha256=digest(self.policy),feature_sha256=feature_identity(self.p,self.r),
            risk_sha256=digest(self.p['risk']),code_sha=CODE_SHA,available_at=case.at(-5.25),
            expires_at=min(case.at(30),binding['review_graph']['expires_at']),principals=principals)
        # Observe the incumbent, unchanged allocator; do not replace its policy
        # or mock any review/admission/completion verifier.
        with patch('research.multi_asset_v1.runtime.propose',wraps=propose) as allocator:
            result=run(self.p,self.r,self.policy,artifact_resolver=self.memory(),
                       review_root=case.root,code_sha=CODE_SHA)
        self.assertTrue(allocator.called,result.get('a3_reference_coverage'))
        self.assertEqual(allocator.call_args.args[-1],{})  # admitted all-cash, not unknown/GENESIS
        self.assertNotEqual(result['proposal']['status'],'BLOCKED',result['proposal'])
        self.assertEqual(result['proposal_context']['mode'],'MODEL')
        self.assertEqual(result['proposal_context']['book_kind'],'MODEL')
        self.assertEqual(result['proposal_context']['cash_weight'],1.0)
        self.assertEqual(result['proposal']['intent'],'NO_ENTRY_HOLD_CASH')
        self.assertEqual(result['proposal']['cash'],1.0)
        self.assertEqual(result['portfolio_exposure']['cash_weight'],1.0)
        self.assertFalse(result['proposal_context']['actual_holdings_claimed'])
        self.assertFalse(result['proposal_context']['execution_or_performance_claimed'])
        self.assertFalse(result['accepted_target_written'])
        self.assertFalse(result['orders_generated'])
        # An absent/unusable original ER is UNKNOWN, never an all-cash decision.
        bad=copy.deepcopy(self.p);bad['a3_reference_entries']=[]
        blocked=run(bad,self.r,self.policy,artifact_resolver=self.memory(),review_root=case.root,code_sha=CODE_SHA)
        self.assertEqual(blocked['proposal']['status'],'BLOCKED')
        self.assertIsNone(blocked['proposal']['proposed_weights'])

    def test_current_review_missing_self_review_or_changed_policy_never_admits(self):
        case,_=self.current_review()
        original=copy.deepcopy(self.policy)
        for change in (lambda p:p.pop('current_a3_review_profile'),
                       lambda p:p['current_a3_review_profile']['principals'].update(A6='PRODUCER:ANALYST'),
                       lambda p:p['current_a3_review_profile'].update(code_sha='0'*40),
                       lambda p:p['current_a3_review_profile'].update(expires_at='2026-09-18T00:00:00Z'),
                       lambda p:p['current_a3_review_profile'].update(available_at=None),
                       lambda p:p['current_a3_review_profile'].update(feature_sha256='0'*64),
                       lambda p:p['reviewed_pins']['risk'].clear(),
                       lambda p:p['validated_models'].clear()):
            self.policy=copy.deepcopy(original);change(self.policy)
            result=run(self.p,self.r,self.policy,artifact_resolver=self.memory(),review_root=case.root,code_sha=CODE_SHA)
            self.assertEqual(result['a3_reference_coverage']['held_count'],1)
            self.assertFalse(result['a3_reference_coverage']['records'][0]['runtime_evaluation_admitted'])
            self.assertFalse(result['global_ranking_ready'])
            self.assertIsNone(result['proposal']['proposed_weights'])

        self.policy=original
        binding=copy.deepcopy(self.p['current_a3_review'])
        for key,value in (('expires_at','2027-01-01T00:00:00Z'),
                          ('collected_at','2026-09-19T09:00:00Z')):
            self.p['current_a3_review']=copy.deepcopy(binding)
            self.p['current_a3_review']['review_graph'][key]=value
            result=run(self.p,self.r,self.policy,artifact_resolver=self.memory(),review_root=case.root,code_sha=CODE_SHA)
            self.assertEqual(result['a3_reference_coverage']['current_review']['reason'],'a3_current_review_pin')
            self.assertEqual(result['a3_reference_coverage']['held_count'],1)

    def test_current_review_does_not_override_final_market_or_partial_cohort_refusal(self):
        self.market['price']+=1
        case,_=self.current_review()
        result=run(self.p,self.r,self.policy,artifact_resolver=self.memory(),review_root=case.root,code_sha=CODE_SHA)
        self.assertEqual(result['a3_reference_coverage']['current_review']['status'],'CURRENT_REFERENCE_REVIEW_VERIFIED')
        self.assertEqual(result['a3_reference_coverage']['held_count'],1)
        self.assertFalse(result['global_ranking_ready'])
        self.p['requested_security_ids'].append('US:UNMAPPED')
        result=run(self.p,self.r,self.policy,artifact_resolver=self.memory(),review_root=case.root,code_sha=CODE_SHA)
        self.assertEqual(result['a3_reference_coverage']['held_count'],2)
        self.assertEqual(result['a3_reference_coverage']['records'][-1]['asset_id'],'US:UNMAPPED')

    def test_original_full_er_is_prepared_for_model_without_claiming_current_review(self):
        result=self.execute()
        coverage=result['a3_reference_coverage']
        self.assertEqual(coverage['original_er_verified_count'],1)
        self.assertTrue(coverage['records'][0]['original_runtime_contract_verified'])
        self.assertFalse(coverage['records'][0]['runtime_evaluation_admitted'])
        self.assertIn('INDEPENDENT_REVIEW_NOT_AUTHENTICATED',coverage['records'][0]['consumption_blockers'])
        self.assertEqual(result['a3_model_input_candidates'][0],self.original)
        self.assertEqual(coverage['records'][0]['original_er_ref']['sha256'],
                         self.packet['artifacts']['validated_er']['sha256'])
        self.assertEqual(result['proposal_context']['mode'],'MODEL')
        self.assertFalse(result['global_ranking_ready'])
        self.assertEqual(result['proposal']['status'],'BLOCKED')
        self.assertFalse(result['accepted_target_written'])
        self.assertFalse(result['orders_generated'])

    def test_missing_and_unmapped_requested_stocks_remain_visible(self):
        self.p['requested_security_ids']=['US:FTI','US:CCJ','US:UNMAPPED']
        self.p['base_equity_ids']=list(self.p['requested_security_ids'])
        self.p['evaluations']=[e for e in self.p['evaluations'] if e['asset_id']!='US:CCJ']
        result=self.execute()
        records=result['a3_reference_coverage']['records']
        self.assertEqual([r['asset_id'] for r in records],self.p['requested_security_ids'])
        self.assertEqual(records[1]['blocker'],'MISSING_A3_REFERENCE')
        self.assertEqual(records[2]['blocker'],'REGISTRY_ASSET_UNMAPPED')
        self.assertIn('unmapped_base_equity',result['base_universe_blockers'])
        self.assertFalse(result['global_ranking_ready'])
        self.assertIsNone(result['proposal']['proposed_weights'])

    def test_scenario_only_a3_never_becomes_expected_return(self):
        self.reseal(include_er=False)
        result=self.execute()
        self.assertEqual(result['a3_reference_coverage']['records'][0]['blocker'],'VALIDATED_ER_NOT_LINKED')
        row=next(r for r in result['multi_asset_leadership_latest'] if r['asset_id']=='US:FTI')
        self.assertIsNone(row['expected_return_12m'])
        self.assertFalse(result['global_ranking_ready'])

    def test_no_repair_or_default_costs_and_model_feature_clocks_stay_bound(self):
        original=copy.deepcopy(self.original)
        for change in (lambda e:e.pop('cost_assumptions'),
                       lambda e:e.update(model_id='UNKNOWN'),
                       lambda e:e.update(feature_sha256='e'*64),
                       lambda e:e.update(training_labels_available_before='2026-10-01T00:00:00Z'),
                       lambda e:e.update(issuer_id='CIK:OTHER')):
            self.original=copy.deepcopy(original);change(self.original)
            self.policy['reviewed_pins']['evaluation'].append(digest(self.original))
            self.reseal()
            result=self.execute()
            record=result['a3_reference_coverage']['records'][0]
            self.assertEqual(record['blocker'],'ORIGINAL_ER_EVALUATION_CONTRACT_BLOCKED')
            self.assertFalse(record['runtime_evaluation_admitted'])
            self.assertFalse(result['global_ranking_ready'])

    def test_market_price_and_relative_features_must_match_actual_runtime_inputs(self):
        original=copy.deepcopy(self.market)
        for key in ('price','return_20d','rs_60d'):
            self.market=copy.deepcopy(original);self.market[key]+=.01
            if key=='return_20d':
                self.market['rs_20d']=math.log1p(self.market[key])-math.log1p(self.market['benchmark_return_20d'])
            if key=='rs_60d':
                self.market['benchmark_return_60d']=math.expm1(math.log1p(self.market['return_60d'])-self.market[key])
            self.reseal()
            result=self.execute()
            row=next(r for r in result['multi_asset_leadership_latest'] if r['asset_id']=='US:FTI')
            self.assertIsNone(row['expected_return_12m'])
            self.assertTrue(any('a3_market_' in b for b in row['blockers']))
            self.assertFalse(result['a3_reference_coverage']['records'][0]['runtime_evaluation_admitted'])

    def test_manual_replacement_and_duplicate_roster_cannot_bypass_references(self):
        self.p['evaluations'].append(self.original)
        with self.assertRaisesRegex(ContractError,'a3_duplicate_evaluation_input'):self.execute()
        self.p['evaluations'].pop()
        self.p['requested_security_ids']*=2
        with self.assertRaisesRegex(ContractError,'a3_duplicate_requested_security'):self.execute()

    def test_local_cli_artifact_loader_is_bounded_and_hash_verified(self):
        from tools.run_multi_asset_leadership import a3_artifacts
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=b'synthetic';(root/'evidence').write_bytes(raw)
            payload={'artifact_files':[dict(artifact_id='TEST',path='evidence',sha256=hashlib.sha256(raw).hexdigest())]}
            self.assertEqual(a3_artifacts(payload,root).read('TEST',hashlib.sha256(raw).hexdigest()),raw)
            (root/'evidence').write_bytes(b'tampered')
            with self.assertRaisesRegex(ContractError,'a3_artifact_input:FILE_HASH'):a3_artifacts(payload,root)
            payload['artifact_files'][0]['path']='../escape'
            with self.assertRaisesRegex(ContractError,'a3_artifact_input:FILE_PATH'):a3_artifacts(payload,root)

    def test_actual_cli_consumes_original_refs_and_revokes_tampered_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);artifacts=out/'evidence';artifacts.mkdir()
            self.p['artifact_files']=[]
            values={aid:raw for (aid,_),raw in self.refs.raw.items()}
            for i,(aid,raw) in enumerate(sorted(values.items())):
                name=f'object-{i}.json';(artifacts/name).write_bytes(raw)
                self.p['artifact_files'].append(dict(artifact_id=aid,path=name,sha256=hashlib.sha256(raw).hexdigest()))
            payload=encoded(self.p)
            (out/'input.json').write_bytes(payload)
            (out/'registry.json').write_bytes(encoded(self.r))
            (out/'policy.json').write_bytes(encoded(self.policy))
            def execute(attempt):
                return subprocess.run([sys.executable,'-B',str(ROOT/'tools/run_multi_asset_leadership.py'),
                    '--input',str(out/'input.json'),'--expected-input-sha256',hashlib.sha256(payload).hexdigest(),
                    '--artifact-root',str(artifacts),'--registry',str(out/'registry.json'),
                    '--policy',str(out/'policy.json'),'--output-dir',str(out/'result'),
                    '--attempt-id',attempt,*configuration_args(out)],capture_output=True,text=True,timeout=60)
            success=execute('a3-original')
            self.assertEqual(success.returncode,2,success.stdout+success.stderr)
            result=load_json((out/'result/attempts/a3-original/result.json').read_bytes())
            self.assertTrue(result['a3_reference_coverage']['records'][0]['original_runtime_contract_verified'])
            self.assertFalse(result['a3_reference_coverage']['records'][0]['runtime_evaluation_admitted'])
            self.assertFalse(result['global_ranking_ready'])
            self.assertEqual(result['proposal_context']['mode'],'MODEL')
            self.assertIn('research/a3_candidate_packet_v1.py',
                          {key.replace('\\','/') for key in result['code_file_sha256']})
            self.assertFalse((out/'result/last_success.json').exists())
            prior=b'prior synthetic success must survive'
            (out/'result/last_success.json').write_bytes(prior)
            (artifacts/self.p['artifact_files'][0]['path']).write_bytes(b'corrupt')
            failed=execute('a3-tampered')
            self.assertEqual(failed.returncode,2)
            self.assertEqual(load_json((out/'result/latest_attempt.json').read_bytes())['status'],'BLOCKED')
            self.assertEqual((out/'result/last_success.json').read_bytes(),prior)


class StockCashResearch(unittest.TestCase):
    """Existing registered suite; synthetic evidence never issues admission."""

    def inputs(self):
        p,r,policy=fixture()
        # The legacy fixture makes SPY the fastest series. Construct a genuine
        # positive ENTRY case from prices, not by overriding computed RS flags.
        index={session:i for i,session in enumerate(SESSIONS)}
        order={a["asset_id"]:i for i,a in enumerate(r["assets"],1)}
        for price in p["prices"]:
            t=index[price["session"]]
            growth=.0002*t+.00005*math.sin(t*.13) if price["asset_id"]=="US:SPY" else (
                .0004*t+.000008*order[price["asset_id"]]*t*t+.0001*math.sin(t*.17+order[price["asset_id"]]))
            price["price"]=price["total_return_index"]=100*math.exp(growth)
        reviewed(p,r,policy)
        policy["stock_cash_research"]["enabled"]=True
        policy["stock_cash_research"]["allocator"]="COST_AWARE_LONG_ONLY"
        for e in p["evaluations"]:
            e["cost_assumptions"]["commission_bps"]=25
            e["portfolio_cost_basis"]=dict(schema="reviewed-portfolio-cost-basis-v1",
                horizon="12_CALENDAR_MONTHS",kind="NET_REFERENCE_ROUND_TRIP",
                cost_assumptions_sha256=digest(e["cost_assumptions"]),evidence_sha256="c"*64,
                reference_cost_bps_per_side=25,embedded_cost_fraction=.005,
                embedded_transaction_cost_fraction=.005,embedded_ongoing_cost_fraction=0,
                gross_expected_return=e["expected_return_12m"]+.005)
        policy["reviewed_pins"]["evaluation"]=[digest(e) for e in p["evaluations"]]
        rr=risk(p,r,policy)
        from research.a2_research_intake_v1 import MemoryArtifacts
        raw=b"DATE,DGS3MO\n2026-09-17,3.0\n"
        sha=hashlib.sha256(raw).hexdigest()
        self.memory=MemoryArtifacts({"CASH:SOURCE":raw})
        rr["stock_cash_allocation"]=dict(horizon="12_CALENDAR_MONTHS",events_sha256=digest([]),
            decision_asset_ids=sorted(e["asset_id"] for e in p["evaluations"]),
            evaluation_sha256_by_asset={e["asset_id"]:digest(e) for e in p["evaluations"]},
            cash_carry=dict(**{**meta("FRED_ARCHIVE"),"raw_sha256":sha},metric="dgs3mo",unit="FRACTION",value=.03,
                observation_date="2026-09-17",original_ref=dict(artifact_id="CASH:SOURCE",sha256=sha,bytes=len(raw))),
            exception_reviews=[],exit_reviews=[])
        policy["reviewed_pins"]["risk"].append(digest(rr))
        return p,r,policy

    def test_real_runtime_optin_shared_cost_inputs_and_no_default_change(self):
        p,r,policy=self.inputs()
        original=copy.deepcopy(p)
        out=run(p,r,policy,artifact_resolver=self.memory)
        proposal=out["proposal"]
        self.assertEqual(proposal["status"],"RESEARCH_PROPOSAL")
        self.assertEqual(p,original)
        source=p["evaluations"][0]
        corresponding=next(x for x in out["multi_asset_leadership_latest"] if x["asset_id"]==source["asset_id"])
        self.assertEqual(corresponding["evaluation_sha256"],digest(source))
        self.assertNotEqual(corresponding["evaluation_sha256"],digest({**source,"expected_alpha_12m":.15,
                            "fundamental_score":None}))
        self.assertGreater(sum(proposal["proposed_weights"].values()),0)
        self.assertLessEqual(sum(proposal["proposed_weights"].values()),.4+1e-8)
        self.assertTrue(all(abs(x-.205)<1e-12 for x in proposal["comparison_inputs"]["gross_er"]))
        self.assertEqual(proposal["comparison_inputs"]["side_cost"],[.0025]*3)
        self.assertEqual(proposal["exception_exposure"],0)
        self.assertEqual(proposal["decision_clock"]["horizon"],"12_CALENDAR_MONTHS")
        self.assertGreater(stamp(proposal["decision_clock"]["earliest_fill_at"]),stamp(CUTOFF))
        self.assertFalse(proposal["orders_generated"])
        self.assertEqual(len(out["stock_research"]["comparison_plan"]["arms"]),18)
        policy["stock_cash_research"]["enabled"]=False
        baseline=run(p,r,policy,artifact_resolver=self.memory)
        self.assertNotIn("stock_research",baseline)
        self.assertNotIn("comparisons",baseline["proposal"])
        policy["stock_cash_research"]["enabled"]=True
        p["evaluations"][0]["signal_confidence"]+=.01
        refused=run(p,r,policy,artifact_resolver=self.memory)
        self.assertEqual(refused["proposal"]["status"],"BLOCKED")
        bad=next(x for x in refused["multi_asset_leadership_latest"] if x["asset_id"]==source["asset_id"])
        self.assertIsNone(bad.get("evaluation_sha256"))

    def test_inactive_optional_unknown_preserves_full_denominator_but_not_stock_block(self):
        p,r,policy=self.inputs()
        complete=json.loads((ROOT/"docs/multi_asset_registry_v1.json").read_bytes())
        r["assets"].append(next(a for a in complete["assets"] if a["symbol"]=="GLDM"))
        # Rebind synthetic original evaluators and risk to this exact feature snapshot.
        for e in p["evaluations"]:e["feature_sha256"]=feature_identity(p,r)
        policy["reviewed_pins"]["evaluation"]=[digest(e) for e in p["evaluations"]]
        p["risk"]["feature_sha256"]=feature_identity(p,r)
        p["risk"]["stock_cash_allocation"]["evaluation_sha256_by_asset"]={e["asset_id"]:digest(e) for e in p["evaluations"]}
        policy["reviewed_pins"]["risk"].append(digest(p["risk"]))
        out=run(p,r,policy,artifact_resolver=self.memory)
        self.assertEqual(out["proposal"]["status"],"RESEARCH_PROPOSAL",out["proposal"].get("reasons"))
        self.assertFalse(out["global_ranking_ready"])
        self.assertEqual(out["stock_research"]["decision_scope"]["numeric_scope_status"],"SCOPED_INPUTS_OBSERVED")
        self.assertEqual(len(out["multi_asset_leadership_latest"]),4)
        missing=next(x for x in out["multi_asset_leadership_latest"] if x["symbol"]=="GLDM")
        self.assertIsNone(missing["expected_return_12m"])
        self.assertIsNone(missing["rank"])
        self.assertEqual(out["stock_research"]["decision_scope"]["unknown_roster_count"],1)
        self.assertEqual(out["stock_research"]["exception_preparation"][1]["status"],"UNREGISTERED")

    def test_unknown_held_and_ambiguous_costs_block_without_zero_fill(self):
        p,r,policy=self.inputs()
        e=p["evaluations"][0]
        e.pop("portfolio_cost_basis")
        policy["reviewed_pins"]["evaluation"].append(digest(e))
        p["risk"]["stock_cash_allocation"]["evaluation_sha256_by_asset"][e["asset_id"]]=digest(e)
        policy["reviewed_pins"]["risk"].append(digest(p["risk"]))
        out=run(p,r,policy,artifact_resolver=self.memory)
        self.assertEqual(out["proposal"]["status"],"BLOCKED")
        self.assertIn("stock_net_er_cost_basis_missing",out["proposal"]["reasons"][0])
        self.assertIsNone(out["proposal"]["proposed_weights"])
        self.assertIsNotNone(out["multi_asset_leadership_latest"][0]["expected_return_12m"])

    def test_scope_union_keeps_top40_outside_winner_and_event_unknown(self):
        from research.multi_asset_v1.decisions import stock_decision_scope
        p,r,policy=self.inputs()
        assets={"S:"+str(i):dict(asset_class="US_EQUITY") for i in range(45)}
        rows=[dict(asset_id=a,discovery_rank=i+1,data_quality="PRICE_OBSERVED_RESEARCH_ONLY",
            risk_adjusted_expected_alpha=1/(i+1),evaluation_sha256="d"*64,expected_return_12m=.2)
            for i,a in enumerate(assets)]
        rows[44]["expected_return_12m"]=None
        rows[44]["risk_adjusted_expected_alpha"]=None
        events=[dict(confirmed=True,materiality=.9,affected_asset_ids=["S:44"])]
        scope=stock_decision_scope(rows,assets,{"S:43":.15},events,CUTOFF,policy,["S:43"])
        self.assertEqual(len(scope["asset_ids"]),42)
        self.assertIn("S:43",scope["asset_ids"])
        self.assertEqual(scope["full_roster_count"],45)
        self.assertEqual(scope["numeric_scope_status"],"SCOPED_INPUTS_OBSERVED")
        self.assertEqual(scope["queue_unknown_count"],1)
        self.assertEqual(len(rows),45)

    def test_healthy_winner_floor_and_typed_thesis_exit_actual_weights(self):
        p,r,policy=self.inputs()
        before=run(p,r,policy,artifact_resolver=self.memory)
        rows=before["multi_asset_leadership_latest"]
        assets={a["asset_id"]:a for a in r["assets"]}
        row=rows[0];aid=row["asset_id"]
        row.update(portfolio_status="HOLD",RS20_change_5d=-.1,RS60_change_5d=-.1)
        kept=propose(rows,assets,p["risk"],{},CUTOFF,policy,feature_identity(p,r),{aid:.08},artifact_resolver=self.memory)
        self.assertGreaterEqual(kept["proposed_weights"][aid],.08-1e-9)
        row["thesis_status"]="INVALID"
        p["risk"]["stock_cash_allocation"]["exit_reviews"]=[dict(asset_id=aid,taxonomy="THESIS_EXIT",
            evaluation_sha256=row["evaluation_sha256"],thesis_id=row["thesis_id"],reason="ORIGINAL_THESIS_INVALID",
            available_at=CUTOFF,expires_at="2026-09-20T10:00:00Z",max_weight=0)]
        policy["reviewed_pins"]["risk"].append(digest(p["risk"]))
        exited=propose(rows,assets,p["risk"],{},CUTOFF,policy,feature_identity(p,r),{aid:.08},artifact_resolver=self.memory)
        self.assertNotIn(aid,exited["proposed_weights"])
        self.assertEqual(exited["exit_reviews"][0]["taxonomy"],"THESIS_EXIT")
        row["thesis_status"]="INTACT"
        with self.assertRaisesRegex(ContractError,"stock_healthy_thesis_exit"):
            propose(rows,assets,p["risk"],{},CUTOFF,policy,feature_identity(p,r),{aid:.08},artifact_resolver=self.memory)

    def test_same_week_schedule_and_confirmed_event_calendar_only(self):
        from research.multi_asset_v1.decisions import stock_decision_clock
        _,_,policy=self.inputs()
        profile=policy["stock_cash_research"]
        profile["cadence"]="WEEKLY"
        review={"previous_decision_at":"2026-09-17T20:00:00Z"}
        clock=stock_decision_clock(CUTOFF,profile,review,[])
        self.assertFalse(clock["scheduled_due"])
        profile["cadence"]="MONTHLY_CONFIRMED_EVENT"
        self.assertFalse(stock_decision_clock(CUTOFF,profile,review,[])["scheduled_due"])
        events=[dict(event_id="NEWS:1",confirmed=True,materiality=.8,first_seen="2026-09-18T20:01:00Z",
                     material_change_times=["2026-09-18T20:01:00Z"])]
        self.assertTrue(stock_decision_clock(CUTOFF,profile,review,events)["scheduled_due"])
        events[0]["confirmed"]=False
        self.assertFalse(stock_decision_clock(CUTOFF,profile,review,events)["scheduled_due"])
        profile["cadence"]="MONTHLY"
        same=stock_decision_clock(CUTOFF,profile,{"previous_decision_at":"2026-09-18T21:00:00Z"},[])
        self.assertTrue(same["same_session"])
        self.assertFalse(same["scheduled_due"])
        boundary=stock_decision_clock("2026-10-01T01:10:00Z",profile,
            {"previous_decision_at":"2026-10-01T00:10:00Z"},[])
        self.assertEqual(boundary["decision_session"],"2026-09-30")
        self.assertFalse(boundary["scheduled_due"])

    def test_cost_components_keep_ongoing_and_all_in_stress_exact(self):
        from research.multi_asset_v1.decisions import _stock_cost
        p,_,_=self.inputs()
        row=copy.deepcopy(p["evaluations"][0])
        row["cost_assumptions"]["expense_bps"]=100
        basis=row["portfolio_cost_basis"]
        basis.update(embedded_cost_fraction=.015,embedded_ongoing_cost_fraction=.01,
            gross_expected_return=.215,cost_assumptions_sha256=digest(row["cost_assumptions"]))
        for bps in (25,50,100):
            annual,side=_stock_cost(row,bps)
            self.assertAlmostEqual(annual,.205)
            self.assertEqual(side,bps/10000)
        basis["embedded_transaction_cost_fraction"]+=.01
        with self.assertRaisesRegex(ContractError,"component_reconciliation"):_stock_cost(row,25)

    def test_original_dgs3mo_value_date_and_resolver_required(self):
        p,r,policy=self.inputs()
        refused=run(p,r,policy)
        self.assertIn("stock_dgs3mo_original_resolver_required",refused["proposal"]["reasons"])
        p["risk"]["stock_cash_allocation"]["cash_carry"]["value"]=.04
        policy["reviewed_pins"]["risk"].append(digest(p["risk"]))
        refused=run(p,r,policy,artifact_resolver=self.memory)
        self.assertIn("stock_dgs3mo_original_value_or_date_mismatch",refused["proposal"]["reasons"])

    def test_opportunity_actual_counterfactual_cap_and_unknown_release(self):
        p,r,policy=self.inputs()
        out=run(p,r,policy,artifact_resolver=self.memory)
        rows=copy.deepcopy(out["multi_asset_leadership_latest"])
        assets={a["asset_id"]:a for a in r["assets"]}
        base=copy.deepcopy(rows[0])
        complete=json.loads((ROOT/"docs/multi_asset_registry_v1.json").read_bytes())
        metal=copy.deepcopy(next(a for a in complete["assets"] if a["symbol"]=="GLDM"))
        metal.update(tradable=True,identity_verified=True,corporate_action_quarantine=False)
        assets["US:GLDM"]=metal
        base.update(asset_id="US:GLDM",symbol="GLDM",expected_return_12m=.6,expected_alpha_12m=.55,
                    evaluation_sha256="e"*64)
        base["portfolio_cost_basis"]["gross_expected_return"]=.605
        rows.append(base)
        rr=p["risk"];rr["max_gross"]=1;rr["max_security_weight"]=.5
        rr["risk_multipliers"][metal["asset_class"]]=1
        rr["risk_group_limits"].update({g:.6 for a in assets.values() for g in a["risk_group_ids"]})
        review=rr["stock_cash_allocation"]
        review.update(decision_asset_ids=sorted(x["asset_id"] for x in rows),
                      evaluation_sha256_by_asset={x["asset_id"]:x["evaluation_sha256"] for x in rows})
        proof=dict(asset_id="US:GLDM",basis="OPPORTUNITY",evaluation_sha256="e"*64,
            thesis_id=base["thesis_id"],reason="REVIEWED_NET_COMPARISON",release_condition="REVIEW_IF_EDGE_DISAPPEARS",
            available_at=CUTOFF,expires_at="2026-09-20T10:00:00Z",max_weight=.2)
        review["exception_reviews"]=[proof]
        policy["reviewed_pins"]["risk"].append(digest(rr))
        result=propose(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),artifact_resolver=self.memory)
        self.assertGreater(result["proposed_weights"]["US:GLDM"],.1)
        self.assertLessEqual(result["exception_exposure"],.2+1e-8)
        self.assertGreater(result["exception_reviews"][0]["objective_improvement"],0)
        from scipy.optimize import minimize as real_minimize
        from types import SimpleNamespace
        count=[0]
        def invalid_second(*args,**kwargs):
            count[0]+=1
            answer=real_minimize(*args,**kwargs)
            return SimpleNamespace(success=True,x=-np.ones_like(answer.x)) if count[0]==2 else answer
        import numpy as np
        with patch("scipy.optimize.minimize",side_effect=invalid_second):
            with self.assertRaisesRegex(ContractError,"counterfactual_failed"):
                propose(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),artifact_resolver=self.memory)
        proof["basis"]="SPECIAL_RISK"
        policy["reviewed_pins"]["risk"].append(digest(rr))
        with self.assertRaisesRegex(ContractError,"joint_evidence_missing"):
            propose(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),artifact_resolver=self.memory)
        review["exception_reviews"]=[]
        policy["reviewed_pins"]["risk"].append(digest(rr))
        with self.assertRaisesRegex(ContractError,"release_proof_missing"):
            propose(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),{"US:GLDM":.1},artifact_resolver=self.memory)

    def test_native_lifecycle_original_and_same_security_not_free_tag(self):
        import csv,io
        from research.a2_research_intake_v1 import MemoryArtifacts
        from research.multi_asset_v1.decisions import _stock_exit
        from tools.security_lifecycle import REQUIRED_COLUMNS,SecurityLifecycleError
        _,_,policy=self.inputs()
        event={key:"" for key in REQUIRED_COLUMNS}
        event.update(stable_security_id="US:FTI",stable_issuer_id="CIK:TEST",ticker="FTI",aliases="FTI",
            event_type="delisting",available_from="2026-09-18T19:00:00Z",effective_date="2026-09-18",
            last_trading_date="2026-09-17",delisting_proceeds="0",currency="USD",source_url="https://example.test/event",
            stable_event_id="EVENT:FTI",source_sha256="a"*64,exact_available_from="true",
            evidence_status="verified",review_status="approved")
        text=io.StringIO(newline="");writer=csv.DictWriter(text,fieldnames=sorted(REQUIRED_COLUMNS))
        writer.writeheader();writer.writerow(event);raw=text.getvalue().encode()
        sha=hashlib.sha256(raw).hexdigest();memory=MemoryArtifacts({"LIFE:1":raw})
        row=dict(asset_id="US:FTI",symbol="FTI",evaluation_sha256="e"*64,thesis_id="THESIS:FTI")
        review=dict(taxonomy="LIFECYCLE_EXIT",evaluation_sha256="e"*64,thesis_id="THESIS:FTI",
            reason="ORIGINAL_TERMINAL_EVENT",max_weight=0,available_at=CUTOFF,expires_at="2026-09-20T10:00:00Z",
            lifecycle_ref=dict(artifact_id="LIFE:1",sha256=sha,bytes=len(raw),available_at=CUTOFF))
        value,audit=_stock_exit(review,row,.1,{"US:FTI":row},CUTOFF,{"US:FTI":.1},memory,{})
        self.assertEqual(value,0)
        self.assertEqual(audit["lifecycle_original_sha256"],sha)
        for field,value in (("delisting_proceeds",""),("delisting_proceeds","NaN"),
                            ("delisting_proceeds","-1"),("evidence_status","unverified")):
            with self.subTest(field=field,value=value):
                bad={**event,field:value};text=io.StringIO(newline="")
                writer=csv.DictWriter(text,fieldnames=sorted(REQUIRED_COLUMNS));writer.writeheader();writer.writerow(bad)
                original=text.getvalue().encode();key=hashlib.sha256(original).hexdigest()
                changed=copy.deepcopy(review)
                changed["lifecycle_ref"].update(sha256=key,bytes=len(original))
                with self.assertRaises((ContractError,SecurityLifecycleError)):
                    _stock_exit(changed,row,.1,{"US:FTI":row},CUTOFF,{"US:FTI":.1},
                                MemoryArtifacts({"LIFE:1":original}),{})
        with self.assertRaisesRegex(ContractError,"resolver_unbound"):
            _stock_exit(review,row,.1,{"US:FTI":row},CUTOFF,{"US:FTI":.1},None,{})

    def test_native_replacement_policy_recomputed_and_margin_not_rank_exit(self):
        from research.multi_asset_v1.decisions import _stock_exit
        p,r,policy=self.inputs()
        rows=run(p,r,policy,artifact_resolver=self.memory)["multi_asset_leadership_latest"]
        own,other=rows[:2]
        other["portfolio_status"]="CANDIDATE"
        evidence={}
        for i,row in enumerate(rows):
            record=dict(ticker=row["symbol"],alphaops_vnext_score=1.5 if i==1 else .2,
                rs_benchmark_1w=.1,rs_benchmark_3m=.3,price_above_ma50=.9,price_above_ma200=.9,
                rs_sector_3m=.2,industry_group_strength_score=.8,portfolio_risk_entry_block_score=0,
                portfolio_stale_mega_leader_score=0,leader_tier="DUAL_LEADER",sector="SECTOR:"+str(i),
                industry_group="INDUSTRY:"+str(i))
            row["hold_exit_evidence"]=dict(security_id=row["asset_id"],as_of=list(SESSIONS)[-1],
                available_at=CUTOFF,record=record)
            evidence[row["asset_id"]]=record
        by_id={row["asset_id"]:row for row in rows}
        review=dict(taxonomy="REPLACEMENT_EXIT",evaluation_sha256=own["evaluation_sha256"],thesis_id=own["thesis_id"],
            reason="NATIVE_FIXED_MARGIN_AND_CONCENTRATION",max_weight=0,available_at=CUTOFF,
            expires_at="2026-09-20T10:00:00Z",replacement_asset_id=other["asset_id"],
            replacement_evaluation_sha256=other["evaluation_sha256"],scored_cohort_sha256=digest(evidence))
        target,audit=_stock_exit(review,own,.15,by_id,CUTOFF,{own["asset_id"]:.15},None,{})
        self.assertEqual(target,0)
        self.assertEqual(audit["replacement_asset_id"],other["asset_id"])
        saved=own["hold_exit_evidence"]["record"].pop("price_above_ma200")
        review["scored_cohort_sha256"]=digest({a:r["hold_exit_evidence"]["record"] for a,r in by_id.items()})
        with self.assertRaisesRegex(ContractError,"incomplete_incumbent"):
            _stock_exit(review,own,.15,by_id,CUTOFF,{own["asset_id"]:.15},None,{})
        own["hold_exit_evidence"]["record"]["price_above_ma200"]=saved
        other["hold_exit_evidence"]["record"]["alphaops_vnext_score"]=.21
        review["scored_cohort_sha256"]=digest({a:r["hold_exit_evidence"]["record"] for a,r in by_id.items()})
        with self.assertRaisesRegex(ContractError,"canonical_replacement_margin_not_met"):
            _stock_exit(review,own,.15,by_id,CUTOFF,{own["asset_id"]:.15},None,{})

    def test_publisher_replays_native_dependency_code_bytes(self):
        import tools.run_multi_asset_leadership as publisher
        native={"tools/run_broker_ledger_replay.py","tools/run287_hold_exit_policy.py","tools/security_lifecycle.py",
                "tools/a4_liquidity_analysis.py","tools/a4_macro_bridge.py","docs/market_analysis_contract_v2.json",
                "tools/a5_model_portfolio.py","tools/a4_macro_learning.py","tools/macro_technical_study.py",
                "tools/run_a4_research_cycle.py"}
        def expected(args,**kwargs):return (ROOT/args[2].split(":",1)[1]).read_bytes()
        with patch.object(publisher.subprocess,"check_output",side_effect=expected):
            checked=publisher.verified_source_hashes(CODE_SHA)
        self.assertTrue(native<=set(checked))
        for operand in sorted(native):
            def wrong(args,**kwargs):
                relative=args[2].split(":",1)[1]
                return b"different native code" if relative==operand else (ROOT/relative).read_bytes()
            with patch.object(publisher.subprocess,"check_output",side_effect=wrong):
                with self.assertRaisesRegex(ContractError,"source_differs_from_claimed_commit:"+operand):
                    publisher.verified_source_hashes(CODE_SHA)

    def test_late_confirmation_triggers_once_and_reprints_do_not(self):
        from research.multi_asset_v1.decisions import stock_decision_clock
        _,r,policy=self.inputs();assets={a['asset_id']:a for a in r['assets']}
        profile=policy['stock_cash_research'];profile['cadence']='MONTHLY_CONFIRMED_EVENT'
        def report(ident,at,confirmed,materiality=.8):
            return dict(**{**meta('CANONICAL_NEWS'),'observed_at':at,'available_at':at},
                event_id=ident,published_at=at,event_type='MINE_OUTAGE',confidence=.9,materiality=materiality,
                confirmed=confirmed,thesis_effect='REVIEW_NEGATIVE',estimated_duration='2_WEEKS',
                asset_ids=[],commodity_ids=['COPPER'],theme_ids=[],duplicate_cluster='OUTAGE:1')
        first=report('EVENT:1','2026-09-18T21:00:00Z',False)
        confirmed=report('EVENT:2','2026-09-18T22:00:00Z',True)
        review={'previous_decision_at':'2026-09-18T21:30:00Z'}
        merged=event_memory([confirmed,first],assets,CUTOFF,policy)
        self.assertEqual(merged[0]['first_seen'],first['available_at'])
        self.assertTrue(stock_decision_clock(CUTOFF,profile,review,merged)['scheduled_due'])
        reprint=report('EVENT:3','2026-09-18T23:00:00Z',True)
        unconfirmed=report('EVENT:4','2026-09-19T01:00:00Z',False,1.0)
        review['previous_decision_at']='2026-09-18T22:30:00Z'
        merged=event_memory([reprint,first,unconfirmed,confirmed],assets,CUTOFF,policy)
        self.assertFalse(stock_decision_clock(CUTOFF,profile,review,merged)['scheduled_due'])
        material=report('EVENT:5','2026-09-19T02:00:00Z',True,.9)
        merged=event_memory([material,reprint,first,confirmed],assets,CUTOFF,policy)
        self.assertTrue(stock_decision_clock(CUTOFF,profile,review,merged)['scheduled_due'])

    def test_joint_replacements_recheck_native_concentration(self):
        from research.multi_asset_v1.decisions import _stock_exit,stock_cash_proposal,_stock_replacement_concentration
        p,r,policy=self.inputs();template=run(p,r,policy,artifact_resolver=self.memory)['multi_asset_leadership_latest'][0]
        original_asset=next(a for a in r['assets'] if a['asset_class'] in {'US_EQUITY','COMMODITY_EQUITY'})
        assets={};rows=[]
        sectors=['A','B','C','D','C','C']
        for i,sector in enumerate(sectors):
            aid='US:SYNTH'+str(i);row=copy.deepcopy(template)
            row.update(asset_id=aid,symbol='SYNTH'+str(i),portfolio_status='CANDIDATE')
            record=dict(ticker=row['symbol'],sector=sector,industry_group='INDUSTRY:'+str(i),
                alphaops_vnext_score=1.5 if i>=4 else .2,rs_benchmark_1w=.1,rs_benchmark_3m=.3,
                price_above_ma50=.9,price_above_ma200=.9,rs_sector_3m=.2,industry_group_strength_score=.8,
                portfolio_risk_entry_block_score=0,portfolio_stale_mega_leader_score=0,leader_tier='DUAL_LEADER')
            row['hold_exit_evidence']=dict(security_id=aid,as_of=list(SESSIONS)[-1],available_at=CUTOFF,record=record)
            assets[aid]={**original_asset,'asset_id':aid,'symbol':row['symbol']};rows.append(row)
        by_id={row['asset_id']:row for row in rows};ids=list(by_id)
        current=dict(zip(ids[:4],[.12,.12,.08,.08]));exits=[]
        scored=digest({a:row['hold_exit_evidence']['record'] for a,row in by_id.items()})
        for i in range(2):
            own,other=rows[i],rows[i+4]
            review=dict(taxonomy='REPLACEMENT_EXIT',asset_id=own['asset_id'],reason='NATIVE_REVIEW',
                evaluation_sha256=own['evaluation_sha256'],thesis_id=own['thesis_id'],max_weight=.08,
                available_at=CUTOFF,expires_at='2026-09-20T10:00:00Z',replacement_asset_id=other['asset_id'],
                replacement_evaluation_sha256=other['evaluation_sha256'],scored_cohort_sha256=scored)
            self.assertEqual(_stock_exit(review,own,.12,by_id,CUTOFF,current,None,{})[0],.08)
            exits.append(review)  # Both isolated native transitions really pass.
        rr=copy.deepcopy(p['risk']);rr['max_security_weight']=.2
        rr['stock_cash_allocation'].update(decision_asset_ids=ids,
            evaluation_sha256_by_asset={a:row['evaluation_sha256'] for a,row in by_id.items()},exit_reviews=exits)
        policy['reviewed_pins']['risk'].append(digest(rr))
        with self.assertRaisesRegex(ContractError,'combined_replacement_concentration_worse'):
            stock_cash_proposal(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),current,artifact_resolver=self.memory)
        combined={**current,ids[0]:.08,ids[1]:.08,ids[4]:.04,ids[5]:.04}
        for arm in ('CONTROL','COST_AWARE_LONG_ONLY'):
            with self.assertRaisesRegex(ContractError,'final_replacement_concentration_worse:'+arm):
                _stock_replacement_concentration(current,combined,by_id,'stock_final_replacement_concentration_worse:'+arm)

    def test_carried_etf_has_direct_vehicle_and_leaf_caps(self):
        from research.multi_asset_v1.decisions import stock_cash_proposal
        p,r,policy=self.inputs();rows=run(p,r,policy,artifact_resolver=self.memory)['multi_asset_leadership_latest']
        assets={a['asset_id']:a for a in r['assets']};fund=copy.deepcopy(rows[0]);aid='US:SYNTHFUND'
        fund.update(asset_id=aid,symbol='SYNTHFUND')
        assets[aid]={**assets[rows[0]['asset_id']],'asset_id':aid,'symbol':'SYNTHFUND','asset_class':'ETF','vehicle_type':'EQUITY_ETF'}
        rows.append(fund)
        holding=dict(**meta('ISSUER_HOLDINGS'),fund_id=aid,source_id='ISSUER_HOLDINGS',
            portfolio_scope='FULL_PORTFOLIO',coverage_kind='FULL',weight_unit='FRACTION',
            holdings_as_of=list(SESSIONS)[-1],expected_unique_rows=2,
            rows=[dict(security_id=row['asset_id'],instrument='COMMON',identity_verified=True,weight=.5) for row in rows[:2]])
        policy['reviewed_pins']['holdings'].append(digest(holding))
        exposure=lookthrough({aid:.3},assets,{aid:holding},CUTOFF,policy)
        self.assertTrue(all(value<=.2 for value in exposure['security_exposure'].values()))
        rr=p['risk'];rr['max_security_weight']=.2
        rr['stock_cash_allocation'].update(decision_asset_ids=[row['asset_id'] for row in rows],
            evaluation_sha256_by_asset={row['asset_id']:row['evaluation_sha256'] for row in rows})
        policy['reviewed_pins']['risk'].append(digest(rr))
        with self.assertRaisesRegex(ContractError,'winner_hard_limit_conflict:'+aid):
            stock_cash_proposal(rows,assets,rr,{aid:holding},CUTOFF,policy,feature_identity(p,r),{aid:.3},artifact_resolver=self.memory)

    def test_same_replacement_receives_all_released_weights_and_cap_conflict_blocks(self):
        from research.multi_asset_v1.decisions import stock_cash_proposal,_stock_exit
        p,r,policy=self.inputs();challenger=p['evaluations'][-1]
        delta=.02-challenger['expected_return_12m']
        challenger['expected_return_12m']=.02;challenger['benchmark_expected_return_12m']=-.03
        for scenario in challenger['scenarios']['12m'].values():scenario['return']+=delta
        challenger['portfolio_cost_basis']['gross_expected_return']=.025
        rr=p['risk'];rr['max_security_weight']=.2
        policy['reviewed_pins']['evaluation']=[digest(e) for e in p['evaluations']]
        rr['stock_cash_allocation']['evaluation_sha256_by_asset']={e['asset_id']:digest(e) for e in p['evaluations']}
        policy['reviewed_pins']['risk'].append(digest(rr))
        rows=run(p,r,policy,artifact_resolver=self.memory)['multi_asset_leadership_latest']
        assets={a['asset_id']:a for a in r['assets']};target=rows[-1]['asset_id']
        for i,row in enumerate(rows):
            record=dict(ticker=row['symbol'],sector='SAME',industry_group='SAME',
                alphaops_vnext_score=1.5 if row['asset_id']==target else .2,
                rs_benchmark_1w=.1,rs_benchmark_3m=.3,price_above_ma50=.9,price_above_ma200=.9,
                rs_sector_3m=.2,industry_group_strength_score=.8,portfolio_risk_entry_block_score=0,
                portfolio_stale_mega_leader_score=0,leader_tier='DUAL_LEADER')
            row['hold_exit_evidence']=dict(security_id=row['asset_id'],as_of=list(SESSIONS)[-1],available_at=CUTOFF,record=record)
        by_id={x['asset_id']:x for x in rows};current={row['asset_id']:.08 for row in rows[:-1]}
        scored=digest({a:row['hold_exit_evidence']['record'] for a,row in by_id.items()});exits=[]
        for own in rows[:-1]:
            review=dict(asset_id=own['asset_id'],taxonomy='REPLACEMENT_EXIT',reason='NATIVE_ORIGINAL_REVIEW',
                evaluation_sha256=own['evaluation_sha256'],thesis_id=own['thesis_id'],max_weight=0,
                available_at=CUTOFF,expires_at='2026-09-20T10:00:00Z',replacement_asset_id=target,
                replacement_evaluation_sha256=by_id[target]['evaluation_sha256'],scored_cohort_sha256=scored)
            self.assertEqual(_stock_exit(review,own,.08,by_id,CUTOFF,current,None,{})[0],0)
            exits.append(review)
        rr['stock_cash_allocation']['exit_reviews']=exits;policy['reviewed_pins']['risk'].append(digest(rr))
        result=stock_cash_proposal(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),current,artifact_resolver=self.memory)
        # C's expected return including reference-trade addback is below cash:
        # voluntary optimizer purchases cannot hide a missing replacement floor.
        self.assertLess(by_id[target]['expected_return_12m']+.005,.03)
        for arm in ('CONTROL','COST_AWARE_LONG_ONLY'):
            self.assertAlmostEqual(result['comparisons'][arm]['weights'][target],.16,places=8)
        rr['max_security_weight']=.12;policy['reviewed_pins']['risk'].append(digest(rr))
        for arm in ('CONTROL','COST_AWARE_LONG_ONLY'):
            policy['stock_cash_research']['allocator']=arm
            with self.assertRaisesRegex(ContractError,'winner_hard_limits_require_review'):
                stock_cash_proposal(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),current,artifact_resolver=self.memory)

    def test_zero_capacity_rows_do_not_suppress_active_correlated_entries(self):
        import numpy as np
        from research.multi_asset_v1.decisions import stock_cash_proposal
        def prepared(returns,invalid=False):
            p,r,policy=self.inputs()
            for i,(original,value) in enumerate(zip(p['evaluations'],returns)):
                delta=value-original['expected_return_12m'];original['expected_return_12m']=value
                for scenario in original['scenarios']['12m'].values():scenario['return']+=delta
                original['portfolio_cost_basis']['gross_expected_return']=value+.005
                if invalid and i==0:original['thesis_status']='INVALID'
            policy['reviewed_pins']['evaluation']=[digest(e) for e in p['evaluations']]
            rr=p['risk'];rr['max_security_weight']=.2;rr['max_pair_correlation']=.5
            rr['stock_cash_allocation']['evaluation_sha256_by_asset']={e['asset_id']:digest(e) for e in p['evaluations']}
            policy['reviewed_pins']['risk'].append(digest(rr))
            rows=run(p,r,policy,artifact_resolver=self.memory)['multi_asset_leadership_latest']
            return p,r,policy,rr,rows,{a['asset_id']:a for a in r['assets']}
        p,r,policy,rr,rows,assets=prepared([.6,.2,.2],True)
        own=rows[0];first=rows[1]['asset_id']
        for row in rows:row['daily_log_returns']=list(rows[0]['daily_log_returns'])
        rr['stock_cash_allocation']['exit_reviews']=[dict(asset_id=own['asset_id'],taxonomy='THESIS_EXIT',
            reason='ORIGINAL_THESIS_INVALID',evaluation_sha256=own['evaluation_sha256'],thesis_id=own['thesis_id'],
            max_weight=0,available_at=CUTOFF,expires_at='2026-09-20T10:00:00Z')]
        policy['reviewed_pins']['risk'].append(digest(rr))
        out=stock_cash_proposal(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),{own['asset_id']:.08},artifact_resolver=self.memory)
        for arm in ('CONTROL','COST_AWARE_LONG_ONLY'):
            self.assertNotIn(own['asset_id'],out['comparisons'][arm]['weights'])
            self.assertGreater(out['comparisons'][arm]['weights'][first],0)
        # A is carried, eliminates higher-mu B, but does not correlate with C.
        # The already eliminated B must not become a second ghost constraint.
        p,r,policy,rr,rows,assets=prepared([.2,.6,.4])
        x=np.sin(np.arange(60)*.53);x-=x.mean();x/=np.linalg.norm(x)
        y=np.cos(np.arange(60)*.83);y-=y.mean();y-=x*(x@y);y/=np.linalg.norm(y)
        values=[x,.8*x+.6*y,y]
        for row,series in zip(rows,values):row['daily_log_returns']=[float(value) for value in series*.01]
        correlations=np.corrcoef(values)
        self.assertGreater(correlations[0,1],.5);self.assertGreater(correlations[1,2],.5)
        self.assertLess(abs(correlations[0,2]),.5)
        ids=[row['asset_id'] for row in rows]
        out=stock_cash_proposal(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),{ids[0]:.08},artifact_resolver=self.memory)
        for arm in ('CONTROL','COST_AWARE_LONG_ONLY'):
            self.assertNotIn(ids[1],out['comparisons'][arm]['weights'])
            self.assertGreater(out['comparisons'][arm]['weights'][ids[2]],0)
        with self.assertRaisesRegex(ContractError,'carried_correlation_review_required'):
            stock_cash_proposal(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),
                {ids[0]:.08,ids[1]:.08},artifact_resolver=self.memory)

    def test_unmapped_unknown_survives_real_lag_history_and_scoped_publication(self):
        import tools.run_multi_asset_leadership as publisher
        p,r,policy=self.inputs();unknown='US:UNMAPPED'
        p['base_equity_ids'].append(unknown)
        p['base_universe_receipt']['asset_ids']=sorted(p['base_equity_ids'])
        policy['reviewed_pins']['base_universe'].append(digest(p['base_universe_receipt']))
        for original in p['evaluations']:original['feature_sha256']=feature_identity(p,r)
        policy['reviewed_pins']['evaluation']=[digest(e) for e in p['evaluations']]
        rr=p['risk'];rr['feature_sha256']=feature_identity(p,r)
        rr['stock_cash_allocation']['evaluation_sha256_by_asset']={e['asset_id']:digest(e) for e in p['evaluations']}
        policy['reviewed_pins']['risk'].append(digest(rr))
        current=run(p,r,policy,artifact_resolver=self.memory);history=[]
        for lag in (5,20):
            session=list(SESSIONS)[-1-lag];close=SESSIONS[session];at=(close+timedelta(minutes=1)).isoformat()
            old_rows=[dict(asset_id=row['asset_id'],as_of=session,rank=None,
                RS_composite=None if row['asset_id']==unknown else row['RS_composite']-lag/100,
                latest_session=None if row['asset_id']==unknown else session)
                for row in current['multi_asset_leadership_latest']]
            snapshot=dict(as_of=session,computed_at=at,registry_sha256=digest(r),multi_asset_leadership_latest=old_rows)
            receipt=dict(**{**meta('CANONICAL_HISTORY'),'observed_at':close.isoformat(),
                'available_at':at,'evidence_kind':'PIT_ARCHIVE'},snapshot_sha256=digest(snapshot))
            snapshot['availability_receipt']=receipt
            policy['reviewed_pins']['history_availability'].append(digest(receipt))
            policy['reviewed_pins']['history'].append(digest(snapshot));history.append(snapshot)
        p['history']=history
        with tempfile.TemporaryDirectory() as folder,patch.object(publisher,'verified_source_hashes',
                return_value={'SYNTHETIC:DIRTY_CODE_ONLY':'a'*64}):
            # Only dirty-source attestation is isolated; runtime history checks,
            # publication/readback and all original synthetic PIT receipts run.
            publisher.publish(p,r,policy,Path(folder),'lag-5-20',CODE_SHA,artifact_resolver=self.memory)
            result=publisher.read_latest(Path(folder),consumed_at=CUTOFF)
        self.assertFalse(result['global_ranking_ready'])
        self.assertEqual(len(result['multi_asset_leadership_latest']),4)
        stub=next(row for row in result['multi_asset_leadership_latest'] if row['asset_id']==unknown)
        for key in ('RS_composite','rank','rank_change_5d','rank_change_20d','score_change_5d','score_change_20d'):
            self.assertIsNone(stub[key])
        known=next(row for row in result['multi_asset_leadership_latest'] if row['asset_id']!=unknown)
        self.assertAlmostEqual(known['score_change_5d'],.05)
        self.assertAlmostEqual(known['score_change_20d'],.20)

    def test_reviewed_group_risk_trim_replays_ceiling_without_selling_unreviewed_winner(self):
        from research.multi_asset_v1.decisions import stock_cash_proposal
        p,r,policy=self.inputs();ids=[e['asset_id'] for e in p['evaluations'][:2]]
        for asset in r['assets']:
            if asset['asset_id'] in ids:asset['risk_group_ids']=['SYNTHETIC:GROUP']
        for original in p['evaluations']:original['feature_sha256']=feature_identity(p,r)
        policy['reviewed_pins']['evaluation']=[digest(e) for e in p['evaluations']]
        rr=p['risk'];rr.update(feature_sha256=feature_identity(p,r),max_gross=.4,max_security_weight=.2)
        rr['risk_group_limits']['SYNTHETIC:GROUP']=.2
        rr['stock_cash_allocation']['evaluation_sha256_by_asset']={e['asset_id']:digest(e) for e in p['evaluations']}
        policy['reviewed_pins']['risk'].append(digest(rr))
        result=run(p,r,policy,artifact_resolver=self.memory)
        rows=[row for row in result['multi_asset_leadership_latest'] if row['asset_id'] in ids]
        assets={a['asset_id']:a for a in r['assets']};current={aid:.15 for aid in ids}
        self.assertLess(sum(current.values()),rr['max_gross'])
        self.assertLess(max(current.values()),rr['max_security_weight'])
        self.assertAlmostEqual(lookthrough(current,assets,{},CUTOFF,policy)['risk_group_exposure']['SYNTHETIC:GROUP'],.30)
        def review(row,target):
            return dict(asset_id=row['asset_id'],taxonomy='RISK_EXIT',reason='REVIEWED_ORIGINAL_GROUP_CEILING',
                evaluation_sha256=row['evaluation_sha256'],thesis_id=row['thesis_id'],max_weight=target,
                available_at=CUTOFF,expires_at='2026-09-20T10:00:00Z',risk_feature_sha256=digest({k:row.get(k)
                    for k in ('expected_drawdown','downside_probability','RS120','RS240')}))
        packet=rr['stock_cash_allocation'];packet.update(decision_asset_ids=ids,
            evaluation_sha256_by_asset={row['asset_id']:row['evaluation_sha256'] for row in rows},
            exit_reviews=[review(row,.10) for row in rows])
        def execute():
            policy['reviewed_pins']['risk'].append(digest(rr))
            return stock_cash_proposal(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),current,artifact_resolver=self.memory)
        trimmed=execute()
        for arm in ('CONTROL','COST_AWARE_LONG_ONLY'):
            for aid in ids:self.assertAlmostEqual(trimmed['comparisons'][arm]['weights'][aid],.10)
        # Existing intact winners retain their floor unless each applicable
        # partial trim has its own reviewed, exactly recomputable RISK_EXIT.
        self.assertTrue(all(row['thesis_status'] in {'POSITIVE','INTACT'} for row in rows))
        original=copy.deepcopy(packet['exit_reviews']);packet['exit_reviews']=original[:1]
        with self.assertRaisesRegex(ContractError,'winner_hard_limits_require_review'):execute()
        packet['exit_reviews']=copy.deepcopy(original);packet['exit_reviews'][0]['max_weight']=0
        with self.assertRaisesRegex(ContractError,'risk_exit_not_recomputed_ceiling'):execute()
        packet['exit_reviews']=copy.deepcopy(original);rr['risk_group_limits']['SYNTHETIC:GROUP']=.4
        with self.assertRaisesRegex(ContractError,'risk_exit_not_recomputed_ceiling'):execute()

    def test_reviewed_lookthrough_risk_trim_needs_original_holdings(self):
        from research.multi_asset_v1.decisions import stock_cash_proposal,_stock_exit
        p,r,policy=self.inputs();native=run(p,r,policy,artifact_resolver=self.memory)['multi_asset_leadership_latest']
        direct=native[0];fund=copy.deepcopy(native[1]);aid='US:SYNTHRISKFUND'
        fund.update(asset_id=aid,symbol='SYNTHRISKFUND');rows=[direct,fund]
        assets={a['asset_id']:a for a in r['assets']}
        assets[aid]={**assets[direct['asset_id']],'asset_id':aid,'symbol':fund['symbol'],
            'asset_class':'ETF','vehicle_type':'EQUITY_ETF'}
        holding=dict(**meta('ISSUER_HOLDINGS'),fund_id=aid,source_id='ISSUER_HOLDINGS',
            portfolio_scope='FULL_PORTFOLIO',coverage_kind='FULL',weight_unit='FRACTION',
            holdings_as_of=list(SESSIONS)[-1],expected_unique_rows=1,
            rows=[dict(security_id=direct['asset_id'],instrument='COMMON',identity_verified=True,weight=1.0)])
        policy['reviewed_pins']['holdings'].append(digest(holding));holdings={aid:holding}
        current={direct['asset_id']:.15,aid:.15};rr=p['risk'];rr['max_security_weight']=.2
        rr['risk_multipliers']['ETF']=1
        exposure=lookthrough(current,assets,holdings,CUTOFF,policy)
        self.assertAlmostEqual(exposure['security_exposure'][direct['asset_id']],.30)
        self.assertTrue(all(value<=rr['risk_group_limits'][group] for group,value in exposure['risk_group_exposure'].items()))
        exits=[dict(asset_id=row['asset_id'],taxonomy='RISK_EXIT',reason='REVIEWED_ORIGINAL_LEAF_CEILING',
            evaluation_sha256=row['evaluation_sha256'],thesis_id=row['thesis_id'],max_weight=.1,
            available_at=CUTOFF,expires_at='2026-09-20T10:00:00Z',risk_feature_sha256=digest({k:row.get(k)
                for k in ('expected_drawdown','downside_probability','RS120','RS240')})) for row in rows]
        rr['stock_cash_allocation'].update(decision_asset_ids=[row['asset_id'] for row in rows],
            evaluation_sha256_by_asset={row['asset_id']:row['evaluation_sha256'] for row in rows},exit_reviews=exits)
        policy['reviewed_pins']['risk'].append(digest(rr))
        result=stock_cash_proposal(rows,assets,rr,holdings,CUTOFF,policy,feature_identity(p,r),current,artifact_resolver=self.memory)
        for arm in ('CONTROL','COST_AWARE_LONG_ONLY'):
            weights=result['comparisons'][arm]['weights']
            for security in current:self.assertAlmostEqual(weights[security],.1)
            self.assertAlmostEqual(lookthrough(weights,assets,holdings,CUTOFF,policy)['security_exposure'][direct['asset_id']],.2)
        with self.assertRaisesRegex(ContractError,'missing_etf_holdings'):
            stock_cash_proposal(rows,assets,rr,{},CUTOFF,policy,feature_identity(p,r),current,artifact_resolver=self.memory)
        with self.assertRaisesRegex(ContractError,'original_exposure_context_required'):
            _stock_exit(exits[0],direct,.15,{row['asset_id']:row for row in rows},CUTOFF,current,None,rr)


if __name__=="__main__":unittest.main()
