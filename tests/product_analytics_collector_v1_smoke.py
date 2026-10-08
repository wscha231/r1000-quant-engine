#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.product_analytics_collector.app import (  # noqa: E402
    COLLECTION,
    CollectorApplication,
    CollectorConfig,
    SlidingWindowLimiter,
    StorageUnavailable,
    _read_body,
)

ORIGIN = "https://wscha231.github.io"
FIXED_NOW = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.fail = False

    def create_or_compare(
        self,
        event_id: str,
        event_payload: dict,
        *,
        server_received_at_utc: datetime,
        expires_at: datetime,
    ) -> str:
        if self.fail:
            raise StorageUnavailable("forced")
        existing = self.docs.get(event_id)
        if existing is not None:
            comparable = {
                key: value for key, value in existing.items()
                if key not in {"server_received_at_utc", "expires_at"}
            }
            return "DUPLICATE" if comparable == event_payload else "CONFLICT"
        self.docs[event_id] = {
            **deepcopy(event_payload),
            "server_received_at_utc": server_received_at_utc,
            "expires_at": expires_at,
        }
        return "CREATED"


def config(**overrides) -> CollectorConfig:
    values = dict(
        allowed_origins=frozenset({ORIGIN}),
        project_id="r1000-test-project",
        firestore_database="r1000-product-analytics",
        firestore_location="asia-northeast3",
        cloud_run_region="asia-northeast3",
        max_body_bytes=16 * 1024,
        rate_per_minute=120,
        raw_ttl_days=89,
    )
    values.update(overrides)
    return CollectorConfig(**values)


def event(event_id: str = "evt-a", **overrides) -> dict:
    row = {
        "schema_version": "b5-product-analytics-event-v1",
        "event_name": "site_viewed",
        "event_version": 1,
        "event_id": event_id,
        "occurred_at_utc": "2026-10-07T23:59:00Z",
        "received_at_utc": "2026-10-07T23:59:00Z",
        "session_id": "session-a",
        "consent_status": "ACTIVE",
        "consent_version": "b6-analytics-consent-v1",
        "page": "home",
        "surface": "site",
        "data_state": "USABLE",
        "public_artifact_version": "artifact-20261008",
        "is_internal": False,
        "is_bot": False,
    }
    row.update(overrides)
    return row


def call(
    app,
    *,
    method: str = "POST",
    payload: dict | bytes | None = None,
    origin: str | None = ORIGIN,
    path: str = "/v1/events",
    content_type: str = "application/json",
):
    if payload is None:
        body = b""
    elif isinstance(payload, bytes):
        body = payload
    else:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    observed = {}

    def start_response(status, headers):
        observed["status"] = status
        observed["headers"] = dict(headers)

    response = b"".join(app(environ, start_response))
    decoded = json.loads(response.decode("utf-8")) if response else None
    return int(observed["status"].split()[0]), observed["headers"], decoded


def make_app(store: FakeStore | None = None, **config_overrides):
    store = store or FakeStore()
    app = CollectorApplication(
        config(**config_overrides),
        store=store,
        clock=lambda: FIXED_NOW,
    )
    return app, store


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_config_is_fail_closed_and_seoul_only() -> None:
    require(config().error() is None, "valid config")
    require(
        config(allowed_origins=frozenset()).error()
        == "allowed_origins_missing",
        "origin required",
    )
    require(
        config(allowed_origins=frozenset({"*"})).error()
        == "allowed_origins_invalid",
        "wildcard forbidden",
    )
    require(
        config(firestore_database="(default)").error()
        == "dedicated_firestore_database_required",
        "dedicated database",
    )
    require(
        config(firestore_location="us-central1").error()
        == "firestore_location_must_be_seoul",
        "firestore Seoul",
    )
    require(
        config(cloud_run_region="asia-northeast1").error()
        == "cloud_run_region_must_be_seoul",
        "Cloud Run Seoul",
    )


def test_cors_preflight_and_origin_rejection() -> None:
    app, _ = make_app()
    code, headers, body = call(app, method="OPTIONS")
    require(code == 204 and body is None, "preflight")
    require(
        headers.get("Access-Control-Allow-Origin") == ORIGIN,
        "exact origin",
    )
    require(
        headers.get("Access-Control-Allow-Methods") == "POST, OPTIONS",
        "methods",
    )
    code, headers, body = call(
        app,
        method="OPTIONS",
        origin="https://evil.example",
    )
    require(code == 403, "bad origin")
    require("Access-Control-Allow-Origin" not in headers, "no reflected origin")


