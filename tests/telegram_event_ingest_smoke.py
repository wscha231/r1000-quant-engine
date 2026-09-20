#!/usr/bin/env python3
from __future__ import annotations

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
    build_outputs,
    canonical_json_bytes,
    parse_telegram_html,
)


def page(posts):
    blocks=[]
    for pid, dt, text in posts:
        blocks.append(f'''<div class="tgme_widget_message" data-post="insidertracking/{pid}">
          <div class="tgme_widget_message_text js-message_text">{text}</div>
          <a class="tgme_widget_message_date"><time datetime="{dt}"></time></a>
        </div>''')
    return ("<html><body>"+"".join(blocks)+"</body></html>").encode()


class TestTelegramIngest(unittest.TestCase):
    def test_parser_extracts_post_identity_time_and_text(self):
        rows=parse_telegram_html(page([(64208,"2026-09-20T18:00:00+00:00","Oil <b>up</b> &amp; NVDA")]),"insidertracking")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].post_id,64208)
        self.assertIn("Oil up & NVDA",rows[0].text)
        self.assertEqual(rows[0].source_url,"https://t.me/insidertracking/64208")

    def test_forward_ingest_is_discovery_only_zero_score(self):
        pages={
            "https://t.me/s/insidertracking": page([
                (64208,"2026-09-20T18:00:00+00:00","Iran missile risk lifts oil; NVDA unchanged"),
                (64209,"2026-09-20T18:01:00+00:00","hello world"),
            ])
        }
        out=build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=None,event_log_raw=None,initial_last_post_id=64207,fetcher=lambda u:pages[u],collected_at="2026-09-20T18:02:00Z")
        cp=json.loads(out["checkpoint.json"])
        a2=json.loads(out["a2_discovery_inputs.json"])
        self.assertEqual(cp["schema_version"],CHECKPOINT_SCHEMA)
        self.assertEqual(cp["last_post_id"],64209)
        self.assertEqual(a2["schema_version"],A2_SCHEMA)
        self.assertEqual(a2["score_contribution"],0.0)
        self.assertFalse(a2["events"][0]["a3_er_eligible"])
        self.assertFalse(a2["events"][0]["selector_eligible"])
        self.assertTrue(a2["events"][0]["requires_independent_verification"])

    def test_gap_is_backfilled_across_pages(self):
        first=page([(64211,"2026-09-20T18:03:00+00:00","CPI surprise"),(64212,"2026-09-20T18:04:00+00:00","Oil")])
        prior=page([(64208,"2026-09-20T18:00:00+00:00","Fed"),(64209,"2026-09-20T18:01:00+00:00","BTC"),(64210,"2026-09-20T18:02:00+00:00","war")])
        def fetch(u):
            return first if "before=" not in u else prior
        out=build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=None,event_log_raw=None,initial_last_post_id=64207,fetcher=fetch,collected_at="2026-09-20T18:05:00Z")
        cp=json.loads(out["checkpoint.json"])
        self.assertFalse(cp["gap_unresolved"])
        self.assertEqual(cp["last_post_id"],64212)
        self.assertEqual(len(out["events.ndjson"].splitlines()),5)

    def test_unresolved_gap_does_not_advance_or_mutate_log(self):
        old_event={
            "schema_version":"telegram-insidertracking-event-v1","channel":"insidertracking","post_id":64208,
            "published_at":"2026-09-20T17:00:00Z","collected_at":"2026-09-20T17:01:00Z","available_from":"2026-09-20T17:01:00Z",
            "source_url":"https://t.me/insidertracking/64208","text":"old","text_sha256":"x","content_status":"TEXT",
            "relevance_categories":[],"tickers_detected":[],"a2_discovery_eligible":False,"verification_status":"UNVERIFIED_TELEGRAM_ONLY",
            "score_contribution":0.0,"a3_er_eligible":False,"selector_eligible":False,"target_authority":False,"order_authority":False,
        }
        old_log=canonical_json_bytes(old_event)
        old_cp=canonical_json_bytes({"schema_version":CHECKPOINT_SCHEMA,"channel":"insidertracking","last_post_id":64208})
        p=page([(65000,"2026-09-20T19:00:00+00:00","NVDA")])
        out=build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=old_cp,event_log_raw=old_log,initial_last_post_id=64207,max_pages=2,fetcher=lambda u:p,collected_at="2026-09-20T19:01:00Z")
        cp=json.loads(out["checkpoint.json"])
        self.assertTrue(cp["gap_unresolved"])
        self.assertEqual(cp["last_post_id"],64208)
        self.assertEqual(out["events.ndjson"],old_log)
        self.assertEqual(json.loads(out["a2_discovery_inputs.json"])["events"],[])

    def test_invalid_checkpoint_fails_closed(self):
        bad=b'{"schema_version":"wrong","channel":"insidertracking","last_post_id":1}\n'
        with self.assertRaisesRegex(ValueError,"invalid_checkpoint_schema"):
            build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=bad,event_log_raw=None,initial_last_post_id=0,fetcher=lambda u:page([(2,"2026-09-20T19:00:00+00:00","Oil")]))

    def test_checkpoint_log_chain_mismatch_fails_closed(self):
        event={
            "schema_version":"telegram-insidertracking-event-v1","channel":"insidertracking","post_id":9,
            "published_at":None,"collected_at":"2026-09-20T17:01:00Z","available_from":"2026-09-20T17:01:00Z",
            "source_url":"https://t.me/insidertracking/9","text":"old","text_sha256":"x","content_status":"TEXT",
            "relevance_categories":[],"tickers_detected":[],"a2_discovery_eligible":False,"verification_status":"UNVERIFIED_TELEGRAM_ONLY",
            "score_contribution":0.0,"a3_er_eligible":False,"selector_eligible":False,"target_authority":False,"order_authority":False,
        }
        cp=canonical_json_bytes({"schema_version":CHECKPOINT_SCHEMA,"channel":"insidertracking","last_post_id":8})
        with self.assertRaisesRegex(ValueError,"event_log_ahead_of_checkpoint"):
            build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=cp,event_log_raw=canonical_json_bytes(event),initial_last_post_id=8,fetcher=lambda u:page([(10,"2026-09-20T19:00:00+00:00","Oil")]))

    def test_void_html_tags_do_not_break_message_boundaries(self):
        raw=b'<div class="tgme_widget_message" data-post="insidertracking/64208"><div class="tgme_widget_message_text js-message_text">Oil<br>up<img src="x"> now</div><time datetime="2026-09-20T18:00:00+00:00"></time></div>'
        rows=parse_telegram_html(raw,"insidertracking")
        self.assertEqual(len(rows),1)
        self.assertIn("Oil\nup now",rows[0].text)

    def test_checkpoint_event_log_hash_mismatch_fails_closed(self):
        cp=canonical_json_bytes({"schema_version":CHECKPOINT_SCHEMA,"channel":"insidertracking","last_post_id":64207,"event_log_sha256":"0"*64})
        with self.assertRaisesRegex(ValueError,"checkpoint_event_log_hash_mismatch"):
            build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=cp,event_log_raw=b"",initial_last_post_id=0,fetcher=lambda u:page([(64208,"2026-09-20T19:00:00+00:00","Oil")]))

    def test_new_source_internal_gap_does_not_advance(self):
        p=page([
            (64208,"2026-09-20T18:00:00+00:00","Fed"),
            (64210,"2026-09-20T18:02:00+00:00","Oil"),
        ])
        out=build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=None,event_log_raw=None,initial_last_post_id=64207,max_pages=1,fetcher=lambda u:p,collected_at="2026-09-20T18:03:00Z")
        cp=json.loads(out["checkpoint.json"])
        self.assertTrue(cp["gap_unresolved"])
        self.assertEqual(cp["last_post_id"],64207)
        self.assertEqual(out["events.ndjson"],b"")
        self.assertEqual(json.loads(out["a2_discovery_inputs.json"])["events"],[])

    def test_checkpoint_ahead_of_event_log_fails_closed(self):
        event={
            "schema_version":"telegram-insidertracking-event-v1","channel":"insidertracking","post_id":64208,
            "published_at":None,"collected_at":"2026-09-20T17:01:00Z","available_from":"2026-09-20T17:01:00Z",
            "source_url":"https://t.me/insidertracking/64208","text":"old","text_sha256":"x","content_status":"TEXT",
            "relevance_categories":[],"tickers_detected":[],"a2_discovery_eligible":False,"verification_status":"UNVERIFIED_TELEGRAM_ONLY",
            "score_contribution":0.0,"a3_er_eligible":False,"selector_eligible":False,"target_authority":False,"order_authority":False,
        }
        log=canonical_json_bytes(event)
        import hashlib
        cp=canonical_json_bytes({"schema_version":CHECKPOINT_SCHEMA,"channel":"insidertracking","last_post_id":64209,"event_log_sha256":hashlib.sha256(log).hexdigest()})
        with self.assertRaisesRegex(ValueError,"checkpoint_ahead_of_event_log"):
            build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=cp,event_log_raw=log,initial_last_post_id=64207,fetcher=lambda u:page([(64210,"2026-09-20T19:00:00+00:00","Oil")]))

    def test_internal_event_log_gap_fails_closed(self):
        def row(pid):
            return {
                "schema_version":"telegram-insidertracking-event-v1","channel":"insidertracking","post_id":pid,
                "published_at":None,"collected_at":"2026-09-20T17:01:00Z","available_from":"2026-09-20T17:01:00Z",
                "source_url":f"https://t.me/insidertracking/{pid}","text":"old","text_sha256":"x","content_status":"TEXT",
                "relevance_categories":[],"tickers_detected":[],"a2_discovery_eligible":False,"verification_status":"UNVERIFIED_TELEGRAM_ONLY",
                "score_contribution":0.0,"a3_er_eligible":False,"selector_eligible":False,"target_authority":False,"order_authority":False,
            }
        log=canonical_json_bytes(row(64208))+canonical_json_bytes(row(64210))
        import hashlib
        cp=canonical_json_bytes({"schema_version":CHECKPOINT_SCHEMA,"channel":"insidertracking","last_post_id":64210,"event_log_sha256":hashlib.sha256(log).hexdigest()})
        with self.assertRaisesRegex(ValueError,"event_log_internal_gap"):
            build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=cp,event_log_raw=log,initial_last_post_id=64207,fetcher=lambda u:page([(64211,"2026-09-20T19:00:00+00:00","Oil")]))

    def test_nonseed_checkpoint_with_empty_log_fails_closed(self):
        import hashlib
        cp=canonical_json_bytes({"schema_version":CHECKPOINT_SCHEMA,"channel":"insidertracking","last_post_id":64208,"event_log_sha256":hashlib.sha256(b"").hexdigest()})
        with self.assertRaisesRegex(ValueError,"checkpoint_ahead_of_empty_event_log"):
            build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=cp,event_log_raw=b"",initial_last_post_id=64207,fetcher=lambda u:page([(64209,"2026-09-20T19:00:00+00:00","Oil")]))

    def test_unapproved_source_url_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"unapproved_source_url"):
            build_outputs(channel="insidertracking",source_url="https://example.com/s/insidertracking",checkpoint_raw=None,event_log_raw=None,initial_last_post_id=64207,fetcher=lambda u:page([(64208,"2026-09-20T18:00:00+00:00","Oil")]),collected_at="2026-09-20T18:01:00Z")

    def test_future_telegram_timestamp_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"future_published_at"):
            build_outputs(channel="insidertracking",source_url="https://t.me/s/insidertracking",checkpoint_raw=None,event_log_raw=None,initial_last_post_id=64207,fetcher=lambda u:page([(64208,"2026-09-20T18:02:00+00:00","Oil")]),collected_at="2026-09-20T18:01:00Z")


if __name__ == "__main__":
    unittest.main()
