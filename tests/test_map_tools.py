"""Calibration policy must distinguish measured finishes from censored samples."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from calibrate_maps import recommend_limits, calibration_action_counts
from generate_maps import make_map, metrics, home_cells


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



class FlagTravelTests(unittest.TestCase):
    def test_all_spawn_slots_need_real_travel_to_unique_flag_sites(self):
        # Old near-home sites make a score a short shuttle; moving only one
        # team's sites or overlapping sites must not pass the geometric gate.
        for players in range(2, 9):
            with self.subTest(players=players):
                game_map = make_map(players)
                stats = metrics(game_map)
                self.assertTrue(all(6 <= d <= 8 for d in stats['nearest_flag']), stats)
                self.assertLessEqual(stats['nearest_spread'], 1)
                flags = {(f['x'], f['y']) for f in game_map['flag_points']}
                self.assertEqual(len(flags), players + 1)
                homes = {p for h in game_map['spawn_regions'] for p in home_cells(h)}
                self.assertTrue(flags.isdisjoint(homes))
                self.assertEqual(game_map['match_limits']['target_score'], 20)
                grid = game_map['terrain']
                self.assertTrue(all(c == '#' for c in grid[0] + grid[-1]))
                self.assertTrue(all(row[0] == row[-1] == '#' for row in grid))


class CalibrationActionTests(unittest.TestCase):
    def record(self, ground=False, validation='carrying_cannot_enter_flag'):
        return {'frame': {'start': {'flags': [{'location': {'state': 'ground', 'position': {'x': 4, 'y': 5}}}] if ground else []},
                         'events': [{'type': 'move', 'unit': {'team_id': 1, 'unit_id': 0},
                                     'target': {'x': 4, 'y': 5}, 'validation': validation}]}}

    def test_unforeseeable_death_drop_blocks_are_counted_without_discarding_game(self):
        result = calibration_action_counts({'ai_failures': [0, 0], 'illegal_actions': [0, 1]}, [self.record()])
        self.assertEqual(result, [0, 1])

    def test_known_flags_bad_actions_faults_and_bad_counts_still_reject_calibration(self):
        for summary, records in [
            ({'ai_failures': [0, 0], 'illegal_actions': [0, 1]}, [self.record(ground=True)]),
            ({'ai_failures': [0, 0], 'illegal_actions': [0, 1]}, [self.record(validation='self_target')]),
            ({'ai_failures': [1, 0], 'illegal_actions': [0, 0]}, []),
            ({'ai_failures': [0, 0], 'illegal_actions': [0, 2]}, [self.record()]),
        ]:
            with self.subTest(summary=summary, records=records), self.assertRaises(ValueError):
                calibration_action_counts(summary, records)

if __name__ == '__main__':
    unittest.main()
