import sys
import unittest
from pathlib import Path
import numpy as np, pandas as pd
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from tools import a4_regime_features as r
import hashlib
from tools import a4_archived_fed_releases as a

def fixture():
    parts = ['<html><body><p>Release Date: January 8, 2016</p>']
    for title, scope in a.SCOPES.items():
        base = {'all': 400.0, 'domestic': 300.0, 'large': 200.0, 'small': 100.0}[scope]
        parts += ['<h2>' + title + '</h2><p>Seasonally adjusted, billions of dollars</p>', '<table summary="' + title + '"><tr><th>Account</th></tr><tr>']
        parts += ['<th id="w' + str(n) + '">Dec ' + str(day) + '</th>' for n, day in enumerate((9, 16, 23, 30), 1)]
        parts += ['</tr>']
        for no, label in enumerate(a.FIELDS):
            parts += ['<tr><th>' + str(no) + '</th><th>' + label + '</th>']
            parts += ['<td headers="w' + str(n) + '">' + str(base) + '</td>' for n in range(1, 5)]
            parts += ['</tr>']
        parts += ['</table>']
    return (''.join(parts) + '</body></html>').encode()

def ref(raw):
    return dict(feed='h8', release_date='20160108', url='https://www.federalreserve.gov/releases/h8/20160108/', collected_at='2026-11-16T00:00:00+00:00', sha256=hashlib.sha256(raw).hexdigest())

class ArchiveChecks(unittest.TestCase):

    def test_typed_values_scope_and_year_rollover(self):
        raw = fixture()
        result = a.h8(raw, ref(raw), {'20160108'})
        self.assertEqual(len(result['observations']), 80)
        self.assertEqual(len(result['reconciliation']), 20)
        self.assertEqual({r['unit'] for r in result['observations']}, {'USD_BILLIONS'})
        self.assertEqual({r['balance_basis'] for r in result['observations']}, {'WEDNESDAY_LEVEL'})
        self.assertEqual({r['seasonal_adjustment'] for r in result['observations']}, {'SA'})
        self.assertEqual({r['observation_date'][:4] for r in result['observations']}, {'2015'})
        self.assertTrue(all((r['published_at'] is None and (not r['historical_pit_certified']) and (not r['training_admitted']) for r in result['observations'])))
        self.assertTrue(all((r['available_at'] == '2016-01-09T05:00:00+00:00' for r in result['observations'])))

    def test_original_hash(self):
        raw = fixture()
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_HASH'):
            a.h8(raw + b' ', ref(raw), {'20160108'})

    def test_official_index_required(self):
        raw = fixture()
        with self.assertRaisesRegex(ValueError, 'OFFICIAL_DATE_INDEX'):
            a.h8(raw, ref(raw), set())

    def test_collection_clock(self):
        raw = fixture()
        r = ref(raw)
        r['collected_at'] = '2015-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'COLLECTION_BEFORE_RELEASE'):
            a.h8(raw, r, {'20160108'})

    def test_naive_collection_clock(self):
        raw = fixture()
        rr = ref(raw)
        rr['collected_at'] = '2026-11-16T00:00:00'
        with self.assertRaisesRegex(ValueError, 'COLLECTION_TIMEZONE'):
            a.h8(raw, rr, {'20160108'})

    def test_document_release_identity(self):
        raw = fixture().replace(b'January 8, 2016', b'January 9, 2016')
        with self.assertRaisesRegex(ValueError, 'DOCUMENT_RELEASE_DATE'):
            a.h8(raw, ref(raw), {'20160108'})

    def test_unit_sa_and_missing_cell(self):
        for old, new in ((b'billions of dollars', b'millions of dollars'), (b'Seasonally adjusted', b'Not seasonally adjusted'), (b'<td headers="w1">400.0</td>', b'')):
            with self.subTest(old=old):
                raw = fixture().replace(old, new)
                with self.assertRaises(ValueError):
                    a.h8(raw, ref(raw), {'20160108'})

    def test_adjustment_and_amount_conflicts_are_independent(self):
        for declaration, reason in (
            (b'Not seasonally adjusted, millions of dollars', 'SEASONAL_AMBIGUITY'),
            (b'Seasonally adjusted, millions of dollars', 'H8_UNIT'),
            (b'Seasonally adjusted, trillions of dollars', 'H8_UNIT'),
        ):
            raw = fixture().replace(b'Seasonally adjusted, billions of dollars', b'Seasonally adjusted, billions of dollars</p><p>' + declaration)
            with self.subTest(declaration=declaration), self.assertRaisesRegex(ValueError, reason):
                a.h8(raw, ref(raw), {'20160108'})

    def test_aggregate_identity_failure(self):
        raw = fixture().replace(b'>100.0</td>', b'>101.0</td>')
        with self.assertRaisesRegex(ValueError, 'DOMESTIC_COMPONENT_SUM'):
            a.h8(raw, ref(raw), {'20160108'})

    def test_duplicate_invalid_and_unknown_week(self):
        for old, new in ((b'id="w2"', b'id="w1"'), (b'Dec 30', b'Dec 31'), (b'headers="w4"', b'headers="w5"')):
            with self.subTest(old=old):
                raw = fixture().replace(old, new)
                with self.assertRaises(ValueError):
                    a.h8(raw, ref(raw), {'20160108'})

    def test_unknown_number_never_zero_fill(self):
        for value in ('12,34', 'NaN', 'inf', '- - 2', '<100', '9' * 65):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    a.number(value)
        self.assertIsNone(a.number('...'))
        self.assertEqual(a.number('1,234.5'), 1234.5)

    def test_release_date_ignores_script_and_text_nodes_are_bounded(self):
        raw = fixture().replace(b'January 8, 2016', b'January 9, 2016') + b'<script>January 8, 2016</script>'
        with self.assertRaisesRegex(ValueError, 'DOCUMENT_RELEASE_DATE'):
            a.h8(raw, ref(raw), {'20160108'})
        raw = b'< ' * 100001
        with self.assertRaisesRegex(ValueError, 'TEXT_BUDGET'):
            a.read_document(raw, hashlib.sha256(raw).hexdigest())

    def test_nested_table_and_budget(self):
        for raw in (b'<table><table></table></table>', b'x' * (a.MAX_BYTES + 1)):
            with self.assertRaises(ValueError):
                a.read_document(raw, hashlib.sha256(raw).hexdigest())

    def test_zero_padded_date_and_footnote(self):
        raw = fixture().replace(b'January 8', b'January 08').replace(b'>Cash assets</th>', b'>Cash assets <a class="foot" href="#fn21">21</a></th>')
        self.assertEqual(len(a.h8(raw, ref(raw), {'20160108'})['observations']), 80)

