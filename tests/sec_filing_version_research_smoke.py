"""Synthetic refusal tests for the opt-in SEC date-version Reader method."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.research_data_access import ResearchDataReader, ContractError
from tools.sec_filing_version_research import SECDateVersionResearchScope, TAGS

CIK = '0000000001'
ACC = '0000000001-21-000001'
CUT = '2021-09-30T00:00:00Z'
CONSUMER = 'CONTRACT_FIXTURE:sec_date_version'
REVIEW = 'independent-a1-sec-reported-version-date-review-v2'


def raw(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()


def digest(b):
    return hashlib.sha256(b).hexdigest()


def fixture():
    member = ('''<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"
xmlns:x="http://www.xbrl.org/2003/instance"
xmlns:xbrli="http://www.xbrl.org/2003/instance"
xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
xmlns:us-gaap="http://fasb.org/us-gaap/2021-01-31"><head/><body>
<x:context id="c"><x:entity><x:identifier scheme="http://www.sec.gov/CIK">0000000001</x:identifier></x:entity><x:period><x:startDate>2021-04-01</x:startDate><x:endDate>2021-06-30</x:endDate></x:period></x:context>
<x:unit id="USD"><x:measure>iso4217:USD</x:measure></x:unit>
<x:unit id="EPS"><x:divide><x:unitNumerator><x:measure>iso4217:USD</x:measure></x:unitNumerator><x:unitDenominator><x:measure>xbrli:shares</x:measure></x:unitDenominator></x:divide></x:unit>
<ix:nonFraction name="us-gaap:EarningsPerShareDiluted" contextRef="c" unitRef="EPS" sign="-">0.2</ix:nonFraction>
<ix:nonFraction name="us-gaap:OperatingIncomeLoss" contextRef="c" unitRef="USD">20</ix:nonFraction>
<ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" contextRef="c" unitRef="USD">100</ix:nonFraction>
</body></html>
''').encode()
    primary = member.replace(b'</body>', b'<script type="text/javascript" src="/script"></script></body>')
    header = ('''<SEC-DOCUMENT>0000000001-21-000001.txt : 20210805
<SEC-HEADER>0000000001-21-000001.hdr.sgml : 20210805
<ACCEPTANCE-DATETIME>20210805160919
ACCESSION NUMBER: 0000000001-21-000001
CONFORMED SUBMISSION TYPE: 10-Q
CONFORMED PERIOD OF REPORT: 20210630
FILED AS OF DATE: 20210805
DATE AS OF CHANGE: 20210805
CENTRAL INDEX KEY: 0000000001
</SEC-HEADER>
<DOCUMENT>
<TYPE>10-Q
<SEQUENCE>1
<FILENAME>fixture.htm
<TEXT>
<XBRL>
''').encode()
    submission = header + member + b'</XBRL>\n</TEXT>\n</DOCUMENT>\n'
    idxline = ['1', 'SYNTHETIC ISSUER', '10-Q', '20210805',
               'edgar/data/1/' + ACC + '.txt']
    index = ('Daily Index of EDGAR Dissemination Feed\n' + '|'.join(idxline) + '\n').encode()
    return dict(member=member, primary=primary, submission=submission, index=index,
                idxline=idxline, changed='20210805', cutoff=CUT,
                rows=[dict(ticker='FIXTURE', cik=CIK, accession=ACC, tag=t,
                           unit='USD/shares' if i == 0 else 'USD',
                           start='2021-04-01', end='2021-06-30', duration='QUARTER',
                           value=('-0.2', '20', '100')[i], context_refs=['c'],
                           status='ORIGINAL_AND_ARCHIVED_FACT_MATCH')
                      for i, t in enumerate(TAGS)])


def seal(f):
    rows = copy.deepcopy(f['rows'])
    for row in rows:
        row.update(document_sha256=digest(f['primary']), index_sha256=digest(f['index']))
    facts = raw({'rows': rows})
    ev = raw(dict(scope='CURRENT_EDGAR_REPRESENTATIONS_CROSSCHECKED_WITH_HISTORICAL_FILING_HEADERS',
                  official_reader_training_admission=False,
                  rows=[dict(accession=ACC, issuer='FIXTURE',
                    source_url=f.get('source_url','https://www.sec.gov/Archives/edgar/data/1/000000000121000001/'+ACC+'.txt'),
                    standalone_sha256=digest(f['primary']),
                    submission_prefix_sha256=digest(f['submission']),
                    inner_primary_sha256=digest(f['member']),
                    last_reported_change_date=f['changed'],
                    linked_decisions_after_change=[f['cutoff'][:10]])]))
    dis = raw(dict(records=[dict(accession=ACC, ticker='FIXTURE',
                    index_line=f['idxline'], index_sha256=digest(f['index']),
                    index_url='https://www.sec.gov/Archives/edgar/daily-index/2021/QTR3/master.20210805.idx',
                    doc_url='https://www.sec.gov/Archives/edgar/data/1/000000000121000001/fixture.htm',
                    acceptance='2021-08-05T20:09:19Z',
                    conservative_evidence_clock='2021-08-06T02:08:54Z')]))
    review = raw(dict(schema=REVIEW,
                     input_refs=[{'sha256': digest(x)} for x in (ev, facts, dis)],
                     exact_decision_links=[dict(accession=ACC, issuer='FIXTURE',
                        decision_date=f['cutoff'][:10],
                        source_rows=['/rows/0', '/rows/1', '/rows/2'])]))
    scope = SECDateVersionResearchScope(digest(ev), digest(facts), digest(dis),
             digest(review), ((CIK, ACC, f['cutoff']),), CONSUMER)
    return dict(evidence_bytes=ev, facts_bytes=facts, dissemination_bytes=dis,
                review_bytes=review, trusted_scope=scope,
                proof_objects=tuple((digest(b), b) for b in
                                    (f['primary'], f['submission'], f['index'])),
                issuer_cik=CIK, accession=ACC, decision_time=f['cutoff'],
                purpose='research', consumer_id=CONSUMER)


class SECDateVersionTests(unittest.TestCase):
    def setUp(self):
        class NoTransport:
            def read(self, *args):
                raise AssertionError('No provider, lake or latest read')
        from tools.research_data_access import PRICE_REGISTRY_ENTRY
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        registry = Path(self.temp.name) / 'registry.json'
        registry.write_bytes(raw(dict(schema='research-dataset-registry-v1',
            eligible_for_selector=False, datasets={'ds.us.prices.daily': PRICE_REGISTRY_ENTRY})))
        self.reader = ResearchDataReader(NoTransport(), registry_path=registry)

    def call(self, f=None, **changes):
        args = seal(f or fixture()); args.update(changes)
        return self.reader.read_sec_filing_version(**args)

    def refuse(self, f=None, **changes):
        with self.assertRaises(ContractError):
            self.call(f, **changes)

    def test_public_reader_returns_exact_immutable_research_rows_without_admission(self):
        r = self.call()
        self.assertEqual([v['value'] for v in r.rows], ['-0.2', '20', '100'])
        self.assertEqual(r.receipt['status'], 'VERIFIED_SEC_REPORTED_VERSION_DATE_RESEARCH')
        for k in ('historical_pit', 'training_admitted', 'source_admitted',
                  'eligible_for_er', 'eligible_for_a5', 'qualified_market_join',
                  'eligible_for_selector', 'eligible_for_economics', 'legacy_generation_relabelled'):
            self.assertIs(r.receipt[k], False)
        self.assertIsNone(r.receipt['data_generation_id'])
        with self.assertRaises(TypeError):
            r.rows[0]['value'] = '0'

    def test_each_unpinned_metadata_change_refuses(self):
        args = seal(fixture())
        for key in ('evidence_bytes','facts_bytes','dissemination_bytes','review_bytes'):
            with self.subTest(key=key):
                changes = {key: args[key] + b' '}
                self.refuse(**changes)

    def test_external_scope_is_typed_and_has_no_manifest_factory(self):
        self.refuse(trusted_scope={})
        a = seal(fixture())
        self.refuse(trusted_scope=replace(a['trusted_scope'], review_sha256='0'*64))

    def test_training_backtest_and_foreign_consumer_refuse(self):
        for purpose in ('training','backtest','portfolio'):
            self.refuse(purpose=purpose)
        self.refuse(consumer_id='foreign')

    def test_cross_issuer_and_accession_substitution_refuse(self):
        self.refuse(issuer_cik='0000000002')
        self.refuse(accession='0000000001-21-000002')
        f=fixture(); f['rows'][0]['cik']='0000000002'; self.refuse(f)

    def test_repinning_false_row_value_does_not_override_original_fact(self):
        f=fixture(); f['rows'][0]['value']='999'; self.refuse(f)

    def test_repinning_wrong_unit_or_quarter_end_refuses(self):
        f=fixture(); f['rows'][1]['unit']='USD/shares'; self.refuse(f)
        f=fixture(); f['rows'][1]['end']='2021-09-30'; self.refuse(f)

    def test_instant_and_nonconsolidated_context_substitution_refuse(self):
        f=fixture(); f['rows'][0]['context_refs']=['instant']; self.refuse(f)
        f=fixture(); f['rows'][0]['start']='2021-01-01'; self.refuse(f)

    def test_utc_required_and_undeclared_cutoff_refuses(self):
        for value in ('2021-09-30','2021-09-30T00:00:00+09:00',
                      '2021-10-01T00:00:00Z'):
            self.refuse(decision_time=value)

    def test_same_day_and_before_dissemination_refuse_even_if_scope_resealed(self):
        for value in ('2021-08-05T23:59:59Z','2021-08-06T00:00:00Z'):
            f=fixture(); f['cutoff']=value; self.refuse(f)

    def test_changed_date_forgery_and_change_after_cutoff_refuse(self):
        f=fixture(); f['changed']='20210804'; self.refuse(f)
        f=fixture(); f['changed']='20211001'
        f['submission']=f['submission'].replace(b'DATE AS OF CHANGE: 20210805',b'DATE AS OF CHANGE: 20211001')
        self.refuse(f)

    def test_index_wrong_issuer_missing_or_duplicate_line_refuses(self):
        f=fixture(); f['idxline'][0]='2'; self.refuse(f)
        f=fixture(); f['index']=b'Daily Index of EDGAR Dissemination Feed\n'; self.refuse(f)
        f=fixture(); f['index']+=('|'.join(f['idxline'])+'\n').encode(); self.refuse(f)

    def test_tampered_original_and_extra_proof_refuse(self):
        a=seal(fixture())
        proofs=a['proof_objects']
        self.refuse(proof_objects=((proofs[0][0],proofs[0][1]+b' '),)+proofs[1:])
        self.refuse(proof_objects=proofs+((digest(b'extra'),b'extra'),))

    def test_nonempty_script_or_internal_fact_difference_refuses(self):
        f=fixture(); f['primary']=f['primary'].replace(b'</script>',b'alert(1)</script>'); self.refuse(f)
        f=fixture(); f['primary']=f['primary'].replace(b'>100<',b'>101<'); self.refuse(f)

    def test_signed_value_and_scale_cannot_be_invented(self):
        f=fixture(); f['rows'][0]['value']='0.2'; self.refuse(f)
        f=fixture(); f['rows'][1]['value']='20000000'; self.refuse(f)

    def test_duplicate_or_missing_fact_refuses(self):
        f=fixture(); f['rows'][2]=copy.deepcopy(f['rows'][1]); self.refuse(f)
        f=fixture(); f['rows'].pop(); self.refuse(f)

    def test_foreign_source_url_refuses_even_with_resealed_metadata(self):
        f=fixture(); f['source_url']='https://example.invalid/filing.txt'; self.refuse(f)


    def edit_member(self, f, old, new):
        member=f['member'].replace(old,new)
        self.assertNotEqual(member,f['member'])
        f['submission']=f['submission'].replace(f['member'],member)
        f['member']=member
        f['primary']=member.replace(b'</body>',b'<script type="text/javascript" src="/script"></script></body>')
        return f

    def test_excluded_numeric_text_and_nested_markup_are_unsupported(self):
        self.refuse(self.edit_member(fixture(),b'>100</ix:nonFraction>',
            b'>1<ix:exclude>0</ix:exclude>0</ix:nonFraction>'))

    def test_continued_numeric_fact_is_unsupported(self):
        self.refuse(self.edit_member(fixture(),b'unitRef="USD">100',
            b'unitRef="USD" continuedAt="continuation">100'))

    def test_scoped_concept_prefix_redefinition_refuses(self):
        self.refuse(self.edit_member(fixture(),b'name="us-gaap:OperatingIncomeLoss"',
            b'xmlns:us-gaap="https://example.invalid/not-gaap" name="us-gaap:OperatingIncomeLoss"'))

    def test_scoped_currency_prefix_redefinition_refuses(self):
        self.refuse(self.edit_member(fixture(),b'<x:measure>iso4217:USD',
            b'<x:measure xmlns:iso4217="https://example.invalid/not-currency">iso4217:USD'))

    def test_scoped_share_prefix_redefinition_refuses(self):
        self.refuse(self.edit_member(fixture(),b'<x:measure>xbrli:shares',
            b'<x:measure xmlns:xbrli="https://example.invalid/not-shares">xbrli:shares'))

    def test_unknown_transformation_namespace_refuses(self):
        self.refuse(self.edit_member(fixture(),b'unitRef="USD">100',
            b'unitRef="USD" xmlns:bad="https://example.invalid/not-transform" format="bad:num-dot-decimal">100'))


    def test_requested_context_list_with_missing_context_refuses(self):
        f=fixture(); f['rows'][1]['context_refs']=['c','missing']; self.refuse(f)

    def test_requested_context_list_with_duplicate_context_refuses(self):
        f=fixture(); f['rows'][1]['context_refs']=['c','c']; self.refuse(f)

    def long_scaled_fixture(self, requested, scale='6', sign=''):
        f=fixture()
        replacement=(b'unitRef="USD" scale="'+scale.encode()+b'"'+
                     (b' sign="-"' if sign else b'')+
                     b'>12345678901234567890123456789</ix:nonFraction>')
        f=self.edit_member(f,b'unitRef="USD">20</ix:nonFraction>',replacement)
        f['rows'][1]['value']=requested
        return f

    def test_rounded_29_digit_amount_is_not_the_original_fact(self):
        self.refuse(self.long_scaled_fixture('1.234567890123456789012345679E+34'))

    def test_exact_29_digit_amount_preserves_every_digit(self):
        value='12345678901234567890123456789'+'000000'
        result=self.call(self.long_scaled_fixture(value))
        self.assertEqual(result.rows[1]['value'],value)

    def test_exact_scale_is_independent_of_decimal_precision(self):
        from decimal import localcontext
        value='12345678901234567890123456789'+'000000'
        with localcontext() as context:
            context.prec=7
            result=self.call(self.long_scaled_fixture(value))
        self.assertEqual(result.rows[1]['value'],value)

    def test_exact_negative_fractional_scale_does_not_round(self):
        value='-12345678901234567890.123456789'
        result=self.call(self.long_scaled_fixture(value,scale='-9',sign='-'))
        self.assertEqual(result.rows[1]['value'],value)

    def test_resource_and_duplicate_proof_refuse(self):
        a=seal(fixture()); p=a['proof_objects']
        self.refuse(proof_objects=(p[0],p[0],p[2]))
        self.refuse(evidence_bytes=b' '*1048577)

    def test_original_forward_only_financial_path_still_refuses_historical_purpose(self):
        from tools.research_data_access import FINANCIAL_DATASET
        with self.assertRaises(ContractError):
            self.reader.read_components(FINANCIAL_DATASET,'0'*64,
                decision_time=CUT,purpose='training',components=[],consumer_id=CONSUMER)

if __name__ == '__main__':
    unittest.main()
