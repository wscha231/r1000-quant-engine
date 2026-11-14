"""Package an explicitly pinned native Source result for the existing A4 reader.

Offline format handoff only. The Source owner must qualify the originals and
their research-use rights before publication. Hash replay here neither reviews
supplier rights nor certifies Source/PIT, training, or an accepted risk policy.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import build_run287_chameleon_macro_inputs as producer
from tools import market_analysis_engine as market
from tools import collect_a4_primary_data as collector, a4_liquidity_analysis as liquidity
from tools.macro_history_sources import digest, encoded, exclusive

FILES = {
    "calendar": ("xnys_calendar.csv", "risk_calendar", market.MAX_FILE_BYTES),
    "metrics": ("input_metrics.csv", "risk_metrics", market.MAX_NATIVE_METRIC_BYTES),
    "context": ("input_context.csv", "risk_context", market.MAX_FILE_BYTES),
    "source_audit": ("source_audit.csv", None, market.MAX_FILE_BYTES),
    "source_lineage": ("source_lineage.json", None, market.MAX_FILE_BYTES),
}
SAFETY = dict(source_admission_allowed=False, historical_pit_certified=False,
    supplier_rights_certified=False, training_allowed=False, backtest_executed=False,
    fullrun_executed=False, accepted_state_changed=False, a3_a5_executed=False,
    ledger_mutated=False, orders_generated=False, provider_requests=0)


def read_local(root, name, limit):
    path = root/name
    market.need(not any(p.is_symlink() for p in (path, *path.parents)), "NATIVE_HANDOFF_SYMLINK")
    return market.bounded(path, limit)


def implementation_identity():
    identity = market.implementation_identity()
    identity[Path(__file__).name] = digest(Path(__file__).read_bytes())
    identity[Path(collector.__file__).name] = digest(Path(collector.__file__).read_bytes().replace(b'\r\n',b'\n'))
    return identity


def prepare(source_root, expected_manifest_sha256, *, cutoff, output_dir,
            current_credit_input_root=None, current_credit_request_sha256=None):
    """Revalidate native readiness and optional pinned current credit originals."""
    identity = implementation_identity()
    market.need((current_credit_input_root is None) == (current_credit_request_sha256 is None),
        'NATIVE_HANDOFF_CREDIT_ARGUMENT_PAIR')
    root, dest = Path(source_root).resolve(), Path(output_dir).resolve()
    market.need(not (dest.is_relative_to(root) or root.is_relative_to(dest)), "NATIVE_HANDOFF_PATH_OVERLAP")
    market.need(not any(p.is_symlink() for p in (Path(source_root), *Path(source_root).parents,
        Path(output_dir), *Path(output_dir).parents)), "NATIVE_HANDOFF_SYMLINK")
    market.need(type(expected_manifest_sha256) is str and
        re.fullmatch("[a-f0-9]{64}", expected_manifest_sha256), "NATIVE_HANDOFF_MANIFEST_PIN")
    raw = read_local(root, "manifest.json", 256*1024)
    market.need(digest(raw) == expected_manifest_sha256, "NATIVE_HANDOFF_MANIFEST_HASH")
    manifest = market.free.strict_json(raw)
    market.need(type(manifest) is dict and type(manifest.get("outputs")) is dict, "NATIVE_HANDOFF_MANIFEST_SCHEMA")
    market.need(manifest.get("schema_version") == producer.SCHEMA_VERSION and
        manifest.get("status") == producer.READY_STATUS, "NATIVE_HANDOFF_PRODUCER_NOT_READY")
    producer.load_contract(producer.DEFAULT_CONTRACT)
    market.need(manifest.get("contract_semantic_sha256") == producer.CANONICAL_CONTRACT_SEMANTIC_SHA256 and
        manifest.get("builder_sha256") == digest(Path(producer.__file__).read_bytes()), "NATIVE_HANDOFF_PRODUCER_IDENTITY")
    market.need(type(manifest.get("git_head")) is str and re.fullmatch("[a-f0-9]{40}", manifest["git_head"]),
        "NATIVE_HANDOFF_PRODUCER_CODE_PIN")
    market.need(manifest.get("truth_class") == "FREE_PROXY" and manifest.get("historical_ab_allowed") is False,
        "NATIVE_HANDOFF_TRUTH_SCOPE")
    market.need(all(manifest.get(k) is v for k, v in producer.SAFETY.items()), "NATIVE_HANDOFF_UNSAFE_PRODUCER")
    session = market.current_session(cutoff)
    market.need(manifest.get("requested_as_of") == manifest.get("resolved_as_of") == session,
        "NATIVE_HANDOFF_SESSION_NOT_CURRENT")
    bodies, pins = {"manifest.json": raw}, {}
    for key, (name, kind, limit) in FILES.items():
        spec = manifest.get("outputs", {}).get(key)
        market.need(type(spec) is dict and type(spec.get("sha256")) is str and
            re.fullmatch("[a-f0-9]{64}", spec["sha256"]), "NATIVE_HANDOFF_OUTPUT_PIN")
        # Producer paths may come from Linux. Resolve only these fixed members
        # under the supplied archive root; never follow the stored absolute path.
        market.need(type(spec.get("path")) is str and
            spec["path"].replace("\\", "/").split("/")[-1] == name, "NATIVE_HANDOFF_OUTPUT_NAME")
        remaining = market.MAX_TOTAL_BYTES-sum(map(len, bodies.values()))
        market.need(remaining > 0, "NATIVE_HANDOFF_TOTAL_BYTES")
        body = read_local(root, name, min(limit, remaining))
        market.need(digest(body) == spec["sha256"], "NATIVE_HANDOFF_OUTPUT_HASH")
        bodies[name] = body
        pins[key] = spec["sha256"]
        market.need(sum(map(len, bodies.values())) <= market.MAX_TOTAL_BYTES, "NATIVE_HANDOFF_TOTAL_BYTES")
    lineage = market.free.strict_json(bodies["source_lineage.json"])
    market.need(type(lineage) is dict and lineage.get("schema_version") == "run287-chameleon-source-lineage-v1" and
        lineage.get("contract_semantic_sha256") == producer.CANONICAL_CONTRACT_SEMANTIC_SHA256 and
        lineage.get("calendar_sha256") == pins["calendar"] and
        lineage.get("resolved_as_of") == lineage.get("requested_as_of") == session and
        lineage.get("truth_class") == "FREE_PROXY" and lineage.get("historical_ab_allowed") is False,
        "NATIVE_HANDOFF_LINEAGE_BINDING")
    blobs = {kind: bodies[name] for name, kind, _ in FILES.values() if kind is not None}
    for kind in ("risk_metrics", "risk_context"):
        table = market.clock.table(blobs[kind])
        market.need(table.empty or (table["source_sha256"].eq(pins["source_lineage"]).all() and
            table["truth_class"].eq("FREE_PROXY").all()), "NATIVE_HANDOFF_ROW_LINEAGE_OR_TRUTH")
    credit_request = None
    credit_root = None
    credit = []
    if current_credit_input_root is not None:
        market.need(type(current_credit_request_sha256) is str and
            re.fullmatch('[a-f0-9]{64}', current_credit_request_sha256), 'NATIVE_HANDOFF_CREDIT_REQUEST_PIN')
        credit_root = Path(current_credit_input_root)
        market.need(not (credit_root.resolve().is_relative_to(dest) or dest.is_relative_to(credit_root.resolve())),
            'NATIVE_HANDOFF_PATH_OVERLAP')
        credit_request = read_local(credit_root, 'request.json', 256*1024)
        supplied = market.verify_request(credit_request, current_credit_request_sha256, cutoff, session)
        for spec in supplied['inputs']:
            if not collector.credit_source_input(spec):
                continue
            body = read_local(credit_root, market.safe_path(spec['path']), market.input_limit(spec))
            market.need(digest(body) == spec['sha256'], 'NATIVE_HANDOFF_CREDIT_ORIGINAL_HASH')
            rows = liquidity.parse_original(body, spec)
            market.need(liquidity.summarize(rows, cutoff)['status'] == 'OBSERVED',
                'NATIVE_HANDOFF_CREDIT_NOT_CURRENT')
            credit.append((spec, body))
            market.need(sum(map(len, bodies.values())) + sum(len(b) for _,b in credit) <= market.MAX_TOTAL_BYTES,
                'NATIVE_HANDOFF_TOTAL_BYTES')
        market.need(credit, 'NATIVE_HANDOFF_CREDIT_ORIGINAL_REQUIRED')
    assessment = market.native_risk(blobs, session, cutoff)
    market.need(assessment["status"] == "READY_RESEARCH_ONLY", "NATIVE_HANDOFF_TEN_AXIS_NOT_READY")
    entries, objects = [], {}
    for name, kind, _ in FILES.values():
        if kind is None:
            continue
        body = bodies[name]
        path = "native/"+digest(body)
        objects[path] = body
        entries.append(dict(kind=kind, path=path, sha256=digest(body), status="COLLECTED", collected_at=cutoff,
            native_source_manifest_sha256=expected_manifest_sha256,
            native_source_lineage_sha256=pins["source_lineage"]))
    for spec, body in credit:
        path = 'native/'+spec['sha256']
        objects[path] = body
        entries.append(dict(spec, path=path))
    request = dict(schema=market.REQUEST_SCHEMA_V2, market="US", session=session,
        available_at=cutoff, expires_at=(market.clock.stamp(cutoff)+timedelta(days=1)).isoformat(), inputs=entries)
    request_raw = encoded(request)
    market.verify_request(request_raw, digest(request_raw), cutoff, session)
    receipt = dict(schema="a4-native-input-preparation-v1", status="PREPARED_LOCAL_RESEARCH_HANDOFF",
        session=session, prepared_at=cutoff, request_sha256=digest(request_raw),
        source_manifest_sha256=expected_manifest_sha256, source_code_sha=manifest.get("git_head"),
        source_output_sha256s=pins, implementation=identity,
        native_ready_axes=assessment["ready_axis_count"], native_required_axes_ready=assessment["required_axes_ready"],
        source_originals_independently_replayed=False, upstream_rights_review_required=True,
        current_credit_request_sha256=current_credit_request_sha256,
        current_credit_original_sha256s=[spec['sha256'] for spec,_ in credit],
        request_collection_clock="DERIVED_PACKET_PREPARATION_ONLY_ORIGINAL_ROW_CLOCKS_UNCHANGED", **SAFETY)
    # Check every consumed file again after native replay, before any write.
    for name, body in bodies.items():
        market.need(read_local(root, name, len(body)+1) == body, "NATIVE_HANDOFF_SOURCE_CHANGED")
    if credit_request is not None:
        market.need(read_local(credit_root, 'request.json', len(credit_request)+1) == credit_request,
            'NATIVE_HANDOFF_CREDIT_CHANGED')
        for spec, body in credit:
            market.need(read_local(credit_root, market.safe_path(spec['path']), len(body)+1) == body,
                'NATIVE_HANDOFF_CREDIT_CHANGED')
    current = implementation_identity()
    market.need(current == identity, "NATIVE_HANDOFF_CODE_CHANGED")
    # The hash file is the existing consumer's commit marker. Write it only
    # after the objects, request and preparation receipt are complete.
    output = {**objects, "request.json": request_raw, "native-preparation.json": encoded(receipt),
        "request.sha256": digest(request_raw).encode("ascii")}
    # Preflight the full destination before writes; a conflicting old attempt
    # must not leave a new request beside a prior receipt.
    for name, body in output.items():
        path = dest/name
        market.need(not any(p.is_symlink() for p in (path, *path.parents)), "NATIVE_HANDOFF_SYMLINK")
        if path.exists():
            market.need(path.is_file() and market.bounded(path, len(body)+1) == body, "NATIVE_HANDOFF_DESTINATION_CONFLICT")
    for name, body in output.items():
        exclusive(dest/name, body)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--manifest-sha256", required=True, help="Exact original Source manifest pin, supplied independently")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument('--current-credit-input-root', help='Optional current Source request with separately qualified HY/IG originals')
    parser.add_argument('--current-credit-request-sha256', help='Independent original request hash, required with the credit root')
    args = parser.parse_args()
    try:
        result = prepare(args.source_root, args.manifest_sha256,
            cutoff=market.clock.trusted_now().isoformat(), output_dir=args.output_dir,
            current_credit_input_root=args.current_credit_input_root,
            current_credit_request_sha256=args.current_credit_request_sha256)
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError) as exc:
        message = str(exc)
        blocker = message if re.fullmatch("NATIVE_HANDOFF_[A-Z_]+", message) else "INVALID_OR_UNAVAILABLE_NATIVE_SOURCE"
        print(encoded(dict(status="BLOCKED_NATIVE_INPUT_PREPARATION", blocker=blocker,
            accepted_state_changed=False)).decode(), end="")
        return 2
    print(encoded(result).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
