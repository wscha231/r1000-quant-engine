"""Parser -> H1 adapter -> batch -> writer tests; no API calls or alpha tests.

Run in the repository with its real submissions collector. The delivery-only
harness can supply a clearly labelled transport import shim when no authorized
worktree is mounted. Never copy that shim into tools/ in the repository.
"""
from __future__ import annotations
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
from tools import run_sec_13f_parser as p

ROW = '''<infoTable><nameOfIssuer>SYNTHETIC</nameOfIssuer>
<titleOfClass>COM</titleOfClass><cusip>023135106</cusip><value>20000</value>
<shrsOrPrnAmt><sshPrnamt>100</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
<investmentDiscretion>SOLE</investmentDiscretion></infoTable>'''
RAW = '<informationTable>'+ROW+'</informationTable>'
META = {'cik10':'0001536411','manager_name':'SYNTHETIC_MANAGER',
        'period_of_report':'2026-06-30','filing_date':'2026-08-14',
        'accepted_at':'2026-08-14T20:00:00Z','available_from':'2026-08-14T20:01:00Z',
        'accession_number':'0001536411-26-000006','form_type':'13F-HR',
        'primary_document':'info.xml'}

class NumericTests(unittest.TestCase):
    def test_zero_is_valid(self): self.assertEqual(p.as_float(0), 0)
    def test_decimal_is_valid(self): self.assertEqual(p.as_float('123.45'),123.45)
    def test_grouped_primitive_is_valid(self): self.assertEqual(p.as_float('1,234.50'),1234.5)
    def test_optional_absence_is_null(self): self.assertIsNone(p.optional_float(''))
    def test_optional_zero_not_absence(self): self.assertEqual(p.optional_float('0'),0)

# Distinct boundary values are distinct test IDs, not repeated runs counted twice.
for name, value in [('none',None),('empty',''),('boolean',False),('word','bad'),
                    ('nan',float('nan')),('infinity',float('inf')),('negative',-1),
                    ('bad_grouping','12,34'),('overflow','9'*400),
                    ('precision_loss','9007199254740993'),('underflow','0.'+'0'*400+'1')]:
    def check(self, value=value):
        with self.assertRaises(ValueError): p.as_float(value)
    setattr(NumericTests,'test_required_rejects_'+name,check)

