#!/usr/bin/env python3
"""Offline adversarial manual pinning tests; no specialist/provider/state writes."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import manual_foundation as manual

BASE = '11163fb3e30125359346102eb2b12c04aa52ae15'
REVIEW_HEAD = 'a' * 40
MOVED_REVIEW_HEAD = 'b' * 40


def independent_hash(value, excluded):
    return hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != excluded},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        paths = set()
        for key in manual.PLAYBOOK_IDS:
            paths.update(manual.required_dependencies(key))
        for row in manual.load_catalog()['entries']:
            paths.update(row['dependency_hashes'])
        for name in paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value, indent=2) + '\n')

    def packet(self, key='L0_RESUME_HANDOFF'):
        _, playbook = manual.load_playbook(key, self.root)
        dependencies = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                        for name in manual.required_dependencies(key, self.root)}
        review_identity = (dict(repository=manual.REVIEW_REPOSITORY, pr_number=593, head_sha=REVIEW_HEAD)
                           if key == 'A6_INDEPENDENT_QA' else None)
        scope = dict(base_sha=BASE, review_identity=copy.deepcopy(review_identity),
                     owner=playbook['owner'], dependencies=dependencies,
                     allowed_files=[], authority=manual.board.AUTHORITY.copy(), authority_tier='T2_PREPARE')
        packet = dict(schema_version='manual-task-packet-v1', task_key='SYNTHETIC-MANUAL-TEST',
            packet_sha256='', playbook_id=key, playbook_version=playbook['playbook_version'],
            playbook_sha256=playbook['playbook_sha256'], owner=playbook['owner'], base_sha=BASE,
            review_identity=copy.deepcopy(review_identity),
            dependencies=copy.deepcopy(dependencies), allowed_files=[],
            toolbox_refs=playbook['toolbox_refs'].copy(), proof_set=playbook['proof_set'].copy(),
            authority=manual.board.AUTHORITY.copy(), authority_tier='T2_PREPARE', mode=playbook['mode'],
            stop_condition=playbook['process']['stop_condition'].copy(),
            output_receipt=dict(schema_version='R1000_WORKER_RESULT_V1', reference='SYNTHETIC_RECEIPT_ONLY'),
            reuse_entries=[])
        return self.bind(packet), scope

    def bind(self, packet):
        packet['packet_sha256'] = independent_hash(packet, 'packet_sha256')
        return packet

    def validate(self, packet, scope, expected_review_head=None):
        if expected_review_head is None and packet['playbook_id'] == 'A6_INDEPENDENT_QA':
            expected_review_head = REVIEW_HEAD
        return manual.validate_packet(packet, scope, expected_base=BASE,
                                      expected_review_head=expected_review_head, root=self.root)

    def rejected(self, packet, scope, reason=None):
        with self.assertRaises(manual.ContractError) as caught:
            self.validate(packet, scope)
        if reason:
            self.assertIn(reason, str(caught.exception))

    def test_all_three_manuals_have_current_hash_and_four_layers(self):
        for key, owner in manual.PLAYBOOK_IDS.items():
            _, row = manual.load_playbook(key, self.root)
            self.assertEqual(row['owner'], owner)
            self.assertEqual(row['playbook_sha256'], independent_hash(row, 'playbook_sha256'))
            for layer in ('process', 'toolbox_refs', 'proof', 'learning'):
                self.assertTrue(row[layer])
            self.assertGreaterEqual(len(row['proof']['checks']), 5)
            self.assertLessEqual(len(row['proof']['checks']), 10)
            packet, scope = self.packet(key)
            result = self.validate(packet, scope)
            self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
            self.assertFalse(result['worker_invoked'])
            self.assertFalse(result['completed_task'])
            self.assertFalse(result['economic_authority'])
            self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})

    def test_stale_version_and_hash_refused_even_after_packet_rebinding(self):
        for field, value in [('playbook_version', '0.0.1'), ('playbook_sha256', 'a' * 64)]:
            packet, scope = self.packet()
            packet[field] = value
            self.rejected(self.bind(packet), scope, 'stale_playbook')

    def test_packet_hash_binds_task_and_every_scope_field(self):
        for field, value in [('task_key', 'RENAMED'), ('playbook_sha256', 'a' * 64),
                             ('output_receipt', {'schema_version': 'R1000_WORKER_RESULT_V1', 'reference': 'OTHER'})]:
            packet, scope = self.packet()
            packet[field] = value
            self.rejected(packet, scope)

    def test_wrong_base_cannot_be_self_attested(self):
        packet, scope = self.packet()
        packet['base_sha'] = scope['base_sha'] = 'b' * 40
        self.rejected(self.bind(packet), scope, 'wrong_base')

    def test_wrong_dependency_cannot_be_rehashed(self):
        packet, scope = self.packet()
        packet['dependencies']['AGENTS.md'] = 'a' * 64
        self.rejected(self.bind(packet), scope, 'wrong_dependency')
        scope['dependencies']['AGENTS.md'] = 'a' * 64
        self.rejected(packet, scope, 'dependency_bytes_changed')

    def test_missing_required_dependency_even_in_matching_scope(self):
        packet, scope = self.packet()
        del packet['dependencies']['AGENTS.md']
        del scope['dependencies']['AGENTS.md']
        self.rejected(self.bind(packet), scope, 'missing_dependency')

    def test_same_head_dirty_toolbox_bytes_are_rejected(self):
        packet, scope = self.packet()
        with (self.root / 'tools/run_agent_board.py').open('a') as stream:
            stream.write('\n# dirty same-head fixture\n')
        self.rejected(packet, scope, 'dependency_bytes_changed')

    def test_authority_escalation_all_existing_flags_and_extra_fields(self):
        for flag in ('execute', 'target', 'broker', 'scheduler', 'promotion', 'peer_dispatch'):
            packet, scope = self.packet()
            packet['authority'][flag] = scope['authority'][flag] = True
            self.rejected(self.bind(packet), scope)
        packet, scope = self.packet()
        packet['authority']['fullrun'] = True
        self.rejected(self.bind(packet), scope)

    def test_boolean_authority_cannot_be_numeric_zero(self):
        packet, scope = self.packet()
        packet['authority']['execute'] = 0
        self.rejected(self.bind(packet), scope)

    def test_authority_tier_cannot_exceed_independent_scope(self):
        packet, scope = self.packet()
        scope['authority_tier'] = 'T0_READ'
        self.rejected(packet, scope, 'authority_tier_escalation')
        packet['authority_tier'] = 'T3_REVERSIBLE_WRITE'
        self.rejected(self.bind(packet), scope)

    def test_source_write_scope_cannot_expand(self):
        packet, scope = self.packet()
        packet['allowed_files'] = ['r1000_config.py']
        self.rejected(self.bind(packet), scope, 'file_scope_escalation')

    def test_a6_remains_read_only_even_if_scope_lists_write_paths(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        packet['allowed_files'] = scope['allowed_files'] = ['r1000_config.py']
        self.rejected(self.bind(packet), scope, 'qa_source_write')

    def test_owner_mode_toolbox_proof_and_stop_condition_cannot_be_waived(self):
        for field, value in [('owner', 'A1'), ('mode', 'READ_ONLY'), ('toolbox_refs', []),
                             ('proof_set', ['ONLY_ONE']), ('stop_condition', ['NO_STOP'])]:
            packet, scope = self.packet()
            packet[field] = value
            self.rejected(self.bind(packet), scope)

    def test_exact_paths_reject_traversal_globs_aliases_and_symlinks(self):
        for path in ('../AGENTS.md', '/tmp/AGENTS.md', 'docs/*', 'docs/./a', 'C:\\a', 'docs//a'):
            with self.assertRaises(manual.ContractError):
                manual.path_at(self.root, path)
        alias = self.root / 'alias'
        alias.symlink_to(self.root / 'docs', target_is_directory=True)
        with self.assertRaises(manual.ContractError):
            manual.path_at(self.root, 'alias/pr_reuse_catalog.json')

    def test_superseded_playbook_never_selected(self):
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        old = copy.deepcopy(manifest['playbooks'][0])
        old['status'] = 'SUPERSEDED'
        old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
        current = manifest['playbooks'][0]
        current['playbook_version'] = '1.1.0'
        current['supersedes'] = '1.0.0'
        current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
        manifest['current_versions'][current['playbook_id']] = '1.1.0'
        manifest['playbooks'].append(old)
        self.write(manual.MANIFEST, manifest)
        packet, scope = self.packet()
        self.assertEqual(packet['playbook_version'], '1.1.0')
        packet['playbook_version'] = old['playbook_version']
        packet['playbook_sha256'] = old['playbook_sha256']
        self.rejected(self.bind(packet), scope, 'stale_playbook')

    def test_hash_valid_manifest_with_wrong_current_mapping_refused(self):
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        manifest['current_versions']['L0_RESUME_HANDOFF'] = '9.0.0'
        self.write(manual.MANIFEST, manifest)
        with self.assertRaises(manual.ContractError):
            manual.load_playbook('L0_RESUME_HANDOFF', self.root)

    def test_duplicate_current_manual_or_tampered_manual_refused(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for mutate in ('duplicate', 'tamper'):
            manifest = copy.deepcopy(original)
            if mutate == 'duplicate':
                manifest['playbooks'].append(copy.deepcopy(manifest['playbooks'][0]))
            else:
                manifest['playbooks'][0]['process']['steps'].clear()
            self.write(manual.MANIFEST, manifest)
            with self.assertRaises(manual.ContractError):
                manual.load_playbook('L0_RESUME_HANDOFF', self.root)

    def test_only_requested_seed_groups_and_issue_pr_distinction(self):
        catalog = manual.load_catalog(self.root)
        expected = {1,158,174,267,400,405,423,574,459,473,505,510,516,526,531,556,559,560,577,578,582,583,584,586,591,592}
        actual = {int(n[1:]) for row in catalog['entries'] for n in row['source_metadata']}
        self.assertEqual(actual, expected)
        for row in catalog['entries']:
            if row['source_kind'] == 'ISSUE':
                self.assertEqual(row['source_heads'], {})
        self.assertEqual(catalog['do_not_repeat_registry'], manual.DNR)

    def test_reuse_now_requires_actual_current_bytes(self):
        self.assertTrue(manual.lookup_reuse('group_591', self.root)['allowed'])
        (self.root / 'tools/research_data_access.py').write_text('CHANGED')
        with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed'):
            manual.lookup_reuse('group_591', self.root)

    def test_selective_port_and_historical_are_not_automatic_reuse(self):
        for key in ('group_400_405', 'group_586', 'group_1'):
            self.assertFalse(manual.lookup_reuse(key, self.root)['allowed'])
            packet, scope = self.packet()
            packet['reuse_entries'] = [key]
            self.rejected(self.bind(packet), scope, 'catalog_reuse_not_allowed')

    def test_superseded_catalog_usage_refused(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row.update(classification='SUPERSEDED', superseded_by='group_423_574')
        self.write(manual.CATALOG, catalog)
        packet, scope = self.packet()
        packet['reuse_entries'] = ['group_591']
        self.rejected(self.bind(packet), scope, 'catalog_superseded')

    def test_do_not_repeat_lookup_uses_canonical_registry(self):
        lookup = manual.lookup_reuse('group_174', self.root)
        self.assertFalse(lookup['allowed'])
        self.assertEqual(lookup['blocked_registry_ids'], ['broad_gross_floor'])
        registry = manual.board.read_json(self.root / manual.DNR)
        row = next(r for r in registry['entries'] if r['id'] == 'broad_gross_floor')
        packet, scope = self.packet()
        packet['do_not_repeat_candidate'] = {k: row[k] for k in ('signal', 'mechanism', 'book', 'window')}
        self.rejected(self.bind(packet), scope, 'BLOCKED_DO_NOT_REPEAT')

    def test_catalog_label_cannot_bypass_canonical_do_not_repeat(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_174')
        row['classification'] = 'REUSE_NOW'
        self.write(manual.CATALOG, catalog)
        packet, scope = self.packet()
        packet['reuse_entries'] = ['group_174']
        self.rejected(self.bind(packet), scope, 'catalog_reuse_not_allowed')

    def test_catalog_change_invalidates_existing_packet(self):
        packet, scope = self.packet()
        catalog = manual.load_catalog(self.root)
        catalog['entries'][0]['next_use'] = 'UPDATED'
        self.write(manual.CATALOG, catalog)
        self.rejected(packet, scope, 'dependency_bytes_changed')

    def test_duplicate_and_nonfinite_json_refused(self):
        path = self.root / 'invalid.json'
        for text in ('{"task_key":"a","task_key":"b"}', '{"x":NaN}'):
            path.write_text(text)
            with self.assertRaises(manual.ContractError):
                manual.board.read_json(path)

    def test_a6_review_identity_accepts_exact_verified_head(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        result = self.validate(packet, scope, REVIEW_HEAD)
        self.assertEqual(result['review_identity']['head_sha'], REVIEW_HEAD)

    def test_a6_old_review_head_refused_after_live_head_moves(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        with self.assertRaisesRegex(manual.ContractError, 'stale_review_head'):
            self.validate(packet, scope, MOVED_REVIEW_HEAD)

    def test_common_lessons_ledger_is_required_for_a1_and_a6(self):
        for key in ('A1_SOURCE_ADMISSION_REFRESH', 'A6_INDEPENDENT_QA'):
            self.assertIn('docs/AGENT_SHARED_LESSONS_LEDGER.md',
                          manual.required_dependencies(key, self.root))
            packet, scope = self.packet(key)
            self.validate(packet, scope)

    def test_lessons_ledger_change_invalidates_old_packet(self):
        packet, scope = self.packet('A1_SOURCE_ADMISSION_REFRESH')
        with (self.root / 'docs/AGENT_SHARED_LESSONS_LEDGER.md').open('a') as stream:
            stream.write('\n# NEW DURABLE LESSON\n')
        self.rejected(packet, scope, 'dependency_bytes_changed')

    def test_superseded_classification_with_successor_is_valid_but_not_reusable(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row.update(classification='SUPERSEDED', superseded_by='group_423_574')
        self.write(manual.CATALOG, catalog)
        manual.load_catalog(self.root)
        with self.assertRaisesRegex(manual.ContractError, 'catalog_superseded'):
            manual.lookup_reuse('group_591', self.root)

    def test_reuse_now_with_superseded_by_is_invalid_catalog(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row['superseded_by'] = 'group_423_574'
        self.write(manual.CATALOG, catalog)
        with self.assertRaisesRegex(manual.ContractError, 'catalog_supersedes_invariant'):
            manual.load_catalog(self.root)

    def test_do_not_repeat_coverage_and_semantic_exceptions_are_preserved(self):
        registry = manual.board.read_json(self.root / manual.DNR)
        row = next(r for r in registry['entries'] if r['id'] == 'broad_gross_floor')
        base = {k: row[k] for k in ('signal', 'mechanism', 'book', 'window')}
        for exception in (
            dict(component_coverage_increase_pp=5.0),
            dict(semantics_changed=True, change_note='Different application semantics')
        ):
            packet, scope = self.packet()
            packet['do_not_repeat_candidate'] = {**base, **exception}
            result = self.validate(self.bind(packet), scope)
            self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')

    def test_do_not_repeat_invalid_exception_still_blocks(self):
        registry = manual.board.read_json(self.root / manual.DNR)
        row = next(r for r in registry['entries'] if r['id'] == 'broad_gross_floor')
        packet, scope = self.packet()
        packet['do_not_repeat_candidate'] = {
            **{k: row[k] for k in ('signal', 'mechanism', 'book', 'window')},
            'semantics_changed': True, 'change_note': '   '
        }
        self.rejected(self.bind(packet), scope, 'BLOCKED_DO_NOT_REPEAT')

    def test_prospective_explicit_allowed_file_is_permitted(self):
        packet, scope = self.packet()
        future = 'docs/future_manual_output.json'
        packet['allowed_files'] = scope['allowed_files'] = [future]
        result = self.validate(self.bind(packet), scope)
        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertFalse((self.root / future).exists())

    def test_existing_directory_cannot_be_allowed_file_scope(self):
        packet, scope = self.packet()
        packet['allowed_files'] = scope['allowed_files'] = ['docs']
        self.rejected(self.bind(packet), scope, 'allowed_file_is_directory')

    def test_current_catalog_pr_issue_provenance_is_structurally_valid(self):
        catalog = manual.load_catalog(self.root)
        for row in catalog['entries']:
            if row['source_kind'] == 'ISSUE':
                self.assertEqual(row['source_heads'], {})
                self.assertTrue(all(meta['kind'] == 'ISSUE' for meta in row['source_metadata'].values()))
            else:
                self.assertEqual(set(row['source_heads']), set(row['source_metadata']))
                self.assertTrue(all(meta['kind'] == 'PR' for meta in row['source_metadata'].values()))

    def test_fake_issue_head_or_pr_kind_metadata_is_rejected(self):
        original = manual.load_catalog(self.root)
        for mutate in ('head', 'kind'):
            catalog = copy.deepcopy(original)
            row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_505')
            if mutate == 'head':
                row['source_heads'] = {'#505': 'a' * 40}
                reason = 'catalog_issue_has_source_head'
            else:
                row['source_metadata']['#505']['kind'] = 'PR'
                reason = 'catalog_source_identity'
            self.write(manual.CATALOG, catalog)
            with self.assertRaisesRegex(manual.ContractError, reason):
                manual.load_catalog(self.root)
        self.write(manual.CATALOG, original)

    def test_reuse_now_consumed_paths_are_all_hash_pinned(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        consumed = set(row['current_equivalent']) | set(row['toolbox_refs'])
        self.assertTrue(consumed.issubset(row['dependency_hashes']))
        self.assertTrue(manual.lookup_reuse('group_591', self.root)['allowed'])

    def test_reuse_now_unpinned_consumed_path_is_rejected(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row['toolbox_refs'].append('AGENTS.md')
        self.write(manual.CATALOG, catalog)
        with self.assertRaisesRegex(manual.ContractError, 'catalog_unpinned_reuse_path'):
            manual.load_catalog(self.root)

    def test_playbook_successor_version_must_increase(self):
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        current = manifest['playbooks'][0]
        old = copy.deepcopy(current)
        old['status'] = 'SUPERSEDED'
        old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
        current['playbook_version'] = '1.1.0'
        current['supersedes'] = '1.0.0'
        current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
        manifest['current_versions'][current['playbook_id']] = '1.1.0'
        manifest['playbooks'].append(old)
        self.write(manual.MANIFEST, manifest)
        _, row = manual.load_playbook(current['playbook_id'], self.root)
        self.assertEqual(row['playbook_version'], '1.1.0')

    def test_playbook_version_downgrade_or_live_predecessor_is_rejected(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for case in ('downgrade', 'predecessor_current'):
            manifest = copy.deepcopy(original)
            current = manifest['playbooks'][0]
            old = copy.deepcopy(current)
            if case == 'downgrade':
                old['playbook_version'] = '1.0.0'
                old['status'] = 'SUPERSEDED'
                old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
                current['playbook_version'] = '0.9.0'
                current['supersedes'] = '1.0.0'
                reason = 'playbook_version_not_increasing'
            else:
                old['playbook_version'] = '0.9.0'
                old['status'] = 'HISTORICAL'
                old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
                current['playbook_version'] = '1.0.0'
                current['supersedes'] = '0.9.0'
                reason = 'predecessor_not_superseded'
            current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
            manifest['current_versions'][current['playbook_id']] = current['playbook_version']
            manifest['playbooks'].append(old)
            self.write(manual.MANIFEST, manifest)
            with self.assertRaisesRegex(manual.ContractError, reason):
                manual.load_playbook(current['playbook_id'], self.root)
        self.write(manual.MANIFEST, original)

    def test_reuse_now_future_expiry_is_allowed(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row['expiry'] = '2099-01-01T00:00:00Z'
        self.write(manual.CATALOG, catalog)
        self.assertTrue(manual.lookup_reuse('group_591', self.root)['allowed'])

    def test_reuse_now_past_or_invalid_expiry_is_rejected(self):
        original = manual.load_catalog(self.root)
        for expiry, reason in (
            ('2000-01-01T00:00:00Z', 'catalog_reuse_expired'),
            ('not-a-time', 'catalog_expiry_invalid'),
        ):
            catalog = copy.deepcopy(original)
            row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
            row['expiry'] = expiry
            self.write(manual.CATALOG, catalog)
            with self.assertRaisesRegex(manual.ContractError, reason):
                manual.load_catalog(self.root)
        self.write(manual.CATALOG, original)

    def test_cli_preflight_is_non_executing_and_wrong_base_returns_two(self):
        # CLI reads canonical repo; packet/scope are ephemeral synthetic artifacts.
        _, row = manual.load_playbook('L0_RESUME_HANDOFF')
        dependencies = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                        for p in manual.required_dependencies(row['playbook_id'])}
        packet, scope = self.packet()
        packet['dependencies'] = copy.deepcopy(dependencies)
        scope['dependencies'] = dependencies
        self.bind(packet)
        self.write('packet.json', packet)
        self.write('scope.json', scope)
        command = [sys.executable, str(ROOT / 'tools/manual_foundation.py'),
                   '--packet', str(self.root / 'packet.json'), '--scope', str(self.root / 'scope.json'),
                   '--expected-base']
        good = subprocess.run(command + [BASE], capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertFalse(json.loads(good.stdout)['worker_invoked'])
        bad = subprocess.run(command + ['b' * 40], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stdout)['status'], 'BLOCKED_INPUT')


def main() -> int:
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ManualTests))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
