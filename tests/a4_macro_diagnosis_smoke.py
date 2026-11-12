"""Condition explanations preserve original clocks and incumbent forecast gates."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import a4_macro_diagnosis as d,market_analysis_engine as m
from tools import a4_liquidity_analysis as a
from tests.a4_liquidity_analysis_smoke import rows,NOW,analyze,raw


def report():
    panel={}
    for sid,values in [('DGS10',[4.0,4.2]),('DFII10',[2.0,1.9])]:
        row=rows(sid,list(zip(['2026-11-05','2026-11-06'],values)))
        point=a.summarize(row,NOW)
        point['changes']['5']=dict(point['changes']['1'])
        panel[point['logical_id']]=point
    return dict(cutoff=NOW,session='2026-11-06',macro_direction_inputs=panel,
        market_assessment=dict(status='DATA_BLOCKED',ready_axis_count=0,blockers=['NATIVE_INPUTS']),
        horizon_outlook=[dict(horizon_sessions=h,direction='INSUFFICIENT_EVIDENCE',
            blockers=['REVIEWED_HISTORICAL_RELATIONSHIP_RELEASE_REQUIRED']) for h in a.HORIZONS])


class DiagnosisTests(unittest.TestCase):
    def test_nominal_real_counter_evidence_remains_mixed_and_uses_bp(self):
        out=d.diagnose(report())['macro_diagnosis']
        family=next(r for r in out['windows']['SHORT']['families'] if r['family']=='rates')
        self.assertEqual(family['observed_pressure'],'MIXED')
        self.assertEqual(family['status'],'OBSERVED')
        self.assertAlmostEqual(family['measures'][0]['change'],20)
        self.assertAlmostEqual(family['measures'][1]['change'],-10)
        self.assertEqual(family['measures'][0]['change_unit'],'basis_points')
        self.assertFalse(family['independent_risk_vote'])
        self.assertEqual(len(family['measures'][0]['evidence'][0]['original_sha256']),64)

    def test_missing_member_never_becomes_neutral_or_complete(self):
        source=report();del source['macro_direction_inputs']['real_yield_10y']
        out=d.diagnose(source)['macro_diagnosis']
        family=next(r for r in out['windows']['SHORT']['families'] if r['family']=='rates')
        self.assertEqual(family['status'],'PARTIAL')
        self.assertEqual(family['missing'],['real_yield_10y'])
        self.assertEqual(family['measures'][1]['status'],'INSUFFICIENT_EVIDENCE')
        self.assertEqual(out['native_ready_axes'],0)
        self.assertEqual(len(out['completion_blockers']),2)

    def test_future_and_stale_observations_cannot_explain_current_conditions(self):
        for key,value in [('available_at','2026-12-01T00:00:00Z'),
                          ('observation_date','2026-12-01'),('observation_date','2025-01-01'),
                          ('status','MISSING')]:
            with self.subTest(key=key,value=value):
                source=report();source['macro_direction_inputs']['yield_10y'][key]=value
                result=d.diagnose(source)['macro_diagnosis']['windows']['SHORT']
                item=next(r for r in result['families'] if r['family']=='rates')['measures'][0]
                self.assertIsNone(item['change']);self.assertFalse(item['evidence'])

    def test_long_horizon_does_not_relabel_short_history_as_forecast(self):
        source=report();before=copy.deepcopy(source['horizon_outlook']);d.diagnose(source)
        for old,new in zip(before,source['horizon_outlook']):
            self.assertEqual(new['direction'],old['direction'])
            self.assertEqual(new['blockers'],old['blockers'])
            self.assertFalse(new['current_conditions_are_return_forecast'])
        self.assertEqual(source['horizon_outlook'][-1]['current_conditions_window'],'LONG')
        self.assertTrue(source['macro_diagnosis']['windows']['LONG']['missing_families'])

    def test_condition_annotation_cannot_replace_reviewed_release(self):
        source=report();source['horizon_outlook'][0].update(direction='HEADWIND',evidence=['fixed-reviewed-trial'])
        source['learning_provenance']=dict(status='EXTERNALLY_REVIEWED_FIXED_RELEASE')
        d.diagnose(source)
        self.assertEqual(source['horizon_outlook'][0]['direction'],'HEADWIND')
        self.assertEqual(source['horizon_outlook'][0]['evidence'],['fixed-reviewed-trial'])
        self.assertEqual(len(source['macro_diagnosis']['completion_blockers']),1)
        self.assertTrue(source['macro_diagnosis']['diagnosis_only'])
        self.assertFalse(source['macro_diagnosis']['portfolio_effect_allowed'])

    def test_weekly_balance_quantity_and_basis_are_preserved(self):
        points=rows('WRESBAL',[('2026-10-28',2900000),('2026-11-04',3000000)])
        point=a.summarize(points,NOW)
        measure=d.measurement({'reserves_week_average':point},'reserves_week_average',1,-1,NOW)
        self.assertEqual(measure['change'],100000)
        self.assertEqual(measure['change_unit'],'millions_usd')
        self.assertEqual(measure['pressure'],'EASING')
        self.assertEqual(measure['evidence'][0]['measurement_basis'],'WEEK_AVERAGE')
        self.assertIsNone(d.measurement({'reserves_week_average':point},'reserves_week_average',4,-1,NOW)['change'])

    def test_overflow_and_null_changes_do_not_produce_pressure(self):
        for value in (None,float('nan'),float('inf'),1e308):
            source=report();point=source['macro_direction_inputs']['yield_10y'];point['changes']['5']['value']=value
            result=d.measurement({'yield_10y':point},'yield_10y',5,1,NOW)
            self.assertIsNone(result['pressure'])

    def test_funding_differences_are_one_family_and_keep_conflicting_changes(self):
        source=report();spreads={}
        for key,change in [('sofr_minus_iorb',2),('effr_minus_iorb',-1)]:
            spreads[key]=dict(status='OBSERVED',value=1,observation_date='2026-11-06',changes_bp={'5':change},original_sha256=['a'*64])
        source['funding']=dict(spreads=spreads)
        result=d.funding(source,5)
        self.assertEqual(result['observed_pressure'],'MIXED')
        self.assertFalse(result['independent_risk_vote'])
        for row in spreads.values():row['observation_date']='2026-10-01'
        self.assertEqual(d.funding(source,5)['observed_pressure'],'INSUFFICIENT_EVIDENCE')

    def test_actual_v2_path_and_markdown_preserve_native_block(self):
        result=analyze([('fred:DGS10',raw('DGS10',[('2026-11-05',4),('2026-11-06',4.2)]))])
        self.assertEqual(result['status'],'DATA_BLOCKED')
        self.assertEqual(result['macro_diagnosis']['native_risk_status'],'DATA_BLOCKED')
        self.assertEqual(result['content_sha256'],m.context.digest({k:v for k,v in result.items() if k!='content_sha256'}))
        self.assertIn('Observed macro conditions',m.render_report(result))
        self.assertTrue(result['macro_diagnosis']['missing_consumption'])
        self.assertIn('a4_macro_diagnosis.py',m.implementation_identity())

    def test_identical_input_is_deterministic_and_source_report_is_not_rewritten(self):
        source=report();original=copy.deepcopy(source['macro_direction_inputs'])
        self.assertEqual(d.diagnose(copy.deepcopy(source)),d.diagnose(copy.deepcopy(source)))
        d.diagnose(source);self.assertEqual(source['macro_direction_inputs'],original)


if __name__=='__main__':unittest.main()
