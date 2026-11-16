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
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import a4_primary_sources as source
from tools import market_analysis_engine as market
from tools.macro_history_sources import digest, encoded, exclusive

FEED_ORDER = ('sofr', 'tgcr', 'effr', 'h41', 'h8', 'prates')
NATIVE_KINDS = frozenset({'risk_metrics', 'risk_calendar', 'risk_context'})
CREDIT_SOURCES = frozenset({'fred:BAMLH0A0HYM2', 'fred:BAMLC0A0CM'})


def credit_source_input(spec):
    return spec['kind'] in {'macro', 'macro_v2'} and spec.get('source_id') in CREDIT_SOURCES


def retained_source_input(spec):
    """Keep native operands and supplied credit originals, never derived proxies.

    The primary feeds do not contain these two credit series. Preserve their
    existing source/hash/clock specification; this filter grants no data rights.
    """
    return spec['kind'] in NATIVE_KINDS or credit_source_input(spec)


def publish_analysis(transport, request_raw, report_raw, *, cutoff):
    """Archive a pinned research/blocked analysis, never an accepted model."""
    source.check(type(report_raw) is bytes and 0<len(report_raw)<=market.MAX_FILE_BYTES, 'PRIMARY_REPORT_SIZE')
    report=market.clock.decode(report_raw)
    request=market.verify_request(request_raw, digest(request_raw), cutoff, market.current_session(cutoff))
    source.check(report.get('schema')=='market-analysis-report-v2' and report.get('request_sha256')==digest(request_raw)
                 and report.get('session')==request['session'] and report.get('cutoff')==cutoff,
                 'PRIMARY_REPORT_REQUEST_BINDING')
    source.check(all(report.get(k) is False for k in ('source_and_pit_admission','source_admission_allowed',
                 'target_book_write_allowed','ledger_mutation_allowed','order_generation_allowed')),
                 'PRIMARY_REPORT_AUTHORITY')
    checked=dict(report); content=checked.pop('content_sha256',None)
    source.check(content==market.context.digest(checked), 'PRIMARY_REPORT_CONTENT_HASH')
    references=[]
    for kind, body in (('request',request_raw),('report',report_raw)):
        path=source.PREFIX+'/reports/'+digest(body)+'.json'
        transport.write(path,body)
        source.check(source.read_object(transport,path,digest(body),market.MAX_FILE_BYTES)==body,'PRIMARY_ANALYSIS_READBACK')
        references.append(dict(kind=kind,path=path,sha256=digest(body),bytes=len(body)))
    return references


