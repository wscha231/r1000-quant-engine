"""Source-only 13F scoped restore and accession checkpoint regressions."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools import run_sec_13f_parser as f13
NOW = '2026-10-20T13:59:06+00:00'
OLD = '2026-05-19T10:03:54+00:00'
ACC = '0000000001-26-000001'

def filing(accession=ACC, cik='0000000001', accepted=NOW, form='4'):
    return dict(ticker='TEST', cik10=cik, accession_number=accession, form_type=form, primary_document='ownership.xml', accepted_at=accepted, available_from=accepted, filing_date=accepted[:10])

class SECSourceRegression(unittest.TestCase):

    def test_explicit_required_restore_precedes_combined_analysis(self):
        workflow=(ROOT/'.github/workflows/sec_13f_quarterly_refresh.yml').read_text()
        restore=workflow.split('- name: Restore required Form4 and ETF evidence for weighted analysis',1)[1].split('- name:',1)[0]
        for name in ('outputs/sec_ownership_signals/form4_latest.csv',
                     'data_pit/sec/sec_form4_merge_manifest.json',
                     'outputs/etf_thematic_signals/signals_latest.csv',
                     'data_pit/etf_holdings/etf_holdings.parquet'):
            self.assertIn(name,restore)
        self.assertIn('timeout 3m rclone copyto "$BASE$f" "$f"',restore)
        self.assertIn('test -s "$f"',restore)
        self.assertNotIn('|| true',restore)
        self.assertLess(workflow.index('Persist collected 13F source independently'),
                        workflow.index('Restore required Form4 and ETF evidence'))
        self.assertLess(workflow.index('Restore required Form4 and ETF evidence'),
                        workflow.index('Validate and score combined 13F Form4 ETF analysis'))

    def checkpoint_fixture(self):
        raw='<informationTable><infoTable><nameOfIssuer>Test</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>123456789</cusip><value>100</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable></informationTable>'
        return raw,pd.DataFrame([{**filing(form='13F-HR'),'period_of_report':'2026-06-30'}])

    def test_original_type_matches_normalized_rows_and_receipt(self):
        raw, index = self.checkpoint_fixture()
        with tempfile.TemporaryDirectory() as td, patch.object(f13, 'cache_13f_document', return_value=(Path('unused'), raw)), \
                patch.object(f13, 'sec_get_text', side_effect=AssertionError('original needs no amendment cover')):
            rows = f13.parse_13f_index(index, raw_dir=Path(td))
        self.assertEqual(rows.iloc[0]['amendment_type'], 'ORIGINAL')
        self.assertEqual(rows.attrs['filing_receipts'][0]['amendment_type'], 'ORIGINAL')

    def test_amendment_types_survive_and_missing_type_refuses(self):
        raw, index = self.checkpoint_fixture()
        index['form_type'] = '13F-HR/A'
        for kind in ('RESTATEMENT', 'NEW HOLDINGS', ''):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td, \
                    patch.object(f13, 'cache_13f_document', return_value=(Path('unused'), raw)), \
                    patch.object(f13, 'sec_get_text', return_value=f'<amendmentType>{kind}</amendmentType>'):
                rows = f13.parse_13f_index(index, raw_dir=Path(td))
            receipt = rows.attrs['filing_receipts'][0]
            if kind:
                self.assertEqual(receipt['status'], 'PARSED')
                self.assertEqual(receipt['amendment_type'], kind)
                self.assertEqual(rows.iloc[0]['amendment_type'], kind)
            else:
                self.assertEqual(receipt['status'], 'PARSE_FAILED')
                self.assertIsNone(receipt['row_count'])

    def test_unchanged_checkpoint_reuses_rows_without_reparsing(self):
        raw,index=self.checkpoint_fixture()
        with tempfile.TemporaryDirectory() as td,patch.object(f13,'cache_13f_document',return_value=(Path('unused'),raw)),patch.object(f13,'cache_13f_amendment_type',return_value='ORIGINAL'):
            f13.parse_13f_index(index,raw_dir=Path(td))
            with patch.object(f13,'parse_13f_xml',side_effect=AssertionError('must reuse verified rows')):
                rows=f13.parse_13f_index(index,raw_dir=Path(td))
            self.assertEqual(rows.attrs['filing_receipts'][0]['status'],'PARSED')
            self.assertEqual(len(rows),1)

    def test_mapping_change_invalidates_checkpoint(self):
        raw,index=self.checkpoint_fixture()
        with tempfile.TemporaryDirectory() as td,patch.object(f13,'cache_13f_document',return_value=(Path('unused'),raw)),patch.object(f13,'cache_13f_amendment_type',return_value='ORIGINAL'):
            f13.parse_13f_index(index,raw_dir=Path(td),cusip_map={'123456789':'ONE'})
            rows=f13.parse_13f_index(index,raw_dir=Path(td),cusip_map={'123456789':'TWO'})
            self.assertEqual(rows.iloc[0]['ticker_mapped'],'TWO')

    def test_parser_code_change_invalidates_checkpoint(self):
        raw,index=self.checkpoint_fixture()
        native=f13.parse_13f_xml
        with tempfile.TemporaryDirectory() as td,patch.object(f13,'cache_13f_document',return_value=(Path('unused'),raw)),patch.object(f13,'cache_13f_amendment_type',return_value='ORIGINAL'):
            with patch.object(f13,'file_hash',return_value='a'*64):f13.parse_13f_index(index,raw_dir=Path(td))
            with patch.object(f13,'file_hash',return_value='b'*64),patch.object(f13,'parse_13f_xml',wraps=native) as parse:
                f13.parse_13f_index(index,raw_dir=Path(td))
                self.assertEqual(parse.call_count,1)

    def test_tampered_checkpoint_is_not_a_zero_position(self):
        raw,index=self.checkpoint_fixture()
        with tempfile.TemporaryDirectory() as td,patch.object(f13,'cache_13f_document',return_value=(Path('unused'),raw)),patch.object(f13,'cache_13f_amendment_type',return_value='ORIGINAL'):
            root=Path(td);f13.parse_13f_index(index,raw_dir=root)
            path=next((root/'parsed'/'13f').glob('*.json'))
            value=json.loads(path.read_text());value['rows'][0]['shares']=999;path.write_text(json.dumps(value))
            rows=f13.parse_13f_index(index,raw_dir=root)
            self.assertEqual(rows.attrs['filing_receipts'][0]['status'],'PARSE_FAILED')
            self.assertIsNone(rows.attrs['filing_receipts'][0]['row_count'])

    def test_scoped_workflow_keeps_combined_analysis_gates(self):
        workflow=(ROOT/'.github/workflows/sec_13f_quarterly_refresh.yml').read_text()
        self.assertNotIn('restore_required_dir data_raw/sec',workflow)
        self.assertIn('--files-from outputs/sec_institutional_signals/restore_xml_files.txt',workflow)
        self.assertLess(workflow.index('Persist collected 13F source independently'),workflow.index('Restore required Form4 and ETF evidence'))
        for token in ('--require-parsed-holdings','--require-current-form4-receipt','--require-weighted-evidence','--minimum-manager-coverage 0.80','--minimum-mapped-row-coverage 0.20','--minimum-mapped-value-coverage 0.50'):
            self.assertIn(token,workflow)

    def test_13f_resumes_parsing_after_interrupted_filing(self):
        raw = '<informationTable><infoTable><nameOfIssuer>Test</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>123456789</cusip><value>100</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable></informationTable>'
        entries = pd.DataFrame([{**filing(form='13F-HR'), 'period_of_report': '2026-06-30'}, {**filing('0000000001-26-000002', form='13F-HR'), 'period_of_report': '2026-06-30'}])
        native = f13.parse_13f_xml
        calls = []

        def interrupted(text, f, **kwargs):
            calls.append(f['accession_number'])
            if len(calls) == 2:
                raise KeyboardInterrupt('interrupted after one accession')
            return native(text, f, **kwargs)
        with tempfile.TemporaryDirectory() as td, patch.object(f13, 'cache_13f_document', return_value=(Path('unused'), raw)), patch.object(f13, 'cache_13f_amendment_type', return_value='ORIGINAL'):
            with patch.object(f13, 'parse_13f_xml', side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
                f13.parse_13f_index(entries, raw_dir=Path(td))
            with patch.object(f13, 'parse_13f_xml', wraps=native) as resumed:
                result = f13.parse_13f_index(entries, raw_dir=Path(td))
                self.assertEqual(resumed.call_count, 1)
            self.assertEqual(len(result), 2)

    def test_13f_restore_is_accession_scoped_and_future_safe(self):
        frame = pd.DataFrame([{**filing(form='13F-HR'), 'primary_document': 'primary_doc.xml'}, {**filing('0000000001-26-000002', form='13F-HR/A'), 'primary_document': 'primary_doc.xml'}, {**filing('0000000001-26-000003', accepted='2099-01-01T00:00:00Z', form='13F-HR'), 'primary_document': 'primary_doc.xml'}])
        paths = f13.selected_restore_paths(frame, as_of=NOW, max_filings=10)
        self.assertEqual(len(paths), 5)
        self.assertTrue(all((p.startswith(('filings/13f/', 'filings/13f_cover/', 'parsed/13f/')) for p in paths)))
        self.assertFalse(any(('000003' in p for p in paths)))

if __name__=="__main__":unittest.main()
