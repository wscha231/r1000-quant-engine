"""Reuse immutable captures, evaluate every horizon and attempt the US replay.

Outputs distinguish an integrated fund result from a benchmark reference. No
cash-only curve or survivor-selected stock result replaces missing fund inputs.
"""
import argparse
from collections import Counter
from datetime import datetime,timedelta,timezone
import json
import math
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from admit_connected_research import verify_capture,load_engine,canonical,sha
from research_rs_horizons import analyze
from research_source_connection import financial_packet
from research_interim_financials import current_packets


def rebound_inputs(root,report):
    """Rebuild observations from receipt-bound raw bytes, not loose derivatives."""
    receipts=json.loads((root/'receipts.json').read_text());bars={'raw':{},'all':{}};rates=[]
    universe=report.get('universe',{});members=universe.get('members',[])
    iwb={};sec=None
    for r in receipts:
        name=r['name'];raw=(root/(r['raw_sha256']+'.raw')).read_bytes()
        if name in ('alpaca_raw','alpaca_all'):
            target=bars[name.removeprefix('alpaca_')]
            for ticker,rows in json.loads(raw)['bars'].items():target.setdefault(ticker,[]).extend(rows)
        elif name.startswith('fred_initial_DGS3MO_'):rates.extend(json.loads(raw)['observations'])
        elif name=='iwb_current_membership':
            from research_universe_connection import parse_iwb
            iwb={r['ticker']:r for r in parse_iwb(raw,report['end'])['members']}
        elif name=='sec_exchange_membership':
            from research_universe_connection import parse_sec_exchange
            sec=parse_sec_exchange(json.loads(raw))
    if report.get('market_profile')=='US_LISTED_USD_V1':
        from research_universe_connection import adr_candidates,US_EXCHANGES
        seeds,provenance=adr_candidates()
        old=next(s['data']['seed_provenance'] for s in universe['sources'] if s['name']=='US_FOREIGN')
        if old!=provenance or sec is None or not iwb:raise ValueError('universe_raw_binding')
        expected=set(iwb)|{r['ticker'] for r in seeds if not r.get('skip') and
            r['ticker'] in sec and sec[r['ticker']]['exchange'] in US_EXCHANGES}
        if len(members)!=len(expected) or {r['ticker'] for r in members}!=expected:
            raise ValueError('universe_raw_binding')
    # Restore IWB sector labels for overlapping foreign candidates from the
    # original CSV. Older merged snapshots overwrote those with seed labels.
    members=[dict(m,sector=iwb[m['ticker']]['sector'],candidate_origins=['US_IWB'])
        if m['ticker'] in iwb else dict(m,candidate_origins=['US_FOREIGN']) for m in members]
    captured=json.loads((root/'bars.json').read_text())
    for basis in ('raw','all'):
        # Provider omits symbols with no observations. Preserve explicit empty
        # source candidates, but reject any changed or added nonempty series.
        actual={t:r for t,r in captured[basis].items() if r}
        if actual!={t:r for t,r in bars[basis].items() if r}:raise ValueError('normalized_bars_raw_binding')
    return bars,members,list({canonical(r):r for r in rates}.values())


def fact_diagnostics(root,report):
    receipts=json.loads((root/'receipts.json').read_text())
    output=[]
    for r in receipts:
        if not r['name'].startswith('sec_facts_'):continue
        ticker=r['name'].removeprefix('sec_facts_');facts=json.loads((root/(r['raw_sha256']+'.raw')).read_text())
        packet=financial_packet(facts,report['end'],ticker)
        # Expose tag/date availability, not whole raw statements. This identifies
        # stale mappings separately from genuinely missing source documents.
        tags=[]
        for ns,group in facts.get('facts',{}).items():
            for tag,entry in group.items():
                if not any(word in tag.lower() for word in ('revenue','profitloss','netincome','propertyplant','cashflow','operatingactivities')):continue
                for unit,values in entry.get('units',{}).items():
                    known=[v for v in values if v.get('filed','9999')<=report['end']]
                    if known:tags.append(dict(namespace=ns,tag=tag,unit=unit,latest_end=max(v['end'] for v in known)))
        output.append(dict(ticker=ticker,ttm_fields=[k for k,v in packet['financial_metrics'].items() if v],
            annual_fields=list(packet['latest_annual_metrics']),reporting=packet['reporting'],tag_coverage=tags,
            current_h1_packet_complete=False))
    return output


