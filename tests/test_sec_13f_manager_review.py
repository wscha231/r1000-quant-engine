from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sec_13f_manager_policy_fixture import CUT, metric_records, active_members, histories
from tools.run_sec_13f_manager_review import evaluate as managers


def manager_bundle():
    return {
        'schema_version': '13f-manager-review-v1',
        'fixture_kind': 'SYNTHETIC_TEST_NOT_MARKET_DATA',
        'decision_cutoff': CUT,
        'expected_manager_ids': [f'SYNTHETIC_M{i:02}' for i in range(1, 21)],
        'records': metric_records(),
        'active_members': active_members(),
        'quarterly_history': histories(),
        'decision_ledger': [],
        'history_complete': True,
        'decision_ledger_complete': True,
        'review_kind': 'SEMIANNUAL',
    }


class ManagerReviewTests(unittest.TestCase):
    def test_manager_chain_end_to_end_proposals_only(self):
        out = managers(manager_bundle())
        self.assertEqual(len(out['cohort_review']['proposals']), 2)
        self.assertFalse(out['active_roster_changed'])
        self.assertFalse(out['full_clone_backtest_executed'])
        self.assertTrue(out['skill_inputs_exclude_aum_and_seed_priority'])

    def test_proposed_incoming_sources_not_assigned_active_influence(self):
        out = managers(manager_bundle())
        for proposal in out['cohort_review']['proposals']:
            self.assertNotIn(proposal['incoming_manager'], out['existing_cohort_influence_diagnostic']['weights'])

    def test_no_real_metrics_produces_no_ranking(self):
        bundle = manager_bundle()
        bundle['records'] = []
        out = managers(bundle)
        self.assertEqual(out['status'], 'INCOMPLETE_MANAGER_EVIDENCE')
        self.assertEqual(out['ranking']['ranking'], [])
        self.assertEqual(out['cohort_review']['proposals'], [])
        self.assertEqual(out['existing_cohort_influence_diagnostic']['weights'], {})

    def test_aum_and_seed_priority_do_not_change_ranking(self):
        base = managers(manager_bundle())['ranking']['ranking']
        bundle = manager_bundle()
        for row in bundle['records']:
            row['latest_13f_aum_usd'] = 10**18
            row['research_priority'] = 1
        changed = managers(bundle)['ranking']['ranking']
        self.assertEqual([(r['economic_manager_id'], r['score']) for r in base],
                         [(r['economic_manager_id'], r['score']) for r in changed])

    def test_cli_exit_two_for_missing_metrics_and_no_canonical_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bundle = manager_bundle()
            bundle['records'] = []
            input_path = root / 'input.json'
            input_path.write_text(json.dumps(bundle), encoding='utf-8')
            protected = root / 'managers.csv'
            protected.write_bytes(b'USER_OWNED_UNCHANGED\n')
            result = subprocess.run(
                [sys.executable, str(ROOT / 'tools/run_sec_13f_manager_review.py'),
                 '--input', str(input_path), '--output-dir', str(root / 'out')],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(protected.read_bytes(), b'USER_OWNED_UNCHANGED\n')
            self.assertIn('INCOMPLETE_MANAGER_EVIDENCE', result.stdout)

    def test_malformed_json_cli_blocks_without_publication(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            input_path = root / 'input.json'
            input_path.write_text('not-json', encoding='utf-8')
            result = subprocess.run(
                [sys.executable, str(ROOT / 'tools/run_sec_13f_manager_review.py'),
                 '--input', str(input_path), '--output-dir', str(root / 'out')],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse((root / 'out').exists())

    def test_unknown_policy_key_not_silently_ignored(self):
        bundle = manager_bundle()
        bundle['policy'] = {'new_magic_alpha': True}
        with self.assertRaises(TypeError):
            managers(bundle)

    def test_complete_scores_missing_ledger_not_green(self):
        bundle = manager_bundle()
        bundle['decision_ledger_complete'] = False
        self.assertEqual(managers(bundle)['status'], 'BLOCKED_COHORT_REVIEW')


if __name__ == '__main__':
    unittest.main()