def test_valid_event_is_accepted_without_transport_metadata() -> None:
    app, store = make_app()
    code, headers, body = call(app, payload=event())
    require(code == 202 and body == {"status": "accepted"}, "accepted")
    require(headers.get("Access-Control-Allow-Origin") == ORIGIN, "cors")
    require(set(store.docs) == {"evt-a"}, "document key")
    stored = store.docs["evt-a"]
    require(stored["event_id"] == "evt-a", "event id")
    require(stored["session_id"] == "session-a", "session id")
    require(
        stored["expires_at"] - stored["server_received_at_utc"]
        == __import__("datetime").timedelta(days=89),
        "89-day TTL target",
    )
    for forbidden in (
        "ip",
        "ip_address",
        "user_agent",
        "referrer",
        "email",
        "account_id",
        "broker_id",
    ):
        require(forbidden not in stored, f"forbidden stored: {forbidden}")


def test_exact_duplicate_is_idempotent_and_conflict_is_409() -> None:
    app, _ = make_app()
    row = event("same")
    require(call(app, payload=row)[0] == 202, "first create")
    require(call(app, payload=deepcopy(row))[0] == 202, "exact duplicate")
    conflict = deepcopy(row)
    conflict["surface"] = "research_results"
    require(call(app, payload=conflict)[0] == 409, "conflict")


def test_consent_schema_and_future_time_fail_closed() -> None:
    app, _ = make_app()
    require(
        call(app, payload=event("no-consent", consent_status="DECLINED"))[0]
        == 403,
        "consent",
    )
    unknown = event("unknown")
    unknown["search_query"] = "secret"
    require(call(app, payload=unknown)[0] == 400, "unknown field")
    require(
        call(
            app,
            payload=event(
                "future",
                occurred_at_utc="2026-10-08T00:00:01Z",
                received_at_utc="2026-10-08T00:00:01Z",
            ),
        )[0]
        == 400,
        "future timestamp",
    )


def test_firestore_document_id_constraints_fail_closed() -> None:
    app, _ = make_app()
    require(call(app, payload=event("."))[0] == 400, "dot id")
    require(call(app, payload=event(".."))[0] == 400, "double-dot id")
    require(call(app, payload=event("__reserved__"))[0] == 400, "reserved id")


def test_payload_content_type_and_persistence_fail_closed() -> None:
    app, store = make_app(max_body_bytes=64)
    require(
        call(app, payload=b"x" * 65)[0] == 413,
        "payload limit",
    )
    require(
        call(app, payload=event(), content_type="text/plain")[0] == 400,
        "content type",
    )
    app, store = make_app()
    store.fail = True
    require(call(app, payload=event("persist"))[0] == 503, "persistence")


def test_rate_limit_is_bounded_per_instance() -> None:
    store = FakeStore()
    limiter = SlidingWindowLimiter(2, now=lambda: 1000.0)
    app = CollectorApplication(
        config(rate_per_minute=2),
        store=store,
        clock=lambda: FIXED_NOW,
        limiter=limiter,
    )
    require(call(app, payload=event("rate-a"))[0] == 202, "rate first")
    require(call(app, payload=event("rate-b"))[0] == 202, "rate second")
    code, headers, _ = call(app, payload=event("rate-c"))
    require(code == 429, "rate third")
    require(headers.get("Retry-After") == "60", "retry after")


def test_no_raw_request_metadata_is_referenced_by_application() -> None:
    source = (
        ROOT
        / "tools"
        / "product_analytics_collector"
        / "app.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "REMOTE_ADDR",
        "HTTP_USER_AGENT",
        "HTTP_REFERER",
        "HTTP_X_FORWARDED_FOR",
        "X-Forwarded-For",
    ):
        require(forbidden not in source, f"transport metadata reference: {forbidden}")


