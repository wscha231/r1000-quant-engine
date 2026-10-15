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
