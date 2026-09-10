"""Pinned-engine boundary tests; fixture observations are not market results."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import admit_connected_research as m


class Admission(unittest.TestCase):
    def us_engine(self):
        data,_,_=m.load_engine(os.environ['RESEARCH_ENGINE_SOURCE'])
        import research_us_decision
        config=json.loads((Path(__file__).resolve().parents[1]/'docs/research_us_fund_config.json').read_text())
        return data,research_us_decision,config

    def test_us_only_uses_us_allocation_profile_without_kr_fx(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.capture(root)
            p=root/'connection_report.json';r=json.loads(p.read_text());r['market_profile']='US_LISTED_USD_V1';p.write_bytes(m.canonical(r))
            out=m.run(root,os.environ['RESEARCH_ENGINE_SOURCE'])
        self.assertEqual(out['country_caps'],{'US':1.,'KR':0.})
        self.assertEqual(out['target_counts'],{'US':5,'KR':0})
        self.assertTrue(out['workflow']['fx_ready'])
        self.assertIn('target_scope_complete',out['readiness'])
        self.assertNotIn('target_5_plus_2_complete',out['readiness'])
        self.assertIsNone(out['portfolio_weights'])

    def test_us_profile_does_not_discard_kr_input_silently(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.capture(root)
            p=root/'connection_report.json';r=json.loads(p.read_text());r['market_profile']='US_LISTED_USD_V1'
            r['sources'].append(dict(name='KR_current_close',data=dict(selected=[dict(ticker='000010')])));p.write_bytes(m.canonical(r))
            self.assertRaisesRegex(ValueError,'us_profile_foreign_input',m.run,root,os.environ['RESEARCH_ENGINE_SOURCE'])

    def test_us_scope_retains_risk_gates_and_rejects_legacy_mixed_profile(self):
        _,engine,config=self.us_engine();engine.validate_config(config)
        self.assertEqual(config['max_security_weight'],.2)
        self.assertEqual(config['gross_caps']['RISK_ON'],.9)
        config['orders_allowed']=True
        self.assertRaisesRegex(ValueError,'research_safety_flag_invalid',engine.validate_config,config)
        config['orders_allowed']=False;config['target_counts']['KR']=2
        self.assertRaisesRegex(ValueError,'target_count_contract_mismatch',engine.validate_config,config)

    def test_five_us_securities_allocate_with_cash_and_costs_without_kr_fx(self):
        data,engine,config=self.us_engine()
        sys.path.insert(0,str(Path(os.environ['RESEARCH_ENGINE_SOURCE'])/'tests'))
        from research_decision_v1_decision_fixture import with_scenario,context
        from research_decision_v1_fixture import rehash
        bundle=with_scenario();bundle['securities']=[]
        for ticker in ('EXAMA','EXAMB','EXAMC','EXAMD','EXAME'):
            sec=with_scenario(ticker=ticker)['securities'][0]
            sec['blocks']['risk']['payload']['exposures']={kind+':'+ticker:1 for kind in ('industry','theme','customer')}
            rehash(sec['blocks']['risk']);bundle['securities'].append(sec)
        ctx=context();ctx.pop('capital_krw');ctx.update(base_currency='USD',capital_base=100000.,fx={'status':'missing'})
        decision=engine.run_decisions([data.export_market(bundle,'US')],ctx,config)
        p=decision['portfolio_proposal']
        self.assertTrue(decision['readiness']['target_scope_complete'])
        self.assertEqual(len(p['rows']),5);self.assertGreater(p['cash_weight'],0)
        self.assertTrue(all(0<r['target_weight']<=.2 for r in p['rows']))
        f=p['funding']
        self.assertAlmostEqual(sum(f['position_values_base'].values())+f['cash_base']+f['transaction_cost_base'],100000.,places=6)
        self.assertGreater(f['transaction_cost_base'],0.)
        ctx['mode']='EXISTING_BOOK_PROPOSAL';ctx['book']={'positions':{'KR:000010':.1}}
        self.assertRaisesRegex(ValueError,'us_profile_foreign_holding',engine.run_decisions,[data.export_market(bundle,'US')],ctx,config)

    def capture(self,root):
        raw=b'{}';h=m.sha(raw);(root/(h+'.raw')).write_bytes(raw)
        receipts=[dict(raw_sha256=h,bytes=2)]
        (root/'receipts.json').write_bytes(m.canonical(receipts))
        report=dict(schema_version='research-source-connection-v1',data_kind='REAL',source_receipt_count=1,
                    source_receipts_hash=m.sha(m.canonical(receipts)),generated_at='2026-09-10T12:00:00Z',end='2026-09-09',
                    sources=[{'name':'US_prices','data':{'securities':[{'ticker':'NVDA','close':100.,'last':'2026-09-09'}]}}])
        (root/'connection_report.json').write_bytes(m.canonical(report))

    def test_changed_raw_rejected_before_engine(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.capture(root)
            next(root.glob('*.raw')).write_bytes(b'changed')
            self.assertRaisesRegex(ValueError,'raw_source_mutated',m.verify_capture,root)

    def test_incomplete_connected_data_not_allocated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.capture(root)
            r=m.run(root,os.environ['RESEARCH_ENGINE_SOURCE'])
        self.assertFalse(r['readiness']['portfolio_proposal_ready'])
        self.assertEqual(r['workflow']['universe_count'],1)
        self.assertEqual(r['workflow']['market_admitted_count'],0)
        self.assertIsNone(r['portfolio_weights']);self.assertIsNone(r['metrics'])
        self.assertIn('financials:missing',r['coverage'][0]['blockers'])

    def test_receipts_cannot_be_relabelled(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.capture(root)
            p=root/'connection_report.json';r=json.loads(p.read_text());r['source_receipts_hash']='0'*64;p.write_bytes(m.canonical(r))
            self.assertRaisesRegex(ValueError,'receipt_binding',m.verify_capture,root)


if __name__=='__main__':unittest.main()
