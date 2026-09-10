#!/usr/bin/env python3
"""Run connected REAL observations through the pinned H1/H2 admission path.

This probe does not invent missing underwriting or label provider bar closes
as independently verified exchange auction prices. It records engine blockers.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ENGINE_COMMIT='3eb068e76d676ec3fc75288b645db8448615aa2d'
ENGINE_DIGEST='e950124946fe73136d78175f3f1bc0311abbb8aba8e06d5c811591ff61926fdb'
MODULES='__init__ currency data engine fund_metrics fund_replay io platform_io portfolio quality quality_bridge quality_index valuation'.split()


def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(x):return hashlib.sha256(x).hexdigest()
def require(ok,reason):
    if not ok:raise ValueError(reason)


def load_engine(root):
    root=Path(root).resolve()
    package=root/'tools/research_decision_v1'
    require(not (root/'tools/__init__.py').exists(),'unexpected_tools_initializer')
    require({p.stem for p in package.glob('*.py')}==set(MODULES),'engine_module_set')
    paths=['tools/research_decision_v1/'+m+'.py' for m in MODULES]+['docs/research_fund_replay_config.json']
    require(not any((root/p).is_symlink() for p in paths),'engine_symlink')
    hashes={p:sha((root/p).read_bytes()) for p in paths}
    require(sha(canonical(hashes))==ENGINE_DIGEST,'engine_source_digest')
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(root))
    from tools.research_decision_v1 import data,engine
    require(Path(data.__file__).resolve()==package/'data.py','engine_import_origin')
    return data,engine,json.loads((root/'docs/research_fund_replay_config.json').read_text())


def verify_capture(root):
    root=Path(root).resolve()
    report=json.loads((root/'connection_report.json').read_text())
    receipts=json.loads((root/'receipts.json').read_text())
    require(report['schema_version']=='research-source-connection-v1' and report['data_kind']=='REAL','real_capture_required')
    require(len(receipts)==report['source_receipt_count'] and sha(canonical(receipts))==report['source_receipts_hash'],'receipt_binding')
    for r in receipts:
        h=r['raw_sha256'];require(len(h)==64 and set(h)<=set('0123456789abcdef'),'raw_digest_format')
        p=root/(h+'.raw');require(not p.is_symlink(),'raw_symlink')
        raw=p.read_bytes();require(len(raw)==r['bytes'] and sha(raw)==h,'raw_source_mutated')
    return report


def run(capture,engine_root):
    report=verify_capture(capture)
    data,engine,config=load_engine(engine_root)
    profile=report.get('market_profile')
    extension_hash=None
    if profile=='US_LISTED_USD_V1':
        # A checked-in, inspectable entry point replaces the obsolete fixed 5+2
        # contract. The verified core is not edited or monkey-patched.
        extension=Path(__file__).resolve().with_name('research_us_decision.py')
        config_path=Path(__file__).resolve().parents[1]/'docs/research_us_fund_config.json'
        require(not extension.is_symlink() and not config_path.is_symlink(),'profile_symlink')
        extension_hash=sha(extension.read_bytes())
        spec=importlib.util.spec_from_file_location('research_us_decision',extension)
        engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
        config=json.loads(config_path.read_text());engine.validate_config(config)
    else:require(profile is None,'unknown_market_profile')
    cutoff=report['generated_at']
    src={s['name']:s for s in report['sources']}
    us=src.get('US_prices',{}).get('data',{}).get('securities',[])
    kr=src.get('KR_current_close',{}).get('data',{}).get('selected',[])
    if profile=='US_LISTED_USD_V1':require(not kr,'us_profile_foreign_input')
    financial={r['name']:r.get('data') for r in src.get('SEC_facts',{}).get('data',[])}
    bundles=[]
    for market,currency,quotes in [('US','USD',us),('KR','KRW',kr)]:
        securities=[]
        for q in quotes:
            if q['ticker']=='SPY':continue
            ticker=q['ticker']
            # These are observations with explicit outstanding transformations,
            # not fabricated H1 blocks with approval flags set to true.
            blocks={'price':{'status':'unverified','reason':'raw_actions_and_official_close_reconciliation_pending',
                              'payload':{'observed_close':q['close'],'observed_session':q.get('last',q.get('session'))}},
                    'financials':{'status':'unverified' if financial.get(ticker) else 'missing',
                                  'reason':'complete_financial_packet_and_publication_binding_pending'},
                    'thesis':{'status':'missing','reason':'complete_company_review_pending'},
                    'risk':{'status':'missing','reason':'common_exposure_and_stress_review_pending'},
                    'scenario':{'status':'missing','reason':'reviewed_12_month_underwriting_pending'}}
            if financial.get(ticker):blocks['financials']['payload']=financial[ticker]['financial_metrics']
            securities.append(dict(security_id=market+':'+ticker,ticker=ticker,market=market,currency=currency,blocks=blocks))
        if securities:
            bundle=dict(schema_version='research-input-v1',data_kind='REAL',market=market,decision_cutoff=cutoff,securities=securities)
            bundles.append(data.export_market(bundle,market))
    require(bundles,'no_connected_securities')
    context=dict(mode='NEW_CAPITAL_RESEARCH',capital_is_assumption=True,base_currency='USD',capital_base=100000.,
                 decision_cutoff=cutoff,fx={'status':'missing'},regime={'state':'UNKNOWN'},benchmark_expected_returns={})
    quality=dict(schema_version='research-quality-bundle-v1',data_kind='REAL',decision_cutoff=cutoff,assessments={})
    decision=engine.run_decisions(bundles,context,config,quality_bundle=quality)
    proposal=decision['portfolio_proposal']
    # A blocked proposal's internal account assumption must not be reported as
    # a chosen 100% cash position or as a realized backtest result.
    output=dict(schema_version='connected-research-admission-v1',engine_commit=ENGINE_COMMIT,engine_source_digest=ENGINE_DIGEST,
        data_kind='REAL',source_receipts_hash=report['source_receipts_hash'],decision_cutoff=cutoff,price_through=report['end'],
        collection_scope=report.get('collection_scope','connection_sample'),
        market_profile=profile,decision_extension_sha256=extension_hash,effective_config_hash=data.digest(config),
        country_caps=config['country_caps'],target_counts=config['target_counts'],
        workflow=decision['workflow'],readiness=decision['readiness'],coverage=decision['coverage'],
        portfolio_weights=proposal['rows'] if proposal['ready'] else None,
        proposal_blockers=proposal.get('blockers',proposal.get('reasons',[])),
        decision_hash=decision['decision_hash'],historical_replay_completed=False,metrics=None,orders_allowed=False)
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',required=True);p.add_argument('--engine-source',required=True);p.add_argument('--report',required=True)
    a=p.parse_args();result=run(a.capture,a.engine_source)
    if result['collection_scope'] in ('current_markets','us_listed'):
        # Full company-by-company diagnostics stay beside the private inputs.
        path=Path(a.capture).resolve()/'admission_report.json'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as out:out.write(canonical(result))
        coverage=result.pop('coverage')
        result['coverage_count']=len(coverage)
        result['blocker_counts']=dict(Counter(b for row in coverage for b in row.get('blockers',[])))
    Path(a.report).write_bytes(canonical(result)+b'\n');print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__':raise SystemExit(main())
