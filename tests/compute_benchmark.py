"""Synthetic compute benchmark of the REAL M0-A callable, not investment alpha."""
from __future__ import annotations
import argparse
import copy
from datetime import date, timedelta
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from research_only.mission_v3 import compute_runtime as c
from research_only.mission_v3 import compute_m0 as m
from research_only.mission_v3 import mission_metrics as old


def fixture(cases):
    dates=[]; d=date.fromisoformat(old.REFERENCE['start']); end=date.fromisoformat(old.REFERENCE['end'])
    while d<=end:
        if d.weekday()<5: dates.append(d.isoformat())
        d+=timedelta(days=1)
    plan={'schema_version':m.PLAN_SCHEMA,'universe_ids':[f'SYNTH:{i:04d}' for i in range(1118)],
          'decision_cutoff':'2026-09-16T20:00:00Z','report_title':'synthetic compute benchmark','entries':[]}
    blobs={}
    for i in range(cases):
        bundle={'contract':dict(old.REFERENCE),'sessions':dates,'portfolios':{}}
        for sleeve in ('main','concentrated'):
            meta={k:'b'*64 for k in old.META_KEYS if k.endswith('sha256')}
            meta.update(sleeve=sleeve,run_id='synthetic',source_commit='a'*40,currency='USD',
                        sampling='DAILY_EOD_LEDGER',nav_basis='NET_WITHOUT_EXTERNAL_FLOWS')
            rng=random.Random(91500+i*2+(sleeve=='concentrated')); cents=10000000; rows=[]
            for index,day in enumerate(dates):
                if index: cents=max(1,cents*(10000+rng.randrange(-110,120))//10000)
                rows.append({'date':day,'nav':f'{cents//100}.{cents%100:02d}','external_flow':0})
            bundle['portfolios'][sleeve]={'metadata':meta,'nav_rows':rows}
        identity=f'case{i:03d}'; blob=c.canonical(bundle); blobs[identity]=blob
        plan['entries'].append({'id':identity,'path':f'inputs/{identity}.json','sha256':c.sha(blob)})
    return plan,blobs,len(dates)


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--cases',type=int,default=32); args=p.parse_args()
    c.need(2<=args.cases<=128,'CASES_LIMIT'); c.need(not args.out.exists(),'OUT_EXISTS')
    args.out.mkdir(parents=True)
    plan,blobs,sessions=fixture(args.cases); tasks=m.build_tasks(plan,blobs); registry=m.operators()
    results={}
    def execute(label,ts,cache,workers=1,stop=None):
        value=c.run(ts,registry,args.out/cache,workers=workers,stop_after_tasks=stop)
        receipt={k:v for k,v in value.items() if k!='outputs'}
        (args.out/f'{label}.json').write_bytes(c.canonical(receipt))
        results[label]={'status':value['status'], **value['stats'], 'semantic_output_hash':value['semantic_output_hash']}
        return value
    serial=execute('cold_1',tasks,'cache_1',1)
    par2=execute('cold_2',tasks,'cache_2',2)
    par4=execute('cold_4',tasks,'cache_4',4)
    warm=execute('warm_4',tasks,'cache_4',4)
    c.need(serial['outputs']==par2['outputs']==par4['outputs']==warm['outputs'],'PARITY_FAILURE')
    execute('interrupted',tasks,'cache_resume',2,max(1,args.cases//4))
    resumed=execute('resumed_4',tasks,'cache_resume',4)
    c.need(resumed['outputs']==serial['outputs'],'RESUME_PARITY_FAILURE')
    changed_plan=copy.deepcopy(plan); changed_blobs=dict(blobs)
    identity=changed_plan['entries'][0]['id']; bundle=json.loads(changed_blobs[identity])
    bundle['portfolios']['main']['nav_rows'][-1]['nav']='99999.00'
    changed_blobs[identity]=c.canonical(bundle); changed_plan['entries'][0]['sha256']=c.sha(changed_blobs[identity])
    changed=m.build_tasks(changed_plan,changed_blobs)
    one=execute('one_bundle_changed',changed,'cache_4',4)
    fresh=execute('changed_fresh_1',changed,'cache_changed_fresh',1)
    c.need(one['outputs']==fresh['outputs'],'INCREMENTAL_PARITY_FAILURE')
    changed_plan['report_title']='changed report title only'
    title=execute('report_only_changed',m.build_tasks(changed_plan,changed_blobs),'cache_4',4)
    c.need(one['stats']['computed']==2 and title['stats']['computed']==1,'INVALIDATION_FAILURE')
    summary={'mode':'SYNTHETIC_COMPUTE_BENCHMARK_NOT_STRATEGY_BACKTEST','cases':args.cases,
             'supplied_weekday_sessions':sessions,'is_exchange_calendar':False,
             'plan_input_bytes':sum(map(len,blobs.values())), 'universe_ids':1118,
             'universe_ids_are_synthetic':True, 'parity':'PASS','results':results,
             'network_requests':0,'mission_status':'NOT_PROVEN', 'orders_allowed':False}
    (args.out/'benchmark_summary.json').write_bytes(c.canonical(summary))
    print(json.dumps(summary,indent=2,sort_keys=True))


if __name__=='__main__': main()