def h41_fixture(kind, extra=''):
    release = '<p>Release Date: January 7, 2016</p>'
    rrplabels = ('Reverse repurchase agreements', 'Foreign official and international accounts', 'Others')
    pairlabels = rrplabels + ('U.S. Treasury, General Account', 'Reserve balances with Federal Reserve Banks')

    def row(label, v=100):
        return label.ljust(65) + str(v) + '  0  0  ' + str(v) + '\n' if kind == 'text' else '<tr><td>' + label + '</td><td>' + str(v) + '</td><td>0</td><td>0</td><td>' + str(v) + '</td></tr>'
    extra_rows = ''.join((row(label) for label in rrplabels[:int(extra)])) if extra else ''
    if kind == 'text':
        header = 'Reserve Bank credit, related items, and  Averages of daily figures  Wednesday\nreserve balances at Banks  Week ended  Change from week ended  Jan 6, 2016\nFederal Reserve Banks  Jan 6, 2016  Dec 30, 2015  Jan 7, 2015\n'
        text = '1. Factors Affecting Reserve Balances\nMillions of dollars\n' + header + row('Reserve Bank credit')
        text += '1. Factors Affecting Reserve Balances (continued)\nMillions of dollars\n' + header + ''.join((row(label) for label in pairlabels)) + extra_rows
        text += '2. Next section\n5. Consolidated Statement of Condition\nMillions of dollars\nAssets, liabilities, and capital  Eliminations  Wednesday  Change since\nfrom  Jan 6, 2016  Wednesday  Wednesday\nconsolidation  Dec 30, 2015  Jan 7, 2015\nTotal assets  (0)  1,000  0  0\n6. Statement of Condition\n'
        return (release + '<pre>' + text + '</pre>').encode()
    avg = '<p>Millions of dollars</p><table><tr><th>Reserve Bank credit</th><th>Averages of daily figures</th><th>Wednesday Jan 6, 2016</th></tr><tr><th>Week ended Jan 6, 2016</th><th>Change from week ended</th></tr><tr><th>Dec 30, 2015</th><th>Jan 7, 2015</th></tr>'
    assets = '<p>Millions of dollars</p><table><tr><th>Assets, liabilities, and capital</th><th>Eliminations from consolidation</th><th>Wednesday Jan 6, 2016</th><th>Change since</th></tr><tr><td>Total assets</td><td>(0)</td><td>1,000</td><td>0</td><td>0</td></tr></table>'
    return (release + avg + ''.join((row(label) for label in pairlabels)) + extra_rows + '</table>' + assets).encode()

def h41_ref(raw):
    r = ref(raw)
    r.update(feed='h41', release_date='20160107', url='https://www.federalreserve.gov/releases/h41/20160107/')
    return r

