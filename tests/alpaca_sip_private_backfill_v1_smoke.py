"""Offline and no-network controls for private Alpaca historical research capture."""
import io
import gzip
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json
import unittest
from unittest.mock import patch
import zipfile

from tools import alpaca_sip_private_backfill_v1 as cap
from tools.twelve_private_capture import Refused


def bar(t="2016-01-04T05:00:00Z", c=10.5):
    return {"t": t, "o": 10.0, "h": 11.0, "l": 9.0, "c": c, "v": 100}


class PrivateHistoryTests(unittest.TestCase):
    def test_cohort_frozen_seed_research_proxy(self):
        names = cap.cohort(cap.SEED.read_bytes())
        self.assertGreaterEqual(len(names), 900)
        self.assertLessEqual(len(names), 1500)
        self.assertEqual(names, sorted(set(names)))
        self.assertIn("AAPL", names)
        self.assertIn("MSFT", names)
        self.assertIn("NVDA", names)

    def test_raw_split_payload_pagination(self):
        responses = [
            json.dumps({"bars": {"AAPL": [bar()]}, "next_page_token": "next"}).encode(),
            json.dumps({"bars": {"AAPL": [bar("2016-01-05T05:00:00Z")]},
                        "next_page_token": None}).encode(),
        ]
        urls = []
        def get(url, **kw):
            urls.append(url)
            self.assertIn("APCA-API-KEY-ID", kw["headers"])
            self.assertEqual(kw["credentials"], ("key", "secret"))
            return responses.pop(0)
        members, grouped, pages = cap.request_pages(
            ["AAPL"], "raw", "2016-01-04", "2016-01-06",
            "key", "secret", get=get, pause=lambda _: None,
        )
        self.assertEqual(len(pages), 2)
        self.assertEqual(len(grouped["AAPL"]), 2)
        self.assertEqual(len(members), 2)
        self.assertIn("feed=sip", urls[0])
        self.assertIn("adjustment=raw", urls[0])
        self.assertIn("page_token=next", urls[1])
        self.assertNotIn("key", urls[0])

    def test_escaped_credential_refused_without_persist(self):
        payload = b'{"bars":{"AAPL":[]},"key":"\\u0073ecret"}'
        with self.assertRaisesRegex(Refused, "^CREDENTIAL_ECHO$"):
            cap.request_pages(["AAPL"], "raw", "2016-01-04",
                              "2016-01-06", "key", "secret",
                              get=lambda *a, **kw: payload,
                              pause=lambda _: None)

    def test_duplicate_session_rejected(self):
        with self.assertRaisesRegex(Refused, "^DUPLICATE_SESSION$"):
            cap.normalize([bar(), bar()], "AAPL", "raw",
                          "2016-01-04", "2016-01-06")

    def test_invalid_price_and_clock_block(self):
        with self.assertRaisesRegex(Refused, "^BAR_VALUE$"):
            cap.normalize([bar(c=float("nan"))], "AAPL", "raw",
                          "2016-01-04", "2016-01-06")
        with self.assertRaisesRegex(Refused, "^BAR_TIMESTAMP$"):
            cap.normalize([bar(t="2016-01-04T05:00:00")], "AAPL", "raw",
                          "2016-01-04", "2016-01-06")

    def test_no_equity_fill_for_missing_symbol(self):
        payload = json.dumps({"bars": {"AAPL": [bar()]},
                              "next_page_token": None}).encode()
        _, grouped, _ = cap.request_pages(
            ["AAPL", "ASML"], "raw", "2016-01-04", "2016-01-06",
            "key", "secret", get=lambda *a, **kw: payload,
            pause=lambda _: None,
        )
        self.assertEqual(len(grouped["AAPL"]), 1)
        self.assertEqual(grouped["ASML"], [])

    def test_resume_requires_exact_ref_hash(self):
        fake = object()
        with self.assertRaisesRegex(Refused, "^RESUME_PAIR$"):
            cap.resume_state(fake, "folder", "some_id", "",
                             "a" * 64, "2016-01-04", "2026-10-10")

    def test_pack_is_deterministic_and_member_bounded(self):
        a = cap.encoded({"schema": "a"})
        b = cap.zip_bytes({"capture.json": a})
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            self.assertEqual(z.namelist(), ["capture.json"])
            self.assertEqual(z.read("capture.json"), a)
        with self.assertRaisesRegex(Refused, "^PACK_MEMBER$"):
            cap.zip_bytes({"../../escape": b"x"})

    def test_no_unapproved_dispatch(self):
        args = type("Args", (), dict(
            start="2016-01-04", end="2026-10-10",
            max_new_symbols=4, private_root_folder_id="root",
            private_data_folder_id="data", resume_file_id="",
            resume_sha256="",
        ))()
        with patch.dict("os.environ", {"A1_PRIVATE_RESEARCH_AUTHORIZED": "false"}, clear=True):
            with self.assertRaisesRegex(Refused, "^USER_AUTHORIZATION_MISSING$"):
                cap.run(args)

    def test_source_identity_and_admission_separate(self):
        self.assertEqual(cap.SOURCE, "ALPACA_STOCK_BARS_V2_HISTORICAL_SIP")
        self.assertEqual(cap.MIN_START, "2016-01-04")
        self.assertEqual(cap.GROUP_SIZE, 4)
        self.assertNotIn("paper", cap.URL.lower())
        self.assertTrue(cap.SEED.name.endswith(".csv"))



