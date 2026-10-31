#!/usr/bin/env python3
"""H1 synthetic arithmetic and refusal tests; unittest checks survive -O."""
from __future__ import annotations

import copy
from functools import lru_cache
import importlib.util
import json
import math
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import build_run287_ohlcv_location_timing_challenger as target
from tools import research_data_access as access
from tools.macro_history_sources import digest, encoded

spec = importlib.util.spec_from_file_location('h1_independent_oracle',
    ROOT / 'tests/fixtures/technical_feature_h1/independent_oracle.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)

SESSION = '2026-10-13'
ASOF = '2026-10-14T00:00:00Z'
GRID = mcal.get_calendar('NYSE').schedule(start_date='2023-01-01', end_date=SESSION).index[-510:]
DAYS = [str(d.date()) for d in GRID]
IDS = {'TEST': 'FIXTURE:US:TEST', 'SPY': 'FIXTURE:US:SPY', '^IXIC': 'FIXTURE:US:IXIC'}


class MemoryTransport:
    def __init__(self):
        self.objects = {}

    def read(self, path):
        if path not in self.objects:
            raise FileNotFoundError(path)
        return self.objects[path]

    def write(self, *_args):
        raise AssertionError('SOURCE_WRITE_NOT_ALLOWED')


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the exact canonical calendar computation, not a weekday or
        # invented-session substitute. Cache only pure close calculations.
        cls.calendar_cache = patch.object(access, '_session_close',
            lru_cache(maxsize=2048)(access._session_close))
        cls.calendar_cache.start()

    @classmethod
    def tearDownClass(cls):
        cls.calendar_cache.stop()

    def setUp(self):
        self.transport = MemoryTransport()
        self.reader = access.ResearchDataReader(self.transport)
        self.manifest = dict(schema='research-data-generation-v1',
            eligible_for_selector=False, created_at='2026-10-13T23:00:00Z',
            source_run_id='SYNTHETIC_H1_NOT_MARKET_DATA', datasets=[dict(
                dataset_id='ds.us.prices.daily', schema='price-daily-v1', files=[],
                source=dict(provider='SYNTHETIC_FIXTURE', license='LOCAL_QA_ONLY',
                    access_policy='LOCAL_QA_ONLY', classification='CONTRACT_FIXTURE',
                    admission_state='RESEARCH_BYTES_ONLY', eligible_purposes=['research'],
                    pit_status='VERIFIED', corporate_action_status='VERIFIED',
                    lifecycle_status='VERIFIED', producer_code_sha='1'*40,
                    producer_config_sha256='2'*64, source_receipt_sha256='3'*64,
                    raw_source_sha256=['4'*64], available_from='2026-10-13T21:05:00Z',
                    collected_at='2026-10-13T22:00:00Z', expires_at='2026-10-20T00:00:00Z'))])
        self.rows = {}
        for ticker, iid in IDS.items():
            j = np.arange(len(DAYS), dtype=float)
            c = (40 + 0.03*j + np.sin(j/7)) if ticker == 'TEST' else (
                300 + 0.02*j + np.sin(j/13) if ticker == 'SPY' else 1000 + 0.2*j + np.sin(j/5))
            self.rows[iid] = [dict(instrument_id=iid, ticker=ticker, session_date=day,
                available_from=day+'T21:05:00Z', open=float(v-.1), high=float(v+.6),
                low=float(v-.6), close=float(v), volume=float(1000+i%23*13))
                for i, (day,v) in enumerate(zip(DAYS,c))]
            self.add_file(iid)

    @property
    def data_spec(self):
        return self.manifest['datasets'][0]

    def add_file(self, iid, *, identity=None):
        rows = self.rows[iid]
        raw = b''.join(encoded(r) for r in rows)
        h = digest(raw)
        ident = identity or dict(instrument_id=iid, ticker=rows[0]['ticker'],
            provider_security_id='SYNTHETIC_PROVIDER:'+iid,
            asset_class='ETF' if iid==IDS['SPY'] else 'INDEX' if iid==IDS['^IXIC'] else 'EQUITY',
            market='US', mic='ARCX' if iid==IDS['SPY'] else 'XNAS' if iid==IDS['^IXIC'] else 'XNYS',
            timezone='America/New_York', calendar='XNYS',
            currency='USD', adjustment_basis='SPLIT_ADJUSTED',
            volume_basis='SPLIT_ADJUSTED', halted_sessions=[])
        if identity is None:
            self.bind_identity_evidence(ident)
        self.data_spec['files'] = [f for f in self.data_spec['files'] if f['instrument']['instrument_id'] != iid]
        self.data_spec['files'].append(dict(storage='archive', format='jsonl', sha256=h,
            bytes=len(raw), rows=len(rows), start=rows[0]['session_date'],
            end=rows[-1]['session_date'], columns=dict(access.PRICE_COLUMNS), instrument=ident))
        self.transport.objects[f'{access.PREFIX_V1}/objects/{h}'] = raw

    def identity(self, iid=IDS['TEST']):
        return next(f['instrument'] for f in self.data_spec['files'] if f['instrument']['instrument_id']==iid)

    def bind_identity_evidence(self, ident, **overrides):
        evidence={key:ident[key] for key in ('instrument_id','provider_security_id','ticker',
            'asset_class','market','mic','calendar','timezone','currency')}
        evidence.update(schema='ohlcv-security-identity-evidence-v1', provider='SYNTHETIC_FIXTURE',
            valid_from=DAYS[0], valid_through=SESSION, available_from='2026-10-13T21:00:00Z',
            collected_at='2026-10-13T22:00:00Z', expires_at='2026-10-20T00:00:00Z')
        evidence.update(overrides)
        raw=encoded(evidence); h=digest(raw)
        self.transport.objects[f'{access.PREFIX_V1}/objects/{h}']=raw
        if h not in self.data_spec['source']['raw_source_sha256']:
            self.data_spec['source']['raw_source_sha256'].append(h)
        ident['identity_evidence_sha256']=h
        return evidence

    def generation(self):
        raw = encoded(self.manifest)
        h = digest(raw)
        self.transport.objects[f'{access.PREFIX_V1}/generations/{h}'] = raw
        return h

    def call(self, **kw):
        opts = dict(security_id=IDS['TEST'], session=SESSION, as_of=ASOF,
            benchmark_ids={'SPY': IDS['SPY'], 'NASDAQ_COMPOSITE': IDS['^IXIC']})
        generation = self.generation()
        raw = copy.deepcopy(self.manifest)
        for f in raw['datasets'][0]['files']:
            f['instrument']['adjustment_basis']='RAW';f['instrument']['volume_basis']='RAW'
        rawbytes = encoded(raw); rawgen = digest(rawbytes)
        self.transport.objects[f'{access.PREFIX_V1}/generations/{rawgen}'] = rawbytes
        opts['raw_generation'] = rawgen
        opts.update(kw)
        return target.research_feature_snapshot(self.reader, generation, **opts)

    def assert_blocked(self, result, code):
        self.assertTrue(all(v is None for v in result['features'].values()))
        self.assertTrue(all(v==code for v in result['blocker'].values()), result['blocker'])

    def frame(self, iid):
        f = pd.DataFrame(self.rows[iid]).rename(columns={'session_date':'session'})
        return f[['session','open','high','low','close','volume']]

    def test_existing_independent_oracle_parity(self):
        p=self.frame(IDS['TEST']); b=self.frame(IDS['SPY'])
        ref=oracle.compute_preview(p,p,b,DAYS,as_of=SESSION,
            source_description='SYNTHETIC_ONLY',split_volume_comparable=True)['features']
        o=self.call()['features']
        names=[f'ret_{n}s' for n in target.TECH_HORIZONS]+[f'rs_log_spy_{n}s' for n in target.TECH_HORIZONS]
        names += [f'sma_{n}s' for n in target.TECH_MAS]
        names += ['rvol_20s_prior_only','volume_z_20s_prior_only','atr_14s_pct',
                  'realized_volatility_20s_over_63s','prior_high_252s','breakout_prior_high_252s']
        for k in names:
            with self.subTest(feature=k):
                if type(ref[k]) is bool:self.assertEqual(o[k],ref[k])
                else:self.assertAlmostEqual(o[k],ref[k],places=11)

    def test_exact_five_horizon_rs_changes_and_composite_price_relative(self):
        o=self.call()['features']; c=[r['close'] for r in self.rows[IDS['TEST']]]
        b=[r['close'] for r in self.rows[IDS['SPY']]]; q=[r['close'] for r in self.rows[IDS['^IXIC']]]
        for n in target.TECH_HORIZONS:
            current=math.log(c[-1]/c[-1-n])-math.log(b[-1]/b[-1-n])
            previous=math.log(c[-1-n]/c[-1-2*n])-math.log(b[-1-n]/b[-1-2*n])
            self.assertAlmostEqual(o[f'rs_log_spy_change_{n}s'],current-previous,places=12)
            self.assertAlmostEqual(o[f'nasdaq_composite_price_relative_{n}s'],(c[-1]/c[-1-n])/(q[-1]/q[-1-n])-1,places=12)

    def test_ma_slopes_scalar_ols_oracle(self):
        o=self.call()['features']; c=[r['close'] for r in self.rows[IDS['TEST']]]
        for n in target.TECH_MAS:
            y=[sum(c[len(c)-n-4+i:len(c)-4+i])/n for i in range(5)]
            mean=sum(y)/5; slope=sum((i-2)*(v-mean) for i,v in enumerate(y))/10
            self.assertAlmostEqual(o[f'sma_{n}s_slope_pct_per_session_5'],slope/mean*100,places=11)

    def test_obv_and_accumulation_scalar_oracle(self):
        o=self.call(); rows=self.rows[IDS['TEST']]; sums=[0.0]
        for a,b in zip(rows,rows[1:]):sums.append(sums[-1]+(1 if b['close']>a['close'] else -1 if b['close']<a['close'] else 0)*b['volume'])
        self.assertEqual(o['features']['obv_anchored'],sums[-1])
        self.assertEqual(o['features']['obv_change_20s'],sums[-1]-sums[-21])
        self.assertEqual(o['obv_anchor_session'],DAYS[0])
        self.assertIsInstance(o['features']['accumulation_day_proxy'],bool)

    def test_prior_20_60_252_high_excludes_today(self):
        r=self.rows[IDS['TEST']][-1];r['high']=1000;r['close']=999;r['open']=998;r['low']=997
        self.add_file(IDS['TEST']);o=self.call()['features']
        for n in target.TECH_BREAKOUTS:
            self.assertEqual(o[f'prior_high_{n}s'],max(x['high'] for x in self.rows[IDS['TEST']][-n-1:-1]))
            self.assertTrue(o[f'breakout_prior_high_{n}s'])

    def test_volume_baseline_never_includes_current_bar(self):
        self.rows[IDS['TEST']][-1]['volume']=12345;self.add_file(IDS['TEST'])
        hist=[r['volume'] for r in self.rows[IDS['TEST']][-21:-1]];mean=sum(hist)/20
        sd=math.sqrt(sum((v-mean)**2 for v in hist)/20)
        o=self.call()['features']
        self.assertAlmostEqual(o['rvol_20s_prior_only'],12345/mean)
        self.assertAlmostEqual(o['volume_z_20s_prior_only'],(12345-mean)/sd)

    def test_zero_variance_is_null_not_neutral(self):
        for r in self.rows[IDS['TEST']]:r['volume']=1000.
        self.rows[IDS['TEST']][-1]['volume']=2000.;self.add_file(IDS['TEST'])
        o=self.call()['features'];self.assertEqual(o['rvol_20s_prior_only'],2)
        self.assertIsNone(o['volume_z_20s_prior_only']);self.assertIsNone(o['accumulation_day_proxy'])

    def test_missing_benchmark_price_features_survive(self):
        o=self.call(benchmark_ids={})
        self.assertIsNotNone(o['features']['ret_20s'])
        self.assertIsNone(o['features']['rs_log_spy_20s'])
        self.assertEqual(o['blocker']['rs_log_spy_20s'],'BENCHMARK_NOT_PROVIDED')

    def test_qqq_never_substitutes_composite_or_spy(self):
        self.identity(IDS['^IXIC'])['ticker']='QQQ'
        for r in self.rows[IDS['^IXIC']]:r['ticker']='QQQ'
        self.add_file(IDS['^IXIC'],identity=self.identity(IDS['^IXIC']))
        o=self.call()
        self.assertIsNone(o['features']['nasdaq_composite_price_relative_20s'])
        self.assertIsNotNone(o['features']['rs_log_spy_20s'])
        o=self.call(benchmark_ids={'SPY':IDS['^IXIC']})
        self.assertIsNone(o['features']['rs_log_spy_20s'])

    def test_benchmark_basis_mismatch_only_blocks_rs(self):
        self.identity(IDS['SPY'])['adjustment_basis']='RAW'
        o=self.call();self.assertIsNone(o['features']['rs_log_spy_5s'])
        self.assertEqual(o['blocker']['rs_log_spy_5s'],'BENCHMARK_ADJUSTMENT_MISMATCH')
        self.assertIsNotNone(o['features']['ret_5s'])

    def test_benchmark_missing_internal_session_no_inner_join_compression(self):
        del self.rows[IDS['SPY']][-8];self.add_file(IDS['SPY'])
        o=self.call()['features']
        self.assertIsNotNone(o['rs_log_spy_5s']);self.assertIsNone(o['rs_log_spy_20s'])
        self.assertIsNone(o['rs_log_spy_change_5s'])

    def test_stock_gap_preserves_only_sufficient_trailing_windows(self):
        del self.rows[IDS['TEST']][-30];self.add_file(IDS['TEST'])
        o=self.call();self.assertIsNotNone(o['features']['ret_20s'])
        self.assertIsNone(o['features']['ret_60s']);self.assertIsNone(o['features']['sma_50s'])
        self.assertEqual(o['coverage']['consecutive_tail_rows'],29)

    def test_short_ipo_history_no_padding(self):
        self.rows[IDS['TEST']]=self.rows[IDS['TEST']][-20:];self.add_file(IDS['TEST'])
        o=self.call()['features'];self.assertIsNotNone(o['sma_20s'])
        self.assertIsNone(o['ret_20s']);self.assertIsNone(o['rvol_20s_prior_only'])
        self.assertIsNone(o['sma_200s'])

    def test_prelisting_session_refuses(self):
        self.rows[IDS['TEST']]=self.rows[IDS['TEST']][-20:];self.add_file(IDS['TEST'])
        self.assert_blocked(self.call(session=DAYS[-21]),'IPO_OR_PRICE_HISTORY_NOT_STARTED')

    def test_unknown_volume_basis_blocks_volume_only(self):
        del self.identity()['volume_basis'];o=self.call()['features']
        for key in ['rvol_20s_prior_only','volume_z_20s_prior_only','obv_anchored','obv_change_20s','accumulation_day_proxy','distribution_day_proxy']:
            self.assertIsNone(o[key])
        self.assertIsNotNone(o['ret_20s'])

    def test_unknown_halt_coverage_blocks_all(self):
        del self.identity()['halted_sessions'];self.assert_blocked(self.call(),'HALT_COVERAGE_UNKNOWN')

    def test_suspension_at_target_session_blocks_all(self):
        self.identity()['halted_sessions']=[SESSION];self.assert_blocked(self.call(),'TRADING_SUSPENDED')

    def test_historical_suspension_is_a_window_gap(self):
        self.identity()['halted_sessions']=[DAYS[-10]];o=self.call()['features']
        self.assertIsNotNone(o['ret_5s']);self.assertIsNone(o['ret_20s'])

    def test_raw_or_total_return_cannot_masquerade_as_split_adjusted(self):
        for basis in ['RAW','TOTAL_RETURN']:
            self.identity()['adjustment_basis']=basis
            self.assert_blocked(self.call(),'FEATURE_REQUIRES_SPLIT_ADJUSTED_OHLC')

    def test_unknown_source_clock_is_not_replaced_by_asof(self):
        del self.data_spec['source']['available_from'];self.assert_blocked(self.call(),'INVALID_AVAILABILITY')

    def test_pit_proxy_never_admits_rs(self):
        self.data_spec['source']['pit_status']='PIT_PROXY';o=self.call()
        self.assertIsNone(o['features']['rs_log_spy_20s'])
        self.assertEqual(o['blocker']['rs_log_spy_20s'],'BENCHMARK_PIT_UNVERIFIED')
        self.assertIsNotNone(o['features']['ret_20s'])

    def test_future_source_rejected(self):
        self.data_spec['source']['collected_at']='2026-10-14T01:00:00Z'
        self.assert_blocked(self.call(),'FUTURE_SOURCE')

    def test_premarket_uncompleted_session_refused(self):
        with self.assertRaisesRegex(access.ContractError,'FEATURE_SESSION_NOT_COMPLETED'):
            self.call(as_of=SESSION+'T19:59:59Z')

    def test_holiday_or_weekend_refused(self):
        for session in ['2026-10-10','2026-12-25']:
            with self.assertRaisesRegex(access.ContractError,'FEATURE_SESSION_NOT_COMPLETED'):
                self.call(session=session)

    def test_naive_or_future_cutoff_refused(self):
        for value in ['2026-10-14','2099-01-01T00:00:00Z']:
            with self.assertRaises(access.ContractError):self.call(as_of=value)

    def test_earlier_session_never_consumes_later_bar(self):
        before=self.call(session=DAYS[-2])['features']
        r=self.rows[IDS['TEST']][-1]
        r.update(close=10000.,open=9999.,high=10001.,low=9998.,volume=99999.)
        self.add_file(IDS['TEST'])
        after=self.call(session=DAYS[-2])['features']
        self.assertEqual(before,after)

    def test_genuine_zero_volume_remains_zero(self):
        self.rows[IDS['TEST']][-1]['volume']=0.;self.add_file(IDS['TEST'])
        o=self.call()['features'];self.assertEqual(o['rvol_20s_prior_only'],0)
        self.assertEqual(o['raw_close_x_raw_volume'],0)

    def test_zero_range_close_location_is_null(self):
        r=self.rows[IDS['TEST']][-1]
        for k in ('open','high','low'):r[k]=r['close']
        self.add_file(IDS['TEST']);o=self.call()['features']
        self.assertIsNone(o['close_location_in_bar'])
        self.assertIsNone(o['accumulation_day_proxy'])

    def test_bad_hash_and_changed_bytes_refused(self):
        f=self.data_spec['files'][0];self.transport.objects[f'{access.PREFIX_V1}/objects/{f["sha256"]}']+=b' '
        self.assert_blocked(self.call(),'HASH_MISMATCH')

    def test_bad_values_never_become_zero(self):
        for value in [0.,-2.,True]:
            with self.subTest(value=value):
                old=self.rows[IDS['TEST']][-1]['close'];self.rows[IDS['TEST']][-1]['close']=value
                self.add_file(IDS['TEST']);self.assert_blocked(self.call(),'INVALID_PRICE_VALUE')
                self.rows[IDS['TEST']][-1]['close']=old

    def test_duplicate_session_refused(self):
        self.rows[IDS['TEST']].append(copy.deepcopy(self.rows[IDS['TEST']][-1]));self.add_file(IDS['TEST'])
        self.assert_blocked(self.call(),'DUPLICATE_SESSION')

    def test_raw_turnover_has_separate_bound_lineage(self):
        adjusted=self.generation();raw=copy.deepcopy(self.manifest)
        for f in raw['datasets'][0]['files']:
            f['instrument']['adjustment_basis']='RAW';f['instrument']['volume_basis']='RAW'
        data=encoded(raw);rawgen=digest(data);self.transport.objects[f'{access.PREFIX_V1}/generations/{rawgen}']=data
        o=target.research_feature_snapshot(self.reader,adjusted,security_id=IDS['TEST'],
            session=SESSION,as_of=ASOF,raw_generation=rawgen)
        r=self.rows[IDS['TEST']][-1]
        self.assertEqual(o['features']['raw_close_x_raw_volume'],r['close']*r['volume'])
        self.assertEqual(o['raw_ref']['generation'],rawgen)
        raw['datasets'][0]['source']['source_receipt_sha256']='9'*64
        data=encoded(raw);rawgen=digest(data);self.transport.objects[f'{access.PREFIX_V1}/generations/{rawgen}']=data
        o=target.research_feature_snapshot(self.reader,adjusted,security_id=IDS['TEST'],
            session=SESSION,as_of=ASOF,raw_generation=rawgen)
        self.assertIsNone(o['features']['raw_close_x_raw_volume'])
        self.assertEqual(o['blocker']['raw_close_x_raw_volume'],'RAW_SOURCE_LINEAGE_MISMATCH')

    def test_no_raw_turnover_from_adjusted_close_times_volume(self):
        o=self.call(raw_generation=None);self.assertIsNone(o['features']['raw_close_x_raw_volume'])
        self.assertEqual(o['blocker']['raw_close_x_raw_volume'],'RAW_GENERATION_NOT_PROVIDED')

    def test_split_price_volume_inverse_relation(self):
        for r in self.rows[IDS['TEST']]:r['volume']*=2
        self.add_file(IDS['TEST']);adjusted=self.generation()
        for row in self.rows[IDS['TEST']][:-10]:
            for k in ('open','high','low','close'):row[k]*=2
            row['volume']/=2
        self.add_file(IDS['TEST']);raw=copy.deepcopy(self.manifest)
        for f in raw['datasets'][0]['files']:
            f['instrument']['adjustment_basis']='RAW';f['instrument']['volume_basis']='RAW'
        rawbytes=encoded(raw);rawgen=digest(rawbytes)
        self.transport.objects[f'{access.PREFIX_V1}/generations/{rawgen}']=rawbytes
        o=target.research_feature_snapshot(self.reader,adjusted,security_id=IDS['TEST'],
            session=SESSION,as_of=ASOF,raw_generation=rawgen)
        self.assertIsNotNone(o['features']['rvol_20s_prior_only'])
        self.assertTrue(o['coverage']['raw_split_volume_relation_verified'])

    def test_fractional_raw_shares_refused(self):
        adjusted=self.generation();self.rows[IDS['TEST']][10]['volume']=1000.5
        self.add_file(IDS['TEST']);raw=copy.deepcopy(self.manifest)
        for f in raw['datasets'][0]['files']:
            f['instrument']['adjustment_basis']='RAW';f['instrument']['volume_basis']='RAW'
        rawbytes=encoded(raw);rawgen=digest(rawbytes)
        self.transport.objects[f'{access.PREFIX_V1}/generations/{rawgen}']=rawbytes
        o=target.research_feature_snapshot(self.reader,adjusted,security_id=IDS['TEST'],
            session=SESSION,as_of=ASOF,raw_generation=rawgen)
        self.assertIsNone(o['features']['rvol_20s_prior_only'])
        self.assertEqual(o['blocker']['raw_close_x_raw_volume'],'RAW_SHARE_VOLUME_NOT_INTEGER')

    def test_mismatched_raw_split_ohlc_blocks_entire_snapshot(self):
        adjusted=self.generation()
        self.rows[IDS['TEST']][-8]['high']+=1
        self.add_file(IDS['TEST']);raw=copy.deepcopy(self.manifest)
        for f in raw['datasets'][0]['files']:
            f['instrument']['adjustment_basis']='RAW';f['instrument']['volume_basis']='RAW'
        rawbytes=encoded(raw);rawgen=digest(rawbytes)
        self.transport.objects[f'{access.PREFIX_V1}/generations/{rawgen}']=rawbytes
        o=target.research_feature_snapshot(self.reader,adjusted,security_id=IDS['TEST'],
            session=SESSION,as_of=ASOF,raw_generation=rawgen)
        self.assert_blocked(o,'RAW_SPLIT_PRICE_BASIS_MISMATCH')

    def test_late_refusal_preserves_feature_coverage_totals(self):
        adjusted=self.generation()
        self.rows[IDS['TEST']][-8]['high']+=1
        self.add_file(IDS['TEST']);raw=copy.deepcopy(self.manifest)
        for f in raw['datasets'][0]['files']:
            f['instrument']['adjustment_basis']='RAW';f['instrument']['volume_basis']='RAW'
        rawbytes=encoded(raw);rawgen=digest(rawbytes)
        self.transport.objects[f'{access.PREFIX_V1}/generations/{rawgen}']=rawbytes
        o=target.research_feature_snapshot(self.reader,adjusted,security_id=IDS['TEST'],
            session=SESSION,as_of=ASOF,raw_generation=rawgen)
        self.assert_blocked(o,'RAW_SPLIT_PRICE_BASIS_MISMATCH')
        self.assertEqual(o['coverage']['features_ready'],0)
        self.assertEqual(o['coverage']['features_total'],len(target.TECH_FEATURE_NAMES))

    def test_mismatched_split_volume_is_not_institutional_activity(self):
        adjusted=self.generation()
        # Rebind a distinct valid raw stream with a price factor mismatch,
        # keeping hashes/metadata coherent: arithmetic, not hash-only, must fail.
        for r in self.rows[IDS['TEST']][:-10]:
            for k in ('open','high','low','close'):r[k]*=2
        self.add_file(IDS['TEST'])
        raw=copy.deepcopy(self.manifest)
        for f in raw['datasets'][0]['files']:
            f['instrument']['adjustment_basis']='RAW';f['instrument']['volume_basis']='RAW'
        rawbytes=encoded(raw);rawgen=digest(rawbytes)
        self.transport.objects[f'{access.PREFIX_V1}/generations/{rawgen}']=rawbytes
        o=target.research_feature_snapshot(self.reader,adjusted,security_id=IDS['TEST'],
            session=SESSION,as_of=ASOF,raw_generation=rawgen)
        self.assertIsNone(o['features']['rvol_20s_prior_only'])
        self.assertIsNone(o['features']['obv_anchored'])
        self.assertEqual(o['blocker']['rvol_20s_prior_only'],'RAW_SPLIT_OHLCV_BASIS_MISMATCH')
        self.assertIsNotNone(o['features']['raw_close_x_raw_volume'])

    def test_spy_wrong_mic_refuses_rs_and_preserves_stock_features(self):
        ident=self.identity(IDS['SPY']); ident['mic']='OTCM'
        self.bind_identity_evidence(ident)
        o=self.call()
        self.assertIsNone(o['features']['rs_log_spy_20s'])
        self.assertEqual(o['blocker']['rs_log_spy_20s'],'FEATURE_MIC_CALENDAR_UNSUPPORTED')
        self.assertIsNotNone(o['features']['ret_20s'])

    def test_spy_index_is_not_an_etf_even_with_rebound_source(self):
        ident=self.identity(IDS['SPY']); ident['asset_class']='INDEX'
        self.bind_identity_evidence(ident)
        o=self.call()
        self.assertIsNone(o['features']['rs_log_spy_20s'])
        self.assertEqual(o['blocker']['rs_log_spy_20s'],'BENCHMARK_SECURITY_TYPE_MISMATCH')
        self.assertIsNotNone(o['features']['ret_20s'])

    def test_subject_mic_calendar_conflict_refuses_all(self):
        ident=self.identity(); ident['mic']='OTCM'
        self.bind_identity_evidence(ident)
        self.assert_blocked(self.call(),'FEATURE_MIC_CALENDAR_UNSUPPORTED')

    def test_ticker_and_asset_class_cannot_replace_source_identity(self):
        ident=self.identity(); h=ident.pop('identity_evidence_sha256')
        self.assert_blocked(self.call(),'INVALID_SHA256')
        ident['identity_evidence_sha256']=h
        self.data_spec['source']['raw_source_sha256'].remove(h)
        self.assert_blocked(self.call(),'FEATURE_IDENTITY_NOT_SOURCE_BOUND')

    def test_source_identity_hash_provider_id_and_role_must_match(self):
        ident=self.identity(); h=ident['identity_evidence_sha256']
        raw=self.transport.objects[f'{access.PREFIX_V1}/objects/{h}']
        self.transport.objects[f'{access.PREFIX_V1}/objects/{h}']=raw+b' '
        self.assert_blocked(self.call(),'HASH_MISMATCH')
        self.transport.objects[f'{access.PREFIX_V1}/objects/{h}']=raw
        for field,bad in (('provider_security_id','OTHER'),('asset_class','ETF'),('mic','XNAS')):
            old=ident[field]; ident[field]=bad
            self.assert_blocked(self.call(),'FEATURE_IDENTITY_SOURCE_MISMATCH'); ident[field]=old
        self.bind_identity_evidence(ident,provider='OTHER_PROVIDER')
        self.assert_blocked(self.call(),'FEATURE_IDENTITY_PROVIDER')

    def test_identity_effective_window_and_original_clocks(self):
        ident=self.identity()
        for fields,code in ((dict(valid_from=DAYS[1]),'FEATURE_IDENTITY_EFFECTIVE_WINDOW'),
            (dict(valid_through=DAYS[-2]),'FEATURE_IDENTITY_EFFECTIVE_WINDOW'),
            (dict(collected_at='2026-10-14T01:00:00Z'),'FEATURE_IDENTITY_CLOCK'),
            (dict(expires_at='2026-10-13T23:59:59Z'),'FEATURE_IDENTITY_CLOCK')):
            self.bind_identity_evidence(ident,**fields)
            self.assert_blocked(self.call(),code)

    def test_spy_arcx_and_composite_xnas_fixture_roles_are_source_bound(self):
        o=self.call()
        self.assertIsNotNone(o['features']['rs_log_spy_20s'])
        self.assertIsNotNone(o['features']['nasdaq_composite_price_relative_20s'])
        spy=o['benchmark_ref']['SPY']; comp=o['benchmark_ref']['NASDAQ_COMPOSITE']
        self.assertEqual((spy['mic'],spy['asset_class']),('ARCX','ETF'))
        self.assertEqual((comp['mic'],comp['asset_class']),('XNAS','INDEX'))
        self.assertIn(spy['identity_evidence_sha256'],o['source_sha'])
        self.assertEqual(spy['provider_security_id'],self.identity(IDS['SPY'])['provider_security_id'])
        self.assertFalse(o['source_admitted']); self.assertFalse(o['historical_pit_certified'])

    def test_composite_etf_and_qqq_cannot_masquerade_as_index(self):
        ident=self.identity(IDS['^IXIC']); ident['asset_class']='ETF'
        self.bind_identity_evidence(ident)
        o=self.call(); self.assertIsNone(o['features']['nasdaq_composite_price_relative_20s'])
        self.assertEqual(o['blocker']['nasdaq_composite_price_relative_20s'],'BENCHMARK_SECURITY_TYPE_MISMATCH')
        ident['ticker']='QQQ'
        for row in self.rows[IDS['^IXIC']]:row['ticker']='QQQ'
        self.bind_identity_evidence(ident); self.add_file(IDS['^IXIC'],identity=ident)
        o=self.call(); self.assertIsNone(o['features']['nasdaq_composite_price_relative_20s'])
        self.assertEqual(o['blocker']['nasdaq_composite_price_relative_20s'],'BENCHMARK_IDENTITY_MISMATCH')

    def test_arcx_original_bar_clock_must_follow_completed_close(self):
        self.rows[IDS['SPY']][-1]['available_from']=SESSION+'T19:59:59Z'
        self.add_file(IDS['SPY'])
        # Scheduled ARCX now reaches Reader's existing global clock gate.
        # Optional absence is local; a false availability clock is not.
        self.assert_blocked(self.call(),'PRE_CLOSE_AVAILABLE_FROM')

    def test_raw_split_provider_identity_must_remain_identical(self):
        original=copy.deepcopy(self.manifest); ident=self.identity()
        ident['provider_security_id']='DIFFERENT_PROVIDER_SECURITY'
        self.bind_identity_evidence(ident)
        raw=copy.deepcopy(self.manifest)
        original['datasets'][0]['source']['raw_source_sha256']=copy.deepcopy(raw['datasets'][0]['source']['raw_source_sha256'])
        data=encoded(original); adjusted=digest(data)
        self.transport.objects[f'{access.PREFIX_V1}/generations/{adjusted}']=data
        for file in raw['datasets'][0]['files']:
            file['instrument']['adjustment_basis']='RAW'; file['instrument']['volume_basis']='RAW'
        data=encoded(raw); rawgen=digest(data)
        self.transport.objects[f'{access.PREFIX_V1}/generations/{rawgen}']=data
        o=target.research_feature_snapshot(self.reader,adjusted,security_id=IDS['TEST'],
            session=SESSION,as_of=ASOF,raw_generation=rawgen)
        self.assertIsNone(o['features']['raw_close_x_raw_volume'])
        self.assertIsNotNone(o['features']['ret_20s'])
        self.assertEqual(o['blocker']['raw_close_x_raw_volume'],'RAW_SOURCE_LINEAGE_MISMATCH')

    def test_every_output_is_provenance_bound_and_non_authoritative(self):
        o=self.call()
        self.assertEqual(o['security_id'],IDS['TEST']);self.assertEqual(o['session'],SESSION)
        self.assertEqual(o['adjustment_basis'],'SPLIT_ADJUSTED')
        self.assertEqual(o['benchmark_ref']['SPY']['generation'],o['source_generation'])
        self.assertEqual(set(o['features']),set(o['feature_status']))
        self.assertEqual(set(o['blocker']),{k for k,v in o['features'].items() if v is None})
        for k in ['source_admitted','historical_pit_certified','eligible_for_selector','ranking_allowed','ER_allowed','portfolio_allowed','orders_generated']:
            self.assertIs(o[k],False)
        self.assertEqual(o['snapshot_sha256'],digest(encoded({k:v for k,v in o.items() if k!='snapshot_sha256'})))


    def test_component_missing_benchmark_preserves_subject(self):
        item=next(f for f in self.data_spec['files'] if f['instrument']['instrument_id']==IDS['SPY'])
        del self.transport.objects[f"{access.PREFIX_V1}/objects/{item['sha256']}"]
        o=self.call(raw_generation=None)
        self.assertIsNotNone(o['features']['ret_20s'])
        self.assertIsNone(o['features']['rs_log_spy_20s'])
        self.assertEqual(o['blocker']['rs_log_spy_20s'],'ARCHIVE_UNAVAILABLE')
        self.assertFalse(o['source_ref']['whole_generation_verified'])
        self.assertEqual(o['source_ref']['validation_scope'],'REQUESTED_COMPONENTS_ONLY')

    def test_component_invalid_benchmark_preserves_subject(self):
        self.rows[IDS['SPY']][-1]['close']=-1
        self.add_file(IDS['SPY'])
        o=self.call(raw_generation=None)
        self.assertIsNotNone(o['features']['ret_20s'])
        self.assertEqual(o['blocker']['rs_log_spy_20s'],'INVALID_PRICE_VALUE')

    def test_component_global_benchmark_hash_failure_aborts(self):
        item=next(f for f in self.data_spec['files'] if f['instrument']['instrument_id']==IDS['SPY'])
        self.transport.objects[f"{access.PREFIX_V1}/objects/{item['sha256']}"]+=b' '
        self.assert_blocked(self.call(raw_generation=None),'HASH_MISMATCH')

    def test_component_global_benchmark_clock_failure_aborts(self):
        self.rows[IDS['SPY']][-1]['available_from']='2026-10-21T00:00:00Z'
        self.add_file(IDS['SPY'])
        self.assert_blocked(self.call(raw_generation=None),'FUTURE_AVAILABLE_FROM')

    def test_component_reads_once_per_selected_partition(self):
        reads=[]
        original=self.transport.read
        def counted(path):
            reads.append(path)
            return original(path)
        with patch.object(self.transport,'read',counted), patch.object(self.reader,'read',side_effect=AssertionError('LEGACY_WHOLE_READ')), patch.object(self.reader,'_rows',wraps=self.reader._rows) as decode_rows:
            o=self.call()
        self.assertIsNotNone(o['features']['ret_20s'])
        self.assertEqual(decode_rows.call_count,4)  # adjusted subject+2 benchmarks, RAW subject
        price_hashes={f['sha256'] for f in self.data_spec['files']}
        price_reads=[p for p in reads if p.rsplit('/',1)[-1] in price_hashes]
        self.assertEqual(len(price_reads),4)
        self.assertEqual(price_reads.count(next(p for p in price_reads if p.endswith(next(f['sha256'] for f in self.data_spec['files'] if f['instrument']['instrument_id']==IDS['SPY'])))),1)

    def test_component_heterogeneous_starts_preserved(self):
        self.rows[IDS['SPY']]=self.rows[IDS['SPY']][-12:]
        self.add_file(IDS['SPY'])
        o=self.call(raw_generation=None)
        self.assertIsNotNone(o['features']['ret_20s'])
        self.assertIsNone(o['features']['rs_log_spy_20s'])
        self.assertIsNotNone(o['features']['rs_log_spy_5s'])
        self.assertNotEqual(o['source_ref']['row_set_sha256'],o['benchmark_ref']['SPY']['row_set_sha256'])

    def test_component_raw_global_hash_failure_aborts(self):
        adjusted=self.generation()
        raw=copy.deepcopy(self.manifest)
        for f in raw['datasets'][0]['files']:
            f['instrument']['adjustment_basis']='RAW'; f['instrument']['volume_basis']='RAW'
        rawbytes=encoded(raw);rawgen=digest(rawbytes)
        self.transport.objects[f'{access.PREFIX_V1}/generations/{rawgen}']=rawbytes+b' '
        o=target.research_feature_snapshot(self.reader,adjusted,security_id=IDS['TEST'],session=SESSION,as_of=ASOF,raw_generation=rawgen)
        self.assert_blocked(o,'HASH_MISMATCH')



    def test_component_role_aliases_share_one_required_read_without_losing_roles(self):
        with patch.object(self.reader,'read_components',wraps=self.reader.read_components) as read:
            o=self.call(security_id=IDS['SPY'],raw_generation=None,
                benchmark_ids={'SPY':IDS['SPY'],'NASDAQ_COMPOSITE':IDS['SPY']})
        self.assertEqual(read.call_count,1)
        requests=read.call_args.kwargs['components']
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0]['instrument_id'],IDS['SPY'])
        self.assertFalse(requests[0]['optional'])
        self.assertIsNotNone(o['features']['ret_20s'])
        self.assertAlmostEqual(o['features']['rs_log_spy_20s'],0)
        self.assertIsNone(o['features']['nasdaq_composite_price_relative_20s'])
        self.assertEqual(o['blocker']['nasdaq_composite_price_relative_20s'],
                         'BENCHMARK_IDENTITY_MISMATCH')

    def test_component_absent_optional_inventory_reaches_public_reader(self):
        self.data_spec['files']=[f for f in self.data_spec['files']
                                if f['instrument']['instrument_id']!=IDS['SPY']]
        with patch.object(self.reader,'read_components',wraps=self.reader.read_components) as read:
            o=self.call(raw_generation=None)
        self.assertEqual(read.call_count,1)
        request=next(r for r in read.call_args.kwargs['components'] if r['instrument_id']==IDS['SPY'])
        self.assertTrue(request['optional'])
        self.assertEqual((request['required_start'],request['required_end']),(SESSION,SESSION))
        self.assertIsNotNone(o['features']['ret_20s'])
        self.assertEqual(o['blocker']['rs_log_spy_20s'],'MISSING_INSTRUMENT')

    def test_component_explicit_windows_keep_OBV_anchor_and_exclude_future_partition(self):
        future=copy.deepcopy(next(f for f in self.data_spec['files']
                                  if f['instrument']['instrument_id']==IDS['TEST']))
        row={**self.rows[IDS['TEST']][-1], 'session_date':'2026-10-15',
             'available_from':'2026-10-15T21:05:00Z'}
        raw=encoded(row);h=digest(raw)
        future.update(sha256=h,bytes=len(raw),rows=1,start='2026-10-15',end='2026-10-15')
        self.data_spec['files'].append(future)
        self.transport.objects[f'{access.PREFIX_V1}/objects/{h}']=raw
        batches=[];reads=[];original=self.reader.read_components;transport_read=self.transport.read
        def recorded(*args,**kwargs):
            batch=original(*args,**kwargs);batches.append((kwargs,batch));return batch
        def counted(path):
            reads.append(path);return transport_read(path)
        with patch.object(self.reader,'read_components',recorded),patch.object(self.transport,'read',counted):
            o=self.call()
        self.assertEqual(len(batches),2)
        split_request,split_batch=batches[0]
        subject=next(r for r in split_request['components'] if r['instrument_id']==IDS['TEST'])
        self.assertEqual((subject['required_start'],subject['required_end']),(DAYS[0],SESSION))
        self.assertEqual(o['obv_anchor_session'],DAYS[0])
        rows=self.rows[IDS['TEST']]
        expected=sum((1 if b['close']>a['close'] else -1 if b['close']<a['close'] else 0)*b['volume']
                     for a,b in zip(rows,rows[1:]))
        self.assertEqual(o['features']['obv_anchored'],expected)
        self.assertNotIn(f'{access.PREFIX_V1}/objects/{h}',reads)
        self.assertIn(h,split_batch.receipt['unverified_file_sha256'])
        self.assertFalse(split_batch.receipt['whole_generation_verified'])

    def test_component_global_identity_and_resource_failures_never_become_optional(self):
        self.rows[IDS['SPY']][-1]['ticker']='WRONG'
        self.add_file(IDS['SPY'])
        self.assert_blocked(self.call(raw_generation=None),'ROW_IDENTITY')
        self.rows[IDS['SPY']][-1]['ticker']='SPY'
        self.add_file(IDS['SPY'])
        with patch.object(access,'MAX_GENERATION_ROWS',100):
            self.assert_blocked(self.call(raw_generation=None),'BLOCKED_GENERATION_ROWS')

    def _identity_proof_fixture(self):
        for iid in IDS.values():
            self.rows[iid]=self.rows[iid][-21:]
            self.add_file(iid)

    def test_component_identity_proof_hash_failure_is_global(self):
        self._identity_proof_fixture()
        for iid in (IDS['SPY'], IDS['TEST']):
            with self.subTest(instrument=iid):
                h=self.identity(iid)['identity_evidence_sha256']
                path=f'{access.PREFIX_V1}/objects/{h}'
                original=self.transport.objects[path]
                self.transport.objects[path]=original+b' '
                try:
                    self.assert_blocked(self.call(raw_generation=None),'HASH_MISMATCH')
                finally:
                    self.transport.objects[path]=original

    def test_component_identity_proof_expiry_is_global(self):
        self._identity_proof_fixture()
        for iid in (IDS['SPY'], IDS['TEST']):
            with self.subTest(instrument=iid):
                ident=self.identity(iid)
                original=ident['identity_evidence_sha256']
                self.bind_identity_evidence(ident,expires_at='2026-10-13T23:59:59Z')
                try:
                    self.assert_blocked(self.call(raw_generation=None),'FEATURE_IDENTITY_CLOCK')
                finally:
                    ident['identity_evidence_sha256']=original

    def test_component_proof_integrity_controls_preserve_optional_semantics(self):
        self._identity_proof_fixture()
        good=self.call(raw_generation=None)
        self.assertIsNotNone(good['features']['ret_20s'])
        self.assertIsNotNone(good['features']['rs_log_spy_20s'])
        ident=self.identity(IDS['SPY']);ident['asset_class']='INDEX'
        self.bind_identity_evidence(ident)
        role=self.call(raw_generation=None)
        self.assertIsNotNone(role['features']['ret_20s'])
        self.assertEqual(role['blocker']['rs_log_spy_20s'],'BENCHMARK_SECURITY_TYPE_MISMATCH')
        self.rows[IDS['SPY']][-1]['close']=-1
        self.add_file(IDS['SPY'])
        semantic=self.call(raw_generation=None)
        self.assertIsNotNone(semantic['features']['ret_20s'])
        self.assertEqual(semantic['blocker']['rs_log_spy_20s'],'INVALID_PRICE_VALUE')
        self.rows[IDS['SPY']][-1]['close']=self.rows[IDS['SPY']][-1]['open']+.1
        self.add_file(IDS['SPY'])
        item=next(f for f in self.data_spec['files'] if f['instrument']['instrument_id']==IDS['SPY'])
        path=f"{access.PREFIX_V1}/objects/{item['sha256']}"
        self.transport.objects[path]+=b' '
        self.assert_blocked(self.call(raw_generation=None),'HASH_MISMATCH')
        del self.transport.objects[path]
        absent=self.call(raw_generation=None)
        self.assertIsNotNone(absent['features']['ret_20s'])
        self.assertEqual(absent['blocker']['rs_log_spy_20s'],'ARCHIVE_UNAVAILABLE')

    def test_component_raw_identity_proof_hash_failure_is_global(self):
        self._identity_proof_fixture()
        h=self.identity()['identity_evidence_sha256']
        path=f'{access.PREFIX_V1}/objects/{h}'
        original=self.transport.read
        proof_reads=[]
        def changed_raw_proof(p):
            raw=original(p)
            if p==path:
                proof_reads.append(p)
                if len(proof_reads)==2:return raw+b' '
            return raw
        with patch.object(self.transport,'read',changed_raw_proof):
            self.assert_blocked(self.call(),'HASH_MISMATCH')
        self.assertEqual(len(proof_reads),2)


