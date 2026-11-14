"""Primary-original scope, units, PIT clocks, immutable readback and cloud hook."""
import copy
from datetime import timedelta
import gzip
import io
import json
import os
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from urllib.error import HTTPError

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import a4_primary_sources as p
from tools import collect_a4_primary_data as c
from tools import market_analysis_engine as m
from tools import a4_macro_learning as learning
from tools.macro_research_checkpoint import LocalTransport
from tools.macro_history_sources import digest, encoded

NOW = '2026-11-07T10:00:00+00:00'


def archive(feed, *, modifier=None, xml_prefix=b''):
    groups = []
    if feed == 'h41':
        for native, (alias, _, kind, component, _) in p.H41.items():
            attrs = dict(SERIES_NAME=native, FREQ='19', UNIT='Currency', UNIT_MULT='1000000',
                         CURRENCY='USD', SERIESTYPE=kind, COMPONENT=component, DISTRIBUTION='TOT')
            groups.append((alias, attrs, 3000000))
    elif feed == 'h8':
        for (item,bg), (alias, _) in p.H8.items():
            attrs = dict(SERIES_NAME='B'+item+'N'+bg+'A', FREQ='19', UNIT='Currency', UNIT_MULT='1000000',
                         CURRENCY='USD', ITEM=item, BG=bg, SA='SA', H8_UNITS='LEVEL')
            amount = {'CB':120000000, 'DM':100000000, 'LG':70000000, 'SM':30000000}[bg]
            groups.append((alias, attrs, amount))
    else:
        groups = [('IORB', dict(SERIES_NAME='RESBM_N.D', FREQ='8', UNIT='Percent', UNIT_MULT='1', CURRENCY='NA'), 3.9)]
    if modifier:
        modifier(groups)
    series = []
    for alias, attrs, amount in groups:
        dates = ('2026-11-06','2026-11-08') if feed == 'prates' else ('2026-11-04',)
        observations = ''.join('<Obs TIME_PERIOD="'+d+'" OBS_STATUS="A" OBS_VALUE="'+str(amount)+'"/>' for d in dates)
        series.append('<Series '+ ' '.join(k+'="'+v+'"' for k,v in attrs.items())+'>'+observations+'</Series>')
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(p.FEEDS[feed][1], xml_prefix+('<Data>'+''.join(series)+'</Data>').encode())
        z.writestr(p.FEEDS[feed][2], b'<Structure/>')
    return raw.getvalue()


def nyfed(feed):
    return encoded(dict(refRates=[dict(type=feed.upper(), effectiveDate='2026-11-06', percentRate=3.88,
        volumeInBillions=100, percentPercentile1=3.8, percentPercentile25=3.85,
        percentPercentile75=3.9, percentPercentile99=4)]))


def retained_credit_input(root, *, now=NOW):
    root.mkdir()
    entries=[];bodies={}
    for name,kind,source_id,body in (
        ('context.json','risk_context',None,b'[]'),
        ('hy.csv','macro','fred:BAMLH0A0HYM2',b'DATE,BAMLH0A0HYM2\n2026-11-06,3.2\n'),
        ('ig.csv','macro_v2','fred:BAMLC0A0CM',b'DATE,BAMLC0A0CM\n2026-11-06,1.0\n'),
        ('rates.csv','macro_v2','fred:DGS10',b'DATE,DGS10\n2026-11-06,4.1\n')):
        (root/name).write_bytes(body);bodies[name]=body
        spec=dict(kind=kind,path=name,sha256=digest(body),status='COLLECTED',collected_at=now)
        if source_id is not None:spec['source_id']=source_id
        entries.append(spec)
    request=dict(schema=m.REQUEST_SCHEMA_V2,market='US',session=m.current_session(now),available_at=now,
        expires_at=(p.clock(now)+timedelta(days=1)).isoformat(),inputs=entries)
    raw=encoded(request);(root/'request.json').write_bytes(raw);(root/'request.sha256').write_text(digest(raw))
    return request,bodies