class ParserTests(unittest.TestCase):
    def test_actual_parser_calls_existing_h1_adapter(self):
        with mock.patch.object(p,'adapt_legacy_parser_rows',wraps=p.adapt_legacy_parser_rows) as adapter:
            rows=p.parse_13f_xml(RAW,META)
        self.assertEqual(adapter.call_count,1)
        self.assertEqual(rows[0]['shares'],100)
        self.assertEqual(rows[0]['raw_reported_shares'],'100')
        self.assertEqual(rows[0]['raw_xml_sha256'],hashlib.sha256(RAW.encode()).hexdigest())
        self.assertEqual(rows[0]['value_unit_status'],'UNVERIFIED_LEGACY_DATE_RULE')
    def test_required_quantity_cannot_be_coerced_to_zero(self):
        with self.assertRaises(ValueError): p.parse_13f_xml(RAW.replace('>100<','>bad<'),META)
    def test_empty_required_value_blocked(self):
        with self.assertRaises(ValueError): p.parse_13f_xml(RAW.replace('>20000<','><'),META)
    def test_optional_votes_remain_null(self):
        row=p.parse_13f_xml(RAW,META)[0]
        self.assertIsNone(row['voting_authority_sole'])
    def test_explicit_vote_zero_preserved(self):
        raw=RAW.replace('</infoTable>','<votingAuthority><Sole>0</Sole></votingAuthority></infoTable>')
        self.assertEqual(p.parse_13f_xml(raw,META)[0]['voting_authority_sole'],0)
    def test_malformed_optional_vote_blocked(self):
        raw=RAW.replace('</infoTable>','<votingAuthority><Sole>oops</Sole></votingAuthority></infoTable>')
        with self.assertRaises(ValueError): p.parse_13f_xml(raw,META)
    def test_cash_call_put_and_classes_preserved(self):
        raw='<informationTable>'+ROW+ROW.replace('</infoTable>','<putCall>CALL</putCall></infoTable>')+ROW.replace('</infoTable>','<putCall>PUT</putCall></infoTable>')+ROW.replace('>COM<','>CLASS B<')+'</informationTable>'
        rows=p.parse_13f_xml(raw,META)
        self.assertEqual(len(rows),4)
        self.assertEqual([r['source_row_id'] for r in rows],['1','2','3','4'])
        self.assertEqual({r['put_call'] for r in rows},{'','CALL','PUT'})
    def test_joint_reporting_contexts_preserved(self):
        rows=p.parse_13f_xml(RAW.replace('</infoTable>','<otherManager>1</otherManager><otherManager>2</otherManager></infoTable>'),META)
        self.assertEqual(rows[0]['other_manager'],'1,2')
    def test_no_corporate_action_factor_invented(self):
        self.assertEqual(p.parse_13f_xml(RAW,META)[0]['shares'],100)
    def test_no_unknown_asset_promoted_to_equity(self):
        self.assertEqual(p.parse_13f_xml(RAW,META)[0]['asset_type'],'UNKNOWN')
    def test_entity_declaration_blocked_before_et(self):
        with self.assertRaises(ValueError): p.parse_13f_xml('<!DOCTYPE x [<!ENTITY x "bad">]>'+RAW,META)
    def test_wrong_root_cannot_be_successfully_empty(self):
        with self.assertRaises(ValueError): p.parse_13f_xml('<html/>',META)
    def test_duplicate_required_xml_field_rejected_by_adapter(self):
        raw=RAW.replace('<value>20000</value>','<value>20000</value><value>3</value>')
        with self.assertRaises(ValueError): p.parse_13f_xml(raw,META)
    def test_legacy_date_unit_is_not_certified(self):
        row=p.parse_13f_xml(RAW,{**META,'filing_date':'2022-12-31'})[0]
        self.assertEqual(row['market_value_usd'],20000000)
        self.assertIn('UNVERIFIED',row['value_unit_status'])
    def test_identical_parse_is_deterministic(self):
        self.assertEqual(p.parse_13f_xml(RAW,META),p.parse_13f_xml(RAW,META))
    def test_changed_xml_changes_evidence(self):
        self.assertNotEqual(p.parse_13f_xml(RAW,META)[0]['parse_evidence_id'],
                            p.parse_13f_xml(RAW.replace('>100<','>120<'),META)[0]['parse_evidence_id'])

