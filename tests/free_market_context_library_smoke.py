# Derived library-boundary test unit; original full parent suite remains immutable.
# Original: tests/free_market_context_smoke.py SHA256 7630113efccb055ae02103cf42e60c9b909d5026c84585dfa51dca91300cf83f
# Retained 78 unchanged cases; excluded 17 unadopted activation cases.
"""Offline synthetic source/consumer tests. No real provider HTTP is permitted."""

import copy

import hashlib

import io

import json

import sys

import tempfile

import unittest

from contextlib import redirect_stdout

from datetime import datetime, timezone

from pathlib import Path

from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from tools import free_market_context as m

CLOCK = "2026-10-04T11:00:00Z"

DAY = "2026-10-02"

KW = {"collected_at": CLOCK, "cutoff": CLOCK}

def raw(x): return json.dumps(x).encode()

def cot(**updates):
    r = {"cftc_contract_market_code": "13874A", "report_date_as_yyyy_mm_dd": "2026-09-29T00:00:00.000",
        "open_interest_all": "100", "asset_mgr_positions_long_all": "60", "asset_mgr_positions_short_all": "20"}
    r.update(updates); return r

def fr(line="20261002|XAAA|60|10|100|Q,N", trailer="1"):
    return ("Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"+line+"\n"+trailer+"\n").encode()

def calrow(symbol="XAAA.US", **updates):
    r = {"code": symbol, "date": "2026-12-31", "period": "0y", "earningsEstimateAvg": "2",
         "epsTrendCurrent": "2", "epsTrend30daysAgo": "1.5"}
    r.update(updates); return r

def calpayload(groups=None, symbols=("XAAA.US",)):
    return raw({"type": "Trends", "symbols": ",".join(symbols), "trends": groups or [[calrow(s)] for s in symbols]})

class CoreTests(unittest.TestCase):
    def test_zero_kept(self): self.assertEqual(m.number("0"), 0)

    def test_none_kept(self): self.assertIsNone(m.number(None))

    def test_bool_rejected(self):
        with self.assertRaises(m.ContextError): m.number(True)

    def test_underflow_rejected(self):
        with self.assertRaises(m.ContextError): m.number("1e-999")

    def test_fractional_count_rejected(self):
        with self.assertRaises(m.ContextError): m.number("2.000000000000001", integral=True)

    def test_nan_rejected(self):
        with self.assertRaises(m.ContextError): m.number(float("nan"))

    def test_duplicate_json_rejected(self):
        with self.assertRaises(m.ContextError): m.strict_json(b'{"a":1,"a":2}')

    def test_json_underflow_rejected(self):
        with self.assertRaises(m.ContextError): m.strict_json(b'{"a":1e-999}')

    def test_date_only_clock_rejected(self):
        with self.assertRaises(m.ContextError): m.utc(DAY)

    def test_timezone_conversion(self): self.assertEqual(m.utc("2026-10-04T20:00:00+09:00"), m.utc(CLOCK))

    def test_future_collection_rejected(self):
        with self.assertRaises(m.ContextError): m.provenance(b'x',provider='X',dataset='Y',collected_at=CLOCK,cutoff="2026-10-03T10:00:00Z")

    def test_csv_duplicate_header(self):
        with self.assertRaises(m.ContextError): m.csv_records(b'a,a\n1,2')

    def test_csv_truncation(self):
        with self.assertRaises(m.ContextError): m.csv_records(b'a,b\n1')


class CotTests(unittest.TestCase):
    def run_cot(self, rows=None, **kw): return m.cot_observations(raw([cot()] if rows is None else rows),report_kind="TFF_FUTURES", **{**KW, **kw})

    def test_net_and_ratio(self):
        rows = self.run_cot(); v=[x for x in rows if x['group']=='ASSET_MANAGER']
        self.assertEqual(v[0]['value'],40); self.assertEqual(v[1]['value'],.4)

    def test_missing_group_not_zero(self): self.assertIsNone(self.run_cot()[0]['value'])

    def test_observation_not_publication(self):
        r=self.run_cot()[0]; self.assertNotEqual(r['observation_date'],r['available_at'][:10]); self.assertFalse(r['h2_eligible'])

    def test_duplicate_rejected(self):
        with self.assertRaises(m.ContextError): self.run_cot([cot(),cot()])

    def test_future_observation_rejected(self):
        with self.assertRaises(m.ContextError): self.run_cot([cot(report_date_as_yyyy_mm_dd="2026-10-06T00:00:00.000")])

    def test_combined_rejected(self):
        with self.assertRaises(m.ContextError): self.run_cot([cot(futonly_or_combined="Combined")])

    def test_position_gt_oi(self):
        with self.assertRaises(m.ContextError): self.run_cot([cot(asset_mgr_positions_long_all="101")])

    def test_numeric_market_rejected(self):
        with self.assertRaises(m.ContextError): self.run_cot([cot(cftc_contract_market_code=13874)])

    def test_zero_oi(self):
        r=self.run_cot([cot(open_interest_all="0",asset_mgr_positions_long_all="0",asset_mgr_positions_short_all="0")])
        self.assertIsNone([x for x in r if x['group']=='ASSET_MANAGER'][1]['value'])

    def test_no_fixed_friday_inference(self): self.assertEqual(self.run_cot()[0]['availability_basis'],'COLLECTION_ONLY_NOT_ORIGINAL_PUBLICATION')

    def test_disagg_separate(self):
        r=cot(m_money_positions_long_all='50',m_money_positions_short_all='30')
        out=m.cot_observations(raw([r]),report_kind='DISAGG_FUTURES',**KW)
        self.assertEqual([x for x in out if x['group']=='MANAGED_MONEY'][0]['value'],20)

    def test_headers_case(self):
        r={k.upper():v for k,v in cot().items()}; self.assertEqual(len(self.run_cot([r])),10)


