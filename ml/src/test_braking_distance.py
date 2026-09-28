import unittest
from prepare_data import distance_evidence, interpolated_position


def track(offset=0, direction=1, lateral=0):
    return [(i / 10, {'x': direction * 20 * i / 10 + offset, 'y': lateral})
            for i in range(31)]


class DistanceTests(unittest.TestCase):
    def test_later_timestamp_at_same_point_is_not_later_braking(self):
        evidence = distance_evidence(track(-20), track(), 2, 1, 1, 1.9, .9)
        self.assertAlmostEqual(evidence['distance_m'], 0)
        self.assertLess(evidence['lower_bound_m'], 5)

    def test_further_down_same_approach_passes(self):
        evidence = distance_evidence(track(), track(), 2, 1, 1, 1.9, .9)
        self.assertAlmostEqual(evidence['distance_m'], 20)
        self.assertAlmostEqual(evidence['lower_bound_m'], 14)

    def test_observed_advantage_under_five_metres_is_ambiguous(self):
        evidence = distance_evidence(track(-16), track(), 2, 1, 1, 1.9, .9)
        self.assertAlmostEqual(evidence['distance_m'], 4)
        self.assertLess(evidence['distance_m'], 5)

    def test_bad_sampling_or_different_approaches_rejected(self):
        self.assertIsNone(distance_evidence(track(), track(), 2, 1, 1, 1, .9))
        self.assertIsNone(distance_evidence(track(), track(direction=-1), 2, 1, 1, 1.9, .9))
        self.assertIsNone(distance_evidence(track(lateral=30), track(), 2, 1, 1, 1.9, .9))
        self.assertIsNone(interpolated_position([(0, {'x': 0, 'y': 0}),
                                               (2, {'x': 40, 'y': 0})], 1))
        self.assertIsNone(interpolated_position(track(), -1))


if __name__ == '__main__':
    unittest.main()
