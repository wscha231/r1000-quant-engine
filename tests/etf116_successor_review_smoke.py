"""New exact-successor review boundaries; synthetic rows, no service calls."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.etf116_research_metrics_h1 import validate_series, verified_session_close, RefuseInput
from tools.etf116_existing_cron_planner_h1 import plan_existing_trigger


class SuccessorReviewTests(unittest.TestCase):
    def validate(self, day='2026-10-16', available='2026-10-16T20:00:00Z'):
        row = {'ticker': 'SPY', 'date': day, 'tr_index': 100., 'basis': 'NAV_TR_INDEX',
               'available_at_utc': available, 'source_sha256': '1' * 64}
        return validate_series([row], [day], ticker='SPY', asof=day,
                               decision_at='2026-12-01T00:00:00Z')

    def test_same_day_midnight_and_preclose_refuse(self):
        for clock in ('2026-10-16T00:00:00Z', '2026-10-16T19:59:59Z'):
            with self.subTest(clock=clock), self.assertRaisesRegex(RefuseInput, 'BEFORE_SESSION_CLOSE'):
                self.validate(available=clock)

    def test_actual_close_and_equivalent_offset_are_allowed(self):
        for clock in ('2026-10-16T20:00:00Z', '2026-10-16T16:00:00-04:00'):
            result = self.validate(available=clock)
            self.assertEqual(result['observations']['2026-10-16'], 100.)

    def test_half_day_uses_existing_reader_calendar(self):
        verified_session_close.cache_clear()
        from tools import research_data_access as reader
        with patch.object(reader, '_session_close', wraps=reader._session_close) as close:
            self.validate(day='2026-11-27', available='2026-11-27T18:00:00Z')
            self.assertEqual(close.call_count, 1)
        with self.assertRaisesRegex(RefuseInput, 'BEFORE_SESSION_CLOSE'):
            self.validate(day='2026-11-27', available='2026-11-27T17:59:59Z')

    def test_unverified_same_date_calendar_refuses(self):
        verified_session_close.cache_clear()
        from tools.research_data_access import ContractError
        with patch('tools.research_data_access._session_close', side_effect=ContractError('FIXTURE')):
            with self.assertRaisesRegex(RefuseInput, 'SESSION_CLOSE_UNVERIFIED'):
                self.validate()
        verified_session_close.cache_clear()

    def test_conservative_next_day_release_does_not_invent_a_close(self):
        with patch('tools.etf116_research_metrics_h1.verified_session_close', side_effect=AssertionError('NO_GUESS')):
            self.validate(available='2026-10-17T00:00:00Z')

    def planner(self, checkpoint, enabled=True):
        return plan_existing_trigger(session='2026-10-16', close_utc='2026-10-16T20:00:00Z',
            now_utc='2026-10-16T23:30:00Z', calendar_session_verified=True,
            provider_available_at_utc='2026-10-16T20:30:00Z',
            prior_eod_processed_session='2026-10-15', prior_holdings_refresh_session=checkpoint,
            schedule_flag_enabled=enabled)

    def test_future_holdings_checkpoint_same_or_later_week_refuses(self):
        for day in ('2026-10-17', '2026-10-19', '2027-01-01'):
            for enabled in (False, True):
                with self.subTest(day=day, enabled=enabled), self.assertRaisesRegex(
                        RefuseInput, 'HOLDINGS_REFRESH_FUTURE_CHECKPOINT'):
                    self.planner(day, enabled)

    def test_current_and_prior_week_remain_prepared_without_authority(self):
        for day, due in [('2026-10-16', False), ('2026-10-09', True), (None, True)]:
            result = self.planner(day)
            self.assertEqual(result['holdings_refresh_due'], due)
            self.assertFalse(result['dispatch_performed'])
            self.assertFalse(result['publish_enabled'])


if __name__ == '__main__':
    unittest.main()
