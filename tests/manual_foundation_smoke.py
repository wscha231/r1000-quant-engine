#!/usr/bin/env python3
"""Offline adversarial manual pinning tests; no specialist/provider/state writes."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        paths = {'AGENTS.md', 'docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md',
                 'docs/AGENT_SHARED_LESSONS_LEDGER.md', 'docs/MANUAL_FOUNDATION_V1.md'}
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

    def packet(self, key='L0_RESUME_HANDOFF', *, propose_successor=False):
        _, playbook = manual.load_playbook(key, self.root, propose_successor=propose_successor)
        dependencies = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                        for name in manual.required_dependencies(key, self.root,
                                                                  propose_successor=propose_successor)}
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

    def rebind_dependency(self, packet, scope, name):
        digest = hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        packet['dependencies'][name] = scope['dependencies'][name] = digest
        return self.bind(packet)

    def validate(self, packet, scope, expected_review_head=None, *, propose_successor=False):
        if expected_review_head is None and packet['playbook_id'] == 'A6_INDEPENDENT_QA':
            expected_review_head = REVIEW_HEAD
        return manual.validate_packet(packet, scope, expected_base=BASE,
                                      expected_review_head=expected_review_head, root=self.root,
                                      propose_successor=propose_successor)

    def rejected(self, packet, scope, reason=None, *, propose_successor=False):
        with self.assertRaises(manual.ContractError) as caught:
            self.validate(packet, scope, propose_successor=propose_successor)
        if reason:
            self.assertIn(reason, str(caught.exception))

    def reviewed_fixture_anchors(self, manifest, accepted=None):
        # Synthetic independent approval context, captured BEFORE mutations.
        # Never overwrite the actual reviewed baseline or read an input anchor.
        trusted = copy.deepcopy(manual.VERSION_ANCHOR_CONTENT)
        for row in manifest['playbooks']:
            identity = (row['playbook_id'], row['playbook_version'])
            if accepted is None or identity in accepted:
                raw = json.dumps({k: v for k, v in row.items()
                                  if k not in ('status', 'playbook_sha256')},
                                 sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                trusted.setdefault(identity, hashlib.sha256(raw).hexdigest())
        return patch.object(manual, 'VERSION_ANCHOR_CONTENT', trusted)

    def successor_fixture(self, manifest, key, version):
        row = next(r for r in manifest['playbooks'] if r['playbook_id'] == key and r['status'] == 'CURRENT')
        old = copy.deepcopy(row)
        old['status'] = 'SUPERSEDED'
        manifest['playbooks'].append(old)
        row.update(playbook_version=version, supersedes=old['playbook_version'])
        manifest['current_versions'][key] = version
        return row

    def cli_fixture(self, packet, scope, *, propose_successor=False):
        self.write('packet.json', packet)
        self.write('scope.json', scope)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE=str(sys.flags.optimize))
        env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
        prefix = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else [])
        command = prefix + [str(self.root / 'tools/manual_foundation.py'), '--packet',
                            str(self.root / 'packet.json'), '--scope', str(self.root / 'scope.json'),
                            '--expected-base', BASE, '--expected-review-head', REVIEW_HEAD]
        if propose_successor:
            command.append('--propose-successor')
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)

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
        with self.reviewed_fixture_anchors(manifest):
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
        _, row = manual.load_playbook(current['playbook_id'], self.root, propose_successor=True)
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

    def test_semantic_version_core_accepts_canonical_integer_components(self):
        for value, expected in (
            ('0.0.0', (0, 0, 0)), ('0.1.0', (0, 1, 0)), ('1.0.0', (1, 0, 0)),
            ('1.10.3', (1, 10, 3)), ('10.2.15', (10, 2, 15)),
        ):
            with self.subTest(version=value):
                self.assertEqual(manual.semantic_version(value), expected)

    def test_semantic_version_core_refuses_malformed_or_extended_versions(self):
        for value in ('00.0.0', '01.1.0', '1.01.0', '1.1.00', '1..0', '1.0',
                      '1.0.0.0', 'v1.0.0', '+1.0.0', '1.0.0-rc.1', '1.0.0+build',
                      '１.０.０', '1.0.0\n', None, 100):
            with self.subTest(version=value):
                with self.assertRaisesRegex(manual.ContractError, 'invalid_playbook_version'):
                    manual.semantic_version(value)

    def test_zero_padded_successor_is_refused_with_fully_rebound_packet(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for version in ('00.0.0', '01.1.0', '1.01.0', '1.1.00'):
            with self.subTest(version=version):
                self.write(manual.MANIFEST, original)
                packet, scope = self.packet()
                manifest = copy.deepcopy(original)
                current = manifest['playbooks'][0]
                old = copy.deepcopy(current)
                old['status'] = 'SUPERSEDED'
                old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
                current.update(playbook_version=version, supersedes='1.0.0')
                current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
                manifest['playbooks'].append(old)
                manifest['current_versions'][current['playbook_id']] = version
                self.write(manual.MANIFEST, manifest)
                packet.update(playbook_version=version, playbook_sha256=current['playbook_sha256'])
                dependency = hashlib.sha256((self.root / manual.MANIFEST).read_bytes()).hexdigest()
                packet['dependencies'][manual.MANIFEST] = scope['dependencies'][manual.MANIFEST] = dependency
                self.rejected(self.bind(packet), scope, 'invalid_playbook_version')
        self.write(manual.MANIFEST, original)

    def test_successor_numeric_tuple_order_and_reflexive_replacement(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for previous, successor, allowed in (
            ('1.9.0', '1.10.0', True), ('1.0.9', '1.0.10', True),
            ('1.10.0', '1.9.0', False), ('1.0.0', '1.0.0', False),
        ):
            with self.subTest(previous=previous, successor=successor):
                manifest = copy.deepcopy(original)
                current = manifest['playbooks'][0]
                anchor = copy.deepcopy(current)
                old = copy.deepcopy(current)
                old.update(playbook_version=previous, status='SUPERSEDED')
                if manual.semantic_version(previous) > manual.semantic_version(anchor['playbook_version']):
                    old['supersedes'] = anchor['playbook_version']
                    anchor['status'] = 'SUPERSEDED'
                    anchor['playbook_sha256'] = independent_hash(anchor, 'playbook_sha256')
                    manifest['playbooks'].append(anchor)
                old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
                current.update(playbook_version=successor, supersedes=previous)
                current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
                manifest['playbooks'].append(old)
                manifest['current_versions'][current['playbook_id']] = successor
                self.write(manual.MANIFEST, manifest)
                if allowed:
                    with self.reviewed_fixture_anchors(manifest):
                        self.assertEqual(manual.load_playbook(current['playbook_id'], self.root)[1]['playbook_version'], successor)
                else:
                    with self.assertRaises(manual.ContractError):
                        manual.load_playbook(current['playbook_id'], self.root)
        self.write(manual.MANIFEST, original)

    def test_expiry_normal_aware_clock_spellings_preserve_reuse(self):
        original = manual.load_catalog(self.root)
        for expiry in ('2099-01-01T00:00:00Z', '2099-01-01T00:00:00+00:00',
                       '2099-01-01T09:00:00+09:00', '2099-01-01T00:00:00-04:00',
                       '2099-01-01T00:00:00.123456Z', '2099-01-01 00:00:00+00:00',
                       '2099-01-01T00:00:00+23:59', None):
            with self.subTest(expiry=expiry):
                catalog = copy.deepcopy(original)
                next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')['expiry'] = expiry
                self.write(manual.CATALOG, catalog)
                packet, scope = self.packet()
                packet['reuse_entries'] = ['group_591']
                self.assertEqual(self.validate(self.bind(packet), scope)['status'], 'VALIDATED_PREPARE_ONLY')
        self.write(manual.CATALOG, original)

    def test_malformed_expiry_offsets_refuse_reuse_and_rebound_packet(self):
        original = manual.load_catalog(self.root)
        for expiry in ('2099-01-01T00:00:00+00:60', '2099-01-01T00:00:00+01:99',
                       '2099-01-01T00:00:00+99:00', '2099-01-01T00:00:00+24:00',
                       '2099-01-01T00:00:00', '2099-01-01',
                       '2099-01-01T00:00:00+00/00', '2099-01-01X00:00:00Z'):
            with self.subTest(expiry=expiry):
                catalog = copy.deepcopy(original)
                next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')['expiry'] = expiry
                self.write(manual.CATALOG, catalog)
                with self.assertRaisesRegex(manual.ContractError, 'catalog_expiry_invalid'):
                    manual.lookup_reuse('group_591', self.root)
                packet, scope = self.packet()
                packet['reuse_entries'] = ['group_591']
                self.rejected(self.bind(packet), scope, 'catalog_expiry_invalid')
        self.write(manual.CATALOG, original)

    def test_cli_malformed_expiry_returns_two_without_invoking_worker(self):
        for name in ('mission_contract.py', 'r1000_config.py'):
            shutil.copyfile(ROOT / name, self.root / name)
        original = manual.load_catalog(self.root)
        for expiry in ('2099-01-01T00:00:00+00:60', '2099-01-01T00:00:00+01:99'):
            with self.subTest(expiry=expiry):
                catalog = copy.deepcopy(original)
                next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')['expiry'] = expiry
                self.write(manual.CATALOG, catalog)
                packet, scope = self.packet()
                packet['reuse_entries'] = ['group_591']
                self.write('packet.json', self.bind(packet))
                self.write('scope.json', scope)
                result = subprocess.run([sys.executable, str(self.root / 'tools/manual_foundation.py'),
                    '--packet', str(self.root / 'packet.json'), '--scope', str(self.root / 'scope.json'),
                    '--expected-base', BASE], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output['reason'], 'catalog_expiry_invalid')
                self.assertFalse(output['worker_invoked'])
        self.write(manual.CATALOG, original)

    def test_fixed_operating_contracts_cannot_be_dropped_by_manifest_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        contracts = ('AGENTS.md', 'docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md',
                     'docs/AGENT_SHARED_LESSONS_LEDGER.md', 'docs/MANUAL_FOUNDATION_V1.md')
        for key in manual.PLAYBOOK_IDS:
            for name in contracts:
                with self.subTest(playbook=key, omitted=name):
                    self.write(manual.MANIFEST, original)
                    packet, scope = self.packet(key)
                    manifest = copy.deepcopy(original)
                    manifest['policy_refs'] = [p for p in manifest['policy_refs'] if p != name]
                    self.write(manual.MANIFEST, manifest)
                    self.assertIn(name, manual.required_dependencies(key, self.root))
                    packet['dependencies'].pop(name, None)
                    scope['dependencies'].pop(name, None)
                    self.rejected(self.rebind_dependency(packet, scope, manual.MANIFEST), scope,
                                  'missing_dependency')
        self.write(manual.MANIFEST, original)

    def test_every_operating_contract_byte_change_invalidates_all_playbook_packets(self):
        for key in manual.PLAYBOOK_IDS:
            for name in ('AGENTS.md', 'docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md',
                         'docs/AGENT_SHARED_LESSONS_LEDGER.md', 'docs/MANUAL_FOUNDATION_V1.md'):
                with self.subTest(playbook=key, changed=name):
                    original = (self.root / name).read_bytes()
                    packet, scope = self.packet(key)
                    (self.root / name).write_bytes(original + b'\n# updated contract fixture\n')
                    try:
                        self.rejected(packet, scope, 'dependency_bytes_changed')
                        self.assertEqual(self.validate(self.rebind_dependency(packet, scope, name), scope)
                                         ['status'], 'VALIDATED_PREPARE_ONLY')
                    finally:
                        (self.root / name).write_bytes(original)

    def succession_packet(self, previous, successor, supersedes, *, older=None):
        packet, scope = self.packet()
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        current = manifest['playbooks'][0]
        anchor = copy.deepcopy(current)
        old = copy.deepcopy(current)
        old.update(playbook_version=previous, status='SUPERSEDED')
        if manual.semantic_version(previous) > manual.semantic_version(anchor['playbook_version']):
            old['supersedes'] = anchor['playbook_version']
            if older != anchor['playbook_version']:
                anchor['status'] = 'SUPERSEDED'
                anchor['playbook_sha256'] = independent_hash(anchor, 'playbook_sha256')
                manifest['playbooks'].append(anchor)
        old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
        current.update(playbook_version=successor, supersedes=supersedes)
        current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
        manifest['playbooks'].append(old)
        if older:
            earlier = copy.deepcopy(old)
            earlier.update(playbook_version=older, supersedes=None)
            earlier['playbook_sha256'] = independent_hash(earlier, 'playbook_sha256')
            manifest['playbooks'].append(earlier)
        manifest['current_versions'][current['playbook_id']] = successor
        self.write(manual.MANIFEST, manifest)
        packet.update(playbook_version=successor, playbook_sha256=current['playbook_sha256'])
        return self.rebind_dependency(packet, scope, manual.MANIFEST), scope

    def test_null_predecessor_cannot_bypass_history_after_full_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for successor in ('0.9.0', '1.1.0'):
            with self.subTest(successor=successor):
                self.write(manual.MANIFEST, original)
                packet, scope = self.succession_packet('1.0.0', successor, None)
                self.rejected(packet, scope, 'missing_playbook_predecessor')
        self.write(manual.MANIFEST, original)

    def test_current_version_cannot_skip_a_higher_history_row(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for successor, reason in (('1.1.0', 'playbook_version_not_increasing'),
                                  ('1.3.0', 'playbook_predecessor_not_latest')):
            with self.subTest(successor=successor):
                self.write(manual.MANIFEST, original)
                packet, scope = self.succession_packet('1.2.0', successor, '1.0.0', older='1.0.0')
                self.rejected(packet, scope, reason)
        self.write(manual.MANIFEST, original)

    def test_normal_upgrade_with_explicit_latest_predecessor_validates_packet(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for previous, successor in (('1.0.0', '1.1.0'), ('1.9.0', '1.10.0'),
                                    ('1.0.9', '1.0.10')):
            with self.subTest(previous=previous, successor=successor):
                self.write(manual.MANIFEST, original)
                packet, scope = self.succession_packet(previous, successor, previous)
                with self.reviewed_fixture_anchors(manual.board.read_json(self.root / manual.MANIFEST)):
                    self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
        self.write(manual.MANIFEST, original)

    def test_empty_reuse_selection_still_refuses_rebound_invalid_catalog(self):
        original = manual.load_catalog(self.root)
        for case, reason in (('expired', 'catalog_reuse_expired'),
                             ('head', 'catalog_pr_head_identity'),
                             ('successor', 'catalog_supersedes_invariant'),
                             ('hash', 'catalog_unpinned_reuse_path')):
            with self.subTest(case=case):
                self.write(manual.CATALOG, original)
                packet, scope = self.packet()
                self.assertEqual(packet['reuse_entries'], [])
                catalog = copy.deepcopy(original)
                row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
                if case == 'expired':
                    row['expiry'] = '2000-01-01T00:00:00Z'
                elif case == 'head':
                    row['source_heads']['#591'] = 'invalid-head'
                elif case == 'successor':
                    row['superseded_by'] = 'group_423_574'
                else:
                    row['dependency_hashes'].clear()
                self.write(manual.CATALOG, catalog)
                self.rejected(self.rebind_dependency(packet, scope, manual.CATALOG), scope, reason)
        self.write(manual.CATALOG, original)

    def test_empty_reuse_selection_with_valid_catalog_remains_prepare_only(self):
        packet, scope = self.packet()
        self.assertEqual(packet['reuse_entries'], [])
        result = self.validate(packet, scope)
        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertFalse(result['worker_invoked'])

    def test_empty_toolbox_refuses_all_fully_rebound_playbooks(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for key in manual.PLAYBOOK_IDS:
            with self.subTest(playbook=key):
                self.write(manual.MANIFEST, original)
                packet, scope = self.packet(key)
                manifest = copy.deepcopy(original)
                row = next(r for r in manifest['playbooks'] if r['playbook_id'] == key)
                row['toolbox_refs'] = []
                row['playbook_sha256'] = independent_hash(row, 'playbook_sha256')
                self.write(manual.MANIFEST, manifest)
                packet.update(toolbox_refs=[], playbook_sha256=row['playbook_sha256'])
                # Reproduce the old dependency builder after Toolbox removal.
                shared = set(manifest['policy_refs']) | {
                    manual.MANIFEST, manual.SCHEMA, manual.CATALOG, manual.DNR,
                    'docs/AGENT_SHARED_LESSONS_LEDGER.md', 'tools/manual_foundation.py',
                    'tools/run_agent_board.py', 'tools/check_run287_do_not_repeat.py',
                    'research/control_plane/agent_contracts_v2.yaml',
                    'research/control_plane/task_packet_schema.json'}
                packet['dependencies'] = {p: h for p, h in packet['dependencies'].items() if p in shared}
                scope['dependencies'] = copy.deepcopy(packet['dependencies'])
                self.rejected(self.rebind_dependency(packet, scope, manual.MANIFEST), scope,
                              'manual_layers_missing')
        self.write(manual.MANIFEST, original)

    def test_a1_canonical_toolbox_still_binds_reader_and_source_contract(self):
        packet, scope = self.packet('A1_SOURCE_ADMISSION_REFRESH')
        for path in ('tools/research_data_access.py', 'docs/RESEARCH_DATA_ACCESS.md'):
            self.assertIn(path, packet['toolbox_refs'])
            self.assertIn(path, packet['dependencies'])
        self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')

    def test_invalid_canonical_coverage_threshold_cannot_allow_unchanged_candidate(self):
        original = manual.board.read_json(self.root / manual.DNR)
        row = next(r for r in original['entries'] if r['id'] == 'broad_gross_floor')
        for threshold in (float('nan'), float('inf'), float('-inf'), -1.0, True, None,
                          '-inf', 'NaN', 'Infinity', '-1e309', 'invalid', '', '5.0'):
            with self.subTest(threshold=threshold):
                self.write(manual.DNR, original)
                packet, scope = self.packet()
                packet['do_not_repeat_candidate'] = {k: row[k] for k in ('signal', 'mechanism', 'book', 'window')}
                registry = copy.deepcopy(original)
                registry['reuse_policy']['minimum_component_coverage_increase_pp'] = threshold
                self.write(manual.DNR, registry)
                self.rejected(self.rebind_dependency(packet, scope, manual.DNR), scope)
        for spelling in ('-1e309', '1e309'):
            with self.subTest(raw_numeric_token=spelling):
                self.write(manual.DNR, original)
                packet, scope = self.packet()
                packet['do_not_repeat_candidate'] = {k: row[k] for k in ('signal', 'mechanism', 'book', 'window')}
                raw = json.dumps(original).replace('"minimum_component_coverage_increase_pp": 5.0',
                    '"minimum_component_coverage_increase_pp": ' + spelling)
                (self.root / manual.DNR).write_text(raw)
                self.rejected(self.rebind_dependency(packet, scope, manual.DNR), scope)
        self.write(manual.DNR, original)

    def test_finite_nonnegative_coverage_thresholds_keep_canonical_exceptions(self):
        original = manual.board.read_json(self.root / manual.DNR)
        row = next(r for r in original['entries'] if r['id'] == 'broad_gross_floor')
        candidate = {k: row[k] for k in ('signal', 'mechanism', 'book', 'window')}
        for threshold in (0, 0.0, 5, 5.0, 7.5):
            with self.subTest(threshold=threshold):
                registry = copy.deepcopy(original)
                registry['reuse_policy']['minimum_component_coverage_increase_pp'] = threshold
                self.write(manual.DNR, registry)
                for exception in (dict(component_coverage_increase_pp=threshold),
                                  dict(semantics_changed=True, change_note='Changed application semantics')):
                    packet, scope = self.packet()
                    packet['do_not_repeat_candidate'] = {**candidate, **exception}
                    self.assertEqual(self.validate(self.bind(packet), scope)['status'], 'VALIDATED_PREPARE_ONLY')
                if threshold > 0:
                    packet, scope = self.packet()
                    packet['do_not_repeat_candidate'] = candidate.copy()
                    self.rejected(self.bind(packet), scope, 'BLOCKED_DO_NOT_REPEAT')
        self.write(manual.DNR, original)

    def test_canonical_match_fields_refuse_fully_rebound_registry_changes(self):
        original = manual.board.read_json(self.root / manual.DNR)
        fields = ['signal', 'mechanism', 'book', 'window']
        row = next(r for r in original['entries'] if r['id'] == 'broad_gross_floor')
        variants = {'missing': None, 'null': None, 'empty': [], 'extra': fields + ['id'],
                    'omitted': fields[:-1], 'reordered': list(reversed(fields)),
                    'duplicate': fields + ['signal'], 'string': ','.join(fields),
                    'mapping': {k: True for k in fields}}
        for case, value in variants.items():
            with self.subTest(case=case):
                self.write(manual.DNR, original)
                packet, scope = self.packet()
                packet['do_not_repeat_candidate'] = {k: row[k] for k in fields}
                registry = copy.deepcopy(original)
                if case == 'missing':
                    del registry['match_fields']
                else:
                    registry['match_fields'] = value
                self.write(manual.DNR, registry)
                self.rejected(self.rebind_dependency(packet, scope, manual.DNR), scope,
                              'do_not_repeat_match_fields_not_canonical')
        self.write(manual.DNR, original)

    def test_canonical_match_fields_preserve_block_and_allowed_controls(self):
        registry = manual.board.read_json(self.root / manual.DNR)
        fields = ['signal', 'mechanism', 'book', 'window']
        self.assertEqual(registry['match_fields'], fields)
        row = next(r for r in registry['entries'] if r['id'] == 'broad_gross_floor')
        candidate = {k: row[k] for k in fields}
        packet, scope = self.packet()
        packet['do_not_repeat_candidate'] = candidate.copy()
        self.rejected(self.bind(packet), scope, 'BLOCKED_DO_NOT_REPEAT')
        for change in (dict(component_coverage_increase_pp=5.0),
                       dict(semantics_changed=True, change_note='Different application semantics'),
                       dict(window='SYNTHETIC_NEW_WINDOW')):
            with self.subTest(change=change):
                packet, scope = self.packet()
                packet['do_not_repeat_candidate'] = {**candidate, **change}
                result = self.validate(self.bind(packet), scope)
                self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertFalse(result['completed_task'])

    def test_current_stop_conditions_refuse_fully_rebound_manifest_changes(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        variants = {'missing': None, 'null': None, 'empty': [],
                    'string': 'CALLER_ONLY_STOP', 'mapping': {'stop': True}, 'boolean': True}
        for changed_key in manual.PLAYBOOK_IDS:
            for requested_key in manual.PLAYBOOK_IDS:
                for case, value in variants.items():
                    with self.subTest(changed=changed_key, requested=requested_key, case=case):
                        self.write(manual.MANIFEST, original)
                        packet, scope = self.packet(requested_key)
                        manifest = copy.deepcopy(original)
                        row = next(r for r in manifest['playbooks'] if r['playbook_id'] == changed_key)
                        if case == 'missing':
                            del row['process']['stop_condition']
                        else:
                            row['process']['stop_condition'] = value
                        row['playbook_sha256'] = independent_hash(row, 'playbook_sha256')
                        self.write(manual.MANIFEST, manifest)
                        if changed_key == requested_key:
                            packet['playbook_sha256'] = row['playbook_sha256']
                        packet['stop_condition'] = ['CALLER_ONLY_STOP']
                        self.rejected(self.rebind_dependency(packet, scope, manual.MANIFEST), scope,
                                      'manual_stop_condition_invalid')
        self.write(manual.MANIFEST, original)

    def test_nonempty_current_stop_conditions_keep_required_stops(self):
        for key in manual.PLAYBOOK_IDS:
            with self.subTest(playbook=key):
                _, row = manual.load_playbook(key, self.root)
                self.assertIsInstance(row['process']['stop_condition'], list)
                self.assertTrue(row['process']['stop_condition'])
                packet, scope = self.packet(key)
                packet['stop_condition'].append('ADDITIONAL_TASK_STOP')
                result = self.validate(self.bind(packet), scope)
                self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertFalse(result['worker_invoked'])
                packet['stop_condition'].remove(row['process']['stop_condition'][0])
                self.rejected(self.bind(packet), scope, 'manual_contract_changed')

    def rebind_all(self, packet, scope, manifest=None):
        if manifest is not None:
            for row in manifest['playbooks']:
                row['playbook_sha256'] = independent_hash(row, 'playbook_sha256')
            self.write(manual.MANIFEST, manifest)
            row = next(row for row in manifest['playbooks']
                       if row['playbook_id'] == packet['playbook_id'] and row['status'] == 'CURRENT')
            packet.update(playbook_version=row['playbook_version'],
                          playbook_sha256=row['playbook_sha256'], toolbox_refs=row['toolbox_refs'].copy())
        for name in packet['dependencies']:
            packet['dependencies'][name] = scope['dependencies'][name] = hashlib.sha256(
                (self.root / name).read_bytes()).hexdigest()
        return self.bind(packet)

    def test_dnr_normalized_identity_refuses_blank_missing_and_wrong_types(self):
        fields = ('signal', 'mechanism', 'book', 'window')
        for field in fields:
            for value in ('', ' ', '\t\r\n', ' \u00a0\u2003\t ', None, False, 0, [], {}):
                with self.subTest(field=field, value=value):
                    packet, scope = self.packet()
                    candidate = dict.fromkeys(fields, 'VALID_NEW_IDENTITY')
                    candidate[field] = value
                    packet['do_not_repeat_candidate'] = candidate
                    self.rejected(self.rebind_all(packet, scope), scope)
            packet, scope = self.packet()
            packet['do_not_repeat_candidate'] = dict.fromkeys(fields, 'VALID_NEW_IDENTITY')
            del packet['do_not_repeat_candidate'][field]
            self.rejected(self.rebind_all(packet, scope), scope)
        packet, scope = self.packet()
        packet['do_not_repeat_candidate'] = dict.fromkeys(fields, ' \t\u2003\n')
        self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_identity_invalid')

    def test_dnr_normalized_valid_identities_preserve_blocks_and_exceptions(self):
        registry = manual.board.read_json(self.root / manual.DNR)
        row = next(row for row in registry['entries'] if row.get('blocked_reuse'))
        candidate = {field: ' \t' + row[field].upper() + '\u2003 '
                     for field in ('signal', 'mechanism', 'book', 'window')}
        packet, scope = self.packet()
        packet['do_not_repeat_candidate'] = copy.deepcopy(candidate)
        self.rejected(self.rebind_all(packet, scope), scope, 'BLOCKED_DO_NOT_REPEAT')
        for exception in ({'component_coverage_increase_pp': 5.0},
                          {'semantics_changed': True, 'change_note': 'Actual changed application'},
                          {'signal': ' VALID_NEW_COMBINATION '}):
            packet, scope = self.packet()
            packet['do_not_repeat_candidate'] = dict(candidate, **exception)
            result = self.validate(self.rebind_all(packet, scope), scope)
            self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
            self.assertFalse(result['economic_authority'])

    def test_reviewed_version_anchor_has_exact_existing_blob_provenance(self):
        # Canonical manifest bytes remain unchanged in this correction. This
        # binds the code anchor to the independently retrieved reviewed blob.
        raw = (ROOT / manual.MANIFEST).read_bytes()
        git_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        self.assertEqual(git_blob, manual.VERSION_ANCHOR_BLOB)
        self.assertEqual(manual.VERSION_ANCHOR_HEAD, '86bdcd474ae12d240d1dac31f72f758f45f26843')
        baseline = json.loads(raw)
        self.assertEqual(dict(manual.VERSION_ANCHOR), baseline['current_versions'])
        self.assertEqual(set(manual.VERSION_ANCHOR),
                         {(row['playbook_id'], row['playbook_version']) for row in baseline['playbooks']})
        for row in baseline['playbooks']:
            semantic = {k: v for k, v in row.items() if k != 'status'}
            self.assertEqual(manual.VERSION_ANCHOR_CONTENT[(row['playbook_id'], row['playbook_version'])],
                             independent_hash(semantic, 'playbook_sha256'))

    def test_history_removal_cannot_reset_reviewed_anchor_after_all_hash_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for selected in manual.PLAYBOOK_IDS:
                for version in ('0.0.0', '0.9.0', '1.1.0'):
                    with self.subTest(changed=changed, selected=selected, version=version):
                        self.write(manual.MANIFEST, original)
                        packet, scope = self.packet(selected)
                        manifest = copy.deepcopy(original)
                        manifest['playbooks'] = [row for row in manifest['playbooks'] if row['status'] == 'CURRENT']
                        row = next(row for row in manifest['playbooks'] if row['playbook_id'] == changed)
                        row.update(playbook_version=version, supersedes=None)
                        manifest['current_versions'][changed] = version
                        # Attacker-controlled declarations are not the anchor.
                        manifest['version_anchor'] = {changed: version}
                        self.rejected(self.rebind_all(packet, scope, manifest), scope,
                                      'missing_reviewed_playbook_anchor')
        self.write(manual.MANIFEST, original)

    def test_reviewed_anchor_preserves_full_upgrade_lineage_for_all_playbooks(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet(changed)
            manifest = copy.deepcopy(original)
            current = next(row for row in manifest['playbooks'] if row['playbook_id'] == changed)
            anchor = copy.deepcopy(current)
            anchor['status'] = 'SUPERSEDED'
            middle = copy.deepcopy(anchor)
            middle.update(playbook_version='1.1.0', supersedes='1.0.0')
            current.update(playbook_version='1.2.0', supersedes='1.1.0')
            manifest['current_versions'][changed] = '1.2.0'
            manifest['playbooks'].extend([anchor, middle])
            with self.reviewed_fixture_anchors(manifest, {(changed, '1.1.0')}):
                result = self.validate(self.rebind_all(packet, scope, manifest), scope, propose_successor=True)
            self.assertEqual(result['playbook_version'], '1.2.0')
            self.assertFalse(result['completed_task'])
        self.write(manual.MANIFEST, original)

    def test_historical_predecessor_edge_cannot_be_erased_after_full_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet()
            manifest = copy.deepcopy(original)
            current = next(row for row in manifest['playbooks'] if row['playbook_id'] == changed)
            anchor = copy.deepcopy(current)
            anchor['status'] = 'SUPERSEDED'
            middle = copy.deepcopy(anchor)
            middle.update(playbook_version='1.1.0', supersedes=None)
            current.update(playbook_version='1.2.0', supersedes='1.1.0')
            manifest['current_versions'][changed] = '1.2.0'
            manifest['playbooks'].extend([anchor, middle])
            self.rejected(self.rebind_all(packet, scope, manifest), scope,
                          'reviewed_playbook_lineage_invalid')
        self.write(manual.MANIFEST, original)

    def test_a1_reader_closure_remains_required_when_toolbox_refs_are_removed(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        expected = {'tools/research_data_access.py', 'data_static/research_dataset_registry_v1.json',
                    'tools/long_history_lake.py', 'tools/macro_history_sources.py',
                    'tools/macro_research_checkpoint.py', 'tools/run_data_freshness_contract.py',
                    'r1000_legacy_input_guard.py'}
        packet, scope = self.packet('A1_SOURCE_ADMISSION_REFRESH')
        manifest = copy.deepcopy(original)
        row = next(row for row in manifest['playbooks'] if row['playbook_id'] == packet['playbook_id'])
        old = copy.deepcopy(row)
        old['status'] = 'SUPERSEDED'
        manifest['playbooks'].append(old)
        row.update(playbook_version='1.1.0', supersedes='1.0.0')
        manifest['current_versions'][row['playbook_id']] = '1.1.0'
        row['toolbox_refs'] = ['docs/RESEARCH_DATA_ACCESS.md']
        self.rebind_all(packet, scope, manifest)
        with self.reviewed_fixture_anchors(manifest):
            self.assertTrue(expected.issubset(manual.required_dependencies(packet['playbook_id'], self.root)))
            self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
            for name in expected:
                with self.subTest(name=name):
                    altered, altered_scope = copy.deepcopy(packet), copy.deepcopy(scope)
                    del altered['dependencies'][name]
                    del altered_scope['dependencies'][name]
                    self.rejected(self.rebind_all(altered, altered_scope), altered_scope, 'missing_dependency')
        self.write(manual.MANIFEST, original)

    def test_each_reader_dependency_byte_change_invalidates_existing_a1_packet(self):
        packet, scope = self.packet('A1_SOURCE_ADMISSION_REFRESH')
        for name in manual.A1_READER_DEPENDENCIES:
            with self.subTest(name=name):
                target = self.root / name
                raw = target.read_bytes()
                try:
                    target.write_bytes(raw + b'\n ')
                    self.rejected(packet, scope, 'dependency_bytes_changed:' + name)
                finally:
                    target.write_bytes(raw)
        self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')

    def test_all_current_nested_instructions_refuse_fully_rebound_mutations(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for selected in manual.PLAYBOOK_IDS:
                for layer, field in (('process', 'steps'), ('process', 'stop_condition'),
                                     ('proof', 'checks'), ('learning', 'steps')):
                    for case, value in (('missing', None), ('null', None), ('empty', []),
                                        ('string', 'instruction'), ('mapping', {'step': 'instruction'}),
                                        ('boolean', False), ('blank', [' \t\u2003\n']),
                                        ('blank_member', ['valid', ' \u00a0\t']), ('nonstring_member', ['valid', 1])):
                        with self.subTest(changed=changed, selected=selected, layer=layer, field=field, case=case):
                            self.write(manual.MANIFEST, original)
                            packet, scope = self.packet(selected)
                            manifest = copy.deepcopy(original)
                            row = next(row for row in manifest['playbooks'] if row['playbook_id'] == changed)
                            if case == 'missing':
                                del row[layer][field]
                            else:
                                row[layer][field] = value
                            reason = ('manual_stop_condition_invalid' if field == 'stop_condition'
                                      else 'manual_instructions_invalid:' + layer + '.' + field)
                            if case == 'missing' and layer == 'proof':
                                reason = 'manual_layers_missing'
                            self.rejected(self.rebind_all(packet, scope, manifest), scope, reason)
        self.write(manual.MANIFEST, original)

    def test_valid_nested_instructions_and_additional_caller_stop_remain_prepare_only(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for key in manual.PLAYBOOK_IDS:
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet(key)
            manifest = copy.deepcopy(original)
            row = next(row for row in manifest['playbooks'] if row['playbook_id'] == key)
            old = copy.deepcopy(row)
            old['status'] = 'SUPERSEDED'
            manifest['playbooks'].append(old)
            row.update(playbook_version='1.1.0', supersedes='1.0.0')
            manifest['current_versions'][key] = '1.1.0'
            for layer, field in (('process', 'steps'), ('proof', 'checks'), ('learning', 'steps')):
                row[layer][field].append('Additional meaningful instruction')
            packet['stop_condition'].append('ADDITIONAL_CALLER_STOP')
            with self.reviewed_fixture_anchors(manifest):
                result = self.validate(self.rebind_all(packet, scope, manifest), scope)
            self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
            self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
            self.assertFalse(result['worker_invoked'])
            self.assertFalse(result['economic_authority'])
        self.write(manual.MANIFEST, original)

    def test_reviewed_semantic_content_cannot_change_at_same_version_after_full_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for selected in manual.PLAYBOOK_IDS:
                for layer, field in (('process', 'steps'), ('process', 'stop_condition'),
                                     ('proof', 'checks'), ('learning', 'steps')):
                    with self.subTest(changed=changed, selected=selected, layer=layer, field=field):
                        self.write(manual.MANIFEST, original)
                        packet, scope = self.packet(selected)
                        manifest = copy.deepcopy(original)
                        row = next(r for r in manifest['playbooks'] if r['playbook_id'] == changed)
                        row[layer][field] = ['Meaningful changed content without advancing the version']
                        if selected == changed and field == 'stop_condition':
                            packet['stop_condition'] = row[layer][field].copy()
                        self.rejected(self.rebind_all(packet, scope, manifest), scope,
                                      'reviewed_playbook_content_changed')
        self.write(manual.MANIFEST, original)

    def test_reviewed_anchor_covers_other_semantics_and_unknown_content_fields(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for field in ('trigger', 'inputs', 'proof_set', 'extra_content'):
                with self.subTest(changed=changed, field=field):
                    self.write(manual.MANIFEST, original)
                    packet, scope = self.packet()
                    manifest = copy.deepcopy(original)
                    row = next(r for r in manifest['playbooks'] if r['playbook_id'] == changed)
                    if field in ('trigger', 'inputs'):
                        row['process'][field] = 'Changed trigger' if field == 'trigger' else ['Changed input']
                    else:
                        row[field] = ['Meaningfully changed content']
                    self.rejected(self.rebind_all(packet, scope, manifest), scope,
                                  'reviewed_playbook_content_changed')
        self.write(manual.MANIFEST, original)

    def test_changed_semantics_require_upgrade_and_immutable_retained_predecessor(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for selected in manual.PLAYBOOK_IDS:
                with self.subTest(changed=changed, selected=selected):
                    self.write(manual.MANIFEST, original)
                    packet, scope = self.packet(selected)
                    manifest = copy.deepcopy(original)
                    row = next(r for r in manifest['playbooks'] if r['playbook_id'] == changed)
                    old = copy.deepcopy(row)
                    old['status'] = 'SUPERSEDED'
                    row.update(playbook_version='1.1.0', supersedes='1.0.0')
                    row['process']['steps'].append('Changed instructions in the new version')
                    manifest['playbooks'].append(old)
                    manifest['current_versions'][changed] = '1.1.0'
                    with self.reviewed_fixture_anchors(manifest):
                        result = self.validate(self.rebind_all(packet, scope, manifest), scope)
                    self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                    self.assertFalse(result['economic_authority'])
                    old['proof']['checks'].append('Retrospectively changed reviewed content')
                    self.rejected(self.rebind_all(packet, scope, manifest), scope,
                                  'reviewed_playbook_content_changed')
        self.write(manual.MANIFEST, original)

    def test_unselected_catalog_failure_references_fail_closed_with_full_rebinding(self):
        original = manual.board.read_json(self.root / manual.CATALOG)
        for selected in manual.PLAYBOOK_IDS:
            for case, refs in (('missing', None), ('null', None), ('empty', []),
                               ('unknown', ['UNKNOWN_REF']), ('mixed', ['broad_gross_floor', 'UNKNOWN_REF']),
                               ('blank', [' \t\n']), ('nonstring', [None]), ('string', 'broad_gross_floor'),
                               ('duplicate', ['broad_gross_floor', 'broad_gross_floor'])):
                with self.subTest(selected=selected, case=case):
                    self.write(manual.CATALOG, original)
                    packet, scope = self.packet(selected)
                    catalog = copy.deepcopy(original)
                    row = next(r for r in catalog['entries'] if r['classification'] == 'DO_NOT_REPEAT')
                    if case == 'missing':
                        del row['do_not_repeat_refs']
                    else:
                        row['do_not_repeat_refs'] = refs
                    self.write(manual.CATALOG, catalog)
                    self.assertEqual(packet['reuse_entries'], [])
                    self.assertNotIn('do_not_repeat_candidate', packet)
                    self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_')
        self.write(manual.CATALOG, original)

    def test_all_catalog_reference_classes_are_validated_and_canonical_refs_remain_valid(self):
        original = manual.board.read_json(self.root / manual.CATALOG)
        for classification in ('REUSE_NOW', 'SELECTIVE_PORT', 'HISTORICAL_LESSON'):
            self.write(manual.CATALOG, original)
            packet, scope = self.packet()
            catalog = copy.deepcopy(original)
            row = next(r for r in catalog['entries'] if r['classification'] == classification)
            row['do_not_repeat_refs'] = ['UNKNOWN_REF']
            self.write(manual.CATALOG, catalog)
            self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_ref_missing')
        self.write(manual.CATALOG, original)
        packet, scope = self.packet()
        self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertEqual(manual.lookup_reuse('group_174', self.root)['blocked_registry_ids'],
                         ['broad_gross_floor'])

    def test_invalid_registry_entries_cannot_bypass_canonical_validation_or_evaluator(self):
        original = manual.board.read_json(self.root / manual.DNR)
        fields = ('signal', 'mechanism', 'book', 'window')
        mutations = ('blocked_false', 'blocked_integer', 'blocked_missing', 'missing_id',
                     'invalid_id', 'duplicate_id', 'duplicate_normalized_id', 'duplicate_descriptor',
                     'empty_entries', 'nonobject_entry', 'missing_status') + tuple('blank_' + f for f in fields)
        for selected in manual.PLAYBOOK_IDS:
            for mutation in mutations:
                with self.subTest(selected=selected, mutation=mutation):
                    self.write(manual.DNR, original)
                    packet, scope = self.packet(selected)
                    registry = copy.deepcopy(original)
                    row = registry['entries'][0]
                    packet['do_not_repeat_candidate'] = {f: row[f] for f in fields}
                    if mutation == 'blocked_false':
                        row['blocked_reuse'] = False
                    elif mutation == 'blocked_integer':
                        row['blocked_reuse'] = 1
                    elif mutation == 'blocked_missing':
                        del row['blocked_reuse']
                    elif mutation == 'missing_id':
                        del row['id']
                    elif mutation == 'invalid_id':
                        row['id'] = 'invalid id!'
                    elif mutation == 'duplicate_id':
                        registry['entries'][1]['id'] = row['id']
                    elif mutation == 'duplicate_normalized_id':
                        duplicate = copy.deepcopy(row)
                        duplicate['id'] = row['id'] + '_'
                        duplicate['signal'] = 'A distinct otherwise valid signal'
                        registry['entries'].append(duplicate)
                    elif mutation == 'duplicate_descriptor':
                        for f in fields:
                            registry['entries'][1][f] = ' \t' + row[f].upper() + ' '
                    elif mutation == 'empty_entries':
                        registry['entries'] = []
                    elif mutation == 'nonobject_entry':
                        registry['entries'][0] = None
                    elif mutation == 'missing_status':
                        del row['status']
                    else:
                        row[mutation[6:]] = ' \t\n'
                    with self.assertRaises(ValueError):
                        manual.validated_do_not_repeat_entries(registry)
                    self.write(manual.DNR, registry)
                    with patch.object(manual, 'evaluate_candidate', side_effect=AssertionError('must not evaluate invalid registry')):
                        self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_registry_invalid')
        self.write(manual.DNR, original)

    def test_registry_is_validated_without_candidate_and_validator_dependency_is_mandatory(self):
        original = manual.board.read_json(self.root / manual.DNR)
        dependency = 'tools/build_run287_u0_v2_github_census.py'
        for key in manual.PLAYBOOK_IDS:
            self.write(manual.DNR, original)
            packet, scope = self.packet(key)
            registry = copy.deepcopy(original)
            registry['entries'][0]['blocked_reuse'] = False
            self.write(manual.DNR, registry)
            self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_registry_invalid')
            self.write(manual.DNR, original)
            packet, scope = self.packet(key)
            del packet['dependencies'][dependency]
            del scope['dependencies'][dependency]
            self.rejected(self.bind(packet), scope, 'missing_dependency')
            packet, scope = self.packet(key)
            raw = (self.root / dependency).read_bytes()
            try:
                (self.root / dependency).write_bytes(raw + b'\n# changed validator fixture\n')
                self.rejected(packet, scope, 'dependency_bytes_changed:' + dependency)
            finally:
                (self.root / dependency).write_bytes(raw)

    def test_registry_descriptors_and_ids_cannot_be_coerced_from_nontext_json(self):
        original = manual.board.read_json(self.root / manual.DNR)
        for key in manual.PLAYBOOK_IDS:
            for field in ('id', 'status', 'signal', 'mechanism', 'book', 'window'):
                for value in (1, True, ['valid'], {'identity': 'valid'}):
                    with self.subTest(key=key, field=field, value=value):
                        self.write(manual.DNR, original)
                        packet, scope = self.packet(key)
                        registry = copy.deepcopy(original)
                        registry['entries'][0][field] = value
                        self.write(manual.DNR, registry)
                        self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_registry_invalid')
        self.write(manual.DNR, original)

    def test_coverage_overflow_is_refused_before_evaluation_and_finite_controls_remain_valid(self):
        row = manual.board.read_json(self.root / manual.DNR)['entries'][0]
        blocked = {f: row[f] for f in ('signal', 'mechanism', 'book', 'window')}
        for key in manual.PLAYBOOK_IDS:
            for coverage in (10**309, -(10**309), 10**399, -(10**399)):
                packet, scope = self.packet(key)
                packet['do_not_repeat_candidate'] = dict(blocked, component_coverage_increase_pp=coverage)
                with patch.object(manual, 'evaluate_candidate', side_effect=AssertionError('must not convert overflow')):
                    self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_coverage_invalid')
            for candidate in (dict(blocked, component_coverage_increase_pp=5),
                              dict(blocked, component_coverage_increase_pp=10**308),
                              dict(blocked, component_coverage_increase_pp=sys.float_info.max),
                              dict(blocked, component_coverage_increase_pp=-1, semantics_changed=True,
                                   change_note='Approved semantic change fixture'),
                              dict(blocked, signal='VALID_NEW_SIGNAL', component_coverage_increase_pp=0)):
                packet, scope = self.packet(key)
                packet['do_not_repeat_candidate'] = candidate
                result = self.validate(self.rebind_all(packet, scope), scope)
                self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertFalse(result['economic_authority'])

    def test_cli_overflow_returns_blocked_input_and_children_preserve_optimization(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE=str(sys.flags.optimize))
        env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
        prefix = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else [])
        child = subprocess.run(prefix + ['-c', 'import sys; print(sys.flags.optimize)'],
                               env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(int(child.stdout), sys.flags.optimize)
        row = manual.board.read_json(self.root / manual.DNR)['entries'][0]
        blocked = {f: row[f] for f in ('signal', 'mechanism', 'book', 'window')}
        for key in manual.PLAYBOOK_IDS:
            for coverage in (10**399, -(10**399)):
                with self.subTest(key=key, sign=coverage > 0):
                    packet, scope = self.packet(key)
                    packet['do_not_repeat_candidate'] = dict(blocked, component_coverage_increase_pp=coverage)
                    self.rebind_all(packet, scope)
                    self.write('packet.json', packet)
                    self.write('scope.json', scope)
                    command = prefix + [str(self.root / 'tools/manual_foundation.py'), '--packet',
                                        str(self.root / 'packet.json'), '--scope', str(self.root / 'scope.json'),
                                        '--expected-base', BASE, '--expected-review-head', REVIEW_HEAD]
                    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED_INPUT',
                                     'reason': 'do_not_repeat_coverage_invalid', 'worker_invoked': False})
                    self.assertNotIn('Traceback', result.stderr)

    def test_every_reviewed_successor_content_is_immutable_even_when_unselected(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for version in ('1.1.0', '1.2.0'):
                manifest = copy.deepcopy(original)
                row = self.successor_fixture(manifest, changed, '1.1.0')
                if version == '1.2.0':
                    row = self.successor_fixture(manifest, changed, version)
                row['process']['steps'].append('Separately reviewed successor fixture')
                for selected in manual.PLAYBOOK_IDS:
                    self.write(manual.MANIFEST, original)
                    packet, scope = self.packet(selected)
                    reviewed = self.reviewed_fixture_anchors(manifest)
                    with reviewed:
                        self.assertEqual(self.validate(self.rebind_all(packet, scope, manifest), scope)['status'],
                                         'VALIDATED_PREPARE_ONLY')
                        for layer, field in (('process', 'steps'), ('process', 'stop_condition'),
                                             ('proof', 'checks'), ('learning', 'steps')):
                            with self.subTest(changed=changed, selected=selected, version=version, field=field):
                                altered = copy.deepcopy(manifest)
                                target = next(r for r in altered['playbooks']
                                              if r['playbook_id'] == changed and r['status'] == 'CURRENT')
                                target[layer][field] = ['Changed same-version content after independent review']
                                candidate, verified_scope = copy.deepcopy(packet), copy.deepcopy(scope)
                                current = next(r for r in altered['playbooks']
                                               if r['playbook_id'] == selected and r['status'] == 'CURRENT')
                                candidate['stop_condition'] = current['process']['stop_condition'].copy()
                                self.rejected(self.rebind_all(candidate, verified_scope, altered), verified_scope,
                                              'reviewed_playbook_content_changed', propose_successor=True)
        self.write(manual.MANIFEST, original)

    def test_later_reviewed_retained_versions_cannot_change_or_disappear(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            manifest = copy.deepcopy(original)
            self.successor_fixture(manifest, changed, '1.1.0')
            self.successor_fixture(manifest, changed, '1.2.0')
            reviewed = self.reviewed_fixture_anchors(manifest, {(changed, '1.1.0')})
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet()
            with reviewed:
                baseline = self.rebind_all(packet, scope, manifest)
                self.assertEqual(self.validate(baseline, scope, propose_successor=True)['status'],
                                 'VALIDATED_SUCCESSOR_PROPOSAL_ONLY')
                for layer, field in (('process', 'steps'), ('process', 'stop_condition'),
                                     ('proof', 'checks'), ('learning', 'steps')):
                    altered = copy.deepcopy(manifest)
                    old = next(r for r in altered['playbooks']
                               if r['playbook_id'] == changed and r['playbook_version'] == '1.1.0')
                    old[layer][field].append('Retrospective alteration of an accepted predecessor')
                    p, s = copy.deepcopy(packet), copy.deepcopy(scope)
                    self.rejected(self.rebind_all(p, s, altered), s, 'reviewed_playbook_content_changed',
                                  propose_successor=True)
                altered = copy.deepcopy(manifest)
                altered['playbooks'] = [r for r in altered['playbooks']
                                       if (r['playbook_id'], r['playbook_version']) != (changed, '1.1.0')]
                next(r for r in altered['playbooks'] if r['playbook_id'] == changed
                     and r['status'] == 'CURRENT')['supersedes'] = '1.0.0'
                p, s = copy.deepcopy(packet), copy.deepcopy(scope)
                self.rejected(self.rebind_all(p, s, altered), s, 'missing_reviewed_playbook_anchor',
                              propose_successor=True)
        self.write(manual.MANIFEST, original)

    def test_successor_proposals_require_reviewed_anchors_for_adoption_and_retention(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for key in manual.PLAYBOOK_IDS:
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet(key)
            manifest = copy.deepcopy(original)
            self.successor_fixture(manifest, key, '1.1.0')
            self.rebind_all(packet, scope, manifest)
            self.rejected(packet, scope, 'unreviewed_playbook_version')
            result = self.validate(packet, scope, propose_successor=True)
            self.assertEqual(result['status'], 'VALIDATED_SUCCESSOR_PROPOSAL_ONLY')
            self.assertEqual(result['proposed_playbook_versions'], {key: '1.1.0'})
            self.assertTrue(result['adoption_requires_independent_anchor_review'])
            self.assertFalse(result['worker_invoked'])
            self.assertFalse(result['completed_task'])
            self.assertFalse(result['economic_authority'])
            self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
            # Caller-controlled manifest claims cannot become the trusted table.
            manifest['version_anchor_content'] = {key: {'1.1.0': packet['playbook_sha256']}}
            self.rejected(self.rebind_all(packet, scope, manifest), scope, 'unreviewed_playbook_version')
            with self.reviewed_fixture_anchors(manifest):
                adopted = self.validate(packet, scope)
                self.assertEqual(adopted['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertNotIn('proposed_playbook_versions', adopted)
            self.successor_fixture(manifest, key, '1.2.0')
            self.rejected(self.rebind_all(packet, scope, manifest), scope,
                          'unreviewed_retained_playbook_version', propose_successor=True)
        self.write(manual.MANIFEST, original)

    def test_manifest_and_catalog_nonobject_roots_fail_closed_after_full_hash_rebinding(self):
        for name, reason, loader in ((manual.MANIFEST, 'manual_manifest_invalid',
                                     lambda: manual.load_playbook('L0_RESUME_HANDOFF', self.root)),
                                    (manual.CATALOG, 'catalog_contract', lambda: manual.load_catalog(self.root))):
            original = (self.root / name).read_bytes()
            for selected in manual.PLAYBOOK_IDS:
                for root in ([], None, 42, 6.25, 'nonobject', True, False):
                    with self.subTest(name=name, selected=selected, root=root):
                        packet, scope = self.packet(selected)
                        try:
                            self.write(name, root)
                            with self.assertRaisesRegex(manual.ContractError, reason):
                                loader()
                            self.rejected(self.rebind_all(packet, scope), scope, reason)
                        finally:
                            (self.root / name).write_bytes(original)

    def test_real_cli_nonobject_canonical_roots_return_structured_blocked_input(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE=str(sys.flags.optimize))
        prefix = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else [])
        child = subprocess.run(prefix + ['-c', 'import sys; print(sys.flags.optimize)'],
                               env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(int(child.stdout), sys.flags.optimize)
        for name, reason in ((manual.MANIFEST, 'manual_manifest_invalid'), (manual.CATALOG, 'catalog_contract')):
            original = (self.root / name).read_bytes()
            for root in ([], None, 42, 6.25, 'nonobject', True, False):
                with self.subTest(name=name, root=root):
                    packet, scope = self.packet()
                    try:
                        self.write(name, root)
                        self.rebind_all(packet, scope)
                        result = self.cli_fixture(packet, scope)
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                        self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED_INPUT',
                                         'reason': reason, 'worker_invoked': False})
                        self.assertNotIn('Traceback', result.stderr)
                        self.assertNotIn('AttributeError', result.stderr)
                    finally:
                        (self.root / name).write_bytes(original)
        packet, scope = self.packet()
        result = self.cli_fixture(packet, scope)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'VALIDATED_PREPARE_ONLY')

    def test_real_cli_successor_proposal_is_not_automatic_adoption(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for key in manual.PLAYBOOK_IDS:
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet(key)
            manifest = copy.deepcopy(original)
            self.successor_fixture(manifest, key, '1.1.0')
            self.rebind_all(packet, scope, manifest)
            blocked = self.cli_fixture(packet, scope)
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
            self.assertEqual(json.loads(blocked.stdout)['reason'], 'unreviewed_playbook_version')
            proposal = self.cli_fixture(packet, scope, propose_successor=True)
            self.assertEqual(proposal.returncode, 0, proposal.stdout + proposal.stderr)
            result = json.loads(proposal.stdout)
            self.assertEqual(result['status'], 'VALIDATED_SUCCESSOR_PROPOSAL_ONLY')
            self.assertTrue(result['adoption_requires_independent_anchor_review'])
            self.assertFalse(result['worker_invoked'])
            self.assertFalse(result['economic_authority'])
        self.write(manual.MANIFEST, original)

    def test_l0_mandatory_board_closure_cannot_be_removed_from_proposed_toolbox(self):
        expected = {'mission_contract.py', 'r1000_config.py', 'requirements_github.txt',
                    'research/control_plane/system_state_schema.json'}
        packet, scope = self.packet()
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        current = self.successor_fixture(manifest, packet['playbook_id'], '1.1.0')
        current['toolbox_refs'] = ['docs/MANUAL_FOUNDATION_V1.md']
        self.rebind_all(packet, scope, manifest)
        self.assertTrue(expected.issubset(manual.required_dependencies(packet['playbook_id'], self.root,
                                                                     propose_successor=True)))
        self.assertEqual(self.validate(packet, scope, propose_successor=True)['status'],
                         'VALIDATED_SUCCESSOR_PROPOSAL_ONLY')
        for name in expected:
            with self.subTest(name=name):
                p, s = copy.deepcopy(packet), copy.deepcopy(scope)
                del p['dependencies'][name]
                del s['dependencies'][name]
                self.rejected(self.rebind_all(p, s), s, 'missing_dependency', propose_successor=True)

    def test_l0_old_packet_byte_pins_and_independent_scope_survive_packet_rehash(self):
        for name in ('mission_contract.py', 'r1000_config.py', 'requirements_github.txt',
                     'research/control_plane/system_state_schema.json'):
            with self.subTest(name=name):
                packet, scope = self.packet()
                original = (self.root / name).read_bytes()
                try:
                    (self.root / name).write_bytes(original + b'\n')
                    self.rejected(self.bind(packet), scope, 'dependency_bytes_changed:' + name)
                    result = self.cli_fixture(packet, scope)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout)['reason'], 'dependency_bytes_changed:' + name)
                    self.assertNotIn('Traceback', result.stderr)
                    fresh_packet, fresh_scope = copy.deepcopy(packet), copy.deepcopy(scope)
                    self.rebind_dependency(fresh_packet, fresh_scope, name)
                    self.assertEqual(self.validate(fresh_packet, fresh_scope)['status'], 'VALIDATED_PREPARE_ONLY')
                    self.rejected(fresh_packet, scope, 'wrong_dependency')
                    del fresh_packet['dependencies'][name]
                    del fresh_scope['dependencies'][name]
                    self.rejected(self.bind(fresh_packet), fresh_scope, 'missing_dependency')
                finally:
                    (self.root / name).write_bytes(original)

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
