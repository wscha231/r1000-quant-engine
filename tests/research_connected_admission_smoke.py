"""Pinned-engine boundary tests; fixture observations are not market results."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import admit_connected_research as m


class Admission(unittest.TestCase):
    def capture(self,root):
        raw=b'{}';h=m.sha(raw);(root/(h+'.raw')).write_bytes(raw)
        receipts=[dict(raw_sha256=h,bytes=2)]
        (root/'receipts.json').write_bytes(m.canonical(receipts))
        report=dict(schema_version='research-source-connection-v1',data_kind='REAL',source_receipt_count=1,
                    source_receipts_hash=m.sha(m.canonical(receipts)),generated_at='2026-09-10T12:00:00Z',end='2026-09-09',
                    sources=[{'name':'US_prices','data':{'securities':[{'ticker':'NVDA','close':100.,'last':'2026-09-09'}]}}])
        (root/'connection_report.json').write_bytes(m.canonical(report))

    def test_changed_raw_rejected_before_engine(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.capture(root)
            next(root.glob('*.raw')).write_bytes(b'changed')
            self.assertRaisesRegex(ValueError,'raw_source_mutated',m.verify_capture,root)

    def test_incomplete_connected_data_not_allocated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.capture(root)
            r=m.run(root,os.environ['RESEARCH_ENGINE_SOURCE'])
        self.assertFalse(r['readiness']['portfolio_proposal_ready'])
        self.assertEqual(r['workflow']['universe_count'],1)
        self.assertEqual(r['workflow']['market_admitted_count'],0)
        self.assertIsNone(r['portfolio_weights']);self.assertIsNone(r['metrics'])
        self.assertIn('financials:missing',r['coverage'][0]['blockers'])

    def test_receipts_cannot_be_relabelled(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.capture(root)
            p=root/'connection_report.json';r=json.loads(p.read_text());r['source_receipts_hash']='0'*64;p.write_bytes(m.canonical(r))
            self.assertRaisesRegex(ValueError,'receipt_binding',m.verify_capture,root)


if __name__=='__main__':unittest.main()
