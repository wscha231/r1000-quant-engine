# Derived library-boundary test unit; original full parent suite remains immutable.
# Original: tests/chameleon_market_context_v2_smoke.py SHA256 8fa882514d7c810f4e50b809612218e8c4fb8831f4ef45ca7ca965adea2fcb87
# Retained 72 unchanged cases; excluded 10 unadopted activation cases.
"""Author-written synthetic tests. No independent A6 or live-data claims."""

import copy

import hashlib

import json

import tempfile

import sys

import unittest

from pathlib import Path

from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import free_market_context as f

from tools import chameleon_market_context_v2 as c

CLOCK='2026-10-04T12:00:00Z'; DAY='2026-10-02'; KW={'collected_at':CLOCK,'cutoff':CLOCK}

CLOCK='2026-10-04T12:00:00Z'; DAY='2026-10-02'; KW={'collected_at':CLOCK,'cutoff':CLOCK}

CLOCK='2026-10-04T12:00:00Z'; DAY='2026-10-02'; KW={'collected_at':CLOCK,'cutoff':CLOCK}

def raw(x):return json.dumps(x).encode()

def series(source='fred:VIXCLS',values=('20','22'),dates=('2026-10-01',DAY),**kw):
    p,s=source.split(':');header='observation_date,'+s if p=='fred' else 'DATE,CLOSE'
    data=(header+'\n'+'\n'.join(d+','+str(v) for d,v in zip(dates,values))).encode()
    return c.macro_source_rows(data,source_id=source,**{**KW,**kw})

def price(cohort='__MARKET__',r=-.01,**updates):
    row={'cohort':cohort,'members':['XAAA'],'metrics':{'pct_above_ma20':{'value':1.,'eligible_count':1,'expected_count':1}},
         'available_at':CLOCK,'collected_at':CLOCK,'mapping_available_at':CLOCK,'cutoff':CLOCK,'advancers':int(r>0),
         'decliners':int(r<0),'unchanged':int(r==0),'missing_return_count':0,'median_return_1d':r,
         'session':DAY,'source_sha256':'a'*64,'truth_class':'CURRENT_COHORT_RESEARCH_NOT_HISTORICAL_PIT',**f.SAFETY}
    row.update(updates);return row

def calendar(**kw):
    data={'type':'Trends','symbols':'XAAA.US','trends':[[{'code':'XAAA.US','date':'2026-12-31','period':'0y',
            'earningsEstimateAvg':'2','epsTrendCurrent':'2','epsTrend30daysAgo':'1.5'}]]}
    return f.calendar_theme_context(raw(data),['XAAA.US'],{'XAAA.US':['power']},observed_at=CLOCK,
                                   mapping_available_at=CLOCK,**{**KW,**kw})

def public():
    return (f.aaii_observations(b'date,bullish,neutral,bearish\n2026-10-01,40,20,40',unit='percent',**KW)+
        f.cboe_observations(b'DATE,CALL,PUT,TOTAL,P/C Ratio\n10/02/2026,100,60,160,0.6',universe='EQUITY',**KW)+
        f.finra_observations(b'Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20261002|XAAA|60|10|100|Q\n1\n',trade_date=DAY,**KW)+
        f.cot_observations(raw([{'cftc_contract_market_code':'13874A','report_date_as_yyyy_mm_dd':'2026-09-29T00:00:00.000',
             'open_interest_all':'100','asset_mgr_positions_long_all':'60','asset_mgr_positions_short_all':'20'}]),report_kind='TFF_FUTURES',**KW))

def context(**kw):
    args={'macro_rows':series()+series('fred:VXVCLS',('21','20'))+series('fred:BAMLH0A0HYM2',('3.1','3.2')),
        'public_rows':public(),'price_rows':[price(),price('power',r=.02)],'calendar_result':calendar(),
        'security_map':{'XAAA.US':'XAAA'},'security_map_available_at':CLOCK,'cutoff':CLOCK,'expected_session':DAY}
    args.update(kw);return c.build_context(**args)