class BenchmarkGenerationTests(unittest.TestCase):
    """Explicit synthetic per-asset generations through the public Reader."""
    @classmethod
    def setUpClass(cls):
        cls.calendar_cache = patch.object(access, '_session_close',
            lru_cache(maxsize=2048)(access._session_close))
        cls.calendar_cache.start()
        cls.no_network = patch.object(socket.socket, 'connect',
            side_effect=AssertionError('NETWORK_NOT_ALLOWED'))
        cls.no_network.start()

    @classmethod
    def tearDownClass(cls):
        cls.no_network.stop()
        cls.calendar_cache.stop()

    def fixture(self, count=21):
        with patch(__name__+'.DAYS', DAYS[-count:]):
            case = FeatureTests('runTest'); case.setUp()
        return case

    def store(self, case, manifest):
        raw = encoded(manifest); generation = digest(raw)
        case.transport.objects[f'{access.PREFIX_V1}/generations/{generation}'] = raw
        return generation

    def separate(self, case):
        benchmark = copy.deepcopy(case.manifest)
        benchmark['source_run_id'] = 'SYNTHETIC_SEPARATE_BENCHMARK'
        benchmark['datasets'][0]['source']['source_receipt_sha256'] = digest(b'BENCHMARK_RECEIPT')
        benchmark['datasets'][0]['files'] = [f for f in benchmark['datasets'][0]['files']
            if f['instrument']['instrument_id'] != IDS['TEST']]
        case.data_spec['files'] = [f for f in case.data_spec['files']
            if f['instrument']['instrument_id'] == IDS['TEST']]
        raw = copy.deepcopy(case.manifest)
        for f in raw['datasets'][0]['files']:
            f['instrument'].update(adjustment_basis='RAW', volume_basis='RAW')
        return benchmark, self.store(case, raw)

    def call(self, case, **options):
        arguments = dict(security_id=IDS['TEST'], session=SESSION, as_of=ASOF,
            benchmark_ids={'SPY': IDS['SPY']})
        arguments.update(options)
        return target.research_feature_snapshot(case.reader, case.generation(), **arguments)

    def test_three_batches_keep_exact_arithmetic_windows_and_same_generation_receipts(self):
        case = self.fixture(510)
        before = case.call(benchmark_ids={'SPY': IDS['SPY']})
        benchmark, raw = self.separate(case)
        # The benchmark's observed window is independent of the subject window.
        item = benchmark['datasets'][0]['files'][0]
        rows = case.rows[IDS['SPY']][-501:]
        price_raw = b''.join(encoded(r) for r in rows)
        item.update(sha256=digest(price_raw), bytes=len(price_raw), rows=len(rows), start=rows[0]['session_date'])
        case.transport.objects[f'{access.PREFIX_V1}/objects/{digest(price_raw)}'] = price_raw
        gen = self.store(case, benchmark)
        with patch.object(case.reader, 'read_components', wraps=case.reader.read_components) as reads, \
             patch.object(case.reader, 'read', side_effect=AssertionError('LEGACY_WHOLE_READ')):
            after = self.call(case, raw_generation=raw, benchmark_generations={'SPY': gen})
        self.assertEqual(before['features'], after['features'])
        self.assertEqual(before['feature_status'], after['feature_status'])
        self.assertEqual(before['blocker'], after['blocker'])
        self.assertEqual(reads.call_count, 3)
        self.assertEqual([c.args[1] for c in reads.call_args_list], [case.generation(), raw, gen])
        for call in reads.call_args_list:
            self.assertEqual(call.kwargs['decision_time'], ASOF)
            self.assertEqual(call.kwargs['purpose'], 'research')
            self.assertEqual(call.kwargs['consumer_id'], 'ohlcv-technical-feature-h1')
            self.assertEqual(len(call.kwargs['components']), 1)
            self.assertEqual(call.kwargs['components'][0]['required_end'], SESSION)
        subject, companion, spy = [c.kwargs['components'][0] for c in reads.call_args_list]
        self.assertFalse(subject['optional']); self.assertTrue(companion['optional']); self.assertTrue(spy['optional'])
        self.assertEqual(subject['required_start'], DAYS[0])
        self.assertEqual(spy['required_start'], rows[0]['session_date'])
        self.assertEqual(after['obv_anchor_session'], DAYS[0])
        self.assertEqual(after['source_ref']['generation'], case.generation())
        self.assertEqual(after['raw_ref']['generation'], raw)
        self.assertEqual(after['benchmark_ref']['SPY']['generation'], gen)
        self.assertNotEqual(after['source_ref']['component_batch_receipt_sha256'],
                            after['benchmark_ref']['SPY']['component_batch_receipt_sha256'])
        self.assertEqual(after, self.call(case, raw_generation=raw, benchmark_generations={'SPY': gen}))

    def test_omitted_empty_and_explicit_same_generation_are_exactly_compatible(self):
        case = self.fixture()
        legacy = case.call()
        self.assertEqual(legacy, case.call(benchmark_generations={},
            benchmark_expected_qualification_sha256={}, benchmark_trusted_qualification_sources={}))
        with patch.object(case.reader, 'read_components', wraps=case.reader.read_components) as reads:
            explicit = case.call(benchmark_generations={
                'SPY': case.generation(), 'NASDAQ_COMPOSITE': case.generation()})
        self.assertEqual(legacy, explicit)
        self.assertEqual(reads.call_count, 2)

    def test_shared_benchmark_generation_batches_all_optional_roles_once(self):
        case = self.fixture()
        benchmark, _ = self.separate(case); gen = self.store(case, benchmark)
        with patch.object(case.reader, 'read_components', wraps=case.reader.read_components) as reads:
            result = self.call(case, benchmark_ids={'SPY': IDS['SPY'], 'NASDAQ_COMPOSITE': IDS['^IXIC']},
                benchmark_generations={'SPY': gen, 'NASDAQ_COMPOSITE': gen})
        self.assertEqual(reads.call_count, 2)
        components = reads.call_args_list[1].kwargs['components']
        self.assertEqual({r['instrument_id'] for r in components}, {IDS['SPY'], IDS['^IXIC']})
        self.assertTrue(all(r['optional'] for r in components))
        self.assertIsNotNone(result['features']['rs_log_spy_5s'])
        self.assertIsNotNone(result['features']['nasdaq_composite_price_relative_5s'])

    def test_distinct_optional_semantic_refusals_preserve_subject_and_generation(self):
        for mode, code in [('absent', 'MISSING_INSTRUMENT'), ('unavailable', 'ARCHIVE_UNAVAILABLE'),
                           ('value', 'INVALID_PRICE_VALUE'), ('role', 'BENCHMARK_SECURITY_TYPE_MISMATCH'),
                           ('basis', 'BENCHMARK_ADJUSTMENT_MISMATCH'), ('pit', 'BENCHMARK_PIT_UNVERIFIED')]:
            with self.subTest(mode=mode):
                case = self.fixture()
                if mode == 'value':
                    case.rows[IDS['SPY']][-1]['close'] = -1; case.add_file(IDS['SPY'])
                if mode == 'role':
                    case.identity(IDS['SPY'])['asset_class'] = 'INDEX'
                    case.bind_identity_evidence(case.identity(IDS['SPY']))
                if mode == 'basis':
                    case.identity(IDS['SPY'])['adjustment_basis'] = 'TOTAL_RETURN'
                benchmark, _ = self.separate(case)
                spec = benchmark['datasets'][0]
                if mode == 'absent':
                    spec['files'] = [f for f in spec['files'] if f['instrument']['instrument_id'] != IDS['SPY']]
                if mode == 'unavailable':
                    item = next(f for f in spec['files'] if f['instrument']['instrument_id'] == IDS['SPY'])
                    del case.transport.objects[f"{access.PREFIX_V1}/objects/{item['sha256']}"]
                if mode == 'pit': spec['source']['pit_status'] = 'PIT_PROXY'
                gen = self.store(case, benchmark)
                result = self.call(case, benchmark_generations={'SPY': gen})
                self.assertIsNotNone(result['features']['ret_5s'], result['blocker'])
                self.assertEqual(result['blocker']['rs_log_spy_5s'], code)
                self.assertEqual(result['benchmark_ref']['SPY']['generation'], gen)
                self.assertIsNone(result['features']['nasdaq_composite_price_relative_5s'])

    def test_distinct_generation_global_integrity_clock_and_rights_refusals(self):
        for mode, code in [('price_hash', 'HASH_MISMATCH'), ('manifest_hash', 'HASH_MISMATCH'),
                           ('generation_future', 'FUTURE_GENERATION'), ('source_future', 'FUTURE_SOURCE'),
                           ('expiry', 'STALE_GENERATION'), ('rights', 'PURPOSE_NOT_LICENSED'),
                           ('identity_hash', 'HASH_MISMATCH'), ('identity_expiry', 'FEATURE_IDENTITY_CLOCK')]:
            with self.subTest(mode=mode):
                case = self.fixture()
                if mode == 'identity_expiry':
                    case.bind_identity_evidence(case.identity(IDS['SPY']), expires_at='2026-10-13T23:59:59Z')
                benchmark, _ = self.separate(case); spec = benchmark['datasets'][0]
                if mode == 'generation_future': benchmark['created_at'] = '2026-10-15T00:00:00Z'
                if mode == 'source_future': spec['source']['available_from'] = '2026-10-15T00:00:00Z'
                if mode == 'expiry': spec['source']['expires_at'] = '2026-10-13T23:59:59Z'
                if mode == 'rights': spec['source']['eligible_purposes'] = []
                gen = self.store(case, benchmark)
                item = next(f for f in spec['files'] if f['instrument']['instrument_id'] == IDS['SPY'])
                h = item['sha256'] if mode == 'price_hash' else item['instrument']['identity_evidence_sha256']
                if mode in ('price_hash', 'identity_hash'):
                    case.transport.objects[f'{access.PREFIX_V1}/objects/{h}'] += b' '
                if mode == 'manifest_hash': case.transport.objects[f'{access.PREFIX_V1}/generations/{gen}'] += b' '
                result = self.call(case, benchmark_generations={'SPY': gen})
                case.assert_blocked(result, code)

    def test_unknown_mapping_or_conflicting_generation_trust_refuses_before_io(self):
        case = self.fixture(); gen = case.generation()
        for options in [dict(benchmark_generations={'QQQ': gen}),
                        dict(benchmark_generations={'SPY': 'latest'}),
                        dict(benchmark_expected_qualification_sha256={'SPY': '1'*64}),
                        dict(benchmark_generations={'SPY': gen},
                             benchmark_expected_qualification_sha256={'SPY': '1'*64},
                             benchmark_trusted_qualification_sources={'SPY': None}),
                        dict(benchmark_ids={'SPY': IDS['SPY'], 'NASDAQ_COMPOSITE': IDS['^IXIC']},
                             benchmark_generations={'SPY': '2'*64, 'NASDAQ_COMPOSITE': '2'*64},
                             benchmark_expected_qualification_sha256={'SPY': '1'*64},
                             benchmark_trusted_qualification_sources={'SPY': None})]:
            with self.subTest(options=options), patch.object(case.transport, 'read',
                    side_effect=AssertionError('READ_BEFORE_MAPPING_REFUSAL')):
                with self.assertRaises(access.ContractError): self.call(case, **options)

    def test_provider_close_requires_its_own_external_pins_and_keeps_proxy_rs_null(self):
        from a1_reader_generation_binding_smoke import provider_close_fixture, rewrite_provider_qualification
        from tools import prepare_a1_reader_generation as binding
        transport = MemoryTransport()
        def prepared(ticker, run):
            state = provider_close_fixture(names=(ticker,), run_id=run)
            if ticker == 'SPY':
                e, objects = state[3], state[5]
                ref = e['technical_metadata']['SPY']['identity_evidence']
                identity = json.loads(objects.pop(ref['sha256'])); identity['asset_class'] = 'ETF'
                raw = encoded(identity); h = digest(raw); objects[h] = raw
                e['technical_metadata']['SPY']['identity_evidence'] = dict(sha256=h, bytes=len(raw))
                rewrite_provider_qualification(state, lambda q: q['instruments']['US.TEST.SPY'].update(
                    identity_evidence_sha256=h))
            raw, norm, rec, e, trust, objects = state
            result = binding.prepare(raw, norm, rec, encoded(e), decision_time='2026-10-24T09:00:00Z',
                trusted_source=trust, proof_objects=tuple(sorted(objects.items())))
            self.assertEqual(result.status, 'REAL_SOURCE_PREPARED_UNADMITTED', result.blockers)
            for base in result.bases:
                transport.objects[f'{access.PREFIX_V1}/generations/{base.generation_id}'] = base.manifest
                for h, raw in base.objects: transport.objects[f'{access.PREFIX_V1}/objects/{h}'] = raw
            raw, split = result.bases
            qsha = json.loads(split.manifest)['datasets'][0]['source']['provider_close_qualification_sha256']
            return raw, split, qsha, trust
        raw, subject, qsha, trust = prepared('AAPL', 987654321)
        _, benchmark, bqsha, btrust = prepared('SPY', 987654322)
        reader = access.ResearchDataReader(transport)
        arguments = dict(security_id='US.TEST.AAPL', session='2016-01-12',
            as_of='2026-10-24T09:00:00Z', raw_generation=raw.generation_id,
            expected_qualification_sha256=qsha, trusted_qualification_source=trust,
            benchmark_ids={'SPY': 'US.TEST.SPY'}, benchmark_generations={'SPY': benchmark.generation_id})
        good = target.research_feature_snapshot(reader, subject.generation_id,
            benchmark_expected_qualification_sha256={'SPY': bqsha},
            benchmark_trusted_qualification_sources={'SPY': btrust}, **arguments)
        self.assertIsNotNone(good['features']['ret_5s'], good['blocker'])
        self.assertEqual(good['blocker']['rs_log_spy_5s'], 'BENCHMARK_PIT_UNVERIFIED')
        self.assertEqual(good['benchmark_ref']['SPY']['generation'], benchmark.generation_id)
        for overrides, code in [({}, 'QUALIFICATION_TRUST_REQUIRED'),
            (dict(benchmark_expected_qualification_sha256={'SPY': bqsha},
                  benchmark_trusted_qualification_sources={'SPY': trust}), 'QUALIFICATION_REVIEW_BINDING'),
            (dict(benchmark_expected_qualification_sha256={'SPY': qsha},
                  benchmark_trusted_qualification_sources={'SPY': trust}), 'HALT_COVERAGE_UNKNOWN')]:
            bad = target.research_feature_snapshot(reader, subject.generation_id, **arguments, **overrides)
            self.assertEqual(set(bad['blocker'].values()), {code})
            self.assertTrue(all(v is None for v in bad['features'].values()))

    def test_explicit_corrected_benchmark_preserves_original_replay_and_subject_values(self):
        case = self.fixture()
        benchmark, _ = self.separate(case); original = self.store(case, benchmark)
        before = self.call(case, benchmark_generations={'SPY': original})
        item = next(f for f in benchmark['datasets'][0]['files']
                    if f['instrument']['instrument_id'] == IDS['SPY'])
        rows = copy.deepcopy(case.rows[IDS['SPY']])
        for field in ('open', 'high', 'low', 'close'): rows[-1][field] += 1
        raw = b''.join(encoded(r) for r in rows); h = digest(raw)
        item.update(sha256=h, bytes=len(raw))
        case.transport.objects[f'{access.PREFIX_V1}/objects/{h}'] = raw
        benchmark['source_run_id'] = 'SYNTHETIC_EXPLICIT_CORRECTION'
        benchmark['datasets'][0]['source']['source_receipt_sha256'] = digest(b'CORRECTED_BENCHMARK_RECEIPT')
        corrected = self.store(case, benchmark)
        after = self.call(case, benchmark_generations={'SPY': corrected})
        self.assertNotEqual(original, corrected)
        self.assertNotEqual(before['features']['rs_log_spy_5s'], after['features']['rs_log_spy_5s'])
        self.assertEqual(before['source_ref'], after['source_ref'])
        for key in target.TECH_FEATURE_NAMES:
            if not key.startswith(('rs_log_spy_', 'nasdaq_composite_')):
                self.assertEqual(before['features'][key], after['features'][key])
        self.assertEqual(before, self.call(case, benchmark_generations={'SPY': original}))

    def test_roster_forwards_separate_generations_and_keeps_negative_and_missing_candidates(self):
        from tools import run_theme_leadership_tape as tape, run_a2_research_intake as caller
        case = self.fixture()
        for i, row in enumerate(case.rows[IDS['TEST']]):
            row.update(open=100-i, high=101-i, low=99-i, close=100-i)
        case.add_file(IDS['TEST'])
        benchmark, raw = self.separate(case); gen = self.store(case, benchmark)
        identities = dict(scope='SUPPLIED_US_IDENTITY_ASSERTIONS', rows=[
            dict(security_id=IDS['TEST'], issuer_id='FIXTURE:ISSUER:TEST', tickers=['TEST'], country='US', currency='USD'),
            dict(security_id='FIXTURE:US:MISSING', issuer_id='FIXTURE:ISSUER:MISSING', tickers=['MISSING'], country='US', currency='USD')])
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(case.reader, 'read_components', wraps=case.reader.read_components) as reads:
            result = tape.prepare_research_roster(case.reader, {IDS['TEST']: case.generation()},
                roster_raw=encoded(dict(scope='PRE_RANKING_RESEARCH_ROSTER', rows=[dict(ticker='TEST'), dict(ticker='MISSING')])),
                identities_raw=encoded(identities), session=SESSION, as_of=ASOF,
                observed_at='2026-10-30T06:30:00Z', intake_cutoff='2026-10-30T06:31:00Z',
                out_dir=Path(tmp)/'new', source_kind='FUSION_REVIEW',
                raw_generations={IDS['TEST']: raw}, benchmark_ids={'SPY': IDS['SPY']},
                benchmark_generations={'SPY': gen})
        self.assertEqual(reads.call_count, 3)
        observation = result['observation']
        self.assertEqual((observation['requested_count'], observation['missing_source_count']), (2, 1))
        self.assertLess(observation['rows'][0]['ret_5s'], 0)
        self.assertIsNone(observation['rows'][1]['ret_5s'])
        self.assertEqual(observation['snapshots'][0]['benchmark_ref']['SPY']['generation'], gen)
        self.assertEqual({r['ticker'] for r in result['a2_result']['queue']['items']}, {'TEST', 'MISSING'})
        self.assertTrue(all(r['state'] == 'DATA_PENDING' for r in result['a2_result']['queue']['items']))
        self.assertIsNone(result['a3_consumer_ack']); self.assertFalse(result['canonical_current_verified'])


