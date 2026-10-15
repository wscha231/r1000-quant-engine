"""Synthetic supplied-byte H1 controls; no actual source/admission evidence."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'research'))
sys.path.insert(0, str(ROOT / 'tests'))
import a2_research_intake_v1 as h

CUTOFF = '2026-10-15T00:00:00Z'
T = '2026-10-13T00:00:00Z'
PILLAR = 'earnings_revision_operating_acceleration'

def identities(n=1):
    return h.canonical({'scope':'SUPPLIED_US_IDENTITY_ASSERTIONS','rows':[
        {'security_id':f'US:S{i}','issuer_id':f'CIK:{i}','tickers':[f'S{i}',f'OLD{i}'],'country':'US','currency':'USD'} for i in range(n)]})

def inventory():
    result={}
    for name,sha in h.SCHEMAS.values():
        raw=(ROOT/'research/control_plane'/name).read_bytes()
        if h.digest(raw)!=sha:
            # Test corpus conversion only, never runtime source normalization.
            lf=raw.replace(b'\r\n',b'\n')
            if h.digest(lf)!=sha: raise ValueError('schema_fixture_git_lf_hash')
            raw=lf
        result['SCHEMA:'+name]=raw
    return result

def event(i=0, **kw):
    out=dict(event_id=f'E:{i}',cohort_id=f'C:{i}',event_family='EARNINGS',observed_at=T,published_at=T,
        available_at=T,collected_at=T,expires_at='2026-10-20T00:00:00Z',source_graph_artifact_id=None,
        source_graph_sha256=None,primary_source='TELEGRAM_SECONDARY',verification_level='V0',claim='Synthetic discovery only',
        verified_fact=None,issuer_ids=[f'CIK:{i}'],security_ids=[f'US:S{i}'],tickers=[f'S{i}'],asset_ids=[f'US:S{i}'],
        themes=['T0'],industry_ids=[],underlyings=[],transmission_channel='DEMAND',affected_pillars=[PILLAR],horizon='1M',
        materiality='LOW',invalidation='Recheck source',state='DISCOVERED',assessment_eligible=False,
        score_contribution=0,requires_a3_refresh=False,authority=h.closed())
    out.update(kw); return out

def envelope(events):
    return dict(schema_version='a2-event-handoff-v1',as_of=CUTOFF,events=events,research_only=True,authority=h.closed())

def graph_event():
    import a3_candidate_packet_v1_smoke as fixtures
    fixtures.RAW.clear()
    graph=fixtures.graph(); graph['asset_id']='US:S0'; graph['issuer_id']='CIK:0'
    memory=inventory()
    for (aid,sha),raw in fixtures.RAW.items(): memory[aid]=raw
    memory['GRAPH']=h.canonical(graph)
    row=event(verification_level='V2',primary_source='COMPANY_IR',state='TRACK',assessment_eligible=True,
              verified_fact='Supplied graph internally consistent',source_graph_artifact_id='GRAPH',source_graph_sha256=h.digest(memory['GRAPH']))
    return row,graph,memory

def queue():
    reason=dict(security_id='US:S0',ticker='S0',reason_type='REVIEWED_THEME_RESEARCH',source_kind='THEME',polarity='CANDIDATE',
        status='ACTIVE',first_seen_at=T,last_observed_at=T,valid_until='',source_event_id='THEME:1',source_hash='a'*64,
        source_quality='BUSINESS_REVIEW_PINNED_EVALUATION_PENDING',security_type='EQUITY',notes='theme_id=T0')
    item=dict(asset_id='US:S0',identity_kind='LISTED_SECURITY',security_id='US:S0',issuer_id='CIK:0',ticker='S0',state='DATA_PENDING',
        membership_reasons=[reason],required_channels=['price'],channel_status={'price':'CONSUMER_RECEIPT_MISSING'},
        next_action='VERIFY_INPUTS',first_seen_at=T,last_checked_at=T,authority=h.closed())
    return dict(schema_version='candidate-data-queue-v1',as_of=CUTOFF,research_only=True,direct_score_contribution=0,authority=h.closed(),items=[item])

def delta():
    return dict(security_id='US:S0',issuer_id='CIK:0',fingerprints={k:'a'*64 for k in h.FINGERPRINTS},
        expires_at='2026-10-20T00:00:00Z',exceptions={k:False for k in h.EXCEPTIONS},research_reuse_ready=True,affected_pillars=[PILLAR])

def reference(aid,raw):
    return dict(artifact_id=aid,sha256=h.digest(raw),available_at=T,collected_at=T,expires_at='2026-10-20T00:00:00Z')

def cohort(matured=False):
    sessions=('2025-09-02','2025-09-08','2025-09-15','2025-10-01','2025-12-01','2026-03-02','2026-09-01')
    targets={f'D:0:{horizon}':{'session':session,'close_at':session+'T21:00:00Z'} for horizon,session in zip(h.HORIZONS,sessions)}
    calendar=h.canonical({'schema':'h1-supplied-target-calendar-v1','targets':targets})
    rows=[]
    for horizon in h.HORIZONS:
        row=dict(event_id='E:0',session_clock='NYSE_CLOSE',target_calendar_sha256=h.digest(calendar),data_manifest_sha256='a'*64,
            config_sha256='b'*64,model_sha256='c'*64,model_id='MODEL:FIXTURE',code_sha256='d'*64,issuer_id='CIK:0',security_id='US:S0',asset_id='US:S0',
            decision_id='D:0',cohort_id='C:0',benchmark_id='US:SPY',decision_at='2025-09-01T21:00:00Z',horizon=horizon,target_session=targets['D:0:'+horizon]['session'],
            status='MATURED' if matured else 'UNRESOLVED',selection_status='WATCH',asset_return=0.1 if matured else None,
            benchmark_return=0.05 if matured else None,excess_return=0.05 if matured else None,source_sha256=None,
            outcome_session=targets['D:0:'+horizon]['session'] if matured else None,outcome_available_at=targets['D:0:'+horizon]['close_at'] if matured else None,
            include_in_denominator=True,authority=h.closed())
        rows.append(row)
    excluded={'source_sha256','status','selection_status','authority','include_in_denominator'}
    # selection_status remains part of the immutable outcome binding.
    excluded.remove('selection_status')
    outcomes=h.canonical({'schema':'h1-supplied-outcomes-v1','rows':[{k:v for k,v in row.items() if k not in excluded} for row in rows]})
    if matured:
        for row in rows: row['source_sha256']=h.digest(outcomes)
    data=dict(schema_version='matured-outcome-cohort-v1',generated_at=CUTOFF,rows=rows,coverage_status='COMPLETE_EXACT' if matured else 'INCOMPLETE',
        learning_eligible=False,research_only=True,authority=h.closed(),calendar_ref=reference('CAL',calendar),outcome_ref=reference('OUT',outcomes) if matured else None)
    memory=inventory(); memory.update(CAL=calendar,OUT=outcomes)
    return data,memory

class IntakeTests(unittest.TestCase):
    def check_events(self, events, memory=None, n=1):
        return h.validate_events(h.canonical(envelope(events)),cutoff=CUTOFF,artifact_resolver=h.MemoryArtifacts(memory or inventory()),identities=identities(n))

    def rejects(self, callable, *args, **kwargs):
        with self.assertRaises(h.IntakeError): callable(*args,**kwargs)

    def check_queue(self,value):
        return h.validate_queue(h.canonical(value),cutoff=CUTOFF,artifact_resolver=h.MemoryArtifacts(inventory()),identities=identities(2))

    def check_cohort(self,value,memory):
        return h.validate_cohort(h.canonical(value),cutoff=CUTOFF,artifact_resolver=h.MemoryArtifacts(memory),identities=identities())

    def test_P01_discovery_and_queue(self):
        result=self.check_events([event()]); self.assertEqual(result['events'][0]['graph_status'],'DISCOVERY_ONLY')
        self.assertFalse(result['canonical_verified']); self.assertFalse(result['events'][0]['assessment_eligible'])
        self.assertEqual(self.check_queue(queue())['items'][0]['state'],'DATA_PENDING')

    def test_P02_graph_research_without_authority(self):
        row,graph,memory=graph_event(); result=self.check_events([row],memory)
        self.assertEqual(result['events'][0]['graph_status'],'GRAPH_BYTES_CONSISTENT_REVIEW_UNAUTHENTICATED')
        self.assertFalse(result['events'][0]['assessment_eligible']); self.assertFalse(result['A5_eligible_input'])

    def test_P03_duplicate_keys_every_depth(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":{"a":0,"a":1}}',b'{"x":[{"a":0,"a":1}]}'):
            self.rejects(h.decode,raw)
        raw=h.canonical(envelope([event()])).replace(b'"paper":false',b'"paper":false,"paper":true')
        self.rejects(h.validate_events,raw,cutoff=CUTOFF,artifact_resolver=h.MemoryArtifacts(inventory()),identities=identities())

    def test_P04_unknown_fields_all_boundaries(self):
        e=event(extra=0); self.rejects(self.check_events,[e])
        e=event(); e['authority']['new_flag']=False; self.rejects(self.check_events,[e])
        q=queue(); q['items'][0]['membership_reasons'][0]['extra']=0; self.rejects(self.check_queue,q)
        q=queue(); q['extra']=0; self.rejects(self.check_queue,q)
        c,m=cohort(); c['rows'][0]['extra']=0; self.rejects(self.check_cohort,c,m)
        c,m=cohort(); c['calendar_ref']['extra']=0; self.rejects(self.check_cohort,c,m)
        row,graph,memory=graph_event(); graph['sources'][0]['extra']=0; memory['GRAPH']=h.canonical(graph)
        row['source_graph_sha256']=h.digest(memory['GRAPH']); self.rejects(self.check_events,[row],memory)
        value,ref,memory=self.er_fixture(); ref['extra']=0; self.rejects(self.check_er,ref,memory)
        now=delta(); now['exceptions']['extra']=False
        self.rejects(h.plan_delta,h.canonical(delta()),h.canonical(now),cutoff=CUTOFF)

    def test_P05_strict_numbers_and_booleans(self):
        for raw in (b'{"x":NaN}',b'{"x":Infinity}',b'{"x":1e999}'):
            self.rejects(h.decode,raw)
        for bad in (True,'0',None): self.rejects(self.check_events,[event(score_contribution=bad)])
        for bad in (0,1): self.rejects(self.check_events,[event(assessment_eligible=bad)])

    def test_P06_preallocation_bounds(self):
        raw=b'{"x":"[\\\"{}]"}'
        with patch.object(h,'MAX_BYTES',len(raw)): self.assertEqual(h.decode(raw)['x'],'["{}]')
        with patch.object(h,'MAX_BYTES',len(raw)-1): self.rejects(h.decode,raw)
        with patch.object(h,'MAX_DEPTH',2):
            self.assertEqual(h.decode(b'{"x":{}}'),{'x':{}}); self.rejects(h.decode,b'{"x":{"y":{}}}')
        with patch.object(h,'MAX_TOKENS',3):
            self.assertEqual(h.decode(b'{"x":0}'),{'x':0}); self.rejects(h.decode,b'{"x":0,"y":1}')
        with patch.object(h,'MAX_TOTAL_BYTES',2):
            h.MemoryArtifacts({'A':b'{}'}); self.rejects(h.MemoryArtifacts,{'A':b'{}','B':b'1'})
        self.rejects(h.MemoryArtifacts,lambda aid,sha:b'{}')
        self.assertEqual(h.decode(b'{"x":[0,1,2]}',max_entries=3)['x'],[0,1,2])
        with patch.object(h.json,'loads',side_effect=RuntimeError('tree allocation forbidden')):
            self.rejects(h.decode,b'{"x":[0,1,2,3]}',max_entries=3)
        self.assertEqual(len(h.decode(h.canonical({'rows':[0]*1001}),max_entries=10000)['rows']),1001)
        self.rejects(h.decode,h.canonical({'rows':[0]*1001}))

    def test_P07_future_available(self):
        self.rejects(self.check_events,[event(available_at='2026-10-16T00:00:00Z')])

    def test_P08_future_collected(self):
        self.rejects(self.check_events,[event(collected_at='2026-10-16T00:00:00Z')])

    def test_P09_clock_order_observation_expiry(self):
        for kw in ({'published_at':'2026-10-14T00:00:00Z'}, {'available_at':'2026-10-14T00:00:00Z'},
                   {'observed_at':'2026-10-16T00:00:00Z'},{'published_at':'2026-10-13T00:00:00'}, {'expires_at':'2026-10-12T00:00:00Z'}):
            self.rejects(self.check_events,[event(**kw)])

    def test_P10_identity_no_ticker_inference(self):
        for kw in ({'issuer_ids':['WRONG']},{'security_ids':['UNKNOWN']},{'tickers':['UNKNOWN']},{'asset_ids':['WRONG']}):
            self.rejects(self.check_events,[event(**kw)])

    def test_P11_V0_no_verification(self):
        for kw in ({'assessment_eligible':True},{'score_contribution':1},{'verified_fact':'claimed'},{'state':'TRACK'},{'state':'VERIFIED'}):
            self.rejects(self.check_events,[event(**kw)])

    def test_P12_telegram_relabel(self):
        row,graph,memory=graph_event(); row['primary_source']='TELEGRAM_SECONDARY'
        self.rejects(self.check_events,[row],memory)

    def test_P13_graph_raw_and_unknown_conflicts(self):
        row,graph,memory=graph_event(); memory['GRAPH']+=b' '; self.rejects(self.check_events,[row],memory)
        row,graph,memory=graph_event(); memory['RAW:IR']=b'tampered'; self.rejects(self.check_events,[row],memory)
        row,graph,memory=graph_event(); graph['sources'][1]['raw_artifact_id']='RAW:IR'; memory['GRAPH']=h.canonical(graph)
        row['source_graph_sha256']=h.digest(memory['GRAPH']); self.rejects(self.check_events,[row],memory)
        for field in ('source_type','raw_sha256','independence_group','source_affiliation','supports_pillars'):
            row,graph,memory=graph_event(); graph['sources'][0][field]=[['bad']]
            memory['GRAPH']=h.canonical(graph); row['source_graph_sha256']=h.digest(memory['GRAPH'])
            self.rejects(self.check_events,[row],memory)

    def test_P14_graph_required_not_canonical(self):
        for tier in ('V1','V2'):
            self.rejects(self.check_events,[event(primary_source='IR',verification_level=tier)])
        row,graph,memory=graph_event(); row['state']='VERIFIED'; self.rejects(self.check_events,[row],memory)

    def test_P15_mirror_independence(self):
        for field,bad in (('independence_group','ISSUER:EXAMPLE'),('raw_sha256',None),('source_type','COMPANY_IR')):
            row,graph,memory=graph_event()
            if field=='raw_sha256':
                graph['sources'][1]['raw_artifact_id']=graph['sources'][0]['raw_artifact_id']; bad=graph['sources'][0]['raw_sha256']
            graph['sources'][1][field]=bad
            if field=='source_type': graph['sources'][1]['source_affiliation']='ISSUER'
            memory['GRAPH']=h.canonical(graph); row['source_graph_sha256']=h.digest(memory['GRAPH'])
            self.rejects(self.check_events,[row],memory)

    def test_P16_inclusive_anchor_and_midnight(self):
        rows=[]
        for index,t in enumerate(('2026-10-12T23:00:00Z','2026-10-13T22:00:00Z','2026-10-13T23:00:00Z')):
            rows.append(event(event_id=f'E:{index}',published_at=t,available_at=t,collected_at=t,observed_at=t))
        self.assertEqual(len(self.check_events(rows)['clusters']),1)

    def test_P17_no_chain_family_or_security_merge(self):
        rows=[event(event_id='E:A'),event(event_id='E:B',published_at='2026-10-14T00:00:00Z',available_at='2026-10-14T00:00:00Z',collected_at='2026-10-14T00:00:00Z'),
              event(event_id='E:C',published_at='2026-10-14T00:00:01Z',available_at='2026-10-14T00:00:01Z',collected_at='2026-10-14T00:00:01Z'),
              event(event_id='E:D',event_family='GUIDANCE'),event(1)]
        self.assertEqual(len(self.check_events(rows,n=2)['clusters']),4)

    def test_P18_deterministic_tie_and_ticker_rename(self):
        a,b=event(event_id='E:A'),event(event_id='E:B',tickers=['OLD0'])
        one=self.check_events([b,a]); two=self.check_events([a,b])
        self.assertEqual(one['clusters'],two['clusters']); self.assertEqual(one['active_security_count'],1)

    def test_P19_active_security_cap(self):
        self.assertEqual(self.check_events([event(i) for i in range(30)],n=31)['active_security_count'],30)
        self.rejects(self.check_events,[event(i) for i in range(31)],n=31)

    def test_P20_active_theme_cap(self):
        self.assertEqual(self.check_events([event(themes=[f'T{i}' for i in range(10)])])['active_theme_count'],10)
        self.rejects(self.check_events,[event(themes=[f'T{i}' for i in range(11)])])

    def test_P21_expired_denominator_retained(self):
        result=self.check_events([event(i,expires_at=CUTOFF) for i in range(31)],n=31)
        self.assertEqual(result['active_security_count'],0); self.assertEqual(len(result['events']),31)
        self.assertTrue(all(e['include_in_denominator'] for e in result['events']))

    def test_P22_unique_security_queue(self):
        q=queue(); q['items'].append(copy.deepcopy(q['items'][0])); self.rejects(self.check_queue,q)
        q=queue(); second=copy.deepcopy(q['items'][0]); second.update(asset_id='US:S1',security_id='US:S1',ticker='S1')
        second['membership_reasons'][0].update(security_id='US:S1',ticker='S1'); q['items'].append(second)
        ids=json.loads(identities(2)); ids['rows'][1]['issuer_id']='CIK:0'
        result=h.validate_queue(h.canonical(q),cutoff=CUTOFF,artifact_resolver=h.MemoryArtifacts(inventory()),identities=h.canonical(ids))
        self.assertEqual(len(result['items']),2)

    def test_P23_unknown_prior_reconcile(self):
        result=h.reference_preview(b'{"entries":null}',cutoff=CUTOFF,artifact_resolver=h.MemoryArtifacts(inventory()))
        self.assertEqual(result['reference_status'],'RECONCILE_PENDING')
        self.assertEqual(h.plan_delta(None,h.canonical(delta()),cutoff=CUTOFF)['plan'],'RECONCILE_PENDING')

    def test_P24_skip_planning_only(self):
        raw=h.canonical(delta()); result=h.plan_delta(raw,raw,cutoff=CUTOFF)
        self.assertEqual(result['plan'],'SKIP_UNCHANGED'); self.assertFalse(result['execution_permitted'])

    def test_P25_same_hash_exceptions(self):
        prior=delta()
        for exception in h.EXCEPTIONS:
            now=copy.deepcopy(prior); now['exceptions'][exception]=True
            self.assertEqual(h.plan_delta(h.canonical(prior),h.canonical(now),cutoff=CUTOFF)['plan'],'REFRESH_REQUIRED')
        now=delta(); now['expires_at']=CUTOFF
        self.assertEqual(h.plan_delta(h.canonical(prior),h.canonical(now),cutoff=CUTOFF)['plan'],'REFRESH_REQUIRED')
        now=delta(); now['expires_at']='2026-10-21T00:00:00Z'
        self.assertEqual(h.plan_delta(h.canonical(prior),h.canonical(now),cutoff=CUTOFF)['plan'],'REFRESH_REQUIRED')
        now=delta(); now['affected_pillars']=[['bad']]
        self.rejects(h.plan_delta,h.canonical(prior),h.canonical(now),cutoff=CUTOFF)

    def test_P26_price_and_earnings(self):
        for name,expected in (('market_price',{'market','valuation','ER'}),('earnings_consensus',{'earnings','valuation','ER'})):
            now=delta(); now['fingerprints'][name]='b'*64
            result=h.plan_delta(h.canonical(delta()),h.canonical(now),cutoff=CUTOFF)
            self.assertEqual(set(result['refresh']),expected)

    def test_P27_industry_and_regime(self):
        for name,expected in (('industry',{PILLAR}),('regime',{'downside','portfolio_overlay'})):
            now=delta(); now['fingerprints'][name]='b'*64
            self.assertEqual(set(h.plan_delta(h.canonical(delta()),h.canonical(now),cutoff=CUTOFF)['refresh']),expected)

    def test_P28_integrity_full_review(self):
        for name in ('source','accounting'):
            now=delta(); now['fingerprints'][name]='b'*64
            self.assertEqual(h.plan_delta(h.canonical(delta()),h.canonical(now),cutoff=CUTOFF)['plan'],'BLOCKED_FULL_A3_REVIEW')
        now=delta(); now['issuer_id']='CIK:OTHER'
        self.assertEqual(h.plan_delta(h.canonical(delta()),h.canonical(now),cutoff=CUTOFF)['plan'],'BLOCKED_FULL_A3_REVIEW')

    def er_fixture(self):
        import a3_candidate_packet_v1_smoke as fixtures
        value=fixtures.valid_er(); value.update(asset_id='US:S0',issuer_id='CIK:0')
        for horizon in ('1m','3m','6m','12m'): value['expected_return_'+horizon]=0
        raw=h.canonical(value); memory=inventory(); memory['ER']=raw
        return value,reference('ER',raw),memory

    def check_er(self,ref,memory):
        return h.er_preview(None if ref is None else h.canonical(ref),cutoff=CUTOFF,artifact_resolver=h.MemoryArtifacts(memory),security_id='US:S0',issuer_id='CIK:0',benchmark_id='US:SPY')

    def test_P29_missing_ER_distinct_from_declared_zero(self):
        self.assertIsNone(self.check_er(None,inventory())['validated_er'])
        value,ref,memory=self.er_fixture(); result=self.check_er(ref,memory)
        self.assertEqual(result['declared_er']['1m']['expected_return'],0); self.assertIsNone(result['validated_er'])

    def test_P30_ER_qualification(self):
        for key,bad in (('net_of_costs',False),('validation_status','SCENARIO'),('benchmark_id','US:QQQ'),('asset_id','WRONG'),('issuer_id','WRONG')):
            value,ref,memory=self.er_fixture(); value[key]=bad; memory['ER']=h.canonical(value); ref['sha256']=h.digest(memory['ER'])
            self.rejects(self.check_er,ref,memory)
        value,ref,memory=self.er_fixture(); ref['expires_at']=CUTOFF; self.rejects(self.check_er,ref,memory)

    def test_P31_authority_every_flag(self):
        for key in h.FLAGS:
            e=event(); e['authority'][key]=True; self.rejects(self.check_events,[e])
            q=queue(); q['authority'][key]=True; self.rejects(self.check_queue,q)
            c,m=cohort(); c['rows'][0]['authority'][key]=True; self.rejects(self.check_cohort,c,m)

    def test_P32_all_horizons_exact_candidates(self):
        c,m=cohort(True); result=self.check_cohort(c,m)
        self.assertTrue(result['maturity_candidate']); self.assertFalse(result['learning_eligible'])
        self.assertEqual({r['horizon'] for r in result['rows']},set(h.HORIZONS))

    def test_P33_late_immature_missing(self):
        for key,bad in (('outcome_session','2026-10-15'),('outcome_available_at','2026-10-16T00:00:00Z'),('asset_return',None)):
            c,m=cohort(True); c['rows'][0][key]=bad; self.rejects(self.check_cohort,c,m)
        c,m=cohort(); c['rows'][0]['asset_return']=0; self.rejects(self.check_cohort,c,m)
        c,m=cohort(True); c['rows'].pop(); self.rejects(self.check_cohort,c,m)
        c,m=cohort(True); c['rows'][0]['outcome_available_at']='2025-09-02T00:00:00Z'; self.rejects(self.check_cohort,c,m)
        c,m=cohort(); self.assertEqual(self.check_cohort(c,m)['denominator_count'],7)

    def test_P34_unselected_delisted_denominator(self):
        for status in ('WATCH','REJECT','BLOCKED','NOT_SELECTED','DELISTED','EXITED'):
            c,m=cohort()
            for row in c['rows']: row['selection_status']=status; row['status']='DELISTED_OR_EXITED_PENDING'
            result=self.check_cohort(c,m); self.assertEqual(result['denominator_count'],7)
            self.assertTrue(all(r['include_in_denominator'] for r in result['rows']))

    def test_P35_inputs_unchanged_success_and_failure(self):
        row,graph,memory=graph_event(); before=copy.deepcopy((row,memory)); self.check_events([row],memory)
        self.assertEqual((row,memory),before)
        row['assessment_eligible']=0; before=copy.deepcopy((row,memory)); self.rejects(self.check_events,[row],memory)
        self.assertEqual((row,memory),before)

    def test_P36_no_IO_or_callback(self):
        memory=h.MemoryArtifacts(inventory()); raw=h.canonical(envelope([event()])); ids=identities()
        import socket, subprocess
        with patch('builtins.open',side_effect=RuntimeError('IO forbidden')),patch.object(Path,'open',side_effect=RuntimeError('IO forbidden')),patch.object(socket,'socket',side_effect=RuntimeError('network forbidden')),patch.object(subprocess,'Popen',side_effect=RuntimeError('process forbidden')):
            self.assertEqual(h.validate_events(raw,cutoff=CUTOFF,artifact_resolver=memory,identities=ids)['status'],'VALID_RESEARCH_PROPOSAL')
        self.rejects(h.validate_events,raw,cutoff=CUTOFF,artifact_resolver=lambda aid,sha:b'{}',identities=ids)

    def test_P37_deterministic_output_digest(self):
        first=self.check_events([event()]); second=self.check_events([event()])
        self.assertEqual(h.digest(h.canonical(first)),h.digest(h.canonical(second)))

    def test_P38_existing_registry_adapter_empty(self):
        result=h.reference_preview(b'{"entries":[]}',cutoff=CUTOFF,artifact_resolver=h.MemoryArtifacts(inventory()))
        self.assertEqual(result['reference_index']['status'],'EMPTY_INPUT')
        self.assertFalse(result['reference_index']['economic_consumption_allowed'])

    def test_P40_proof_schema_bytes_refused(self):
        for name,sha in h.SCHEMAS.values():
            memory=inventory(); memory['SCHEMA:'+name]+=b' '
            if name.startswith('a2_'): self.rejects(self.check_events,[event()],memory)
            elif name.startswith('candidate_'):
                self.rejects(h.validate_queue,h.canonical(queue()),cutoff=CUTOFF,artifact_resolver=h.MemoryArtifacts(memory),identities=identities())
            else:
                c,m=cohort(); m['SCHEMA:'+name]+=b' '; self.rejects(self.check_cohort,c,m)
        from tools import manual_foundation as manual
        expected={'research/a2_research_intake_v1.py','tests/a2_research_intake_v1_smoke.py'}
        self.assertLessEqual(expected,set(manual.A6_FIXED_PROOF_PROGRAMS))
        self.assertLessEqual({'research/control_plane/'+name for name,sha in h.SCHEMAS.values()},set(manual.A6_FIXED_PROOF_INPUTS))

if __name__=='__main__': unittest.main()
