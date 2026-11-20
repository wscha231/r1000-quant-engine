#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.telegram_event_v1.ingest import (
    A2_SCHEMA,
    CHECKPOINT_SCHEMA,
    build_latest_pointer,
    build_outputs,
    canonical_json_bytes,
    parse_latest_pointer,
    parse_telegram_html,
    verify_latest_pointer_files,
    verify_run_bundle,
)

SOURCE = "https://t.me/s/insidertracking"
CHANNEL = "insidertracking"
SEED = 64207


def page(posts):
    blocks=[]
    for pid, dt, text in posts:
        blocks.append(f'''<div class="tgme_widget_message" data-post="insidertracking/{pid}">
          <div class="tgme_widget_message_text js-message_text">{text}</div>
          <a class="tgme_widget_message_date"><time datetime="{dt}"></time></a>
        </div>''')
    return ("<html><body>"+"".join(blocks)+"</body></html>").encode()


def receipt(outputs):
    return json.loads(outputs["receipt.json"])


def checkpoint(outputs):
    return json.loads(outputs["checkpoint.json"])


class TestTelegramIngest(unittest.TestCase):
    def test_parser_extracts_post_identity_time_and_text(self):
        rows=parse_telegram_html(page([(64208,"2026-09-20T18:00:00+00:00","Oil <b>up</b> &amp; NVDA")]),CHANNEL)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].post_id,64208)
        self.assertIn("Oil up & NVDA",rows[0].text)
        self.assertEqual(rows[0].source_url,"https://t.me/insidertracking/64208")

    def test_void_html_tags_do_not_break_message_boundaries(self):
        raw=b'<div class="tgme_widget_message" data-post="insidertracking/64208"><div class="tgme_widget_message_text js-message_text">Oil<br>up<img src="x"> now</div><time datetime="2026-09-20T18:00:00+00:00"></time></div>'
        rows=parse_telegram_html(raw,CHANNEL)
        self.assertEqual(len(rows),1)
        self.assertIn("Oil\nup now",rows[0].text)

    def test_forward_ingest_is_discovery_only_zero_score(self):
        p=page([
            (64208,"2026-09-20T18:00:00+00:00","Iran missile risk lifts oil; NVDA unchanged"),
            (64209,"2026-09-20T18:01:00+00:00","hello world"),
        ])
        out=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=None,initial_last_post_id=SEED,fetcher=lambda u:p,collected_at="2026-09-20T18:02:00Z")
        cp=checkpoint(out); a2=json.loads(out["a2_discovery_inputs.json"])
        self.assertEqual(cp["schema_version"],CHECKPOINT_SCHEMA)
        self.assertEqual(cp["last_post_id"],64209)
        self.assertTrue(cp["event_delta_committed"])
        self.assertEqual(len(out["events.ndjson"].splitlines()),2)
        self.assertEqual(a2["schema_version"],A2_SCHEMA)
        self.assertEqual(a2["score_contribution"],0.0)
        self.assertFalse(a2["events"][0]["a3_er_eligible"])
        self.assertFalse(a2["events"][0]["selector_eligible"])
        self.assertTrue(a2["events"][0]["requires_independent_verification"])

    def test_archive_boundary_closes_even_with_deleted_id_holes(self):
        first=page([(64211,"2026-09-20T18:03:00+00:00","CPI surprise"),(64212,"2026-09-20T18:04:00+00:00","Oil")])
        prior=page([(64205,"2026-09-20T17:58:00+00:00","older"),(64208,"2026-09-20T18:00:00+00:00","Fed"),(64210,"2026-09-20T18:02:00+00:00","war")])
        def fetch(u): return first if "before=" not in u else prior
        out=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=None,initial_last_post_id=SEED,fetcher=fetch,collected_at="2026-09-20T18:05:00Z")
        cp=checkpoint(out)
        self.assertFalse(cp["gap_unresolved"])
        self.assertEqual(cp["last_post_id"],64212)
        self.assertEqual([json.loads(x)["post_id"] for x in out["events.ndjson"].splitlines()],[64208,64210,64211,64212])

    def test_unresolved_interval_does_not_advance_chain(self):
        first=page([(65000,"2026-09-20T19:00:00+00:00","NVDA")])
        seed=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=None,initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T17:00:00+00:00","Fed")]),collected_at="2026-09-20T17:01:00Z")
        prior_cp=checkpoint(seed)
        out=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=seed["checkpoint.json"],initial_last_post_id=SEED,max_pages=2,fetcher=lambda u:first,collected_at="2026-09-20T19:01:00Z")
        cp=checkpoint(out); a2=json.loads(out["a2_discovery_inputs.json"])
        self.assertTrue(cp["gap_unresolved"])
        self.assertEqual(cp["last_post_id"],prior_cp["last_post_id"])
        self.assertEqual(cp["event_chain_sha256"],prior_cp["event_chain_sha256"])
        self.assertFalse(cp["event_delta_committed"])
        self.assertEqual(a2["events"],[])
        self.assertEqual(receipt(out)["status"],"BLOCKED_GAP_UNRESOLVED")

    def test_successive_runs_store_only_delta_and_extend_chain(self):
        first=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=None,initial_last_post_id=SEED,fetcher=lambda u:page([
            (64208,"2026-09-20T18:00:00+00:00","Fed"),(64209,"2026-09-20T18:01:00+00:00","BTC")
        ]),collected_at="2026-09-20T18:02:00Z")
        second=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=first["checkpoint.json"],initial_last_post_id=SEED,fetcher=lambda u:page([
            (64208,"2026-09-20T18:00:00+00:00","Fed"),(64209,"2026-09-20T18:01:00+00:00","BTC"),(64210,"2026-09-20T18:03:00+00:00","Oil")
        ]),collected_at="2026-09-20T18:04:00Z")
        cp1=checkpoint(first); cp2=checkpoint(second)
        self.assertEqual(len(first["events.ndjson"].splitlines()),2)
        self.assertEqual([json.loads(x)["post_id"] for x in second["events.ndjson"].splitlines()],[64210])
        self.assertNotEqual(cp1["event_chain_sha256"],cp2["event_chain_sha256"])
        self.assertEqual(cp2["previous_event_chain_sha256"],cp1["event_chain_sha256"])

    def test_unchanged_run_preserves_event_chain_with_empty_delta(self):
        first=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=None,initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T18:00:00+00:00","Fed")]),collected_at="2026-09-20T18:01:00Z")
        second=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=first["checkpoint.json"],initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T18:00:00+00:00","Fed")]),collected_at="2026-09-20T19:01:00Z")
        self.assertEqual(second["events.ndjson"],b"")
        self.assertEqual(checkpoint(first)["event_chain_sha256"],checkpoint(second)["event_chain_sha256"])
        self.assertEqual(receipt(second)["status"],"UNCHANGED")

    def test_invalid_checkpoint_schema_fails_closed(self):
        bad=b'{"schema_version":"wrong","channel":"insidertracking","last_post_id":64208}\n'
        with self.assertRaisesRegex(ValueError,"invalid_checkpoint_schema"):
            build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=bad,initial_last_post_id=SEED,fetcher=lambda u:page([(64209,"2026-09-20T19:00:00+00:00","Oil")]))

    def test_invalid_checkpoint_event_chain_fails_closed(self):
        bad=canonical_json_bytes({"schema_version":CHECKPOINT_SCHEMA,"channel":CHANNEL,"source_url":SOURCE,"last_post_id":SEED,"event_chain_sha256":"bad"})
        with self.assertRaisesRegex(ValueError,"invalid_checkpoint_event_chain"):
            build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=bad,initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T19:00:00+00:00","Oil")]))

    def test_checkpoint_source_mismatch_fails_closed(self):
        seed=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=None,initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T18:00:00+00:00","Fed")]),collected_at="2026-09-20T18:01:00Z")
        value=checkpoint(seed); value["source_url"]="https://t.me/s/otherchannel"
        with self.assertRaisesRegex(ValueError,"checkpoint_source_mismatch"):
            build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=canonical_json_bytes(value),initial_last_post_id=SEED,fetcher=lambda u:b"")

    def test_unapproved_source_url_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"unapproved_source_url"):
            build_outputs(channel=CHANNEL,source_url="https://example.com/s/insidertracking",checkpoint_raw=None,initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T18:00:00+00:00","Oil")]),collected_at="2026-09-20T18:01:00Z")

    def test_future_telegram_timestamp_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"future_published_at"):
            build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=None,initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T18:02:00+00:00","Oil")]),collected_at="2026-09-20T18:01:00Z")

    def test_latest_pointer_binds_exact_immutable_run_files(self):
        outputs={"checkpoint.json":b"cp\n","events.ndjson":b"events\n","a2_discovery_inputs.json":b"a2\n","receipt.json":b"receipt\n"}
        raw=build_latest_pointer(channel=CHANNEL,source_url=SOURCE,run_key="12345-1",head_sha="a"*40,generated_at="2026-09-20T18:00:00Z",outputs=outputs)
        pointer=parse_latest_pointer(raw,channel=CHANNEL,source_url=SOURCE)
        verify_latest_pointer_files(pointer,outputs)
        self.assertEqual(pointer["run_key"],"12345-1")

    def test_latest_pointer_detects_tampered_run_file(self):
        outputs={"checkpoint.json":b"cp\n","events.ndjson":b"events\n","a2_discovery_inputs.json":b"a2\n","receipt.json":b"receipt\n"}
        raw=build_latest_pointer(channel=CHANNEL,source_url=SOURCE,run_key="12345-1",head_sha="a"*40,generated_at="2026-09-20T18:00:00Z",outputs=outputs)
        pointer=parse_latest_pointer(raw,channel=CHANNEL,source_url=SOURCE)
        tampered=dict(outputs); tampered["events.ndjson"]=b"tampered\n"
        with self.assertRaisesRegex(ValueError,"pointer_file_hash_mismatch:events.ndjson"):
            verify_latest_pointer_files(pointer,tampered)

    def test_latest_pointer_rejects_unsafe_run_key(self):
        outputs={"checkpoint.json":b"cp\n","events.ndjson":b"events\n","a2_discovery_inputs.json":b"a2\n","receipt.json":b"receipt\n"}
        with self.assertRaisesRegex(ValueError,"invalid_pointer_run_key"):
            build_latest_pointer(channel=CHANNEL,source_url=SOURCE,run_key="../escape",head_sha="a"*40,generated_at="2026-09-20T18:00:00Z",outputs=outputs)

    def test_run_bundle_verifier_accepts_committed_delta(self):
        out=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=None,initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T18:00:00+00:00","Fed")]),collected_at="2026-09-20T18:01:00Z")
        verify_run_bundle(checkpoint_raw=out["checkpoint.json"],event_delta_raw=out["events.ndjson"],a2_raw=out["a2_discovery_inputs.json"],receipt_raw=out["receipt.json"],channel=CHANNEL,source_url=SOURCE,initial_last_post_id=SEED)

    def test_run_bundle_verifier_detects_tampered_delta(self):
        out=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=None,initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T18:00:00+00:00","Fed")]),collected_at="2026-09-20T18:01:00Z")
        with self.assertRaisesRegex(ValueError,"receipt_event_delta_hash_mismatch"):
            verify_run_bundle(checkpoint_raw=out["checkpoint.json"],event_delta_raw=b"tampered\n",a2_raw=out["a2_discovery_inputs.json"],receipt_raw=out["receipt.json"],channel=CHANNEL,source_url=SOURCE,initial_last_post_id=SEED)

    def test_run_bundle_verifier_accepts_unchanged_empty_delta(self):
        first=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=None,initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T18:00:00+00:00","Fed")]),collected_at="2026-09-20T18:01:00Z")
        out=build_outputs(channel=CHANNEL,source_url=SOURCE,checkpoint_raw=first["checkpoint.json"],initial_last_post_id=SEED,fetcher=lambda u:page([(64208,"2026-09-20T18:00:00+00:00","Fed")]),collected_at="2026-09-20T19:01:00Z")
        verify_run_bundle(checkpoint_raw=out["checkpoint.json"],event_delta_raw=out["events.ndjson"],a2_raw=out["a2_discovery_inputs.json"],receipt_raw=out["receipt.json"],channel=CHANNEL,source_url=SOURCE,initial_last_post_id=SEED)


if __name__ == "__main__":
    unittest.main()
