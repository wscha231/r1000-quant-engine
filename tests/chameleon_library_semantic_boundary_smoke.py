"""Separate semantic regressions; preserve original core/parent/clock tests."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import chameleon_market_context_v2 as c
from tools import free_market_context as f

CLOCK = '2026-10-04T12:00:00Z'
DAY = '2026-10-02'
KW = {'collected_at': CLOCK, 'cutoff': CLOCK}

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def price(cohort='__MARKET__', move=-.01):
    return {'cohort': cohort, 'members': ['XAAA'], 'metrics': {'pct_above_ma20': {'value': 1., 'eligible_count': 1, 'expected_count': 1}},
            'available_at': CLOCK, 'collected_at': CLOCK, 'mapping_available_at': CLOCK, 'cutoff': CLOCK,
            'advancers': int(move > 0), 'decliners': int(move < 0), 'unchanged': int(move == 0),
            'missing_return_count': 0, 'median_return_1d': move, 'session': DAY, 'source_sha256': 'a' * 64,
            'truth_class': 'CURRENT_COHORT_RESEARCH_NOT_HISTORICAL_PIT', **f.SAFETY}

def survey(line='60,20,20', unit='percent'):
    return f.aaii_observations(('date,bullish,neutral,bearish\n2026-10-01,' + line).encode(), unit=unit, **KW)

def cot(kind='TFF_FUTURES', long=60, short=20, oi=100):
    prefix = 'asset_mgr' if kind == 'TFF_FUTURES' else 'm_money'
    raw = [{'cftc_contract_market_code': '13874A', 'report_date_as_yyyy_mm_dd': '2026-09-29T00:00:00.000',
            'open_interest_all': str(oi), prefix + '_positions_long_all': str(long), prefix + '_positions_short_all': str(short)}]
    return f.cot_observations(encoded(raw), report_kind=kind, **KW)

def finra(short=60):
    raw = ('Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20261002|XAAA|'
           + str(short) + '|0|100|Q\n1\n').encode()
    return f.finra_observations(raw, trade_date=DAY, **KW)

def cboe(universe='EQUITY', calls=100, puts=60):
    ratio = 0 if calls == 0 else puts / calls
    raw = ('DATE,CALL,PUT,TOTAL,P/C Ratio\n10/02/2026,' + str(calls) + ',' + str(puts) + ','
           + str(calls + puts) + ',' + str(ratio)).encode()
    return f.cboe_observations(raw, universe=universe, **KW)

def context(*, prices=None, public=None):
    macro = []
    for symbol, values in (('VIXCLS', (20, 22)), ('VXVCLS', (21, 20)), ('BAMLH0A0HYM2', (3.1, 3.2))):
        raw = ('observation_date,' + symbol + '\n2026-10-01,' + str(values[0]) + '\n2026-10-02,' + str(values[1]) + '\n').encode()
        macro += c.macro_source_rows(raw, source_id='fred:' + symbol, **KW)
    calendar = f.calendar_theme_context(encoded({'type': 'Trends', 'symbols': 'XAAA.US', 'trends': [[{
        'code': 'XAAA.US', 'date': '2026-12-31', 'period': '0y', 'earningsEstimateAvg': '2',
        'epsTrendCurrent': '2', 'epsTrend30daysAgo': '1.5'}]]}), ['XAAA.US'], {'XAAA.US': ['power']},
        observed_at=CLOCK, mapping_available_at=CLOCK, **KW)
    return c.build_context(macro_rows=macro, public_rows=survey() if public is None else public,
        price_rows=[price(), price('power', .02)] if prices is None else prices,
        calendar_result=calendar, security_map={'XAAA.US': 'XAAA'}, security_map_available_at=CLOCK,
        cutoff=CLOCK, expected_session=DAY)

class ChameleonSemanticBoundaryTests(unittest.TestCase):
    def closed(self, value):
        c.verify_context(value)
        self.assertEqual({k: value[k] for k in c.SAFETY}, c.SAFETY)
        self.assertFalse(value['input_producer_authenticated'])
        self.assertIsNone(value['regime'])

    def test_typed_and_numeric_string_prices_have_same_semantics_without_input_mutation(self):
        baseline = context()
        self.closed(baseline)
        changes = [(0, 'median_return_1d', '-0.01'), (1, 'median_return_1d', '0.02'),
                   (0, 'missing_return_count', '0'), (1, 'missing_return_count', '0')]
        for index, field, value in changes:
            with self.subTest(index=index, field=field):
                rows = [price(), price('power', .02)]
                rows[index][field] = value
                before = encoded(rows)
                self.assertEqual(context(prices=rows), baseline)
                self.assertEqual(encoded(rows), before)
        rows = [price(), price('power', .02)]
        for row in rows:
            for field in ('advancers', 'decliners', 'unchanged', 'missing_return_count'):
                row[field] = str(row[field])
            row['metrics']['pct_above_ma20'].update(value='1.0', eligible_count='1', expected_count='1')
        before = encoded(rows)
        self.assertEqual(context(prices=rows), baseline)
        self.assertEqual(encoded(rows), before)

    def test_price_null_stale_and_invalid_controls_stay_bounded(self):
        for field, value in (('median_return_1d', None), ('session', '2026-10-01')):
            rows = [price(), price('power', .02)]
            for row in rows:
                row[field] = value
            before = encoded(rows)
            self.closed(context(prices=rows))
            self.assertEqual(encoded(rows), before)
        for value in (True, 'NaN', -1):
            rows = [price(), price('power', .02)]; rows[0]['median_return_1d'] = value
            before = encoded(rows)
            with self.assertRaises(f.ContextError):
                context(prices=rows)
            self.assertEqual(encoded(rows), before)
        rows = [price(), price('power', .02)]; rows[0]['metrics']['pct_above_ma20']['value'] = 2
        with self.assertRaises(f.ContextError):
            context(prices=rows)

    def test_public_registered_parser_pairs_and_signed_cot_zero_oi_controls(self):
        cases = [survey(), survey('100,0,0'), survey('0,0,100'), survey('0.6,0.2,0.2', 'fraction'), finra(0), finra(100)]
        cases += [cboe(u) for u in ('EQUITY', 'INDEX', 'TOTAL')] + [cboe(calls=0)]
        cases += [cot(k, long, short, oi) for k in ('TFF_FUTURES', 'DISAGG_FUTURES')
                  for long, short, oi in ((100, 0, 100), (0, 100, 100), (0, 0, 0))]
        for rows in cases:
            with self.subTest(provider=rows[0]['provider'], dataset=rows[0]['dataset'], value=rows[0]['value']):
                before = encoded(rows)
                panel = c.public_panel(rows, cutoff=CLOCK)
                self.assertEqual(len(panel), len(rows))
                self.closed(context(public=rows))
                self.assertEqual(encoded(rows), before)

    def test_public_provider_dataset_entity_metric_unit_are_bounded(self):
        seeds = [survey()[0], finra()[0], cboe()[0], next(r for r in cot() if r['group'] == 'ASSET_MANAGER')]
        for seed in seeds:
            for field, invalid in (('dataset', 'OTHER'), ('entity_id', 'WRONG_SCOPE'), ('metric', 'UNREGISTERED'), ('unit', 'percent')):
                with self.subTest(provider=seed['provider'], field=field):
                    row = copy.deepcopy(seed); row[field] = invalid; before = encoded(row)
                    with self.assertRaises(f.ContextError):
                        c.public_panel([row], cutoff=CLOCK)
                    self.assertEqual(encoded(row), before)
        for field in ('provider', 'dataset', 'entity_id', 'metric', 'unit'):
            row = survey()[0]; row[field] = []
            with self.assertRaises(f.ContextError):
                c.public_panel([row], cutoff=CLOCK)

    def test_public_numeric_domains_and_cot_metadata_are_bounded(self):
        seeds = [(survey()[0], (-2, 2)), (finra()[0], (-.1, 1.1)), (cboe()[0], (-.1,)),
                 (next(r for r in cot() if r['group'] == 'ASSET_MANAGER' and r['metric'] == 'net_fraction_oi'), (-2, 2)),
                 (next(r for r in cot() if r['group'] == 'ASSET_MANAGER' and r['metric'] == 'net_contracts'), (.5,))]
        for seed, values in seeds:
            for value in (*values, True, 'NaN'):
                with self.subTest(provider=seed['provider'], metric=seed['metric'], value=value):
                    row = copy.deepcopy(seed); row['value'] = value; before = encoded(row)
                    with self.assertRaises(f.ContextError):
                        c.public_panel([row], cutoff=CLOCK)
                    self.assertEqual(encoded(row), before)
        seed = next(r for r in cot() if r['group'] == 'ASSET_MANAGER' and r['metric'] == 'net_contracts')
        for field, value in (('group', 'OTHER'), ('open_interest', -1), ('long_contracts', 101), ('value', 41)):
            row = copy.deepcopy(seed); row[field] = value
            with self.assertRaises(f.ContextError):
                c.public_panel([row], cutoff=CLOCK)

    def test_public_null_stale_and_numeric_string_controls_preserve_authority(self):
        for changes, expected in (({'value': None}, 'MISSING'), ({'observation_date': '2020-01-01'}, 'STALE'),
                                  ({'value': '0.4'}, 'OBSERVED')):
            row = survey()[0]; row.update(changes); before = encoded(row)
            result = context(public=[row]); self.closed(result)
            self.assertEqual(result['public'][0]['status'], expected)
            self.assertEqual(encoded(row), before)
            codes = [x['code'] for x in result['diagnostics']]
            self.assertEqual('BULLISH_SURVEY_WITH_PRICE_DECLINE' in codes, expected == 'OBSERVED')

    def test_wrong_public_domain_never_reaches_survey_diagnostic(self):
        for field, value in (('dataset', 'OTHER'), ('unit', 'percent'), ('entity_id', 'WRONG_SCOPE'), ('value', 2)):
            row = survey()[0]; row[field] = value; before = encoded(row)
            with self.assertRaises(f.ContextError):
                context(public=[row])
            self.assertEqual(encoded(row), before)

if __name__ == '__main__':
    unittest.main(verbosity=2)
