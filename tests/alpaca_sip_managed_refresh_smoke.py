"""Synthetic component isolation; no credentials, provider or Drive transport."""
from contextlib import ExitStack
from datetime import date, timedelta
import gzip
import io
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import alpaca_sip_managed_refresh as runtime


cap = runtime.capture
FULL = ["2026-10-21", "2026-10-22", "2026-10-23"]
HELD = "BASELINE_COVERAGE_OR_LIFECYCLE_REVIEW_REQUIRED"


def bar(day):
    return dict(t=day + "T04:00:00Z", o=10, h=11, l=9, c=10.5, v=100)


def asset(symbol):
    return dict(symbol=symbol, id="00000000-0000-0000-0000-000000000001",
                exchange="NASDAQ", status="active", **{"class": "us_equity"})


class Reply:
    status = 200

    def __init__(self, body):
        self.body = body
        self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda _: None)))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read1(self, n):
        result, self.body = self.body[:n], self.body[n:]
        return result


class Opener:
    def __init__(self):
        self.urls = []

    def open(self, request, **_):
        self.urls.append(request.full_url)
        url = urlsplit(request.full_url)
        if "/assets/" in url.path:
            return Reply(runtime.encoded(asset(url.path.rsplit("/", 1)[1])))
        query = parse_qs(url.query)
        end = (date.fromisoformat(query["end"][0][:10]) + timedelta(days=1)).isoformat()
        days = sorted(runtime.expected_sessions(query["start"][0][:10], end))
        return Reply(runtime.encoded(dict(bars={t: [bar(d) for d in days]
            for t in query["symbols"][0].split(",")}, next_page_token=None)))


class MemoryDrive:
    root_id, owner, token, free = "fixture-root-123", "fixture-owner", "fixture-token", 2 * 1024**3

    def __init__(self, meter):
        self.meter = meter
        self.objects, self.parents, self.names, self.checked = {}, {}, {}, []

    def seed(self, folder, body, ext=".json"):
        fid = "fixture-object-" + str(len(self.objects) + 1).zfill(6)
        self.objects[fid], self.parents[fid], self.names[fid] = body, folder, runtime.digest(body) + ext
        return dict(file_id=fid, sha256=runtime.digest(body), bytes=len(body))

    def cost(self):
        self.meter.debit(dict(drive_requests=1, drive_bytes=100))

    def check(self, fid, parent=None, folder=False):
        self.cost()
        if fid in {"fixture-data-123", "fixture-journal-123", "fixture-evidence-123"} and parent == self.root_id:
            return
        self.checked.append(fid)
        runtime.require(fid in self.objects and self.parents[fid] == parent, "FIXTURE_OWNER")

    def read(self, fid, limit=16_000_000):
        self.cost()
        body = self.objects[fid]
        runtime.require(len(body) <= limit, "FIXTURE_LIMIT")
        return body

    def request(self, url, **_):
        self.cost()
        query = parse_qs(urlsplit(url).query)["q"][0]
        parent = re.search(r"'([^']+)' in parents", query).group(1)
        name = re.search(r"name = '([^']+)'", query)
        return runtime.encoded(dict(files=[dict(id=fid, name=self.names[fid], size=str(len(body)))
            for fid, body in self.objects.items() if self.parents[fid] == parent
            and (name is None or self.names[fid] == name.group(1))]))

    def write(self, folder, body, ext):
        self.cost()
        self.meter.reserve_storage(len(body))
        return self.seed(folder, body, ext)


class ComponentHoldTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        # Refuse default transports or child collectors if a fixture regresses.
        stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("network")))
        stack.enter_context(patch.object(runtime.subprocess, "run", side_effect=AssertionError("child")))
        stack.enter_context(patch.object(cap.time, "sleep", return_value=None))
        stack.enter_context(patch.dict("os.environ", {
            "GITHUB_SHA": "2" * 40, "ALPACA_API_KEY": "fixture-key",
            "ALPACA_API_SECRET": "fixture-secret"}, clear=True))
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.now = runtime.campaign.utc("2026-10-24T00:30:00Z")
        allowance = dict(provider_gets=20, drive_requests=200, drive_bytes=100_000_000, storage_bytes=2_000_000)
        identity = dict(run_id=1, run_attempt=1, source_sha="2" * 40,
                        parent_checkpoint_sha256=None, examined_before=0)
        self.opener = Opener()
        self.meter = runtime.campaign.RuntimeMeter(allowance, self.root / "meter.json",
            (self.now + timedelta(seconds=300)).isoformat(), identity,
            clock=lambda: self.now, opener=self.opener)
        self.drive = MemoryDrive(self.meter)
        self.control = dict(task_key="R1000-SYNTHETIC-COMPONENT-HOLD-ONLY", max_symbols_per_run=4,
            private_root_folder_id=self.drive.root_id, private_data_folder_id="fixture-data-123",
            journal_folder_id="fixture-journal-123", evidence_folder_id="fixture-evidence-123",
            authorized_tickers=["AAPL", "MSFT"], backfill_tickers=[], max_runs=2,
            per_run_allowance=allowance, inventory_sha256="a" * 64,
            owner_sha256=runtime.digest(self.drive.owner.encode()),
            credential_binding=runtime.digest(b"fixture-key\0fixture-secret"),
            expires_at=(self.now + timedelta(seconds=300)).isoformat(), max_active_seconds_per_run=300)
        self.identities = {t: self.drive.seed(self.control["evidence_folder_id"], runtime.encoded(asset(t)))
                           for t in self.control["authorized_tickers"]}

    def baseline(self, dates, *, split=None, start="2026-10-21", end="2026-10-24"):
        """Construct original response pages and matching normalized bytes."""
        names, members, pages, normalized = sorted(dates), {}, [], []
        for basis, grid in (("raw", dates), ("split", split if split is not None else dates)):
            payload = runtime.encoded(dict(bars={t: [bar(d) for d in grid[t]] for t in names},
                                           next_page_token=None, adjustment=basis))
            h = runtime.digest(payload)
            members[h + ".json"] = payload
            pages.append(dict(symbols=names, adjustment=basis, page=0, bytes=len(payload),
                              sha256=h, member=h + ".json"))
        for t in names:
            for basis, grid in (("raw", dates), ("split", split if split is not None else dates)):
                normalized.extend(cap.normalize([bar(d) for d in grid[t]], t, basis, start, end))
        meta = dict(schema=cap.SCHEMA, source=cap.SOURCE, symbols=names,
            collected=[t for t in names if dates[t]], no_bars=[t for t in names if not dates[t]],
            start=start, end=end, asof=cap.mapping_asof(end), seed_sha256="a" * 64,
            source_sha="2" * 40, pages=pages, raw_adjustments=["raw", "split"],
            historical_identity_verified=False, pit_verified=False,
            source_admission=False, commercial_use_authorized=False)
        members["capture.json"] = runtime.encoded(meta)
        folder = self.control["private_data_folder_id"]
        raw = self.drive.seed(folder, cap.zip_bytes(members), ".zip")
        norm = self.drive.seed(folder, gzip.compress(b"".join(runtime.encoded(r) for r in normalized), mtime=0), ".jsonl.gz")
        receipt = dict(meta, pages=len(pages), rows=len(normalized), raw_object=raw, normalized_object=norm)
        ref = self.drive.seed(folder, runtime.encoded(receipt))
        return dict(provider="alpaca_sip", symbols=names, receipt=ref)

    def collect(self, groups, tracked=("AAPL", "MSFT"), prior=None, held=None):
        return runtime.collect_groups(self.drive, self.meter, self.control,
            dict(groups=groups, asset_identity_refs=self.identities), set(tracked), prior or {}, held or {},
            "2026-10-23", "fixture-key", "fixture-secret", lambda: self.now)

    def execute(self, groups, tracked=("AAPL", "MSFT")):
        gate = runtime.managed.evaluate_market_session(now_utc=self.now, min_close_age_minutes=120)
        return runtime.execute(self.control, "b" * 64,
            dict(active_tickers=list(tracked[:1]), watch_tickers=list(tracked[1:])),
            dict(groups=groups, asset_identity_refs=self.identities), [dict(id=1, head_sha="2" * 40)],
            self.drive, self.meter, dict(run_id=1, head="2" * 40), "fixture-key", "fixture-secret",
            lambda: self.now, market_preflight=gate)

    def test_strict_bootstrap_still_refuses_incomplete_partition(self):
        group = self.baseline(dict(AAPL=FULL, MSFT=FULL[1:]))
        with self.assertRaisesRegex(runtime.IncompleteBootstrapCoverage, "^MANAGED_BOOTSTRAP_INCOMPLETE_GRID$") as caught:
            runtime.bootstrap_coverage(self.drive, self.control, dict(groups=[group]), {"AAPL", "MSFT"})
        self.assertEqual(caught.exception.coverage, {"AAPL": FULL[-1]})
        self.assertEqual(caught.exception.held, {"MSFT": HELD})

    def test_mixed_reuse_and_prefix_hold_no_identity_or_provider_for_held(self):
        result = self.execute([self.baseline(dict(AAPL=FULL, MSFT=FULL[1:]))])
        self.assertEqual((result["valid_updated"], result["reused"], result["held"], result["rows"]), (0, 1, 1, 0))
        self.assertFalse(any(result[k] for k in ("source_admission", "pit_verified", "economic_authority")))
        self.assertEqual(self.opener.urls, [])
        self.assertNotIn(self.identities["MSFT"]["file_id"], self.drive.checked)
        terminal = next(row for _, row in runtime.journal_rows(self.drive, self.control) if row["state"] == "COMPLETE")
        self.assertEqual(terminal["coverage_updates"], {"AAPL": FULL[-1]})
        self.assertEqual(terminal["held"], {"MSFT": HELD})
        self.assertEqual(terminal["reused"], ["AAPL"])

    def test_internal_hole_held_even_when_explicit_backfill_lists_it(self):
        self.control["backfill_tickers"] = ["MSFT"]
        values = self.collect([self.baseline(dict(AAPL=FULL, MSFT=FULL[::2]))])
        self.assertEqual(values[:3], ({"AAPL": FULL[-1]}, {"MSFT": HELD}, ["AAPL"]))
        self.assertEqual(self.opener.urls, [])

    def test_complete_sibling_updates_while_prefix_held_is_not_backfilled(self):
        self.control["backfill_tickers"] = ["MSFT"]
        group = self.baseline(dict(AAPL=FULL[:2], MSFT=FULL[1:2]), end="2026-10-23")
        result = self.execute([group])
        self.assertEqual((result["valid_updated"], result["reused"], result["held"], result["rows"]), (1, 0, 1, 2))
        self.assertEqual(self.meter.used["provider_gets"], 3)
        self.assertEqual(len(self.opener.urls), 3)
        self.assertTrue(all("MSFT" not in u for u in self.opener.urls))
        self.assertNotIn(self.identities["MSFT"]["file_id"], self.drive.checked)

    def test_absent_bootstrap_requires_explicit_backfill(self):
        values = self.collect([], tracked=("AAPL",))
        self.assertEqual(values[:3], ({}, {"AAPL": "MISSING_VERIFIED_ALPACA_COVERAGE"}, []))
        self.assertEqual(self.opener.urls, [])
        self.control["backfill_tickers"] = ["AAPL"]
        values = self.collect([], tracked=("AAPL",))
        self.assertEqual(values[0], {"AAPL": FULL[-1]})
        self.assertEqual(values[1:3], ({}, []))
        self.assertEqual(self.meter.used["provider_gets"], 3)
        self.assertTrue(any("start=" + cap.MIN_START in url for url in self.opener.urls))

    def test_prior_held_stays_visible_and_is_not_retried(self):
        values = self.collect([], prior={"AAPL": FULL[-1], "MSFT": FULL[-1]}, held={"MSFT": "PRIOR_REVIEW"})
        self.assertEqual(values[:3], ({"AAPL": FULL[-1]}, {"MSFT": "PRIOR_REVIEW"}, ["AAPL"]))
        self.assertEqual(self.opener.urls, [])
        self.assertNotIn(self.identities["MSFT"]["file_id"], self.drive.checked)
        prior = {"AAPL": "PRIOR_REVIEW", "MSFT": "PRIOR_REVIEW"}
        self.assertEqual(self.collect([], held=prior)[:3], ({}, prior, []))
        self.assertEqual(self.opener.urls, [])

    def test_all_held_real_run_blocks_journal_meter_and_caller(self):
        group = self.baseline(dict(AAPL=FULL[1:], MSFT=FULL[1:]))
        self.assert_all_held_run([group], {"AAPL": HELD, "MSFT": HELD})

    def test_no_coverage_or_backfill_is_not_a_successful_empty_run(self):
        self.assert_all_held_run([], {t: "MISSING_VERIFIED_ALPACA_COVERAGE" for t in ("AAPL", "MSFT")})

    def assert_all_held_run(self, groups, expected_held):
        policy = dict(automatic_capture_enabled=True, active_tickers=["AAPL"], watch_tickers=["MSFT"])
        args = SimpleNamespace(policy=self.root / "policy.json", inventory=self.root / "inventory.json",
                               output=self.root / "result.json", meter=self.root / "meter.json")
        with ExitStack() as stack:
            for name, value in (("validate_control", "b" * 64), ("deployed_source", self.now),
                    ("owner_grant", self.now), ("source_history_fence", []),
                    ("run_history", [dict(id=1, head_sha="2" * 40)]),
                    ("context_from_env", dict(run_id=1, attempt=1, head="2" * 40)),
                    ("rights_and_bootstrap", dict(groups=groups, asset_identity_refs=self.identities)),
                    ("final_meter_reader", None)):
                stack.enter_context(patch.object(runtime, name, return_value=value))
            stack.enter_context(patch.object(runtime.managed, "load", side_effect=[(policy, "c" * 64), ({}, "a" * 64)]))
            for name in ("inventory_rows", "policy_rows", "transition"):
                stack.enter_context(patch.object(runtime.managed, name))
            stack.enter_context(patch.object(runtime.campaign, "RuntimeMeter", return_value=self.meter))
            stack.enter_context(patch.dict("os.environ", {"A1_MANAGED_OHLCV_CONTROL": json.dumps(self.control)}))
            with self.assertRaisesRegex(runtime.Refused, "^MANAGED_ALL_COMPONENTS_HELD$"):
                runtime.run(args, gh=lambda _: self.fail("metadata"),
                            drive_factory=lambda *a, **k: self.drive, clock=lambda: self.now)
        self.assertEqual(self.opener.urls, [])
        rows = runtime.journal_rows(self.drive, self.control)
        self.assertEqual({r["state"] for _, r in rows}, {"RESERVED", "BLOCKED"})
        terminal = next(r for _, r in rows if r["state"] == "BLOCKED")
        self.assertEqual(terminal["reason"], "MANAGED_ALL_COMPONENTS_HELD")
        self.assertEqual(terminal["held"], expected_held)
        self.assertEqual((terminal["coverage_updates"], terminal["reused"], terminal["receipts"], terminal["rows"]), ({}, [], [], 0))
        meter = json.loads(args.meter.read_text(encoding="utf-8"))
        self.assertEqual((meter["status"], meter["finalized"], meter["usage"]["provider_gets"]), ("BLOCKED", True, 0))
        self.assertEqual(meter["reason"], "MANAGED_RUN_BLOCKED")
        self.assertTrue(all(meter[k] is False for k in ("source_admission", "pit_verified", "economic_authority")))
        with self.assertRaisesRegex(runtime.Refused, "MANAGED_PRIOR_FAILURE_REQUIRES_RECONCILIATION"):
            runtime.restore_journal(rows, [dict(id=1, head_sha="2" * 40), dict(id=2)], "b" * 64)

    def repack(self, group, mutate):
        receipt = runtime.decode(self.drive.objects[group["receipt"]["file_id"]])
        with zipfile.ZipFile(io.BytesIO(self.drive.objects[receipt["raw_object"]["file_id"]])) as archive:
            members = {n: archive.read(n) for n in archive.namelist()}
        mutate(members)
        receipt["raw_object"] = self.drive.seed(self.control["private_data_folder_id"], cap.zip_bytes(members), ".zip")
        group["receipt"] = self.drive.seed(self.control["private_data_folder_id"], runtime.encoded(receipt))

    def test_integrity_failures_after_a_held_group_remain_global(self):
        for case in ("receipt_hash", "raw_hash", "norm_hash", "raw_bytes", "norm_bytes", "schema", "malformed", "norm_row", "basis"):
            with self.subTest(case=case):
                held = self.baseline(dict(MSFT=FULL[1:]))
                good = self.baseline(dict(AAPL=FULL), split=dict(AAPL=FULL[:2]) if case == "basis" else None)
                receipt = runtime.decode(self.drive.objects[good["receipt"]["file_id"]])
                if case == "receipt_hash":
                    good["receipt"]["sha256"] = "0" * 64
                elif case in ("raw_hash", "norm_hash", "raw_bytes", "norm_bytes", "norm_row"):
                    key = "raw_object" if case.startswith("raw") else "normalized_object"
                    if case.endswith("hash"):
                        receipt[key]["sha256"] = "0" * 64
                    elif case.endswith("bytes"):
                        receipt[key]["bytes"] += 1
                    else:
                        receipt[key] = self.drive.seed(self.control["private_data_folder_id"], gzip.compress(b'{}\n', mtime=0), ".jsonl.gz")
                    good["receipt"] = self.drive.seed(self.control["private_data_folder_id"], runtime.encoded(receipt))
                elif case in ("schema", "malformed"):
                    def mutate(members):
                        meta = runtime.decode(members["capture.json"])
                        if case == "schema":
                            meta["schema"] = "invalid"
                        else:
                            page = meta["pages"][0]
                            body = runtime.decode(members.pop(page["member"]))
                            body["bars"]["AAPL"][0]["c"] = None
                            raw = runtime.encoded(body)
                            h = runtime.digest(raw)
                            page.update(member=h + ".json", sha256=h, bytes=len(raw))
                            members[page["member"]] = raw
                        members["capture.json"] = runtime.encoded(meta)
                    self.repack(good, mutate)
                reason = {"schema": "RESUME_ARCHIVE", "malformed": "BAR_VALUE",
                          "norm_row": "RESUME_NORMALIZED_MISMATCH", "basis": "RESUME_BASIS_GRID"}.get(
                              case, "MANAGED_OBJECT_HASH")
                with self.assertRaisesRegex(runtime.Refused, "^" + reason + "$") as caught:
                    self.collect([held, good])
                self.assertNotIsInstance(caught.exception, runtime.IncompleteBootstrapCoverage)
                self.assertEqual(self.opener.urls, [])

    def test_unexpected_exchange_holiday_is_not_a_recoverable_gap(self):
        group = self.baseline(dict(AAPL=["2026-11-25", "2026-11-26", "2026-11-27"]),
                              start="2026-11-25", end="2026-11-28")
        with self.assertRaisesRegex(runtime.Refused, "^MANAGED_BOOTSTRAP_UNEXPECTED_SESSION$") as caught:
            self.collect([group], tracked=("AAPL",))
        self.assertNotIsInstance(caught.exception, runtime.IncompleteBootstrapCoverage)
        self.assertEqual(self.opener.urls, [])


if __name__ == "__main__":
    unittest.main()
