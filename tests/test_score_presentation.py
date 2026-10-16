"""Display scale must not change ranking, precision or existing data contracts."""
import csv
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tournament_lib import reporting, league_reporting
from test_league_reporting import fixture


class ScorePresentationTests(unittest.TestCase):
    def test_half_up_boundaries_and_exact_fractions(self):
        convert = getattr(reporting,'display_score',None)
        self.assertTrue(callable(convert),'missing per-mille score conversion')
        for value,want in [(0,0),(1,1000),(Fraction(1,2),500),
                           (Fraction(1,2000),1),(Fraction(1001,2000),501),
                           (.5005,501),(Fraction(1,3),333)]:
            with self.subTest(value=value):
                self.assertEqual(convert(value),want)

    def test_league_exports_scaled_scores_and_keeps_normalized_data(self):
        plan,rows = fixture(5)
        for block in plan['blocks']:
            duel=block['group']=='duel'
            block['coverage']={'matches':6 if duel else 12,'appearances_min':4 if duel else 12,
                               'seat_min':2 if duel else 3,'pair_min':2 if duel else 12,'pair_seat_min':1}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'plan.json').write_text(json.dumps(plan))
            result=league_reporting.write_reports(root,plan,rows)
            self.assertEqual(result.get('score_scale'),1000)
            overall={x['id']:x for x in result['overall']['standings']}
            self.assertEqual(overall['a']['score'],667)
            self.assertAlmostEqual(overall['a']['rank_score'],2/3)
            self.assertEqual(overall['a']['score_ci95'],[667,667])
            self.assertEqual(overall['a']['by_map_score'],{'duel':1000,'melee':333})
            self.assertEqual(overall['b']['score'],750)
            self.assertEqual(overall['b']['rank'],1)
            a=next(x for x in result['groups'][1]['standings'] if x['id']=='a')
            self.assertTrue(all(x['score']==333 for x in a['by_slot']))
            text=(root/'report.md').read_text()
            self.assertIn('| 667 | 667–667 |',text)
            with (root/'standings.csv').open(newline='') as stream:
                exported=list(csv.DictReader(stream))
            a=next(x for x in exported if x['scope']=='overall' and x['id']=='a')
            self.assertEqual(a['score'],'667')
            self.assertAlmostEqual(float(a['rank_score']),2/3)
            disk=json.loads((root/'results.json').read_text())
            self.assertEqual(disk['overall']['standings'][0]['score'],750)

    def test_fixed_roster_exports_and_missing_interval(self):
        plan,rows=fixture()
        plan.update(version=1,mode='balanced')
        plan['groups']=[plan['groups'][1]]
        plan['blocks']=[b for b in plan['blocks'] if b['group']=='melee']
        plan['matches']=[m for m in plan['matches'] if m['group']=='melee']
        rows=[r for r in rows if r['group']=='melee']
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'plan.json').write_text(json.dumps(plan))
            result=reporting.write_reports(root,plan,rows)
            self.assertEqual(result.get('score_scale'),1000)
            a=next(x for x in result['groups'][0]['standings'] if x['id']=='a')
            self.assertEqual(a['score'],333)
            self.assertAlmostEqual(a['rank_score'],1/3)
            self.assertIsNone(a['score_ci95'])
            self.assertIn('| 333 / 完整块不足 5 |',(root/'report.md').read_text())
            with (root/'standings.csv').open(newline='') as stream:
                a=next(x for x in csv.DictReader(stream) if x['id']=='a')
            self.assertEqual(a['score'],'333')

    def test_same_display_score_does_not_create_a_tie(self):
        plan,rows=fixture(100)
        plan['groups']=[plan['groups'][1]]
        plan['blocks']=[b for b in plan['blocks'] if b['group']=='melee']
        plan['matches']=[m for m in plan['matches'] if m['group']=='melee']
        rows=[r for r in rows if r['group']=='melee']
        for row in rows:
            row['summary']['scores']=[20 if ai in ('a','b') else 0 for ai in row['slots']]
            row['summary']['outcome']['winners']=[i for i,ai in enumerate(row['slots']) if ai in ('a','b')]
        i=rows[-1]['slots'].index('a')
        rows[-1]['summary']['scores'][i]=21
        rows[-1]['summary']['outcome']['winners']=[i]
        result=league_reporting.build_results(plan,rows)
        a,b=result['overall']['standings'][:2]
        self.assertIn('score',a)
        self.assertEqual((a['id'],b['id']),("a","b"))
        self.assertEqual((a['score'],b['score']),(833,833))
        self.assertEqual((a['rank'],b['rank']),(1,2))
        self.assertGreater(a['rank_score'],b['rank_score'])


if __name__=='__main__':unittest.main()