class BatchTests(unittest.TestCase):
    def test_valid_cache_passes_actual_cache_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); d=root/'filings/13f'; d.mkdir(parents=True)
            (d/p.cache_name(META['accession_number'],'info.xml')).write_text(RAW)
            with mock.patch.object(p.requests,'get',side_effect=AssertionError('no network')):
                frame=p.parse_13f_index(pd.DataFrame([META]),raw_dir=root)
            self.assertEqual(len(frame),1)
            self.assertEqual(frame.iloc[0]['raw_reported_shares'],'100')
    def test_corrupt_filing_blocks_whole_snapshot(self):
        good=META; bad={**META,'accession_number':'0001536411-26-000007'}
        def cached(meta,*args,**kwargs):
            return None,RAW if meta['accession_number']==good['accession_number'] else RAW.replace('>100<','>oops<')
        with mock.patch.object(p,'cache_13f_document',side_effect=cached):
            with self.assertRaises(p.FilingBatchError) as ctx:
                p.parse_13f_index(pd.DataFrame([bad,good]),raw_dir=Path('.'))
        self.assertEqual(len(ctx.exception.errors),1)
        self.assertEqual(ctx.exception.errors[0]['source_accession'],bad['accession_number'])
    def test_fetch_failure_not_encoded_in_holdings(self):
        with mock.patch.object(p,'cache_13f_document',side_effect=RuntimeError('secret-do-not-echo')):
            with self.assertRaises(p.FilingBatchError) as ctx:
                p.parse_13f_index(pd.DataFrame([META]),raw_dir=Path('.'))
        self.assertNotIn('secret',json.dumps(ctx.exception.errors))
    def test_future_filing_not_fetched(self):
        with mock.patch.object(p,'cache_13f_document') as cache:
            frame=p.parse_13f_index(pd.DataFrame([META]),raw_dir=Path('.'),as_of='2026-08-14T20:00:59Z')
        self.assertTrue(frame.empty);cache.assert_not_called()
    def test_cutoff_exact_availability_allowed(self):
        with mock.patch.object(p,'cache_13f_document',return_value=(None,RAW)):
            frame=p.parse_13f_index(pd.DataFrame([META]),raw_dir=Path('.'),as_of=META['available_from'])
        self.assertEqual(len(frame),1)
    def test_cli_blocks_without_calling_writer(self):
        with mock.patch.object(p,'read_filings_index',return_value=pd.DataFrame([META])), \
             mock.patch.object(p,'cache_13f_document',side_effect=ValueError('bad')), \
             mock.patch.object(p,'write_outputs') as writer, \
             mock.patch('sys.argv',['parser']),contextlib.redirect_stdout(io.StringIO()) as out:
            code=p.main()
        self.assertEqual(code,2);writer.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())['status'],'BLOCKED_PARTIAL_PARSE')
    def test_empty_cli_does_not_publish(self):
        with mock.patch.object(p,'read_filings_index',return_value=pd.DataFrame()), \
             mock.patch.object(p,'write_outputs') as writer, \
             mock.patch('sys.argv',['parser']),contextlib.redirect_stdout(io.StringIO()) as out:
            code=p.main()
        self.assertEqual(code,2);writer.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())['status'],'BLOCKED_EMPTY_PARSE')
    def test_bounded_batch_prefers_latest_with_valid_fixture(self):
        old={**META,'accession_number':'0001536411-25-000001','accepted_at':'2025-08-14T20:00:00Z'}
        with mock.patch.object(p,'cache_13f_document',return_value=(None,RAW)) as cache:
            frame=p.parse_13f_index(pd.DataFrame([old,META]),raw_dir=Path('.'),max_filings=1)
        self.assertEqual(cache.call_count,1)
        self.assertEqual(frame.iloc[0]['source_accession'],META['accession_number'])

class WriterTests(unittest.TestCase):
    def frame(self): return pd.DataFrame(p.parse_13f_xml(RAW,META))
    def test_roundtrip_preserves_null_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=p.write_outputs(self.frame(),Path(tmp))
            got=pd.read_parquet(paths['parquet'])
            self.assertTrue(pd.isna(got.iloc[0]['voting_authority_sole']))
            self.assertEqual(got.iloc[0]['raw_reported_shares'],'100')
            summary=json.loads(Path(paths['summary']).read_text())
            self.assertFalse(summary['unit_scope_pit_and_corporate_actions_accepted'])
    def test_missing_required_value_rejected_before_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'new'; f=self.frame();f.loc[0,'shares']=None
            with self.assertRaises(ValueError): p.write_outputs(f,out)
            self.assertFalse(out.exists())
    def test_invalid_required_text_cannot_be_zero(self):
        f=self.frame().astype({'shares':object});f.loc[0,'shares']='oops'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): p.write_outputs(f,Path(tmp))
    def test_legacy_error_does_not_overwrite_prior_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);paths=p.write_outputs(self.frame(),root)
            before={k:Path(v).read_bytes() for k,v in paths.items()}
            f=self.frame();f.loc[0,'issuer_name']='PARSE_ERROR: bad'
            with self.assertRaises(ValueError): p.write_outputs(f,root)
            self.assertEqual(before,{k:Path(v).read_bytes() for k,v in paths.items()})
    def test_required_column_not_fabricated(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): p.write_outputs(self.frame().drop(columns=['shares']),Path(tmp))
    def test_empty_writer_does_not_delete_previous_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'new'
            with self.assertRaises(ValueError): p.write_outputs(pd.DataFrame(),out)
            self.assertFalse(out.exists())
    def test_optional_nan_stays_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=self.frame();f['voting_authority_sole']=float('nan')
            paths=p.write_outputs(f,Path(tmp))
            self.assertTrue(pd.isna(pd.read_parquet(paths['parquet']).iloc[0]['voting_authority_sole']))

if __name__=='__main__': unittest.main()
