#!/usr/bin/env python3
"""Bounded, opt-in frozen A/B byte contract. No economic execution or approval.

The runner/consumer boundary is trusted, not an OS sandbox. Native consumers must
route ALL reads through ConsumerView before this can prove real consumption.
Uninstrumented legacy workflows cannot obtain a certificate from this module.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research import evaluation_v2_admission as admission
from tools import build_fullrun_runtime_source_manifest as runtime

SCHEMA = 'r1000-frozen-stage-ab-fairness-h1-v1'
GROUPS = frozenset({
    'prices', 'universe_identity', 'candidates', 'macro', 'fundamentals',
    'sec_event', 'calendar_pit', 'cost_slippage_tax_fx', 'capital_cash_accounting',
    'strategy_model_parameters', 'code_evaluator', 'session_decision',
})
CONSUMERS = {'A': ('engine', 'broker'), 'B': ('replay',)}
ROLE_GROUP = {
    'data_release': 'prices', 'eligible_universe': 'universe_identity',
    'calendar': 'calendar_pit', 'corporate_actions': 'prices',
    'fx': 'cost_slippage_tax_fx', 'benchmark': 'macro', 'risk_free': 'macro',
    'execution_contract': 'session_decision', 'cost_contract': 'cost_slippage_tax_fx',
    'cash_accounting': 'capital_cash_accounting', 'metric_contract': 'code_evaluator',
    'evaluator_source': 'code_evaluator', 'mission_contract': 'strategy_model_parameters',
    'pit_availability': 'calendar_pit', 'reference_initial_capital': 'capital_cash_accounting',
    'decision_clock_schema': 'session_decision',
}
CONTRACT_KEYS = frozenset({'schema', 'data_scope', 'price_generation_sha256',
    'code_sha', 'session', 'decision_time', 'context_sha256', 'groups', 'consumers'})
SOURCE_KEYS = frozenset({'ref', 'bytes', 'available_at', 'collected_at', 'expires_at'})
AUTHORITY = dict(research_only=True, fairness_certified=False, g0_certified=False,
    economic_comparison_ready=False, fullrun_allowed=False,
    target_paper_broker_mutation_allowed=False, champion_promotion_allowed=False,
    public_publication_allowed=False, live_trading_allowed=False)
require = admission.require


def keys(value: Any, expected: frozenset | set, reason: str) -> None:
    require(type(value) is dict and set(value) == expected, reason)


def clock(value: Any) -> datetime:
    require(type(value) is str and re.fullmatch(
        r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)', value)
        is not None and not value.endswith('-00:00'), 'CLOCK_INVALID')
    if not value.endswith('Z'):
        require(int(value[-5:-3]) < 24 and int(value[-2:]) < 60, 'CLOCK_INVALID')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise admission.AdmissionError('CLOCK_INVALID') from None


def validate_contract(raw: bytes, pin: str) -> dict:
    require(type(pin) is str and admission.HEX64.fullmatch(pin) is not None,
            'GENERATION_PIN_REQUIRED')
    require(type(raw) is bytes and admission.digest(raw) == pin, 'GENERATION_BYTES_MISMATCH')
    value = admission.strict_json(raw)
    keys(value, CONTRACT_KEYS, 'CONTRACT_FIELDS')
    require(value['schema'] == SCHEMA, 'CONTRACT_SCHEMA')
    require(value['data_scope'] in ('SYNTHETIC', 'HISTORICAL_RESEARCH', 'FORWARD_RESEARCH'),
            'DATA_SCOPE')
    for name in ('price_generation_sha256', 'context_sha256'):
        require(type(value[name]) is str and admission.HEX64.fullmatch(value[name]) is not None,
                'CONTRACT_HASH')
    require(type(value['code_sha']) is str and re.fullmatch(r'[0-9a-f]{40}', value['code_sha'])
            is not None, 'CODE_SHA')
    require(type(value['session']) is str and re.fullmatch(r'\d{4}-\d\d-\d\d', value['session'])
            is not None, 'SESSION_INVALID')
    try:
        require(date.fromisoformat(value['session']) <= clock(value['decision_time']).date(),
                'SESSION_FUTURE')
    except ValueError:
        raise admission.AdmissionError('SESSION_INVALID') from None
    cutoff = clock(value['decision_time'])
    keys(value['groups'], GROUPS, 'ALL_SOURCE_GROUPS_REQUIRED')
    seen = set()
    for group, spec in value['groups'].items():
        keys(spec, {'basis', 'sources'}, 'GROUP_FIELDS')
        require(type(spec['basis']) is str and bool(spec['basis'].strip()), 'SOURCE_BASIS')
        sources = spec['sources']
        require(type(sources) is list and len(sources) <= 2048
                and (bool(sources) or group == 'sec_event'), 'GROUP_SOURCES')
        for source in sources:
            keys(source, SOURCE_KEYS, 'SOURCE_FIELDS')
            admission.validate_ref(source['ref'])
            ident = source['ref']['artifact_id']
            require(ident not in seen, 'SOURCE_ID_DUPLICATE'); seen.add(ident)
            require(type(source['bytes']) is int and 0 < source['bytes'] <= admission.MAX_BLOB_BYTES,
                    'SOURCE_BYTE_BUDGET')
            available, collected, expiry = (clock(source[k]) for k in
                ('available_at', 'collected_at', 'expires_at'))
            require(available <= collected <= cutoff <= expiry, 'SOURCE_AVAILABILITY_PIT')
    keys(value['consumers'], {'A', 'B'}, 'STAGE_PLANS')
    active = {g for g in GROUPS if value['groups'][g]['sources']}
    for stage, names in CONSUMERS.items():
        keys(value['consumers'][stage], set(names), 'CONSUMER_PLANS')
        union = set()
        for plan in value['consumers'][stage].values():
            require(type(plan) is list and bool(plan) and all(type(g) is str for g in plan)
                    and len(plan) == len(set(plan)) and set(plan) <= active, 'CONSUMER_GROUPS')
            union.update(plan)
        require(union == active, 'CONSUMED_GROUP_COVERAGE')
    return value


def group_digest(records: list[dict]) -> str:
    # Same record identity and canonical hashing as the existing runtime manifest.
    return runtime.sha256_bytes(runtime.canonical_json(sorted(records, key=lambda r: r['path'])))


def phase_order(stage: str) -> list[str]:
    order = ['FROZEN', 'RESTORE']
    for name in CONSUMERS[stage]:
        order += ['PRE_' + name, 'EXECUTION_' + name, 'POST_' + name]
    return order + ['POST']


def receipt_bytes(contract: dict, pin: str, stage: str, run_id: str, phases: list) -> bytes:
    return admission.canonical({'schema': SCHEMA, 'stage': stage,
        'generation_sha256': pin, **{k: contract[k] for k in
            ('price_generation_sha256', 'code_sha', 'session', 'decision_time')},
        'run_id': run_id, 'phases': phases})


def require_receipt_capacity(contract: dict, pin: str, stage: str, run_id: str) -> None:
    # The sink may legally choose any 200-character ASCII artifact ID for each
    # save. Reserve that worst case before saving evidence or invoking consumers.
    # Receipt byte/node/depth budgets are the verifier's unchanged JSON budgets.
    groups = {g: [{'path': s['ref']['artifact_id'], 'size_bytes': s['bytes'],
        'sha256': s['ref']['sha256'], 'evidence_ref': {
            'artifact_id': 'x' * 200, 'sha256': s['ref']['sha256']}}
        for s in spec['sources']] for g, spec in contract['groups'].items()}
    phases = []
    for phase in phase_order(stage):
        used = contract['consumers'][stage][phase[10:]] if phase.startswith('EXECUTION_') else GROUPS
        phases.append({'phase': phase, 'groups': {g: groups[g] for g in used}})
    try:
        admission.strict_json(receipt_bytes(contract, pin, stage, run_id, phases))
    except admission.AdmissionError:
        raise admission.AdmissionError('STAGE_RECEIPT_BUDGET') from None


def bound_environment(contract: dict, control: dict, challenger: dict, root: str | Path) -> dict:
    resolver = admission.BoundedArtifactResolver(root)
    result = admission.compare_environment(control, challenger,
        expected_context_sha256=contract['context_sha256'], artifact_resolver=resolver)
    require(result['data_scope'] == contract['data_scope'], 'DATA_SCOPE_MISMATCH')
    context = admission.strict_json(resolver(control['context_ref']['artifact_id']))
    require(context['shared_refs']['data_release']['sha256'] == contract['price_generation_sha256'],
            'PRICE_GENERATION_BINDING')
    for role, group in ROLE_GROUP.items():
        require(context['shared_refs'][role] in [s['ref'] for s in contract['groups'][group]['sources']],
                'ENVIRONMENT_SOURCE_BINDING')
    resolver.validate_snapshot()
    return result


def record(source: dict, raw: bytes, save: Callable[[bytes], dict]) -> dict:
    require(type(raw) is bytes and len(raw) == source['bytes']
            and admission.digest(raw) == source['ref']['sha256'], 'RUNTIME_SOURCE_BYTES_MISMATCH')
    ref = save(raw)
    admission.validate_ref(ref)
    require(ref['sha256'] == admission.digest(raw), 'EVIDENCE_HASH_MISMATCH')
    return {'path': source['ref']['artifact_id'], 'size_bytes': len(raw),
            'sha256': admission.digest(raw), 'evidence_ref': dict(ref)}


class ConsumerView:
    """Return the verified runtime bytes and archive those exact returned bytes."""
    def __init__(self, contract: dict, groups: list[str], resolver: Callable, save: Callable):
        self.contract, self.groups, self.resolver, self.save = contract, groups, resolver, save
        self.records: dict[str, dict[str, dict]] = {g: {} for g in groups}
        self.closed = False

    def read(self, group: str, artifact_id: str) -> bytes:
        require(not self.closed and group in self.records, 'UNDECLARED_CONSUMER_INPUT')
        source = next((s for s in self.contract['groups'][group]['sources']
                       if s['ref']['artifact_id'] == artifact_id), None)
        require(source is not None, 'UNDECLARED_CONSUMER_INPUT')
        raw = self.resolver(artifact_id)
        self.records[group][artifact_id] = record(source, raw, self.save)
        return raw

    def external_input(self, _operation: str) -> None:
        # No refresh/stale-repair/cache-selection/candidate/target fallback API.
        raise admission.AdmissionError('STRICT_EXTERNAL_INPUT_FORBIDDEN')

    def finish(self) -> dict:
        self.closed = True
        for group in self.groups:
            require(set(self.records[group]) == {s['ref']['artifact_id']
                for s in self.contract['groups'][group]['sources']}, 'RUNTIME_CONSUMPTION_INCOMPLETE')
        return {g: sorted(v.values(), key=lambda r: r['path']) for g, v in self.records.items()}


class FrozenStage:
    """Trusted offline adapter boundary; failures poison the entire invocation.

    Restore is external and must finish before construction. Each phase gets a
    fresh native resolver, so a prior cache hit cannot mask runtime byte drift.
    Callback results are returned unchanged. Nothing executes an engine itself.
    """
    def __init__(self, contract_raw: bytes, *, expected_generation_sha256: str,
                 stage: str, runtime_root: str | Path, frozen_root: str | Path,
                 save_evidence: Callable[[bytes], dict], run_id: str,
                 control: dict, challenger: dict, environment_root: str | Path):
        self.contract = validate_contract(contract_raw, expected_generation_sha256)
        require(stage in CONSUMERS, 'STAGE_INVALID')
        require(type(run_id) is str and bool(run_id.strip()), 'RUN_ID_REQUIRED')
        require_receipt_capacity(self.contract, expected_generation_sha256, stage, run_id)
        require(runtime.git_head() == self.contract['code_sha'], 'EXECUTED_CODE_SHA_MISMATCH')
        self.environment = bound_environment(self.contract, control, challenger, environment_root)
        self.stage, self.root, self.frozen, self.save = stage, runtime_root, frozen_root, save_evidence
        self.pin, self.run_id = expected_generation_sha256, run_id
        self.phases: list[dict] = []; self.next_consumer = 0; self.failed = False
        self.snapshot('FROZEN', frozen_root)
        self.snapshot('RESTORE', runtime_root)

    def snapshot(self, phase: str, root: str | Path) -> None:
        require(not self.failed, 'STAGE_ALREADY_BLOCKED')
        try:
            resolver = admission.BoundedArtifactResolver(root)
            groups = {}
            for group, spec in sorted(self.contract['groups'].items()):
                groups[group] = [record(s, resolver(s['ref']['artifact_id']), self.save)
                                 for s in spec['sources']]
            resolver.validate_snapshot()
            self.phases.append({'phase': phase, 'groups': groups})
        except Exception:
            self.failed = True
            raise

    def run_consumer(self, name: str, consume: Callable[[ConsumerView], Any]) -> Any:
        try:
            require(not self.failed and self.next_consumer < len(CONSUMERS[self.stage])
                    and name == CONSUMERS[self.stage][self.next_consumer], 'CONSUMER_ORDER')
            self.snapshot('PRE_' + name, self.root)
            resolver = admission.BoundedArtifactResolver(self.root)
            view = ConsumerView(self.contract, self.contract['consumers'][self.stage][name],
                                resolver, self.save)
            result = consume(view)
            groups = view.finish(); resolver.validate_snapshot()
            self.phases.append({'phase': 'EXECUTION_' + name, 'groups': groups})
            self.snapshot('POST_' + name, self.root)
            self.next_consumer += 1
            return result
        except Exception:
            self.failed = True
            raise

    def finish(self) -> bytes:
        try:
            require(not self.failed and self.next_consumer == len(CONSUMERS[self.stage]),
                    'STAGE_INCOMPLETE_OR_BLOCKED')
            require(runtime.git_head() == self.contract['code_sha'], 'EXECUTED_CODE_SHA_MISMATCH')
            self.snapshot('POST', self.root)
            raw = receipt_bytes(self.contract, self.pin, self.stage, self.run_id, self.phases)
            admission.strict_json(raw)
            self.failed = True  # Seal the successful invocation; no later reuse.
        except Exception:
            self.failed = True
            raise
        return raw


def verify(contract_raw: bytes, stage_a_raw: bytes, stage_b_raw: bytes, *,
           expected_generation_sha256: str, expected_stage_a_sha256: str,
           expected_stage_b_sha256: str, frozen_root: str | Path,
           evidence_root: str | Path, control: dict, challenger: dict,
           environment_root: str | Path) -> dict:
    """Independent reconstruction before handing anything to an economic verifier.

    Pins must come from the runner's immutable receipts, not the presented JSON.
    Rebuild every phase/group from retained raw bytes; declared digests alone fail.
    This does NOT authenticate source/PIT declarations or consumer completeness.
    """
    contract = validate_contract(contract_raw, expected_generation_sha256)
    bound_environment(contract, control, challenger, environment_root)
    frozen = admission.BoundedArtifactResolver(frozen_root)
    expected = {}
    for group, spec in contract['groups'].items():
        rows = []
        for source in spec['sources']:
            raw = frozen(source['ref']['artifact_id'])
            require(len(raw) == source['bytes'] and admission.digest(raw) == source['ref']['sha256'],
                    'FROZEN_SOURCE_BYTES_MISMATCH')
            rows.append({'path': source['ref']['artifact_id'], 'size_bytes': len(raw),
                         'sha256': admission.digest(raw)})
        expected[group] = group_digest(rows)
    evidence_snapshots = []
    rebuilt = {}
    for stage, raw, pin in (('A', stage_a_raw, expected_stage_a_sha256),
                            ('B', stage_b_raw, expected_stage_b_sha256)):
        require(type(pin) is str and admission.HEX64.fullmatch(pin) is not None
                and type(raw) is bytes and admission.digest(raw) == pin, 'STAGE_RECEIPT_PIN_MISMATCH')
        receipt = admission.strict_json(raw)
        keys(receipt, {'schema', 'stage', 'generation_sha256', 'price_generation_sha256',
             'code_sha', 'session', 'decision_time', 'run_id', 'phases'}, 'RECEIPT_FIELDS')
        require(receipt['schema'] == SCHEMA and receipt['stage'] == stage, 'RECEIPT_STAGE')
        for key, wanted in {'generation_sha256': expected_generation_sha256,
            **{k: contract[k] for k in ('price_generation_sha256', 'code_sha', 'session', 'decision_time')}}.items():
            require(receipt[key] == wanted, 'STAGE_IDENTITY_MISMATCH')
        require(type(receipt['run_id']) is str and bool(receipt['run_id'].strip()), 'RUN_ID_REQUIRED')
        order = phase_order(stage)
        phases = receipt['phases']
        require(type(phases) is list and len(phases) == len(order), 'PHASE_COVERAGE')
        rebuilt[stage] = []
        for phase, wanted in zip(phases, order):
            keys(phase, {'phase', 'groups'}, 'PHASE_FIELDS')
            require(phase['phase'] == wanted, 'PHASE_ORDER')
            used = set(contract['consumers'][stage][wanted[10:]]) if wanted.startswith('EXECUTION_') else GROUPS
            keys(phase['groups'], used, 'RUNTIME_GROUP_COVERAGE')
            # A fresh immutable copy per save is valid: charge one phase, not
            # every retained copy across all A/B phases, against the 16 MiB cap.
            evidence = admission.BoundedArtifactResolver(evidence_root)
            hashes = {}
            for group, records in phase['groups'].items():
                require(type(records) is list, 'RUNTIME_RECORDS')
                sources = {s['ref']['artifact_id']: s for s in contract['groups'][group]['sources']}
                require(len(records) == len(sources), 'RUNTIME_SOURCE_COVERAGE')
                independent = []; seen = set()
                for row in records:
                    keys(row, {'path', 'size_bytes', 'sha256', 'evidence_ref'}, 'RUNTIME_RECORD_FIELDS')
                    require(type(row['path']) is str and row['path'] in sources and row['path'] not in seen,
                            'RUNTIME_SOURCE_COVERAGE'); seen.add(row['path'])
                    admission.validate_ref(row['evidence_ref'])
                    original = evidence(row['evidence_ref']['artifact_id'])
                    source = sources[row['path']]
                    require(type(row['size_bytes']) is int and row['size_bytes'] == len(original)
                        == source['bytes'] and row['sha256'] == admission.digest(original)
                        == row['evidence_ref']['sha256'] == source['ref']['sha256'],
                        'RECONSTRUCTED_SOURCE_MISMATCH')
                    independent.append({k: row[k] for k in ('path', 'size_bytes', 'sha256')})
                hashes[group] = group_digest(independent)
                require(hashes[group] == expected[group], 'COMMON_SOURCE_MISMATCH')
            evidence.validate_snapshot()
            evidence_snapshots.append(evidence)
            rebuilt[stage].append({'phase': wanted, 'group_sha256': hashes})
    frozen.validate_snapshot()
    # Later phase reads must not hide replacement of an earlier retained leaf.
    for evidence in evidence_snapshots:
        evidence.validate_snapshot()
    return {'schema': SCHEMA, 'status': 'FROZEN_CONTRACT_BYTE_PASS_RESEARCH_ONLY',
        'generation_sha256': expected_generation_sha256, 'data_scope': contract['data_scope'],
        'rebuilt_phases': rebuilt, 'common_group_sha256': expected,
        'unverified_domains': list(admission.UNVERIFIED) + ['NATIVE_CONSUMER_READ_CLOSURE',
            'ACTUAL_A1_GENERATION_ADMISSION', 'ROW_LEVEL_PIT_AND_AVAILABILITY'], **AUTHORITY}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('contract', 'stage-a', 'stage-b', 'generation-sha256', 'stage-a-sha256',
                 'stage-b-sha256', 'frozen-root', 'evidence-root', 'control', 'challenger',
                 'environment-root'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    try:
        # Native safe resolver also bounds and validates input receipt files.
        def read(path: str) -> bytes:
            p = Path(path).absolute()
            return admission.BoundedArtifactResolver(p.parent)(p.name)
        result = verify(read(args.contract), read(args.stage_a), read(args.stage_b),
            expected_generation_sha256=args.generation_sha256,
            expected_stage_a_sha256=args.stage_a_sha256, expected_stage_b_sha256=args.stage_b_sha256,
            frozen_root=args.frozen_root, evidence_root=args.evidence_root,
            control=admission.strict_json(read(args.control)),
            challenger=admission.strict_json(read(args.challenger)), environment_root=args.environment_root)
    except admission.AdmissionError as exc:
        print(json.dumps({'status': 'BLOCKED_FROZEN_FAIRNESS', 'reason': str(exc), **AUTHORITY}))
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'status': 'BLOCKED_FROZEN_FAIRNESS', 'reason': 'INVALID_INPUT', **AUTHORITY}))
        return 2
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
