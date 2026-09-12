#!/usr/bin/env python3
"""Fault-injection regressions for durable history; synthetic data is not coverage."""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.long_history_lake import Lake,LocalTransport,sec_rows,fact_coverage,issuer_queue,encoded,digest,materialize,wb_rows,PREFIX


def source():
    base=dict(start='2016-01-01',end='2016-12-31',filed='2017-02-01',accn='0000000001-17-000001',form='10-K',val=100)
    amendment=dict(base,filed='2018-01-01',accn='0000000001-18-000001',form='10-K/A',val=90)
    return dict(cik=1,facts={'us-gaap':{'Revenues':{'units':{'USD':[base,amendment]}}}})


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.t=LocalTransport(self.root/'remote')
        self.lake=Lake(self.t,self.root/'first')

    def put(self,lake=None,value=100):
        lake=lake or self.lake
        lake.dataset('sec/0000000001',[b'original'],[dict(end='2016-12-31',filed='2017-02-01',value=value,concept='Revenue',unit='USD')],
            dict(evidence='SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT',rows=1))

    def test_roundtrip_and_version_preservation(self):
        self.put(); first=self.lake.publish('one',{})
        next_lake=Lake(self.t,self.root/'second'); self.put(next_lake,90)
        second=next_lake.publish('two',{})
        self.assertNotEqual(first['catalog_sha256'],second['catalog_sha256'])
        self.assertEqual(next_lake.get_records('sec/0000000001')[0]['value'],90)
        old=json.loads(next_lake.read_hash('catalogs',first['catalog_sha256']))
        self.assertIn(old['datasets']['sec/0000000001']['normalized'],next_lake.catalog['locations'])
        self.assertFalse(second['remote_verified'])

    def test_unchanged_objects_not_uploaded_again(self):
        self.put(); self.lake.publish('one',{})
        after=Lake(self.t,self.root/'second'); self.put(after)
        self.assertFalse(after.pending)
        self.assertEqual(after.publish('two',{})['new_packs'],0)

    def test_stale_writer_cannot_advance(self):
        other=Lake(self.t,self.root/'second')
        self.put(); self.lake.publish('one',{})
        self.put(other)
        with self.assertRaisesRegex(ValueError,'stale_writer'): other.publish('two',{})

    def test_corruption_stops_clean_consumer(self):
        self.put(); self.lake.publish('one',{})
        pack=next((self.root/'remote'/PREFIX/'packs').iterdir()); pack.write_bytes(b'bad')
        reader=Lake(self.t,self.root/'clean')
        with self.assertRaisesRegex(ValueError,'remote_hash'): reader.get_records('sec/0000000001')

    def test_failed_readback_no_catalog_commit(self):
        self.put()
        original=self.t.read
        def broken(path):
            if '/packs/' in path: return b'corrupt'
            return original(path)
        self.t.read=broken
        with self.assertRaisesRegex(ValueError,'remote_hash'): self.lake.publish('one',{})
        self.assertEqual(self.t.names(PREFIX+'/commits'),[])

    def test_failure_preserves_prior_but_consumer_blocks(self):
        self.put(); self.lake.publish('one',{})
        other=Lake(self.t,self.root/'second'); other.blocked('sec/0000000001',ValueError('HTTP_429'))
        self.assertEqual(other.catalog['datasets']['sec/0000000001']['status'],'STALE_RETAINED')
        other.publish('two',{})
        with self.assertRaisesRegex(ValueError,'stale_dataset'):
            materialize(other,self.root/'x.sqlite',['sec/0000000001'],'2026-09-12')

    def test_amendments_and_filed_cutoff(self):
        early,_=sec_rows(encoded(source()),'0000000001','2016-01-01','2017-12-31')
        later,_=sec_rows(encoded(source()),'0000000001','2016-01-01','2026-09-12')
        self.assertEqual([r['value'] for r in early],[100])
        self.assertEqual([r['value'] for r in later],[100,90])
        self.assertEqual(later[0]['duration_days'],366)

    def test_identity_conflict_fails(self):
        src=source(); values=src['facts']['us-gaap']['Revenues']['units']['USD']
        values.append(dict(values[0],val=1))
        with self.assertRaisesRegex(ValueError,'conflicting_fact_version'):
            sec_rows(encoded(src),'0000000001','2016-01-01','2026-09-12')
        with self.assertRaisesRegex(ValueError,'issuer_identity'):
            sec_rows(encoded(source()),'0000000002','2016-01-01','2026-09-12')

    def test_no_manufactured_ten_years(self):
        rows,_=sec_rows(encoded(source()),'0000000001','2016-01-01','2026-09-12')
        c=fact_coverage(rows,'2016-01-01','2026-09-12')
        self.assertEqual(c['years_with_any_facts'],[2016])
        self.assertEqual(len(c['missing_years']),9)
        self.assertEqual(c['statement_completeness'],'NOT_CERTIFIED')

    def test_ytd_quarter_and_currency_remain_distinct(self):
        src=source(); units=src['facts']['us-gaap']['Revenues']['units']
        units['EUR']=[dict(units['USD'][0])]
        units['USD'].append(dict(units['USD'][0],start='2016-10-01',val=30))
        rows,_=sec_rows(encoded(src),'0000000001','2016-01-01','2026-09-12')
        self.assertEqual(len(rows),4)
        self.assertEqual({r['unit'] for r in rows},{'USD','EUR'})
        self.assertIn(92,{r['duration_days'] for r in rows})

    def test_whole_cohort_and_missing_mapping(self):
        members=[dict(ticker='A'+str(i)) for i in range(1000)]
        mapping={str(i):dict(ticker='A'+str(i),cik_str=i+1) for i in range(999)}
        groups,missing=issuer_queue(members,mapping)
        self.assertEqual(len(groups),999); self.assertEqual(len(missing),1)
        with self.assertRaisesRegex(ValueError,'cohort_below_1000'): issuer_queue(members[:2],mapping)

    def test_retains_rolling_prefix_not_interior_gap(self):
        from tools.long_history_lake import retain_price_prefix
        old=[dict(observation_date='2016-01-0'+str(i),value=i,evidence='current_only') for i in range(1,6)]
        new=[dict(observation_date='2016-01-0'+str(i),value=i*10,evidence='current_only') for i in (3,5)]
        rows,n=retain_price_prefix(old,new,'2026-09-11T00:00:00+00:00')
        self.assertEqual(n,2)
        self.assertEqual([r['value'] for r in rows],[1,2,30,50])
        self.assertEqual(rows[0]['source_retrieved_at'],'2026-09-11T00:00:00+00:00')

    def test_sql_cutoff(self):
        self.put(); self.lake.publish('one',{})
        reader=Lake(self.t,self.root/'consumer')
        count=materialize(reader,self.root/'x.sqlite',['sec/0000000001'],'2016-12-31')
        self.assertEqual(count,0)

    def test_current_vintage_cannot_be_backdated(self):
        self.lake.dataset('current/UNRATE',[b'raw'],[dict(observation_date='2000-01-01',value=4)],
            dict(evidence='current_only',retrieved_at='2026-09-12T00:00:00+00:00'))
        with self.assertRaisesRegex(ValueError,'current_vintage_historical_cutoff_forbidden'):
            materialize(self.lake,self.root/'x.sqlite',['current/UNRATE'],'2016-12-31')

    def test_worldbank_identity_and_partial_pages(self):
        payload=[dict(pages=1,total=1),[dict(indicator=dict(id='SP.POP.TOTL'),countryiso3code='USA',date='2000',value=100)]]
        rows=wb_rows(encoded(payload),'SP.POP.TOTL','1996-01-01','2026-09-12','2026-09-12T00:00:00+00:00')
        self.assertEqual(rows[0]['evidence'],'current_only')
        payload[0]['pages']=2
        with self.assertRaisesRegex(ValueError,'worldbank_pagination'):
            wb_rows(encoded(payload),'SP.POP.TOTL','1996-01-01','2026-09-12','2026-09-12T00:00:00+00:00')

if __name__=='__main__': unittest.main()