class MacroParserTests(unittest.TestCase):
    def test_fred_level(self):self.assertEqual(series()[-1]['value'],22)

    def test_cboe_level(self):self.assertEqual(series('cboe:VIX9D')[-1]['value'],22)

    def test_cboe_us_date(self):self.assertEqual(series('cboe:VVIX',dates=('10/01/2026','10/02/2026'))[-1]['observation_date'],DAY)

    def test_null_preserved(self):self.assertIsNone(series(values=('20','.'))[-1]['value'])

    def test_missing_not_empty_history(self):self.assertEqual(len(series(values=('.','.'))),2)

    def test_non_numeric_rejected(self):
        with self.assertRaises(ValueError):series(values=('20','nonsense'))

    def test_underflow_rejected(self):
        with self.assertRaises(ValueError):series(values=('20','1e-999'))

    def test_infinity_rejected(self):
        with self.assertRaises(ValueError):series(values=('20','inf'))

    def test_zero_vol_rejected(self):
        with self.assertRaises(ValueError):series(values=('20','0'))

    def test_negative_vol_rejected(self):
        with self.assertRaises(ValueError):series(values=('20','-1'))

    def test_zero_yield_kept(self):self.assertEqual(series('fred:DGS2',values=('1','0'))[-1]['value'],0)

    def test_future_date(self):
        with self.assertRaises(ValueError):series(dates=('2026-10-01','2026-10-05'))

    def test_future_collection(self):
        with self.assertRaises(ValueError):series(collected_at='2026-10-05T12:00:00Z')

    def test_duplicate_date(self):
        with self.assertRaises(ValueError):series(dates=(DAY,DAY))

    def test_wrong_series(self):
        with self.assertRaises(ValueError):c.macro_source_rows(b'observation_date,DGS10\n2026-10-02,4',source_id='fred:VIXCLS',**KW)

    def test_duplicate_header(self):
        with self.assertRaises(ValueError):c.macro_source_rows(b'DATE,date,VIXCLS\n2026-10-02,2026-10-02,20',source_id='fred:VIXCLS',**KW)

    def test_unknown_source(self):
        with self.assertRaises(ValueError):series('fred:UNKNOWN')

    def test_original_publication_not_fabricated(self):
        row=series()[-1];self.assertIsNone(row['provider_published_at']);self.assertEqual(f.utc(row['available_at']),f.utc(CLOCK))


class MacroPanelTests(unittest.TestCase):
    def test_delta(self):self.assertEqual(c.macro_panel(series(),cutoff=CLOCK)['vix_30d']['change_from_previous_observation'],2)

    def test_latest_null_blocks(self):self.assertIsNone(c.macro_panel(series(values=('20','.')),cutoff=CLOCK)['vix_30d']['value'])

    def test_stale_blocks(self):self.assertEqual(c.macro_panel(series(),cutoff='2026-11-04T12:00:00Z')['vix_30d']['status'],'STALE')

    def test_future_ignored(self):self.assertEqual(c.macro_panel(series(),cutoff='2026-10-03T12:00:00Z'),{})

    def test_source_collision(self):
        with self.assertRaises(ValueError):c.macro_panel(series()+series('cboe:VIX'),cutoff=CLOCK)

    def test_exact_duplicates_idempotent(self):
        r=series();self.assertEqual(c.macro_panel(r+r,cutoff=CLOCK),c.macro_panel(r,cutoff=CLOCK))

    def test_ambiguous_vintage(self):
        r=series();r.append({**r[-1],'value':40})
        with self.assertRaises(ValueError):c.macro_panel(r,cutoff=CLOCK)

    def test_later_correction(self):
        r=series(collected_at='2026-10-04T11:00:00Z');r.append({**r[-1],'collected_at':CLOCK,'available_at':CLOCK,'value':25})
        self.assertEqual(c.macro_panel(r,cutoff=CLOCK)['vix_30d']['value'],25)

    def test_authority_rejected(self):
        r=series();r[-1]['h2_eligible']=True
        with self.assertRaises(ValueError):c.macro_panel(r,cutoff=CLOCK)

    def test_hash_rejected(self):
        r=series();r[-1]['source_sha256']='x'
        with self.assertRaises(ValueError):c.macro_panel(r,cutoff=CLOCK)

    def test_unit_rejected(self):
        r=series();r[-1]['unit']='percent'
        with self.assertRaises(ValueError):c.macro_panel(r,cutoff=CLOCK)

    def test_negative_observation_rejected(self):
        r=series();r[-1]['value']=-2
        with self.assertRaises(ValueError):c.macro_panel(r,cutoff=CLOCK)

    def test_matching_dates_ratio(self):
        p=c.macro_panel(series()+series('fred:VXVCLS',('20','20')),cutoff=CLOCK)
        self.assertEqual(c.derived_macro(p)['vix30_to_vix3m']['value'],1.1)

    def test_mismatched_dates_not_backfilled(self):
        p=c.macro_panel(series()+series('fred:VXVCLS',dates=('2026-09-30','2026-10-01')),cutoff=CLOCK)
        self.assertEqual(c.derived_macro(p)['vix30_to_vix3m']['status'],'OBSERVATION_DATE_MISMATCH')

    def test_sofr_iorb_difference(self):
        p=c.macro_panel(series('fred:SOFR',('4','4.1'))+series('fred:IORB',('4','4')),cutoff=CLOCK)
        self.assertAlmostEqual(c.derived_macro(p)['sofr_minus_iorb']['value'],.1)

    def test_missing_3m(self):self.assertEqual(c.derived_macro({})['vix30_to_vix3m']['status'],'MISSING_INPUT')

    def test_gap_previous_null(self):self.assertIsNone(c.macro_panel(series(values=('.','22')),cutoff=CLOCK)['vix_30d']['change_from_previous_observation'])

    def test_old_previous_not_delta(self):self.assertIsNone(c.macro_panel(series(dates=('2020-01-01',DAY)),cutoff=CLOCK)['vix_30d']['change_from_previous_observation'])


