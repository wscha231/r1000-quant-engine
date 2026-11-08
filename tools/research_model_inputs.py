#!/usr/bin/env python3
"""Model-version references to the existing shared Reader, never a collector.

Input metadata is model-independent. Model bindings reference it without copying
source objects. Stored metadata is a locator, not a Source trust anchor: replay
always goes through the original Reader and its externally supplied trust.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from tools.macro_history_sources import digest, encoded, exclusive
from tools.research_data_access import (
    ComponentReadResult, PREFIX_V1, ResearchDataReader, _freeze, check, clock,
    day, decode, sha, MAX_GENERATION_ROWS, MAX_GENERATION_DECOMPRESSED_BYTES,
)

MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_MODELS = 32
INPUT_SCHEMA = 'research-model-input-v1'
BINDING_SCHEMA = 'research-model-input-binding-v1'


@dataclass(frozen=True)
class ModelInputBundle:
    read: ComponentReadResult
    input_id: str
    input_bytes: bytes
    binding_bytes: tuple  # Immutable per-model metadata; no prices or fact values.


def _metadata(value):
    # Bound caller graphs and strings before the JSON encoder can allocate a
    # giant escaped string. Walk iterators rather than copying container members.
    pending, charge = [iter((value,))], 0
    while pending:
        try:
            item = next(pending[-1])
        except StopIteration:
            pending.pop(); continue
        charge += 8
        if type(item) is str:
            charge += 6 * len(item) + 2  # worst-case JSON escaping
        elif type(item) is dict:
            charge += 2 * len(item)
            check(len(item) <= MAX_METADATA_BYTES // 8, 'MODEL_INPUT_METADATA_LIMIT')
            check(all(type(k) is str for k in item), 'MODEL_INPUT_METADATA_SCHEMA')
            pending.append(iter(item))
            pending.append(iter(item.values()))
        elif type(item) in (list, tuple):
            charge += len(item)
            pending.append(iter(item))
        elif type(item) is int:
            check(item.bit_length() <= 64, 'MODEL_INPUT_METADATA_SCHEMA')
        elif type(item) is float:
            check(math.isfinite(item), 'MODEL_INPUT_METADATA_SCHEMA')
        else:
            check(item is None or type(item) is bool, 'MODEL_INPUT_METADATA_SCHEMA')
        check(charge <= MAX_METADATA_BYTES and len(pending) <= 64,
              'MODEL_INPUT_METADATA_LIMIT')
    raw = bytearray()
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False,
                               separators=(',', ':'))
    for chunk in encoder.iterencode(value):
        chunk = chunk.encode('utf-8')
        check(len(raw) + len(chunk) + 1 <= MAX_METADATA_BYTES, 'MODEL_INPUT_METADATA_LIMIT')
        raw.extend(chunk)
    raw.extend(b'\n')
    return bytes(raw)


def _input_manifest(raw, input_id):
    sha(input_id)
    check(type(raw) is bytes and len(raw) <= MAX_METADATA_BYTES and
          digest(raw) == input_id, 'MODEL_INPUT_HASH')
    manifest = decode(raw)
    check(type(manifest) is dict and manifest.get('schema') == INPUT_SCHEMA,
          'MODEL_INPUT_SCHEMA')
    return manifest


def _validated_bundle(bundle):
    check(type(bundle) is ModelInputBundle and type(bundle.read) is ComponentReadResult,
          'MODEL_INPUT_BUNDLE')
    manifest = _input_manifest(bundle.input_bytes, bundle.input_id)
    read = bundle.read
    check(len(read.receipt_bytes) <= MAX_METADATA_BYTES and
          decode(read.receipt_bytes) == manifest['read_receipt'] and
          read.receipt == _freeze(manifest['read_receipt']), 'MODEL_INPUT_READ_BINDING')
    check(set(read.results) == set(manifest['component_receipts']), 'MODEL_INPUT_READ_BINDING')
    charged_rows, charged_bytes = 0, 0
    for name, item in read.results.items():
        receipt = manifest['component_receipts'][name]
        check(len(item.receipt_bytes) <= MAX_METADATA_BYTES and
              decode(item.receipt_bytes) == receipt and item.receipt == _freeze(receipt),
              'MODEL_INPUT_READ_BINDING')
        # Stream the canonical row-set hash without constructing another full
        # price/fact array. A replaced dataclass cannot borrow genuine receipts.
        row_hash = hashlib.sha256(); row_hash.update(b'[')
        for index, row in enumerate(item.rows):
            charged_rows += 1
            check(charged_rows <= MAX_GENERATION_ROWS, 'MODEL_INPUT_ROW_BUDGET')
            raw = _metadata(dict(row))[:-1]
            charged_bytes += len(raw) + 1
            check(charged_bytes <= MAX_GENERATION_DECOMPRESSED_BYTES, 'MODEL_INPUT_ROW_BUDGET')
            if index: row_hash.update(b',')
            row_hash.update(raw)
        row_hash.update(b']\n')
        check(len(item.rows) == receipt['rows'] and row_hash.hexdigest() == receipt['row_set_sha256'],
              'MODEL_INPUT_ROW_BINDING')
    return manifest


def _models(models):
    check(type(models) in (list, tuple) and 0 < len(models) <= MAX_MODELS,
          'MODEL_BINDINGS')
    result, seen = [], set()
    fields = {'model_id', 'model_version', 'code_sha', 'config_sha256', 'feature_recipe_sha256'}
    for model in models:
        check(type(model) is dict and set(model) == fields, 'MODEL_BINDINGS')
        for field in ('model_id', 'model_version'):
            check(type(model[field]) is str and
                  re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', model[field]),
                  'MODEL_BINDINGS')
        check(type(model['code_sha']) is str and re.fullmatch(r'[0-9a-f]{40}', model['code_sha']),
              'MODEL_CODE_SHA')
        sha(model['config_sha256']); sha(model['feature_recipe_sha256'])
        key = (model['model_id'], model['model_version'])
        check(key not in seen, 'DUPLICATE_MODEL_VERSION')
        seen.add(key); result.append(dict(model))
    return result


def prepare_model_inputs(reader, dataset_id, generation_id, *, decision_time,
                         components, consumer_id, models, financial_trust=None):
    """One original component read for up to 32 model versions, research only.

    consumer_id remains the original qualified application identity. Model names
    never replace it. No training, selection, evaluation or provider call occurs.
    Any original global/required refusal propagates without a success bundle.
    """
    check(type(reader) is ResearchDataReader, 'MODEL_INPUT_READER')
    models = _models(models)
    sha(generation_id); clock(decision_time)
    check(type(components) in (list, tuple) and 0 < len(components) <= 256,
          'COMPONENT_REQUESTS')
    # Detach caller requests before validation or serialization. The original
    # Reader enforces dataset-specific fields, identity, clocks and coverage.
    components = decode(_metadata(components))
    check(type(components) is list, 'COMPONENT_REQUESTS')
    result = reader.read_components(dataset_id, generation_id,
        decision_time=decision_time, purpose='research', components=components,
        consumer_id=consumer_id, financial_trust=financial_trust)
    check(type(result) is ComponentReadResult and bool(result.results), 'NO_MODEL_INPUTS')
    check(len(result.receipt_bytes) + sum(len(item.receipt_bytes) for item in result.results.values())
          <= MAX_METADATA_BYTES, 'MODEL_INPUT_METADATA_LIMIT')
    receipt = decode(result.receipt_bytes)
    component_receipts = {name: decode(item.receipt_bytes)
                          for name, item in result.results.items()}
    manifest = dict(schema=INPUT_SCHEMA, mode='RESEARCH_ONLY',
        dataset_id=dataset_id, generation_id=generation_id,
        decision_time=decision_time, consumer_id=consumer_id, components=components,
        read_receipt=receipt, component_receipts=component_receipts,
        source_objects_copied=0, provider_refresh_count=0,
        eligible_for_selector=False, eligible_for_economics=False,
        source_admission=False, historical_pit_admission=False,
        er_admission=False, a5_admission=False)
    raw = _metadata(manifest); input_id = digest(raw)
    bindings = tuple(_metadata(dict(schema=BINDING_SCHEMA, model=model,
        input_id=input_id, decision_time=decision_time, mode='RESEARCH_ONLY',
        evaluation_status='NOT_RUN', eligible_for_selector=False,
        eligible_for_economics=False)) for model in models)
    return ModelInputBundle(result, input_id, raw, bindings)


def store_model_inputs(bundle, private_root):
    """Explicit local T2 metadata write, using the existing write-once primitive.

    private_root is supplied by the caller inside its approved private boundary.
    This does not create a remote connection or prove Drive publication. No raw
    data is copied. Repeating an identical write is idempotent; conflicts fail.
    """
    manifest = _validated_bundle(bundle)
    check(type(bundle.binding_bytes) is tuple and 0 < len(bundle.binding_bytes) <= MAX_MODELS,
          'MODEL_BINDINGS')
    paths = [(f'{PREFIX_V1}/model-inputs/{bundle.input_id}', bundle.input_bytes)]
    for raw in bundle.binding_bytes:
        check(type(raw) is bytes and len(raw) <= MAX_METADATA_BYTES, 'MODEL_INPUT_METADATA_LIMIT')
        binding = decode(raw)
        check(binding.get('schema') == BINDING_SCHEMA and
              binding.get('input_id') == bundle.input_id, 'MODEL_BINDING_INPUT')
        check(set(binding) == {'schema', 'model', 'input_id', 'decision_time', 'mode',
                               'evaluation_status', 'eligible_for_selector', 'eligible_for_economics'}
              and binding.get('decision_time') == manifest['decision_time']
              and binding.get('mode') == 'RESEARCH_ONLY'
              and binding.get('evaluation_status') == 'NOT_RUN'
              and binding.get('eligible_for_selector') is False
              and binding.get('eligible_for_economics') is False, 'MODEL_BINDING_AUTHORITY')
        paths.append((f'{PREFIX_V1}/model-bindings/{digest(raw)}', raw))
    _models([decode(raw)['model'] for raw in bundle.binding_bytes])
    # Validate all metadata before the first write. Partial writes after an I/O
    # failure are unaccepted, immutable metadata, never a completed publication.
    for _, raw in paths:
        check(len(raw) <= MAX_METADATA_BYTES, 'MODEL_INPUT_METADATA_LIMIT')
    for path, raw in paths:
        exclusive(Path(private_root) / path, raw)
    return _freeze(dict(status='LOCAL_METADATA_ONLY', input_id=bundle.input_id,
        paths=[p for p, _ in paths], binding_sha256=[digest(r) for r in bundle.binding_bytes],
        source_objects_copied=0, durable_publication_verified=False,
        provider_refresh_count=0, accepted_write_count=0))


def replay_model_inputs(reader, input_bytes, *, expected_input_id, models,
                        financial_trust=None):
    """Revalidate the pinned original research cutoff; never relabel it current.

    For a new decision, call prepare_model_inputs with the new cutoff instead.
    Hash-identical metadata alone cannot bypass expired/changed original inputs.
    """
    manifest = _input_manifest(input_bytes, expected_input_id)
    bundle = prepare_model_inputs(reader, manifest['dataset_id'], manifest['generation_id'],
        decision_time=manifest['decision_time'], components=manifest['components'],
        consumer_id=manifest['consumer_id'], models=models, financial_trust=financial_trust)
    check(bundle.input_id == expected_input_id, 'MODEL_INPUT_REPLAY_CHANGED')
    return bundle


def plan_model_input_reuse(bundle, requests, *, decision_time):
    """Reuse exact verified price-session slices; unknown coverage never collects.

    This is an invocation-local plan over the successful Reader result. Dates
    outside that slice may already exist in the same generation; therefore they
    require an expanded Reader check, not a provider request or a 'missing' claim.
    Financial periods and macro vintages must use their own existing contracts.
    """
    manifest = _validated_bundle(bundle)
    decision = clock(decision_time)
    check(type(requests) in (list, tuple) and 0 < len(requests) <= 256, 'REUSE_REQUESTS')
    current_cutoff = decision == clock(manifest['decision_time'])
    plans, names, total_sessions = [], set(), 0
    for request in requests:
        check(type(request) is dict and set(request) == {'component_id', 'required_sessions'},
              'REUSE_REQUESTS')
        name, sessions = request['component_id'], request['required_sessions']
        check(type(name) is str and name not in names and name, 'REUSE_REQUESTS')
        names.add(name)
        check(type(sessions) in (list, tuple) and 0 < len(sessions) <= 10000, 'REUSE_SESSIONS')
        parsed = [day(s) for s in sessions]
        total_sessions += len(parsed)
        check(total_sessions <= 100000 and parsed == sorted(set(parsed)) and
              all(s <= decision.date() for s in parsed), 'REUSE_SESSIONS')
        item = bundle.read.results.get(name)
        status, reason, verified = 'BLOCKED', 'COMPONENT_NOT_VERIFIED', []
        if not current_cutoff:
            reason = 'NEW_DECISION_REQUIRES_READER'
        elif item is not None and manifest['dataset_id'] == 'ds.us.prices.daily':
            r = item.receipt
            if r.get('requested_session_coverage_verified') is not True:
                reason = 'COVERAGE_UNKNOWN'
            else:
                verified = sorted(row['session_date'] for row in item.rows)
                if set(sessions) <= set(verified):
                    status, reason = 'REUSE_EXISTING', 'VERIFIED_SESSION_SLICE'
                else:
                    status, reason = 'REVALIDATION_REQUIRED', 'OUTSIDE_VERIFIED_SLICE'
        elif item is not None:
            reason = 'DATASET_SPECIFIC_COVERAGE_REQUIRED'
        verified_set = set(verified)
        plans.append(dict(component_id=name, status=status, reason=reason,
            requested_sessions=list(sessions), verified_sessions=verified,
            unverified_sessions=[s for s in sessions if s not in verified_set],
            collection_sessions=[], collection_approved=False))
    return _freeze(dict(schema='research-model-input-reuse-plan-v1', input_id=bundle.input_id,
        decision_time=decision_time, components=plans, provider_refresh_count=0,
        collection_approved=False, eligible_for_economics=False, eligible_for_selector=False))
