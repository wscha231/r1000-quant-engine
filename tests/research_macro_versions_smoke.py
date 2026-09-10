#!/usr/bin/env python3
"""Offline checks of public graph parsing and explicit current-only evidence."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.collect_research_macro_versions import NoRedirect, parse_fred


class MacroTests(unittest.TestCase):
    def parse(self, raw):
        return parse_fred(raw, "DGS10", "2019-01-01", "2019-01-03", "2026-09-10T00:00:00Z")

    def test_missing_data_does_not_become_zero_or_historical_pit(self):
        rows=self.parse(b"observation_date,DGS10\n2019-01-01,.\n2019-01-02,2.66\n")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["value"],2.66)
        self.assertEqual(rows[0]["available_at"],"2026-09-10T00:00:00Z")
        self.assertEqual(rows[0]["evidence"],"current_only")

    def test_bad_schema_duplicate_future_nan_or_empty_fail(self):
        for raw in [b"<html>access denied</html>", b"DATE,DGS10\n2019-01-02,2\n2019-01-02,3\n",
                    b"DATE,DGS10\n2026-09-10,2\n",b"DATE,DGS10\n2019-01-02,NaN\n",
                    b"DATE,DGS10\n2019-01-02,.\n"]:
            with self.assertRaises(ValueError):self.parse(raw)

    def test_redirects_cannot_change_source(self):
        with self.assertRaisesRegex(ValueError,"redirect_rejected"):
            NoRedirect().redirect_request(None,None,302,"",{},"https://example.com")

    def test_unknown_series_cannot_be_requested(self):
        with self.assertRaisesRegex(ValueError,"series_not_allowlisted"):
            parse_fred(b"", "untrusted", "2019-01-01", "2019-01-03", "2026-09-10T00:00:00Z")


if __name__ == "__main__":
    unittest.main(verbosity=2)
