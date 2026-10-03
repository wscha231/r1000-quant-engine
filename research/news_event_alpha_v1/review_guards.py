"""Review fixes shared by SEC backoff and ID-pinned Drive metadata reads.

No network is performed without the supplied rclone transport. These checks do
not grant collection/learning rights, create directories or delete remote data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import re
import tempfile

from .admission import json_load, read_bounded, safe_rel
from .execution import require
from .runtime import utc


def retry_directive(value: str | None, *, received_at: str) -> dict:
    """RFC 9110 seconds/HTTP-date -> UTC deadline. Unknown nonempty => block.

    Never log raw headers. Delay is measured from response receipt, not from a
    later rerun. All three HTTP-date shapes are supported; arbitrary dates and
    timezone-less non-HTTP strings are not repaired into valid instructions.
    """
    at = utc(received_at)
    result = {"retry_not_before": None, "retry_manual_review_required": False}
    if value is None or value == "":
        return result
    if not isinstance(value, str) or len(value) > 128 or any(ord(c) < 32 for c in value):
        return {**result, "retry_manual_review_required": True}
    text = value.strip()
    try:
        if re.fullmatch(r"[0-9]{1,10}", text):
            until = at + timedelta(seconds=int(text))
        else:
            imf = r"[A-Z][a-z]{2}, [0-9]{2} [A-Z][a-z]{2} [0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT"
            obsolete = r"[A-Z][a-z]+, [0-9]{2}-[A-Z][a-z]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT"
            asctime = r"[A-Z][a-z]{2} [A-Z][a-z]{2} [ 0-9][0-9] [0-9]{2}:[0-9]{2}:[0-9]{2} [0-9]{4}"
            require(re.fullmatch(f"(?:{imf}|{obsolete}|{asctime})", text) is not None, "RETRY_DATE_FORMAT")
            until = parsedate_to_datetime(text)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)  # HTTP asctime is GMT by definition
            # RFC 9110 obsolete two-digit years >50 years ahead mean past century.
            if re.fullmatch(obsolete, text) and until.year > at.year + 50:
                until = until.replace(year=until.year - 100)
        result["retry_not_before"] = max(at, until.astimezone(timezone.utc)).isoformat()
    except (ValueError, TypeError, OverflowError):
        result["retry_manual_review_required"] = True
    return result


def checkpoint_lifetime(start: dict, checkpoint: dict, terminal: dict) -> None:
    require(utc(start["started_at"]) <= utc(checkpoint["generated_at"]) <= utc(terminal["finished_at"]),
            "RESUME_CHECKPOINT_OUTSIDE_PARENT_LIFETIME")


def enforce_retry(terminal: dict, *, as_of: str) -> None:
    require(terminal.get("retry_manual_review_required", False) is False,
            "RESUME_RETRY_MANUAL_REVIEW_REQUIRED")
    if terminal.get("retry_not_before") is not None:
        require(utc(terminal["retry_not_before"]) <= utc(as_of), "RESUME_RETRY_AFTER_NOT_REACHED")


class DriveReferences:
    """Resolve each parent by ID and fail on duplicate names or shortcuts.

    lsf/name-based lookup cannot distinguish Google's same-name objects.
    lsjson provides IDs; small metadata files are fetched with backend copyid.
    Single writer remains required. Before/after listings detect races, not a
    transactional Drive lock. Content hashes remain the byte authority.
    """
    def __init__(self, call, root_id: str):
        self.call = call
        self.root_id = self.object_id(root_id)

    @staticmethod
    def object_id(value: str) -> str:
        require(type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value) is not None,
                "DRIVE_OBJECT_ID_REQUIRED")
        return value

    def ref(self, object_id: str) -> str:
        return "gdrive,root_folder_id=" + self.object_id(object_id) + ":"

    def children(self, folder_id: str) -> dict[str, dict]:
        raw = self.call("lsjson", self.ref(folder_id))
        require(type(raw) is bytes and len(raw) <= 8 * 1024 * 1024, "DRIVE_ID_LIST_BUDGET")
        rows = json_load(raw)
        require(type(rows) is list and len(rows) <= 2001, "DRIVE_ID_LIST_COUNT")
        names, ids, result = set(), set(), {}
        for row in rows:
            require(type(row) is dict, "DRIVE_ID_LIST_ROW")
            name = safe_rel(row.get("Name"))
            require("/" not in name and row.get("Path") == name, "DRIVE_ID_LIST_PATH")
            oid = self.object_id(row.get("ID"))
            require(row.get("OrigID", oid) in (None, "", oid), "DRIVE_SHORTCUT_NOT_ALLOWED")
            require(row.get("MimeType") != "application/vnd.google-apps.shortcut", "DRIVE_SHORTCUT_NOT_ALLOWED")
            require(type(row.get("IsDir")) is bool, "DRIVE_ID_LIST_TYPE")
            require(name.casefold() not in names and oid not in ids, "DRIVE_DUPLICATE_NAME_OR_ID")
            names.add(name.casefold()); ids.add(oid); result[name] = row
        return result

    def directory(self, relative: str) -> str:
        oid = self.root_id
        if relative:
            for part in safe_rel(relative.rstrip("/")).split("/"):
                row = self.children(oid).get(part)
                require(row is not None and row["IsDir"] is True, "DRIVE_DIRECTORY_MISSING")
                oid = row["ID"]
        return oid

    def read_child(self, parent_id: str, name: str, *, expected_id: str | None = None) -> bytes:
        require("/" not in safe_rel(name), "DRIVE_METADATA_NAME")
        entry = self.children(parent_id).get(name)
        require(entry is not None and entry["IsDir"] is False, "DRIVE_METADATA_FILE_MISSING")
        require(type(entry.get("Size")) is int and 0 <= entry["Size"] <= 16 * 1024 * 1024,
                "DRIVE_METADATA_SIZE")
        if expected_id is not None:
            require(entry["ID"] == expected_id, "DRIVE_METADATA_ID_MISMATCH")
        with tempfile.TemporaryDirectory(prefix="news-id-read-") as tmp:
            target = Path(tmp) / "metadata.bin"
            self.call("backend", "copyid", self.ref(parent_id), entry["ID"], str(target),
                      "--immutable", "--max-transfer", "16M")
            raw = read_bounded(target, 16 * 1024 * 1024)
        require(len(raw) == entry["Size"], "DRIVE_METADATA_SIZE_CHANGED")
        after = self.children(parent_id).get(name)
        require(after == entry, "DRIVE_METADATA_ID_CHANGED_DURING_READ")
        return raw

    def read_path(self, path: str, *, expected_id: str | None = None) -> bytes:
        require(type(path) is str and path.startswith("gdrive:"), "DRIVE_METADATA_SCOPE")
        parts = safe_rel(path[len("gdrive:"):]).split("/")
        parent = self.directory("/".join(parts[:-1]))
        return self.read_child(parent, parts[-1], expected_id=expected_id)
