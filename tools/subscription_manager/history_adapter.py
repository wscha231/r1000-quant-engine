"""Read-only long-history inputs for the subscription model-cycle.

Reuse Lake's complete archive/receipt checks; never collect or publish data.
Coverage is research inventory, not normalized statements, fresh quotes, a
reviewed investment proposal, historical PIT, or permission to execute events.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.long_history_lake import Lake, diagnostics, issuer_queue, unpacked
from tools.macro_history_sources import digest, encoded, require, stamp
from tools.macro_research_checkpoint import (
    LocalTransport, RcloneTransport, checked_bytes, safe_path,
)

SCHEMA = 'subscription-history-input-v1'
GOOD = {'COLLECTED', 'UNCHANGED'}
STATES = GOOD | {'BLOCKED', 'STALE_RETAINED'}
LIMITS = dict(orders_allowed=False, commercial_release_allowed=False,
              auto_promotion=False, model_execution_allowed=False,
              historical_training_allowed=False, eligible_for_selector=False)


def hash_value(value, length=64):
    require(isinstance(value, str) and
            re.fullmatch('[a-f0-9]{' + str(length) + '}', value), 'input_hash_format')
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def read_pinned(path, expected):
    raw = checked_bytes(Path(path), hash_value(expected))
    def invalid_number(_):
        raise ValueError('nonfinite_json')
    return json.loads(raw, object_pairs_hook=unique_object,
                      parse_constant=invalid_number), raw


class ReadOnlyRcloneTransport(RcloneTransport):
    """Including constructor recovery: a missing folder cannot cause mkdir."""
    def call(self, *args):
        require(args and args[0] in {'lsjson', 'cat'}, 'read_only_transport')
        return super().call(*args)

    def write(self, *_):
        raise ValueError('read_only_transport')

    def upload(self, *_):
        raise ValueError('read_only_transport')


class ReadOnlyTransport:
    """Expose only reads to Lake, for remote or local-copy consumers."""
    def __init__(self, transport):
        self._transport = transport
        self.remote_verified = transport.remote_verified

    def names(self, prefix):
        return self._transport.names(prefix)

    def read(self, path):
        return self._transport.read(path)

    def write(self, *_):
        raise ValueError('read_only_transport')


def members(payload, decision):
    require(isinstance(payload, dict) and isinstance(payload.get('rows'), list),
            'cohort_schema')
    rows = payload['rows']
    require(type(payload.get('candidate_count')) is int and
            payload['candidate_count'] == len(rows) and len(rows) >= 1000,
            'whole_cohort_required')
    require(date.fromisoformat(payload['as_of']) <= decision.date(), 'future_cohort')
    identities = {}
    tickers = set()
    for row in rows:
        sid, ticker = row.get('security_id'), row.get('ticker')
        require(isinstance(sid, str) and re.fullmatch(r'US:[A-Za-z0-9.-]{1,30}', sid)
                and isinstance(ticker, str) and
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,14}', ticker),
                'cohort_security_identity')
        require(sid not in identities and ticker not in tickers, 'duplicate_security')
        identities[sid] = ticker
        tickers.add(ticker)
    return identities


def build_input(lake, cohort, cohort_sha256, *, commit_sha256, catalog_sha256,
                execution_sha256, source_commit, decision_at, max_age_hours=48,
                partial_policy='research', required_datasets=()):
    """Bind caller's full cohort to the exact latest archive, preserving missingness.

    Lake must have completed its normal full restore. No metadata-only or
    selected-pack shortcut is accepted, and no historical failure is hidden.
    """
    for value in (commit_sha256, catalog_sha256, execution_sha256, cohort_sha256):
        hash_value(value)
    hash_value(source_commit, 40)
    decision = stamp(decision_at)
    require(type(max_age_hours) is int and 0 < max_age_hours <= 168,
            'freshness_window')
    require(partial_policy in {'research', 'reject'}, 'partial_policy')
    require(lake.parent == commit_sha256 and not lake.pending, 'history_head_mismatch')
    commit = json.loads(lake.read_hash('commits', commit_sha256))
    chain = {commit_sha256}
    previous = commit.get('parent')
    while previous is not None:
        require(previous not in chain, 'history_chain_cycle')
        chain.add(previous)
        previous = json.loads(lake.read_hash('commits', previous)).get('parent')
    require(commit['catalog'] == catalog_sha256, 'history_catalog_mismatch')
    require(digest(encoded(lake.catalog)) == catalog_sha256, 'mutated_catalog')
    catalog = lake.catalog
    require(catalog.get('code_sha') == source_commit and
            catalog.get('run_id') == commit.get('run_id'), 'history_source_mismatch')
    require(digest(encoded(catalog['config'])) == catalog['config_sha256'],
            'history_config_hash')
    execution = lake.verified_execution()
    require(execution['execution_receipt_sha256'] == execution_sha256,
            'history_execution_mismatch')
    require(execution['study_recomputed_from_drive'] is True, 'study_not_completed')
    created, completed = stamp(catalog['created_at']), stamp(execution['created_at'])
    require(created <= completed <= decision and
            created <= stamp(commit['created_at']) <= completed, 'history_availability')
    require(decision - completed <= timedelta(hours=max_age_hours), 'stale_execution')
    require(date.fromisoformat(catalog['config']['through']) <= decision.date(),
            'future_history_window')
    quality = json.loads(lake.read_hash('reports', execution['reports']['quality.json']))
    require(stamp(quality['as_of']) <= completed, 'quality_availability')
    # Recompute semantic coverage; a valid hash alone does not certify its counts.
    recomputed = diagnostics(lake)
    for key, value in recomputed.items():
        if key != 'as_of':
            require(quality.get(key) == value, 'quality_coverage_mismatch')
    if partial_policy == 'reject':
        require(quality['status'] != 'PARTIAL', 'partial_history')

    consumer, consumer_raw = read_pinned(cohort, cohort_sha256)
    expected_members = members(consumer, decision)
    dataset = catalog['datasets']['universe/cohort']
    require(dataset['status'] in GOOD, 'cohort_not_consumable')
    archived_rows = lake.get_records('universe/cohort')
    require(len(dataset['raw_objects']) == 2, 'cohort_source_contract')
    original = unpacked(lake.get_bytes(dataset['raw_objects'][0]))
    require(digest(original) == catalog['config']['cohort_sha256'], 'archive_cohort_hash')
    archived = json.loads(original)
    require(archived_rows == archived['rows'], 'cohort_normalization_mismatch')
    archive_members = members(archived, decision)
    require(archive_members == expected_members, 'cohort_identity_mismatch')
    require(dataset['rows'] == dataset['requested_securities'] == len(archive_members),
            'cohort_count_mismatch')
    mapping = json.loads(unpacked(lake.get_bytes(dataset['raw_objects'][1])))
    groups, missing = issuer_queue(archived_rows, mapping)
    require(sorted(groups) == sorted(key.removeprefix('sec/')
            for key in dataset['active_issuer_keys']) and
            len(groups) == dataset['mapped_issuers'] and missing == dataset['missing'],
            'issuer_mapping_mismatch')
    reverse = {ticker: cik for cik, tickers in groups.items() for ticker in tickers}

    sources = {}
    for key, entry in sorted(catalog['datasets'].items()):
        require(entry.get('status') in STATES, 'dataset_status')
        checked = stamp(entry['checked_at'])
        require(checked <= completed, 'dataset_check_availability')
        fresh = decision - checked <= timedelta(hours=max_age_hours)
        usable = entry['status'] in GOOD and fresh
        if entry.get('retrieved_at'):
            require(stamp(entry['retrieved_at']) <= checked, 'dataset_retrieval_availability')
        sources[key] = dict(status=entry['status'], fresh=fresh, research_readable=usable,
            checked_at=entry['checked_at'], retrieved_at=entry.get('retrieved_at'),
            evidence=entry.get('evidence'), rows=entry.get('rows'),
            earliest=entry.get('earliest'), latest=entry.get('latest'),
            first_filed=entry.get('first_filed'), last_filed=entry.get('last_filed'),
            normalized_sha256=entry.get('normalized'), raw_sha256=entry.get('raw_objects', []),
            statement_completeness=entry.get('statement_completeness'),
            quarter_completeness=entry.get('quarter_completeness'),
            missing_years=entry.get('missing_years'),
            missing_values=entry.get('missing_values'), last_failure=entry.get('last_failure'))
    require(sources['universe/cohort']['research_readable'], 'stale_cohort')
    securities = []
    for sid, ticker in sorted(expected_members.items()):
        cik = reverse.get(ticker)
        key = 'sec/' + cik if cik else None
        source = sources.get(key)
        if cik:
            require(source is not None, 'active_issuer_missing')
            entry = catalog['datasets'][key]
            if source['status'] in GOOD:
                require(entry.get('cik') == cik and
                        sorted(entry.get('tickers', [])) == sorted(groups[cik]),
                        'issuer_security_mismatch')
        securities.append(dict(security_id=sid, ticker=ticker, cik=cik, dataset=key,
            research_readable=bool(source and source['research_readable']),
            missing_reason=('CIK_MISSING_OR_AMBIGUOUS' if not cik else
                None if source['research_readable'] else
                source['status'] if source['status'] not in GOOD else 'STALE_DATASET')))
    required = sorted(set(required_datasets))
    require(len(required) == len(required_datasets), 'duplicate_requested_dataset')
    selected = {}
    for key in required:
        require(key in sources and sources[key]['research_readable'], 'required_dataset_unavailable')
        rows = lake.get_records(key)
        require(len(rows) == sources[key]['rows'], 'consumed_rows_mismatch')
        # Current revised observations are admitted only as current research.
        # No source row is rewritten, imputed, or relabelled historical PIT.
        selected[key] = dict(rows=rows, records_sha256=digest(encoded(rows)))
    active = set(dataset['active_issuer_keys'])
    stale = sorted(key for key, value in sources.items() if not value['fresh'] and
                   (not key.startswith('sec/') or key in active))
    result = dict(schema=SCHEMA, mode='RESEARCH_ONLY', data_kind='REAL_SOURCE_RESEARCH',
        status='PARTIAL_RESEARCH_INPUT' if quality['status'] == 'PARTIAL' or stale
               else 'COLLECTED_RESEARCH_INPUT',
        decision_at=decision.isoformat(), max_age_hours=max_age_hours,
        partial_policy=partial_policy, required_datasets=required,
        provenance=dict(commit_sha256=commit_sha256, catalog_sha256=catalog_sha256,
            execution_receipt_sha256=execution_sha256, collector_source_commit=source_commit,
            run_id=execution['run_id'], reports=execution['reports'],
            history_cohort_sha256=catalog['config']['cohort_sha256'],
            model_cohort_sha256=digest(consumer_raw), config_sha256=catalog['config_sha256'],
            catalog_created_at=catalog['created_at'], execution_created_at=execution['created_at'],
            adapter_code_sha256={path: digest((ROOT/path).read_bytes()) for path in (
                'tools/subscription_manager/history_adapter.py',
                'tools/subscription_manager/run_model_cycle.py',
                'tools/long_history_lake.py', 'tools/macro_history_sources.py',
                'tools/macro_research_checkpoint.py')},
            archive_bytes_verified=True, remote_verified=lake.transport.remote_verified),
        coverage=dict(requested_securities=len(securities), mapped_issuers=len(groups),
            securities_research_readable=sum(row['research_readable'] for row in securities),
            missing_identities=missing, financial_issuers_collected=quality['financial_issuers_collected'],
            financial_fact_rows=quality['financial_fact_rows'], upstream_status=quality['status'],
            stale_datasets=stale, historical_membership_verified=False,
            three_statement_ten_year_completeness='NOT_CERTIFIED', historical_pit_certified=False),
        source_window=catalog['config'], price_snapshot_as_of=archived['as_of'],
        current_prices_verified=False, securities=securities, datasets=sources,
        selected_records=selected, **LIMITS)
    # Detect a newer publication even when the requested pinned commit still exists.
    names = lake.transport.names('long-history-v1/commits')
    require(len(names) == len(set(names)) and set(names) == chain and
            len(names) == catalog['generation'], 'history_changed_during_read')
    return result


def prepare_history(*, output, workspace, cohort, cohort_sha256, commit_sha256,
                    catalog_sha256, execution_sha256, source_commit, decision_at,
                    remote=None, local_archive=None, max_age_hours=48,
                    partial_policy='research', required_datasets=()):
    require(bool(remote) != bool(local_archive), 'one_history_transport_required')
    output, workspace = safe_path(output), safe_path(workspace)
    require(not output.exists() and not workspace.exists(), 'new_run_directory_required')
    require(output != workspace and output not in workspace.parents and
            workspace not in output.parents, 'separate_output_and_cache')
    if local_archive:
        archive = safe_path(local_archive)
        require(archive.is_dir(), 'local_archive_missing')
        require(all(path != archive and archive not in path.parents and
                    path not in archive.parents for path in (output, workspace)),
                'history_archive_is_read_only')
        transport = LocalTransport(archive)
    else:
        transport = ReadOnlyRcloneTransport(remote)
    lake = Lake(ReadOnlyTransport(transport), workspace)
    result = build_input(lake, cohort, cohort_sha256, commit_sha256=commit_sha256,
        catalog_sha256=catalog_sha256, execution_sha256=execution_sha256,
        source_commit=source_commit, decision_at=decision_at, max_age_hours=max_age_hours,
        partial_policy=partial_policy, required_datasets=required_datasets)
    output.mkdir(parents=True)
    raw = encoded(result)
    with (output / 'history-input.json').open('xb') as handle:
        handle.write(raw)
    require((output / 'history-input.json').read_bytes() == raw, 'input_readback')
    manifest = dict(schema='subscription-model-input-manifest-v1',
        status=result['status'], files={'history-input.json': digest(raw)},
        coverage=result['coverage'], provenance=result['provenance'],
        drive_saved=False, model_cycle_events_executed=False, **LIMITS)
    with (output / 'manifest.json').open('xb') as handle:
        handle.write(encoded(manifest))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument('--remote')
    transport.add_argument('--local-archive', type=Path)
    for flag in ('cohort', 'workspace', 'output'):
        parser.add_argument('--' + flag, type=Path, required=True)
    for flag in ('cohort-sha256', 'commit-sha256', 'catalog-sha256',
                 'execution-sha256', 'source-commit', 'decision-at'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--max-age-hours', type=int, default=48)
    parser.add_argument('--partial-policy', choices=('research', 'reject'), default='research')
    parser.add_argument('--required-dataset', action='append', default=[], dest='required_datasets')
    result = prepare_history(**vars(parser.parse_args(argv)))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
