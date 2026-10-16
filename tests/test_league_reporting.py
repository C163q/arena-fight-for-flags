"""Hand-computed league ranking and incomplete-map regression cases."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tournament_lib.league_reporting import build_results
from tournament_lib.league_schedule import schedule


def fixture(repeats=1):
    ids = ['a','b','c']
    plan = {'version':2,'kind':'league','participants':ids,'ais':[{'id':a,'name':a} for a in ids+['fill']],
            'groups':[{'id':'duel','players':2,'ais':ids,'sha256':'map1'},
                      {'id':'melee','players':4,'ais':ids+['fill'],'sha256':'map2'}],
            'blocks':[],'matches':[],'repeats':repeats,'environment':{}}
    rows = []
    for r in range(repeats):
        for group in plan['groups']:
            bid = f"{group['id']}-{r}"
            plan['blocks'].append({'id':bid,'group':group['id'],'repeat':r,'coverage':{}})
            design,_ = schedule(3,group['players'])
            for i,seats in enumerate(design):
                slots = [group['ais'][a] for a in seats]
                match = {'id':f'{bid}-{i}','group':group['id'],'block':bid,'slots':slots}
                plan['matches'].append(match)
                # a wins duel; b wins melee. All individual score comparisons clear.
                values = {'a':3,'b':2,'c':1} if group['id']=='duel' else {'a':1,'b':3,'c':2,'fill':0}
                scores = [values[a] for a in slots]
                winners = [scores.index(max(scores))]
                rows.append({'match_id':match['id'],'group':group['id'],'block':bid,'slots':slots,
                    'execution_jobs':1,'directory':f'matches/{match["id"]}',
                    'summary':{'scores':scores,'turns':1,'ai_failures':[0]*len(slots),'illegal_actions':[0]*len(slots),
                               'outcome':{'reason':'turn_limit','winners':winners}},
                    'call_stats':[{'calls':1,'timeouts':0,'statuses':{'ok':1},'elapsed_histogram':{'100':1}} for _ in slots]})
    return plan,rows


class LeagueReportTests(unittest.TestCase):
    def test_missing_candidates_and_fillers_have_correct_denominators(self):
        plan,rows = fixture()
        result = build_results(plan,rows)
        duel,melee = result['groups']
        a = next(x for x in duel['standings'] if x['id']=='a')
        self.assertEqual(a['matches'],4)
        self.assertEqual(a['rank_score'],1)
        self.assertEqual(duel['pairwise']['a']['b'],{'wins':2,'ties':0,'losses':0,'matches':2})
        self.assertEqual({x['id'] for x in melee['standings']},{'a','b','c'})
        self.assertAlmostEqual(next(x for x in melee['standings'] if x['id']=='a')['rank_score'],1/3)

    def test_total_is_equal_map_weight_not_game_weight(self):
        plan,rows = fixture()
        result = build_results(plan,rows)
        overall = {x['id']:x for x in result['overall']['standings']}
        self.assertAlmostEqual(overall['a']['rank_score'],2/3)
        self.assertAlmostEqual(overall['b']['rank_score'],.75)
        self.assertEqual(overall['b']['rank'],1)

    def test_incomplete_map_excludes_whole_global_repeat(self):
        plan,rows = fixture(2)
        result = build_results(plan,rows[:-1])
        self.assertEqual(result['overall']['complete_repeats'],[0])
        self.assertEqual(result['groups'][0]['complete_blocks'],2)
        self.assertEqual(result['groups'][1]['complete_blocks'],1)
        self.assertEqual(next(x for x in result['overall']['standings'] if x['id']=='a')['matches'],16)
        result = build_results(plan,[r for r in rows if r['group']=='duel'])
        self.assertEqual(result['overall']['standings'],[])
        self.assertEqual(result['groups'][1]['standings'],[])

    def test_partial_parallel_rows_still_mark_total_self_test(self):
        plan,rows = fixture()
        rows[-1]['execution_jobs']=4
        result = build_results(plan,rows[-1:])
        self.assertEqual(result['execution']['classification'],'parallel_self_test')
        self.assertEqual(result['overall']['standings'],[])

    def test_bootstrap_and_ties(self):
        plan,rows = fixture(5)
        for row in rows:
            row['summary']['scores']=[0]*len(row['slots'])
            row['summary']['outcome']['winners']=list(range(len(row['slots'])))
        result = build_results(plan,rows)
        for item in result['overall']['standings']:
            self.assertEqual(item['rank'],1)
            self.assertEqual(item['rank_score_ci95'],[.5,.5])
        for group in result['groups']:
            self.assertEqual({x['rank'] for x in group['standings']},{1})

    def test_duplicate_or_wrong_results_rejected(self):
        plan,rows = fixture()
        for bad in [rows+[rows[0]], [{**rows[0],'slots':['c','b']}], [{**rows[0],'execution_jobs':True}]]:
            with self.assertRaises(ValueError):
                build_results(plan,bad)
