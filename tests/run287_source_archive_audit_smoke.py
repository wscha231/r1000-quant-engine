#!/usr/bin/env python3
"""Offline archive/provenance regressions, also called by the registered clean7y suite."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import audit_run287_source_archive as audit


class ArchiveAuditTests(unittest.TestCase):
    def inspect(self,files):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.zip'
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for name,content in files: archive.writestr(name,content)
            return audit.audit_archive(path,expected_hash=hashlib.sha256(path.read_bytes()).hexdigest(),expected_bytes=path.stat().st_size)

    def test_wrong_hash_stops_before_parsing_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.zip';path.write_bytes(b'not a zip')
            result=audit.audit_archive(path)
            self.assertEqual(result['status'],'SOURCE_IDENTITY_FAILED')
            self.assertFalse(result['artifact_identity_verified'])
            self.assertNotIn('books',result)

    def test_manifest_only_never_counts_as_prices(self):
        result=self.inspect([('cache_prices/replay_price_cache_manifest.json','{"start":"2016-01-01","end":"2026-09-09","status":"completed"}')])
        self.assertEqual(result['price_cache']['parquet_files'],0)
        self.assertIsNone(result['price_cache']['common_end'])
        self.assertFalse(result['research_replay_ready'])
        self.assertFalse(result['artifact_identity_verified'])
        self.assertEqual(result['data_kind'],'SYNTHETIC_TEST_ONLY')

    def test_book_counts_missing_and_future_provenance_without_raw_rows(self):
        csv='rebalance_date,ticker,valuation_price_cutoff_date,feature_available_from,private_note\n2019-05-31,AAA,2019-06-01,2019-06-02T20:00:00Z,DO_NOT_PUBLISH\n2019-06-28,BBB,,bad,DO_NOT_PUBLISH\n'
        result=self.inspect([('outputs/reports/candidate_replay_book.csv',csv)])
        book=result['books'][0]
        self.assertEqual(book['rows'],2);self.assertEqual(book['unique_tickers'],2)
        self.assertTrue(book['has_2019_05_31_decision'])
        self.assertEqual(book['features_after_decision_day_rows'],1)
        self.assertEqual(book['prices_after_decision_day_rows'],1)
        self.assertEqual(book['dates']['valuation_price_cutoff_date']['invalid_or_missing'],1)
        self.assertFalse(book['intraday_pit_verified'])
        self.assertNotIn('DO_NOT_PUBLISH',json.dumps(result))

    def test_real_parquet_dates_are_scanned(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        data=io.BytesIO()
        pq.write_table(pa.table({'date':['2019-05-09','2026-06-23'],'close':[100.,200.]}),data)
        result=self.inspect([('cache_prices/AAA.parquet',data.getvalue())])
        prices=result['price_cache']
        self.assertEqual(prices['parquet_files'],1);self.assertEqual(prices['total_rows'],2)
        self.assertEqual(prices['common_start'],'2019-05-09');self.assertEqual(prices['common_end'],'2026-06-23')
        self.assertFalse(prices['missing_session_and_lifecycle_checks_completed'])

    def test_traversal_duplicates_and_symlinks_rejected(self):
        for name in ('../escape.csv','/absolute.csv','C:/drive.csv','safe\\escape.csv'):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'unsafe_or_duplicate'):
                self.inspect([(name,'x')])
        with self.assertRaisesRegex(ValueError,'unsafe_or_duplicate'):
            self.inspect([('Safe.csv','x'),('safe.csv','x')])
        symlink=zipfile.ZipInfo('link');symlink.external_attr=(stat.S_IFLNK|0o777)<<16
        with self.assertRaisesRegex(ValueError,'unsafe_or_duplicate'):
            self.inspect([(symlink,'target')])

    def test_ambiguous_anchor_does_not_select_first_match(self):
        suffix=audit.EXPECTED['raw_candidate_replay_book'][0]
        result=self.inspect([(suffix,'ticker\nAAA\n'),('nested/'+suffix,'ticker\nBBB\n')])
        self.assertEqual(result['contract_files']['raw_candidate_replay_book']['match_count'],2)
        self.assertFalse(result['contract_files']['raw_candidate_replay_book']['hash_verified'])

    def test_metric_allowlist_does_not_publish_account_or_credentials(self):
        payload={'cagr':.1,'max_drawdown':-.2,'api_key':'secret','account':{'equity':123},'start_date':'2020-01-01','sharpe':float('nan')}
        result=audit.metric_summary(payload)
        self.assertEqual(result,{'cagr':.1,'max_drawdown':-.2,'start_date':'2020-01-01'})

    def test_expected_hashes_match_existing_source_contract(self):
        contract=json.loads((ROOT/'docs/run287_next_single_ab_readiness_contract.json').read_text())
        for entry in contract['generated_substrate']['local_artifacts']:
            suffix,sha=audit.EXPECTED[entry['id']]
            self.assertEqual(sha,entry['expected_sha256'])
            self.assertTrue(entry['path'].replace('\\','/').endswith(suffix))


if __name__=='__main__':unittest.main(verbosity=2)
