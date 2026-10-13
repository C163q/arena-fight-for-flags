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


try:
    from tournament_lib.execution import run, collect
except ImportError:
    run = collect = None


class ExecutionTests(PlanFixture):
    def setUp(self):
        super().setUp()
        fixture = Path(__file__).with_name('fixtures')/'tournament_runner.py'
        # Keep the portable Python fixture executable using this interpreter.
        (self.base/'fff-runner').write_text('#!'+sys.executable+'\n'+fixture.read_text().split('\n',1)[1])
        (self.base/'fff-runner').chmod(0o755)

    def start(self, **kwargs):
        self.assertIsNotNone(run, 'tournament execution is missing')
        return run(self.root, **kwargs)

    def test_completed_records_are_reused_without_checkpoint(self):
        plan=self.make(repeats=1)
        result=self.start(max_matches=1)
        self.assertEqual(result['completed'],1)
        attempt=self.root/'matches'/plan['matches'][0]['id']/'attempt-000'
        before=(attempt/'match/summary.json').stat().st_mtime_ns
        (self.root/'checkpoint.json').unlink()
        meta=json.loads((attempt/'attempt.json').read_text())
        meta['state']='running'  # Simulate crash after recorder.finish, before checkpoint.
        atomic_json(attempt/'attempt.json',meta)
        result=self.start()
        self.assertEqual(result['completed'],2)
        self.assertEqual((attempt/'match/summary.json').stat().st_mtime_ns,before)
        self.assertEqual(len(list(attempt.parent.glob('attempt-*'))),1)
        self.assertEqual(len(collect(self.root,plan)),2)

    def test_partial_attempt_is_preserved_and_retried(self):
        plan=self.make(repeats=1)
        match=plan['matches'][0]
        attempt=self.root/'matches'/match['id']/'attempt-000'
        (attempt/'match').mkdir(parents=True)
        (attempt/'match/partial').write_text('keep me')
        atomic_json(attempt/'attempt.json',{'match_id':match['id'],'state':'running'})
        self.start(max_matches=1)
        self.assertEqual((attempt/'match/partial').read_text(),'keep me')
        self.assertTrue((attempt.parent/'attempt-001/match/summary.json').is_file())
        self.assertEqual(json.loads((attempt/'attempt.json').read_text())['state'],'interrupted')

    def test_invalid_completed_record_stops_instead_of_replaying(self):
        plan=self.make(repeats=1)
        self.start(max_matches=1)
        attempt=self.root/'matches'/plan['matches'][0]['id']/'attempt-000'
        (attempt/'match/bad-verify').touch()
        with self.assertRaisesRegex(ValueError,'verif'):
            self.start()
        self.assertEqual(len(list(attempt.parent.glob('attempt-*'))),1)

    def test_changed_identity_or_seed_cannot_be_reused(self):
        plan=self.make(repeats=1)
        self.start(max_matches=1)
        path=self.root/'matches'/plan['matches'][0]['id']/'attempt-000/match/manifest.json'
        manifest=json.loads(path.read_text())
        manifest['teams'][0]['ai_seed']+=1
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'input mismatch'):
            self.start()

    def test_sigkill_cannot_leave_runner_live_with_unlocked_output(self):
        import os
        import signal
        import subprocess
        import time
        runner=self.base/'fff-runner'
        text=runner.read_text().replace('root.mkdir()', "root.mkdir()\nimport os, time\nif Path(__file__).with_name('hold').exists():\n    (root/'runner.pid').write_text(str(os.getpid()))\n    time.sleep(30)")
        runner.write_text(text)
        self.make(repeats=1)
        (self.base/'hold').touch()
        cli=Path(__file__).resolve().parents[1]/'scripts/tournament.py'
        process=subprocess.Popen([sys.executable,str(cli),'run',str(self.root),'--max-matches','1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        pid=None
        def live(child):
            path=Path(f'/proc/{child}/stat')
            try:
                return path.read_text().rsplit(')',1)[1].split()[0] not in ('Z','X')
            except FileNotFoundError:
                return False
        try:
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                files=list((self.root/'matches').glob('*/attempt-000/match/runner.pid'))
                if files:
                    pid=int(files[0].read_text())
                    break
                time.sleep(.005)
            self.assertIsNotNone(pid,'runner did not start')
            process.kill()
            process.wait()
            try:
                with locked(self.root):
                    self.assertFalse(live(pid),'orphan runner is still live while output is unlocked')
            except ValueError as error:
                self.assertIn('locked',str(error))
            deadline=time.monotonic()+3
            while live(pid) and time.monotonic()<deadline:
                time.sleep(.005)
            self.assertFalse(live(pid),'runner did not stop after tournament SIGKILL')
            (self.base/'hold').unlink()
            self.assertEqual(self.start(max_matches=1)['completed'],1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if pid is not None and live(pid):
                os.kill(pid,signal.SIGKILL)

    def test_runner_error_is_not_a_loss_or_automatic_retry(self):
        self.make(repeats=1)
        (self.base/'control').touch()
        with self.assertRaisesRegex(ValueError,'runner'):
            self.start()
        (self.base/'control').unlink()
        with self.assertRaisesRegex(ValueError,'infrastructure'):
            self.start()
        self.assertEqual(len(list((self.root/'matches').glob('*/attempt-*'))),1)


try:
    from tournament_lib.reporting import build_results, write_reports
except ImportError:
    build_results = write_reports = None


class ReportingTests(PlanFixture):
    def results(self, plan, scores):
        rows=[]
        for match, values in zip(plan['matches'], scores):
            top=max(values)
            rows.append({'match_id':match['id'],'group':match['group'],'block':match['block'],
                         'slots':match['slots'],'directory':'matches/test',
                         'summary':{'complete':True,'turns':30,'scores':values,'outcome':{'reason':'target_score','winners':[i for i,v in enumerate(values) if v==top]},
                                    'ai_failures':[0]*len(values),'illegal_actions':[0]*len(values)},
                         'call_stats':[{'calls':30,'timeouts':0,'statuses':{'ok':30},'elapsed_histogram':{'10':29,'100':1}} for _ in values],
                         'wall_seconds':1.0})
        return rows

    def build(self, plan, rows):
        self.assertIsNotNone(build_results,'tournament statistics are missing')
        return build_results(plan,rows)

    def test_partial_blocks_do_not_enter_standings(self):
        plan=self.make(repeats=1)
        result=self.build(plan,self.results(plan,[[20,0]]))
        group=result['groups'][0]
        self.assertEqual(group['complete_blocks'],0)
        self.assertEqual(group['standings'],[])
        self.assertEqual(group['verified_matches'],1)
        self.assertEqual(group['ranked_matches'],0)

    def test_tied_scores_do_not_become_losses_or_arbitrary_winner(self):
        plan=self.make(repeats=1)
        rows=self.results(plan,[[20,20],[20,20]])
        rows[0]['summary']['ai_failures'][0]=1
        rows[0]['call_stats'][0]['timeouts']=1
        rows[0]['summary']['illegal_actions'][1]=2
        standings=self.build(plan,rows)['groups'][0]['standings']
        self.assertEqual([s['id'] for s in standings],['a','b'])
        for item in standings:
            self.assertEqual((item['rank'],item['rank_score'],item['mean_rank']),(1,0.5,1.5))
            self.assertEqual((item['sole_wins'],item['joint_firsts'],item['first_credit']),(0,2,0.5))
            self.assertIsNone(item['rank_score_ci95'])
            self.assertEqual(item['elapsed_us']['p99'],100)
            self.assertEqual({s['matches'] for s in item['by_slot']},{1})
        fault_ai=rows[0]['slots'][0]
        self.assertEqual(next(s for s in standings if s['id']==fault_ai)['ai_failures'],1)
        self.assertEqual(next(s for s in standings if s['id']==fault_ai)['timeouts'],1)

    def test_multiplayer_midrank_and_pairwise_scores(self):
        cfg=copy.deepcopy(self.config)
        cfg['ais'].append({'id':'c','library':'shared.so'})
        cfg['lineups'][0].update(players=3,ais=['a','b','c'])
        plan=self.make(cfg,repeats=1,mode='quick')
        rows=self.results(plan,[[20 if a in ('a','b') else 5 for a in m['slots']] for m in plan['matches']])
        group=self.build(plan,rows)['groups'][0]
        a,b,c=group['standings']
        self.assertEqual([x['id'] for x in (a,b,c)],['a','b','c'])
        self.assertEqual((a['rank_score'],a['mean_rank'],a['first_credit']),(0.75,1.5,0.5))
        self.assertEqual((b['rank'],c['rank'],c['rank_score'],c['mean_score_difference']),(1,3,0,-15))
        self.assertEqual(group['pairwise']['a']['b'],{'wins':0,'ties':3,'losses':0})
        self.assertEqual(group['pairwise']['a']['c'],{'wins':3,'ties':0,'losses':0})

    def test_confidence_interval_preserves_correlated_rotation_blocks(self):
        plan=self.make(repeats=5)
        # Three whole blocks won by a, two whole blocks lost. Per-game
        # resampling would incorrectly narrow this interval to about .3..9.
        block_ids=[b['id'] for b in plan['blocks']]
        scores=[]
        for match in plan['matches']:
            winner='a' if block_ids.index(match['block']) < 3 else 'b'
            scores.append([20 if aid==winner else 0 for aid in match['slots']])
        result=self.build(plan,self.results(plan,scores))
        a=next(x for x in result['groups'][0]['standings'] if x['id']=='a')
        self.assertEqual(a['rank_score'],0.6)
        self.assertEqual(a['rank_score_ci95'],[0.2,1.0])

    def test_display_names_remain_plain_text_in_markdown(self):
        cfg=copy.deepcopy(self.config)
        cfg['ais'][0]['name']='![AI](https://example.org/pixel) **bold** `code` &lt;'
        plan=self.make(cfg,repeats=1)
        self.assertIsNotNone(write_reports)
        write_reports(self.root,plan,self.results(plan,[[20,20]]*2))
        text=(self.root/'report.md').read_text()
        self.assertNotIn('![AI](',text)
        self.assertNotIn('**bold**',text)
        self.assertNotIn('`code`',text)
        self.assertIn('&amp;lt;',text)
        self.assertIn('\\!\\[AI\\]\\(https://example\\.org/pixel\\)',text)

    def test_intervals_resample_blocks_and_exports_escape_names(self):
        plan=self.make(repeats=5)
        rows=self.results(plan,[[20,20]]*10)
        result=self.build(plan,rows)
        self.assertEqual(result['groups'][0]['standings'][0]['rank_score_ci95'],[0.5,0.5])
        self.assertIsNotNone(write_reports)
        write_reports(self.root,plan,rows)
        import csv
        with (self.root/'standings.csv').open(newline='') as stream:
            csv_rows=list(csv.DictReader(stream))
        self.assertEqual(csv_rows[0]['name'],'甲|AI')
        self.assertIn('甲\\|AI',(self.root/'report.md').read_text())
        self.assertEqual(json.loads((self.root/'results.json').read_text())['completed_matches'],10)


if __name__ == '__main__':
    unittest.main()
