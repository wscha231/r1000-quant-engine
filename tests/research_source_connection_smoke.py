#!/usr/bin/env python3
"""Provider failures, historical dates and source persistence boundaries."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import research_source_connection as m


def fact(start,end,filed,value):
    return dict(start=start,end=end,filed=filed,val=value,form='10-Q',accn=filed)


def facts(rows):
    return {'facts':{'us-gaap':{'Revenues':{'units':{'USD':rows}}}}}


class Connection(unittest.TestCase):
    def test_provider_error_discarded_even_for_csv(self):
        with tempfile.TemporaryDirectory() as d:
            c=m.Capture(d)
            for json_body in (True,False):
                with patch.object(m,'request_raw',return_value=b'{"Information":"key=private echoed here"}'):
                    self.assertRaisesRegex(ValueError,'provider_body_error',c.get,'x','https://www.alphavantage.co/query',json_body=json_body)
            self.assertEqual(list(Path(d).iterdir()),[])
            self.assertEqual(c.receipts,[])

    def test_raw_digest_and_credentials_not_in_receipt(self):
        raw=b'{"bars":{}}'
        with tempfile.TemporaryDirectory() as d,patch.object(m,'request_raw',return_value=raw):
            c=m.Capture(d)
            _,r=c.get('bars','https://data.alpaca.markets/v2/stocks/bars',{'api_key':'secret'},{'Auth':'secret'})
            self.assertEqual((Path(d)/(r['raw_sha256']+'.raw')).read_bytes(),raw)
            self.assertNotIn('secret',json.dumps(r))

    def test_existing_raw_symlink_rejected(self):
        raw=b'{}'
        with tempfile.TemporaryDirectory() as d,patch.object(m,'request_raw',return_value=raw):
            target=Path(d)/'target';target.write_bytes(raw)
            (Path(d)/(m.digest_bytes(raw)+'.raw')).symlink_to(target)
            self.assertRaisesRegex(ValueError,'symlink_path',m.Capture(d).get,'x','https://data.sec.gov/x')

    def test_missing_key_and_alias_conflict_are_distinct(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(m.guarded('x',lambda:m.key('KEY'))['reason'],'credential_missing')
        with patch.dict(os.environ,{'KEY':'one','ALIAS':'two'},clear=True):
            self.assertEqual(m.guarded('x',lambda:m.key('KEY','ALIAS'))['reason'],'credential_alias_conflict')

    def test_arbitrary_error_cannot_leak_into_report(self):
        def bad():raise ValueError('https://example.test/?key=private')
        self.assertEqual(m.guarded('x',bad)['reason'],'INPUT_OR_PROVIDER_CONTRACT')

    def test_ttm_annual_plus_ytd_minus_comparable_not_quarter(self):
        rows=[fact('2024-01-01','2024-12-31','2025-02-01',100),
              fact('2024-01-01','2024-06-30','2024-08-01',40),
              fact('2025-01-01','2025-06-30','2025-08-01',70),
              fact('2025-04-01','2025-06-30','2025-08-01',35)]
        result=m.ttm_from_facts(facts(rows),['Revenues'],'2025-08-05')
        self.assertEqual(result['value'],130)
        self.assertFalse(result['valuation_approved'])
        self.assertFalse(result['intraday_publication_verified'])

    def test_future_restatement_not_used(self):
        rows=[fact('2024-01-01','2024-12-31','2025-02-01',100),
              fact('2024-01-01','2024-12-31','2025-10-01',900)]
        self.assertEqual(m.ttm_from_facts(facts(rows),['Revenues'],'2025-09-09')['value'],100)

    def test_incomplete_fiscal_ytd_or_unknown_never_filled(self):
        rows=[fact('2024-01-01','2024-12-31','2025-02-01',100),
              fact('2025-04-01','2025-06-30','2025-08-01',35)]
        self.assertIsNone(m.ttm_from_facts(facts(rows),['Revenues'],'2025-09-09'))
        self.assertIsNone(m.ttm_from_facts(facts([]),['Revenues'],'2025-09-09'))

    def test_pagination_collects_later_symbols_and_preserves_missing(self):
        calls=[]
        def response(base,params,headers):
            calls.append(params.copy())
            if 'page_token' not in params:
                value={'bars':{'NVDA':[{'t':'2026-09-08T04:00:00Z','c':100}]},'next_page_token':'p2'}
            else:value={'bars':{'SPY':[{'t':'2026-09-09T04:00:00Z','c':200}]},'next_page_token':None}
            return json.dumps(value).encode()
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ALPACA_API_KEY':'a','ALPACA_API_SECRET':'b'}),patch.object(m,'request_raw',side_effect=response):
            result=m.collect_bars(m.Capture(d),'2026-09-08','2026-09-09')
        self.assertEqual(len(calls),4)
        by={r['ticker']:r for r in result['securities']}
        self.assertFalse(by['NVDA']['exact_requested_close'])
        self.assertTrue(by['SPY']['exact_requested_close'])
        self.assertIsNone(by['EME']['close'])
        self.assertFalse(result['historical_universe_verified'])

    def test_repeated_token_rejected(self):
        raw=b'{"bars":{},"next_page_token":"repeat"}'
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ALPACA_API_KEY':'a','ALPACA_API_SECRET':'b'}),patch.object(m,'request_raw',return_value=raw):
            self.assertRaisesRegex(ValueError,'repeated_page_token',m.collect_bars,m.Capture(d),'2026-09-08','2026-09-09')

    def test_future_price_rejected(self):
        raw=b'{"bars":{"NVDA":[{"t":"2026-09-10T04:00:00Z","c":100}]}}'
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ALPACA_API_KEY':'a','ALPACA_API_SECRET':'b'}),patch.object(m,'request_raw',return_value=raw):
            self.assertRaisesRegex(ValueError,'bar_value_or_date',m.collect_bars,m.Capture(d),'2026-09-08','2026-09-09')

    def test_all_sources_blocked_does_not_create_cash_allocation(self):
        with tempfile.TemporaryDirectory() as d,patch.object(m,'request_raw',side_effect=OSError),patch.dict(os.environ,{},clear=True):
            r=m.run(d,'2019-05-09','2026-09-09')
        self.assertEqual(r['backtest_status'],'BLOCKED')
        self.assertIsNone(r['portfolio_weights'])
        self.assertIsNone(r['metrics'])
        self.assertFalse(r['orders_allowed'])


if __name__=='__main__':unittest.main()
