#!/usr/bin/env python3
"""Checkpoint corruption/failure/retry and orchestration regressions; synthetic."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import macro_history_sources as source
from tools import macro_research_checkpoint as checkpoint
from tools import macro_research_cycle as cycle


def fixture(root):
    fetcher = lambda *a: ([b"DATE,UNRATE\n2020-01-01,3.5\n"], "2026-09-11T00:00:00Z")
    source.collect(root / "store", ["UNRATE"], "2020-01-01", "2020-01-31", fetcher=fetcher)
    raw = source.REGISTRY.read_bytes()
    source.exclusive(root / "store/registries" / (source.digest(raw) + ".json"), raw)
    source.exclusive(root / "reports/fixture.json", source.encoded(dict(data_kind="SYNTHETIC")))


class CheckpointTests(unittest.TestCase):
    def test_roundtrip_and_stale_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root / "first")
            transport = checkpoint.LocalTransport(root / "remote")
            result = checkpoint.publish(transport, root / "first", None, "one")
            self.assertFalse(result["remote_verified"])
            restored = checkpoint.restore_latest(transport, root / "clean")
            self.assertEqual(result["manifest_sha256"], restored["manifest_sha256"])
            self.assertEqual(result["commit"], restored["commit"])
            with self.assertRaisesRegex(ValueError, "stale_parent"):
                checkpoint.publish(transport, root / "first", None, "stale")
            with self.assertRaisesRegex(ValueError, "destination_exists"):
                checkpoint.restore_latest(transport, root / "clean")

    def test_corruption_and_partial_upload_never_advance_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root / "data")
            transport = checkpoint.LocalTransport(root / "remote")
            original = transport.download
            def corrupt(hashes, target):
                original(hashes, target)
                next(target.iterdir()).write_bytes(b"corrupt")
            with patch.object(transport, "download", corrupt):
                with self.assertRaisesRegex(ValueError, "checkpoint_hash"):
                    checkpoint.publish(transport, root / "data", None, "broken")
            self.assertIsNone(checkpoint.head(transport)[0])
            result = checkpoint.publish(transport, root / "data", None, "retry")
            # Damage a referenced remote raw object after an accepted roundtrip.
            next((root / "remote/objects").iterdir()).write_bytes(b"damaged")
            with self.assertRaisesRegex(ValueError, "checkpoint_hash"):
                checkpoint.restore_latest(transport, root / "restore")
            self.assertFalse((root / "restore").exists())
            self.assertEqual(checkpoint.head(transport)[0], result["commit"])

    def test_broken_chain_does_not_fall_back_to_old_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root / "data")
            transport = checkpoint.LocalTransport(root / "remote")
            first = checkpoint.publish(transport, root / "data", None, "first")
            broken = dict(schema="macro-checkpoint-commit-v1", parent="a"*64,
                          generation=2, manifest=first["manifest_sha256"], eligible_for_selector=False)
            raw = source.encoded(broken)
            transport.write("commits/" + source.digest(raw) + ".json", raw)
            with self.assertRaisesRegex(ValueError, "broken_chain"):
                checkpoint.restore_latest(transport, root / "restore")

    def test_path_secret_scope_and_symlink_rejection(self):
        for name in ("../secret", "/absolute", "store/../../ledger", "reports/token.txt"):
            with self.assertRaises(ValueError):
                checkpoint.data_path(name)
        for remote in ("gdrive:accounts", "other:research/macro_technical_evidence/v1/scheduled"):
            with self.assertRaisesRegex(ValueError, "research_remote_scope"):
                checkpoint.RcloneTransport(remote)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root / "data")
            (root / "data/reports/secret.json").symlink_to(root / "data/reports/fixture.json")
            with self.assertRaisesRegex(ValueError, "symlink"):
                checkpoint.prepare(root / "data", root / "stage")

    def test_changed_retrieval_is_not_changed_economy(self):
        old = dict(series="UNRATE", observation_date="2020-01-01", vintage_date=None, value=3.5, retrieved_at="2020-02-01")
        self.assertFalse(cycle.source_changes({"UNRATE": [old]}, {"UNRATE": [dict(old, retrieved_at="2026-09-11")]})[0]["changed"])
        self.assertEqual(cycle.source_changes({"UNRATE": [old]}, {"UNRATE": [dict(old, value=3.6)]})[0]["revised"], 1)
        self.assertEqual(cycle.source_changes({"UNRATE": [old]}, {})[0]["removed"], 1)

    def test_poll_does_not_confirm_release_and_rechecks_late_data(self):
        calendar = dict(events=[dict(series="UNRATE", release_at="2026-09-11T04:00:00Z")])
        previous = dict(sources=[dict(series="UNRATE", status="COLLECTED", retrieved_at="2026-09-11T06:00:00Z", latest="2026-07-01")])
        job = next(j for j in cycle.job_plan("2026-09-11T07:00:00Z", previous, calendar)["jobs"] if j["series"] == "UNRATE")
        self.assertEqual(job["collection_action"], "REFRESH_FULL_HISTORY")
        self.assertFalse(job["release_confirmed"])

    def test_rolling_price_window_retains_old_history_but_not_missing_interior(self):
        with tempfile.TemporaryDirectory() as tmp:
            def row(day, value):
                return dict(observation_date=day, value=value, evidence="current_only")
            old = {"SP500": [row("2016-01-01", 100), row("2016-01-02", 110), row("2016-01-03", 120)]}
            new = {"SP500": [row("2016-01-02", 111), row("2016-01-04", 130)]}
            old_receipt = dict(sources=[dict(series="SP500", status="COLLECTED", raw_sha256=["a"*64])])
            fresh = dict(sources=[dict(series="SP500", status="COLLECTED", raw_sha256=["b"*64], earliest="2016-01-02")])
            receipt, merged = cycle.retain_expired_price_history(tmp, fresh, new, old_receipt, old)
            self.assertEqual([(r["observation_date"], r["value"]) for r in merged["SP500"]],
                [("2016-01-01", 100), ("2016-01-02", 111), ("2016-01-04", 130)])
            self.assertEqual(receipt["sources"][0]["retained_expired_provider_rows"], 1)

    def test_transport_redacts_errors_and_environment_collisions(self):
        import subprocess
        transport = object.__new__(checkpoint.RcloneTransport)
        transport.binary = "rclone"
        with patch.dict(os.environ, {"MACRO_RCLONE_CONFIG": "/tmp/config", "RCLONE_VERSION": "1.75.0", "RCLONE_CONFIG_GDRIVE": "secret"}):
            def fail(args, **kwargs):
                self.assertNotIn("RCLONE_VERSION", kwargs["env"])
                self.assertNotIn("RCLONE_CONFIG_GDRIVE", kwargs["env"])
                return subprocess.CompletedProcess(args, 1, b"", b"private-secret")
            with patch.object(checkpoint.subprocess, "run", fail):
                with self.assertRaisesRegex(ValueError, "^research_transport_failed:command:exit_1:UNCLASSIFIED$"):
                    transport.call("version")
        message = checkpoint.transport_failure(b"secret-key: Error 403: insufficient permissions", "cat", 1)
        self.assertEqual(message, "research_transport_failed:cat:exit_1:PERMISSION")

    def test_two_cycles_failure_journal_and_readonly_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transport = checkpoint.LocalTransport(root / "remote")
            def collector(store, ids, start, through, mode="current"):
                # Actual parsers, receipts, raw persistence; only HTTP is synthetic.
                def fetcher(sid, *args):
                    if mode == "current":
                        raw = f"DATE,{sid}\n2020-01-01,100\n2020-02-01,101\n".encode()
                    else:
                        rows = [dict(date="2020-01-01", value="100", realtime_start="2020-02-07", realtime_end="9999-12-31")]
                        raw = source.encoded(dict(units="lin", output_type=1, count=1, offset=0, observations=rows))
                    return [raw], source.utc_now()
                return source.collect(store, ids, start, through, mode, fetcher)
            def evaluate(*args):
                rows = [dict(asset=asset, feature=f"synthetic_{feature}", horizon_sessions=horizon,
                    status="INSUFFICIENT_INDEPENDENT_EVIDENCE", oos_rows=0, nonoverlap_windows=0,
                    effect_per_training_sd_pp=None, effect_ci95_pp=None, family_q_value=None,
                    oos_mse_improvement=None) for asset in ["SP500", "NASDAQCOM"]
                    for feature in range(24) for horizon in [1, 5, 10, 21, 63, 126, 252]]
                return dict(schema="macro-technical-evidence-v1", as_of=source.utc_now(),
                    tests_declared=336, coverage=dict(SP500={}, NASDAQCOM={}), results=rows,
                    code_file_sha256={}, input_receipt_sha256="a"*64,
                    eligible_for_selector=False, model_promoted=False)
            calendar = lambda *args: dict(schema="macro-release-calendar-v1", events=[], retrieved_at=source.utc_now())
            first = cycle.run_cycle(transport, root / "one", "one", collector=collector, calendar_fetcher=calendar, evaluator=evaluate)
            first_head = first["checkpoint"]["commit"]
            self.assertFalse(first["checkpoint"]["remote_verified"])
            # Subsequent provider failure must preserve the accepted predecessor.
            with self.assertRaisesRegex(ValueError, "macro_cycle_blocked"):
                cycle.run_cycle(transport, root / "failed", "failed", collector=lambda *a, **k: (_ for _ in ()).throw(ValueError("secret")), calendar_fetcher=calendar, evaluator=evaluate)
            self.assertEqual(checkpoint.head(transport)[0], first_head)
            second = cycle.run_cycle(transport, root / "two", "two", collector=collector, calendar_fetcher=calendar, evaluator=evaluate)
            self.assertEqual(second["checkpoint"]["parent"], first_head)
            changes = json.loads((root / "two/current/reports/comparison.json").read_bytes())
            self.assertFalse(changes["economic_data_changed"])
            context = json.loads((root / "two/current/reports/engine-context.json").read_bytes())
            self.assertFalse(context["eligible_for_selector"])
            self.assertEqual(context["stock_selection_weight"], 0)
            journal = [json.loads(p.read_bytes()) for p in (root / "remote/attempts").iterdir()]
            self.assertEqual(sum(r["phase"] == "STARTED" for r in journal), 3)
            self.assertEqual(sum(r["phase"] == "FAILED" for r in journal), 1)
            self.assertNotIn("secret", source.encoded(journal).decode())


def run_tests():
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(CheckpointTests))
    if not result.wasSuccessful():
        raise AssertionError("macro_research_cycle_smoke_failed")


if __name__ == "__main__":
    run_tests()
