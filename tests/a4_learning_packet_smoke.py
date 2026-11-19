"""Synthetic archive and price receipt round-trip for the A4-only input packet."""
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.a4_rtdsm_sources_smoke import workbook
from tools import a4_rtdsm_sources as vintage
from tools import prepare_a4_daily_direction_inputs as packet
from tools import run_a4_research_cycle as cycle
from tools.macro_history_sources import digest, encoded


class LearningPacketTests(unittest.TestCase):
    def setUp(self):
        archive = tempfile.TemporaryDirectory()
        self.addCleanup(archive.cleanup)
        self.root = Path(archive.name)
        self.objects = {}
        documentation, notice = b'Synthetic method', b'Synthetic rights notice'
        feeds = {key: (*value[:4], digest(documentation)) for key, value in vintage.FEEDS.items()}
        registry = patch.dict(vintage.FEEDS, feeds)
        registry.start()
        self.addCleanup(registry.stop)
        rights = self.put('evidence/purpose.txt', b'Synthetic purpose approval fixture')
        receipt = self.put('evidence/price_source.txt', b'Synthetic normalization evidence fixture')
        self.cutoff = '2018-03-29T23:00:00Z'
        provenance = {}
        for feed, fields in feeds.items():
            alias = fields[0]
            if alias == 'RUC':
                book = workbook(alias, ('RUC18Q1',), values=[('2017:12', [4.1]), ('2018:01', [4.0])])
            else:
                book = workbook(alias, (f'{alias}18M1', f'{alias}18M2'))
            result = vintage.store_capture(self.root/'rtdsm', book, feed, documentation_raw=documentation,
                rights_raw=notice, collected_at='2018-03-02T12:00:00Z')
            provenance[feed] = dict(generation_sha256=result['generation_sha256'], rights_evidence_sha256=rights)
        self.sessions = packet.session_grid('2018-03-01', '2018-03-29')
        self.prices, self.price_sources = {}, {}
        for target in packet.direction.TARGETS:
            original = self.put(f'evidence/{target}_original', f'Synthetic {target} price original'.encode())
            clocks = self.put(f'evidence/{target}_timestamps', f'Synthetic {target} release clocks'.encode())
            selected = self.sessions if target == 'SPY' else self.sessions[:-1]
            self.prices[target] = [dict(session=row['session'], value=100+i, original_sha256=original,
                available_at=(packet.free.utc(row['close_utc']) + timedelta(minutes=75 if i == 3 else 15)).isoformat(),
                return_basis='TOTAL_RETURN') for i, row in enumerate(selected)]
            self.price_sources[original] = dict(historical_use='DATE_ARCHIVE_RESEARCH_ONLY',
                price_series_id='synthetic:'+target, rights_evidence_sha256=rights, source_receipt_sha256=receipt,
                price_publication_clock_evidence_sha256=self.clock_export(target, original, clocks))
        self.spec = dict(schema=packet.REQUEST, cutoff=self.cutoff, calendar_origin_session='2018-03-01',
                         through_session='2018-03-29', vintage=dict(root='rtdsm', generations=provenance),
                         price_sources=self.price_sources, objects=self.objects,
                         policy_window=dict(available_at='2018-03-29T00:00:00Z',expires_at='2018-04-30T00:00:00Z'),
                         trial_identity=dict(signal='PACKET_FIXTURE', mechanism='SYNTHETIC', book='NO BOOK', window='NONE'))

    def put(self, name, body):
        sha = digest(body)
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        self.objects[sha] = packet.ref(name, sha)
        return sha

    def clock_export(self, target, origin, clocks):
        document = dict(schema=packet.CLOCK, original_sha256=origin, time_source_sha256=clocks,
                        price_rows_sha256=digest(encoded({target:self.prices[target]})))
        return self.put(f'evidence/{target}_clock.json', encoded(document))

    def stage(self):
        raw = encoded(self.prices)
        (self.root/'prices.json').write_bytes(raw)
        self.spec['prices'] = packet.ref('prices.json', digest(raw))
        (self.root/'source.json').write_bytes(encoded(self.spec))
        return packet.stage(self.root, 'source.json')

    def test_full_private_root_round_trip_and_exact_external_pin(self):
        with patch.object(packet.direction, 'forecast', side_effect=AssertionError('training reached')):
            candidate = self.stage()
            self.assertEqual(self.stage(), candidate)
            self.assertEqual(candidate['horizons_sessions'], [21, 63, 126])
            self.assertEqual(candidate['status'], 'INDEPENDENT_POLICY_REVIEW_REQUIRED')
            self.assertFalse(candidate['training_executed'])
            self.assertEqual(candidate['price_coverage']['QQQ']['missing_closes'], 1)
            self.assertEqual(candidate['price_coverage']['SPY']['late_closes'], 1)
            self.assertEqual(candidate['common_on_time_closes'], len(self.sessions)-2)
            self.assertFalse((self.root/'learning_request.json').exists())
            wrong = '0'*64
            with self.assertRaises(FileNotFoundError):
                packet.seal(self.root, wrong)
            self.assertFalse((self.root/'learning_request.json').exists())
            pin = candidate['candidate_policy_sha256']
            self.assertEqual(packet.seal(self.root, pin), packet.seal(self.root, pin))
            payload, policy, resolve = cycle.load_learning(self.root, pin)
            prepared = packet.direction.prepare(payload, policy, pin, resolve)
            self.assertEqual(len(prepared['days']), len(self.sessions))
            self.assertEqual(len({obs['source_id'] for obs in payload['observations']}), 3)

    def test_edited_observation_clock_cannot_reuse_original_clock_receipt(self):
        self.prices['SPY'][0]['available_at'] = self.sessions[0]['close_utc']
        with self.assertRaisesRegex(ValueError, 'PRICE_CLOCK_SCOPE'):
            self.stage()
        self.assertFalse((self.root/'a4_learning_candidates').exists())

    def test_forward_only_price_cannot_assert_collection_before_close(self):
        origin = self.prices['SPY'][0]['original_sha256']
        self.price_sources[origin]['historical_use'] = 'FORWARD_CAPTURE_ONLY'
        for row, session in zip(self.prices['SPY'], self.sessions):
            row['collected_at'] = (packet.free.utc(session['close_utc'])-timedelta(seconds=1)).isoformat()
        clocks = next(sha for sha, r in self.objects.items() if r['path']=='evidence/SPY_timestamps')
        self.price_sources[origin]['price_publication_clock_evidence_sha256'] = self.clock_export('SPY', origin, clocks)
        with self.assertRaisesRegex(ValueError, 'FORWARD_CAPTURE_CLOCK'):
            self.stage()

    def test_tamper_or_missing_vintage_original_blocks_canonical_request(self):
        pin = self.stage()['candidate_policy_sha256']
        clock_file = self.root/'evidence/SPY_timestamps'
        original = clock_file.read_bytes()
        clock_file.write_bytes(b'edited timestamp proof')
        with self.assertRaisesRegex(ValueError, 'ARTIFACT_HASH'):
            packet.seal(self.root, pin)
        self.assertFalse((self.root/'learning_request.json').exists())
        clock_file.write_bytes(original)
        generation = self.spec['vintage']['generations']['rtdsm_ruc']['generation_sha256']
        (self.root/'rtdsm/generations'/f'{generation}.json').unlink()
        with self.assertRaises(FileNotFoundError):
            packet.seal(self.root, pin)
        self.assertFalse((self.root/'learning_request.json').exists())

    def test_request_cannot_read_a_path_outside_the_input_root(self):
        with self.assertRaisesRegex(ValueError, 'INPUT_PATH'):
            packet.stage(self.root, '../source.json')


if __name__ == '__main__':
    unittest.main()