def test_firestore_adapter_uses_create_then_single_document_get() -> None:
    source = (
        ROOT
        / "tools"
        / "product_analytics_collector"
        / "firestore_store.py"
    ).read_text(encoding="utf-8")
    require("firestore.Client(" in source, "client")
    require("database=database_id" in source, "named database")
    require(".document(event_id)" in source, "event document")
    require("ref.create(document)" in source, "create-only first")
    require("snapshot = ref.get()" in source, "single-document duplicate read")
    require(".stream(" not in source and ".where(" not in source, "no query/list")


def test_deploy_plan_is_render_only_and_predeploy_probe_is_read_only() -> None:
    root = ROOT / "tools" / "product_analytics_collector"
    render = (root / "render_deploy_plan.py").read_text(encoding="utf-8")
    probe = (root / "predeploy_check.py").read_text(encoding="utf-8")
    env = (root / "deploy.env.example").read_text(encoding="utf-8")
    role = (root / "iam_role.yaml").read_text(encoding="utf-8")
    cloudbuild = (root / "cloudbuild.yaml").read_text(encoding="utf-8")
    require("MUTATING COMMANDS BELOW" in render, "plan warning")
    require("subprocess.run" not in render, "renderer must not execute commands")
    for forbidden in ("services enable", "repositories create", "run deploy"):
        require(forbidden not in probe, f"probe contains mutation: {forbidden}")
    require("REGION=asia-northeast3" in env, "Seoul env")
    require("DEPLOY_SHA=" in env and "BUDGET_AMOUNT_USD=" in env, "deploy/budget pins")
    require("tools/product_analytics_collector/Dockerfile" in cloudbuild, "custom Dockerfile")
    require("${_IMAGE}" in cloudbuild, "immutable image substitution")
    require("datastore.entities.create" in role, "create permission")
    require("datastore.entities.get" in role, "get permission")
    require("datastore.entities.update" not in role, "no update permission")
    require("datastore.entities.delete" not in role, "no delete permission")
    require("datastore.entities.list" not in role, "no list permission")
    require("billing budgets create" in render, "budget plan")
    require("logging sinks update _Default" in render, "logging exclusion plan")
    require("builds submit . --region=" in render, "Cloud Build config plan")


def test_container_and_docs_remain_prepare_only() -> None:
    docker = (
        ROOT
        / "tools"
        / "product_analytics_collector"
        / "Dockerfile"
    ).read_text(encoding="utf-8")
    doc = (
        ROOT
        / "docs"
        / "B5_PRODUCT_ANALYTICS_COLLECTOR_V1.md"
    ).read_text(encoding="utf-8")
    require("gunicorn" in docker, "gunicorn")
    require("NO_DEPLOY" in doc, "no deploy")
    require("asia-northeast3" in doc, "Seoul")
    require("D1/D7/D30" in doc and "NOT_AVAILABLE" in doc, "retention boundary")
    require(COLLECTION in doc, "collection")


def test_wsgi_read_stays_inside_declared_body() -> None:
    class DeclaredStream:
        def read(self, size):
            require(size == 2, "WSGI must not read past CONTENT_LENGTH")
            return b"{}"
    require(_read_body({"CONTENT_LENGTH": "2", "wsgi.input": DeclaredStream()}, 100) == b"{}", "declared body")
    from tools.aggregate_product_analytics import ContractError
    try:
        _read_body({"wsgi.input": DeclaredStream()}, 100)
    except ContractError:
        pass
    else:
        raise AssertionError("unterminated stream without a length must be rejected")
    require(_read_body({"wsgi.input": io.BytesIO(b"{}"), "wsgi.input_terminated": True}, 100) == b"{}", "terminated chunked body")


def test_origins_are_exact_and_json_errors_are_finite() -> None:
    app, store = make_app()
    for origin in (ORIGIN + "/", ORIGIN + " ", "https://*.example.com", "https://example.com?x=1", "https://user@example.com"):
        require(call(app, payload=event(), origin=origin)[0] == 403, "exact request origin")
    for invalid in ("https://*.example.com", "https://example.com?x=1", "https://user@example.com", "https://"):
        require(config(allowed_origins=frozenset({invalid})).error() is not None, "invalid configured origin")
    for body in (b"{", b'{"event_version":' + b"9" * 5000 + b"}", b"[" * 2000 + b"]" * 2000, b'{"event_id":1,"event_id":2}'):
        require(call(app, payload=body)[0] == 400, "finite malformed JSON response")
    require(not store.docs, "rejected input never persists")


