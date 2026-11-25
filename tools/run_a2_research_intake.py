"""Read already-held event evidence into the existing A2 proposal API.

No fetcher, scheduler, Registry writer or source/economic admission is provided.
The caller owns the read-only input tree and supplies an exact request hash and
cutoff. A new result file is an execution output, never a current-state pointer.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research import a2_research_intake_v1 as intake


def need(ok, reason):
    if not ok:
        raise intake.IntakeError(reason)


class Files:
    """Bound reads before allocation; never resolve URLs or traversal aliases.

    This is a loader for a caller-owned, stable local tree, not an OS sandbox
    against a concurrent hostile filesystem writer.
    """
    def __init__(self, root):
        root = Path(root)
        need(not root.is_symlink() and root.is_dir(), 'INPUT_ROOT')
        self.root = root.resolve()
        self.total = 0
        self.read_set = []

    def read(self, ref, role, artifact_id=None, *, limit=None):
        cap = intake.MAX_BYTES if limit is None else limit
        need(type(cap) is int and 0 < cap <= 16 * 1024 * 1024, 'FILE_BYTE_BUDGET')
        need(type(ref) is dict and set(ref) == {'path', 'sha256'}, 'FILE_REFERENCE')
        name, sha = ref['path'], ref['sha256']
        need(type(name) is str and 0 < len(name) <= 512
             and not any(c in name for c in '\\:*?[]\x00'), 'FILE_PATH')
        parts = name.split('/')
        need(not PurePosixPath(name).is_absolute()
             and all(p not in ('', '.', '..') for p in parts), 'FILE_PATH')
        need(type(sha) is str and len(sha) == 64
             and all(c in '0123456789abcdef' for c in sha), 'FILE_HASH')
        path = self.root
        for part in parts:
            path = path / part
            info = path.lstat()
            need(not stat.S_ISLNK(info.st_mode)
                 and not (getattr(info, 'st_file_attributes', 0) & 0x400), 'FILE_LINK')
        need(stat.S_ISREG(info.st_mode), 'FILE_REGULAR')
        need(path.resolve().is_relative_to(self.root), 'FILE_PATH')
        with path.open('rb') as stream:
            info = os.fstat(stream.fileno())
            need(stat.S_ISREG(info.st_mode), 'FILE_REGULAR')
            need(0 < info.st_size <= cap, 'FILE_BYTE_BUDGET')
            need(self.total + info.st_size <= intake.MAX_TOTAL_BYTES, 'FILE_TOTAL_BUDGET')
            raw = stream.read(min(cap,
                                  intake.MAX_TOTAL_BYTES - self.total) + 1)
        need(len(raw) == info.st_size and len(raw) <= cap,
             'FILE_CHANGED_OR_BYTE_BUDGET')
        self.total += len(raw)
        need(intake.digest(raw) == sha, 'FILE_HASH_MISMATCH')
        self.read_set.append(dict(role=role, artifact_id=artifact_id, path=name,
                                  sha256=sha, bytes=len(raw)))
        return raw


def prepare(*, input_root, request_path, request_sha256, cutoff, maturity_only=False):
    intake.stamp(cutoff)
    files = Files(input_root)
    request_raw = files.read({'path': request_path, 'sha256': request_sha256}, 'request')
    request = intake.decode(request_raw)
    need(type(request) is dict, 'FILE_REQUEST_FIELDS')
    if maturity_only:
        need(request.get('schema') == 'a8-maturity-files-v1', 'MATURITY_REQUEST_REQUIRED')
        return prepare_maturity(files, request, cutoff)
    if request.get('schema') == 'a2-candidate-queue-files-v1':
        return prepare_candidate_queue(files, request, request_raw, cutoff)
    need(set(request) == {'schema', 'events', 'identities', 'artifacts', 'event_sources'}
         and request['schema'] == 'a2-file-intake-v1', 'FILE_REQUEST_FIELDS')
    rows = request['artifacts']
    need(type(rows) is list and len(rows) <= intake.MAX_ARTIFACTS, 'FILE_ARTIFACT_COUNT')
    memory, hashes = {}, {}
    for row in rows:
        need(type(row) is dict and set(row) == {'artifact_id', 'path', 'sha256'},
             'FILE_ARTIFACT_FIELDS')
        aid = intake.identifier(row['artifact_id'])
        need(aid not in memory and not aid.startswith('SCHEMA:'), 'FILE_ARTIFACT_ID')
        raw = files.read({'path': row['path'], 'sha256': row['sha256']}, 'artifact', aid)
        memory[aid], hashes[aid] = raw, row['sha256']
    events_raw = files.read(request['events'], 'events')
    identities_raw = files.read(request['identities'], 'identities')
    schema_name, schema_sha = intake.SCHEMAS['events']
    schema_raw = Files(ROOT).read({'path': 'research/control_plane/' + schema_name,
                                   'sha256': schema_sha}, 'schema')
    memory['SCHEMA:' + schema_name] = schema_raw
    result = intake.validate_events(events_raw, cutoff=cutoff,
        artifact_resolver=intake.MemoryArtifacts(memory), identities=identities_raw)
    bindings = request['event_sources']
    need(type(bindings) is dict
         and set(bindings) == {row['event_id'] for row in result['events']},
         'FILE_EVENT_SOURCE_SCOPE')
    sources = {}
    for eid, aids in bindings.items():
        need(type(aids) is list and 0 < len(aids) <= 10
             and all(type(aid) is str and aid in hashes for aid in aids)
             and len(aids) == len(set(aids)), 'FILE_EVENT_SOURCE_REFERENCE')
        sources[eid] = [dict(artifact_id=aid, sha256=hashes[aid]) for aid in aids]
    return dict(schema='a2-file-intake-result-v1', status='READ_ONLY_RESEARCH_PROPOSAL',
        cutoff=cutoff, request_sha256=intake.digest(request_raw),
        code_identity=dict(adapter_sha256=intake.digest(Path(__file__).read_bytes()),
                           intake_sha256=intake.digest(Path(intake.__file__).read_bytes()),
                           schema_sha256=schema_sha),
        read_set=files.read_set, event_source_bindings=sources, proposal=result,
        source_authenticity='NOT_VERIFIED', semantic_claim_review='NOT_VERIFIED',
        recurring_pipeline_connected=False, authority=intake.closed())


def prepare_maturity(files, request, cutoff):
    """Replay the private frozen cohort and route only changed measured outcomes."""
    from tools import candidate_reassessment_bridge as bridge

    fields = {'schema', 'frozen', 'previous', 'current', 'previous_response',
              'calendar', 'identities', 'implementation', 'expires_at'}
    need(set(request) == fields, 'MATURITY_REQUEST_FIELDS')
    need(intake.stamp(cutoff) < intake.stamp(request['expires_at']), 'MATURITY_ROUTE_EXPIRED')
    calendar_raw = files.read(request['calendar'], 'frozen_calendar')
    calendar = intake.decode(calendar_raw)
    identities = files.read(request['identities'], 'frozen_identities')
    implementation_raw = files.read(request['implementation'], 'frozen_implementation')
    implementation = intake.decode(implementation_raw)
    need(isinstance(implementation, dict) and 'base_commit' in implementation,
         'MATURITY_IMPLEMENTATION')
    schema_name, schema_hash = intake.SCHEMAS['cohort']
    schema = Files(ROOT).read({'path': 'research/control_plane/' + schema_name,
                               'sha256': schema_hash}, 'native_schema')

    def replay(role):
        refs = request[role]
        need(type(refs) is dict and set(refs) == {'cohort', 'outcomes'}, 'MATURITY_FILE_REFS')
        raw = files.read(refs['cohort'], role)
        doc = intake.decode(raw)
        need(type(doc) is dict and type(doc.get('calendar_ref')) is dict
             and isinstance(doc['calendar_ref'].get('artifact_id'), str), 'MATURITY_CALENDAR')
        calendar_id = doc['calendar_ref']['artifact_id']
        need(not calendar_id.startswith('SCHEMA:'), 'MATURITY_CALENDAR')
        memory = {'SCHEMA:' + schema_name: schema, calendar_id: calendar_raw}
        outref = doc.get('outcome_ref')
        if outref is None:
            need(refs['outcomes'] is None, 'MATURITY_OUTCOME_REF')
        else:
            need(type(outref) is dict and isinstance(outref.get('artifact_id'), str)
                 and outref['artifact_id'] not in memory, 'MATURITY_OUTCOME_REF')
            memory[outref['artifact_id']] = files.read(refs['outcomes'], role + '_outcomes')
        result = intake.validate_cohort(raw, cutoff=cutoff, identities=identities,
                                        artifact_resolver=intake.MemoryArtifacts(memory))
        return doc, result

    frozen, base = replay('frozen')
    prior, old = replay('previous')
    current, new = replay('current')
    prior_receipt = files.read(request['previous_response'], 'previous_response')
    need(intake.canonical(old) == prior_receipt, 'MATURITY_PREVIOUS_RECEIPT')
    need(frozen['outcome_ref'] is None and base['denominator_count'] > 0
         and intake.stamp(frozen['generated_at']) <= intake.stamp(prior['generated_at'])
         <= intake.stamp(current['generated_at']) <= intake.stamp(cutoff),
         'MATURITY_SEQUENCE')
    need(frozen['calendar_ref'] == prior['calendar_ref'] == current['calendar_ref'],
         'MATURITY_CALENDAR_CHANGED')
    variable = {'status', 'asset_return', 'benchmark_return', 'excess_return',
                'outcome_session', 'outcome_available_at', 'source_sha256'}

    def keyed(result):
        return {(r['decision_id'], r['horizon']): r for r in result['rows']}

    original, before, after = map(keyed, (base, old, new))
    need(original.keys() == before.keys() == after.keys(), 'MATURITY_DENOMINATOR')
    events, subjects = [], {}
    measured = unchanged = due_missing = 0
    models = set()
    for key, row in after.items():
        previous = before[key]
        fixed = {k: v for k, v in original[key].items() if k not in variable}
        need(all(all(r[k] == v for k, v in fixed.items()) for r in (previous, row)),
             'MATURITY_FROZEN_ROW_CHANGED')
        need(row['code_sha256'] == intake.digest(implementation_raw), 'MATURITY_IMPLEMENTATION_HASH')
        models.add((row['model_id'], row['config_sha256']))
        event_id = ':'.join(key)
        closed = calendar['targets'][event_id]['close_at']
        if row['status'] != 'MATURED':
            need(previous['status'] != 'MATURED', 'MATURITY_PREVIOUS_OUTCOME_WITHDRAWN')
            due_missing += int(intake.stamp(closed) <= intake.stamp(cutoff))
            continue
        measured += 1
        # The reference hashes the whole batch. Adding another maturity to the
        # batch must not reissue earlier rows with unchanged values and clocks.
        if all(previous[k] == row[k] for k in variable - {'source_sha256'}):
            unchanged += 1
            continue
        subjects[row['asset_id']] = dict(asset_id=row['asset_id'], issuer_id=row['issuer_id'])
        events.append(dict(event_id=event_id, kind='OUTCOME_MATURED', entity_kind='SECURITY',
                           entity_id=row['asset_id'], due_at=closed, evidence_sha256=row['source_sha256']))
    need(len(models) == 1, 'MATURITY_MODEL_SCOPE')
    response_hash = intake.digest(intake.canonical(new))
    result = dict(schema='a8-private-maturity-research-v1', status='SKIP_UNCHANGED',
                  frozen_input_sha256=base['input_sha256'], previous_response_sha256=intake.digest(prior_receipt),
                  current_response_sha256=response_hash, denominator_count=len(original), measured_count=measured,
                  unchanged_count=unchanged, due_unmeasured_count=due_missing, changed_count=len(events),
                  learning_eligible=False, outcome_admission_status=new['outcome_admission_status'],
                  authority=intake.closed(), proposal=None, a0_parameters={})
    if not events:
        if due_missing:
            result['status'] = 'PENDING_VERIFIED_OUTCOMES'
        return result
    model, config = next(iter(models))
    contract = dict(code_sha=implementation['base_commit'], model_version=model, config_sha256=config,
                    parameters_sha256=config, dependency_sha256=response_hash)
    try:
        snapshot = bridge.snapshot([], scope_id='A8:' + base['input_sha256'], cutoff=cutoff,
                                   expires_at=request['expires_at'])
        index = bridge.exposure_index(candidates=list(subjects.values()), edges=[],
                                      available_at=cutoff, expires_at=request['expires_at'])
        plan = bridge.plan_reassessment(None, snapshot, index, now=cutoff,
                                        contract_identity=contract, due_events=events)
        parameters = bridge.a0_parameter_proposals(plan)
    except bridge.ReassessmentError as exc:
        raise intake.IntakeError(str(exc)) from None
    need(set(parameters) == {'A8'} and not plan['execute'] and not plan['canonical_write'],
         'MATURITY_AUTHORITY')
    result.update(status='VALID_RESEARCH_PROPOSAL', proposal=plan, a0_parameters=parameters)
    return result


def prepare_candidate_queue(files, request, request_raw, cutoff):
    """Join explicit native CSV selections into the existing pending queue.

    Observation clocks describe seeing the producer output, not publication of
    its underlying filings/prices. Neither scores nor a new observation clock
    can establish source freshness, an investment conclusion or data admission.
    """
    fields = {'schema', 'identities', 'sources'}
    need(set(request) in (fields, fields | {'retain_missing_candidates'}),
         'CANDIDATE_REQUEST_FIELDS')
    retain_missing = request.get('retain_missing_candidates', False)
    need(type(retain_missing) is bool, 'CANDIDATE_RETENTION_POLICY')
    sources = request['sources']
    need(type(sources) is list and 0 < len(sources) <= 10, 'CANDIDATE_SOURCE_COUNT')
    identities_raw = files.read(request['identities'], 'identities')
    subjects = intake._identities(identities_raw)
    by_ticker = {}
    for sid, (issuer, aliases) in subjects.items():
        for ticker in aliases:
            by_ticker.setdefault(ticker, []).append((sid, issuer))
    kinds = {'SEC_OWNERSHIP', 'SEC_13F', 'POST_DISCLOSURE', 'FUNDAMENTAL_EARNINGS',
             'RELATIVE_STRENGTH', 'ESTIMATE_REVISION', 'FUSION_REVIEW'}
    channels = ['price', 'fundamentals', 'thesis', 'valuation', 'expected_return',
                'identity', 'corporate_actions', 'listing_history', 'filings',
                'consensus', 'rights', 'liquidity']
    items, bindings, source_ids, csv_cache = {}, [], set(), {}
    for source in sources:
        need(type(source) is dict and set(source) ==
             {'kind', 'file', 'ticker_column', 'tickers', 'polarity', 'observed_at'},
             'CANDIDATE_SOURCE_FIELDS')
        kind, column, tickers = source['kind'], source['ticker_column'], source['tickers']
        need(type(kind) is str and kind in kinds, 'CANDIDATE_SOURCE_KIND')
        need(source['polarity'] in ('CANDIDATE', 'RISK_WATCH'), 'CANDIDATE_POLARITY')
        intake.identifier(column)
        need(type(tickers) is list and 0 < len(tickers) <= 1000, 'CANDIDATE_SELECTION_COUNT')
        for ticker in tickers:
            intake.identifier(ticker)
        need(len(set(tickers)) == len(tickers), 'CANDIDATE_DUPLICATE_SELECTION')
        selection = set(tickers)
        observed = source['observed_at']
        need(intake.stamp(observed) <= intake.stamp(cutoff), 'CANDIDATE_OBSERVATION_CLOCK')
        # Native scored_latest.csv is larger than the default JSON object cap.
        # Only CSV gets this explicit 16MiB cap; the shared 32MiB budget remains.
        file_key = intake.canonical(source['file'])
        if file_key not in csv_cache:
            csv_cache[file_key] = files.read(source['file'], 'candidate_csv', limit=16 * 1024 * 1024)
        raw = csv_cache[file_key]
        sha = intake.digest(raw)
        source_id = (kind, sha, source['polarity'])
        need(source_id not in source_ids, 'CANDIDATE_DUPLICATE_SOURCE')
        source_ids.add(source_id)
        try:
            reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
            header = reader.fieldnames
            need(header and len(header) <= 2048 and len(header) == len(set(header))
                 and column in header, 'CANDIDATE_CSV_HEADER')
            selected, row_count = {}, 0
            for ordinal, row in enumerate(reader, 1):
                row_count = ordinal
                need(ordinal <= 10000 and None not in row and None not in row.values(),
                     'CANDIDATE_CSV_ROWS')
                ticker = row[column]
                if ticker in selection:
                    selected.setdefault(ticker, []).append(dict(
                        data_row=ordinal, row_sha256=intake.digest(intake.canonical(row))))
        except (UnicodeError, csv.Error):
            raise intake.IntakeError('CANDIDATE_CSV_ENCODING_OR_SYNTAX') from None
        missing = sorted(selection - set(selected))
        need(retain_missing or not missing, 'CANDIDATE_SELECTED_TICKER_MISSING')
        source_bindings = []
        for ticker in sorted(selection):
            rows = selected.get(ticker, [])
            matches = by_ticker.get(ticker, [])
            need(len(matches) == 1, 'CANDIDATE_EXACT_SECURITY_MAPPING')
            sid, issuer = matches[0]
            item = items.setdefault(sid, dict(asset_id=sid, identity_kind='LISTED_SECURITY',
                security_id=sid, issuer_id=issuer, ticker=ticker, state='DATA_PENDING',
                membership_reasons=[], required_channels=channels,
                channel_status={c: 'CONSUMER_RECEIPT_MISSING' for c in channels},
                next_action='LOOKUP_EXISTING_INPUTS_BEFORE_COLLECTION', first_seen_at=observed,
                last_checked_at=cutoff, authority=intake.closed()))
            item['ticker'] = min(item['ticker'], ticker)
            if intake.stamp(observed) < intake.stamp(item['first_seen_at']):
                item['first_seen_at'] = observed
            evidence = dict(kind=kind, source_sha256=sha, security_id=sid,
                            ticker=ticker, polarity=source['polarity'], rows=rows)
            reason_id = ('CANDIDATE_REVIEW:' if rows else 'CANDIDATE_DATA_PENDING:') + intake.digest(intake.canonical(evidence))
            item['membership_reasons'].append(dict(security_id=sid, ticker=ticker,
                reason_type='PRODUCER_OUTPUT_REVIEW' if rows else 'REQUESTED_CANDIDATE_DATA_PENDING',
                source_kind=kind, polarity=source['polarity'],
                status='ACTIVE', first_seen_at=observed, last_observed_at=observed, valid_until='',
                source_event_id=reason_id, source_hash=sha,
                source_quality='UNVERIFIED_PRODUCER_OUTPUT' if rows else 'MISSING_PRODUCER_ROW',
                security_type='EQUITY', notes=(
                    'Review trigger only; source publication, expiry, rights, '
                    'PIT and economic value remain unverified. Native scores confer no direct score.'
                    if rows else
                    'Retained by the explicit hash-bound request despite an absent producer row. '
                    'This is a data lookup request, not an observed financial, price or technical signal. '
                    'Missing values are unknown, not zero. Reuse existing inputs before collection.')))
            source_bindings.append(dict(**evidence, reason_id=reason_id))
        bindings.append(dict(kind=kind, file=source['file'], total_rows=row_count,
            selected_rows=sum(len(r) for r in selected.values()), selected_tickers=len(selected),
            observed_at=observed, observation_is_publication=False,
            source_publication_at=None, source_expiry_at=None, bindings=source_bindings))
        if retain_missing:
            bindings[-1].update(requested_tickers=len(selection),
                                missing_selected_tickers=missing)
    for item in items.values():
        item['membership_reasons'].sort(key=lambda r: r['source_event_id'])
    queue = dict(schema_version='candidate-data-queue-v1', as_of=cutoff, research_only=True,
        direct_score_contribution=0, authority=intake.closed(),
        items=[items[sid] for sid in sorted(items)])
    name, sha = intake.SCHEMAS['queue']
    schema_raw = Files(ROOT).read({'path': 'research/control_plane/' + name, 'sha256': sha}, 'schema')
    proposal = intake.validate_queue(intake.canonical(queue), cutoff=cutoff,
        artifact_resolver=intake.MemoryArtifacts({'SCHEMA:' + name: schema_raw}), identities=identities_raw)
    result = dict(schema='a2-candidate-queue-result-v1', status='READ_ONLY_RESEARCH_PROPOSAL',
        cutoff=cutoff, request_sha256=intake.digest(request_raw), read_set=files.read_set,
        code_identity=dict(adapter_sha256=intake.digest(Path(__file__).read_bytes()),
                           intake_sha256=intake.digest(Path(intake.__file__).read_bytes()), schema_sha256=sha),
        producer_bindings=bindings, queue=queue, proposal=proposal,
        source_authenticity='NOT_VERIFIED', source_freshness='NOT_VERIFIED', source_independence='NOT_VERIFIED',
        recurring_pipeline_connected=False, authority=intake.closed())
    if retain_missing:
        result['candidate_retention'] = dict(
            policy='KEEP_EXPLICIT_REQUESTED_CANDIDATES_DATA_PENDING',
            request_sha256=intake.digest(request_raw),
            missing_producer_row_securities=sorted({e['security_id'] for p in bindings
                for e in p['bindings'] if not e['rows']}),
            current_roster_authority='CALLER_SUPPLIED_EXACT_IDENTITIES_AND_REQUEST_NOT_RANKED_CSV',
            absence_is_rejection=False, missing_values_imputed=False,
            collection_dispatched=False, membership_or_investment_admitted=False)
    return result


def write_result(path, result):
    """Expose the final name only after the local file has fully closed.

    Hard-link creation is atomic/create-only on the supported local filesystem.
    Unsupported filesystems fail closed. This is not a durable account commit.
    """
    raw = intake.canonical(result)
    path, temporary, cleanup = Path(path), None, True
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent,
                prefix='.a2-intake-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            need(stream.write(raw) == len(raw), 'OUTPUT_SHORT_WRITE')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                # A cleanup failure cannot undo a published, complete result
                # or change a pre-publication refusal into a successful result.
                cleanup = False
    return dict(status=result['status'], result_sha256=intake.digest(raw),
                bytes=len(raw), temporary_cleanup_complete=cleanup)


def write_maturity_result(path, result):
    """A repeated delivery produces neither another file nor another event."""
    path = Path(path)
    summary = {k: result[k] for k in ('status', 'denominator_count', 'measured_count',
               'unchanged_count', 'changed_count', 'due_unmeasured_count', 'learning_eligible')}
    summary['result_written'] = False
    summary['proposal_events_written'] = 0
    if result['changed_count'] == 0:
        return summary
    body_hash = intake.digest(intake.canonical(result))
    if not path.exists() and not path.is_symlink():
        try:
            receipt = write_result(path, result)
            return dict(summary, result_written=True, proposal_events_written=result['changed_count'],
                        result_sha256=receipt['result_sha256'])
        except FileExistsError:
            # Another process won create-only publication of this exact path.
            pass
    Files(path.parent).read({'path': path.name, 'sha256': body_hash}, 'existing_maturity_result')
    return dict(summary, status='REUSED_IDENTICAL_RESEARCH_PROPOSAL', result_sha256=body_hash)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--request', required=True, help='Relative path below the read-only input root')
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--cutoff', required=True, help='Explicit aware research cutoff; no wallclock inference')
    parser.add_argument('--output', required=True, help='A new local proposal file; parent must already exist')
    parser.add_argument('--maturity-only', action='store_true', help='Replay only the private A8 maturity request')
    args = parser.parse_args(argv)
    try:
        if not args.maturity_only:
            need(not Path(args.output).exists() and not Path(args.output).is_symlink(),
                 'OUTPUT_ALREADY_EXISTS')
        result = prepare(input_root=args.input_root, request_path=args.request,
                         request_sha256=args.request_sha256, cutoff=args.cutoff,
                         maturity_only=args.maturity_only)
        summary = write_maturity_result(args.output, result) if args.maturity_only else write_result(args.output, result)
    except intake.IntakeError as exc:
        summary = dict(status='BLOCKED', reason=str(exc), result_completed=False)
    except OSError:
        summary = dict(status='BLOCKED', reason='FILE_ACCESS_OR_EXISTING_OUTPUT', result_completed=False)
    print(json.dumps(summary, sort_keys=True))
    return 2 if summary['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
