import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone

from download_openf1 import (Downloader, completed_races, has_attack_telemetry,
                             parquet_table, same_lap_overtakes)


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        Downloader.process_next_request_at = 0

    def tearDown(self):
        Downloader.process_next_request_at = 0

    def test_attack_telemetry_requires_braking_pair_and_speed_advantage(self):
        def samples(number, speeds, brakes):
            return [{'driver_number': number, 'date': f'2025-01-01T00:00:0{i}Z',
                     'speed': speed, 'brake': brake}
                    for i, (speed, brake) in enumerate(zip(speeds, brakes))]
        rows = {
            1: samples(1, [250, 250, 250, 250], [0, 0, 1, 1]),
            2: samples(2, [220, 220, 220, 220], [0, 1, 1, 0]),
        }
        self.assertTrue(has_attack_telemetry(rows, 1, {2}))
        for row in rows[1]:
            row['speed'] = 230
        self.assertFalse(has_attack_telemetry(rows, 1, {2}))

    def test_lapped_passes_are_excluded(self):
        laps = [
            {'driver_number': 1, 'lap_number': 5, 'date_start': '2025-01-01T00:00:00Z'},
            {'driver_number': 2, 'lap_number': 5, 'date_start': '2025-01-01T00:00:01Z'},
            {'driver_number': 3, 'lap_number': 4, 'date_start': '2025-01-01T00:00:01Z'},
        ]
        base = {'overtaking_driver_number': 1, 'date': '2025-01-01T00:00:10Z'}
        overtakes = [{**base, 'overtaken_driver_number': 2}, {**base, 'overtaken_driver_number': 3}]
        filtered = same_lap_overtakes(overtakes, laps)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]['overtaken_driver_number'], 2)
        self.assertTrue(filtered[0]['same_lap'])

    def test_mixed_numeric_and_lapped_values_are_parquet_safe(self):
        import pyarrow as pa
        table = parquet_table(pa, [{'gap_to_leader': 2.5}, {'gap_to_leader': '+4 LAPS'}])
        self.assertEqual(table.to_pylist(), [{'gap_to_leader': '2.5'}, {'gap_to_leader': '+4 LAPS'}])

    def test_only_completed_grand_prix_races(self):
        template = {'date_end': '2025-01-01T00:00:00+00:00'}
        rows = [dict(template, session_name=name) for name in ('Race', 'Sprint', 'Practice 1', 'Testing')]
        rows += [dict(template, session_name='Race', is_cancelled=True),
                 {'session_name': 'Race', 'date_end': '2026-01-01T00:00:00+00:00'}]
        self.assertEqual(completed_races(rows, datetime(2025, 2, 1, tzinfo=timezone.utc)), rows[:1])

    def test_parquet_roundtrip_and_restart(self):
        with TemporaryDirectory() as folder:
            rows = [{'driver_number': 16, 'brake': 100, 'throttle': 104, 'date': '2025-01-01T00:00:00Z'}]
            with patch('download_openf1.urlopen', return_value=io.BytesIO(json.dumps(rows).encode())) as request:
                first = Downloader(Path(folder), spacing=0)
                params = {'session_key': 10, 'date>': rows[0]['date']}
                self.assertEqual(first.get('car_data', params), rows)
                second = Downloader(Path(folder), spacing=0)
                self.assertEqual(second.get('car_data', params), rows)
                self.assertEqual(request.call_count, 1)
                self.assertEqual(parse_qs(urlparse(request.call_args.args[0]).query)['date>'], [rows[0]['date']])

    def test_429_retries_after_persisted_cooldown(self):
        with TemporaryDirectory() as folder:
            error = HTTPError('url', 429, 'rate limited', {'Retry-After': '120'}, None)
            with patch('download_openf1.urlopen', side_effect=[error, io.BytesIO(b'[]')]) as request, \
                    patch('download_openf1.time.time', return_value=1000), \
                    patch('download_openf1.time.sleep') as sleep:
                client = Downloader(Path(folder), spacing=0)
                self.assertEqual(client.get('laps', {'session_key': 10}), [])
                self.assertEqual(request.call_count, 2)
                sleep.assert_called_once_with(120)
                restored = Downloader(Path(folder))
                state = next(iter(restored.state['requests'].values()))
                self.assertEqual(state['status'], 'complete')
                self.assertEqual(state['rate_limit_retries'], 1)

    def test_failed_request_is_requested_on_manual_resume(self):
        with TemporaryDirectory() as folder:
            client = Downloader(Path(folder), spacing=0)
            with patch('download_openf1.urlopen', side_effect=HTTPError('url', 404, 'missing', {}, None)):
                with self.assertRaises(HTTPError):
                    client.get('laps', {'session_key': 10})
            with patch('download_openf1.urlopen', return_value=io.BytesIO(b'[]')) as request:
                self.assertEqual(Downloader(Path(folder), spacing=0).get('laps', {'session_key': 10}), [])
                self.assertEqual(request.call_count, 1)
                self.assertEqual(Downloader(Path(folder), spacing=0).get('laps', {'session_key': 10}), [])
                self.assertEqual(request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
