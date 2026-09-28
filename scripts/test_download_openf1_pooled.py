import unittest

from download_openf1_pooled import merge_ranges, pair_windows, retryable, MissingSourceData
from urllib.error import HTTPError
from datetime import datetime, timezone
from download_openf1_pooled import completed_racing_sessions
from download_openf1_pooled import required_source
from unittest.mock import Mock


class PooledDownloaderTests(unittest.TestCase):
    def test_empty_event_responses_do_not_retry(self):
        for endpoint in ('overtakes', 'intervals', 'race_control'):
            client = Mock()
            client.get.return_value = []
            self.assertEqual(required_source(client, 123, endpoint), [])
            self.assertEqual(client.get.call_count, 1)

    def test_missing_laps_and_event_404_are_not_valid_empty_results(self):
        client = Mock()
        client.get.return_value = []
        with self.assertRaises(MissingSourceData):
            required_source(client, 123, 'laps')
        self.assertEqual(client.get.call_count, 2)
        client.get.side_effect = HTTPError('url', 404, '', {}, None)
        with self.assertRaises(MissingSourceData):
            required_source(client, 123, 'overtakes')
    def test_discovery_includes_sprints_but_not_qualifying_or_unfinished_sessions(self):
        rows = [{'session_name': name, 'date_end': '2023-01-01T12:00:00Z'}
                for name in ('Race', 'Sprint', 'Sprint Qualifying', 'Sprint Shootout',
                             'Qualifying', 'Practice 1', 'Testing')]
        rows += [dict(rows[1], is_cancelled=True),
                 dict(rows[1], date_end='2023-01-01T12:45:00Z'),
                 dict(rows[1], date_end=None)]
        self.assertEqual(completed_racing_sessions(
            rows, datetime(2023, 1, 1, 13, tzinfo=timezone.utc)), rows[:2])

    def test_permanent_http_errors_are_not_retried(self):
        for code in (400, 401, 403, 404):
            self.assertFalse(retryable(HTTPError('url', code, '', {}, None)))
        for code in (429, 500, 502, 503, 504):
            self.assertTrue(retryable(HTTPError('url', code, '', {}, None)))
        self.assertTrue(retryable(MissingSourceData('missing laps')))

    def test_pit_filter_keeps_earlier_candidate_in_long_episode(self):
        positions = [{'driver_number': n, 'position': p, 'date': '2025-01-01T00:00:00Z'}
                     for n, p in [(1, 2), (2, 1)]]
        laps = [{'driver_number': n, 'lap_number': 2, 'date_start': '2025-01-01T00:00:00Z'}
                for n in (1, 2)]
        intervals = [{'driver_number': 1, 'interval': .3,
                      'date': f'2025-01-01T00:00:{s:02d}Z'} for s in (10, 30, 50)]
        pits = [{'driver_number': 1, 'date': '2025-01-01T00:00:50Z'}]
        windows = pair_windows(intervals, positions, [], laps, .5, 15, pits)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]['end'].second, 45)
    def test_ranges_merge_only_when_overlapping(self):
        self.assertEqual(merge_ranges([(3, 5), (1, 4), (8, 9)]), [(1, 5), (8, 9)])

    def test_pair_windows_use_half_second_gap_and_preserve_confirmed_pass(self):
        positions = [
            {'driver_number': 1, 'position': 2, 'date': '2025-01-01T00:00:00Z'},
            {'driver_number': 2, 'position': 1, 'date': '2025-01-01T00:00:00Z'},
        ]
        laps = [
            {'driver_number': 1, 'lap_number': 2, 'date_start': '2025-01-01T00:00:00Z'},
            {'driver_number': 2, 'lap_number': 2, 'date_start': '2025-01-01T00:00:00Z'},
        ]
        intervals = [
            {'driver_number': 1, 'interval': .8, 'date': '2025-01-01T00:00:05Z'},
            {'driver_number': 1, 'interval': .4, 'date': '2025-01-01T00:01:00Z'},
        ]
        overtakes = [{'overtaking_driver_number': 2, 'overtaken_driver_number': 1,
                      'date': '2025-01-01T00:02:00Z'}]
        windows = pair_windows(intervals, positions, overtakes, laps, .5, 5)
        self.assertEqual(len(windows), 2)
        self.assertFalse(windows[0]['confirmed'])
        self.assertTrue(windows[1]['confirmed'])

    def test_lap_one_interval_does_not_open_candidate_window(self):
        positions = [
            {'driver_number': 1, 'position': 2, 'date': '2025-01-01T00:00:00Z'},
            {'driver_number': 2, 'position': 1, 'date': '2025-01-01T00:00:00Z'},
        ]
        laps = [
            {'driver_number': 1, 'lap_number': 1, 'date_start': '2025-01-01T00:00:00Z'},
            {'driver_number': 2, 'lap_number': 1, 'date_start': '2025-01-01T00:00:00Z'},
        ]
        intervals = [{'driver_number': 1, 'interval': .2,
                      'date': '2025-01-01T00:00:05Z'}]
        self.assertEqual(pair_windows(intervals, positions, [], laps, .5, 5), [])


if __name__ == '__main__':
    unittest.main()