class FakePrivateDrive:
    token = "fake-token"
    folder = "private_folder_123456"
    def __init__(self):
        self.objects, self.names, self.write_count = {}, {}, 0
    def check(self, file_id, parent=None, folder=False):
        if file_id not in self.objects or (parent and parent != self.folder):
            raise Refused("MISSING_OBJECT")
    def read(self, file_id, limit=16_000_000):
        self.check(file_id)
        raw = self.objects[file_id]
        if len(raw) > limit:
            raise Refused("OVERSIZE_OBJECT")
        return raw
    def request(self, url, **kwargs):
        q = parse_qs(urlparse(url).query)["q"][0]
        name = re.search(r"name = '([^']+)'", q).group(1)
        return cap.encoded({"files": [
            {"id": fid, "name": name} for fid, n in self.names.items() if n == name]})
    def write(self, folder_id, raw, extension):
        if folder_id != self.folder:
            raise Refused("INVALID_FOLDER")
        self.write_count += 1
        fid = "private_object_" + str(self.write_count).zfill(6)
        self.objects[fid], self.names[fid] = raw, cap.digest(raw) + extension
        return {"file_id": fid, "sha256": cap.digest(raw), "bytes": len(raw)}


def saved_checkpoint(drive, names, completed, previous):
    raw = cap.persist_object(drive, drive.folder,
                             cap.zip_bytes({"capture.json": b'{}'}), ".zip")
    norm = cap.persist_object(drive, drive.folder,
                              gzip.compress(b'{}\n', mtime=0), ".jsonl.gz")
    rec = cap.persist_object(drive, drive.folder, cap.encoded({
        "schema": cap.SCHEMA, "scope": "PRIVATE_RESEARCH_ONLY", "source": cap.SOURCE,
        "seed_sha256": "a" * 64, "start": cap.MIN_START, "end": "2026-10-10",
        "source_admission": False, "readback_verified": True, "raw_object": raw,
        "normalized_object": norm, "symbols": names,
        "collected": names, "no_bars": []}), ".json")
    return cap.persist_object(drive, drive.folder, cap.encoded({
        "schema": cap.SCHEMA, "state": "PRIVATE_RESEARCH_ONLY",
        "source": cap.SOURCE, "seed_sha256": "a" * 64,
        "start": cap.MIN_START, "end": "2026-10-10", "completed": completed,
        "last_objects": [raw, norm, rec], "last_collected": names,
        "last_no_bars": [], "previous_checkpoint": previous,
        "historical_identity_verified": False, "pit_verified": False,
        "source_admission": False}), ".json")


