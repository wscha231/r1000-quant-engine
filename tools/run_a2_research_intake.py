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


def prepare(*, input_root, request_path, request_sha256, cutoff):
    intake.stamp(cutoff)
    files = Files(input_root)
    request_raw = files.read({'path': request_path, 'sha256': request_sha256}, 'request')
    request = intake.decode(request_raw)
    need(type(request) is dict, 'FILE_REQUEST_FIELDS')
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


def prepare_candidate_queue(files, request, request_raw, cutoff):
    """Join explicit native CSV selections into the existing pending queue.

    Observation clocks describe seeing the producer output, not publication of
    its underlying filings/prices. Neither scores nor a new observation clock
    can establish source freshness, an investment conclusion or data admission.
    """
    need(set(request) == {'schema', 'identities', 'sources'}, 'CANDIDATE_REQUEST_FIELDS')
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
        need(set(selected) == selection, 'CANDIDATE_SELECTED_TICKER_MISSING')
        source_bindings = []
        for ticker, rows in sorted(selected.items()):
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
            reason_id = 'CANDIDATE_REVIEW:' + intake.digest(intake.canonical(evidence))
            item['membership_reasons'].append(dict(security_id=sid, ticker=ticker,
                reason_type='PRODUCER_OUTPUT_REVIEW', source_kind=kind, polarity=source['polarity'],
                status='ACTIVE', first_seen_at=observed, last_observed_at=observed, valid_until='',
                source_event_id=reason_id, source_hash=sha, source_quality='UNVERIFIED_PRODUCER_OUTPUT',
                security_type='EQUITY', notes='Review trigger only; source publication, expiry, rights, '
                'PIT and economic value remain unverified. Native scores confer no direct score.'))
            source_bindings.append(dict(**evidence, reason_id=reason_id))
        bindings.append(dict(kind=kind, file=source['file'], total_rows=row_count,
            selected_rows=sum(len(r) for r in selected.values()), selected_tickers=len(selected),
            observed_at=observed, observation_is_publication=False,
            source_publication_at=None, source_expiry_at=None, bindings=source_bindings))
    for item in items.values():
        item['membership_reasons'].sort(key=lambda r: r['source_event_id'])
    queue = dict(schema_version='candidate-data-queue-v1', as_of=cutoff, research_only=True,
        direct_score_contribution=0, authority=intake.closed(),
        items=[items[sid] for sid in sorted(items)])
    name, sha = intake.SCHEMAS['queue']
    schema_raw = Files(ROOT).read({'path': 'research/control_plane/' + name, 'sha256': sha}, 'schema')
    proposal = intake.validate_queue(intake.canonical(queue), cutoff=cutoff,
        artifact_resolver=intake.MemoryArtifacts({'SCHEMA:' + name: schema_raw}), identities=identities_raw)
    return dict(schema='a2-candidate-queue-result-v1', status='READ_ONLY_RESEARCH_PROPOSAL',
        cutoff=cutoff, request_sha256=intake.digest(request_raw), read_set=files.read_set,
        code_identity=dict(adapter_sha256=intake.digest(Path(__file__).read_bytes()),
                           intake_sha256=intake.digest(Path(intake.__file__).read_bytes()), schema_sha256=sha),
        producer_bindings=bindings, queue=queue, proposal=proposal,
        source_authenticity='NOT_VERIFIED', source_freshness='NOT_VERIFIED', source_independence='NOT_VERIFIED',
        recurring_pipeline_connected=False, authority=intake.closed())


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--request', required=True, help='Relative path below the read-only input root')
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--cutoff', required=True, help='Explicit aware research cutoff; no wallclock inference')
    parser.add_argument('--output', required=True, help='A new local proposal file; parent must already exist')
    args = parser.parse_args(argv)
    try:
        need(not Path(args.output).exists() and not Path(args.output).is_symlink(),
             'OUTPUT_ALREADY_EXISTS')
        result = prepare(input_root=args.input_root, request_path=args.request,
                         request_sha256=args.request_sha256, cutoff=args.cutoff)
        summary = write_result(args.output, result)
    except intake.IntakeError as exc:
        summary = dict(status='BLOCKED', reason=str(exc), result_completed=False)
    except OSError:
        summary = dict(status='BLOCKED', reason='FILE_ACCESS_OR_EXISTING_OUTPUT', result_completed=False)
    print(json.dumps(summary, sort_keys=True))
    return 2 if summary['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