def collect(output_dir, *, code_sha, fetcher=None, transport=None, existing_input_root=None, include_economic=False,
            include_financing=False):
    root = Path(output_dir)
    source.check(re.fullmatch('[a-f0-9]{40}', code_sha or '') is not None, 'PRIMARY_CODE_PIN')
    source.check(not any(p.is_symlink() for p in (root, *root.parents)) and not root.exists(), 'PRIMARY_ATTEMPT_EXISTS_OR_SYMLINK')
    root.mkdir(parents=True)
    captures, failures, funding_dates = [], [], []
    from tools import a4_primary_macro_sources as economic
    from tools import a4_financing_sources as financing
    def adapter_for(feed):
        return financing if feed in financing.FEEDS else economic if feed in economic.FEEDS else source
    order=FEED_ORDER+(economic.FEEDS if include_economic else ())+(financing.FEEDS if include_financing else ())
    for feed in order:
        adapter=adapter_for(feed)
        try:
            parameters=dict(request_year=source.clock(source.now()).year) if feed.startswith('ust_') else {}
            if feed=='sloos_domestic':
                periods=[r['manifest']['resolved_period'] for r in captures if r['manifest']['feed']=='sloos_index']
                source.check(len(periods)==1,'SLOOS_INDEX_NOT_CAPTURED')
                parameters['period']=periods[0]
            raw, collected = adapter.capture(feed, fetcher=fetcher,**parameters)
            through = min(funding_dates) if feed == 'prates' and len(funding_dates) == 3 else None
            prepared = adapter.store_capture(root/'archive', raw, feed, collected_at=collected, through=through,**parameters)
            manifest = prepared['manifest']
            if feed in {'sofr', 'tgcr', 'effr'}:
                funding_dates.append(manifest['last_observation'])
            captures.append(prepared)
        except HTTPError as exc:
            failures.append(dict(feed=feed, blocker='PRIMARY_HTTP_STATUS', http_status=exc.code))
        except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
            failures.append(dict(feed=feed, blocker='PRIMARY_CAPTURE_OR_NORMALIZATION_FAILED'))
    cutoff = source.now()
    published = []
    core_failed=any(r['feed'] in FEED_ORDER for r in failures)
    status = 'BLOCKED_SOURCE_CAPTURE' if core_failed else 'PARTIAL_RESEARCH_CAPTURE' if failures else 'LOCAL_RESEARCH_CAPTURE_COMPLETE'
    if not core_failed and transport is not None:
        try:
            for item in captures:
                adapter=adapter_for(item['manifest']['feed'])
                published.append(adapter.publish_capture(transport, root/'archive', item['generation_sha256'], cutoff=cutoff))
            status = ('DURABLE_PARTIAL_RESEARCH_CAPTURE' if transport.remote_verified is True else 'LOCAL_PARTIAL_RESEARCH_CAPTURE') if failures else (
                'DURABLE_RESEARCH_CAPTURE_COMPLETE' if transport.remote_verified is True else 'LOCAL_TRANSPORT_CHECKED')
        except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
            failures.append(dict(feed='archive', blocker='PRIMARY_PUBLICATION_OR_READBACK_FAILED'))
            status = 'BLOCKED_DURABLE_PUBLICATION'
    session = market.current_session(cutoff)
    inputs = root/'inputs'
    entries, analysis_publication = [], []
    if not core_failed and not any(r['feed']=='archive' for r in failures):
        for item in captures:
            manifest = item['manifest']
            path = 'originals/'+manifest['original_sha256']
            raw = market.bounded(root/'archive/objects'/manifest['original_sha256'], source.MAX_ORIGINAL)
            exclusive(inputs/path, raw)
            is_financing=manifest['feed'] in financing.FEEDS
            entries.append(dict(kind='financing_primary' if is_financing else 'macro_primary', feed=manifest['feed'], path=path,
                sha256=manifest['original_sha256'], status='COLLECTED', collected_at=manifest['collected_at'],
                observation_start=manifest.get('requested_start',manifest['first_observation']), observation_through=manifest['requested_through']))
            if is_financing:entries[-1]['source_period']=manifest['period']
            if manifest['feed'] in economic.FEEDS:
                entries[-1]['source_request_year']=manifest['request_year']
        # Only a current, valid original request may supply native risk operands
        # and the credit originals absent from the primary feeds. A stale or
        # corrupt restore never becomes a partial retained-source input.
        if existing_input_root is not None:
            try:
                previous = Path(existing_input_root)
                pin = market.bounded(previous/'request.sha256', 128).decode('ascii').strip()
                raw = market.bounded(previous/'request.json', 256*1024)
                req = market.verify_request(raw, pin, cutoff, session)
                native = [s for s in req['inputs'] if retained_source_input(s)]
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
        if transport is not None:
            try:
                analysis_publication=publish_analysis(transport,raw,encoded(report),cutoff=cutoff)
            except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
                failures.append(dict(feed='analysis',blocker='PRIMARY_ANALYSIS_PUBLICATION_FAILED'))
                status='BLOCKED_DURABLE_PUBLICATION'
    else:
        market_status = 'DATA_BLOCKED'
    result = dict(schema='a4-primary-collection-execution-v1', status=status, code_sha=code_sha,
        completed_at=source.now(), cutoff=cutoff, session=session,
        generation_sha256s=[r['generation_sha256'] for r in captures],
        requested_feeds=list(order),economic_inputs_enabled=include_economic,financing_inputs_enabled=include_financing,
        provider_request_upper_bound=len(order),provider_retries=0,
        originals=len(captures), original_bytes=sum(r['manifest']['original_bytes'] for r in captures),
        observations=sum(r['manifest']['observations'] for r in captures),
        publication=published, analysis_publication=analysis_publication, failures=failures, market_status=market_status,
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



def collect_rtdsm_extension(output_dir, *, code_sha, recipe_raw, expected_recipe_sha256,
                            material_root, fetcher=None, transport=None,
                            reuse_archive_root=None):
    """Explicit closed research component; never starts native analysis/learning.

    The caller separately supplies the current Source-owner execution packet.
    A matching recipe hash is integrity evidence, not permission or admission.
    """
    import time
    from tools import a4_rtdsm_extension as extension
    source.check(type(recipe_raw) is bytes and 0 < len(recipe_raw) <= 65536 and
                 re.fullmatch('[a-f0-9]{64}', expected_recipe_sha256 or '') and
                 digest(recipe_raw) == expected_recipe_sha256, 'RTDSM_EXTENSION_RECIPE_PIN')
    recipe = source.f.strict_json(recipe_raw)
    keys = {'schema','feeds','start','through','rights_notice_sha256','normalizer_sha256',
            'legacy_codec_sha256','shared_codec_sha256','collector_sha256','reuse_generations'}
    source.check(type(recipe) is dict and set(recipe) == keys and
                 recipe['schema'] == 'a4-rtdsm-extension-capture-recipe-v1' and
                 recipe['feeds'] == list(extension.FEEDS), 'RTDSM_EXTENSION_CLOSED_RECIPE')
    source.check(re.fullmatch('[a-f0-9]{40}', code_sha or '') is not None, 'PRIMARY_CODE_PIN')
    source.check(recipe['normalizer_sha256'] == extension.LOADED_NORMALIZER_SHA256 and
                 recipe['legacy_codec_sha256'] == extension.LOADED_LEGACY_CODEC_SHA256 and
                 recipe['shared_codec_sha256'] == extension.LOADED_SHARED_CODEC_SHA256 and
                 recipe['collector_sha256'] == digest(Path(__file__).read_bytes().replace(b'\r\n',b'\n')),
                 'RTDSM_EXTENSION_RECIPE_CODE')
    start, through = source.day(recipe['start']), source.day(recipe['through'])
    source.check(source.day('1998-11-01') <= start <= through <= source.clock(source.now()).date() and
                 start.day == through.day == 1, 'RTDSM_EXTENSION_WINDOW')
    source.check(type(recipe['reuse_generations']) is dict and
                 set(recipe['reuse_generations']) <= set(extension.FEEDS), 'RTDSM_EXTENSION_REUSE_SCOPE')
    def exact_pin(pin):
        source.check(type(pin) is str and re.fullmatch('[a-f0-9]{64}', pin), 'RTDSM_EXTENSION_OBJECT_PIN')
        return pin
    materials = Path(material_root)
    source.check(materials.is_dir() and not any(x.is_symlink() for x in (materials,*materials.parents)), 'RTDSM_EXTENSION_MATERIAL_ROOT')
    pins = [exact_pin(recipe['rights_notice_sha256'])] + [s[4] for s in extension.FEEDS.values()]
    objects = {}
    for pin in pins:
        path = materials/'objects'/pin
        source.check(not any(x.is_symlink() for x in (path,*path.parents)), 'RTDSM_EXTENSION_MATERIAL_SYMLINK')
        raw = source._bounded(path, 256*1024 if pin == pins[0] else 1024*1024)
        source.check(digest(raw) == pin, 'RTDSM_EXTENSION_MATERIAL_HASH')
        objects[pin] = raw
    source.check(sum(map(len,objects.values())) <= 2*1024*1024, 'RTDSM_EXTENSION_MATERIAL_TOTAL')
    reused = {}
    if recipe['reuse_generations']:
        source.check(reuse_archive_root is not None, 'RTDSM_EXTENSION_REUSE_ROOT')
        root = Path(reuse_archive_root)
        source.check(root.is_dir() and not any(x.is_symlink() for x in (root,*root.parents)), 'RTDSM_EXTENSION_REUSE_SYMLINK')
        for feed,pin in recipe['reuse_generations'].items():
            pin = exact_pin(pin)
            _,meta = extension.read_generation(extension.PreparedReader(root),pin,cutoff=source.now())
            source.check(meta['feed'] == feed and meta['requested_start'] == recipe['start'] and
                         meta['requested_through'] == recipe['through'] and meta['capture_ref'] is not None and
                         meta['rights_notice_sha256'] == recipe['rights_notice_sha256'], 'RTDSM_EXTENSION_REUSE_BINDING')
            reused[feed] = (root,pin,meta)
    root = Path(output_dir)
    source.check(not root.exists() and not any(x.is_symlink() for x in (root,*root.parents)), 'PRIMARY_ATTEMPT_EXISTS_OR_SYMLINK')
    root.mkdir(parents=True)
    exclusive(root/'archive/objects'/expected_recipe_sha256,recipe_raw)
    captures,failures,published = [],[],[]
    requested = list(extension.FEEDS)
    started = time.monotonic()
    provider_calls = provider_bytes = 0
    deadline = started + 180
    status = 'BLOCKED_EXTENSION_CAPTURE'
    for feed in requested:
        if failures:
            break
        try:
            source.check(time.monotonic() < deadline, 'RTDSM_EXTENSION_CAPTURE_TIME_BUDGET')
            if feed in reused:
                old,pin,meta = reused[feed]
                bodies = [meta[k] for k in ('original_sha256','documentation_sha256','rights_notice_sha256','normalized_object_sha256')]
                for name in ['objects/'+x for x in dict.fromkeys(bodies)]+['generations/'+pin+'.json']:
                    body = source._bounded(old/name,extension.MAX_RAW)
                    if not (root/'archive'/name).exists():exclusive(root/'archive'/name,body)
                _,meta = extension.read_generation(extension.PreparedReader(root/'archive'),pin,cutoff=source.now())
                captures.append(dict(generation_sha256=pin,manifest=meta,reused=True))
                continue
            request_started = source.now()
            uri = extension.source_uri(feed)
            provider_calls += 1
            if fetcher is not None:
                raw = fetcher(uri,extension.MAX_RAW)
            else:
                chunks=[];count=0
                with source.build_opener(source.NoRedirect()).open(source.Request(uri,headers={
                    'User-Agent':'r1000-primary-macro-research/1.0',
                    'Accept':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}),timeout=30) as response:
                    source.check(response.status == 200 and response.geturl() == uri, 'RTDSM_EXTENSION_HTTP_IDENTITY')
                    while True:
                        source.check(time.monotonic() < deadline, 'RTDSM_EXTENSION_CAPTURE_TIME_BUDGET')
                        chunk=response.read1(min(65536,extension.MAX_RAW+1-count))
                        if not chunk:break
                        chunks.append(chunk);count+=len(chunk)
                        source.check(count<=extension.MAX_RAW,'RTDSM_EXTENSION_ORIGINAL_BUDGET')
                raw=b''.join(chunks)
            completed = source.now()
            source.check(type(raw) is bytes and 0<len(raw)<=extension.MAX_RAW, 'RTDSM_EXTENSION_ORIGINAL_BUDGET')
            provider_bytes += len(raw)
            clock=dict(source_uri=uri,original_sha256=digest(raw),original_bytes=len(raw),
                       request_started_at=request_started,body_completed_at=completed,http_status=200)
            # Retain each returned original before normalization, including a
            # refused workbook, so a failed attempt does not erase its evidence.
            exclusive(root/'returned_originals'/digest(raw),raw)
            exclusive(root/'capture_receipts'/(feed+'.json'),encoded(clock))
            source.check(provider_bytes<=3*extension.MAX_RAW and time.monotonic()<deadline,'RTDSM_EXTENSION_CAPTURE_TIME_OR_TOTAL')
            prepared=extension.store_capture(root/'archive',raw,feed,collected_at=completed,
                start=recipe['start'],through=recipe['through'],capture_ref=clock,
                documentation_raw=objects[extension.FEEDS[feed][4]],rights_raw=objects[pins[0]])
            prepared['reused']=False;captures.append(prepared)
        except HTTPError as exc:
            failures.append(dict(feed=feed,blocker='RTDSM_EXTENSION_HTTP_STATUS',http_status=exc.code))
            exc.close()
        except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
            failures.append(dict(feed=feed,blocker='RTDSM_EXTENSION_CAPTURE_OR_NORMALIZATION_FAILED'))
    cutoff=source.now()
    if not failures:
        status='LOCAL_EXTENSION_RESEARCH_CAPTURE_COMPLETE'
        if transport is not None:
            try:
                recipe_path=source.PREFIX+'/objects/'+expected_recipe_sha256
                transport.write(recipe_path,recipe_raw)
                source.check(source.read_object(transport,recipe_path,expected_recipe_sha256,65536)==recipe_raw,'RTDSM_EXTENSION_RECIPE_READBACK')
                for item in captures:
                    published.append(extension.publish_capture(transport,root/'archive',item['generation_sha256'],cutoff=cutoff))
                status='DURABLE_EXTENSION_RESEARCH_CAPTURE_COMPLETE' if transport.remote_verified is True else 'LOCAL_EXTENSION_TRANSPORT_CHECKED'
            except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
                failures.append(dict(feed='archive',blocker='RTDSM_EXTENSION_PUBLICATION_OR_REPLAY_FAILED'))
                status='BLOCKED_EXTENSION_DURABLE_PUBLICATION'
    result=dict(schema='a4-rtdsm-extension-execution-v1',status=status,code_sha=code_sha,
        recipe_sha256=expected_recipe_sha256,requested_feeds=requested,
        generation_sha256s=[x['generation_sha256'] for x in captures],
        captures=[dict(feed=x['manifest']['feed'],generation_sha256=x['generation_sha256'],reused=x['reused']) for x in captures],
        failures=failures,not_run_feeds=requested[len(captures)+int(bool(failures)):],
        cutoff=cutoff,completed_at=source.now(),provider_requests=provider_calls,provider_retries=0,
        provider_bytes=provider_bytes,actual_seconds=time.monotonic()-started,
        publication=published,model_fit_performed=False,a3_executed=False,a5_executed=False,
        accepted_model_changed=False,accepted_portfolio_changed=False,ledger_mutated=False,**extension.SAFETY)
    body=encoded(result);exclusive(root/'execution.json',body)
    exclusive(root/'archive/executions'/(digest(body)+'.json'),body)
    if transport is not None:
        try:
            path=source.PREFIX+'/executions/'+digest(body)+'.json';transport.write(path,body)
            source.check(source.read_object(transport,path,digest(body),128*1024)==body,'RTDSM_EXTENSION_EXECUTION_READBACK')
        except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
            exclusive(root/'publication_failed.json',encoded(dict(execution_sha256=digest(body),blocker='RTDSM_EXTENSION_EXECUTION_READBACK_FAILED')))
            raise ValueError('RTDSM_EXTENSION_EXECUTION_READBACK_FAILED') from None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--existing-input-root')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--include-economic-inputs', action='store_true')
    parser.add_argument('--include-financing-inputs', action='store_true')
    parser.add_argument('--rtdsm-extension-only', action='store_true')
    parser.add_argument('--extension-recipe')
    parser.add_argument('--extension-recipe-sha256')
    parser.add_argument('--extension-material-root')
    parser.add_argument('--extension-reuse-archive-root')
    args = parser.parse_args()
    try:
        transport = None
        if args.rtdsm_extension_only:
            source.check(not args.include_economic_inputs and not args.include_financing_inputs and args.existing_input_root is None and all((args.extension_recipe,args.extension_recipe_sha256,args.extension_material_root)), 'RTDSM_EXTENSION_ISOLATED_MODE')
        if args.publish:
            from tools.macro_research_checkpoint import RcloneTransport
            if args.rtdsm_extension_only:
                class ExistingResearchOnly(RcloneTransport):
                    def call(self,*items):
                        source.check(items and str(items[0]) in {'lsjson','cat','copyto'},'RTDSM_EXTENSION_EXISTING_REMOTE_ONLY')
                        return super().call(*items)
                transport=ExistingResearchOnly(os.environ['MACRO_RESEARCH_REMOTE'])
            else:
                transport = RcloneTransport(os.environ['MACRO_RESEARCH_REMOTE'])
        if args.rtdsm_extension_only:
            source.check(not args.include_economic_inputs and not args.include_financing_inputs and args.existing_input_root is None, 'RTDSM_EXTENSION_ISOLATED_MODE')
            result=collect_rtdsm_extension(args.output_dir,code_sha=os.environ.get('GITHUB_SHA'),
                recipe_raw=source._bounded(Path(args.extension_recipe),65536),expected_recipe_sha256=args.extension_recipe_sha256,
                material_root=args.extension_material_root,reuse_archive_root=args.extension_reuse_archive_root,transport=transport)
            print(json.dumps({k:result[k] for k in ('status','provider_requests','provider_bytes','failures')}))
            return 2 if result['failures'] else 0
        source.check(not any((args.extension_recipe,args.extension_recipe_sha256,args.extension_material_root,args.extension_reuse_archive_root)), 'RTDSM_EXTENSION_MODE_REQUIRED')
        result = collect(args.output_dir, code_sha=os.environ.get('GITHUB_SHA'), transport=transport,
                         existing_input_root=args.existing_input_root,include_economic=args.include_economic_inputs,
                         include_financing=args.include_financing_inputs)
        print(json.dumps({k: result[k] for k in ('status', 'originals', 'original_bytes', 'observations', 'market_status', 'training_blockers')}))
        return 2 if result['failures'] else 0
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
        print('{"status":"BLOCKED","blocker":"A4_PRIMARY_COLLECTION_INVALID"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
