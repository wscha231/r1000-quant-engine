"""Offline and no-network controls for private Alpaca historical research capture."""
import io
import contextlib
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


def fixture_collect(args):
    # Exercise the original parser/storage invariants with explicitly injected
    # fixture transport. The public run/CLI now requires campaign control.
    return cap._collect(args, drive_factory=cap.OwnerDrive)


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
            resume_clean(fake, "folder", "some_id", "",
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
                fixture_collect(args)

    def test_source_identity_and_admission_separate(self):
        self.assertEqual(cap.SOURCE, "ALPACA_STOCK_BARS_V2_HISTORICAL_SIP")
        self.assertEqual(cap.MIN_START, "2016-01-04")
        self.assertEqual(cap.GROUP_SIZE, 4)
        self.assertNotIn("paper", cap.URL.lower())
        self.assertTrue(cap.SEED.name.endswith(".csv"))



class FakePrivateDrive:
    root_id = "private_root_123456"
    token = "fake-token"
    folder = "private_folder_123456"
    def __init__(self):
        self.objects, self.names, self.write_count = {}, {}, 0
    def check(self, file_id, parent=None, folder=False):
        if file_id == self.folder and parent == self.root_id:
            return
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


def saved_checkpoint(drive, names, completed, previous,
                     bad_original=False, bad_normalized=False,
                     seed_sha=None, source_sha="b" * 40):
    """Realistically shaped SHA-pinned two-basis archive for resume tests."""
    seed_sha = seed_sha or "a" * 64
    start, end = cap.MIN_START, "2026-10-10"
    response = cap.encoded({
        "bars": {name: [bar()] for name in names},
        "next_page_token": None,
    })
    member = cap.digest(response) + ".json"
    pages = [
        {"member": member, "sha256": cap.digest(response),
         "bytes": len(response), "page": 0, "symbols": names,
         "adjustment": adjustment}
        for adjustment in ("raw", "split")
    ]
    manifest = {
        "schema": cap.SCHEMA, "source": cap.SOURCE,
        "symbols": names, "collected": names, "no_bars": [],
        "seed_sha256": seed_sha, "source_sha": source_sha,
        "start": start, "end": end, "asof": cap.mapping_asof(end),
        "pages": pages,
        "raw_adjustments": ["raw", "split"],
        "pit_verified": False, "historical_identity_verified": False,
        "commercial_use_authorized": False,
        "source_admission": False,
    }
    raw_archive = cap.zip_bytes({
        member: response,
        "capture.json": cap.encoded(manifest) if not bad_original else b"{}",
    })
    raw = cap.persist_object(drive, drive.folder, raw_archive, ".zip")
    rows = []
    for name in names:
        for adjustment in ("raw", "split"):
            rows.extend(cap.normalize([bar()], name, adjustment, start, end))
    compressed = gzip.compress(
        b"".join(cap.encoded(row) for row in rows)
        if not bad_normalized else b'{}\n',
        mtime=0,
    )
    norm = cap.persist_object(drive, drive.folder, compressed, ".jsonl.gz")
    receipt = {
        "schema": cap.SCHEMA, "scope": "PRIVATE_RESEARCH_ONLY",
        "source": cap.SOURCE, "seed_sha256": seed_sha,
        "source_sha": source_sha, "start": start, "end": end,
        "asof": cap.mapping_asof(end),
        "source_admission": False, "readback_verified": True,
        "pit_verified": False, "historical_identity_verified": False,
        "commercial_use_authorized": False,
        "raw_object": raw, "normalized_object": norm,
        "symbols": names, "collected": names, "no_bars": [],
        "pages": 2, "rows": len(rows),
    }
    rec = cap.persist_object(drive, drive.folder, cap.encoded(receipt), ".json")
    state = {
        "schema": cap.SCHEMA, "state": "PRIVATE_RESEARCH_ONLY",
        "source": cap.SOURCE, "seed_sha256": seed_sha,
        "source_sha": source_sha,
        "start": start, "end": end, "asof": cap.mapping_asof(end),
        "examined": completed, "completed": completed, "held": [],
        "last_status": "VERIFIED_RAW_SPLIT", "last_held": [],
        "last_objects": [raw, norm, rec], "last_collected": names,
        "last_no_bars": [], "previous_checkpoint": previous,
        "historical_identity_verified": False, "pit_verified": False,
        "source_admission": False,
        "commercial_use_authorized": False,
    }
    return cap.persist_object(drive, drive.folder, cap.encoded(state), ".json")


def resume_clean(*args):
    """Backwards-compatible assertion for verified-only test fixtures."""
    examined, completed, held, ref = cap.resume_state(*args)
    if examined != completed or held:
        raise AssertionError("expected verified-only checkpoint")
    return completed, ref


def held_checkpoint(drive, marker_source="b" * 40):
    marker = {
        "schema": cap.SCHEMA, "scope": "PRIVATE_RESEARCH_ONLY",
        "status": "HELD_BAR_VALUE", "reason": "BAR_VALUE",
        "source": cap.SOURCE, "source_sha": marker_source,
        "seed_sha256": "a" * 64, "symbols": ["AAPL"],
        "start": cap.MIN_START, "end": "2026-10-10", "asof": "2026-10-09",
        "original_price_bytes_retained": False,
        "source_admission": False, "pit_verified": False,
        "historical_identity_verified": False, "commercial_use_authorized": False,
    }
    marker_ref = cap.persist_object(drive, drive.folder, cap.encoded(marker), ".json")
    state = dict(marker, state="PRIVATE_RESEARCH_ONLY", source_sha="b" * 40,
                 examined=["AAPL"], completed=[], held=["AAPL"],
                 last_status="HELD_BAR_VALUE", last_objects=[marker_ref],
                 previous_checkpoint=None, last_collected=[], last_no_bars=[],
                 last_held=["AAPL"])
    return cap.persist_object(drive, drive.folder, cap.encoded(state), ".json")


def rebind_verified(drive, ref, edits):
    """Append forged objects with every dependent hash and byte count refreshed."""
    state = cap.decode(drive.read(ref["file_id"]))
    raw_ref, _, receipt_ref = state["last_objects"]
    receipt = cap.decode(drive.read(receipt_ref["file_id"]))
    with zipfile.ZipFile(io.BytesIO(drive.read(raw_ref["file_id"]))) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = cap.decode(members["capture.json"])
    for target, changes in edits.items():
        obj = {"manifest": manifest, "receipt": receipt, "checkpoint": state}[target]
        for key, value in changes.items():
            if value is MISSING:
                obj.pop(key, None)
            else:
                obj[key] = value
    members["capture.json"] = cap.encoded(manifest)
    raw_ref = cap.persist_object(drive, drive.folder, cap.zip_bytes(members), ".zip")
    state["last_objects"][0] = receipt["raw_object"] = raw_ref
    state["last_objects"][2] = cap.persist_object(
        drive, drive.folder, cap.encoded(receipt), ".json")
    return cap.persist_object(drive, drive.folder, cap.encoded(state), ".json")


MISSING = object()


class CorrectionTests(unittest.TestCase):
    def test_rehashed_pagination_cycles_and_page_budgets(self):
        # Each adjustment can legitimately reuse the other's token values.
        cases = ((None, 3, 3), ("raw", 3, 3), ("split", 3, 3),
                 (None, cap.MAX_PAGES, cap.MAX_PAGES),
                 (None, cap.MAX_PAGES + 1, 1),
                 (None, 1, cap.MAX_PAGES + 1))
        for repeated_basis, raw_pages, split_pages in cases:
            with self.subTest(repeated_basis=repeated_basis,
                              raw_pages=raw_pages, split_pages=split_pages):
                drive = FakePrivateDrive()
                original = saved_checkpoint(drive, ["AAPL"], ["AAPL"], None)
                prior_bytes = dict(drive.objects)
                state = cap.decode(drive.read(original["file_id"]))
                receipt = cap.decode(drive.read(state["last_objects"][2]["file_id"]))
                with zipfile.ZipFile(io.BytesIO(drive.read(state["last_objects"][0]["file_id"]))) as archive:
                    manifest = cap.decode(archive.read("capture.json"))
                members, pages = {}, []
                for basis, page_count in (("raw", raw_pages), ("split", split_pages)):
                    tokens = ["next-" + str(i + 1) for i in range(page_count - 1)] + [None]
                    if basis == repeated_basis:
                        tokens[1] = tokens[0]
                    for index, token in enumerate(tokens):
                        payload = cap.encoded({
                            "bars": {"AAPL": [bar()]} if index == 0 else {},
                            "next_page_token": token,
                        })
                        member = cap.digest(payload) + ".json"
                        members[member] = payload
                        pages.append({"member": member, "sha256": cap.digest(payload),
                                      "bytes": len(payload), "page": index,
                                      "symbols": ["AAPL"], "adjustment": basis})
                manifest["pages"] = pages
                members["capture.json"] = cap.encoded(manifest)
                raw_ref = cap.persist_object(drive, drive.folder, cap.zip_bytes(members), ".zip")
                state["last_objects"][0] = receipt["raw_object"] = raw_ref
                receipt["pages"] = len(pages)
                state["last_objects"][2] = cap.persist_object(
                    drive, drive.folder, cap.encoded(receipt), ".json")
                rebound = cap.persist_object(drive, drive.folder, cap.encoded(state), ".json")
                args = (drive, drive.folder, rebound["file_id"], rebound["sha256"],
                        "a" * 64, cap.MIN_START, "2026-10-10")
                if repeated_basis is None and max(raw_pages, split_pages) <= cap.MAX_PAGES:
                    self.assertEqual(resume_clean(*args)[0], ["AAPL"])
                else:
                    with self.assertRaises(Refused):
                        cap.resume_state(*args)
                self.assertTrue(all(drive.objects[k] == v for k, v in prior_bytes.items()))

    def test_fully_rehashed_unsupported_authority_is_refused(self):
        flags = ("pit_verified", "historical_identity_verified",
                 "commercial_use_authorized", "source_admission")
        for target in ("manifest", "receipt", "checkpoint", "all", "held"):
            for flag in flags:
                for value in (True, 1, 0, None, "false", MISSING):
                    with self.subTest(target=target, flag=flag, value=value):
                        drive = FakePrivateDrive()
                        original = (held_checkpoint(drive) if target == "held" else
                                    saved_checkpoint(drive, ["AAPL"], ["AAPL"], None))
                        prior_bytes = dict(drive.objects)
                        # The untouched positive control must restore first.
                        cap.resume_state(drive, drive.folder, original["file_id"],
                                         original["sha256"], "a" * 64,
                                         cap.MIN_START, "2026-10-10")
                        if target == "held":
                            state = cap.decode(drive.read(original["file_id"]))
                            marker = cap.decode(drive.read(state["last_objects"][0]["file_id"]))
                            if value is MISSING:
                                marker.pop(flag)
                            else:
                                marker[flag] = value
                            state["last_objects"] = [cap.persist_object(
                                drive, drive.folder, cap.encoded(marker), ".json")]
                            forged = cap.persist_object(drive, drive.folder,
                                                        cap.encoded(state), ".json")
                        else:
                            targets = ("manifest", "receipt", "checkpoint") if target == "all" else (target,)
                            forged = rebind_verified(drive, original,
                                                     {t: {flag: value} for t in targets})
                        with self.assertRaises(Refused):
                            cap.resume_state(drive, drive.folder, forged["file_id"],
                                             forged["sha256"], "a" * 64,
                                             cap.MIN_START, "2026-10-10")
                        self.assertTrue(all(drive.objects[k] == v for k, v in prior_bytes.items()))

    def test_rehashed_receipt_revision_must_match_its_checkpoint(self):
        for kind in ("held", "verified"):
            for source in ("c" * 40, "", None, "z" * 40, MISSING):
                with self.subTest(kind=kind, source=source):
                    drive = FakePrivateDrive()
                    if kind == "held":
                        ref = held_checkpoint(drive)
                        state = cap.decode(drive.read(ref["file_id"]))
                        marker = cap.decode(drive.read(state["last_objects"][0]["file_id"]))
                        if source is MISSING:
                            marker.pop("source_sha")
                        else:
                            marker["source_sha"] = source
                        state["last_objects"] = [cap.persist_object(
                            drive, drive.folder, cap.encoded(marker), ".json")]
                        forged = cap.persist_object(drive, drive.folder, cap.encoded(state), ".json")
                    else:
                        ref = saved_checkpoint(drive, ["AAPL"], ["AAPL"], None)
                        forged = rebind_verified(drive, ref, {
                            "manifest": {"source_sha": source},
                            "receipt": {"source_sha": source},
                        })
                    with patch.dict("os.environ", {"GITHUB_SHA": "d" * 40}):
                        cap.resume_state(drive, drive.folder, ref["file_id"],
                                         ref["sha256"], "a" * 64,
                                         cap.MIN_START, "2026-10-10")
                    with self.assertRaises(Refused):
                        cap.resume_state(drive, drive.folder, forged["file_id"],
                                         forged["sha256"], "a" * 64,
                                         cap.MIN_START, "2026-10-10")

    def test_missing_or_invalid_execution_sha_refuses_before_io(self):
        env = {
            "A1_PRIVATE_RESEARCH_AUTHORIZED": "true",
            "ALPACA_NONCOMMERCIAL_ACKNOWLEDGED": "true",
            "GITHUB_REPOSITORY": cap.REPOSITORY, "GITHUB_REF": "refs/heads/master",
            "ALPACA_API_KEY": "dummy-key", "ALPACA_API_SECRET": "dummy-secret",
        }
        for source in (MISSING, "", "short", "z" * 40, "a" * 39,
                       "a" * 41, "A" * 40, "a" * 40 + "\n"):
            with self.subTest(source=source):
                current = dict(env)
                if source is not MISSING:
                    current["GITHUB_SHA"] = source
                with patch.dict("os.environ", current, clear=True), \
                     patch.object(Path, "read_bytes") as seed_read, \
                     patch.object(cap, "OwnerDrive") as drive, \
                     patch.object(cap, "request_pages") as provider:
                    with self.assertRaisesRegex(Refused, "^SOURCE_SHA$"):
                        fixture_collect(object())
                    seed_read.assert_not_called()
                    drive.assert_not_called()
                    provider.assert_not_called()

    def test_shell_inputs_protected_and_no_opaque_campaign_bootstrap(self):
        yml = (Path(__file__).resolve().parents[1] /
               ".github/workflows/alpaca_sip_private_backfill_v1.yml").read_text()
        self.assertNotIn('Install reviewed rclone', yml)
        self.assertIn('--campaign-control-file "$RUNNER_TEMP/campaign_control.json"', yml)
        self.assertIn('--private-root-folder-id "$INPUT_PRIVATE_ROOT_FOLDER_ID"', yml)
        self.assertIn('--resume-sha256 "$INPUT_RESUME_SHA256"', yml)
        capture = yml.rsplit("      - name: Collect immutable owner-only Alpaca history", 1)[1]
        self.assertNotIn("$" + "{{ inputs.", capture)
        pre_capture = yml.split("\n  capture:\n", 1)[1].split("\n    steps:\n", 1)[0]
        self.assertNotIn("secrets.ALPACA_API_KEY", pre_capture)
        self.assertNotIn("secrets.ALPACA_API_SECRET", pre_capture)
        self.assertNotIn("secrets.RCLONE_CONFIG_GDRIVE", pre_capture)
        for name in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "MACRO_DRIVE_CONFIG"):
            self.assertIn("          " + name + ":", capture)

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
        self.assertEqual(resume_clean(*args)[0], ["AAPL", "MSFT"])
        prior = cap.decode(drive.read(first["file_id"]))
        del drive.objects[prior["last_objects"][0]["file_id"]]
        with self.assertRaises(Refused):
            resume_clean(*args)

    def test_checkpoint_omitted_chain_fails_closed(self):
        drive = FakePrivateDrive()
        invalid = saved_checkpoint(drive, ["AAPL"], ["MSFT", "AAPL"], None)
        with self.assertRaisesRegex(Refused, "^RESUME_CHAIN_TRUNCATED$"):
            resume_clean(drive, drive.folder, invalid["file_id"],
                             invalid["sha256"], "a" * 64,
                             "2016-01-04", "2026-10-10")

    def test_symbol_mapping_asof_is_frozen_from_exclusive_end(self):
        urls = []
        cap.request_pages(["AAPL"], "raw", "2016-01-04", "2016-01-06",
                          "key", "secret", get=lambda url, **kwargs:
                          (urls.append(url) or cap.encoded({
                              "bars": {"AAPL": [bar()]},
                              "next_page_token": None,
                          })), pause=lambda _: None)
        query = parse_qs(urlparse(urls[0]).query)
        self.assertEqual(query["asof"], ["2016-01-05"])
        self.assertEqual(cap.mapping_asof("2026-10-10"), "2026-10-09")
        drive = FakePrivateDrive()
        checkpoint = saved_checkpoint(drive, ["AAPL"], ["AAPL"], None)
        state = cap.decode(drive.read(checkpoint["file_id"]))
        receipt = cap.decode(drive.read(state["last_objects"][2]["file_id"]))
        self.assertEqual(state["asof"], "2026-10-09")
        self.assertEqual(receipt["asof"], "2026-10-09")
        with self.assertRaisesRegex(Refused, "^RESUME_CONTEXT$"):
            resume_clean(drive, drive.folder, checkpoint["file_id"],
                         checkpoint["sha256"], "a" * 64, "2016-01-04",
                         "2026-10-11")

    def test_invalid_numeric_group_is_held_and_next_group_processed(self):
        drive = FakePrivateDrive()
        names = cap.cohort(cap.SEED.read_bytes())
        selected = names[:8]
        args = type("Args", (), dict(
            start=cap.MIN_START, end="2026-10-10",
            max_new_symbols=8, private_root_folder_id=drive.root_id,
            private_data_folder_id=drive.folder, resume_file_id="",
            resume_sha256="",
        ))()
        calls = []
        def fake_capture(drive_arg, folder, group, start, end,
                         key, secret, seed_sha, source_sha):
            calls.append(tuple(group))
            if len(calls) == 1:
                raise Refused("BAR_VALUE")
            cp = saved_checkpoint(drive_arg, group, group, None,
                                  seed_sha=seed_sha, source_sha=source_sha)
            state = cap.decode(drive_arg.read(cp["file_id"]))
            return state["last_objects"], group, [], 2 * len(group)
        env = {
            "A1_PRIVATE_RESEARCH_AUTHORIZED": "true",
            "ALPACA_NONCOMMERCIAL_ACKNOWLEDGED": "true",
            "GITHUB_REPOSITORY": cap.REPOSITORY,
            "GITHUB_REF": "refs/heads/master",
            "GITHUB_SHA": "b" * 40,
            "ALPACA_API_KEY": "dummy-key",
            "ALPACA_API_SECRET": "dummy-secret",
        }
        output = io.StringIO()
        with patch.dict("os.environ", env, clear=True), \
             patch.object(cap, "OwnerDrive", return_value=drive), \
             patch.object(cap, "capture_one_group", side_effect=fake_capture), \
             contextlib.redirect_stdout(output):
            fixture_collect(args)
        report = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(report["status"], "PRIVATE_HISTORY_PARTIAL_HELD")
        self.assertEqual(report["total_examined"], 8)
        self.assertEqual(report["verified_or_no_bar"], 4)
        self.assertEqual(report["total_held_invalid"], 4)
        examined, done, held, ref = cap.resume_state(
            drive, drive.folder, report["checkpoint"]["file_id"],
            report["checkpoint"]["sha256"],
            cap.digest(cap.SEED.read_bytes()),
            cap.MIN_START, "2026-10-10")
        self.assertEqual(examined, selected)
        self.assertEqual(done, selected[4:])
        self.assertEqual(held, selected[:4])
        self.assertEqual(ref, report["checkpoint"])

        # Restart from prior checkpoint: the held group must not repeat.
        args.resume_file_id = ref["file_id"]
        args.resume_sha256 = ref["sha256"]
        args.max_new_symbols = 4
        next_calls = []
        def resumed_capture(*params):
            group = params[2]
            next_calls.append(tuple(group))
            cp = saved_checkpoint(drive, group, group, None,
                                  seed_sha=params[7], source_sha=params[8])
            st = cap.decode(drive.read(cp["file_id"]))
            return st["last_objects"], group, [], 2 * len(group)
        resumed_output = io.StringIO()
        with patch.dict("os.environ", dict(env, GITHUB_SHA="c" * 40), clear=True), \
             patch.object(cap, "OwnerDrive", return_value=drive), \
             patch.object(cap, "capture_one_group", side_effect=resumed_capture), \
             contextlib.redirect_stdout(resumed_output):
            fixture_collect(args)
        self.assertEqual(next_calls, [tuple(names[8:12])])
        next_ref = json.loads(resumed_output.getvalue().splitlines()[-1])["checkpoint"]
        state = cap.decode(drive.read(next_ref["file_id"]))
        self.assertEqual(state["source_sha"], "c" * 40)
        self.assertEqual(cap.resume_state(
            drive, drive.folder, next_ref["file_id"], next_ref["sha256"],
            cap.digest(cap.SEED.read_bytes()), cap.MIN_START, "2026-10-10",
        )[:3], (names[:12], names[4:12], names[:4]))

    def test_quota_refusal_still_fails_without_hold(self):
        drive = FakePrivateDrive()
        args = type("Args", (), dict(
            start=cap.MIN_START, end="2026-10-10",
            max_new_symbols=4, private_root_folder_id=drive.root_id,
            private_data_folder_id=drive.folder, resume_file_id="",
            resume_sha256="",
        ))()
        env = {
            "A1_PRIVATE_RESEARCH_AUTHORIZED": "true",
            "ALPACA_NONCOMMERCIAL_ACKNOWLEDGED": "true",
            "GITHUB_REPOSITORY": cap.REPOSITORY,
            "GITHUB_REF": "refs/heads/master",
            "GITHUB_SHA": "b" * 40,
            "ALPACA_API_KEY": "dummy-key",
            "ALPACA_API_SECRET": "dummy-secret",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch.object(cap, "OwnerDrive", return_value=drive), \
             patch.object(cap, "capture_one_group",
                          side_effect=Refused("RATE_LIMIT")):
            with self.assertRaisesRegex(Refused, "^RATE_LIMIT$"):
                fixture_collect(args)
        self.assertEqual(drive.write_count, 0)

    def test_archive_bytes_deterministic(self):
        members = {"capture.json": cap.encoded({"symbols": ["AAPL"]})}
        self.assertEqual(cap.zip_bytes(members), cap.zip_bytes(members))

    def test_hash_valid_but_semantically_forged_archive_refused(self):
        drive = FakePrivateDrive()
        forged = saved_checkpoint(drive, ["AAPL"], ["AAPL"], None,
                                  bad_original=True)
        with self.assertRaises(Refused):
            resume_clean(drive, drive.folder, forged["file_id"],
                             forged["sha256"], "a" * 64, "2016-01-04",
                             "2026-10-10")

    def test_hash_valid_but_false_normalized_records_refused(self):
        drive = FakePrivateDrive()
        forged = saved_checkpoint(drive, ["AAPL"], ["AAPL"], None,
                                  bad_normalized=True)
        with self.assertRaisesRegex(Refused, "RESUME_NORMALIZED_MISMATCH"):
            resume_clean(drive, drive.folder, forged["file_id"],
                             forged["sha256"], "a" * 64, "2016-01-04",
                             "2026-10-10")

    def test_retry_across_run_ids_reuses_receipt_and_checkpoint_bytes(self):
        drive = FakePrivateDrive()
        count = {"calls": 0}
        def offline_provider(symbols, adjustment, start, end, key, secret):
            count["calls"] += 1
            response = cap.encoded({
                "bars": {name: [bar()] for name in symbols},
                "next_page_token": None,
            })
            member = cap.digest(response) + ".json"
            page = {
                "member": member, "sha256": cap.digest(response),
                "bytes": len(response), "page": 0, "symbols": symbols,
                "adjustment": adjustment,
            }
            return {member: response}, {name: [bar()] for name in symbols}, [page]
        refs = []
        with patch.object(cap, "request_pages", side_effect=offline_provider):
            for run_id in ("attempt-A", "attempt-B"):
                with patch.dict("os.environ", {"GITHUB_RUN_ID": run_id}):
                    objects, accepted, missing, rows = cap.capture_one_group(
                        drive, drive.folder, ["AAPL"], cap.MIN_START,
                        "2026-10-10", "key", "secret", "a" * 64, "b" * 40)
                    refs.append(objects)
        self.assertEqual(refs[0], refs[1])
        self.assertEqual(drive.write_count, 3)
        self.assertEqual(count["calls"], 4)


    def test_resume_checkpoint_reference_keeps_byte_count(self):
        drive = FakePrivateDrive()
        first = saved_checkpoint(drive, ["AAPL"], ["AAPL"], None)
        completed, resumed = resume_clean(
            drive, drive.folder, first["file_id"], first["sha256"],
            "a" * 64, "2016-01-04", "2026-10-10")
        self.assertEqual(completed, ["AAPL"])
        self.assertEqual(resumed, first)
        same_continuous = saved_checkpoint(
            drive, ["MSFT"], ["AAPL", "MSFT"], first)
        same_resumed = saved_checkpoint(
            drive, ["MSFT"], ["AAPL", "MSFT"], resumed)
        self.assertEqual(same_continuous, same_resumed)

    def test_checkpoint_limit_covers_all_valid_single_symbol_batches(self):
        self.assertGreaterEqual(cap.MAX_CHECKPOINT_CHAIN, 1500)
        self.assertLessEqual(cap.MAX_CHECKPOINT_CHAIN, 10000)

    def test_all_missing_group_is_checkpointed_and_restored(self):
        drive = FakePrivateDrive()
        payload = cap.encoded({"bars": {}, "next_page_token": None})
        member = cap.digest(payload) + ".json"

        def only_missing(symbols, adjustment, start, end, key, secret):
            page = {"member": member, "sha256": cap.digest(payload),
                    "bytes": len(payload), "page": 0,
                    "symbols": symbols, "adjustment": adjustment}
            return {member: payload}, {name: [] for name in symbols}, [page]

        with patch.object(cap, "request_pages", side_effect=only_missing):
            objects, collected, absent, rows = cap.capture_one_group(
                drive, drive.folder, ["IPO"], "2016-01-04", "2026-10-10",
                "key", "secret", "a" * 64, "b" * 40)
        self.assertEqual((collected, absent, rows), ([], ["IPO"], 0))
        state = {
            "schema": cap.SCHEMA, "state": "PRIVATE_RESEARCH_ONLY",
            "source": cap.SOURCE, "seed_sha256": "a" * 64,
            "source_sha": "b" * 40,
            "start": "2016-01-04", "end": "2026-10-10",
            "asof": "2026-10-09",
            "examined": ["IPO"], "completed": ["IPO"], "held": [],
            "last_status": "VERIFIED_RAW_SPLIT", "last_held": [],
            "last_objects": objects,
            "last_collected": [], "last_no_bars": ["IPO"],
            "previous_checkpoint": None,
            "historical_identity_verified": False,
            "pit_verified": False, "source_admission": False,
            "commercial_use_authorized": False,
        }
        checkpoint = cap.persist_object(
            drive, drive.folder, cap.encoded(state), ".json")
        completed, ref = resume_clean(
            drive, drive.folder, checkpoint["file_id"], checkpoint["sha256"],
            "a" * 64, "2016-01-04", "2026-10-10")
        self.assertEqual(completed, ["IPO"])
        self.assertEqual(ref, checkpoint)



class ExternalDiscoveryTests(unittest.TestCase):
    def test_ticker_only_bounded_input_preserves_priority_and_legacy_guard(self):
        raw=b'ticker\nUMAC\nTSM\n'
        self.assertEqual(cap.external_cohort(raw),['UMAC','TSM'])
        with self.assertRaises(Refused):cap.cohort(raw)
        for value in (b'ticker\n',b'ticker\nAAPL\nAAPL\n',b'ticker\naapl\n',b'ticker,rank\nAAPL,1\n',
                      b'ticker\n../AAPL\n',b'ticker\nAAPL\n\n',b'\xff',
                      ('ticker\n'+'\n'.join('ZZZ'+str(i) for i in range(501))+'\n').encode()):
            with self.subTest(value=value[:40]),self.assertRaises(Refused):cap.external_cohort(value)

    def test_asset_identity_hash_clock_and_supported_status_are_not_invented(self):
        names=['UMAC'];raw=cap.encoded(dict(id='00000000-0000-0000-0000-000000000001',symbol='UMAC',
                                           exchange='AMEX',status='active',**{'class':'us_equity'}))
        evidence=cap.precheck_assets(names,'key','secret',lambda *a,**kw:raw)
        self.assertTrue(cap.asset_supported(evidence[0]))
        self.assertEqual(cap.asset_record(raw,'UMAC')['exchange'],'AMEX')
        for key,value in [('sha256','0'*64),('symbol','VRTX'),('collected_at_utc','2026-10-17'),('http_status',True)]:
            row=dict(evidence[0]);row[key]=value
            with self.subTest(key=key),self.assertRaises(Refused):cap.verify_asset_evidence([row],names)
        with self.assertRaises(Refused):cap.asset_record(raw,'TSM')
        value=cap.decode(raw);value['id']='-'*36
        with self.assertRaisesRegex(Refused,'EXTERNAL_ASSET_IDENTITY'):
            cap.asset_record(cap.encoded(value),'UMAC')

    def test_external_resume_namespace_and_held_prefix_do_not_recollect(self):
        from types import SimpleNamespace
        drive=FakePrivateDrive();calls=[]
        names=['ZZZAA','ZZZBB','ZZZCC'];raw=('ticker\n'+'\n'.join(names)+'\n').encode()
        scope=dict(task_key='R1000-DISCOVERY-OFFLINE-20261017',namespace='fixture-discovery',input_sha256=cap.digest(raw))
        args=SimpleNamespace(start=cap.MIN_START,end='2026-10-14',max_new_symbols=2,
            private_root_folder_id=drive.root_id,private_data_folder_id=drive.folder,resume_file_id='',resume_sha256='')
        env=dict(A1_PRIVATE_RESEARCH_AUTHORIZED='true',ALPACA_NONCOMMERCIAL_ACKNOWLEDGED='true',
            GITHUB_REPOSITORY=cap.REPOSITORY,GITHUB_REF='refs/heads/master',GITHUB_SHA='b'*40,
            ALPACA_API_KEY='dummy-key',ALPACA_API_SECRET='dummy-secret')
        def get(url,**kw):
            calls.append(url)
            if '/v2/assets/' in url:
                symbol=url.rsplit('/',1)[1]
                if symbol=='ZZZBB':raise Refused('ASSET_NOT_FOUND')
                return cap.encoded(dict(id='00000000-0000-0000-0000-000000000001',symbol=symbol,
                    exchange='NASDAQ',status='active',**{'class':'us_equity'}))
            symbols=parse_qs(urlparse(url).query)['symbols'][0].split(',')
            return cap.encoded(dict(bars={s:[bar()] for s in symbols},next_page_token=None))
        with patch.dict('os.environ',env,clear=True),patch.object(cap.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):
            result=cap._collect(args,drive_factory=lambda *a:drive,get=get,expected_examined=0,
                                external=dict(input_csv=raw.decode(),scope=scope))
            ref=result['checkpoint']
            restored=cap.resume_state(drive,drive.folder,ref['file_id'],ref['sha256'],cap.digest(raw),args.start,args.end,scope=scope)
            self.assertEqual(restored[:3],(names[:2],[names[0]],[names[1]]))
            before=dict(drive.objects);calls.clear()
            args.resume_file_id=ref['file_id'];args.resume_sha256=ref['sha256'];args.max_new_symbols=1
            cap._collect(args,drive_factory=lambda *a:drive,get=get,expected_examined=2,
                         external=dict(input_csv=raw.decode(),scope=scope))
            self.assertTrue(all(drive.objects[k]==v for k,v in before.items()))
            self.assertTrue(all('ZZZAA' not in url and 'ZZZBB' not in url for url in calls))
            for wrong in (None,dict(scope,namespace='other-discovery')):
                with self.assertRaisesRegex(Refused,'RESUME_CONTEXT'):
                    cap.resume_state(drive,drive.folder,ref['file_id'],ref['sha256'],cap.digest(raw),args.start,args.end,scope=wrong)

    def test_external_wrong_input_hash_refuses_before_any_transport(self):
        from types import SimpleNamespace
        env=dict(A1_PRIVATE_RESEARCH_AUTHORIZED='true',ALPACA_NONCOMMERCIAL_ACKNOWLEDGED='true',
            GITHUB_REPOSITORY=cap.REPOSITORY,GITHUB_REF='refs/heads/master',GITHUB_SHA='b'*40,
            ALPACA_API_KEY='dummy-key',ALPACA_API_SECRET='dummy-secret')
        args=SimpleNamespace(start=cap.MIN_START,end='2026-10-14',max_new_symbols=1)
        external=dict(input_csv='ticker\nUMAC\n',scope=dict(task_key='R1000-DISCOVERY-OFFLINE-20261017',
                      namespace='fixture-discovery',input_sha256='0'*64))
        with patch.dict('os.environ',env,clear=True),self.assertRaisesRegex(Refused,'EXTERNAL_COHORT_HASH'):
            cap._collect(args,drive_factory=lambda *a:self.fail('Drive before validation'),
                         get=lambda *a,**kw:self.fail('Provider before validation'),external=external)


class UncertainStorageQuarantineTests(unittest.TestCase):
    """Synthetic source/Drive bytes. This fixture is never a real held receipt."""
    def setUp(self):
        import copy
        from types import SimpleNamespace
        self.drive = FakePrivateDrive()
        self.names = (["ZQ%03d"%i for i in range(76)]+["VLO","MFG","BP","BTI"]+
                      ["SPGI"]+["ZQ%03d"%i for i in range(81,417)])
        self.csv = "ticker\n"+"\n".join(self.names)+"\n"
        self.scope = dict(task_key="R1000-DISCOVERY-EXPANSION-INTAKE-20261017",
                          namespace="top500-20261017",input_sha256=cap.digest(self.csv.encode()))
        self.args = SimpleNamespace(start=cap.MIN_START,end="2026-10-14",max_new_symbols=32,
            private_root_folder_id=self.drive.root_id,private_data_folder_id=self.drive.folder,
            resume_file_id="",resume_sha256="")
        self.env = dict(A1_PRIVATE_RESEARCH_AUTHORIZED="true",ALPACA_NONCOMMERCIAL_ACKNOWLEDGED="true",
            GITHUB_REPOSITORY=cap.REPOSITORY,GITHUB_REF="refs/heads/master",GITHUB_SHA="c"*40,
            GITHUB_RUN_ID="39103855451",ALPACA_API_KEY="fixture-key",ALPACA_API_SECRET="fixture-secret")
        self.calls = []
        self.addCleanup(patch.stopall)
        patch.dict("os.environ",self.env,clear=True).start()
        patch.object(cap.time,"sleep").start()
        pages = cap.request_pages
        patch.object(cap,"request_pages",side_effect=lambda *a,**kw:
            pages(*a,**dict(kw,pause=lambda _:None))).start()
        for count in (32,32,12):
            self.args.max_new_symbols=count
            with contextlib.redirect_stdout(io.StringIO()):
                result=cap._collect(self.args,drive_factory=lambda *a:self.drive,get=self.get,
                    external=dict(input_csv=self.csv,scope=self.scope))
            self.prefix=result["checkpoint"]
            self.args.resume_file_id=self.prefix["file_id"];self.args.resume_sha256=self.prefix["sha256"]
        patch.dict(cap.STORAGE_QUARANTINE,checkpoint_sha256=self.prefix["sha256"],
                   input_sha256=self.scope["input_sha256"]).start()
        self.evidence = dict(copy.deepcopy(cap.STORAGE_QUARANTINE),authorization_sha256="d"*64,
            external_proof_sha256="e"*64,native_settlement_sha256="f"*64,recovery_run_id=39103855451)
        self.originals=dict(self.drive.objects);self.calls.clear()
        self.args.max_new_symbols=4

    def get(self,url,**kw):
        self.calls.append(url)
        if "/v2/assets/" in url:
            symbol=url.rsplit("/",1)[1]
            return cap.encoded(dict(id="00000000-0000-0000-0000-000000000001",symbol=symbol,
                exchange="NYSE",status="active",**{"class":"us_equity"}))
        symbols=parse_qs(urlparse(url).query)["symbols"][0].split(",")
        return cap.encoded(dict(bars={s:[bar()] for s in symbols},next_page_token=None))

    def hold(self,on_group=None):
        with contextlib.redirect_stdout(io.StringIO()):
            result=cap._collect(self.args,drive_factory=lambda *a:self.drive,
                get=lambda *a,**kw:self.fail("Provider I/O for unknown storage"),
                on_group=on_group,expected_examined=76,
                external=dict(input_csv=self.csv,scope=self.scope,storage_quarantine=self.evidence))
        return result["checkpoint"]

    def restore(self,ref):
        return cap.resume_state(self.drive,self.drive.folder,ref["file_id"],ref["sha256"],
                                self.scope["input_sha256"],self.args.start,self.args.end,scope=self.scope)

    def test_marker_and_checkpoint_restore_without_old_pack_or_provider_call(self):
        with patch.object(cap,"capture_one_group",side_effect=AssertionError("old body regeneration")), \
             patch.object(cap.gzip,"compress",side_effect=AssertionError("unknown normalized body regeneration")), \
             patch.object(cap,"precheck_assets",side_effect=AssertionError("asset I/O")):
            ref=self.hold()
        restored=self.restore(ref)
        self.assertEqual(restored[:3],(self.names[:80],self.names[:76],self.names[76:80]))
        self.assertEqual(self.calls,[])
        self.assertTrue(all(self.drive.objects[k]==v for k,v in self.originals.items()))
        additions=[v for k,v in self.drive.objects.items() if k not in self.originals]
        self.assertEqual(len(additions),2)
        state=cap.decode(self.drive.read(ref["file_id"]))
        marker=cap.decode(self.drive.read(state["last_objects"][0]["file_id"]))
        self.assertEqual(marker["status"],"HELD_UNCERTAIN_STORAGE")
        self.assertFalse(marker["uncertain_storage"]["absence_proven"])
        self.assertFalse(marker["uncertain_storage"]["failed_request_body_hash_known"])
        self.assertFalse(marker["source_admission"]);self.assertFalse(marker["original_price_bytes_retained"])
        self.assertEqual(state["last_collected"],[]);self.assertEqual(state["last_no_bars"],[])
        self.assertTrue(all(not raw.startswith((b"PK",b"\x1f\x8b")) for raw in additions))

    def test_next_fixed_group_starts_after_four_held_and_restores_full_chain(self):
        ref=self.hold();self.calls.clear()
        self.args.resume_file_id=ref["file_id"];self.args.resume_sha256=ref["sha256"]
        with contextlib.redirect_stdout(io.StringIO()):
            result=cap._collect(self.args,drive_factory=lambda *a:self.drive,get=self.get,
                expected_examined=80,external=dict(input_csv=self.csv,scope=self.scope))
        examined,done,held,_=self.restore(result["checkpoint"])
        self.assertEqual(examined,self.names[:84]);self.assertEqual(held,self.names[76:80])
        self.assertEqual(done,self.names[:76]+self.names[80:84])
        self.assertTrue(any("/assets/SPGI" in u for u in self.calls))
        self.assertTrue(all(not any(symbol in u for symbol in self.names[76:80]) for u in self.calls))
        self.assertTrue(all(self.drive.objects[k]==v for k,v in self.originals.items()))

    def test_foreign_identity_and_unselected_group_fail_before_new_storage(self):
        import copy
        mutations=(lambda e:e.update(native_run_id=1),lambda e:e.update(owner_sha256="0"*64),
            lambda e:e.update(native_meter_sha256="0"*64),lambda e:e.update(failed_meter_sha256="0"*64),
            lambda e:e.update(checkpoint_sha256="0"*64),lambda e:e.update(symbols=list(reversed(e["symbols"]))),
            lambda e:e.update(absence_proven=True),lambda e:e.update(unknown_storage_bytes_still_charged=0),
            lambda e:e.update(recovery_run_id=True),lambda e:e.update(input_sha256="0"*64))
        original=copy.deepcopy(self.evidence)
        for mutate in mutations:
            self.evidence=copy.deepcopy(original);mutate(self.evidence);before=self.drive.write_count
            with self.subTest(mutate=mutate),self.assertRaises(Refused):self.hold()
            self.assertEqual(self.drive.write_count,before)
        self.evidence=original;self.args.max_new_symbols=5
        with self.assertRaisesRegex(Refused,"STORAGE_QUARANTINE_PREFIX"):self.hold()

    def test_fully_rehashed_marker_or_membership_forgery_is_not_admitted(self):
        import copy
        ref=self.hold();original=cap.decode(self.drive.read(ref["file_id"]))
        marker=cap.decode(self.drive.read(original["last_objects"][0]["file_id"]))
        mutations=(
            lambda m,s:m["uncertain_storage"].update(absence_proven=True),
            lambda m,s:m["uncertain_storage"].update(owner_sha256="0"*64),
            lambda m,s:m.update(source_admission=True),
            lambda m,s:m.update(reason="BAR_VALUE"),
            lambda m,s:m.update(symbols=list(reversed(m["symbols"]))),
            lambda m,s:s.update(last_no_bars=s["last_held"],last_held=[]),
            lambda m,s:s.update(completed=s["examined"],held=[]),
            lambda m,s:s.update(previous_checkpoint=None))
        for mutate in mutations:
            m,s=copy.deepcopy(marker),copy.deepcopy(original);mutate(m,s)
            s["last_objects"]=[cap.persist_object(self.drive,self.drive.folder,cap.encoded(m),".json")]
            bad=cap.persist_object(self.drive,self.drive.folder,cap.encoded(s),".json")
            with self.subTest(mutate=mutate),self.assertRaises(Refused):self.restore(bad)

    def test_checkpoint_write_failure_does_not_advance_or_turn_hold_into_prices(self):
        before=dict(self.drive.objects);write=self.drive.write
        def fail_checkpoint(folder,raw,extension):
            if cap.decode(raw).get("last_status")=="HELD_UNCERTAIN_STORAGE":
                raise Refused("SYNTHETIC_UNKNOWN_NEW_MARKER_POST")
            return write(folder,raw,extension)
        with patch.object(self.drive,"write",side_effect=fail_checkpoint),self.assertRaises(Refused):self.hold()
        self.assertEqual(self.restore(self.prefix)[:3],(self.names[:76],self.names[:76],[]))
        self.assertEqual(self.calls,[])
        self.assertTrue(all(self.drive.objects[k]==v for k,v in before.items()))



class FixedSpyScopeFixtureTests(unittest.TestCase):
    """Real collector/archive/verifier functions over tiny fake vendor bytes."""
    def setUp(self):
        from types import SimpleNamespace
        self.drive, self.calls = FakePrivateDrive(), []
        self.args = SimpleNamespace(start=cap.FIXED_SPY_START, end=cap.FIXED_SPY_END,
            max_new_symbols=1, private_root_folder_id=self.drive.root_id,
            private_data_folder_id=self.drive.folder, resume_file_id="", resume_sha256="")
        self.external = dict(input_csv=cap.FIXED_SPY_INPUT.decode(), scope=cap._fixed_spy_scope())
        self.env = dict(A1_PRIVATE_RESEARCH_AUTHORIZED="true", ALPACA_NONCOMMERCIAL_ACKNOWLEDGED="true",
            GITHUB_REPOSITORY=cap.REPOSITORY, GITHUB_REF="refs/heads/master", GITHUB_SHA="b"*40,
            ALPACA_API_KEY="dummy-key", ALPACA_API_SECRET="dummy-secret")
        self.grid = {basis: [bar("2024-03-01T05:00:00Z"), bar("2026-10-23T04:00:00Z")]
                     for basis in ("raw", "split")}

    def get(self, url, **kwargs):
        self.calls.append(url)
        if "/v2/assets/" in url:
            self.assertTrue(url.endswith("/SPY"))
            return cap.encoded(dict(id="00000000-0000-0000-0000-000000000001", symbol="SPY",
                exchange="ARCA", status="active", **{"class": "us_equity"}))
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["symbols"], ["SPY"])
        self.assertEqual(query["feed"], ["sip"])
        self.assertTrue(query["start"][0].startswith(cap.FIXED_SPY_START))
        self.assertEqual(query["end"], ["2026-10-23T23:59:59Z"])
        return cap.encoded(dict(bars={"SPY": self.grid[query["adjustment"][0]]}, next_page_token=None))

    def collect(self, on_group=None):
        with patch.dict("os.environ", self.env, clear=True), patch.object(cap.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            return cap._collect(self.args, drive_factory=lambda *a: self.drive, get=self.get,
                expected_examined=0, external=self.external, fixed_profile=cap.FIXED_SPY_PROFILE,
                on_group=on_group)

    def test_exact_subject_window_actual_archive_readback_and_explicit_new_genesis(self):
        from tools import alpaca_sip_campaign as campaign
        from types import SimpleNamespace
        meter = SimpleNamespace(identity=dict(fixed_profile=cap.FIXED_SPY_PROFILE,
            cohort_scope=cap._fixed_spy_scope()), checkpoint_sha=cap._fixed_spy_genesis(),
            examined=0, rows=0, states=dict(VALID_COLLECTED=0, VERIFIED_NO_DATA=0, QUARANTINED=0),
            save=lambda: None)
        def verify(drive, state, ref):
            campaign.verify_new_group(drive, drive.folder, state, ref, meter, fixed_spy=True)
        result = self.collect(verify)
        self.assertEqual((len(self.calls), meter.examined, meter.rows), (3, 1, 4))
        self.assertEqual(meter.states, dict(VALID_COLLECTED=1, VERIFIED_NO_DATA=0, QUARANTINED=0))
        state = cap.decode(self.drive.read(result["checkpoint"]["file_id"]))
        self.assertIsNone(state["previous_checkpoint"])
        self.assertEqual((state["start"], state["end"], state["examined"]),
                         (cap.FIXED_SPY_START, cap.FIXED_SPY_END, ["SPY"]))
        self.assertFalse(state["source_admission"])
        self.assertFalse(state["pit_verified"])
        restored = cap.resume_state(self.drive, self.drive.folder, result["checkpoint"]["file_id"],
            result["checkpoint"]["sha256"], cap.digest(cap.FIXED_SPY_INPUT), cap.FIXED_SPY_START,
            cap.FIXED_SPY_END, scope=cap._fixed_spy_scope())
        self.assertEqual(restored[:3], (["SPY"], ["SPY"], []))
        # Four synthetic rows are not asserted as665 observed sessions.
        self.assertEqual(meter.rows, 4)

    def test_scope_changes_refuse_before_provider_or_storage(self):
        for field, value in (("start", cap.MIN_START), ("end", "2026-10-25"), ("max_new_symbols", 2),
                             ("resume_sha256", "a"*64)):
            before = getattr(self.args, field); setattr(self.args, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(Refused, "SPY665_SCOPE"):
                self.collect()
            setattr(self.args, field, before)
        self.external["input_csv"] = "ticker\nMU\n"
        with self.assertRaisesRegex(Refused, "SPY665_SCOPE"): self.collect()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.drive.objects, {})

    def test_unequal_basis_grid_and_out_of_window_price_never_publish(self):
        self.grid["split"] = [bar("2024-03-04T05:00:00Z")]
        with self.assertRaisesRegex(Refused, "RAW_SPLIT_GRID_MISMATCH"): self.collect()
        self.assertEqual(self.drive.objects, {})
        self.calls.clear()
        self.grid["raw"] = self.grid["split"] = [bar("2026-10-24T04:00:00Z")]
        with self.assertRaises(Refused): self.collect()
        self.assertEqual(self.drive.objects, {})

    def test_wrong_window_or_legacy_first_parent_is_not_a_scoped_verified_group(self):
        from tools import alpaca_sip_campaign as campaign
        from types import SimpleNamespace
        result = self.collect()
        state = cap.decode(self.drive.read(result["checkpoint"]["file_id"]))
        def meter(genesis):
            return SimpleNamespace(identity=dict(fixed_profile=cap.FIXED_SPY_PROFILE,
                cohort_scope=cap._fixed_spy_scope()), checkpoint_sha=genesis, examined=0)
        with patch.dict("os.environ", self.env, clear=True):
            with self.assertRaisesRegex(Refused, "CAMPAIGN_CHECKPOINT_CHAIN"):
                campaign.verify_new_group(self.drive, self.drive.folder, state, result["checkpoint"],
                    meter(campaign.external_genesis(cap._fixed_spy_scope())), fixed_spy=True)
            with self.assertRaisesRegex(Refused, "CAMPAIGN_CHECKPOINT_CHAIN"):
                campaign.verify_new_group(self.drive, self.drive.folder, state, result["checkpoint"],
                    meter(cap._fixed_spy_genesis()))
            bad = dict(state, start=cap.MIN_START)
            with self.assertRaisesRegex(Refused, "SPY665_GROUP_SCOPE"):
                campaign.verify_new_group(self.drive, self.drive.folder, bad, result["checkpoint"],
                    meter(cap._fixed_spy_genesis()), fixed_spy=True)

    def test_public_worker_consumes_authenticated_fixed_control_and_real_meter(self):
        import tempfile
        from datetime import timedelta
        from types import SimpleNamespace
        from tools import alpaca_sip_campaign as campaign
        import alpaca_sip_campaign_smoke as fixtures
        value = fixtures.fixed_spy_auth()
        value.update(phases=["capture"], private_root_folder_id=self.drive.root_id,
                     private_data_folder_id=self.drive.folder)
        parent = fixtures.fixed_spy_parent(value)
        value["parent_manifest_sha256"] = cap.digest(cap.encoded(parent))
        reference = "https://github.com/"+campaign.REPO+"/issues/448#issuecomment-12"
        grant = dict(schema="a1-fixed-spy-execution-v1", auth_sha256=cap.digest(cap.encoded(value)),
            parent_manifest_sha256=value["parent_manifest_sha256"], profile=cap.FIXED_SPY_PROFILE,
            start=cap.FIXED_SPY_START, end=cap.FIXED_SPY_END, input_sha256=cap.digest(cap.FIXED_SPY_INPUT),
            eligible_purpose="PRIVATE_NONCOMMERCIAL_RESEARCH", current_account_reviewed=True,
            supplier_rights_verified=False, source_admission=False, economic_authority=False,
            not_before_utc=value["not_before_utc"], expires_at_utc=value["expires_at_utc"],
            account_permission_reference_sha256=cap.digest(value["account_permission_reference"].encode()))
        def comment(index, tag, record):
            created = (campaign.utc(value["not_before_utc"])+timedelta(seconds=1)).isoformat()
            return dict(id=index, issue_url=f"https://api.github.com/repos/{campaign.REPO}/issues/448",
                author_association="OWNER", user=dict(type="User", id=123), created_at=created,
                updated_at=created, body=tag+cap.encoded(record).decode())
        offline_seconds = [20]
        def gh(path):
            if path.endswith("/issues/comments/11"):
                return comment(11, "A1_SIP_CLOSED_PARENT_MANIFEST ", parent)
            if path.endswith("/issues/comments/12"):
                return comment(12, "A1_SIP_FIXED_SPY_EXECUTION ", grant)
            if path.endswith("/actions/runs/2/jobs?per_page=100"):
                started = campaign.utc()
                return dict(total_count=2, jobs=[dict(name="offline", status="completed", conclusion="success",
                    started_at=(started-timedelta(seconds=offline_seconds[0])).isoformat(),
                    completed_at=started.isoformat()), dict(name="capture", status="in_progress",
                    started_at=started.isoformat())])
            self.fail("Unexpected GitHub fixture operation: "+path)
        asset = cap.encoded(dict(id="00000000-0000-0000-0000-000000000001", symbol="SPY",
            exchange="ARCA", status="active", **{"class": "us_equity"}))
        payload = cap.encoded(dict(bars={"SPY": self.grid["raw"]}, next_page_token=None))
        class FixtureOpener:
            def __init__(self):
                self.bodies = [asset, payload, payload]
                self.calls = 0
            def open(self, request, **kwargs):
                self.calls += 1
                return fixtures.Reply(self.bodies.pop(0))
        opener = FixtureOpener()
        real_meter, meters = campaign.RuntimeMeter, []
        def meter(*a, **kw):
            result = real_meter(*a, opener=opener, **kw); meters.append(result); return result
        self.drive.owner, self.drive.free = value["owner_permission_id"], 1000000000
        nonce = campaign.PREFIX+"b"*24
        control = dict(authorization=value, nonce=nonce, fixed_spy_grant_reference=reference, preflight_only=False)
        current = dict(fixtures.fixed_spy_run(parent["runs"][0]), id=2, run_number=2,
            status="in_progress", conclusion=None, head_sha=value["expected_master"], display_title="a1-sip "+nonce)
        env = dict(self.env, GITHUB_SHA=value["expected_master"], GITHUB_EVENT_NAME="workflow_dispatch",
            GITHUB_RUN_ATTEMPT="1", GITHUB_RUN_ID="2", INPUT_CAMPAIGN_NONCE=nonce,
            ALPACA_API_KEY="fixture-key", ALPACA_API_SECRET="fixture-secret")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"control.json"; path.write_bytes(cap.encoded(control))
            args = SimpleNamespace(**dict(vars(self.args), start=cap.MIN_START, campaign_control_file=str(path)))
            env["RUNNER_TEMP"] = tmp
            with patch.dict("os.environ", env, clear=True), patch.object(campaign, "gh_json", side_effect=gh), patch.object(campaign, "campaign_runs", return_value=[fixtures.fixed_spy_run(parent["runs"][0]), current]), patch.object(campaign, "campaign_run_pages", return_value=[fixtures.fixed_spy_run(parent["runs"][0]), current]), patch.object(campaign, "RuntimeMeter", side_effect=meter), patch.object(real_meter, "process_deadline", lambda self: contextlib.nullcontext()), patch.object(cap, "OwnerDrive", return_value=self.drive), patch.object(cap.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
                offline_seconds[0] = value["wall_seconds"]
                with self.assertRaisesRegex(Refused, "CAMPAIGN_DEADLINE"):
                    cap.run(args)
                self.assertEqual((meters, opener.calls), ([], 0))
                self.assertFalse((Path(tmp)/"campaign_meter.json").exists())
                offline_seconds[0] = 20
                result = cap.run(args)
            saved = cap.decode((Path(tmp)/"campaign_meter.json").read_bytes())
        self.assertEqual((result["rows_new"], result["total_examined"]), (4, 1))
        self.assertEqual(len(meters), 1)
        self.assertEqual((opener.calls, opener.bodies), (3, []))
        self.assertEqual((saved["usage"]["provider_gets"], saved["finalized"], saved["status"]), (3, True, "COMPLETE"))
        self.assertEqual(saved["fixed_profile"], cap.FIXED_SPY_PROFILE)
        self.assertFalse(saved["source_admission"])
        self.assertFalse(saved["economic_authority"])


def load_tests(loader, standard_tests, pattern):
    import importlib.util
    path = Path(__file__).with_name('alpaca_sip_campaign_smoke.py')
    spec = importlib.util.spec_from_file_location('a1_campaign_registered', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    standard_tests.addTests(loader.loadTestsFromModule(module))
    return standard_tests


if __name__ == "__main__":
    unittest.main()