class PrimaryTests(unittest.TestCase):
    def test_checkout_preserves_hash_bound_normalizer_bytes(self):
        paths=('tools/a4_primary_sources.py','tools/a4_primary_macro_sources.py',
               'tools/a4_financing_sources.py','tools/a4_financing_analysis.py',
               'tools/market_analysis_engine.py','tools/chameleon_market_context_v2.py',
               'tools/free_market_context.py','tools/build_run287_chameleon_macro_risk.py',
               'tools/daily_crisis_report_clock.py','docs/run287_chameleon_macro_risk_contract.json',
               'docs/market_analysis_contract_v1.json','tools/build_run287_chameleon_macro_inputs.py',
               'tools/candidate_reassessment_bridge.py','tools/a4_liquidity_analysis.py',
               'tools/a4_macro_bridge.py','docs/market_analysis_contract_v2.json',
               'tools/a4_macro_learning.py','tools/macro_technical_study.py','tools/a4_data_center.py',
               'docs/research_data_access.json','tools/a4_macro_diagnosis.py',
               'docs/A4_MACRO_CONDITION_DIAGNOSIS_V1.md')
        self.assertEqual({Path(name).name for name in paths},set(m.implementation_identity())|{'a4_data_center.py','research_data_access.json'})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'.gitattributes').write_bytes((ROOT/'.gitattributes').read_bytes())
            def git(*args):
                return subprocess.run(['git','-C',str(root),*args],check=True,
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            git('init','-q');git('config','core.autocrlf','true')
            originals={name:(ROOT/name).read_bytes() for name in paths}
            for name in paths:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(originals[name])
                self.assertNotIn(b'\r\n',originals[name])
            git('add','--','.gitattributes',*paths)
            for name in paths:(root/name).unlink()
            git('checkout-index','-f','--',*paths)
            for name in paths:self.assertEqual((root/name).read_bytes(),originals[name])

    def test_official_zip_mime_type_is_accepted_without_provider_retry(self):
        raw=archive('h8'); calls=[]
        class Opener:
            def open(self, request, timeout):
                calls.append(request.full_url)
                if 'application/x-zip-compressed' not in request.get_header('Accept'):
                    raise HTTPError(request.full_url,406,'not acceptable',{},None)
                response=io.BytesIO(raw);response.status=200
                return response
        with patch.object(p,'build_opener',return_value=Opener()):
            actual,_=p.capture('h8')
        self.assertEqual(actual,raw)
        self.assertEqual(calls,[p.FEEDS['h8'][0]])

    def test_bank_native_millions_become_billions_with_all_scopes(self):
        rows, receipt = p.normalize(archive('h8'), 'h8', collected_at=NOW)
        self.assertEqual(len(rows), 20)
        self.assertEqual(len(receipt['series']), 20)
        all_banks = next(r for r in rows if r['logical_id'] == 'deposits_all')
        self.assertEqual(all_banks['value'], 120000)
        self.assertEqual(all_banks['bank_aggregation'], 'CB')
        self.assertEqual(all_banks['unit'], 'billions_usd')
        self.assertTrue(all(r['source_id'].startswith('frb:') and r['seasonal_basis']=='SA' for r in rows))

    def test_balance_levels_weekly_averages_and_rrp_accounts_are_distinct(self):
        rows, _ = p.normalize(archive('h41'), 'h41', collected_at=NOW)
        by = {r['logical_id']: r for r in rows}
        self.assertEqual(by['fed_assets']['measurement_basis'], 'WEDNESDAY_LEVEL')
        self.assertEqual(by['reserves_week_average']['measurement_basis'], 'WEEK_AVERAGE')
        self.assertTrue({'rrp_total_week_average','rrp_foreign_week_average','rrp_other_week_average'} <= set(by))
        self.assertTrue(all(r['unit']=='millions_usd' for r in rows))

    def test_current_histories_never_gain_old_publication_or_future_rate(self):
        rows, _ = p.normalize(archive('prates'), 'prates', collected_at=NOW)
        self.assertEqual([r['observation_date'] for r in rows], ['2026-11-06'])
        self.assertEqual(rows[0]['available_at'], NOW)
        self.assertIsNone(rows[0]['published_at'])
        self.assertFalse(rows[0]['historical_pit_certified'])
        with self.assertRaises(ValueError): p.normalize(archive('prates'), 'prates', collected_at=NOW, through='2026-11-08')
        with self.assertRaises(ValueError): p.normalize(archive('prates'), 'prates', collected_at='2026-11-07')
        self.assertEqual(learning.replay_features(rows, [dict(session='2026-11-06',close_utc='2026-11-06T21:00:00Z')])['funding:sofr_minus_iorb'].notna().sum(), 0)

    def test_wrong_units_identity_duplicate_or_missing_series_refuse(self):
        variants = [lambda g: g[0][1].update(UNIT_MULT='1000'), lambda g: g[0][1].update(SERIES_NAME='foreign'),
                    lambda g: g.append(g[0]), lambda g: g.pop()]
        for modify in variants:
            with self.subTest(modify=modify), self.assertRaises(ValueError):
                p.normalize(archive('h8',modifier=modify), 'h8', collected_at=NOW)

    def test_xml_entities_encoding_and_path_members_refuse(self):
        for declaration in (b'<!DOCTYPE Data [<!ENTITY x "boom">]>', b'\xff\xfe<\0!\0D\0O\0C\0T\0Y\0P\0E\0'):
            with self.assertRaises(ValueError): p.normalize(archive('h8',xml_prefix=declaration), 'h8', collected_at=NOW)
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z: z.writestr('../H8_data.xml',b'<Data/>')
        with self.assertRaises(ValueError): p.normalize(raw.getvalue(),'h8',collected_at=NOW)

    def test_decompression_rows_and_retained_memory_are_bounded(self):
        raw=archive('h8')
        for constant, bound in (('MAX_EXPANDED',100), ('MAX_ROWS',2), ('MAX_TOTAL',200)):
            with self.subTest(constant=constant), patch.object(p,constant,bound), self.assertRaises(ValueError):
                p.normalize(raw,'h8',collected_at=NOW)
        reader=p.SafeXML(io.BytesIO(b'0123456789'),5)
        with self.assertRaises(ValueError):reader.read(6)

    def test_same_capture_reuses_bytes_and_conflict_refuses_before_write(self):
        with tempfile.TemporaryDirectory() as d:
            first=p.store_capture(d,archive('h8'),'h8',collected_at=NOW)
            second=p.store_capture(d,archive('h8'),'h8',collected_at=NOW)
            self.assertEqual(first,second)
            path=Path(d)/first['files'][0];path.write_bytes(b'tampered')
            before=set(Path(d).rglob('*'))
            with self.assertRaises(ValueError):p.store_capture(d,archive('h8'),'h8',collected_at=NOW)
            self.assertEqual(before,set(Path(d).rglob('*')))

    def test_shared_transport_readback_recomputes_original_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); prepared=p.store_capture(root/'prepared',archive('h8'),'h8',collected_at=NOW)
            transport=LocalTransport(root/'remote')
            result=p.publish_capture(transport,root/'prepared',prepared['generation_sha256'],cutoff=NOW)
            self.assertFalse(result['transport_readback_verified'])
            rows, manifest=p.read_generation(transport,prepared['generation_sha256'],cutoff=NOW)
            self.assertEqual(len(rows),20)
            self.assertFalse(manifest['training_admitted'])
            with self.assertRaisesRegex(ValueError,'FUTURE_CAPTURE'):
                p.read_generation(transport,prepared['generation_sha256'],cutoff='2026-11-06T10:00:00Z')
            (transport.root/p.PREFIX/'objects'/manifest['original_sha256']).write_bytes(b'tampered')
            with self.assertRaises(ValueError):p.read_generation(transport,prepared['generation_sha256'],cutoff=NOW)

    def test_cross_platform_gzip_encoding_does_not_change_semantic_replay(self):
        raw=archive('h8'); rows,manifest,files=p.prepare(raw,'h8',collected_at=NOW)
        canonical=b''.join(encoded(r) for r in rows)
        alternate=bytearray(gzip.compress(canonical,compresslevel=1,mtime=0));alternate[9]=3
        with tempfile.TemporaryDirectory() as d:
            transport=LocalTransport(d)
            for body in (bytes(alternate),gzip.compress(canonical.replace(b'120000.0',b'120001.0'),mtime=0)):
                altered=dict(manifest,normalized_object_sha256=digest(body),normalized_object_bytes=len(body))
                pin=digest(encoded(altered))
                transport.write(p.PREFIX+'/objects/'+digest(raw),raw)
                transport.write(p.PREFIX+'/objects/'+digest(body),body)
                transport.write(p.PREFIX+'/generations/'+pin+'.json',encoded(altered))
                if body==bytes(alternate):
                    replay,_=p.read_generation(transport,pin,cutoff=NOW);self.assertEqual(replay,rows)
                else:
                    with self.assertRaisesRegex(ValueError,'NORMALIZATION_REPLAY'):p.read_generation(transport,pin,cutoff=NOW)

    def test_v2_engine_consumes_each_primary_original_once_and_v1_refuses(self):
        raw=archive('h8'); spec=dict(kind='macro_primary',feed='h8',path='original.zip',sha256=digest(raw),
            status='COLLECTED',collected_at=NOW,observation_start='1996-01-01',observation_through='2026-11-07')
        req=dict(schema=m.REQUEST_SCHEMA_V2,market='US',session='2026-11-06',available_at=NOW,
                 expires_at='2026-11-08T10:00:00Z',inputs=[spec])
        result=m.analyze(encoded(req),{'original.zip':raw},expected_sha=digest(encoded(req)),cutoff=NOW,session=req['session'])
        self.assertTrue(result['enhanced_readiness']['bank_credit'])
        self.assertEqual(len(result['bank_credit']['additional_scoped_series']),12)
        self.assertEqual(result['status'],'DATA_BLOCKED')
        self.assertFalse(result['source_and_pit_admission'])
        req['schema']=m.REQUEST_SCHEMA
        with self.assertRaises(ValueError):m.verify_request(encoded(req),digest(encoded(req)),NOW,req['session'])

    def test_collection_replays_all_six_feeds_and_refuses_attempt_overwrite(self):
        bodies={feed:nyfed(feed) if feed in {'sofr','tgcr','effr'} else archive(feed) for feed in c.FEED_ORDER}
        calls=[]
        def fetch(url,limit):
            calls.append(url)
            return next(bodies[k] for k,v in p.FEEDS.items() if v[0]==url)
        with tempfile.TemporaryDirectory() as d, patch.object(p,'now',return_value=NOW):
            result=c.collect(Path(d)/'attempt',code_sha='a'*40,fetcher=fetch,transport=LocalTransport(Path(d)/'remote'))
            self.assertFalse(result['failures'])
            self.assertEqual(len(calls),6)
            self.assertEqual(result['originals'],6)
            self.assertFalse(result['model_fit_performed'])
            self.assertEqual({r['kind'] for r in result['analysis_publication']},{'request','report'})
            report=json.loads((Path(d)/'attempt/market_analysis.json').read_bytes())
            self.assertTrue(report['enhanced_readiness']['funding'])
            self.assertTrue(report['enhanced_readiness']['liquidity'])
            with self.assertRaises(ValueError):c.collect(Path(d)/'attempt',code_sha='a'*40,fetcher=fetch)
            self.assertEqual(len(calls),6)

    def test_failed_source_keeps_failure_receipt_and_never_publishes_a_generation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(p,'now',return_value=NOW):
            transport=LocalTransport(Path(d)/'remote')
            result=c.collect(Path(d)/'attempt',code_sha='a'*40,fetcher=lambda *_:b'invalid',transport=transport)
            self.assertEqual(result['status'],'BLOCKED_SOURCE_CAPTURE')
            self.assertEqual(len(result['failures']),6)
            self.assertFalse((transport.root/p.PREFIX/'generations').exists())
            self.assertEqual(len(list((transport.root/p.PREFIX/'executions').iterdir())),1)
            self.assertFalse((Path(d)/'attempt/inputs/request.json').exists())

    def test_collection_preserves_supplied_credit_bytes_specification_and_clocks(self):
        bodies={feed:nyfed(feed) if feed in {'sofr','tgcr','effr'} else archive(feed) for feed in c.FEED_ORDER}
        def fetch(url,limit):return next(bodies[k] for k,v in p.FEEDS.items() if v[0]==url)
        with tempfile.TemporaryDirectory() as tmp,patch.object(p,'now',return_value=NOW):
            root=Path(tmp);request,originals=retained_credit_input(root/'native')
            c.collect(root/'capture',code_sha='a'*40,fetcher=fetch,existing_input_root=root/'native')
            restored=json.loads((root/'capture/inputs/request.json').read_bytes())
            retained=[s for s in restored['inputs'] if s['kind'] in {'macro','macro_v2','risk_context'}]
            self.assertEqual(len(retained),3)
            for spec in request['inputs'][:3]:
                output=next(s for s in retained if s['sha256']==spec['sha256'])
                self.assertEqual({k:v for k,v in output.items() if k!='path'},
                                 {k:v for k,v in spec.items() if k!='path'})
                self.assertEqual((root/'capture/inputs'/output['path']).read_bytes(),originals[spec['path']])
            report=json.loads((root/'capture/market_analysis.json').read_bytes())
            self.assertEqual(report['macro_direction_inputs']['hy_oas']['value'],3.2)
            self.assertEqual(report['macro_direction_inputs']['ig_oas']['available_at'],NOW)
            self.assertEqual(report['status'],'DATA_BLOCKED')
            self.assertFalse(report['source_and_pit_admission'])

    def test_corrupt_or_expired_credit_request_is_not_partially_retained(self):
        bodies={feed:nyfed(feed) if feed in {'sofr','tgcr','effr'} else archive(feed) for feed in c.FEED_ORDER}
        def fetch(url,limit):return next(bodies[k] for k,v in p.FEEDS.items() if v[0]==url)
        for reason in ('hash','expiry'):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as tmp,patch.object(p,'now',return_value=NOW):
                root=Path(tmp);request,_=retained_credit_input(root/'native')
                if reason=='hash':(root/'native/hy.csv').write_bytes(b'tampered')
                else:
                    request['available_at']='2026-11-07T08:00:00+00:00';request['expires_at']='2026-11-07T09:00:00+00:00'
                    for spec in request['inputs']:spec['collected_at']='2026-11-07T07:00:00+00:00'
                    raw=encoded(request);(root/'native/request.json').write_bytes(raw)
                    (root/'native/request.sha256').write_text(digest(raw))
                c.collect(root/'capture',code_sha='a'*40,fetcher=fetch,existing_input_root=root/'native')
                output=json.loads((root/'capture/inputs/request.json').read_bytes())
                self.assertTrue(all(s['kind']=='macro_primary' for s in output['inputs']))

    def test_fresh_packet_does_not_refresh_an_old_credit_observation(self):
        bodies={feed:nyfed(feed) if feed in {'sofr','tgcr','effr'} else archive(feed) for feed in c.FEED_ORDER}
        def fetch(url,limit):return next(bodies[k] for k,v in p.FEEDS.items() if v[0]==url)
        with tempfile.TemporaryDirectory() as tmp,patch.object(p,'now',return_value=NOW):
            root=Path(tmp);request,_=retained_credit_input(root/'native')
            old=b'DATE,BAMLH0A0HYM2\n2026-10-01,3.2\n';(root/'native/hy.csv').write_bytes(old)
            request['inputs'][1]['sha256']=digest(old);raw=encoded(request)
            (root/'native/request.json').write_bytes(raw);(root/'native/request.sha256').write_text(digest(raw))
            c.collect(root/'capture',code_sha='a'*40,fetcher=fetch,existing_input_root=root/'native')
            report=json.loads((root/'capture/market_analysis.json').read_bytes())
            self.assertEqual(report['macro_direction_inputs']['hy_oas']['status'],'STALE')
            self.assertEqual(report['macro_direction_inputs']['hy_oas']['observation_date'],'2026-10-01')
            self.assertEqual(report['status'],'DATA_BLOCKED')

    def test_primary_learning_requires_forward_capture_and_reviewed_price_scope(self):
        from tests.a4_macro_learning_smoke import fixture
        payload, policy, resolver=fixture()
        for row in payload['observations']:
            if row['source_id']=='fred:IORB':row['source_id']='frb:IORB'
        binding=next(iter(policy['source_bindings'].values()))
        binding['source_ids']=['fred:SOFR','frb:IORB','price:SPY']
        policy['input_pins']=[digest(encoded(payload))]
        learning.validate_inputs(payload,policy,digest(encoded(policy)),resolver)
        binding['historical_use']='DATE_ARCHIVE_RESEARCH_ONLY'
        with self.assertRaisesRegex(ValueError,'PRIMARY_HISTORY_NOT_PIT'):
            learning.validate_inputs(payload,policy,digest(encoded(policy)),resolver)

    def test_workflow_uses_existing_hosted_cadence_and_no_stale_fallback(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/daily_crisis_monitor.yml').read_text())
        job=workflow['jobs']['monitor']; steps=job['steps']
        self.assertEqual(job['runs-on'],'ubuntu-latest')
        collect=next(s for s in steps if s.get('id')=='a4_primary_collect')
        self.assertIn('--publish',collect['run'])
        self.assertLess(collect['run'].index('A4_INPUT_ROOT='),collect['run'].index('python tools/collect_'))
        self.assertIn('PRIMARY',steps[-1]['run'])
        legacy=next(s for s in steps if s.get('name')=='Configure rclone')
        self.assertIn('A4_PRIMARY_COLLECTION_ENABLED',legacy['env']['RCLONE_CONFIG_GDRIVE'])
        self.assertIn('A4_RCLONE_CONFIG_GDRIVE',legacy['env']['RCLONE_CONFIG_GDRIVE'])
        cycle=next(s for s in steps if s.get('id')=='a4_cycle')
        self.assertIn('--learning-input-root outputs/market_analysis_inputs',cycle['run'])
        config=next(s for s in steps if s.get('id')=='a4_primary_config')
        self.assertIn('A4_RCLONE_CONFIG_GDRIVE',config['env']['MACRO_DRIVE_CONFIG'])
        self.assertIn('command -v rclone',config['run'])
        self.assertLess(config['run'].index('sudo install'),config['run'].index('python tools/configure_'))

    def test_cloud_final_gate_propagates_each_failed_prerequisite_in_real_shell(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/daily_crisis_monitor.yml').read_text())
        script=workflow['jobs']['monitor']['steps'][-1]['run']
        bash = str(Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Git/bin/bash.exe') if os.name=='nt' else shutil.which('bash')
        self.assertTrue(bash and Path(bash).is_file(),'actual bash required for workflow exit-status validation')
        for research, primary in (('true','false'),('true','true'),('false','true')):
            baseline=dict(os.environ,RESEARCH_ENABLED=research,PRIMARY_ENABLED=primary,
                          RESTORE='success',CYCLE='success',PERSIST='success',PRIMARY_CONFIG='success',PRIMARY='success',DATA_CENTER='success')
            self.assertEqual(subprocess.run([bash,'-c',script],env=baseline,capture_output=True,timeout=10).returncode,0)
            keys=(['RESTORE','CYCLE','PERSIST'] if research=='true' else [])+(['PRIMARY_CONFIG','PRIMARY','DATA_CENTER'] if primary=='true' else [])
            for key in keys:
                for outcome in ('failure','skipped','cancelled'):
                    with self.subTest(research=research,primary=primary,key=key,outcome=outcome):
                        result=subprocess.run([bash,'-c',script],env=dict(baseline,**{key:outcome}),capture_output=True,timeout=10)
                        self.assertNotEqual(result.returncode,0)


if __name__=='__main__':unittest.main()