class H41Checks(unittest.TestCase):

    def test_padded_malformed_row_finishes_within_process_budget(self):
        import subprocess
        malformed = b'x' + (b' ' * 1200 + b'1') * 3 + b'\n'
        raw = h41_fixture('text').replace(b'2. Next section', malformed + b'2. Next section')
        code = "import sys,hashlib; from tools import a4_archived_fed_releases as a; raw=sys.stdin.buffer.read(); ref=dict(feed='h41',release_date='20160107',url='https://www.federalreserve.gov/releases/h41/20160107/',collected_at='2026-11-16T00:00:00+00:00',sha256=hashlib.sha256(raw).hexdigest()); print(len(a.h41(raw,ref,{'20160107'})['observations']))"
        result = subprocess.run([sys.executable, '-c', code], input=raw, capture_output=True, timeout=5, cwd=REPO)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.strip(), b'7')

    def test_linear_signed_columns_and_malformed_critical_row(self):
        self.assertEqual(a.text_columns('Label  1  -    2  + 3  4'), ['Label', '1', '-2', '+ 3', '4'])
        raw = h41_fixture('text').replace(b'2. Next section', b'Reserve balances with Federal Reserve Banks  1  2  3\n2. Next section')
        with self.assertRaisesRegex(ValueError, 'H41_CRITICAL_ROW_FORMAT'):
            a.h41(raw, h41_ref(raw), {'20160107'})

    def test_both_layouts_keep_units_dates_and_value_bases(self):
        for kind in ('text', 'html'):
            raw = h41_fixture(kind)
            result = a.h41(raw, h41_ref(raw), {'20160107'})
            self.assertEqual(len(result['observations']), 7)
            self.assertEqual({r['observation_date'] for r in result['observations']}, {'2016-01-06'})
            self.assertEqual({r['unit'] for r in result['observations']}, {'USD_MILLIONS'})
            self.assertEqual(sum((r['balance_basis'] == 'WEEKLY_AVERAGE' for r in result['observations'])), 3)

    def test_wednesday_date_and_semantics_cannot_drift(self):
        for kind in ('text', 'html'):
            raw = h41_fixture(kind)
            for altered in (raw.replace(b'Jan 6, 2016', b'Dec 30, 2015', 1), raw.replace(b'Wednesday', b'Thursday', 1)):
                with self.subTest(kind=kind):
                    with self.assertRaises(ValueError):
                        a.h41(altered, h41_ref(altered), {'20160107'})

    def test_consolidated_asset_date_must_match_week(self):
        for kind in ('text', 'html'):
            raw = h41_fixture(kind)
            p = raw.index(b'Consolidated' if kind == 'text' else b'Eliminations from consolidation')
            altered = raw[:p] + raw[p:].replace(b'Jan 6, 2016', b'Dec 30, 2015', 1)
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, 'CONSOLIDATED_DATE_MISMATCH'):
                    a.h41(altered, h41_ref(altered), {'20160107'})

    def test_rrp_duplicate_and_pending_blocks_refused(self):
        for kind in ('text', 'html'):
            for extra in ('1', '2', '3'):
                raw = h41_fixture(kind, extra)
                with self.subTest(kind=kind, extra=extra):
                    with self.assertRaisesRegex(ValueError, 'RRP_'):
                        a.h41(raw, h41_ref(raw), {'20160107'})

    def test_current_table_amount_units_required(self):
        for kind in ('text', 'html'):
            raw = h41_fixture(kind).replace(b'Millions of dollars', b'Billions of dollars')
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, 'H41_UNIT'):
                    a.h41(raw, h41_ref(raw), {'20160107'})

    def test_all_conflicting_h41_amount_scales_are_refused(self):
        for kind in ('text', 'html'):
            for scale in (b'Trillions', b'billions', b'Thousands'):
                raw = h41_fixture(kind).replace(b'Millions of dollars', b'Millions of dollars\n' + scale + b' of dollars')
                with self.subTest(kind=kind, scale=scale), self.assertRaisesRegex(ValueError, 'H41_UNIT'):
                    a.h41(raw, h41_ref(raw), {'20160107'})

    def test_completed_rrp_rejects_adjacent_duplicate_children(self):
        for kind in ('text', 'html'):
            raw = h41_fixture(kind)
            if kind == 'text':
                original = b'Others'.ljust(65) + b'100  0  0  100\n'
            else:
                original = b'<tr><td>Others</td><td>100</td><td>0</td><td>0</td><td>100</td></tr>'
            self.assertIn(original, raw)
            altered = raw.replace(original, original + original.replace(b'100', b'200'), 1)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'RRP_DUPLICATE_CHILD'):
                a.h41(altered, h41_ref(altered), {'20160107'})

    def test_extra_numeric_column_cannot_hide_a_critical_label(self):
        raw = h41_fixture('text')
        original = b'Others'.ljust(65) + b'100  0  0  100\n'
        self.assertIn(original, raw)
        for label in a.CRITICAL_LABELS:
            for variant in (label, label.replace(' ', '  '), label.replace(' ', '\t'), label.replace(' ', '\u00a0'), label.lower()):
                altered = raw.replace(original, original + variant.encode() + b'  200  0  0  200  999\n', 1)
                with self.subTest(label=label, variant=variant), self.assertRaisesRegex(ValueError, 'H41_CRITICAL_ROW_FORMAT'):
                    a.h41(altered, h41_ref(altered), {'20160107'})

    def test_shared_whitespace_normalization_for_units_and_html_labels(self):
        self.assertEqual(a.amount_units('Millions of dollars\n billions of\t dollars'), {'millions', 'billions'})
        raw = h41_fixture('html')
        original = b'<tr><td>Others</td><td>100</td><td>0</td><td>0</td><td>100</td></tr>'
        for variant, reason in (('others', 'H41_CRITICAL_ROW_FORMAT'), ('Foreign  official and international accounts 200', 'RRP_DUPLICATE_CHILD')):
            extra = '<tr><td>' + variant + '</td><td>200</td><td>0</td><td>0</td><td>200</td></tr>'
            altered = raw.replace(original, original + extra.encode(), 1)
            with self.subTest(variant=variant), self.assertRaisesRegex(ValueError, reason):
                a.h41(altered, h41_ref(altered), {'20160107'})

    def test_h8_both_adjustments_retained_beyond_old_context_cap(self):
        raw = fixture().replace(b'Seasonally adjusted, billions of dollars', b'Not seasonally adjusted, billions of dollars</p><p>' + b'x' * 1800 + b'</p><p>Seasonally adjusted, billions of dollars')
        with self.assertRaisesRegex(ValueError, 'SEASONAL_AMBIGUITY'):
            a.h8(raw, ref(raw), {'20160108'})

    def test_h8_mixed_adjustment_not_hidden_by_long_description(self):
        raw = fixture().replace(b'Seasonally adjusted, billions of dollars', b'Seasonally adjusted, billions of dollars</p><p>Not seasonally adjusted, billions of dollars</p><p>' + b'x' * 240)
        with self.assertRaisesRegex(ValueError, 'SEASONAL_AMBIGUITY'):
            a.h8(raw, ref(raw), {'20160108'})

