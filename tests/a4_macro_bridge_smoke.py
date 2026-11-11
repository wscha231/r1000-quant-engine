"""Real local Lake integration with disposable synthetic original responses."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import a4_macro_bridge as bridge
from tools import macro_history_sources as source
from tools.long_history_lake import Lake, LocalTransport, PREFIX

COLLECTED = "2026-11-06T22:00:00Z"
CUTOFF = "2026-11-07T22:00:00Z"


def original():
    return source.encoded(dict(file_type="json", units="lin", output_type=1,
        offset=0, limit=50000, count=2, observation_start="2026-10-01",
        observation_end="2026-11-06", realtime_start="2026-11-06", realtime_end="2026-11-06",
        observations=[dict(date=d, value=v, realtime_start="2026-11-06", realtime_end="2026-11-06")
                      for d, v in [("2026-11-04", "3.5"), ("2026-11-05", ".")]]))


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.transport = LocalTransport(self.root / "remote")
        self.stream = io.StringIO()
        self.quiet = redirect_stdout(self.stream); self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)
        self.lake = Lake(self.transport, self.root / "writer")
        raw = original()
        rows, missing = source.parse_current([raw], "SOFR", "2026-10-01", "2026-11-06", COLLECTED)
        rows = [{k: v for k, v in r.items() if k not in {"available_at", "retrieved_at"}} for r in rows]
        self.lake.dataset("current/SOFR", [raw], rows, dict(series="SOFR", evidence="current_only",
            requested_start="2026-10-01", requested_through="2026-11-06", retrieved_at=COLLECTED,
            missing_observation_dates=missing))
        self.publish_reader()

    def publish_reader(self):
        self.publication = self.lake.publish("fixture", {})
        quality = source.encoded(dict(schema="long-history-quality-v1", eligible_for_selector=False,
                                     status="COLLECTED_NOT_PIT_CERTIFIED"))
        qsha = source.digest(quality)
        self.transport.write(PREFIX+"/reports/"+qsha, quality)
        self.receipt = dict(schema="long-history-execution-v1", run_id="fixture",
            created_at=json.loads(self.lake.read_hash("commits",self.publication["commit_sha256"]))["created_at"],
            commit_sha256=self.publication["commit_sha256"], catalog_sha256=self.publication["catalog_sha256"],
            reports={"quality.json": qsha}, consumer_rows=1, study_recomputed_from_drive=True,
            quality_status="COLLECTED_NOT_PIT_CERTIFIED", eligible_for_selector=False)
        raw = source.encoded(self.receipt); self.execution = source.digest(raw)
        self.transport.write(PREFIX+"/executions/"+self.execution, raw)
        self.reader = Lake(self.transport, self.root / "reader")

    def read(self, **changes):
        args = dict(series_ids=["SOFR"], **self.publication, execution_sha256=self.execution, cutoff=CUTOFF)
        args.pop("new_packs"); args.pop("verified_new_bytes"); args.pop("remote_verified"); args.pop("eligible_for_selector")
        args.update(changes)
        return bridge.lake_current_inputs(self.reader, **args)

    def test_original_json_to_native_csv_preserves_latest_null_and_separate_hashes(self):
        bundle = self.read(); item = bundle["sources"][0]
        self.assertEqual(item["original"], original())
        self.assertIn(b"2026-11-05,.\n", item["normalized"])
        self.assertNotEqual(item["manifest"]["original_sha256"], item["manifest"]["normalized_sha256"])
        self.assertIsNone(item["manifest"]["published_at"])
        self.assertFalse(item["manifest"]["learning_permission_granted"])
        bridge.verify_normalization(item["original"], item["normalized"], item["manifest"])

    def test_store_is_idempotent_and_conflicting_attempt_does_not_replace_originals(self):
        bundle = self.read(); root = self.root / "out"
        first = bridge.store_bundle(bundle, root)
        self.assertEqual(first, bridge.store_bundle(bundle, root))
        before = (root / "originals/SOFR.raw").read_bytes()
        (root / "fred/SOFR.csv").write_bytes(b"foreign")
        with self.assertRaisesRegex(ValueError, "a4_output_conflict"):
            bridge.store_bundle(bundle, root)
        self.assertEqual((root / "originals/SOFR.raw").read_bytes(), before)

    def test_corrupt_or_missing_execution_refuses_before_source_read(self):
        (self.transport.root / PREFIX / "executions" / self.execution).write_bytes(b"tampered")
        with patch.object(self.reader, "get_records") as read:
            with self.assertRaises(ValueError): self.read()
            read.assert_not_called()

    def test_wrong_generation_catalog_execution_and_future_source_are_refused(self):
        for changes in ({"commit_sha256": "a"*64}, {"catalog_sha256": "a"*64},
                        {"execution_sha256": "a"*64}, {"cutoff": "2026-11-05T00:00:00Z"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.read(**changes)

    def test_blocked_dataset_and_absent_series_do_not_fall_back(self):
        with self.assertRaises(ValueError): self.read(series_ids=["IORB"])
        self.lake=Lake(self.transport,self.root/"stale-writer")
        self.lake.blocked("current/SOFR",ValueError("synthetic_source_failed"))
        self.publish_reader()
        with self.assertRaisesRegex(ValueError, "a4_dataset_unavailable"): self.read()

    def test_storage_success_without_study_is_not_consumer_success(self):
        self.reader.verified_execution = lambda: {**self.receipt, "execution_receipt_sha256": self.execution,
                                                "study_recomputed_from_drive": False}
        with self.assertRaisesRegex(ValueError, "a4_execution_incomplete"): self.read()

    def test_head_change_and_normalized_mismatch_refuse(self):
        with patch.object(self.reader, "restore_catalog", return_value=("a"*64, {})):
            with self.assertRaisesRegex(ValueError, "a4_lake_head_changed"): self.read()
        with patch.object(self.reader, "get_records", return_value=[]):
            with self.assertRaisesRegex(ValueError, "a4_original_normalized_parity"): self.read()

    def test_manifest_cannot_add_authority_or_change_clocks(self):
        item = self.read()["sources"][0]
        for key, value in (("learning_permission_granted", True), ("published_at", COLLECTED),
                           ("arbitrary_approval", True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                bridge.verify_normalization(item["original"], item["normalized"], {**item["manifest"], key: value})


if __name__ == "__main__": unittest.main()