class IntegrationTests(unittest.TestCase):
    def test_real_c1_pairing_functions(self):
        v=context();self.assertEqual(v['paired_themes'][0]['positive_vendor_revision_fraction'],1)

    def test_no_automatic_regime(self):
        v=context();self.assertIsNone(v['regime']);self.assertFalse(v['regime_authorized']);self.assertFalse(v['orders_generated'])

    def test_joint_condition(self):self.assertIn('MEDIAN_PRICE_DOWN_CREDIT_SPREAD_UP',[x['code'] for x in context()['diagnostics']])

    def test_term_condition(self):self.assertIn('FRONT_IV_ABOVE_3M',[x['code'] for x in context()['diagnostics']])

    def test_no_independent_votes(self):self.assertIsNone(context()['independent_alpha_votes'])

    def test_missing_macro_not_neutral(self):self.assertIn('macro',context(macro_rows=[])['missing_families'])

    def test_optional_calendar_absent(self):self.assertEqual(context(calendar_result=None)['paired_themes'],[])

    def test_optional_public_absent(self):self.assertEqual(context(public_rows=[])['public'],[])

    def test_wrong_price_session_separate(self):
        p=[price(),price('power',session='2026-10-01')]
        self.assertEqual(context(price_rows=p)['paired_themes'][0]['status'],'WAIT_EXPECTED_PRICE_SESSION')

    def test_calendar_stale_not_usable(self):
        v=context(cutoff='2026-10-09T12:00:01Z')
        self.assertEqual(v['paired_themes'][0]['status'],'STALE_CALENDAR_CONTEXT');self.assertIsNone(v['paired_themes'][0]['positive_vendor_revision_fraction'])

    def test_cohort_mismatch_separate(self):
        p=[price(),price('power',members=['XBBB'])]
        self.assertEqual(context(price_rows=p)['paired_themes'][0]['status'],'COHORT_MISMATCH_SEPARATE_CONTEXTS')

    def test_bad_denominator(self):
        with self.assertRaises(ValueError):context(price_rows=[price(advancers=3)])

    def test_bad_metric_denominator(self):
        p=price();p['metrics']['pct_above_ma20']['expected_count']=2
        with self.assertRaises(ValueError):context(price_rows=[p])

    def test_calendar_forged_fraction(self):
        x=calendar();x['themes'][0]['coverage_fraction']=.2
        with self.assertRaises(ValueError):context(calendar_result=x)

    def test_partial_prices_not_joint_confirmation(self):
        p=price(members=['XAAA','XBBB'],missing_return_count=1,metrics={})
        self.assertNotIn('MEDIAN_PRICE_DOWN_CREDIT_SPREAD_UP',[x['code'] for x in context(price_rows=[p])['diagnostics']])

    def test_future_mapping(self):
        with self.assertRaises(ValueError):context(price_rows=[price(mapping_available_at='2026-10-05T12:00:00Z')])

    def test_unknown_public_provider(self):
        rows=public();rows[0]['provider']='UNKNOWN'
        with self.assertRaises(ValueError):context(public_rows=rows)

    def test_hash_integrity(self):c.verify_context(context())

    def test_inputs_preserved(self):
        prices=[price(),price('power')];before=copy.deepcopy(prices);context(price_rows=prices);self.assertEqual(prices,before)


