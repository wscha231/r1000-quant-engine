"""Offline regression fixtures, not investment performance evidence."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'tools/universe_integrity/financial_coverage.py'
spec = importlib.util.spec_from_file_location('coverage_audit', PATH)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def fact(start, end, value, filed='2026-08-01', accn='0001'):
    return dict(start=start, end=end, val=value, filed=filed, accn=accn, form='10-Q')


def payload(revenues, income=None, currencies=None):
    return {'facts': {'us-gaap': {
        'Revenues': {'units': currencies or {'USD': revenues}},
        'NetIncomeLoss': {'units': {'USD': income or []}}
    }}}


class UniverseIntegrityTests(unittest.TestCase):
    def test_queue_covers_more_than_thousand(self):
        members = [{'ticker': 'T'+str(i)} for i in range(1100)]
        mapping = {str(i): {'ticker':'T'+str(i), 'cik_str':i+1} for i in range(1099)}
        groups, missing = c.issuer_queue(members, mapping)
        self.assertEqual(len(groups), 1099)
        self.assertEqual(missing, [{'ticker':'T1099','reason':'CIK_MISSING'}])
        self.assertEqual(sum(map(len,groups.values()))+len(missing), 1100)

    def test_shared_issuer_one_request(self):
        groups, missing=c.issuer_queue([{'ticker':'BRK.A'},{'ticker':'BRK.B'}], {
          'a':{'ticker':'BRK-A','cik_str':10},'b':{'ticker':'BRK-B','cik_str':10}})
        self.assertEqual(groups, {'0000000010':['BRK.A','BRK.B']})
        self.assertEqual(missing, [])

    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            c.issuer_queue([{'ticker':'A'},{'ticker':'A'}], {})

    def test_ambiguous_cik_retained(self):
        groups, missing=c.issuer_queue([{'ticker':'A'}], {
          'a':{'ticker':'A','cik_str':1},'b':{'ticker':'A','cik_str':2}})
        self.assertEqual(groups,{})
        self.assertEqual(missing[0]['reason'],'CIK_AMBIGUOUS')

    def test_future_revision_cutoff(self):
        old=fact('2024-01-01','2024-03-31',100,'2024-05-01','old')
        later=fact('2024-01-01','2024-03-31',120,'2025-05-01','new')
        self.assertEqual(c.facts_for(payload([old,later]), ['Revenues'], '2024-08-02')[0]['val'],100)
        self.assertEqual(c.facts_for(payload([old,later]), ['Revenues'], '2025-05-02')[0]['val'],120)

    def test_conflicting_fact_version_rejected(self):
        a=fact('2026-01-01','2026-03-31',100)
        with self.assertRaisesRegex(ValueError,'conflicting_fact_version'):
            c.facts_for(payload([a,{**a,'val':120}]), ['Revenues'], '2026-09-11')

    def test_zero_is_observed_not_missing(self):
        revenue=[fact('2026-04-01','2026-06-30',100)]
        report=c.packet(payload(revenue,[fact('2026-04-01','2026-06-30',0)]),'2026-09-11')
        self.assertEqual(report['net_income_quarter'],0)
        self.assertTrue(report['current_quarter_usable'])

    def test_ambiguous_native_currency_not_usd_default(self):
        rows=[fact('2026-04-01','2026-06-30',100)]
        report=c.packet(payload([],currencies={'USD':rows,'TWD':rows}),'2026-09-11')
        self.assertFalse(report['current_quarter_usable'])
        self.assertEqual(report['reason'],'QUARTER_OR_REPORTING_CURRENCY_UNRESOLVED')

    def test_growth_acceleration(self):
        periods=[('2025-01-01','2025-03-31',100),('2025-04-01','2025-06-30',100),
                 ('2026-01-01','2026-03-31',110),('2026-04-01','2026-06-30',130)]
        report=c.packet(payload([fact(*x) for x in periods]), '2026-09-11')
        self.assertAlmostEqual(report['revenue_yoy'],.3)
        self.assertAlmostEqual(report['revenue_growth_acceleration_pp'],20)

    def test_ttm_preserves_all_component_dates(self):
        rows=[fact('2025-01-01','2025-12-31',400,'2026-02-01','annual'),
              fact('2025-01-01','2025-06-30',180,'2026-08-01','restated'),
              fact('2026-01-01','2026-06-30',240,'2026-08-01','current')]
        data=c.facts_for(payload(rows),['Revenues'],'2026-09-11')
        result=c.annualized_flow(data,'us-gaap','USD')
        self.assertEqual(result['value'],460)
        self.assertEqual(result['period_end'],'2026-06-30')
        self.assertEqual(result['latest_component_filed'],'2026-08-01')
        self.assertEqual(len(result['components']),3)

    def test_nonmatching_ytd_not_used(self):
        rows=[fact('2025-01-01','2025-12-31',400),fact('2026-04-01','2026-06-30',120)]
        result=c.annualized_flow(c.facts_for(payload(rows),['Revenues'],'2026-09-11'),'us-gaap','USD')
        self.assertEqual(result['period_end'],'2025-12-31')

    def test_stale_quarter_not_usable(self):
        report=c.packet(payload([fact('2025-01-01','2025-03-31',100)],
                                [fact('2025-01-01','2025-03-31',10)]),'2026-09-11')
        self.assertFalse(report['current_quarter_usable'])
        self.assertFalse(report['historical_pit_verified'])
        self.assertFalse(report['valuation_approved'])

    def test_negative_growth_base_not_percent(self):
        report=c.packet(payload([fact('2025-04-01','2025-06-30',-10),
                                 fact('2026-04-01','2026-06-30',20)]),'2026-09-11')
        self.assertIsNone(report['revenue_yoy'])

    def test_endpoint_rejects_redirect_domain_credentials(self):
        for url in ['http://data.sec.gov/x', 'https://evil.com/x','https://user@data.sec.gov/x']:
            with self.assertRaisesRegex(ValueError,'source_url'):
                c.get_public(url,Path('.'))

if __name__ == '__main__':
    unittest.main()
