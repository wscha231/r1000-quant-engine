#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
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
                key: existing.get(key)
                for key in event_payload
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
    require("MUTATING COMMANDS BELOW" in render, "plan warning")
    require("subprocess.run" not in render, "renderer must not execute commands")
    for forbidden in ("services enable", "repositories create", "run deploy"):
        require(forbidden not in probe, f"probe contains mutation: {forbidden}")
    require("REGION=asia-northeast3" in env, "Seoul env")
    require("datastore.entities.create" in role, "create permission")
    require("datastore.entities.get" in role, "get permission")
    require("datastore.entities.update" not in role, "no update permission")
    require("datastore.entities.delete" not in role, "no delete permission")
    require("datastore.entities.list" not in role, "no list permission")


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
    ]
    for test in tests:
        test()
    print(
        f"product_analytics_collector_v1_smoke: PASS ({len(tests)} tests)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
