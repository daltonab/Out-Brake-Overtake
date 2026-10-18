import unittest

from prepare_data import (heading_change_before, nearby_traffic_count, prior_lap_duration,
                          rate_before)


class ContextFeatureTests(unittest.TestCase):
    def test_speed_rate_uses_only_history(self):
        items = [(0, {'speed': 100}), (1, {'speed': 110}), (2, {'speed': 999})]
        self.assertEqual(rate_before(items, 1, 'speed'), 10)

    def test_heading_change_is_past_only(self):
        items = [(0, {'x': 0, 'y': 0}), (.75, {'x': 1, 'y': 0}),
                 (1.5, {'x': 1, 'y': 1}), (2, {'x': 9, 'y': 9})]
        self.assertAlmostEqual(heading_change_before(items, 1.5), 90)

    def test_prior_lap_never_reads_current_lap_duration(self):
        items = [(0, {'lap_duration': 90}), (90, {'lap_duration': 91})]
        self.assertEqual(prior_lap_duration(items, 100), 90)

    def test_traffic_count_requires_a_close_interval(self):
        intervals = {1: [(1, {'interval': .4})], 2: [(1, {'interval': 1.4})],
                     3: [(1, {'interval': .8})]}
        self.assertEqual(nearby_traffic_count(intervals, 1), 2)


if __name__ == '__main__':
    unittest.main()