class FinraTests(unittest.TestCase):
    def run_fr(self, data=None): return m.finra_observations(fr() if data is None else data,trade_date=DAY,**KW)

    def test_exempt_is_not_added(self): self.assertEqual(self.run_fr()[0]['value'],.6)

    def test_no_short_interest_claim(self): self.assertIn('NOT_SHORT_INTEREST',self.run_fr()[0]['interpretation'])

    def test_trailer_mismatch(self):
        with self.assertRaises(m.ContextError): self.run_fr(fr(trailer='2'))

    def test_missing_trailer(self):
        with self.assertRaises(m.ContextError): self.run_fr(fr().rsplit(b'1\n',1)[0])

    def test_empty_file_with_zero(self): self.assertEqual(self.run_fr(fr(line='',trailer='0')),[])

    def test_duplicate_symbol(self):
        with self.assertRaises(m.ContextError): self.run_fr(fr(line='20261002|XAAA|1|0|2|Q\n20261002|XAAA|1|0|2|N',trailer='2'))

    def test_wrong_date(self):
        with self.assertRaises(m.ContextError): self.run_fr(fr(line='20261001|XAAA|1|0|2|Q'))

    def test_volume_order(self):
        with self.assertRaises(m.ContextError): self.run_fr(fr(line='20261002|XAAA|101|0|100|Q'))

    def test_exempt_subset(self):
        with self.assertRaises(m.ContextError): self.run_fr(fr(line='20261002|XAAA|1|2|100|Q'))

    def test_zero_volume(self): self.assertIsNone(self.run_fr(fr(line='20261002|XAAA|0|0|0|Q'))[0]['value'])

    def test_component_other_scope_rejected(self):
        with self.assertRaises(m.ContextError): self.run_fr(fr(line='20261002|XAAA|1|0|2|O'))


class OtherSourcesTests(unittest.TestCase):
    def cb(self, line='10/02/2026,100,60,160,0.60'):
        return m.cboe_observations(('DATE,CALL,PUT,TOTAL,P/C Ratio\n'+line).encode(), universe='EQUITY',**KW)

    def test_cboe_ratio(self): self.assertEqual(self.cb()[0]['value'],.6)

    def test_cboe_mismatch(self):
        with self.assertRaises(m.ContextError): self.cb('10/02/2026,100,60,160,0.8')

    def test_cboe_zero_calls(self): self.assertIsNone(self.cb('10/02/2026,0,60,60,0')[0]['value'])

    def test_cboe_duplicate(self):
        with self.assertRaises(m.ContextError): self.cb('10/02/2026,100,60,160,0.6\n10/02/2026,100,60,160,0.6')

    def test_aaii_percent(self):
        r=m.aaii_observations(b'date,bullish,neutral,bearish\n2026-10-01,40,25,35',unit='percent',**KW)
        self.assertEqual(r[0]['value'],.05)

    def test_aaii_wrong_scale(self):
        with self.assertRaises(m.ContextError): m.aaii_observations(b'date,bullish,neutral,bearish\n2026-10-01,40,25,35',unit='fraction',**KW)

    def test_aaii_missing(self):
        with self.assertRaises(m.ContextError): m.aaii_observations(b'date,bullish,neutral,bearish\n2026-10-01,40,,35',unit='percent',**KW)


