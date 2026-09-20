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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research.multi_asset_v1.contracts import ContractError,digest,encoded,load_json,metadata,registry_rows
from research.multi_asset_v1.prices import grid,admit_prices
from research.multi_asset_v1.runtime import run,feature_identity
from research.multi_asset_v1.decisions import classify,evaluation,event_memory,lookthrough,propose
from tools.run_multi_asset_leadership import parse_chart,publish,read_latest
from research.multi_asset_v1.sources import candles,capture_spot_metrics,crypto_chart

CUTOFF="2026-09-19T10:00:00+00:00"
SESSIONS=grid(CUTOFF)


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
    policy["validated_models"]={"TEST_MODEL":{"asset_classes":["US_EQUITY","COMMODITY_EQUITY"],"validation_sha256":"c"*64}}
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
        policy["reviewed_pins"]["evaluation"].append(digest(e))
        p["evaluations"].append(e)
    receipt={"asset_ids":sorted(p["base_equity_ids"]),"as_of":list(SESSIONS)[-1]}
    p["base_universe_receipt"]=receipt
    policy["reviewed_pins"]["base_universe"].append(digest(receipt))
    return p,r,policy


def risk(p,r,policy):
    risk=dict(**meta("REVIEWED_RISK"),feature_sha256=feature_identity(p,r),regime="RISK_OFF",max_gross=.4,max_security_weight=.1,max_pair_correlation=1.0,minimum_expected_alpha=.01,risk_multipliers={"US_EQUITY":1,"COMMODITY_EQUITY":1},risk_group_limits={g:.3 for a in r["assets"] for g in a["risk_group_ids"]})
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
        self.r["assets"][0]["tradable"]="true"
        with self.assertRaises(ContractError):registry_rows(self.r)

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
        self.p["metrics"]=[dict(**meta("REVIEWED_NETWORK"),subject_id="BTC",metric="net_issuance",unit="TOKEN",value=0)]
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
        for x in self.p["prices"]:x["return_basis"]="PROVIDER_ADJUSTED_CLOSE_PROXY"
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
        with self.assertRaisesRegex(ContractError,"mixed_return_basis"):admit_prices(rows,a,CUTOFF,self.policy,SESSIONS)


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
                with self.assertRaises(ContractError):evaluation(e,a,CUTOFF,self.policy,feature_identity(self.p,self.r))

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
        row=dict(asset_id="US:FTI",portfolio_status="CANDIDATE",expected_alpha_12m=.3,liquidity_pass=True,RS20_change_5d=.1,RS60_change_5d=.1,RS120=.1,RS240=.1,signal_confidence=.8,thesis_confidence=.8,expected_drawdown=.2,daily_log_returns=[math.sin(i) for i in range(60)])
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
            out=Path(temp);publish(p,r,policy,out,"one","fixture-code")
            saved=(out/"last_success.json").read_bytes();result=(out/"attempts/one/result.json").read_bytes()
            bad=copy.deepcopy(p);bad["schema"]="wrong"
            with self.assertRaises(ContractError):publish(bad,r,policy,out,"two","fixture-code")
            self.assertEqual((out/"last_success.json").read_bytes(),saved)
            self.assertEqual((out/"attempts/one/result.json").read_bytes(),result)
            with self.assertRaises(ContractError):read_latest(out)

    def test_result_tampering_rejected(self):
        p,r,policy=reviewed(*fixture());risk(p,r,policy)
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);publish(p,r,policy,out,"one","fixture-code")
            (out/"attempts/one/result.json").write_text('{}')
            with self.assertRaisesRegex(ContractError,"tampered"):read_latest(out)

    def test_complete_rank_with_missing_or_invalid_risk_is_not_consumable(self):
        p,r,policy=reviewed(*fixture());risk(p,r,policy)
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);publish(p,r,policy,out,"good","fixture-code")
            self.assertEqual(read_latest(out)["proposal"]["status"],"RESEARCH_PROPOSAL")
            saved=(out/"last_success.json").read_bytes()
            for mode in ("missing","invalid"):
                with self.subTest(mode=mode):
                    bad=copy.deepcopy(p)
                    if mode=="missing":bad.pop("risk")
                    else:bad["risk"]["max_gross"]=.9
                    result=publish(bad,r,policy,out,mode,"fixture-code")
                    self.assertTrue(result["global_ranking_ready"])
                    self.assertEqual(result["proposal"]["status"],"BLOCKED")
                    self.assertEqual((out/"last_success.json").read_bytes(),saved)
                    with self.assertRaisesRegex(ContractError,"not_ready"):read_latest(out)
                    for name,obj in (("input",bad),("registry",r),("policy",policy)):
                        (out/(name+".json")).write_bytes(encoded(obj))
                    proc=subprocess.run([sys.executable,str(ROOT/"tools/run_multi_asset_leadership.py"),"--input",str(out/"input.json"),"--expected-input-sha256",hashlib.sha256(encoded(bad)).hexdigest(),"--registry",str(out/"registry.json"),"--policy",str(out/"policy.json"),"--output-dir",str(out),"--attempt-id",mode+"-cli"],capture_output=True,text=True)
                    self.assertEqual(proc.returncode,2,proc.stdout+proc.stderr)
                    self.assertEqual((out/"last_success.json").read_bytes(),saved)

    def test_cli_missing_input_revokes_prior_success(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);(out/"latest_attempt.json").write_text('{"global_ranking_ready":true}')
            proc=subprocess.run([sys.executable,str(ROOT/"tools/run_multi_asset_leadership.py"),"--input",str(out/"missing.json"),"--output-dir",str(out),"--attempt-id","missing"],capture_output=True,text=True)
            self.assertEqual(proc.returncode,2)
            self.assertEqual(json.loads((out/"latest_attempt.json").read_bytes())["status"],"BLOCKED")

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


if __name__=="__main__":unittest.main()
