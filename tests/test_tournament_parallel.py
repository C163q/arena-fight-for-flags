"""Concurrency contracts at the real subprocess and saved-result boundaries."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
import test_tournament as fixtures
from tournament_lib.execution import run, collect
from tournament_lib.reporting import write_reports


class ParallelTests(fixtures.PlanFixture):
    def setUp(self):
        super().setUp()
        fixture = Path(__file__).with_name('fixtures')/'tournament_runner.py'
        # Real subprocesses publish intervals/PIDs; the orchestration is not mocked.
        source = fixture.read_text().split('\n',1)[1]
        source = source.replace('root.mkdir()', '''root.mkdir()
import os, time
stamp = root/'timing.json'
start = time.monotonic()
stamp.write_text(json.dumps({'start':start,'pid':os.getpid()}))
if Path(__file__).with_name('hold').exists():
    time.sleep(30)
if Path(__file__).with_name('fail-pair').exists():
    peers = root.parents[3]
    while len(list(peers.glob('matches/*/attempt-*/match/timing.json'))) < 2:
        time.sleep(.01)
    if root.parent.parent.name.endswith('m000'):
        sys.exit('injected pair failure')
    time.sleep(30)
time.sleep(.15)
stamp.write_text(json.dumps({'start':start,'end':time.monotonic(),'pid':os.getpid()}))''')
        runner=self.base/'fff-runner'
        runner.write_text('#!'+sys.executable+'\n'+source)
        runner.chmod(0o755)

    def test_parallel_overlap_bound_segment_and_serial_resume(self):
        plan=self.make()
        result=run(self.root,max_matches=3,jobs=2)
        self.assertEqual(result['new_matches'],3)
        intervals=[json.loads(p.read_text()) for p in self.root.glob('matches/*/attempt-*/match/timing.json')]
        events=sorted([(x['start'],1) for x in intervals]+[(x['end'],-1) for x in intervals])
        active=peak=0
        for _,change in events:
            active+=change
            peak=max(peak,active)
        self.assertEqual(peak,2,'matches must actually overlap, and never exceed jobs')
        saved={p:p.stat().st_mtime_ns for p in self.root.glob('matches/*/attempt-*/match/summary.json')}
        self.assertEqual(run(self.root)['completed'],4)
        self.assertTrue(all(p.stat().st_mtime_ns==mtime for p,mtime in saved.items()))
        rows=collect(self.root,plan)
        self.assertEqual(sorted(r['execution_jobs'] for r in rows),[1,2,2,2])
        result=write_reports(self.root,plan,rows)
        self.assertEqual(result['execution']['jobs_used'],[1,2])
        self.assertEqual(result['execution']['classification'],'parallel_self_test')
        self.assertIn('并行自测',(self.root/'report.md').read_text())
        self.assertIn('execution_classification',(self.root/'standings.csv').read_text())

    def test_default_one_and_legacy_attempt_are_serial(self):
        plan=self.make(repeats=1)
        run(self.root)
        intervals=[json.loads(p.read_text()) for p in self.root.glob('matches/*/attempt-*/match/timing.json')]
        intervals.sort(key=lambda x:x['start'])
        self.assertLessEqual(intervals[0]['end'],intervals[1]['start'])
        for path in self.root.glob('matches/*/attempt-*/attempt.json'):
            meta=json.loads(path.read_text())
            self.assertEqual(meta.pop('jobs'),1)
            path.write_text(json.dumps(meta))
        rows=collect(self.root,plan)
        self.assertEqual([r['execution_jobs'] for r in rows],[1,1])
        self.assertEqual(write_reports(self.root,plan,rows)['execution']['classification'],'serial')

    def test_invalid_jobs_rejected_without_attempts(self):
        self.make()
        for jobs in (0,-1,True,1.5,'2'):
            with self.subTest(jobs=jobs), self.assertRaisesRegex(ValueError,'jobs'):
                run(self.root,jobs=jobs)
        self.assertFalse((self.root/'matches').exists())

    def test_invalid_saved_concurrency_cannot_be_reported_as_serial(self):
        plan=self.make(repeats=1)
        run(self.root,max_matches=1)
        path=next(self.root.glob('matches/*/attempt-*/attempt.json'))
        meta=json.loads(path.read_text())
        meta['jobs']=0
        path.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError,'jobs'):
            collect(self.root,plan)

    @staticmethod
    def live(pid):
        try:
            return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0] not in ('Z','X')
        except (FileNotFoundError,ProcessLookupError):
            return False

    def test_failure_stops_other_matches_and_does_not_refill(self):
        self.make()
        (self.base/'fail-pair').touch()
        cli=Path(__file__).resolve().parents[1]/'scripts/tournament.py'
        process=subprocess.Popen([sys.executable,str(cli),'run',str(self.root),'--jobs','2'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            self.assertEqual(process.wait(timeout=10),1)
            attempts=list(self.root.glob('matches/*/attempt-*'))
            self.assertEqual(len(attempts),2)
            states=sorted(json.loads((p/'attempt.json').read_text())['state'] for p in attempts)
            self.assertEqual(states,['infra_error','interrupted'])
            pids=[json.loads(p.read_text())['pid'] for p in self.root.glob('matches/*/attempt-*/match/timing.json')]
            self.assertEqual(len(pids),2)
            self.assertTrue(all(not self.live(pid) for pid in pids))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            for path in self.root.glob('matches/*/attempt-*/match/timing.json'):
                pid=json.loads(path.read_text())['pid']
                if self.live(pid):
                    os.kill(pid,signal.SIGKILL)


class ParallelReportTests(fixtures.PlanFixture):
    results = fixtures.ReportingTests.results
    build = fixtures.ReportingTests.build
    # Only own test is loaded; the existing reporting cases remain in their module.
    def test_parallel_metadata_survives_complete_block_ranking(self):
        plan=self.make(repeats=1)
        rows=self.results(plan,[[20,0],[0,20]])
        rows[0]['execution_jobs']=4
        rows[1]['execution_jobs']=1
        result=self.build(plan,rows)
        self.assertEqual(result['execution']['classification'],'parallel_self_test')
        self.assertEqual(result['execution']['jobs_used'],[1,4])
        self.assertEqual(result['groups'][0]['ranked_matches'],2)
