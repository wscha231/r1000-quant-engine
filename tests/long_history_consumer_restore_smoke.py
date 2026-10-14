"""Synthetic integrity faults, distinct from real Drive recovery evidence."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.long_history_lake import Lake,LocalTransport,PREFIX
from tools.long_history_consumer_restore import SnapshotReadOnlyTransport,restore_consumer


class ConsumerRestoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.remote=LocalTransport(self.root/'export')
        lake=Lake(self.remote,self.root/'writer')
        lake.dataset('sec/0000000001',[b'original'],[
            dict(end='2016-12-31',filed='2017-02-01',value=100,concept='Revenue',unit='USD')],
            dict(evidence='SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT'))
        self.first=lake.publish('one',{})

    def run_reader(self,**kwargs):
        transport=SnapshotReadOnlyTransport(self.root/'export')
        self.output=self.root/('consumer-'+str(len(list(self.root.glob('consumer-*')))))
        return restore_consumer(transport,self.output,
            commit_sha256=self.first['commit_sha256'],
            catalog_sha256=kwargs.get('catalog_sha256',self.first['catalog_sha256']),
            datasets=['sec/0000000001'],cutoff='2018-01-01')

    def test_real_api_control_uses_no_provider_or_remote_writes(self):
        with patch('tools.long_history_lake.get_public',side_effect=AssertionError('provider')), \
             patch.object(SnapshotReadOnlyTransport,'write',side_effect=AssertionError('write')):
            result=self.run_reader()
        self.assertEqual(result['consumer_rows'],1)
        self.assertEqual((result['provider_calls'],result['remote_writes']),(0,0))
        self.assertFalse(result['verified_execution'])
        self.assertFalse(result['source_admitted'])

    def test_pin_does_not_follow_new_generation(self):
        next_lake=Lake(self.remote,self.root/'second')
        next_lake.publish('two',{})
        self.assertEqual(self.run_reader()['generation'],1)

    def test_missing_or_corrupt_pack_blocks_sql(self):
        path=next((self.root/'export'/PREFIX/'packs').iterdir())
        original=path.read_bytes()
        for raw in (b'corrupt',None):
            with self.subTest(raw=raw):
                if raw is None: path.unlink()
                else: path.write_bytes(raw)
                with self.assertRaises((OSError,ValueError)): self.run_reader()
                self.assertFalse((self.output/'slice.sqlite').exists())
                path.write_bytes(original)

    def test_wrong_catalog_refuses_without_sql(self):
        with self.assertRaisesRegex(ValueError,'consumer_pin_mismatch'):
            self.run_reader(catalog_sha256='0'*64)
        self.assertFalse((self.output/'slice.sqlite').exists())

    def test_transport_never_creates_missing_root_and_refuses_writes(self):
        absent=self.root/'absent'
        with self.assertRaisesRegex(ValueError,'snapshot_missing'):
            SnapshotReadOnlyTransport(absent)
        self.assertFalse(absent.exists())
        with self.assertRaisesRegex(ValueError,'read_only_snapshot'):
            SnapshotReadOnlyTransport(self.root/'export').write('path',b'bytes')

    def test_transport_budget_refuses_before_opened_data_read(self):
        transport=SnapshotReadOnlyTransport(self.root/'export')
        path=f'{PREFIX}/commits/{self.first["commit_sha256"]}'
        with patch('tools.long_history_consumer_restore.MAX_READ_BYTES',1):
            with self.assertRaisesRegex(ValueError,'snapshot_read_budget'):
                transport.read(path)
        self.assertEqual(transport.read_bytes,0)


if __name__=='__main__': unittest.main()