def test_adapter_duplicate_compares_all_fields_and_only_already_exists_reads() -> None:
    from tools.product_analytics_collector.firestore_store import FirestoreEventStore
    class ApiError(Exception): pass
    class Conflict(ApiError): pass
    class AlreadyExists(Conflict): pass
    class Ref:
        def __init__(self):
            self.saved = None
            self.failure = None
            self.gets = 0
        def create(self, document):
            if self.failure:
                raise self.failure
            if self.saved is not None:
                raise AlreadyExists()
            self.saved = deepcopy(document)
        def get(self):
            self.gets += 1
            return SimpleNamespace(exists=True, to_dict=lambda: deepcopy(self.saved))
    ref = Ref()
    store = FirestoreEventStore.__new__(FirestoreEventStore)
    store._exceptions = SimpleNamespace(AlreadyExists=AlreadyExists, Conflict=Conflict, GoogleAPICallError=ApiError)
    store._collection = COLLECTION
    store._client = SimpleNamespace(collection=lambda name: SimpleNamespace(document=lambda key: ref))
    row = event(market="US")
    def put(payload):
        return store.create_or_compare(payload["event_id"], payload, server_received_at_utc=FIXED_NOW, expires_at=FIXED_NOW)
    require(put(row) == "CREATED" and ref.gets == 0, "atomic create first")
    require(put(deepcopy(row)) == "DUPLICATE", "exact duplicate")
    less = deepcopy(row); less.pop("market")
    require(put(less) == "CONFLICT", "removing a stored optional field conflicts")
    ref.saved["unexpected"] = "unknown"
    require(put(row) == "CONFLICT", "unknown stored fields fail exact comparison")
    before = ref.gets
    ref.failure = Conflict()
    try:
        put(row)
    except StorageUnavailable:
        pass
    else:
        raise AssertionError("non-AlreadyExists conflict must be unavailable")
    require(ref.gets == before, "only AlreadyExists permits get")


def deploy_values():
    from tools.product_analytics_collector.render_deploy_plan import read_env
    raw = (ROOT / "tools/product_analytics_collector/deploy.env.example").read_text()
    raw = raw.replace("PROJECT_ID=\n", "PROJECT_ID=r1000-test-project\n").replace("BILLING_ACCOUNT_ID=\n", "BILLING_ACCOUNT_ID=000000-000000-000000\n").replace("BUDGET_AMOUNT_USD=\n", "BUDGET_AMOUNT_USD=10\n").replace("DEPLOY_SHA=\n", "DEPLOY_SHA=" + "a" * 40 + "\n")
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "deploy.env"
        path.write_text(raw)
        return read_env(path)


def test_render_input_rejects_nonfinite_budget_and_invalid_limits() -> None:
    from tools.product_analytics_collector.render_deploy_plan import read_env
    values = deploy_values()
    for key, value in (("BUDGET_AMOUNT_USD", "nan"), ("BUDGET_AMOUNT_USD", "inf"), ("ALLOWED_ORIGINS", "https://*.example.com"), ("ALLOWED_ORIGINS", "http://example.com"), ("MAX_INSTANCES", "1000"), ("RAW_TTL_DAYS", "90"), ("DATABASE_ID", "x")):
        bad = {**values, key: value}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "deploy.env"
            path.write_text("\n".join(k + "=" + v for k, v in bad.items()))
            try:
                read_env(path)
            except SystemExit:
                pass
            else:
                raise AssertionError("invalid deployment value accepted: " + key)


