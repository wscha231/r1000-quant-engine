#!/usr/bin/env python3
"""Firestore persistence adapter for the PREPARE_ONLY B5 collector."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from tools.aggregate_product_analytics import canonical_bytes
from tools.product_analytics_collector.app import SERVER_FIELDS, StorageUnavailable


class FirestoreEventStore:
    """Create-only event storage with exact-duplicate comparison.

    A create is attempted first. Only when the document already exists is that
    exact document read back to distinguish an idempotent duplicate from a
    conflicting reuse of event_id. No query/list/update/delete operation is used.
    """

    def __init__(
        self,
        *,
        project_id: str,
        database_id: str,
        collection: str,
    ) -> None:
        if not project_id or not database_id or database_id == "(default)":
            raise ValueError("dedicated Firestore database required")
        if not collection:
            raise ValueError("collection required")
        try:
            from google.api_core import exceptions as api_exceptions
            from google.cloud import firestore
        except Exception as exc:
            raise StorageUnavailable("firestore_dependency_unavailable") from exc
        self._exceptions = api_exceptions
        self._client = firestore.Client(
            project=project_id,
            database=database_id,
        )
        self._collection = collection

    def create_or_compare(
        self,
        event_id: str,
        event_payload: dict[str, Any],
        *,
        server_received_at_utc: datetime,
        expires_at: datetime,
    ) -> str:
        ref = self._client.collection(self._collection).document(event_id)
        document = {
            **event_payload,
            "server_received_at_utc": server_received_at_utc,
            "expires_at": expires_at,
        }
        try:
            ref.create(document)
            return "CREATED"
        except self._exceptions.AlreadyExists:
            pass
        except self._exceptions.GoogleAPICallError as exc:
            raise StorageUnavailable("firestore_create_failed") from exc

        try:
            snapshot = ref.get()
        except self._exceptions.GoogleAPICallError as exc:
            raise StorageUnavailable("firestore_duplicate_read_failed") from exc
        if not snapshot.exists:
            raise StorageUnavailable("firestore_duplicate_missing_after_conflict")
        existing = snapshot.to_dict() or {}
        comparable = {
            key: value for key, value in existing.items()
            if key not in SERVER_FIELDS
        }
        if canonical_bytes(comparable) == canonical_bytes(event_payload):
            return "DUPLICATE"
        return "CONFLICT"
