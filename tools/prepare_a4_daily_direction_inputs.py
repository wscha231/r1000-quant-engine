"""Stage and materialize the existing A4 learning request from private evidence."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
import re

from tools import a4_daily_direction as direction
from tools import a4_macro_learning as learning
from tools import a4_rtdsm_sources as vintage
from tools import free_market_context as free
from tools import market_analysis_engine as market
from tools.macro_history_sources import digest, encoded, exclusive

REQUEST = 'a4-daily-direction-source-request-v1'
CLOCK = 'a4-daily-direction-price-clock-export-v1'
PURPOSE = 'MACRO_RELATIONSHIP_RESEARCH'
MAX_OBJECT = 32*1024**2
MAX_ARTIFACT_BYTES = 64*1024**2
MAX_ARTIFACTS = 128
SHA = re.compile('[a-f0-9]{64}')


def require(condition, code):
    market.need(condition, 'A4_LEARNING_PACKET_'+code)


def private_path(root, name):
    path = Path(root).joinpath(*market.safe_path(name).parts)
    require(path.resolve().is_relative_to(Path(root).resolve()) and
            not any(p.is_symlink() for p in (path, *path.parents)), 'PATH')
    return path


def ref(path, sha):
    return {'path': path, 'sha256': sha}


def checked_bytes(root, reference, limit):
    require(type(reference) is dict and set(reference) == {'path', 'sha256'} and
            isinstance(reference['sha256'], str) and SHA.fullmatch(reference['sha256']), 'REFERENCE')
    raw = market.bounded(private_path(root, reference['path']), limit)
    require(bool(raw) and digest(raw) == reference['sha256'], 'ARTIFACT_HASH')
    return raw


class Evidence:
    """Resolve exact references in an already-restored private input tree."""

    def __init__(self, root, references):
        require(type(references) is dict and len(references) <= MAX_ARTIFACTS, 'INVENTORY')
        self.root = root
        self.references = {}
        self.cache = {}
        self.remaining = MAX_ARTIFACT_BYTES
        for sha, reference in references.items():
            self.register(sha, reference)

    def register(self, sha, reference):
        require(isinstance(sha, str) and SHA.fullmatch(sha) and type(reference) is dict and
                reference.get('sha256') == sha, 'REFERENCE')
        if sha not in self.references:
            require(len(self.references) < MAX_ARTIFACTS, 'INVENTORY')
            self.references[sha] = reference

    def read(self, sha, limit=MAX_OBJECT):
        require(isinstance(sha, str) and sha in self.references, 'MISSING_ARTIFACT')
        if sha not in self.cache:
            self.cache[sha] = checked_bytes(self.root, self.references[sha], min(self.remaining, limit))
            self.remaining -= len(self.cache[sha])
        raw = self.cache[sha]
        require(len(raw) <= limit, 'ARTIFACT_SIZE')
        return raw


def session_grid(start, end):
    first, last = free.iso_date(start), free.iso_date(end)
    require(first <= last and (last-first).days <= 15000, 'CALENDAR_RANGE')
    schedule = learning.mcal.get_calendar('NYSE').schedule(start_date=first, end_date=last)
    dates = [d.date().isoformat() for d in schedule.index]
    require(bool(dates) and dates[0] == start and dates[-1] == end, 'CALENDAR_BOUNDARIES')
    return [dict(session=day, close_utc=stamp.isoformat()) for day, stamp in zip(dates, schedule.market_close)]


def price_bindings(prices, supplied, evidence, sessions, cutoff):
    require(type(prices) is dict and set(prices) == set(direction.TARGETS), 'BENCHMARK_PAIR')
    grouped = defaultdict(dict)
    close_by_session = {row['session']: free.utc(row['close_utc']) for row in sessions}
    for target, rows in prices.items():
        require(type(rows) is list and bool(rows) and all(
            type(row) is dict and {'session','value','original_sha256','return_basis','available_at'} <= set(row)
            and set(row) <= {'session','value','original_sha256','return_basis','available_at','collected_at'}
            and type(row['original_sha256']) is str for row in rows), 'PRICE_ROW_SCHEMA')
        learning.price_series(rows, sessions, cutoff)
        for row in rows:
            grouped[row['original_sha256']].setdefault(target, []).append(row)
    require(type(supplied) is dict and set(supplied) == set(grouped), 'PRICE_BINDING_SCOPE')
    bindings = {}
    for sha, targets in grouped.items():
        entry = supplied[sha]
        fields = {'historical_use', 'price_series_id', 'rights_evidence_sha256', 'source_receipt_sha256',
                  'price_publication_clock_evidence_sha256'}
        require(type(entry) is dict and set(entry) == fields and
                entry['historical_use'] in {'DATE_ARCHIVE_RESEARCH_ONLY', 'FORWARD_CAPTURE_ONLY'}, 'PRICE_BINDING')
        if entry['historical_use'] == 'FORWARD_CAPTURE_ONLY':
            require(all('collected_at' in row and close_by_session[row['session']] <= free.utc(row['collected_at'])
                        <= free.utc(row['available_at']) for rows in targets.values() for row in rows),
                    'FORWARD_CAPTURE_CLOCK')
        clock_hash = entry['price_publication_clock_evidence_sha256']
        clock = market.clock.decode(evidence.read(clock_hash, 1024**2))
        require(type(clock) is dict and set(clock) == {'schema','original_sha256','price_rows_sha256','time_source_sha256'} and
                clock['schema'] == CLOCK and clock['original_sha256'] == sha and
                clock['price_rows_sha256'] == digest(encoded(targets)), 'PRICE_CLOCK_SCOPE')
        # The time-source file remains available for independent comparison
        # with every claimed price and availability time in the pinned export.
        evidence.read(clock['time_source_sha256'])
        evidence.read(entry['rights_evidence_sha256'])
        evidence.read(entry['source_receipt_sha256'])
        bindings[sha] = dict(entry, purpose=PURPOSE, source_ids=['price:'+target for target in sorted(targets)],
                             size_bytes=len(evidence.read(sha)))
    return bindings


def dated_observations(spec, evidence, cutoff):
    prefix = spec['root']
    market.safe_path(prefix)
    generations = spec['generations']
    require(type(generations) is dict and set(generations) == set(vintage.FEEDS), 'VINTAGE_GENERATIONS')

    class ArchiveReader:
        def read(self, path):
            subpath = path.removeprefix(vintage.p.PREFIX+'/')
            require(subpath != path, 'VINTAGE_PATH')
            sha = Path(subpath).name.removesuffix('.json')
            evidence.register(sha, ref(prefix+'/'+subpath, sha))
            return evidence.read(sha, vintage.MAX_RAW)

    observations, bindings, notices = [], {}, set()
    for feed, item in sorted(generations.items()):
        generation, rights = item['generation_sha256'], item['rights_evidence_sha256']
        evidence.read(rights)
        rows, manifest = vintage.read_generation(ArchiveReader(), generation, cutoff=cutoff)
        require(manifest['feed'] == feed and bool(rows), 'VINTAGE_FEED')
        original = manifest['original_sha256']
        require(original not in bindings, 'VINTAGE_ORIGINAL')
        notices.add(manifest['rights_notice_sha256'])
        bindings[original] = dict(purpose=PURPOSE, source_ids=[rows[0]['source_id']],
            historical_use='DATE_ARCHIVE_RESEARCH_ONLY', size_bytes=manifest['original_bytes'],
            rights_evidence_sha256=rights, source_receipt_sha256=generation, vintage_manifest_sha256=generation)
        observations.extend(rows)
    return observations, bindings, notices


def candidate_paths(pin):
    require(isinstance(pin, str) and SHA.fullmatch(pin), 'EXTERNAL_POLICY_PIN')
    base = 'a4_learning_candidates/'+pin+'/'
    return {name: base+name+'.json' for name in ('policy', 'inputs', 'review')}


def stage(root, request_path):
    raw = market.bounded(private_path(root, request_path), 256*1024)
    spec = market.clock.decode(raw)
    require(type(spec) is dict and spec.get('schema') == REQUEST, 'SOURCE_REQUEST')
    cutoff = spec['cutoff']
    sessions = session_grid(spec['calendar_origin_session'], spec['through_session'])
    evidence = Evidence(root, spec['objects'])
    prices = market.clock.decode(checked_bytes(root, spec['prices'], 16*1024**2))
    bindings = price_bindings(prices, spec['price_sources'], evidence, sessions, cutoff)
    observations, dated_bindings, notices = dated_observations(spec['vintage'], evidence, cutoff)
    require(not set(bindings) & set(dated_bindings), 'SOURCE_ORIGINAL_COLLISION')
    bindings.update(dated_bindings)
    # Stage only referenced evidence. Extra unconsumed entries cannot leak
    # into a candidate and cannot be used to change the size limits at seal.
    artifacts = {sha: evidence.references[sha] for sha in sorted(evidence.cache)}
    payload = dict(schema='a4-macro-learning-inputs-v1', cutoff=cutoff, sessions=sessions,
                   observations=observations, prices=prices)
    window = spec['policy_window']
    policy = dict(schema='a4-learning-input-policy-v1', purpose=PURPOSE, input_pins=[digest(encoded(payload))],
        available_at=window['available_at'], expires_at=window['expires_at'], source_bindings=bindings,
        reviewed_rights_pins=sorted(notices | {row['rights_evidence_sha256'] for row in bindings.values()}),
        reviewed_source_receipt_pins=sorted({row['source_receipt_sha256'] for row in bindings.values()} |
                                          {row['price_publication_clock_evidence_sha256'] for sha, row in bindings.items()
                                           if sha not in dated_bindings}),
        trial_identity=spec['trial_identity'], daily_direction_calendar_origin_session=sessions[0]['session'],
        daily_direction_protocol_sha256=digest(encoded(direction.specification())),
        preparation_evidence=dict(source_request_sha256=digest(raw), price_export_sha256=spec['prices']['sha256'],
                                  original_artifacts=artifacts))
    policy_raw, payload_raw = encoded(policy), encoded(payload)
    require(len(policy_raw) <= 1024**2 and len(payload_raw) <= MAX_ARTIFACT_BYTES, 'CONSUMER_SIZE_BUDGET')
    policy_pin = digest(policy_raw)
    paths = candidate_paths(policy_pin)
    direction.prepare(payload, policy, policy_pin, evidence.read)
    anchors = {row['session']: free.utc(row['close_utc'])+timedelta(minutes=60) for row in sessions}
    coverage, timely_sets = {}, []
    for target, rows in prices.items():
        usable = [row for row in rows if row['value'] is not None]
        timely = {row['session'] for row in usable if free.utc(row['available_at']) <= anchors[row['session']]}
        timely_sets.append(timely)
        coverage[target] = dict(rows=len(rows), usable_closes=len(usable), missing_closes=len(sessions)-len(usable),
            late_closes=len(usable)-len(timely), last_close=max((row['session'] for row in usable), default=None))
    common = set.intersection(*timely_sets)
    report = dict(status='INDEPENDENT_POLICY_REVIEW_REQUIRED', candidate_policy_sha256=policy_pin,
                  policy_path=paths['policy'], inputs_path=paths['inputs'], session_count=len(sessions),
                  price_coverage=coverage, common_on_time_closes=len(common), last_common_on_time_close=max(common, default=None),
                  horizons_sessions=list(direction.HORIZONS), training_executed=False)
    exclusive(private_path(root, paths['inputs']), payload_raw)
    exclusive(private_path(root, paths['policy']), policy_raw)
    exclusive(private_path(root, paths['review']), encoded(report))
    return report


def seal(root, reviewed_policy_pin):
    """Publish only the launch descriptor for an independently pinned policy."""
    paths = candidate_paths(reviewed_policy_pin)
    policy_ref = ref(paths['policy'], reviewed_policy_pin)
    policy = market.clock.decode(checked_bytes(root, policy_ref, 1024**2))
    require(len(policy['input_pins']) == 1, 'INPUT_PIN')
    payload_ref = ref(paths['inputs'], policy['input_pins'][0])
    payload = market.clock.decode(checked_bytes(root, payload_ref, MAX_ARTIFACT_BYTES))
    artifacts = policy['preparation_evidence']['original_artifacts']
    evidence = Evidence(root, artifacts)
    for sha in artifacts:
        evidence.read(sha)
    direction.prepare(payload, policy, reviewed_policy_pin, evidence.read)
    request = dict(schema='a4-learning-request-v1', policy=policy_ref, inputs=payload_ref, originals=artifacts)
    raw = encoded(request)
    require(len(raw) <= 256*1024, 'CONSUMER_SIZE_BUDGET')
    exclusive(private_path(root, 'learning_request.json'), raw)
    return dict(status='REQUEST_READY_FOR_A4_READER', policy_sha256=reviewed_policy_pin,
                request_sha256=digest(raw), training_executed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    action = parser.add_subparsers(dest='action', required=True)
    draft = action.add_parser('stage', help='Create a private candidate for independent review')
    draft.add_argument('--source-request', default='daily_direction_source_request.json')
    release = action.add_parser('seal', help='Materialize the descriptor using a separately reviewed policy SHA256')
    release.add_argument('--reviewed-policy-sha256', required=True)
    args = parser.parse_args()
    result = (stage(args.root, args.source_request) if args.action == 'stage'
              else seal(args.root, args.reviewed_policy_sha256))
    print(encoded(result).decode(), end='')


if __name__ == '__main__':
    main()