def sessions(n=4):
    dates = pd.bdate_range('2020-02-03', periods=n)
    return [dict(session=d.date().isoformat(), close_utc=d.strftime('%Y-%m-%dT21:00:00+00:00')) for d in dates]

def rows(key='unemployment', values=None, available='2020-02-03T20:00:00+00:00'):
    vals = [4.0] * 15 if values is None else values
    source = {'unemployment': 'RUC', 'payrolls': 'EMPLOY', 'cpi': 'PCPI'}[key]
    unit = {'unemployment': 'percent', 'payrolls': 'thousands_persons', 'cpi': 'index'}[key]
    return [dict(logical_id=key, source_id='rtdsm:' + source, observation_date=p.strftime('%Y-%m-01'), value=v, unit=unit, frequency='monthly', family='INFLATION' if key == 'cpi' else 'GROWTH', measurement_basis='PERIOD_OBSERVATION', seasonal_basis='SA', max_age_days=150 if key == 'unemployment' else 90, available_at=available, collected_at='2026-11-16T00:00:00+00:00', original_sha256='a' * 64) for p, v in zip(pd.period_range('2018-11', periods=len(vals), freq='M'), vals)]

class RegimeFeatures(unittest.TestCase):

    def test_sahm_percentage_point_boundary(self):
        a = r.dated_economy(rows(values=[4.0] * 12 + [4.5] * 3), sessions())
        self.assertEqual(a.delayed_sahm_gap_pp.iloc[0], 0.5)
        self.assertEqual(a.delayed_sahm_above_05pp.iloc[0], 1)

    def test_sahm_excludes_current_ma_from_prior_minimum(self):
        a = r.dated_economy(rows(values=[4.0] * 12 + [3.0] * 3), sessions())
        self.assertLess(a.delayed_sahm_gap_pp.iloc[0], 0)

    def test_fifteen_months_required(self):
        a = r.dated_economy(rows(values=[4.0] * 14), sessions())
        self.assertTrue(a.delayed_sahm_gap_pp.isna().all())

    def test_null_month_and_stale_never_fill(self):
        data = rows()
        data[7]['value'] = None
        self.assertTrue(r.dated_economy(data, sessions()).delayed_sahm_gap_pp.isna().all())
        data = rows(available='2020-08-03T00:00:00+00:00')
        ss = [dict(session='2020-08-04', close_utc='2020-08-04T20:00:00+00:00'), dict(session='2020-08-05', close_utc='2020-08-05T20:00:00+00:00')]
        self.assertTrue(r.dated_economy(data, ss).delayed_sahm_gap_pp.isna().all())

    def test_future_vintage_never_changes_prior_features(self):
        original = rows()
        extra = rows(values=[10.0] * 15, available='2020-02-10T20:00:00+00:00')
        pd.testing.assert_frame_equal(r.dated_economy(original, sessions()), r.dated_economy(original + extra, sessions()))

    def test_publication_cutoff(self):
        a = r.dated_economy(rows(available='2020-02-03T21:00:00.000001+00:00'), sessions())
        self.assertTrue(np.isnan(a.delayed_sahm_gap_pp.iloc[0]))
        self.assertEqual(a.delayed_sahm_gap_pp.iloc[1], 0)

    def test_full_latest_vintage_not_mixed_with_old_month(self):
        older = rows()
        newer = rows(available='2020-02-04T20:00:00+00:00')
        newer = newer[-3:]
        a = r.dated_economy(older + newer, sessions())
        self.assertEqual(a.delayed_sahm_gap_pp.iloc[0], 0)
        self.assertTrue(a.delayed_sahm_gap_pp.iloc[1:].isna().all())

    def test_curve_bp_and_components(self):
        idx = pd.bdate_range('2020-01-01', periods=65)
        f = pd.DataFrame(dict(yield_10y=np.linspace(3, 4, 65), yield_2y=np.linspace(4, 2, 65), yield_3m=3.5), index=idx)
        a = r.yield_curve(f)
        self.assertEqual(a.curve_10y_2y_bp.iloc[0], -100)
        self.assertEqual(a.curve_10y_2y_re_cross.sum(), 1)
        np.testing.assert_allclose(a.curve_10y_2y_change_21_bp.dropna(), (a.curve_10y_2y_long_rise_21_bp + a.curve_10y_2y_short_fall_21_bp).dropna())

    def test_curve_duration_and_future_extension(self):
        idx = pd.bdate_range('2020-01-01', periods=7)
        f = pd.DataFrame(dict(yield_10y=[2, 2, 3, 3, 3, np.nan, 4], yield_2y=2.5, yield_3m=2.5), index=idx)
        a = r.yield_curve(f)
        self.assertEqual(a.curve_10y_2y_inverted_sessions.iloc[1], 2)
        self.assertEqual(a.curve_10y_2y_sessions_since_re_cross.iloc[4], 2)
        self.assertTrue(np.isnan(a.curve_10y_2y_sessions_since_re_cross.iloc[6]))
        pd.testing.assert_frame_equal(r.yield_curve(f.iloc[:4]), a.iloc[:4])

    def test_zero_put_call_and_missing_volatility_remain_distinct(self):
        index = pd.bdate_range('2020-01-01', periods=6)
        frame = pd.DataFrame(dict(vix=20., vix3m=30., vvix=100., equity_put_call=0.), index=index)
        result = r.implied_volatility(frame)
        self.assertEqual(result.equity_put_call_5d.iloc[-1], 0)
        frame.loc[index[-1], 'vix3m'] = np.nan
        self.assertTrue(np.isnan(r.implied_volatility(frame).vix_vix3m.iloc[-1]))
        frame['equity_put_call'] = -1
        with self.assertRaisesRegex(ValueError, 'NEGATIVE_PUT_CALL'):
            r.implied_volatility(frame)

    def test_sector_missing_and_energy_separate(self):
        idx = pd.bdate_range('2020-01-01', periods=70)
        f = pd.DataFrame(100.0, index=idx, columns=r.SECTORS + ('SPY',))
        f.loc[idx[-1], 'XLE'] = 200
        f.loc[idx[0], 'XLC'] = np.nan
        a = r.sectors(f)
        self.assertEqual(a.cyclical_minus_defensive_21.iloc[-1], 0)
        self.assertEqual(a.energy_minus_spy_21.iloc[-1], 1)
        self.assertTrue(np.isnan(a.sector_XLC_return_21.iloc[21]))

    def test_breadth_complete_and_no_gap_cumsum(self):
        idx = pd.bdate_range('2020-01-01', periods=260)
        f = pd.DataFrame(dict(advances=2.0, declines=1.0, unchanged=0.0, new_highs=1.0, new_lows=0.0, eligible=3.0, above_ma50=2.0, above_ma200=2.0, eligible_ma50=3.0, eligible_ma200=3.0), index=idx)
        p = pd.Series(np.arange(260) + 100.0, index=idx)
        a = r.breadth(f, p, population_id='TEST_COHORT')
        self.assertTrue(a.new_high_low_ratio.isna().all())
        self.assertEqual(a.ad_line.iloc[-1], 260)
        f.loc[idx[5], 'advances'] = np.nan
        a = r.breadth(f, p, population_id='TEST_COHORT')
        self.assertTrue(a.ad_line.iloc[5:].isna().all())

    def test_breadth_identity_counts(self):
        idx = pd.bdate_range('2020-01-01', periods=2)
        f = pd.DataFrame(dict(advances=2.0, declines=1.0, unchanged=0.0, new_highs=1.0, new_lows=0.0, eligible=4.0, above_ma50=2.0, above_ma200=2.0, eligible_ma50=3.0, eligible_ma200=3.0), index=idx)
        with self.assertRaisesRegex(ValueError, 'COVERAGE'):
            r.breadth(f, pd.Series(100.0, index=idx), population_id='TEST_COHORT')

    def test_breadth_missing_current_or_reference_never_confirms(self):
        idx = pd.bdate_range('2020-01-01', periods=260)
        f = pd.DataFrame(dict(advances=2., declines=1., unchanged=0., new_highs=1., new_lows=0., eligible=3., above_ma50=2., above_ma200=2., eligible_ma50=3., eligible_ma200=3.), index=idx)
        price = pd.Series(np.arange(260) + 100., index=idx)
        for field, at in (('advances', -1), ('price', -1), ('price', -100)):
            counts, p = f.copy(), price.copy()
            if field == 'price':
                p.iloc[at] = np.nan
            else:
                counts.loc[idx[at], field] = np.nan
            with self.subTest(field=field, at=at):
                result = r.breadth(counts, p, population_id='TEST_COHORT')
                self.assertTrue(np.isnan(result.index_new_high_without_ad_confirmation.iloc[-1]))
                pd.testing.assert_frame_equal(result.iloc[:-1], r.breadth(counts.iloc[:-1], p.iloc[:-1], population_id='TEST_COHORT'))

    def test_partial_breadth_cannot_bypass_operand_bounds(self):
        idx = pd.bdate_range('2020-01-01', periods=2)
        base = pd.DataFrame(dict(advances=np.nan, declines=1., unchanged=0., new_highs=1., new_lows=0., eligible=3., above_ma50=2., above_ma200=2., eligible_ma50=3., eligible_ma200=3.), index=idx)
        for changes, reason in (({'above_ma50': 4}, 'BREADTH_MA_LIMIT'), ({'new_highs': 4}, 'BREADTH_LIMIT'), ({'eligible_ma200': 4}, 'BREADTH_LIMIT'), ({'eligible': 0}, 'EMPTY_BREADTH_POPULATION'), ({'declines': 2, 'unchanged': 2}, 'BREADTH_COVERAGE')):
            f = base.assign(**changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, reason):
                r.breadth(f, pd.Series(100., index=idx), population_id='TEST_COHORT')
        self.assertTrue(r.breadth(base, pd.Series(100., index=idx), population_id='TEST_COHORT').ad_line.isna().all())

    def test_breadth_ma_denominators_and_signed_credit(self):
        idx = pd.bdate_range('2020-01-01', periods=2)
        f = pd.DataFrame(dict(advances=2.0, declines=1.0, unchanged=0.0, new_highs=1.0, new_lows=0.0, eligible=3.0, above_ma50=2.0, above_ma200=1.0, eligible_ma50=2.0, eligible_ma200=1.0), index=idx)
        a = r.breadth(f, pd.Series(100.0, index=idx), population_id='TEST_COHORT')
        self.assertEqual(a.above_ma200_fraction.iloc[0], 1)
        self.assertEqual(a.above_ma50_fraction.iloc[0], 1)
        f['above_ma200'] = 2
        with self.assertRaisesRegex(ValueError, 'BREADTH_MA_LIMIT'):
            r.breadth(f, pd.Series(100.0, index=idx), population_id='TEST_COHORT')
        c = r.credit(pd.DataFrame(dict(hy_oas=3.0, ig_oas=-0.01, ccc_oas=10.0), index=idx))
        self.assertEqual(c.ig_oas_bp.iloc[0], -1)

    def test_inverted_and_duplicate_grid_refused(self):
        idx = pd.bdate_range('2020-01-01', periods=2)
        f = pd.DataFrame(dict(hy_oas=3.0, ig_oas=1.0, ccc_oas=10.0), index=idx)
        for x in (f.iloc[::-1], pd.concat([f.iloc[:1], f.iloc[:1]])):
            with self.assertRaisesRegex(ValueError, 'DATE_GRID'):
                r.credit(x)

    def test_credit_not_universal_signal(self):
        idx = pd.bdate_range('2020-01-01', periods=260)
        f = pd.DataFrame(dict(hy_oas=3.0, ig_oas=1.0, ccc_oas=10.0), index=idx)
        a = r.credit(f)
        self.assertEqual(a.hy_oas_bp.iloc[0], 300)
        self.assertEqual(a.ccc_minus_hy_bp.iloc[0], 700)
        self.assertTrue(a.hy_oas_past_252_z.isna().all())
        self.assertEqual(a.hy_above_4pp_USER_HYPOTHESIS.iloc[0], 0)
