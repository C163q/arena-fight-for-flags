"""Count real rows, independently of the league construction."""
from collections import Counter
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from tournament_lib.league_schedule import schedule, coverage


class LeagueScheduleTests(unittest.TestCase):
    def test_all_small_pools_have_exact_single_and_pair_seats(self):
        for candidates in range(1, 17):
            for players in range(2, 9):
                with self.subTest(candidates=candidates, players=players):
                    rows, method = schedule(candidates, players)
                    self.assertTrue(method)
                    singles, pairs = Counter(), Counter()
                    for row in rows:
                        self.assertEqual(len(row), players)
                        self.assertEqual(len(set(row)), players)
                        for slot, ai in enumerate(row):
                            if ai >= candidates:
                                self.assertLess(candidates, players)
                                continue
                            singles[ai, slot] += 1
                            for other_slot, other in enumerate(row):
                                if other < candidates and other != ai:
                                    pairs[ai, other, slot, other_slot] += 1
                    self.assertEqual(len(singles), candidates * players)
                    self.assertEqual(len(set(singles.values())), 1)
                    if candidates > 1:
                        self.assertEqual(len(pairs), candidates * (candidates-1) * players * (players-1))
                        self.assertEqual(len(set(pairs.values())), 1)
                    actual = coverage(rows, candidates, players)
                    self.assertEqual(actual['matches'], len(rows))

    def test_sixteen_in_eight_needs_240_games(self):
        rows, _ = schedule(16, 8)
        self.assertEqual(len(rows), 240)
        self.assertEqual(coverage(rows, 16, 8)['appearances_min'], 120)
        self.assertEqual(coverage(rows, 16, 8)['seat_min'], 15)
        self.assertEqual(coverage(rows, 16, 8)['pair_min'], 56)
        self.assertEqual(coverage(rows, 16, 8)['pair_seat_min'], 1)

    def test_fifteen_in_eight_uses_compact_geometry(self):
        rows, _ = schedule(15, 8)
        self.assertEqual(len(rows), 840)

    def test_invalid_rows_and_large_fallback_are_rejected(self):
        for args in [(True, 3), (0, 3), (3, 9)]:
            with self.assertRaises(ValueError):
                schedule(*args)
        with self.assertRaisesRegex(ValueError, 'limit'):
            schedule(30, 8, max_rows=10000)
        for rows in [[(0, 0)], [(0, 1)], [(0, 2), (1, 0)]]:
            with self.assertRaises(ValueError):
                coverage(rows, 3, 2)