class DeltaTests(unittest.TestCase):
    def test_first_suggests_review(self):self.assertEqual(c.context_delta(None,context())['status'],'CONTEXT_CHANGED_REVIEW_ONLY')

    def test_unchanged(self):
        x=context();self.assertEqual(c.context_delta(x,x)['status'],'SKIP_UNCHANGED_CONTEXT')

    def test_clock_only_not_semantic_change(self):
        x=context();y=copy.deepcopy(x);y['cutoff']='2026-10-04T13:00:00Z';y['content_sha256']=c.digest({k:v for k,v in y.items() if k!='content_sha256'})
        self.assertEqual(c.context_delta(x,y)['status'],'SKIP_UNCHANGED_CONTEXT')

    def test_expiry_forces_review(self):self.assertEqual(c.context_delta(context(),context(cutoff='2026-11-04T12:00:00Z'))['status'],'CONTEXT_CHANGED_REVIEW_ONLY')

    def test_tamper_rejected(self):
        x=context();x['macro']['vix_30d']['value']=99
        with self.assertRaises(ValueError):c.context_delta(None,x)

    def test_backwards_rejected(self):
        with self.assertRaises(ValueError):c.context_delta(context(cutoff='2026-10-05T12:00:00Z'),context())

    def test_rehashed_economic_flag_rejected(self):
        x=context();x['h2_eligible']=True;x['content_sha256']=c.digest({k:v for k,v in x.items() if k!='content_sha256'})
        with self.assertRaises(ValueError):c.context_delta(None,x)


class AdditionalIntegrationTests(unittest.TestCase):
    def test_provider_binding(self):
        rows=series();rows[-1]['provider']='CBOE'
        with self.assertRaises(ValueError):c.macro_panel(rows,cutoff=CLOCK)

    def test_dataset_binding(self):
        rows=series();rows[-1]['dataset']='OTHER'
        with self.assertRaises(ValueError):c.macro_panel(rows,cutoff=CLOCK)

    def test_future_calendar_collection(self):
        x=calendar();x['source']['collected_at']='2026-10-05T12:00:00Z'
        with self.assertRaises(ValueError):context(calendar_result=x)

    def test_bad_calendar_hash(self):
        x=calendar();x['source']['source_sha256']='invalid'
        with self.assertRaises(ValueError):context(calendar_result=x)

    def test_price_revision_joint_positive(self):
        codes=[r['code'] for r in context()['diagnostics']]
        self.assertIn('PRICE_UP_VENDOR_REVISIONS_MAJORITY_POSITIVE',codes)

    def test_price_revision_divergence(self):
        codes=[r['code'] for r in context(price_rows=[price(),price('power')])['diagnostics']]
        self.assertIn('PRICE_DOWN_VENDOR_REVISIONS_MAJORITY_POSITIVE',codes)

    def test_joint_source_refs(self):
        row=context()['paired_themes'][0]
        self.assertEqual(len(row['source_refs']['calendar_sha256']),64)

    def test_market_rally_front_inversion(self):
        codes=[r['code'] for r in context(price_rows=[price(r=.01),price('power')])['diagnostics']]
        self.assertIn('PRICE_UP_WITH_FRONT_IV_INVERSION',codes)

    def test_bullish_survey_divergence(self):
        rows=f.aaii_observations(b'date,bullish,neutral,bearish\n2026-10-01,50,20,30',unit='percent',**KW)
        codes=[r['code'] for r in context(public_rows=rows)['diagnostics']]
        self.assertIn('BULLISH_SURVEY_WITH_PRICE_DECLINE',codes)

    def test_stale_survey_not_used(self):
        rows=f.aaii_observations(b'date,bullish,neutral,bearish\n2026-01-01,50,20,30',unit='percent',**KW)
        codes=[r['code'] for r in context(public_rows=rows)['diagnostics']]
        self.assertNotIn('BULLISH_SURVEY_WITH_PRICE_DECLINE',codes)


if __name__=='__main__':unittest.main(verbosity=2)