class HistoryTests(unittest.TestCase):
    def rows(self):
        r=m.finra_observations(fr(),trade_date=DAY,**KW)[0]
        old={**r,'observation_date':'2026-10-01','value':.4}
        return [old,r]

    def calc(self,r=None,**kw): return m.trailing_context(self.rows() if r is None else r,cutoff=CLOCK,max_age_days=5,lookback=3,minimum=2,**kw)

    def test_midrank(self): self.assertEqual(self.calc()[0]['trailing_midrank'],.75)

    def test_latest_null_no_backfill(self):
        r=self.rows();r[-1]['value']=None; self.assertIsNone(self.calc(r)[0]['current_value'])

    def test_stale_not_current(self):
        r=self.rows();[x.update(observation_date='2020-01-01') for x in r]
        r=r[:1];out=self.calc(r)[0];self.assertEqual(out['status'],'STALE');self.assertIsNone(out['current_value'])

    def test_future_record_ignored(self):
        r=self.rows();r[-1].update(available_at='2026-10-05T11:00:00Z',collected_at='2026-10-05T11:00:00Z')
        self.assertEqual(self.calc(r)[0]['current_value'],.4)

    def test_conflict_rejected(self):
        r=self.rows();r.append({**r[-1],'value':.9})
        with self.assertRaises(m.ContextError):self.calc(r)

    def test_revision_later_not_best(self):
        r=self.rows();r.append({**r[-1],'available_at':'2026-10-04T10:00:00Z','collected_at':'2026-10-04T10:00:00Z','value':.9})
        self.assertEqual(self.calc(r)[0]['current_value'],.6)


class CalendarBridgeTests(unittest.TestCase):
    def calc(self, data=None, symbols=('XAAA.US',), mapping=None, **kw):
        return m.calendar_theme_context(calpayload(symbols=symbols) if data is None else data,list(symbols),
            mapping or {s:['power'] for s in symbols}, observed_at=CLOCK, mapping_available_at=CLOCK, **{**KW,**kw})

    def test_actual_c1_h1_executes(self):
        r=self.calc(); self.assertEqual(r['snapshot_count'],1); self.assertFalse(r['h2_eligible']);self.assertEqual(r['themes'][0]['vendor_positive_change_fraction'],1)

    def test_no_true_revision_admission(self): self.assertIsNone(self.calc()['themes'][0]['strict_h1_revision'])

    def test_zero_denominator_missing(self): self.assertEqual(self.calc(calpayload([[calrow(epsTrend30daysAgo='0')]]))['themes'][0]['computable_symbol_count'],0)

    def test_negative_denominator_missing(self): self.assertEqual(self.calc(calpayload([[calrow(epsTrend30daysAgo='-1')]]))['themes'][0]['computable_symbol_count'],0)

    def test_missing_symbol_stays_denominator(self):
        r=self.calc(calpayload([[calrow()],[]],('XAAA.US','XBBB.US')),symbols=('XAAA.US','XBBB.US'))
        self.assertEqual(r['themes'][0]['coverage_fraction'],.5)

    def test_old_fiscal_omitted(self): self.assertEqual(self.calc(calpayload([[calrow(date='2020-12-31')]]))['themes'],[])

    def test_symbol_mismatch_rejected_by_c1(self):
        with self.assertRaises(ValueError): self.calc(calpayload([[calrow('XBBB.US')]]))

    def test_actual_not_estimate_rejected_by_c1(self):
        with self.assertRaises(ValueError): self.calc(calpayload([[calrow(is_estimate=False)]]))

    def test_c1_underflow_not_zero(self):
        r=self.calc(calpayload([[calrow(epsTrendCurrent='1e-999')]]));self.assertEqual(r['themes'][0]['computable_symbol_count'],0)

    def test_mapping_coverage(self):
        with self.assertRaises(m.ContextError): self.calc(mapping={'XBBB.US':['x']})


class PriceTests(unittest.TestCase):
    def data(self):
        import pandas as pd
        idx=pd.bdate_range(end=DAY,periods=255)
        return pd.DataFrame({'XAAA':range(1,256),'XBBB':range(255,0,-1)},index=idx),pd.DataFrame(100.,columns=['XAAA','XBBB'],index=idx)

    def calc(self, px=None,vol=None,**kw):
        x,y=self.data();x=x if px is None else px;y=y if vol is None else vol
        return m.price_theme_context(x,y,list(x.index),['XAAA','XBBB','XMISSING'],{'XAAA':['growth'],'XBBB':['growth']},
            membership_available_at=CLOCK,source_sha256='a'*64,**{**KW,**kw})

    def test_native_helper_reuse(self):
        r=self.calc()[0];self.assertEqual(r['metrics']['pct_above_ma50']['value'],.5)
        self.assertEqual(r['metrics']['pct_above_ma50']['expected_count'],3)

    def test_ma20_added(self): self.assertEqual(self.calc()[0]['metrics']['pct_above_ma20']['value'],.5)

    def test_missing_count_preserved(self): self.assertEqual(self.calc()[0]['missing_return_count'],1)

    def test_theme_membership(self): self.assertEqual(self.calc()[1]['metrics']['pct_above_ma50']['expected_count'],2)

    def test_adjusted_price_not_dollar_turnover(self): self.assertIsNone(self.calc()[0]['metrics']['adv_decl_dollar_volume_ratio']['value'])

    def test_negative_price(self):
        x,y=self.data();x.iloc[-1,0]=-1
        with self.assertRaises(m.ContextError):self.calc(x,y)

    def test_grid_mismatch(self):
        x,y=self.data()
        with self.assertRaises(m.ContextError):self.calc(x,y.iloc[:-1])

    def test_future_collection(self):
        with self.assertRaises(m.ContextError):self.calc(collected_at='2026-10-05T11:00:00Z')

    def test_bool_price_rejected(self):
        x,y=self.data();x=x.astype(bool)
        with self.assertRaises(m.ContextError):self.calc(x,y)


