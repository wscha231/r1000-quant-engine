"""Fixed-scope primary macro capture, shared archive publication and A4 replay.

Never repairs a missing Lake execution, certifies historical PIT, admits a
training policy or touches accepted account/ledger/model state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import a4_primary_sources as source
from tools import market_analysis_engine as market
from tools.macro_history_sources import digest, encoded, exclusive

FEED_ORDER = ('sofr', 'tgcr', 'effr', 'h41', 'h8', 'prates')


def collect(output_dir, *, code_sha, fetcher=None, transport=None, existing_input_root=None):
    root = Path(output_dir)
    source.check(re.fullmatch('[a-f0-9]{40}', code_sha or '') is not None, 'PRIMARY_CODE_PIN')
    source.check(not any(p.is_symlink() for p in (root, *root.parents)) and not root.exists(), 'PRIMARY_ATTEMPT_EXISTS_OR_SYMLINK')
    root.mkdir(parents=True)
    captures, failures, funding_dates = [], [], []
    for feed in FEED_ORDER:
        try:
            raw, collected = source.capture(feed, fetcher=fetcher)
            through = min(funding_dates) if feed == 'prates' and len(funding_dates) == 3 else None
            prepared = source.store_capture(root/'archive', raw, feed, collected_at=collected, through=through)
            manifest = prepared['manifest']
            if feed in {'sofr', 'tgcr', 'effr'}:
                funding_dates.append(manifest['last_observation'])
            captures.append(prepared)
        except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
            failures.append(dict(feed=feed, blocker='PRIMARY_CAPTURE_OR_NORMALIZATION_FAILED'))
    cutoff = source.now()
    published = []
    status = 'BLOCKED_SOURCE_CAPTURE' if failures else 'LOCAL_RESEARCH_CAPTURE_COMPLETE'
    if not failures and transport is not None:
        try:
            for item in captures:
                published.append(source.publish_capture(transport, root/'archive', item['generation_sha256'], cutoff=cutoff))
            status = 'DURABLE_RESEARCH_CAPTURE_COMPLETE' if transport.remote_verified is True else 'LOCAL_TRANSPORT_CHECKED'
        except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
            failures.append(dict(feed='archive', blocker='PRIMARY_PUBLICATION_OR_READBACK_FAILED'))
            status = 'BLOCKED_DURABLE_PUBLICATION'
    session = market.current_session(cutoff)
    inputs = root/'inputs'
    entries = []
    if not failures:
        for item in captures:
            manifest = item['manifest']
            path = 'originals/'+manifest['original_sha256']
            raw = market.bounded(root/'archive/objects'/manifest['original_sha256'], source.MAX_ORIGINAL)
            exclusive(inputs/path, raw)
            entries.append(dict(kind='macro_primary', feed=manifest['feed'], path=path,
                sha256=manifest['original_sha256'], status='COLLECTED', collected_at=manifest['collected_at'],
                observation_start=manifest['requested_start'], observation_through=manifest['requested_through']))
        # Only a current, valid original request may supply native risk operands.
        # A stale or corrupt restore never becomes a partial native-risk input.
        if existing_input_root is not None:
            try:
                previous = Path(existing_input_root)
                pin = market.bounded(previous/'request.sha256', 128).decode('ascii').strip()
                raw = market.bounded(previous/'request.json', 256*1024)
                req = market.verify_request(raw, pin, cutoff, session)
                native = [s for s in req['inputs'] if s['kind'] in {'risk_metrics', 'risk_calendar', 'risk_context'}]
                operands = []
                for spec in native:
                    relative = market.safe_path(spec['path'])
                    path = previous.joinpath(*relative.parts)
                    source.check(not any(p.is_symlink() for p in (path, *path.parents)), 'PRIMARY_NATIVE_SYMLINK')
                    body = market.bounded(path, market.input_limit(spec))
                    source.check(digest(body) == spec['sha256'], 'PRIMARY_NATIVE_HASH')
                    operands.append((spec, body))
                source.check(sum(len(b) for _,b in operands)+sum(e['manifest']['original_bytes'] for e in captures)
                             <= market.MAX_TOTAL_BYTES, 'PRIMARY_TOTAL_INPUT_BUDGET')
                for spec, body in operands:
                    name = 'native/'+spec['sha256']
                    exclusive(inputs/name, body)
                    entries.append(dict(spec, path=name))
            except (ValueError, OSError, KeyError, TypeError, UnicodeError, OverflowError, RecursionError):
                # The collection succeeds independently; the native risk report
                # truthfully remains DATA_BLOCKED and does not use an old score.
                pass
        request = dict(schema=market.REQUEST_SCHEMA_V2, market='US', session=session, available_at=cutoff,
            expires_at=(datetime.fromisoformat(cutoff)+timedelta(days=1)).isoformat(), inputs=entries)
        raw = encoded(request)
        exclusive(inputs/'request.json', raw)
        exclusive(inputs/'request.sha256', digest(raw).encode('ascii'))
        report = market.load_report(inputs/'request.json', inputs, digest(raw), cutoff=cutoff)
        exclusive(root/'market_analysis.json', encoded(report))
        exclusive(root/'market_analysis.md', market.render_report(report).encode('utf-8'))
        market_status = report['status']
    else:
        market_status = 'DATA_BLOCKED'
    result = dict(schema='a4-primary-collection-execution-v1', status=status, code_sha=code_sha,
        completed_at=source.now(), cutoff=cutoff, session=session,
        generation_sha256s=[r['generation_sha256'] for r in captures],
        originals=len(captures), original_bytes=sum(r['manifest']['original_bytes'] for r in captures),
        observations=sum(r['manifest']['observations'] for r in captures),
        publication=published, failures=failures, market_status=market_status,
        model_fit_performed=False, training_blockers=['REVIEWED_TARGET_PRICE_RIGHTS_AND_HISTORICAL_PIT_INPUT_POLICY_REQUIRED'],
        historical_pit_certified=False, source_admitted=False, orders_generated=False,
        accepted_model_changed=False, accepted_portfolio_changed=False, ledger_mutated=False)
    body = encoded(result)
    exclusive(root/'execution.json', body)
    if transport is not None:
        try:
            path = source.PREFIX+'/executions/'+digest(body)+'.json'
            transport.write(path, body)
            source.check(source.read_object(transport, path, digest(body)) == body, 'PRIMARY_EXECUTION_READBACK')
        except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
            # The original attempt is immutable. A separate failed-publication
            # witness prevents a local COMPLETE receipt being called durable.
            exclusive(root/'publication_failed.json', encoded(dict(schema='a4-primary-publication-failure-v1',
                execution_sha256=digest(body), blocker='EXECUTION_RECEIPT_READBACK_FAILED')))
            raise ValueError('PRIMARY_EXECUTION_READBACK_FAILED') from None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--existing-input-root')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    try:
        transport = None
        if args.publish:
            from tools.macro_research_checkpoint import RcloneTransport
            transport = RcloneTransport(os.environ['MACRO_RESEARCH_REMOTE'])
        result = collect(args.output_dir, code_sha=os.environ.get('GITHUB_SHA'), transport=transport,
                         existing_input_root=args.existing_input_root)
        print(json.dumps({k: result[k] for k in ('status', 'originals', 'original_bytes', 'observations', 'market_status', 'training_blockers')}))
        return 2 if result['failures'] else 0
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
        print('{"status":"BLOCKED","blocker":"A4_PRIMARY_COLLECTION_INVALID"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
