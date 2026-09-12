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
from unittest.mock import patch
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
        with self.assertRaisesRegex(ValueError,'remote_hash'): Lake(self.t,self.root/'clean')

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

    def test_schema_and_window_changes_invalidate_http_validators(self):
        from tools.long_history_lake import sec_conditional,extraction_identity
        old=dict(start='2016-01-01',through='2026-09-12',http={'etag':'v1'},extraction_sha256=extraction_identity(),deferred_until=None)
        self.assertEqual(sec_conditional(old,old['start'],old['through']),old['http'])
        with patch('tools.long_history_lake.FORMS',{'10-K'}):
            self.assertIsNone(sec_conditional(old,old['start'],old['through']))
        self.assertEqual(sec_conditional(old,old['start'],'2026-09-13'),old['http'])
        self.assertIsNone(sec_conditional(old,old['start'],'2026-09-11'))
        self.assertIsNone(sec_conditional(dict(old,extraction_sha256='old'),old['start'],old['through']))

    def test_deferred_financial_period_invalidates_reuse_when_due(self):
        from tools.long_history_lake import sec_future_boundary,sec_conditional,extraction_identity
        boundary=sec_future_boundary(encoded(source()),'2017-12-31')
        self.assertEqual(boundary,'2018-01-01')
        old=dict(start='2016-01-01',through='2017-12-31',http={'etag':'v1'},extraction_sha256=extraction_identity(),deferred_until=boundary)
        self.assertIsNone(sec_conditional(old,old['start'],'2018-01-01'))

    def test_old_catalog_corruption_is_not_hidden_by_valid_tip(self):
        self.put(); first=self.lake.publish('one',{})
        other=Lake(self.t,self.root/'second'); self.put(other,90); other.publish('two',{})
        (self.root/'remote'/PREFIX/'catalogs'/first['catalog_sha256']).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'remote_hash'): Lake(self.t,self.root/'third')

    def test_preserves_fiscal_contexts(self):
        src=source(); values=src['facts']['us-gaap']['Revenues']['units']['USD']
        values.append(dict(values[0],fy=2017,fp='FY',frame='CY2016'))
        rows,_=sec_rows(encoded(src),'0000000001','2016-01-01','2026-09-12')
        self.assertEqual(len(rows),3)
        self.assertEqual(sum(r['frame']=='CY2016' for r in rows),1)

    def test_unmapped_security_keeps_cycle_partial(self):
        from tools.long_history_lake import diagnostics
        self.lake.catalog['datasets']['universe/cohort']=dict(status='COLLECTED',active_issuer_keys=[],missing=[dict(ticker='HOLX')])
        self.assertEqual(diagnostics(self.lake)['status'],'PARTIAL')

    def test_country_year_missing_coverage(self):
        from tools.long_history_lake import wb_coverage
        rows=[dict(country='USA',observation_date='2024-01-01',value=3),dict(country='USA',observation_date='2025-01-01',value=None)]
        result=wb_coverage(rows)
        self.assertEqual(result['missing_values'],1)
        self.assertEqual(result['missing_country_years'],[dict(country='USA',year=2025)])
        self.assertEqual(result['country_coverage']['USA']['latest'],'2024-01-01')

    def test_secret_job_is_default_branch_only(self):
        workflow=(ROOT/'.github/workflows/long_history_research.yml').read_text()
        self.assertIn("branches: ['master']",workflow)
        self.assertIn("&& github.ref == 'refs/heads/master'",workflow)
        self.assertNotIn('codex/durable-long-history-20260912',workflow)

    def test_transient_fred_retry_and_secret_safe_failure(self):
        from urllib.error import URLError,HTTPError
        from tools.long_history_lake import fetch_fred_retry,safe_error
        expected=([b'data'],'2026-09-12T00:00:00+00:00')
        with patch('tools.long_history_lake.fetch_fred',side_effect=[URLError('api_key=private'),expected]) as fetch,patch('tools.long_history_lake.time.sleep'):
            self.assertEqual(fetch_fred_retry('NFCI','1996-01-01','2026-09-12','alfred'),expected)
            self.assertEqual(fetch.call_count,2)
        self.assertEqual(safe_error(HTTPError('https://example.com/?api_key=private',403,'private',{},None)),'HTTP_403')
        with patch('tools.long_history_lake.fetch_fred',side_effect=URLError('api_key=private')) as fetch,patch('tools.long_history_lake.time.sleep'):
            with self.assertRaisesRegex(ValueError,'^TRANSPORT_ERROR$'):
                fetch_fred_retry('NFCI','1996-01-01','2026-09-12','alfred')
            self.assertEqual(fetch.call_count,3)

    def test_source_contract_errors_are_not_retried(self):
        from tools.long_history_lake import fetch_fred_retry
        with patch('tools.long_history_lake.fetch_fred',side_effect=ValueError('alfred_count')) as fetch:
            with self.assertRaisesRegex(ValueError,'alfred_count'):
                fetch_fred_retry('NFCI','1996-01-01','2026-09-12','alfred')
            self.assertEqual(fetch.call_count,1)

    def test_fred_missing_dates_survive_parser(self):
        from tools.long_history_lake import parse_graph,fred_missing
        rows,missing=parse_graph(b'observation_date,UNRATE\n2025-09-01,4.4\n2025-10-01,.\n2025-11-01,4.5\n',
            'UNRATE','2025-01-01','2025-12-31','2026-09-12T00:00:00+00:00')
        result=fred_missing(rows,missing)
        self.assertEqual(result['missing_values'],1)
        self.assertEqual(result['missing_observation_dates'],['2025-10-01'])

    def test_current_mapping_excludes_retained_old_issuer(self):
        from tools.long_history_lake import diagnostics
        self.put()
        self.lake.catalog['datasets']['sec/0000000002']=dict(status='BLOCKED',rows=0)
        self.lake.catalog['datasets']['universe/cohort']=dict(status='COLLECTED',active_issuer_keys=['sec/0000000001'])
        report=diagnostics(self.lake)
        self.assertEqual(report['financial_issuers'],1)
        self.assertEqual(report['archived_inactive_issuers'],1)
        self.assertEqual(report['status_counts']['BLOCKED'],0)
        self.assertIn('sec/0000000002',self.lake.catalog['datasets'])

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


    def append_catalog_for_fault(self,catalog,parent):
        """Inject a hash-valid successor with broken dependencies, without publishing."""
        catalog=copy.deepcopy(catalog)
        catalog['generation']+=1
        raw=encoded(catalog); catalog_sha=digest(raw)
        self.t.write(PREFIX+'/catalogs/'+catalog_sha,raw)
        commit=encoded(dict(schema='long-history-commit-v1',parent=parent,
            catalog=catalog_sha,generation=catalog['generation']))
        self.t.write(PREFIX+'/commits/'+digest(commit),commit)

    def alternate_pack(self,names_and_bytes):
        import io
        import warnings
        import zipfile
        output=io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
                for name,raw in names_and_bytes: archive.writestr(name,raw)
        raw=output.getvalue(); sha=digest(raw)
        self.t.write(PREFIX+'/packs/'+sha,raw)
        return sha

    def test_missing_active_pack_blocks_restore(self):
        self.put(); self.lake.publish('one',{})
        next((self.root/'remote'/PREFIX/'packs').iterdir()).unlink()
        with self.assertRaisesRegex(ValueError,'checkpoint_object_size'):
            Lake(self.t,self.root/'empty-cache')

    def test_old_pack_missing_cannot_hide_behind_empty_tip(self):
        self.put(); first=self.lake.publish('one',{})
        old_pack=next((self.root/'remote'/PREFIX/'packs').iterdir())
        latest=copy.deepcopy(self.lake.catalog)
        latest['datasets']={}; latest['locations']={}
        self.append_catalog_for_fault(latest,first['commit_sha256'])
        old_pack.unlink()
        with self.assertRaisesRegex(ValueError,'checkpoint_object_size'):
            Lake(self.t,self.root/'empty-cache')

    def test_valid_pack_hash_with_missing_object_is_rejected(self):
        self.put(); first=self.lake.publish('one',{})
        latest=copy.deepcopy(self.lake.catalog)
        obj=latest['datasets']['sec/0000000001']['normalized']
        latest['locations'][obj]=self.alternate_pack([(digest(b'other'),b'other')])
        self.append_catalog_for_fault(latest,first['commit_sha256'])
        with self.assertRaisesRegex(ValueError,'pack_dependency'):
            Lake(self.t,self.root/'empty-cache')

    def test_valid_pack_hash_with_wrong_object_bytes_is_rejected(self):
        self.put(); first=self.lake.publish('one',{})
        latest=copy.deepcopy(self.lake.catalog)
        obj=latest['datasets']['sec/0000000001']['normalized']
        latest['locations'][obj]=self.alternate_pack([(obj,b'wrong-content')])
        self.append_catalog_for_fault(latest,first['commit_sha256'])
        with self.assertRaisesRegex(ValueError,'pack_object_hash'):
            Lake(self.t,self.root/'empty-cache')

    def test_duplicate_pack_members_are_rejected(self):
        self.put(); first=self.lake.publish('one',{})
        latest=copy.deepcopy(self.lake.catalog)
        obj=latest['datasets']['sec/0000000001']['normalized']
        raw=self.lake.get_bytes(obj)
        latest['locations'][obj]=self.alternate_pack([(obj,raw),(obj,raw)])
        self.append_catalog_for_fault(latest,first['commit_sha256'])
        with self.assertRaisesRegex(ValueError,'pack_inventory'):
            Lake(self.t,self.root/'empty-cache')

    def test_warm_disk_and_memory_cache_do_not_hide_remote_corruption(self):
        self.put(); self.lake.publish('one',{})
        reader=Lake(self.t,self.root/'consumer')
        self.assertEqual(reader.get_records('sec/0000000001')[0]['value'],100)
        next((self.root/'remote'/PREFIX/'packs').iterdir()).write_bytes(b'bad')
        before=self.t.names(PREFIX+'/commits')
        with self.assertRaisesRegex(ValueError,'remote_hash'): reader.publish('two',{})
        self.assertEqual(self.t.names(PREFIX+'/commits'),before)
        with self.assertRaisesRegex(ValueError,'remote_hash'):
            Lake(self.t,self.root/'consumer')

    def test_sec_304_cannot_publish_after_prior_pack_disappears(self):
        from tools.long_history_lake import collect_financials,extraction_identity
        self.put()
        self.lake.catalog['datasets']['sec/0000000001'].update(
            start='2016-01-01',through='2026-09-12',years_with_any_facts=[2016],
            http={'etag':'v1'},extraction_sha256=extraction_identity(),deferred_until=None)
        self.lake.publish('one',{})
        reader=Lake(self.t,self.root/'collector')
        cohort=self.root/'cohort.json'
        cohort.write_bytes(encoded(dict(candidate_count=1,as_of='2026-09-12',rows=[dict(ticker='A')])))
        before=self.t.names(PREFIX+'/commits')
        next((self.root/'remote'/PREFIX/'packs').iterdir()).unlink()
        with patch('tools.long_history_lake.COHORT_SHA',digest(cohort.read_bytes())), \
             patch('tools.long_history_lake.issuer_queue',return_value=({'0000000001':['A']},[])), \
             patch('tools.long_history_lake.get_public',side_effect=[(b'{}',{}),(None,{'etag':'v1'})]) as fetch:
            collect_financials(reader,cohort,'2016-01-01','2026-09-12')
            self.assertEqual(fetch.call_args.args[1],{'etag':'v1'})
        self.assertEqual(reader.catalog['datasets']['sec/0000000001']['status'],'UNCHANGED')
        with self.assertRaisesRegex(ValueError,'checkpoint_object_size'): reader.publish('two',{})
        self.assertEqual(self.t.names(PREFIX+'/commits'),before)

    def test_shared_packs_are_read_once_per_restore(self):
        from collections import Counter
        self.put(); self.lake.publish('one',{})
        next_lake=Lake(self.t,self.root/'second')
        self.put(next_lake,90); next_lake.publish('two',{})
        expected=set(next_lake.catalog['locations'].values())
        with patch.object(self.t,'read',wraps=self.t.read) as read:
            Lake(self.t,self.root/'clean')
        counts=Counter(c.args[0].rsplit('/',1)[1] for c in read.call_args_list if '/packs/' in c.args[0])
        self.assertEqual(dict(counts),dict.fromkeys(expected,1))

    def test_push_filters_cover_all_consumed_source_paths(self):
        import re
        workflow=(ROOT/'.github/workflows/long_history_research.yml').read_text()
        push=workflow.split('  push:',1)[1].split('  workflow_dispatch:',1)[0]
        paths=set(re.findall(r"^      - '([^']+)'$",push,re.MULTILINE))
        checkout=set(re.findall(r'^            /(.+)$',workflow,re.MULTILINE))
        self.assertFalse(checkout-paths,'Unchecked dependency changes: '+repr(sorted(checkout-paths)))


if __name__=='__main__': unittest.main()
