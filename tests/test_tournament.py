"""Schedule fairness, frozen inputs and tournament result contracts."""
from collections import Counter
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
try:
    from tournament_lib.schedule import permutations_for, coverage
    from tournament_lib.storage import create_plan, load_plan, locked, atomic_json
except ImportError:
    permutations_for = coverage = create_plan = load_plan = locked = atomic_json = None


class ScheduleTests(unittest.TestCase):
    def test_balanced_schedules_cover_every_pair_of_distinct_slots(self):
        self.assertIsNotNone(permutations_for, 'tournament scheduler is missing')
        for n, count, pair_count in [(2,2,1),(3,6,1),(4,12,1),(5,20,1),(6,60,2),(7,42,1),(8,56,1)]:
            with self.subTest(n=n):
                rows = permutations_for(n, 'balanced')
                self.assertEqual(len(rows), count)
                self.assertEqual(len(set(rows)), count)
                self.assertTrue(all(sorted(row) == list(range(n)) for row in rows))
                singles = Counter((i,row[i]) for row in rows for i in range(n))
                pairs = Counter((i,j,row[i],row[j]) for row in rows for i in range(n) for j in range(n) if i != j)
                self.assertEqual(len(singles), n*n)
                self.assertEqual(set(singles.values()), {count//n})
                self.assertEqual(len(pairs), n*n*(n-1)*(n-1))
                self.assertEqual(set(pairs.values()), {pair_count})

    def test_quick_rotations_balance_slots_but_not_every_pair(self):
        self.assertIsNotNone(permutations_for)
        for n in range(2,9):
            rows = permutations_for(n, 'quick')
            self.assertEqual(len(rows), n)
            self.assertEqual(Counter((i,row[i]) for row in rows for i in range(n)), Counter({(i,s):1 for i in range(n) for s in range(n)}))
        self.assertLess(coverage(permutations_for(8,'quick'))['pair_coverage'], 1)
        self.assertEqual(coverage(permutations_for(8,'balanced'))['pair_coverage'], 1)


class PlanFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.config = {'version':1, 'runner':'fff-runner', 'mode':'balanced', 'repeats':2,
                       'ais':[{'id':'a','name':'甲|AI','library':'shared.so'}, {'id':'b','name':'乙','library':'shared.so'}],
                       'lineups':[{'id':'duel','players':2,'map':'map.ron','ais':['a','b']}]}
        for name in ('fff-runner','fff-ai-worker'):
            path = self.base/name
            path.write_text('#!/bin/sh\nexit 0\n')
            path.chmod(0o755)
        (self.base/'shared.so').write_bytes(b'library')
        (self.base/'map.ron').write_text('(players: 2)')
        self.config_path = self.base/'config.json'
        self.root = self.base/'output'

    def make(self, config=None, **kwargs):
        self.assertIsNotNone(create_plan, 'plan creator is missing')
        self.config_path.write_text(json.dumps(self.config if config is None else config))
        return create_plan(self.config_path, self.root, **kwargs)


class PlanTests(PlanFixture):
    def test_plan_freezes_files_and_seeds_follow_identity(self):
        plan = self.make()
        self.assertEqual(len(plan['matches']), 4)
        for block in plan['blocks']:
            rows = [m for m in plan['matches'] if m['block'] == block['id']]
            self.assertEqual({m['engine_seed'] for m in rows}, {block['engine_seed']})
            for row in rows:
                self.assertEqual(row['ai_seeds'], [block['ai_seeds'][ai] for ai in row['slots']])
            self.assertEqual({tuple(m['slots']) for m in rows}, {('a','b'),('b','a')})
            self.assertNotEqual(block['ai_seeds']['a'], block['ai_seeds']['b'])
        self.assertEqual(load_plan(self.root), plan)
        (self.base/'shared.so').write_bytes(b'changed source: frozen copy remains usable')
        self.assertEqual(load_plan(self.root), plan)
        (self.root/plan['ais'][0]['path']).write_bytes(b'changed snapshot')
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            load_plan(self.root)

    def test_plan_rejects_changed_schedule_and_binary(self):
        self.make()
        saved=(self.root/'plan.json').read_text()
        (self.root/'plan.json').write_text(saved.replace('"engine_seed":', '"engine_seed": 0, "unused":',1))
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            load_plan(self.root)
        (self.root/'plan.json').write_text(saved)
        (self.base/'fff-ai-worker').write_text('changed worker')
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            load_plan(self.root)

    def test_config_rejects_ambiguous_ids_and_incorrect_lineups(self):
        mutations = [lambda c:c['ais'].append(copy.deepcopy(c['ais'][0])),
                     lambda c:c['lineups'][0].update(ais=['a','a']),
                     lambda c:c['lineups'][0].update(players=9),
                     lambda c:c['lineups'][0].update(ais=['a']),
                     lambda c:c['ais'][0].update(id='../escape'),
                     lambda c:c.update(repeats=True),
                     lambda c:c.update(mode='unknown')]
        for mutation in mutations:
            cfg=copy.deepcopy(self.config)
            mutation(cfg)
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                self.make(cfg)
        self.assertFalse(self.root.exists())

    def test_lock_excludes_other_writers(self):
        self.make()
        with locked(self.root):
            with self.assertRaisesRegex(ValueError, 'locked'):
                with locked(self.root):
                    self.fail('second writer entered')


if __name__ == '__main__':
    unittest.main()
