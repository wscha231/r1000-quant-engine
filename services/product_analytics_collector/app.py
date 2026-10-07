#!/usr/bin/env python3
"""PREPARE_ONLY Cloud Run WSGI collector for consented B5 analytics events.

No deployment, credential mutation, browser instrumentation, or A-side authority
is performed by this module. Runtime transmission stays unauthorized until the
separate deployment/privacy gates are satisfied.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Protocol

from tools.aggregate_product_analytics import (
    ContractError,
    DEFAULT_CONTRACT,
    load_contract,
    strict_json_loads,
    validate_event,
)

COLLECTION = "product_analytics_events_v1"
SERVER_FIELDS = {"server_received_at_utc", "expires_at"}
SEOUL_REGION = "asia-northeast3"
DEFAULT_MAX_BODY_BYTES = 16 * 1024
DEFAULT_RATE_PER_MINUTE = 120
RAW_TTL_DAYS = 89


class StorageUnavailable(RuntimeError):
    pass


class EventStore(Protocol):
    def create_or_compare(
        self,
        event_id: str,
        event_payload: dict[str, Any],
        *,
        server_received_at_utc: datetime,
        expires_at: datetime,
    ) -> str:
        """Return CREATED, DUPLICATE, or CONFLICT."""


@dataclass(frozen=True)
class CollectorConfig:
    allowed_origins: frozenset[str]
    project_id: str
    firestore_database: str
    firestore_location: str
    cloud_run_region: str
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    rate_per_minute: int = DEFAULT_RATE_PER_MINUTE
    raw_ttl_days: int = RAW_TTL_DAYS

    @classmethod
    def from_environment(cls) -> "CollectorConfig":
        raw_origins = os.environ.get("R1000_ANALYTICS_ALLOWED_ORIGINS", "")
        origins = frozenset(
            token.strip().rstrip("/")
            for token in raw_origins.split(",")
            if token.strip()
        )
        def integer(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                value = int(raw)
            except ValueError:
                return -1
            return value
        return cls(
            allowed_origins=origins,
            project_id=os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip(),
            firestore_database=os.environ.get(
                "R1000_ANALYTICS_FIRESTORE_DATABASE", ""
            ).strip(),
            firestore_location=os.environ.get(
                "R1000_ANALYTICS_FIRESTORE_LOCATION", ""
            ).strip(),
            cloud_run_region=os.environ.get(
                "R1000_ANALYTICS_CLOUD_RUN_REGION", ""
            ).strip(),
            max_body_bytes=integer(
                "R1000_ANALYTICS_MAX_BODY_BYTES",
                DEFAULT_MAX_BODY_BYTES,
            ),
            rate_per_minute=integer(
                "R1000_ANALYTICS_RATE_PER_MINUTE",
                DEFAULT_RATE_PER_MINUTE,
            ),
            raw_ttl_days=integer(
                "R1000_ANALYTICS_RAW_TTL_DAYS",
                RAW_TTL_DAYS,
            ),
        )

    def error(self) -> str | None:
        if not self.allowed_origins:
            return "allowed_origins_missing"
        if any(
            origin == "*"
            or not origin.startswith("https://")
            or "/" in origin[len("https://"):]
            for origin in self.allowed_origins
        ):
            return "allowed_origins_invalid"
        if not self.project_id:
            return "project_id_missing"
        if not self.firestore_database or self.firestore_database == "(default)":
            return "dedicated_firestore_database_required"
        if self.firestore_location != SEOUL_REGION:
            return "firestore_location_must_be_seoul"
        if self.cloud_run_region != SEOUL_REGION:
            return "cloud_run_region_must_be_seoul"
        if not (1 <= self.max_body_bytes <= 64 * 1024):
            return "max_body_bytes_invalid"
        if not (1 <= self.rate_per_minute <= 10_000):
            return "rate_per_minute_invalid"
        if not (1 <= self.raw_ttl_days <= 89):
            return "raw_ttl_days_invalid"
        return None


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._now = now
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = self._now()
        cutoff = now - 60.0
        with self._lock:
            while self._events and self._events[0] <= cutoff:
                self._events.popleft()
            if len(self._events) >= self._limit:
                return False
            self._events.append(now)
            return True


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_body(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _cors_headers(origin: str | None) -> list[tuple[str, str]]:
    if not origin:
        return []
    return [
        ("Access-Control-Allow-Origin", origin),
        ("Vary", "Origin"),
    ]


def _respond(
    start_response: Callable[..., Any],
    status: str,
    payload: dict[str, Any] | None = None,
    *,
    origin: str | None = None,
    extra_headers: Iterable[tuple[str, str]] = (),
) -> list[bytes]:
    body = b"" if payload is None else _json_body(payload)
    headers = [
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        *_cors_headers(origin),
        *list(extra_headers),
    ]
    if payload is not None:
        headers.extend(
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ]
        )
    else:
        headers.append(("Content-Length", "0"))
    start_response(status, headers)
    return [body]


def _read_body(environ: dict[str, Any], max_bytes: int) -> bytes:
    raw_length = str(environ.get("CONTENT_LENGTH") or "").strip()
    expected: int | None = None
    if raw_length:
        try:
            expected = int(raw_length)
        except ValueError as exc:
            raise ContractError("invalid_content_length") from exc
        if expected < 0:
            raise ContractError("invalid_content_length")
        if expected > max_bytes:
            raise ContractError("payload_too_large")
    stream = environ.get("wsgi.input")
    if stream is None or not hasattr(stream, "read"):
        raise ContractError("missing_request_body_stream")
    body = stream.read(max_bytes + 1)
    if not isinstance(body, (bytes, bytearray)):
        raise ContractError("request_body_not_bytes")
    encoded = bytes(body)
    if len(encoded) > max_bytes:
        raise ContractError("payload_too_large")
    if expected is not None and len(encoded) != expected:
        raise ContractError("content_length_mismatch")
    return encoded


class CollectorApplication:
    def __init__(
        self,
        config: CollectorConfig | None = None,
        *,
        store: EventStore | None = None,
        clock: Callable[[], datetime] = utc_now,
        limiter: SlidingWindowLimiter | None = None,
    ) -> None:
        self.config = config or CollectorConfig.from_environment()
        self._contract = load_contract(DEFAULT_CONTRACT)
        self._store = store
        self._store_lock = threading.Lock()
        self._clock = clock
        self._limiter = limiter or SlidingWindowLimiter(
            max(1, self.config.rate_per_minute)
        )

    def _allowed_origin(self, environ: dict[str, Any]) -> str | None:
        origin = str(environ.get("HTTP_ORIGIN") or "").strip().rstrip("/")
        if origin in self.config.allowed_origins:
            return origin
        return None

    def _get_store(self) -> EventStore:
        if self._store is not None:
            return self._store
        with self._store_lock:
            if self._store is None:
                try:
                    from services.product_analytics_collector.firestore_store import (
                        FirestoreEventStore,
                    )
                    self._store = FirestoreEventStore(
                        project_id=self.config.project_id,
                        database_id=self.config.firestore_database,
                        collection=COLLECTION,
                    )
                except Exception as exc:
                    raise StorageUnavailable("store_initialization_failed") from exc
        return self._store

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[..., Any],
    ) -> list[bytes]:
        path = str(environ.get("PATH_INFO") or "")
        method = str(environ.get("REQUEST_METHOD") or "").upper()
        if path != "/v1/events":
            return _respond(
                start_response,
                "404 Not Found",
                {"status": "not_found"},
            )

        config_error = self.config.error()
        if config_error:
            return _respond(
                start_response,
                "503 Service Unavailable",
                {"status": "unavailable"},
            )

        origin = self._allowed_origin(environ)
        if origin is None:
            return _respond(
                start_response,
                "403 Forbidden",
                {"status": "forbidden"},
            )

        if method == "OPTIONS":
            return _respond(
                start_response,
                "204 No Content",
                None,
                origin=origin,
                extra_headers=(
                    ("Access-Control-Allow-Methods", "POST, OPTIONS"),
                    ("Access-Control-Allow-Headers", "Content-Type"),
                    ("Access-Control-Max-Age", "600"),
                ),
            )
        if method != "POST":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                {"status": "method_not_allowed"},
                origin=origin,
                extra_headers=(("Allow", "POST, OPTIONS"),),
            )
        if not self._limiter.allow():
            return _respond(
                start_response,
                "429 Too Many Requests",
                {"status": "overloaded"},
                origin=origin,
                extra_headers=(("Retry-After", "60"),),
            )

        content_type = str(environ.get("CONTENT_TYPE") or "").lower()
        if content_type.split(";", 1)[0].strip() != "application/json":
            return _respond(
                start_response,
                "400 Bad Request",
                {"status": "rejected", "reason": "content_type"},
                origin=origin,
            )

        try:
            body = _read_body(environ, self.config.max_body_bytes)
        except ContractError as exc:
            code = "413 Payload Too Large" if str(exc) == "payload_too_large" else "400 Bad Request"
            return _respond(
                start_response,
                code,
                {"status": "rejected", "reason": "payload"},
                origin=origin,
            )
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return _respond(
                start_response,
                "400 Bad Request",
                {"status": "rejected", "reason": "json"},
                origin=origin,
            )
        try:
            payload = strict_json_loads(text)
            if not isinstance(payload, dict):
                raise ContractError("event_not_object")
            normalized = validate_event(payload, self._contract)
        except ContractError as exc:
            reason = str(exc)
            if reason in {
                "analytics_consent_not_active",
                "consent_version_mismatch",
            }:
                return _respond(
                    start_response,
                    "403 Forbidden",
                    {"status": "forbidden", "reason": "consent"},
                    origin=origin,
                )
            return _respond(
                start_response,
                "400 Bad Request",
                {"status": "rejected", "reason": "schema"},
                origin=origin,
            )

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            return _respond(
                start_response,
                "503 Service Unavailable",
                {"status": "unavailable"},
                origin=origin,
            )
        now = now.astimezone(timezone.utc)
        if normalized["_occurred"] > now or normalized["_received"] > now:
            return _respond(
                start_response,
                "400 Bad Request",
                {"status": "rejected", "reason": "future_timestamp"},
                origin=origin,
            )

        public_event = {
            key: value
            for key, value in normalized.items()
            if not key.startswith("_")
        }
        event_id = public_event["event_id"]
        if (
            event_id in {".", ".."}
            or (event_id.startswith("__") and event_id.endswith("__"))
        ):
            return _respond(
                start_response,
                "400 Bad Request",
                {"status": "rejected", "reason": "storage_key"},
                origin=origin,
            )
        expires_at = now + timedelta(days=self.config.raw_ttl_days)
        try:
            outcome = self._get_store().create_or_compare(
                event_id,
                public_event,
                server_received_at_utc=now,
                expires_at=expires_at,
            )
        except StorageUnavailable:
            return _respond(
                start_response,
                "503 Service Unavailable",
                {"status": "unavailable"},
                origin=origin,
            )
        except Exception:
            return _respond(
                start_response,
                "503 Service Unavailable",
                {"status": "unavailable"},
                origin=origin,
            )

        if outcome == "CONFLICT":
            return _respond(
                start_response,
                "409 Conflict",
                {"status": "conflict"},
                origin=origin,
            )
        if outcome not in {"CREATED", "DUPLICATE"}:
            return _respond(
                start_response,
                "503 Service Unavailable",
                {"status": "unavailable"},
                origin=origin,
            )
        return _respond(
            start_response,
            "202 Accepted",
            {"status": "accepted"},
            origin=origin,
        )


app = CollectorApplication()


if __name__ == "__main__":
    raise SystemExit(
        "Use a WSGI server (for example gunicorn) to run this PREPARE_ONLY service."
    )