class CorrectionTests(unittest.TestCase):
    def test_shell_inputs_protected_and_rclone_exported(self):
        yml = (Path(__file__).resolve().parents[1] /
               ".github/workflows/alpaca_sip_private_backfill_v1.yml").read_text()
        self.assertIn('>> "$GITHUB_ENV"', yml)
        self.assertIn('--private-root-folder-id "$INPUT_PRIVATE_ROOT_FOLDER_ID"', yml)
        self.assertIn('--resume-sha256 "$INPUT_RESUME_SHA256"', yml)
        capture = yml.rsplit("      - name: Collect immutable owner-only Alpaca history", 1)[1]
        self.assertNotIn("$" + "{{ inputs.", capture)

    def test_dependency_changes_trigger_and_registered_runner(self):
        root = Path(__file__).resolve().parents[1]
        yml = (root / ".github/workflows/alpaca_sip_private_backfill_v1.yml").read_text()
        for dep in ("tools/twelve_private_capture.py",
                    "tools/configure_macro_research_drive.py",
                    "tools/macro_history_sources.py", "tests/api_credentials_check_smoke.py"):
            self.assertIn("'" + dep + "'", yml)
        entry = (root / "tests/api_credentials_check_smoke.py").read_text()
        self.assertIn("alpaca_sip_private_backfill_v1_smoke.py", entry)

    def test_exclusive_end_maps_to_inclusive_api_query(self):
        urls = []
        cap.request_pages(["AAPL"], "raw", "2016-01-04", "2016-01-06",
                          "key", "secret", get=lambda url, **kw:
                          (urls.append(url) or cap.encoded({"bars": {}, "next_page_token": None})),
                          pause=lambda _: None)
        q = parse_qs(urlparse(urls[0]).query)
        self.assertEqual(q["start"], ["2016-01-04T00:00:00Z"])
        self.assertEqual(q["end"], ["2016-01-05T23:59:59Z"])
        with self.assertRaisesRegex(Refused, "^BAR_RANGE$"):
            cap.normalize([bar("2016-01-06T05:00:00Z")], "AAPL", "raw",
                          "2016-01-04", "2016-01-06")

    def test_exact_source_bytes_deduplicated(self):
        drive = FakePrivateDrive()
        raw = b'{"sample":"safe"}\n'
        a = cap.persist_object(drive, drive.folder, raw, ".json")
        self.assertEqual(a, cap.persist_object(drive, drive.folder, raw, ".json"))
        self.assertEqual(drive.write_count, 1)
        drive.objects[a["file_id"]] = b"corrupt"
        with self.assertRaisesRegex(Refused, "^STORAGE_CONTENT_CONFLICT$"):
            cap.persist_object(drive, drive.folder, raw, ".json")

    def test_full_chain_rejects_deleted_ancestor(self):
        drive = FakePrivateDrive()
        first = saved_checkpoint(drive, ["AAPL"], ["AAPL"], None)
        second = saved_checkpoint(drive, ["MSFT"], ["AAPL", "MSFT"], first)
        args = (drive, drive.folder, second["file_id"], second["sha256"],
                "a" * 64, "2016-01-04", "2026-10-10")
        self.assertEqual(cap.resume_state(*args)[0], ["AAPL", "MSFT"])
        prior = cap.decode(drive.read(first["file_id"]))
        del drive.objects[prior["last_objects"][0]["file_id"]]
        with self.assertRaises(Refused):
            cap.resume_state(*args)

    def test_checkpoint_omitted_chain_fails_closed(self):
        drive = FakePrivateDrive()
        invalid = saved_checkpoint(drive, ["AAPL"], ["MSFT", "AAPL"], None)
        with self.assertRaisesRegex(Refused, "^RESUME_CHAIN_TRUNCATED$"):
            cap.resume_state(drive, drive.folder, invalid["file_id"],
                             invalid["sha256"], "a" * 64,
                             "2016-01-04", "2026-10-10")

    def test_archive_bytes_deterministic(self):
        members = {"capture.json": cap.encoded({"symbols": ["AAPL"]})}
        self.assertEqual(cap.zip_bytes(members), cap.zip_bytes(members))


if __name__ == "__main__":
    unittest.main()