from tools import a4_regime_context as c

def event(day, rate, effective=None, action='NO_CHANGE'):
    return dict(announced_at=day + 'T19:00:00+00:00', available_at=day + 'T19:00:00+00:00', effective_on=effective or day, target_lower=rate - 0.25, target_upper=rate, balance_sheet_action=action, original_sha256='a' * 64)

def ss():
    return [dict(session=x, close_utc=x + 'T20:00:00+00:00') for x in ('2020-03-03', '2020-03-04', '2020-03-05')]

class RegimeContext(unittest.TestCase):

    def test_late_old_policy_does_not_restore_superseded_target(self):
        older = event('2020-03-03', 2.)
        older['available_at'] = '2020-03-05T19:00:00+00:00'
        newer = event('2020-03-04', 1.5)
        result = c.policy([older, newer], ss())
        self.assertTrue(np.isnan(result.announced_target_mid.iloc[0]))
        self.assertEqual(result.announced_target_mid.iloc[1], 1.375)
        self.assertEqual(result.announced_target_mid.iloc[2], 1.375)
        self.assertEqual(result.effective_target_mid.iloc[2], 1.375)
        self.assertEqual(result.latest_announced_change_bp.iloc[2], -50.)
        self.assertEqual(result.consecutive_hike_decisions.iloc[2], 0)
        pd.testing.assert_frame_equal(c.policy([newer], ss()).iloc[:2], result.iloc[:2])
        pd.testing.assert_frame_equal(c.policy([newer, older], ss()), result)

    def test_effective_chronology_and_announcement_conflicts(self):
        older = event('2020-03-03', 2., effective='2020-03-05')
        newer = event('2020-03-04', 1.5)
        result = c.policy([older, newer], ss())
        self.assertEqual(result.announced_target_mid.iloc[-1], 1.375)
        self.assertEqual(result.effective_target_mid.iloc[-1], 1.875)
        conflict = event('2020-03-03', 1.)
        conflict['available_at'] = '2020-03-04T19:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_ANNOUNCEMENT'):
            c.policy([older, conflict], ss())

    def test_batch_availability_is_not_policy_identity(self):
        older, newer = event('2020-03-03', 2.), event('2020-03-04', 1.5)
        for e in (older, newer):
            e['available_at'] = '2020-03-05T19:00:00+00:00'
        result = c.policy([older, newer, older], ss())
        self.assertTrue(result.announced_target_mid.iloc[:2].isna().all())
        self.assertEqual(result.announced_target_mid.iloc[-1], 1.375)
        self.assertEqual(result.latest_announced_change_bp.iloc[-1], -50.)
        self.assertEqual(result.consecutive_cut_decisions.iloc[-1], 1)
        pd.testing.assert_frame_equal(c.policy([newer, older], ss()), result)

    def test_announced_and_effective_are_separate(self):
        a = c.policy([event('2020-02-01', 1.75), event('2020-02-02', 2), event('2020-03-03', 1.5, effective='2020-03-04')], ss())
        self.assertEqual(a.announced_target_mid.iloc[0], 1.375)
        self.assertEqual(a.effective_target_mid.iloc[0], 1.875)
        self.assertEqual(a.effective_target_mid.iloc[1], 1.375)
        self.assertEqual(a.latest_announced_change_bp.iloc[0], -50)
        self.assertTrue(a.first_cut_of_known_cycle.iloc[0])
        self.assertTrue(a.qe_probability.isna().all())

    def test_unknown_first_cut_not_guessed(self):
        a = c.policy([event('2020-02-01', 2), event('2020-03-03', 1.5)], ss())
        self.assertTrue(a.first_cut_of_known_cycle.isna().all())

    def test_future_event_never_changes_past(self):
        past = [event('2020-02-01', 2)]
        pd.testing.assert_frame_equal(c.policy(past, ss()), c.policy(past + [event('2020-03-10', 1)], ss()))

    def test_exact_available_clock(self):
        e = event('2020-03-03', 1.5)
        e['available_at'] = '2020-03-03T20:00:00.000001+00:00'
        a = c.policy([e], ss())
        self.assertTrue(np.isnan(a.announced_target_mid.iloc[0]))
        self.assertEqual(a.announced_target_mid.iloc[1], 1.375)

    def test_policy_rejects_naive_clock_conflicts_and_early_effect(self):
        for change in ({'available_at': '2020-03-03T20:00:00'}, {'effective_on': '2020-03-02'}, {'target_lower': 10}, {'balance_sheet_action': 'INFERRED_FROM_ASSETS'}):
            e = event('2020-03-03', 2)
            e.update(change)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    c.policy([e], ss())
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_ANNOUNCEMENT'):
            c.policy([event('2020-03-03', 2), event('2020-03-03', 1)], ss())

    def test_holds_break_consecutive_not_first_cut_context(self):
        events = [event('2020-02-01', 1), event('2020-02-02', 1.25), event('2020-02-03', 1.5), event('2020-02-04', 1.5), event('2020-03-03', 1)]
        a = c.policy(events, ss())
        self.assertTrue(a.first_cut_of_known_cycle.iloc[0])
        self.assertEqual(a.consecutive_hike_decisions.iloc[0], 0)
        self.assertEqual(a.consecutive_cut_decisions.iloc[0], 1)

    def test_lei_user_streak_and_versioned_rule(self):
        p = pd.period_range('2020-01', periods=7, freq='M')
        values = pd.Series(np.linspace(100, 97, 7), index=p)
        a = c.lei(values, 49, method_version='2026_3DS_MINUS4.3', annualized_threshold=-0.043)
        self.assertEqual(a['consecutive_decline_months'], 6)
        self.assertTrue(a['six_consecutive_declines_USER_HYPOTHESIS'])
        self.assertTrue(a['depth_diffusion_threshold_condition'])
        self.assertFalse(a['official_recession_prediction'])

    def test_lei_gap_never_imputed_and_missing_diffusion_unknown(self):
        p = pd.period_range('2020-01', periods=8, freq='M')
        values = pd.Series(np.linspace(100, 98, 8), index=p).drop(p[4])
        a = c.lei(values, None, method_version='A', annualized_threshold=-0.043)
        self.assertIsNone(a['six_month_annualized_growth'])
        self.assertIsNone(a['depth_diffusion_threshold_condition'])
        self.assertEqual(a['consecutive_decline_months'], 2)
        self.assertIsNone(a['six_consecutive_declines_USER_HYPOTHESIS'])

    def test_lei_unknown_latest_and_partial_decline_window(self):
        for at in (-1, -4):
            values = pd.Series(np.linspace(100, 97, 8), index=pd.period_range('2020-01', periods=8, freq='M'))
            values.iloc[at] = np.nan
            result = c.lei(values, 40, method_version='A', annualized_threshold=-.043)
            with self.subTest(at=at):
                self.assertIsNone(result['six_consecutive_declines_USER_HYPOTHESIS'])
                self.assertEqual(result['decline_count_basis'], 'CONFIRMED_CONTIGUOUS_SUFFIX_ONLY')
        values = pd.Series(np.arange(8) + 100., index=pd.period_range('2020-01', periods=8, freq='M'))
        self.assertFalse(c.lei(values, 40, method_version='A', annualized_threshold=-.043)['six_consecutive_declines_USER_HYPOTHESIS'])

    def test_month_span_is_bounded_before_allocating(self):
        from unittest.mock import patch
        series = pd.Series([1., 2.], index=pd.PeriodIndex(['1900-01', '2100-01'], freq='M'))
        with patch.object(c.pd, 'period_range', side_effect=AssertionError('must reject before expansion')):
            with self.assertRaisesRegex(ValueError, 'MONTHLY_EXPANSION_BUDGET'):
                c.monthly(series)

    def test_lei_threshold_units_and_method_required(self):
        values = pd.Series(np.arange(7) + 100.0, index=pd.period_range('2020-01', periods=7, freq='M'))
        for version, threshold, diffusion in (('', -0.043, 40), ('A', -4.3, 40), ('A', -0.043, 101)):
            with self.assertRaises(ValueError):
                c.lei(values, diffusion, method_version=version, annualized_threshold=threshold)

    def test_cape_reference_excludes_current_and_counts_complete(self):
        values = pd.Series(20.0, index=pd.period_range('2000-01', periods=121, freq='M'))
        values.iloc[-1] = 40
        a = c.valuation(values, up_revisions=5, down_revisions=3, unchanged_revisions=2, eligible_estimates=10)
        self.assertEqual(a['cape_prior_120m_percentile'], 1)
        self.assertEqual(a['earnings_revision_breadth'], 0.2)
        self.assertFalse(a['automatic_valuation_bear_trigger'])
        with self.assertRaisesRegex(ValueError, 'REVISION_COVERAGE'):
            c.valuation(values, up_revisions=5, down_revisions=3, unchanged_revisions=1, eligible_estimates=10)

    def test_bad_monthly_order_and_empty(self):
        values = pd.Series(20.0, index=pd.period_range('2000-01', periods=8, freq='M'))
        for value in (values.iloc[::-1], values.iloc[:0]):
            with self.assertRaises(ValueError):
                c.monthly(value)

class HypothesisRegister(unittest.TestCase):

    def test_versioned_groups_priorities_and_closed_authority(self):
        import json
        registry = json.loads((REPO / 'docs/a4_regime_hypotheses_v1.json').read_text(encoding='utf-8'))
        expected = {'CURVE', 'INTERNALS', 'CREDIT', 'POLICY', 'VALUATION_EARNINGS', 'LEADING_LABOR', 'SECTOR_ROTATION'}
        self.assertEqual({item['id'] for item in registry['groups']}, expected)
        self.assertEqual(len(registry['groups']), 7)
        self.assertTrue(all(item['priority'] in {'P0', 'P1'} and item['bear_hypothesis'] and item['bull_hypothesis'] for item in registry['groups']))
        for name in ('probabilities_calibrated', 'approved_model_changed', 'priorities_are_investment_weights', 'derived_features_are_independent_sources', 'source_or_PIT_or_training_admitted', 'native_risk_readiness_changed'):
            self.assertFalse(registry[name], name)
        self.assertFalse(next(item for item in registry['sentiment'] if item['id'] == 'CNN_FEAR_GREED')['independent_vote'])

if __name__ == '__main__':
    unittest.main()
