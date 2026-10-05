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


class ChameleonHostedReviewBoundaryTests(unittest.TestCase):
    def full_public(self):
        return survey() + cot() + finra()

    def missing_market(self, *, median=None, metric_value=None, eligible=0):
        value = price()
        value.update(advancers=0, decliners=0, unchanged=0, missing_return_count=1,
                     median_return_1d=median)
        value['metrics']['pct_above_ma20'].update(value=metric_value, eligible_count=eligible)
        return value

    def closed(self, value):
        c.verify_context(value)
        self.assertEqual({key: value[key] for key in c.SAFETY}, c.SAFETY)
        self.assertFalse(value['input_producer_authenticated'])

    def test_all_missing_market_is_not_usable_breadth(self):
        for median in (None, -.01):
            with self.subTest(median=median):
                rows = [self.missing_market(median=median), price('power', .02)]
                before = encoded(rows)
                result = context(prices=rows, public=self.full_public())
                self.assertEqual(result['family_presence']['breadth'], [])
                self.assertEqual(result['status'], 'PARTIAL_RESEARCH_CONTEXT')
                self.assertIn('breadth', result['missing_families'])
                self.closed(result)
                self.assertEqual(encoded(rows), before)

    def test_breadth_requires_valid_returns_or_nonnull_eligible_metrics(self):
        partial = price()
        partial.update(members=['XAAA', 'XBBB'], missing_return_count=1)
        partial['metrics']['pct_above_ma20'].update(value=None, eligible_count=0, expected_count=2)
        cases = [(price(move=0), True), (partial, True),
                 (self.missing_market(metric_value=0, eligible=1), True),
                 (self.missing_market(metric_value=None, eligible=1), False),
                 (self.missing_market(), False)]
        stale = price(); stale['session'] = '2026-10-01'
        cases.append((stale, False))
        for market, present in cases:
            with self.subTest(market=market, present=present):
                result = context(prices=[market, price('power', .02)], public=self.full_public())
                self.assertEqual(bool(result['family_presence']['breadth']), present)
                self.assertEqual('breadth' in result['missing_families'], not present)
                self.closed(result)

    def test_finra_activity_cannot_replace_fresh_cftc_positioning(self):
        missing = cot()
        for row in missing: row['value'] = None
        stale = cot()
        for row in stale: row['observation_date'] = '2020-01-01'
        cases = [(survey() + finra(), False, True),
                 (survey() + finra() + missing, False, True),
                 (survey() + finra() + stale, False, True),
                 (survey() + cot(), True, False),
                 (self.full_public(), True, True)]
        for rows, positioning, activity in cases:
            with self.subTest(positioning=positioning, activity=activity):
                before = encoded(rows)
                result = context(public=rows)
                self.assertEqual(result['family_presence']['positioning'], ['CFTC'] if positioning else [])
                self.assertEqual(result['family_presence']['short_sale_activity'], ['FINRA'] if activity else [])
                self.assertEqual('positioning' in result['missing_families'], not positioning)
                self.assertNotIn('short_sale_activity', result['missing_families'])
                self.assertEqual(result['status'], 'RESEARCH_CONTEXT_COMPOSED' if positioning else 'PARTIAL_RESEARCH_CONTEXT')
                self.closed(result)
                self.assertEqual(encoded(rows), before)

    def mapped(self, mapping=None, available=CLOCK):
        symbols = ['XAAA.US', 'XBBB.US']
        payload = {'type': 'Trends', 'symbols': ','.join(symbols), 'trends': [
            [
            {'code': symbol, 'date': '2026-12-31', 'period': '0y', 'earningsEstimateAvg': '2',
             'epsTrendCurrent': '2', 'epsTrend30daysAgo': '1.5'}] for symbol in symbols]}
        calendar = f.calendar_theme_context(encoded(payload), symbols, {symbol: ['power'] for symbol in symbols},
            observed_at=CLOCK, mapping_available_at=CLOCK, **KW)
        rows = [price(), price('power', .02)]
        for row in rows:
            row['members'] = ['XAAA', 'XBBB']
            for field in ('advancers', 'decliners', 'unchanged'): row[field] *= 2
            row['metrics']['pct_above_ma20'].update(eligible_count=2, expected_count=2)
        return c.build_context(macro_rows=[], public_rows=self.full_public(), price_rows=rows,
            calendar_result=calendar, security_map={'XAAA.US':'XAAA', 'XBBB.US':'XBBB'} if mapping is None else mapping,
            security_map_available_at=available, cutoff=CLOCK, expected_session=DAY)

    def test_consumed_security_map_permutation_is_hashed_and_reviewed(self):
        mapping = {'XAAA.US':'XBBB', 'XBBB.US':'XAAA'}
        before = encoded(mapping)
        original, changed = self.mapped(), self.mapped(mapping)
        self.assertEqual(original['paired_themes'], changed['paired_themes'])
        self.assertNotEqual(original['content_sha256'], changed['content_sha256'])
        self.assertNotEqual(original['security_map_binding']['mapping_sha256'], changed['security_map_binding']['mapping_sha256'])
        self.assertEqual(c.context_delta(original, changed)['status'], 'CONTEXT_CHANGED_REVIEW_ONLY')
        self.assertEqual(encoded(mapping), before)
        reordered = self.mapped({'XBBB.US':'XBBB', 'XAAA.US':'XAAA'})
        self.assertEqual(original, reordered)
        self.assertEqual(c.context_delta(original, reordered)['status'], 'SKIP_UNCHANGED_CONTEXT')
        self.closed(changed)

    def test_security_map_availability_clock_is_semantic_and_bounded(self):
        earlier = self.mapped(available='2026-10-04T11:00:00Z')
        current = self.mapped()
        self.assertEqual(earlier['paired_themes'], current['paired_themes'])
        self.assertNotEqual(earlier['content_sha256'], current['content_sha256'])
        self.assertEqual(c.context_delta(earlier, current)['status'], 'CONTEXT_CHANGED_REVIEW_ONLY')
        equivalent = self.mapped(available='2026-10-04T21:00:00+09:00')
        self.assertEqual(current, equivalent)
        self.assertEqual(c.context_delta(current, equivalent)['status'], 'SKIP_UNCHANGED_CONTEXT')
        with self.assertRaisesRegex(f.ContextError, 'FUTURE_SECURITY_MAPPING'):
            self.mapped(available='2026-10-05T12:00:00Z')
        with self.assertRaisesRegex(f.ContextError, 'EXPLICIT_SECURITY_MAPPING'):
            self.mapped({'XAAA.US':'XAAA','XBBB.US':'XAAA'})

    def test_absent_optional_calendar_keeps_no_consumed_security_map(self):
        result = c.build_context(macro_rows=[], public_rows=survey(), price_rows=[price()],
            calendar_result=None, security_map=None, security_map_available_at=None,
            cutoff=CLOCK, expected_session=DAY)
        self.assertIsNone(result['security_map_binding'])
        self.assertEqual(result['paired_themes'], [])
        self.closed(result)


