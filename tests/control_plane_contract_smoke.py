#!/usr/bin/env python3
from __future__ import annotations
import json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
CP=ROOT/'research_only'/'control_plane'
HEX40=re.compile(r'^[0-9a-f]{40}$')
HEX64=re.compile(r'^[0-9a-f]{64}$')
def load(n): return json.loads((CP/n).read_text(encoding='utf-8'))
def check(c,m):
    if not c: raise AssertionError(m)
def main():
    state=load('system_state_registry.snapshot.json')
    check(state['authority']=='RESEARCH_ONLY','authority drift')
    us=state['repositories']['us']; kr=state['repositories']['kr']; lake=state['durable_data']
    check(HEX40.fullmatch(us['repo_head_sha']) is not None,'bad US head')
    check(HEX40.fullmatch(us['reviewed_feature_baseline_sha']) is not None,'bad baseline')
    check(us['repo_head_sha']!=us['reviewed_feature_baseline_sha'],'head/baseline conflated')
    check(HEX40.fullmatch(kr['repo_head_sha']) is not None,'bad KR head')
    for k in ('archive_commit_sha256','catalog_sha256','execution_receipt_sha256'):
        check(HEX64.fullmatch(lake[k]) is not None,f'bad lake hash {k}')
    check(lake['status']=='PARTIAL' and not lake['historical_pit_complete'],'lake overclaimed')
    artifacts=load('artifact_contract_registry.json')
    check(all(not x['trade_authority'] for x in artifacts['artifacts'].values()),'artifact gained trade authority')
    packet=json.dumps(load('research_candidate_packet.schema.json'),sort_keys=True)
    for forbidden in ('order_qty','broker_action','target_weight','buy_signal','sell_signal'):
        check(forbidden not in packet,f'forbidden packet field {forbidden}')
    fixture=load('integration_fixture.synthetic.json')
    check(fixture['universe']['event_membership_score_bonus']==0.0,'event bonus drift')
    check(fixture['expected_return']['h12m']<0,'leadership forced positive expected return')
    check(fixture['information_evidence']['form4']['status']=='BLOCKED_UNVERIFIED','Form4 prematurely enabled')
    matrix={x['ref']:x for x in load('dependency_merge_matrix.json')['entries']}
    check(matrix['PR#439']['depends_on']==['PR#437'],'437->439 drift')
    check(matrix['PR#445']['depends_on']==['PR#439'],'439->445 drift')
    check('PR#440' in matrix['PR#445']['supersedes'],'440 supersession missing')
    check(matrix['PR#431']['merge_action']=='DO_NOT_BLIND_MERGE','431 overlap guard missing')
    check(matrix['PR#446']['merge_action']=='WAIT_CODEX_EXACT_HEAD_REVIEW','Codex gate hidden')
    exp=load('experiment_registry.snapshot.json')
    by={x['experiment_id']:x for x in exp['experiments']}
    check(by['HIST-PR212-MAIN-CONC-HOOKS-20260629']['authority']=='HISTORICAL_RESEARCH_ONLY','legacy result promoted')
    check(by['HIST-KR-V5-20260506']['status']=='BLOCKED','KR legacy result promoted')
    replay=load('bounded_real_replay.archived_20260908.json')
    check(not replay['new_market_data'] and not replay['successful_real_h1_admission'],'archived replay overclaimed')
    check(all(x['status']=='BLOCKED_INCOMPLETE_DATA' for x in replay['securities']),'blocked replay changed')
    check(all(all(v is None for v in x['expected_return'].values()) for x in replay['securities']),'return invented')
    book=load('global_book_separation.synthetic.json')
    check(book['source_of_truth_priority'][0]=='ACTUAL_BROKER_BOOK','book priority drift')
    check(book['research_signal']['suggested_weight'] is None and book['target_book']['target_weight'] is None,'book layers conflated')
    check(all(book['invariants'].values()),'book invariant false')
    print(json.dumps({'status':'PASS','test':'control_plane_contract_smoke','authority':'RESEARCH_ONLY'},sort_keys=True))
    return 0
if __name__=='__main__': raise SystemExit(main())