def benchmark_reference(bars,rates,start,end):
    from tools.research_decision_v1.fund_metrics import metrics
    from tools.research_decision_v1.data import session_close,sessions
    bars=bars['all']['SPY']
    selected=[r for r in bars if start<=r['t'][:10]<=end]
    expected=sessions('US',start,end+'T23:59:59Z')
    if tuple(r['t'][:10] for r in selected)!=expected:raise ValueError('benchmark_session_gap')
    rates=sorted([r for r in rates if r.get('value') not in ('.','',None)],key=lambda r:r['realtime_start'])
    import pandas_market_calendars as mcal
    schedule=mcal.get_calendar('NYSE').schedule(start_date=start,end_date=end)
    closes={d.date().isoformat():r['market_close'].to_pydatetime() for d,r in schedule.iterrows()}
    first=closes[expected[0]];base=selected[0]['c'];fee=.0025
    curve=[dict(time=(first-timedelta(seconds=1)).isoformat(),equity_usd=100000.,cash_usd=0.,risk_free_return=0.)]
    for row in selected:
        stamp=closes[row['t'][:10]];last=datetime.fromisoformat(curve[-1]['time'])
        # A release date is not an intraday timestamp. Use the previous fully
        # completed UTC release day, disclosed as a conservative RF convention.
        available=[r for r in rates if r['realtime_start']<last.date().isoformat()]
        if not available:raise ValueError('benchmark_risk_free_missing')
        annual=float(available[-1]['value'])/100.
        rf=(1+annual)**((stamp-last).total_seconds()/(365.25*86400))-1.
        curve.append(dict(time=stamp.isoformat(),equity_usd=100000./(1+fee)*row['c']/base,
            cash_usd=0.,risk_free_return=rf))
    result=metrics(curve)
    return dict(status='COMPLETED_BENCHMARK_REFERENCE',ticker='SPY',start=start,end=end,
        methodology='provider_adjusted_total_return_proxy; fractional benchmark units; 25bps initial cost; no final liquidation',
        risk_free_method='DGS3MO initial-release dates lagged to completed UTC day; ACT/365.25 compounding approximation',
        strategy_result=False,metrics=result,equity_curve=curve)


