"""Native Source-only ownership freshness regressions; no Main adapter imports."""
from __future__ import annotations
import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools import run_sec_submissions_collector as source
from tools import run_sec_form4_parser as parser
from tools import run_sec_form4_merge_shards as merge
from tools.run_sec_ownership_signals import build_form4_signal
ROOT = Path(__file__).resolve().parent.parent
NOW = '2026-10-20T13:59:06+00:00'
OLD = '2026-05-19T10:03:54+00:00'
ACC = '0000000001-26-000001'

def payload(accession=ACC, accepted=NOW):
    return {'cik': 1, 'filings': {'recent': {'form': ['4'], 'accessionNumber': [accession], 'acceptanceDateTime': [accepted], 'filingDate': [accepted[:10]], 'reportDate': [accepted[:10]], 'primaryDocument': ['ownership.xml']}}}

def filing(accession=ACC, cik='0000000001', accepted=NOW, form='4'):
    return dict(ticker='TEST', cik10=cik, accession_number=accession, form_type=form, primary_document='ownership.xml', accepted_at=accepted, available_from=accepted, filing_date=accepted[:10])

def xml(form='4', code='P', missing=False):
    amounts = '' if missing else '<transactionShares><value>10</value></transactionShares><transactionPricePerShare><value>5</value></transactionPricePerShare>'
    return f'<ownershipDocument><documentType>{form}</documentType>\n    <issuer><issuerCik>1</issuerCik><issuerTradingSymbol>TEST</issuerTradingSymbol></issuer>\n    <reportingOwner><reportingOwnerId><rptOwnerCik>2</rptOwnerCik><rptOwnerName>One</rptOwnerName></reportingOwnerId></reportingOwner>\n    <reportingOwner><reportingOwnerId><rptOwnerCik>3</rptOwnerCik><rptOwnerName>Two</rptOwnerName></reportingOwnerId></reportingOwner>\n    <nonDerivativeTransaction><securityTitle><value>Common</value></securityTitle>\n    <transactionDate><value>2026-10-19</value></transactionDate><transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>\n    <transactionAmounts>{amounts}<footnoteId id="F1"/></transactionAmounts>\n    <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature></nonDerivativeTransaction>\n    <footnotes><footnote id="F1">Private transaction; trading venue not verified.</footnote></footnotes></ownershipDocument>'

def event_rows(form='4', code='P'):
    return parser.parse_form4_xml(xml(form, code), ACC, filing(form=form))

