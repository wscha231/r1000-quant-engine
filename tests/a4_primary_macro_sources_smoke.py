"""Government economic input identity, current-vintage clocks and shared archive."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import a4_primary_macro_sources as a
from tools import a4_primary_sources as p
from tools import collect_a4_primary_data as c
from tools import market_analysis_engine as m
from tools import a4_macro_learning as learning
from tools import a4_liquidity_analysis as liquidity
from tools.macro_research_checkpoint import LocalTransport
from tools.macro_history_sources import encoded,digest
from tests.a4_primary_sources_smoke import NOW,archive,nyfed


def h10(*,unit='Index:_1997_Jan_100',name='JRXWTFB_N.B'):
    raw=io.BytesIO()
    xml=('<Data><Series SERIES_NAME="'+name+'" FREQ="9" FX="BRD" CURRENCY="NA" UNIT="'+unit+'" UNIT_MULT="1">'
         '<Obs TIME_PERIOD="2026-11-05" OBS_STATUS="A" OBS_VALUE="120"/>'
         '<Obs TIME_PERIOD="2026-11-06" OBS_STATUS="A" OBS_VALUE="121"/></Series>'
         '<Series SERIES_NAME="V0.JRXWTFB_N.B" FREQ="9" FX="BRDG"><Obs TIME_PERIOD="1996-01-01" OBS_STATUS="A" OBS_VALUE="99"/></Series></Data>')
    with zipfile.ZipFile(raw,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('H10_data.xml',xml);z.writestr('H10_struct.xml','<Structure/>')
    return raw.getvalue()


def treasury(feed='ust_nominal',year=2026):
    fields='<d:TC_10YEAR m:type="Edm.Double">-0.25</d:TC_10YEAR>' if feed=='ust_real' else (
        '<d:BC_2YEAR m:type="Edm.Double">4</d:BC_2YEAR><d:BC_10YEAR m:type="Edm.Double">4.2</d:BC_10YEAR>')
    entry='<entry><updated>2030-01-01T00:00:00Z</updated><content><m:properties><d:NEW_DATE>'+str(year)+'-11-06T00:00:00</d:NEW_DATE>'+fields+'</m:properties></content></entry>'
    return ('<feed xmlns="'+a.ATOM+'" xmlns:d="'+a.DATA+'" xmlns:m="'+a.META+'">'+entry+'</feed>').encode()


def bls(payload):
    series=[]
    for native in a.BLS:
        year=payload['endyear'];month='M10' if year=='2026' else 'M12'
        series.append(dict(seriesID=native,data=[dict(year=year,period=month,value='4.1' if native=='LNS14000000' else '159293' if native.startswith('CES') else '300.1',footnotes=[dict(code='P',text='preliminary')])]))
    return encoded(dict(status='REQUEST_SUCCEEDED',message=[],Results=dict(series=series)))


def fetch(url,limit,body=None):
    if url==a.BLS_URI:return bls(json.loads(body))
    if '/h10/' in url:return h10()
    if 'daily_treasury_real_yield_curve' in url:return treasury('ust_real')
    if 'daily_treasury_yield_curve' in url:return treasury()
    for feed,values in p.FEEDS.items():
        if values[0]==url:return nyfed(feed) if feed in {'sofr','tgcr','effr'} else archive(feed)
    raise AssertionError('unexpected provider request')


class EconomicTests(unittest.TestCase):
    def test_dollar_current_definition_excludes_old_goods_only_history(self):
        rows,receipt=a.normalize(h10(),'h10',collected_at=NOW)
        self.assertEqual(len(rows),2);self.assertEqual(rows[-1]['value'],121)
        self.assertEqual(rows[0]['native_unit'],'Index:_1997_Jan_100')
        self.assertEqual(receipt['first_observation'],'2026-11-05')
        self.assertTrue(all(r['source_id']=='frb:H10_BROAD' for r in rows))
        for kwargs in (dict(unit='Index:_2006_Jan_100'),dict(name='V0.JRXWTFB_N.B')):
            with self.assertRaises(ValueError):a.normalize(h10(**kwargs),'h10',collected_at=NOW)

    def test_treasury_negative_real_rates_are_valid_and_updated_is_not_publication(self):
        rows,receipt=a.normalize(treasury('ust_real'),'ust_real',collected_at=NOW,request_year=2026)
        self.assertEqual(rows[0]['value'],-.25)
        self.assertEqual(rows[0]['available_at'],NOW);self.assertIsNone(rows[0]['published_at'])
        self.assertFalse(receipt['historical_pit_certified'])
        for year in (None,True,2000,2027):
            with self.subTest(year=year),self.assertRaises(ValueError):
                a.normalize(treasury('ust_real'),'ust_real',collected_at=NOW,request_year=year)
        with self.assertRaisesRegex(ValueError,'TREASURY_YEAR'):
            a.normalize(treasury(year=2025),'ust_nominal',collected_at=NOW,request_year=2026)

    def test_treasury_missing_duplicate_and_paginated_data_refuse(self):
        raw=treasury()
        variants=[raw.replace(b'<d:BC_2YEAR m:type="Edm.Double">4</d:BC_2YEAR>',b''),
                  raw.replace(b'</m:properties>',b'<d:BC_2YEAR>5</d:BC_2YEAR></m:properties>'),
                  raw.replace(b'</feed>',b'<link rel="next" href="https://untrusted.example"/></feed>'),
                  b'<!DOCTYPE feed [<!ENTITY x "boom">]>'+raw]
        for body in variants:
            with self.assertRaises(ValueError):a.normalize(body,'ust_nominal',collected_at=NOW,request_year=2026)

    def test_bls_decade_windows_keep_sa_footnotes_and_actual_collection(self):
        uri,payload=a.request_spec('bls_1996_2005',NOW)
        rows,receipt=a.normalize(bls(payload),'bls_1996_2005',collected_at=NOW)
        self.assertEqual(uri,a.BLS_URI);self.assertEqual(len(rows),4)
        self.assertTrue(all(r['seasonal_basis']=='SA' and r['available_at']==NOW and r['published_at'] is None for r in rows))
        self.assertTrue(all(r['source_footnotes']==[dict(code='P',text='preliminary')] for r in rows))
        self.assertEqual(receipt['request_json'],payload)
        self.assertEqual(receipt['first_observation'],'2005-12-01')
        self.assertTrue(all(r['source_id'].startswith('bls:') for r in rows))

    def test_bls_partial_messages_scope_annual_periods_and_duplicates_refuse(self):
        _,payload=a.request_spec('bls_recent',NOW);base=json.loads(bls(payload))
        for kind in ('message','scope','annual','duplicate','negative'):
            value=copy.deepcopy(base)
            if kind=='message':value['message']=['REQUEST LIMIT EXCEEDED']
            if kind=='scope':value['Results']['series'][0]['seriesID']='foreign'
            if kind=='annual':value['Results']['series'][0]['data'][0]['period']='M13'
            if kind=='duplicate':value['Results']['series'][0]['data']*=2
            if kind=='negative':value['Results']['series'][0]['data'][0]['value']='-1'
            with self.subTest(kind=kind),self.assertRaises(ValueError):a.normalize(encoded(value),'bls_recent',collected_at=NOW)

    def test_learning_never_silently_splices_alternate_publisher_series(self):
        _,payload=a.request_spec('bls_recent',NOW)
        rows,_=a.normalize(bls(payload),'bls_recent',collected_at=NOW)
        row=next(r for r in rows if r['logical_id']=='unemployment')
        other=liquidity.parse_original(b'observation_date,UNRATE\n2026-10-01,9\n',
            dict(source_id='fred:UNRATE',collected_at=NOW))[0]
        sessions=[dict(session='2026-11-09',close_utc='2026-11-09T21:00:00Z')]
        with self.assertRaisesRegex(ValueError,'CHOOSE_ONE_SOURCE'):
            learning.replay_features([row,other],sessions)
        other['available_at']='2026-11-10T21:00:00Z'
        before=learning.replay_features([row],sessions)
        after=learning.replay_features([row,other],sessions)
        for key in before:
            self.assertTrue(before[key].equals(after[key]))

    def test_typed_generation_replays_shared_objects_and_keeps_bank_codec_separate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);prepared=a.store_capture(root/'prepare',h10(),'h10',collected_at=NOW)
            transport=LocalTransport(root/'remote');result=a.publish_capture(transport,root/'prepare',prepared['generation_sha256'],cutoff=NOW)
            self.assertFalse(result['transport_readback_verified'])
            rows,manifest=a.read_generation(transport,prepared['generation_sha256'],cutoff=NOW)
            self.assertEqual(len(rows),2);self.assertFalse(manifest['training_admitted'])
            with self.assertRaisesRegex(ValueError,'GENERATION_SCHEMA'):
                p.read_generation(transport,prepared['generation_sha256'],cutoff=NOW)
            with self.assertRaisesRegex(ValueError,'FUTURE_CAPTURE'):
                a.read_generation(transport,prepared['generation_sha256'],cutoff='2026-11-06T00:00:00Z')
            (transport.root/p.PREFIX/'objects'/manifest['original_sha256']).write_bytes(b'corrupt')
            with self.assertRaises(ValueError):a.read_generation(transport,prepared['generation_sha256'],cutoff=NOW)

    def test_integrated_capture_adds_seven_government_feeds_without_risk_promotion(self):
        with tempfile.TemporaryDirectory() as d,patch.object(p,'now',return_value=NOW):
            root=Path(d)
            result=c.collect(root/'attempt',code_sha='a'*40,fetcher=fetch,transport=LocalTransport(root/'remote'),include_economic=True)
            self.assertEqual(result['originals'],13);self.assertEqual(result['failures'],[])
            report=json.loads((root/'attempt/market_analysis.json').read_bytes())
            families={r['family'] for r in report['macro_direction_inputs'].values()}
            self.assertEqual(families,{'GROWTH','INFLATION','RATES','FX'})
            self.assertFalse(report['enhanced_readiness']['macro']) # Licensed native credit evidence is still absent.
            self.assertEqual(report['status'],'DATA_BLOCKED');self.assertFalse(result['model_fit_performed'])
            self.assertTrue(all(report['enhanced_readiness'][k] for k in ('funding','liquidity','bank_credit')))

    def test_optional_economic_failure_keeps_verified_core_bytes_and_closed_partial_attempt(self):
        def partial(url,limit,body=None):return b'invalid' if '/h10/' in url else fetch(url,limit,body)
        with tempfile.TemporaryDirectory() as d,patch.object(p,'now',return_value=NOW):
            root=Path(d);result=c.collect(root/'attempt',code_sha='a'*40,fetcher=partial,
                transport=LocalTransport(root/'remote'),include_economic=True)
            self.assertEqual(result['status'],'LOCAL_PARTIAL_RESEARCH_CAPTURE')
            self.assertEqual(result['originals'],12)
            self.assertEqual(result['failures'],[dict(feed='h10',blocker='PRIMARY_CAPTURE_OR_NORMALIZATION_FAILED')])
            self.assertEqual(len(result['publication']),12)
            self.assertTrue((root/'attempt/inputs/request.json').exists())
            self.assertFalse(result['source_admitted']);self.assertFalse(result['model_fit_performed'])


if __name__=='__main__':unittest.main()