def test_render_preserves_multiple_origins_and_source_sha() -> None:
    import shlex
    from tools.product_analytics_collector.render_deploy_plan import render_plan
    values = deploy_values()
    values["ALLOWED_ORIGINS"] = ORIGIN + ",https://r1000.example.com"
    commands = render_plan(values)
    stop = next(c for c in commands if "exit 2" in c and "private bootstrap" in c)
    require(commands.index(stop) < next(i for i, c in enumerate(commands) if c.startswith("gcloud ")), "bootstrap incompatibility blocks all mutation")
    deploy = next(c for c in commands if c.startswith("gcloud run deploy "))
    env_arg = next(c for c in shlex.split(deploy) if c.startswith("--set-env-vars="))
    require(env_arg.startswith("--set-env-vars=^|^"), "alternate gcloud dictionary delimiter")
    require("R1000_ANALYTICS_ALLOWED_ORIGINS=" + values["ALLOWED_ORIGINS"] + "|" in env_arg, "two origins stay in one env value")
    require(any("git rev-parse HEAD" in c and values["DEPLOY_SHA"] in c for c in commands), "source SHA guard before mutations")
    require(any("git status --porcelain" in c for c in commands), "clean build-source guard")
    log = next(c for c in commands if c.startswith("gcloud logging sinks update"))
    require("--add-exclusion=" in log and "cloud_run_revision" in log and "run.googleapis.com%2Frequests" in log, "scoped request-log exclusion")
    require(commands.index(log) < commands.index(deploy), "exclusion precedes private deployment")
    require("--no-allow-unauthenticated" in deploy and "--no-traffic" in deploy, "private no-traffic boundary")


def test_readonly_probe_blocks_failed_or_ambiguous_queries() -> None:
    from tools.product_analytics_collector import predeploy_check as probe
    values = deploy_values()
    observed = []
    def response(*args):
        observed.append(args)
        if args[1:3] == ("auth", "list"): return 0, "operator@example.invalid"
        if args[1:3] == ("config", "get-value"): return 0, values["PROJECT_ID"]
        if "describe" in args: return 0, json.dumps({"name": "_Default", "destination": "logging.googleapis.com/projects/r1000-test-project/locations/global/buckets/_Default"})
        return 0, "[]"
    with patch.object(probe, "run", side_effect=response):
        result = probe.probe(values)
    require(result["status"] == "PREDEPLOY_READ_ONLY_OK" and result["mutations_performed"] == [], "successful absent resources")
    require(all("--project" in cmd for cmd in observed if cmd[1] not in {"auth", "config"}), "explicit project for every resource query")
    for code, output in ((1, "PERMISSION_DENIED credential-like-stderr"), (0, "invalid-json"), (0, "[{}]"), (0, json.dumps([{"name": "projects/" + values["PROJECT_ID"] + "/databases/" + values["DATABASE_ID"], "type": "FIRESTORE_NATIVE"}]))):
        def broken(*args):
            if args[1:3] == ("firestore", "databases"): return code, output
            return response(*args)
        with patch.object(probe, "run", side_effect=broken): result = probe.probe(values)
        require(result["status"] == "BLOCKED", "unknown database state fails closed")
        require("credential-like-stderr" not in json.dumps(result), "raw query output never printed")
    def existing_service(*args):
        if args[1:3] == ("run", "services"): return 0, json.dumps([{"metadata": {"name": values["SERVICE_NAME"]}}])
        return response(*args)
    with patch.object(probe, "run", side_effect=existing_service): result = probe.probe(values)
    require(result["status"] == "BLOCKED", "existing service cannot be overwritten")


def main() -> int:
    tests = [
        test_config_is_fail_closed_and_seoul_only,
        test_cors_preflight_and_origin_rejection,
        test_valid_event_is_accepted_without_transport_metadata,
        test_exact_duplicate_is_idempotent_and_conflict_is_409,
        test_consent_schema_and_future_time_fail_closed,
        test_firestore_document_id_constraints_fail_closed,
        test_payload_content_type_and_persistence_fail_closed,
        test_rate_limit_is_bounded_per_instance,
        test_no_raw_request_metadata_is_referenced_by_application,
        test_firestore_adapter_uses_create_then_single_document_get,
        test_deploy_plan_is_render_only_and_predeploy_probe_is_read_only,
        test_container_and_docs_remain_prepare_only,
        test_wsgi_read_stays_inside_declared_body,
        test_origins_are_exact_and_json_errors_are_finite,
        test_adapter_duplicate_compares_all_fields_and_only_already_exists_reads,
        test_render_input_rejects_nonfinite_budget_and_invalid_limits,
        test_render_preserves_multiple_origins_and_source_sha,
        test_readonly_probe_blocks_failed_or_ambiguous_queries,
    ]
    for test in tests:
        test()
    print(
        f"product_analytics_collector_v1_smoke: PASS ({len(tests)} tests)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