class CompositionFeatureTests(unittest.TestCase):
    def test_actual_reader_and_feature_accept_only_external_composition_review(self):
        from a1_reader_generation_binding_smoke import composition_fixture
        from tools import prepare_a1_reader_generation as binding
        parents,e,trust,proofs=composition_fixture()
        result=binding.compose_prepared(parents,encoded(e),decision_time='2026-10-26T02:00:00Z',
            trusted_source=trust,proof_objects=tuple(sorted(proofs.items())))
        self.assertEqual(result.status,'REAL_SOURCE_COMPOSED_UNADMITTED',result.blockers)
        transport=MemoryTransport()
        for base in result.bases:
            transport.objects[f'{access.PREFIX_V1}/generations/{base.generation_id}']=base.manifest
            for h,raw in base.objects:
                transport.objects[f'{access.PREFIX_V1}/objects/{h}']=raw
        raw,split=result.bases
        qsha=json.loads(split.manifest)['datasets'][0]['source']['provider_close_qualification_sha256']
        args=dict(security_id='US.TEST.AAPL',session='2016-01-15',as_of='2026-10-26T02:00:00Z',
            raw_generation=raw.generation_id,expected_qualification_sha256=qsha,
            benchmark_ids={'SPY':'US.TEST.SPY'})
        reader=access.ResearchDataReader(transport)
        good=target.research_feature_snapshot(reader,split.generation_id,
            trusted_qualification_source=trust,**args)
        self.assertIsNotNone(good['features']['ret_5s'],good['blocker'])
        self.assertIsNotNone(good['raw_ref'])
        self.assertEqual(good['blocker']['rs_log_spy_20s'],'MISSING_INSTRUMENT')
        self.assertEqual(good,target.research_feature_snapshot(reader,split.generation_id,
            trusted_qualification_source=trust,**args))
        for flag in ('source_admitted','historical_pit_certified','ranking_allowed','ER_allowed',
                     'portfolio_allowed','orders_generated'):
            self.assertFalse(good[flag])
        bad=target.research_feature_snapshot(reader,split.generation_id,
            trusted_qualification_source=None,**args)
        self.assertIsNone(bad['features']['ret_5s'])


