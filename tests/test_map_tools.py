"""Calibration policy must distinguish measured finishes from censored samples."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from calibrate_maps import recommend_limits


class CalibrationTests(unittest.TestCase):
    def rows(self):
        return [{'players': n, 'summary': {'turns': t, 'outcome': {'reason': 'target_score'}}}
                for n, t in [(2, 278), (3, 337), (4, 363), (5, 413), (6, 367), (7, 371), (8, 341)]]

    def test_margin_rounding_and_increasing_caps(self):
        self.assertEqual(recommend_limits(self.rows()), {2: 400, 3: 500, 4: 600, 5: 700, 6: 800, 7: 900, 8: 1000})

    def test_unfinished_games_are_not_treated_as_target_score_durations(self):
        rows = self.rows()
        rows[0]['summary']['outcome']['reason'] = 'max_turns'
        with self.assertRaisesRegex(ValueError, 'censored'):
            recommend_limits(rows)

    def test_incomplete_player_set_cannot_calibrate_all_defaults(self):
        with self.assertRaisesRegex(ValueError, 'all seven'):
            recommend_limits(self.rows()[:1])


if __name__ == '__main__':
    unittest.main()