class IntegrationBoundaryTests(unittest.TestCase):
    def test_cot_no_fabricated_publication_clock(self):
        r=m.cot_observations(raw([cot()]),report_kind='TFF_FUTURES',**KW)
        self.assertIsNone(r[0]['provider_published_at'])
        self.assertNotEqual(r[0]['observation_date'],r[0]['available_at'][:10])

    def test_calendar_overflow_does_not_become_positive_signal(self):
        r=CalendarBridgeTests().calc(calpayload([[calrow(epsTrendCurrent='1e308',epsTrend30daysAgo='1e-308')]]))
        self.assertEqual(r['themes'][0]['computable_symbol_count'],0)

    def test_socrata_suffix_alias(self):
        row=cot();row['asset_mgr_positions_long']=row.pop('asset_mgr_positions_long_all')
        r=m.cot_observations(raw([row]),report_kind='TFF_FUTURES',**KW)
        self.assertEqual([v['value'] for v in r if v['group']=='ASSET_MANAGER'][0],40)

    def test_conflicting_socrata_alias(self):
        with self.assertRaises(m.ContextError):
            m.cot_observations(raw([cot(asset_mgr_positions_long='9')]),report_kind='TFF_FUTURES',**KW)

    def fixture(self):
        px=PriceTests().calc()
        cal=CalendarBridgeTests().calc(mapping={'XAAA.US':['growth']})
        public=m.cot_observations(raw([cot()]),report_kind='TFF_FUTURES',**KW)+m.finra_observations(fr(),trade_date=DAY,**KW)
        return px,cal,public

    def compose(self, data=None,**kw):
        return m.compose_research_context(*(data or self.fixture()),security_map={'XAAA.US':'XAAA'},
            security_map_available_at=CLOCK,cutoff=CLOCK,expected_session=DAY,**kw)

    def test_end_to_end_different_cohort_never_paired(self):
        r=self.compose();self.assertEqual(r['paired_themes'][0]['status'],'COHORT_MISMATCH_SEPARATE_CONTEXTS')
        self.assertIsNone(r['paired_themes'][0]['price_context'])

    def test_end_to_end_c1_price_and_public_bundle(self):
        x,c,p=self.fixture()
        c=CalendarBridgeTests().calc(symbols=('XAAA.US','XBBB.US'),mapping={'XAAA.US':['growth'],'XBBB.US':['growth']})
        r=m.compose_research_context(x,c,p,security_map={'XAAA.US':'XAAA','XBBB.US':'XBBB'},
            security_map_available_at=CLOCK,cutoff=CLOCK,expected_session=DAY)
        self.assertEqual(r['paired_themes'][0]['status'],'PAIRED_DIAGNOSTICS_NOT_ALPHA')
        self.assertFalse(r['h2_eligible']);self.assertEqual(len(r['sections']['public']),11)
        x[0]['cohort']='MUTATED';self.assertNotEqual(r['sections']['price'][0]['cohort'],'MUTATED')

    def test_bundle_future_public_rejected(self):
        x,c,p=self.fixture();p[0]['available_at']='2027-01-01T00:00:00Z'
        with self.assertRaises(m.ContextError):self.compose((x,c,p))

    def test_bundle_permission_conflict(self):
        x,c,p=self.fixture();c['h2_eligible']=True
        with self.assertRaises(m.ContextError):self.compose((x,c,p))

    def test_bundle_wrong_session_not_current(self):
        x,c,p=self.fixture();x[1]['session']='2026-10-01'
        r=self.compose((x,c,p));self.assertEqual(r['paired_themes'][0]['status'],'WAIT_EXPECTED_PRICE_SESSION')

    def test_bundle_duplicate_cohort_rejected(self):
        x,c,p=self.fixture();x.append(copy.deepcopy(x[0]))
        with self.assertRaises(m.ContextError):self.compose((x,c,p))


if __name__=='__main__':
    import requests,socket
    with patch.object(requests.sessions.Session,'get',side_effect=AssertionError('REAL_HTTP_FORBIDDEN')),patch.object(socket,'create_connection',side_effect=AssertionError('REAL_NETWORK_FORBIDDEN')):
        unittest.main(verbosity=2)