def run(current,sample,output,fund_manifest=None,extend_rs=False):
    current,sample,output=map(Path,(current,sample,output));output.mkdir(parents=True,exist_ok=True)
    reports=[verify_capture(p) for p in (current,sample)]
    here=Path(__file__).resolve().parents[1];data,_,_=load_engine(here)
    import research_us_fund_replay as replay
    report=reports[0];end=report['end'];start='2019-06-03'
    bars,members,_=rebound_inputs(current,report)
    sample_bars,_,rates=rebound_inputs(sample,reports[1])
    extension=None
    if extend_rs:
        from extend_us_rs_history import extend,persist,merge_histories
        cached=current.parent/'rs_extension'
        if cached.is_dir():
            cached_report=verify_capture(cached)
            older,_,_=rebound_inputs(cached,cached_report)
            bars,statuses=merge_histories(bars,older,report['start'])
            extension=dict(cached_report,reused=True,merge_counts=dict(Counter(statuses.values())),
                overlap_conflicts=[t for t,s in statuses.items() if s=='source_overlap_conflict'],
                private_persistence={'status':'RESTORED_VERIFIED_PRIVATE_EXTENSION'})
        else:
            private=output.parent/'us-rs-extension-private'
            bars,extension=extend(bars,report,private)
            extension['private_persistence']=persist(private)
        (output/'rs_extension_report.json').write_bytes(canonical(extension))
    rs=analyze(bars['all'],members,end)
    (output/'all_us_relative_strength.json').write_bytes(canonical(rs))
    financial=fact_diagnostics(current,report)+fact_diagnostics(sample,reports[1])
    (output/'financial_mapping_diagnostics.json').write_bytes(canonical(financial))
    interim=current_packets(datetime.now(timezone.utc).isoformat())
    (output/'current_interim_financials.json').write_bytes(canonical(interim))
    benchmark=benchmark_reference(sample_bars,rates,start,end)
    (output/'benchmark_reference.json').write_bytes(canonical(benchmark))
    config=json.loads((here/'docs/research_us_fund_config.json').read_text())
    manifest_path=Path(fund_manifest) if fund_manifest else current/'fund_manifest.json'
    if manifest_path.is_file():
        manifest,events,loader=replay.load_history(manifest_path)
        result=replay.replay(manifest,events,config,loader)
    else:
        result=dict(schema_version='fund-manager-replay-v1',status='BLOCKED',data_kind='REAL',
            base_currency='USD',objective='after_cost_usd_cagr',metrics=None,
            reason='fund_chronological_manifest_missing',orders_allowed=False,
            missing=['historical_date_indexed_eligible_universe','normalized_publication_timed_financial_packets',
                'complete_raw_price_and_held_action_cashflows','reviewed_historical_underwriting_and_regime_packets'])
    result.update(candidate_id='US_INTEGRATED_QUALITY_V1_20260910',requested_start=start,requested_end=end,
        starting_capital_usd=100000.,source_receipts_hashes=[r['source_receipts_hash'] for r in reports],
        us_config_hash=data.digest(config))
    (output/'integrated_fund_result.json').write_bytes(canonical(result))
    (output/'integrated_fund_result.md').write_text(replay.render(result))
    leaders={str(n):[dict(ticker=r['ticker'],excess_return_pp=r['horizons'][str(n)]['excess_return_pp'],
        percentile=r['horizons'][str(n)]['market_percentile']) for r in sorted(
        [r for r in rs['rows'] if r['horizons'][str(n)]['status']=='available'],
        key=lambda r:(-r['horizons'][str(n)]['excess_return_pp'],r['ticker']))[:10]] for n in rs['horizons']}
    summary=dict(schema_version='us-research-continuation-v1',as_of=end,candidate_count=rs['candidate_count'],
        rs_extension=extension,
        rs_coverage=rs['coverage'],strength_states=rs['state_counts'],leaders=leaders,
        financial_coverage=[{k:v for k,v in r.items() if k!='tag_coverage'} for r in financial],
        priority_tag_diagnostics=[r for r in financial[:2]],
        priority_strength=[r for r in rs['rows'] if r['ticker'] in ('TSM','ASML','NVDA','MU','DELL','BE')],
        current_interim_financials=interim,
        integrated_fund=result,benchmark_reference={k:v for k,v in benchmark.items() if k!='equity_curve'})
    # Keep the log concise; detailed derived outputs are separate artifacts.
    summary['benchmark_reference']['metrics']={k:v for k,v in benchmark['metrics'].items()
        if k not in ('daily_drawdown','rolling_12m','rolling_36m')}
    (output/'summary.json').write_bytes(canonical(summary));print(json.dumps(summary,sort_keys=True))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--current',required=True);p.add_argument('--sample',required=True);p.add_argument('--output',required=True)
    p.add_argument('--fund-manifest');p.add_argument('--extend-rs',action='store_true');a=p.parse_args()
    run(a.current,a.sample,a.output,a.fund_manifest,a.extend_rs)

if __name__=='__main__':main()