class CalendarBatchFeatureTests(unittest.TestCase):
    """Tiny actual Reader/Feature parity, separate from the 510-row oracles."""
    class OriginalLookup:
        # Conservative baseline: even the legacy single-date close checks get
        # invocation-local date reuse here. The product has no cross-call cache.
        def __init__(self, **_): self.cache = {}
        def include(self, *_): pass
        def __getitem__(self, value):
            if value not in self.cache:
                self.cache[value] = access._session_close(value)
            return self.cache[value]
        def sessions(self, *_): return None

    def compare(self, transform=None, *, days=None, options=None, count=False):
        with patch(__name__+'.DAYS', list(days or DAYS[-6:])):
            case = FeatureTests('runTest')
            case.setUp()
            if transform is not None:
                transform(case)
            calendar = mcal.get_calendar('NYSE')
            def run():
                with patch.object(calendar, 'schedule', wraps=calendar.schedule) as schedules, \
                     patch.object(mcal, 'get_calendar', return_value=calendar):
                    result = case.call(**(options or {}))
                    return result, schedules.call_count
            with patch.object(access, '_SessionCloseMap', self.OriginalLookup):
                before, old_calls = run()
            after, new_calls = run()
            # Same loaded code provenance in both strategies: exact receipts,
            # source refs, numeric/status/coverage and final semantic hash.
            self.assertEqual(before, after)
            if count:
                # Includes the fixed calculator grid and one original authority
                # anchor per Reader call and per Feature snapshot close map.
                self.assertEqual((old_calls, new_calls), (21, 8))
                replay, replay_calls = run()
                self.assertEqual(after, replay)
                self.assertEqual(replay_calls, 8)  # no cache survives the call
            return after

    def test_calendar_batch_snapshot_reuses_subject_raw_and_coverage(self):
        result = self.compare(count=True)
        self.assertIsNotNone(result['features']['ret_5s'])
        self.assertEqual(result['coverage']['consecutive_tail_rows'], 6)
        self.assertIsNotNone(result['raw_ref'])
        for key in ('source_admitted', 'historical_pit_certified', 'eligible_for_selector',
                    'ranking_allowed', 'ER_allowed', 'portfolio_allowed', 'orders_generated'):
            self.assertFalse(result[key])

    def test_calendar_batch_dst_and_full_obv_anchor_are_unchanged(self):
        result = self.compare(days=['2026-03-03', '2026-03-04', '2026-03-05',
                                    '2026-03-06', '2026-03-09', SESSION])
        # The declared internal gap keeps the original suffix; it never pads
        # missing history or extends an accumulation/OBV anchor across it.
        self.assertEqual(result['coverage']['consecutive_tail_rows'], 1)
        self.assertIsNone(result['features']['ret_5s'])
        result = self.compare(days=['2026-03-03', '2026-03-04', '2026-03-05',
                                    '2026-03-06', '2026-03-09', '2026-03-10'],
                              options={'session': '2026-03-10'})
        self.assertIsNotNone(result['features']['ret_5s'])
        self.assertEqual(result['coverage']['consecutive_tail_rows'], 6)
        self.assertEqual(result['coverage']['first_observed_session'], '2026-03-03')

    def test_calendar_batch_known_halts_unknown_and_optional_absence_keep_semantics(self):
        def current(case):
            case.identity()['halted_sessions'] = [SESSION]
        result = self.compare(current)
        self.assertEqual(set(result['blocker'].values()), {'TRADING_SUSPENDED'})
        def historical(case):
            case.identity()['halted_sessions'] = [DAYS[-3]]
        result = self.compare(historical)
        self.assertEqual(result['coverage']['consecutive_tail_rows'], 2)
        self.assertIsNone(result['features']['ret_5s'])
        def unknown(case):
            case.identity()['halted_sessions'] = None
        result = self.compare(unknown)
        self.assertEqual(set(result['blocker'].values()), {'HALT_COVERAGE_UNKNOWN'})
        def missing(case):
            case.data_spec['files'] = [f for f in case.data_spec['files']
                                      if f['instrument']['instrument_id'] != IDS['SPY']]
        result = self.compare(missing)
        self.assertIsNotNone(result['features']['ret_5s'])
        self.assertEqual(result['blocker']['rs_log_spy_5s'], 'MISSING_INSTRUMENT')

    def test_calendar_batch_optional_integrity_and_clocks_stay_global(self):
        def corrupt(case):
            h = case.identity(IDS['SPY'])['identity_evidence_sha256']
            case.transport.objects[f'{access.PREFIX_V1}/objects/{h}'] += b' '
        result = self.compare(corrupt)
        self.assertEqual(set(result['blocker'].values()), {'HASH_MISMATCH'})
        def before_close(case):
            rows = case.rows[IDS['TEST']]
            rows[0]['available_from'] = rows[0]['session_date']+'T19:59:59Z'
            case.add_file(IDS['TEST'])
        result = self.compare(before_close)
        self.assertEqual(set(result['blocker'].values()), {'PRE_CLOSE_AVAILABLE_FROM'})
        # Completion is checked before reading a generation, with the existing
        # public finite refusal on pre-close and non-session requests.
        for session, cutoff in ((SESSION, SESSION+'T19:59:59Z'),
                                ('2026-07-04', ASOF), ('2026-07-03', ASOF)):
            with self.subTest(session=session), self.assertRaisesRegex(
                    access.ContractError, '^FEATURE_SESSION_NOT_COMPLETED$'):
                self.compare(options={'session': session, 'as_of': cutoff})


def run_contract_suite():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FeatureTests)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(BenchmarkGenerationTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(CompositionFeatureTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(CalendarBatchFeatureTests))
    outcome=unittest.TextTestRunner(verbosity=1).run(suite)
    if not outcome.wasSuccessful():raise RuntimeError('TECHNICAL_FEATURE_H1_CONTRACT_FAILED')


if __name__=='__main__':run_contract_suite()