class ContextTransportIdentityBoundaryTests(unittest.TestCase):
    def build(self, *, price_hash='a' * 64, calendar_whitespace=False, move=.02,
              session=DAY, members=None, vendor_previous='1.5', mapping=None, map_clock=CLOCK, eligible=2):
        symbols = ['XAAA.US', 'XBBB.US']
        payload = {'type': 'Trends', 'symbols': ','.join(symbols), 'trends': [[
            {'code': symbol, 'date': '2026-12-31', 'period': '0y', 'earningsEstimateAvg': '2',
             'epsTrendCurrent': '2', 'epsTrend30daysAgo': vendor_previous}] for symbol in symbols]}
        raw = encoded(payload)
        if calendar_whitespace: raw = b'\n ' + raw + b' \n'
        calendar = f.calendar_theme_context(raw, symbols, {symbol: ['power'] for symbol in symbols},
            observed_at=CLOCK, mapping_available_at=CLOCK, **KW)
        rows = [price(), price('power', move)]
        for item in rows:
            item.update(members=['XAAA', 'XBBB'] if members is None else members,
                        session=session, source_sha256=price_hash)
            for name in ('advancers', 'decliners', 'unchanged'): item[name] *= 2
            item['metrics']['pct_above_ma20'].update(eligible_count=eligible, expected_count=2)
        security_map = {'XAAA.US': 'XAAA', 'XBBB.US': 'XBBB'} if mapping is None else mapping
        before = encoded([rows, calendar, security_map])
        value = c.build_context(macro_rows=[], public_rows=survey() + cot() + finra(), price_rows=rows,
            calendar_result=calendar, security_map=security_map, security_map_available_at=map_clock,
            cutoff=CLOCK, expected_session=DAY)
        self.assertEqual(encoded([rows, calendar, security_map]), before)
        c.verify_context(value)
        self.assertEqual({key: value[key] for key in c.SAFETY}, c.SAFETY)
        return value

    def test_only_price_calendar_transport_hash_churn_does_not_request_review(self):
        original = self.build()
        for options in ({'price_hash': 'b' * 64}, {'calendar_whitespace': True},
                        {'price_hash': 'b' * 64, 'calendar_whitespace': True}):
            with self.subTest(options=options):
                current = self.build(**options)
                self.assertNotEqual(original['content_sha256'], current['content_sha256'])
                self.assertNotEqual(original['paired_themes'][0]['source_refs'], current['paired_themes'][0]['source_refs'])
                self.assertEqual(c.context_delta(original, current)['status'], 'SKIP_UNCHANGED_CONTEXT')

    def test_actual_normalized_value_date_status_and_cohort_changes_remain_semantic(self):
        original = self.build()
        for options in ({'move': .03}, {'vendor_previous': '3'}, {'session': '2026-10-01'},
                        {'members': ['XAAA', 'XCCC']}, {'eligible': 1}):
            with self.subTest(options=options):
                current = self.build(**options, price_hash='b' * 64, calendar_whitespace=True)
                if 'eligible' in options:
                    self.assertNotEqual(original['price'][0]['metrics'], current['price'][0]['metrics'])
                else:
                    self.assertNotEqual(original['paired_themes'], current['paired_themes'])
                self.assertEqual(c.context_delta(original, current)['status'], 'CONTEXT_CHANGED_REVIEW_ONLY')
        from tests import chameleon_market_context_v2_library_smoke as fixture
        self.assertEqual(c.context_delta(fixture.context(), fixture.context(cutoff='2026-11-04T12:00:00Z'))['status'], 'CONTEXT_CHANGED_REVIEW_ONLY')

    def test_consumed_security_map_hash_and_clock_are_not_transport_aliases(self):
        original = self.build()
        for options in ({'mapping': {'XAAA.US': 'XBBB', 'XBBB.US': 'XAAA'}},
                        {'map_clock': '2026-10-04T11:00:00Z'}):
            with self.subTest(options=options):
                current = self.build(**options, price_hash='b' * 64, calendar_whitespace=True)
                self.assertNotEqual(original['security_map_binding'], current['security_map_binding'])
                self.assertEqual(c.context_delta(original, current)['status'], 'CONTEXT_CHANGED_REVIEW_ONLY')

if __name__ == '__main__':
    unittest.main(verbosity=2)
