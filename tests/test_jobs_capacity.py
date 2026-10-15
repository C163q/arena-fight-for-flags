"""Capacity decisions must retain both repeats and stop at first failing level."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
try:
    from benchmark_jobs import assess_capacity
except ImportError:
    assess_capacity=None

class CapacityTests(unittest.TestCase):
    def rows(self):
        return [{'profile':profile,'pass':p,'jobs':j,'faults':0,'illegal_actions':0,
                 'regular_us':{'p95':36000 if profile=='cpu35' else 1000,'p99':38000 if profile=='cpu35' else 2000}}
                for profile in ('baseline','cpu35') for p in (0,1) for j in (1,2,4,8)]

    def test_no_skipping_a_failed_level_or_dropping_a_repeat(self):
        self.assertIsNotNone(assess_capacity,'capacity assessment missing')
        rows=self.rows()
        next(r for r in rows if r['profile']=='cpu35' and r['pass']==1 and r['jobs']==4)['regular_us']['p99']=46000
        result=assess_capacity(rows,[1,2,4,8],2)
        self.assertEqual(result['measured_max_jobs'],2)
        self.assertTrue(result['levels'][-1]['passed'])
        rows.pop()
        with self.assertRaisesRegex(ValueError,'missing|duplicate'):
            assess_capacity(rows,[1,2,4,8],2)

    def test_faults_and_unstable_serial_prevent_a_capacity_claim(self):
        self.assertIsNotNone(assess_capacity,'capacity assessment missing')
        rows=self.rows()
        next(r for r in rows if r['profile']=='baseline' and r['pass']==0 and r['jobs']==2)['faults']=1
        self.assertEqual(assess_capacity(rows,[1,2,4,8],2)['measured_max_jobs'],1)
        rows=self.rows()
        next(r for r in rows if r['profile']=='cpu35' and r['pass']==1 and r['jobs']==1)['faults']=1
        self.assertIsNone(assess_capacity(rows,[1,2,4,8],2)['measured_max_jobs'])
