import unittest
from prepare_pooled import assign_splits, driver_identity, exclusion, neutralized
from prepare_data import timeline
from prepare_data import prepare_session, build_session
from pathlib import Path
from unittest.mock import Mock, patch


class PooledTests(unittest.TestCase):
    def test_track_clear_releases_safety_car_and_lingering_sectors(self):
        for deployment in ('SAFETY CAR DEPLOYED', 'VIRTUAL SAFETY CAR DEPLOYED'):
            messages = [(1, {'category': 'SafetyCar', 'message': deployment}),
                        (2, {'flag': 'YELLOW', 'scope': 'Sector', 'sector': 3}),
                        (3, {'flag': 'CLEAR', 'scope': 'Track', 'message': 'TRACK CLEAR'})]
            self.assertTrue(neutralized(2.9, messages))
            self.assertFalse(neutralized(3, messages))

    def test_sector_clear_pit_green_and_ending_do_not_release_safety_car(self):
        messages = [(1, {'message': 'SAFETY CAR DEPLOYED'}),
                    (2, {'flag': 'CLEAR', 'scope': 'Sector', 'sector': 3}),
                    (3, {'flag': 'GREEN', 'scope': 'Track', 'message': 'GREEN LIGHT - PIT EXIT OPEN'}),
                    (4, {'message': 'SAFETY CAR IN THIS LAP'}),
                    (5, {'message': 'VIRTUAL SAFETY CAR ENDING'})]
        self.assertTrue(neutralized(5, messages))

    def test_red_flag_requires_restart_even_after_track_clear(self):
        messages = [(1, {'message': 'SAFETY CAR DEPLOYED'}),
                    (2, {'flag': 'RED', 'scope': 'Track'}),
                    (3, {'flag': 'CLEAR', 'scope': 'Track', 'message': 'TRACK CLEAR'}),
                    (4, {'category': 'SessionStatus', 'message': 'SESSION STARTED'})]
        self.assertTrue(neutralized(3, messages))
        self.assertFalse(neutralized(4, messages))

    def test_restart_does_not_clear_active_safety_car(self):
        messages = [(1, {'flag': 'RED'}), (2, {'message': 'SAFETY CAR DEPLOYED'}),
                    (3, {'category': 'SessionStatus', 'message': 'SESSION STARTED'})]
        self.assertTrue(neutralized(3, messages))

    def test_local_clear_only_clears_its_own_sector(self):
        messages = [(1, {'flag': 'YELLOW', 'scope': 'Sector', 'sector': 1}),
                    (2, {'flag': 'DOUBLE YELLOW', 'scope': 'Sector', 'sector': 2}),
                    (3, {'flag': 'CLEAR', 'scope': 'Sector', 'sector': 1}),
                    (4, {'flag': 'CLEAR', 'scope': 'Sector', 'sector': 2})]
        self.assertTrue(neutralized(3, messages))
        self.assertFalse(neutralized(4, messages))

    def test_shared_session_is_not_rebuilt_for_each_driver(self):
        session = Path('/tmp/pooled-unit-session')
        reader = Mock(side_effect=lambda path: [
            {'driver_number': 1, 'position': 1, 'date': '2023-01-01T00:00:00Z'},
            {'driver_number': 2, 'position': 2, 'date': '2023-01-01T00:00:00Z'},
        ] if path.name == 'position' else [])
        with patch('prepare_data.coordinate_scale', return_value=None) as scale:
            context = prepare_session(session, reader)
            initial_reads = reader.call_count
            for driver in (1, 2):
                self.assertEqual(build_session(session, driver, reader=reader, context=context), ([], 0))
            self.assertEqual(reader.call_count, initial_reads)
            scale.assert_called_once()
            with self.assertRaises(ValueError):
                build_session(Path('/tmp/different-session'), 1, context=context)

    def test_number_changes_keep_identity(self):
        self.assertEqual(driver_identity({'full_name': 'Max VERSTAPPEN', 'driver_number': 1}),
                         driver_identity({'full_name': 'Max Verstappen', 'driver_number': 3}))

    def test_weekends_stay_together_and_split_is_reproducible(self):
        rows = [dict(year=2025, meeting_key=m, session_name=s, attacker_driver_number=n)
                for m in range(10) for s in ('Sprint', 'Race') for n in (1, 4)]
        assign_splits(rows)
        for m in range(10):
            self.assertEqual(len({r['dataset_split'] for r in rows if r['meeting_key'] == m}), 1)
        self.assertEqual({r['dataset_split'] for r in rows}, {'train', 'validation', 'test'})
        other = [dict(r) for r in reversed(rows)]
        assign_splits(other)
        self.assertEqual(rows, list(reversed(other)))

    def test_pit_out_lap_excludes_preceding_in_lap_for_either_driver(self):
        row = dict(brake_onset_at='2023-01-01T00:00:10Z', attacker_driver_number=1,
                   defender_driver_number=2)
        windows = [dict(attacker_driver_number=1, defender_driver_number=2,
                        date_start='2023-01-01T00:00:00Z', date_end='2023-01-01T00:00:20Z')]
        laps = {n: timeline([
            dict(lap_number=2, date_start='2023-01-01T00:00:00Z'),
            dict(lap_number=3, date_start='2023-01-01T00:01:00Z', is_pit_out_lap=n == 2)
        ], date_field='date_start') for n in (1, 2)}
        self.assertEqual(exclusion(row, windows, laps, [], []), 'pit_in_or_out_lap')
        self.assertEqual(exclusion(row, [], laps, [], []), 'outside_qualified_window')


if __name__ == '__main__':
    unittest.main()
