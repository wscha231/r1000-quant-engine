"""Synthetic reference-plumbing fixtures, not market/domain/ER validation."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "tests"))

import a3_candidate_packet_v1_smoke as a3_fixture
import candidate_registry_v1 as registry
import a3_candidate_packet_v1 as a3
from a3_candidate_packet_v1 import evaluate_packet
from candidate_registry_v1 import ReferenceIndexError, build_reference_index

CUTOFF = "2026-09-19T04:00:00Z"


def raw_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.raw = {}
        self.counter = 0

    def put(self, aid, value, *, raw=None, at="2026-09-19T01:10:00Z"):
        payload = raw_json(value) if raw is None else raw
        digest = hashlib.sha256(payload).hexdigest()
        self.raw[(aid, digest)] = payload
        return {"artifact_id": aid, "sha256": digest, "available_at": at,
                "collected_at": at, "expires_at": "2026-09-20T00:00:00Z"}

    def resolve(self, aid, sha):
        return self.raw[(aid, sha)]

    def fixture(self, asset="US:BIO", issuer="CIK:1", *, er=False, country="US"):
        # Reuse the actual existing A3 producer and its fixture shape. Every
        # artifact ID is immutable within this supplied snapshot.
        a3_fixture.RAW.clear()
        packet = a3_fixture.packet(er)
        prefix = asset.replace(":", "_") + ":" + str(self.counter) + ":"
        self.counter += 1
        originals = dict(a3_fixture.RAW)
        rewritten = {}

        def rewrite_ref(aid, sha):
            key = (aid, sha)
            if key in rewritten:
                return rewritten[key]
            payload = rewrite(json.loads(originals[key]))
            ref = self.put(prefix + aid, payload)
            rewritten[key] = ref
            return ref

        def rewrite(value):
            if isinstance(value, list):
                return [rewrite(x) for x in value]
            if not isinstance(value, dict):
                return value
            result = {k: rewrite(v) for k, v in value.items()}
            if "asset_id" in result:
                result["asset_id"] = asset
            if "issuer_id" in result:
                result["issuer_id"] = issuer
            if "benchmark_id" in result:
                result["benchmark_id"] = "KR:KOSPI200" if country == "KR" else "US:SPY"
            if "currency" in result:
                result["currency"] = "KRW" if country == "KR" else "USD"
            if "raw_artifact_id" in value:
                ref = rewrite_ref(value["raw_artifact_id"], value["raw_sha256"])
                result["raw_artifact_id"], result["raw_sha256"] = ref["artifact_id"], ref["sha256"]
            if "artifact_id" in value and "sha256" in value:
                ref = rewrite_ref(value["artifact_id"], value["sha256"])
                result["artifact_id"], result["sha256"] = ref["artifact_id"], ref["sha256"]
            return result

        packet = rewrite(packet)
        packet["country"] = country
        result = evaluate_packet(packet, CUTOFF, self.resolve)
        packet_ref = self.put(prefix + "PACKET", packet)
        result_ref = self.put(prefix + "RESULT", result, at="2026-09-19T01:20:00Z")
        return {"asset_id": asset, "issuer_id": issuer,
                "a3_packet_ref": packet_ref, "a3_result_ref": result_ref}

    def build(self, *entries, **kw):
        return build_reference_index(list(entries), cutoff=kw.get("cutoff", CUTOFF),
                                     artifact_resolver=kw.get("resolver", self.resolve))

    def read(self, ref):
        return json.loads(self.resolve(ref["artifact_id"], ref["sha256"]))

    def replace(self, entry, role, obj=None, *, raw=None):
        old = entry[role]
        self.counter += 1
        new = self.put(old["artifact_id"] + ":REVISED" + str(self.counter), obj, raw=raw,
                       at=old["available_at"])
        new["collected_at"] = old["collected_at"]
        new["expires_at"] = old["expires_at"]
        entry[role] = new

    def assert_blocked(self, entry, reason):
        out = self.build(entry)
        self.assertEqual(out["status"], "REFERENCE_ERRORS_PRESENT")
        self.assertEqual(out["records"][0]["reference_status"], "BLOCKED")
        self.assertIn(reason, out["records"][0]["blockers"][0])
        self.assertFalse(out["records"][0]["A5_eligible_input"])
        return out

    def test_verified_reference_keeps_authority_closed(self):
        entry = self.fixture()
        out = self.build(entry)
        row = out["records"][0]
        self.assertEqual(out["status"], "REFERENCE_INDEX_BUILT")
        self.assertEqual(row["reference_status"], "A3_REFERENCE_REPLAY_VERIFIED")
        self.assertEqual(row["a3_packet_ref"], entry["a3_packet_ref"])
        self.assertFalse(row["A5_eligible_input"])
        self.assertFalse(row["selector_eligible"])
        self.assertFalse(out["economic_consumption_allowed"])
        self.assertEqual(row["review_authentication_status"], "NOT_VERIFIED")
        self.assertEqual(row["current_selection_status"], "NOT_VERIFIED")
        self.assertEqual(row["research_freshness_state"], "NOT_CERTIFIED")

    def test_four_market_domain_labels_use_same_path(self):
        rows = [self.fixture(a, "ISSUER:" + a, country=c) for a, c in
                [("US:BIO", "US"), ("US:CLEAN", "US"), ("KR:BIO", "KR"), ("KR:CLEAN", "KR")]]
        out = self.build(*rows)
        self.assertEqual(out["reference_verified_count"], 4)
        self.assertEqual({r["metadata"]["currency"] for r in out["records"]}, {"USD", "KRW"})
        self.assertTrue(all(r["domain_admission_status"] == "NOT_VERIFIED" for r in out["records"]))

    def test_same_issuer_distinct_security_is_not_collapsed(self):
        out = self.build(self.fixture("US:BIO.A"), self.fixture("US:BIO.B"))
        self.assertEqual(len(out["records"]), 2)
        self.assertEqual({r["issuer_id"] for r in out["records"]}, {"CIK:1"})

    def test_duplicate_security_fails_entire_batch(self):
        entry = self.fixture()
        with self.assertRaisesRegex(ReferenceIndexError, "duplicate_asset_id"):
            self.build(entry, deepcopy(entry))

    def test_conflicting_issuer_for_same_security_fails_batch(self):
        with self.assertRaisesRegex(ReferenceIndexError, "duplicate_asset_id"):
            self.build(self.fixture(), self.fixture(issuer="CIK:2"))

    def test_result_does_not_depend_on_input_order(self):
        a, b = self.fixture("US:BIO"), self.fixture("US:CLEAN")
        self.assertEqual(raw_json(self.build(a, b)), raw_json(self.build(b, a)))

    def test_input_not_mutated_and_repeatable(self):
        e = self.fixture()
        before = deepcopy(e)
        x, y = self.build(e), self.build(e)
        self.assertEqual(e, before)
        self.assertEqual(x, y)
        self.assertNotIn("SKIP_UNCHANGED", raw_json(x).decode())

    def test_empty_input_not_successful_universe(self):
        out = self.build()
        self.assertEqual(out["status"], "EMPTY_INPUT")
        self.assertEqual(out["input_count"], 0)
        self.assertFalse(out["economic_consumption_allowed"])

    def test_known_identity_rejection_remains_visible(self):
        good, bad = self.fixture("US:BIO"), self.fixture("US:CLEAN")
        self.raw.pop((bad["a3_packet_ref"]["artifact_id"], bad["a3_packet_ref"]["sha256"]))
        out = self.build(good, bad)
        self.assertEqual(len(out["records"]), 2)
        self.assertEqual(out["reference_verified_count"], 1)
        self.assertEqual(out["blocked_count"], 1)

    def test_malformed_identity_cannot_be_silently_dropped(self):
        e = self.fixture(); e["asset_id"] = " US:BIO"
        with self.assertRaisesRegex(ReferenceIndexError, "asset_id"):
            self.build(e)

    def test_missing_resolver_fails_at_entry(self):
        with self.assertRaisesRegex(ReferenceIndexError, "artifact_resolver_required"):
            self.build(self.fixture(), resolver=None)

    def test_packet_hash_mismatch(self):
        e = self.fixture(); ref = e["a3_packet_ref"]
        self.raw[(ref["artifact_id"], ref["sha256"])] = b"tampered"
        self.assert_blocked(e, "artifact_hash_mismatch")

    def test_result_hash_mismatch(self):
        e = self.fixture(); ref = e["a3_result_ref"]
        self.raw[(ref["artifact_id"], ref["sha256"])] = b"tampered"
        self.assert_blocked(e, "artifact_hash_mismatch")

    def test_rehashed_forged_result_rejected(self):
        e = self.fixture(); obj = self.read(e["a3_result_ref"])
        obj["status"] = "VALIDATED_ER_LINKED"
        self.replace(e, "a3_result_ref", obj)
        self.assert_blocked(e, "result_replay_mismatch")

    def test_boolean_zero_in_result_not_equal_by_python_coercion(self):
        e = self.fixture(); obj = self.read(e["a3_result_ref"])
        obj["selector_eligible"] = 0
        self.replace(e, "a3_result_ref", obj)
        self.assert_blocked(e, "result_replay_mismatch")

    def test_packet_raw_hash_not_confused_with_semantic_hash(self):
        e = self.fixture(); obj = self.read(e["a3_packet_ref"])
        self.replace(e, "a3_packet_ref", raw=json.dumps(obj, indent=2).encode())
        row = self.build(e)["records"][0]
        self.assertEqual(row["reference_status"], "A3_REFERENCE_REPLAY_VERIFIED")
        self.assertNotEqual(row["a3_packet_ref"]["sha256"], row["packet_semantic_sha256"])

    def test_packet_asset_identity_conflict(self):
        e = self.fixture(); e["asset_id"] = "US:OTHER"
        self.assert_blocked(e, "packet_asset_identity")

    def test_packet_issuer_identity_conflict(self):
        e = self.fixture(); e["issuer_id"] = "CIK:OTHER"
        self.assert_blocked(e, "packet_issuer_identity")

    def test_dependency_tamper_is_rechecked(self):
        e = self.fixture(); obj = self.read(e["a3_packet_ref"])
        r = obj["artifacts"]["methodology"]
        self.raw[(r["artifact_id"], r["sha256"])] = b"tampered"
        self.assert_blocked(e, "artifact_hash_mismatch")

    def test_raw_source_tamper_is_rechecked(self):
        e = self.fixture(); p = self.read(e["a3_packet_ref"])
        g = self.read(p["artifacts"]["source_graph"]); r = g["sources"][0]
        self.raw[(r["raw_artifact_id"], r["raw_sha256"])]=b"tampered"
        self.assert_blocked(e, "A3_VALIDATION_FAILED")

    def test_future_available_reference_rejected(self):
        e = self.fixture(); e["a3_packet_ref"]["available_at"] = "2026-09-20T01:00:00Z"
        self.assert_blocked(e, "reference_time_order")

    def test_future_collected_reference_rejected(self):
        e = self.fixture(); e["a3_result_ref"]["collected_at"] = "2026-09-20T01:00:00Z"
        self.assert_blocked(e, "reference_time_order")

    def test_naive_time_rejected(self):
        e = self.fixture(); e["a3_result_ref"]["available_at"] = "2026-09-19T01:20:00"
        self.assert_blocked(e, "timezone_required")

    def test_result_available_before_packet_collected_rejected(self):
        e = self.fixture(); e["a3_result_ref"]["available_at"] = "2026-09-19T01:05:00Z"
        self.assert_blocked(e, "result_precedes_packet")

    def test_packet_available_before_review_rejected(self):
        e = self.fixture(); e["a3_packet_ref"]["available_at"] = "2026-09-19T00:30:00Z"
        self.assert_blocked(e, "packet_precedes_review")

    def test_expired_reference_not_current_or_reusable(self):
        e = self.fixture(); e["a3_packet_ref"]["expires_at"] = "2026-09-19T03:00:00Z"
        row = self.build(e)["records"][0]
        self.assertEqual(row["declared_expiry_state"], "EXPIRED")
        self.assertFalse(row["reuse_authorized"])
        self.assertFalse(row["A5_eligible_input"])

    def test_expiry_boundary_is_exclusive(self):
        e = self.fixture(); e["a3_result_ref"]["expires_at"] = CUTOFF
        self.assertEqual(self.build(e)["records"][0]["declared_expiry_state"], "EXPIRED")

    def test_unknown_expiry_stays_unknown(self):
        e = self.fixture(); e["a3_result_ref"]["expires_at"] = None
        self.assertEqual(self.build(e)["records"][0]["declared_expiry_state"], "UNKNOWN")

    def test_expiry_before_creation_invalid(self):
        e = self.fixture(); e["a3_result_ref"]["expires_at"] = "2026-09-18T00:00:00Z"
        self.assert_blocked(e, "expiry_precedes_collection")

    def test_future_packet_review_rejected(self):
        e = self.fixture(); p = self.read(e["a3_packet_ref"])
        p["reviewed_at"] = "2026-09-20T00:00:00Z"
        self.replace(e,"a3_packet_ref",p)
        self.assert_blocked(e, "packet_precedes_review")

    def test_missing_er_stays_null(self):
        row = self.build(self.fixture())["records"][0]
        self.assertIsNone(row["validated_er_ref"])
        self.assertNotIn("expected_return_12m", raw_json(row).decode())
        self.assertIn("VALIDATED_ER_NOT_LINKED", row["consumption_blockers"])

    def test_linked_er_is_reference_not_a5_authority(self):
        row = self.build(self.fixture(er=True))["records"][0]
        self.assertIsNotNone(row["validated_er_ref"])
        self.assertEqual(row["a3_result_status"], "VALIDATED_ER_LINKED")
        self.assertNotIn("expected_alpha", raw_json(row).decode())
        self.assertFalse(row["A5_eligible_input"])
        self.assertIn("ECONOMIC_ADMISSION_NOT_VERIFIED", row["consumption_blockers"])

    def test_scenario_probability_uses_existing_rejection(self):
        e = self.fixture(); p = self.read(e["a3_packet_ref"])
        p["scenario_research"]["12m"]["base"]["probability"] = .5
        self.replace(e,"a3_packet_ref",p)
        self.assert_blocked(e, "A3_VALIDATION_FAILED")

    def test_duplicate_json_key_rejected(self):
        e = self.fixture()
        r = self.resolve(e["a3_packet_ref"]["artifact_id"], e["a3_packet_ref"]["sha256"])
        self.replace(e,"a3_packet_ref",raw=b'{"schema":"wrong",'+r[1:])
        self.assert_blocked(e, "duplicate_json_key")

    def test_nonfinite_json_constant_rejected(self):
        e = self.fixture()
        self.replace(e,"a3_result_ref",raw=b'{"x":NaN}')
        self.assert_blocked(e, "nonfinite_json")

    def test_overflow_json_number_rejected(self):
        e = self.fixture()
        self.replace(e,"a3_result_ref",raw=b'{"x":1e999}')
        self.assert_blocked(e, "nonfinite_json")

    def test_deep_json_rejected(self):
        e = self.fixture()
        self.replace(e,"a3_result_ref",raw=b'{"x":'+b'['*80+b'0'+b']'*80+b'}')
        self.assert_blocked(e, "json_depth_limit")

    def test_nested_structured_dependency_duplicate_json_rejected(self):
        e = self.fixture(); p = self.read(e["a3_packet_ref"])
        r = p["artifacts"]["methodology"]
        old = self.resolve(r["artifact_id"],r["sha256"])
        nr = self.put(r["artifact_id"]+":BAD",None,raw=b'{"schema":"wrong",'+old[1:])
        r["artifact_id"],r["sha256"]=nr["artifact_id"],nr["sha256"]
        self.replace(e,"a3_packet_ref",p)
        self.assert_blocked(e, "duplicate_json_key")

    def test_unknown_entry_authority_field_rejected(self):
        e = self.fixture(); e["target_weight"] = .01
        self.assert_blocked(e, "entry_fields")

    def test_unknown_reference_field_rejected(self):
        e = self.fixture(); e["a3_result_ref"]["review_approved"] = True
        self.assert_blocked(e, "reference_fields")

    def test_duplicate_immutable_id_with_different_bytes_fails_batch(self):
        a,b = self.fixture("US:A"),self.fixture("US:B")
        ra,rb=a["a3_packet_ref"],b["a3_packet_ref"]
        self.raw[(ra["artifact_id"],rb["sha256"])]=self.resolve(rb["artifact_id"],rb["sha256"])
        rb["artifact_id"] = ra["artifact_id"]
        with self.assertRaisesRegex(ReferenceIndexError,"artifact_id_conflict"):
            self.build(a,b)

    def test_budget_fails_closed(self):
        e = self.fixture()
        with patch("candidate_registry_v1.MAX_TOTAL_BYTES",8):
            with self.assertRaisesRegex(ReferenceIndexError,"total_byte_budget"):
                self.build(e)

    def test_identity_conflicts_precede_row_metadata_errors(self):
        a, b = self.fixture("US:A"), self.fixture("US:B")
        for source_role in ("a3_packet_ref", "a3_result_ref"):
            for target_role in ("a3_packet_ref", "a3_result_ref"):
                for bad_index in (0, 1):
                    for error in ("timestamp", "reference_fields", "entry_fields"):
                        with self.subTest(source=source_role, target=target_role,
                                          bad_index=bad_index, error=error):
                            rows = deepcopy([a, b])
                            rows[1][target_role]["artifact_id"] = rows[0][source_role]["artifact_id"]
                            bad = rows[bad_index]
                            if error == "timestamp":
                                bad["a3_packet_ref"]["available_at"] = "invalid"
                            elif error == "reference_fields":
                                del bad["a3_packet_ref"]["expires_at"]
                            else:
                                bad["unexpected"] = True
                            for ordered in (rows, rows[::-1]):
                                with patch.object(self, "resolve") as resolver:
                                    with self.assertRaisesRegex(ReferenceIndexError, "artifact_id_conflict"):
                                        self.build(*ordered, resolver=resolver)
                                    resolver.assert_not_called()

    def test_shared_json_decode_outcomes_are_cached(self):
        for payload, reason in ((b'{', "invalid_json"),
                                (b'{"x":1,"x":2}', "duplicate_json_key"),
                                (b'{"x":1e999}', "nonfinite_json"),
                                (b'{}', "packet_asset_identity")):
            with self.subTest(reason=reason):
                entry = self.fixture()
                self.replace(entry, "a3_packet_ref", raw=payload)
                rows = [dict(deepcopy(entry), asset_id=f"US:SHARED{i}") for i in range(20)]
                with patch.object(a3, "_strict_json_object", wraps=a3._strict_json_object) as decode:
                    out = self.build(*rows)
                packet_decodes = [call for call in decode.call_args_list if call.args == (payload,)]
                self.assertEqual(len(packet_decodes), 1)
                self.assertEqual(out["blocked_count"], len(rows))
                self.assertTrue(all(row["blockers"] == [reason] for row in out["records"]))

    def test_cached_objects_preserve_read_tracking_and_invocation_scope(self):
        entry = self.fixture()
        snapshot = registry._Snapshot(self.resolve)
        ref = entry["a3_packet_ref"]
        with patch.object(a3, "_strict_json_object", wraps=a3._strict_json_object) as decode:
            first = snapshot.object(ref)
            snapshot.current_reads.clear()
            self.assertEqual(snapshot.object(ref), first)
            self.assertEqual(snapshot.current_reads, {(ref["artifact_id"], ref["sha256"])})
            self.assertEqual(decode.call_count, 1)
            registry._Snapshot(self.resolve).object(ref)
            self.assertEqual(decode.call_count, 2)

    def test_failed_reads_cached_for_every_rejection_phase(self):
        for mode in ("provider", "type", "bytearray", "memoryview", "empty", "oversize", "hash"):
            with self.subTest(mode=mode):
                a, b = self.fixture("US:A"), self.fixture("US:B")
                b["a3_packet_ref"] = deepcopy(a["a3_packet_ref"])
                ref = a["a3_packet_ref"]
                key = ref["artifact_id"], ref["sha256"]
                calls = []
                def resolver(aid, sha):
                    calls.append((aid, sha))
                    if (aid, sha) == key:
                        if mode == "provider":
                            raise OSError("secret-provider-url")
                        return {"type": {}, "bytearray": bytearray(b"x"), "memoryview": memoryview(b"x"), "empty": b"", "oversize": b"x" * 33,
                                "hash": b"tampered"}[mode]
                    return self.resolve(aid, sha)
                with patch.object(registry, "MAX_ARTIFACT_BYTES", 32 if mode == "oversize" else registry.MAX_ARTIFACT_BYTES):
                    first = self.build(a, b, resolver=resolver)
                    second = self.build(a, b, resolver=resolver)
                self.assertEqual(calls.count(key), 2)  # one per fresh invocation
                self.assertEqual(first, second)
                self.assertEqual(first["blocked_count"], 2)
                self.assertNotIn("secret-provider-url", raw_json(first).decode())

    def test_oversized_bytes_consume_aggregate_before_blob_rejection(self):
        for payload in (b"x" * 17, bytearray(b"x" * 17), memoryview(b"x" * 17)):
            with self.subTest(type=type(payload).__name__):
                rows = [self.fixture("US:A"), self.fixture("US:B")]
                calls = []
                def resolver(aid, sha):
                    calls.append((aid, sha))
                    return payload
                with patch.object(registry, "MAX_ARTIFACT_BYTES", 16), patch.object(registry, "MAX_TOTAL_BYTES", 30):
                    with self.assertRaisesRegex(ReferenceIndexError, "total_byte_budget"):
                        self.build(*rows, resolver=resolver)
                self.assertEqual(len(calls), 2)

    def test_exact_byte_budget_and_replay_read_tracking(self):
        entry = self.fixture()
        expected = sum(map(len, self.raw.values()))
        calls = []
        def resolver(aid, sha):
            calls.append((aid, sha))
            return self.resolve(aid, sha)
        with patch.object(registry, "MAX_TOTAL_BYTES", expected):
            out = self.build(entry, resolver=resolver)
        self.assertEqual(out["reference_verified_count"], 1)
        self.assertEqual(len(calls), len(set(calls)))
        self.assertEqual({(r["artifact_id"], r["sha256"]) for r in out["records"][0]["resolved_blob_refs"]}, set(self.raw))

    def test_downstream_cache_budget_is_batch_fatal(self):
        entry = self.fixture()
        with patch.object(a3, "MAX_CACHED_TOTAL_BYTES", 1):
            with self.assertRaisesRegex(ReferenceIndexError, "total_byte_budget"):
                self.build(entry)

    def test_nested_identity_conflicts_precede_all_row_failures(self):
        for early in ("asset", "issuer", "clock", "roles", "missing_dependency", "bad_dependency", "bad_result"):
            for role in ("methodology", "moat", "market_valuation", "source_graph"):
                with self.subTest(early=early, role=role):
                    a, b = self.fixture("US:A"), self.fixture("US:B")
                    pa, pb = self.read(a["a3_packet_ref"]), self.read(b["a3_packet_ref"])
                    pa["artifacts"][role]["artifact_id"] = pb["artifacts"][role]["artifact_id"]
                    if early == "asset": pa["asset_id"] = "US:WRONG"
                    elif early == "issuer": pa["issuer_id"] = "WRONG"
                    elif early == "clock": pa["reviewed_at"] = "invalid"
                    elif early == "roles": pa["artifacts"]["invalid_role"] = None
                    elif early in {"missing_dependency", "bad_dependency"}:
                        ref = pa["artifacts"]["methodology"]
                        key = ref["artifact_id"], ref["sha256"]
                        if early == "missing_dependency": self.raw.pop(key, None)
                        else: self.raw[key] = b"tampered"
                    elif early == "bad_result":
                        self.replace(a, "a3_result_ref", raw=b"{")
                    self.replace(a, "a3_packet_ref", pa)
                    for ordered in ((a, b), (b, a)):
                        with self.assertRaisesRegex(ReferenceIndexError, "artifact_id_conflict"):
                            self.build(*ordered)

    def test_raw_nested_conflict_precedes_unavailable_other_dependency(self):
        a, b = self.fixture("US:A"), self.fixture("US:B")
        pa, pb = self.read(a["a3_packet_ref"]), self.read(b["a3_packet_ref"])
        ga, gb = self.read(pa["artifacts"]["source_graph"]), self.read(pb["artifacts"]["source_graph"])
        ga["sources"][0]["raw_artifact_id"] = gb["sources"][0]["raw_artifact_id"]
        ga["sources"][0]["raw_sha256"] = "0" * 64
        new = self.put("REVISED:GRAPH", ga)
        pa["artifacts"]["source_graph"].update(artifact_id=new["artifact_id"], sha256=new["sha256"])
        method = pa["artifacts"]["methodology"]
        self.raw.pop((method["artifact_id"], method["sha256"]))
        self.replace(a, "a3_packet_ref", pa)
        for ordered in ((a, b), (b, a)):
            with self.assertRaisesRegex(ReferenceIndexError, "artifact_id_conflict"):
                self.build(*ordered)

    def test_future_row_preflight_does_not_resolve(self):
        for role in ("a3_packet_ref", "a3_result_ref"):
            entry = self.fixture()
            entry[role]["collected_at"] = "2026-09-20T01:00:00Z"
            with patch.object(self, "resolve", side_effect=RuntimeError("secret")) as resolver:
                out = self.build(entry, resolver=resolver)
            self.assertEqual(resolver.call_count, 0)
            self.assertEqual(out["blocked_count"], 1)

    def test_A3_replay_reuses_actual_json_and_hash_outcomes(self):
        a, b = self.fixture("US:A"), self.fixture("US:B")
        # Distinct packet/result pairs share structured and raw dependencies;
        # row B ultimately fails packet identity, but must not reparse A's deps.
        p = self.read(a["a3_packet_ref"])
        shared = deepcopy(p)
        shared["asset_id"] = "US:B"
        self.replace(b, "a3_packet_ref", shared)
        original_loads, original_hash = json.loads, hashlib.sha256
        decoded, hashed = [], []
        def loads(raw, *args, **kw):
            decoded.append(raw)
            return original_loads(raw, *args, **kw)
        def sha(raw=b""):
            hashed.append(raw)
            return original_hash(raw)
        with patch.object(a3.json, "loads", side_effect=loads), patch.object(a3.hashlib, "sha256", side_effect=sha):
            out = self.build(a, b)
        self.assertEqual(out["reference_verified_count"], 1)
        structured = [a["a3_packet_ref"], a["a3_result_ref"]] + list(p["artifacts"].values())
        for ref in structured:
            raw = self.resolve(ref["artifact_id"], ref["sha256"])
            self.assertEqual(decoded.count(raw), 1)
            self.assertGreaterEqual(hashed.count(raw), 1)

    def test_hash_mismatches_consume_total_byte_budget(self):
        entries = [self.fixture(f"US:BROKEN{i}") for i in range(3)]
        payload = b"x" * (48 * 1024 * 1024)

        for entry in entries:
            ref = entry["a3_packet_ref"]
            ref["artifact_id"] = "BROKEN:PACKET:" + entry["asset_id"]
            ref["sha256"] = "0" * 64

        def resolver(aid, sha):
            if aid.startswith("BROKEN:PACKET:"):
                return payload
            return self.resolve(aid, sha)

        with self.assertRaisesRegex(ReferenceIndexError, "total_byte_budget"):
            self.build(*entries, resolver=resolver)

    def test_max_node_packet_reused_by_max_invalid_rows_is_scanned_and_sealed_once(self):
        packet = {"asset_id": "US:ABSENT", "as_of": "2026-09-18T21:00:00Z",
                  "artifacts": {}, "pad": [0] * (a3.MAX_JSON_NODES - 5)}
        pref, rref = self.put("SHARED_PACKET", packet), self.put("SHARED_RESULT", {})
        rows = [{"asset_id": f"US:ROW{i:05d}", "issuer_id": "CIK:1",
                 "a3_packet_ref": pref, "a3_result_ref": rref} for i in range(registry.MAX_ENTRIES)]
        counts = {"scans": 0, "visits": 0, "seal": 0, "decode": 0, "reads": 0}
        scan, seal, loads = registry._register_nested, a3._sealed_json, a3.json.loads

        def scan_once(value, snapshot):
            counts["scans"] += 1
            # Abort before a repeated full traversal, including on old source.
            self.assertLessEqual(counts["scans"], 1)
            counts["visits"] += scan(value, snapshot)

        def seal_once(value):
            counts["seal"] += 1
            self.assertLessEqual(counts["seal"], a3.MAX_JSON_NODES + 1)
            return seal(value)

        def decode_once(*args, **kwargs):
            counts["decode"] += 1
            return loads(*args, **kwargs)

        def read(aid, sha):
            counts["reads"] += 1
            return self.resolve(aid, sha)

        with patch.object(registry, "_register_nested", new=scan_once), \
             patch.object(a3, "_sealed_json", new=seal_once), \
             patch.object(a3.json, "loads", new=decode_once):
            out = self.build(*rows, resolver=read)
        self.assertEqual(out["blocked_count"], registry.MAX_ENTRIES)
        self.assertEqual(counts, {"scans": 1, "visits": a3.MAX_JSON_NODES,
                                  "seal": a3.MAX_JSON_NODES + 1, "decode": 2, "reads": 2})

    def test_shared_large_dependency_preflight_is_scanned_once_across_packet_identities(self):
        dep = self.put("LARGE_DEP", {"pad": [0] * (a3.MAX_JSON_NODES - 2)})
        rref = self.put("RESULT", {})
        rows = []
        for i in range(8):
            packet = {"asset_id": "US:ABSENT", "as_of": "2026-09-19T02:00:00Z",
                      "artifacts": {"methodology": dep}}
            rows.append({"asset_id": f"US:{i}", "issuer_id": "CIK:1",
                         "a3_packet_ref": self.put(f"PACKET{i}", packet), "a3_result_ref": rref})
        visits = []
        scan = registry._register_nested

        def measured(value, snapshot):
            if "pad" in value:
                self.assertEqual(visits, [])  # Guard before any repeated large scan.
                visits.append(scan(value, snapshot))
            else:
                scan(value, snapshot)

        with patch.object(registry, "_register_nested", new=measured):
            self.assertEqual(self.build(*rows)["blocked_count"], 8)
        self.assertEqual(visits, [a3.MAX_JSON_NODES])

    def test_nested_clock_gate_precedes_every_cache_access(self):
        for role in ("methodology", "moat", "market_valuation", "source_graph", "validated_er"):
            for at in ("2026-09-18T21:00:00.000001Z", "2026-09-19T03:00:00Z", "2026-09-20T01:00:00Z"):
                with self.subTest(role=role, at=at):
                    entry = self.fixture(er=True)
                    packet = self.read(entry["a3_packet_ref"])
                    ref = packet["artifacts"][role]
                    ref["available_at"] = at
                    self.replace(entry, "a3_packet_ref", packet)
                    key = ref["artifact_id"], ref["sha256"]
                    accesses = []
                    original = registry._Snapshot.object

                    def object_access(snapshot, descriptor):
                        accesses.append((descriptor["artifact_id"], descriptor["sha256"]))
                        return original(snapshot, descriptor)

                    with patch.object(registry._Snapshot, "object", new=object_access):
                        out = self.build(entry)
                    self.assertEqual(out["blocked_count"], 1)
                    self.assertNotIn(key, accesses)

    def test_nested_clock_equality_positive_and_invalid_packet_clock_zero_dependencies(self):
        entry = self.fixture(er=True)
        packet = self.read(entry["a3_packet_ref"])
        for ref in packet["artifacts"].values():
            ref["available_at"] = packet["as_of"]
        self.replace(entry, "a3_result_ref", evaluate_packet(packet, CUTOFF, self.resolve))
        self.replace(entry, "a3_packet_ref", packet)
        self.assertEqual(self.build(entry)["reference_verified_count"], 1)
        for at in (None, "invalid", "2026-09-20T01:00:00Z"):
            changed = deepcopy(packet)
            changed["as_of"] = at
            self.replace(entry, "a3_packet_ref", changed)
            dep_keys = {(r["artifact_id"], r["sha256"]) for r in changed["artifacts"].values()}
            reads = []
            def read(aid, sha):
                reads.append((aid, sha))
                return self.resolve(aid, sha)
            self.assertEqual(self.build(entry, resolver=read)["blocked_count"], 1)
            self.assertTrue(dep_keys.isdisjoint(reads))

    def test_future_dependency_in_one_packet_does_not_suppress_later_eligible_shared_dependency(self):
        dep = self.put("SHARED_DEP", {"raw_artifact_id": "RAW", "raw_sha256": "0" * 64},
                       at="2026-09-19T01:00:00Z")
        rref = self.put("RESULT", {})
        rows = []
        for name, as_of in (("A", "2026-09-18T21:00:00Z"), ("B", "2026-09-19T02:00:00Z")):
            packet = {"asset_id": "US:ABSENT", "as_of": as_of, "artifacts": {"methodology": dep}}
            rows.append({"asset_id": "US:" + name, "issuer_id": "CIK:1",
                         "a3_packet_ref": self.put("PACKET" + name, packet), "a3_result_ref": rref})
        for ordered in (rows, list(reversed(rows))):
            reads = []
            def read(aid, sha):
                reads.append((aid, sha))
                return self.resolve(aid, sha)
            self.build(*ordered, resolver=read)
            self.assertEqual(reads.count((dep["artifact_id"], dep["sha256"])), 1)

    def test_future_nested_ref_cannot_access_an_already_warm_dependency_cache(self):
        a, b = self.fixture("US:A"), self.fixture("US:B")
        pa, pb = self.read(a["a3_packet_ref"]), self.read(b["a3_packet_ref"])
        shared = deepcopy(pa["artifacts"]["methodology"])
        shared["available_at"] = "2026-09-18T20:00:00.000001Z"
        pb["artifacts"]["methodology"] = shared
        pb["as_of"] = "2026-09-18T19:00:00Z"
        self.replace(b, "a3_packet_ref", pb)
        accesses = []
        original = registry._Snapshot.object
        def object_access(snapshot, descriptor):
            if descriptor["artifact_id"] == shared["artifact_id"]:
                accesses.append(descriptor["available_at"])
            return original(snapshot, descriptor)
        with patch.object(registry._Snapshot, "object", new=object_access):
            out = self.build(a, b)
        self.assertEqual(out["reference_verified_count"], 1)
        self.assertTrue(accesses)
        self.assertNotIn(shared["available_at"], accesses)

    def test_future_nested_descriptor_identity_conflicts_still_reject_without_resolving_future(self):
        a, b = self.fixture("US:A"), self.fixture("US:B")
        pa, pb = self.read(a["a3_packet_ref"]), self.read(b["a3_packet_ref"])
        ra, rb = pa["artifacts"]["methodology"], pb["artifacts"]["methodology"]
        ra["artifact_id"] = rb["artifact_id"]
        ra["available_at"] = rb["available_at"] = "2026-09-20T00:00:00Z"
        self.replace(a, "a3_packet_ref", pa)
        self.replace(b, "a3_packet_ref", pb)
        for ordered in ((a, b), (b, a)):
            reads = []
            def read(aid, sha):
                reads.append((aid, sha))
                return self.resolve(aid, sha)
            with self.assertRaisesRegex(ReferenceIndexError, "artifact_id_conflict"):
                self.build(*ordered, resolver=read)
            self.assertFalse(any(aid == rb["artifact_id"] for aid, _ in reads))

    def test_no_network_calls_or_file_writes_from_builder(self):
        e = self.fixture()
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
             patch("builtins.open", side_effect=AssertionError("file write forbidden")):
            self.assertEqual(self.build(e)["reference_verified_count"],1)

    def test_resolver_failure_does_not_echo_secret(self):
        e = self.fixture()
        def fail(aid,sha): raise RuntimeError("fake-secret-do-not-echo")
        out = self.build(e,resolver=fail)
        self.assertNotIn("fake-secret-do-not-echo",raw_json(out).decode())
        self.assertEqual(out["blocked_count"],1)

    def test_reference_set_digest_changes_with_expiry_not_just_bytes(self):
        e = self.fixture(); a = self.build(e)
        e["a3_result_ref"]["expires_at"] = "2026-09-21T00:00:00Z"
        self.assertNotEqual(a["index_sha256"], self.build(e)["index_sha256"])

    def test_unknown_freshness_cannot_skip_due_catalyst(self):
        e = self.fixture(); row=self.build(e)["records"][0]
        self.assertFalse(row["reuse_authorized"])
        self.assertIn("FRESHNESS_CATALYST_COLLECTION_CHECK_REQUIRED",row["consumption_blockers"])


if __name__ == "__main__":
    unittest.main()