class SECSourceRegression(unittest.TestCase):

    def test_invalid_delay_refuses_before_provider_even_for_empty_input(self):
        for delay in (-1, float('nan'), float('inf'), True):
            with self.subTest(delay=delay), tempfile.TemporaryDirectory() as td, \
                    patch.object(source, 'load_company_tickers', side_effect=AssertionError('provider must not run')):
                with self.assertRaisesRegex(ValueError, 'safety_delay_hours'):
                    source.collect_filings_index(tickers=['TEST'], raw_dir=Path(td), forms=['4'], safety_delay_hours=delay)
                with self.assertRaisesRegex(ValueError, 'safety_delay_hours'):
                    source.available_from(None, safety_delay_hours=delay)
                with self.assertRaisesRegex(ValueError, 'safety_delay_hours'):
                    source.filings_from_submissions('TEST', '1', {'filings': {'recent': {}}}, safety_delay_hours=delay)

    def test_future_accepted_or_missing_source_clock_cannot_be_current(self):
        for accepted in ((pd.Timestamp(NOW) + timedelta(minutes=30)).isoformat(), ''):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as td:
                pit, shard, args = self.make_current_generation(Path(td))
                table = shard / 'sec_filings_index.parquet'
                index = pd.read_parquet(table)
                index['accepted_at'] = accepted
                index.to_parquet(table, index=False)
                path = shard / 'sec_filings_index_summary.json'
                receipt = json.loads(path.read_text())
                receipt['output_sha256']['parquet'] = source.file_hash(table)
                path.write_text(json.dumps(receipt))
                result = merge.run(args)
                self.assertFalse(result['current_eligible'])
                self.assertIn('SOURCE_FILING_CLOCK_CONFLICT', result['blockers'])
                self.assertEqual(result['signal_rows'], 0)

    def test_parser_clocks_must_match_the_checked_index(self):
        for column in ('accepted_at', 'available_from'):
            with self.subTest(column=column), tempfile.TemporaryDirectory() as td:
                pit, shard, args = self.make_current_generation(Path(td))
                table = shard / 'form4_transactions.parquet'
                rows = pd.read_parquet(table)
                rows[column] = OLD
                rows.to_parquet(table, index=False)
                path = shard / 'form4_transactions_summary.json'
                receipt = json.loads(path.read_text())
                receipt['output_sha256']['parquet'] = source.file_hash(table)
                path.write_text(json.dumps(receipt))
                result = merge.run(args)
                self.assertFalse(result['current_eligible'])
                self.assertIn('PARSER_FILING_CLOCK_CONFLICT', result['blockers'])
                self.assertEqual(result['signal_rows'], 0)

    def test_daily_current_range_prevents_history_using_parser_cap(self):
        current = [filing(f'0000000001-26-{i:06d}') for i in range(1, 401)]
        old = [filing(f'0000000001-26-{i:06d}', accepted=OLD) for i in range(401, 1001)]
        recent = {'form': [], 'accessionNumber': [], 'acceptanceDateTime': [],
                  'filingDate': [], 'reportDate': [], 'primaryDocument': []}
        for row in old + current:
            for target, key in [('form', 'form_type'), ('accessionNumber', 'accession_number'),
                                ('acceptanceDateTime', 'accepted_at'), ('filingDate', 'filing_date'),
                                ('primaryDocument', 'primary_document')]:
                recent[target].append(row[key])
            # Late reports must follow acceptance, not the old underlying transaction date.
            recent['reportDate'].append('2025-01-01')
        cutoff = (pd.Timestamp(NOW) - timedelta(days=90)).isoformat()
        seen = []
        def cached_xml(row, raw, **kwargs):
            seen.append(row['accession_number'])
            return Path('unused'), xml()
        with tempfile.TemporaryDirectory() as td, patch.object(source, 'load_company_tickers',
                return_value=pd.DataFrame([dict(ticker='TEST', cik10='0000000001', name='Test')])), \
                patch.object(source, 'fetch_submissions', return_value={'cik': 1, 'filings': {'recent': recent}}), \
                patch.object(parser, 'cache_form4_document', side_effect=cached_xml):
            index = source.collect_filings_index(tickers=['TEST'], raw_dir=Path(td), forms=['4'],
                refresh_recent_submissions=True, history_start=cutoff)
            parsed = parser.parse_form4_index(index, raw_dir=Path(td), max_filings=500)
        self.assertEqual(len(index), 400)
        self.assertEqual(set(seen), {r['accession_number'] for r in current})
        self.assertEqual(parsed.attrs['parse_receipt']['backlog_filings'], 0)
        workflow = (ROOT / '.github/workflows/sec_form4_daily_refresh.yml').read_text()
        self.assertIn('--history-start "$HISTORY_START"', workflow)
        self.assertIn('timedelta(days=90, hours=delay)', workflow)
        self.assertNotIn('--history-end', workflow)

    def test_delayed_availability_range_keeps_the_lower_boundary(self):
        accepted = (pd.Timestamp(NOW) - timedelta(days=91)).isoformat()
        cutoff = (pd.Timestamp(NOW) - timedelta(days=90, hours=24)).isoformat()
        index = source.filings_from_submissions('TEST', '1', payload(accepted=accepted),
            forms=['4'], history_start=cutoff, safety_delay_hours=24)
        self.assertEqual(len(index), 1)
        self.assertEqual(pd.Timestamp(index.iloc[0]['available_from']), pd.Timestamp(NOW) - timedelta(days=90))

    def test_successful_check_with_zero_filings_is_not_source_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);pit=root/'pit';shard=pit/'shards'/'daily'
            index=pd.DataFrame([filing()]).iloc[0:0]
            checks=[{'ticker':'TEST','cik10':'0000000001','status':'CHECKED_NO_NEW_FILINGS','checked_at':NOW,'payload_sha256':'a'*64}]
            source.write_outputs(index,shard,collection_metadata={'source_checks':checks})
            parsed=parser.parse_form4_index(index,raw_dir=root/'raw')
            parser.write_outputs(parsed,shard)
            args=argparse.Namespace(pit_root=str(pit),output_dir=str(root/'out'),as_of_dates_csv='',as_of_date_column='date',window_days=90,decision_at=NOW,source_check_summary=str(shard/'sec_filings_index_summary.json'))
            result=merge.run(args)
            self.assertTrue(result['current_eligible'])
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['ownership_event_status'],'CHECKED_NO_CURRENT_ROWS')
            self.assertEqual(result['legacy_signal_status'],'NO_LEGACY_SIGNALS')
            self.assertEqual(result['signal_rows'],0)
            self.assertEqual(result['blockers'],[])

    def test_checked_issuer_must_match_index_and_parser_scope(self):
        with tempfile.TemporaryDirectory() as td:
            pit, shard, args = self.make_current_generation(Path(td))
            path = shard / 'sec_filings_index_summary.json'
            summary = json.loads(path.read_text())
            summary['source_checks'][0].update(cik10='0000009999', ticker='OTHER')
            path.write_text(json.dumps(summary))
            result = merge.run(args)
            self.assertFalse(result['current_eligible'])
            self.assertIn('SOURCE_IDENTITY_SCOPE_CONFLICT', result['blockers'])
            self.assertEqual(result['signal_rows'], 0)

    def test_duplicate_source_checks_cannot_inflate_checked_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            pit, shard, args = self.make_current_generation(Path(td))
            path = shard / 'sec_filings_index_summary.json'
            summary = json.loads(path.read_text())
            summary['source_checks'] *= 2
            summary['source_coverage'].update(requested=2, checked=2)
            path.write_text(json.dumps(summary))
            result = merge.run(args)
            self.assertFalse(result['current_eligible'])
            self.assertIn('SOURCE_IDENTITY_SCOPE_CONFLICT', result['blockers'])

    def test_checked_ticker_must_match_even_when_cik_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            pit, shard, args = self.make_current_generation(Path(td))
            path = shard / 'sec_filings_index_summary.json'
            summary = json.loads(path.read_text())
            summary['source_checks'][0]['ticker'] = 'UNVERIFIED_ALIAS'
            path.write_text(json.dumps(summary))
            result = merge.run(args)
            self.assertFalse(result['current_eligible'])
            self.assertIn('SOURCE_IDENTITY_SCOPE_CONFLICT', result['blockers'])

    def test_parser_ticker_must_belong_to_the_checked_index_scope(self):
        with tempfile.TemporaryDirectory() as td:
            pit, shard, args = self.make_current_generation(Path(td))
            table = shard / 'form4_transactions.parquet'
            parsed = pd.read_parquet(table)
            parsed['issuer_ticker'] = 'OTHER'
            parsed.to_parquet(table, index=False)
            path = shard / 'form4_transactions_summary.json'
            summary = json.loads(path.read_text())
            summary['output_sha256']['parquet'] = source.file_hash(table)
            path.write_text(json.dumps(summary))
            result = merge.run(args)
            self.assertFalse(result['current_eligible'])
            self.assertIn('SOURCE_IDENTITY_SCOPE_CONFLICT', result['blockers'])

    def test_checked_ticker_cannot_resolve_to_conflicting_issuers(self):
        with tempfile.TemporaryDirectory() as td:
            pit, shard, args = self.make_current_generation(Path(td))
            path = shard / 'sec_filings_index_summary.json'
            summary = json.loads(path.read_text())
            summary['source_checks'].append({**summary['source_checks'][0], 'cik10': '0000009999'})
            summary['source_coverage'].update(requested=2, checked=2, checked_ciks=2)
            path.write_text(json.dumps(summary))
            result = merge.run(args)
            self.assertFalse(result['current_eligible'])
            self.assertIn('SOURCE_IDENTITY_SCOPE_CONFLICT', result['blockers'])

    def test_distinct_checked_aliases_share_one_issuer_without_duplicate_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            pit, shard, args = self.make_current_generation(Path(td))
            path = shard / 'sec_filings_index_summary.json'
            summary = json.loads(path.read_text())
            summary['source_checks'].append({**summary['source_checks'][0], 'ticker': 'ALIAS'})
            summary['source_coverage'].update(requested=2, checked=2, checked_ciks=1)
            path.write_text(json.dumps(summary))
            result = merge.run(args)
            self.assertTrue(result['current_eligible'])

    def test_nonfinite_source_age_cannot_disable_stale_rejection(self):
        for age in (float('nan'), float('inf'), -1, 0, True):
            with self.subTest(age=age), tempfile.TemporaryDirectory() as td:
                pit, shard, args = self.make_current_generation(Path(td))
                args.max_source_age_hours = age
                with self.assertRaisesRegex(ValueError, 'max_source_age_hours'):
                    merge.run(args)

    def test_joint_owners_do_not_invent_individual_attribution(self):
        row=event_rows()[0]
        self.assertEqual(row['owner_attribution_status'],'AMBIGUOUS')
        self.assertEqual(row['reporting_owner_cik'],'')
        self.assertIsNone(row['is_officer'])
        self.assertEqual(len(json.loads(row['reporting_owners_json'])),2)

    def test_derivatives_never_invent_cash_transaction_values(self):
        raw=xml().replace('nonDerivativeTransaction','derivativeTransaction')
        self.assertIsNone(parser.parse_form4_xml(raw,ACC,filing())[0]['transaction_value'])

    def test_form3_holdings_and_form5_late_reports_do_not_create_form4_scores(self):
        for form in ('3','5'):
            self.assertTrue(build_form4_signal(pd.DataFrame(event_rows(form)),as_of=NOW).empty)

    def test_missing_numbers_remain_null(self):
        row=parser.parse_form4_xml(xml(missing=True),ACC,filing())[0]
        self.assertIsNone(row['transaction_value'])
        self.assertIsNone(row['transaction_price'])
        self.assertEqual(parser.as_float('0'),0)
        self.assertIsNone(parser.as_float('NaN'))

    def make_current_generation(self, root):
        pit = root / 'pit'
        shard = pit / 'shards' / 'daily'
        shard.mkdir(parents=True)
        frame = pd.DataFrame([filing()])
        checks = [{'ticker': 'TEST', 'cik10': '0000000001', 'status': 'CHECKED_NEW_FILINGS', 'checked_at': NOW, 'payload_sha256': 'a' * 64}]
        source.write_outputs(frame, shard, collection_metadata={'source_checks': checks})
        parsed = pd.DataFrame(event_rows())
        parsed.attrs['parse_receipt'] = {'schema_version': 'sec-ownership-parser-receipt-v2', 'completed': {'0000000001:' + ACC + ':4': {'status': 'PARSED', 'row_count': 1}}, 'parse_error_rows': 0}
        parser.write_outputs(parsed, shard)
        args = argparse.Namespace(pit_root=str(pit), output_dir=str(root / 'out'), as_of_dates_csv='', as_of_date_column='date', window_days=90, decision_at=NOW, source_check_summary=str(shard / 'sec_filings_index_summary.json'))
        return (pit, shard, args)

    def test_parser_deleted_or_tampered_output_cannot_be_current(self):
        for deleted in [True, False]:
            with self.subTest(deleted=deleted), tempfile.TemporaryDirectory() as td:
                pit, shard, args = self.make_current_generation(Path(td))
                path = shard / 'form4_transactions.parquet'
                if deleted:
                    path.unlink()
                else:
                    frame = pd.read_parquet(path)
                    frame['transaction_value'] = 9000000
                    frame.to_parquet(path, index=False)
                result = merge.run(args)
                self.assertFalse(result['current_eligible'])
                self.assertIn('PARSER_OUTPUT_HASH_CONFLICT', result['blockers'])

    def test_parser_completed_counts_cannot_mask_missing_rows(self):
        with tempfile.TemporaryDirectory() as td:
            pit, shard, args = self.make_current_generation(Path(td))
            p = shard / 'form4_transactions_summary.json'
            receipt = json.loads(p.read_text())
            receipt['completed']['0000000001:' + ACC + ':4']['row_count'] = 2
            p.write_text(json.dumps(receipt))
            result = merge.run(args)
            self.assertIn('PARSER_RECEIPT_ROW_COUNT_CONFLICT', result['blockers'])

    def test_issuer_identity_conflict_is_not_a_successful_parse(self):
        with self.assertRaises(ValueError):
            parser.parse_form4_xml(xml(), ACC, filing(cik='0000009999'))

    def test_recent_submissions_refresh_and_immutable_xml_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'submissions').mkdir()
            (root / 'submissions' / 'CIK0000000001.json').write_text(json.dumps(payload(accepted=OLD)))
            with patch.object(source, 'sec_get_json', return_value=payload()) as network:
                self.assertEqual(source.fetch_submissions('1', root)['filings']['recent']['acceptanceDateTime'], [OLD])
                self.assertEqual(network.call_count, 0)
                self.assertEqual(source.fetch_submissions('1', root, refresh=True)['filings']['recent']['acceptanceDateTime'], [NOW])
                self.assertEqual(network.call_count, 1)
            p = root / 'filings' / 'form4' / parser.cache_name(ACC, 'ownership.xml')
            p.parent.mkdir(parents=True)
            p.write_text(xml())
            with patch.object(parser, 'sec_get_text', side_effect=AssertionError('repeat XML download')):
                parser.cache_form4_document(filing(), root)

    def test_no_new_filing_is_checked_not_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'submissions').mkdir()
            (root / 'submissions' / 'CIK0000000001.json').write_text(json.dumps(payload()))
            checks = []
            with patch.object(source, 'load_company_tickers', return_value=pd.DataFrame([dict(ticker='TEST', cik10='0000000001', name='Test')])), patch.object(source, 'sec_get_json', return_value=payload()), patch.object(source, 'utc_now', return_value=NOW):
                frame = source.collect_filings_index(tickers=['TEST'], raw_dir=root, forms=['4'], refresh_recent_submissions=True, collection_checks=checks)
            self.assertEqual(checks[0]['status'], 'CHECKED_NO_NEW_FILINGS')
            self.assertEqual(checks[0]['checked_at'], NOW)
            paths = source.write_outputs(frame, root / 'out', collection_metadata={'source_checks': checks})
            receipt = json.loads(Path(paths['summary']).read_text())
            self.assertEqual(receipt['status'], 'CHECKED')
            self.assertTrue(receipt['source_coverage']['complete'])

    def test_failed_recent_check_never_falls_back_to_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checks = []
            with patch.object(source, 'load_company_tickers', return_value=pd.DataFrame([dict(ticker='TEST', cik10='0000000001', name='Test')])), patch.object(source, 'fetch_submissions', side_effect=OSError('offline')):
                with self.assertRaises(RuntimeError):
                    source.collect_filings_index(tickers=['TEST'], raw_dir=root, forms=['4'], refresh_recent_submissions=True, collection_checks=checks)
            self.assertEqual(checks[-1]['status'], 'SOURCE_UNAVAILABLE')
            self.assertIsNone(checks[-1]['checked_at'])

    def test_corrupt_current_cache_is_not_empty_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'submissions').mkdir()
            (root / 'submissions' / 'CIK0000000001.json').write_text('{bad')
            with self.assertRaises(ValueError):
                source.fetch_submissions('1', root)

    def test_identity_mismatch_and_malformed_recent_are_rejected(self):
        bad = payload()
        bad['cik'] = 5
        with self.assertRaises(ValueError):
            source.validate_submissions(bad, '1')
        bad = payload()
        bad['filings']['recent']['form'] = []
        with self.assertRaises(ValueError):
            source.validate_submissions(bad, '1')

    def test_cap_selects_newest_per_issuer_before_old_backlog(self):
        index = pd.DataFrame([filing(accepted=OLD), filing('0000000001-26-000002'), filing('0000000004-26-000001', cik='0000000004')])
        seen = []

        def load(f, raw, **kwargs):
            seen.append(f['accession_number'])
            return (Path('unused'), xml().replace('<issuerCik>1</issuerCik>', '<issuerCik>' + str(int(f['cik10'])) + '</issuerCik>'))
        with tempfile.TemporaryDirectory() as td, patch.object(parser, 'cache_form4_document', side_effect=load):
            parsed = parser.parse_form4_index(index, raw_dir=Path(td), max_filings=2)
        self.assertEqual(set(seen), {'0000000001-26-000002', '0000000004-26-000001'})
        self.assertEqual(parsed.attrs['parse_receipt']['backlog_filings'], 1)

    def test_completed_accessions_resume_without_xml_read(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(parser, 'cache_form4_document', return_value=(None, xml())):
                first = parser.parse_form4_index(pd.DataFrame([filing()]), raw_dir=Path(td))
            completed = first.attrs['parse_receipt']['completed']
            with patch.object(parser, 'cache_form4_document', side_effect=AssertionError('reparse')):
                result = parser.parse_form4_index(pd.DataFrame([filing()]), raw_dir=Path(td), completed=completed)
        self.assertTrue(result.empty)
        self.assertEqual(result.attrs['parse_receipt']['selected_filings'], 0)

    def test_multiple_owners_notes_and_derivatives_survive(self):
        raw = xml().replace('</ownershipDocument>', '<derivativeTransaction><securityTitle><value>Option</value></securityTitle><conversionOrExercisePrice><value>7</value></conversionOrExercisePrice></derivativeTransaction></ownershipDocument>')
        rows = parser.parse_form4_xml(raw, ACC, filing())
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(json.loads(rows[0]['reporting_owners_json'])), 2)
        self.assertIn('Private transaction', rows[0]['footnotes_json'])
        self.assertEqual(rows[1]['conversion_or_exercise_price'], 7)
        self.assertTrue(rows[1]['is_derivative'])
        self.assertIsNone(rows[1]['transaction_value'])

    def test_form3_initial_holdings_and_form5_late_transactions(self):
        raw = xml('3').replace('nonDerivativeTransaction', 'nonDerivativeHolding')
        row = parser.parse_form4_xml(raw, ACC, filing(form='3'))[0]
        self.assertEqual(row['row_kind'], 'HOLDING')
        row = event_rows('5')[0]
        self.assertEqual(row['form_type'], '5')

    def test_merger_requires_source_check_and_refreshes_both_formats(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pit = root / 'pit'
            pit.mkdir()
            pd.DataFrame(event_rows()).to_parquet(pit / 'form4_transactions.parquet', index=False)
            pd.DataFrame([filing()]).to_parquet(pit / 'sec_filings_index.parquet', index=False)
            args = argparse.Namespace(pit_root=str(pit), output_dir=str(root / 'out'), as_of_dates_csv='', as_of_date_column='date', window_days=90, decision_at=NOW)
            result = merge.run(args)
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(result['signal_rows'], 0)
            self.assertEqual(len(pd.read_csv(pit / 'form4_transactions.csv')), len(pd.read_parquet(pit / 'form4_transactions.parquet')))
            self.assertEqual(json.loads((pit / 'form4_transactions_summary.json').read_text())['generation_id'], result['generation_id'])

    def test_merged_write_failure_revokes_old_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pit = root / 'pit'
            pit.mkdir()
            manifest = pit / 'sec_form4_merge_manifest.json'
            manifest.write_text('{"status":"completed","current_eligible":true}')
            args = argparse.Namespace(pit_root=str(pit), output_dir=str(root / 'out'), as_of_dates_csv='', as_of_date_column='date', window_days=90, decision_at=NOW)
            with patch.object(merge, 'write_table', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    merge.run(args)
            self.assertEqual(json.loads(manifest.read_text())['status'], 'BUILDING')

if __name__=="__main__":unittest.main()
